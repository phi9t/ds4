#!/usr/bin/env bash
# Enter the DS4 CUDA bwrap rootfs with this checkout mounted read-write at
# /workspace/ds4. With no command, opens an interactive bash shell.
#
# The rootfs ships the pinned CUDA 13.2 devel toolkit (nvcc + cuBLAS) so DS4
# compiles hermetically; the host NVIDIA driver (libcuda.so*, libnvidia-*.so*)
# and /dev/nvidia* are bound in so the compiled kernels run on the host's
# 8x B200 (sm_100) GPUs. Adapted from torchtitan/scripts/rootfs/enter_rootfs.sh.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOTFS="$REPO_ROOT/scripts/rootfs/rootfs"
ROOTFS_DEFAULT="$ROOTFS"
ROOTFS_EXPLICIT=0

# shellcheck source=scripts/rootfs/rootfs_target.sh
source "$REPO_ROOT/scripts/rootfs/rootfs_target.sh"

usage() {
  cat <<'EOF'
Usage: scripts/rootfs/enter_rootfs.sh [options] [-- <command> [args...]]

Enter the DS4 bwrap rootfs with this checkout mounted read-write at
/workspace/ds4. With no command, opens an interactive bash shell.

Options:
  --rootfs DIR    Rootfs directory to enter (default: scripts/rootfs/rootfs).
  --emit-plan-only
                  Emit the resolved bwrap plan as JSON and exit before running
                  bwrap. Writes to DS4_ROOTFS_PLAN_OUTPUT when set, else stdout.
  -h, --help      Show this help and exit.
EOF
}

EMIT_PLAN_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rootfs) ROOTFS="${2:?--rootfs requires a value}"; ROOTFS_EXPLICIT=1; shift 2 ;;
    --rootfs=*) ROOTFS="${1#*=}"; ROOTFS_EXPLICIT=1; shift ;;
    --emit-plan-only) EMIT_PLAN_ONLY=1; shift ;;
    --) shift; break ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

die() {
  printf '\033[1;31merror: %s\033[0m\n' "$*" >&2
  exit 1
}

