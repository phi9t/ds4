#!/usr/bin/env python3
"""Build DS4 for Colab A100 and import a current executable rootfs image."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import time

PROFILE = Path(__file__).resolve().parent
REPO_ROOT = PROFILE.parents[2]
APPS = ('ds4', 'ds4-server', 'ds4-bench', 'ds4-eval', 'ds4-agent')


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, **kwargs)


def output(command):
    return subprocess.check_output(command, text=True, cwd=REPO_ROOT).strip()


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def parse_contract(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key] = value.strip().strip('"')
    return values


def ensure_repo_path(path, label):
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError(f'{label} must live under {REPO_ROOT}') from exc
    if any(part == '..' for part in relative.parts):
        raise ValueError(f'{label} must not escape the repository')
    return resolved, relative


def git_value(*args):
    return output(['git', *args])


def tracked_git_dirty():
    unstaged = subprocess.run(['git', 'diff', '--quiet'], cwd=REPO_ROOT)
    staged = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=REPO_ROOT)
    return unstaged.returncode != 0 or staged.returncode != 0


def stage_binaries(run_dir, bazel_config):
    stage = run_dir / 'staged-binaries'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    _, stage_rel = ensure_repo_path(stage, 'binary stage')
    stage_sandbox = '/workspace/ds4/' + str(stage_rel)
    targets = [f'//:{app}' for app in APPS]
    config = shlex.quote(bazel_config)
    script = f"""
set -euo pipefail
cd /workspace/ds4
bazel build --config={config} {' '.join(targets)}
mkdir -p {stage_sandbox}
for app in {' '.join(APPS)}; do
  cp -f "bazel-bin/${{app}}" "{stage_sandbox}/${{app}}"
  chmod 0755 "{stage_sandbox}/${{app}}"
