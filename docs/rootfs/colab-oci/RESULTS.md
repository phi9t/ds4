# Shared-layer CPU results — 2026-10-11

Historical experiment record. Filenames below refer to the retained external
archive or [evidence/](evidence/); use [README.md](README.md) for landed commands.

Final corrected release is private in `ghcr.io/phi9t/ds4-a100-build-rootfs`, tags `fc80bd6-cu130-layered-{runtime,build,seed}-20261011-r2`. Immutable references and ordered component names are in release.json.

## Current no-rebuild Colab run

The default Colab worker now runs `DS4_ROOTFS_TEST_MODE=run`: it restores the
build rootfs, enters it through the Insula-style launcher, and executes the
already built DS4 payload from that rootfs. It does not rebuild DS4 on the Colab
host. Fresh CPU Standard evidence is in
[evidence/cpu-colab-r5](evidence/cpu-colab-r5/README.md):

- Build rootfs cold restore: 62.638 seconds, 938,251,303 bytes downloaded, 0
  cached layers.
- Inside-rootfs checks after restore: 1.573 seconds total across all five DS4
  `--help` commands, `nvcc --version`, GCC version, and read-only-root check.
- Status: `complete`, `mode: run`, `no_remote_rebuild: true`, no return-code
  mismatches.

The rebuild and offline OCI composition measurements below are release
validation costs, not the normal Colab run path.

| Image | Compressed payload | Download + streaming SHA256 | Package cached raw blobs | Extract + verify | Restore total including metadata |
|---|---:|---:|---:|---:|---:|
| runtime | 653.76 MB | 14.77 s | 2.20 s | 19.13 s | 37.02 s |
| build | 938.25 MB | 17.34 s | 8.33 s | 36.83 s | 63.43 s |
| seed | 977.13 MB | 4.48 s | 4.68 s | 44.57 s | 54.75 s |

Runtime and build used distinct empty acquisition caches. Seed reused all 11 verified build layers and downloaded only 38.88 MB of compiled objects. Its restore total still includes repacking/extracting the complete seeded rootfs; it is not a cold-download measurement.

The previous full-development image was 4,624.66 MB and took 413.44 seconds to restore on CPU Colab. Final build payload is 79.71% smaller. Observed final build restore is 63.43 seconds, about 6.5 times faster in these trials. Allocated sessions and network/cache conditions were not controlled, and the new client hashes during download instead of doing an extra read. This establishes actual payload size and useful observed launch times, not a rigorously isolated speedup attributable only to layer count. All tests used CPU Standard, no NVIDIA device or driver projection.

At the observed 0.08 CU/hour CPU rate, 63.43 seconds corresponds to approximately 0.0014 CU. This is a rate-derived estimate; individual phases were not separately metered. It must not be substituted directly for A100 setup cost.

## Rebuild and composition evidence

- Clean offline full CUDA build, with zero source-tree objects initially: 644.12 seconds, or 10.74 minutes.
- Copy a compatible seed into a writable workspace: 6.05 seconds. Seed validation: 1.07 seconds.
- Forced benchmark-source incremental rebuild using direct Make target: 2.13 seconds. The CUDA kernel objects were not recompiled.
- Actual isolated benchmark edit/rebuild: 1.37 seconds. The edit adds an unused named constant; it changes ELF bytes without modifying inference logic.
- First offline Bazel composition inside the delivered build rootfs: 51.57 seconds. It produced exactly the published runtime/build manifest digests.
- Edited offline Bazel composition: 20.35 seconds. Source, benchmark executable, and identity/checksum metadata are the only changed build blobs; eight other blobs are identical. Runtime changes only benchmark and metadata. The candidate remains unpublished.

The benchmark binary's compressed layer is 27.11 MB, versus 135.98 MB for all five application layers. An application-only change can therefore retain the other four application blobs instead of republishing the aggregate. Source adds approximately 16.09 MB; metadata is tiny. Registry/client cache reuse requires the blobs still to be available.

All 22 scripted checks passed, including five runtime-only loader checks with compiler/source absent, fresh sm_80 CUDA compilation and SASS inspection, a read-only-root negative write, a clean source rebuild, mismatch refusal for sm_100, seed reuse, and baseline/edited OCI descriptor assertions. A separate postcheck executed the edited stripped CLI successfully. Source/toolchain flags remain the original fc80bd6/CUDA13.0/sm_80/x86-64 benchmark contract. The current DS4 Bazel engine build was not migrated; Bazel here handles image packaging.

Independent spec/quality review and two fresh offline read-only builder compositions are recorded in REVIEW.md and bazel/proofs/r2. Actual Bazel 9.2.0 and rules_oci 2.3.3 are pinned. No Bazel output-base state or original developer checkout is required by the shipped bundle.

## Retained attempts and limits

The first layered trial restored and loaded successfully, then failed SASS inspection because cuobjdump needs nvdisasm. The corrected compiler adds 4.24 MB compressed; a live builder probe and the final Colab probe passed. cpu-first-attempt.zip and release-first-attempt.json preserve that trial; final figures above come from cpu-results-final.zip.

Weight files remain a separate 86.72 GB artifact. No GPU inference or driver-projection test was performed for these trimmed images. The minimal launcher follows the Insula execution model but is not yet the existing Rust Insula CLI. The launcher's host proc/PID exposure means it accepts trusted commands only. The full offline build proof does not imply that every dynamically loaded GPU runtime dependency has been validated.

Evidence: cpu-results-final.zip, verified-results.json, edited-cli-postcheck.json, release.json, selection-receipt.json, seed-manifest.json, path-ownership.json, publication-r2.log and bazel/proofs/r2.
