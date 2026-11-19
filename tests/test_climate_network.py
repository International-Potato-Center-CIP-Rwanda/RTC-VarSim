"""Transport-level regression checks against a local HTTP range server.

These verify byte-for-byte equivalence, request counts and failure behaviour.
They are software checks only; they say nothing about agronomic validity.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window
import climate_access
from climate_access import RangeReader
from climate_block_cache import BlockCache
from range_server import serve, loopback_available

# Short client timeouts and few retries so an environment that blocks loopback HTTP
# fails fast (or is skipped with a clear reason) instead of appearing to hang.
climate_access.HTTP_TIMEOUT = 5
LOOPBACK_SKIP = 'loopback HTTP (127.0.0.1) is blocked in this environment; HTTP tests skipped'


def write_raster(path, *, tiled, size=1024, seed=0, year=1991, month=1, nodata_rows=40):
    """Write a deterministic synthetic GeoTIFF with the requested layout, identity and nodata rows."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size]
    data = (2900 + 60*np.sin(x/90) + 40*np.cos(y/70) + rng.normal(0, 3, (size, size))).astype('uint16')
    data[:nodata_rows, :] = 65535
    layout = dict(tiled=True, blockxsize=256, blockysize=256) if tiled else dict(tiled=False, blockysize=1)
    with rasterio.open(path, 'w', driver='GTiff', height=size, width=size, count=1, dtype='uint16', nodata=65535,
                       crs='EPSG:4326', transform=from_origin(-20, 40, 1/120, 1/120), compress='deflate', **layout) as dest:
        dest.write(data, 1)
        dest.scales = (0.1,)
        dest.offsets = (0.0,)
        dest.update_tags(variable='tas', variable_unit='K', datetime=f'{year}-{month:02d}-15')
    return data


