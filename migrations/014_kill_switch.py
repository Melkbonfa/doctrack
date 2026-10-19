"""Migration 014: trava de emergência (kill switch).

Cria a tabela `sistema_lock` — uma linha só (id=1) com o estado da trava:

  travado             se o sistema está desligado agora
  travado_em/motivo   quando e por quê (aparece na tela de bloqueio)
  origem              IP que disparou o gatilho
  tokens_validos_apos corte de sessão: todo JWT emitido antes é recusado

No banco e não em arquivo porque o estado precisa valer para todos os processos
que servem o app; um arquivo-sentinela travaria só o worker que o enxergasse.

Espelha o que `db.create_all()` faz na subida do servidor, para quem prefere
aplicar no banco antes de trocar o código. Idempotente.

Uso: python migrations/014_kill_switch.py [db_path]

Depois de aplicar, configure os dois segredos no ambiente — sem eles o gatilho
recusa travar (ver killswitch.py):

    python scripts/kill_switch.py hash
"""
import sqlite3
import sys
from pathlib import Path


DDL = """
CREATE TABLE sistema_lock (
    id INTEGER PRIMARY KEY,
    travado BOOLEAN DEFAULT 0 NOT NULL,
    travado_em TIMESTAMP,
    motivo VARCHAR(300) DEFAULT '',
    origem VARCHAR(60) DEFAULT '',
    destravado_em TIMESTAMP,
    tokens_validos_apos TIMESTAMP
)
"""


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tabelas = {r[0] for r in cur.fetchall()}

        if "sistema_lock" in tabelas:
            print("  = sistema_lock ja existia")
        else:
            cur.execute(DDL)
            print("  + sistema_lock criada")

        # A linha nasce destravada. Criá-la aqui evita que o primeiro pedido de
        # estado tenha de escrever no banco para poder responder.
        cur.execute("SELECT COUNT(*) FROM sistema_lock WHERE id = 1")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO sistema_lock (id, travado) VALUES (1, 0)")
            print("  + estado inicial gravado (destravado)")
        else:
            cur.execute("SELECT travado FROM sistema_lock WHERE id = 1")
            print(f"  = estado atual: {'TRAVADO' if cur.fetchone()[0] else 'destravado'}")

        conn.commit()
    finally:
        conn.close()

    print("  i configure DOCTRACK_KILL_TOKEN_HASH e DOCTRACK_UNLOCK_HASH no .env")
    print("  i gere os dois com: python scripts/kill_switch.py hash")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 014 em {db}...")
    upgrade(db)
    print("OK")
