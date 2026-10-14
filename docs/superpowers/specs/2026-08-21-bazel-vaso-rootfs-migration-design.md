# DS4 build migration: native Bazel (rules_cuda) inside a vaso-style bwrap rootfs

**Status:** Design record (approved in brainstorming, pending spec review)
**Date:** 2026-08-21
**Base commit:** `ca17482`
**Repo:** `<HOME_PATH>`

## Purpose

Replace the DS4 Makefile with a native **Bazel** build driven by
**rules_cuda**, executed inside a **vaso-style `bwrap` rootfs**, so the
NVIDIA-CUDA-only DS4 inference engine builds and runs end-to-end repeatably on
the 8x B200 (sm_100) host. The migration is **incremental**: the Makefile stays
authoritative and buildable until the last target is ported, then it is
deleted.

This supersedes the earlier "Bazel wraps the Makefile" bridge
(`bazel/ds4_make_build.bzl`, currently untracked), which only re-shelled `make`
and gave Bazel no real leverage. Here Bazel owns the compile and link steps
directly.

Non-goals: no change to inference semantics, model loading, SSD streaming,
distributed / tensor-parallel execution, KV cache, or the CPU reference math.
Only the build system and the rootfs contract move.

## Decisions (locked in brainstorming)

- **ds4 gets its own vaso-style rootfs** — self-contained (like
  `torchtitan`/`monarch`), not a repo mounted into the `vaso` substrate. The
  rootfs *contract* is borrowed from `~/workspace/vaso`'s design
  (`docs/rootfs-container-infra-design.md`); the implementation lives in ds4.
- **Native Bazel, incremental** — port target by target; delete the Makefile
  last.
- **rules_cuda toolchain** — real Bazel CUDA build (like `nccl` /
  `ferric_continuum`), not a genrule around `nvcc`.
- **CUDA toolkit via rules_cuda redist download** — pinned to CUDA 13.2 (the
  channel the rootfs and host driver already agree on), like `nccl`'s
  `redist_json` 13.0.2. Bazel-hermetic; seeded into the repo cache at rootfs
  build time so the first in-rootfs build needs no network for the toolkit.
- **vaso `/opt`-style tool snapshot** — `bazel` (via bazelisk) + `mise` +
  launcher shims live in a read-only `/opt/ds4` bind, not baked ad hoc into the
  image.
- **CPU reference preserved via a Bazel `config_setting`** — `--//:backend=cpu`
  compiles the same `.c` with `-DDS4_NO_GPU` and links with `cc`, keeping the
  correctness oracle inside the one build system.
- **Scope-out of vaso** — DS4 has no Python/uv/Spack build and no in-repo agent
  runs, so vaso's Tier 2 (Python/uv/PyTorch), Tier 3 (Spack), and Tier 4 (agent
  trajectory capture) are **not** ported. Only the rootfs contract + Bazel/CUDA
  path apply.

## Current build, mapped

The Makefile's substance (base commit `ca17482`):

- **C sources** compiled with `cc` (`-O3 -ffast-math -march=native -std=c99
  -D_GNU_SOURCE`): `ds4.c`, `ds4_distributed.c`, `ds4_tp.c`, `ds4_ssd.c`,
  `ds4_layer_pack.c`, `ds4_build.c` (generated stamp), plus per-binary
  `ds4_cli.c`, `ds4_server.c`, `ds4_bench.c`, `ds4_eval.c`, `ds4_agent.c`,
  and helpers `ds4_help.c`, `ds4_gpu_args.c`, `ds4_web.c`, `ds4_kvstore.c`,
  `rax.c`, `linenoise.c`.
- **CUDA sources** compiled with `nvcc` (`-std=c++17 -Icuda/mmq`, arch flags):
  `ds4_cuda.cu` and the vendored MMQ tier `cuda/mmq/{ds4_ggml_stubs,ds4_mmq,
  ds4_mmq_d2r,quantize,mmid,mmvq,ds4_repack}.cu`.
- **Link** with `nvcc` (`-lcudart -lcublas`, CUDA lib dirs) into five binaries
  sharing `CORE_OBJS`: `ds4`, `ds4-server`, `ds4-bench`, `ds4-eval`,
  `ds4-agent`.
- **C <-> CUDA boundary**: `ds4_gpu.h` wraps the CUDA entry points in
  `extern "C"`; the `.c` files never see CUDA types.
