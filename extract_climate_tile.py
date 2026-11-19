"""Resumable native-grid monthly normal for one tile; never a continent-wide claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import rasterio
from rasterio.windows import Window
import climate_access
from climate_access import RangeReader
from climate_normals import MonthlyNormal
from climate_block_cache import BlockCache

BASE = Path(__file__).resolve().parent

def run(variable, month, lon, lat, size=32, *, grid_window=None):
    """Build one resumable monthly normal from all thirty annual CHELSA windows; validate units and grid before writing tile outputs."""
    if not 1 <= month <= 12 or not 1 <= size <= 512: raise ValueError('Invalid month or tile size')
    inventory = json.loads((BASE/'data/africa-1991-2020-inventory.json').read_text())['files']
    items = sorted([x for x in inventory if x['variable']==variable and x['month']==month],key=lambda x:x['year'])
    if [x['year'] for x in items] != list(range(1991,2021)): raise ValueError('Incomplete inventory')
    grid = json.loads((BASE/'data/probe-tas-1991-01.json').read_text())
    transform = rasterio.Affine(*grid['transform'][:6])
    if grid_window is None:
        row,col = rasterio.transform.rowcol(transform,lon,lat)
        row,col = int(row),int(col)
        width=height=size
    else:
        row,col,height,width = (int(grid_window[k]) for k in ('row','col','height','width'))
    window = Window(col,row,width,height)
    if not 1 <= width <= 512 or not 1 <= height <= 512 or row < 0 or col < 0 or row+height > grid['shape'][0] or col+width > grid['shape'][1]: raise ValueError('Outside grid')
    identity = dict(variable=variable,month=month,row=row,col=col,size=size,sources=items,algorithm='strict-normal-v1')
    if grid_window is not None: identity.update(height=height,width=width)
    digest = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    folder = BASE/'data/climate-tiles'/digest[:16]
    folder.mkdir(parents=True,exist_ok=True)
    block_cache=BlockCache(BASE/'data/http-block-cache.sqlite')
    def fetch_year(item):
        """Reuse a matching annual extract or fetch, convert and cache that year after validating its source metadata."""
        cached = folder/f"{item['year']}.npz"
        if cached.exists():
            with np.load(cached,allow_pickle=False) as saved:
                if str(saved['identity']) != digest: raise ValueError('Cache identity mismatch')
                return item['year'],np.ma.array(saved['values'],mask=saved['mask'])
        def opener(path,mode='rb'):
            """Adapt the range reader to Rasterio file access; accept the expected virtual raster path and preserve source identity checks."""
            if str(path) != 'remote.tif': raise FileNotFoundError(path)
            return RangeReader(item['url'],item['bytes'],item['etag'],disk_cache=block_cache).prime()
        with rasterio.open('remote.tif',opener=opener) as src:
            tags = src.tags()
            if tags.get('variable') != variable or not tags.get('datetime','').startswith(f"{item['year']}-{month:02d}-"): raise ValueError('Source identity mismatch')
            if tags.get('variable_unit') != {'tas':'K','pr':'kg m-2 month-1'}[variable]: raise ValueError('Units mismatch')
            if src.crs != rasterio.crs.CRS.from_epsg(4326) or src.count != 1 or list(src.shape)!=grid['shape'] or not np.allclose(list(src.transform),grid['transform'],rtol=0,atol=1e-10): raise ValueError('Grid mismatch')
            values = src.read(1,window=window,masked=True).astype('float64')
            values = values*src.scales[0]+src.offsets[0]-(273.15 if variable=='tas' else 0)
        temp = cached.with_suffix('.partial')
        with temp.open('wb') as stream:
            np.savez_compressed(stream,values=values.data,mask=np.ma.getmaskarray(values),identity=digest)
        temp.replace(cached)
        print(f"Cached {variable} {item['year']}-{month:02d}",flush=True)
        return item['year'],values
    def fetch(item):
        """Fetch one annual extract and record permanent integrity failures without retrying them as network outages."""
        try:
            return fetch_year(item)
        except ValueError:
            # Identity/units/grid checks: permanent data errors, never retried as network failures.
            climate_access.STATS.add(integrity_errors=1)
            raise
    normal = MonthlyNormal((height,width))
    try:
        with ThreadPoolExecutor(max_workers=int(os.environ.get('AFSA_YEAR_WORKERS', 2))) as pool:
            for year,values in pool.map(fetch,items): normal.add(year,values)
    finally:
        block_cache.close()   # after all worker threads have finished (the with-block joins them)
    mean,counts = normal.finish()
    profile = dict(driver='GTiff',height=height,width=width,count=1,crs='EPSG:4326',transform=rasterio.windows.transform(window,transform),compress='deflate')
    for name,data,dtype,nodata in [('mean.tif',mean.filled(-9999),'float32',-9999),('valid-years.tif',counts,'uint8',None)]:
        target = folder/name
        temp = target.with_suffix('.partial.tif')
        with rasterio.open(temp,'w',**profile,dtype=dtype,nodata=nodata) as dest:
            dest.write(data.astype(dtype),1)
            units = 'years' if name=='valid-years.tif' else ('degree_Celsius' if variable=='tas' else 'mm/month')
            dest.update_tags(period='1991-2020',variable=variable,month=str(month),units=units,scope='Unmasked tile; not complete Africa coverage')
        temp.replace(target)
    (folder/'metadata.json').write_text(json.dumps(dict(**identity,identity=digest,status='Complete 30-year tile, not continental coverage',valid_cells=int(mean.count())),indent=2))
    print(json.dumps(dict(folder=str(folder),valid_cells=int(mean.count()),minimum=float(mean.min()),maximum=float(mean.max()))))
    return folder

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--variable',choices=['tas','pr'],required=True)
    parser.add_argument('--month',type=int,required=True)
    parser.add_argument('--lon',type=float,required=True)
    parser.add_argument('--lat',type=float,required=True)
    parser.add_argument('--size',type=int,default=32)
    args=parser.parse_args()
    run(args.variable,args.month,args.lon,args.lat,args.size)
