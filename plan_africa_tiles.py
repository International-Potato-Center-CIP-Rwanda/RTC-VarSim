"""Plan native-grid 512-pixel tiles intersecting the prepared African mask."""
import json
from pathlib import Path
import rasterio
from shapely.geometry import shape, box
from shapely.strtree import STRtree

BASE=Path(__file__).resolve().parent
grid=json.loads((BASE/'data/probe-tas-1991-01.json').read_text())
features=json.loads((BASE/'data/africa-extraction-mask.geojson').read_text())['features']
geometries=[shape(f['geometry']) for f in features]
tree=STRtree(geometries)
transform=rasterio.Affine(*grid['transform'][:6])
height,width=grid['shape']
tiles=[]
for row in range(0,height,512):
    for col in range(0,width,512):
        window=rasterio.windows.Window(col,row,min(512,width-col),min(512,height-row))
        bounds=rasterio.windows.bounds(window,transform)
        if len(tree.query(box(*bounds),predicate='intersects')):
            tiles.append(dict(row=row,col=col,height=int(window.height),width=int(window.width),bounds=bounds))
result=dict(status='Spatial plan only; extraction not run',tile_size=512,crs='EPSG:4326',transform=list(transform),
            total_tiles=len(tiles),tiles=tiles,
            requirement='Apply the land mask per tile; tile bounding rectangles also contain sea and non-African land.')
(BASE/'data/africa-tiles.json').write_text(json.dumps(result,indent=2))
print(f'{len(tiles)} tiles planned; 24 monthly-variable outputs per tile')
