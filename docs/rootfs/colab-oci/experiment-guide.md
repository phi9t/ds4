# Shared DS4 rootfs layers

Historical experiment record. Filenames below refer to the retained external
archive or [evidence/](evidence/); use [README.md](README.md) for landed commands.

Private package: `ghcr.io/phi9t/ds4-a100-build-rootfs`.

| Tag suffix, after `fc80bd6-cu130-layered-` | Compressed payload | Layers | Purpose |
|---|---:|---:|---|
| `runtime-20261011-r2` | 653,761,527 bytes | 8 | Prebuilt applications and runtime libraries |
| `build-20261011-r2` | 938,251,303 bytes | 11 | Runtime plus source, compiler, Bazel and offline packaging dependencies |
| `seed-20261011-r2` | 977,131,374 bytes | 12 | Build plus a compatible optional compiled-object seed |

Restore by the immutable references in release.json. Every runtime blob is also present in build; every build blob is also present in seed. These manifests share OS, CUDA libraries and five independently packaged application binaries. The seed adds only 38,880,071 bytes. A build image still downloads all its referenced layers; runtime selection is a different manifest.

## Contract

Source archive is the benchmarked fc80bd6 snapshot, SHA256 `1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3`. Compiler/runtime are from the pinned CUDA 13.0 development rootfs, targeting sm_80 and portable x86-64. That snapshot rebuilds with Makefiles. Bazel 9.2.0 and rules_oci 2.3.3 compose the OCI images; the current DS4 checkout's CUDA13.2/sm100 build system was not modified. Exact compiler/tool/source/object identities are retained in the selection and seed receipts.

The publisher checks package privacy before upload and afterward. No credential is included in the images. The weight GGUF remains a separate artifact. No GPU inference was attempted during this CPU transport/rebuild test; loading dynamically selected GPU dependencies remains a later functional check.

## Files and layer ownership

- `prepare_layers.py`: validates the source snapshot against the pinned source archive, selects files from the exact builder image, strips debug sections from application copies, creates deterministic gzip tars, and retains licenses.
- `refine_layers.py`: removes excluded profiler/GDS aliases, separates the five application blobs, and binds the optional object seed to source/compiler/flags/object digests.
- `bazel/`: pinned rules_oci composition, offline vendored dependencies, fixture/real proofs, and layer-byte verification commands. The actual verified Bazel binary and vendor tree are in the build image's `bazel-tools` layer.
- `publish_layers.py`: materializes Bazel's symlinked OCI layouts into private regular-file release views using hardlinks where possible, then pushes exact blobs with crane. The v0.22.1 crane OCI reader rejects symlinked blobs.
- `restore_layers.py`: verifies the pinned manifest, downloads four blobs concurrently, hashes while writing, validates cached blobs, packages raw compressed bytes, and atomically promotes a verified flattened rootfs.
- `cpu_layered_test.py`: live CPU proof with a default no-rebuild run mode for restored prebuilt payload execution, plus an explicit release-validation mode for cold runtime/build acquisition, clean offline CUDA compilation, seed mismatch refusal, incremental rebuild, offline Bazel composition, and an isolated source edit's exact changed-layer set.

Path ownership is explicit. Directory headers can repeat with identical metadata; non-directory files have one component owner. No lower-layer deletion whiteouts hide development bytes. Test executables, Nsight, CUDA compatibility drivers, unused CUDA libraries and redundant source-tree executable copies are absent from default images. Source-tree application links point to the single canonical prebuilt copies and are followed into the writable experiment workspace when rebuilding.

## Run and rebuild

Restore release.json's chosen image with restore_layers.py and the adjacent pinned crane/pack_verified_layers.py client. The Colab worker demonstrates the complete invocation. The launcher is the existing minimal bubblewrap proof in the parent artifact directory; it follows the Insula model but does not integrate the existing Rust Insula CLI. It projects rootfs/weights read-only and work/results writable, shares host proc/PIDs, isolates networking, and accepts trusted experiment commands. GPU projection is opt-in and untested for these trimmed images.

Within a build rootfs, copy source into a new workspace, then compile:

```sh
cp -aL /opt/ds4/source /work/source
make -C /work/source -j2 cuda CUDA_ARCH=sm_80 NATIVE_CPU_FLAG=-march=x86-64
```

That full `cuda` target forces `-B`. For the seeded image, verify cache compatibility before copying source and use direct targets for incremental reuse:

```sh
python3 /opt/ds4/validate_object_seed.py
cp -aL /opt/ds4/source /work/source
touch /work/source/ds4_bench.c
make -C /work/source -j2 ds4-bench CUDA_ARCH=sm_80 NATIVE_CPU_FLAG=-march=x86-64
```

The seed validator refuses a different CUDA architecture, CPU flag, source archive, Makefile/compiler bytes or object bytes. Run it before reuse; raw Make commands do not themselves enforce this check. A seed is a performance aid; the build bundle must also compile without it.

## Offline OCI composition

Copy `/opt/ds4/bazel/project` into a writable `/work/packaging` and hardlink the verified downloaded layer blobs into `inputs/<component>.tar.gz` according to release.json's layer_names. Those blob files are already in the acquisition cache; they do not need another download or copies inside the rootfs.

```sh
DS4_BAZEL_WORK_ROOT=/work/bazel-state /work/packaging/compose-offline.sh
```

The script copies the immutable packaged vendor tree into writable storage and disables repository downloads, repository cache, disk cache and remote cache. Default targets are runtime/build; objects are optional until seed_image is explicitly selected. `/work/bazel-state` keeps output symlinks meaningful across separate launcher invocations. Never bundle Bazel output-base state as a portable cache.

The recipe was tested twice from fresh output roots with a read-only root/vendor and no network. Exact manifests and compressed blob descriptors matched. Colab evidence additionally checks the actual delivered rootfs and recompiled source edit. For a real new release, update source/patch provenance and binary checksums together; the source-edit test does so for its private, unpublished candidate.

## Builder reproduction and evidence

Preparation consumes the exact existing Linux builder image ID recorded by selection-receipt.json, plus the adjacent pinned source archive. On this builder, run prepare_layers.py into an empty layer destination, then refine_layers.py. The pinned Bazel/vendor acquisition record is in bazel/acquisition.json; final tools archive SHA256 is `529ec429a6d55325545b91368bd23446e0016d039f699717f4c262be8a6b84cd`. Use bazel/link-layers.sh and compose-offline.sh against those immutable inputs, then publish_layers.py with the builder's existing credential configuration. Paths are explicit; this artifact does not depend on a live DS4 checkout.

Failed extraction attempt evidence is retained remotely in attempt-extraction-1. Unanchored tar exclusions initially dropped nested C headers. Anchoring exclusions restored them; a real clean CUDA build then passed. Private-publication preflight, runtime-only loader checks, writable vendor storage and object-seed compatibility were reviewed independently.
