"""Migration 001: adiciona ativo e deleted_at em documentos.

Idempotente — pode rodar multiplas vezes sem efeito colateral.
Uso: python migrations/001_soft_delete_documentos.py [db_path]
"""
import sqlite3
import sys
from pathlib import Path


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(documentos)")
        cols = {row[1] for row in cur.fetchall()}
        changed = False
        if "ativo" not in cols:
            cur.execute("ALTER TABLE documentos ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1")
            changed = True
            print("  + coluna 'ativo' adicionada")
        if "deleted_at" not in cols:
            cur.execute("ALTER TABLE documentos ADD COLUMN deleted_at TEXT NULL")
            changed = True
            print("  + coluna 'deleted_at' adicionada")
        conn.commit()
        if not changed:
            print("  = nenhuma mudanca necessaria (ja aplicada)")
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 001 em {db}...")
    upgrade(db)
    print("OK")
