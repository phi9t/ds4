#!/bin/sh
set -eu
cd "$(dirname "$0")"
: "${DS4_BAZEL:=/opt/ds4/bin/bazel}"
: "${DS4_BAZEL_WORK_ROOT:=${TMPDIR:-/tmp}/ds4-bazel}"
: "${DS4_BAZEL_VENDOR_SOURCE:=/opt/ds4/bazel/vendor}"
mkdir -p "$DS4_BAZEL_WORK_ROOT"
if test -z "${DS4_BAZEL_VENDOR:-}"; then
    DS4_BAZEL_VENDOR="$DS4_BAZEL_WORK_ROOT/vendor"
    if ! test -d "$DS4_BAZEL_VENDOR"; then
        stage=$(mktemp -d "$DS4_BAZEL_WORK_ROOT/vendor.XXXXXX")
        cp -a "$DS4_BAZEL_VENDOR_SOURCE/." "$stage/"
        rm -f "$stage/bazel-external"
        mv "$stage" "$DS4_BAZEL_VENDOR"
    fi
fi
: "${DS4_BAZEL_OUTPUT_ROOT:=$DS4_BAZEL_WORK_ROOT/output}"
if test "$#" -eq 0; then
    set -- //:runtime_image //:build_image
fi
exec "$DS4_BAZEL" --batch --output_user_root="$DS4_BAZEL_OUTPUT_ROOT" build \
    --vendor_dir="$DS4_BAZEL_VENDOR" --repository_disable_download --lockfile_mode=error \
    --repository_cache= --disk_cache= --remote_cache= \
    "$@"
