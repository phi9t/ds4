# DS4 Colab OCI layering recommendation

Historical experiment record. Filenames below refer to the retained external
archive or [evidence/](evidence/); use [README.md](README.md) for landed commands.

Research date: 2026-10-11. Scope: primary documentation review and critique of the proposed packaging. No publishing, credential inspection, GPU allocation, or repository mutation. Measurements and DS4 build facts below were supplied by the coordinating task; this review did not independently reproduce them. The coordinating task captured the measured inventory and ldd closure in layering-inventory.json, and separately hashed all eight source/bin executable pairs to confirm exact duplicate contents. Upstream `main` documentation describes current capabilities, not a guarantee about the project's installed versions. Pin the chosen ruleset before implementation.

## Recommendation

Create two independently selectable manifests in the same GHCR package: a runtime image and a rebuild image. Share exactly identical OS and CUDA runtime layer blobs between them. Build their layers from selected inputs rather than inheriting the full development rootfs and deleting files afterward. Keep the rebuild image complete enough to compile without the original developer checkout. Make profiler/debug payload and cache seeds optional, versioned artifacts.

Use `rules_oci` with explicit deterministic tars as the initial, easy-to-audit implementation if the existing Bazel integration does not already choose a ruleset. Its `oci_image` preserves tar order and accepts a base image; one tar becomes one layer. `oci_push` publishes by digest and then applies tags sequentially, so a two-tag release is not atomic. Record both manifest digests in a release descriptor and restore by digest. [rules_oci image API](https://github.com/bazel-contrib/rules_oci/blob/main/docs/image.md), [migration documentation](https://github.com/bazel-contrib/rules_oci/blob/main/docs/migrate_from_rules_docker.md), [push API](https://github.com/bazel-contrib/rules_oci/blob/main/docs/push.md).

`rules_img` is a credible alternative when avoiding base-blob materialization during Bazel image assembly matters. Its layer creation produces blob and metadata in one action; image assembly can depend on metadata alone. Its default shallow base pull fetches manifest/config and defers layer bytes. These optimize the build and publish path. They do not remove bytes that a cold Colab restore needs. Do not justify a migration with an unmeasured notebook speedup. [rules_img architecture comparison](https://github.com/bazel-contrib/rules_img#key-differences-explained), [pull API](https://github.com/bazel-contrib/rules_img/blob/main/docs/pull.md).

## What the measurements establish

| Supplied observation | Packaging implication |
| --- | --- |
| Rootfs regular unique files: 8,573,331,996 bytes; compressed OCI: 4,624,656,116 bytes | Separate logical contents from compressed transfer sizes. New compressed sizes require measurement. |
| `/opt/nvidia`: 1,303,412,104 bytes, identified as Nsight payload | Exclude from runtime; make profiler tooling optional unless a rebuild actually requires it. |
| CUDA target static libraries: 2,563,805,528 bytes; headers: 30,814,337 bytes | Development contents belong in the rebuild image. Retain the static libraries the actual link uses. |
| Required cuBLAS/cuBLASLt/cudart: 596,592,456 bytes; other CUDA libraries: 1,377,285,074 bytes | Use the observed loader closure as a starting point. GPU execution and dynamic loading must decide which additional runtime libraries survive. |
| Executable duplicates under `/opt/ds4/source` and `/opt/ds4/bin`: approximately 428.75 MB each | Verify byte identity, then keep one canonical copy; do not package generated executable copies as source. |
| Five binaries: debug stripping changes 284.33 MB to 170.57 MB; original unstripped objects: 93.04 MB | Package stripped runtime binaries only after validating them; retain symbols/objects separately when needed. These quantities can overlap other rows. |
| CPU restore: 159.49 s download/hash, 32.28 s direct compressed packing, 221.05 s export/extract | The measured path spends time after transfer too. Layering alone does not eliminate export/extraction. No GPU inference timing follows from this CPU test. |

Do not add these observations into a claimed savings total. Categories can overlap, and their compression ratios differ.

## Refine the proposed layer split

| Layer or artifact | Runtime manifest | Rebuild manifest |
| --- | --- | --- |
| Stable minimal OS, loader, glibc/libstdc++ closure, shell and extraction essentials | Yes | Same blob |
| CUDA runtime closure with SONAME links | Yes | Same blob |
| Compiler, Bazel, CUDA development tools/headers/required static libraries | No | Yes |
| Pinned offline external dependency inputs | No | Yes |
| Exact source snapshot, build files, lockfiles, patches, recipe and provenance | No | Yes, late layer |
| DS4 runtime binaries and runtime configuration | Yes, late layer | Yes for the requested build bundle, identical shared blob |
| Test executables, debug symbols, profiler tools | No | Optional distinct payload |
| Compatible Bazel cache seed | No | Optional artifact |

Put stable OS contents first and frequently edited source/binaries last, but avoid making the launcher part of a large stable layer if it changes with the recipe. A tiny launcher/config layer is cheap to replace. Prevent paths from being owned by several layers unless replacement is deliberate; preserve permissions and required symlinks.

Layer reuse requires identical compressed bytes/digests, not just equivalent filesystem contents. Use stable tar metadata and compression settings. Two manifests referencing the same layer descriptors in one package give a straightforward shared-blob design; client-side warm restore still needs a persistent, digest-keyed blob cache. A fresh notebook has no such cache by default. OCI manifests describe their layers by digest and size. [OCI manifest specification](https://github.com/opencontainers/image-spec/blob/main/manifest.md).

Do not base runtime on rebuild and add deletion whiteouts. Whiteouts hide lower-layer paths when applying changesets; the older blobs remain referenced. Ordinary tar extraction of independent layers also needs proper whiteout handling. Preserve an OCI-aware flattening step or deliberately create disjoint layers without deletion markers. [OCI layer specification](https://github.com/opencontainers/image-spec/blob/main/layer.md). Current `go-containerregistry` extraction iterates through all image layers and reads their uncompressed tar contents. [Extraction implementation](https://github.com/google/go-containerregistry/blob/main/pkg/v1/mutate/mutate.go).

`rules_img` can hardlink identical files within a generated tar. Explicitly removing redundant source-tree executables is easier to inspect and works with either ruleset. Do not assume its hardlink optimization deduplicates arbitrary separate layers or cached developer outputs. [rules_img layer optimization](https://github.com/bazel-contrib/rules_img#layer-optimization).

## Rebuilding and compatibility are acceptance criteria

The live devx checkout at HEAD `0be4cd46f1bc888218c7972713f5a54b652e8f6a` used CUDA 13.2, sm100, hardcoded buildstamp and `-march=native`. The previously benchmarked immutable `fc80bd6` snapshot targets CUDA 13.0, sm80 and portable x86-64. These are different build contracts. Label each artifact with its actual source revision, CUDA/toolchain versions, target GPU architecture, CPU ISA flags and recipe digest. An amd64 OCI label alone does not establish CPU or GPU portability.

The `fc80bd6` source archive contains Makefiles and no `BUILD.bazel` or `MODULE.bazel`. Preserve its Makefile bundle as the rebuild baseline. First prove a clean rebuild with the bundled compiler, Make, development CUDA and required external inputs. Bazel image packaging can wrap immutable built-artifact inputs without changing engine source or moving compiler actions onto Bazel. A Bazel rebuild of this snapshot requires an explicit, source-pinned build-rule overlay and its own validation. Moving compilation onto the live Bazel checkout changes the source and target contract; it requires portable CPU/GPU configuration and a correct buildstamp. A source layer cannot repair incompatible flags or a fabricated buildstamp.

The viewed rootfs builder installs a Bazelisk shim and sets `USE_BAZEL_VERSION`; this does not demonstrate that the actual Bazel executable or dependency archives are bundled. If Bazel execution is part of the delivered offline workflow, include the actual pinned executable and complete fetch inputs, then prove that workflow works with networking disabled and empty user/repository/action caches. Do not infer prefetching from the version environment variable. This requirement is separate from the Makefile engine rebuild.

An offline dependency layer must include the actual fetch inputs for the selected Bazel version and dependency mechanism. A repository cache, a disk action cache, and an output base have different purposes. Bazel documents the repository cache and `--distdir` as fetch mechanisms; action caches reuse action results. Keep any seed optional so an absent/incompatible seed causes a rebuild rather than invalidating the bundle. Version its contract and verify an empty-cache rebuild first. Never package opaque `bazel-out`/output-base state or absolute checkout symlinks as the rebuilding mechanism. [Bazel external dependency FAQ](https://bazel.build/external/faq), [Bazel cache documentation](https://bazel.build/remote/caching).

## Compression and restore gates

Keep gzip as the baseline. Test a small zstd OCI fixture through the exact installed `crane` and offline restore commands before selecting zstd for the full payload. Current upstream `go-containerregistry` has zstd support, but that does not prove the installed binary's version or every used path. Compare compressed size, download/hash, packing and export/extraction separately on the final candidate. [Current tarball implementation](https://github.com/google/go-containerregistry/blob/main/pkg/v1/tarball/layer.go).

eStargz needs a compatible lazy snapshotter for demand-driven filesystem access. Plain `crane export` produces a flattened tar and cannot deliver that runtime benefit. Exclude a snapshotter migration from the first Colab packaging change. [stargz snapshotter overview](https://github.com/containerd/stargz-snapshotter/blob/main/docs/overview.md), [crane export API](https://github.com/google/go-containerregistry/blob/main/cmd/crane/doc/crane_export.md).

Before claiming completion, verify manifest layer overlap, compressed blob sizes/digests, final path inventory, duplicate elimination, CPU restore, an empty-cache offline rebuild and runtime loading. GPU inference must exercise the pruned runtime including dynamically loaded dependencies; `ldd` alone is insufficient. With `rules_img`, do not treat an `mtree` from a shallow image as complete filesystem evidence: its API explicitly permits unavailable layers to be skipped. [rules_img image API](https://github.com/bazel-contrib/rules_img/blob/main/docs/image.md).

Keep the separate 86.72 GB weights outside these rootfs images. A later weight-transfer change should verify chunks during transfer, resume verified chunks, and bind the ordered chunk manifest to the final weights digest. No weight-transfer implementation or speed estimate is proposed here.

## Proposed bounded comparison

This is a recommended design, not an implemented replacement or a proven global optimum. Compare three candidates on CPU-only Colab: the published full development rootfs as baseline; a selected minimal rebuild rootfs with coarse layers; and the same selected contents split by dependency version and change frequency. Separately measure an inference-only runtime manifest. Hold source commit, CUDA version, sm_80 target, x86-64 flags, compression, downloader concurrency and cache conditions fixed. Include download+digest verification, materialization, fresh offline compile, incremental rebuild and exact blob reuse after a one-source-file edit. Exclude weights from this rootfs comparison. Confirm GPU-loaded runtime dependencies in a later authorized GPU validation before treating the trimmed runtime as inference-ready.

Use identical OS/CUDA/runtime-binary blobs in runtime and build tags within the existing package. Compose both from a common base, rather than making runtime inherit the development image. A tiny bundle-identity/launcher layer stays separate from large stable files. Actual source and app payload change together as needed; compiler/dependency layers should stay identical. Seeded action caches remain a performance aid, while source/toolchain/offline dependency inputs must be sufficient without them.

A standard OCI manifest fetches all referenced layers in a cold restore. Splitting compiler files into another layer does not make that layer optional within the build manifest. Runtime/build selection happens by choosing a different manifest. A full build bundle remains the default for experiments that may rebuild.
