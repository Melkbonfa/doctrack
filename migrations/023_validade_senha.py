"""Migration 023: a senha ganha data — base da validade da senha.

`users.senha_definida_em` guarda quando a senha atual foi definida. O login
recusa senha mais velha que DOCTRACK_SENHA_VALIDADE_DIAS (padrão 180) e manda
a pessoa para a troca de senha.

As contas que já existem começam a contar de agora: sem o backfill a data
ficaria nula (senha que nunca vence).

Espelha o que `servidor._sync_schema()` faz na subida do servidor, para quem
prefere aplicar no banco antes de trocar o código. Idempotente.

Uso: python migrations/023_validade_senha.py [db_path]
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(users)")
        existentes = {row[1] for row in cur.fetchall()}
        if not existentes:
            print("  ! tabela users nao existe")
            return
        if "senha_definida_em" in existentes:
            print("  = coluna users.senha_definida_em ja existia")
            return
        cur.execute("ALTER TABLE users ADD COLUMN senha_definida_em TIMESTAMP")
        cur.execute("UPDATE users SET senha_definida_em = ? WHERE senha_definida_em IS NULL",
                    (datetime.now().isoformat(sep=" "),))
        print(f"  + coluna users.senha_definida_em ({cur.rowcount} conta(s) datada(s) de hoje)")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        sys.exit(f"banco nao encontrado: {db}")
    print(f"023_validade_senha em {db}")
    upgrade(db)