- **Arch / MXFP4 gating** (Makefile `NVCC_ARCH_FLAGS` switch): sm_120/sm_121
  emit `compute_12Xa` + `-DDS4_CUDA_HAVE_MXF4=1`; **sm_100 emits
  `compute_100,sm_100` with no `DS4_CUDA_HAVE_MXF4`** because the warp-level
  `mma.sync ... kind::mxf4.block_scale` used by the MMQ tier is not supported on
  `sm_100a` (ptxas rejects it; datacenter Blackwell only exposes block-scaled
  FP4 through `tcgen05.mma`). This exact behavior must be preserved.
- **Build identity** (`ds4_build.c`): compiled with `DS4_BUILD_*` `-D` flags
  (backend/arch/CUDA/git), regenerated every build via the phony
  `force-build-stamp`, and printed by `--build-id`.
- **CPU reference** (`cpu:` target): recurses with `DS4_BACKEND=cpu
  DS4_BUILD_ARCH=cpu`, compiles the `.c` with `-DDS4_NO_GPU`, links with `cc`,
  stamps `backend=cpu` (no `cuda=`).
- **Verify ladder** (`scripts/verify.sh`, `make verify-b200`): self-re-execs
  into the rootfs; stages preflight/build/launch(`--build-id`)/generate with
  exit codes 21/22/23/24, 25 = generate-skipped, 0 = pass.

## Target Bazel graph

Package layout:

```text
MODULE.bazel                 rules_cc, rules_cuda, CUDA 13.2 redist toolchain
.bazelrc                     default (cuda disabled) + `cuda` config (sm_100)
.bazelversion                9.2.0
BUILD.bazel                  C cc_library(s), build-stamp genrule, 5 cc_binary,
                             config_setting //:backend, verify runner
cuda/mmq/BUILD.bazel         cuda_library for the vendored MMQ tier
bazel/                       shared .bzl helpers (stamp, arch select)
```

### Libraries and binaries

- Group the C sources into a small number of `cc_library` targets by role so
  the graph stays legible rather than one library per file:
  - `//:core` — `ds4.c`, `ds4_distributed.c`, `ds4_tp.c`, `ds4_ssd.c`,
    `ds4_layer_pack.c`, `ds4_build` (generated), headers.
  - `//:net` — `ds4_web.c`, `ds4_kvstore.c`, `rax.c`.
  - `//:repl` — `linenoise.c`.
  - `//:help` — `ds4_help.c`; `//:gpu_args` — `ds4_gpu_args.c`.
- `//cuda/mmq:mmq` — `cuda_library` over the seven vendored `.cu` files, with
  `copts` `-std=c++17`, include `cuda/mmq`, and the arch/MXFP4 `select()`.
- `//:cuda` — `cuda_library` over `ds4_cuda.cu`, depending on `//cuda/mmq:mmq`.
- Five `cc_binary` targets (`//:ds4`, `//:ds4-server`, `//:ds4-bench`,
  `//:ds4-eval`, `//:ds4-agent`), each depending on the relevant C libs plus
  `//:cuda`. rules_cuda contributes `cudart`/`cublas` link deps, so DS4's BUILD
  files do not hand-roll `-lcudart -lcublas`.

### Arch / MXFP4 gating

- `.bazelrc` `cuda` config sets
  `--@rules_cuda//cuda:archs=compute_100:sm_100` (default build has cuda
  disabled and `-cuda` tag filters, like `nccl`).
- `DS4_CUDA_HAVE_MXF4` is a `select()` on the CUDA arch flag: **off for
  sm_100** (matching today), on for the consumer-Blackwell `sm_120a/sm_121a`
  arches if/when built. The `select` carries a comment pointing at the ptxas
  limitation so the gate is not silently widened.

### Build identity

- Bazel `--workspace_status_command` (a small script) emits stable and volatile
  keys: `DS4_BUILD_BACKEND`, `DS4_BUILD_ARCH`, `DS4_BUILD_CUDA`,
  `DS4_BUILD_GIT`.
- A `genrule` writes `ds4_build.c` from those keys (or passes them as `-D`
  defines through a `cc_library` `local_defines`), linked into all five
  binaries. `--build-id` prints the identical string to today:
  `ds4 backend=cuda arch=sm_100 cuda=13.2 git=<sha>`; CPU config prints
  `backend=cpu arch=cpu git=<sha>` with no `cuda=`.

### CPU config

- `string_flag` `//:backend` with values `cuda` (default) and `cpu`; two
  `config_setting`s.
- The C libraries add `-DDS4_NO_GPU` to `local_defines` under
  `select({"//:backend_cpu": [...], "//conditions:default": []})`, and the
  binaries `select()` their deps so the CPU config links with `cc` and omits
  `//:cuda`/`//cuda/mmq:mmq`. Build with
  `bazel build --//:backend=cpu //:ds4`.

