# DS4 Bazel + vaso-rootfs Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the DS4 Makefile with a native Bazel build (rules_cuda) that runs end-to-end inside a vaso-style read-only bwrap rootfs on the 8x B200 (sm_100) host, migrated incrementally with the Makefile deleted last.

**Architecture:** Bazel owns the C compile (`cc_library`), CUDA compile (`cuda_library` via rules_cuda), and link (`cc_binary`). A read-only bwrap rootfs projects the host NVIDIA driver and provides a pinned `/opt/ds4` tool snapshot (bazel via bazelisk, mise). Thin `scripts/ds4` wrappers self-re-exec into the rootfs. The CPU reference build survives via a `--//:backend=cpu` config. The Makefile stays authoritative until the final slice.

**Tech Stack:** Bazel 9.2.0, rules_cc, rules_cuda (CUDA toolkit via redist), bwrap 0.8.0, docker (rootfs build only), CUDA 13.2, C99/C++17, nvcc, cuBLAS.

**Spec:** `docs/superpowers/specs/2026-08-21-bazel-vaso-rootfs-migration-design.md`

## Global Constraints

- NVIDIA CUDA only. Do not touch inference semantics, model loading, SSD streaming, distributed / tensor-parallel execution, KV cache, or CPU reference math. Only build system + rootfs change.
- sm_100 must **not** define `DS4_CUDA_HAVE_MXF4` (ptxas rejects the warp-level `mma.sync ... kind::mxf4.block_scale` on `sm_100a`). MXFP4 stays a consumer-Blackwell (`sm_120a/sm_121a`) feature.
- `--build-id` output must stay byte-identical to today: `ds4 backend=cuda arch=sm_100 cuda=13.2 git=<sha>`; CPU: `ds4 backend=cpu arch=cpu git=<sha>` (no `cuda=`).
- C compile flags must match the Makefile: `-O3 -ffast-math -march=native -std=c99 -D_GNU_SOURCE -fno-finite-math-only -Wall -Wextra` (correctness before speed — carry `-ffast-math`/`-march=native` exactly). CUDA: `-std=c++17 -Icuda/mmq`, arch `compute_100:sm_100`.
- The rootfs is **read-only** at run time with explicit writable binds. `/run/nvidia-driver/lib` first in `LD_LIBRARY_PATH`.
- Every command runs inside the rootfs via `scripts/rootfs/enter_rootfs.sh -- ...` or `scripts/ds4 ...`.
- The Makefile stays buildable until Task 12 (deleted last). The repo is never un-buildable mid-migration.
- No C++ added to DS4's own sources; kernels stay under `cuda/`.
- Landing is **local `main` only, never push**. Commit trailer exactly once: `Co-authored-by: TRAE CLI <noreply@bytedance.com>`.
- Exit-code ladder preserved: 0 pass, 21 preflight, 22 build, 23 launch, 24 generate-crashed/empty, 25 generate-skipped.

---

## Slice 1 — Substrate (rootfs + tooling + doctor)

### Task 1: Toolchain manifest (contract.env) with CUDA channel + driver floor

**Files:**
- Modify: `scripts/rootfs/contract.env`
- Modify: `scripts/rootfs/rootfs_target.sh` (extend `rootfs_contract_identity` hash inputs)

**Interfaces:**
- Consumes: existing `rootfs_contract_identity()` and `rootfs_assert_contract_match` (already present).
- Produces: contract keys `DS4_ROOTFS_SCHEMA=2`, `DS4_CUDA_CHANNEL=cu132`, `DS4_DRIVER_FLOOR=<min libcuda version for cu132>`, `DS4_BAZELISK_VERSION`, `DS4_MISE_VERSION`, consumed by build_rootfs.sh (Task 2) and doctor (Task 4).

- [ ] **Step 1: Add channel + tool pins to contract.env**

Append to `scripts/rootfs/contract.env` (keep existing base image + bazel pins):

```sh
# CUDA channel is the single source of truth tying the host driver floor, the
# rules_cuda redist toolkit, and the compiled arch together. cu132 = CUDA 13.2.
DS4_CUDA_CHANNEL=cu132
# Minimum host libcuda.so.1 version that satisfies cu132 (CUDA 13.2 forward-compat
# floor). nvidia-smi on this host reports driver 580.x / libcuda.so.580.
DS4_DRIVER_FLOOR=580.0
# Tooling baked read-only into /opt/ds4.
DS4_BAZELISK_VERSION=1.26.0
DS4_MISE_VERSION=2025.1.0
```

Bump `DS4_ROOTFS_SCHEMA=1` to `DS4_ROOTFS_SCHEMA=2` (new identity).

- [ ] **Step 2: Fold new keys into the identity hash**

In `scripts/rootfs/rootfs_target.sh`, find `rootfs_contract_identity()` and add the new fields to the hashed material (same style as the existing fields):

```sh
# In rootfs_contract_identity(): include the channel + tool pins so a drifted
# manifest fails closed. Append these to the printf feeding sha256.
"$DS4_CUDA_CHANNEL" "$DS4_DRIVER_FLOOR" "$DS4_BAZELISK_VERSION" "$DS4_MISE_VERSION"
```

- [ ] **Step 3: Recompute + verify the identity hash is stable across two calls**

