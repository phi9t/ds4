# DS4 OCI rootfs and Colab experiments

This directory owns the completed CPU Colab transport/run experiment and
its reproducible recipe. The implementation is in
[scripts/rootfs/a100_oci](../../../scripts/rootfs/a100_oci/README.md).
For the step-by-step Colab operator flow, see
[COLAB_RECIPE.md](COLAB_RECIPE.md).

The published profile pins source `fc80bd695da76ee14bcb86820bf900a5cdfda806`,
CUDA 13.0.3, `sm_80`, and portable `-march=x86-64`. That archived source rebuilds
with Makefiles. DS4's current engine uses Bazel/CUDA 13.2; the nested `rules_oci`
module here handles image packaging only. These are distinct build identities.
The existing engine build, rootfs contract and wrapper remain authoritative for
current source. GPU inference with the trimmed images is still unverified.

## Releases and measured results

[release.json](evidence/release.json) is the immutable final release record for
the private `ghcr.io/phi9t/ds4-a100-build-rootfs` package.

| Bundle | Compressed bytes | CPU Colab restore | Components |
| --- | ---: | ---: | ---: |
| Runtime | 653,761,527 | 37.02 s | 8 |
| Build | 938,251,303 | 63.43 s | 11 |
| Seed | 977,131,374 | 54.75 s with build cache | 12 |

Build includes source, native/CUDA compilers, prebuilt apps, and offline Bazel
packaging dependencies. Seed adds 38,880,071 bytes of compatible objects.
[RESULTS.md](RESULTS.md) explains cold-cache conditions, rebuild measurements,
CU estimates, failures, and limits. The 86.72 GB model weights are separate.
Use a CPU-only Colab instance for transport tests. GPU inference is a later gate.

The current default Colab recipe is the no-rebuild build-rootfs run recorded in
[evidence/cpu-colab-r5](evidence/cpu-colab-r5/README.md): cold restore of the
build image took 62.638 s, then all packaged DS4 binary/toolchain/read-only
checks completed in 1.573 s total. The longer rebuild/composition path is
available as explicit release validation and is recorded in
[evidence/cpu-colab-r3](evidence/cpu-colab-r3/README.md).

## Restore and enter an image

Use Linux amd64 with Python 3.11+, GNU tar, and access to the private package.
Acquire the benchmarked crane binary and prepare a private registry-auth directory.
For a Colab run use a short-lived pull-only token, not the publishing credential.
The CLI honors `DOCKER_CONFIG`; never put credentials into the repository,
Docker context, logs or image layers.

```sh
PROFILE="$PWD/scripts/rootfs/a100_oci"
STATE="/absolute/external/path/ds4-oci-run"
mkdir -p "$STATE"
python3 "$PROFILE/acquire_crane.py" --output "$STATE/crane"
export DOCKER_CONFIG=/absolute/private/registry-auth
# Registry-auth directory mode 0700; config.json mode 0600.
python3 "$PROFILE/layered/restore_layers.py" \
  --release "$PWD/docs/rootfs/colab-oci/evidence/release.json" --image build \
  --cache "$STATE/cache" --rootfs "$STATE/build-root" \
  --logs "$STATE/restore-build" --crane "$STATE/crane"
python3 "$PROFILE/launch_insula.py" \
  --rootfs "$STATE/build-root" --work "$STATE/work" \
  --weights "$STATE/weights" --outputs "$STATE/results" \
  -- /usr/local/cuda/bin/nvcc --version
```

Targets must be new directories; restore fails closed on an existing rootfs.
Downloaded blobs are SHA256-verified while writing, atomically cached, and
validated again before cache reuse. Four concurrent transfers feed crane's
compressed image-tar format. `crane export` handles OCI flattening/whiteouts.
Keep cache files stable while packing; use a separate run/cache per writer.

The minimal bubblewrap launcher follows the Insula execution model. It is not
the Rust Insula CLI or its typed admission protocol. It mounts rootfs/weights
read-only, work/results writable, and isolates networking. It shares host
proc/PIDs and accepts trusted experiment commands only. It uses the rootfs's
own loader and bubblewrap. GPU projection is explicit with `--gpu` and remains
unvalidated for this profile.

Inside build, copy `/opt/ds4/source` into `/work/source` and run:

```sh
cp -aL /opt/ds4/source /work/source
make -C /work/source -j2 cuda CUDA_ARCH=sm_80 NATIVE_CPU_FLAG=-march=x86-64
```

