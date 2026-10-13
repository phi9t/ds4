# CPU-only GHCR rootfs results — 2026-10-11

Historical experiment record. Filenames below refer to the retained external
archive or [evidence/](evidence/); use [README.md](README.md) for landed commands.

Private image: `ghcr.io/phi9t/ds4-a100-build-rootfs@sha256:f6634afd91ac32e8080ea24b5ae3fc77ed740261255413d16a44d6426c880c3c`.

Built on devx_b200_dbg; downloaded on Colab CPU Standard (13 GB RAM, no NVIDIA device). Image contains CUDA 13.0 build toolchain, DS4 source/objects/binaries targeting sm_80 and x86-64. Weight files are separate.

| Measured step | Seconds |
|---|---:|
| Cold parallel download + compressed-blob SHA256 verification (4.62 GB, zero cached layers) | 159.49 |
| Acquire/verify pinned manifest and config | 0.61 |
| Direct package verified compressed layers | 32.28 |
| Export/flatten/extract rootfs | 221.05 |
| Cold restore subtotal | 413.44 |
| Repeat cached package (separate benchmark) | 42.05 |
| Fresh offline CUDA sm_80 compilation | 2.13 |
| Copy source and objects to writable work directory | 9.81 |
| Forced incremental DS4 benchmark rebuild | 2.39 |
| Rebuilt benchmark CLI help | 2.68 |

Cold restore subtotal is 6.89 minutes and excludes the extra repeat-pack benchmark and validation workloads. At the observed CPU rate of 0.08 CU/hour it corresponds to about 0.0092 CU; this is a rate-derived estimate, not a per-step meter reading.

The earlier CPU baseline used crane pull: download/verify 150.59 s, cached packaging 189.58 s, extraction 196.15 s, totaling 536.32 s (8.94 minutes). Direct compressed-layer packaging measured 32.28 s; total restore fell to 6.89 minutes, approximately 23% in these sequential trials. Revisions differed by roughly 16 MB and host cache/CPU conditions were not controlled, so this is a practical observation rather than a rigorous isolated benchmark.

The rebuild revision took 35.51 s to docker-save and 25.02 s for crane append/push using previously published layers. That is an update measurement, not a fresh full image upload. The initial full publication push took 181.51 s. GHCR package private visibility was checked after publication.

All seven execution checks passed: nvcc version; fresh sm_80 cubin compilation; SASS inspection; read-only rootfs negative write; copy source/objects to writable workspace; incremental DS4 rebuild; rebuilt CLI help. Run receipts show no GPU projections. The archive also captures compiler command lines, SASS, and CLI output. Source-tamper build and invalid writable projection checks passed separately.

Evidence: cpu-results-r2.zip, cpu-status-r2.json, cpu-baseline-results.zip, publication-r2.json, build-r2.log, publication-r2.log, mount-contract-tests.json, source-pin-negative-test.log.

Limitations: no inference or GPU kernel execution of this rootfs was attempted in this CPU test. The launcher is a minimal Insula-model proof, not integrated with the existing Insula Rust CLI. Colab requires a read-only host proc projection with shared PID namespace here; only trusted experiments are admitted by this proof workflow. Full development rootfs extraction remains the largest CPU restore step. The 86.72 GB model download and full weight verification costs remain separate; chunked/resumable weights with verification during transfer are the next storage task.
