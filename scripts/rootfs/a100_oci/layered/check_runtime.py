import json
import os
from pathlib import Path
import subprocess
import time
RECIPE=Path(__file__).resolve().parent
HERE=Path(os.environ.get('DS4_ROOTFS_STATE', RECIPE))

state=Path(json.loads((HERE/'selection-receipt.json').read_text())['state'])
root=state/'runtime-only';root.mkdir()
for name in ['os','cuda-runtime',*['app-'+n for n in ('ds4','ds4-bench','ds4-server','ds4-eval','ds4-agent')],'metadata']:
    subprocess.run(['tar','-xzf',str(HERE/'layers'/(name+'.tar.gz')),'-C',str(root),'--no-same-owner'],check=True)
assert not (root/'usr/local/cuda-13.0/bin/nvcc').exists()
assert not (root/'usr/bin/x86_64-linux-gnu-gcc-13').exists()
assert not (root/'opt/ds4/source').exists()
records=[]
for name in ('ds4','ds4-bench','ds4-server','ds4-eval','ds4-agent'):
    out=state/'runtime-checks'/name;out.mkdir(parents=True)
    before=time.monotonic()
    with (out/'stdout.log').open('w') as log:
        r=subprocess.run(['python3',str(RECIPE.parent/'launch_insula.py'),'--rootfs',str(root),
            '--work',str(state/'runtime-work'),'--weights',str(state/'weights-empty'),'--outputs',str(out),
            '--','/opt/ds4/bin/'+name,'--help'],stdout=log,stderr=subprocess.STDOUT,timeout=120)
    records.append(dict(name=name,seconds=time.monotonic()-before,returncode=r.returncode))
    if r.returncode:raise RuntimeError('Runtime-only application failed: '+name)
(HERE/'runtime-checks.json').write_text(json.dumps(dict(root=str(root),records=records,compiler_absent=True,source_absent=True),indent=2)+'\n')
print('Runtime-only checks passed for all five binaries')
