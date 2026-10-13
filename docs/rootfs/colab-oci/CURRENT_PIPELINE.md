# Current DS4 Colab A100 Pipeline

This recipe packages the current DS4 checkout as one CUDA 13.2, Bazel-built,
Insula-executable rootfs image for Google Colab. It is separate from the
historical `fc80bd6` CUDA 13.0 layered experiment documented elsewhere in this
directory.

The normal Colab path does not rebuild on the remote host. Build locally inside
the repo rootfs, inject the verified Bazel outputs into the rootfs image, push
that image to GHCR, restore it on Colab, and enter it with the same bwrap-style
execution boundary. Model weights remain outside the image under
`/content/weights`.

## Local Build And Package

Rebuild the rootfs whenever `scripts/rootfs/contract.env` changes:

```sh
scripts/rootfs/build_rootfs.sh --rebuild
```

Build the A100 binaries and import a local Docker image:

```sh
python3 scripts/rootfs/a100_oci/current_package.py
```

The script runs `bazel build --config=cuda-a100` inside
`scripts/rootfs/enter_rootfs.sh`, stages `ds4`, `ds4-server`, `ds4-bench`,
`ds4-eval`, and `ds4-agent`, checks `--build-id` for `backend=cuda arch=sm_80`,
and writes a candidate receipt under `.ds4/colab-current/<run>/`.
`--config=cuda-a100` compiles GPU code for `sm_80` and uses portable
`-march=x86-64` for host CPU code so the binaries can launch on Colab CPUs.
For a release artifact, run it from the committed pipeline revision so the
receipt's `tracked_git_dirty` field is false.

Use `--no-import` for a fast receipt/staging smoke that does not create a Docker
image.

## Publish

Use a GHCR token from a mode-0600 file outside the repo. The script writes a
temporary Docker config and never embeds credentials in the image:

```sh
export GHCR_TOKEN_FILE=/path/to/mode-0600/ghcr-token
python3 scripts/rootfs/a100_oci/current_publish.py \
  --candidate .ds4/colab-current/latest-candidate.json \
  --owner phi9t \
  --package ds4-current-rootfs
```

The release record is `.ds4/colab-current/<run>/release.json`. It records the
GHCR tag, immutable digest reference, compressed layer descriptors, build IDs,
binary hashes, rootfs contract identity, and the SHA256 of
`/opt/ds4/bundle-manifest.json`. The GHCR digest is the retrieval handle.

The script refuses to push over an already-public package unless
`--skip-private-check` is passed. After push, it checks that the package is still
private.

## Colab Upload

Create the flat helper bundle from the release record:

```sh
python3 scripts/rootfs/a100_oci/make_current_colab_upload.py \
  --release .ds4/colab-current/<run>/release.json \
  --force
```

Upload `/tmp/ds4-current-colab-upload.tgz` to Colab and unpack it:

```python
!tar -xzf /content/ds4-current-colab-upload.tgz -C /content
```

Then provide a pull-only GHCR token:

```python
import getpass, subprocess, sys

user = input("GHCR username: ")
token = getpass.getpass("GHCR pull token: ")
subprocess.run(
    [sys.executable, "/content/write_pull_auth.py",
     "--username", user, "--token-stdin"],
    input=token + "\n",
    text=True,
    check=True,
)
```

## CPU Admission Gate

Run this first on a CPU Standard runtime:

```python
import os, subprocess, sys

os.environ["DS4_CURRENT_COLAB_RUN"] = "cpu1"
os.environ["DS4_CURRENT_COLAB_MODE"] = "cpu"
subprocess.run([sys.executable, "/content/start_current_worker.py"], check=True)
```

Follow progress and collect evidence:

```python
!tail -f /content/current-worker.log
!cat /content/current-status-cpu1.json
```

Passing CPU admission means:

- The digest-pinned GHCR image restored and matched its manifest.
- Registry auth was deleted after acquisition.
- The restored rootfs contained `/usr/bin/bwrap`, CUDA 13.2 `nvcc`, the five DS4
  binaries, `bundle-manifest.json`, and `binaries.sha256`.
- The worker entered the rootfs through `launch_insula.py`.
- Packaged binary help checks, `--build-id`, `nvcc --version`, and read-only
  rootfs checks passed.
- No source rebuild ran on Colab.

Retain `/content/current-status-<run>.json` and
`/content/current-results-<run>.zip`.

## A100 Gate

Start a fresh A100 Colab runtime, unpack the same helper bundle, provide
pull-only auth again, and stage weights under `/content/weights` if generation
is part of the experiment. The default model filename is
`/content/weights/ds4flash.gguf`; override it with `DS4_CURRENT_COLAB_MODEL`.

```python
import os, subprocess, sys

os.environ["DS4_CURRENT_COLAB_RUN"] = "a1001"
os.environ["DS4_CURRENT_COLAB_MODE"] = "gpu"
subprocess.run([sys.executable, "/content/start_current_worker.py"], check=True)
```

The GPU worker requires `/dev/nvidia0`, checks that `nvidia-smi` reports an A100
unless `DS4_CURRENT_COLAB_ALLOW_NON_A100=1`, checks the driver version against
the rootfs contract floor, enters the restored rootfs with `--gpu`, and repeats
the packaged binary/toolchain/read-only checks. If the model file exists, it
runs a bounded greedy generation smoke:

```sh
/opt/ds4/bin/ds4 --cuda -m /weights/ds4flash.gguf -n 8 --temp 0 \
  -p "The capital of France is"
```

Set `DS4_CURRENT_COLAB_TOKENS` and `DS4_CURRENT_COLAB_PROMPT` to adjust the
smoke. If weights are absent, GPU setup still records a pass for restore,
driver projection, and binary launch, with generation marked skipped.

Always stop the Colab session after collecting evidence.

## Host Convenience

If the Colab CLI is authenticated, the host auth helper can upload the pull auth
and start the current worker without putting the token on a command line:

```sh
python3 scripts/rootfs/a100_oci/provide_colab_auth.py \
  --session ds4-cpu-current \
  --username "$GHCR_USER" \
  --token-file "$GHCR_TOKEN_FILE" \
  --start-worker \
  --worker current \
  --run-name cpu1 \
  --mode cpu
```

Use `--mode gpu` and an A100 session name for the GPU gate.
