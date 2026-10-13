# Define The CPU Colab Admission Gate

Type: grilling
Status: resolved
Blocked by: 03, 04
Parent: ../map.md
Labels: wayfinder:grilling

## Question

What must a CPU Standard Colab session prove before the pipeline may spend A100
time? Decide the no-rebuild checks, expected status schema, auth deletion check,
artifact downloads, timeout/retry rules, and whether the gate uses the build
rootfs, runtime rootfs, or both.

## Decision

Use the current single rootfs image. The CPU admission worker runs
`DS4_CURRENT_COLAB_MODE=cpu` through
`scripts/rootfs/a100_oci/start_current_worker.py`. It rejects GPU devices,
restores `images.current` from `release.json` by digest, verifies the restored
bundle hash, deletes `/content/ghcr-auth` after acquisition, and runs all checks
through `launch_insula.py`.

Required checks: `/usr/bin/bwrap`, CUDA 13.2 `nvcc`, the five DS4 binaries,
`bundle-manifest.json`, `binaries.sha256`, app `--help`, `ds4 --build-id`,
`ds4-server --build-id`, `nvcc --version`, and a read-only `/opt/ds4` probe.
The gate records `/content/current-status-<run>.json` and
`/content/current-results-<run>.zip`. No Colab source rebuild is allowed in this
mode.
