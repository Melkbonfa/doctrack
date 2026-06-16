"""Migration 004: campos de PMO/EVM em projetos + tabela projeto_mensal.

Adiciona ao Projeto o cronograma (datas previstas/reais) e o orcamento (BAC),
e cria a tabela de acompanhamento mensal (previsto x realizado x custo).

Idempotente. Uso: python migrations/004_projeto_pmo.py [db_path]
"""
import sqlite3
import sys
from pathlib import Path


NOVAS_COLUNAS = [
    ("data_inicio_prev", "TEXT DEFAULT ''"),
    ("data_inicio_real", "TEXT DEFAULT ''"),
    ("data_fim_prev",    "TEXT DEFAULT ''"),
    ("data_fim_real",    "TEXT DEFAULT ''"),
    ("orcamento",        "REAL DEFAULT 0"),
]


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        # 1) colunas novas em projetos
        cur.execute("PRAGMA table_info(projetos)")
        cols = {row[1] for row in cur.fetchall()}
        for nome, ddl in NOVAS_COLUNAS:
            if nome not in cols:
                cur.execute(f"ALTER TABLE projetos ADD COLUMN {nome} {ddl}")
                print(f"  + coluna projetos.{nome} adicionada")
            else:
                print(f"  = coluna projetos.{nome} ja existia")

        # 2) tabela de acompanhamento mensal
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='projeto_mensal'")
        if not cur.fetchone():
            cur.execute("""
                CREATE TABLE projeto_mensal (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    projeto_id      INTEGER NOT NULL,
                    competencia     VARCHAR(7) NOT NULL,
                    pct_previsto    INTEGER DEFAULT 0,
                    pct_realizado   INTEGER DEFAULT 0,
                    custo_acumulado REAL DEFAULT 0,
                    atualizado_por  VARCHAR(120) DEFAULT '',
                    atualizado_em   DATETIME,
                    FOREIGN KEY(projeto_id) REFERENCES projetos(id),
                    CONSTRAINT uq_projeto_competencia UNIQUE (projeto_id, competencia)
                )
            """)
            cur.execute(
                "CREATE INDEX ix_projeto_mensal_projeto_id ON projeto_mensal(projeto_id)")
            print("  + tabela projeto_mensal criada")
        else:
            print("  = tabela projeto_mensal ja existia")

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 004 em {db}...")
    upgrade(db)
    print("OK")
