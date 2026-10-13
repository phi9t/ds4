# DS4 layered OCI composition

Bazel 9.2.0 and rules_oci 2.3.3 compose existing deterministic gzip tar inputs.
The benchmark source build remains its pinned Makefile workflow.

Copy `/opt/ds4/bazel/project` to a writable directory, such as
`/work/packaging`. Populate `inputs/*.tar.gz` with already acquired and verified
compressed blobs (hardlinks are sufficient). Required inputs are `os`,
`cuda-runtime`, `compiler`, `bazel-tools`, `source`, `app-ds4`, `app-ds4-bench`,
`app-ds4-server`, `app-ds4-eval`, `app-ds4-agent`, and `metadata`. Seed also
requires `objects`. Source tars stay outside the packaged recipe.

`link-layers.sh` links the sibling `../layers/` layout. Objects are optional;
`link-layers.sh seed` explicitly requires them. Each application has its own
layer, so changing one executable replaces only that executable's blob.

Runtime order: os, cuda-runtime, five applications, metadata (8 layers).
Build order: os, cuda-runtime, compiler, bazel-tools, source, five applications,
metadata (11 layers). Seed appends objects (12 layers).

```sh
# Defaults to runtime and build; no object seed is required.
./compose-offline.sh
# Explicit optional seed:
./compose-offline.sh //:seed_image
# Optional daemon-loadable archives, without loading or publishing:
./compose-offline.sh //:runtime_load //:build_load --output_groups=+tarball
```

The default binary is `/opt/ds4/bin/bazel`. The packaged dependency template
`/opt/ds4/bazel/vendor` may remain read-only. The command copies it once into
`${TMPDIR:-/tmp}/ds4-bazel/vendor`; Bazel can then create its per-invocation
`bazel-external` pointer there. Set `DS4_BAZEL_WORK_ROOT=/work/bazel-cache` to
use a writable work mount. `DS4_BAZEL_OUTPUT_ROOT` overrides the output root.
`DS4_BAZEL_VENDOR` selects an existing writable vendor directory and skips the
copy. `DS4_BAZEL` and `DS4_BAZEL_VENDOR_SOURCE` override packaged source paths.
The workspace and output root also must be writable.

The portable tools layer excludes `bazel-external`, inputs, fixtures, and all
output/action/download caches. Generated local repositories require local
fetching, so `--nofetch` cannot serve a fresh output root. The script disables
repository downloads and repository, disk and remote caches. Run the container
with `--network none` to enforce offline operation.

OCI layouts contain relative symlinks to source compressed blobs. Keep inputs
available when inspecting layouts, or export the `tarball` output group for a
standalone archive. `verify-layout.py LAYOUT inputs NAME...` checks ordered
descriptors and SHA256 equality of the exact compressed bytes.

`MODULE.bazel.lock` and vendored repositories preserve dependency metadata;
`acquisition.json` records authoritative acquisition URLs and checksums.
Historical proofs live under `docs/rootfs/colab-oci/evidence/bazel-proofs/`
in the DS4 checkout. They retain the aggregate-app and split-app recipes,
relocated read-only tools, fresh offline roots, and source-edit invalidation.
