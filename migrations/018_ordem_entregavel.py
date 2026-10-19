"""Migration 018: ordem dos entregáveis dentro do projeto.

O gestor passa a definir a ordem dos entregáveis arrastando-os na tela do
projeto. A coluna `ordem` guarda a posição; os entregáveis que já existem
nascem todos com 0 e o id desempata — é exatamente a ordem que a tela já
mostrava, então não há backfill.

Espelha o que `servidor._sync_schema()` faz na subida do servidor, para quem
prefere aplicar no banco antes de trocar o código. Idempotente.

Uso: python migrations/018_ordem_entregavel.py [db_path]
"""
import sqlite3
import sys
from pathlib import Path


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(entregaveis)")
        colunas = {row[1] for row in cur.fetchall()}
        if not colunas:
            print("  ! tabela entregaveis nao existe")
            return
        if "ordem" in colunas:
            print("  = coluna entregaveis.ordem ja existia")
        else:
            cur.execute("ALTER TABLE entregaveis ADD COLUMN ordem INTEGER DEFAULT 0")
            print("  + coluna entregaveis.ordem adicionada (existentes = 0, desempate pelo id)")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 018 em {db}...")
    upgrade(db)
    print("OK")
