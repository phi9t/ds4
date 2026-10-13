# Choose The Artifact Boundary

Type: grilling
Status: resolved
Blocked by:
Parent: ../map.md
Labels: wayfinder:grilling

## Question

What exact DS4 artifact is this pipeline supposed to move from local build to
Colab A100 execution: the current repository commit built by the Bazel/CUDA 13.2
rootfs, the historical `fc80bd6`/CUDA 13.0 A100 OCI profile, or a named release
branch/tag? The answer must name the candidate identity, included binaries,
CUDA/rootfs contract, build flags, and what counts as the immutable artifact
boundary before packaging begins.

## Answer

The pipeline target is the current DS4 repository commit selected at packaging
time, starting from `main` unless a later ticket names a release branch or tag.
The first candidate while charting this route is
`82d8806546961dabb200a0c955b1e66cfb949b03`.

Build identity is the repo-local CUDA production path:

- Build wrapper: `scripts/ds4`.
- Build command family: `scripts/ds4 bazel -- build --config=cuda ...` with an
  A100-compatible CUDA architecture selection. The current `--config=cuda`
  default is B200-oriented `compute_100:sm_100`, so the A100 pipeline must add a
  `compute_80:sm_80` override or dedicated `cuda-a100` config before publishing
  GPU experiment artifacts.
- Rootfs contract: `scripts/rootfs/contract.env`, schema 2, Linux x86_64,
  NVIDIA CUDA `13.2.0-devel-ubuntu24.04` pinned by digest, Bazel `9.2.0`,
  CUDA channel `cu132`, driver floor `580.0`.
- CUDA architecture: Colab A100 requires `sm_80`-compatible code. A B200-only
  `sm_100` binary is not an acceptable A100 experiment artifact.
- Included payload binaries: `ds4`, `ds4-server`, `ds4-bench`, `ds4-eval`, and
  `ds4-agent`.

The immutable artifact boundary is the tuple of Git commit SHA, rootfs contract
identity, Bazel/CUDA configuration, selected output binaries, binary checksums,
and packaged rootfs layer digests. The historical `fc80bd6`/CUDA 13.0 A100 OCI
profile remains a working transport precedent and evidence source, but it is not
the target artifact for the A100 experiment pipeline.
