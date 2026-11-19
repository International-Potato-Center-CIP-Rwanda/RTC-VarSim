"""Local exploratory runs; catalogue tolerances do not enter this calculation."""
import json
import struct
import zlib
import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds
from build_map_layers import chunk
from .engine import static_similarity
from .setup import validate_setup


def compute(payload, cfg, catalogue, directory):
    """Validate a Rwanda pilot setup, compute the raster and save result files with configuration and source provenance."""
    setup = validate_setup(payload, cfg, catalogue)
    site = setup['reference_site']
    if site is None:
        raise ValueError('Select a reference site before computing.')
    available = {layer['id']: dict(layer) for layer in cfg['layers']}
    for layer in cfg.get('supplemental_layers', []):
        # Harmonized soil/terrain rasters already contain physical units.
        available[layer['id']] = dict(layer, scale=1, offset=0)
    layers = [dict(available[p['id']], **p) for p in setup['parameters']]
    stats = static_similarity(layers, site['longitude'], site['latitude'], directory / 'similarity.tif')
    setup['limitations'] = [item for item in setup['limitations'] if item != 'No calculation has been run.']
    with rasterio.open(directory / 'similarity.tif') as src:
        affine, width, height = calculate_default_transform(src.crs, 'EPSG:3857', src.width, src.height, *src.bounds)
        projected = np.full((height, width), np.nan, dtype='float32')
        reproject(src.read(1, masked=True).filled(np.nan), projected,
                  src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
                  dst_transform=affine, dst_crs='EPSG:3857', dst_nodata=np.nan,
                  resampling=Resampling.nearest)
        rgba = np.zeros((height, width, 4), dtype='uint8')
        t = np.clip(np.nan_to_num(projected), 0, 1)
        colors = ['#440154', '#21918c', '#fde725']
        rgb = np.array([[int(c[i:i+2], 16) for i in (1,3,5)] for c in colors])
        for band in range(3):
            rgba[:,:,band] = np.interp(t, [0, .5, 1], rgb[:,band])
        rgba[:,:,3] = np.where(np.isfinite(projected), 255, 0)
        raw = b''.join(b'\0' + row.tobytes() for row in rgba)
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width,height,8,6,0,0,0)) + chunk(b'IDAT',zlib.compress(raw)) + chunk(b'IEND',b'')
        (directory / 'similarity.png').write_bytes(png)
        west,south,east,north = transform_bounds('EPSG:3857','EPSG:4326',affine.c,affine.f+affine.e*height,affine.c+affine.a*width,affine.f)
    metadata = {'execution_status':'completed', 'setup': setup, 'statistics': stats,
                'interpretation': 'Exploratory environmental similarity to a reference site, not crop suitability or yield probability. Variety is contextual only; its tolerance ranges are not used.',
                'formula': 'sum(weight * normalization / (normalization + abs(value - reference)))',
                'bounds': [[south,west],[north,east]], 'colors': colors}
    (directory / 'metadata.json').write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding='utf-8')
    return metadata
