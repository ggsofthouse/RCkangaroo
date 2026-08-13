# 🦘 RCKangaroo Distributed Mining Pool Guide

Guia completo para rodar a Pool de processamento distribuído do **RCKangaroo** em sua máquina local (NVIDIA RTX 2060 Super), conectar máquinas Windows/Linux remotas e alugar GPUs na **Vast.ai** ou **RunPod**.

> Antes de implantar GPUs, leia [POOL_CORRECTNESS_AUDIT.md](POOL_CORRECTNESS_AUDIT.md).

---

## 📐 Arquitetura da Pool

```
                                  ┌───────────────────────────┐
                                  │   Pool Coordinator Server │
                                  │   (FastAPI + Dashboard)   │
                                  │      Porta 8000           │
                                  └─────────────▲─────────────┘
                                                │ (HTTP REST / WebSockets)
             ┌──────────────────────────────────┼──────────────────────────────────┐
             │                                  │                                  │
┌───────────────────────────┐      ┌───────────────────────────┐      ┌───────────────────────────┐
│   Worker Local (Windows)  │      │   Worker Remoto (Linux)   │      │   Vast.ai / Cloud GPU     │
│   RTX 2060 Super (local)  │      │   GPUs adicionais         │      │   RTX 4090 / 5090 Docker  │
└───────────────────────────┘      └───────────────────────────┘      └───────────────────────────┘
```

1. **Pool Coordinator (Servidor)**:
   - Gerencia a chave pública alvo (`-pubkey`), deslocamento inicial (`-start`) e o intervalo total (`-range`).
   - Divide o intervalo em sub-blocos (*chunks*) e os atribui aos workers conectados.
   - Fornece um **Dashboard HTML em tempo real** com taxa de hash total (GH/s), estatísticas de cada GPU e chaves encontradas.
   - Salva automaticamente as chaves resolvidas em `POOL_RESULTS.TXT`.

2. **Workers (Clientes)**:
   - Detectam o sistema operacional (Windows/Linux) e o modelo de GPU.
   - Compilam ou executam o binário do RCKangaroo automaticamente.
   - Solicitam tarefas, executam o algoritmo Pollard's Kangaroo e reportam o progresso em tempo real.
   - Enviam a chave privada para o servidor assim que encontrada.

---

## 🚀 Passo 1: Iniciar o Servidor da Pool (Coordinator)

### 1. Instalar Dependências do Servidor
Na pasta da pool:
```bash
cd e:\RCkangaroo\pool\server
pip install -r requirements.txt
```

### 2. Rodar o Servidor
```bash
python app.py
```
O servidor estará rodando em: `http://localhost:8000` (ou no seu IP público/VPN se for acessar remotamente).

### 3. Acessar o Dashboard Web
Abra o navegador em: `http://localhost:8000`
No dashboard você pode:
- Acompanhar a taxa de hash total da pool.
- Criar novos alvos de busca inserindo `Public Key`, `Start Offset` e `Range Bits`.
- Visualizar todos os workers conectados.

---

## 💻 Passo 2: Conectar Workers (Windows / Linux)

### Em qualquer máquina local ou remota (Windows / Linux):

1. Clone o repositório ou copie os arquivos da pasta `pool/worker`.
2. Configure a variável de ambiente apontando para o IP do seu servidor:

**No Windows (PowerShell):**
```powershell
$env:POOL_SERVER_URL="http://IP_DO_SEU_SERVIDOR:8000"
$env:WORKER_NAME="Minha-RTX-2060-Super"
python pool/worker/worker.py
```

**No Linux (Bash):**
```bash
export POOL_SERVER_URL="http://IP_DO_SEU_SERVIDOR:8000"
export WORKER_NAME="Rig-Linux-01"
python3 pool/worker/worker.py
```

O worker irá detectar a GPU, compilar o binário (se necessário no Linux), conectar-se à pool e iniciar o processamento imediatamente.

---

## ☁️ Passo 3: Conectar Instâncias Alugadas na Vast.ai

Para alugar GPUs de alta performance (ex: RTX 4090 ou RTX 5090) na **Vast.ai** e conectar diretamente à sua pool:

### Opção A: Usando a imagem Docker oficial / customizada

1. No painel da Vast.ai, escolha a imagem base `nvidia/cuda:12.8.0-devel-ubuntu22.04` ou crie a imagem a partir do `pool/docker/Dockerfile`.
2. Nas opções de lançamento da instância (Docker Options / Environment variables), defina:
   ```bash
   -e POOL_SERVER_URL="http://SEU_IP_PUBLICO_OU_NGROK:8000" -e WORKER_NAME="VastAI-RTX4090"
   ```
3. Comando de inicialização (*On-start script*):
   ```bash
   git clone https://github.com/RetiredC/RCKangaroo.git /app && cd /app && chmod +x pool/docker/start_worker.sh && ./pool/docker/start_worker.sh
   ```

---

## 📌 Exemplo Prático de Teste (Puzzle #40 ou #85)

1. No Dashboard (`http://localhost:8000`), clique em **Create New Target Job**:
   - **Public Key**: `02145d223c51a33f932612296f6e3c2992ea7105642ead300067d2b0900139b85c`
   - **Start Hex**: `8000000000`
   - **Range Bits**: `40`
2. Clique em **Launch Job**.
3. O worker local na sua RTX 2060 Super pegará a tarefa automaticamente e resolverá a chave em poucos segundos!
4. O resultado aparecerá em tempo real no Dashboard e será salvo em `pool/server/POOL_RESULTS.TXT`.
