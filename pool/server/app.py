import os
import time
import json
import sqlite3
import hashlib
import secrets
import threading
from typing import Dict, List, Optional
from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

app = FastAPI(title="RCKangaroo Distributed Pool Coordinator", version="6.1")

@app.get("/worker.py")
def download_worker_script():
    worker_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "worker", "worker.py"))
    return FileResponse(worker_file, media_type="text/x-python", filename="worker.py")


# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = os.path.join(os.path.dirname(__file__), "pool.db")
db_lock = threading.RLock()
security = HTTPBasic()

def authenticate_dashboard(credentials: HTTPBasicCredentials = Depends(security)):
    is_correct_username = secrets.compare_digest(credentials.username, "fogaca05")
    is_correct_password = secrets.compare_digest(credentials.password, "Ti210911@")
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acesso Restrito: Usuario ou senha incorretos",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Base58 and WIF key conversion utilities
BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def base58_encode(b: bytes) -> str:
    n = int.from_bytes(b, 'big')
    res = ''
    while n > 0:
        n, r = divmod(n, 58)
        res = BASE58_ALPHABET[r] + res
    for byte in b:
        if byte == 0:
            res = '1' + res
        else:
            break
    return res

def hex_to_wif(privkey_hex: str, compressed: bool = True) -> str:
    try:
        clean_hex = privkey_hex.lower().replace("0x", "").strip()
        clean_hex = clean_hex.zfill(64)
        raw_key = bytes.fromhex(clean_hex)
        payload = b'\x80' + raw_key
        if compressed:
            payload += b'\x01'
        checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        return base58_encode(payload + checksum)
    except Exception:
        return privkey_hex

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
                chunk_bits INTEGER DEFAULT 66,
                start_percent REAL DEFAULT 0.0,
                end_percent REAL DEFAULT 100.0,
                base_start_hex TEXT NOT NULL,
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

        # Auto-migrate existing jobs table if new columns are missing
        columns_to_add = [
            ("start_percent", "REAL DEFAULT 0.0"),
            ("end_percent", "REAL DEFAULT 100.0"),
            ("base_start_hex", "TEXT DEFAULT '0'")
        ]
        for col_name, col_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

        conn.commit()
        conn.close()

init_db()

# Pydantic Schemas
class CreateJobRequest(BaseModel):
    pubkey: Optional[str] = None
    puzzle_number: Optional[int] = None
    start_percent: float = 0.0
    end_percent: float = 100.0
    start_hex: Optional[str] = None
    range_bits: Optional[int] = None
    dp_bits: int = 18
    chunk_bits: int = 66

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

# Preset Puzzles Dictionary (Dados Oficiais dos Desafios Bitcoin)
PUZZLE_PRESETS = {
    40: {
        "pubkey": "03a2efa402fd5268400c77c20e574ba86409ededee7c4020e4b9f0edbee53de0d4",
        "bits": 40,
        "base_start": "8000000000",
        "dp": 16
    },
    50: {
        "pubkey": "03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6",
        "bits": 50,
        "base_start": "200000000000",
        "dp": 16
    },
    60: {
        "pubkey": "0348e843dc5b1bd246e6309b4924b81543d02b16c8083df973a89ce2c7eb89a10d",
        "bits": 60,
        "base_start": "800000000000000",
        "dp": 16
    },
    66: {
        "pubkey": "024ee2be2d4e9f92d2f5a4a03058617dc45befe22938feed5b7a6b7282dd74cbdd",
        "bits": 66,
        "base_start": "20000000000000000",
        "dp": 16
    },
    130: {
        "pubkey": "03633cbe3ec02b9401c5effa144c5b4d22f87940259634858fc7e59b1c09937852",
        "bits": 130,
        "base_start": "20000000000000000000000000000000",
        "dp": 18
    },
    135: {
        "pubkey": "02145d2611c823a396ef6712ce0f712f09b9b4f3135e3e0aa3230fb9b6d08d1e16",
        "bits": 135,
        "base_start": "4000000000000000000000000000000004",
        "dp": 18
    },
    140: {
        "pubkey": "031f6a332d3c5c4f2de2378c012f429cd109ba07d69690c6c701b6bb87860d6640",
        "bits": 140,
        "base_start": "80000000000000000000000000000000000",
        "dp": 18
    },
    145: {
        "pubkey": "03afdda497369e219a2c1c369954a930e4d3740968e5e4352475bcffce3140dae5",
        "bits": 145,
        "base_start": "1000000000000000000000000000000000000",
        "dp": 18
    },
    150: {
        "pubkey": "03137807790ea7dc6e97901c2bc87411f45ed74a5629315c4e4b03a0a102250c49",
        "bits": 150,
        "base_start": "20000000000000000000000000000000000000",
        "dp": 18
    }
}

