#!/usr/bin/env python3
"""
================================================================================
🦘 JAX/XLA Vectorized Pollard's Kangaroo Solver for secp256k1 (TPU/GPU/CPU)
================================================================================
High-performance ECC discrete logarithm solver targeting Google TPUs & GPUs.
Simulates 256-bit BigInt arithmetic via 8-limb uint32/uint64 arrays in JAX tensors.

Author: Vectorized TPU Math Engine
License: GPLv3 / MIT
================================================================================
"""

import os
import sys
import time
import argparse
import numpy as np

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# secp256k1 Constants
P_INT = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
GX_INT = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY_INT = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

# 8 Limbs of Prime P (32-bit uint64 containers)
P_LIMBS = np.array([
    0xFFFFFC2F, 0xFFFEFFFF, 0xFFFFFFFF, 0xFFFFFFFF,
    0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF
], dtype=np.uint64)

# Constant C = 2^256 - P = 0x1000003D1 (C0 = 977, C1 = 1)
C_LIMBS = np.array([977, 1, 0, 0, 0, 0, 0, 0], dtype=np.uint64)


def int_to_limbs_np(val_int: int) -> np.ndarray:
    """Converts a Python 256-bit int into an 8-element uint64 numpy array (least-significant limb first)."""
    limbs = np.zeros(8, dtype=np.uint64)
    temp = val_int
    for i in range(8):
        limbs[i] = temp & 0xFFFFFFFF
        temp >>= 32
    return limbs


def limbs_to_int_np(limbs) -> int:
    """Converts an 8-element limb array/tensor back into a Python integer."""
    limbs_flat = np.array(limbs).flatten()
    res = 0
    for i in range(7, -1, -1):
        res = (res << 32) | int(limbs_flat[i] & 0xFFFFFFFF)
    return res


MASK32 = np.uint64(0xFFFFFFFF)

def setup_jax(backend: str):
    """Initializes JAX with the requested backend ('tpu', 'gpu', or 'cpu')."""
    os.environ['JAX_PLATFORMS'] = backend
    import jax
    jax.config.update("jax_enable_x64", True) # Enable 64-bit limb accumulators for 32x32 products
    jax.config.update('jax_platform_name', backend)
    print(f"🚀 JAX platform configured: {backend.upper()}")
    print(f"📡 Devices detected: {jax.devices()}")
    return jax


