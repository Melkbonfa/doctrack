"""Migration 006: tipo de projeto (OEM/Revenda) + modelos de entregáveis.

- Adiciona a coluna projetos.tipo (TEXT '').
- Cria a tabela modelos_entregavel (templates editáveis por tipo de projeto).
- Semeia OEM e Revenda a partir dos entregáveis distintos já existentes no
  banco (preservando acentos e a ordem de aparição). O usuário ajusta cada
  lista depois, na tela de Modelos.

Idempotente. Uso: python migrations/006_tipo_projeto_e_modelos.py [db_path]
"""
import sqlite3
import sys
from pathlib import Path

TIPOS_PROJETO = ["OEM", "Revenda"]


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        # 1) coluna projetos.tipo ──────────────────────────────────────────────
        cur.execute("PRAGMA table_info(projetos)")
        cols = {row[1] for row in cur.fetchall()}
        if "tipo" not in cols:
            cur.execute("ALTER TABLE projetos ADD COLUMN tipo TEXT DEFAULT ''")
            print("  + coluna projetos.tipo adicionada")
        else:
            print("  = coluna projetos.tipo ja existia")

        # 2) tabela modelos_entregavel ─────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS modelos_entregavel (
                id                 INTEGER PRIMARY KEY,
                tipo_projeto       TEXT NOT NULL,
                categoria          TEXT DEFAULT 'Produto',
                tipo               TEXT NOT NULL,
                responsavel_padrao TEXT DEFAULT '',
                ordem              INTEGER DEFAULT 0
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_modelos_tipo_projeto "
                    "ON modelos_entregavel (tipo_projeto)")
        print("  = tabela modelos_entregavel pronta")

        # 3) semeadura (só se estiver vazia) ────────────────────────────────────
        cur.execute("SELECT COUNT(*) FROM modelos_entregavel")
        if cur.fetchone()[0] > 0:
            print("  = modelos ja semeados; nada a fazer")
            conn.commit()
            return

        # entregáveis distintos (categoria, tipo) na ordem de aparição (MIN id),
        # com o responsável padrão do primeiro registro daquele tipo.
        cur.execute("""
            SELECT categoria, tipo,
                   COALESCE((SELECT responsaveis FROM entregaveis e2
                             WHERE e2.categoria IS e1.categoria AND e2.tipo = e1.tipo
                             ORDER BY e2.id LIMIT 1), '') AS resp,
                   MIN(id) AS ord
              FROM entregaveis e1
             GROUP BY categoria, tipo
             ORDER BY ord
        """)
        base = cur.fetchall()
        if not base:
            print("  ! nenhum entregavel existente para semear; modelos ficam vazios")
            conn.commit()
            return

        n = 0
        for tp in TIPOS_PROJETO:
            for ordem, (categoria, tipo, resp, _min) in enumerate(base):
                cur.execute(
                    "INSERT INTO modelos_entregavel "
                    "(tipo_projeto, categoria, tipo, responsavel_padrao, ordem) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (tp, categoria or "Produto", tipo, resp or "", ordem))
                n += 1
        print(f"  ~ {n} itens de modelo semeados ({len(base)} por tipo × {len(TIPOS_PROJETO)} tipos)")

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 006 em {db}...")
    upgrade(db)
    print("OK")
