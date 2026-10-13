#ifndef DS4_BUILD_H
#define DS4_BUILD_H

/* Build identity banner.
 *
 * ds4_build.c is compiled with the backend, GPU arch, CUDA version, and git SHA
 * passed as -D flags by the Bazel build_stamp local_defines (see BUILD.bazel),
 * and its object is rebuilt on every build so the SHA never goes stale.
 * Because the CPU build and every CUDA target emit the same filenames (./ds4,
 * ./ds4-server, ...), the filename alone cannot tell you what a binary is; this
 * banner lets each binary describe itself so a launch or a verify step can
 * refuse a stale or wrong-arch build instead of guessing. */

/* One-line human/machine-readable identity, e.g.
 *   "ds4 backend=cuda arch=sm_100 cuda=13.2 git=84cc882" */
const char *ds4_build_id(void);

#endif
