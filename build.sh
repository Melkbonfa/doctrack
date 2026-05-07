#!/usr/bin/env bash
# build.sh — Script de build para o Render
# Executado automaticamente antes do startCommand

set -o errexit  # Aborta se qualquer comando falhar

echo "=== DocTrack Build ==="

# Instalar dependências Python
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Build concluído com sucesso ==="
