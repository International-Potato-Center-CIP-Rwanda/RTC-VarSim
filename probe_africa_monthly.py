"""Probe actual monthly series at independent African locations (not a climatology)."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import rasterio
import numpy as np
from climate_access import RangeReader

BASE = Path(__file__).resolve().parent
SITES = {'Morocco': (-6, 32), 'Ghana': (-1, 7), 'Kenya': (37, 0), 'South Africa': (25, -29), 'Madagascar': (47, -19)}

def probe(item):
    """Inspect a remote CHELSA raster through bounded reads and record its grid, units and encoding metadata."""
    readers = []
    def opener(path, mode='rb'):
        """Adapt the range reader to Rasterio file access; accept the expected virtual raster path and preserve source identity checks."""
        if str(path) != 'remote.tif': raise FileNotFoundError(path)
        reader = RangeReader(item['url'], item['bytes'], item['etag'])
        readers.append(reader)
        return reader
    with rasterio.open('remote.tif', opener=opener) as src:
        tags = src.tags()
        if tags.get('variable') != item['variable']: raise ValueError('Variable mismatch')
        if not tags.get('datetime', '').startswith(f"{item['year']}-{item['month']:02d}-"):
            raise ValueError('Date mismatch')
        if src.crs != rasterio.crs.CRS.from_epsg(4326) or src.count != 1:
            raise ValueError('Unexpected grid or band count')
        unit = tags.get('variable_unit')
        if unit != {'tas':'K', 'pr':'kg m-2 month-1'}[item['variable']]:
            raise ValueError(f'Unexpected units: {unit}')
        samples = {}
        for name, point in SITES.items():
            value = next(src.sample([point], masked=True))[0]
            samples[name] = None if np.ma.is_masked(value) else float(value * src.scales[0] + src.offsets[0] - (273.15 if item['variable']=='tas' else 0))
        result = dict(source=item, tags=tags, scale=src.scales[0], offset=src.offsets[0],
                      nodata=src.nodata, crs=str(src.crs), transform=list(src.transform),
                      shape=list(src.shape), samples=samples,
                      sample_unit='Celsius' if item['variable']=='tas' else 'mm/month',
                      transferred_bytes=sum(r.transferred for r in readers))
    path = BASE/'data'/f"probe-{item['variable']}-{item['year']}-{item['month']:02d}.json"
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return {k:result[k] for k in ('source', 'samples', 'transferred_bytes')}

if __name__ == '__main__':
    files = json.loads((BASE/'data/africa-1991-2020-inventory.json').read_text())['files']
    selected = [f for f in files if f['year'] in (1991,2020) and f['month']==1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(probe, selected): print(json.dumps(result), flush=True)