Run: `source scripts/rootfs/contract.env && source scripts/rootfs/rootfs_target.sh && a=$(rootfs_contract_identity) && b=$(rootfs_contract_identity) && [ "$a" = "$b" ] && echo "STABLE $a"`
Expected: prints `STABLE <64-hex>`; the two calls agree.

- [ ] **Step 4: Commit**

```bash
git add scripts/rootfs/contract.env scripts/rootfs/rootfs_target.sh
git commit -m "rootfs: pin CUDA channel + tool versions in contract manifest

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

### Task 2: Rootfs image builds /opt/ds4 tool snapshot (bazelisk + mise)

**Files:**
- Modify: `scripts/rootfs/build_rootfs.sh` (Dockerfile body)

**Interfaces:**
- Consumes: `DS4_BASE_IMAGE`, `DS4_BAZEL_VERSION`, `DS4_BAZELISK_VERSION`, `DS4_MISE_VERSION` from contract.env (Task 1).
- Produces: a rootfs whose `/opt/ds4/bin` contains `bazel` (bazelisk shim pinned to `DS4_BAZEL_VERSION`) and `mise`; `/opt/ds4` is bound read-only at run time (Task 3).

- [ ] **Step 1: Install bazelisk + mise into /opt/ds4 in the Dockerfile**

In the here-doc Dockerfile in `build_rootfs.sh`, replace the bare-bazel install block with a `/opt/ds4` snapshot. bazelisk is pinned and told to use `DS4_BAZEL_VERSION`:

```dockerfile
ARG BAZELISK_VERSION
ARG MISE_VERSION
# /opt/ds4 is the read-only tool snapshot (bound ro at runtime). bazelisk pins
# the exact bazel; mise selects any auxiliary tools. USE_BAZEL_VERSION forces
# the pinned bazel so no network resolution happens at build time inside rootfs.
RUN set -euo pipefail; \
    mkdir -p /opt/ds4/bin; \
    curl -fsSL -o /opt/ds4/bin/bazel \
      "https://github.com/bazelbuild/bazelisk/releases/download/v${BAZELISK_VERSION}/bazelisk-linux-amd64"; \
    chmod +x /opt/ds4/bin/bazel; \
    curl -fsSL -o /opt/ds4/bin/mise \
      "https://github.com/jdx/mise/releases/download/v${MISE_VERSION}/mise-v${MISE_VERSION}-linux-x64"; \
    chmod +x /opt/ds4/bin/mise
ENV USE_BAZEL_VERSION=${BAZEL_VERSION}
```

Pass the new args from the `docker build` invocation:

```sh
docker build -t "$TAG" \
  --build-arg BASE_IMAGE="$DS4_BASE_IMAGE" \
  --build-arg BAZEL_VERSION="$DS4_BAZEL_VERSION" \
  --build-arg BAZELISK_VERSION="$DS4_BAZELISK_VERSION" \
  --build-arg MISE_VERSION="$DS4_MISE_VERSION" \
  -f - "$ROOTFS_DIR" <<'DOCKERFILE'
```

Add `ARG BAZELISK_VERSION` / `ARG MISE_VERSION` near the top of the Dockerfile and drop the old `/usr/local/bin/bazel` install.

- [ ] **Step 2: Rebuild the rootfs**

Run: `scripts/rootfs/build_rootfs.sh --rebuild`
Expected: image builds; export succeeds; `scripts/rootfs/rootfs/opt/ds4/bin/bazel` and `.../mise` exist and are executable.

- [ ] **Step 3: Verify tools resolve inside**

Run: `scripts/rootfs/enter_rootfs.sh -- /bin/bash -lc '/opt/ds4/bin/bazel --version && /opt/ds4/bin/mise --version'`
Expected: `bazel 9.2.0` and a mise version line.

- [ ] **Step 4: Commit**

```bash
git add scripts/rootfs/build_rootfs.sh
git commit -m "rootfs: build read-only /opt/ds4 tool snapshot (bazelisk + mise)

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

### Task 3: Flip rootfs to read-only with explicit writable binds

**Files:**
- Modify: `scripts/rootfs/enter_rootfs.sh`

**Interfaces:**
- Consumes: the rootfs from Task 2, `rootfs_plan_devices`/`rootfs_plan_driver_libraries`/`rootfs_plan_nvidia_smi` from `rootfs_target.sh` (already used).
- Produces: a launcher that ro-binds `/`, rw-binds `/workspace/ds4`, `/ds4/cache`, `/home/<user>`, `/tmp`; ro-binds `/opt/ds4`; sets `PATH`/`LD_LIBRARY_PATH`/`BAZEL_*` per contract. Consumed by `scripts/ds4` (Task 5) and verify (Task 11).

- [ ] **Step 1: Change the root bind from writable to read-only and add writable surfaces**

In `enter_rootfs.sh` where `bwrap_args` is assembled: change the rootfs bind from `--bind "$ROOTFS" /` to `--ro-bind "$ROOTFS" /`. Add explicit writable binds after the pseudo-filesystems:

```sh
# Read-only rootfs; every writable surface is an explicit bind layered on top.
--ro-bind "$ROOTFS" /
--proc /proc
--dev /dev
--tmpfs /tmp
--bind "$REPO_ROOT" "$REPO_MNT"           # /workspace/ds4 rw
--bind "$DS4_CACHE_HOST" /ds4/cache        # bazel output base / caches rw
--bind "$DS4_HOME_HOST" "$HOME_MNT"        # /home/<user> rw
--ro-bind "$ROOTFS/opt/ds4" /opt/ds4       # tool snapshot ro (already in image)
```

