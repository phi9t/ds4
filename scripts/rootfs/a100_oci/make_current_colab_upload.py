#!/usr/bin/env python3
"""Create the flat Colab upload archive for the current DS4 rootfs image."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

PROFILE = Path(__file__).resolve().parent
REPO_ROOT = PROFILE.parents[2]
TOP_LEVEL_FILES = (
    'launch_insula.py',
    'pack_verified_layers.py',
    'write_pull_auth.py',
)
CURRENT_FILES = (
    'current_colab_worker.py',
    'start_current_worker.py',
)
LAYERED_FILES = (
    'restore_layers.py',
)


def copy_checked(source, destination):
    if not source.is_file():
        raise FileNotFoundError(source)
    shutil.copy2(source, destination)


def validate_release(path):
    release = json.loads(path.read_text())
    image = release.get('images', {}).get('current')
    if not isinstance(image, dict):
        raise ValueError('release record must contain images.current')
    if not image.get('reference') or '@sha256:' not in image['reference']:
        raise ValueError('current image reference must be digest-pinned')
    if not image.get('layers'):
        raise ValueError('current image is missing layers')
    if not image.get('bundle_manifest_sha256'):
        raise ValueError('current image is missing bundle_manifest_sha256')
    return release


def write_readme(destination, release):
    reference = release['images']['current']['reference']
    arch = release['candidate']['bundle_manifest']['cuda_arch']
    destination.write_text(f"""DS4 current Colab rootfs bundle

This archive restores and runs the current DS4 Bazel/CUDA rootfs image:

  {reference}

The packaged DS4 binaries were built for {arch}. CPU mode is the admission gate:
it restores the rootfs, enters it through bwrap, runs packaged binaries and
toolchain/read-only checks, and does not rebuild on the Colab host. GPU mode
requires an A100 runtime and optionally runs a bounded generation smoke if
/content/weights/ds4flash.gguf is present.

Colab cells:

  !tar -xzf /content/ds4-current-colab-upload.tgz -C /content

  import getpass, subprocess, sys
  user = input("GHCR username: ")
  token = getpass.getpass("GHCR pull token: ")
  subprocess.run(
      [sys.executable, "/content/write_pull_auth.py",
       "--username", user, "--token-stdin"],
      input=token + "\\n", text=True, check=True)

  import os, subprocess, sys
  os.environ["DS4_CURRENT_COLAB_RUN"] = "cpu1"
  os.environ["DS4_CURRENT_COLAB_MODE"] = "cpu"
  subprocess.run([sys.executable, "/content/start_current_worker.py"], check=True)

  !tail -f /content/current-worker.log
  !cat /content/current-status-cpu1.json

For A100, use a fresh GPU runtime, stage weights under /content/weights if a
generation smoke is desired, set DS4_CURRENT_COLAB_MODE=gpu, and use a fresh
run name. The worker consumes /content/pull-auth.json, moves it into a private
/content/ghcr-auth/config.json directory, and removes registry auth after
restore.
""")


def build_bundle(output, release_path, crane_path=None):
    release = validate_release(release_path)
    if output.is_symlink():
        raise ValueError('output must not be a symlink')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ds4-current-colab-upload-',
                                     dir=str(output.parent)) as temporary:
        staging = Path(temporary)
        for name in TOP_LEVEL_FILES:
            copy_checked(PROFILE / name, staging / name)
        for name in CURRENT_FILES:
            copy_checked(PROFILE / name, staging / name)
        for name in LAYERED_FILES:
            copy_checked(PROFILE / 'layered' / name, staging / name)
        copy_checked(release_path, staging / 'release.json')
        write_readme(staging / 'README-COLAB.txt', release)
        crane_destination = staging / 'crane'
        if crane_path is None:
            acquired = subprocess.run(
                [sys.executable, str(PROFILE / 'acquire_crane.py'),
                 '--output', str(crane_destination)],
                capture_output=True,
                text=True,
            )
            if acquired.returncode != 0:
                raise RuntimeError('crane acquisition failed: ' +
                                   (acquired.stderr or acquired.stdout).strip())
        else:
            copy_checked(crane_path, crane_destination)
            crane_destination.chmod(crane_destination.stat().st_mode | 0o755)
        with tarfile.open(output, 'w:gz') as archive:
            for path in sorted(staging.iterdir(), key=lambda item: item.name):
                archive.add(path, arcname=path.name, recursive=False)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/ds4-current-colab-upload.tgz'))
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--crane', type=Path)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()

    if args.output.exists():
        if not args.force:
            parser.error(f'{args.output} already exists; pass --force to replace it')
        if args.output.is_dir():
            parser.error('output path is a directory')
        args.output.unlink()
    elif args.output.is_symlink():
        parser.error('output must not be a symlink')

    try:
        output = build_bundle(args.output, args.release, args.crane)
    except Exception as exc:
        raise SystemExit(f'error: {exc}') from exc
    print(output)
    print('Upload this archive to Colab and follow README-COLAB.txt.')


if __name__ == '__main__':
    main()
