#!/usr/bin/env python3
"""
test_puzzle80_vast.py
=====================
Teste standalone do RCKangaroo para Puzzle #80 em máquinas Vast.ai.
- Sem servidor / sem pool / sem token
- Compila o binário automaticamente se necessário
- Detecta todas as GPUs e roda em paralelo
- Exibe a chave privada se encontrar (puzzle 80 já tem solução conhecida)

Uso na Vast.ai:
  git clone https://github.com/ggsofthouse/RCkangaroo.git /workspace/RCkangaroo
  cd /workspace/RCkangaroo
  python3 test_puzzle80_vast.py
"""

import os
import sys
import time
import subprocess
import shutil

sys.stdout.reconfigure(encoding='utf-8')

# ─── Parâmetros do Puzzle #80 ──────────────────────────────────────────────────
PUBKEY     = "037e1238f7b1ce757df94faa9a2eb261bf0aeb9f84dbf81212104e78931c2a19dc"
BASE_START = "80000000000000000000"  # 2^79 em hex
RANGE_BITS = 79
DP_BITS    = 16     # RTX 4090: 16-18 ideal para 79-bit
MAX_OPS    = 2.0    # Margem: ~2x o esperado para ter certeza de encontrar
# ──────────────────────────────────────────────────────────────────────────────

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def detect_gpus():
    """Retorna lista de índices de GPUs disponíveis via nvidia-smi."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,name,memory.total",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        gpus = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            idx  = int(parts[0])
            name = parts[1] if len(parts) > 1 else f"GPU{idx}"
            mem  = parts[2] if len(parts) > 2 else "?"
            gpus.append((idx, name, mem))
        return gpus
    except Exception:
        return [(0, "GPU0", "?")]


def find_or_build_binary():
    """Procura o binário compilado; se não existir, compila automaticamente."""
    candidates = [
        os.path.join(ROOT_DIR, "build", "bin", "rckangaroo"),
        os.path.join(ROOT_DIR, "build", "rckangaroo"),
        os.path.join(ROOT_DIR, "build", "RCKangaroo"),
        os.path.join(ROOT_DIR, "bin", "rckangaroo"),
        os.path.join(ROOT_DIR, "rckangaroo"),
        os.path.join(ROOT_DIR, "RCKangaroo"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p

    # Não encontrou → compilar com cmake
    print("⚙️  Binário não encontrado. Compilando com cmake...")
    build_dir = os.path.join(ROOT_DIR, "build")
    os.makedirs(build_dir, exist_ok=True)

    cmake_ok = subprocess.run(
        ["cmake", "..", "-DCMAKE_BUILD_TYPE=Release"],
        cwd=build_dir
    ).returncode == 0

    if not cmake_ok:
        print("❌ cmake falhou. Verifique se cmake e nvcc estão instalados.")
        sys.exit(1)

    nproc = os.cpu_count() or 4
    make_ok = subprocess.run(
        ["make", f"-j{nproc}"],
        cwd=build_dir
    ).returncode == 0

    if not make_ok:
        print("❌ make falhou. Verifique se nvcc/CUDA estão instalados.")
        sys.exit(1)

    for p in candidates:
        if os.path.isfile(p):
            print(f"✅ Compilação concluída: {p}\n")
            return p

    print("❌ Compilação aparentemente completou mas binário não foi encontrado.")
    sys.exit(1)


def main():
    print("=" * 58)
    print("🦘  RCKangaroo — TESTE STANDALONE VAST.AI  (PUZZLE #80)")
    print("=" * 58)
    print(f"   Pubkey     : {PUBKEY}")
    print(f"   Start      : 0x{BASE_START}")
    print(f"   Range bits : {RANGE_BITS}  (busca em 2^{RANGE_BITS} → 2^{RANGE_BITS+1}-1)")
    print(f"   DP bits    : {DP_BITS}")
    print(f"   Max ops    : {MAX_OPS}x")
    print()

    gpus = detect_gpus()
    print(f"🖥️  GPUs detectadas: {len(gpus)}")
    for idx, name, mem in gpus:
        print(f"   [{idx}] {name}  ({mem} MB)")
    print()

    bin_path = find_or_build_binary()
    print(f"🔧 Binário: {bin_path}\n")

    bin_dir = os.path.dirname(bin_path)

    # Roda em todas as GPUs em paralelo (uma instância por GPU)
    procs = []
    t0 = time.time()

    for idx, name, mem in gpus:
        cmd = [
            bin_path,
            "-gpu",   str(idx),
            "-dp",    str(DP_BITS),
            "-range", str(RANGE_BITS),
            "-start", BASE_START,
            "-pubkey", PUBKEY,
            "-max",   str(MAX_OPS)
        ]
        print(f"🚀 GPU [{idx}] {name}: {' '.join(cmd)}")
        p = subprocess.Popen(cmd, cwd=bin_dir)
        procs.append((idx, name, p))

    print(f"\n⏳ {len(procs)} instância(s) rodando... Aguardando conclusão.\n")

    for idx, name, proc in procs:
        ret = proc.wait()
        elapsed = time.time() - t0
        status = "✅ OK" if ret == 0 else f"⚠️ exit={ret}"
        print(f"   GPU [{idx}] {name}: {status}  ({elapsed:.1f}s)")

    print(f"\n✅ Teste finalizado em {time.time()-t0:.1f} segundos.")
    print("   Se a chave foi encontrada, ela aparece acima nas linhas 'SOLVED'.")


if __name__ == "__main__":
    main()