def remote_read(url, size, window, disk_cache=None):
    """Read a synthetic remote raster window through the range reader under test."""
    readers = []

    def opener(path, mode='rb'):
        """Adapt the range reader to Rasterio file access; accept the expected virtual raster path and preserve source identity checks."""
        if str(path) != 'remote.tif':
            raise FileNotFoundError(path)
        reader = RangeReader(url, size, '"v1"', disk_cache=disk_cache).prime()
        readers.append(reader)
        return reader
    with rasterio.open('remote.tif', opener=opener) as src:
        return src.read(1, window=window, masked=True), readers


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Create shared synthetic test resources and check local transport availability."""
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        write_raster(root/'tiled.tif', tiled=True)
        write_raster(root/'strips.tif', tiled=False)
        cls.server, cls.base, cls.stats = serve(cls.directory.name)
        cls.root = root
        if not loopback_available(cls.server):
            cls.server.shutdown(); cls.directory.cleanup()
            raise unittest.SkipTest(LOOPBACK_SKIP)
        cls.direct = patch('climate_access._proxied', return_value=False)
        cls.direct.start()

    @classmethod
    def tearDownClass(cls):
        """Stop shared test services and clean up their temporary inputs."""
        cls.direct.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.directory.cleanup()

    def setUp(self):
        """Create isolated synthetic inputs for this test; do not use or modify private research data."""
        climate_access._local.__dict__.clear()   # fresh connections per test
        self.stats.connections = self.stats.requests = self.stats.bytes = self.stats.fail_next = 0

    def check_equal(self, name, window):
        """Compare a remote masked raster window with the independently read local fixture."""
        path = self.root/name
        with rasterio.open(path) as src:
            truth = src.read(1, window=window, masked=True)
        values, readers = remote_read(self.base + name, path.stat().st_size, window)
        np.testing.assert_array_equal(values.data, truth.data)
        np.testing.assert_array_equal(np.ma.getmaskarray(values), np.ma.getmaskarray(truth))
        return readers

    def test_identical_values_and_mask_tiled_and_strips(self):
        """Verify that identical values and mask tiled and strips."""
        for name in ('tiled.tif', 'strips.tif'):
            for window in (Window(0, 0, 512, 512), Window(512, 256, 512, 512), Window(700, 900, 324, 124)):
                with self.subTest(name=name, window=window):
                    self.check_equal(name, window)

    def test_keep_alive_reuses_connections(self):
        """Verify that keep alive reuses connections."""
        self.check_equal('strips.tif', Window(0, 0, 512, 512))
        self.assertGreater(self.stats.requests, 1)
        self.assertEqual(self.stats.connections, 1)

    def test_sequential_reads_are_coalesced(self):
        """Verify that sequential reads are coalesced."""
        name = 'strips.tif'
        size = (self.root/name).stat().st_size
        with patch.object(RangeReader, 'max_coalesce_blocks', 1):
            remote_read(self.base + name, size, Window(0, 0, 512, 1024))
        single_block_requests = self.stats.requests
        self.stats.requests = 0
        climate_access._local.__dict__.clear()
        remote_read(self.base + name, size, Window(0, 0, 512, 1024))
        self.assertLess(self.stats.requests, single_block_requests / 2)

    def test_dropped_connections_recover_with_identical_values(self):
        """Verify that dropped connections recover with identical values."""
        with patch('climate_access.time.sleep'):
            self.stats.fail_next = 3
            self.check_equal('tiled.tif', Window(256, 256, 512, 512))
        self.assertEqual(self.stats.fail_next, 0)

    def test_exhausted_network_retries_raise_and_are_counted(self):
        """A network outage must surface as an exception, never as fill values."""
        name = 'tiled.tif'
        size = (self.root/name).stat().st_size
        before = climate_access.STATS.network_giveups
        with patch('climate_access.time.sleep'), patch.object(RangeReader, 'max_attempts', 2):
            self.stats.fail_next = 10**6
            with self.assertRaises(Exception):
                remote_read(self.base + name, size, Window(0, 0, 512, 512))
        self.assertGreater(climate_access.STATS.network_giveups, before)

    def test_outage_during_pixel_reads_raises(self):
        """Verify that outage during pixel reads raises."""
        name = 'tiled.tif'
        size = (self.root/name).stat().st_size
        original = climate_access._get_range
        calls = []

        def flaky(url, start, stop):
            """Inject the network failure required by this test scenario."""
            calls.append(start)
            if len(calls) > 2:      # header already read; fail on pixel blocks
                raise OSError('getaddrinfo failed')
            return original(url, start, stop)
        with patch('climate_access._get_range', flaky), patch('climate_access.time.sleep'), \
                patch.object(RangeReader, 'max_attempts', 2):
            with self.assertRaises(Exception):
                remote_read(self.base + name, size, Window(0, 512, 512, 512))

    def test_disk_cache_round_trip_is_identical(self):
        """Verify that disk cache round trip is identical."""
        name = 'strips.tif'
        size = (self.root/name).stat().st_size
        window = Window(100, 100, 400, 400)
        with tempfile.TemporaryDirectory() as directory:
            cache = BlockCache(Path(directory)/'blocks.sqlite')
            try:
                first, _ = remote_read(self.base + name, size, window, cache)
                requests = self.stats.requests
                second, readers = remote_read(self.base + name, size, window, cache)
                self.assertEqual(self.stats.requests, requests)
                self.assertEqual(readers[0].transferred, 0)
                np.testing.assert_array_equal(first.filled(0), second.filled(0))
            finally:
                cache.close()


CHILD = r"""
import sys, rasterio
from unittest.mock import patch
import climate_access
from climate_access import RangeReader
def fail(*args): raise OSError('getaddrinfo failed')
with patch('climate_access._get_range', fail), patch('climate_access.time.sleep'):
    def opener(path, mode='rb'):
        if str(path) != 'remote.tif': raise FileNotFoundError(path)
        return RangeReader('https://example.test/a', 10**6, 'v1').prime()
    try:
        with rasterio.open('remote.tif', opener=opener) as src: pass
    except Exception as error:
        print('raised', type(error).__name__)
