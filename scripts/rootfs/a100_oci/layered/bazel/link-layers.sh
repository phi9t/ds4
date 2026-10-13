#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p inputs
for layer in os cuda-runtime compiler source app-ds4 app-ds4-bench app-ds4-server app-ds4-eval app-ds4-agent metadata bazel-tools; do
    test -f "../layers/$layer.tar.gz"
    ln -sfn "../../layers/$layer.tar.gz" "inputs/$layer.tar.gz"
done
if test -f ../layers/objects.tar.gz; then
    ln -sfn ../../layers/objects.tar.gz inputs/objects.tar.gz
elif test "${1:-}" = seed; then
    echo "seed requires ../layers/objects.tar.gz" >&2
    exit 1
fi
