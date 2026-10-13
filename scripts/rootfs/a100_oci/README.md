# A100 OCI experiment profile

The recipe and CPU benchmark are documented in
[docs/rootfs/colab-oci](../../../docs/rootfs/colab-oci/README.md).

This profile packages the pinned fc80bd6/CUDA 13.0/sm_80/x86-64 experiment.
It does not replace DS4's current Bazel/CUDA 13.2 build or rootfs contract.
The nested layered/bazel module composes OCI images, not current engine binaries.

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
