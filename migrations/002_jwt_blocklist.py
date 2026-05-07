"""Migration 002: tabela revoked_tokens para JWT blocklist.

Idempotente. Uso: python migrations/002_jwt_blocklist.py [db_path]
"""
import sqlite3
import sys
from pathlib import Path


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS revoked_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                jti TEXT UNIQUE NOT NULL,
                revoked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_revoked_jti ON revoked_tokens(jti)")
        conn.commit()
        print("  + tabela revoked_tokens pronta")
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 002 em {db}...")
    upgrade(db)
    print("OK")
