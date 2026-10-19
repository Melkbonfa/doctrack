"""Migration 019: categorias de entregável cadastráveis.

Até aqui as categorias eram uma lista fixa no código (Produto, Sistema,
Documentação, Capacitação, Marketing). Cria a tabela `categorias_entregavel`,
de onde a tela passa a ler — o gestor cadastra outras pelo próprio seletor de
categoria ou pela aba Modelos do módulo Projetos.

`entregaveis.categoria` e `modelos_entregavel.categoria` NÃO mudam: continuam
guardando o nome. Por isso a semeadura inclui, além das cinco padrão, qualquer
nome que já esteja gravado nessas colunas.

Espelha o que `db.create_all()` + `servidor._seed_categorias_entregavel()`
fazem na subida do servidor, para quem prefere aplicar no banco antes de trocar
o código. Idempotente.

Uso: python migrations/019_categorias_entregavel.py [db_path]
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

CATEGORIAS_ENTREGAVEL = ["Produto", "Sistema", "Documentação", "Capacitação", "Marketing"]

DDL_CATEGORIAS = """
CREATE TABLE categorias_entregavel (
    id INTEGER PRIMARY KEY,
    nome VARCHAR(40) NOT NULL UNIQUE,
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

        if "categorias_entregavel" in tabs:
            print("  = categorias_entregavel ja existia")
        else:
            cur.execute(DDL_CATEGORIAS)
            print("  + categorias_entregavel criada")

        cur.execute("SELECT COUNT(*) FROM categorias_entregavel")
        if cur.fetchone()[0] > 0:
            print("  = categorias ja semeadas; nada a fazer")
            conn.commit()
            return

        nomes = list(CATEGORIAS_ENTREGAVEL)
        for tabela in ("entregaveis", "modelos_entregavel"):
            if tabela not in tabs:
                continue
            cur.execute(f"SELECT DISTINCT categoria FROM {tabela}")
            for (nome,) in cur.fetchall():
                if nome and nome not in nomes:
                    nomes.append(nome)

        agora = datetime.now().isoformat(sep=" ")
        for ordem, nome in enumerate(nomes):
            cur.execute("INSERT INTO categorias_entregavel (nome, ordem, criado_em) "
                        "VALUES (?, ?, ?)", (nome, ordem, agora))
        print(f"  ~ {len(nomes)} categoria(s) semeada(s): {', '.join(nomes)}")

        conn.commit()
    finally:
        conn.close()

    print("  i novas categorias sao criadas no seletor de categoria ou na aba Modelos")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 019 em {db}...")
    upgrade(db)
    print("OK")
