# Agent Notes

`ds4.c` is a DeepSeek V4 Flash specific inference engine. It is not a generic
GGUF runner. The goal is a small, readable, high-performance C codebase. The
engine is NVIDIA-CUDA-only; the CPU backend exists solely as a reference/debug
oracle.

## Goals

- Keep the production path as whole-model CUDA graph inference.
- Always make sure that the SSD streaming, CUDA, distributed, and tensor-parallel inference paths are not affected by fixes to other parts of the code.
- Keep model loading mmap-backed for the default case; do not eagerly copy the full GGUF. Keep the model loading for SSD streaming of routed experts explicit: allocated buffers, fast reads from disk, always try to hide loading of missing routed experts by loading them while performing the inference of the shared expert and routed experts already in RAM. Always try to hide loading of layers for prefill in SSD streaming mode using the inference time of the current layer as the next one is loaded.
- Keep the CPU backend CPU-only and use it only as reference/debug code.
- Preserve correctness before speed. Do not keep a faster path with unexplained attention, KV cache, or logits drift.
- Make long local agent sessions practical through live KV reuse and disk KV checkpoints.

## Quality Rules

- Keep the implementation small, sharp, easy to understand. Try to write elegant code in a state of grace. Don't settle for the first thing that comes to mind, try to find the most minimal and better working design. Don't introduce slop: very fragile code that just patches specific cases, dead code, useless code and code ways more complicated of how it should be.
- Comment important inference code where the model mechanics, cache lifetime, memory policy, or API orchestration are not obvious from the local code.
- Prefer comments beside the implementation over separate design documents.
- Keep comments instructive and compact: explain why a shape, ordering, cache boundary, or memory choice exists.
- Keep public APIs narrow. CLI/server code should not know tensor internals.
- Do not add permanent semantic variants behind flags. Diagnostic switches are fine when they validate the one release path.
- Do not introduce C++.

## Safety

- Avoid large CPU inference runs; the CPU path has previously exposed kernel VM failures with very large mappings.
- Do not run multiple huge model processes concurrently. The instance lock is intentional.

## Layout

- `ds4.c`: model loading, tokenizer, CPU reference code, CUDA graph scheduling,
  sessions, disk-cache payload serialization.
- `ds4_cli.c`: command line, linenoise REPL, interactive transcript handling.
- `ds4_server.c`: OpenAI/Anthropic compatible HTTP API, worker queue, streaming,
  tool-call mapping, disk KV cache policy.
- `ds4_cuda.cu`: CUDA runtime, kernels, and graph execution.
- `ds4_build.{c,h}`: build identity stamp (backend/arch/CUDA/git), one function.
- `scripts/rootfs/`: repo-local bwrap rootfs (build, launch, contract identity).
- `tests/`: unit and live integration tests.
- `misc/`: ignored notes, experiments, and old planning material.

This list is not complete, check the files for more info.

## Build and launch

- The engine is NVIDIA-CUDA-only. Build and run everything inside the repo-local
  bwrap rootfs: `scripts/rootfs/enter_rootfs.sh -- <cmd>`. The rootfs ships the
  pinned CUDA 13.2 toolkit; the host driver runs the kernels.
- The rootfs launcher fails closed if the on-disk rootfs was built from a
  different `scripts/rootfs/contract.env` (identity stamped in the ownership
  marker). Any change to the pinned base image, bazel, or CUDA version requires
  `scripts/rootfs/build_rootfs.sh --rebuild`.
- Every binary is stamped with its backend/arch/CUDA/git SHA (see `ds4_build.h`)
  because the CPU build and every CUDA target share the `./ds4` filename. Query
  it with `./ds4 --build-id`; do not trust the filename to know which build it is.
- `scripts/ds4 verify` is the one-command build+launch smoke (preflight → build
  via bazel → `--build-id` check → bounded greedy generate). Use it as the
  repeatable proof that a fresh checkout builds and generates before claiming the
  engine works.

## Testing

The Bazel + rootfs build is the only build path. Build the engine with
`scripts/ds4 bazel -- build --config=cuda //:ds4` (add the other binaries
`//:ds4-server //:ds4-bench //:ds4-eval //:ds4-agent` when validating the full
set). Smoke the end-to-end build+launch with `scripts/ds4 verify`. Run unit
tests with `scripts/ds4 bazel -- test //tests/...` (the FP4 CUDA check is
`scripts/ds4 bazel -- test --config=cuda //tests:test_mxfp4_cuda`). The CPU
reference/correctness oracle is `scripts/ds4 bazel -- build --//:backend=cpu
//:ds4`. Use live server tests only when intentionally testing the API surface.

At every major change where one of the following could be affected, make sure to:

1. Run `scripts/ds4 verify` and confirm CUDA build + generation still pass.
2. Test the SSD streaming path.
3. Test the distributed / tensor-parallel inference if it could be affected, but ask the user before doing so.
4. Keep the CPU reference (`scripts/ds4 bazel -- build --//:backend=cpu //:ds4`) path building; it is the correctness oracle.
