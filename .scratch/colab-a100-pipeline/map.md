# Codify DS4 Colab A100 Pipeline

Labels: wayfinder:map

## Destination

A reviewed implementation spec for a CUDA-only DS4 pipeline that builds the
chosen DS4 candidate locally, packages an Insula-executable OCI rootfs, publishes
immutable GHCR artifacts, verifies no-rebuild execution on CPU Colab, then
launches an A100 Colab runtime and runs the selected experiments with retained
evidence.

## Notes

- Follow `CONSTITUTION.md`, `AGENTS.md`,
  `docs/agents/evidence-bound-method.md`, and `docs/agents/task-runs.md`.
- Use DS4 vocabulary and preserve DS4 boundaries: production CUDA path, CPU
  reference only as debug/oracle, model weights outside rootfs, no generic GGUF
  runner expansion.
- The historical `scripts/rootfs/a100_oci` profile and
  `docs/rootfs/colab-oci` evidence are useful precedent, but its
  `fc80bd6`/CUDA 13.0 identity is distinct from the current DS4 Bazel/CUDA 13.2
  engine.
- The CPU Colab gate should be no-rebuild by default: restore the rootfs, enter
  through the Insula-style launcher, and run packaged payload checks. Full
  rebuild/composition is release validation, not the normal run path.
- Registry publication, Google Colab GPU allocation, model download, push, and
  merge are external/promotional effects. They require explicit authorization in
  execution tickets.
- Credentials stay outside Git and outside images. Use the smallest practical
  token scope for each phase, and never print token contents.

## Decisions so far

- [Default Colab Worker To No-Rebuild Run](../colab-oci-rootfs/issues/03-default-no-rebuild-colab-run.md) — CPU Colab should consume a restored rootfs and run prebuilt payload; rebuild/composition remains explicit release validation.
- [Choose The Artifact Boundary](issues/01-choose-artifact-boundary.md) — Package the current DS4 repository commit selected at pipeline invocation, built by the repo-local Bazel/CUDA 13.2 rootfs for Colab A100; the historical A100 OCI profile is precedent only.
- [Define The Local Build Receipt](issues/02-define-local-build-receipt.md) — A packageable candidate needs an A100-compatible CUDA Bazel build of all five binaries, rootfs/build metadata, build IDs/checksums, and smoke evidence captured outside secrets.
- [Choose The Rootfs Topology](issues/03-choose-rootfs-topology.md) — Publish one current-source build-capable Insula rootfs image first; let GHCR tag/digest identify the packed image, keep weights external, and avoid runtime/build/seed splits unless a later bottleneck demands them.
- [Define The GHCR Publication Contract](issues/04-define-ghcr-publication-contract.md) — Push one private `ghcr.io/phi9t/ds4-current-rootfs` image by tag, record the immutable digest in release.json, and keep credentials outside Git/images.
- [Define The CPU Colab Admission Gate](issues/05-define-cpu-colab-admission-gate.md) — CPU Colab restores the digest-pinned image and runs packaged payload/toolchain/read-only checks through bwrap without rebuilding.
- [Define The A100 Experiment Protocol](issues/06-define-a100-experiment-protocol.md) — A100 Colab restores the same image, projects NVIDIA devices/driver libraries through `launch_insula.py --gpu`, checks driver floor/A100 shape, and runs optional bounded generation when weights are staged.
- [Define Evidence And Promotion Gates](issues/07-define-evidence-and-promotion-gates.md) — Git keeps scripts/docs/tracker and compact evidence; `.ds4`/GHCR/Colab keep bulky images, credentials, and live logs.
- [Write The Execution Spec And Script Tickets](issues/08-write-execution-spec-and-script-tickets.md) — Current pipeline is codified in `docs/rootfs/colab-oci/CURRENT_PIPELINE.md` plus `current_*` scripts.

## Not yet specified

- The full experiment list, model prompt/data inputs, and output schema beyond
  the default bounded generation smoke for the A100 phase.
- The model-weight source, cache/mount location, integrity checks, and cleanup
  policy once the experiment protocol is chosen.
- A100 Colab runtime budget, retry policy, and stop/cleanup automation after the
  initial GPU gate.
- How this pipeline should sequence with the later CUDA-only upstream sync.

## Out of scope

- Apple Metal, AMD/ROCm kernels, or generic GGUF runner support.
- Treating CPU Colab restore/execution as GPU inference validation.
- Publishing with broad, long-lived, or repository-embedded credentials.
- Changing DS4 inference semantics while this map is only deciding the pipeline.
