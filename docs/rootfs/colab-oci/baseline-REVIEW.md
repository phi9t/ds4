# Review and verification record

Historical experiment record. Filenames below refer to the retained external
archive or [evidence/](evidence/); use [README.md](README.md) for landed commands.

Independent review covered publisher base identity, source checksum gating, declared mount boundaries, rootfs-owned ELF loader selection, and compressed-layer tar packing. Source tampering was rejected by an actual Docker build; five invalid writable-mount cases were rejected before mutation. See source-pin-negative-test.log and mount-contract-tests.json.

The transport worker verifies the raw OCI manifest against the pinned digest, the config bytes against their descriptor, and all acquired or reused compressed blobs. The packer preserves layer order and stores duplicate blobs once. Its cache is single-writer for this experiment and must remain stable between verification and packaging.

A live CPU trial identified Colab's denial of a new proc mount. The launcher now uses explicit user/IPC/UTS/network namespace isolation and read-only host proc with shared host PID namespace; a live nvcc version invocation succeeded with this configuration. The CPU transport trial does not validate NVIDIA driver projection or GPU execution.

The original baseline restored successfully, then failed at the proc mount. Its timing results remain valid for acquisition/pack/extraction; final rebuild validation is recorded separately in the r2 result archive.