Add near the other path vars:

```sh
HOME_MNT=/home/ds4
DS4_CACHE_HOST="$REPO_ROOT/.ds4/cache"
DS4_HOME_HOST="$REPO_ROOT/.ds4/home"
mkdir -p "$DS4_CACHE_HOST" "$DS4_HOME_HOST"
```

Pre-create the leaf mount targets in the image is not needed for these (they are bound over the ro root, but the *target dirs must exist in the rootfs*). Ensure `build_rootfs.sh` Dockerfile creates them — add to Task 2's Dockerfile a `RUN mkdir -p /workspace/ds4 /ds4/cache /home/ds4 /opt/ds4` before export. (If revisiting Task 2 is undesirable mid-execution, create them here via a `--dir` in the bwrap argv before each bind.)

- [ ] **Step 2: Set the environment (clearenv + allowlist + explicit vars)**

Add to `bwrap_args` env section:

```sh
--setenv HOME "$HOME_MNT"
--setenv CUDA_HOME /usr/local/cuda
--setenv PATH "/run/nvidia-driver/bin:/opt/ds4/bin:/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin"
--setenv LD_LIBRARY_PATH "/run/nvidia-driver/lib:/usr/local/cuda/lib64"
--setenv XDG_CACHE_HOME "$HOME_MNT/.cache"
--setenv DS4_IN_ROOTFS 1
```

Point the driver projection at `/run/nvidia-driver` (the current script binds driver libs at their host paths; move them under `/run/nvidia-driver/lib` and nvidia-smi under `/run/nvidia-driver/bin`, adding `--dir /run/nvidia-driver` before the file binds and `--dir` for `lib`/`bin`).

- [ ] **Step 3: Prove the root is read-only and workspace is writable**

Run:
```bash
scripts/rootfs/enter_rootfs.sh -- /bin/bash -lc '
  ( : > /usr/_probe 2>/dev/null && echo "BAD: rootfs writable" ) || echo "OK: rootfs read-only";
  ( : > /workspace/ds4/.probe && rm -f /workspace/ds4/.probe && echo "OK: workspace writable" );
  ( : > /ds4/cache/.probe && rm -f /ds4/cache/.probe && echo "OK: cache writable" )'
```
Expected: `OK: rootfs read-only`, `OK: workspace writable`, `OK: cache writable`.

- [ ] **Step 4: Prove the emit-plan-only path still works and shows ro root**

Run: `scripts/rootfs/enter_rootfs.sh --emit-plan-only | python3 -c 'import json,sys; p=json.load(sys.stdin); r=[m for m in p["mounts"] if m["target"]=="/"][0]; print("root writable:", r["writable"])'`
Expected: `root writable: False`.

- [ ] **Step 5: Add /run/nvidia-driver to .gitignore-safe host dirs and commit**

```bash
git add scripts/rootfs/enter_rootfs.sh
git commit -m "rootfs: read-only root with explicit writable binds + driver projection

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

Note: `.ds4/` host cache/home is generated — add `/.ds4/` to `.gitignore` in this commit.

### Task 4: `scripts/ds4 doctor` — host + rootfs + CUDA-channel coherence

**Files:**
- Create: `scripts/ds4_doctor.sh`

**Interfaces:**
- Consumes: contract.env (Task 1), the rootfs launcher (Task 3).
- Produces: `scripts/ds4_doctor.sh` runnable inside the rootfs, exit 0 = all green, exit 21 = a check failed (matches verify preflight code). Consumed by `scripts/ds4 doctor` (Task 5) and verify (Task 11).

- [ ] **Step 1: Write the doctor script (runs *inside* rootfs; scripts/ds4 re-execs it)**

Create `scripts/ds4_doctor.sh`:

```sh
#!/usr/bin/env bash
# Host + rootfs + CUDA-channel coherence checks for the DS4 Bazel build.
# Runs inside the rootfs (DS4_IN_ROOTFS=1). Exit 0 = all green, 21 = a failure.
set -euo pipefail
fail() { printf '\033[1;31mdoctor: %s\033[0m\n' "$1" >&2; exit 21; }
ok()   { printf '\033[1;32mdoctor ok: %s\033[0m\n' "$1" >&2; }

[[ "${DS4_IN_ROOTFS:-0}" = "1" ]] || fail "not in rootfs"

# bazel from the tool snapshot
command -v bazel >/dev/null || fail "bazel not on PATH"
bazel --version >/dev/null 2>&1 || fail "bazel --version failed"
ok "bazel: $(bazel --version)"

# nvcc from the toolkit
command -v nvcc >/dev/null || fail "nvcc not on PATH"
ok "nvcc present"

