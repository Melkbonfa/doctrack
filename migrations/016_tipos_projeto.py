"""Migration 016: tipos de projeto cadastráveis.

Até aqui os tipos eram uma lista fixa no código (`OEM`, `Revenda`). Cria a
tabela `tipos_projeto`, de onde a tela passa a ler — o gestor cadastra outros
pela aba Modelos do módulo Projetos.

`projetos.tipo` e `modelos_entregavel.tipo_projeto` NÃO mudam: continuam
guardando o nome do tipo. Por isso a semeadura inclui, além dos dois padrão,
qualquer nome que já esteja gravado nessas colunas.

Espelha o que `db.create_all()` + `servidor._seed_tipos_projeto()` fazem na
subida do servidor, para quem prefere aplicar no banco antes de trocar o
código. Idempotente.

Uso: python migrations/016_tipos_projeto.py [db_path]
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

TIPOS_PROJETO = ["OEM", "Revenda"]

DDL_TIPOS = """
CREATE TABLE tipos_projeto (
    id INTEGER PRIMARY KEY,
    nome VARCHAR(20) NOT NULL UNIQUE,
    ordem INTEGER DEFAULT 0,
    criado_em TIMESTAMP
)
"""


def _tabelas(cur):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in cur.fetchall()}


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        tabs = _tabelas(cur)

        if "tipos_projeto" in tabs:
            print("  = tipos_projeto ja existia")
        else:
            cur.execute(DDL_TIPOS)
            print("  + tipos_projeto criada")

        cur.execute("SELECT COUNT(*) FROM tipos_projeto")
        if cur.fetchone()[0] > 0:
            print("  = tipos ja semeados; nada a fazer")
            conn.commit()
            return

        nomes = list(TIPOS_PROJETO)
        for tabela, coluna in (("projetos", "tipo"),
                               ("modelos_entregavel", "tipo_projeto")):
            if tabela not in tabs:
                continue
            cur.execute(f"SELECT DISTINCT {coluna} FROM {tabela}")
            for (nome,) in cur.fetchall():
                if nome and nome not in nomes:
                    nomes.append(nome)

        agora = datetime.now().isoformat(sep=" ")
        for ordem, nome in enumerate(nomes):
            cur.execute("INSERT INTO tipos_projeto (nome, ordem, criado_em) "
                        "VALUES (?, ?, ?)", (nome, ordem, agora))
        print(f"  ~ {len(nomes)} tipo(s) semeado(s): {', '.join(nomes)}")

        conn.commit()
    finally:
        conn.close()

    print("  i novos tipos sao criados na aba Modelos (modulo Projetos)")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 016 em {db}...")
    upgrade(db)
    print("OK")
