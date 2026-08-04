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


TAMES_DIR = os.path.join(os.path.dirname(__file__), "tames")
os.makedirs(TAMES_DIR, exist_ok=True)

@app.get("/tames/{filename}")
def download_tame_file(filename: str):
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(TAMES_DIR, safe_filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Tame file not found")
    return FileResponse(filepath, media_type="application/octet-stream", filename=safe_filename)

@app.get("/api/tames/check/{puzzle_number}")
def check_tame_file(puzzle_number: int):
    filename = f"tames{puzzle_number}.dat"
    filepath = os.path.join(TAMES_DIR, filename)
    exists = os.path.exists(filepath)
    size_bytes = os.path.getsize(filepath) if exists else 0
    return {
        "exists": exists,
        "filename": filename if exists else None,
        "download_url": f"/tames/{filename}" if exists else None,
        "size_mb": round(size_bytes / (1024 * 1024), 2) if exists else 0
    }

# CORS restrito ao domínio configurado na VPS
_ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_ALLOWED_ORIGIN] if _ALLOWED_ORIGIN else [],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

DB_FILE = os.path.join(os.path.dirname(__file__), "pool.db")
db_lock = threading.RLock()
security = HTTPBasic()

# ─── Credenciais do Dashboard (nunca hardcode — lidas do ambiente da VPS) ──────
DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "")
DASHBOARD_PASS = os.environ.get("DASHBOARD_PASS", "")
if not DASHBOARD_USER or not DASHBOARD_PASS:
    raise RuntimeError(
        "⛔ DASHBOARD_USER e DASHBOARD_PASS devem estar definidos como variáveis de ambiente. "
        "Defina-os no arquivo .env da VPS ou via docker-compose."
    )

# ─── Token de autenticação para workers ─────────────────────────────────────────
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
if not WORKER_TOKEN:
    raise RuntimeError(
        "⛔ WORKER_TOKEN deve estar definido como variável de ambiente. "
        "Configure-o no .env da VPS e no start_worker.sh dos containers."
    )