done
"{stage_sandbox}/ds4" --build-id > "{stage_sandbox}/ds4.build-id"
"{stage_sandbox}/ds4-server" --build-id > "{stage_sandbox}/ds4-server.build-id"
"""
    run([str(REPO_ROOT / 'scripts/rootfs/enter_rootfs.sh'), '--', '/bin/bash', '-lc', script])
    return stage


def write_overlay(run_dir, stage, args, rootfs):
    overlay = run_dir / 'overlay'
    if overlay.exists():
        shutil.rmtree(overlay)
    opt = overlay / 'opt/ds4'
    bindir = opt / 'bin'
    if (rootfs / 'opt/ds4').is_dir():
        shutil.copytree(rootfs / 'opt/ds4', opt, symlinks=True)
    bindir.mkdir(parents=True, exist_ok=True)
    for mountpoint in ('work', 'weights', 'outputs'):
        (overlay / mountpoint).mkdir()
    binary_hashes = {}
    for app in APPS:
        source = stage / app
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, bindir / app)
        (bindir / app).chmod(0o755)
        binary_hashes[f'/opt/ds4/bin/{app}'] = sha256(bindir / app)

    contract = parse_contract(REPO_ROOT / 'scripts/rootfs/contract.env')
    rootfs_identity = output([
        'bash', '-lc',
        'source scripts/rootfs/rootfs_target.sh; rootfs_contract_identity',
    ])
    build_ids = {
        'ds4': (stage / 'ds4.build-id').read_text().strip(),
        'ds4-server': (stage / 'ds4-server.build-id').read_text().strip(),
    }
    for name, build_id in build_ids.items():
        if 'backend=cuda' not in build_id or f'arch={args.expected_arch}' not in build_id:
            raise ValueError(f'{name} build id does not match {args.expected_arch}: {build_id}')

    manifest = {
        'schema_version': 1,
        'profile': 'current-bazel-rootfs',
        'no_remote_rebuild': True,
        'git_commit': git_value('rev-parse', 'HEAD'),
        'git_short': git_value('rev-parse', '--short=12', 'HEAD'),
        'tracked_git_dirty': tracked_git_dirty(),
        'bazel_config': args.bazel_config,
        'cuda_arch': args.expected_arch,
        'host_cpu_copt': '-march=x86-64' if args.expected_arch == 'sm_80' else '-march=native',
        'bazel_targets': [f'//:{app}' for app in APPS],
        'rootfs_contract': contract,
        'rootfs_contract_identity': rootfs_identity,
        'build_ids': build_ids,
        'binary_sha256': binary_hashes,
        'created_unix': int(time.time()),
    }
    bundle = opt / 'bundle-manifest.json'
    bundle.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    (opt / 'binaries.sha256').write_text(''.join(
        f'{digest}  {path}\n' for path, digest in sorted(binary_hashes.items())
    ))
    return overlay, manifest, sha256(bundle)


def import_image(rootfs, overlay, image_tag, run_dir):
    if not (rootfs / 'usr/bin/bwrap').is_file():
        raise FileNotFoundError('rootfs is missing /usr/bin/bwrap; rebuild scripts/rootfs/rootfs')
    if not any((rootfs / 'usr/local').glob('cuda-*/bin/nvcc')):
        raise FileNotFoundError('rootfs is missing versioned CUDA nvcc')
    for mountpoint in ('work', 'weights', 'outputs'):
        if not (overlay / mountpoint).is_dir():
            raise FileNotFoundError(f'overlay is missing /{mountpoint} mountpoint')
    command = [
        'bash',
        '-lc',
        'set -euo pipefail; '
        'tmp="$(mktemp "$0/current-rootfs.XXXXXX.tar")"; '
        'trap \'rm -f "$tmp"\' EXIT; '
        'tar --numeric-owner -C "$1" '
        '--exclude=./opt/ds4 --exclude=./work --exclude=./weights --exclude=./outputs '
        '-cf "$tmp" .; '
        'tar --numeric-owner -C "$2" -rf "$tmp" ./opt/ds4 ./work ./weights ./outputs; '
        'cat "$tmp"',
        str(run_dir),
        str(rootfs),
        str(overlay),
    ]
    importer = [
        'docker', 'import', '--platform', 'linux/amd64',
        '--change', 'ENV PATH=/opt/ds4/bin:/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin',
        '--change', 'ENV CUDA_HOME=/usr/local/cuda',
        '--change', 'ENV CUDA_PATH=/usr/local/cuda',
        '--change', 'LABEL org.opencontainers.image.title=ds4-current-colab-rootfs',
        '-', image_tag,
    ]
    with (run_dir / 'docker-import.log').open('w') as log:
        tar = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)
        try:
            result = subprocess.run(importer, stdin=tar.stdout, stdout=log, stderr=subprocess.STDOUT)
            tar.stdout.close()
            tar_code = tar.wait()
        finally:
            if tar.poll() is None:
                tar.kill()
                tar.wait()
        if result.returncode or tar_code:
            raise RuntimeError('docker import failed; see docker-import.log')
    return output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image_tag])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=REPO_ROOT / '.ds4/colab-current',
                        help='repo-local state parent; default: .ds4/colab-current')
    parser.add_argument('--run-name',
                        help='state subdirectory name; default uses commit, arch, and timestamp')
    parser.add_argument('--rootfs', type=Path, default=REPO_ROOT / 'scripts/rootfs/rootfs')
    parser.add_argument('--bazel-config', default='cuda-a100')
    parser.add_argument('--expected-arch', default='sm_80')
    parser.add_argument('--image-tag',
                        help='local Docker tag; default: ds4-current-rootfs:<run-name>')
    parser.add_argument('--force', action='store_true',
                        help='replace an existing run directory')
    parser.add_argument('--no-import', action='store_true',
                        help='stage and write the receipt without docker import')
    args = parser.parse_args()

    state_dir, _ = ensure_repo_path(args.state_dir, 'state dir')
    short = git_value('rev-parse', '--short=12', 'HEAD')
    run_name = args.run_name or f'{short}-{args.expected_arch}-{time.strftime("%Y%m%d%H%M%S", time.gmtime())}'
    if '/' in run_name or run_name in ('', '.', '..'):
        parser.error('run name must be a single path segment')
    run_dir = state_dir / run_name
    if run_dir.exists():
        if not args.force:
            parser.error(f'{run_dir} already exists; pass --force to replace it')
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    rootfs = args.rootfs.resolve()
    if not rootfs.is_dir() or rootfs.is_symlink():
        parser.error(f'rootfs must be a real directory: {rootfs}')

    stage = stage_binaries(run_dir, args.bazel_config)
    overlay, manifest, bundle_sha = write_overlay(run_dir, stage, args, rootfs)
    image_tag = args.image_tag or f'ds4-current-rootfs:{run_name}'
    image_id = None
    if not args.no_import:
        image_id = import_image(rootfs, overlay, image_tag, run_dir)

    receipt = {
        'schema_version': 1,
        'profile': 'current-bazel-rootfs',
        'state_dir': str(run_dir),
        'local_image': image_tag,
        'local_image_id': image_id,
        'bundle_manifest_sha256': bundle_sha,
        'bundle_manifest': manifest,
        'overlay': str(overlay),
        'rootfs': str(rootfs),
    }
    receipt_path = run_dir / 'current-candidate.json'
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    latest = state_dir / 'latest-candidate.json'
    latest.write_text(json.dumps({'candidate': str(receipt_path)}, indent=2) + '\n')
    print(receipt_path)


if __name__ == '__main__':
    main()
