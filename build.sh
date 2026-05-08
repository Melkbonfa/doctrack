#!/usr/bin/env bash
# build.sh — Script de build para o Render
# Executado automaticamente antes do startCommand

set -o errexit  # Aborta se qualquer comando falhar

echo "=== DocTrack Build ==="

# Dependências de sistema para WeasyPrint (geração de PDF)
apt-get install -y \
  libpango-1.0-0 \
  libpangoft2-1.0-0 \
  libgdk-pixbuf-2.0-0 \
  libcairo2 \
  libffi-dev \
  shared-mime-info \
  fonts-liberation \
  2>/dev/null || echo "[WARN] apt-get não disponível, ignorando libs do sistema"

# Instalar dependências Python
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Build concluído com sucesso ==="
