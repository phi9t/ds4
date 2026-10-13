"""Run exact argv in the pinned DS4 rootfs with declared workspace/GPU mounts."""
import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--rootfs', type=Path, required=True)
p.add_argument('--work', type=Path, required=True)
p.add_argument('--weights', type=Path, required=True)
p.add_argument('--outputs', type=Path, required=True)
p.add_argument('--expected-bundle-sha256',
               default=os.environ.get('DS4_EXPECTED_BUNDLE_SHA256'),
               help='optional SHA256 of /opt/ds4/bundle-manifest.json')
p.add_argument('--gpu', action='store_true', help='Project NVIDIA devices and host driver libraries')
p.add_argument('command', nargs=argparse.REMAINDER)
a = p.parse_args()
argv = a.command[1:] if a.command[:1] == ['--'] else a.command
if not argv or not argv[0].startswith('/'):
    p.error('provide an exact absolute executable path after --')
if a.rootfs.is_symlink() or not a.rootfs.is_dir():
    p.error('rootfs must be a materialized directory, not a symlink')
root = a.rootfs.resolve(strict=True)
def overlaps(left, right):
    return left == right or left in right.parents or right in left.parents
weights = a.weights.resolve()
for writable in (a.work.resolve(), a.outputs.resolve()):
    if overlaps(writable, root) or overlaps(writable, weights):
        p.error('writable projections must not overlap the rootfs or weights')
manifest = json.loads((root/'opt/ds4/bundle-manifest.json').read_text())
bundle_sha256 = hashlib.sha256((root/'opt/ds4/bundle-manifest.json').read_bytes()).hexdigest()
if a.expected_bundle_sha256:
    if bundle_sha256 != a.expected_bundle_sha256:
        p.error('rootfs bundle manifest differs from the release record')
elif manifest.get('source_archive_sha256') != '1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3':
    p.error('rootfs source identity differs from the reviewed build')
for directory in (a.work, a.weights, a.outputs):
    if directory.is_symlink():
        p.error('projected directories must not be symlinks')
    directory.mkdir(parents=True, exist_ok=True)
loader = root/'usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
if loader.is_symlink() or not loader.is_file():
    p.error('rootfs must contain its own regular ELF loader file')
library = root/'usr/lib/x86_64-linux-gnu'
args = [str(loader), '--library-path', str(library), str(root/'usr/bin/bwrap'),
        '--unshare-user', '--unshare-ipc', '--unshare-uts', '--unshare-net',
        '--die-with-parent', '--new-session',
        '--ro-bind', str(root), '/', '--ro-bind', '/proc', '/proc', '--dev', '/dev',
        '--tmpfs', '/tmp', '--tmpfs', '/run',
        '--dir', '/run/nvidia-driver', '--dir', '/run/nvidia-driver/lib',
        '--bind', str(a.work.resolve()), '/work',
        '--ro-bind', str(a.weights.resolve()), '/weights',
        '--bind', str(a.outputs.resolve()), '/outputs',
        '--clearenv', '--setenv', 'HOME', '/work',
        '--setenv', 'PATH', '/run/nvidia-driver/bin:/opt/ds4/bin:/usr/local/cuda/bin:/usr/bin:/bin',
        '--setenv', 'CUDA_HOME', '/usr/local/cuda',
        '--setenv', 'LD_LIBRARY_PATH', '/run/nvidia-driver/lib:/usr/local/cuda/lib64',
        '--setenv', 'CUDA_VISIBLE_DEVICES', '0' if a.gpu else '-1', '--chdir', '/work']
devices = sorted(glob.glob('/dev/nvidia*')) if a.gpu else []
for device in devices:
    if Path(device).is_dir():
        continue
    args += ['--dev-bind', device, device]
drivers = {}
for directory in ([
    '/usr/lib/x86_64-linux-gnu',
    '/lib/x86_64-linux-gnu',
    '/usr/local/nvidia/lib64',
    '/usr/local/nvidia/lib',
    '/usr/lib64-nvidia',
] if a.gpu else []):
    for pattern in ['libcuda.so*', 'libnvidia-*.so*']:
        for name in glob.glob(directory+'/'+pattern):
            path = Path(name)
            if path.is_file():
                drivers[path.name] = path.resolve()
if a.gpu and (not devices or not any(n.startswith('libcuda.so') for n in drivers)):
    p.error('host NVIDIA devices and driver libraries are required')
for name, path in sorted(drivers.items()):
    args += ['--ro-bind', str(path), '/run/nvidia-driver/lib/'+name]
nvidia_smi = shutil.which('nvidia-smi') if a.gpu else None
if nvidia_smi:
    args += ['--ro-bind', nvidia_smi, '/run/nvidia-driver/bin/nvidia-smi']
args += ['--', *argv]
receipt = dict(rootfs=str(root), bundle=manifest, argv=argv,
               work=str(a.work.resolve()), weights=str(a.weights.resolve()),
               outputs=str(a.outputs.resolve()), devices=devices,
               driver_libraries={k:str(v) for k,v in drivers.items()},
               bundle_manifest_sha256=bundle_sha256,
               network='isolated', rootfs_access='read-only', proc='host proc read-only; host PID namespace',
               limitations='Shares the host kernel. This is not a hostile-code security boundary.')
result = subprocess.run(args, env={'PATH':'/usr/bin:/bin'})
receipt['returncode'] = result.returncode
(a.outputs/'insula-run-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
raise SystemExit(result.returncode)