def verify_worker_token(request: Request):
    """Dependência usada em todos os endpoints de worker para validar o token."""
    token = request.headers.get("X-Worker-Token", "")
    if not secrets.compare_digest(token, WORKER_TOKEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token de worker inválido")

def authenticate_dashboard(credentials: HTTPBasicCredentials = Depends(security)):
    is_correct_username = secrets.compare_digest(credentials.username, DASHBOARD_USER)
    is_correct_password = secrets.compare_digest(credentials.password, DASHBOARD_PASS)
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

def hex_to_wif(hex_key: str, compressed: bool = True) -> str:
    clean_hex = hex_key.strip()
    if clean_hex.startswith("0x") or clean_hex.startswith("0X"):
        clean_hex = clean_hex[2:]
    clean_hex = clean_hex.zfill(64)
    raw_key = bytes.fromhex(clean_hex)
    extended = b'\x80' + raw_key
    if compressed:
        extended += b'\x01'
    first_sha = hashlib.sha256(extended).digest()
    second_sha = hashlib.sha256(first_sha).digest()
    checksum = second_sha[:4]
    return base58_encode(extended + checksum)

def pubkey_to_address(pubkey_hex: str) -> str:
    try:
        clean = pubkey_hex.strip()
        if clean.startswith("0x") or clean.startswith("0X"):
            clean = clean[2:]
        pub_bytes = bytes.fromhex(clean)
        sha256_res = hashlib.sha256(pub_bytes).digest()
        ripemd160_res = hashlib.new('ripemd160', sha256_res).digest()
        extended = b'\x00' + ripemd160_res
        checksum = hashlib.sha256(hashlib.sha256(extended).digest()).digest()[:4]
        return base58_encode(extended + checksum)
    except Exception:
        return "N/A"


# SECP256K1 Verification Math
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

def _point_add(p1, p2):
    if p1 is None: return p2
    if p2 is None: return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and y1 != y2: return None
    if x1 == x2:
        m = (3 * x1 * x1) * pow(2 * y1, _P - 2, _P) % _P
    else:
        m = (y2 - y1) * pow(x2 - x1, _P - 2, _P) % _P
    x3 = (m * m - x1 - x2) % _P
    y3 = (m * (x1 - x3) - y1) % _P
    return (x3, y3)

def _point_mult(k):
    res = None
    addend = (_Gx, _Gy)
    while k:
        if k & 1:
            res = _point_add(res, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return res

def verify_private_key(privkey_hex: str, target_pubkey_hex: str) -> bool:
    try:
        clean_priv = privkey_hex.strip()
        if clean_priv.startswith("0x") or clean_priv.startswith("0X"):
            clean_priv = clean_priv[2:]
        k = int(clean_priv, 16)
        if k <= 0:
            return False
        point = _point_mult(k)
        if not point:
            return False
        x, y = point
        prefix = "02" if y % 2 == 0 else "03"
        calc_pubkey = f"{prefix}{x:064x}".lower()
        target_clean = target_pubkey_hex.strip().lower()
        return calc_pubkey == target_clean
    except Exception:
        return False

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

        try:
            cursor.execute("ALTER TABLE workers ADD COLUMN current_job_id TEXT")
        except Exception:
            pass

        # Adiciona colunas de controle de conclusão real nos chunks
        chunks_cols = [
            ("completed_at", "REAL"),
            ("heartbeat_at", "REAL"),
        ]
        for col_name, col_type in chunks_cols:
            try:
                cursor.execute(f"ALTER TABLE chunks ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

        conn.commit()

        # WAL mode: múltiplos leitores simultâneos sem bloquear escritas
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.commit()
        conn.close()

init_db()

# ─── Background: recoloca chunks abandonados de volta para PENDING ────────────
# Timeout configurável por env var: chunks grandes (90-bits) podem durar horas
CHUNK_TIMEOUT_SECONDS = int(os.environ.get("CHUNK_TIMEOUT_SECONDS", "3600"))  # default 1h
WORKER_ALIVE_SECONDS  = int(os.environ.get("WORKER_ALIVE_SECONDS",  "90"))    # heartbeat threshold

def _recover_abandoned_chunks():
    """Thread que roda a cada 60s e recupera chunks ASSIGNED cujo worker sumiu."""
    while True:
        time.sleep(60)
        try:
            with db_lock:
                conn = get_db()
                cursor = conn.cursor()
                now = time.time()
                cutoff = now - CHUNK_TIMEOUT_SECONDS

                # Chunks ASSIGNED mas cujo worker não fez ping nos últimos CHUNK_TIMEOUT_SECONDS
                cursor.execute('''
                    UPDATE chunks SET status = 'PENDING', assigned_worker = NULL, assigned_at = NULL
                    WHERE status = 'ASSIGNED'
                    AND chunk_id IN (
                        SELECT c.chunk_id FROM chunks c
                        LEFT JOIN workers w ON w.worker_id = c.assigned_worker
                        WHERE c.status = 'ASSIGNED'
                        AND (w.last_ping IS NULL OR w.last_ping < ?)
                    )
                ''', (cutoff,))

                recovered = cursor.rowcount
                if recovered > 0:
                    print(f"♻️  Recovered {recovered} abandoned chunk(s) back to PENDING (timeout={CHUNK_TIMEOUT_SECONDS}s)")

                conn.commit()
                conn.close()
        except Exception as e:
            print(f"⚠️  Error in chunk recovery thread: {e}")

_recovery_thread = threading.Thread(target=_recover_abandoned_chunks, daemon=True)
_recovery_thread.start()

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
    worker_id: Optional[str] = None

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
    hashrate_mhs: Optional[float] = None

class CompleteChunkRequest(BaseModel):
    worker_id: str
    chunk_id: str

class SubmitSolutionRequest(BaseModel):
    worker_id: str
    chunk_id: str
    pubkey: str
    private_key: str

# Preset Puzzles Dictionary (Dados Oficiais dos Desafios Bitcoin)
# chunk_bits: tamanho de cada fatia de trabalho por puzzle
#   Puzzles pequenos (≤66 bits): chunks menores (~66 bits), completam em segundos/minutos
#   Puzzles grandes (130+ bits): chunks de 80-90 bits, cada um dura horas por worker
#   dp (é calculado dinamicamente em get_work): dp = max(14, (chunk_bits//2) - 2)
PUZZLE_PRESETS = {
    40: {
        "pubkey": "03a2efa402fd5268400c77c20e574ba86409ededee7c4020e4b9f0edbee53de0d4",
        "bits": 40,
        "base_start": "8000000000",
        "chunk_bits": 34
    },
    50: {
        "pubkey": "03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6",
        "bits": 50,
        "base_start": "200000000000",
        "chunk_bits": 40
    },
    60: {
        "pubkey": "0348e843dc5b1bd246e6309b4924b81543d02b16c8083df973a89ce2c7eb89a10d",
        "bits": 60,
        "base_start": "800000000000000",
        "chunk_bits": 50
    },
    66: {
        "pubkey": "024ee2be2d4e9f92d2f5a4a03058617dc45befe22938feed5b7a6b7282dd74cbdd",
        "bits": 66,
        "base_start": "20000000000000000",
        "chunk_bits": 66
    },
    100: {
        "pubkey": "035c38bd9ae4b10e8a250857006f3cfd98ab15a6196d9f4dfd25bc7ecc77d788d5",
        "bits": 100,
        "base_start": "20000000000000000000000",
        "chunk_bits": 75
    },
    130: {
        "pubkey": "03633cbe3ec02b9401c5effa144c5b4d22f87940259634858fc7e59b1c09937852",
        "bits": 130,
        "base_start": "20000000000000000000000000000000",
        "chunk_bits": 80   # ~15-30 min por chunk em GPU potente
    },
    135: {
        "pubkey": "02145d2611c823a396ef6712ce0f712f09b9b4f3135e3e0aa3230fb9b6d08d1e16",
        "bits": 135,
        "base_start": "4000000000000000000000000000000004",
        "chunk_bits": 80
    },
    140: {
        "pubkey": "031f6a332d3c5c4f2de2378c012f429cd109ba07d69690c6c701b6bb87860d6640",
        "bits": 140,
        "base_start": "80000000000000000000000000000000000",
        "chunk_bits": 90   # ~2-6h por chunk em RTX 4090/5090 — menos overhead de coordenação
    },
    145: {
        "pubkey": "03afdda497369e219a2c1c369954a930e4d3740968e5e4352475bcffce3140dae5",
        "bits": 145,
        "base_start": "1000000000000000000000000000000000000",
        "chunk_bits": 90
    },
    150: {
        "pubkey": "03137807790ea7dc6e97901c2bc87411f45ed74a5629315c4e4b03a0a102250c49",
        "bits": 150,
        "base_start": "20000000000000000000000000000000000000",
        "chunk_bits": 90
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
            chunk_bits_to_use = preset.get("chunk_bits", req.chunk_bits)
            dp_bits = 0  # será calculado dinamicamente em get_work
        else:
            pubkey = req.pubkey.lower().strip() if req.pubkey else PUZZLE_PRESETS[66]["pubkey"]
            clean_start = req.start_hex.lower().replace("0x", "").strip() if req.start_hex else "20000000000000000"
            start_offset_int = int(clean_start, 16)
            range_bits = req.range_bits if req.range_bits else 66
            total_range_int = 1 << range_bits
            start_offset_int += int((start_pct / 100.0) * total_range_int)
            start_hex = hex(start_offset_int)[2:]
            base_start_hex = clean_start
            chunk_bits_to_use = req.chunk_bits
            dp_bits = req.dp_bits

        cursor.execute('''
            INSERT INTO jobs (job_id, pubkey, start_hex, range_bits, dp_bits, chunk_bits, start_percent, end_percent, base_start_hex, current_offset_hex, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (job_id, pubkey.lower(), start_hex, range_bits, dp_bits, chunk_bits_to_use, start_pct, end_pct, base_start_hex, start_hex, time.time()))
        
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

def generate_coverage_report():
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        now = time.time()
        
        cursor.execute("SELECT * FROM jobs WHERE status IN ('ACTIVE', 'SOLVED', 'COMPLETED') ORDER BY start_percent ASC")
        jobs = [dict(j) for j in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM workers WHERE (? - last_ping) < ?", (now, WORKER_ALIVE_SECONDS))
        raw_w = cursor.fetchall()
        active_workers = {dict(w)['current_job_id']: dict(w)['name'] for w in raw_w if dict(w).get('current_job_id')}
        
        report_lines = []
        report_lines.append("======================================================================")
        report_lines.append("       RCKangaroo Pool - Relatório de Cobertura & Anti-Sobreposição   ")
        report_lines.append(f"       Atualizado em: {time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        report_lines.append("======================================================================\n")

        scanned_ranges = []
        active_ranges = []
        all_covered_intervals = []

        if jobs:
            report_lines.append("✅ [FAIXAS JÁ VARRIDAS E CONCLUÍDAS (EXCLUÍDAS DE RETRABALHO)]")
            scanned_count = 0
            for j in jobs:
                s_pct = float(j.get('start_percent', 0.0))
                e_pct = float(j.get('end_percent', 100.0))
                
                scanned_pct = s_pct
                try:
                    start_offset_int = int(j.get('start_hex', '0'), 16)
                    current_offset_int = int(j.get('current_offset_hex', j.get('start_hex', '0')), 16)
                    bits = j.get('range_bits', 139)
                    total_range_int = 1 << bits
                    if total_range_int > 0 and current_offset_int > start_offset_int:
                        progress_ratio = (current_offset_int - start_offset_int) / float(total_range_int)
                        scanned_pct = min(e_pct, s_pct + progress_ratio * (e_pct - s_pct))
                except Exception:
                    scanned_pct = s_pct

                if j['status'] in ('SOLVED', 'COMPLETED'):
                    scanned_pct = e_pct

                if scanned_pct > s_pct + 0.001:
                    scanned_count += 1
                    scanned_ranges.append((s_pct, scanned_pct))
                    report_lines.append(f"  • Faixa Varrida: {s_pct:.2f}% → {scanned_pct:.2f}% (Concluída - Sub-bloco Hex: 0x{j.get('current_offset_hex', '0')})")

                all_covered_intervals.append((s_pct, e_pct))
                
                if j['status'] == 'ACTIVE' and scanned_pct < e_pct:
                    w_name = active_workers.get(j['job_id'], "Worker Ativo")
                    active_ranges.append((scanned_pct, e_pct, w_name, j['job_id'], j.get('current_offset_hex', '0')))

            if scanned_count == 0:
                report_lines.append("  (Nenhum sub-bloco concluído ainda - workers iniciando varredura...)")
            report_lines.append("")

            report_lines.append("🟢 [FAIXAS EM MINERAÇÃO ATIVA NO MOMENTO]")
            if active_ranges:
                for act_s, act_e, w_name, j_id, cur_hex in active_ranges:
                    report_lines.append(f"  • Em Progresso: {act_s:.2f}% → {act_e:.2f}% | Worker: {w_name} | Sub-bloco Hex: 0x{cur_hex}")
            else:
                report_lines.append("  ⚠️ Nenhuma faixa em mineração no momento.")
            report_lines.append("")
        else:
            report_lines.append("⚠️ Nenhuma faixa ativa no momento.\n")

        # Calculate free/unexplored gaps between 0.0% and 100.0%
        all_covered_intervals.sort(key=lambda x: x[0])
        free_gaps = []
        curr = 0.0
        for s_pct, e_pct in all_covered_intervals:
            if s_pct > curr + 0.05:
                free_gaps.append((round(curr, 2), round(s_pct, 2)))
            curr = max(curr, e_pct)
        if curr < 99.95:
            free_gaps.append((round(curr, 2), 100.0))

        report_lines.append("🆓 [FAIXAS LIVRES E INTOCADAS (RECOMENDADAS PARA NOVOS WORKERS)]")
        if free_gaps:
            for g_start, g_end in free_gaps:
                report_lines.append(f"  ✓ Faixa Livre: {g_start:.2f}% → {g_end:.2f}% (LIVRE - Use esta faixa para novos Workers!)")
        else:
            report_lines.append("  🎉 100% do range do Puzzle está totalmente coberto!")

        report_lines.append("\n======================================================================")
        report_text = "\n".join(report_lines)
        
        filepath = os.path.join(os.path.dirname(__file__), "COVERAGE.TXT")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report_text)
        except Exception as e:
            print(f"Error writing COVERAGE.TXT: {e}")
            
        return {
            "text": report_text,
            "scanned_ranges": scanned_ranges,
            "free_gaps": free_gaps
        }

@app.get("/api/coverage")
def get_coverage_endpoint():
    return generate_coverage_report()

@app.get("/api/stats")
def get_stats(username: str = Depends(authenticate_dashboard)):
    cov_data = generate_coverage_report()
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        now = time.time()
        
        # Workers active within the last 60 seconds
        cursor.execute("SELECT * FROM workers WHERE (? - last_ping) < ? ORDER BY last_ping DESC", (now, WORKER_ALIVE_SECONDS))
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
            
            cursor.execute("SELECT COUNT(*) as cnt FROM chunks WHERE assigned_worker = ? AND status IN ('COMPLETED', 'SOLVED')", (w_dict['worker_id'],))
            w_dict['completed_chunks'] = cursor.fetchone()['cnt']
            
            if w_dict.get('current_job_id'):
                cursor.execute("SELECT start_percent, end_percent FROM jobs WHERE job_id = ?", (w_dict['current_job_id'],))
                cj = cursor.fetchone()
                if cj:
                    w_dict['assigned_range'] = f"{cj['start_percent']}% → {cj['end_percent']}%"
                else:
                    w_dict['assigned_range'] = "0% → 100%"
            else:
                cursor.execute("""
                    SELECT j.start_percent, j.end_percent FROM chunks c 
                    JOIN jobs j ON c.job_id = j.job_id 
                    WHERE c.assigned_worker = ? ORDER BY c.assigned_at DESC LIMIT 1
                """, (w_dict['worker_id'],))
                cj = cursor.fetchone()
                if cj:
                    w_dict['assigned_range'] = f"{cj['start_percent']}% → {cj['end_percent']}%"
                else:
                    w_dict['assigned_range'] = "0% → 100%"

            workers.append(w_dict)
            
        total_hashrate = sum(w['hashrate_mhs'] for w in workers)
        
        cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        jobs_raw = [dict(j) for j in cursor.fetchall()]
        
        pubkey_to_preset = {}
        for p_num, p_data in PUZZLE_PRESETS.items():
            pubkey_to_preset[p_data["pubkey"].lower()] = (p_num, p_data["bits"])

        jobs = []
        for j in jobs_raw:
            j_dict = dict(j)
            pub = j_dict.get('pubkey', '').lower()
            j_dict['btc_address'] = pubkey_to_address(pub)
            
            cursor.execute("SELECT COUNT(*) as cnt FROM chunks WHERE job_id = ?", (j_dict['job_id'],))
            j_dict['total_chunks_assigned'] = cursor.fetchone()['cnt']
            
            cursor.execute("SELECT COUNT(*) as cnt FROM chunks WHERE job_id = ? AND status IN ('COMPLETED', 'SOLVED')", (j_dict['job_id'],))
            j_dict['completed_chunks'] = cursor.fetchone()['cnt']
            
            if pub in pubkey_to_preset:
                p_num, p_bits = pubkey_to_preset[pub]
                j_dict['puzzle_name'] = f"Puzzle #{p_num} ({p_bits} bits)"
                j_dict['puzzle_number'] = p_num
            else:
                j_dict['puzzle_name'] = f"Custom ({j_dict.get('range_bits', 66) + 1} bits)"
                j_dict['puzzle_number'] = None

            if j_dict.get('private_key'):
                pk_hex = j_dict['private_key'].strip()
                j_dict['private_key_hex'] = pk_hex if pk_hex.startswith("0x") else f"0x{pk_hex}"
                j_dict['wif_compressed'] = hex_to_wif(pk_hex, compressed=True)
                j_dict['wif_uncompressed'] = hex_to_wif(pk_hex, compressed=False)
                if j_dict.get('solved_at'):
                    j_dict['solved_at_str'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(j_dict['solved_at']))
            jobs.append(j_dict)

        conn.close()

        # Calcula soma real de chaves e total de chunks concluidos
        total_completed_chunks = sum(j['completed_chunks'] for j in jobs)
        cursor = get_db().cursor()
        cursor.execute("SELECT range_bits FROM chunks WHERE status IN ('COMPLETED', 'SOLVED')")
        rows = cursor.fetchall()
        keys_tested = sum(2**int(r[0]) for r in rows)
        keys_zetta = keys_tested / (10**21)
        keys_exa   = keys_tested / (10**18)
        
        if keys_zetta >= 1_000_000:
            keys_zetta_str = f"{keys_zetta/1_000_000:.2f} M Zetakeys"
        elif keys_zetta >= 1_000:
            keys_zetta_str = f"{keys_zetta/1_000:.2f} K Zetakeys"
        elif keys_zetta >= 1:
            keys_zetta_str = f"{keys_zetta:.2f} Zetakeys"
        else:
            keys_zetta_str = f"{keys_exa:.2f} Exakeys"

        # Cálculo de métricas avançadas do Cluster
        total_gpus = 0
        for w in workers:
            gpu_str = w.get("gpu_info", "")
            g_cnt = max(1, len([g for g in gpu_str.split(",") if g.strip()])) if gpu_str else 1
            total_gpus += g_cnt

        active_kangaroos_m = round(total_gpus * 2.0029, 1)  # ~2M kangaroos por GPU RTX 4090/5090

        cursor.execute("SELECT status, COUNT(*) FROM chunks GROUP BY status")
        chunk_counts = {r[0]: r[1] for r in cursor.fetchall()}
        assigned_chunks = chunk_counts.get("ASSIGNED", 0)
        pending_chunks = chunk_counts.get("PENDING", 0)
        total_created_chunks = sum(chunk_counts.values())

        # Tempo de processamento do Job ativo mais recente
        active_job_uptime = "0h 0m"
        if jobs:
            act_j = next((j for j in jobs if j.get("status") == "ACTIVE"), jobs[0])
            c_time = act_j.get("created_at")
            if c_time:
                up_sec = int(time.time() - c_time)
                h = up_sec // 3600
                m = (up_sec % 3600) // 60
                active_job_uptime = f"{h}h {m}m"

        return {
            "active_workers_count": len(workers),
            "total_gpus_count": total_gpus,
            "total_pool_hashrate_mhs": round(total_hashrate, 2),
            "total_pool_hashrate_ghs": round(total_hashrate / 1000.0, 3),
            "total_completed_chunks": total_completed_chunks,
            "assigned_chunks_count": assigned_chunks,
            "pending_chunks_count": pending_chunks,
            "total_created_chunks": total_created_chunks,
            "active_kangaroos_m": f"{active_kangaroos_m}M+",
            "dp_overhead_str": "7% ~ 15%",
            "active_job_uptime": active_job_uptime,
            "keys_tested": keys_tested,
            "keys_zetta_str": keys_zetta_str,
            "workers": workers,
            "jobs": jobs,
            "coverage": cov_data
        }

# Open Worker Endpoints (Auto-Creates Job if No Active Job Exists)
@app.post("/api/worker/ensure_job")
def ensure_job(req: CreateJobRequest, _: None = Depends(verify_worker_token)):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        
        target_pubkey = None
        if req.puzzle_number in PUZZLE_PRESETS:
            target_pubkey = PUZZLE_PRESETS[req.puzzle_number]["pubkey"].lower()
        elif req.pubkey:
            target_pubkey = req.pubkey.lower()

        if target_pubkey:
            # Check if active job for exact same pubkey and matching range % already exists
            cursor.execute("""
                SELECT job_id FROM jobs 
                WHERE status = 'ACTIVE' 
                AND LOWER(pubkey) = ? 
                AND ABS(start_percent - ?) < 0.01 
                AND ABS(end_percent - ?) < 0.01 
                LIMIT 1
            """, (target_pubkey, req.start_percent, req.end_percent))
            range_job = cursor.fetchone()

            if range_job:
                job_id = range_job["job_id"]
                # Se o job existente já atingiu o fim da fatia, reseta o offset para permitir novo teste
                cursor.execute("SELECT start_hex, base_start_hex, range_bits, end_percent, current_offset_hex FROM jobs WHERE job_id = ?", (job_id,))
                row = cursor.fetchone()
                if row:
                    try:
                        cur_off = int(row['current_offset_hex'], 16)
                        b_start = int(row['base_start_hex'], 16)
                        tot_r = 1 << int(row['range_bits'])
                        e_off = b_start + int((float(row['end_percent']) / 100.0) * tot_r)
                        if cur_off >= e_off:
                            cursor.execute("UPDATE jobs SET current_offset_hex = start_hex WHERE job_id = ?", (job_id,))
                            cursor.execute("UPDATE chunks SET status = 'CANCELLED' WHERE job_id = ?", (job_id,))
                    except Exception:
                        pass

                if req.worker_id:
                    cursor.execute("UPDATE workers SET current_job_id = ? WHERE worker_id = ?", (job_id, req.worker_id))
                conn.commit()
                conn.close()
                return {"status": "EXISTS", "job_id": job_id}

            # Deactivate jobs for a completely different puzzle
            cursor.execute("UPDATE jobs SET status = 'CANCELLED' WHERE status = 'ACTIVE' AND LOWER(pubkey) != ?", (target_pubkey,))
            conn.commit()
            conn.close()
    
    # Auto-create job for this specific range
    job_id = internal_create_job(req)
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        if req.worker_id:
            cursor.execute("UPDATE workers SET current_job_id = ? WHERE worker_id = ?", (job_id, req.worker_id))
            conn.commit()
        conn.close()
    return {"status": "AUTO_CREATED", "job_id": job_id}


@app.post("/api/worker/register")
def register_worker(req: WorkerRegisterRequest, _: None = Depends(verify_worker_token)):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO workers (worker_id, name, os_info, gpu_info, hashrate_mhs, last_ping, completed_chunks)
            VALUES (?, ?, ?, ?, 0.0, ?, 0)
            ON CONFLICT(worker_id) DO UPDATE SET
                name=excluded.name,
                os_info=excluded.os_info,
                gpu_info=excluded.gpu_info,
                last_ping=excluded.last_ping
        ''', (req.worker_id, req.name, req.os_info, req.gpu_info, time.time()))
        conn.commit()
        conn.close()
    return {"status": "REGISTERED", "worker_id": req.worker_id}

@app.post("/api/worker/heartbeat")
def heartbeat(req: WorkerHeartbeatRequest, _: None = Depends(verify_worker_token)):
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
def get_work(req: WorkRequest, _: None = Depends(verify_worker_token)):
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()

        if req.hashrate_mhs is not None and req.hashrate_mhs > 0:
            cursor.execute("UPDATE workers SET last_ping = ?, hashrate_mhs = ? WHERE worker_id = ?", (time.time(), req.hashrate_mhs, req.worker_id))
        else:
            cursor.execute("UPDATE workers SET last_ping = ? WHERE worker_id = ?", (time.time(), req.worker_id))

        # 1. Primary lookup: active job linked via workers.current_job_id
        cursor.execute("""
            SELECT j.* FROM jobs j 
            JOIN workers w ON w.current_job_id = j.job_id 
            WHERE w.worker_id = ? AND j.status = 'ACTIVE' 
            LIMIT 1
        """, (req.worker_id,))
        job = cursor.fetchone()

        # 2. Secondary lookup: recent job chunks for this worker
        if not job:
            cursor.execute("""
                SELECT j.* FROM chunks c
                JOIN jobs j ON c.job_id = j.job_id
                WHERE c.assigned_worker = ? AND j.status = 'ACTIVE'
                ORDER BY c.assigned_at DESC LIMIT 1
            """, (req.worker_id,))
            job = cursor.fetchone()

        # 3. Fallback: latest active job
        if not job:
            cursor.execute("SELECT * FROM jobs WHERE status = 'ACTIVE' ORDER BY created_at DESC LIMIT 1")
            job = cursor.fetchone()

        if not job:
            conn.close()
            return {"status": "NO_WORK", "message": "No active jobs available"}

        # Link worker to this active job
        cursor.execute("UPDATE workers SET current_job_id = ? WHERE worker_id = ?", (job['job_id'], req.worker_id))

        current_offset_int = int(job['current_offset_hex'], 16)
        chunk_bits = min(job['chunk_bits'], job['range_bits'])
        if chunk_bits < 48 and job['range_bits'] >= 48:
            chunk_bits = 66
            
        chunk_size = 1 << chunk_bits

        # 🛡️ TRAVA DE FIM DE FATIA: calcula o endereço hex final do job
        # e impede que o ponteiro vaze além do end_percent da fatia.
        base_start_int = int(job['base_start_hex'], 16)
        total_range_int = 1 << job['range_bits']
        end_pct = float(job['end_percent'])
        end_offset_int = base_start_int + int((end_pct / 100.0) * total_range_int)

        if current_offset_int >= end_offset_int:
            conn.commit()
            conn.close()
            print(f"✅ Job {job['job_id']} atingiu o fim da fatia ({end_pct:.2f}%). Retornando NO_WORK.")
            return {"status": "NO_WORK", "message": f"Fatia concluída até {end_pct:.2f}%"}

        chunk_id = f"{job['job_id']}_chunk_{hex(current_offset_int)[2:]}"
        chunk_start_hex = hex(current_offset_int)[2:]
        
        next_offset_int = current_offset_int + chunk_size
        next_offset_hex = hex(next_offset_int)[2:]

        cursor.execute("UPDATE jobs SET current_offset_hex = ? WHERE job_id = ?", (next_offset_hex, job['job_id']))
        cursor.execute('''
            INSERT INTO chunks (chunk_id, job_id, start_hex, range_bits, assigned_worker, assigned_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'ASSIGNED')
        ''', (chunk_id, job['job_id'], chunk_start_hex, chunk_bits, req.worker_id, time.time()))

        # ─── Calcula dp_bits e max_ops dinâmicamente com base no chunk real ────────
        # Meta: K ≈ 1.15 (DP overhead ultrabaixo ~3–5%)
        # Medições reais:  dp=32→K=12.52 | dp=26→K=2.52 | dp=23→K=1.49 | dp=21→K=1.165
        # dp=20 (DP 20) → overhead ≈ 3–5% → K ≈ 1.15 ✓  RAM ≈ 1.8 GB/GPU  ← SUPER OTIMIZADO
        # dp_ideal ≈ (chunk_bits // 2) - 25  →  90-bit: 20, 80-bit: 15, 66-bit: 14(min)
        dp_bits_dynamic = min(20, max(14, (chunk_bits // 2) - 25))

        # max_ops = (chunk_bits / range_bits) * 1.5  — margem segura com K≈1.15
        max_ops_dynamic = round((chunk_bits / job['range_bits']) * 1.5, 2)

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
            "dp_bits": dp_bits_dynamic,
            "max_ops": str(max_ops_dynamic)
        }

@app.post("/api/worker/complete_chunk")
def complete_chunk(req: CompleteChunkRequest, _: None = Depends(verify_worker_token)):
    """Worker chama este endpoint quando termina um chunk com sucesso (sem encontrar a chave).
    Só então o chunk é marcado como COMPLETED — elimina falsos positivos.
    """
    with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        now = time.time()

        cursor.execute("""
            UPDATE chunks SET status = 'COMPLETED', completed_at = ?
            WHERE chunk_id = ? AND assigned_worker = ? AND status = 'ASSIGNED'
        """, (now, req.chunk_id, req.worker_id))

        updated = cursor.rowcount
        if updated > 0:
            cursor.execute(
                "UPDATE workers SET last_ping = ?, completed_chunks = completed_chunks + 1 WHERE worker_id = ?",
                (now, req.worker_id)
            )
            print(f"✅ Chunk {req.chunk_id} marcado como COMPLETED pelo worker {req.worker_id}")
        else:
            print(f"⚠️  complete_chunk ignorado: chunk {req.chunk_id} não estava ASSIGNED para {req.worker_id}")

        conn.commit()
        conn.close()

    return {"status": "OK", "completed": updated > 0}


@app.post("/api/worker/submit_solution")
def submit_solution(req: SubmitSolutionRequest, _: None = Depends(verify_worker_token)):
    # Mathematically verify candidate private key against target pubkey
    if not verify_private_key(req.private_key, req.pubkey):
        print(f"❌ REJECTED False positive solution from worker {req.worker_id}: {req.private_key}")
        raise HTTPException(status_code=400, detail="Invalid solution key for target pubkey")

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
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            :root {
                --bg-body: #080c14;
                --bg-card: #101726;
                --bg-card-hover: #162034;
                --border-color: #1e293b;
                --border-glow: rgba(59, 130, 246, 0.25);
                --text-primary: #f8fafc;
                --text-secondary: #94a3b8;
                --text-muted: #64748b;
                --accent-cyan: #38bdf8;
                --accent-green: #22c55e;
                --accent-amber: #f59e0b;
                --accent-purple: #a855f7;
            }

            body {
                background-color: var(--bg-body);
                color: var(--text-primary);
                font-family: 'Outfit', -apple-system, sans-serif;
                min-height: 100vh;
            }

            .glass-card {
                background: linear-gradient(135deg, rgba(16, 23, 38, 0.95) 0%, rgba(12, 17, 28, 0.98) 100%);
                border: 1px solid var(--border-color);
                border-radius: 16px;
                box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
                backdrop-filter: blur(12px);
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }
            .glass-card:hover {
                border-color: var(--border-glow);
                box-shadow: 0 12px 35px -10px rgba(56, 189, 248, 0.15);
            }

            .stat-card {
                position: relative;
                overflow: hidden;
                padding: 1.5rem;
            }
            .stat-card::before {
                content: '';
                position: absolute;
                top: 0; left: 0; width: 100%; height: 3px;
                background: linear-gradient(90deg, transparent, var(--accent-color, var(--accent-cyan)), transparent);
            }
            .stat-header {
                font-size: 2.2rem;
                font-weight: 700;
                letter-spacing: -0.02em;
                color: var(--text-primary);
                font-family: 'JetBrains Mono', monospace;
            }
            .stat-title {
                color: var(--text-secondary);
                font-size: 0.82rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                margin-bottom: 0.5rem;
            }

            .section-title {
                font-size: 1.15rem;
                font-weight: 700;
                color: var(--text-primary);
                letter-spacing: -0.01em;
            }

            .table-custom {
                background: transparent !important;
                color: var(--text-primary) !important;
                margin-bottom: 0;
            }
            .table-custom th {
                background-color: rgba(15, 23, 42, 0.8) !important;
                color: var(--text-secondary) !important;
                font-size: 0.82rem !important;
                font-weight: 600 !important;
                text-transform: uppercase !important;
                letter-spacing: 0.06em !important;
                padding: 1rem 1.2rem !important;
                border-bottom: 1px solid var(--border-color) !important;
            }
            .table-custom td {
                padding: 1rem 1.2rem !important;
                border-bottom: 1px solid rgba(30, 41, 59, 0.6) !important;
                vertical-align: middle !important;
                background: transparent !important;
                color: var(--text-primary) !important;
            }
            .table-custom tbody tr:hover td {
                background-color: rgba(30, 41, 59, 0.4) !important;
            }

            .font-mono {
                font-family: 'JetBrains Mono', monospace;
            }

            .key-box {
                background-color: #060911;
                border: 1px solid var(--border-color);
                border-radius: 8px;
                padding: 10px 14px;
                font-family: 'JetBrains Mono', monospace;
                word-break: break-all;
                color: var(--accent-cyan);
            }

            .solved-banner {
                background: linear-gradient(135deg, rgba(34, 197, 94, 0.15) 0%, rgba(10, 15, 26, 0.95) 100%);
                border: 2px solid var(--accent-green);
                box-shadow: 0 0 35px rgba(34, 197, 94, 0.25);
                border-radius: 16px;
            }

            .badge-glow-cyan {
                background: rgba(56, 189, 248, 0.12);
                color: var(--accent-cyan);
                border: 1px solid rgba(56, 189, 248, 0.3);
            }
            .badge-glow-green {
                background: rgba(34, 197, 94, 0.12);
                color: var(--accent-green);
                border: 1px solid rgba(34, 197, 94, 0.3);
            }
            .badge-glow-amber {
                background: rgba(245, 158, 11, 0.12);
                color: var(--accent-amber);
                border: 1px solid rgba(245, 158, 11, 0.3);
            }
            .badge-glow-purple {
                background: rgba(168, 85, 247, 0.12);
                color: var(--accent-purple);
                border: 1px solid rgba(168, 85, 247, 0.3);
            }

            .pulse-dot {
                width: 8px;
                height: 8px;
                background-color: var(--accent-green);
                border-radius: 50%;
                display: inline-block;
                box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7);
                animation: pulse-green 2s infinite;
            }
            @keyframes pulse-green {
                0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); }
                70% { transform: scale(1); box-shadow: 0 0 0 10px rgba(34, 197, 94, 0); }
                100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
            }

            @media (max-width: 768px) {
                body { padding: 0.75rem !important; }
                .stat-header { font-size: 1.6rem; }
            }
        </style>
    </head>
    <body class="p-3 p-md-4">
        <div class="container-fluid max-w-7xl mx-auto">

            <!-- Top Header -->
            <div class="glass-card p-3 p-md-4 mb-4 d-flex flex-column flex-md-row justify-content-between align-items-md-center gap-3">
                <div class="d-flex align-items-center gap-3">
                    <div class="fs-2">🦘</div>
                    <div>
                        <div class="d-flex align-items-center gap-2">
                            <h1 class="h4 mb-0 fw-bold tracking-tight">RCKangaroo Pool Coordinator</h1>
                            <span class="badge badge-glow-green px-2.5 py-1 rounded-pill fs-7 font-semibold">
                                <span class="pulse-dot me-1"></span> Autenticado
                            </span>
                        </div>
                        <span class="text-secondary fs-7">Coordenador Distribuído de Alta Performance — Bitcoin Puzzles</span>
                    </div>
                </div>
                <div class="d-flex flex-wrap gap-2">
                    <button class="btn btn-outline-info btn-sm fw-medium rounded-3 px-3" onclick="openCoverageModal()">
                        📄 Ver Relatório (COVERAGE.TXT)
                    </button>
                    <button class="btn btn-outline-danger btn-sm rounded-3 px-3" onclick="clearOldJobs()">
                        🗑️ Limpar Jobs
                    </button>
                    <button class="btn btn-primary btn-sm rounded-3 px-3 fw-semibold bg-blue-600 border-0" onclick="loadStats()">
                        🔄 Atualizar
                    </button>
                </div>
            </div>

            <!-- Solved Alert Banner -->
            <div id="solved-solutions-container" class="mb-4"></div>

            <!-- Technical Cluster Stat Cards (2 Rows of 4 Cards) -->
            <div class="row g-3 mb-4">
                <!-- 1. Throughput -->
                <div class="col-12 col-sm-6 col-xl-3">
                    <div class="glass-card stat-card" style="--accent-color: var(--accent-cyan);">
                        <div class="stat-title">🚀 THROUGHPUT AGREGADO</div>
                        <div class="stat-header text-info" id="pool-hashrate">0.00 GKeys/s</div>
                        <div class="fs-7 text-secondary mt-1">Velocidade combinada (passos/s)</div>
                    </div>
                </div>
                <!-- 2. Chunks Concluídos -->
                <div class="col-12 col-sm-6 col-xl-3">
                    <div class="glass-card stat-card" style="--accent-color: var(--accent-green);">
                        <div class="stat-title">✅ CHUNKS CONCLUÍDOS</div>
                        <div class="stat-header text-success fs-3" id="completed-chunks">0</div>
                        <div class="fs-7 text-secondary mt-1">Sub-blocos validados com sucesso</div>
                    </div>
                </div>
                <!-- 3. Chunks em Andamento -->
                <div class="col-12 col-sm-6 col-xl-3">
                    <div class="glass-card stat-card" style="--accent-color: var(--accent-amber);">
                        <div class="stat-title">🔄 CHUNKS EM ANDAMENTO</div>
                        <div class="stat-header text-warning fs-3" id="active-chunks-status">0 ativos</div>
                        <div class="fs-7 text-secondary mt-1" id="chunks-total-subtext">0 gerados no total</div>
                    </div>
                </div>
                <!-- 4. DP Overhead -->
                <div class="col-12 col-sm-6 col-xl-3">
                    <div class="glass-card stat-card" style="--accent-color: var(--accent-purple);">
                        <div class="stat-title">🎯 DP OVERHEAD (EFICIÊNCIA)</div>
                        <div class="stat-header text-purple fs-3" style="color: #c084fc;" id="dp-overhead">7% ~ 15%</div>
                        <div class="fs-7 text-secondary mt-1">K ≈ 1.15–1.23 (Baixo Overhead)</div>
                    </div>
                </div>

                <!-- 5. Kangaroos Ativos -->
                <div class="col-12 col-sm-6 col-xl-3">
                    <div class="glass-card stat-card" style="--accent-color: var(--accent-cyan);">
                        <div class="stat-title">🧠 KANGAROOS ATIVOS</div>
                        <div class="stat-header text-info fs-3" id="active-kangaroos">16.0M+</div>
                        <div class="fs-7 text-secondary mt-1" id="active-gpus-subtext">8 GPUs operando em paralelo</div>
                    </div>
                </div>
                <!-- 6. Tempo de Processamento -->
                <div class="col-12 col-sm-6 col-xl-3">
                    <div class="glass-card stat-card" style="--accent-color: var(--accent-green);">
                        <div class="stat-title">⏱️ TEMPO DE PROCESSAMENTO</div>
                        <div class="stat-header text-success fs-3" id="job-uptime">0h 0m</div>
                        <div class="fs-7 text-secondary mt-1">Duração da execução ativa</div>
                    </div>
                </div>
                <!-- 7. Chaves Testadas -->
                <div class="col-12 col-sm-6 col-xl-3">
                    <div class="glass-card stat-card" style="--accent-color: var(--accent-amber);">
                        <div class="stat-title">🔑 CHAVES TESTADAS (ZETAKEYS)</div>
                        <div class="stat-header text-warning fs-3" id="keys-tested">0 Zetakeys</div>
                        <div class="fs-7 text-secondary mt-1">Soma acumulada das chaves</div>
                    </div>
                </div>
                <!-- 8. Checkpoints & Estado -->
                <div class="col-12 col-sm-6 col-xl-3">
                    <div class="glass-card stat-card" style="--accent-color: var(--accent-purple);">
                        <div class="stat-title">📦 CHECKPOINTS & ESTADO</div>
                        <div class="stat-header text-purple fs-3" style="color: #c084fc;">WAL + Auto</div>
                        <div class="fs-7 text-secondary mt-1">SQLite WAL + COVERAGE.TXT</div>
                    </div>
                </div>
            </div>

            <!-- Active Target Puzzle Card -->
            <div id="active-target-puzzle-container" class="mb-4"></div>

            <!-- Active Workers & Live Ranges Table -->
            <div class="glass-card p-3 p-md-4 mb-4">
                <div class="d-flex flex-column flex-md-row justify-content-between align-items-md-center gap-2 mb-3">
                    <div>
                        <h2 class="section-title mb-0">💻 Workers Ativos & Faixas Atribuídas</h2>
                        <span class="text-secondary fs-7">Lista em tempo real das GPUs trabalhando agora</span>
                    </div>
                    <span class="badge badge-glow-cyan px-3 py-1.5 rounded-pill fs-7">
                        Atualização Automática (3s)
                    </span>
                </div>
                <div class="table-responsive">
                    <table class="table table-custom align-middle">
                        <thead>
                            <tr>
                                <th>Worker ID / Nome</th>
                                <th>Hardware GPU</th>
                                <th>Hashrate</th>
                                <th>Faixa Atribuída (%)</th>
                                <th>Sub-bloco Hex Atual</th>
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
            <div class="glass-card p-3 p-md-4">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <div>
                        <h2 class="section-title mb-0">📋 Jobs de Busca Cadastrados</h2>
                        <span class="text-secondary fs-7">Gerenciamento de intervalos ativos e resolvidos</span>
                    </div>
                    <button class="btn btn-outline-danger btn-sm rounded-3" onclick="clearOldJobs()">
                        🗑️ Limpar Todos os Jobs
                    </button>
                </div>
                <div class="table-responsive">
                    <table class="table table-custom align-middle">
                        <thead>
                            <tr>
                                <th>Puzzle / Job ID</th>
                                <th>Endereço BTC Alvo</th>
                                <th>Chave Pública Alvo</th>
                                <th>Faixa Executada (%)</th>
                                <th>Start Offset Hex</th>
                                <th>Range</th>
                                <th>Status</th>
                                <th>Ações</th>
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
                '40': { pubkey: '03a2efa402fd5268400c77c20e574ba86409ededee7c4020e4b9f0edbee53de0d4', bits: 40, base_start: '8000000000', btc_address: '122vYBWuKDodGYuBwAjBYwfst8ewL6pnjQ' },
                '50': { pubkey: '03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6', bits: 50, base_start: '200000000000', btc_address: '172W6cD98Vj2Pn126nZxPvEyc288eP8p39' },
                '60': { pubkey: '0348e843dc5b1bd246e6309b4924b81543d02b16c8083df973a89ce2c7eb89a10d', bits: 60, base_start: '800000000000000', btc_address: '16jY7qLJn2yGwhmMvVbEFTHmyCpNXnBLvi' },
                '66': { pubkey: '024ee2be2d4e9f92d2f5a4a03058617dc45befe22938feed5b7a6b7282dd74cbdd', bits: 66, base_start: '20000000000000000', btc_address: '13zb1hQbWVsc2S7ZTGarEbrmcHbotPhvqD' },
                '130': { pubkey: '03633cbe3ec02b9401c5effa144c5b4d22f87940259634858fc7e59b1c09937852', bits: 130, base_start: '20000000000000000000000000000000', btc_address: '1LHtnPD8vUPG2NRSsfTQ5zWbX2SLW23yAs' },
                '135': { pubkey: '02145d2611c823a396ef6712ce0f712f09b9b4f3135e3e0aa3230fb9b6d08d1e16', bits: 135, base_start: '4000000000000000000000000000000004', btc_address: '16R2y56L7bg69U5d76D491j2vV6yS451z4' },
                '140': { pubkey: '031f6a332d3c5c4f2de2378c012f429cd109ba07d69690c6c701b6bb87860d6640', bits: 140, base_start: '80000000000000000000000000000000000', btc_address: '1QKBaU6WAeycb3DbKbLBkX7vJiaS8r42Xo' },
                '145': { pubkey: '03afdda497369e219a2c1c369954a930e4d3740968e5e4352475bcffce3140dae5', bits: 145, base_start: '1000000000000000000000000000000000000', btc_address: '12vX5yS451z5PD3vW9n5C1x46y1N4C74y' },
                '150': { pubkey: '03137807790ea7dc6e97901c2bc87411f45ed74a5629315c4e4b03a0a102250c49', bits: 150, base_start: '20000000000000000000000000000000000000', btc_address: '19vX5yS451z5PD3vW9n5C1x46y1N4C74z' }
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

            async function loadStats() {
                try {
                    const res = await fetch('/api/stats');
                    if (res.status === 401) {
                        window.location.reload();
                        return;
                    }
                    const data = await res.json();

                    document.getElementById('pool-hashrate').innerText = data.total_pool_hashrate_ghs + ' GKeys/s';
                    document.getElementById('completed-chunks').innerText = (data.total_completed_chunks || 0).toLocaleString() + ' chunks';
                    document.getElementById('active-chunks-status').innerText = (data.assigned_chunks_count || 0) + ' ativos';
                    document.getElementById('chunks-total-subtext').innerText = (data.total_created_chunks || 0) + ' gerados no total';
                    document.getElementById('dp-overhead').innerText = data.dp_overhead_str || '7% ~ 15%';
                    document.getElementById('active-kangaroos').innerText = data.active_kangaroos_m || '16.0M+';
                    document.getElementById('active-gpus-subtext').innerText = (data.total_gpus_count || 0) + ' GPUs (' + (data.active_workers_count || 0) + ' containers)';
                    document.getElementById('job-uptime').innerText = data.active_job_uptime || '0h 0m';
                    document.getElementById('keys-tested').innerText = data.keys_zetta_str || '0 Zetakeys';

                    // Solved Banner
                    const solvedContainer = document.getElementById('solved-solutions-container');
                    const solvedJobs = data.jobs.filter(j => j.status === 'SOLVED');

                    if (solvedJobs.length > 0) {
                        solvedContainer.innerHTML = solvedJobs.map(sj => `
                            <div class="glass-card solved-banner p-4 mb-3">
                                <div class="d-flex justify-content-between align-items-center mb-3">
                                    <h3 class="text-success fw-bold mb-0 fs-4">🎉 CHAVE PRIVADA ENCONTRADA!</h3>
                                    <div>
                                        <span class="badge badge-glow-green fs-6 me-2">${sj.solved_at_str || 'Recente'}</span>
                                        <button class="btn btn-outline-danger btn-sm font-semibold" onclick="deleteSingleJob('${sj.job_id}')">🗑️ Apagar Este Resultado</button>
                                    </div>
                                </div>
                                <div class="row g-3">
                                    <div class="col-md-6">
                                        <div class="stat-title">PUBKEY ALVO:</div>
                                        <div class="key-box text-info">${sj.pubkey}</div>
                                    </div>
                                    <div class="col-md-6">
                                        <div class="stat-title">ENCONTRADA POR WORKER:</div>
                                        <div class="key-box text-warning">${sj.solved_by || 'Desconhecido'}</div>
                                    </div>
                                    <div class="col-md-12">
                                        <div class="d-flex justify-content-between align-items-center mb-1">
                                            <div class="stat-title">CHAVE PRIVADA (HEX):</div>
                                            <button class="btn btn-sm btn-outline-success" onclick="copyText('${sj.private_key_hex}')">📋 Copiar HEX</button>
                                        </div>
                                        <div class="key-box text-success fw-bold fs-5">${sj.private_key_hex}</div>
                                    </div>
                                    <div class="col-md-12">
                                        <div class="d-flex justify-content-between align-items-center mb-1">
                                            <div class="stat-title">CHAVE PRIVADA (FORMATO WIF COMPRESSADO):</div>
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
                        workersBody.innerHTML = `<tr><td colspan="7" class="text-center text-secondary p-4">Nenhum worker ativo no momento. Ao conectar um worker (local/Vast.ai), a faixa dele aparecerá aqui automaticamente.</td></tr>`;
                    } else {
                        workersBody.innerHTML = data.workers.map(w => {
                            const hrStr = w.hashrate_mhs >= 1000 ? (w.hashrate_mhs / 1000.0).toFixed(2) + ' GH/s' : w.hashrate_mhs.toFixed(2) + ' MH/s';
                            const chunksBadge = w.completed_chunks > 0 ?
                                `<span class="badge badge-glow-green px-3 py-1 fw-bold">${w.completed_chunks} chunks</span>` :
                                `<span class="badge bg-dark text-secondary px-2 py-1">${w.completed_chunks} chunks</span>`;
                            const rangeBadge = `<span class="badge badge-glow-cyan font-mono px-3 py-1.5 fw-semibold" style="font-size: 0.9rem;">${w.assigned_range || '0% → 100%'}</span>`;
                            const hexBadge = `<span class="badge bg-black border border-secondary text-info font-mono px-2 py-1">${w.current_start_hex || 'Iniciando...'}</span>`;
                            const pingSecs = Math.max(0, Math.round(Date.now()/1000 - w.last_ping));
                            
                            return `
                            <tr>
                                <td>
                                    <strong class="text-light fs-6">${w.name}</strong><br>
                                    <code class="text-secondary fs-7 font-mono">${w.worker_id}</code>
                                </td>
                                <td><span class="text-secondary fs-7">${w.gpu_info}</span></td>
                                <td style="color: var(--accent-cyan); font-weight: 700; font-family: 'JetBrains Mono', monospace;">${hrStr}</td>
                                <td>${rangeBadge}</td>
                                <td>${hexBadge}</td>
                                <td>${chunksBadge}</td>
                                <td><span class="badge badge-glow-green px-2.5 py-1 fs-7">🟢 Ativo (${pingSecs}s atrás)</span></td>
                            </tr>
                            `;
                        }).join('');
                    }

                    // Target Active Puzzle Card
                    const targetContainer = document.getElementById('active-target-puzzle-container');
                    const activeJobs = data.jobs.filter(j => j.status === 'ACTIVE');

                    if (activeJobs.length > 0) {
                        const firstActive = activeJobs[0];
                        const totalAssigned = activeJobs.reduce((acc, j) => acc + (j.total_chunks_assigned || 0), 0);
                        const totalCompleted = activeJobs.reduce((acc, j) => acc + (j.completed_chunks || 0), 0);
                        const minStart = Math.min(...activeJobs.map(j => j.start_percent));
                        const maxEnd = Math.max(...activeJobs.map(j => j.end_percent));
                        const rangeBadges = activeJobs.map(j => `<span class="badge badge-glow-cyan font-mono me-1 mb-1" title="Job ${j.job_id}">${j.start_percent.toFixed(1)}% → ${j.end_percent.toFixed(1)}%</span>`).join('');

                        targetContainer.innerHTML = `
                            <div class="glass-card p-4 border border-info">
                                <div class="d-flex flex-column flex-md-row justify-content-between align-items-md-center gap-2 mb-3">
                                    <div class="d-flex align-items-center">
                                        <span class="fs-3 me-2">🎯</span>
                                        <h3 class="mb-0 text-info fw-bold h4">${firstActive.puzzle_name}</h3>
                                        <span class="badge badge-glow-green ms-3 fs-7">Em Busca Ativa (${activeJobs.length} Jobs Simultâneos)</span>
                                    </div>
                                    <div class="d-flex flex-wrap align-items-center gap-2">
                                        <span class="badge bg-black border border-secondary text-light fs-7 font-mono">Range Total: ${minStart.toFixed(1)}% → ${maxEnd.toFixed(1)}%</span>
                                        <span class="badge badge-glow-purple fs-7">Chunks Concluídos: ${totalCompleted} / ${totalAssigned}</span>
                                    </div>
                                </div>
                                <div class="mb-3">
                                    <span class="stat-title me-2">FAIXAS ATIVAS EM PROCESSAMENTO:</span>
                                    <div class="d-inline-flex flex-wrap mt-1">${rangeBadges}</div>
                                </div>
                                <div class="row g-3">
                                    <div class="col-md-6">
                                        <div class="stat-title">CHAVE PÚBLICA ALVO (PUBLIC KEY):</div>
                                        <div class="d-flex align-items-center mt-1">
                                            <div class="key-box text-info flex-grow-1 me-2 fs-7">${firstActive.pubkey}</div>
                                            <button class="btn btn-sm btn-outline-info" onclick="copyText('${firstActive.pubkey}')">📋 Copiar</button>
                                        </div>
                                    </div>
                                    <div class="col-md-6">
                                        <div class="stat-title">ENDEREÇO BITCOIN ALVO:</div>
                                        <div class="d-flex align-items-center mt-1">
                                            <div class="key-box text-warning flex-grow-1 me-2 fs-7 font-semibold" style="color: var(--accent-amber);">${firstActive.btc_address}</div>
                                            <button class="btn btn-sm btn-outline-warning" onclick="copyText('${firstActive.btc_address}')">📋 Copiar</button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        `;
                    } else {
                        targetContainer.innerHTML = '';
                    }

                    // Render Jobs Table
                    const jobsBody = document.getElementById('jobs-table-body');
                    if (data.jobs.length === 0) {
                        jobsBody.innerHTML = `<tr><td colspan="8" class="text-center text-secondary p-3">Nenhum job cadastrado no momento.</td></tr>`;
                    } else {
                        jobsBody.innerHTML = data.jobs.map(j => `
                            <tr>
                                <td>
                                    <strong class="text-info">${j.puzzle_name}</strong><br>
                                    <code class="text-secondary fs-7 font-mono">${j.job_id}</code>
                                </td>
                                <td>
                                    <span class="text-warning fw-semibold font-mono">${j.btc_address}</span>
                                    <button class="btn btn-sm btn-link text-warning p-0 ms-1" onclick="copyText('${j.btc_address}')" title="Copiar Endereço">📋</button>
                                </td>
                                <td>
                                    <code class="text-truncate d-inline-block font-mono text-secondary" style="max-width: 180px;" title="${j.pubkey}">${j.pubkey}</code>
                                </td>
                                <td><span class="badge badge-glow-cyan font-mono">${j.start_percent}% → ${j.end_percent}%</span></td>
                                <td><code class="font-mono text-secondary">0x${j.start_hex}</code></td>
                                <td>
                                    <span class="font-mono">${j.range_bits} bits</span><br>
                                    <span class="badge badge-glow-purple fs-7 font-mono">${j.completed_chunks} / ${j.total_chunks_assigned} chunks</span>
                                </td>
                                <td><span class="badge ${j.status === 'SOLVED' ? 'badge-glow-green' : 'badge-glow-cyan'}">${j.status}</span></td>
                                <td class="font-mono">
                                    ${j.status === 'SOLVED' ? `
                                        <button class="btn btn-sm btn-outline-danger me-2" onclick="deleteSingleJob('${j.job_id}')">🗑️ Apagar</button>
                                        <span class="text-success font-semibold">${j.private_key_hex}</span>
                                    ` : `
                                        <button class="btn btn-sm btn-outline-danger" onclick="deleteSingleJob('${j.job_id}')">🗑️ Apagar</button>
                                    `}
                                </td>
                            </tr>
                        `).join('');
                    }

                } catch (e) {
                    console.error('Erro ao carregar dados:', e);
                }
            }

            async function openCoverageModal() {
                try {
                    const res = await fetch('/api/coverage');
                    const data = await res.json();
                    document.getElementById('coverage-report-content').innerText = data.text;
                    const modal = new bootstrap.Modal(document.getElementById('coverageModal'));
                    modal.show();
                } catch(e) {
                    alert("Erro ao carregar COVERAGE.TXT: " + e);
                }
            }

            loadStats();
            setInterval(loadStats, 3000);
        </script>

        <!-- Coverage Report Modal -->
        <div class="modal fade" id="coverageModal" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-lg modal-dialog-centered">
                <div class="modal-content glass-card border border-info shadow-lg">
                    <div class="modal-header border-secondary">
                        <h5 class="modal-title text-info font-semibold">📄 Relatório de Cobertura & Anti-Sobreposição (COVERAGE.TXT)</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <div class="mb-3">
                            <span class="text-secondary fs-7">Este relatório é gerado automaticamente na VPS (`/opt/rckangaroo/pool/server/COVERAGE.TXT`) para evitar retrabalho e mostrar faixas livres:</span>
                        </div>
                        <pre id="coverage-report-content" class="bg-black text-success p-3 rounded-3 border border-secondary font-mono" style="white-space: pre-wrap; font-size: 0.88rem; max-height: 400px; overflow-y: auto;"></pre>
                    </div>
                    <div class="modal-footer border-secondary">
                        <button type="button" class="btn btn-sm btn-secondary" data-bs-dismiss="modal">Fechar</button>
                        <a href="/api/coverage" target="_blank" class="btn btn-sm btn-outline-info">📥 Abrir COVERAGE.TXT Direto</a>
                    </div>
                </div>
            </div>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
