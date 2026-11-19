"""Build a separate, sampled display dataset; never modify source tiles."""
import hashlib
import json
from pathlib import Path
import numpy as np
import rasterio
BASE=Path(__file__).resolve().parent
STEP=16

def build():
    """Sample every completed tile/month into monthly.npz using the current plan-mask-inventory signature; reject incomplete inputs."""
    plan=json.loads((BASE/'data/africa-tiles.json').read_text())
    tiles=plan['tiles']; r0=min(t['row'] for t in tiles); c0=min(t['col'] for t in tiles)
    h=(max(t['row']+t['height'] for t in tiles)-r0)//STEP
    w=(max(t['col']+t['width'] for t in tiles)-c0)//STEP
    data=np.full((h,w,2,12),np.nan,dtype='float32')
    signature=hashlib.sha256((json.dumps(plan,sort_keys=True)
        +(BASE/'data/africa-extraction-mask.geojson').read_text()
        +(BASE/'data/africa-1991-2020-inventory.json').read_text()).encode()).hexdigest()[:16]
    root=BASE/'data/africa-jobs'/signature
    for vi,v in enumerate(('tas','pr')):
        for month in range(1,13):
            for t in tiles:
                job=json.loads((root/f"r{t['row']}-c{t['col']}-{v}-{month:02d}.json").read_text())
                if job['status']!='complete': raise ValueError('Incomplete tile')
                with rasterio.open(Path(job['folder'])/'africa-mean.tif') as src:
                    values=src.read(1,masked=True).filled(np.nan)[STEP//2::STEP,STEP//2::STEP]
                r=(t['row']-r0)//STEP;c=(t['col']-c0)//STEP
                data[r:r+values.shape[0],c:c+values.shape[1],vi,month-1]=values
            print(f'{v}-{month:02d} prepared',flush=True)
    dest=BASE/'data/demo-climate';dest.mkdir(exist_ok=True)
    np.savez_compressed(dest/'monthly.npz',values=data,row=r0,col=c0,step=STEP)
    print('Demo dataset ready',flush=True)
if __name__=='__main__':build()
