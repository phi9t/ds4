#!/usr/bin/env bash
# Build and export the DS4 CUDA bwrap rootfs. Host-side work is limited to
# shell, docker, and tar. The rootfs ships the pinned CUDA 13.2 devel toolkit
# (nvcc + cuBLAS) plus build-essential/make and a pinned bazel 9.2.0, so DS4's
# Bazel wrapper and compatibility build tools run hermetically inside it. The host
# driver (libcuda.so) is bound in at launch by enter_rootfs.sh.
#
# Adapted from torchtitan/scripts/rootfs/build_rootfs.sh.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOTFS_DIR="$REPO_ROOT/scripts/rootfs"

# shellcheck source=scripts/rootfs/rootfs_target.sh
source "$ROOTFS_DIR/rootfs_target.sh"
# shellcheck source=scripts/rootfs/contract.env
source "$ROOTFS_DIR/contract.env"

TAG="ds4-rootfs:local"
DEST="$ROOTFS_DIR/rootfs"
REBUILD=0
BASE_IMAGE="$DS4_BASE_IMAGE"
BAZEL_VERSION="$DS4_BAZEL_VERSION"
BAZELISK_VERSION="$DS4_BAZELISK_VERSION"
MISE_VERSION="$DS4_MISE_VERSION"

usage() {
  cat <<'EOF'
Usage: scripts/rootfs/build_rootfs.sh [options]

Build and export the DS4 CUDA bwrap rootfs. Host-side work is limited to
shell, docker, and tar.

Options:
  --rebuild       Force a docker rebuild even if the image tag exists.
  --tag TAG       Docker image tag to build/use (default: ds4-rootfs:local).
  --dest DIR      Directory to export the flattened rootfs into
                  (default: scripts/rootfs/rootfs).
  -h, --help      Show this help and exit.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=1; shift ;;
    --tag) TAG="${2:?--tag requires a value}"; shift 2 ;;
    --tag=*) TAG="${1#*=}"; shift ;;
    --dest) DEST="${2:?--dest requires a value}"; shift 2 ;;
    --dest=*) DEST="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

log() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
die() {
  printf '\033[1;31merror: %s\033[0m\n' "$*" >&2
  exit 1
}

command -v docker >/dev/null || die "docker not found on host"

# Resolve the destination through the shared fail-closed resolver before any
# Docker work or filesystem mutation. An arbitrary --dest that is not in the
# allowlist, is symlinked, or has a symlinked parent is refused here rather
# than becoming a deletion target below.
DEST="$(rootfs_resolve_managed_dest "$DEST")"

image_exists() { docker image inspect "$TAG" >/dev/null 2>&1; }

if image_exists && [[ "$REBUILD" -eq 0 ]]; then
  log "image $TAG already exists (use --rebuild to force)"
else
  log "building $TAG from $BASE_IMAGE (bazel $BAZEL_VERSION)"
  docker build -t "$TAG" \
    --build-arg BASE_IMAGE="$BASE_IMAGE" \
    --build-arg BAZEL_VERSION="$BAZEL_VERSION" \
    --build-arg BAZELISK_VERSION="$BAZELISK_VERSION" \
    --build-arg MISE_VERSION="$MISE_VERSION" \
    -f - "$ROOTFS_DIR" <<'DOCKERFILE'
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG BAZEL_VERSION
ARG BAZELISK_VERSION
ARG MISE_VERSION
SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# build-essential/make/gcc provide the C/C++ build toolchain; curl+ca-certificates
# fetch bazel and, at runtime inside the rootfs, model shards.
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
        bash build-essential gcc g++ make \
        git curl ca-certificates python3 && \
    rm -rf /var/lib/apt/lists/*

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

# The CUDA devel base already provides /usr/local/cuda with nvcc + cuBLAS. Prove
# it so a broken base fails the build rather than the first Bazel build.
RUN test -x /usr/local/cuda/bin/nvcc && /usr/local/cuda/bin/nvcc --version

RUN mkdir -p /workspace/ds4 /ds4/cache /home/ds4 /opt/ds4/bin

ENV CUDA_HOME=/usr/local/cuda CUDA_PATH=/usr/local/cuda
ENV PATH=/opt/ds4/bin:/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin
DOCKERFILE
fi

log "exporting $TAG to $DEST"
mkdir -p "$(dirname "$DEST")"
STAGE="$(mktemp -d "${DEST%/*}/.rootfs.stage.XXXXXX")"
cid="$(docker create "$TAG")"
trap 'docker rm -f "$cid" >/dev/null 2>&1 || true; rm -rf "$STAGE"' EXIT
docker export "$cid" | tar -C "$STAGE" -xf -
[[ -x "$STAGE/bin/bash" ]] || die "export produced an unusable rootfs (no bin/bash)"
# Mark the staged tree as builder-owned before it can replace the destination,
# so a later rebuild can prove the target is a managed rootfs.
rootfs_write_ownership_marker "$STAGE"
# Only replace an existing destination that carries a valid ownership marker;
# an unrelated or ambiguous existing directory is never removed.
if [[ -e "$DEST" ]]; then
  rootfs_assert_removable "$DEST"
  rm -rf "$DEST"
fi
mv "$STAGE" "$DEST"
trap 'docker rm -f "$cid" >/dev/null 2>&1 || true' EXIT

log "rootfs ready: $DEST"
