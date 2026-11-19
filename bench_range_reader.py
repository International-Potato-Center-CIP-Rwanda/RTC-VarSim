"""Benchmark the RangeReader transport. Writes nothing to data/ and never touches
job markers, the shared block cache or the running worker.

Synthetic mode (default): local server with simulated latency/bandwidth; compares
this directory's climate_access.py with another copy (--baseline DIR).
Remote mode (--remote): read ONE window of ONE inventory file a few times, without
the disk cache, and report requests, bytes and seconds. Run it while the worker is
stopped, or accept that both share your bandwidth for ~1 minute.

  python bench_range_reader.py --baseline ../source-original
  python bench_range_reader.py --remote --years 3
"""
import argparse
import importlib.util
import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

HERE = Path(__file__).resolve().parent


def load_module(path, name):
    """Load an alternate range-reader module from a file for a controlled benchmark comparison."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_window(module, url, size, etag, window):
    """Read one masked raster window through the supplied range-reader implementation."""
    def opener(path, mode='rb'):
        """Adapt the range reader to Rasterio file access; accept the expected virtual raster path and preserve source identity checks."""
        if str(path) != 'remote.tif':
            raise FileNotFoundError(path)
        reader = module.RangeReader(url, size, etag)
        return reader.prime() if hasattr(reader, 'prime') else reader
    with rasterio.open('remote.tif', opener=opener) as src:
        return src.read(1, window=window, masked=True)


def job(module, url, size, etag, window, years, workers):
    """Benchmark repeated annual window reads with the requested worker count and return transport statistics."""
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: read_window(module, url, size, etag, window), range(years)))
    return time.monotonic() - started, results[0]


def synthetic(args):
    """Benchmark local synthetic tiled and striped rasters under simulated connection, latency and bandwidth limits."""
    sys.path.insert(0, str(HERE/'tests'))
    from range_server import serve
    from test_climate_network import write_raster  # noqa: E402
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        layouts = {}
        for name, tiled in (('tiled.tif', True), ('strips.tif', False)):
            write_raster(root/name, tiled=tiled, size=args.size)
            layouts[name] = root/name
        server, base, stats = serve(directory, connect_delay=args.connect_delay, rtt=args.rtt, bandwidth=args.bandwidth)
        versions = {'proposed': load_module(HERE/'climate_access.py', 'ca_proposed')}
        if args.baseline:
            versions = {'baseline': load_module(Path(args.baseline)/'climate_access.py', 'ca_baseline'), **versions}
        if 'proposed' in versions:
            versions['proposed']._proxied = lambda url: False
        window = Window(args.size//4, args.size//4, 512, 512)
        rows, reference = [], {}
        for name, path in layouts.items():
            size = path.stat().st_size
            for label, module in versions.items():
                stats.connections = stats.requests = stats.bytes = 0
                seconds, values = job(module, base + name, size, '"v1"', window, args.years, args.workers)
                key = name
                if key in reference:
                    same = np.array_equal(values.filled(0), reference[key].filled(0)) and \
                        np.array_equal(np.ma.getmaskarray(values), np.ma.getmaskarray(reference[key]))
                else:
                    reference[key], same = values, True
                rows.append(dict(layout=name, version=label, seconds=round(seconds, 2), requests=stats.requests,
                                 connections=stats.connections, mbytes=round(stats.bytes/1e6, 2), identical=same))
        server.shutdown()
    print(json.dumps(dict(assumptions=dict(connect_delay_s=args.connect_delay, rtt_s=args.rtt,
                                           bandwidth_Bps=args.bandwidth, years=args.years, workers=args.workers,
                                           note='Simulated network; NOT a prediction for the real CHELSA server'),
                          results=rows), indent=2))


def remote(args):
    """Benchmark the configured CHELSA inventory source; this explicitly selected mode makes network requests."""
    module = load_module(HERE/'climate_access.py', 'ca_proposed')
    inventory = json.loads((HERE/'data/africa-1991-2020-inventory.json').read_text())['files']
    item = next(x for x in inventory if x['variable'] == args.variable and x['month'] == 1)
    grid = json.loads((HERE/'data/probe-tas-1991-01.json').read_text())
    window = Window(args.col, args.row, 512, 512)
    before = module.STATS.snapshot()
    seconds, _ = job(module, item['url'], item['bytes'], item['etag'], window, args.years, args.workers)
    after = module.STATS.snapshot()
    def opener(path, mode='rb'):
        """Adapt the range reader to Rasterio file access; accept the expected virtual raster path and preserve source identity checks."""
        if str(path) != 'remote.tif':
            raise FileNotFoundError(path)
        return module.RangeReader(item['url'], item['bytes'], item['etag']).prime()
    with rasterio.open('remote.tif', opener=opener) as src:
        layout = dict(block_shapes=src.block_shapes, compression=str(src.compression), overviews=src.overviews(1),
                      shape=src.shape, interleave=str(src.interleaving))
    print(json.dumps(dict(file=item['url'], grid_shape=grid['shape'], layout=layout, seconds=round(seconds, 2),
                          per_year_seconds=round(seconds/args.years, 2),
                          **{k: after[k]-before[k] for k in after}), indent=2, default=str))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', help='directory holding the original climate_access.py')
    parser.add_argument('--remote', action='store_true')
    parser.add_argument('--variable', default='tas', choices=['tas', 'pr'])
    parser.add_argument('--row', type=int, default=10240)
    parser.add_argument('--col', type=int, default=22016)
    parser.add_argument('--years', type=int, default=6)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--size', type=int, default=2048)
    parser.add_argument('--connect-delay', type=float, default=0.35)
    parser.add_argument('--rtt', type=float, default=0.15)
    parser.add_argument('--bandwidth', type=float, default=2.5e6)
    args = parser.parse_args()
    remote(args) if args.remote else synthetic(args)
