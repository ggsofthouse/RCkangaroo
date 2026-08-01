import os
import time
import json
import sqlite3
import threading
from typing import Dict, List, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="RCKangaroo Distributed Pool Coordinator", version="1.0")

# Enable CORS for cross-origin dashboard access or remote workers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = os.path.join(os.path.dirname(__file__), "pool.db")
db_lock = threading.Lock()

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        
        # Jobs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                pubkey TEXT NOT NULL,
                start_hex TEXT NOT NULL,
                range_bits INTEGER NOT NULL,
                dp_bits INTEGER DEFAULT 16,
                chunk_bits INTEGER DEFAULT 36,
                current_offset_hex TEXT NOT NULL,
                status TEXT DEFAULT 'ACTIVE',
                created_at REAL,
                solved_at REAL,
                solved_by TEXT,
                private_key TEXT
            )
        ''')

        # Work units / Chunks
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                start_hex TEXT NOT NULL,
                range_bits INTEGER NOT NULL,
                assigned_worker TEXT,
                assigned_at REAL,
                status TEXT DEFAULT 'PENDING'
            )
        ''')

        # Workers
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS workers (
                worker_id TEXT PRIMARY KEY,
                name TEXT,
                os_info TEXT,
                gpu_info TEXT,
                hashrate_mhs REAL DEFAULT 0.0,
                last_ping REAL,
                completed_chunks INTEGER DEFAULT 0
            )
        ''')

        conn.commit()
        conn.close()

init_db()

# Pydantic Schemas
class CreateJobRequest(BaseModel):
    pubkey: str
    start_hex: str
    range_bits: int
    dp_bits: int = 16
    chunk_bits: int = 36  # Sub-range bit size assigned per worker task

class WorkerRegisterRequest(BaseModel):
    worker_id: str
    name: str
    os_info: str
    gpu_info: str

class WorkerHeartbeatRequest(BaseModel):
    worker_id: str
    hashrate_mhs: float

class WorkRequest(BaseModel):
    worker_id: str

class SubmitSolutionRequest(BaseModel):
    worker_id: str
    chunk_id: str
    pubkey: str
    private_key: str

# API Endpoints
@app.post("/api/jobs/create")
def create_job(req: CreateJobRequest):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        job_id = f"job_{int(time.time())}"
        
        # Clean start_hex (remove 0x prefix if present)
        clean_start = req.start_hex.lower().replace("0x", "")
        
        cursor.execute('''
            INSERT INTO jobs (job_id, pubkey, start_hex, range_bits, dp_bits, chunk_bits, current_offset_hex, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (job_id, req.pubkey.lower(), clean_start, req.range_bits, req.dp_bits, req.chunk_bits, clean_start, time.time()))
        
        conn.commit()
        conn.close()
        return {"status": "SUCCESS", "job_id": job_id}

@app.post("/api/worker/register")
def register_worker(req: WorkerRegisterRequest):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO workers (worker_id, name, os_info, gpu_info, hashrate_mhs, last_ping)
            VALUES (?, ?, ?, ?, 0.0, ?)
        ''', (req.worker_id, req.name, req.os_info, req.gpu_info, time.time()))
        conn.commit()
        conn.close()
    return {"status": "REGISTERED", "worker_id": req.worker_id}

@app.post("/api/worker/heartbeat")
def heartbeat(req: WorkerHeartbeatRequest):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE workers SET hashrate_mhs = ?, last_ping = ? WHERE worker_id = ?
        ''', (req.hashrate_mhs, time.time(), req.worker_id))
        conn.commit()
        conn.close()
    return {"status": "OK"}

