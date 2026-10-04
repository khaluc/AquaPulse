# GPU training image. Used instead of a Windows venv because Smart App Control
# blocks PyTorch's unsigned DLLs on this machine; Linux containers are not affected.
#   docker build -t aquapulse-ml ml
#   docker run --rm --gpus all --shm-size=4g -v "<repo>:/workspace" aquapulse-ml yolo ...
FROM pytorch/pytorch:2.14.0-cuda13.0-cudnn9-runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# The base image installs torch into the system Python, which is PEP 668 "externally
# managed"; inside a throwaway container adding packages there is fine.
ENV PIP_BREAK_SYSTEM_PACKAGES=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

ENV YOLO_CONFIG_DIR=/workspace/ml/.ultralytics
WORKDIR /workspace/ml
