# Define Evidence And Promotion Gates

Type: grilling
Status: resolved
Blocked by: 01, 04, 05, 06
Parent: ../map.md
Labels: wayfinder:grilling

## Question

What evidence is retained in Git versus external storage for each stage, and
what gates must pass before the pipeline result can be called complete? Decide
the receipts, checksums, logs, run summaries, secret-scan checks, review
requirements, and what remains human-owned: publish, GPU allocation, push,
pull-request creation, and merge.

## Decision

Git retains the scripts, docs, tracker files, and small copied evidence summaries
or status JSONs. `.ds4/colab-current/` retains local candidate receipts, staged
binaries, release records, import logs, and acquired crane binaries. GHCR owns
the image blobs. Colab owns live logs until the operator downloads the status
JSON and results ZIP. Credentials and model weights stay outside Git and outside
images.

Promotion gates:

1. Python profile tests pass.
2. `scripts/ds4 bazel -- build --config=cuda-a100` builds all five binaries.
3. `ds4 --build-id` reports `backend=cuda arch=sm_80 cuda=13.2`.
4. The default B200 build still reports `backend=cuda arch=sm_100 cuda=13.2`.
5. `current_package.py` writes a candidate receipt and imports the local image.
6. `current_publish.py` writes a digest-pinned release record.
7. CPU Colab admission completes with `no_remote_rebuild=true`.
8. A100 Colab gate completes, with generation smoke passing when weights are
   staged or explicitly skipped when weights are absent.

Publishing, Colab allocation, PR creation, pushing branches, and merging remain
operator-owned side effects unless explicitly requested in the active run.
