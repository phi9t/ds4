# CPU Colab OCI no-rebuild run r5

Captured on 2026-10-12 from Google Colab session `ds4-cpu-oci`, hardware
`CPU`, shape `Standard`, after uploading `/tmp/ds4-colab-upload.tgz` built from
the `DS4_ROOTFS_TEST_MODE=run` worker.

The token file lives outside this repository. It is not part of this evidence
and was not present in the downloaded status or result archive.

## Result

- Status: `complete`
- Mode: `run`
- CPU-only guard: `true`
- Remote rebuild: none
- Status JSON: `status.json`
- Downloaded result archive: `/tmp/ds4-colab-r5/layered-results-r5.zip`
- Result archive SHA256:
  `f7614bce9100675d30e3c6690cd7c461de432dae140a13a41f8ae56a6de20704`
- Status JSON SHA256:
  `f483cef9fdad9114b3e2a50c32c9c449e1716a0b029a1ae3015df103c013b0c2`
- Source archive SHA256:
  `1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3`
- Record count: 8
- Return-code mismatches: none

## Restore Summary

| Component | Reference digest | Downloaded bytes | Cached layers | Download + verify | Restore total |
|---|---|---:|---:|---:|---:|
| build | `sha256:863159635b37e2280346657114583eb0835697b8c97cd84366bd2c5a2b8343bc` | 938251303 | 0 | 15.414 s | 62.638 s |

This run uses the build image because it is the rootfs that contains the
compiler toolchain, runtime libraries, dependencies and prebuilt DS4 binaries.
It enters that rootfs with `launch_insula.py` and runs the packaged payload
directly. The 631.031 s `clean-cuda-build` from the r3 validation run is not on
this path.

## Scripted Checks

| Check | Return | Expected | Seconds |
|---|---:|---:|---:|
| build-ds4 | 0 | 0 | 0.219 |
| build-ds4-bench | 0 | 0 | 0.215 |
| build-ds4-server | 0 | 0 | 0.215 |
| build-ds4-eval | 0 | 0 | 0.215 |
| build-ds4-agent | 0 | 0 | 0.215 |
| toolchain-nvcc-version | 0 | 0 | 0.115 |
| toolchain-gcc-version | 0 | 0 | 0.115 |
| readonly-root | 0 | 0 | 0.265 |

After collection, `colab stop -s ds4-cpu-oci` terminated the runtime and
`colab sessions` reported no active sessions.
