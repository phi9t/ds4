# Colab CPU OCI Run Recipe

This recipe runs the landed DS4 A100 OCI transport proof on Google Colab. It
restores the private GHCR rootfs layers, verifies their digests, enters the
minimal Insula-style sandbox, runs the packaged payload from inside the restored
rootfs, and records reproducible evidence.

Use a CPU Standard Colab runtime. This recipe is not a GPU inference proof; the
worker refuses to start when `/dev/nvidia0` exists. Model weights remain a
separate artifact.

## 1. Build The Upload Bundle Locally

From this repository:

```sh
cd /data02/home/philip.yang/workspace/ds4
python3 scripts/rootfs/a100_oci/make_colab_upload.py --force
```

The command writes `/tmp/ds4-colab-upload.tgz`. It includes:

- `crane`, pinned to go-containerregistry `v0.22.1`.
- `release.json`, copied from `docs/rootfs/colab-oci/evidence/release.json`.
- The restore, launcher, packaging, auth, and CPU worker scripts required under
  Colab's `/content` directory.
- `README-COLAB.txt`, a compact copy of the Colab cells below.

To reuse an already downloaded Linux amd64 crane binary:

```sh
python3 scripts/rootfs/a100_oci/make_colab_upload.py \
  --crane /absolute/path/crane --output /tmp/ds4-colab-upload.tgz --force
```

## 2. Upload And Unpack In Colab

Create a CPU Standard runtime, upload `/tmp/ds4-colab-upload.tgz`, then run:

```python
!tar -xzf /content/ds4-colab-upload.tgz -C /content
!ls -1 /content/{release.json,start_cpu_worker.py,cpu_layered_test.py,crane}
```

## 3. Write Pull-Only GHCR Auth

Use a short-lived pull-only token for `ghcr.io/phi9t/ds4-a100-build-rootfs`.
Do not use a publishing token.

Preferred host-side helper:

```sh
python3 scripts/rootfs/a100_oci/provide_colab_auth.py \
  --session ds4-cpu-oci --username "$GHCR_USER"
```

That command prompts locally for the token, writes a temporary Docker auth file
with mode `0600`, uploads it to `/content/pull-auth.json`, fixes the remote mode
to `0600`, verifies the remote JSON shape, and deletes the temporary local file.
To upload auth and start the worker in one step:

```sh
python3 scripts/rootfs/a100_oci/provide_colab_auth.py \
  --session ds4-cpu-oci --username "$GHCR_USER" \
  --start-worker --run-name r4 --mode run
```

Notebook fallback:

```python
import getpass
import subprocess
import sys

user = input("GHCR username: ")
token = getpass.getpass("GHCR pull token: ")
subprocess.run(
    [
        sys.executable,
        "/content/write_pull_auth.py",
        "--username",
        user,
        "--token-stdin",
    ],
    input=token + "\n",
    text=True,
    check=True,
)
```

The helper writes `/content/pull-auth.json` with mode `0600`. The worker moves
it to `/content/ghcr-auth/config.json` and removes that auth directory when the
run finishes or fails.

## 4. Start The CPU Worker

Pick a fresh lowercase/digit/hyphen run name:

```python
import os
import subprocess
import sys

os.environ["DS4_ROOTFS_TEST_RUN"] = "r4"
os.environ["DS4_ROOTFS_TEST_MODE"] = "run"
subprocess.run([sys.executable, "/content/start_cpu_worker.py"], check=True)
```

The starter records `/content/layered-worker.pid` and will not start a duplicate
worker if one is already running. `run` is the default mode: it restores the
build rootfs and runs the already built DS4 binaries through the Insula-style
launcher. It does not rebuild on the Colab host.

## 5. Watch And Collect Results

```python
!tail -f /content/layered-worker.log
```

When the worker finishes:

```python
!cat /content/layered-status-r4.json
!ls -lh /content/layered-results-r4.zip
```

Download the evidence:

```python
from google.colab import files

files.download("/content/layered-status-r4.json")
files.download("/content/layered-results-r4.zip")
```

Stop the Colab runtime after collecting the files.

## Expected Fast Run Checks

The worker:

- Rejects GPU runtimes by checking `/dev/nvidia0`.
- Downloads and verifies the build image.
- Deletes registry auth after acquisition.
- Runs all five packaged DS4 CLI `--help` checks from inside the restored
  rootfs.
- Checks the rootfs-provided `nvcc` and GCC toolchain versions.
- Confirms the restored rootfs is read-only.

## Optional Release-Validation Mode

Use the slower release-validation mode when rechecking publication integrity,
object-seed compatibility, or offline OCI composition:

```sh
python3 scripts/rootfs/a100_oci/provide_colab_auth.py \
  --session ds4-cpu-oci --username "$GHCR_USER" \
  --start-worker --run-name rv1 --mode release-validation
```

That mode:

- Downloads runtime and build images into distinct cold caches.
- Restores seed from the build cache and downloads only object-seed deltas.
- Compiles and inspects an `sm_80` CUDA cubin.
- Rebuilds pinned source without network.
- Validates compatible object seeds and rejects an `sm_100` mismatch.
- Rebuilds one edited benchmark from the seed and verifies changed OCI layers.
- Re-composes exact runtime/build manifests offline with the shipped Bazel
  module.

## Troubleshooting

- `CPU-only worker required`: switch the Colab runtime to CPU Standard.
- `Worker already running`: tail `/content/layered-worker.log` or delete the
  stale PID only after checking `/proc/<pid>/cmdline`.
- Auth or manifest fetch failures: create a fresh pull-only token and rerun the
  auth cell. The token must read the private GHCR package.
- Existing root/cache path failures: choose a new `DS4_ROOTFS_TEST_RUN` value or
  restart the Colab runtime.
- Missing `/content/crane`: rebuild the upload bundle or upload the pinned crane
  binary separately.

## Local Sanity Check

Before uploading, run the portable profile tests from the repository:

```sh
python3 scripts/rootfs/a100_oci/tests/test_profile.py
git diff --check
```
