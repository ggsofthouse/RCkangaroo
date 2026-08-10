#!/bin/bash

# Atualiza e instala dependências básicas caso necessário
apt-get update
apt-get install -y git cmake build-essential python3 python3-pip python3-venv tzdata screen

# Define timezone (opcional, útil para logs)
ln -fs /usr/share/zoneinfo/America/Sao_Paulo /etc/localtime
dpkg-reconfigure -f noninteractive tzdata

# Clona o repositório
cd /root
if [ -d "RCkangaroo" ]; then
    rm -rf RCkangaroo
fi
git clone https://github.com/ggsofthouse/RCkangaroo.git
cd RCkangaroo

# Compila o RCKangaroo
mkdir build
cd build
cmake ..
make -j$(nproc)
cd ..

# Configura as variáveis de ambiente para o Pool
export POOL_SERVER_URL="https://valyrafi.com.br"
export WORKER_TOKEN="9e14298f5ff89daf91b2ab7550506cf06157dffbdbcfcbf7124dae1a33f0b138"

# Instala dependências do Python
pip3 install --upgrade pip
pip3 install -r pool/worker/requirements.txt

# Cria um arquivo de serviço ou usa o screen/nohup para rodar
echo "Iniciando o worker em background com nohup..."
nohup python3 pool/worker/worker.py > /root/worker.log 2>&1 &

echo "Instalação concluída! O worker está rodando. Use 'tail -f /root/worker.log' para ver os logs."
