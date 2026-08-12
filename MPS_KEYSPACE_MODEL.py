"""
MPS_KEYSPACE_MODEL.py
=====================
Modela a distribuição conjunta dos bits das chaves resolvidas como um MPS.
Extrai correlações de longo alcance para direcionar seeds do Kangaroo.

Integração com RCkangaroo:
  1. Rode o treinamento offline (usa as 82 chaves resolvidas)
  2. Exporte os "pesos de seed" (probabilidade por região)
  3. No RCkangaroo, use os pesos para priorizar ranges no start_offset

Dependências: numpy, scipy (opcional para otimização)
"""

import numpy as np
from collections import Counter
import json

class MPSKeyspaceModel:
    """
    Matrix Product State para modelar a distribuição de bits das chaves.

    Cada site i representa um bit da chave privada.
    O MPS aprende P(bit_i | bit_{i-1}, bit_{i-2}, ...) de forma eficiente.
    """

    def __init__(self, n_bits=160, bond_dim=64):
        self.n_bits = n_bits
        self.bond_dim = bond_dim
        self.d = 2  # bits: 0 ou 1

        # Inicializar tensores MPS aleatórios (serão treinados)
        self.tensors = []
        for i in range(n_bits):
            if i == 0:
                shape = (1, self.d, bond_dim)
            elif i == n_bits - 1:
                shape = (bond_dim, self.d, 1)
            else:
                shape = (bond_dim, self.d, bond_dim)

            # Inicialização com pequeno ruído (não uniforme)
            A = np.random.randn(*shape) * 0.01 + 0.5
            # Normalizar
            A /= np.linalg.norm(A)
            self.tensors.append(A)

    def train_from_keys(self, keys_dict, max_bits=70):
        """
        Treina o MPS a partir das chaves resolvidas.

        Args:
            keys_dict: dict {puzzle_num: private_key_int}
            max_bits: número máximo de bits para treinar
        """
        # Converter chaves para matriz de bits
        bit_matrix = []
        for n, key in keys_dict.items():
            if n > max_bits:
                continue
            bits = [(key >> i) & 1 for i in range(n)]
            # Preencher com zeros até max_bits
            bits += [0] * (max_bits - len(bits))
            bit_matrix.append(bits)

        bit_matrix = np.array(bit_matrix)  # shape: (n_keys, max_bits)

        print(f"[MPS] Treinando com {len(bit_matrix)} chaves, {max_bits} bits")

        # Treinamento via DMRG-like variational optimization simplificado
        # Para cada site, ajustamos o tensor para maximizar a likelihood

        for epoch in range(100):
            total_ll = 0

            for site in range(max_bits):
                # Coletar estatísticas locais
                counts = np.zeros((self.d, self.bond_dim, self.bond_dim))

                for bits in bit_matrix:
                    # Contrair MPS para obter estado no site
                    left = self._contract_left(bits, site)
                    right = self._contract_right(bits, site)

                    b = bits[site]
                    counts[b] += np.outer(left, right)

                # Atualizar tensor do site (regra simplificada)
                for b in range(self.d):
                    if counts[b].sum() > 0:
                        self.tensors[site][:, b, :] = counts[b] / counts[b].sum()

                # Normalizar
                self.tensors[site] /= np.linalg.norm(self.tensors[site])

            if epoch % 20 == 0:
                ll = self._log_likelihood(bit_matrix[:10])
                print(f"[MPS] Epoch {epoch}, LL: {ll:.4f}")

        print("[MPS] Treinamento concluído")

    def _contract_left(self, bits, site):
        """Contrai MPS da esquerda até o site"""
        vec = np.ones(1)
        for i in range(site):
            b = bits[i]
            vec = vec @ self.tensors[i][:, b, :]
        return vec

    def _contract_right(self, bits, site):
        """Contrai MPS da direita até o site"""
        vec = np.ones(1)
        for i in range(self.n_bits - 1, site, -1):
            b = bits[i] if i < len(bits) else 0
            vec = self.tensors[i][:, b, :] @ vec
        return vec

    def _log_likelihood(self, bit_matrix):
        """Calcula log-likelihood média"""
        ll = 0
        for bits in bit_matrix:
            prob = 1.0
            for i in range(len(bits)):
                left = self._contract_left(bits, i)
                right = self._contract_right(bits, i)
                b = bits[i]
                prob *= (left @ self.tensors[i][:, b, :] @ right)
            ll += np.log(max(prob, 1e-300))
        return ll / len(bit_matrix)

    def get_bit_probabilities(self, n_bits):
        """
        Retorna P(bit_i = 1) para cada posição.
        Usado para identificar vieses no keyspace.
        """
        probs = []
        for i in range(n_bits):
            # Marginalizar sobre todos os outros bits
            # Aproximação: usar estado do site isolado
            p1 = np.sum(self.tensors[i][:, 1, :]**2)
            probs.append(p1)
        return np.array(probs)

    def generate_seed_weights(self, n_bits, n_buckets=1024):
        """
        Gera pesos para cada bucket do keyspace.
        Buckets com peso maior são mais prováveis de conter a chave.

        Retorna: array de pesos (n_buckets,) que somam 1
        """
        weights = np.ones(n_buckets) / n_buckets

        # Ajustar pesos baseado nos vieses de bits
        bit_probs = self.get_bit_probabilities(n_bits)

        for bucket in range(n_buckets):
            # Posição média do bucket no range [0, 1)
            pos = (bucket + 0.5) / n_buckets

            # Converter posição para bits
            bits = []
            temp = int(pos * (2**n_bits))
            for i in range(n_bits):
                bits.append((temp >> i) & 1)

            # Calcular likelihood dessa configuração de bits
            likelihood = 1.0
            for i in range(min(n_bits, len(bit_probs))):
                if bits[i] == 1:
                    likelihood *= bit_probs[i]
                else:
                    likelihood *= (1 - bit_probs[i])

            weights[bucket] *= likelihood

        weights /= weights.sum()
        return weights

    def export_seed_prior(self, filename="mps_seed_prior.json"):
        """Exporta pesos para uso no RCkangaroo"""
        weights = self.generate_seed_weights(140, n_buckets=4096)

        # Converter para formato que o RCkangaroo pode usar
        prior = {
            "n_buckets": 4096,
            "weights": weights.tolist(),
            "description": "MPS-based seed prior for Puzzle 140+"
        }

        with open(filename, "w") as f:
            json.dump(prior, f)

        print(f"[MPS] Seed prior exportado para {filename}")
        return prior


# ============================================
# USO EXEMPLO
# ============================================
if __name__ == "__main__":
    # Chaves resolvidas (1-70)
    keys = {
        1: 0x1, 2: 0x3, 3: 0x7, 4: 0x8, 5: 0x15,
        6: 0x31, 7: 0x4c, 8: 0xe0, 9: 0x1d3, 10: 0x202,
        # ... (completar com todas as 82 chaves)
    }

    model = MPSKeyspaceModel(n_bits=140, bond_dim=64)
    model.train_from_keys(keys, max_bits=70)

    # Exportar prior para RCkangaroo
    prior = model.export_seed_prior("seed_prior_140.json")

    # Verificar vieses
    probs = model.get_bit_probabilities(50)
    print("\nVieses de bits (P=1):")
    for i, p in enumerate(probs):
        if abs(p - 0.5) > 0.05:
            print(f"  Bit {i}: P(1)={p:.3f} (desvio={p-0.5:+.3f})")
