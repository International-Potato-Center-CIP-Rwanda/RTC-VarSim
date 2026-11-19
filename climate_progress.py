"""Summarize current-plan markers without reading or changing climate rasters.

Completion counts are processing status, not output verification or web readiness.
"""
import calendar
import datetime
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def summarize():
    """Count pending, running, failed and complete markers for the current plan signature; do not read or modify climate rasters."""
    plan = json.loads((BASE / 'data/africa-tiles.json').read_text())
    signature = hashlib.sha256((
        json.dumps(plan, sort_keys=True)
        + (BASE / 'data/africa-extraction-mask.geojson').read_text()
        + (BASE / 'data/africa-1991-2020-inventory.json').read_text()
    ).encode()).hexdigest()
    root = BASE / 'data/africa-jobs' / signature[:16]
    layers = []
    for variable in ('tas', 'pr'):
        for month in range(1, 13):
            counts = dict(complete=0, running=0, failed=0, pending=0)
            for tile in plan['tiles']:
                job_id = f"r{tile['row']}-c{tile['col']}-{variable}-{month:02d}"
                marker = root / (job_id + '.json')
                state = 'pending'
                if marker.exists():
                    job = json.loads(marker.read_text())
                    if job['id'] != job_id:
                        raise ValueError(f'Marker identity mismatch: {marker}')
                    state = job['status']
                if state not in counts:
                    raise ValueError(f'Unknown status {state}: {marker}')
                counts[state] += 1
            layers.append(dict(variable=variable, month=month,
                               expected=len(plan['tiles']), **counts))
    return dict(checked_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                signature=signature, layers=layers,
                note='Marker counts only. Run verify_climate_outputs.py for output checks. '
                     'Completed layers are not necessarily integrated into the platform.')


if __name__ == '__main__':
    report = summarize()
    target = BASE / 'data/climate-progress.json'
    temporary = target.with_suffix('.partial')
    temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
    temporary.replace(target)
    print('Variable  Month       Complete  Running  Failed  Pending')
    for row in report['layers']:
        print(f"{row['variable']:8}  {calendar.month_name[row['month']]:10}  "
              f"{row['complete']:3}/{row['expected']:<3}   {row['running']:7}  "
              f"{row['failed']:6}  {row['pending']:7}")
    print(report['note'])
