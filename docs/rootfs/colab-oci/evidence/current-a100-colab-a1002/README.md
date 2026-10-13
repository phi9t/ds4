# Current A100 Colab gate run a1002

Run date: 2026-10-13 UTC.

This run validates the current DS4 Bazel/CUDA 13.2 A100 rootfs image on a Google
Colab A100 runtime. It restores the digest-pinned GHCR image, enters it through
`launch_insula.py --gpu`, and runs packaged payload, toolchain, driver-projection,
and read-only checks without rebuilding on the Colab host.

## Artifact

- Reference: `ghcr.io/phi9t/ds4-current-rootfs@sha256:3b828391b5c97ff04aa90a0677d738705b624f237492e0fdaa597a885a2ba863`
- Mode: `gpu`
- Phase: `complete`
- No remote rebuild: `True`
- Status SHA256: `d22f93fccbd31a0f7536c5e02fe6d79400a32ca7c521c0c5fdf468792a498377`
- Results ZIP SHA256: `88bbc87d3bf4978e64ae2d550cbd451d68c7c9737980578bd3397f3455f8019c`

## Restore Timings

- `metadata`: 0.795 s
- `download-and-verify`: 137.870 s; bytes=3723639511; cached_layers=0
- `pack`: 6.926 s
- `materialize-and-verify`: 78.907 s

## In-Rootfs Checks

- `help-ds4`: rc=0 in 0.214 s
- `help-ds4-bench`: rc=0 in 0.265 s
- `help-ds4-server`: rc=0 in 0.215 s
- `help-ds4-eval`: rc=0 in 0.264 s
- `help-ds4-agent`: rc=0 in 0.214 s
- `build-id-ds4`: rc=0 in 0.264 s
- `build-id-ds4-server`: rc=0 in 0.214 s
- `toolchain-nvcc-version`: rc=0 in 0.164 s
- `readonly-root`: rc=0 in 0.164 s
- `inside-nvidia-smi`: rc=0 in 0.164 s

`inside-nvidia-smi` reported `NVIDIA A100-SXM4-40GB, 580.82.07` in the downloaded results ZIP. No model weights were staged under `/content/weights`, so this gate did not run generation.
