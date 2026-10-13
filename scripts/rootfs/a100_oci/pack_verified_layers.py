"""Assemble crane's documented compressed image-tar format without inflating layers."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

def pack_image(publication, manifest, config, cache, destination):
    expected = publication['reference'].split('@')[1]
    if not expected.startswith('sha256:'): raise ValueError('Manifest reference must be SHA256 pinned')
    # The raw manifest, config, and layer bytes are verified at acquisition.
    descriptor = manifest['config']
    if len(config)!=descriptor['size']: raise ValueError('Config size mismatch')
    if 'sha256:'+hashlib.sha256(config).hexdigest()!=descriptor['digest']: raise ValueError('Config digest mismatch')
    config_name = descriptor['digest']
    layer_names = [x['digest'][7:]+'.tar.gz' for x in manifest['layers']]
    archive_manifest = json.dumps([dict(Config=config_name,RepoTags=[],Layers=layer_names)]).encode()
    with tarfile.open(destination,'w') as archive:
        for name,data in [('manifest.json',archive_manifest),(config_name,config)]:
            item=tarfile.TarInfo(name); item.size=len(data); item.mode=0o600
            archive.addfile(item,io.BytesIO(data))
        seen=set()
        for descriptor,name in zip(manifest['layers'],layer_names):
            if name in seen:
                continue
            seen.add(name)
            source=cache/descriptor['digest']
            if source.is_symlink() or source.stat().st_size!=descriptor['size']: raise ValueError('Unsafe or invalid cached layer')
            item=tarfile.TarInfo(name); item.size=descriptor['size']; item.mode=0o600
            with source.open('rb') as stream:
                archive.addfile(item,stream)
