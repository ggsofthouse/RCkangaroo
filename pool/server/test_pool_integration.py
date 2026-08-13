import importlib
import os
import sqlite3
import tempfile
import time
import unittest

from starlette.requests import Request

from collision_sota import encode_rc_distance


class PoolIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        os.environ["POOL_DB_FILE"] = os.path.join(cls.tempdir.name, "pool.db")
        os.environ["DASHBOARD_USER"] = "test"
        os.environ["DASHBOARD_PASS"] = "test"
        os.environ["WORKER_TOKEN"] = "test-token"
        cls.pool = importlib.import_module("app")

    @classmethod
    def tearDownClass(cls):
        cls.tempdir.cleanup()

    def setUp(self):
        conn = self.pool.get_db()
        for table in ("global_dps", "worker_sessions", "jobs", "workers"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()

    def _request(self):
        return Request({
            "type": "http",
            "headers": [(b"x-worker-token", b"test-token")],
        })

    def test_two_workers_recover_planted_key_through_sqlite_endpoint(self):
        bits = 40
        range_bits = bits - 1
        start = 1 << (bits - 1)
        private_key = start + 0x12345
        x, y = self.pool._point_mult(private_key)
        pubkey = ("02" if y % 2 == 0 else "03") + f"{x:064x}"
        job_id = "plant-job"
        now = time.time()

        conn = self.pool.get_db()
        conn.execute(
            """INSERT INTO jobs
               (job_id,pubkey,start_hex,range_bits,dp_bits,chunk_bits,start_percent,
                end_percent,base_start_hex,current_offset_hex,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (job_id, pubkey, f"{start:x}", range_bits, 14, range_bits, 0, 100,
             f"{start:x}", f"{start:x}", "ACTIVE", now),
        )
        for worker, session in (("worker-a", "session-a"), ("worker-b", "session-b")):
            conn.execute(
                "INSERT INTO workers(worker_id,name,last_ping) VALUES(?,?,?)",
                (worker, worker, now),
            )
            conn.execute(
                """INSERT INTO worker_sessions
                   (session_id,job_id,worker_id,started_at,last_heartbeat,status)
                   VALUES(?,?,?,?,?,'ACTIVE')""",
                (session, job_id, worker, now, now),
            )
        conn.commit()
        conn.close()

        internal = private_key - start + (1 << (range_bits - 5))
        wild = -42424242
        tame = internal + wild
        x_prefix = "00112233445566778899aabb"

        first = self.pool.submit_dp_batch_v2(
            self.pool.DPBatchSubmit(
                worker_id="worker-a", session_id="session-a", job_id=job_id,
                puzzle_number=bits,
                dps=[{"x_prefix": x_prefix, "dist_hex": encode_rc_distance(tame), "dp_type": 0}],
            ),
            self._request(),
        )
        self.assertFalse(first["solved"])

        second = self.pool.submit_dp_batch_v2(
            self.pool.DPBatchSubmit(
                worker_id="worker-b", session_id="session-b", job_id=job_id,
                puzzle_number=bits,
                dps=[{"x_prefix": x_prefix, "dist_hex": encode_rc_distance(wild), "dp_type": 1}],
            ),
            self._request(),
        )
        self.assertTrue(second["solved"])

        conn = self.pool.get_db()
        row = conn.execute("SELECT status, private_key FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        conn.close()
        self.assertEqual(row["status"], "SOLVED")
        self.assertEqual(int(row["private_key"], 16), private_key)


if __name__ == "__main__":
    unittest.main()