def internal_create_job(req: CreateJobRequest) -> str:
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        job_id = f"job_{int(time.time())}"
        
        start_pct = max(0.0, min(100.0, req.start_percent))
        end_pct = max(start_pct, min(100.0, req.end_percent))

        if req.puzzle_number in PUZZLE_PRESETS:
            preset = PUZZLE_PRESETS[req.puzzle_number]
            pubkey = preset["pubkey"]
            bits = preset["bits"]
            base_start_int = int(preset["base_start"], 16)
            total_range_int = 1 << (bits - 1)
            
            start_offset_int = base_start_int + int((start_pct / 100.0) * total_range_int)
            start_hex = hex(start_offset_int)[2:]
            base_start_hex = preset["base_start"]
            range_bits = bits - 1
            dp_bits = preset["dp"]
        else:
            pubkey = req.pubkey.lower().strip() if req.pubkey else PUZZLE_PRESETS[66]["pubkey"]
            clean_start = req.start_hex.lower().replace("0x", "").strip() if req.start_hex else "20000000000000000"
            start_offset_int = int(clean_start, 16)
            range_bits = req.range_bits if req.range_bits else 66
            total_range_int = 1 << range_bits
            start_offset_int += int((start_pct / 100.0) * total_range_int)
            start_hex = hex(start_offset_int)[2:]
            base_start_hex = clean_start
            dp_bits = req.dp_bits

        cursor.execute('''
            INSERT INTO jobs (job_id, pubkey, start_hex, range_bits, dp_bits, chunk_bits, start_percent, end_percent, base_start_hex, current_offset_hex, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (job_id, pubkey.lower(), start_hex, range_bits, dp_bits, req.chunk_bits, start_pct, end_pct, base_start_hex, start_hex, time.time()))
        
        conn.commit()
        conn.close()
        print(f"🚀 Job Created: {job_id} for Puzzle {req.puzzle_number or 'Custom'} (Start Hex: {start_hex})")
        return job_id

# Protected Dashboard API
@app.post("/api/jobs/create")
def create_job(req: CreateJobRequest, username: str = Depends(authenticate_dashboard)):
    job_id = internal_create_job(req)
    return {"status": "SUCCESS", "job_id": job_id}

@app.post("/api/jobs/delete/{job_id}")
def delete_single_job(job_id: str, username: str = Depends(authenticate_dashboard)):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        cursor.execute("DELETE FROM chunks WHERE job_id = ?", (job_id,))
        conn.commit()
        conn.close()
    return {"status": "DELETED", "job_id": job_id}

@app.post("/api/jobs/clear")
def clear_jobs(username: str = Depends(authenticate_dashboard)):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM jobs")
        cursor.execute("DELETE FROM chunks")
        conn.commit()
        conn.close()
    return {"status": "CLEARED"}

@app.get("/api/stats")
def get_stats(username: str = Depends(authenticate_dashboard)):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        now = time.time()
        
        # Workers active within the last 60 seconds
        cursor.execute("SELECT * FROM workers WHERE (? - last_ping) < 60 ORDER BY last_ping DESC", (now,))
        raw_workers = [dict(w) for w in cursor.fetchall()]
        
        workers = []
        for w in raw_workers:
            w_dict = dict(w)
            cursor.execute('''
                SELECT start_hex, range_bits, assigned_at FROM chunks 
                WHERE assigned_worker = ? ORDER BY assigned_at DESC LIMIT 1
            ''', (w_dict['worker_id'],))
            chunk = cursor.fetchone()
            if chunk:
                w_dict['current_start_hex'] = f"0x{chunk['start_hex']}"
                w_dict['current_range_bits'] = chunk['range_bits']
            else:
                w_dict['current_start_hex'] = "Aguardando tarefa..."
                w_dict['current_range_bits'] = "-"
            workers.append(w_dict)
            
        total_hashrate = sum(w['hashrate_mhs'] for w in workers)
        
        cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        jobs_raw = [dict(j) for j in cursor.fetchall()]
        
        jobs = []
        for j in jobs_raw:
            j_dict = dict(j)
            if j_dict.get('private_key'):
                pk_hex = j_dict['private_key'].strip()
                j_dict['private_key_hex'] = pk_hex if pk_hex.startswith("0x") else f"0x{pk_hex}"
                j_dict['wif_compressed'] = hex_to_wif(pk_hex, compressed=True)
                j_dict['wif_uncompressed'] = hex_to_wif(pk_hex, compressed=False)
                if j_dict.get('solved_at'):
                    j_dict['solved_at_str'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(j_dict['solved_at']))
            jobs.append(j_dict)

        conn.close()

        return {
            "active_workers_count": len(workers),
            "total_pool_hashrate_mhs": round(total_hashrate, 2),
            "total_pool_hashrate_ghs": round(total_hashrate / 1000.0, 3),
            "workers": workers,
            "jobs": jobs
        }

# Open Worker Endpoints (Auto-Creates Job if No Active Job Exists)
@app.post("/api/worker/ensure_job")
def ensure_job(req: CreateJobRequest):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT job_id FROM jobs WHERE status = 'ACTIVE' LIMIT 1")
        active_job = cursor.fetchone()
        if active_job:
            conn.close()
            return {"status": "EXISTS", "job_id": active_job["job_id"]}
    
    # If no active job exists, auto-create requested puzzle job
    job_id = internal_create_job(req)
    return {"status": "AUTO_CREATED", "job_id": job_id}

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

        cursor.execute("UPDATE workers SET last_ping = ? WHERE worker_id = ?", (time.time(), req.worker_id))
        conn.commit()

        cursor.execute("SELECT * FROM jobs WHERE status = 'ACTIVE' ORDER BY created_at ASC LIMIT 1")
        job = cursor.fetchone()

        if not job:
            conn.close()
            return {"status": "NO_WORK", "message": "No active jobs available"}

        current_offset_int = int(job['current_offset_hex'], 16)
        chunk_bits = min(job['chunk_bits'], job['range_bits'])
        if chunk_bits < 48 and job['range_bits'] >= 48:
            chunk_bits = 66
            
        chunk_size = 1 << chunk_bits
        
        chunk_id = f"{job['job_id']}_chunk_{hex(current_offset_int)[2:]}"
        chunk_start_hex = hex(current_offset_int)[2:]
        
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
            "max_ops": "1.0"
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
        
        results_file = os.path.join(os.path.dirname(__file__), "POOL_RESULTS.TXT")
        wif_key = hex_to_wif(req.private_key, compressed=True)
        with open(results_file, "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] PUBKEY: {req.pubkey} | PRIVATE KEY HEX: {req.private_key} | WIF: {wif_key} | SOLVED BY: {req.worker_id}\n")

        conn.commit()
        conn.close()

    print(f"🎉 SOLVED! Worker {req.worker_id} found private key: {req.private_key} (WIF: {wif_key})")
    return {"status": "ACCEPTED", "message": "Solution recorded!"}

# HTML Dashboard Route
@app.get("/", response_class=HTMLResponse)
def get_dashboard(username: str = Depends(authenticate_dashboard)):
    html_content = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RCKangaroo Pool Coordinator Dashboard</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }
            .card { background-color: #161b22; border: 1px solid #30363d; border-radius: 10px; }
            .stat-header { font-size: 2.2rem; font-weight: bold; color: #58a6ff; }
            .stat-sub { color: #8b949e; font-size: 0.85rem; letter-spacing: 1px; }
            .table-dark { background-color: #161b22; color: #c9d1d9; border-color: #30363d; }
            .solved-banner {
                background: linear-gradient(135deg, rgba(35, 134, 54, 0.25) 0%, rgba(22, 27, 34, 0.95) 100%);
                border: 2px solid #238636;
                box-shadow: 0 0 25px rgba(35, 134, 54, 0.4);
                border-radius: 12px;
            }
            .key-box {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 10px 14px;
                font-family: monospace;
                word-break: break-all;
            }
        </style>
    </head>
    <body class="p-4">
        <div class="container-fluid">
            <!-- Header -->
            <div class="d-flex justify-content-between align-items-center mb-4 pb-2 border-bottom border-secondary">
                <div class="d-flex align-items-center">
                    <h2 class="mb-0 me-3">🦘 RCKangaroo Pool Coordinator</h2>
                    <span class="badge bg-success">Autenticado</span>
                </div>
                <div>
                    <button class="btn btn-outline-danger btn-sm me-2" onclick="clearOldJobs()">🗑️ Limpar Todos os Jobs e Testes</button>
                    <button class="btn btn-outline-primary btn-sm" onclick="loadStats()">🔄 Atualizar</button>
                </div>
            </div>

            <!-- Solved Alert Banner -->
            <div id="solved-solutions-container" class="mb-4"></div>

            <!-- Stats Row -->
            <div class="row g-3 mb-4">
                <div class="col-md-4">
                    <div class="card p-3 text-center">
                        <div class="stat-sub">HASHRATE TOTAL DA POOL</div>
                        <div class="stat-header" id="pool-hashrate">0.00 GH/s</div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card p-3 text-center">
                        <div class="stat-sub">WORKERS ATIVOS NO MOMENTO</div>
                        <div class="stat-header text-info" id="active-workers">0</div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card p-3 text-center">
                        <div class="stat-sub">JOBS ATIVOS</div>
                        <div class="stat-header text-warning" id="total-jobs">0</div>
                    </div>
                </div>
            </div>

            <!-- Create Job Form -->
            <div class="card p-4 mb-4">
                <h5 class="mb-3">➕ Lançar Busca de Puzzle (Definir Faixa %)</h5>
                
                <form id="jobForm" class="row g-3">
                    <div class="col-md-4">
                        <label class="form-label text-muted">Escolha o Puzzle Oficial:</label>
                        <select id="puzzle_select" class="form-select bg-dark text-light border-secondary" onchange="onPuzzleSelectChange()">
                            <option value="40">Puzzle #40 (40 bits)</option>
                            <option value="50">Puzzle #50 (50 bits)</option>
                            <option value="60">Puzzle #60 (60 bits)</option>
                            <option value="66" selected>Puzzle #66 (66 bits)</option>
                            <option value="130">Puzzle #130 (130 bits)</option>
                            <option value="135">Puzzle #135 (135 bits)</option>
                            <option value="140">Puzzle #140 (140 bits)</option>
                            <option value="145">Puzzle #145 (145 bits)</option>
                            <option value="150">Puzzle #150 (150 bits)</option>
                            <option value="custom">-- Customizado (Chave/Hex) --</option>
                        </select>
                    </div>

                    <div class="col-md-3">
                        <label class="form-label text-muted">Porcentagem Inicial (%):</label>
                        <div class="input-group">
                            <input type="number" step="0.00001" min="0" max="100" id="start_pct" class="form-control bg-dark text-light border-secondary" value="0.0" oninput="updateCalculatedHexPreview()">
                            <span class="input-group-text bg-dark text-muted border-secondary">%</span>
                        </div>
                    </div>

                    <div class="col-md-3">
                        <label class="form-label text-muted">Porcentagem Final (%):</label>
                        <div class="input-group">
                            <input type="number" step="0.00001" min="0" max="100" id="end_pct" class="form-control bg-dark text-light border-secondary" value="100.0" oninput="updateCalculatedHexPreview()">
                            <span class="input-group-text bg-dark text-muted border-secondary">%</span>
                        </div>
                    </div>

                    <div class="col-md-2 d-flex align-items-end">
                        <button type="submit" id="btn-submit-job" class="btn btn-success w-100 py-2 fw-bold">🚀 Lançar Busca</button>
                    </div>

                    <!-- Custom Fields (shown only if custom selected) -->
                    <div id="custom-fields" class="row g-2 mt-2 d-none">
                        <div class="col-md-6">
                            <input type="text" id="custom_pubkey" class="form-control bg-dark text-light border-secondary" placeholder="Public Key Hex">
                        </div>
                        <div class="col-md-4">
                            <input type="text" id="custom_start" class="form-control bg-dark text-light border-secondary" placeholder="Start Hex Prefix">
                        </div>
                        <div class="col-md-2">
                            <input type="number" id="custom_range" class="form-control bg-dark text-light border-secondary" placeholder="Range Bits" value="66">
                        </div>
                    </div>

                    <!-- Live Hex Calculation Preview -->
                    <div class="col-12 mt-2">
                        <div class="p-2 px-3 rounded bg-dark border border-secondary fs-7">
                            <span class="text-info fw-bold">🔍 Info da Faixa:</span>
                            <span class="ms-2 text-muted" id="preview-hex-info">Carregando...</span>
                        </div>
                    </div>
                </form>
            </div>

            <!-- Active Workers & Live Ranges Table -->
            <div class="card p-3 mb-4">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h5 class="mb-0">💻 Workers Ativos & Faixa Atual que Cada um Começou</h5>
                    <span class="badge bg-info">Desaparecem Automaticamente se Pararem</span>
                </div>
                <div class="table-responsive mt-2">
                    <table class="table table-dark table-hover align-middle">
                        <thead>
                            <tr>
                                <th>Worker ID / Nome</th>
                                <th>Hardware GPU</th>
                                <th>Hashrate</th>
                                <th>Faixa / Sub-bloco Atual Inicializado</th>
                                <th>Chunks Concluídos</th>
                                <th>Status (Último Ping)</th>
                            </tr>
                        </thead>
                        <tbody id="workers-table-body">
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Active Target Jobs Overview -->
            <div class="card p-3">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h5 class="mb-0">📋 Jobs de Busca</h5>
                    <button class="btn btn-outline-danger btn-sm" onclick="clearOldJobs()">🗑️ Limpar Todos os Jobs</button>
                </div>
                <div class="table-responsive mt-2">
                    <table class="table table-dark table-hover align-middle">
                        <thead>
                            <tr>
                                <th>Job ID</th>
                                <th>Public Key</th>
                                <th>Start Offset Hex</th>
                                <th>Range</th>
                                <th>Status</th>
                                <th>Ações / Resultado</th>
                            </tr>
                        </thead>
                        <tbody id="jobs-table-body">
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <script>
            const presets = {
                '40': { pubkey: '03a2efa402fd5268400c77c20e574ba86409ededee7c4020e4b9f0edbee53de0d4', bits: 40, base_start: '8000000000' },
                '50': { pubkey: '03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6', bits: 50, base_start: '200000000000' },
                '60': { pubkey: '0348e843dc5b1bd246e6309b4924b81543d02b16c8083df973a89ce2c7eb89a10d', bits: 60, base_start: '800000000000000' },
                '66': { pubkey: '024ee2be2d4e9f92d2f5a4a03058617dc45befe22938feed5b7a6b7282dd74cbdd', bits: 66, base_start: '20000000000000000' },
                '130': { pubkey: '03633cbe3ec02b9401c5effa144c5b4d22f87940259634858fc7e59b1c09937852', bits: 130, base_start: '20000000000000000000000000000000' },
                '135': { pubkey: '02145d2611c823a396ef6712ce0f712f09b9b4f3135e3e0aa3230fb9b6d08d1e16', bits: 135, base_start: '4000000000000000000000000000000004' },
                '140': { pubkey: '031f6a332d3c5c4f2de2378c012f429cd109ba07d69690c6c701b6bb87860d6640', bits: 140, base_start: '80000000000000000000000000000000000' },
                '145': { pubkey: '03afdda497369e219a2c1c369954a930e4d3740968e5e4352475bcffce3140dae5', bits: 145, base_start: '1000000000000000000000000000000000000' },
                '150': { pubkey: '03137807790ea7dc6e97901c2bc87411f45ed74a5629315c4e4b03a0a102250c49', bits: 150, base_start: '20000000000000000000000000000000000000' }
            };

            function copyText(str) {
                navigator.clipboard.writeText(str);
                alert("Copiado para a área de transferência!");
            }

            async function deleteSingleJob(jobId) {
                if (confirm("Apagar este job e o resultado de teste?")) {
                    await fetch('/api/jobs/delete/' + jobId, { method: 'POST' });
                    loadStats();
                }
            }

            async function clearOldJobs() {
                if (confirm("Tem certeza que deseja apagar TODOS os jobs e resultados de teste?")) {
                    await fetch('/api/jobs/clear', { method: 'POST' });
                    loadStats();
                }
            }

            function onPuzzleSelectChange() {
                const val = document.getElementById('puzzle_select').value;
                const customDiv = document.getElementById('custom-fields');
                if (val === 'custom') {
                    customDiv.classList.remove('d-none');
                } else {
                    customDiv.classList.add('d-none');
                }
                updateCalculatedHexPreview();
            }

            function updateCalculatedHexPreview() {
                const val = document.getElementById('puzzle_select').value;
                const startPct = parseFloat(document.getElementById('start_pct').value) || 0.0;
                const endPct = parseFloat(document.getElementById('end_pct').value) || 100.0;
                const previewEl = document.getElementById('preview-hex-info');

                if (presets[val]) {
                    const p = presets[val];
                    previewEl.innerHTML = `Puzzle #${val} (${p.bits} bits) | Pubkey: <code>${p.pubkey.substring(0, 24)}...</code> | Intervalo: <strong>${startPct}% → ${endPct}%</strong>`;
                } else {
                    previewEl.innerHTML = `Modo Customizado | Intervalo: <strong>${startPct}% → ${endPct}%</strong>`;
                }
            }

            async function loadStats() {
                try {
                    const res = await fetch('/api/stats');
                    if (res.status === 401) {
                        window.location.reload();
                        return;
                    }
                    const data = await res.json();

                    document.getElementById('pool-hashrate').innerText = data.total_pool_hashrate_ghs + ' GH/s';
                    document.getElementById('active-workers').innerText = data.active_workers_count;
                    document.getElementById('total-jobs').innerText = data.jobs.length;

                    // Solved Banner
                    const solvedContainer = document.getElementById('solved-solutions-container');
                    const solvedJobs = data.jobs.filter(j => j.status === 'SOLVED');

                    if (solvedJobs.length > 0) {
                        solvedContainer.innerHTML = solvedJobs.map(sj => `
                            <div class="card solved-banner p-4 mb-3">
                                <div class="d-flex justify-content-between align-items-center mb-3">
                                    <h3 class="text-success fw-bold mb-0">🎉 CHAVE PRIVADA ENCONTRADA!</h3>
                                    <div>
                                        <span class="badge bg-success fs-6 me-2">${sj.solved_at_str || 'Recente'}</span>
                                        <button class="btn btn-outline-danger btn-sm fw-bold" onclick="deleteSingleJob('${sj.job_id}')">🗑️ Apagar Este Resultado</button>
                                    </div>
                                </div>
                                <div class="row g-3">
                                    <div class="col-md-6">
                                        <div class="stat-sub">PUBKEY ALVO:</div>
                                        <div class="key-box text-info">${sj.pubkey}</div>
                                    </div>
                                    <div class="col-md-6">
                                        <div class="stat-sub">ENCONTRADA POR WORKER:</div>
                                        <div class="key-box text-warning">${sj.solved_by || 'Desconhecido'}</div>
                                    </div>
                                    <div class="col-md-12">
                                        <div class="d-flex justify-content-between align-items-center mb-1">
                                            <div class="stat-sub">CHAVE PRIVADA (HEX):</div>
                                            <button class="btn btn-sm btn-outline-success" onclick="copyText('${sj.private_key_hex}')">📋 Copiar HEX</button>
                                        </div>
                                        <div class="key-box text-success fw-bold fs-5">${sj.private_key_hex}</div>
                                    </div>
                                    <div class="col-md-12">
                                        <div class="d-flex justify-content-between align-items-center mb-1">
                                            <div class="stat-sub">CHAVE PRIVADA (FORMATO WIF COMPRESSADO):</div>
                                            <button class="btn btn-sm btn-outline-success" onclick="copyText('${sj.wif_compressed}')">📋 Copiar WIF</button>
                                        </div>
                                        <div class="key-box text-warning fw-bold fs-5">${sj.wif_compressed}</div>
                                    </div>
                                </div>
                            </div>
                        `).join('');
                    } else {
                        solvedContainer.innerHTML = '';
                    }

                    // Render Active Workers & Their Live Started Ranges
                    const workersBody = document.getElementById('workers-table-body');
                    if (data.workers.length === 0) {
                        workersBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted p-4">Nenhum worker ativo no momento. Ao conectar um worker (local/Vast.ai), a faixa dele aparecerá aqui automaticamente. Se o worker parar, ele é removido da lista.</td></tr>`;
                    } else {
                        workersBody.innerHTML = data.workers.map(w => `
                            <tr>
                                <td><code>${w.worker_id}</code><br><strong>${w.name}</strong></td>
                                <td>${w.gpu_info}</td>
                                <td style="color: #58a6ff; font-weight: bold;">${w.hashrate_mhs.toFixed(2)} MH/s</td>
                                <td style="font-family: monospace;">
                                    <span class="badge bg-dark border border-primary text-info fs-7">${w.current_start_hex || 'Iniciando...'}</span>
                                </td>
                                <td><span class="badge bg-secondary fs-7">${w.completed_chunks}</span></td>
                                <td><span class="badge bg-success">🟢 Ativo (${Math.round(Date.now()/1000 - w.last_ping)}s atrás)</span></td>
                            </tr>
                        `).join('');
                    }

                    // Render Jobs Table
                    const jobsBody = document.getElementById('jobs-table-body');
                    if (data.jobs.length === 0) {
                        jobsBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted p-3">Nenhum job no momento.</td></tr>`;
                    } else {
                        jobsBody.innerHTML = data.jobs.map(j => `
                            <tr>
                                <td><code>${j.job_id}</code></td>
                                <td class="text-truncate" style="max-width: 250px;">${j.pubkey}</td>
                                <td><code>0x${j.start_hex}</code></td>
                                <td>${j.range_bits} bits</td>
                                <td><span class="badge ${j.status === 'SOLVED' ? 'bg-success' : 'bg-primary'}">${j.status}</span></td>
                                <td style="font-family: monospace;">
                                    ${j.status === 'SOLVED' ? `
                                        <button class="btn btn-sm btn-outline-danger me-2" onclick="deleteSingleJob('${j.job_id}')">🗑️ Apagar</button>
                                        <span class="text-success fw-bold">${j.private_key_hex}</span>
                                    ` : `
                                        <button class="btn btn-sm btn-outline-danger" onclick="deleteSingleJob('${j.job_id}')">🗑️ Cancelar / Apagar</button>
                                    `}
                                </td>
                            </tr>
                        `).join('');
                    }

                } catch (e) {
                    console.error('Erro ao carregar dados:', e);
                }
            }

            document.getElementById('jobForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const btn = document.getElementById('btn-submit-job');
                btn.disabled = true;
                btn.innerText = 'Lançando...';

                const pVal = document.getElementById('puzzle_select').value;
                const payload = {
                    start_percent: parseFloat(document.getElementById('start_pct').value) || 0.0,
                    end_percent: parseFloat(document.getElementById('end_pct').value) || 100.0,
                    dp_bits: 18,
                    chunk_bits: 66
                };

                if (pVal !== 'custom') {
                    payload.puzzle_number = parseInt(pVal);
                } else {
                    payload.pubkey = document.getElementById('custom_pubkey').value.trim();
                    payload.start_hex = document.getElementById('custom_start').value.trim();
                    payload.range_bits = parseInt(document.getElementById('custom_range').value) || 66;
                }

                try {
                    const res = await fetch('/api/jobs/create', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    if (res.ok) {
                        alert("🚀 Busca lançada com sucesso! O worker iniciará o processamento em poucos segundos.");
                    }
                } catch(err) {
                    alert("Erro ao lançar busca: " + err);
                } finally {
                    btn.disabled = false;
                    btn.innerText = '🚀 Lançar Busca';
                    loadStats();
                }
            });

            onPuzzleSelectChange();
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
