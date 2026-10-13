#!/usr/bin/env python3
"""Check OCI descriptor order and exact compressed source bytes."""
import hashlib
import json
from pathlib import Path
import sys

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

layout = Path(sys.argv[1])
inputs = Path(sys.argv[2])
names = sys.argv[3:]
index = json.loads((layout / "index.json").read_text())
manifest_digest = index["manifests"][0]["digest"].split(":", 1)[1]
manifest_path = layout / "blobs/sha256" / manifest_digest
assert sha256(manifest_path) == manifest_digest
manifest = json.loads(manifest_path.read_text())
assert len(manifest["layers"]) == len(names)
for name, descriptor in zip(names, manifest["layers"]):
    source = inputs / (name + ".tar.gz")
    digest = sha256(source)
    assert descriptor["digest"] == "sha256:" + digest, name
    assert descriptor["size"] == source.stat().st_size, name
    assert descriptor["mediaType"] == "application/vnd.oci.image.layer.v1.tar+gzip", name
    assert sha256(layout / "blobs/sha256" / digest) == digest, name
print(json.dumps({"layout": layout.name, "manifest": "sha256:" + manifest_digest, "layers": names, "compressed_bytes_verified": True}))
