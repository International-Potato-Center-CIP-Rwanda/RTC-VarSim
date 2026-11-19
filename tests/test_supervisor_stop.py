"""Supervisor-level checks: an outage followed by STOP ends as 'stopped' (not 'failed'),
and an outage followed by recovery completes the jobs without a manual restart.

Runs run_climate_background.py -> africa_climate_jobs.py as real subprocesses on a tiny
synthetic plan served by a local HTTP server. On non-Windows systems the Windows file
lock is stubbed by a small launcher (on Windows the real supervisor runs unchanged).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
import rasterio
from range_server import serve, loopback_available
from test_climate_network import write_raster

SOURCE = Path(__file__).resolve().parent.parent
SCRIPTS = ('run_climate_background.py', 'africa_climate_jobs.py', 'extract_climate_tile.py', 'climate_access.py',
           'climate_block_cache.py', 'climate_normals.py', 'verify_climate_outputs.py')
# Off Windows, run the supervisor through a launcher that stubs `msvcrt` *after* importing
# subprocess (subprocess itself treats an importable msvcrt as "this is Windows").
LAUNCHER = '''import runpy, subprocess, sys, types
stub = types.ModuleType('msvcrt')
stub.LK_NBLCK, stub.LK_UNLCK = 2, 0
stub.locking = lambda fd, mode, nbytes: None
sys.modules['msvcrt'] = stub
runpy.run_path('run_climate_background.py', run_name='__main__')
'''


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        """Create isolated synthetic inputs for this test; do not use or modify private research data."""
        self.work = Path(tempfile.mkdtemp())
        sources = self.work/'sources'
        sources.mkdir()
        for year in range(1991, 2021):
            write_raster(sources/f'tas_{year}.tif', tiled=True, size=300, seed=year, year=year)
        self.server, url, self.stats = serve(str(sources))
        if not loopback_available(self.server):
            self.server.shutdown()
            self.skipTest('loopback HTTP (127.0.0.1) is blocked in this environment')
        self.base = self.work/'app'
        (self.base/'data').mkdir(parents=True)
        for name in SCRIPTS:
            shutil.copy(SOURCE/name, self.base/name)
        (self.base/'launch_supervisor.py').write_text(LAUNCHER)
        files = [dict(variable='tas', year=y, month=1, url=url + f'tas_{y}.tif',
                      bytes=(sources/f'tas_{y}.tif').stat().st_size, etag='"v1"') for y in range(1991, 2021)]
        (self.base/'data/africa-1991-2020-inventory.json').write_text(json.dumps(dict(files=files)))
        with rasterio.open(sources/'tas_1991.tif') as src:
            grid = dict(transform=list(src.transform), shape=list(src.shape))
            b = src.bounds
        (self.base/'data/probe-tas-1991-01.json').write_text(json.dumps(grid))
        tiles = [dict(row=0, col=0, height=150, width=150), dict(row=150, col=150, height=150, width=150)]
        (self.base/'data/africa-tiles.json').write_text(json.dumps(dict(tiles=tiles)))
        ring = [[b.left, b.bottom], [b.right, b.bottom], [b.right, b.top], [b.left, b.top], [b.left, b.bottom]]
        (self.base/'data/africa-extraction-mask.geojson').write_text(
            json.dumps(dict(features=[dict(geometry=dict(type='Polygon', coordinates=[ring]))])))
        self.env = dict(os.environ, AFSA_RANGE_ATTEMPTS='2', AFSA_NETWORK_POLL_SECONDS='1',
                        AFSA_NETWORK_WAIT_SECONDS='120', AFSA_HTTP_TIMEOUT='5', NO_PROXY='127.0.0.1', no_proxy='127.0.0.1')

    def tearDown(self):
        """Release the temporary resources created by this test."""
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.work, ignore_errors=True)

    def supervise(self, during):
        """Run the climate-supervisor test fixture and apply its simulated outage or stop action."""
        threading.Thread(target=during, daemon=True).start()
        script = 'run_climate_background.py' if os.name == 'nt' else 'launch_supervisor.py'
        child = subprocess.run([sys.executable, '-W', 'ignore', script], cwd=self.base,
                               env=self.env, capture_output=True, text=True, timeout=300)
        status = json.loads((self.base/'data/background/status.json').read_text())
        root = next((self.base/'data/africa-jobs').iterdir())
        markers = {p.name: json.loads(p.read_text())['status'] for p in root.glob('r*.json')}
        log = (self.base/'data/background/worker.log').read_text()
        return child.returncode, status, markers, log

    def test_stop_during_outage_is_stopped_not_failed(self):
        """Verify that stop during outage is stopped not failed."""
        self.stats.fail_next = 10**9                       # network down from the start

        def during():
            """Apply the stop or network-recovery event while the isolated supervisor is running."""
            deadline = time.time() + 60
            while 'Network unavailable' not in self._log() and time.time() < deadline:
                time.sleep(0.2)
            (self.base/'data/background/STOP').write_text('')
        code, status, markers, log = self.supervise(during)
        self.assertEqual(code, 0, log[-1500:])
        self.assertEqual(status['status'], 'stopped', log[-1500:])
        self.assertNotIn('failed', markers.values())
        self.assertEqual(markers, {})                      # interrupted job returned to pending
        self.assertIn('job left pending', log)

    def test_outage_then_recovery_completes_without_restart(self):
        """Verify that outage then recovery completes without restart."""
        self.stats.fail_next = 10**9

        def during():
            """Apply the stop or network-recovery event while the isolated supervisor is running."""
            deadline = time.time() + 60
            while 'Network unavailable' not in self._log() and time.time() < deadline:
                time.sleep(0.2)
            self.stats.fail_next = 0
        code, status, markers, log = self.supervise(during)
        january = {name: state for name, state in markers.items() if name.endswith('-tas-01.json')}
        self.assertEqual(january, {'r0-c0-tas-01.json': 'complete', 'r150-c150-tas-01.json': 'complete'}, log[-1500:])
        self.assertIn('network_retry', log)
        # The synthetic inventory only has January temperature, so the next planned layer
        # (February) fails its inventory check by design; that is unrelated to the outage.

    def _log(self):
        """Read the isolated supervisor test log for failure diagnostics."""
        try:
            return (self.base/'data/background/worker.log').read_text()
        except OSError:
            return ''


if __name__ == '__main__':
    unittest.main()
