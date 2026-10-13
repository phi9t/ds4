#!/usr/bin/env python3
"""Write the pull-only GHCR auth file expected by the Colab CPU worker."""

import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import sys


def read_secret(args, parser):
    if args.token_env:
        token = os.environ.get(args.token_env)
        if not token:
            parser.error(f'environment variable {args.token_env!r} is empty')
        return token
    if args.token_stdin:
        token = sys.stdin.readline().rstrip('\n')
        if not token:
            parser.error('no token received on stdin')
        return token
    return getpass.getpass('GHCR pull token: ')


def read_username(args, parser):
    if args.username_env:
        username = os.environ.get(args.username_env)
        if not username:
            parser.error(f'environment variable {args.username_env!r} is empty')
        return username
    if args.username:
        return args.username
    return input('GHCR username: ')


def write_auth(output, registry, username, token, force=False):
    if output.is_symlink():
        raise ValueError('output must not be a symlink')
    if output.exists():
        if not force:
            raise FileExistsError(f'{output} already exists; pass --force to replace it')
        if output.is_dir():
            raise ValueError('output path is a directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {'auths': {registry: {
        'auth': base64.b64encode(f'{username}:{token}'.encode()).decode()
    }}}
    temporary = output.with_name(output.name + '.tmp')
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f'temporary auth path already exists: {temporary}')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream)
            stream.write('\n')
        os.replace(temporary, output)
        output.chmod(0o600)
    except Exception:
        try:
            temporary.unlink()
        finally:
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/content/pull-auth.json'),
                        help='auth file consumed by start_cpu_worker.py')
    parser.add_argument('--registry', default='ghcr.io')
    parser.add_argument('--username')
    parser.add_argument('--username-env')
    parser.add_argument('--token-env')
    parser.add_argument('--token-stdin', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()

    username = read_username(args, parser)
    token = read_secret(args, parser)
    try:
        write_auth(args.output, args.registry, username, token, args.force)
    except Exception as exc:
        raise SystemExit(f'error: {exc}') from exc
    print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
