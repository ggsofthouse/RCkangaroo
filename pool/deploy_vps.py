import paramiko
import os
import sys
import time

def read_env():
    env_vars = {}
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env_vars[k] = v
    return env_vars

def exec_cmd(ssh, cmd, ignore_error=False):
    print(f"--> [VPS] {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    if out:
        safe_out = out.encode('ascii', errors='backslashreplace').decode('ascii')
        print(f"    [OUT] {safe_out}")
    if err and not ignore_error:
        safe_err = err.encode('ascii', errors='backslashreplace').decode('ascii')
        print(f"    [ERR] {safe_err}")
    return out, err


def upload_folder(sftp, local_dir, remote_dir):
    print(f"Uploading {local_dir} -> {remote_dir}...")
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass  # Directory already exists

    for root, dirs, files in os.walk(local_dir):
        rel_path = os.path.relpath(root, local_dir)
        target_dir = remote_dir if rel_path == "." else os.path.join(remote_dir, rel_path).replace("\\", "/")
        
        try:
            sftp.mkdir(target_dir)
        except IOError:
            pass

        for file in files:
            if file in [".env", "pool.db", "POOL_RESULTS.TXT", "__pycache__"] or file.endswith(".pyc"):
                continue
            local_file = os.path.join(root, file)
            remote_file = os.path.join(target_dir, file).replace("\\", "/")
            print(f"  --> Uploading {file}")
            sftp.put(local_file, remote_file)

def main():
    env_vars = read_env()
    host = env_vars.get("VPS_HOST", "179.197.231.166")
    user = env_vars.get("VPS_USER", "root")
    password = env_vars.get("VPS_PASS")

    if not password:
        print("Error: VPS_PASS not found in .env file.")
        sys.exit(1)

    print("==================================================")
    print(f"[+] Initializing RCKangaroo Pool Deployment to VPS")
    print(f"    Target Host: {user}@{host}")
    print(f"    Domain: valyrafi.com.br")
    print("==================================================")


    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=15)
    sftp = ssh.open_sftp()

    # Step 1: Stop and disable old cyclone-master service
    print("\n--- Step 1: Removing Old CUDA Project (cyclone-master) ---")
    exec_cmd(ssh, "systemctl stop cyclone-master", ignore_error=True)
    exec_cmd(ssh, "systemctl disable cyclone-master", ignore_error=True)
    exec_cmd(ssh, "rm -f /etc/systemd/system/cyclone-master.service", ignore_error=True)
    exec_cmd(ssh, "systemctl daemon-reload")
    exec_cmd(ssh, "rm -rf /opt/cyclone-master", ignore_error=True)
    print("[+] Old CUDA project stopped and cleaned.")


    # Step 2: Upload pool server files to /opt/rckangaroo/pool/server
    print("\n--- Step 2: Deploying RCKangaroo Pool Server Files ---")
    exec_cmd(ssh, "mkdir -p /opt/rckangaroo/pool/server")
    local_server_dir = os.path.join(os.path.dirname(__file__), "server")
    upload_folder(sftp, local_server_dir, "/opt/rckangaroo/pool/server")

    # Step 3: Setup Virtualenv & Dependencies
    print("\n--- Step 3: Setting Up Python Virtual Environment & Dependencies ---")
    exec_cmd(ssh, "python3 -m venv /opt/rckangaroo/pool/server/venv")
    exec_cmd(ssh, "/opt/rckangaroo/pool/server/venv/bin/pip install --upgrade pip")
    exec_cmd(ssh, "/opt/rckangaroo/pool/server/venv/bin/pip install -r /opt/rckangaroo/pool/server/requirements.txt")
    exec_cmd(ssh, "/opt/rckangaroo/pool/server/venv/bin/pip install uvicorn")

    # Step 4: Create Systemd Service
    print("\n--- Step 4: Configuring Systemd Service (rckangaroo-pool.service) ---")
    service_content = """[Unit]
Description=RCKangaroo Mining Pool Coordinator Server
After=network.target

[Service]
User=root
WorkingDirectory=/opt/rckangaroo/pool/server
ExecStart=/opt/rckangaroo/pool/server/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
    with sftp.open("/etc/systemd/system/rckangaroo-pool.service", "w") as f:
        f.write(service_content)

    exec_cmd(ssh, "systemctl daemon-reload")
    exec_cmd(ssh, "systemctl enable --now rckangaroo-pool")
    time.sleep(2)
    exec_cmd(ssh, "systemctl status rckangaroo-pool --no-pager")

    # Step 5: Configure Nginx & SSL Certificate
    print("\n--- Step 5: Configuring Nginx & Certbot SSL for valyrafi.com.br ---")
    nginx_config = """server {
    listen 80;
    server_name valyrafi.com.br www.valyrafi.com.br;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
"""
    with sftp.open("/etc/nginx/sites-available/valyrafi", "w") as f:
        f.write(nginx_config)

    exec_cmd(ssh, "ln -sf /etc/nginx/sites-available/valyrafi /etc/nginx/sites-enabled/valyrafi")
    exec_cmd(ssh, "nginx -t")
    exec_cmd(ssh, "systemctl reload nginx")

    # Run certbot for SSL
    print("Issuing/updating SSL Certificate via Certbot...")
    exec_cmd(ssh, "certbot --nginx -d valyrafi.com.br -d www.valyrafi.com.br --non-interactive --agree-tos --register-unsafely-without-email --redirect", ignore_error=True)

    # Step 6: Final Verification
    print("\n--- Step 6: Verifying Deployment & Services ---")
    exec_cmd(ssh, "curl -s http://127.0.0.1:8000/api/stats | head -c 200")
    exec_cmd(ssh, "systemctl is-active rckangaroo-pool")
    exec_cmd(ssh, "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'")

    sftp.close()
    ssh.close()
    print("\n[SUCCESS] DEPLOYMENT COMPLETE!")
    print("Dashboard available at: https://valyrafi.com.br")


if __name__ == "__main__":
    main()
