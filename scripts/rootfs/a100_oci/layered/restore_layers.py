"""Digest-verified parallel acquisition and atomic materialization of pinned images."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import uuid
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pack_verified_layers import pack_image

DIGEST=re.compile(r'^sha256:[0-9a-f]{64}$')

def file_hash(path):
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def restore(publication,cache,root,crane,logs,notify=lambda phase,record:None):
    repository,expected=publication['reference'].split('@')
    if not DIGEST.fullmatch(expected):raise ValueError('Manifest must be pinned by SHA256')
    cache=Path(cache);root=Path(root);logs=Path(logs)
    if cache.is_symlink() or logs.is_symlink() or root.exists() or root.is_symlink():raise ValueError('Unsafe or existing restore target')
    cache.mkdir(parents=True,exist_ok=True);logs.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ)
    env.setdefault('DOCKER_CONFIG','/content/ghcr-auth')
    records=[]
    def record(name,before,**extra):
        value=dict(name=name,seconds=time.monotonic()-before,**extra);records.append(value);notify(name,value)
    before=time.monotonic()
    raw=subprocess.check_output([str(crane),'manifest',publication['reference']],env=env,timeout=120)
    if 'sha256:'+hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Manifest digest mismatch')
    manifest=json.loads(raw)
    if manifest['layers']!=publication['layers']:raise ValueError('Manifest differs from acquisition receipt')
    config=subprocess.check_output([str(crane),'blob',repository+'@'+manifest['config']['digest']],env=env,timeout=120)
    record('metadata',before)
    layers={x['digest']:x for x in manifest['layers']}
    for layer in layers.values():
        if not DIGEST.fullmatch(layer['digest']) or not isinstance(layer['size'],int) or layer['size']<0:raise ValueError('Invalid layer descriptor')
        if layer['mediaType'] not in ('application/vnd.oci.image.layer.v1.tar+gzip','application/vnd.docker.image.rootfs.diff.tar.gzip'):raise ValueError('This restore recipe supports gzip layers only')
    def fetch(layer):
        target=cache/layer['digest']
        if target.exists():
            if target.is_symlink() or target.stat().st_size!=layer['size'] or file_hash(target)!=layer['digest'][7:]:raise ValueError('Corrupt cached layer')
            return dict(digest=layer['digest'],bytes=0,cached=True)
        temporary=cache/(layer['digest']+'.partial-'+uuid.uuid4().hex)
        with (logs/(layer['digest'][7:]+'.log')).open('w') as log:
            process=subprocess.Popen([str(crane),'blob',repository+'@'+layer['digest']],env=env,
                                     stdout=subprocess.PIPE,stderr=log,start_new_session=True)
            def kill():
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            watchdog=threading.Timer(900,kill);watchdog.start()
            try:
                count=0;digest=hashlib.sha256()
                with temporary.open('xb') as destination:
                    while block:=process.stdout.read(1024*1024):
                        count+=len(block)
                        if count>layer['size']:raise ValueError('Layer exceeded declared size')
                        digest.update(block);destination.write(block)
                code=process.wait(timeout=10)
                if code or count!=layer['size'] or digest.hexdigest()!=layer['digest'][7:]:raise ValueError('Layer acquisition failed integrity check')
                temporary.replace(target)
            finally:
                watchdog.cancel();process.stdout.close()
                if process.poll() is None:kill();process.wait(timeout=10)
                temporary.unlink(missing_ok=True)
        return dict(digest=layer['digest'],bytes=count,cached=False)
    before=time.monotonic();acquired=[]
    notify('download',dict(total_layers=len(layers)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pending=[pool.submit(fetch,layer) for layer in layers.values()]
        for future in concurrent.futures.as_completed(pending):
            acquired.append(future.result());notify('download-progress',dict(completed_layers=len(acquired),total_layers=len(layers)))
    record('download-and-verify',before,bytes=sum(x['bytes'] for x in acquired),cached_layers=sum(x['cached'] for x in acquired))
    image=logs/'image.tar';before=time.monotonic()
    pack_image(publication,manifest,config,cache,image);record('pack',before)
    stage=root.with_name(root.name+'.stage-'+uuid.uuid4().hex);stage.mkdir()
    before=time.monotonic()
    with image.open('rb') as source,(logs/'export.log').open('w') as log:
        export=subprocess.Popen([str(crane),'export','-','-'],stdin=source,stdout=subprocess.PIPE,stderr=log,start_new_session=True)
        try:
            extracted=subprocess.run(['tar','-xf','-','-C',str(stage),'--no-same-owner'],stdin=export.stdout,stderr=log,timeout=900)
            export.stdout.close();code=export.wait(timeout=30)
            if code or extracted.returncode:raise ValueError('Rootfs export/extract failed')
        finally:
            if export.poll() is None:
                os.killpg(export.pid,signal.SIGKILL);export.wait(timeout=10)
    bundle_path=stage/'opt/ds4/bundle-manifest.json'
    bundle=json.loads(bundle_path.read_text())
    expected_bundle=publication.get('bundle_manifest_sha256')
    if expected_bundle:
        if file_hash(bundle_path)!=expected_bundle:raise ValueError('Unexpected bundle manifest')
    elif bundle.get('source_archive_sha256')!='1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3':
        raise ValueError('Unexpected source contract')
    for line in (stage/'opt/ds4/binaries.sha256').read_text().splitlines():
        digest,name=line.split(maxsplit=1)
        if file_hash(stage/name.lstrip('/'))!=digest:raise ValueError('Restored binary differs from bundle')
    (stage/'opt/ds4/restore-receipt.json').write_text(json.dumps(dict(reference=publication['reference'],layers=manifest['layers']),indent=2)+'\n')
    stage.rename(root);record('materialize-and-verify',before)
    image.unlink()
    return dict(reference=publication['reference'],rootfs=str(root),records=records,layer_digests=[x['digest'] for x in manifest['layers']])


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--image', choices=('runtime', 'build', 'seed'), default='build')
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--logs', type=Path, required=True)
    parser.add_argument('--crane', default='crane')
    args = parser.parse_args()
    release = json.loads(args.release.read_text())
    result = restore(release['images'][args.image], args.cache, args.rootfs, args.crane, args.logs)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
