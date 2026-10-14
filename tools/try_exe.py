"""Run a candidate exe and report whether it starts (GUI appears) or exits early.

Usage: py313 try_exe.py <exe> [--silent] [--work <dir>] [--wait <sec>]
"""
import os
import subprocess
import sys
import tempfile
import time

exe = sys.argv[1]
extra = [a for a in sys.argv[2:] if not a.startswith('--')]
work = tempfile.mkdtemp(prefix='try-exe-')
wait = 20
for a in sys.argv[2:]:
    if a.startswith('--work='):
        work = a.split('=', 1)[1]
    elif a.startswith('--wait='):
        wait = int(a.split('=', 1)[1])
os.makedirs(work, exist_ok=True)

proc = subprocess.Popen([exe] + extra, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
t0 = time.time()
while time.time() - t0 < wait:
    if proc.poll() is not None:
        out, err = proc.communicate(timeout=10)
        print('exited early after %.1fs rc=%s' % (time.time() - t0, proc.returncode))
        print('stdout:', (out or b'').decode('utf-8', 'ignore')[-500:])
        print('stderr:', (err or b'').decode('utf-8', 'ignore')[-800:])
        sys.exit(1)
    time.sleep(0.4)
print('still running after %ds -> startup OK (GUI up)' % wait)
proc.kill()
