# DS4 CUDA copts + the MXFP4 arch gate. sm_100 MUST NOT define
# DS4_CUDA_HAVE_MXF4: ptxas rejects the warp-level mma.sync kind::mxf4.block_scale
# on sm_100a (datacenter Blackwell exposes block-scaled FP4 only via tcgen05.mma,
# which these warp-MMA kernels do not use). MXFP4 is a consumer-Blackwell
# (sm_120a/sm_121a) feature. The default cuda config builds sm_100, so the
# default here defines nothing.
def ds4_cuda_copts():
    return [
        "-std=c++17",
        "-Icuda/mmq",
        "-O3",
        "-g",
        "-lineinfo",
        "--use_fast_math",
        "-Xcompiler",
    ] + select({
        "//:cuda_a100_binary": ["-march=x86-64"],
        "//conditions:default": ["-march=native"],
    }) + [
        "-Xcompiler",
        "-pthread",
    ]

def ds4_c_copts():
    # Match the Makefile CFLAGS on the local B200 path. The Colab A100 build
    # keeps the CPU side portable because the restore gate runs on Colab CPUs.
    return [
        "-O3",
        "-ffast-math",
    ] + select({
        "//:cuda_a100_binary": ["-march=x86-64"],
        "//conditions:default": ["-march=native"],
    }) + [
        "-g",
        "-std=c99",
        "-D_GNU_SOURCE",
        "-fno-finite-math-only",
        "-Wall",
        "-Wextra",
    ]

# When consumer-Blackwell arches are wired later, add a config_setting and flip
# this select. Today only sm_100 is built, so no MXFP4 define is emitted.
DS4_MXF4_DEFINES = select({
    "//conditions:default": [],
})
