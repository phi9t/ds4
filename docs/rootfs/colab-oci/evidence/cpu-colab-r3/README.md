# CPU Colab OCI release-validation run r3

Captured on 2026-10-12 from Google Colab session `ds4-cpu-oci`, hardware
`CPU`, shape `Standard`, after uploading `/tmp/ds4-colab-upload.tgz` and
starting the worker with:

```sh
python3 scripts/rootfs/a100_oci/provide_colab_auth.py \
  --session ds4-cpu-oci --username phi9t --token-file <repo-external-token> \
  --start-worker --run-name r3
```

The token file lives outside this repository. It is not part of this evidence
and was not present in the downloaded status or result archive.

This run used the full validation behavior that predated the `run` versus
`release-validation` mode split. Its checks match the current
`DS4_ROOTFS_TEST_MODE=release-validation` path, not the faster default no-rebuild
run path.

## Result

- Status: `complete`
- CPU-only guard: `true`
- Status JSON: `status.json`
- Downloaded result archive: `/tmp/ds4-colab-r3/layered-results-r3.zip`
- Result archive SHA256:
  `eff8927fd577ef5846c67515f448ade9c4ded62a5707db865212ae8143808a2d`
- Status JSON SHA256:
  `237f9744bf002453c5e07c6c38e553b8165e6d9befa0b60e8609ad7b5e971919`
- Source archive SHA256:
  `1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3`
- Record count: 23
- Return-code mismatches: none

## Restore Summary

| Component | Reference digest | Downloaded bytes | Cached layers | Download + verify | Restore total |
|---|---|---:|---:|---:|---:|
| runtime | `sha256:2e6ffa03bbe6b22e757554446b921ac32be24386954cb12879f4e524a7505d4c` | 653761527 | 0 | 10.981 s | 36.565 s |
| build | `sha256:863159635b37e2280346657114583eb0835697b8c97cd84366bd2c5a2b8343bc` | 938251303 | 0 | 12.434 s | 74.300 s |
| seed | `sha256:3cf696c2d4ff8578a0caafb54046dfb0f0a9cdee83d8f437ac6845460ec93dbf` | 38880071 | 11 | 5.139 s | 51.266 s |

## Scripted Checks

| Check | Return | Expected | Seconds |
|---|---:|---:|---:|
| runtime-ds4 | 0 | 0 | 2.421 |
| runtime-ds4-bench | 0 | 0 | 0.215 |
| runtime-ds4-server | 0 | 0 | 0.216 |
| runtime-ds4-eval | 0 | 0 | 0.215 |
| runtime-ds4-agent | 0 | 0 | 0.215 |
| compile-sm80 | 0 | 0 | 1.821 |
| inspect-sm80 | 0 | 0 | 0.567 |
| readonly-root | 0 | 0 | 0.519 |
| copy-clean-source | 0 | 0 | 3.877 |
| clean-cuda-build | 0 | 0 | 631.031 |
| clean-rebuilt-help | 0 | 0 | 2.271 |
| validate-object-seed | 0 | 0 | 0.918 |
| refuse-mismatched-seed | 2 | 2 | 0.317 |
| copy-seeded-source | 0 | 0 | 6.095 |
| seeded-incremental-build | 0 | 0 | 2.132 |
| seeded-rebuilt-help | 0 | 0 | 0.266 |
| edit-one-source-rebuild | 0 | 0 | 1.472 |
| edit-strip-binary | 0 | 0 | 0.167 |
| edited-stripped-help | 0 | 0 | 0.215 |
| offline-bazel-compose | 0 | 0 | 49.625 |
| offline-baseline-manifests | 0 | 0 | 0.417 |
| offline-bazel-compose-edited | 0 | 0 | 20.140 |
| offline-edited-manifests | 0 | 0 | 0.368 |

After collection, `colab stop -s ds4-cpu-oci` terminated the runtime and
`colab sessions` reported no active sessions.
