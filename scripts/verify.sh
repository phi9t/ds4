#!/usr/bin/env bash
# Build-and-launch smoke for the DS4 CUDA inference engine.
#
# One command that proves a fresh checkout builds and can actually generate a
# token, so "build + launch repeatably" is a truthful pass/fail instead of a
# memorized ritual. Runs entirely inside the bwrap rootfs: if invoked from a
# bare host shell it re-execs itself through enter_rootfs.sh.
#
# Usage: scripts/verify.sh [<arch-label> <expected-arch>]
#   defaults: cuda-b200 sm_100  (the wired `scripts/ds4 verify` instance)
#
# Exit-code ladder (each failure names its own stage):
#   0  pass (built, launches, generated a token)
#   21 preflight failed (no nvcc, or no visible GPU)
#   22 build failed
#   23 launch failed (binary present but --build-id wrong/missing)
#   24 generate failed (model present but no output / crash)
#   25 generate skipped (no model on disk; build + launch still verified)
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MAKE_TARGET="${1:-cuda-b200}"
EXPECTED_ARCH="${2:-sm_100}"
MODEL="${DS4_TEST_MODEL:-$REPO_ROOT/ds4flash.gguf}"
FIXTURE_PROMPT="${DS4_VERIFY_PROMPT:-The capital of France is}"

log() { printf '\033[1m== verify: %s ==\033[0m\n' "$*" >&2; }
fail() { printf '\033[1;31mverify: %s\033[0m\n' "$2" >&2; exit "$1"; }

# Re-exec into the rootfs so the pinned toolchain builds and the host driver
# runs the kernels. DS4_IN_ROOTFS is set by enter_rootfs.sh; if it is missing we
# are on the bare host and hand ourselves to the launcher.
if [[ "${DS4_IN_ROOTFS:-0}" != "1" ]]; then
  log "not in rootfs; re-exec via enter_rootfs.sh"
  exec "$REPO_ROOT/scripts/rootfs/enter_rootfs.sh" -- /bin/bash -lc \
    "cd /workspace/ds4 && scripts/verify.sh $(printf '%q ' "$MAKE_TARGET" "$EXPECTED_ARCH")"
fi

cd "$REPO_ROOT"

# --- Stage 1: preflight -----------------------------------------------------
log "preflight (nvcc + GPU visibility)"
command -v nvcc >/dev/null 2>&1 || fail 21 "nvcc not found on PATH"
if command -v nvidia-smi >/dev/null 2>&1; then
  gpu_count="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | grep -c . || true)"
else
  gpu_count=0
fi
[[ "${gpu_count:-0}" -ge 1 ]] || fail 21 "no visible NVIDIA GPU (nvidia-smi reported ${gpu_count:-0})"
log "preflight ok: nvcc present, ${gpu_count} GPU(s)"

# --- Stage 2: build ---------------------------------------------------------
log "build ($MAKE_TARGET)"
bazel build --config=cuda //:ds4 || fail 22 "bazel build --config=cuda //:ds4 failed"
[[ -x bazel-bin/ds4 ]] || fail 22 "build did not produce bazel-bin/ds4"

# --- Stage 3: launch (identity check) --------------------------------------
log "launch (--build-id)"
build_id="$(bazel-bin/ds4 --build-id 2>/dev/null)" || fail 23 "bazel-bin/ds4 --build-id did not run"
printf 'verify: %s\n' "$build_id" >&2
grep -q "backend=cuda" <<<"$build_id" || fail 23 "build is not a CUDA build: $build_id"
grep -q "arch=$EXPECTED_ARCH" <<<"$build_id" \
  || fail 23 "build arch != $EXPECTED_ARCH: $build_id"
log "launch ok: $build_id"

# --- Stage 4: generate ------------------------------------------------------
if [[ ! -e "$MODEL" ]]; then
  log "generate skipped: model not found at $MODEL"
  printf '\033[1;33mverify: build + launch verified; generate skipped (no model)\033[0m\n' >&2
  exit 25
fi

log "generate (bounded greedy, 8 tokens)"
out="$(bazel-bin/ds4 --cuda -m "$MODEL" -n 8 --temp 0 -p "$FIXTURE_PROMPT" 2>/dev/null)" \
  || fail 24 "generation run crashed"
# Strip whitespace; a live engine must emit at least some non-empty text.
[[ -n "${out//[[:space:]]/}" ]] || fail 24 "generation produced no output"
log "generate ok (${#out} chars)"

printf '\033[1;32mverify: PASS — %s builds, launches, and generates\033[0m\n' "$build_id" >&2
exit 0
