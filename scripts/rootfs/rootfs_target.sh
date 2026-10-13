#!/usr/bin/env bash
# Shared canonical target resolver for the DS4 bwrap rootfs.
#
# The builder and launcher must agree on exactly which directories may be
# created, replaced, or deleted. An arbitrary --dest or --rootfs must never
# become a deletion target through a typo, a symlink, or a broad directory.
# This library provides one fail-closed resolver and an ownership-marker
# contract that both scripts source. Adapted from torchtitan/scripts/rootfs.
#
# Policy: the allowlist contains only the canonical target scripts/rootfs/rootfs.

ROOTFS_TARGET_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOTFS_OWNERSHIP_MARKER_NAME=".ds4-rootfs-owner"

# The allowlist: canonical real paths that may be built or replaced.
rootfs_allowlist() {
  printf '%s\n' "${ROOTFS_TARGET_REPO_ROOT}/scripts/rootfs/rootfs"
}

rootfs_die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

# Canonicalize a requested destination without following a final symlink and
# refuse hostile shapes. Prints the canonical absolute path on success.
#
# The parent directory must already exist and be a real, non-symlinked
# directory; the basename is appended without traversal. This lets us resolve a
# not-yet-created target while refusing a symlinked or non-directory parent.
rootfs_resolve_managed_dest() {
  local requested="$1"
  if [[ -z "${requested}" ]]; then
    rootfs_die "empty rootfs destination is not allowed"
  fi
  if [[ "${requested}" == "/" ]]; then
    rootfs_die "refusing / as a rootfs destination"
  fi

  local parent basename
  parent="$(dirname -- "${requested}")"
  basename="$(basename -- "${requested}")"
  if [[ -z "${basename}" || "${basename}" == "." || "${basename}" == ".." ]]; then
    rootfs_die "invalid rootfs basename in ${requested}"
  fi
  if [[ ! -d "${parent}" ]]; then
    rootfs_die "rootfs parent is not an existing directory: ${parent}"
  fi
  # Refuse a symlinked parent component: canonicalize the parent with -P (no
  # symlinks) and compare against a plain resolution. A symlinked parent would
  # otherwise let a delete target escape the allowlist.
  local canonical_parent
  canonical_parent="$(cd -P -- "${parent}" && pwd)" \
    || rootfs_die "cannot resolve rootfs parent: ${parent}"
  local logical_parent
  logical_parent="$(cd -- "${parent}" && pwd)" \
    || rootfs_die "cannot resolve rootfs parent: ${parent}"
  if [[ "${canonical_parent}" != "${logical_parent}" ]]; then
    rootfs_die "refusing symlinked parent component for ${requested}"
  fi

  local canonical="${canonical_parent}/${basename}"

  # Refuse broad or sensitive roots outright.
  case "${canonical}" in
    "/"|"${HOME}"|"${ROOTFS_TARGET_REPO_ROOT}")
      rootfs_die "refusing broad rootfs destination: ${canonical}"
      ;;
  esac

  # If the exact path already exists it must be a real directory, not a symlink
  # or other file type.
  if [[ -L "${canonical}" ]]; then
    rootfs_die "refusing symlink rootfs destination: ${canonical}"
  fi
  if [[ -e "${canonical}" && ! -d "${canonical}" ]]; then
    rootfs_die "rootfs destination exists and is not a directory: ${canonical}"
  fi

  local allowed
  while IFS= read -r allowed; do
    if [[ "${canonical}" == "${allowed}" ]]; then
      printf '%s\n' "${canonical}"
      return 0
    fi
  done < <(rootfs_allowlist)

  rootfs_die "rootfs destination is not in the allowlist: ${canonical}"
}

rootfs_ownership_marker_path() {
  printf '%s/%s\n' "$1" "${ROOTFS_OWNERSHIP_MARKER_NAME}"
}

