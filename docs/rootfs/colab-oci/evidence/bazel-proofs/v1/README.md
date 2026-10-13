# DS4 layered OCI composition

Bazel 9.2.0 and rules_oci 2.3.3 compose existing deterministic gzip tar inputs.
The benchmark source build remains its pinned Makefile workflow. This recipe
introduces no dependency on a host checkout or host compiler.

Copy `/opt/ds4/bazel/project` to a writable work directory, such as
`/work/packaging`. Populate `inputs/*.tar.gz` with the already acquired and
verified compressed blobs (hardlinks are sufficient). The inputs are `os`,
`cuda-runtime`, `compiler`, `source`, `app`, `metadata`, `bazel-tools`, and
optionally `objects`. `link-layers.sh` is a sibling-directory convenience for
this bundle's `../layers/` layout. No source tar belongs inside the template.

The runtime order is os, cuda-runtime, app, metadata. The build order is os,
cuda-runtime, compiler, source, app, metadata, bazel-tools. Seed appends objects.
No full CUDA devel base image is included.

```sh
./compose-offline.sh //:runtime_image //:build_image
./compose-offline.sh //:seed_image
# Optional daemon-loadable archives, without loading or publishing:
./compose-offline.sh //:runtime_load //:build_load --output_groups=+tarball
```

The default binary is `/opt/ds4/bin/bazel`, and dependency vendor directory is
`/opt/ds4/bazel/vendor`. Override with `DS4_BAZEL`, `DS4_BAZEL_VENDOR` and
`DS4_BAZEL_OUTPUT_ROOT`. The workspace, output root, and vendor directory must
be writable. Bazel creates a `bazel-external` symlink under the vendor directory
for each invocation; that symlink is excluded from the portable bundle.
Bazel's generated local repositories require local fetching, so `--nofetch`
is unsuitable with a fresh output root. The script instead disables repository
downloads and repository, disk and remote caches. Run the container with
`--network none` for an enforceable offline proof.

OCI layouts contain relative symlinks to source compressed blobs. Keep the
workspace inputs available when inspecting layouts, or export the `tarball`
output group for a standalone archive. `verify-layout.py LAYOUT inputs NAME...`
checks ordered descriptors and SHA256 equality of the exact compressed bytes.

`MODULE.bazel.lock` and vendored repositories preserve dependency metadata.
`acquisition.json` records authoritative acquisition URLs and checksums.
The fixture proof used fresh empty outputs in the preexisting CPU-only image
`ds4-a100-build:fc80bd6-cu130`, with Docker networking disabled. It composed
runtime/build/seed layouts and daemon-loadable tarballs in 54 actions; all
fixture gzip bytes matched their OCI descriptors. Real-layer integration is
recorded separately after the parent provides the complete tools layer.
