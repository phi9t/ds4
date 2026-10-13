"""Split independently changing applications and bind the optional object seed."""
import json
import os
from pathlib import Path
import shutil
from prepare_layers import APPS,HERE,ORIGINAL,RECIPE,digest,write_layer

receipt=json.loads((HERE/'selection-receipt.json').read_text());root=Path(receipt['state'])/'root'
paths=json.loads((HERE/'path-ownership.json').read_text())
for name in ('usr/local/bin/nsys','etc/cufile.json','etc/alternatives/cufile.json'):
    if name in paths['os']:paths['os'].remove(name)
for name in ('etc/alternatives/cc','etc/alternatives/c++','etc/alternatives/cpp','etc/alternatives/c89','etc/alternatives/c99'):
    if name in paths['os']:
        paths['os'].remove(name);paths['compiler'].append(name)
paths['compiler'].append('usr/local/cuda-13.0/bin/nvdisasm')
for component in ('os','compiler'):
    receipt['layers'][component]=write_layer(root,set(paths[component]),HERE/'layers'/(component+'.tar.gz'))
for name in APPS:
    selected={'opt','opt/ds4','opt/ds4/bin','opt/ds4/bin/'+name}
    receipt['layers']['app-'+name]=write_layer(root,selected,HERE/'layers'/('app-'+name+'.tar.gz'))
    paths['app-'+name]=sorted(selected)
receipt['superseded_aggregate_app']=receipt['layers'].pop('app',receipt.get('superseded_aggregate_app'))
paths.pop('app',None)
seed=dict(schema_version=1,source_archive_sha256='1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3',
          producer_rootfs=receipt['source_image'],producer_build_log_sha256=digest(Path(os.environ.get('DS4_BUILD_LOG', ORIGINAL/'build-r2.log'))),
          cuda_arch='sm_80',cpu_flag='-march=x86-64',
          makefile_sha256=digest(root/'opt/ds4/source/Makefile'),
          build_argv=['make','-j16','cuda','CUDA_ARCH=sm_80','NATIVE_CPU_FLAG=-march=x86-64'],
          compiler_files={name:digest(root/name) for name in (
              'usr/bin/x86_64-linux-gnu-gcc-13','usr/bin/make','opt/ds4/source/Makefile',
              'usr/local/cuda-13.0/bin/nvcc','usr/local/cuda-13.0/bin/ptxas')},
          object_files={name:digest(root/name) for name in paths['objects'] if name.endswith('.o')})
(root/'opt/ds4/object-seed.json').write_text(json.dumps(seed,indent=2)+'\n')
paths['objects'].append('opt/ds4/object-seed.json')
receipt['layers']['objects']=write_layer(root,set(paths['objects']),HERE/'layers/objects.tar.gz')
shutil.copy2(RECIPE/'validate_object_seed.py',root/'opt/ds4/validate_object_seed.py')
paths['metadata'].append('opt/ds4/validate_object_seed.py')
bundle=json.loads((root/'opt/ds4/bundle-manifest.json').read_text())
bundle['packaging_recipe_sha256']=digest(RECIPE/'prepare_layers.py')
bundle['component_recipe_sha256']=digest(Path(__file__))
(root/'opt/ds4/bundle-manifest.json').write_text(json.dumps(bundle,indent=2)+'\n')
receipt['layers']['metadata']=write_layer(root,set(paths['metadata']),HERE/'layers/metadata.tar.gz')
(HERE/'selection-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
(HERE/'path-ownership.json').write_text(json.dumps({n:sorted(set(v)) for n,v in paths.items()},indent=2)+'\n')
(HERE/'seed-manifest.json').write_text(json.dumps(seed,indent=2)+'\n')
print(json.dumps({name:r['compressed_bytes'] for name,r in receipt['layers'].items()},indent=2))
