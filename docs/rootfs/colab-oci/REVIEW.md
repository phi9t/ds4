# Independent review and repair

Historical experiment record. Filenames below refer to the retained external
archive or [evidence/](evidence/); use [README.md](README.md) for landed commands.

Spec review found and resolved private-registry preflight ordering, optional object inputs, writable vendored Bazel storage, and source/compiler/flags/object seed provenance. Runtime-only loader checks and clean source rebuild checks were required separately. Quality review found and resolved duplicated aggregate application ownership in the receipt. Publication now materializes verified regular-file OCI views because the installed crane rejects Bazel's blob symlinks.

Source pinning and application duplicates were verified against real bytes. Both fresh offline Bazel builds from final inputs must yield identical manifests and preserve raw compressed descriptors. CPU Colab tests verify cold acquisition, rootfs protection, complete compiler tools, clean offline compilation, guarded seed reuse, default offline Bazel composition, and an actual benchmark edit's changed descriptor set. Review output was evaluated against the final code; execution evidence remains distinct from inspected reports.

The first extraction attempt dropped nested C headers through an unanchored top-level sys exclusion; a real compile failed and passed after anchoring it. The first published layered CPU trial restored and loaded correctly but exposed missing nvdisasm, required by cuobjdump SASS inspection. The corrected compiler layer adds it; live builder compilation/SASS inspection then passed. First-attempt receipts and ZIP are retained separately from the final release.

This remains a trusted-command Insula-model proof launcher, not the existing Insula Rust CLI or a hostile-code boundary. GPU driver projection/inference validation is outside the CPU-only test.

Final independent integration review passed against cpu-results-final.zip, release.json and the edited CLI postcheck: all 22 scripted outcomes, CPU-only receipts, source/compiler/cache contracts, exact baseline manifests, and intended changed descriptor sets were verified. Colab termination was confirmed with zero active assignments and zero usage rate.
