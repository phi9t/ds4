#!/usr/bin/env python3
"""Upload pull-only GHCR auth to a prepared Colab CPU OCI session."""

import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def read_username(args, parser):
    if args.username_env:
        username = os.environ.get(args.username_env)
        if not username:
            parser.error(f'environment variable {args.username_env!r} is empty')
        return username
    if args.username:
        return args.username
    return input('GHCR username: ')


def read_token(args, parser):
    if args.token_env:
        token = os.environ.get(args.token_env)
        if not token:
            parser.error(f'environment variable {args.token_env!r} is empty')
        return token
    if args.token_file:
        token = args.token_file.read_text().strip()
        if not token:
            parser.error(f'token file {args.token_file} is empty')
        return token
    if args.token_stdin:
        token = sys.stdin.readline().rstrip('\n')
        if not token:
            parser.error('no token received on stdin')
        return token
    return getpass.getpass('GHCR pull token: ')


def auth_payload(registry, username, token):
    return {'auths': {registry: {
        'auth': base64.b64encode(f'{username}:{token}'.encode()).decode()
    }}}


def write_auth_file(output, payload, force=False):
    if output.is_symlink():
        raise ValueError('auth file path must not be a symlink')
    if output.exists():
        if not force:
            raise FileExistsError(f'{output} already exists; pass --force to replace it')
        if output.is_dir():
            raise ValueError('auth file path is a directory')
        output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(payload, stream)
        stream.write('\n')
    output.chmod(0o600)


def run_checked(command, *, input_text=None, timeout=30):
    result = subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f'command failed: {command!r}\n{detail}')
    output = (result.stdout or result.stderr).strip()
    if output:
        print(output)


def verify_remote_auth(args):
    code = f"""
import json
from pathlib import Path

path = Path({args.remote_output!r})
registry = {args.registry!r}
if not path.exists():
    raise SystemExit(f'missing remote auth file: {{path}}')
path.chmod(0o600)
data = json.loads(path.read_text())
if registry not in data.get('auths', {{}}):
    raise SystemExit(f'missing auth entry for {{registry}}')
mode = path.stat().st_mode & 0o777
if mode != 0o600:
    raise SystemExit(f'unexpected remote auth mode: {{oct(mode)}}')
print(f'remote auth ready: {{path}} mode={{oct(mode)}} bytes={{path.stat().st_size}}')
"""
    run_checked([args.colab, 'exec', '-s', args.session, '--timeout', '30'],
                input_text=code)


def start_worker(args):
    if not re.fullmatch(r'[a-z0-9-]+', args.run_name):
        raise ValueError('run name must contain only lowercase letters, digits, and hyphens')
    if args.mode == 'full':
        args.mode = 'release-validation'
    code = f"""
import os
import subprocess
import sys

os.environ['DS4_ROOTFS_TEST_RUN'] = {args.run_name!r}
os.environ['DS4_ROOTFS_TEST_MODE'] = {args.mode!r}
subprocess.run([sys.executable, '/content/start_cpu_worker.py'], check=True)
"""
    run_checked([args.colab, 'exec', '-s', args.session, '--timeout', '60'],
                input_text=code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', '-s', default='ds4-cpu-oci',
                        help='Colab session name; default: ds4-cpu-oci')
    parser.add_argument('--colab', default=os.environ.get('COLAB_BIN', 'colab'),
                        help='colab CLI executable')
    parser.add_argument('--registry', default='ghcr.io')
    parser.add_argument('--remote-output', default='/content/pull-auth.json')
    parser.add_argument('--username')
    parser.add_argument('--username-env')
    parser.add_argument('--token-env')
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--token-stdin', action='store_true')
    parser.add_argument('--local-output', type=Path,
                        help='write the auth JSON locally and do not call colab')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--start-worker', action='store_true',
                        help='start /content/start_cpu_worker.py after auth upload')
    parser.add_argument('--run-name', default='r4',
                        help='DS4_ROOTFS_TEST_RUN value when --start-worker is used')
    parser.add_argument('--mode', choices=('run', 'release-validation', 'full'), default='run',
                        help='worker mode for --start-worker; run skips remote rebuilds')
    args = parser.parse_args()

    if args.local_output is None and shutil.which(args.colab) is None:
        parser.error(f'colab CLI not found: {args.colab}')

    username = read_username(args, parser)
    token = read_token(args, parser)
    payload = auth_payload(args.registry, username, token)

    try:
        if args.local_output is not None:
            write_auth_file(args.local_output, payload, args.force)
            print(f'wrote local auth file: {args.local_output}')
            return
        with tempfile.TemporaryDirectory(prefix='ds4-colab-auth-') as temporary:
            auth_file = Path(temporary) / 'pull-auth.json'
            write_auth_file(auth_file, payload)
            run_checked([args.colab, 'upload', '-s', args.session,
                         str(auth_file), args.remote_output])
        verify_remote_auth(args)
        if args.start_worker:
            start_worker(args)
    except Exception as exc:
        raise SystemExit(f'error: {exc}') from exc


if __name__ == '__main__':
    main()
