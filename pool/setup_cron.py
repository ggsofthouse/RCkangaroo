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

stdin, stdout, stderr = ssh.exec_command('chmod +x /opt/rckangaroo/pool/server/backup_pool.sh && /opt/rckangaroo/pool/server/backup_pool.sh && (crontab -l 2>/dev/null | grep -v backup_pool.sh; echo "*/30 * * * * /opt/rckangaroo/pool/server/backup_pool.sh >> /var/log/pool_backup.log 2>&1") | crontab - && crontab -l')
print(stdout.read().decode('utf-8', errors='replace'))
ssh.close()
