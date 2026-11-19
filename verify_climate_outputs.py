"""Verify completed continental jobs without downloading or modifying rasters."""
import hashlib
import json
from pathlib import Path
import numpy as np
import rasterio
from extract_climate_tile import BASE

def verify():
    """Verify completed climate job rasters and provenance; report failures without claiming that pending jobs are complete."""
    plan=json.loads((BASE/'data/africa-tiles.json').read_text())
    mask=BASE/'data/africa-extraction-mask.geojson'
    inventory=BASE/'data/africa-1991-2020-inventory.json'
    signature=hashlib.sha256((json.dumps(plan,sort_keys=True)+mask.read_text()+inventory.read_text()).encode()).hexdigest()
    root=BASE/'data/africa-jobs'/signature[:16]
    jobs=[json.loads(p.read_text()) for p in root.glob('*.json') if p.name!='plan.json']
    completed=[job for job in jobs if job['status']=='complete']
    cells=0
    for job in completed:
        folder=Path(job['folder'])
        output=folder/'africa-mean.tif'
        if hashlib.sha256(output.read_bytes()).hexdigest()!=job['output_sha256']:
            raise ValueError(f"Changed output: {job['id']}")
        with rasterio.open(output) as mean, rasterio.open(folder/'valid-years.tif') as counts:
            values=mean.read(1,masked=True)
            valid=~np.ma.getmaskarray(values)
            if mean.shape!=counts.shape or mean.transform!=counts.transform or mean.crs!=counts.crs:
                raise ValueError(f"Output grid mismatch: {job['id']}")
            if not (counts.read(1)[valid]==30).all() or not np.isfinite(values.compressed()).all():
                raise ValueError(f"Incomplete or nonfinite output: {job['id']}")
            if int(valid.sum())!=job['valid_land_cells'] or mean.tags().get('period')!='1991-2020':
                raise ValueError(f"Output metadata mismatch: {job['id']}")
            cells+=int(valid.sum())
    report=dict(signature=signature,verified_completed_outputs=len(completed),valid_land_cells=cells,
                failed_jobs=sum(job['status']=='failed' for job in jobs),
                running_jobs=sum(job['status']=='running' for job in jobs),
                note='Valid pixel count sums across outputs; it is not an area or a unique continental pixel count across months.')
    (BASE/'data/climate-output-verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))

if __name__=='__main__': verify()
