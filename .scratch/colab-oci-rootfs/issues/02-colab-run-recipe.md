# Add The Colab Run Recipe

Type: task
Status: resolved
Blocked by:

## Outcome

Make the CPU Colab OCI transport proof runnable from a small, repeatable recipe
instead of hand-copying files and auth snippets.

## Answer

Added `docs/rootfs/colab-oci/COLAB_RECIPE.md` as the operator runbook. Added
`scripts/rootfs/a100_oci/make_colab_upload.py` to build the flat
`/content` upload archive and `scripts/rootfs/a100_oci/write_pull_auth.py` to
create the pull-only GHCR auth file without echoing the token. Added
`scripts/rootfs/a100_oci/provide_colab_auth.py` so a host with the Colab CLI can
prompt locally for the token, upload `/content/pull-auth.json`, verify it
remotely, and optionally start the worker. Extended the portable profile tests
to check these helpers.

## Evidence

- `python3 scripts/rootfs/a100_oci/tests/test_profile.py`
- `git diff --check`
