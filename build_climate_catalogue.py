"""Build a preparation catalogue; never authorize web analysis from markers alone."""
import json
from pathlib import Path
from climate_progress import BASE, summarize


def build():
    """Index current-plan job markers and layer paths in a preparation catalogue; completion does not replace output verification."""
    progress = summarize()
    plan = json.loads((BASE / 'data/africa-tiles.json').read_text())
    root = BASE / 'data/africa-jobs' / progress['signature'][:16]
    layers = []
    for layer in progress['layers']:
        entries = []
        for tile in plan['tiles']:
            job_id = f"r{tile['row']}-c{tile['col']}-{layer['variable']}-{layer['month']:02d}"
            marker = root / (job_id + '.json')
            entry = dict(id=job_id, grid_window=tile, status='pending')
            if marker.exists():
                job = json.loads(marker.read_text())
                if (job.get('id') != job_id or job.get('tile') != tile
                        or job.get('variable') != layer['variable']
                        or job.get('month') != layer['month']):
                    raise ValueError(f'Incompatible marker: {job_id}')
                entry['status'] = job['status']
                if job['status'] == 'complete':
                    path = (Path(job['folder']) / 'africa-mean.tif').resolve()
                    relative = path.relative_to((BASE / 'data/climate-tiles').resolve())
                    entry.update(path='data/climate-tiles/' + relative.as_posix(),
                                 file_present=path.is_file(),
                                 recorded_sha256=job['output_sha256'],
                                 mask_sha256=job['mask_sha256'])
            entries.append(entry)
        layers.append(dict(variable=layer['variable'], month=layer['month'],
                           units='degrees Celsius' if layer['variable']=='tas' else 'mm/month',
                           tiles=entries))
    return dict(schema_version=1, generated_utc=progress['checked_utc'],
                plan_signature=progress['signature'], period='1991-2020',
                source='CHELSA monthly V2.1', analysis_enabled=False,
                verification='Not performed by this catalogue builder; hashes are copied from markers.',
                layers=layers)


if __name__ == '__main__':
    catalogue = build()
    target = BASE / 'data/climate-catalogue.json'
    temporary = target.with_suffix('.partial')
    temporary.write_text(json.dumps(catalogue, indent=2), encoding='utf-8')
    temporary.replace(target)
    tiles = [tile for layer in catalogue['layers'] for tile in layer['tiles']]
    print(json.dumps(dict(layers=len(catalogue['layers']), planned_tiles=len(tiles),
                          present_outputs=sum(t.get('file_present', False) for t in tiles),
                          analysis_enabled=catalogue['analysis_enabled'])))