The full `cuda` target forces `-B`. For seed, run
`python3 /opt/ds4/validate_object_seed.py` before copying source. Then touch the
edited source and use the direct `ds4-bench` Make target to reuse compatible
objects. Architecture, source, compiler, flags and object digest mismatches
are rejected by the validator. Make alone does not enforce this check.

## Recompose exact published blobs offline

Restore build first. It supplies `/opt/ds4/bin/bazel` and the vendored
repositories under `/opt/ds4/bazel/vendor`. Copy its immutable project template
from `/opt/ds4/bazel/project` into writable `/work/packaging`. Link each
verified cached blob to `inputs/<component>.tar.gz` using the release record's
ordered `layer_names` and matching `layers[].digest`. The CPU worker demonstrates
this exact mapping and checks the resulting manifest digests.

```sh
DS4_BAZEL_WORK_ROOT=/work/bazel-state /work/packaging/compose-offline.sh
# Optional seed needs objects.tar.gz too:
DS4_BAZEL_WORK_ROOT=/work/bazel-state /work/packaging/compose-offline.sh //:seed_image
```

The command copies vendor metadata into writable storage and disables
repository downloads and repository/disk/remote caches. The launcher enforces
network isolation. Do not ship Bazel output-base state as a portable cache.
Use the project shipped in the image when reproducing historical digests;
new recipe/docs bytes in this checkout define a new tools layer.

## Build and publish a new experiment release

The Dockerfile consumes an externally supplied `ds4-fc80bd6-source.tar.gz` with
SHA256 `1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3`.
The original 16 MB archive remains in the external experiment archive; it is
not duplicated in Git. A current-source build needs a separately qualified
profile and must not claim this archive's identity.

```sh
export DS4_ROOTFS_INPUTS=/absolute/path/build-inputs
export DS4_ROOTFS_STATE=/absolute/path/new-layer-run
mkdir -p "$DS4_ROOTFS_INPUTS" "$DS4_ROOTFS_STATE"
cp "$PROFILE/Dockerfile" "$PROFILE/bundle-manifest.json" "$DS4_ROOTFS_INPUTS/"
# Supply the exact pinned source archive in DS4_ROOTFS_INPUTS.
# Keep the build context free of credentials.
set -o pipefail
docker build -t ds4-a100-build:fc80bd6-cu130 "$DS4_ROOTFS_INPUTS" \
  2>&1 | tee "$DS4_ROOTFS_INPUTS/build-r2.log"
export DS4_BUILDER_IMAGE="$(docker image inspect --format '{{.Id}}' ds4-a100-build:fc80bd6-cu130)"
python3 "$PROFILE/layered/prepare_layers.py"
python3 "$PROFILE/layered/refine_layers.py"
```

Preparation verifies every source member against the pinned archive and selects
components from the builder. It retains licenses, strips application debug
sections, splits the five app blobs, and creates source/compiler/object receipts.
Base apt repositories are not snapshot-pinned, so a fresh Docker build is not
promised byte-identical to the original builder. Its receipts bind the actual
image. Restore from the immutable release for exact historical bytes.

To package Bazel tools, stage verified `/opt/ds4/bin/bazel`, its adjacent license,
and `/opt/ds4/bazel/vendor` from a restored build rootfs into a tools directory
with `bin/bazel`, `bazel.LICENSE`, and `vendor/`. Then:

```sh
python3 "$PROFILE/layered/package_tools.py" \
  --tools /absolute/path/staged-tools --output "$DS4_ROOTFS_STATE/layers/bazel-tools.tar.gz"
cp -a "$PROFILE/layered/bazel" "$DS4_ROOTFS_STATE/bazel"
"$DS4_ROOTFS_STATE/bazel/link-layers.sh" seed
# Use the build rootfs's pinned Bazel/vendor via the documented DS4_BAZEL overrides.
# Compose runtime_image, build_image, and seed_image; retain their layout paths.
```

[The packaging README](../../../scripts/rootfs/a100_oci/layered/bazel/README.md)
lists tool overrides. `package_tools.py` checks the binary pin and excludes caches
and vendor's machine-local `bazel-external` link. The independent module pins
Bazel 9.2.0 and `rules_oci` 2.3.3 acquisition metadata.

