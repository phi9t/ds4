"""Publish rules_oci layouts privately and record immutable image descriptors."""
import base64
import errno
import shutil
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

HERE=Path(os.environ.get('DS4_ROOTFS_STATE', Path(__file__).resolve().parent))
CRANE=os.environ.get('DS4_CRANE', 'crane')
PACKAGE='ds4-a100-build-rootfs'
REPOSITORY='ghcr.io/phi9t/'+PACKAGE
TOKEN=Path(os.environ['GHCR_TOKEN_FILE'])
if TOKEN.stat().st_mode & 0o777 != 0o600:raise PermissionError('Registry credential must have mode 0600')
secret=TOKEN.read_text().strip()
def verify_private():
    request=urllib.request.Request('https://api.github.com/users/phi9t/packages/container/'+PACKAGE,
        headers={'Authorization':'Bearer '+secret,'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=60) as response:package=json.load(response)
    if package['visibility']!='private':raise ValueError('Package visibility differs from private')
verify_private()
layouts=json.loads(Path(os.environ['DS4_OCI_LAYOUTS']).read_text())
apps=['app-'+n for n in ('ds4','ds4-bench','ds4-server','ds4-eval','ds4-agent')]
names={'runtime':['os','cuda-runtime',*apps,'metadata'],
       'build':['os','cuda-runtime','compiler','bazel-tools','source',*apps,'metadata']}
names['seed']=[*names['build'],'objects']
release=dict(schema_version=1,package=REPOSITORY,images={})
with tempfile.TemporaryDirectory(prefix='ds4-layered-publish-',dir='/tmp') as temporary:
    auth=Path(temporary);config=auth/'config.json'
    config.write_text(json.dumps({'auths':{'ghcr.io':{'auth':base64.b64encode(('phi9t:'+secret).encode()).decode()}}}));config.chmod(0o600)
    env=dict(os.environ,DOCKER_CONFIG=str(auth))
    with tempfile.TemporaryDirectory(prefix='.publish-layouts-',dir=HERE) as view_dir:
      for name in ('runtime','build','seed'):
        original=Path(layouts[name]);layout=Path(view_dir)/name;layout.mkdir()
        for source in original.rglob('*'):
            destination=layout/source.relative_to(original)
            if source.is_dir():destination.mkdir(exist_ok=True)
            else:
                real=source.resolve(strict=True)
                if not real.is_file():raise ValueError('OCI layout entry is not a regular file')
                if source.parent.name=='sha256':
                    with real.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
                    if actual!=source.name:raise ValueError('OCI layout blob digest mismatch')
                try:os.link(real,destination)
                except OSError as error:
                    if error.errno!=errno.EXDEV:raise
                    shutil.copyfile(real,destination)
        tag=REPOSITORY+':'+os.environ['DS4_RELEASE_PREFIX']+'-'+name+'-'+os.environ['DS4_RELEASE_SUFFIX']
        before=time.monotonic()
        subprocess.run([CRANE,'push',str(layout),tag],env=env,check=True)
        seconds=time.monotonic()-before
        digest=subprocess.check_output([CRANE,'digest',tag],env=env,text=True).strip()
        reference=REPOSITORY+'@'+digest
        raw=subprocess.check_output([CRANE,'manifest',reference],env=env)
        if 'sha256:'+hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Published manifest identity mismatch')
        manifest=json.loads(raw)
        if len(manifest['layers'])!=len(names[name]):raise ValueError('Unexpected image topology')
        for component,descriptor in zip(names[name],manifest['layers']):
            path=HERE/'layers'/(component+'.tar.gz')
            with path.open('rb') as source:actual=hashlib.file_digest(source,'sha256').hexdigest()
            if descriptor['digest']!='sha256:'+actual:raise ValueError('Published layer differs from pinned input')
        receipt=dict(layer_names=names[name],image=tag,reference=reference,digest=digest,layers=manifest['layers'],manifest=manifest,
                     compressed_layer_bytes=sum(x['size'] for x in manifest['layers']),push_seconds=seconds)
        release['images'][name]=receipt
        (HERE/('publication-'+name+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    shared={x['digest'] for x in release['images']['runtime']['layers']}
    if not shared.issubset({x['digest'] for x in release['images']['build']['layers']}):raise ValueError('Runtime blobs not shared by build')
    verify_private()
    release['visibility']='private';release['shared_runtime_digests']=sorted(shared)
    (HERE/'release.json').write_text(json.dumps(release,indent=2)+'\n')
print(json.dumps({name:dict(reference=value['reference'],compressed_layer_bytes=value['compressed_layer_bytes'],push_seconds=value['push_seconds']) for name,value in release['images'].items()},indent=2))
