#!/usr/bin/env python3
"""Create the flat upload archive for the DS4 CPU Colab OCI recipe."""

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
DEFAULT_RELEASE = REPO_ROOT / 'docs/rootfs/colab-oci/evidence/release.json'
TOP_LEVEL_FILES = (
    'launch_insula.py',
    'pack_verified_layers.py',
    'write_pull_auth.py',
)
REQUIRED_LAYERED_FILES = (
    'colab_safe.py',
    'cpu_layered_test.py',
    'prepare_layers.py',
    'restore_layers.py',
    'start_cpu_worker.py',
)


def validate_release(path):
    release = json.loads(path.read_text())
    images = release.get('images')
    if not isinstance(images, dict):
        raise ValueError('release record must contain an images object')
    for name in ('runtime', 'build', 'seed'):
        image = images.get(name)
        if not isinstance(image, dict):
            raise ValueError(f'release record is missing image {name!r}')
        if not image.get('reference'):
            raise ValueError(f'release image {name!r} is missing a reference')
        if not image.get('layers'):
            raise ValueError(f'release image {name!r} is missing layers')
    return release


def copy_checked(source, destination):
    if not source.is_file():
        raise FileNotFoundError(source)
    shutil.copy2(source, destination)


def write_readme(destination, release):
    package = release.get('package', 'unknown package')
    destination.write_text(
        f"""DS4 CPU Colab OCI recipe bundle

This archive is for the CPU-only transport/run proof for {package}. Run it on a
Colab CPU Standard runtime. Do not select a GPU runtime for this proof;
start_cpu_worker.py intentionally refuses /dev/nvidia0.

The default worker mode is run: restore the build rootfs, enter it through the
Insula-style launcher, and run the prebuilt DS4 payload from that rootfs. It
does not rebuild on the Colab host. Use DS4_ROOTFS_TEST_MODE=release-validation
only for the slower source rebuild and offline OCI composition proof.

Colab cells:

  !tar -xzf /content/ds4-colab-upload.tgz -C /content

  import getpass, subprocess, sys
  user = input("GHCR username: ")
  token = getpass.getpass("GHCR pull token: ")
  subprocess.run(
      [sys.executable, "/content/write_pull_auth.py",
       "--username", user, "--token-stdin"],
      input=token + "\\n", text=True, check=True)

  import os, subprocess, sys
  os.environ["DS4_ROOTFS_TEST_RUN"] = "r4"
  os.environ["DS4_ROOTFS_TEST_MODE"] = "run"
  subprocess.run([sys.executable, "/content/start_cpu_worker.py"], check=True)

  !tail -f /content/layered-worker.log
  !cat /content/layered-status-r4.json

Outputs:

  /content/layered-status-r4.json
  /content/layered-results-r4.zip

Use a fresh lowercase/digit/hyphen run name for another measurement.
The worker consumes /content/pull-auth.json, moves it into a private
/content/ghcr-auth/config.json directory, and removes that auth directory when
the run finishes or fails.
""")


def build_bundle(output, release_path, crane_path=None):
    release = validate_release(release_path)
    if output.is_symlink():
        raise ValueError('output must not be a symlink')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ds4-colab-upload-',
                                     dir=str(output.parent)) as temporary:
        staging = Path(temporary)
        for name in TOP_LEVEL_FILES:
            copy_checked(PROFILE / name, staging / name)
        layered = PROFILE / 'layered'
        for name in REQUIRED_LAYERED_FILES:
            copy_checked(layered / name, staging / name)
        copy_checked(release_path, staging / 'release.json')
        write_readme(staging / 'README-COLAB.txt', release)
        crane_destination = staging / 'crane'
        if crane_path is None:
            acquired = subprocess.run(
                [sys.executable, str(PROFILE / 'acquire_crane.py'),
                 '--output', str(crane_destination)],
                capture_output=True, text=True)
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
    parser.add_argument('--output', type=Path, default=Path('/tmp/ds4-colab-upload.tgz'),
                        help='archive to create; default: /tmp/ds4-colab-upload.tgz')
    parser.add_argument('--release', type=Path, default=DEFAULT_RELEASE,
                        help='release record to include as /content/release.json')
    parser.add_argument('--crane', type=Path,
                        help='use an existing Linux amd64 crane binary instead of downloading one')
    parser.add_argument('--force', action='store_true',
                        help='replace an existing output archive')
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
    print('Upload this archive to a Colab CPU Standard runtime and follow README-COLAB.txt.')


if __name__ == '__main__':
    main()
