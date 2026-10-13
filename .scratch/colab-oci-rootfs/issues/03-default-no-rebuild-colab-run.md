# Default Colab Worker To No-Rebuild Run

Type: task
Status: resolved
Blocked by:

## Outcome

Make the regular CPU Colab recipe prove the remote Insula-style execution path
without rebuilding DS4 on the Colab host. Keep the expensive rebuild, object
seed, and OCI composition proof available as an explicit release-validation
mode.

## Answer

Changed the worker mode contract so `DS4_ROOTFS_TEST_MODE=run` is the default.
That mode restores the build rootfs, enters it with `launch_insula.py`, runs the
prebuilt DS4 binaries and quick toolchain probes, then stops without invoking
`make` or offline OCI composition. The previous full proof remains available as
`DS4_ROOTFS_TEST_MODE=release-validation`; `full` is accepted as a compatibility
alias. Updated the Colab host helper, upload bundle README, operator recipe and
rootfs docs to make the no-rebuild path explicit.

## Evidence

- `python3 -m py_compile scripts/rootfs/a100_oci/layered/cpu_layered_test.py scripts/rootfs/a100_oci/layered/start_cpu_worker.py scripts/rootfs/a100_oci/provide_colab_auth.py scripts/rootfs/a100_oci/make_colab_upload.py`
- `python3 scripts/rootfs/a100_oci/tests/test_profile.py`
- `git diff --check`
- `python3 scripts/rootfs/a100_oci/make_colab_upload.py --output /tmp/ds4-colab-upload.tgz --force`
- Google Colab CPU Standard `DS4_ROOTFS_TEST_MODE=run`, `DS4_ROOTFS_TEST_RUN=r5`:
  `phase=complete`, `no_remote_rebuild=true`, 8 records, no return-code
  mismatches.
- `colab stop -s ds4-cpu-oci`; `colab sessions` reported no active sessions.
