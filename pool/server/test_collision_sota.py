import unittest

from collision_sota import (
    SECP256K1_N,
    decode_rc_distance,
    encode_rc_distance,
    final_private_key_candidates,
)


class CollisionSotaTests(unittest.TestCase):
    def test_signed_little_endian_round_trip(self):
        for value in (0, 1, -1, 0x123456789ABC, -0x123456789ABC):
            self.assertEqual(decode_rc_distance(encode_rc_distance(value)), value)

    def test_tame_wild_planted_key_with_start_and_smoothing(self):
        range_bits = 40
        start = 1 << 39
        private_key = start + 0x12345
        internal = private_key - start + (1 << (range_bits - 5))
        wild = -987654321
        tame = internal + wild
        candidates = final_private_key_candidates(
            encode_rc_distance(tame), 0,
            encode_rc_distance(wild), 1,
            start, range_bits,
        )
        self.assertIn(private_key, candidates)

    def test_tame_wild_negative_branch(self):
        range_bits = 50
        start = 1 << 49
        private_key = start + 0xFEDCB
        internal = private_key - start + (1 << (range_bits - 5))
        wild = 777777
        # The IsNeg=true branch computes -tame-wild.
        tame = -internal - wild
        candidates = final_private_key_candidates(
            encode_rc_distance(wild), 1,
            encode_rc_distance(tame), 0,
            start, range_bits,
        )
        self.assertIn(private_key, candidates)

    def test_same_wild_collision_supported(self):
        range_bits = 60
        start = 1 << 59
        private_key = start + 0x234567
        internal = private_key - start + (1 << (range_bits - 5))
        wild_b = -13579
        wild_a = 2 * internal + wild_b
        candidates = final_private_key_candidates(
            encode_rc_distance(wild_a), 1,
            encode_rc_distance(wild_b), 1,
            start, range_bits,
        )
        self.assertIn(private_key, candidates)
        self.assertTrue(all(0 <= value < SECP256K1_N for value in candidates))

    def test_two_tames_do_not_reconstruct(self):
        self.assertEqual(
            final_private_key_candidates(
                encode_rc_distance(10), 0, encode_rc_distance(20), 0, 0, 40
            ),
            set(),
        )


if __name__ == "__main__":
    unittest.main()
