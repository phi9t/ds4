import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import traceback
import zipfile
import re
from pack_verified_layers import pack_image

run_name = os.environ.get('DS4_ROOTFS_TEST_RUN', '')
assert re.fullmatch('[a-z0-9-]*', run_name)
suffix = '-'+run_name if run_name else ''
BASE = Path('/content/ds4-cpu-rootfs-test'+suffix)
BASE.mkdir(exist_ok=True)
records = []
status_path = Path('/content/cpu-rootfs-status'+suffix+'.json')
publication = json.loads(Path('/content/publication.json').read_text())
crane = Path('/content/crane')
env = dict(os.environ, DOCKER_CONFIG='/content/ghcr-auth')

def status(phase, **extra):
    temp = status_path.with_suffix('.tmp')
    temp.write_text(json.dumps(dict(phase=phase,records=records,**extra),indent=2))
    temp.replace(status_path)

def run(name, args, **kwargs):
    status(name)
    begin = time.monotonic()
    with (BASE/(name+'.log')).open('w') as log:
        result = subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=900,**kwargs)
    records.append(dict(name=name,seconds=time.monotonic()-begin,returncode=result.returncode))
    if result.returncode:
        raise RuntimeError(f'{name} failed; see log')

success = False
try:
    assert not Path('/dev/nvidia0').exists(), 'Transfer benchmark must use a CPU-only session'
    assert hashlib.sha256(crane.read_bytes()).hexdigest()=='8e75c326adb43b053cfd78b9b987663f8f4fe4557f4d3915905643f25c730992'
    crane.chmod(0o755)
    cache = Path('/content/registry-cache'+suffix)
    cache.mkdir(mode=0o700,exist_ok=True)
    if not run_name:
        assert not any(cache.iterdir()), 'Cold test needs an empty cache'
    status('parallel-cold-layer-fetch')
    begin = time.monotonic()
    repository = publication['reference'].split('@')[0]
    layers = {layer['digest']:layer for layer in publication['layers']}
    def fetch(layer):
        digest = layer['digest']
        assert digest.startswith('sha256:') and len(digest)==71
        target = cache/digest
        if target.exists():
            assert not target.is_symlink() and target.stat().st_size==layer['size']
            with target.open('rb') as source:
                assert hashlib.file_digest(source,'sha256').hexdigest()==digest[7:]
            return dict(digest=digest,size=layer['size'],cached=True)
        temporary = cache/(digest+'.partial')
        with temporary.open('wb') as output, (BASE/(digest[7:]+'.log')).open('w') as log:
            subprocess.run([str(crane),'blob',repository+'@'+digest],env=env,
                           stdout=output,stderr=log,check=True,timeout=900)
        assert temporary.stat().st_size==layer['size']
        with temporary.open('rb') as source:
            assert hashlib.file_digest(source,'sha256').hexdigest()==digest[7:]
        temporary.replace(target)
        return dict(digest=digest,size=layer['size'],cached=False)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        downloaded = list(pool.map(fetch,layers.values()))
    records.append(dict(name='parallel-cold-layer-fetch',seconds=time.monotonic()-begin,returncode=0,
                        workers=4,bytes=sum(x['size'] for x in downloaded if not x['cached']),
                        cached_layers=sum(x['cached'] for x in downloaded)))
    image = BASE/'image.tar'
    status('acquire-image-metadata')
    begin=time.monotonic()
    raw_manifest=subprocess.check_output([str(crane),'--platform','linux/amd64','manifest',publication['reference']],env=env,timeout=120)
    assert 'sha256:'+hashlib.sha256(raw_manifest).hexdigest()==publication['reference'].split('@')[1]
    manifest=json.loads(raw_manifest)
    assert manifest['layers']==publication['layers']
    config=subprocess.check_output([str(crane),'blob',repository+'@'+manifest['config']['digest']],env=env,timeout=120)
    records.append(dict(name='acquire-image-metadata',seconds=time.monotonic()-begin,returncode=0))
    status('pack-verified-compressed-layers')
    begin=time.monotonic()
    pack_image(publication,manifest,config,cache,image)
    records.append(dict(name='pack-verified-compressed-layers',seconds=time.monotonic()-begin,returncode=0))
    status('repeat-cached-pack')
    begin=time.monotonic()
    pack_image(publication,manifest,config,cache,BASE/'repeat.tar')
    records.append(dict(name='repeat-cached-pack',seconds=time.monotonic()-begin,returncode=0))
    (BASE/'repeat.tar').unlink()
    shutil.rmtree('/content/ghcr-auth')
    root = Path('/content/ds4-rootfs'+suffix)
    stage = root.with_name(root.name+'.stage')
    assert not stage.exists() and not root.exists()
    stage.mkdir()
    status('export-and-materialize')
    begin = time.monotonic()
    with image.open('rb') as source, (BASE/'export.log').open('w') as log:
        export = subprocess.Popen([str(crane),'export','-','-'],stdin=source,stdout=subprocess.PIPE,stderr=log)
        extracted = subprocess.run(['tar','--extract','--file=-','--directory',str(stage),'--no-same-owner'],
                                   stdin=export.stdout,stderr=log,timeout=900)
        export.stdout.close()
        code = export.wait(timeout=900)
    assert code==0 and extracted.returncode==0
    records.append(dict(name='export-and-materialize',seconds=time.monotonic()-begin,returncode=0))
    manifest = json.loads((stage/'opt/ds4/bundle-manifest.json').read_text())
    assert manifest['source_archive_sha256']=='1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3'
    for line in (stage/'opt/ds4/binaries.sha256').read_text().splitlines():
        digest,name=line.split(maxsplit=1)
        with (stage/name.lstrip('/')).open('rb') as source:
            assert hashlib.file_digest(source,'sha256').hexdigest()==digest
    stage.rename(root)
    work = Path('/content/ds4-experiment-work'+suffix)
    def insula(name,args):
        run(name,['python','/content/launch_insula.py','--rootfs',str(root),'--work',str(work),
                  '--weights','/content/weights-empty','--outputs',str(BASE/name),'--',*args])
    insula('toolchain',['/usr/local/cuda/bin/nvcc','--version'])
    work.mkdir(exist_ok=True)
    (work/'rebuild_probe.cu').write_text('#include <cuda_runtime.h>\n__global__ void probe(int *p) { *p=42; }\n')
    insula('compile-cuda-sm80',['/usr/local/cuda/bin/nvcc','-arch=sm_80','-cubin',
                              '-o','/work/rebuild_probe.cubin','/work/rebuild_probe.cu'])
    insula('inspect-sm80-cubin',['/usr/local/cuda/bin/cuobjdump','--dump-sass','/work/rebuild_probe.cubin'])
    assert 'sm_80' in (BASE/'inspect-sm80-cubin.log').read_text()
    insula('read-only-rootfs',['/usr/bin/python3','-c',
        "import errno; from pathlib import Path; "
        "exec(\"try:\\n Path('/opt/ds4/write-probe').write_text('x')\\nexcept OSError as e:\\n assert e.errno==errno.EROFS\\nelse:\\n raise AssertionError('rootfs writable')\")"])
    insula('prepare-rebuild',['/usr/bin/python3','-c',
        "import shutil; from pathlib import Path; shutil.copytree('/opt/ds4/source','/work/source'); "
        "Path('/work/source/ds4_bench.c').touch()"])
    insula('rebuild-ds4-bench',['/usr/bin/make','-C','/work/source','-j2','ds4-bench',
                              'CUDA_ARCH=sm_80','NATIVE_CPU_FLAG=-march=x86-64'])
    insula('rebuilt-cli-help',['/work/source/ds4-bench','--help'])
    success = True
    status('complete',publication=publication,environment=dict(cpu_only=True,
        memory=Path('/proc/meminfo').read_text(),platform=os.uname()._asdict() if hasattr(os.uname(),'_asdict') else list(os.uname())))
except BaseException:
    status('failed',error=traceback.format_exc())
finally:
    shutil.rmtree('/content/ghcr-auth',ignore_errors=True)
    with zipfile.ZipFile('/content/cpu-rootfs-results'+suffix+'.zip','w',zipfile.ZIP_DEFLATED) as archive:
        archive.write(status_path,'status.json')
        for path in BASE.rglob('*'):
            if path.is_file() and path.suffix in ('.log','.json','.csv'):
                archive.write(path,path.relative_to(BASE))
raise SystemExit(0 if success else 1)
