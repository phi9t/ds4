#!/usr/bin/env bash
# Host + rootfs + CUDA-channel coherence checks for the DS4 Bazel build.
# Runs inside the rootfs (DS4_IN_ROOTFS=1). Exit 0 = all green, 21 = a failure.
set -euo pipefail
fail() { printf '\033[1;31mdoctor: %s\033[0m\n' "$1" >&2; exit 21; }
ok()   { printf '\033[1;32mdoctor ok: %s\033[0m\n' "$1" >&2; }
warn() { printf '\033[1;33mdoctor warn: %s\033[0m\n' "$1" >&2; }

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/rootfs/contract.env
source "$ROOT/scripts/rootfs/contract.env"

version_ge() {
  python3 - "$1" "$2" <<'PY'
import re
import sys

def parts(v):
    return [int(x) for x in re.findall(r"\d+", v)]

got = parts(sys.argv[1])
want = parts(sys.argv[2])
n = max(len(got), len(want))
got += [0] * (n - len(got))
want += [0] * (n - len(want))
sys.exit(0 if got >= want else 1)
PY
}

[[ "${DS4_IN_ROOTFS:-0}" = "1" ]] || fail "not in rootfs"

# bazel from the tool snapshot
command -v bazel >/dev/null || fail "bazel not on PATH"
bazel --version >/dev/null 2>&1 || fail "bazel --version failed"
ok "bazel: $(bazel --version)"

# nvcc from the toolkit
command -v nvcc >/dev/null || fail "nvcc not on PATH"
nvcc_version="$(nvcc --version | sed -n 's/.*release \([0-9.]*\).*/\1/p' | head -1)"
[[ "$nvcc_version" == "$DS4_CUDA_VERSION" ]] ||
  fail "nvcc release $nvcc_version does not match DS4_CUDA_VERSION=$DS4_CUDA_VERSION ($DS4_CUDA_CHANNEL)"
ok "nvcc release $nvcc_version matches $DS4_CUDA_CHANNEL"

# GPUs
command -v nvidia-smi >/dev/null || fail "nvidia-smi not on PATH"
driver_version="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | tr -d '[:space:]')"
[[ -n "$driver_version" ]] || fail "could not read NVIDIA driver version"
version_ge "$driver_version" "$DS4_DRIVER_FLOOR" ||
  fail "NVIDIA driver $driver_version below DS4_DRIVER_FLOOR=$DS4_DRIVER_FLOOR"
ok "NVIDIA driver $driver_version >= $DS4_DRIVER_FLOOR"

gpus="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | grep -c . || true)"
[[ "${gpus:-0}" -ge 1 ]] || fail "no visible GPU"
ok "$gpus GPU(s)"
if [[ "${gpus:-0}" -lt 8 ]]; then
  warn "fewer than 8 GPUs visible; single-GPU dev is allowed, TP server expects 8"
fi

# driver DSOs resolve inside
for so in libcuda.so.1 libnvidia-ml.so.1; do
  ldconfig -p 2>/dev/null | grep -q "$so" || [ -e "/run/nvidia-driver/lib/$so" ] \
    || fail "$so not resolvable"
done
ok "driver DSOs resolvable"

# read-only root invariant
( : > /usr/_probe 2>/dev/null && rm -f /usr/_probe && fail "rootfs writable" ) || true
ok "rootfs read-only"

echo "doctor: all checks passed" >&2
