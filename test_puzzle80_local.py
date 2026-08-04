import os
import sys
import time
import subprocess

sys.stdout.reconfigure(encoding='utf-8')

def main():
    pubkey = "037e1238f7b1ce757df94faa9a2eb261bf0aeb9f84dbf81212104e78931c2a19dc"
    base_start = "80000000000000000000"
    dp_bits = 20
    range_bits = 79
    max_ops = 1.62

    print("==================================================")
    print("🦘 RCKangaroo — TESTE LOCAL DIRETO (PUZZLE #80)")
    print("==================================================")

    root_dir = os.path.dirname(__file__)
    bin_path = os.path.join(root_dir, "x64", "Release", "RCKangaroo.exe")
    if not os.path.exists(bin_path):
        bin_path = os.path.join(root_dir, "RCKangaroo.exe")

    if not os.path.exists(bin_path):
        print(f"❌ Binário não encontrado em: {bin_path}")
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
