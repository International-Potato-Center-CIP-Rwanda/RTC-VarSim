"""Build an unsimplified African extraction mask from local CGAZ boundaries."""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from shapely import from_wkb, make_valid
from shapely.geometry import box, mapping

BASE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get('AFSA_BOUNDARIES_PATH') or BASE/'data/source/geoBoundariesCGAZ_ADM0.gpkg').expanduser().resolve()
CODES = set('AGO BDI BEN BFA BWA CAF CIV CMR COD COG COM CPV DJI DZA EGY ERI ETH GAB GHA GIN GMB GNB GNQ KEN LBR LBY LSO MAR MDG MLI MOZ MRT MUS MWI NAM NER NGA RWA SDN SEN SLE SOM SSD STP SWZ SYC TCD TGO TUN TZA UGA ZAF ZMB ZWE ESH 111 122 124'.split())
# Overseas regions are selected geographically, not by their sovereign's entire geometry.
EXTRAS = {'ESP':[(-19,27,-13,30),(-6,35,-2,36)], 'PRT':[(-18,32,-16,34)],
          'FRA':[(43,-14,46,-11),(55,-22,56,-20)],
          'GBR':[(-15,-17,-5,-7)], 'YEM':[(52,12,55,13.5)]}

def build():
    """Read the supplied boundaries, validate CRS provenance and write the African extraction mask and its checksummed provenance."""
    features = []
    seen = set()
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    with sqlite3.connect(SOURCE.as_uri()+'?mode=ro', uri=True) as conn:
        srs = conn.execute("select srs_id from gpkg_geometry_columns where table_name='globalADM0'").fetchone()[0]
        # The official GPKG omits its CRS. Its identical-release shapefile PRJ
        # declares WGS84; permit that correction only for this verified file.
        verified_hash = '6bdeb27072cf3759edfe9d31e037ebaf2481d9e0fa5ad18c1036346e42b4c41a'
        if srs != 4326 and not (srs == 0 and source_hash == verified_hash):
            raise ValueError('Unverified source CRS')
        for blob, code, name in conn.execute('select geom,shapeGroup,shapeName from globalADM0'):
            if code not in CODES and code not in EXTRAS: continue
            offset = 8 + {0:0,1:32,2:48,3:48,4:64}[(blob[3] >> 1) & 7]
            geometry = make_valid(from_wkb(blob[offset:]))
            if code in CODES:
                pieces = [geometry]
                seen.add(code)
            else:
                pieces = [geometry.intersection(box(*bounds)) for bounds in EXTRAS[code]]
            for piece in pieces:
                if piece.is_empty or piece.area == 0: continue
                features.append(dict(type='Feature', properties=dict(code=code, name=name), geometry=mapping(piece)))
    missing = sorted(CODES-seen)
    if missing: raise ValueError(f'Missing source boundaries: {missing}')
    output = BASE/'data/africa-extraction-mask.geojson'
    output.write_text(json.dumps(dict(type='FeatureCollection', features=features), separators=(',',':')), encoding='utf-8')
    provenance = dict(source=str(SOURCE), sha256=source_hash,
                      crs='EPSG:4326', original_srs_id=srs,
                      crs_evidence='Official same-release shapefile geoBoundariesCGAZ_ADM0.prj declares GCS_WGS_1984; local GPKG SHA256 matches official Git LFS pointer, checked 2026-10-07',
                      crs_evidence_url='https://github.com/wmgeolab/geoBoundaries/tree/main/releaseData/CGAZ',
                      simplification=False, included_codes=sorted(CODES), additional_region_boxes=EXTRAS,
                      status='Extraction mask prepared; small-island raster coverage still requires checking',
                      note='Boundary labels retained from source; geographic processing scope does not assert sovereignty.')
    (BASE/'data/africa-extraction-mask-provenance.json').write_text(json.dumps(provenance,indent=2))
    print(f'{len(features)} features written; no missing requested codes')

if __name__ == '__main__': build()