"""


class FirstReadFailureTests(unittest.TestCase):
    def test_network_failure_before_open_raises_instead_of_aborting(self):
        """Runs in a child process: without prime(), this scenario aborts Python."""
        import subprocess, sys
        root = Path(__file__).resolve().parent.parent
        child = subprocess.run([sys.executable, '-c', CHILD], cwd=root, capture_output=True, text=True, timeout=120)
        self.assertEqual(child.returncode, 0, child.stderr[-500:])
        self.assertIn('raised', child.stdout)


class TileRunEquivalence(unittest.TestCase):
    """run() over 30 synthetic years equals an independent strict mean."""

    def test_run_matches_independent_mean(self):
        """Verify that run matches independent mean."""
        import extract_climate_tile
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base/'data/sources').mkdir(parents=True)
            stack, files = [], []
            for year in range(1991, 2021):
                name = f'tas_{year}.tif'
                data = write_raster(base/'data/sources'/name, tiled=year % 2 == 0, size=600, seed=year, year=year)
                if year == 2005:     # one source year missing at some pixels
                    with rasterio.open(base/'data/sources'/name, 'r+') as dest:
                        data[100:110, 200:260] = 65535
                        dest.write(data, 1)
                stack.append(data)
                files.append(dict(variable='tas', year=year, month=1, url=None, bytes=(base/'data/sources'/name).stat().st_size,
                                  etag='"v1"', name=name))
            server, url, _ = serve(str(base/'data/sources'))
            if not loopback_available(server):
                server.shutdown()
                self.skipTest(LOOPBACK_SKIP)
            try:
                for item in files:
                    item['url'] = url + item.pop('name')
                (base/'data/africa-1991-2020-inventory.json').write_text(json.dumps(dict(files=files)))
                with rasterio.open(base/'data/sources/tas_1991.tif') as src:
                    grid = dict(transform=list(src.transform), shape=list(src.shape))
                (base/'data/probe-tas-1991-01.json').write_text(json.dumps(grid))
                window = dict(row=64, col=128, height=300, width=400)
                with patch.object(extract_climate_tile, 'BASE', base), patch('climate_access._proxied', return_value=False):
                    folder = extract_climate_tile.run('tas', 1, None, None, grid_window=window)
            finally:
                server.shutdown()
                server.server_close()
            raw = np.stack(stack)[:, 64:364, 128:528].astype('float64')
            valid = raw != 65535
            celsius = raw*0.1 - 273.15
            expected = np.where(valid.all(axis=0), np.where(valid, celsius, 0).sum(axis=0)/30, np.nan)
            with rasterio.open(folder/'mean.tif') as out, rasterio.open(folder/'valid-years.tif') as counts:
                mean = out.read(1, masked=True)
                np.testing.assert_array_equal(counts.read(1), valid.sum(axis=0))
            np.testing.assert_array_equal(np.ma.getmaskarray(mean), ~valid.all(axis=0))
            np.testing.assert_allclose(mean.compressed(), expected[valid.all(axis=0)].astype('float32'), rtol=0, atol=1e-4)


class JobRetryTests(unittest.TestCase):
    def setUp(self):
        """Create isolated synthetic inputs for this test; do not use or modify private research data."""
        import africa_climate_jobs
        self.jobs = africa_climate_jobs
        self.job = dict(id='r0-c0-tas-01', variable='tas', month=1, tile=dict(row=0, col=0, height=1, width=1))

    def test_network_failure_is_retried_after_source_returns(self):
        """Verify that network failure is retried after source returns."""
        calls = []

        def runner(*args, **kwargs):
            """Provide the controlled job outcome required by this retry test."""
            calls.append(1)
            if len(calls) == 1:
                climate_access.STATS.add(network_giveups=1)
                raise rasterio.errors.RasterioIOError('Read failed')
            return 'folder'
        waits = []
        folder, result = self.jobs.execute_job(self.job, None, {}, attempts=3, runner=runner,
                                               masker=lambda folder, mask: {'ok': True},
                                               waiter=lambda item, deadline: waits.append(item) or True)
        self.assertEqual((folder, result, len(calls), len(waits)), ('folder', {'ok': True}, 2, 1))

    def test_data_error_is_not_retried(self):
        """Verify that data error is not retried."""
        calls = []

        def runner(*args, **kwargs):
            """Provide the controlled job outcome required by this retry test."""
            calls.append(1)
            raise ValueError('Grid mismatch')
        with self.assertRaises(ValueError):
            self.jobs.execute_job(self.job, None, {}, attempts=5, runner=runner, waiter=lambda item, deadline: True)
        self.assertEqual(len(calls), 1)

    def test_retries_are_bounded_and_stop_when_network_never_returns(self):
        """Verify that retries are bounded and stop when network never returns."""
        def runner(*args, **kwargs):
            """Provide the controlled job outcome required by this retry test."""
            climate_access.STATS.add(network_giveups=1)
            raise OSError('getaddrinfo failed')
        with self.assertRaises(OSError):
            self.jobs.execute_job(self.job, None, {}, attempts=5, runner=runner, waiter=lambda item, deadline: False)

    def test_wait_for_source_polls_until_reachable(self):
        """Verify that wait for source polls until reachable."""
        answers = iter(['unreachable', 'unreachable', 'reachable'])
        sleeps = []
        with patch('climate_access.source_state', lambda *a: next(answers)), \
                patch.object(self.jobs, 'stop_requested', return_value=False):
            self.assertTrue(self.jobs.wait_for_source(dict(url='u', bytes=1, etag=None), deadline=600, poll=60,
                                                      sleep=sleeps.append, clock=lambda: 0))
        self.assertEqual(sleeps, [60, 60])

    def test_stop_after_successful_probe_is_a_clean_stop(self):
        """Verify that stop after successful probe is a clean stop."""
        stops = iter([False, True])          # STOP appears while the probe is in flight
        with patch('climate_access.source_state', return_value='reachable'), \
                patch.object(self.jobs, 'stop_requested', lambda: next(stops)):
            with self.assertRaises(self.jobs.StopRequested):
                self.jobs.wait_for_source(dict(url='u', bytes=1), deadline=600, sleep=lambda s: None, clock=lambda: 0)

    def test_stop_during_outage_is_a_clean_stop(self):
        """Verify that stop during outage is a clean stop."""
        stops = iter([False, False, True])
        with patch('climate_access.source_state', return_value='unreachable'), \
                patch.object(self.jobs, 'stop_requested', lambda: next(stops)):
            with self.assertRaises(self.jobs.StopRequested):
                self.jobs.wait_for_source(dict(url='u', bytes=1), deadline=600, poll=60, sleep=lambda s: None, clock=lambda: 0)

    def test_deadline_counts_probe_time(self):
        """Fake clock: each probe takes 50 s, each sleep advances the clock by its length."""
        now = [0.0]
        def slow_probe(*args):
            """Simulate a source probe that requests a stop during the network wait."""
            now[0] += 50
            return 'unreachable'
        def sleep(seconds):
            """Advance the simulated test clock instead of waiting in real time."""
            now[0] += seconds
        with patch('climate_access.source_state', slow_probe), patch.object(self.jobs, 'stop_requested', return_value=False):
            self.assertFalse(self.jobs.wait_for_source(dict(url='u', bytes=1), deadline=300, poll=60,
                                                       sleep=sleep, clock=lambda: now[0]))
        self.assertLessEqual(now[0], 300 + 50)   # may overrun by at most one probe

    def test_integrity_answer_stops_waiting(self):
        """Verify that integrity answer stops waiting."""
        sleeps = []
        with patch('climate_access.source_state', return_value='integrity'), patch.object(self.jobs, 'stop_requested', return_value=False):
            self.assertFalse(self.jobs.wait_for_source(dict(url='u', bytes=1), deadline=600, sleep=sleeps.append, clock=lambda: 0))
        self.assertEqual(sleeps, [])

    def test_one_wait_budget_per_job_across_outages(self):
        """Verify that one wait budget per job across outages."""
        deadlines = []
        def runner(*args, **kwargs):
            """Provide the controlled job outcome required by this retry test."""
            climate_access.STATS.record_giveup('u', 1, None)
            raise OSError('getaddrinfo failed')
        with self.assertRaises(OSError):
            self.jobs.execute_job(self.job, None, {}, attempts=4, runner=runner, clock=lambda: 1000.0, wait_budget=7200,
                                  waiter=lambda item, deadline: deadlines.append(deadline) or True)
        self.assertEqual(deadlines, [8200.0] * 3)

    def test_integrity_error_in_same_attempt_is_not_retried(self):
        """Verify that integrity error in same attempt is not retried."""
        calls = []
        def runner(*args, **kwargs):
            """Provide the controlled job outcome required by this retry test."""
            calls.append(1)
            climate_access.STATS.record_giveup('u', 1, None)        # year A: network gave up
            climate_access.STATS.add(integrity_errors=1)              # year B: identity mismatch
            raise rasterio.errors.RasterioIOError('Read failed')
        with self.assertRaises(rasterio.errors.RasterioIOError):
            self.jobs.execute_job(self.job, None, {}, attempts=5, runner=runner, waiter=lambda item, deadline: True)
        self.assertEqual(len(calls), 1)

    def test_retry_probes_the_source_that_failed(self):
        """Verify that retry probes the source that failed."""
        probed = []
        calls = []
        def runner(*args, **kwargs):
            """Provide the controlled job outcome required by this retry test."""
            calls.append(1)
            if len(calls) == 1:
                climate_access.STATS.record_giveup('https://x/failing.tif', 7, '"e"')
                raise OSError('reset')
            return 'folder'
        self.jobs.execute_job(self.job, None, dict(url='https://x/first.tif'), attempts=3, runner=runner,
                              masker=lambda f, m: {}, waiter=lambda item, deadline: probed.append(item['url']) or True)
        self.assertEqual(probed, ['https://x/failing.tif'])

    def test_stop_between_attempts_is_clean(self):
        """Verify that stop between attempts is clean."""
        def runner(*args, **kwargs):
            """Provide the controlled job outcome required by this retry test."""
            climate_access.STATS.record_giveup('u', 1, None)
            raise OSError('reset')
        with patch.object(self.jobs, 'stop_requested', return_value=True):
            with self.assertRaises(self.jobs.StopRequested):
                self.jobs.execute_job(self.job, None, {}, attempts=3, runner=runner, waiter=lambda item, deadline: True)


class DeadlineTests(unittest.TestCase):
    """Cumulative network-wait budget semantics (Codex v2 review)."""

    def setUp(self):
        """Create isolated synthetic inputs for this test; do not use or modify private research data."""
        import africa_climate_jobs
        self.jobs = africa_climate_jobs
        self.job = dict(id='r0-c0-tas-01', variable='tas', month=1, tile=dict(row=0, col=0, height=1, width=1))
        self.no_stop = patch.object(self.jobs, 'stop_requested', return_value=False)
        self.no_stop.start()

    def tearDown(self):
        """Release the temporary resources created by this test."""
        self.no_stop.stop()

    def test_expired_deadline_with_reachable_source_returns_false(self):
        """Verify that expired deadline with reachable source returns false."""
        probes = []
        with patch('climate_access.source_state', lambda *a: probes.append(1) or 'reachable'):
            self.assertFalse(self.jobs.wait_for_source({'url': 'synthetic', 'bytes': 1}, deadline=10, clock=lambda: 20))
        self.assertEqual(probes, [])              # no probe once the budget is spent

    def test_reachable_answer_after_expiry_does_not_permit_retry(self):
        """Verify that reachable answer after expiry does not permit retry."""
        now = [0.0]
        def late_success(*args):
            """Simulate a successful probe that returns only after its deadline."""
            now[0] = 15.0                         # the probe itself finishes past the deadline
            return 'reachable'
        with patch('climate_access.source_state', late_success):
            self.assertFalse(self.jobs.wait_for_source({'url': 'u', 'bytes': 1}, deadline=10, clock=lambda: now[0],
                                                       sleep=lambda s: None))

    def test_successive_outages_share_one_budget(self):
        """Verify that successive outages share one budget."""
        now = [0.0]
        waits = []
        def runner(*args, **kwargs):
            """Provide the controlled job outcome required by this retry test."""
            climate_access.STATS.record_giveup('u', 1, None)
            raise OSError('getaddrinfo failed')
        def waiter(item, deadline):
            """Simulate source waiting and deadline consumption for this test."""
            waits.append(deadline - now[0])       # budget offered to this wait
            now[0] += 400                         # each outage lasts 400 s
            return now[0] < deadline
        with self.assertRaises(OSError):
            self.jobs.execute_job(self.job, None, {}, attempts=10, runner=runner, waiter=waiter,
                                  clock=lambda: now[0], wait_budget=1000)
        self.assertEqual(waits, [1000, 600, 200])  # shared budget, then no further attempt

    def test_compute_time_is_not_charged_to_the_wait_budget(self):
        """Verify that compute time is not charged to the wait budget."""
        now = [0.0]
        calls = []
        offered = []
        def runner(*args, **kwargs):
            """Provide the controlled job outcome required by this retry test."""
            calls.append(1)
            now[0] += 5000                        # a long normal download/compute
            if len(calls) == 1:
                climate_access.STATS.record_giveup('u', 1, None)
                raise OSError('reset')
            return 'folder'
        def waiter(item, deadline):
            """Simulate source waiting and deadline consumption for this test."""
            offered.append(deadline - now[0])
            return True
        self.jobs.execute_job(self.job, None, {}, attempts=3, runner=runner, masker=lambda f, m: {},
                              waiter=waiter, clock=lambda: now[0], wait_budget=1000)
        self.assertEqual(offered, [1000])

    def test_no_retry_when_budget_already_spent(self):
        """Verify that no retry when budget already spent."""
        calls = []
        def runner(*args, **kwargs):
            """Provide the controlled job outcome required by this retry test."""
            calls.append(1)
            climate_access.STATS.record_giveup('u', 1, None)
            raise OSError('reset')
        with self.assertRaises(OSError):
            self.jobs.execute_job(self.job, None, {}, attempts=5, runner=runner, wait_budget=0,
                                  waiter=lambda item, deadline: self.fail('must not wait'))
        self.assertEqual(len(calls), 1)


class BoundedReadTests(unittest.TestCase):
    """A misbehaving server must not make the reader download or buffer a whole file."""

    @classmethod
    def setUpClass(cls):
        """Create shared synthetic test resources and check local transport availability."""
        cls.directory = tempfile.TemporaryDirectory()
        cls.path = Path(cls.directory.name)/'big.bin'
        cls.path.write_bytes(np.random.default_rng(1).bytes(8 * 1024 * 1024))
        cls.server, cls.base, cls.stats = serve(cls.directory.name)
        if not loopback_available(cls.server):
            cls.server.shutdown(); cls.directory.cleanup()
            raise unittest.SkipTest(LOOPBACK_SKIP)
        cls.direct = patch('climate_access._proxied', return_value=False)
        cls.direct.start()
        cls.fast = [patch('climate_access.time.sleep'), patch.object(RangeReader, 'max_attempts', 2)]
        for patcher in cls.fast: patcher.start()

    @classmethod
    def tearDownClass(cls):
        """Stop shared test services and clean up their temporary inputs."""
        for patcher in cls.fast: patcher.stop()
        cls.direct.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.directory.cleanup()

    def setUp(self):
        """Create isolated synthetic inputs for this test; do not use or modify private research data."""
        climate_access._local.__dict__.clear()
        self.stats.mode, self.stats.requests, self.stats.connections = 'normal', 0, 0

    def reads(self):
        """Count HTTP response bytes read during a bounded-read test."""
        import http.client
        amounts = []
        original = http.client.HTTPResponse.read
        def read(response, amt=None):
            """Read bytes at the current position, preserving the file-like contract and configured response-size bounds."""
            amounts.append(amt)
            return original(response, amt)
        return amounts, patch('http.client.HTTPResponse.read', read)

    def test_ignored_range_is_rejected_without_reading_body(self):
        """Verify that ignored range is rejected without reading body."""
        self.stats.mode = 'ignore_range'
        amounts, patcher = self.reads()
        with patcher, self.assertRaises(climate_access.SourceIntegrityError):
            RangeReader(self.base + 'big.bin', self.path.stat().st_size, '"v1"').read(10)
        self.assertNotIn(None, amounts)                     # never an unbounded read
        self.assertTrue(all(a <= 65537 for a in amounts))
        self.assertEqual(self.stats.requests, 1)            # not retried
        self.assertEqual(climate_access._local.connections, {})   # socket discarded

    def test_oversized_body_is_rejected_and_connection_discarded(self):
        """Verify that oversized body is rejected and connection discarded."""
        self.stats.mode = 'oversize'
        amounts, patcher = self.reads()
        with patcher, self.assertRaises(climate_access.SourceIntegrityError):
            RangeReader(self.base + 'big.bin', self.path.stat().st_size, '"v1"').read(10)
        self.assertTrue(all(a is not None and a <= 65537 for a in amounts))
        self.assertEqual(self.stats.requests, 1)
        self.assertEqual(climate_access._local.connections, {})
        self.stats.mode = 'normal'
        data = RangeReader(self.base + 'big.bin', self.path.stat().st_size, '"v1"').read(10)
        self.assertEqual(data, self.path.read_bytes()[:10])
        self.assertEqual(self.stats.connections, 2)         # a fresh socket after the bad one

    def test_source_state_distinguishes_outcomes(self):
        """Verify that source state distinguishes outcomes."""
        size = self.path.stat().st_size
        url = self.base + 'big.bin'
        self.assertEqual(climate_access.source_state(url, size, '"v1"'), 'reachable')
        self.assertEqual(climate_access.source_state(url, size, '"other"'), 'integrity')
        self.assertEqual(climate_access.source_state(url, size + 1, '"v1"'), 'integrity')
        self.stats.mode = 'ignore_range'
        self.assertEqual(climate_access.source_state(url, size, '"v1"'), 'integrity')
        self.assertEqual(climate_access.source_state('http://127.0.0.1:9/none', size), 'unreachable')


if __name__ == '__main__':
    unittest.main()
