#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p inputs
for layer in os cuda-runtime compiler source app metadata objects bazel-tools; do
    test -f "../layers/$layer.tar.gz"
    ln -sfn "../../layers/$layer.tar.gz" "inputs/$layer.tar.gz"
done
