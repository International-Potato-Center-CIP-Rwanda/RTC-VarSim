"""Align local environmental inputs to CHELSA without altering their originals.

Run from any directory with the project Python environment. Source rasters are
cleaned block by block to avoid loading the full 30 m DEM into memory.
"""
import hashlib
import json
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

BASE = Path(__file__).resolve().parent
NODATA = -9999.0


def sha256(path):
    """Hash a local source file for provenance and integrity comparisons."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def harmonize(source, template, destination, method, scale=1.0, valid_range=None):
    """Average continuous values; use modal classes for categorical values.

    Does not fill missing input data or extrapolate outside their coverage.
    The output is additionally masked to the reference raster's valid domain.
    """
    with rasterio.open(template) as ref:
        profile = ref.profile.copy()
        profile.update(driver='GTiff', dtype='float32', count=1, nodata=NODATA, compress='deflate')
        domain = ref.read_masks(1) > 0
        grid = (ref.crs, ref.transform, ref.width, ref.height)
    rejected = 0
    with tempfile.TemporaryDirectory(prefix='afsa-harmonize-') as tmp:
        clean = Path(tmp) / 'clean.tif'
        with rasterio.open(source) as src:
            if src.crs is None or src.count != 1:
                raise ValueError('A georeferenced single-band source is required.')
            src_profile = src.profile.copy()
            src_profile.update(driver='GTiff', dtype='float32', count=1, nodata=NODATA, compress='deflate')
            with rasterio.open(clean, 'w', **src_profile) as dst:
                for _, window in src.block_windows(1):
                    raw = src.read(1, window=window, masked=True).astype('float32')
                    values = raw.filled(np.nan) * scale
                    valid = np.isfinite(values) & (values != NODATA * scale) & (values > -1e30)
                    if valid_range is not None:
                        valid &= (values >= valid_range[0]) & (values <= valid_range[1])
                    rejected += int((~valid & ~np.ma.getmaskarray(raw)).sum())
                    dst.write(np.where(valid, values, NODATA).astype('float32'), 1, window=window)
        output = np.full((grid[3], grid[2]), NODATA, dtype='float32')
        with rasterio.open(clean) as src:
            reproject(source=rasterio.band(src, 1), destination=output,
                      src_transform=src.transform, src_crs=src.crs, src_nodata=NODATA,
                      dst_transform=grid[1], dst_crs=grid[0], dst_nodata=NODATA,
                      resampling=method)
    output[~domain] = NODATA
    output[~np.isfinite(output)] = NODATA
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(destination, 'w', **profile) as dst:
        dst.write(output, 1)
        dst.update_tags(source=str(source), resampling=method.name, source_scale=str(scale),
                        reference_grid=str(template), status='harmonized; not an agronomic validation')
    valid = output != NODATA
    return {'valid_cells': int(valid.sum()), 'missing_in_climate_domain': int((domain & ~valid).sum()),
            'climate_domain_cells': int(domain.sum()), 'extra_invalid_source_pixels_masked': rejected,
            'minimum': float(output[valid].min()) if valid.any() else None,
            'maximum': float(output[valid].max()) if valid.any() else None,
            'unique_values': np.unique(output[valid]).tolist() if method == Resampling.mode else None}


def main():
    """Write aligned pilot-layer copies and a provenance report; leave the original source rasters unchanged."""
    docs = Path.home() / 'Documents'
    downloads = Path.home() / 'Downloads'
    template = docs / 'Rwanda_CHELSA_bio01_1981-2010.tif'
    target = BASE / 'data' / 'harmonized'
    specs = [
        ('ph', docs/'Rwanda_SoilGrids_pH_raw_0-5cm.tif', 'pH', Resampling.average, .1, (1,14),
         'SoilGrids pH water, 0–5 cm, as described in supplied progress report. Source values divided by 10; zeros and values outside 1–14 masked as invalid soil pH.'),
        ('texture', docs/'Rwanda_USDA_soil_texture..tif', 'USDA class code', Resampling.mode, 1, (1,12),
         'Categorical raster supplied by user. Modal class per target cell; class-code legend still needs confirmation.'),
        ('elevation', downloads/'Rwanda_DEM_UTM35S_30m_clean.tif', 'm', Resampling.average, 1, None,
         'User-prepared DEM; original elevation dataset provenance remains unconfirmed.'),
        ('slope', docs/'Rwanda_slope_percent_30m.tif', '%', Resampling.average, 1, (0,1e20),
         'Mean of existing percent-slope values; not slope recomputed from the aggregated DEM. Units follow supplied progress report and filename.')
    ]
    records=[]
    for key,source,unit,method,scale,valid_range,note in specs:
        path=target/f'Rwanda_{key}_CHELSA_grid.tif'
        before=sha256(source)
        stats=harmonize(source,template,path,method,scale,valid_range)
        if before != sha256(source):
            raise RuntimeError('Source changed during harmonization.')
        record={'id':key,'source':str(source),'source_sha256':before,'path':str(path),
                'unit':unit,'resampling':method.name,'scale':scale,'note':note,**stats}
        records.append(record)
        print(json.dumps(record),flush=True)
    with rasterio.open(template) as ref:
        common=ref.read_masks(1)>0
        profile=ref.profile.copy()
        reference_grid=(ref.crs,ref.transform,ref.width,ref.height)
    for rec in records:
        with rasterio.open(rec['path']) as src:
            if (src.crs,src.transform,src.width,src.height)!=reference_grid:
                raise RuntimeError('Output grid mismatch.')
            common &= src.read_masks(1)>0
    profile.update(driver='GTiff',dtype='uint8',nodata=0,count=1,compress='deflate')
    with rasterio.open(target/'common_valid_mask.tif','w',**profile) as dst:
        dst.write(common.astype('uint8'),1)
    report={'template':str(template),'template_sha256':sha256(template),
            'grid':{'crs':str(reference_grid[0]),'transform':list(reference_grid[1]),'width':reference_grid[2],'height':reference_grid[3]},
            'layers':records,'common_valid_cells':int(common.sum()),
            'limitations':['Harmonization does not validate source agronomic assumptions.',
                          'Average uses valid contributing source cells; partially covered target cells are retained without extrapolation.',
                          'No missing-data imputation; coverage differs by layer.',
                          'No variable weights or crop tolerance assumptions were introduced.']}
    (target/'manifest.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Harmonisation des couches Rwanda','',
           'Copies alignées sur la grille CHELSA : 245 × 216 cellules, EPSG:4326, environ 1 km. Les originaux sont inchangés (empreintes contrôlées).','',
           '| Variable | Méthode | Cellules valides | Manquantes dans le domaine climatique | Min–max |',
           '|---|---|---:|---:|---|']
    for r in records:
        lines.append(f"| {r['id']} ({r['unit']}) | {r['resampling']} | {r['valid_cells']} | {r['missing_in_climate_domain']} | {r['minimum']:.3f}–{r['maximum']:.3f} |")
    lines+=['',f"Couverture commune aux quatre couches et au masque climatique : **{int(common.sum())} cellules**.",'',
            'Le pH brut a été divisé par 10. Les zéros ont été exclus, car ils ne représentent pas une valeur exploitable de pH du sol. Les anciennes valeurs sentinelles non déclarées ont aussi été masquées.',
            '', 'La texture utilise la classe majoritaire (mode), sans calculer une moyenne entre codes de catégories. Le pH, l’altitude et la pente utilisent une moyenne des pixels valides qui contribuent à chaque cellule cible.',
            '', 'La pente est une moyenne des pentes locales en pourcentage ; ce n’est pas la pente d’un relief recalculé à 1 km. La légende des codes de texture et la provenance initiale du DEM restent à documenter.',
            '', 'Aucune donnée manquante n’a été inventée. Les cellules partiellement couvertes utilisent leurs contributions valides ; les couvertures exactes sont consignées dans manifest.json. L’alignement technique ne valide pas l’aptitude agronomique ni les poids du futur modèle.']
    (BASE/'HARMONISATION.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