# GPUs
gpus="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | grep -c . || true)"
[[ "${gpus:-0}" -ge 1 ]] || fail "no visible GPU"
ok "$gpus GPU(s)"

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
```

`chmod +x scripts/ds4_doctor.sh`.

- [ ] **Step 2: Run it through the rootfs**

Run: `scripts/rootfs/enter_rootfs.sh -- /bin/bash -lc 'cd /workspace/ds4 && ./scripts/ds4_doctor.sh'`
Expected: several `doctor ok:` lines, final `doctor: all checks passed`, exit 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/ds4_doctor.sh
git commit -m "rootfs: add ds4 doctor (bazel/nvcc/GPU/driver/read-only checks)

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

### Task 5: `scripts/ds4` dispatcher (self-re-exec into rootfs)

**Files:**
- Create: `scripts/ds4`

**Interfaces:**
- Consumes: `enter_rootfs.sh` (Task 3), `ds4_doctor.sh` (Task 4).
- Produces: `scripts/ds4 {doctor|bazel|verify|shell} ...`; every subcommand runs inside the rootfs. `scripts/ds4 bazel -- <args>` runs `bazel <args>` in `/workspace/ds4`. Consumed by all later verification.

- [ ] **Step 1: Write the dispatcher**

Create `scripts/ds4`:

```sh
#!/usr/bin/env bash
# Thin front door: every subcommand runs inside the DS4 bwrap rootfs.
#   scripts/ds4 doctor
#   scripts/ds4 bazel -- build //:ds4
#   scripts/ds4 verify
#   scripts/ds4 shell
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
enter() { exec "$REPO_ROOT/scripts/rootfs/enter_rootfs.sh" -- /bin/bash -lc "cd /workspace/ds4 && $1"; }

cmd="${1:-}"; shift || true
case "$cmd" in
  doctor) enter "./scripts/ds4_doctor.sh" ;;
  bazel)  [[ "${1:-}" = "--" ]] && shift; enter "bazel $(printf '%q ' "$@")" ;;
  verify) enter "./scripts/verify.sh $(printf '%q ' "$@")" ;;
  shell)  exec "$REPO_ROOT/scripts/rootfs/enter_rootfs.sh" ;;
  *) echo "usage: scripts/ds4 {doctor|bazel|verify|shell} [args]" >&2; exit 2 ;;
esac
```

`chmod +x scripts/ds4`.

- [ ] **Step 2: Prove dispatch to doctor and a trivial bazel**

Run: `scripts/ds4 doctor`
Expected: doctor green, exit 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/ds4
git commit -m "rootfs: add scripts/ds4 dispatcher (doctor/bazel/verify/shell in rootfs)

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

## Slice 2 — First native target `//:ds4`

### Task 6: Bazel module + rules_cuda toolchain + .bazelrc

**Files:**
- Create: `MODULE.bazel`, `.bazelrc`, `.bazelversion`, `.bazelignore`
- Modify: `.gitignore` (Bazel symlinks already added at `ca17482`)

**Interfaces:**
- Produces: a Bazel workspace where `--config=cuda` enables rules_cuda with arch `compute_100:sm_100`, CUDA toolkit from redist. Consumed by all BUILD files.

- [ ] **Step 1: Resolve the redist version (open question from the spec)**

Run: `scripts/ds4 bazel -- --version` to confirm bazel works, then check rules_cuda's available redist versions. nccl pins `13.0.2`. Attempt `13.2.x`; if rules_cuda has no 13.2 redist entry, pin the newest published redist whose `nvcc` still targets `compute_100` (record the exact version chosen in a comment). If none works with the rootfs driver, fall back to `local_cuda` pointing at the rootfs `/usr/local/cuda` and note the deviation.
Expected: a concrete redist version string decided and written into MODULE.bazel Step 2.

- [ ] **Step 2: Write MODULE.bazel**

```python
module(name = "ds4", version = "0.0.0")

bazel_dep(name = "rules_cc", version = "0.2.22")
bazel_dep(name = "rules_cuda", version = "0.3.0")

# CUDA toolkit via NVIDIA redistributable metadata (Bazel-hermetic). Version is
# the CUDA channel cu132; if the redist index lacks 13.2, this pins the nearest
# published toolkit whose nvcc still targets compute_100 (see contract cu132).
cuda = use_extension("@rules_cuda//cuda:extensions.bzl", "toolchain")
cuda.redist_json(name = "cuda_redist", version = "13.2.0")  # adjust per Step 1
cuda.toolkit(name = "cuda")
use_repo(cuda, "cuda")
```

- [ ] **Step 3: Write .bazelrc (cuda disabled by default, sm_100 config)**

```
common --enable_bzlmod
build --jobs=HOST_CPUS

# Bazel caches live under the rootfs writable bind, never a host-absolute path.
startup --output_base=/ds4/cache/bazel/output
build --disk_cache=/ds4/cache/bazel/disk
build --repository_cache=/ds4/cache/bazel/repo

build --flag_alias=cuda_enable=@rules_cuda//cuda:enable
build --@rules_cuda//cuda:enable=False
build --build_tag_filters=-cuda
test  --test_tag_filters=-cuda

# --config=cuda: the datacenter Blackwell (sm_100) build.
build:cuda --build_tag_filters=
test:cuda  --test_tag_filters=
build:cuda --@rules_cuda//cuda:enable=True
build:cuda --@rules_cuda//cuda:compiler=nvcc
build:cuda --@rules_cuda//cuda:archs=compute_100:sm_100

test --test_output=errors
```

- [ ] **Step 4: Write .bazelversion and .bazelignore**

`.bazelversion`: `9.2.0`. `.bazelignore`: `scripts/rootfs/rootfs` and `.ds4` and `misc`.

- [ ] **Step 5: Prove the toolchain resolves**

Run: `scripts/ds4 bazel -- build --config=cuda --nobuild @cuda//:cuda_runtime`
Expected: analysis succeeds (toolkit fetched/seeded, no build errors). If it needs network, note that the redist must be seeded into the repo cache in build_rootfs.sh (revisit Task 2).

- [ ] **Step 6: Commit**

