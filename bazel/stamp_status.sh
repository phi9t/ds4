#!/usr/bin/env bash
# Stable build identity for --build-id. Bazel calls this; keys become available
# to genrules/defines. The git SHA must be stable, not volatile, so a new commit
# invalidates the stamped ds4_build_git.h action instead of reusing an old SHA.
echo "STABLE_DS4_BUILD_GIT_SHA $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
