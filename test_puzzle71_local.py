import os
import sys
import time
import subprocess

sys.stdout.reconfigure(encoding='utf-8')

def main():
    """
    Script de Teste Local — Bitcoin Puzzle #71
    -------------------------------------------------------------------------
    ATENÇÃO CRÍTICA SOBRE O PUZZLE #71:
    - O Puzzle #71 possui apenas ENDEREÇO (1PWo3JeB9jrGwfHDNpdGK54CRas7fsVzXU) 
      e Hash160 (f6f5431d25bbf7b12e8add9af5e3475c44a0a5b8).
    - A Chave Pública secp256k1 NUNCA foi revelada na blockchain.
    - O algoritmo Pollard's Kangaroo (RCKangaroo) exige obrigatoriamente a 
      Chave Pública (P = k*G). Portanto, para buscar o Puzzle #71 via RCKangaroo,
      é necessário o pubkey pré-calculado ou o uso de motores de Hash160 direto
      (como o ShorCudaHunter ou BitCrack/KeyHunt).
    -------------------------------------------------------------------------
    """
    puzzle_num = 71
    target_address = "1PWo3JeB9jrGwfHDNpdGK54CRas7fsVzXU"
    target_hash160 = "f6f5431d25bbf7b12e8add9af5e3475c44a0a5b8"
    base_start = "400000000000000000"  # 2^70 em Hex (Início do Range do Puzzle 71)
    dp_bits = 14
    range_bits = 70
    max_ops = 1.62

    print("==================================================")
    print(f"🦘 RCKangaroo — TESTE LOCAL DIRETO (PUZZLE #{puzzle_num})")
    print("==================================================")
    print(f"📍 Endereço Alvo : {target_address}")
    print(f"🔑 Hash160 Alvo  : {target_hash160}")
    print(f"📐 Range (Hex)   : {base_start} .. 7fffffffffffffffff (2^70 .. 2^71)")
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

    print("⚠️ NOTA: Pollard's Kangaroo necessita da Chave Pública secp256k1.")
    print("   Se a chave pública do Puzzle 71 não for fornecida, utilize o motor ShorCudaHunter para busca por Hash160.\n")

if __name__ == "__main__":
    main()
