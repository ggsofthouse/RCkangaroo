#!/usr/bin/env python3
"""Reduce an interval ECDLP using hypotheses for k mod 2^b.

For k = 2^b*q + r and Q = kG, construct
    Q_r = (2^b)^(-1) * (Q - rG) = qG
for every candidate residue r.  A correct residue reduces the interval by b bits.
Wrong residues normally produce no solution in the reduced interval.
"""

import argparse
import csv
import math
import shlex
from pathlib import Path


P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)


def inv(value, modulus):
    return pow(value % modulus, -1, modulus)


def point_add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    x1, y1 = a
    x2, y2 = b
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if a == b:
        slope = (3 * x1 * x1) * inv(2 * y1, P) % P
    else:
        slope = (y2 - y1) * inv(x2 - x1, P) % P
    x3 = (slope * slope - x1 - x2) % P
    y3 = (slope * (x1 - x3) - y1) % P
    return x3, y3


def scalar_mult(k, point):
    k %= N
    result = None
    addend = point
    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result


def decode_pubkey(text):
    raw = bytes.fromhex(text.strip())
    if len(raw) == 33 and raw[0] in (2, 3):
        x = int.from_bytes(raw[1:], "big")
        y = pow((pow(x, 3, P) + 7) % P, (P + 1) // 4, P)
        if (y & 1) != (raw[0] & 1):
            y = P - y
        point = (x, y)
    elif len(raw) == 65 and raw[0] == 4:
        point = (int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big"))
    else:
        raise ValueError("expected a compressed or uncompressed secp256k1 public key")
    x, y = point
    if not (0 <= x < P and 0 <= y < P and (y * y - x * x * x - 7) % P == 0):
        raise ValueError("public key is not on secp256k1")
    return point


def encode_compressed(point):
    if point is None:
        raise ValueError("point at infinity cannot be encoded")
    x, y = point
    return f"{2 + (y & 1):02x}{x:064x}"


def parse_residues(args, modulus):
    values = []
    if args.residues:
        values.extend(int(item.strip(), 0) for item in args.residues.split(",") if item.strip())
    if args.residue_file:
        for line in Path(args.residue_file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                values.append(int(line, 0))
    if not values:
        raise ValueError("provide --residues or --residue-file")
    unique = []
    seen = set()
    for value in values:
        if not 0 <= value < modulus:
            raise ValueError(f"residue {value} is outside 0...{modulus - 1}")
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pubkey", required=True)
    parser.add_argument("--start", required=True, help="original interval start, hexadecimal")
    parser.add_argument("--range", dest="range_bits", required=True, type=int,
                        help="log2 of original interval width")
    modulus_group = parser.add_mutually_exclusive_group(required=True)
    modulus_group.add_argument("--residue-bits", type=int)
    modulus_group.add_argument("--modulus", type=lambda value: int(value, 0),
                               help="arbitrary positive modulus d, decimal or 0x-prefixed")
    parser.add_argument("--residues", help="comma-separated integers; 0x prefix is accepted")
    parser.add_argument("--residue-file")
    parser.add_argument("--binary", default="./RCKangaroo.exe")
    parser.add_argument("--gpu", default="0")
    parser.add_argument("--dp", type=int, default=14)
    parser.add_argument("--max", dest="max_factor", type=float)
    parser.add_argument("--csv", default="residue_jobs.csv")
    parser.add_argument("--known-key", help="optional private key for validation, hexadecimal")
    args = parser.parse_args()

    if args.residue_bits is not None:
        b = args.residue_bits
        if not 1 <= b < args.range_bits:
            raise ValueError("residue-bits must be between 1 and range-1")
        d = 1 << b
    else:
        d = args.modulus
        if d <= 1 or d >= N or math.gcd(d, N) != 1:
            raise ValueError("modulus must be in 2...N-1 and invertible modulo the curve order")
        b = math.log2(d)
    start = int(args.start, 16)
    end = start + (1 << args.range_bits) - 1
    point_q = decode_pubkey(args.pubkey)
    d_inverse = inv(d, N)
    residues = parse_residues(args, d)

    if args.known_key:
        known = int(args.known_key, 16)
        expected = known % d
        print(f"Known-key residue: 0x{expected:x} ({expected})")
        print(f"Candidate set contains it: {expected in residues}")

    rows = []
    for index, residue in enumerate(residues):
        q_start = (start - residue + d - 1) // d
        q_end = (end - residue) // d
        if q_start > q_end:
            print(f"Skipping residue {residue}: no scalar in the source interval")
            continue
        q_width = q_end - q_start + 1
        reduced_range = max(1, (q_width - 1).bit_length())
        minus_r_g = scalar_mult((-residue) % N, G)
        transformed = scalar_mult(d_inverse, point_add(point_q, minus_r_g))
        transformed_hex = encode_compressed(transformed)
        cmd = [
            args.binary, "-gpu", args.gpu, "-dp", str(args.dp),
            "-range", str(reduced_range), "-start", f"{q_start:x}",
            "-pubkey", transformed_hex,
        ]
        if args.max_factor is not None:
            cmd.extend(["-max", str(args.max_factor)])
        command = " ".join(shlex.quote(part) for part in cmd)
        rows.append({
            "index": index,
            "residue": residue,
            "residue_hex": f"{residue:x}",
            "modulus": d,
            "modulus_hex": f"{d:x}",
            "reduced_start_hex": f"{q_start:x}",
            "reduced_range": reduced_range,
            "exact_q_width": q_width,
            "padding_factor": (1 << reduced_range) / q_width,
            "transformed_pubkey": transformed_hex,
            "command": command,
        })
        print(command)

    if not rows:
        raise ValueError("no residue produced a non-empty reduced interval")
    with open(args.csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} jobs to {Path(args.csv).resolve()}")


if __name__ == "__main__":
    main()