```bash
git add MODULE.bazel .bazelrc .bazelversion .bazelignore .gitignore
git commit -m "build: add Bazel module with rules_cuda sm_100 toolchain

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

### Task 7: `cuda/mmq` cuda_library with arch/MXFP4 select

**Files:**
- Create: `cuda/mmq/BUILD.bazel`
- Create: `bazel/defs.bzl` (shared `DS4_MXF4_SELECT`, copts helpers)

**Interfaces:**
- Consumes: rules_cuda `cuda_library` (Task 6).
- Produces: `//cuda/mmq:mmq` (cuda_library) exporting the vendored MMQ objects; `bazel/defs.bzl` provides `ds4_cuda_copts()` and the MXFP4 arch `select`. Consumed by `//:cuda` (Task 8).

- [ ] **Step 1: Write bazel/defs.bzl with the MXFP4 gate**

```python
# DS4 CUDA copts + the MXFP4 arch gate. sm_100 MUST NOT define
# DS4_CUDA_HAVE_MXF4: ptxas rejects the warp-level mma.sync kind::mxf4.block_scale
# on sm_100a (datacenter Blackwell exposes block-scaled FP4 only via tcgen05.mma,
# which these warp-MMA kernels do not use). MXFP4 is a consumer-Blackwell
# (sm_120a/sm_121a) feature. The default cuda config builds sm_100, so the
# default here defines nothing.
def ds4_cuda_copts():
    return ["-std=c++17", "-Icuda/mmq", "-O3", "--use_fast_math"]

# When consumer-Blackwell arches are wired later, add a config_setting and flip
# this select. Today only sm_100 is built, so no MXFP4 define is emitted.
DS4_MXF4_DEFINES = select({
    "//conditions:default": [],
})
```

- [ ] **Step 2: Write cuda/mmq/BUILD.bazel**

```python
load("@rules_cuda//cuda:defs.bzl", "cuda_library")
load("//bazel:defs.bzl", "ds4_cuda_copts", "DS4_MXF4_DEFINES")

package(default_visibility = ["//visibility:public"])

cuda_library(
    name = "mmq",
    srcs = glob(["*.cu"]),
    hdrs = glob(["*.cuh", "*.h"]),
    copts = ds4_cuda_copts(),
    local_defines = DS4_MXF4_DEFINES,
    includes = ["."],
    tags = ["cuda"],
)
```

- [ ] **Step 3: Build it**

Run: `scripts/ds4 bazel -- build --config=cuda //cuda/mmq:mmq`
Expected: compiles the seven `.cu` files; no ptxas MXFP4 error (because no `DS4_CUDA_HAVE_MXF4`).

- [ ] **Step 4: Commit**

```bash
git add bazel/defs.bzl cuda/mmq/BUILD.bazel
git commit -m "build: cuda_library for vendored MMQ tier (sm_100, MXFP4 off)

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

### Task 8: Root BUILD.bazel — C libraries, build stamp, `//:ds4`

**Files:**
- Create: `BUILD.bazel` (root)
- Modify: `bazel/defs.bzl` (add `ds4_c_copts()`, build-stamp genrule helper)
- Create: `bazel/stamp_status.sh` (workspace status command for git SHA)

**Interfaces:**
- Consumes: `//cuda/mmq:mmq` (Task 7), the existing `ds4_build.c` (reads `DS4_BUILD_*` defines).
- Produces: `//:core`, `//:net`, `//:repl`, `//:help`, `//:gpu_args`, `//:build_stamp` (cc_library with `local_defines` for identity), and `//:ds4` cc_binary. Consumed by Tasks 9-10.

- [ ] **Step 1: Add C copts to bazel/defs.bzl**

```python
def ds4_c_copts():
    # Match the Makefile CFLAGS exactly (correctness before speed): keep
    # -ffast-math and -march=native so numeric behavior is identical.
    return [
        "-O3", "-ffast-math", "-march=native", "-g",
        "-std=c99", "-D_GNU_SOURCE", "-fno-finite-math-only",
        "-Wall", "-Wextra",
    ]
```

- [ ] **Step 2: Write the workspace status command for the git SHA**

Create `bazel/stamp_status.sh`:

```sh
#!/usr/bin/env bash
# Volatile build identity for --build-id. Bazel calls this; keys become
# available to genrules/defines. Only the git SHA is volatile here.
echo "DS4_BUILD_GIT_SHA $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
```

`chmod +x`. Add `build --workspace_status_command=bazel/stamp_status.sh` to `.bazelrc`.

- [ ] **Step 3: Write the build_stamp genrule + cc_library**

In root `BUILD.bazel`, generate `ds4_build_gen.c` that includes the volatile SHA, and compile `ds4_build.c` with the backend/arch/cuda defines. The simplest faithful approach: a genrule reads `bazel-out/stable-status.txt`/`volatile-status.txt` and writes a header with the SHA; the `build_stamp` cc_library compiles the existing `ds4_build.c` with `-D` defines. Because `ds4_build.c` reads `DS4_BUILD_GIT` at compile time, pass the SHA via `local_defines` computed by a genrule-produced `.bzl`... simpler: use a genrule to emit the whole `ds4_build_gen.c` from `ds4_build.c` semantics.

Concretely, write a genrule that produces a compilable source and a cc_library:

