"""Exact Python reconstruction of RCKangaroo's Collision_SOTA semantics.

The streamed 22-byte distances are the low bytes of an EcInt in native
little-endian order.  Byte 21 carries the sign bit and the C++ code sign
extends it before doing collision arithmetic.
"""

SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
TAME = 0


def decode_rc_distance(dist_hex: str) -> int:
    raw = bytes.fromhex(dist_hex)
    if len(raw) != 22:
        raise ValueError("RC distance must contain exactly 22 bytes")
    return int.from_bytes(raw, byteorder="little", signed=True)


def encode_rc_distance(value: int) -> str:
    """Test/vector helper for RC's signed 176-bit wire representation."""
    return int(value).to_bytes(22, byteorder="little", signed=True).hex()


def internal_collision_candidates(dist_a: str, type_a: int, dist_b: str, type_b: int):
    """Yield internal scalars tried by Collision_SOTA, including both signs."""
    a = decode_rc_distance(dist_a)
    b = decode_rc_distance(dist_b)
    if type_a == TAME and type_b == TAME:
        return set()

    if type_a == TAME or type_b == TAME:
        tame, wild = (a, b) if type_a == TAME else (b, a)
        bases = (tame - wild, -tame - wild)
    else:
        # Same-wild collisions are explicitly supported by the upstream C++.
        # C++ takes the magnitude before ShiftRight(1).
        bases = (abs(a - b) // 2, abs(-a - b) // 2)

    result = set()
    for value in bases:
        result.add(value % SECP256K1_N)
        result.add((-value) % SECP256K1_N)
    result.discard(0)
    return result


def final_private_key_candidates(
    dist_a: str,
    type_a: int,
    dist_b: str,
    type_b: int,
    start: int,
    range_bits: int,
):
    """Undo RC main-mode's start offset and smooth-edge transformation."""
    smooth_edge = 1 << (range_bits - 5)
    return {
        (internal + start - smooth_edge) % SECP256K1_N
        for internal in internal_collision_candidates(dist_a, type_a, dist_b, type_b)
    }
