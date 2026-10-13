"""Refuse object reuse under a different source/compiler/target contract."""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--rootfs',type=Path,default=Path('/'))
p.add_argument('--cuda-arch',default='sm_80')
p.add_argument('--cpu-flag',default='-march=x86-64')
a=p.parse_args();root=a.rootfs
seed=json.loads((root/'opt/ds4/object-seed.json').read_text())
bundle=json.loads((root/'opt/ds4/bundle-manifest.json').read_text())
for key,value in [('source_archive_sha256',bundle['source_archive_sha256']),('cuda_arch',a.cuda_arch),('cpu_flag',a.cpu_flag)]:
    if seed[key]!=value:p.error('Object seed incompatible: '+key)
for name,expected in {**seed['compiler_files'],**seed['object_files']}.items():
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts:p.error('Invalid seed path')
    target=root/relative
    if target.is_symlink() or not target.is_file():p.error('Seed input is not a regular file: '+name)
    with target.open('rb') as source:
        if hashlib.file_digest(source,'sha256').hexdigest()!=expected:p.error('Seed input digest mismatch: '+name)
print('Object seed matches source, compiler, sm_80 and x86-64 contract')
