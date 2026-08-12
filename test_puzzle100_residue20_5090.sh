#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "== GPU =="
nvidia-smi --query-gpu=index,name,memory.total,compute_cap --format=csv,noheader
nvcc --version | tail -n 1

echo "== Build Release (native RTX 5090 / sm_120) =="
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel "$(nproc)"

binary="./build/bin/rckangaroo"
if [[ ! -x "$binary" ]]; then
  echo "Binary not found: $binary" >&2
  exit 1
fi

echo "== Puzzle #100 reduced by 20 known low bits =="
echo "Expected reduced key q: AF55FC59C335C8EC67ED"
echo "Expected original key: 000000000000000000000000000000000000000AF55FC59C335C8EC67ED24826"

start_epoch="$(date +%s)"
"$binary" \
  -gpu 0 \
  -dp 20 \
  -range 79 \
  -start 80000000000000000000 \
  -pubkey 02e30ebca184b4c950fa32593583ebf5214401f58c8ab3e99f56dbb6a02e7d27c6 \
  | tee p100_20bit_5090.log
elapsed="$(( $(date +%s) - start_epoch ))"

found="$(sed -n 's/.*PRIVATE KEY:[[:space:]]*\([0-9A-Fa-f]*\).*/\1/p' p100_20bit_5090.log | tail -n 1)"
expected_q="AF55FC59C335C8EC67ED"

echo "== Verification =="
echo "Elapsed: ${elapsed}s"
echo "Found q: ${found:-NOT_FOUND}"
if [[ "${found^^}" == "$expected_q" ]]; then
  echo "EXACT_MATCH=true"
else
  echo "EXACT_MATCH=false"
  exit 2
fi
