"""Static-only AFSA pilot. Seasonal alignment is intentionally not implemented here."""
from pathlib import Path
import math
import numpy as np
import rasterio
from rasterio.warp import transform


def inspect_layers(layers):
    """Check that configured raster layers share the grid and report their readable metadata before computation."""
    rows = []
    reference = None
    for layer in layers:
        row = dict(layer)
        row['ready'] = False
        if not layer.get('path'):
            row['status'] = 'File not configured'
        else:
            try:
                with rasterio.open(layer['path']) as src:
                    grid = (src.crs, src.transform, src.width, src.height)
                    row.update(crs=str(src.crs), resolution=str(src.res), width=src.width, height=src.height)
                    if src.crs is None or src.count != 1:
                        row['status'] = 'A CRS and a single band are required'
                    elif reference is not None and grid != reference:
                        row['status'] = 'Grid mismatch: harmonization required'
                    else:
                        reference = grid
                        row['ready'] = True
                        row['status'] = 'Compatible grid; units and provenance require verification'
            except (OSError, rasterio.errors.RasterioError):
                row['status'] = 'File missing or unreadable'
        rows.append(row)
    return rows


def static_similarity(layers, longitude, latitude, output):
    """Weighted c/(c+abs(x-reference)), following upstream static branch.

    No variety suitability claim, no seasonal rotation, no categorical soil codes.
    All positive-weight inputs must share their full grid; missing data stay masked.
    """
    if not layers or not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ValueError('Invalid coordinates or layers.')
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError('Coordinates must use WGS84 longitude/latitude.')
    weights = [float(l['weight']) for l in layers]
    if any(not math.isfinite(w) or w <= 0 for w in weights) or not math.isclose(sum(weights), 1, abs_tol=1e-6):
        raise ValueError('Weights must be positive and sum to 1.')
    rows = inspect_layers(layers)
    if not all(r['ready'] for r in rows):
        raise ValueError('Rasters must be available and share the same grid.')
    combined = None
    valid = None
    refs = {}
    for layer, weight in zip(layers, weights):
        coefficient = float(layer['normalization'])
        scale = float(layer.get('scale', 1))
        offset = float(layer.get('offset', 0))
        if not all(math.isfinite(v) for v in (coefficient, scale, offset)) or coefficient <= 0 or scale <= 0:
            raise ValueError('Invalid normalization or unit conversion.')
        with rasterio.open(layer['path']) as src:
            if src.width * src.height > 4_000_000:
                raise ValueError('Clip rasters to the pilot region before computing (maximum 4 million cells).')
            xs, ys = transform('EPSG:4326', src.crs, [longitude], [latitude])
            r, c = src.index(xs[0], ys[0])
            if not (0 <= r < src.height and 0 <= c < src.width):
                raise ValueError('The reference site is outside the raster.')
            data = src.read(1, masked=True).astype('float64') * scale + offset
            if np.ma.is_masked(data[r, c]) or not np.isfinite(data[r, c]):
                raise ValueError('A variable is missing at the reference site.')
            ref = float(data[r, c])
            refs[layer['id']] = ref
            values = data.filled(np.nan)
            mask = np.isfinite(values)
            score = weight * coefficient / (coefficient + np.abs(values - ref))
            combined = score if combined is None else combined + score
            valid = mask if valid is None else valid & mask
            profile = src.profile.copy()
    result = np.where(valid, combined, -9999).astype('float32')
    profile.update(driver='GTiff', dtype='float32', count=1, nodata=-9999, compress='deflate')
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output, 'w', **profile) as dst:
        dst.write(result, 1)
        dst.update_tags(method='AFSA-derived static similarity; no seasonal alignment', validation='experimental_unvalidated')
    return {'reference_values': refs, 'valid_cells': int(valid.sum()), 'minimum': float(combined[valid].min()), 'maximum': float(combined[valid].max())}
