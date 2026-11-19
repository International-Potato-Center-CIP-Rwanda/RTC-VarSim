"""Single-instance supervised climate worker with durable status and log files."""
import datetime
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import sys

BASE=Path(__file__).resolve().parent
CONTROL=BASE/'data/background'

def write_status(status, **details):
    """Atomically record the local climate-worker status and supplied diagnostic fields."""
    target=CONTROL/'status.json'
    temp=CONTROL/'status.partial'
    temp.write_text(json.dumps(dict(status=status,pid=os.getpid(),updated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),**details),indent=2))
    temp.replace(target)

def main():
    """Run the optional Windows climate-queue supervisor with a lock, status and STOP sentinel; this is not a Django server."""
    CONTROL.mkdir(parents=True,exist_ok=True)
    with (CONTROL/'worker.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1): lock.write(b'0'); lock.flush()
        lock.seek(0)
        try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            print('An existing worker already holds the lock.',flush=True)
            return 2
        try:
            if (CONTROL/'STOP').exists():
                write_status('stopped',reason='STOP file is present; no job started')
                return 0
            with (CONTROL/'worker.log').open('a',encoding='utf-8',buffering=1) as log:
                log.write('\nStarting resumable continental processing '+datetime.datetime.now(datetime.timezone.utc).isoformat()+'\n')
                child=subprocess.Popen([sys.executable,'-u',str(BASE/'africa_climate_jobs.py'),'--execute','4848'],cwd=BASE,stdout=log,stderr=subprocess.STDOUT)
                write_status('running',worker_pid=child.pid,log=str(CONTROL/'worker.log'))
                code=child.wait()
                if code:
                    write_status('failed',exit_code=code,log=str(CONTROL/'worker.log'))
                    return code
                if (CONTROL/'STOP').exists():
                    write_status('stopped',reason='Stopped at a job boundary')
                    return 0
                verify=subprocess.run([sys.executable,str(BASE/'verify_climate_outputs.py')],cwd=BASE,stdout=log,stderr=subprocess.STDOUT)
                if verify.returncode:
                    write_status('verification_failed',exit_code=verify.returncode)
                    return verify.returncode
                report=json.loads((BASE/'data/climate-output-verification.json').read_text())
                complete=report['verified_completed_outputs']==4848 and report['failed_jobs']==0 and report['running_jobs']==0
                write_status('complete' if complete else 'incomplete',verification=report)
                return 0 if complete else 1
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

if __name__=='__main__': sys.exit(main())