@app.post("/api/worker/get_work")
def get_work(req: WorkRequest):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()

        # Update worker heartbeat timestamp
        cursor.execute("UPDATE workers SET last_ping = ? WHERE worker_id = ?", (time.time(), req.worker_id))

        # Check if there is an active job
        cursor.execute("SELECT * FROM jobs WHERE status = 'ACTIVE' ORDER BY created_at ASC LIMIT 1")
        job = cursor.fetchone()

        if not job:
            conn.close()
            return {"status": "NO_WORK", "message": "No active jobs available"}

        # Assign next chunk for this job
        current_offset_int = int(job['current_offset_hex'], 16)
        chunk_bits = min(job['chunk_bits'], job['range_bits'])
        if chunk_bits < 32:
            chunk_bits = job['range_bits']
            
        chunk_size = 1 << chunk_bits
        
        chunk_id = f"{job['job_id']}_chunk_{hex(current_offset_int)[2:]}"
        chunk_start_hex = hex(current_offset_int)[2:]
        
        # Advance job's current offset
        next_offset_int = current_offset_int + chunk_size
        next_offset_hex = hex(next_offset_int)[2:]

        cursor.execute("UPDATE jobs SET current_offset_hex = ? WHERE job_id = ?", (next_offset_hex, job['job_id']))
        cursor.execute('''
            INSERT INTO chunks (chunk_id, job_id, start_hex, range_bits, assigned_worker, assigned_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'ASSIGNED')
        ''', (chunk_id, job['job_id'], chunk_start_hex, chunk_bits, req.worker_id, time.time()))

        conn.commit()
        conn.close()

        return {
            "status": "WORK_ASSIGNED",
            "chunk_id": chunk_id,
            "job_id": job['job_id'],
            "pubkey": job['pubkey'],
            "start_hex": chunk_start_hex,
            "range_bits": job['range_bits'],
            "chunk_bits": chunk_bits,
            "dp_bits": job['dp_bits'],
            "max_ops": "3.0"
        }

@app.post("/api/worker/submit_solution")
def submit_solution(req: SubmitSolutionRequest):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        now = time.time()
        
        cursor.execute('''
            UPDATE jobs SET status = 'SOLVED', solved_at = ?, solved_by = ?, private_key = ?
            WHERE pubkey = ? OR job_id = (SELECT job_id FROM chunks WHERE chunk_id = ?)
        ''', (now, req.worker_id, req.private_key, req.pubkey.lower(), req.chunk_id))
        
        cursor.execute("UPDATE chunks SET status = 'SOLVED' WHERE chunk_id = ?", (req.chunk_id,))
        cursor.execute("UPDATE workers SET completed_chunks = completed_chunks + 1 WHERE worker_id = ?", (req.worker_id,))
        
        # Save solution to POOL_RESULTS.TXT file
        results_file = os.path.join(os.path.dirname(__file__), "POOL_RESULTS.TXT")
        with open(results_file, "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] PUBKEY: {req.pubkey} | PRIVATE KEY: {req.private_key} | SOLVED BY: {req.worker_id}\n")

        conn.commit()
        conn.close()

    print(f"🎉 SOLVED! Worker {req.worker_id} found private key: {req.private_key}")
    return {"status": "ACCEPTED", "message": "Solution recorded!"}

