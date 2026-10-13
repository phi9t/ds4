#!/usr/bin/env python3
"""Start the current DS4 Colab worker in the background."""

import os
from pathlib import Path
import subprocess
import sys

mode = os.environ.get('DS4_CURRENT_COLAB_MODE', 'cpu')
if mode == 'run':
    mode = 'cpu'
if mode not in {'cpu', 'gpu'}:
    raise SystemExit('Invalid DS4_CURRENT_COLAB_MODE')
os.environ['DS4_CURRENT_COLAB_MODE'] = mode

pidfile = Path('/content/current-worker.pid')
if pidfile.exists():
    pid = int(pidfile.read_text())
    command = Path('/proc') / str(pid) / 'cmdline'
    if command.exists() and b'current_colab_worker.py' in command.read_bytes():
        print('Current worker already running:', pid)
        raise SystemExit(0)

auth = Path('/content/ghcr-auth')
auth.mkdir(mode=0o700, exist_ok=True)
Path('/content/pull-auth.json').replace(auth / 'config.json')
auth.chmod(0o700)
(auth / 'config.json').chmod(0o600)
log = open('/content/current-worker.log', 'w')
process = subprocess.Popen(
    [sys.executable, '/content/current_colab_worker.py'],
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
pidfile.write_text(str(process.pid))
print('Started current Colab worker:', process.pid, 'mode:', mode)
