# Current CPU Colab no-rebuild run cpu3

Run date: 2026-10-13 UTC.

This run validates the current DS4 Bazel/CUDA 13.2 A100 rootfs image on a CPU
Standard Google Colab session. It restores the digest-pinned GHCR image, enters
it through `launch_insula.py`, and runs packaged payload checks without rebuilding
on the Colab host.

## Artifact

- Reference: `ghcr.io/phi9t/ds4-current-rootfs@sha256:3b828391b5c97ff04aa90a0677d738705b624f237492e0fdaa597a885a2ba863`
- Mode: `cpu`
- Phase: `complete`
- No remote rebuild: `True`
- Status SHA256: `6e189c0f82537fe6d8acc43160b2d6557c8f91501f6eb32fa3b247e80b81c918`
- Results ZIP SHA256: `5cd3b6bc24b6218057f4372e48ff4d9ea718ae068d08a3421f51f84c7ba6b272`

## Restore Timings

- `metadata`: 1.057 s
- `download-and-verify`: 122.932 s; bytes=3723639511; cached_layers=0
- `pack`: 108.337 s
- `materialize-and-verify`: 183.904 s

## In-Rootfs Checks

- `help-ds4`: rc=0 in 2.378 s
- `help-ds4-bench`: rc=0 in 0.215 s
- `help-ds4-server`: rc=0 in 0.215 s
- `help-ds4-eval`: rc=0 in 0.215 s
- `help-ds4-agent`: rc=0 in 0.215 s
- `build-id-ds4`: rc=0 in 0.266 s
- `build-id-ds4-server`: rc=0 in 0.215 s
- `toolchain-nvcc-version`: rc=0 in 0.115 s
- `readonly-root`: rc=0 in 0.215 s

The CPU Colab session was stopped after evidence collection; `colab sessions` reported no active sessions.