## Rootfs contract (vaso-derived, ds4-scoped)

The rootfs is **read-only** at run time with explicit writable binds (today's
`enter_rootfs.sh` binds `/` writable; that is dropped). Inner layout, a subset
of vaso's:

```text
/                         read-only rootfs bind (built image)
/workspace/ds4            checkout, rw
/home/<user>              real user home (bazelisk/mise ~/.cache, dotfiles)
/opt/ds4                  read-only tool snapshot: bazel (bazelisk), mise, shims
/ds4/cache/bazel/...      Bazel output base / repo cache / disk cache (rw)
/run/nvidia-driver/lib    host libcuda.so*/libnvidia-ml.so* (ro)
/run/nvidia-driver/bin    host nvidia-smi (ro)
/dev/nvidia*              device nodes (dev-bind)
/proc /dev /tmp /run      pseudo/tmpfs
```

Environment: `--clearenv` + small allowlist (`TERM`, `COLORTERM`, `LANG`,
`LC_ALL`, `TZ`, `CUDA_VISIBLE_DEVICES`, `NVIDIA_VISIBLE_DEVICES`, proxy/SSL
vars), plus explicit `CUDA_HOME`, `PATH` (driver bin first, then `/opt/ds4`,
then rootfs), `LD_LIBRARY_PATH` (driver projection first so CUDA userspace
resolves the host driver; the rules_cuda-downloaded toolkit is compile-time
only), `BAZEL_*`, `MISE_*`, and `DS4_IN_ROOTFS=1`.

Library-path precedence rule (from vaso): `/run/nvidia-driver/lib` first so
`libcuda.so.1` / NVML resolve from the host driver projection, never from the
toolkit.

### Toolchain manifest and identity gate

`scripts/rootfs/contract.env` grows into a pinned toolchain manifest: base
image digest, bazel version, mise + tool versions, CUDA channel (`13.2`), and
the minimum host driver floor for that channel. The existing
`contract_identity` sha256 gate (`rootfs_target.sh` +
`rootfs_assert_contract_match`) covers the new fields, so a drifted manifest
fails closed before launch. `--emit-plan-only` continues to emit
`bwrap-plan.json` for auditability.

### Provisioning

`build_rootfs.sh`: `docker build` the OS base, install `bazelisk`->pinned
`bazel 9.2.0` and `mise` into `/opt/ds4`, seed the rules_cuda CUDA-13.2 redist
into the Bazel repo cache, then `docker export` -> flatten to a read-only
rootfs. `/opt/ds4` is bound read-only at run time.

## CLI surface

Thin, vaso-style wrappers; no raw bwrap flags leak to callers:

```bash
scripts/rootfs/build_rootfs.sh           # build + export read-only rootfs
scripts/rootfs/enter_rootfs.sh [-- cmd]  # bwrap launcher (interactive/one-shot)
scripts/ds4 doctor                       # host + rootfs + CUDA-channel checks
scripts/ds4 bazel -- build //:ds4        # bazel inside rootfs (self-re-execs)
scripts/ds4 verify                       # build + launch + generate ladder
```

`scripts/ds4` self-re-execs into the rootfs (the pattern `verify.sh` already
uses), then runs `bazel` from `/opt/ds4`.

### doctor checks (ds4-scoped subset of vaso's)

- `bwrap` present and supports required flags; user namespaces work.
- rootfs read-only enforced (negative write probe to `/usr`); writable binds
  work (`/workspace/ds4`, `/ds4/cache`, `/home/<user>`, `/tmp`).
- 8 NVIDIA devices visible; `nvidia-smi` runs.
- `libcuda.so.1` + `libnvidia-ml.so.1` resolve inside; `cuInit` smoke succeeds.
- CUDA-channel coherence: host driver floor vs. channel `13.2`; rules_cuda
  redist version matches the channel; projected `libcuda` API version
  compatible.
- `bazel --version` from `/opt/ds4`; Bazel cache paths are sandbox-relative
  (no host-absolute output base).

### verify ladder (behavior preserved)

Same exit codes: `0` pass, `21` preflight (`doctor`), `22` build
(`bazel build //:ds4`), `23` launch (`//:ds4 --build-id` wrong/missing),
`24` generate crashed/empty, `25` generate skipped (no model). Fixture prompt
`"The capital of France is"`, `-n 8 --temp 0`, assert non-empty output.

## Migration slices

The Makefile stays authoritative and buildable until slice 5. Each slice lands
only after its parity proof.

