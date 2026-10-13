import os
from pathlib import Path
import subprocess
import sys

VALID_MODES = {'run', 'release-validation', 'full'}

mode = os.environ.get('DS4_ROOTFS_TEST_MODE', 'run')
if mode == 'full':
    mode = 'release-validation'
if mode not in VALID_MODES:
    raise SystemExit('Invalid DS4_ROOTFS_TEST_MODE')
os.environ['DS4_ROOTFS_TEST_MODE'] = mode

pidfile=Path('/content/layered-worker.pid')
if pidfile.exists():
    pid=int(pidfile.read_text());command=Path('/proc')/str(pid)/'cmdline'
    if command.exists() and b'cpu_layered_test.py' in command.read_bytes():
        print('Worker already running:',pid)
        raise SystemExit(0)
assert not Path('/dev/nvidia0').exists(), 'CPU-only worker required'
auth=Path('/content/ghcr-auth');auth.mkdir(mode=0o700,exist_ok=True)
Path('/content/pull-auth.json').replace(auth/'config.json');auth.chmod(0o700);(auth/'config.json').chmod(0o600)
p=subprocess.Popen([sys.executable,'/content/cpu_layered_test.py'],stdout=open('/content/layered-worker.log','w'),stderr=subprocess.STDOUT,start_new_session=True)
pidfile.write_text(str(p.pid))
print('Started CPU-only worker:',p.pid,'mode:',mode)