```python
load("@rules_cc//cc:defs.bzl", "cc_binary", "cc_library")
load("//bazel:defs.bzl", "ds4_c_copts", "ds4_cuda_copts")

package(default_visibility = ["//visibility:public"])

# Build identity. ds4_build.c already reads DS4_BUILD_* -D defines and omits
# cuda= when empty; we pass backend/arch/cuda as static defines and inject the
# git SHA via a genrule that reads Bazel's volatile-status.txt so the SHA is
# always fresh without busting the cache for unrelated changes.
genrule(
    name = "build_git_h",
    outs = ["ds4_build_git.h"],
    cmd = "echo \"#define DS4_BUILD_GIT \\\"$$(sed -n 's/^DS4_BUILD_GIT_SHA //p' bazel-out/volatile-status.txt)\\\"\" > $@",
    stamp = 1,
)

cc_library(
    name = "build_stamp",
    srcs = ["ds4_build.c"],
    hdrs = ["ds4_build.h", ":build_git_h"],
    copts = ds4_c_copts() + ["-include", "$(location :build_git_h)"],
    local_defines = [
        "DS4_BUILD_BACKEND=\\\"cuda\\\"",
        "DS4_BUILD_ARCH=\\\"sm_100\\\"",
        "DS4_BUILD_CUDA=\\\"13.2\\\"",
    ],
)
```

Note: if the `-include` genrule-header interaction is awkward, the fallback is a full genrule that emits `ds4_build_gen.c` inlining all four defines; keep whichever compiles. The **acceptance test is the `--build-id` string**, not the mechanism.

- [ ] **Step 4: Write the C libraries and //:ds4**

```python
cc_library(name = "core",
    srcs = ["ds4.c", "ds4_distributed.c", "ds4_tp.c", "ds4_ssd.c", "ds4_layer_pack.c"],
    hdrs = glob(["*.h"]), copts = ds4_c_copts(), includes = ["."])
cc_library(name = "net", srcs = ["ds4_web.c", "ds4_kvstore.c", "rax.c"],
    hdrs = glob(["*.h"]), copts = ds4_c_copts(), includes = ["."])
cc_library(name = "repl", srcs = ["linenoise.c"], hdrs = ["linenoise.h"], copts = ds4_c_copts())
cc_library(name = "help", srcs = ["ds4_help.c"], hdrs = ["ds4_help.h"], copts = ds4_c_copts())
cc_library(name = "gpu_args", srcs = ["ds4_gpu_args.c"], hdrs = glob(["ds4_gpu*.h"]), copts = ds4_c_copts())

cc_library(name = "cuda", srcs = ["ds4_cuda.cu"], hdrs = glob(["*.h", "*.cuh", "*.inc"]),
    copts = ds4_cuda_copts(), includes = ["."], deps = ["//cuda/mmq:mmq"], tags = ["cuda"])

cc_binary(name = "ds4",
    srcs = ["ds4_cli.c"],
    copts = ds4_c_copts(),
    deps = [":core", ":cuda", ":help", ":repl", ":gpu_args", ":build_stamp"],
    tags = ["cuda"])
```

