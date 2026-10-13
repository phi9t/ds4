"""Publish only image layers above the pinned CUDA base using crane append."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(os.environ.get('DS4_ROOTFS_INPUTS', Path(__file__).resolve().parent))
CRANE = os.environ.get('DS4_CRANE', 'crane')
BASE_REF = 'nvidia/cuda@sha256:b7ae301dea2c162444795462ce17a05f6a516e5a75944b57af5b88540a1a2266'
IMAGE = 'ds4-a100-build:fc80bd6-cu130'
PACKAGE = 'ds4-a100-build-rootfs'
REF = 'ghcr.io/phi9t/'+PACKAGE+':'+os.environ['DS4_BASELINE_TAG']
TOKEN_FILE = Path(os.environ['GHCR_TOKEN_FILE'])
assert TOKEN_FILE.stat().st_mode & 0o777 == 0o600
token = TOKEN_FILE.read_text().strip()
def verify_private():
    request = urllib.request.Request('https://api.github.com/users/phi9t/packages/container/'+PACKAGE,
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        package = json.load(response)
    if package['visibility'] != 'private':
        raise ValueError('Package visibility differs from private')
verify_private()
receipt = dict(image=REF, base=BASE_REF, phases=[])
def call(name, args, **kwargs):
    begin = time.monotonic()
    result = subprocess.run(args, check=True, **kwargs)
    receipt['phases'].append(dict(name=name, seconds=time.monotonic()-begin))
    return result
with tempfile.TemporaryDirectory(prefix='ds4-oci-publish-', dir='/tmp') as temp:
    stage = Path(temp)
    config = stage/'auth'
    config.mkdir(mode=0o700)
    path = config/'config.json'
    path.write_text(json.dumps({'auths':{'ghcr.io':{'auth':base64.b64encode(('phi9t:'+token).encode()).decode()}}}))
    path.chmod(0o600)
    env = dict(os.environ, DOCKER_CONFIG=str(config))
    inspect = json.loads(subprocess.check_output(['docker','inspect',BASE_REF],text=True))[0]
    base_layers = inspect['RootFS']['Layers']
    base_count = len(base_layers)
    saved = stage/'image.tar'
    call('docker-save', ['docker','save','-o',str(saved),IMAGE])
    layers = []
    with tarfile.open(saved) as archive:
        manifest = json.load(archive.extractfile('manifest.json'))[0]
        saved_config = json.load(archive.extractfile(manifest['Config']))
        assert saved_config['rootfs']['diff_ids'][:base_count] == base_layers, 'image base DiffIDs differ from the pinned base'
        for i, name in enumerate(manifest['Layers'][base_count:]):
            target = stage/f'layer-{i}.tar'
            with archive.extractfile(name) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output, 1024*1024)
            layers.append(target)
    assert layers
    args = [CRANE,'--platform','linux/amd64','append','--base',BASE_REF,'--new_tag',REF,'--set-base-image-annotations']
    for layer in layers:
        args += ['--new_layer',str(layer)]
    call('crane-append-push',args,env=env)
    digest = subprocess.check_output([CRANE,'--platform','linux/amd64','digest',REF],env=env,text=True).strip()
    receipt['digest'] = digest
    receipt['reference'] = REF.split(':')[0]+'@'+digest
    manifest = json.loads(subprocess.check_output([CRANE,'--platform','linux/amd64','manifest',receipt['reference']],env=env,text=True))
    receipt['layers'] = manifest['layers']
    receipt['manifest'] = manifest
    receipt['compressed_layer_bytes'] = sum(l['size'] for l in manifest['layers'])
    request = urllib.request.Request('https://api.github.com/users/phi9t/packages/container/'+PACKAGE,
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request) as response:
        package = json.load(response)
    assert package['visibility'] == 'private', package['visibility']
    receipt['visibility'] = package['visibility']
    (ROOT/'publication.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
