# Define The GHCR Publication Contract

Type: grilling
Status: resolved
Blocked by: 03
Parent: ../map.md
Labels: wayfinder:grilling

## Question

What GHCR package, tag scheme, digest-pinning rule, visibility check, and
credential boundary should the pipeline use for publication? Decide the
pre-push safety checks, immutable release-record format, rollback behavior, and
the exact human authorization required before any registry mutation.

## Decision

Use one package for the current pipeline: `ghcr.io/phi9t/ds4-current-rootfs`.
`scripts/rootfs/a100_oci/current_publish.py` tags the local imported image as
`main-<git-short>-<cuda-arch>` unless the operator supplies `--tag`. The
immutable `repository@sha256:<manifest>` reference is the retrieval handle used
by Colab.

The release record lives outside Git by default under
`.ds4/colab-current/<run>/release.json`. It stores the tag, digest, manifest
layers, compressed byte count, rootfs contract identity, build IDs, binary
hashes, and `/opt/ds4/bundle-manifest.json` SHA256. Git may later retain a
compact copied evidence summary, but the image and credentials stay out of Git.

Credentials are read from a mode-0600 token file. The publisher creates a
temporary Docker config for push and does not bake credentials into the image.
The package must be private before push when it already exists, and must be
private after push unless the operator explicitly passes `--skip-private-check`.
