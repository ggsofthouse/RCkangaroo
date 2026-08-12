#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-benchmark}"
SECONDS="${2:-30}"
RANGE_BITS="${3:-139}"
DP_BITS="${4:-20}"
INV_SM="${5:-10}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULT_DIR="${RESULT_DIR:-/workspace/rck-cluster-results}"

mkdir -p "$RESULT_DIR"
cd "$ROOT_DIR"
mapfile -t GPU_IDS < <(nvidia-smi --query-gpu=index --format=csv,noheader,nounits | tr -d ' ')
[[ ${#GPU_IDS[@]} -gt 0 ]] || { echo "No NVIDIA GPUs detected" >&2; exit 1; }

HOST_TAG="$(hostname | tr -cs 'A-Za-z0-9._-' '_')"
GPU_MASK="$(printf '%s' "${GPU_IDS[@]}")"
echo "commit=$(git rev-parse HEAD) host=$HOST_TAG gpus=${GPU_IDS[*]}"
nvidia-smi --query-gpu=index,name,memory.total,compute_cap --format=csv,noheader

cmake -S . -B build-cluster -DCMAKE_BUILD_TYPE=Release
cmake --build build-cluster --parallel "$(nproc)"
BINARY="$ROOT_DIR/build-cluster/bin/rckangaroo"

case "$MODE" in
  benchmark)
    for gpu in "${GPU_IDS[@]}"; do
      stem="$RESULT_DIR/${HOST_TAG}_gpu${gpu}_r${RANGE_BITS}_dp${DP_BITS}_inv${INV_SM}"
      python3 tune_gpu.py --binary "$BINARY" --seconds "$SECONDS" \
        --range "$RANGE_BITS" --dp "$DP_BITS" --gpu "$gpu" --inv-sm "$INV_SM" \
        --csv "${stem}.csv" | tee "${stem}.log"
    done
    ;;
  p100-residue20)
    stem="$RESULT_DIR/${HOST_TAG}_p100_residue20_${#GPU_IDS[@]}gpu"
    "$BINARY" -gpu "$GPU_MASK" -inv-sm "$INV_SM" -dp 18 -range 79 \
      -start 80000000000000000000 \
      -pubkey 02e30ebca184b4c950fa32593583ebf5214401f58c8ab3e99f56dbb6a02e7d27c6 \
      -tune-stats | tee "${stem}.log"
    found="$(sed -n 's/.*PRIVATE KEY:[[:space:]]*\([0-9A-Fa-f]*\).*/\1/p' "${stem}.log" | tail -n 1)"
    [[ "${found^^}" == "AF55FC59C335C8EC67ED" ]] || { echo "EXACT_MATCH=false" >&2; exit 2; }
    echo "EXACT_MATCH=true"
    ;;
  *) echo "Usage: $0 [benchmark|p100-residue20] [seconds] [range] [dp] [inv-sm]" >&2; exit 64 ;;
esac

tar --exclude='*.tar.gz' -czf "$RESULT_DIR/${HOST_TAG}_${MODE}.tar.gz" -C "$RESULT_DIR" .
echo "results=$RESULT_DIR"
