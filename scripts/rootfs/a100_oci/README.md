# A100 OCI experiment profile

The recipe and CPU benchmark are documented in
[docs/rootfs/colab-oci](../../../docs/rootfs/colab-oci/README.md).

This directory contains two related flows:

- the historical pinned `fc80bd6`/CUDA 13.0/sm_80/x86-64 layered experiment;
- the current DS4 Bazel/CUDA 13.2 Colab pipeline, which packages the repo-local
  rootfs plus locally built A100 binaries and does not rebuild on Colab.

The current pipeline recipe is
[docs/rootfs/colab-oci/CURRENT_PIPELINE.md](../../../docs/rootfs/colab-oci/CURRENT_PIPELINE.md).
The historical profile remains useful precedent and evidence, but it does not
replace DS4's current Bazel/CUDA 13.2 build or rootfs contract.

Requires Linux amd64 and Python 3.11 or later. Run portable tests with:

```sh
python3 scripts/rootfs/a100_oci/tests/test_profile.py
```

Create the flat archive expected by Colab with:

```sh
python3 scripts/rootfs/a100_oci/make_colab_upload.py --force
```

Upload `/tmp/ds4-colab-upload.tgz` to a CPU Standard Colab runtime, unpack it
under `/content`, create pull-only GHCR auth with `write_pull_auth.py`, and run
`start_cpu_worker.py`. The default worker mode restores the build rootfs and
runs the already built payload through the Insula-style launcher; it does not
rebuild on the Colab host. The full operator recipe is
`docs/rootfs/colab-oci/COLAB_RECIPE.md`.

If using the Colab CLI from this host, create `/content/pull-auth.json` without
putting the token in a command line:

```sh
python3 scripts/rootfs/a100_oci/provide_colab_auth.py \
  --session ds4-cpu-oci --username "$GHCR_USER" \
  --start-worker --run-name r4 --mode run
```

Restore can run without Docker. Building the historical source image requires
Docker and the exact source archive declared in bundle-manifest.json.

For the current DS4 pipeline:

```sh
scripts/rootfs/build_rootfs.sh --rebuild
python3 scripts/rootfs/a100_oci/current_package.py
python3 scripts/rootfs/a100_oci/current_publish.py --token-file "$GHCR_TOKEN_FILE"
python3 scripts/rootfs/a100_oci/make_current_colab_upload.py \
  --release .ds4/colab-current/<run>/release.json --force
```

Use `provide_colab_auth.py --worker current --mode cpu` for CPU admission and
`--mode gpu` for the A100 gate.
