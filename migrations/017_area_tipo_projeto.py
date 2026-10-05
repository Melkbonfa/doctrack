"""Migration 017: área do tipo (modelo) de projeto.

Projetos passa a ser um módulo único para PDE, PDR e INOV. O que separa um
departamento do outro é o modelo do projeto (`PDE RUO`, `PDR IVD`, `INOV`…),
então o tipo ganha a coluna `area` com o slug de `areas.py`. A área do projeto
é derivada do tipo — `projetos` não muda.

Os tipos que já existem nascem `pde`: até aqui o módulo só existia no PDE.

Espelha o que `servidor._sync_schema()` faz na subida do servidor, para quem
prefere aplicar no banco antes de trocar o código. Idempotente.

Uso: python migrations/017_area_tipo_projeto.py [db_path]
"""
import sqlite3
import sys
from pathlib import Path


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tipos_projeto'")
        if not cur.fetchone():
            print("  ! tipos_projeto nao existe; rode a migration 016 antes")
            return

        cur.execute("PRAGMA table_info(tipos_projeto)")
        if "area" in {row[1] for row in cur.fetchall()}:
            print("  = coluna tipos_projeto.area ja existia")
        else:
            cur.execute("ALTER TABLE tipos_projeto "
                        "ADD COLUMN area VARCHAR(20) NOT NULL DEFAULT 'pde'")
            print("  + coluna tipos_projeto.area adicionada (tipos existentes = pde)")

        conn.commit()
    finally:
        conn.close()

    print("  i a area de cada modelo e ajustada na aba Modelos (modulo Projetos)")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 017 em {db}...")
    upgrade(db)
    print("OK")
