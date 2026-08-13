"""Real RC -> SQLite pool cross-process positive control for solved Puzzle 70."""

import argparse
import importlib
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from starlette.requests import Request

PUZZLE = 70
RANGE_BITS = 69
START = 1 << 69
PUBKEY = "0290e6900a58d33393bc1097b5aed31f2e4e7cbd3e5466af958665bc0121248483"
KNOWN_KEY = int("0000000000000000000000000000000000000000000000349b84b6431a6c4ef1", 16)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default=r"E:\RCkangaroo\RCKangaroo.exe")
    parser.add_argument("--dp", type=int, default=18)
    parser.add_argument("--tame-max", type=float, default=1.5)
    parser.add_argument("--solve-max", type=float, default=4.0)
    return parser.parse_args()


def main():
    args = parse_args()
    server_dir = Path(__file__).resolve().parents[1] / "server"
    sys.path.insert(0, str(server_dir))
    temp = tempfile.TemporaryDirectory(prefix="rc_pool_p70_")
    os.environ.update({
        "POOL_DB_FILE": str(Path(temp.name) / "pool.db"),
        "DASHBOARD_USER": "control",
        "DASHBOARD_PASS": "control",
        "WORKER_TOKEN": "control-token",
    })
    pool = importlib.import_module("app")
    request = Request({"type": "http", "headers": [(b"x-worker-token", b"control-token")]})
    job_id = "p70-real-cross-process"
    now = time.time()
    conn = pool.get_db()
    conn.execute(
        """INSERT INTO jobs(job_id,pubkey,start_hex,range_bits,dp_bits,chunk_bits,
           start_percent,end_percent,base_start_hex,current_offset_hex,status,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job_id, PUBKEY, f"{START:x}", RANGE_BITS, args.dp, RANGE_BITS, 0, 100,
         f"{START:x}", f"{START:x}", "ACTIVE", now),
    )
    for worker, session in (("tame-process", "tame-session"), ("wild-process", "wild-session")):
        conn.execute("INSERT INTO workers(worker_id,name,last_ping) VALUES(?,?,?)", (worker, worker, now))
        conn.execute(
            """INSERT INTO worker_sessions(session_id,job_id,worker_id,started_at,
               last_heartbeat,status) VALUES(?,?,?,?,?,'ACTIVE')""",
            (session, job_id, worker, now, now),
        )
    conn.commit()
    conn.close()

    tames_file = str(Path(temp.name) / "tames70.dat")
    tame_cmd = [args.binary, "-gpu", "0", "-dp", str(args.dp), "-range", str(RANGE_BITS),
                "-tames", tames_file, "-max", str(args.tame_max), "-stream-dps"]
    solve_cmd = [args.binary, "-gpu", "0", "-dp", str(args.dp), "-range", str(RANGE_BITS),
                 "-start", f"{START:x}", "-pubkey", PUBKEY, "-tames", tames_file,
                 "-max", str(args.solve_max), "-stream-dps"]

    def run_and_submit(cmd, worker, session, accepted_type):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, cwd=str(Path(args.binary).parent), bufsize=1)
        batch = []
        submitted = 0
        solved = False
        for raw in proc.stdout:
            line = raw.strip()
            if not line.startswith("DP_ENTRY:"):
                continue
            match = re.fullmatch(r"DP_ENTRY:([01]):([0-9a-fA-F]{24}):([0-9a-fA-F]{44})", line)
            if not match:
                continue
            type_text, x_prefix, distance = match.groups()
            dp_type = int(type_text)
            if dp_type != accepted_type:
                continue
            batch.append({"x_prefix": x_prefix, "dist_hex": distance, "dp_type": dp_type})
            if len(batch) == 500:
                result = pool.submit_dp_batch_v2(pool.DPBatchSubmit(
                    worker_id=worker, session_id=session, job_id=job_id,
                    puzzle_number=PUZZLE, dps=batch), request)
                submitted += result["ingested"]
                batch.clear()
                if result["solved"]:
                    solved = True
                    proc.terminate()
                    break
        if batch and not solved:
            result = pool.submit_dp_batch_v2(pool.DPBatchSubmit(
                worker_id=worker, session_id=session, job_id=job_id,
                puzzle_number=PUZZLE, dps=batch), request)
            submitted += result["ingested"]
            solved = result["solved"]
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return submitted, solved, proc.returncode

    started = time.time()
    tame_count, _, tame_rc = run_and_submit(tame_cmd, "tame-process", "tame-session", 0)
    print({"phase": "tame", "records": tame_count, "returncode": tame_rc,
           "seconds": round(time.time() - started, 3)})
    wild_started = time.time()
    wild_count, solved, wild_rc = run_and_submit(solve_cmd, "wild-process", "wild-session", 1)
    conn = pool.get_db()
    row = conn.execute("SELECT status,private_key FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    conn.close()
    recovered = int(row["private_key"], 16) if row["private_key"] else None
    report = {"phase": "wild", "records": wild_count, "returncode": wild_rc,
              "seconds": round(time.time() - wild_started, 3), "pool_solved": solved,
              "exact_key": recovered == KNOWN_KEY, "status": row["status"]}
    print(report)
    if not solved or recovered != KNOWN_KEY:
        raise SystemExit("P70 cross-process control failed")


if __name__ == "__main__":
    main()