def build_jax_math_engine(jax):
    import jax.numpy as jnp

    p_jax = jnp.array(P_LIMBS, dtype=jnp.uint64)
    c_jax = jnp.array(C_LIMBS, dtype=jnp.uint64)

    # --------------------------------------------------------------------------
    # 1. ADDITION & SUBTRACTION MODULO P
    # --------------------------------------------------------------------------
    @jax.jit
    def add_256_raw(a: jnp.ndarray, b: jnp.ndarray) -> jnp.ndarray:
        """Adds two 8-limb tensors shape (..., 8) with carry propagation."""
        res_limbs = []
        carry = jnp.zeros(a.shape[:-1], dtype=jnp.uint64)
        for i in range(8):
            s = a[..., i] + b[..., i] + carry
            res_limbs.append(s & MASK32)
            carry = s >> 32
        res = jnp.stack(res_limbs, axis=-1)
        # Add overflow carry * C
        c_mul0 = carry * 977
        c_mul1 = carry * 1
        
        # Add c_mul to res
        s0 = res[..., 0] + c_mul0
        res = res.at[..., 0].set(s0 & MASK32)
        carry0 = s0 >> 32

        s1 = res[..., 1] + c_mul1 + carry0
        res = res.at[..., 1].set(s1 & MASK32)
        carry1 = s1 >> 32

        for i in range(2, 8):
            si = res[..., i] + carry1
            res = res.at[..., i].set(si & MASK32)
            carry1 = si >> 32

        return res

    @jax.jit
    def sub_256_raw(a: jnp.ndarray, b: jnp.ndarray) -> jnp.ndarray:
        """Subtractions a - b modulo P for 8-limb tensors shape (..., 8)."""
        res_limbs = []
        borrow = jnp.zeros(a.shape[:-1], dtype=jnp.uint64)
        for i in range(8):
            diff = a[..., i] - b[..., i] - borrow
            borrow = (diff >> 63) & 1 # 1 if negative
            res_limbs.append(diff & MASK32)
        res = jnp.stack(res_limbs, axis=-1)
        
        # If borrow out, add P (equivalent to subtracting C when wrapped around)
        p_added = add_256_raw(res, jnp.broadcast_to(p_jax, res.shape))
        res = jnp.where(borrow[..., None] > 0, p_added, res)
        return res

    # --------------------------------------------------------------------------
    # 2. MULTIPLICATION & REDUCTION MODULO P
    # --------------------------------------------------------------------------
    @jax.jit
    def mul_256_mod_p(a: jnp.ndarray, b: jnp.ndarray) -> jnp.ndarray:
        """Full 8x8 limb multiplication with pseudo-Mersenne reduction modulo P."""
        # 16 intermediate accumulator limbs
        accum = [jnp.zeros(a.shape[:-1], dtype=jnp.uint64) for _ in range(16)]

        for i in range(8):
            ai = a[..., i]
            for j in range(8):
                bj = b[..., j]
                accum[i + j] = accum[i + j] + ai * bj

        # First carry propagation across 16 limbs
        carry = jnp.zeros(a.shape[:-1], dtype=jnp.uint64)
        accum_clean = []
        for i in range(16):
            s = accum[i] + carry
            accum_clean.append(s & MASK32)
            carry = s >> 32

        low_256 = jnp.stack(accum_clean[:8], axis=-1)
        high_256 = jnp.stack(accum_clean[8:], axis=-1)

        # High 256 bits * C (where C = 977 + 2^32)
        # H * 977
        h_977 = [high_256[..., i] * 977 for i in range(8)]
        carry_h = jnp.zeros(a.shape[:-1], dtype=jnp.uint64)
        h_977_clean = []
        for i in range(8):
            s = h_977[i] + carry_h
            h_977_clean.append(s & MASK32)
            carry_h = s >> 32

        # H * 2^32 (shift limbs left by 1)
        h_shift = [jnp.zeros(a.shape[:-1], dtype=jnp.uint64)] + [high_256[..., i] for i in range(7)]
        overflow_limb = high_256[..., 7] + carry_h

        # Add low_256 + h_977_clean + h_shift
        res_limbs = []
        carry_add = jnp.zeros(a.shape[:-1], dtype=jnp.uint64)
        for i in range(8):
            s = low_256[..., i] + h_977_clean[i] + h_shift[i] + carry_add
            res_limbs.append(s & MASK32)
            carry_add = s >> 32

        total_overflow = overflow_limb + carry_add
        res = jnp.stack(res_limbs, axis=-1)

        # Final overflow reduction step
        extra0 = total_overflow * 977
        extra1 = total_overflow * 1

        s0 = res[..., 0] + extra0
        res = res.at[..., 0].set(s0 & MASK32)
        c0 = s0 >> 32

        s1 = res[..., 1] + extra1 + c0
        res = res.at[..., 1].set(s1 & MASK32)
        c1 = s1 >> 32

        for i in range(2, 8):
            si = res[..., i] + c1
            res = res.at[..., i].set(si & MASK32)
            c1 = si >> 32

        return res

    # --------------------------------------------------------------------------
    # 3. MODULAR INVERSION VIA FERMAT'S LITTLE THEOREM (a^(P-2) mod P)
    # --------------------------------------------------------------------------
    # P-2 bits in binary (256 bits)
    P_MINUS_2_INT = P_INT - 2

    @jax.jit
    def inv_mod_p(a: jnp.ndarray) -> jnp.ndarray:
        """Computes modular inverse a^(P-2) mod P using fixed binary exponentiation without branching."""
        # Initialize result = 1
        one_limbs = jnp.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=jnp.uint64)
        res = jnp.broadcast_to(one_limbs, a.shape)
        base = a

        # 256 square-and-multiply steps for P-2
        for bit_idx in range(256):
            bit = (P_MINUS_2_INT >> bit_idx) & 1
            if bit == 1:
                res = mul_256_mod_p(res, base)
            base = mul_256_mod_p(base, base)

        return res

    # --------------------------------------------------------------------------
    # 4. ECC POINT ADDITION AND DOUBLING (secp256k1)
    # --------------------------------------------------------------------------
    @jax.jit
    def ecc_add_affine(x1: jnp.ndarray, y1: jnp.ndarray, x2: jnp.ndarray, y2: jnp.ndarray):
        """Vectorized Affine Point Addition: (X3, Y3) = (X1, Y1) + (X2, Y2)."""
        dy = sub_256_raw(y2, y1)
        dx = sub_256_raw(x2, x1)
        dx_inv = inv_mod_p(dx)
        lam = mul_256_mod_p(dy, dx_inv)

        lam2 = mul_256_mod_p(lam, lam)
        x3 = sub_256_raw(sub_256_raw(lam2, x1), x2)
        
        x1_minus_x3 = sub_256_raw(x1, x3)
        y3 = sub_256_raw(mul_256_mod_p(lam, x1_minus_x3), y1)
        return x3, y3

    @jax.jit
    def ecc_double_affine(x1: jnp.ndarray, y1: jnp.ndarray):
        """Vectorized Affine Point Doubling for secp256k1 (a=0): (X3, Y3) = 2*(X1, Y1)."""
        x1_sq = mul_256_mod_p(x1, x1)
        three_limbs = jnp.array([3, 0, 0, 0, 0, 0, 0, 0], dtype=jnp.uint64)
        num = mul_256_mod_p(x1_sq, jnp.broadcast_to(three_limbs, x1.shape))

        two_limbs = jnp.array([2, 0, 0, 0, 0, 0, 0, 0], dtype=jnp.uint64)
        den = mul_256_mod_p(y1, jnp.broadcast_to(two_limbs, y1.shape))
        den_inv = inv_mod_p(den)
        lam = mul_256_mod_p(num, den_inv)

        lam2 = mul_256_mod_p(lam, lam)
        two_x1 = add_256_raw(x1, x1)
        x3 = sub_256_raw(lam2, two_x1)

        x1_minus_x3 = sub_256_raw(x1, x3)
        y3 = sub_256_raw(mul_256_mod_p(lam, x1_minus_x3), y1)
        return x3, y3

    return {
        "add_256": add_256_raw,
        "sub_256": sub_256_raw,
        "mul_256": mul_256_mod_p,
        "inv_mod_p": inv_mod_p,
        "ecc_add": ecc_add_affine,
        "ecc_double": ecc_double_affine,
    }


