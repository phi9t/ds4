# Define The A100 Experiment Protocol

Type: grilling
Status: resolved
Blocked by: 05
Parent: ../map.md
Labels: wayfinder:grilling

## Question

After CPU admission passes, how should the pipeline launch an A100 Colab runtime
and run DS4 experiments? Decide the Colab CLI/session steps, GPU projection into
the Insula rootfs, model-weight acquisition/mounting, exact experiment commands,
timeouts, cost guardrails, evidence files, and mandatory session cleanup.

## Decision

Use the same `release.json` and helper bundle on a fresh A100 Colab runtime with
`DS4_CURRENT_COLAB_MODE=gpu`. The worker restores the current image, checks that
`nvidia-smi` reports A100 unless `DS4_CURRENT_COLAB_ALLOW_NON_A100=1`, verifies
the driver version meets `DS4_DRIVER_FLOOR`, and enters the restored rootfs with
`launch_insula.py --gpu`.

Weights are mounted read-only from `/content/weights` and remain outside the
image. If `/content/weights/ds4flash.gguf` exists, the default smoke runs
`/opt/ds4/bin/ds4 --cuda -m /weights/ds4flash.gguf -n 8 --temp 0 -p "The capital
of France is"`. `DS4_CURRENT_COLAB_MODEL`, `DS4_CURRENT_COLAB_PROMPT`, and
`DS4_CURRENT_COLAB_TOKENS` adjust the smoke. If weights are absent, the worker
records generation skipped after proving restore, driver projection, binary
launch, and toolchain checks.

Stop the Colab runtime after collecting `/content/current-status-<run>.json` and
`/content/current-results-<run>.zip`.
