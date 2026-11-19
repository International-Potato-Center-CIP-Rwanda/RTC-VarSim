"""Build an offline geographic context from the user's local geoBoundaries file."""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from shapely import from_wkb, make_valid
from shapely.geometry import mapping, box

BASE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get('AFSA_BOUNDARIES_PATH') or BASE/'data/source/geoBoundariesCGAZ_ADM0.gpkg').expanduser().resolve()
extent = box(-30, -40, 65, 42)
features = []
with sqlite3.connect(SOURCE.as_uri() + '?mode=ro', uri=True) as connection:
    for blob, code, name in connection.execute('select geom,shapeGroup,shapeName from globalADM0'):
        offset = 8 + {0:0,1:32,2:48,3:48,4:64}[(blob[3] >> 1) & 7]
        geometry = from_wkb(blob[offset:])
        if not geometry.intersects(extent):
            continue
        geometry = make_valid(geometry.simplify(.025, preserve_topology=True)).intersection(extent)
        largest = max(geometry.geoms, key=lambda g:g.area) if geometry.geom_type == 'MultiPolygon' else geometry
        point = largest.representative_point()
        features.append({'type':'Feature','properties':{'name':name,'code':code,'label':[point.y,point.x], 'area':geometry.area},'geometry':mapping(geometry)})
(BASE/'assets/africa-boundaries.json').write_text(json.dumps({'type':'FeatureCollection','features':features},separators=(',',':')),encoding='utf-8')
(BASE/'assets/africa-basemap-provenance.json').write_text(json.dumps({'source':SOURCE.name,'sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'provider':'geoBoundaries CGAZ ADM0, user-provided local file','extent':[-30,-40,65,42],'simplification_degrees':.025,'purpose':'Geographic context only; does not extend Rwanda analysis coverage.'},indent=2),encoding='utf-8')
print(f'Created offline basemap: {len(features)} geographic features.')
