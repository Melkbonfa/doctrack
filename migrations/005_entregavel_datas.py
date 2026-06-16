"""Migration 005: datas de início e conclusão por entregável (tarefa).

Permite reconstruir o realizado/Curva-S automaticamente pelas conclusões.

Idempotente. Uso: python migrations/005_entregavel_datas.py [db_path]
"""
import sqlite3
import sys
from pathlib import Path


NOVAS_COLUNAS = [
    ("data_inicio",    "TEXT DEFAULT ''"),
    ("data_conclusao", "TEXT DEFAULT ''"),
]


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(entregaveis)")
        cols = {row[1] for row in cur.fetchall()}
        for nome, ddl in NOVAS_COLUNAS:
            if nome not in cols:
                cur.execute(f"ALTER TABLE entregaveis ADD COLUMN {nome} {ddl}")
                print(f"  + coluna entregaveis.{nome} adicionada")
            else:
                print(f"  = coluna entregaveis.{nome} ja existia")

        # Retroalimenta a conclusao dos ja concluidos com a ultima atualizacao,
        # para que projetos existentes ja mostrem alguma curva (melhor esforco).
        cur.execute("""
            UPDATE entregaveis
               SET data_conclusao = substr(atualizado_em, 1, 10)
             WHERE status = 'concluido'
               AND (data_conclusao IS NULL OR data_conclusao = '')
               AND atualizado_em IS NOT NULL
        """)
        print(f"  ~ {cur.rowcount} entregavel(is) concluido(s) com conclusao retroalimentada")

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 005 em {db}...")
    upgrade(db)
    print("OK")
