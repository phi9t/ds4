# Define The Local Build Receipt

Type: grilling
Status: resolved
Blocked by: 01
Parent: ../map.md
Labels: wayfinder:grilling

## Question

For the chosen artifact boundary, what local commands and captured metadata prove
that the build is ready to package? Decide whether the receipt requires
`scripts/ds4 verify`, a full Bazel build of every DS4 binary, `--build-id`
output, CUDA architecture/driver/rootfs identity, source SHA, and binary
checksums, and where that receipt should live.

## Answer

The local build receipt is the admission record for packaging a DS4 candidate.
It must be generated before any OCI rootfs is assembled or published, and it
must bind the current source, rootfs contract, build configuration, output
binaries, and smoke-test evidence.

Required local commands:

- An A100-specific verification command. The existing `scripts/ds4 verify`
  default is B200 `sm_100`; the implemented A100 mode is
  `scripts/ds4 verify cuda-a100`.
- `scripts/ds4 bazel -- build --config=cuda-a100 //:ds4 //:ds4-server //:ds4-bench //:ds4-eval //:ds4-agent`. This config compiles GPU code for
  `compute_80:sm_80` and host CPU code with portable `-march=x86-64`.
- `scripts/ds4 bazel -- test //tests/...`
- For each produced binary, run `--build-id` where supported and record stdout.

Required metadata:

- Git commit SHA and dirty-tree policy. A publishable receipt must either come
  from a clean tree or include a deterministic patch/checksum snapshot that is
  named as part of the candidate.
- `scripts/rootfs/contract.env` content hash and parsed fields:
  `DS4_ROOTFS_SCHEMA`, `DS4_ROOTFS_ARCH`, `DS4_BASE_IMAGE`,
  `DS4_BAZEL_VERSION`, `DS4_CUDA_VERSION`, `DS4_CUDA_CHANNEL`, and
  `DS4_DRIVER_FLOOR`.
- Bazel version and CUDA config expansion sufficient to show
  `compute_80:sm_80` for A100 artifacts.
- The exact target list: `//:ds4`, `//:ds4-server`, `//:ds4-bench`,
  `//:ds4-eval`, and `//:ds4-agent`.
- SHA256, byte size, and executable mode for each packaged binary.
- The `--build-id` stdout for each binary that supports it. Any binary that
  lacks `--build-id` must be called out in the receipt and justified before it
  can be packaged.
- Verification command exit codes, elapsed time, and retained stdout/stderr
  paths.
- If `ds4_build` still stamps CUDA binaries as `sm_100` after an A100 override,
  implementation must fix the stamp/config before publishing rather than
  weakening the receipt.

Receipt storage:

- The implementation should write the machine-readable receipt to an external
  run directory first, for example
  `$DS4_COLAB_PIPELINE_STATE/build-receipt.json`.
- A compact non-secret summary may be copied into
  `docs/rootfs/colab-a100/evidence/<run-id>/build-receipt.json` after review.
- Build logs, Bazel output bases, caches, model weights, and credentials stay
  outside Git.

Invalidation rule:

- Any change to Git SHA, dirty patch snapshot, `scripts/rootfs/contract.env`,
  `.bazelrc` CUDA configuration, target list, binary bytes, or verification
  command result invalidates the receipt and requires regenerating it before
  packaging.
