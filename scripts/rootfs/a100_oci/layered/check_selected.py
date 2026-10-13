"""Live CPU-only loader/compiler checks for selected component layers."""
import json
import os
from pathlib import Path
import subprocess
import time

RECIPE=Path(__file__).resolve().parent
HERE=Path(os.environ.get('DS4_ROOTFS_STATE', RECIPE))
receipt=json.loads((HERE/'selection-receipt.json').read_text())
state=Path(receipt['state']);root=state/'curated';root.mkdir()
for name in ('os','cuda-runtime','compiler','source','app','metadata'):
    subprocess.run(['tar','-xzf',str(HERE/'layers'/(name+'.tar.gz')),'-C',str(root),'--no-same-owner'],check=True)
work=state/'work';outputs=state/'checks';records=[]
def run(name,argv,timeout=1800):
    out=outputs/name;out.mkdir(parents=True)
    args=['python3',str(RECIPE.parent/'launch_insula.py'),'--rootfs',str(root),'--work',str(work),
          '--weights',str(state/'weights-empty'),'--outputs',str(out),'--',*argv]
    begin=time.monotonic()
    with (out/'stdout.log').open('w') as log:
        result=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
    records.append(dict(name=name,seconds=time.monotonic()-begin,returncode=result.returncode))
    (HERE/'selected-checks.json').write_text(json.dumps(dict(state=str(state),root=str(root),records=records),indent=2)+'\n')
    print(name,result.returncode,records[-1]['seconds'],flush=True)
    if result.returncode:raise RuntimeError(name+' failed: '+str(out/'stdout.log'))
for app in ('ds4','ds4-bench','ds4-server','ds4-eval','ds4-agent'):
    run(app+'-help',['/opt/ds4/bin/'+app,'--help'])
run('nvcc',['/usr/local/cuda/bin/nvcc','--version'])
run('copy-source',['/usr/bin/python3','-c',"import shutil; shutil.copytree('/opt/ds4/source','/work/source')"])
run('clean-cuda-build',['/usr/bin/make','-C','/work/source','-j4','cuda','CUDA_ARCH=sm_80','NATIVE_CPU_FLAG=-march=x86-64'])
run('rebuilt-help',['/work/source/ds4-bench','--help'])
print('All selected-rootfs checks passed',flush=True)