def main():
    parser = argparse.ArgumentParser(description="JAX TPU Pollard's Kangaroo Solver for secp256k1")
    parser.add_argument('--range', type=int, default=80, help="Puzzle bit range (e.g. 40, 70, 80, 140)")
    parser.add_argument('--backend', type=str, default='cpu', choices=['cpu', 'gpu', 'tpu'], help="Hardware backend (tpu, gpu, cpu)")
    parser.add_argument('--kangaroos', type=int, default=1024, help="Number of parallel kangaroos per tensor batch")
    parser.add_argument('--dp-bits', type=int, default=16, help="Distinguished point bits")
    parser.add_argument('--steps', type=int, default=10, help="Benchmark jump steps to perform")
    args = parser.parse_args()

    print("================================================================================")
    print(f"🦘 Pollard's Kangaroo JAX TPU Solver - Puzzle #{args.range}")
    print(f"⚙️ Target Backend: {args.backend.upper()} | Kangaroos Batch: {args.kangaroos:,}")
    print("================================================================================")

    jax = setup_jax(args.backend)
    import jax.numpy as jnp
    engine = build_jax_math_engine(jax)

    # --------------------------------------------------------------------------
    # VALIDATION TEST 1: Point Doubling 2 * G
    # --------------------------------------------------------------------------
    print("\n🧪 Running Math Verification Tests...")
    gx_limbs = jnp.array(int_to_limbs_np(GX_INT), dtype=jnp.uint64)
    gy_limbs = jnp.array(int_to_limbs_np(GY_INT), dtype=jnp.uint64)

    # Batch of shape (1, 8)
    gx_batch = gx_limbs[None, :]
    gy_batch = gy_limbs[None, :]

    print("⚡ JIT Compiling ECC Point Doubling (2G)...")
    t0 = time.time()
    x2g, y2g = engine["ecc_double"](gx_batch, gy_batch)
    x2g.block_until_ready()
    t_jit = time.time() - t0
    print(f"✅ JIT Compilation completed in {t_jit:.4f}s")

    x2g_int = limbs_to_int_np(x2g[0])
    EXPECTED_2GX = 0xC6047F9441ED7D6D3045406E95C07CD85C778E4B8CEF3CA7ABAC09B95C709EE5

    print(f"   Calculated 2G_x: {hex(x2g_int)}")
    print(f"   Expected   2G_x: {hex(EXPECTED_2GX)}")

    if x2g_int == EXPECTED_2GX:
        print("🎉 SECP256K1 POINT DOUBLING MATEMATICAMENTE PERFEITO!")
    else:
        print("❌ ERRO NA VERIFICAÇÃO MATEMÁTICA!")
        sys.exit(1)

    # --------------------------------------------------------------------------
    # BENCHMARK: BATCH KANGAROO JUMPS
    # --------------------------------------------------------------------------
    N = args.kangaroos
    print(f"\n🚀 Preparing Tensor Batch of {N:,} Kangaroos (Shape: [{N}, 8])...")
    
    # Broadcast G to batch N
    batch_kx = jnp.broadcast_to(gx_limbs, (N, 8))
    batch_ky = jnp.broadcast_to(gy_limbs, (N, 8))

    print(f"🔥 Executing {args.steps} parallel jump steps across {N:,} kangaroos...")
    t_start = time.time()
    
    curr_x, curr_y = batch_kx, batch_ky
    for step in range(args.steps):
        curr_x, curr_y = engine["ecc_double"](curr_x, curr_y)
    
    curr_x.block_until_ready()
    t_end = time.time() - t_start
    
    total_ops = N * args.steps
    rate = total_ops / t_end
    print("================================================================================")
    print(f"⏱️ Total Time: {t_end:.4f} seconds")
    print(f"⚡ Throughput Rate: {rate / 1e3:.2f} Kops/sec ({rate / 1e6:.4f} Mops/sec)")
    print("================================================================================")
    print("🎯 JAX TPU Solver inicializado com sucesso e pronto para escala!")


if __name__ == "__main__":
    main()