1. **Substrate** — vaso-style read-only rootfs, `/opt/ds4` tool snapshot,
   `scripts/ds4` dispatcher, `doctor`, contract manifest + identity gate.
   *Proof:* `scripts/ds4 doctor` green; 8 GPUs; `cuInit` smoke; `bazel
   --version` from `/opt/ds4`.
2. **First native target `//:ds4`** — `MODULE.bazel`, `.bazelrc`,
   `cuda/mmq/BUILD.bazel`, root `BUILD.bazel` (C libs, cuda libs, build-stamp
   genrule, `//:ds4`). *Proof:* `bazel build //:ds4` yields a binary whose
   `--build-id` shows `backend=cuda arch=sm_100 cuda=13.2` and that reproduces
   the `make cuda-b200` generation on the same prompt.
3. **Remaining binaries** — `//:ds4-server`, `//:ds4-bench`, `//:ds4-eval`,
   `//:ds4-agent`. *Proof:* each matches its `make` counterpart.
4. **CPU config + tests** — `--//:backend=cpu` `config_setting`; port test
   targets (`test-mxfp4-cuda`, gpu/engine/sampling/session-batch tests,
   `q4k-dot`/`mxfp4-dot`) into `bazel test`. *Proof:* CPU `//:ds4 --build-id`
   shows `backend=cpu`; `bazel test //...` green where hardware allows.
5. **Retire the Makefile** — replace `make verify-b200` with `scripts/ds4
   verify`; delete the Makefile and the untracked
   `bazel/ds4_make_build.bzl` bridge; update `.gitignore`, `README.md`,
   `AGENT.md`. *Proof:* fresh checkout -> `scripts/ds4 verify` -> PASS with no
   Makefile present.

## Testing

- Per slice: **build parity** vs. the `make` target it replaces (same binary
  behavior on the fixture prompt) plus the verify ladder.
- sm_100 MXFP4-off invariant asserted by the arch `select()` (the sm_100 config
  must not define `DS4_CUDA_HAVE_MXF4`) and the existing Q8-path expectation.
- CUDA correctness oracle: the CPU reference build stays reachable
  (`--//:backend=cpu`) for logits/token comparison.

## Guardrails (AGENT.md)

- Touch only the build system and rootfs; inference semantics, SSD streaming,
  distributed, tensor-parallel, and CPU math compile unchanged.
- Single model process (instance lock) preserved.
- CPU reference remains a real, reachable build.
- Makefile deleted **last**, so the repo is never un-buildable mid-migration.
- No C++ added; kernels stay under `cuda/`.

## Landing

Local `main` only, never push. Commit trailer exactly once:
`Co-authored-by: TRAE CLI <noreply@bytedance.com>`.

## Open questions / risks

- **rules_cuda + link-with-nvcc parity**: today the final link is `nvcc`
  (device link + host link). rules_cuda's `cuda_library` + `cc_binary` performs
  the device link internally; slice 2 must confirm the produced binary links
  and runs identically (no missing `__cudaRegister*` device-link step). If a
  raw-`nvcc` device link is needed, keep it inside a rules_cuda-provided path,
  not a genrule.
- **Redist availability for 13.2**: confirm rules_cuda's `redist_json` has a
  13.2 entry; if only 13.0.x is published, either pin the nearest compatible
  toolkit that still targets `sm_100` or fall back to the rootfs
  `/usr/local/cuda` toolkit for the toolchain while keeping the host driver
  projection. Resolve in slice 1/2 before committing the toolchain choice.
- **`-ffast-math` / `-march=native` parity**: carry the exact C `copts` so
  numeric behavior matches the Makefile build (correctness before speed).

## Parity resolution (slice 2, Task 9)

Both open build questions above are **resolved**:

- **rules_cuda device link**: `cuda_library` (`//cuda/mmq:mmq`, `//:cuda`) +
  the `//:ds4` `cc_binary` performs the device link internally — no missing
  `__cudaRegister*` step, no raw-`nvcc` genrule needed. The binary links and
  runs.
- **Redist 13.2**: rules_cuda ships a 13.2 entry (13.2.0/1/2); pinned
  **13.2.2** to match the `cu132` contract. No `/usr/local/cuda` fallback.

Verification: built the Makefile baseline (`make cuda-b200`) and bazel
`//:ds4` inside the rootfs. `--build-id` prints the same shape from both:
`ds4 backend=cuda arch=sm_100 cuda=13.2 git=<sha>` (SHA differs only by the
commit each was built at). Greedy generation (`--temp 0 -n 8`) on
`ds4flash.gguf` produced **byte-identical output** from both binaries —
parity OK.
