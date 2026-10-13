#!/bin/sh
set -eu
cd "$(dirname "$0")"
: "${DS4_BAZEL:=/opt/ds4/bin/bazel}"
: "${DS4_BAZEL_VENDOR:=/opt/ds4/bazel/vendor}"
: "${DS4_BAZEL_OUTPUT_ROOT:=/tmp/ds4-bazel-output}"
exec "$DS4_BAZEL" --batch --output_user_root="$DS4_BAZEL_OUTPUT_ROOT" build \
    --vendor_dir="$DS4_BAZEL_VENDOR" --repository_disable_download --lockfile_mode=error \
    --repository_cache= --disk_cache= --remote_cache= \
    "$@"