# Identity of the pinned rootfs contract: a hash over the reviewed contract.env
# values that define what the rootfs *is* (base image digest, bazel, CUDA). The
# builder stamps this into the ownership marker; the launcher recomputes it from
# the current contract.env and refuses a rootfs whose identity has drifted. Any
# edit to contract.env therefore forces an explicit rebuild instead of silently
# launching a stale or hand-modified tree.
rootfs_contract_identity() {
  local contract="${ROOTFS_TARGET_REPO_ROOT}/scripts/rootfs/contract.env"
  [[ -f "${contract}" ]] || rootfs_die "missing rootfs contract: ${contract}"
  # Hash only the pinned identity fields, so cosmetic comment edits don't churn
  # the identity but any pin change does.
  local fields
  fields="$(
    # shellcheck disable=SC1090
    source "${contract}"
    printf 'schema=%s arch=%s image=%s bazel=%s cuda=%s channel=%s driver_floor=%s bazelisk=%s mise=%s' \
      "${DS4_ROOTFS_SCHEMA:-}" "${DS4_ROOTFS_ARCH:-}" "${DS4_BASE_IMAGE:-}" \
      "${DS4_BAZEL_VERSION:-}" "${DS4_CUDA_VERSION:-}" \
      "${DS4_CUDA_CHANNEL:-}" "${DS4_DRIVER_FLOOR:-}" "${DS4_BAZELISK_VERSION:-}" \
      "${DS4_MISE_VERSION:-}"
  )"
  printf '%s' "${fields}" | sha256sum | cut -d' ' -f1
}

# Record builder ownership before extraction so a later replace can prove the
# target is a managed rootfs and not an unrelated directory. The marker also
# carries the contract identity (see rootfs_contract_identity) so the launcher
# can detect a rootfs built from a different contract.env.
rootfs_write_ownership_marker() {
  local dest="$1"
  [[ -d "${dest}" ]] || rootfs_die "cannot mark non-directory: ${dest}"
  {
    printf 'ds4-rootfs\n'
    printf 'contract_identity=%s\n' "$(rootfs_contract_identity)"
  } > "$(rootfs_ownership_marker_path "${dest}")"
}

# Assert the rootfs at $dest was built from the current contract.env. Prints a
# clear remediation and fails closed on any mismatch or a legacy identity-free
# marker, so a stale rootfs cannot launch silently.
rootfs_assert_contract_match() {
  local dest="$1"
  local marker
  marker="$(rootfs_ownership_marker_path "${dest}")"
  [[ -f "${marker}" ]] || rootfs_die "rootfs has no ownership marker: ${dest} (rebuild with scripts/rootfs/build_rootfs.sh)"
  local stamped
  stamped="$(sed -n 's/^contract_identity=//p' "${marker}")"
  if [[ -z "${stamped}" ]]; then
    rootfs_die "rootfs marker predates contract identity: ${dest} (rebuild with scripts/rootfs/build_rootfs.sh --rebuild)"
  fi
  local current
  current="$(rootfs_contract_identity)"
  if [[ "${stamped}" != "${current}" ]]; then
    rootfs_die "rootfs was built from a different contract.env (marker ${stamped:0:12} != contract ${current:0:12}); rebuild with scripts/rootfs/build_rootfs.sh --rebuild"
  fi
}

# Refuse to remove or replace a directory unless its exact, non-symlink path
# carries a valid builder ownership marker.
rootfs_assert_removable() {
  local dest="$1"
  if [[ -z "${dest}" ]]; then
    rootfs_die "empty rootfs destination is not removable"
  fi
  if [[ -L "${dest}" ]]; then
    rootfs_die "refusing to remove symlink rootfs destination: ${dest}"
  fi
  if [[ ! -d "${dest}" ]]; then
    rootfs_die "rootfs destination is not a directory: ${dest}"
  fi
  local marker
  marker="$(rootfs_ownership_marker_path "${dest}")"
  if [[ ! -f "${marker}" ]]; then
    rootfs_die "refusing to remove rootfs without ownership marker: ${dest}"
  fi
}
