"""Migration 003: adiciona coluna version em documentos (optimistic lock).

Idempotente. Uso: python migrations/003_documento_version.py [db_path]
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
        if "version" not in cols:
            cur.execute("ALTER TABLE documentos ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
            print("  + coluna 'version' adicionada")
        else:
            print("  = coluna 'version' ja existia")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 003 em {db}...")
    upgrade(db)
    print("OK")
