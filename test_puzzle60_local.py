import os
import sys
import time
import subprocess

sys.stdout.reconfigure(encoding='utf-8')

def main():
    puzzle_num = 60
    pubkey = "0348e843dc5b1bd246e6309b4924b81543d02b16c8083df973a89ce2c7eb89a10d"
    base_start = "800000000000000"  # 2^59 em Hex
    dp_bits = 14
    range_bits = 59

    print("==================================================")
    print(f"🦘 RCKangaroo — TESTE LOCAL DIRETO (PUZZLE #{puzzle_num})")
    print("==================================================")
    print(f"🔑 Chave Pública: {pubkey}")
    print(f"📐 Range (Hex)  : {base_start} .. fffffffffffffff (2^59 .. 2^60)")
    print("--------------------------------------------------")

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
        "-pubkey", pubkey
    ]

    print(f"⚙️ Executando busca direta na GPU (SEM LATTICE):\n   {' '.join(cmd)}\n")
    t0 = time.time()
    subprocess.run(cmd, cwd=os.path.dirname(bin_path))
    print(f"\n✅ Teste do Puzzle {puzzle_num} concluído em {time.time()-t0:.2f} segundos.")

if __name__ == "__main__":
    main()
