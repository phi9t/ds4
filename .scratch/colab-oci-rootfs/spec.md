# Land the Colab OCI rootfs experiment in DS4

The user approved landing the completed rootfs packaging, CPU Colab proof,
release references, and documentation in DS4. This is integration of a verified
experiment, not migration of the current CUDA 13.2 engine build.

Route: gated delivery. The source and layer design were approved and independently
reviewed in the preceding experiment. Integration gets separate-context review.

## Acceptance

- Own the complete build, publication, restore, launcher and CPU benchmark recipe
  under scripts/rootfs/a100_oci, including its isolated rules_oci Bazel module.
- Include docs, pinned releases and compact historical evidence under docs/rootfs.
- Eliminate mandatory references to another checkout or developer credential path.
- Provide fresh smoke tests for restore, offline composition and path relocation.
- Preserve source fc80bd6, CUDA 13.0/sm_80/x86-64 provenance and historical results.
- Keep engine sources, current rootfs contract and top-level Bazel build unchanged.
- No GPU allocation, model download, registry upload, push or mainline merge.
- Commit the reviewed candidate locally on codex/colab-oci-rootfs.

## Evidence

Historical experiment: colab-ds4-rootfs-20261011/layered, private GHCR package
phi9t/ds4-a100-build-rootfs. Docs distinguish prior live Colab evidence from
fresh repository integration checks. Large blobs, weights, credentials and build
caches stay outside Git.
