#include "ds4_build.h"

/* Identity values are injected by the Bazel build_stamp rule's local_defines
 * (see BUILD.bazel) so the git SHA never goes stale. */

#ifndef DS4_BUILD_BACKEND
#define DS4_BUILD_BACKEND "unknown"
#endif
#ifndef DS4_BUILD_ARCH
#define DS4_BUILD_ARCH "unknown"
#endif
#ifndef DS4_BUILD_CUDA
#define DS4_BUILD_CUDA ""
#endif
#ifndef DS4_BUILD_GIT
#define DS4_BUILD_GIT "unknown"
#endif

const char *ds4_build_id(void) {
    /* cuda= is omitted for the CPU build, where it is empty. */
    if (DS4_BUILD_CUDA[0])
        return "ds4 backend=" DS4_BUILD_BACKEND " arch=" DS4_BUILD_ARCH
               " cuda=" DS4_BUILD_CUDA " git=" DS4_BUILD_GIT;
    return "ds4 backend=" DS4_BUILD_BACKEND " arch=" DS4_BUILD_ARCH
           " git=" DS4_BUILD_GIT;
}
