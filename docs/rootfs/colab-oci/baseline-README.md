# DS4 build-rootfs transport experiment

Historical experiment record. Filenames below refer to the retained external
archive or [evidence/](evidence/); use [README.md](README.md) for landed commands.

Built on `devx_b200_dbg`; transfer and rebuild validation use **CPU-only Colab**.

Private OCI payload: `ghcr.io/phi9t/ds4-a100-build-rootfs:fc80bd6-cu130-x86-64-20261011-r2`.
Immutable reference: `ghcr.io/phi9t/ds4-a100-build-rootfs@sha256:f6634afd91ac32e8080ea24b5ae3fc77ed740261255413d16a44d6426c880c3c`.

The payload contains CUDA 13.0 development tools, compiler dependencies, the pinned DS4 source, compiled objects, inference binaries, and CUDA test binaries. It targets `sm_80` and portable `x86-64` CPU instructions. It is an OCI transport for a filesystem: consume with crane and the launcher, rather than relying on Docker image entrypoint/config metadata.

Weights are deliberately a separate artifact. The 86.72 GB GGUF is not in this 4.62 GB compressed image. Inference still requires separately staging weights and enabling GPU projection. GPU execution of this image has not been validated by this CPU transport test.

## Build and publish

The adjacent source archive is pinned by SHA256 in Dockerfile. On the Linux builder, from this directory:

```sh
docker build -t ds4-a100-build:fc80bd6-cu130 .
python3 publish.py
```

`publish.py` uses the existing builder's credential file and `tools/crane`, verifies the pinned CUDA base DiffIDs, reuses compressed base layers, adds the build layers, checks private package visibility, and writes a digest receipt. Credentials are temporary and excluded from image contents. Adapt its explicit host paths/tag for another builder. Never put credentials into build context.

## CPU-only Colab proof

`cpu_restore_test.py` consumes `/content/publication.json` (use publication-r2.json), the verified Linux crane binary at `/content/crane`, `/content/pack_verified_layers.py`, and `/content/launch_insula.py`. Supply a short-lived pull-only GHCR registry token in `/content/ghcr-auth/config.json`, with directory mode 0700 and file mode 0600. The worker removes this authorization after acquisition and on failure. It explicitly rejects `/dev/nvidia0`.

Launch the script in a background subprocess with `DS4_ROOTFS_TEST_RUN=r2` to retain evidence while the CLI disconnects. A named run permits resuming verified blobs; use a fresh name/cache to measure cold transfer. The script writes `/content/cpu-rootfs-status-r2.json` and `/content/cpu-rootfs-results-r2.zip`. It performs four parallel blob downloads with digest checks, verifies raw manifest identity and config bytes, creates a compressed image tar without re-encoding blobs, and uses crane export for correct layer/whiteout flattening. Restore happens in a staging directory before promotion.

`pack_verified_layers.py` follows go-containerregistry's compressed image-tar format. Cached layers are assumed stable after caller verification; do not mutate a cache concurrently with packing. The initial crane-pull baseline and the optimized run use different empty caches.

## Run and rebuild

```sh
python /content/launch_insula.py \
  --rootfs /content/ds4-rootfs-r2 \
  --work /content/experiment \
  --weights /content/model-cache \
  --outputs /content/results \
  -- /usr/local/cuda/bin/nvcc --version
```

This proof uses a minimal bubblewrap launcher following the Insula execution model. It does not yet use the existing Insula Rust CLI's typed contract admission or canonical receipt schema. The launcher uses the rootfs's own loader and bubblewrap. Rootfs and weights are read-only; work and outputs are writable. Colab permits user/mount/network isolation but denied a fresh proc mount in this trial, so the launcher projects the host proc filesystem read-only and shares the host PID namespace. It shares the kernel and is not a hostile-code security boundary. This variant exposes host process metadata and must run only trusted experiment commands. Network is isolated. CPU is the default; `--gpu` explicitly projects NVIDIA devices and host driver libraries for later inference testing.

To change DS4, copy `/opt/ds4/source` into `/work/source` inside the launcher, then run `make -C /work/source ... CUDA_ARCH=sm_80 NATIVE_CPU_FLAG=-march=x86-64`. This keeps immutable source/build artifacts reusable while experiments write into their own workspace. The CPU proof compiles a fresh CUDA cubin offline, inspects its sm_80 SASS, forces an incremental DS4 benchmark rebuild, and checks the resulting CLI.

## Storage implications

Keep source/toolchain/build layers separately versioned from GGUF weights. Digest pinning makes registry blobs reusable across revisions; an update here uploaded only new layers. Fresh Colab machines still need the full cold download. Persisting a cache elsewhere does not make Colab local disk persistent. Future weights storage should support chunked/resumable transfer and verify bytes while downloading to avoid a separate full 86.72 GB reread. CPU transfer time is measured here; it should not be substituted directly for A100 disk/CPU timings.
