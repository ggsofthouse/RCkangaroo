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

remote_script = '''import sqlite3, os
conn = sqlite3.connect('/opt/rckangaroo/pool/server/pool.db')
c = conn.cursor()
tables = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("=== TABELAS SQLITE DO POOL ===")
for t in tables:
    cnt = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  • {t}: {cnt} registros")

print("\\n=== CHUNKS COMPLETED / SOLVED / CANCELLED ===")
for st in ['COMPLETED', 'SOLVED', 'ASSIGNED', 'PENDING', 'CANCELLED']:
    cnt = c.execute(f"SELECT COUNT(*) FROM chunks WHERE status='{st}'").fetchone()[0]
    print(f"  • Status {st}: {cnt} chunks")

print("\\n=== ARQUIVOS EM /opt/rckangaroo/pool/server ===")
for f in os.listdir('/opt/rckangaroo/pool/server'):
    sz = os.path.getsize(os.path.join('/opt/rckangaroo/pool/server', f))
    print(f"  • {f} ({sz} bytes)")
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
