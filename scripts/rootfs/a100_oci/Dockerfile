FROM nvidia/cuda:13.0.3-devel-ubuntu24.04@sha256:b7ae301dea2c162444795462ce17a05f6a516e5a75944b57af5b88540a1a2266
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential bubblewrap ca-certificates curl python3 zstd \
    && rm -rf /var/lib/apt/lists/*
COPY ds4-fc80bd6-source.tar.gz /tmp/ds4-source.tar.gz
RUN printf '%s  /tmp/ds4-source.tar.gz\n' \
      '1c640b28efcc685778beb131b53f86ce06facf851e7956c93dced29fd7fd71f3' \
      | sha256sum -c - \
    && mkdir -p /opt/ds4/source \
    && tar -xzf /tmp/ds4-source.tar.gz -C /opt/ds4/source \
    && rm /tmp/ds4-source.tar.gz
WORKDIR /opt/ds4/source
RUN make -j16 cuda CUDA_ARCH=sm_80 NATIVE_CPU_FLAG=-march=x86-64 \
    && make -j8 CUDA_ARCH=sm_80 NATIVE_CPU_FLAG=-march=x86-64 \
        tests/test_cuda_ssd_cache tests/test_cuda_q8_0_gemv tests/test_cuda_reductions \
    && mkdir -p /opt/ds4/bin /work /weights /outputs /run/nvidia-driver/lib \
    && cp ds4 ds4-bench ds4-server ds4-eval ds4-agent \
        tests/test_cuda_ssd_cache tests/test_cuda_q8_0_gemv tests/test_cuda_reductions /opt/ds4/bin/ \
    && dpkg-query -W > /opt/ds4/packages.txt \
    && nvcc --version > /opt/ds4/cuda-version.txt \
    && sha256sum /opt/ds4/bin/* > /opt/ds4/binaries.sha256
COPY bundle-manifest.json /opt/ds4/bundle-manifest.json
LABEL org.opencontainers.image.title="DS4 A100 build rootfs" \
      org.opencontainers.image.revision="fc80bd695da76ee14bcb86820bf900a5cdfda806" \
      io.ds4.cuda.arch="sm_80" \
      io.ds4.cpu.arch="x86-64" \
      io.ds4.bundle.kind="build-rootfs"
ENV PATH=/opt/ds4/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WORKDIR /work
CMD ["/bin/bash"]