For publication set `DS4_OCI_LAYOUTS` to a JSON file mapping `runtime`, `build`,
`seed` to the generated OCI layout directories. Set `DS4_CRANE` to the pinned
binary, `GHCR_TOKEN_FILE` to a mode-0600 publishing credential outside the build
context, and choose **new** `DS4_RELEASE_PREFIX`/`DS4_RELEASE_SUFFIX` tag strings.
Then run `python3 "$PROFILE/layered/publish_layers.py"`. It requires the existing
package to be private before any upload, checks privacy afterward, validates all
blob hashes and records new immutable references in the run's release.json.
Bazel blob symlinks are materialized with hardlinks or copies before crane push.
Do not overwrite the historical tags or evidence records. The older full-image
publisher remains in `publish.py` for the baseline experiment.

## CPU Colab reproduction

Allocate CPU Standard only. The repeatable path is
`python3 scripts/rootfs/a100_oci/make_colab_upload.py --force`, then upload the
resulting `/tmp/ds4-colab-upload.tgz` to Colab and unpack it under `/content`.
The archive contains the layered helper scripts as flat `/content/*.py` files,
plus `launch_insula.py`, `pack_verified_layers.py`, `crane`,
`write_pull_auth.py`, and the chosen release record as `/content/release.json`.
Provide pull-only auth as
`/content/pull-auth.json`, then execute `start_cpu_worker.py`.
`colab_safe.py` wraps the installed Colab CLI and redacts proxy tokens from its
output. The CLI uses the operator's existing Google authorization.

The worker rejects NVIDIA devices, deletes registry auth after acquisition, and
supports two modes. The default `DS4_ROOTFS_TEST_MODE=run` downloads the build
rootfs, then uses the Insula-style launcher to execute the prebuilt DS4 payload
and quick toolchain probes from inside that rootfs. It intentionally skips
remote source rebuilds because the rootfs already supplies the same compiler,
runtime libraries, packages and tools that produced the packaged binaries.

Use `DS4_ROOTFS_TEST_MODE=release-validation` only when revalidating the full
publication profile. That slower mode downloads runtime/build into distinct
cold caches, restores seed against the build cache, rebuilds source without
network, validates/refuses object seeds, composes exact manifests, and proves
the changed-layer set for one source edit. The landed worker also runs the
edited stripped benchmark's `--help` directly. The historical run had that check
as a separate postcheck.

Use `DS4_ROOTFS_TEST_RUN` with a fresh safe run name for another measurement.
Collect `/content/layered-results-<run>.zip` and
`/content/layered-status-<run>.json`, and stop the session afterward.
`start_cpu_worker.py` retains a PID to avoid duplicate concurrent workers.

## Evidence and storage

[evidence/](evidence/) contains final and failed-attempt release records,
selection/object provenance, extracted CPU logs, raw OCI manifests, independent
review and offline builder proofs. Historical logs may name the original builder
paths; those are provenance, not runtime dependencies. Files named
`experiment-artifact-checksums.json` describe the original external archive.
[experiment-guide.md](experiment-guide.md) and `baseline-*` docs retain the
original context. [REVIEW.md](REVIEW.md) records the experiment review.

Git owns code, docs, compact receipts and logs. GHCR owns immutable image blobs.
Model weights, source tar input, binaries, registry credentials and build caches
stay outside Git. The original complete archive is retained at
`colab-ds4-rootfs-20261011` on the operator and builder hosts; the release record
can restore published artifacts independently of those host directories.
Fresh integration checks and their exact scope are in
[integration-results.json](integration-results.json).

## Repository integration checks

Run the portable suite with Python 3.11 or later:

```sh
python3 scripts/rootfs/a100_oci/tests/test_profile.py
```

For real artifact verification, supply component tars, the verified crane client,
and registry auth. This uses a Linux builder with no GPU projection. It restores
from validated cached layers, runs five CLI help checks, compiles and inspects
sm_80 code, reproduces all three historical manifests with the landed module,
and tests portable tools packaging. It records source-file hashes and leaves
its receipt/logs in a new external run directory.

```sh
python3 scripts/rootfs/a100_oci/tests/check_live_profile.py \
  --layers /absolute/path/component-tars --crane /absolute/path/crane \
  --state-parent /absolute/path/validation-runs \
  --docker-config /absolute/private/registry-auth
```

This gate checks artifact packaging and launching. It does not run the current
engine's CUDA 13.2 build/generation suite or claim GPU inference correctness.
