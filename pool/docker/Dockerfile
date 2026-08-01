FROM nvidia/cuda:12.8.0-devel-ubuntu22.04

# Avoid interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    python3 \
    python3-pip \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy RCKangaroo repository
COPY . /app

# Make startup script executable
RUN chmod +x /app/pool/docker/start_worker.sh

ENV POOL_SERVER_URL="http://127.0.0.1:8000"
ENV WORKER_NAME="VastAI-GPU-Worker"
ENV GPU_MASK="0"

ENTRYPOINT ["/app/pool/docker/start_worker.sh"]