(`ds4_cuda.cu` as a `cc_library` src requires rules_cuda's `cuda_library`; if `cc_library` rejects `.cu`, make `//:cuda` a `cuda_library` instead. Use whichever rules_cuda supports.)

- [ ] **Step 5: Build //:ds4**

Run: `scripts/ds4 bazel -- build --config=cuda //:ds4`
Expected: links a `bazel-bin/ds4` binary with no undefined CUDA symbols.

- [ ] **Step 6: Prove --build-id parity**

Run: `scripts/ds4 bazel -- run --config=cuda //:ds4 -- --build-id`
Expected: `ds4 backend=cuda arch=sm_100 cuda=13.2 git=<sha>` — identical shape to the Makefile build.

- [ ] **Step 7: Commit**

```bash
git add BUILD.bazel bazel/defs.bzl bazel/stamp_status.sh .bazelrc
git commit -m "build: native Bazel //:ds4 (C libs + cuda_library + build stamp)

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

### Task 9: End-to-end parity of `//:ds4` vs `make cuda-b200`

**Files:** none (verification task)

**Interfaces:**
- Consumes: `//:ds4` (Task 8), the model `ds4flash.gguf`, the Makefile build.

- [ ] **Step 1: Build both and generate on the same prompt**

Run inside rootfs:
```bash
scripts/ds4 bazel -- build --config=cuda //:ds4
make cuda-b200   # (still authoritative)
bazel-bin/ds4 --cuda -m ds4flash.gguf -n 8 --temp 0 -p "The capital of France is" > /tmp/bz.txt
./ds4          --cuda -m ds4flash.gguf -n 8 --temp 0 -p "The capital of France is" > /tmp/mk.txt
diff /tmp/bz.txt /tmp/mk.txt && echo "PARITY OK"
```
Expected: greedy (`--temp 0`) output matches → `PARITY OK`. If it differs, stop and diagnose (copts drift) before proceeding — do not delete the Makefile.

- [ ] **Step 2: Record the parity result in the spec's open-questions section**

Append a short note to the spec confirming rules_cuda device-link + redist version worked (or the fallback taken).

- [ ] **Step 3: Commit the note**

```bash
git add docs/superpowers/specs/2026-08-21-bazel-vaso-rootfs-migration-design.md
git commit -m "docs: record //:ds4 parity + resolved toolchain open questions

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

## Slice 3 — Remaining binaries

### Task 10: `//:ds4-server`, `//:ds4-bench`, `//:ds4-eval`, `//:ds4-agent`

**Files:**
- Modify: `BUILD.bazel`

**Interfaces:**
- Consumes: the libraries from Task 8.
- Produces: four more cc_binary targets mirroring the Makefile link lines.

- [ ] **Step 1: Add the four binaries with the Makefile's dep sets**

```python
cc_binary(name = "ds4-server", srcs = ["ds4_server.c"], copts = ds4_c_copts(),
    deps = [":core", ":cuda", ":help", ":net", ":gpu_args", ":build_stamp"], tags = ["cuda"])
cc_binary(name = "ds4-bench", srcs = ["ds4_bench.c"], copts = ds4_c_copts(),
    deps = [":core", ":cuda", ":help", ":gpu_args", ":build_stamp"], tags = ["cuda"])
cc_binary(name = "ds4-eval", srcs = ["ds4_eval.c"], copts = ds4_c_copts(),
    deps = [":core", ":cuda", ":help", ":build_stamp"], tags = ["cuda"])
cc_binary(name = "ds4-agent", srcs = ["ds4_agent.c"], copts = ds4_c_copts(),
    deps = [":core", ":cuda", ":help", ":net", ":repl", ":gpu_args", ":build_stamp"], tags = ["cuda"])
```

- [ ] **Step 2: Build all five**

Run: `scripts/ds4 bazel -- build --config=cuda //:ds4 //:ds4-server //:ds4-bench //:ds4-eval //:ds4-agent`
Expected: all link.

- [ ] **Step 3: Parity spot-check server --build-id**

Run: `scripts/ds4 bazel -- run --config=cuda //:ds4-server -- --build-id`
Expected: `ds4 backend=cuda arch=sm_100 cuda=13.2 git=<sha>`.

- [ ] **Step 4: Commit**

```bash
git add BUILD.bazel
git commit -m "build: native Bazel targets for server/bench/eval/agent

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

## Slice 4 — CPU config + tests

### Task 11: CPU backend config_setting + verify.sh switched to Bazel

**Files:**
- Modify: `BUILD.bazel`, `bazel/defs.bzl`, `scripts/verify.sh`

**Interfaces:**
- Consumes: all binaries.
- Produces: `--//:backend=cpu` builds `//:ds4` with `-DDS4_NO_GPU`, links with cc, stamps `backend=cpu arch=cpu` (no cuda=). `scripts/verify.sh` builds via bazel.

- [ ] **Step 1: Add the backend flag + config_setting**

In `BUILD.bazel`:

```python
load("@bazel_skylib//rules:common_settings.bzl", "string_flag")
string_flag(name = "backend", build_setting_default = "cuda", values = ["cuda", "cpu"])
config_setting(name = "backend_cpu", flag_values = {":backend": "cpu"})
```

Add `bazel_dep(name = "bazel_skylib", version = "1.7.1")` to MODULE.bazel.

- [ ] **Step 2: select() the CPU compile + link**

Make the C libraries add `-DDS4_NO_GPU` under the cpu setting, and `//:ds4` select its deps so cpu omits `:cuda`/mmq and links with cc:

```python
_GPU_DEFINE = select({":backend_cpu": ["DS4_NO_GPU"], "//conditions:default": []})
# apply _GPU_DEFINE as local_defines on core/net/help/gpu_args libraries

cc_binary(name = "ds4", srcs = ["ds4_cli.c"], copts = ds4_c_copts(),
    local_defines = _GPU_DEFINE,
    deps = [":core", ":help", ":repl", ":gpu_args", ":build_stamp"] + select({
        ":backend_cpu": [],
        "//conditions:default": [":cuda"],
    }), tags = ["cuda"])
```

Make `build_stamp` defines depend on backend:

```python
local_defines = select({
    ":backend_cpu": ["DS4_BUILD_BACKEND=\\\"cpu\\\"", "DS4_BUILD_ARCH=\\\"cpu\\\""],
    "//conditions:default": ["DS4_BUILD_BACKEND=\\\"cuda\\\"", "DS4_BUILD_ARCH=\\\"sm_100\\\"", "DS4_BUILD_CUDA=\\\"13.2\\\""],
})
```

- [ ] **Step 3: Prove CPU build identity**

Run: `scripts/ds4 bazel -- run --//:backend=cpu //:ds4 -- --build-id`
Expected: `ds4 backend=cpu arch=cpu git=<sha>` (no `cuda=`).

- [ ] **Step 4: Point verify.sh at bazel**

In `scripts/verify.sh`, replace the `make "$MAKE_TARGET"` build stage with `bazel build --config=cuda //:ds4` and use `bazel-bin/ds4` for the launch/generate stages. Keep the exit-code ladder (21/22/23/24/25) and the fixture prompt unchanged.

- [ ] **Step 5: Run the full ladder**

Run: `scripts/ds4 verify`
Expected: `verify: PASS`, exit 0.

- [ ] **Step 6: Commit**

```bash
git add BUILD.bazel bazel/defs.bzl scripts/verify.sh MODULE.bazel
git commit -m "build: CPU backend config + verify.sh builds via bazel

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

### Task 12: Port test targets to `bazel test`

**Files:**
- Modify: `BUILD.bazel`; Create: `tests/BUILD.bazel`

**Interfaces:**
- Consumes: libraries + cuda_library.
- Produces: `bazel test //tests/...` covering `test_mxfp4_cuda`, gpu/engine/sampling/session-batch tests, `q4k-dot`, `mxfp4-dot`.

- [ ] **Step 1: Write tests/BUILD.bazel mirroring the Makefile test link sets**

For each Makefile test target, create a `cc_test` (CPU tests) or `cuda`-tagged `cc_test` (GPU tests) with the same srcs + deps. Example:

```python
load("@rules_cc//cc:defs.bzl", "cc_test")
load("//bazel:defs.bzl", "ds4_c_copts", "ds4_cuda_copts")

cc_test(name = "test_layer_pack", srcs = ["test_layer_pack.c"],
    copts = ds4_c_copts(), deps = ["//:core"])

cc_test(name = "test_mxfp4_cuda", srcs = ["test_mxfp4_cuda.cu"],
    copts = ds4_cuda_copts(), deps = ["//cuda/mmq:mmq"], tags = ["cuda"])
# ... one per Makefile test target, copying its dep set
```

- [ ] **Step 2: Run the CPU tests**

Run: `scripts/ds4 bazel -- test //tests/test_layer_pack //tests/test_gpu_args`
Expected: PASS.

- [ ] **Step 3: Run the CUDA tests**

Run: `scripts/ds4 bazel -- test --config=cuda //tests:test_mxfp4_cuda`
Expected: PASS (FP4 unit check).

- [ ] **Step 4: Commit**

```bash
git add tests/BUILD.bazel BUILD.bazel
git commit -m "build: port unit/CUDA tests to bazel test

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

---

## Slice 5 — Retire the Makefile

### Task 13: Delete the Makefile + bridge, update docs

**Files:**
- Delete: `Makefile`, `bazel/ds4_make_build.bzl` (untracked bridge — remove file)
- Modify: `README.md`, `AGENT.md`, `.gitignore`

**Interfaces:**
- Consumes: a fully working Bazel build (Tasks 6-12).

- [ ] **Step 1: Confirm nothing but docs references make**

Run: `grep -rn "make cuda-b200\|make verify\|\$(MAKE)\|make test" --include=*.md --include=*.sh . | grep -v docs/superpowers`
Expected: only intended references; fix any script still calling `make`.

- [ ] **Step 2: Delete the Makefile and the untracked bridge**

```bash
git rm Makefile
rm -f bazel/ds4_make_build.bzl bazel/BUILD.bazel   # untracked bridge remnants
```

- [ ] **Step 3: Update README.md + AGENT.md**

Replace all `make ...` / `make verify-b200` instructions with `scripts/ds4 bazel -- build --config=cuda //:...`, `scripts/ds4 verify`, `scripts/ds4 doctor`. In AGENT.md's Testing/Layout sections, describe the Bazel + rootfs build as the one path; note CPU reference is `--//:backend=cpu`.

- [ ] **Step 4: Fresh-checkout verify with no Makefile**

Run: `scripts/ds4 verify`
Expected: `verify: PASS`, exit 0, with no Makefile present.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "build: retire Makefile; Bazel + rootfs is the only build path

Co-authored-by: TRAE CLI <noreply@bytedance.com>"
```

### Task 14: Final end-to-end acceptance

**Files:** none

- [ ] **Step 1: Clean rebuild from a cold Bazel cache**

Run: `scripts/ds4 bazel -- clean --expunge && scripts/ds4 doctor && scripts/ds4 bazel -- build --config=cuda //:ds4 //:ds4-server //:ds4-bench //:ds4-eval //:ds4-agent && scripts/ds4 verify`
Expected: doctor green, all five build, `verify: PASS`.

- [ ] **Step 2: Confirm sm_100 MXFP4-off invariant**

Run: `scripts/ds4 bazel -- build --config=cuda //cuda/mmq:mmq 2>&1 | grep -i "block scale" && echo "BAD" || echo "OK: no MXFP4 on sm_100"`
Expected: `OK: no MXFP4 on sm_100`.

- [ ] **Step 3: Land on local main (never push)**

The commits are already on `main` (or a feature branch fast-forwarded onto it). Confirm `git log --oneline` shows the slices and that `origin` was **not** pushed.

---

## Self-Review

- **Spec coverage:** substrate (Tasks 1-5), native `//:ds4` + rules_cuda + redist + arch/MXFP4 gate (Tasks 6-9), remaining binaries (Task 10), CPU config + verify + tests (Tasks 11-12), Makefile retirement + docs (Tasks 13-14). Build-identity, CUDA-channel doctor, read-only rootfs, and the exit-code ladder are all covered.
- **Open questions** from the spec (rules_cuda device-link parity; redist 13.2 availability) are resolved explicitly in Task 6 Step 1 and Task 9 before the Makefile is deleted — the Makefile is the safety net until parity is proven.
- **Type/name consistency:** `ds4_c_copts()`/`ds4_cuda_copts()`/`DS4_MXF4_DEFINES` defined in `bazel/defs.bzl` (Tasks 7-8) and used consistently; `//:backend` + `//:backend_cpu` consistent across Tasks 11-12; `--build-id` string identical everywhere.
- **Risk note:** the `.cu`-in-`cc_library` vs `cuda_library` choice (Task 8 Step 4) and the build-stamp `-include`/genrule mechanism (Task 8 Step 3) are flagged as "use whichever rules_cuda supports; the acceptance test is the behavior, not the mechanism" so the executor adapts without a placeholder.
