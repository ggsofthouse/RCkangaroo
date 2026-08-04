import os
import sys
import time
import subprocess
import paramiko

sys.stdout.reconfigure(encoding='utf-8')

def read_env():
    env_vars = {}
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env_vars[k] = v
    return env_vars

def main():
    env_vars = read_env()
    host = env_vars.get("VPS_HOST", "179.197.231.166")
    user = env_vars.get("VPS_USER", "root")
    password = env_vars.get("VPS_PASS", "")

    puzzle_num = 140
    range_bits = 90
    dp_bits = 32
    max_ops = 8.0
    tames_filename = f"tames{puzzle_num}.dat"

    pubkey = "031f6a332d3c5c4f2de2378c012f429cd109ba07d69690c6c701b6bb87860d6640"
    base_start = "80000000000000000000000000000000000"

    print("==================================================")
    print(f"🦘 RCKangaroo Tames Generator — Puzzle #{puzzle_num}")
    print("==================================================")

    # Binário RCKangaroo
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    bin_path = os.path.join(root_dir, "x64", "Release", "RCKangaroo.exe")
    if not os.path.exists(bin_path):
        bin_path = os.path.join(root_dir, "rckangaroo")

    if not os.path.exists(bin_path):
        print(f"❌ Binário RCKangaroo não encontrado em: {bin_path}")
        sys.exit(1)

    output_tames_path = os.path.join(os.path.dirname(bin_path), tames_filename)
    if os.path.exists(output_tames_path):
        print(f"⚠️ O arquivo {tames_filename} já existe localmente ({os.path.getsize(output_tames_path)/(1024*1024):.2f} MB).")
        res = input("Deseja regerar do zero? (s/N): ").strip().lower()
        if res != 's':
            print("🚀 Pulando geração local, avançando direto para upload...")
        else:
            os.remove(output_tames_path)

    if not os.path.exists(output_tames_path):
        cmd = [
            bin_path,
            "-gpu", "0",
            "-dp", str(dp_bits),
            "-range", str(range_bits),
            "-start", base_start,
            "-pubkey", pubkey,
            "-max", str(max_ops),
            "-tames", tames_filename
        ]
        print(f"⚙️ Gerando tames com o comando:\n   {' '.join(cmd)}\n")
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=os.path.dirname(bin_path))
        if proc.returncode != 0:
            print("❌ Falha ao gerar tames.")
            sys.exit(1)
        print(f"✅ Tames gerados em {time.time()-t0:.1f}s: {output_tames_path}")

    if not password:
        print("❌ VPS_PASS não encontrado no .env, não foi possível enviar à VPS.")
        sys.exit(1)

    print(f"\n📡 Enviando {tames_filename} para a VPS ({user}@{host})...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=20)
    sftp = ssh.open_sftp()

    remote_dir = "/opt/rckangaroo/pool/server/tames"
    try:
        sftp.mkdir(remote_dir)
    except Exception:
        pass

    remote_file = f"{remote_dir}/{tames_filename}"
    print(f"--> Uploading: {output_tames_path} -> {remote_file}")
    sftp.put(output_tames_path, remote_file)
    sftp.close()
    ssh.close()

    print(f"\n🎉 SUCESSO! Arquivo {tames_filename} publicado no servidor VPS.")
    print(f"   A partir de agora, todos os workers que conectarem para o Puzzle #{puzzle_num}")
    print(f"   baixarão este arquivo automaticamente e rodarão com -tames ativado!\n")

if __name__ == "__main__":
    main()
