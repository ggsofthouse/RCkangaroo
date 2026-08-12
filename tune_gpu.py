#!/usr/bin/env python3
"""Fixed-time RCKangaroo GPU tuning sweep.

Example (Linux RTX 5090):
  python3 tune_gpu.py --binary ./rckangaroo --seconds 60 --inv-sm auto,4,5,6,7,8,9,10
"""

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path


RESULT_RE = re.compile(
    r"TUNE RESULT: elapsed ([0-9.]+) s, ops ([0-9]+), average ([0-9.]+) MKeys/s"
)
TUNE_RE = re.compile(
    r"TUNE GPU (\d+): speed (\d+) MKeys/s, batches (\d+), loops (\d+), "
    r"DP/s ([0-9.]+), inv-sm (\d+)"
)


def parse_inv_values(text):
    values = []
    for item in text.split(","):
        item = item.strip().lower()
        if item == "auto":
            values.append(None)
        else:
            value = int(item)
            if not 1 <= value <= 64:
                raise ValueError("inv-sm values must be in 1...64")
            values.append(value)
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="./rckangaroo")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--range", dest="range_bits", type=int, default=100)
    parser.add_argument("--dp", type=int, default=20)
    parser.add_argument("--gpu", default="0")
    parser.add_argument("--inv-sm", default="auto,4,5,6,7,8,9,10")
    parser.add_argument("--csv", default="tune_gpu_results.csv")
    args = parser.parse_args()

    binary = str(Path(args.binary).resolve())
    inv_values = parse_inv_values(args.inv_sm)
    rows = []

    for inv_sm in inv_values:
        label = "auto" if inv_sm is None else str(inv_sm)
        cmd = [
            binary, "-gpu", args.gpu, "-dp", str(args.dp),
            "-range", str(args.range_bits), "-bench-seconds", str(args.seconds),
            "-tune-stats",
        ]
        if inv_sm is not None:
            cmd.extend(["-inv-sm", str(inv_sm)])

        print(f"\n=== inv-sm {label} ===", flush=True)
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, errors="replace")
        print(proc.stdout, end="")

        result_matches = RESULT_RE.findall(proc.stdout)
        tune_matches = TUNE_RE.findall(proc.stdout)
        if proc.returncode != 0 or not result_matches or not tune_matches:
            print(f"FAILED: inv-sm {label}, exit {proc.returncode}", file=sys.stderr)
            rows.append({"requested_inv_sm": label, "status": "failed"})
            continue

        elapsed, ops, average = result_matches[-1]
        gpu, speed, batches, loops, dp_rate, actual_inv = tune_matches[-1]
        rows.append({
            "requested_inv_sm": label,
            "actual_inv_sm": actual_inv,
            "gpu": gpu,
            "elapsed_s": elapsed,
            "ops": ops,
            "average_mkeys_s": average,
            "window_mkeys_s": speed,
            "batches": batches,
            "loops": loops,
            "dp_s": dp_rate,
            "status": "ok",
        })

    fieldnames = [
        "requested_inv_sm", "actual_inv_sm", "gpu", "elapsed_s", "ops",
        "average_mkeys_s", "window_mkeys_s", "batches", "loops", "dp_s", "status",
    ]
    with open(args.csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    good = [row for row in rows if row.get("status") == "ok"]
    if good:
        best = max(good, key=lambda row: float(row["average_mkeys_s"]))
        print(f"\nBEST: inv-sm {best['requested_inv_sm']}, "
              f"{best['average_mkeys_s']} MKeys/s")
    print(f"CSV: {Path(args.csv).resolve()}")


if __name__ == "__main__":
    main()
