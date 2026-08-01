#!/bin/bash
set -e

echo "=================================================="
echo "🦘 RCKangaroo Vast.ai / Cloud GPU Container Startup"
echo "=================================================="

# Check if rckangaroo linux binary is compiled, if not build it
if [ ! -f "/app/rckangaroo" ]; then
    echo "⚙️ Compiling RCKangaroo Linux binary..."
    cd /app
    nvcc -O3 -std=c++17 -o rckangaroo RCKangaroo.cpp GpuKang.cpp Ec.cpp utils.cpp CallCubin.cpp RCGpuCore.cu -lcuda -lcudart -lpthread
    echo "✅ Linux binary compiled successfully!"
fi

echo "🚀 Starting RCKangaroo Worker connecting to: $POOL_SERVER_URL"
python3 /app/pool/worker/worker.py
