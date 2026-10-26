"""Migration 022: o projeto ganha o equipamento; o entregável, a natureza.

Ondas A e B do estudo de ligações (docs/planos/ESTUDO_ligacoes_entregaveis.md):

  * `projetos.equipamento_id` — o produto que o projeto desenvolve (PDE);
  * `modelos_entregavel.natureza` / `.alvo` — o que o item do modelo É e, para
    documento, QUAL documento do equipamento;
  * `entregaveis.natureza` / `.alvo` — o mesmo, só para avulso ou exceção.

Tudo nasce vazio: nada fica ligado sem alguém escolher o equipamento do projeto e
a natureza do item. Por isso não há backfill.

Espelha o que `servidor._sync_schema()` faz na subida do servidor, para quem
prefere aplicar no banco antes de trocar o código. Idempotente.

Uso: python migrations/022_projeto_equipamento.py [db_path]
"""
import sqlite3
import sys
from pathlib import Path

COLUNAS = {
    "projetos": [("equipamento_id", "INTEGER")],
    "modelos_entregavel": [("natureza", "VARCHAR(20) DEFAULT ''"),
                           ("alvo", "VARCHAR(60) DEFAULT ''")],
    "entregaveis": [("natureza", "VARCHAR(20) DEFAULT ''"),
                    ("alvo", "VARCHAR(60) DEFAULT ''")],
}


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        for tabela, cols in COLUNAS.items():
            cur.execute(f"PRAGMA table_info({tabela})")
            existentes = {row[1] for row in cur.fetchall()}
            if not existentes:
                print(f"  ! tabela {tabela} nao existe")
                continue
            for nome, ddl in cols:
                if nome in existentes:
                    print(f"  = coluna {tabela}.{nome} ja existia")
                else:
                    cur.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {ddl}")
                    print(f"  + coluna {tabela}.{nome}")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_projetos_equipamento_id "
                    "ON projetos (equipamento_id)")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        sys.exit(f"banco nao encontrado: {db}")
    print(f"022_projeto_equipamento em {db}")
    upgrade(db)