json_escape() { python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"; }
json_array() { python3 -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@"; }

REPO_MNT=/workspace/ds4
HOME_MNT=/home/ds4
HOST_LIBDIR=/usr/lib/x86_64-linux-gnu
DS4_CACHE_HOST="$REPO_ROOT/.ds4/cache"
DS4_HOME_HOST="$REPO_ROOT/.ds4/home"
mkdir -p "$DS4_CACHE_HOST" "$DS4_HOME_HOST"
ROOTFS_CUDA_HOME=/usr/local/cuda
ROOTFS_PATH="/run/nvidia-driver/bin:/opt/ds4/bin:$ROOTFS_CUDA_HOME/bin:/usr/local/bin:/usr/bin:/bin"
ROOTFS_LD="/run/nvidia-driver/lib:$ROOTFS_CUDA_HOME/lib64"
ROOTFS_XDG_CACHE_HOME="$HOME_MNT/.cache"

emit_bwrap_plan() {
  local output="${DS4_ROOTFS_PLAN_OUTPUT:-}"
  local inner_argv_json bwrap_argv_json
  inner_argv_json="$(json_array "$@")"
  bwrap_argv_json="$(json_array "${bwrap_args[@]}")"
  local entrypoint_json rootfs_json repo_root_json host_libdir_json cwd_json
  local ds4_cache_json ds4_home_json opt_ds4_json
  entrypoint_json="$(json_escape "${REPO_ROOT}/scripts/rootfs/enter_rootfs.sh")"
  rootfs_json="$(json_escape "$ROOTFS")"
  repo_root_json="$(json_escape "$REPO_ROOT")"
  host_libdir_json="$(json_escape "$HOST_LIBDIR")"
  cwd_json="$(json_escape "$REPO_MNT")"
  ds4_cache_json="$(json_escape "$DS4_CACHE_HOST")"
  ds4_home_json="$(json_escape "$DS4_HOME_HOST")"
  opt_ds4_json="$(json_escape "$ROOTFS/opt/ds4")"

  local plan
  plan="$(cat <<EOF
{
  "schema_version": 1,
  "entrypoint": ${entrypoint_json},
  "rootfs": {
    "path": ${rootfs_json},
    "explicit": $([[ "$ROOTFS_EXPLICIT" -eq 1 ]] && printf 'true' || printf 'false')
  },
  "cwd": ${cwd_json},
  "network_mode": "shared",
  "mounts": [
EOF
)"
  local first=1
  append_mount() {
    local item="$1"
    if [[ "$first" -eq 0 ]]; then plan+=$',\n'; fi
    plan+="    ${item}"
    first=0
  }
  append_mount "{\"kind\":\"ro-bind\",\"source\":${rootfs_json},\"target\":\"/\",\"writable\":false}"
  append_mount "{\"kind\":\"proc\",\"source\":\"procfs\",\"target\":\"/proc\",\"writable\":false}"
  append_mount "{\"kind\":\"tmpfs\",\"source\":\"tmpfs\",\"target\":\"/tmp\",\"writable\":true}"
  append_mount "{\"kind\":\"dev\",\"source\":\"devfs\",\"target\":\"/dev\",\"writable\":true}"
  append_mount "{\"kind\":\"bind\",\"source\":${repo_root_json},\"target\":\"${REPO_MNT}\",\"writable\":true}"
  append_mount "{\"kind\":\"bind\",\"source\":${ds4_cache_json},\"target\":\"/ds4/cache\",\"writable\":true}"
  append_mount "{\"kind\":\"bind\",\"source\":${ds4_home_json},\"target\":\"${HOME_MNT}\",\"writable\":true}"
  append_mount "{\"kind\":\"ro-bind\",\"source\":${opt_ds4_json},\"target\":\"/opt/ds4\",\"writable\":false}"
  append_mount "{\"kind\":\"tmpfs\",\"source\":\"tmpfs\",\"target\":\"/run\",\"writable\":true}"
  append_mount "{\"kind\":\"dir\",\"source\":\"dir\",\"target\":\"/run/nvidia-driver\",\"writable\":true}"
  append_mount "{\"kind\":\"dir\",\"source\":\"dir\",\"target\":\"/run/nvidia-driver/lib\",\"writable\":true}"
  append_mount "{\"kind\":\"dir\",\"source\":\"dir\",\"target\":\"/run/nvidia-driver/bin\",\"writable\":true}"
  for f in /etc/resolv.conf /etc/hosts; do
    if [[ -e "$f" ]]; then
      local escaped; escaped="$(json_escape "$f")"
      append_mount "{\"kind\":\"ro-bind\",\"source\":${escaped},\"target\":${escaped},\"writable\":false}"
    fi
  done
  local dev_json_entries=() lib_json_entries=()
  for dev in "${rootfs_plan_devices[@]}"; do
    local escaped_dev; escaped_dev="$(json_escape "$dev")"
    append_mount "{\"kind\":\"dev-bind\",\"source\":${escaped_dev},\"target\":${escaped_dev},\"writable\":true}"
    dev_json_entries+=("$dev")
  done
  for lib in "${rootfs_plan_driver_libraries[@]}"; do
    local escaped_lib target_lib
    escaped_lib="$(json_escape "$lib")"
    target_lib="$(json_escape "/run/nvidia-driver/lib/$(basename "$lib")")"
    append_mount "{\"kind\":\"ro-bind\",\"source\":${escaped_lib},\"target\":${target_lib},\"writable\":false}"
    lib_json_entries+=("$lib")
  done
  if [[ -n "${rootfs_plan_nvidia_smi:-}" ]]; then
    local nvidia_smi_json nvidia_smi_target_json
    nvidia_smi_json="$(json_escape "$rootfs_plan_nvidia_smi")"
    nvidia_smi_target_json="$(json_escape "/run/nvidia-driver/bin/nvidia-smi")"
    append_mount "{\"kind\":\"ro-bind\",\"source\":${nvidia_smi_json},\"target\":${nvidia_smi_target_json},\"writable\":false}"
  fi

  local devices_json driver_libraries_json nvidia_visible_json ld_json path_json cuda_visible_json
  devices_json="$(json_array "${dev_json_entries[@]}")"
  driver_libraries_json="$(json_array "${lib_json_entries[@]}")"
  nvidia_visible_json="$(json_escape "${NVIDIA_VISIBLE_DEVICES:-all}")"
  ld_json="$(json_escape "$ROOTFS_LD")"
  path_json="$(json_escape "$ROOTFS_PATH")"
  plan+=$'\n'
  plan+="  ],
  \"devices\": ${devices_json},
  \"driver_libraries\": ${driver_libraries_json},
  \"environment\": {
    \"PATH\": ${path_json},
    \"CUDA_HOME\": \"${ROOTFS_CUDA_HOME}\",
    \"CUDA_PATH\": \"${ROOTFS_CUDA_HOME}\",
    \"LD_LIBRARY_PATH\": ${ld_json},
    \"DS4_IN_ROOTFS\": \"1\",
    \"HOME\": \"${HOME_MNT}\",
    \"XDG_CACHE_HOME\": \"${ROOTFS_XDG_CACHE_HOME}\",
    \"NVIDIA_VISIBLE_DEVICES\": ${nvidia_visible_json}"
  if [[ "${CUDA_VISIBLE_DEVICES+set}" == set ]]; then
    cuda_visible_json="$(json_escape "$CUDA_VISIBLE_DEVICES")"
    plan+=",
    \"CUDA_VISIBLE_DEVICES\": ${cuda_visible_json}"
  fi
  plan+="
  },
  \"inner_argv\": ${inner_argv_json},
  \"bwrap_argv\": ${bwrap_argv_json},
  \"host\": {
    \"repo_root\": ${repo_root_json},
    \"host_libdir\": ${host_libdir_json}
  }
}
"
  if [[ -n "$output" ]]; then
    mkdir -p "$(dirname -- "$output")"
    printf '%s' "$plan" > "$output"
  else
    printf '%s' "$plan"
  fi
}