@app.get("/api/stats")
def get_stats():
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        now = time.time()
        
        # Active workers (pinged within last 60 seconds)
        cursor.execute("SELECT * FROM workers WHERE (? - last_ping) < 60", (now,))
        workers = [dict(w) for w in cursor.fetchall()]
        
        total_hashrate = sum(w['hashrate_mhs'] for w in workers)
        
        cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        jobs = [dict(j) for j in cursor.fetchall()]

        conn.close()

        return {
            "active_workers_count": len(workers),
            "total_pool_hashrate_mhs": round(total_hashrate, 2),
            "total_pool_hashrate_ghs": round(total_hashrate / 1000.0, 3),
            "workers": workers,
            "jobs": jobs
        }

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RCKangaroo Pool Coordinator Dashboard</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', system-ui, sans-serif; }
            .card { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; }
            .stat-header { font-size: 2.2rem; font-weight: bold; color: #58a6ff; }
            .stat-sub { color: #8b949e; font-size: 0.9rem; }
            .badge-online { background-color: #238636; color: #fff; }
            .table-dark { background-color: #161b22; color: #c9d1d9; border-color: #30363d; }
            .solved-box { background-color: #1f6feb22; border: 1px solid #1f6feb; border-radius: 6px; padding: 15px; }
        </style>
    </head>
    <body class="p-4">
        <div class="container-fluid">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2>🦘 RCKangaroo Distributed Pool Coordinator</h2>
                <button class="btn btn-outline-primary btn-sm" onclick="loadStats()">🔄 Refresh</button>
            </div>

            <!-- Stats Row -->
            <div class="row g-3 mb-4">
                <div class="col-md-4">
                    <div class="card p-3 text-center">
                        <div class="stat-sub">TOTAL POOL HASHRATE</div>
                        <div class="stat-header" id="pool-hashrate">0.00 GH/s</div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card p-3 text-center">
                        <div class="stat-sub">ACTIVE WORKERS</div>
                        <div class="stat-header" id="active-workers">0</div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card p-3 text-center">
                        <div class="stat-sub">TOTAL JOBS</div>
                        <div class="stat-header" id="total-jobs">0</div>
                    </div>
                </div>
            </div>

            <!-- Create Job Form -->
            <div class="card p-3 mb-4">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h5 class="mb-0">➕ Create New Target Job</h5>
                    <div>
                        <span class="me-2 text-muted fs-7">Quick Presets:</span>
                        <button class="btn btn-sm btn-outline-info me-1" onclick="loadPreset('140')">Puzzle #140 (139b)</button>
                        <button class="btn btn-sm btn-outline-info me-1" onclick="loadPreset('145')">Puzzle #145 (144b)</button>
                        <button class="btn btn-sm btn-outline-info me-1" onclick="loadPreset('150')">Puzzle #150 (149b)</button>
                        <button class="btn btn-sm btn-outline-warning" onclick="loadPreset('66')">Puzzle #66 (66b)</button>
                    </div>
                </div>
                <form id="jobForm" class="row g-2 mt-1">
                    <div class="col-md-4">
                        <input type="text" id="pubkey" class="form-control bg-dark text-light border-secondary" placeholder="Public Key (Compressed/Uncompressed)" required>
                    </div>
                    <div class="col-md-3">
                        <input type="text" id="start_hex" class="form-control bg-dark text-light border-secondary" placeholder="Start Offset Hex" required>
                    </div>
                    <div class="col-md-2">
                        <input type="number" id="range_bits" class="form-control bg-dark text-light border-secondary" placeholder="Range Bits" required>
                    </div>
                    <div class="col-md-1">
                        <input type="number" id="dp_bits" class="form-control bg-dark text-light border-secondary" placeholder="DP Bits" value="18">
                    </div>
                    <div class="col-md-2">
                        <button type="submit" class="btn btn-success w-100">Launch Job</button>
                    </div>
                </form>
            </div>

            <!-- Active Jobs Section -->
            <div class="card p-3 mb-4">
                <h5>📋 Target Jobs</h5>
                <div class="table-responsive mt-2">
                    <table class="table table-dark table-hover align-middle">
                        <thead>
                            <tr>
                                <th>Job ID</th>
                                <th>Public Key</th>
                                <th>Start Hex</th>
                                <th>Range</th>
                                <th>Status</th>
                                <th>Private Key Result</th>
                            </tr>
                        </thead>
                        <tbody id="jobs-table-body">
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Connected Workers Section -->
            <div class="card p-3">
                <h5>💻 Connected Workers</h5>
                <div class="table-responsive mt-2">
                    <table class="table table-dark table-hover align-middle">
                        <thead>
                            <tr>
                                <th>Worker ID</th>
                                <th>Name</th>
                                <th>OS / Architecture</th>
                                <th>GPU Hardware</th>
                                <th>Hash Rate</th>
                                <th>Completed Chunks</th>
                                <th>Last Ping</th>
                            </tr>
                        </thead>
                        <tbody id="workers-table-body">
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <script>
            function loadPreset(puzzle) {
                const presets = {
                    '140': {
                        pubkey: '031f6a332d3c5c4f2de2378c012f429cd109ba07d69690c6c701b6bb87860d6640',
                        start_hex: '80000000000000000000000000000000000',
                        range_bits: 139,
                        dp_bits: 18
                    },
                    '145': {
                        pubkey: '03afdda497369e219a2c1c369954a930e4d3740968e5e4352475bcffce3140dae5',
                        start_hex: '1000000000000000000000000000000000000',
                        range_bits: 144,
                        dp_bits: 18
                    },
                    '150': {
                        pubkey: '03137807790ea7dc6e97901c2bc87411f45ed74a5629315c4e4b03a0a102250c49',
                        start_hex: '20000000000000000000000000000000000000',
                        range_bits: 149,
                        dp_bits: 18
                    },
                    '66': {
                        pubkey: '02145d223c51a33f932612296f6e3c2992ea7105642ead300067d2b0900139b85c',
                        start_hex: '20000000000000000',
                        range_bits: 66,
                        dp_bits: 16
                    }
                };

                if (presets[puzzle]) {
                    document.getElementById('pubkey').value = presets[puzzle].pubkey;
                    document.getElementById('start_hex').value = presets[puzzle].start_hex;
                    document.getElementById('range_bits').value = presets[puzzle].range_bits;
                    document.getElementById('dp_bits').value = presets[puzzle].dp_bits;
                }
            }

            async function loadStats() {
                try {
                    const res = await fetch('/api/stats');
                    const data = await res.json();

                    document.getElementById('pool-hashrate').innerText = data.total_pool_hashrate_ghs + ' GH/s';
                    document.getElementById('active-workers').innerText = data.active_workers_count;
                    document.getElementById('total-jobs').innerText = data.jobs.length;

                    // Populate Jobs
                    const jobsBody = document.getElementById('jobs-table-body');
                    jobsBody.innerHTML = data.jobs.map(j => `
                        <tr>
                            <td><code>${j.job_id}</code></td>
                            <td class="text-truncate" style="max-width: 250px;">${j.pubkey}</td>
                            <td><code>${j.start_hex}</code></td>
                            <td>${j.range_bits} bits</td>
                            <td><span class="badge ${j.status === 'SOLVED' ? 'bg-success' : 'bg-primary'}">${j.status}</span></td>
                            <td style="color: #7ee787; font-family: monospace;">${j.private_key ? j.private_key : '-'}</td>
                        </tr>
                    `).join('');

                    // Populate Workers
                    const workersBody = document.getElementById('workers-table-body');
                    workersBody.innerHTML = data.workers.map(w => `
                        <tr>
                            <td><code>${w.worker_id}</code></td>
                            <td><strong>${w.name}</strong></td>
                            <td>${w.os_info}</td>
                            <td>${w.gpu_info}</td>
                            <td style="color: #58a6ff; font-weight: bold;">${w.hashrate_mhs.toFixed(2)} MH/s</td>
                            <td>${w.completed_chunks}</td>
                            <td>${Math.round(Date.now()/1000 - w.last_ping)}s ago</td>
                        </tr>
                    `).join('');
                } catch (e) {
                    console.error('Error fetching stats:', e);
                }
            }

            document.getElementById('jobForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const payload = {
                    pubkey: document.getElementById('pubkey').value.trim(),
                    start_hex: document.getElementById('start_hex').value.trim(),
                    range_bits: parseInt(document.getElementById('range_bits').value),
                    dp_bits: parseInt(document.getElementById('dp_bits').value) || 16
                };

                await fetch('/api/jobs/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                loadStats();
            });

            loadStats();
            setInterval(loadStats, 3000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
