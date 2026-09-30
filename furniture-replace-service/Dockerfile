# Furniture Replacement Service — GPU image.
# CUDA 12.1 runtime + cuDNN, matching the pinned torch build.
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/srv/data/weights/hf \
    TORCH_HOME=/srv/data/weights/torch \
    XDG_CACHE_HOME=/srv/data/weights/cache

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3-pip python3.10-dev \
        git ffmpeg libsm6 libxext6 libgl1 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python

WORKDIR /srv

# Torch first, from the CUDA 12.1 wheel index, so the rest resolve against it.
RUN pip install --upgrade pip && \
    pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu121

COPY requirements.txt .
RUN pip install -r requirements.txt

# SAM 2.1 from source (not on PyPI).
RUN pip install "git+https://github.com/facebookresearch/sam2.git"

COPY app ./app
COPY frontend ./frontend

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
