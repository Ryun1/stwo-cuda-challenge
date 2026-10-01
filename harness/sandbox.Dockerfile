# The operator supplies an NVIDIA CUDA runtime base pinned by repository digest.
# Build this once outside the measured interval and pass its local sha256 image ID
# as STWO_SANDBOX_IMAGE. Only the fixed pipeline driver enters the image.
ARG CUDA_RUNTIME_IMAGE
FROM ${CUDA_RUNTIME_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /judge/harness /candidate /inputs /work/run /assets/cuda-artifacts \
    && touch /assets/preprocessed.bin

COPY harness/__init__.py harness/run_arm.py harness/run_pipeline.py harness/sandbox.py /judge/harness/

USER 65532:65532
WORKDIR /work/run
