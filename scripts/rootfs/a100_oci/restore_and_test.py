import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import traceback
import zipfile

BASE = Path('/content/ds4-rootfs-test')
BASE.mkdir(exist_ok=True)
records = []
status_path = Path('/content/rootfs-status.json')
def status(phase, **extra):
    data = dict(phase=phase, records=records, **extra)
    temporary = status_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2))
    temporary.replace(status_path)

def run(name, args, **kwargs):
    status(name)
    start = time.monotonic()
    with (BASE/(name+'.log')).open('w') as log:
        result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT,
                                timeout=600, **kwargs)
    records.append(dict(name=name, seconds=time.monotonic()-start, returncode=result.returncode))
    if result.returncode:
        raise RuntimeError(f'{name} failed; see log')
    return result

try:
    publication = json.loads(Path('/content/publication.json').read_text())
    crane = Path('/content/crane')
    assert hashlib.sha256(crane.read_bytes()).hexdigest() == '8e75c326adb43b053cfd78b9b987663f8f4fe4557f4d3915905643f25c730992'
    crane.chmod(0o755)
    env = dict(os.environ, DOCKER_CONFIG='/content/ghcr-auth')
    cache = Path('/content/registry-cache')
    image = BASE/'image.tar'
    run('registry-pull', [str(crane),'--platform','linux/amd64','pull',
                         '--cache_path',str(cache),publication['reference'],str(image)], env=env)
    # Exercise the same digest again against the downloaded layer cache.
    run('registry-cached-pull', [str(crane),'--platform','linux/amd64','pull',
                                '--cache_path',str(cache),publication['reference'],str(BASE/'cached-image.tar')], env=env)
    (BASE/'cached-image.tar').unlink()
    shutil.rmtree('/content/ghcr-auth')
    root = Path('/content/ds4-rootfs')
    stage = Path('/content/ds4-rootfs.stage')
    assert not root.exists() and not stage.exists()
    stage.mkdir()
    status('rootfs-export-extract')
    start = time.monotonic()
    with image.open('rb') as source, (BASE/'export.log').open('w') as log:
        export = subprocess.Popen([str(crane),'export','-','-'],stdin=source,stdout=subprocess.PIPE,stderr=log)
        extract = subprocess.run(['tar','--extract','--file=-','--directory',str(stage),'--no-same-owner'],stdin=export.stdout,stderr=log)
        export.stdout.close()
        exported = export.wait(timeout=600)
    assert exported == 0 and extract.returncode == 0
    records.append(dict(name='rootfs-export-extract',seconds=time.monotonic()-start,returncode=0))
    manifest = json.loads((stage/'opt/ds4/bundle-manifest.json').read_text())
    assert manifest['cuda_arch']=='sm_80'
    assert manifest['source_archive_sha256']=='1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3'
    for line in (stage/'opt/ds4/binaries.sha256').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        with (stage/name.lstrip('/')).open('rb') as f:
            assert hashlib.file_digest(f,'sha256').hexdigest()==digest
    stage.rename(root)
    work = Path('/content/ds4-experiment-work')
    weights = Path('/content/ds4-weight-bootstrap/gguf')
    def insula(name, args):
        output = BASE/name
        run(name,['python','/content/launch_insula.py','--rootfs',str(root),
                  '--work',str(work),'--weights',str(weights),'--outputs',str(output),'--gpu','--',*args])
    for binary in ['test_cuda_ssd_cache','test_cuda_q8_0_gemv','test_cuda_reductions']:
        insula(binary,['/opt/ds4/bin/'+binary])
    insula('compiler-version',['/usr/local/cuda/bin/nvcc','--version'])
    work.mkdir(exist_ok=True)
    (work/'probe.cu').write_text('''#include <cuda_runtime.h>
#include <stdio.h>
__global__ void compute(int *x) { *x=42; }
int main() { int *d, h=0; if(cudaMalloc(&d,sizeof(int))) return 1;
compute<<<1,1>>>(d); if(cudaMemcpy(&h,d,sizeof(int),cudaMemcpyDeviceToHost)) return 2;
cudaFree(d); printf("rebuilt A100 CUDA result: %d\\n",h); return h!=42; }
''')
    insula('compile-in-colab',['/usr/local/cuda/bin/nvcc','-arch=sm_80','-o','/work/probe','/work/probe.cu'])
    insula('execute-rebuilt-cuda',['/work/probe'])
    insula('prepare-ds4-rebuild',['/usr/bin/python3','-c',
        "import shutil; from pathlib import Path; "
        "shutil.copytree('/opt/ds4/source','/work/source'); "
        "Path('/work/source/ds4_bench.c').touch()"])
    insula('rebuild-ds4-bench',['/usr/bin/make','-C','/work/source','-j4','ds4-bench',
        'CUDA_ARCH=sm_80','NATIVE_CPU_FLAG=-march=x86-64'])
    insula('rootfs-read-only',['/usr/bin/python3','-c',
        "import errno; from pathlib import Path; "
        "p=Path('/opt/ds4/write-probe'); "
        "exec(\"try:\\n p.write_text('x')\\nexcept OSError as e:\\n assert e.errno==errno.EROFS\\nelse:\\n raise AssertionError('rootfs was writable')\")"])
    status('waiting-for-weights')
    deadline = time.monotonic()+900
    while not Path('/content/ds4-weight-ready.json').exists():
        if time.monotonic()>deadline:
            raise RuntimeError('Checkpoint staging did not complete')
        time.sleep(5)
    model = json.loads(Path('/content/ds4-weight-ready.json').read_text())
    name = Path(model['model']).name
    insula('ds4-inference',['/work/source/ds4-bench','--cuda','-m','/weights/'+name,
        '--ssd-streaming','--ssd-streaming-cache-experts','16GB','--prefill-chunk','1024',
        '--prompt-file','/opt/ds4/source/speed-bench/promessi_sposi.txt',
        '--ctx-alloc','4096','--ctx-start','1024','--ctx-max','1024','--gen-tokens','32',
        '--csv','/outputs/inference.csv'])
    row = list(csv.DictReader((BASE/'ds4-inference/inference.csv').open()))[0]
    assert int(row['prefill_tokens'])==1024 and int(row['gen_tokens'])==32
    status('complete', metrics=row, publication=publication, weights=model)
except BaseException:
    status('failed', error=traceback.format_exc())
finally:
    shutil.rmtree('/content/ghcr-auth',ignore_errors=True)
    with zipfile.ZipFile('/content/rootfs-test-results.zip','w',zipfile.ZIP_DEFLATED) as archive:
        archive.write(status_path,'status.json')
        for path in BASE.rglob('*'):
            if path.is_file() and path.suffix in ('.log','.json','.csv'):
                archive.write(path,path.relative_to(BASE))
