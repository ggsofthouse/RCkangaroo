import os
import sys
import time
import subprocess

sys.stdout.reconfigure(encoding='utf-8')

def main():
    pubkey = "0290e6900a58d33393bc1097b5aed31f2e4e7cbd3e5466af958665bc0121248483"
    base_start = "200000000000000000"
    dp_bits = 18
    range_bits = 69
    max_ops = 1.62

    print("==================================================")
    print("🦘 RCKangaroo — TESTE LOCAL DIRETO (PUZZLE #70)")
    print("==================================================")

    root_dir = os.path.dirname(os.path.abspath(__file__))
    if sys.platform == "win32":
        candidates = [
            os.path.join(root_dir, "x64", "Release", "RCKangaroo.exe"),
            os.path.join(root_dir, "RCKangaroo.exe")
        ]
    else:
        candidates = [
            os.path.join(root_dir, "rckangaroo"),
            os.path.join(root_dir, "RCKangaroo")
        ]
    bin_path = next((p for p in candidates if os.path.isfile(p)), None)

    if not bin_path:
        print(f"❌ Binário RCKangaroo não encontrado na pasta: {root_dir}")
        sys.exit(1)

    cmd = [
        bin_path,
        "-gpu", "0",
        "-dp", str(dp_bits),
        "-range", str(range_bits),
        "-start", base_start,
        "-pubkey", pubkey,
        "-max", str(max_ops)
    ]

    print(f"⚙️ Executando busca na GPU:\n   {' '.join(cmd)}\n")
    t0 = time.time()
    subprocess.run(cmd, cwd=os.path.dirname(bin_path))
    print(f"\n✅ Teste concluído em {time.time()-t0:.1f} segundos.")

if __name__ == "__main__":
    main()
