"""Explicit, resumable continental job queue. Defaults to planning, not downloading."""
import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import shape, box, mapping
from shapely.strtree import STRtree
from extract_climate_tile import run, BASE
import climate_access

JOB_ATTEMPTS = int(os.environ.get('AFSA_JOB_ATTEMPTS', 6))
NETWORK_WAIT_SECONDS = int(os.environ.get('AFSA_NETWORK_WAIT_SECONDS', 4 * 3600))
NETWORK_POLL_SECONDS = int(os.environ.get('AFSA_NETWORK_POLL_SECONDS', 60))

def save_json(path, value):
    """Atomically replace a JSON job marker through a partial file so interrupted writes do not publish an incomplete marker."""
    temp=path.with_suffix('.partial')
    temp.write_text(json.dumps(value,indent=2),encoding='utf-8')
    temp.replace(path)

def mask_output(folder, mask_path):
    """Apply the African land geometry mask to a completed tile and write africa-mean.tif with source and mask checksums."""
    features=json.loads(mask_path.read_text())['features']
    geometries=[shape(f['geometry']) for f in features]
    tree=STRtree(geometries)
    with rasterio.open(folder/'mean.tif') as src:
        selected=tree.query(box(*src.bounds),predicate='intersects')
        shapes=[mapping(geometries[i]) for i in selected]
        land=geometry_mask(shapes,out_shape=src.shape,transform=src.transform,invert=True) if shapes else np.zeros(src.shape,dtype=bool)
        data=src.read(1,masked=True)
        valid=land & ~np.ma.getmaskarray(data)
        output=np.where(valid,data.data,-9999).astype('float32')
        profile=src.profile
        tags=src.tags()
    target=folder/'africa-mean.tif'
    temp=folder/'africa-mean.partial.tif'
    with rasterio.open(temp,'w',**profile) as dest:
        dest.write(output,1)
        dest.update_tags(**{**tags,'scope':'African land mask, one tile only','mask_rule':'pixel centre'})
    temp.replace(target)
    return dict(valid_land_cells=int(valid.sum()),land_cells=int(land.sum()),
                mask_sha256=hashlib.sha256(mask_path.read_bytes()).hexdigest(),
                output_sha256=hashlib.sha256(target.read_bytes()).hexdigest())

class StopRequested(Exception):
    """STOP sentinel seen while a job was waiting for the network: a clean stop, not a failure."""

def stop_requested():
    """Return whether the local STOP sentinel requests a clean processing stop."""
    return (BASE/'data/background/STOP').exists()

def wait_for_source(item, deadline, *, poll=None, sleep=time.sleep, clock=time.monotonic):
    """Wait until `item` answers a valid 1-byte range request, strictly before `deadline`.

    `deadline` is a time.monotonic() value. It is checked before every probe and again
    after it: a probe that succeeds only after the deadline does NOT permit a retry.
    Overshoot is bounded by one in-flight probe (HTTP timeout, AFSA_HTTP_TIMEOUT, 30 s by default).
    Returns True when reachable in time; False when the budget is spent or the server
    answers with an integrity problem (waiting would not help). Raises StopRequested if
    the STOP sentinel appears, including just after a successful probe.
    """
    poll = NETWORK_POLL_SECONDS if poll is None else poll
    while True:
        if stop_requested():
            raise StopRequested()
        if clock() >= deadline:
            return False
        state = climate_access.source_state(item['url'], item['bytes'], item.get('etag'))
        if stop_requested():
            raise StopRequested()
        if clock() >= deadline:
            return False
        if state == climate_access.REACHABLE:
            return True
        if state == climate_access.INTEGRITY:
            print(json.dumps(dict(event='source_integrity_problem', url=item['url'])), flush=True)
            return False
        remaining = deadline - clock()
        print(f'Network unavailable; waiting up to {min(poll, remaining):.0f}s ({remaining:.0f}s of network budget left)', flush=True)
        sleep(min(poll, remaining))

def is_network_failure(error, giveups_before, integrity_before):
    """Retry only if network retries were exhausted during this attempt AND no permanent
    data/integrity error was recorded. With parallel year reads both can happen in one
    attempt; the integrity error then wins, so a data problem is never masked as network."""
    if isinstance(error, (ValueError, climate_access.SourceIntegrityError)):
        return False
    stats = climate_access.STATS
    return stats.network_giveups > giveups_before and stats.integrity_errors == integrity_before

