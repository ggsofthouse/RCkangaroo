import paramiko
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

env = {}
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v

host = env.get("VPS_HOST", "179.197.231.166")
user = env.get("VPS_USER", "root")
password = env.get("VPS_PASS", "")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host, username=user, password=password)

remote_script = '''import os, glob, subprocess

print("=== 1. BUSCANDO ARQUIVOS DE BACKUP E .DB EM TODO O DISCO DA VPS ===")
found_files = []
for root, dirs, files in os.walk('/'):
    if any(skip in root for skip in ['/proc', '/sys', '/dev', '/run', '/var/lib/docker/overlay2']):
        continue
    for f in files:
        if any(ext in f.lower() for ext in ['pool', '.db', '.bak', '.sqlite', 'coverage', 'results']):
            full_path = os.path.join(root, f)
            try:
                sz = os.path.getsize(full_path)
                found_files.append((full_path, sz))
            except Exception:
                pass

for path, sz in found_files:
    print(f"  • {path} ({sz} bytes)")

print("\\n=== 2. ANALISANDO STRINGS E RECURSOS NO POOL.DB E POOL.DB-WAL ===")
wal_path = '/opt/rckangaroo/pool/server/pool.db-wal'
db_path = '/opt/rckangaroo/pool/server/pool.db'

for p in [db_path, wal_path]:
    if os.path.exists(p):
        try:
            res = subprocess.run(["strings", p], capture_output=True, text=True, errors="replace")
            lines = [l for l in res.stdout.splitlines() if "chunk_" in l or "job_" in l or "0x" in l]
            print(f"  • {p}: {len(lines)} registros de chunk/job/hex encontrados nas strings brutas")
            if lines:
                print("    Amostra dos 15 primeiros:")
                for l in lines[:15]:
                    print("     ", l)
        except Exception as e:
            print(f"  • Erro ao analisar {p}: {e}")
'''

sftp = ssh.open_sftp()
with sftp.open('/opt/rckangaroo/pool/server/audit_tmp.py', 'w') as f:
    f.write(remote_script)
sftp.close()

stdin, stdout, stderr = ssh.exec_command('python3 /opt/rckangaroo/pool/server/audit_tmp.py')
out = stdout.read().decode('utf-8', errors='replace')
err = stderr.read().decode('utf-8', errors='replace')
print("STDOUT:", out)
if err:
    print("STDERR:", err)
ssh.close()
