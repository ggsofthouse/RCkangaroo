import os
import sys
import time
import subprocess

sys.stdout.reconfigure(encoding='utf-8')

def main():
    pubkey = "035c38bd9ae4b10e8a250857006f3cfd98ab15a6196d9f4dfd25bc7ecc77d788d5"
    base_start = "20000000000000000000000"
    dp_bits = 22
    range_bits = 89
    max_ops = 1.62

    print("==================================================")
    print("🦘 RCKangaroo — TESTE LOCAL DIRETO (PUZZLE #90)")
    print("==================================================")

    root_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(root_dir, "rckangaroo"),
        os.path.join(root_dir, "RCKangaroo"),
        os.path.join(root_dir, "RCKangaroo.exe"),
        os.path.join(root_dir, "x64", "Release", "RCKangaroo.exe"),
    ]
    bin_path = next((p for p in candidates if os.path.exists(p)), None)

    if not bin_path:
        print(f"❌ Binário rckangaroo não encontrado na pasta: {root_dir}")
        print("   No Linux, compile com: nvcc -O3 -std=c++17 -o rckangaroo RCKangaroo.cpp GpuKang.cpp Ec.cpp utils.cpp CallCubin.cpp RCGpuCore.cu -lcuda -lcudart -lpthread")
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
