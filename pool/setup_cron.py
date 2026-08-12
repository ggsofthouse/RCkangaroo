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

sftp = ssh.open_sftp()
sftp.put(os.path.join(os.path.dirname(__file__), "server", "backup_pool.sh"), "/opt/rckangaroo/pool/server/backup_pool.sh")
sftp.close()

remote_cmd = """chmod +x /opt/rckangaroo/pool/server/backup_pool.sh
/opt/rckangaroo/pool/server/backup_pool.sh
(crontab -l 2>/dev/null | grep -v backup_pool.sh; echo "*/30 * * * * /opt/rckangaroo/pool/server/backup_pool.sh >> /var/log/pool_backup.log 2>&1") | crontab -
print("=== CRONTAB ATUAL ===")
crontab -l
"""

command = r'''chmod +x /opt/rckangaroo/pool/server/backup_pool.sh && \
/opt/rckangaroo/pool/server/backup_pool.sh && \
python3 -c "import sqlite3; c=sqlite3.connect('/opt/rckangaroo/pool/server/backups/pool_latest.db'); print(c.execute('PRAGMA integrity_check').fetchone()[0])" | grep -qx ok && \
(crontab -l 2>/dev/null | grep -v backup_pool.sh; echo "*/30 * * * * /opt/rckangaroo/pool/server/backup_pool.sh >> /var/log/pool_backup.log 2>&1") | crontab - && \
crontab -l && df -h / && du -sh /opt/rckangaroo/pool/server/backups'''
if "--cleanup-old" in sys.argv:
    command += r''' && \
find /opt/rckangaroo/pool/server/backups -maxdepth 1 -type f \( -name 'pool_*.db' -o -name 'pool_*.db-wal' \) ! -name 'pool_latest.db' -delete && \
find /opt/rckangaroo/backups -mindepth 2 -maxdepth 2 -type f -path '*/deploy_*/pool.db' -delete && \
python3 -c "import sqlite3; c=sqlite3.connect('/opt/rckangaroo/pool/server/backups/pool_latest.db'); print(c.execute('PRAGMA integrity_check').fetchone()[0])" | grep -qx ok && \
echo '--- APOS LIMPEZA ---' && df -h / && du -sh /opt/rckangaroo/pool/server/backups /opt/rckangaroo/backups && \
find /opt/rckangaroo/pool/server/backups -maxdepth 1 -type f -printf '%f %s bytes\n' | sort'''
stdin, stdout, stderr = ssh.exec_command(command)
print(stdout.read().decode('utf-8', errors='replace'))
errors = stderr.read().decode('utf-8', errors='replace')
if errors:
    print(errors)
ssh.close()