# When only emitting the plan we still resolve mounts, but a missing rootfs must
# not trigger an implicit build. Guard the build path on real invocations.
if [[ ! -x "$ROOTFS/bin/bash" ]]; then
  if [[ "$EMIT_PLAN_ONLY" -eq 0 ]]; then
    # Implicit build is allowed only for the canonical default rootfs. A missing
    # custom --rootfs is an error, not an invitation to build, so a typo cannot
    # silently trigger Docker work or a deletion at an arbitrary path.
    if [[ "$ROOTFS_EXPLICIT" -eq 1 || "$ROOTFS" != "$ROOTFS_DEFAULT" ]]; then
      die "rootfs not found at $ROOTFS; refusing implicit build of a custom --rootfs (build it explicitly with scripts/rootfs/build_rootfs.sh)"
    fi
    printf '\033[1m== rootfs not found at %s; building default ==\033[0m\n' "$ROOTFS" >&2
    "$REPO_ROOT/scripts/rootfs/build_rootfs.sh" --dest "$ROOTFS"
    [[ -x "$ROOTFS/bin/bash" ]] || die "rootfs build did not produce a usable rootfs at $ROOTFS"
  fi
fi

# Refuse to launch a rootfs that was built from a different contract.env: the
# pinned identity (base image digest, bazel, CUDA) is only meaningful if the
# tree on disk still matches it. Skipped for --emit-plan-only, where the rootfs
# may legitimately be absent. A drifted or legacy rootfs fails closed here with
# a rebuild instruction rather than launching silently.
if [[ "$EMIT_PLAN_ONLY" -eq 0 ]]; then
  rootfs_assert_contract_match "$ROOTFS"
fi

rootfs_plan_devices=()
rootfs_plan_driver_libraries=()
rootfs_plan_nvidia_smi=""

bwrap_args=(
  --ro-bind "$ROOTFS" /
  --proc /proc
  --tmpfs /tmp
  --dev /dev
  --bind "$REPO_ROOT" "$REPO_MNT"
  --bind "$DS4_CACHE_HOST" /ds4/cache
  --bind "$DS4_HOME_HOST" "$HOME_MNT"
  --ro-bind "$ROOTFS/opt/ds4" /opt/ds4
  --tmpfs /run
  --unshare-all --share-net
  --die-with-parent
  --chdir "$REPO_MNT"
)

for f in /etc/resolv.conf /etc/hosts; do
  [[ -e "$f" ]] && bwrap_args+=(--ro-bind "$f" "$f")
done

shopt -s nullglob
for dev in /dev/nvidia* /dev/nvidia-caps; do
  bwrap_args+=(--dev-bind "$dev" "$dev")
  rootfs_plan_devices+=("$dev")
done
bwrap_args+=(
  --dir /run/nvidia-driver
  --dir /run/nvidia-driver/lib
  --dir /run/nvidia-driver/bin
)
# Bind the host driver runtime (libcuda + libnvidia-*) so the in-rootfs toolkit
# links kernels that the host driver executes; the rootfs itself ships no driver.
for lib in "$HOST_LIBDIR"/libcuda.so* "$HOST_LIBDIR"/libnvidia-*.so*; do
  bwrap_args+=(--ro-bind "$lib" "/run/nvidia-driver/lib/$(basename "$lib")")
  rootfs_plan_driver_libraries+=("$lib")
done
if [[ -x /usr/bin/nvidia-smi ]]; then
  bwrap_args+=(--ro-bind /usr/bin/nvidia-smi /run/nvidia-driver/bin/nvidia-smi)
  rootfs_plan_nvidia_smi="/usr/bin/nvidia-smi"
fi
shopt -u nullglob

bwrap_args+=(
  --setenv PATH "$ROOTFS_PATH"
  --setenv CUDA_HOME "$ROOTFS_CUDA_HOME"
  --setenv CUDA_PATH "$ROOTFS_CUDA_HOME"
  --setenv LD_LIBRARY_PATH "$ROOTFS_LD"
  --setenv DS4_IN_ROOTFS 1
  --setenv HOME "$HOME_MNT"
  --setenv XDG_CACHE_HOME "$ROOTFS_XDG_CACHE_HOME"
)

if [[ "${CUDA_VISIBLE_DEVICES+set}" == set ]]; then
  bwrap_args+=(--setenv CUDA_VISIBLE_DEVICES "$CUDA_VISIBLE_DEVICES")
fi
bwrap_args+=(--setenv NVIDIA_VISIBLE_DEVICES "${NVIDIA_VISIBLE_DEVICES:-all}")

if [[ "$EMIT_PLAN_ONLY" -eq 1 ]]; then
  if [[ $# -eq 0 ]]; then
    emit_bwrap_plan /bin/bash -l
  else
    emit_bwrap_plan "$@"
  fi
  exit 0
fi

command -v bwrap >/dev/null || die "bwrap not found on host"

if [[ $# -eq 0 ]]; then
  exec bwrap "${bwrap_args[@]}" /bin/bash -l
else
  exec bwrap "${bwrap_args[@]}" "$@"
fi
