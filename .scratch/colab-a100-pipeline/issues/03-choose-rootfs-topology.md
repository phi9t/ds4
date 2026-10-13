# Choose The Rootfs Topology

Type: grilling
Status: resolved
Blocked by: 01, 02
Parent: ../map.md
Labels: wayfinder:grilling

## Question

What OCI/rootfs topology should the codified pipeline publish for Colab: one
build-capable image, separate runtime/build images, optional object/cache seed
images, or another split? The answer must define which CUDA-only files are
included, which artifacts stay external, how the rootfs remains
Insula-executable with `bwrap`, and how Apple Metal or AMD/ROCm content stays
out of the package.

## Answer

Use one current-source, build-capable Insula rootfs image for the first
codified Colab A100 pipeline.

Rationale:

- The normal remote path should not rebuild DS4. It should restore the image,
  enter it with the Insula-style `bwrap` launcher, and run the prebuilt payload.
- Keeping the rootfs build-capable is acceptable for now because it makes the
  Colab execution environment match the local build environment: compiler
  toolchain, CUDA runtime libraries, system packages, `bwrap`, Python and helper
  tools are all present.
- Avoid the historical runtime/build/seed split for the first current-source
  pipeline. That split is useful precedent, but it adds publication and
  validation machinery before the A100 experiment loop needs it.
- Do not create a separate object/cache seed image initially. Bazel proves the
  local build; Colab consumes the already built rootfs.

Image contents:

- Include the CUDA 13.2 rootfs/toolchain needed by `scripts/rootfs/contract.env`
  and the Insula/bubblewrap execution path.
- Include the five A100-compatible DS4 binaries: `ds4`, `ds4-server`,
  `ds4-bench`, `ds4-eval`, and `ds4-agent`.
- Include compact build metadata: local build receipt, binary checksums, rootfs
  contract identity, source Git SHA, and build-id outputs.
- Include only helper scripts needed to restore, enter, inspect and run the
  rootfs from Colab.

External artifacts:

- Model weights, prompts/datasets, Bazel output bases, transient caches, run
  outputs and credentials stay outside the image.
- GHCR authentication is mounted or supplied at restore time only, then removed.

CUDA-only rule:

- The package must be A100-compatible, which means `sm_80` support is required
  even though this repo's current default CUDA config is B200 `sm_100`.
- Do not package Apple Metal or AMD/ROCm kernels, libraries, build outputs or
  optional runtime dependencies.
- Source may be retained for provenance or debugging only if packaging filters
  out non-CUDA backend artifacts and the receipt makes clear that remote
  rebuild is not part of the normal Colab run.

Container identity:

- Do not over-engineer the packed image identity. Once Bazel has produced the
  candidate and the image has been pushed, use the GHCR tag and digest reported
  by that push as the retrieval handle.
- The release record should preserve that tag/digest and the build receipt, but
  it does not need to re-prove every Bazel action.
