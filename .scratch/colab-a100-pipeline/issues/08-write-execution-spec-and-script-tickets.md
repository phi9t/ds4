# Write The Execution Spec And Script Tickets

Type: task
Status: resolved
Blocked by: 01, 02, 03, 04, 05, 06, 07
Parent: ../map.md
Labels: wayfinder:task

## Question

Once the upstream decisions are resolved, write the execution spec and
implementation tickets that codify the pipeline as scripts/docs. The output
should be ready for separate delivery agents and should include task contracts,
allowed side effects, validation commands, expected Colab/GHCR evidence, and
rollback/cleanup instructions.

## Result

The execution spec is `docs/rootfs/colab-oci/CURRENT_PIPELINE.md`.

Implementation entrypoints:

- `scripts/rootfs/a100_oci/current_package.py`
- `scripts/rootfs/a100_oci/current_publish.py`
- `scripts/rootfs/a100_oci/make_current_colab_upload.py`
- `scripts/rootfs/a100_oci/start_current_worker.py`
- `scripts/rootfs/a100_oci/current_colab_worker.py`
- `scripts/rootfs/a100_oci/provide_colab_auth.py --worker current`

Validation commands:

- `python3 -m py_compile scripts/rootfs/a100_oci/current_package.py scripts/rootfs/a100_oci/current_publish.py scripts/rootfs/a100_oci/current_colab_worker.py scripts/rootfs/a100_oci/start_current_worker.py scripts/rootfs/a100_oci/make_current_colab_upload.py`
- `python3 scripts/rootfs/a100_oci/tests/test_profile.py`
- `scripts/ds4 bazel -- build --config=cuda-a100 //:ds4 //:ds4-server //:ds4-bench //:ds4-eval //:ds4-agent`
- `scripts/ds4 bazel -- run --config=cuda-a100 //:ds4 -- --build-id`
- `scripts/ds4 bazel -- run --config=cuda //:ds4 -- --build-id`