def execute_job(job, mask, probe_item, *, attempts=None, runner=None, masker=None, waiter=None,
                clock=time.monotonic, wait_budget=None):
    """Run one job with bounded network retries.

    Bounds per job:
    - at most `attempts` attempts (AFSA_JOB_ATTEMPTS);
    - a CUMULATIVE network-wait budget (AFSA_NETWORK_WAIT_SECONDS): only time spent in
      wait_for_source (probes + sleeps) is charged. Normal download/compute time is not.
      Each wait gets deadline = now + remaining budget; the time it actually took is then
      subtracted. No retry starts once the budget is spent.
    Not charged to the budget (bounded separately): the reader's own in-attempt retries
    (AFSA_RANGE_ATTEMPTS, ~4.5 min per failing read) and one in-flight probe of overshoot.
    Data/identity errors are raised immediately, exactly as before. Completed year
    extracts are reused on retry, so a retry repeats only unfinished downloads.
    """
    attempts = JOB_ATTEMPTS if attempts is None else attempts
    runner = runner or run
    masker = masker or mask_output
    waiter = waiter or wait_for_source
    budget = float(NETWORK_WAIT_SECONDS if wait_budget is None else wait_budget)
    for attempt in range(1, attempts + 1):
        if attempt > 1 and stop_requested():
            raise StopRequested()
        stats = climate_access.STATS
        giveups, integrity = stats.network_giveups, stats.integrity_errors
        before = stats.snapshot()
        started = time.monotonic()
        try:
            folder = runner(job['variable'], job['month'], None, None, grid_window=job['tile'])
            result = masker(folder, mask)
        except Exception as error:
            if not is_network_failure(error, giveups, integrity) or attempt == attempts or budget <= 0:
                raise
            print(json.dumps(dict(event='network_retry', job=job['id'], attempt=attempt,
                                  wait_budget_left_s=round(budget), error=str(error)[:300])), flush=True)
            source = stats.last_failed_source or probe_item   # prefer the source that actually failed
            wait_started = clock()
            ok = waiter(source, wait_started + budget)
            budget -= clock() - wait_started
            if not ok or budget <= 0:
                raise
            continue
        after = stats.snapshot()
        print(json.dumps(dict(event='job_metrics', job=job['id'], attempt=attempt,
                              seconds=round(time.monotonic() - started, 1),
                              **{k: after[k] - before[k] for k in after})), flush=True)
        return folder, result

def main():
    """Plan jobs by default; execute only the requested number, resuming markers and respecting STOP and bounded network waits."""
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute',type=int,default=0,help='Maximum pending jobs to execute now')
    args=parser.parse_args()
    if args.execute < 0: raise ValueError('Invalid execution limit')
    plan=json.loads((BASE/'data/africa-tiles.json').read_text())
    mask=BASE/'data/africa-extraction-mask.geojson'
    inventory=BASE/'data/africa-1991-2020-inventory.json'
    signature=hashlib.sha256((json.dumps(plan,sort_keys=True)+mask.read_text()+inventory.read_text()).encode()).hexdigest()
    root=BASE/'data/africa-jobs'/signature[:16]
    root.mkdir(parents=True,exist_ok=True)
    # Neighbouring spatial jobs share the same source files, improving block reuse.
    jobs=[dict(id=f"r{t['row']}-c{t['col']}-{v}-{m:02d}",tile=t,variable=v,month=m) for v in ('tas','pr') for m in range(1,13) for t in plan['tiles']]
    save_json(root/'plan.json',dict(signature=signature,jobs=jobs))
    pending=[]
    for job in jobs:
        marker=root/(job['id']+'.json')
        if marker.exists():
            done=json.loads(marker.read_text())
            if done.get('status')=='complete' and done.get('folder'):
                output=Path(done['folder'])/'africa-mean.tif'
                if output.exists() and hashlib.sha256(output.read_bytes()).hexdigest()==done.get('output_sha256'): continue
        pending.append(job)
    print(json.dumps(dict(total=len(jobs),complete=len(jobs)-len(pending),pending=len(pending),free_disk_bytes=shutil.disk_usage(BASE).free)),flush=True)
    probe_item=json.loads(inventory.read_text())['files'][0]
    for job in pending[:args.execute]:
        if stop_requested():
            print('STOP requested; stopping before next job',flush=True)
            break
        if shutil.disk_usage(BASE).free < 20*1024**3: raise RuntimeError('Less than 20 GiB free; stopping before next job')
        marker=root/(job['id']+'.json')
        save_json(marker,dict(**job,status='running'))
        try:
            folder,result=execute_job(job,mask,probe_item)
            save_json(marker,dict(**job,**result,folder=str(folder),status='complete'))
        except StopRequested:
            # Clean stop during a network wait: the job returns to 'pending' (no marker),
            # exit code 0, so the supervisor records 'stopped', not 'failed'.
            marker.unlink(missing_ok=True)
            print('STOP requested during network wait; job left pending',flush=True)
            break
        except Exception as error:
            save_json(marker,dict(**job,status='failed',error=str(error)))
            raise

if __name__=='__main__': main()
