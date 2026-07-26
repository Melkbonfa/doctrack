"""Migration 008: evolução do módulo de Documentos.

Espelha o que `_sync_schema()` + os backfills de boot fazem na subida do
servidor, para quem prefere aplicar no banco antes de trocar o código.

  1) documentos.prazo            — data ALVO (as outras datas são realizadas)
  2) documentos.motivo_na_codigo — motivo do N/A em lista fechada (analisável)
  3) documento_historico         — trilha de status (cycle time, aging, throughput)
  4) consolidação do armazenamento: o caminho sobe para o equipamento e as 12
     cópias por documento viram herança (só caminho divergente vira override)
  5) marco inicial do histórico para os documentos que já existiam

Idempotente. Uso: python migrations/008_documentos_evolucao.py [db_path]
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def _cols(cur, tabela):
    cur.execute(f"PRAGMA table_info({tabela})")
    return {row[1] for row in cur.fetchall()}


def _add_col(cur, tabela, nome, ddl):
    if nome in _cols(cur, tabela):
        print(f"  = {tabela}.{nome} ja existia")
        return False
    cur.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {ddl}")
    print(f"  + {tabela}.{nome} adicionada")
    return True


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        # 1-2) colunas novas ───────────────────────────────────────────────────
        _add_col(cur, "documentos", "prazo", "DATE")
        _add_col(cur, "documentos", "motivo_na_codigo", "TEXT DEFAULT ''")

        # 3) trilha de status ──────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documento_historico (
                id            INTEGER PRIMARY KEY,
                documento_id  INTEGER NOT NULL REFERENCES documentos(id),
                evento        TEXT DEFAULT 'status',
                status_antigo TEXT DEFAULT '',
                status_novo   TEXT DEFAULT '',
                aplicavel     BOOLEAN,
                motivo        TEXT DEFAULT '',
                em            TIMESTAMP,
                por           TEXT DEFAULT ''
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_dochist_documento "
                    "ON documento_historico (documento_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_dochist_em "
                    "ON documento_historico (em)")
        print("  = documento_historico pronta")

        # 4) armazenamento: caminho e do equipamento, documento so guarda override
        cur.execute("SELECT id, COALESCE(armazenamento_base, '') "
                    "FROM equipamentos WHERE ativo = 1")
        promovidos = limpos = 0
        for equip_id, base in cur.fetchall():
            base = (base or "").strip()
            if not base:
                cur.execute(
                    "SELECT TRIM(COALESCE(armazenamento, '')) AS p, COUNT(*) c "
                    "  FROM documentos "
                    " WHERE ativo = 1 AND equipamento_id = ? AND p != '' "
                    " GROUP BY p ORDER BY c DESC LIMIT 1", (equip_id,))
                row = cur.fetchone()
                if row:
                    base = row[0]
                    cur.execute("UPDATE equipamentos SET armazenamento_base = ? "
                                "WHERE id = ?", (base, equip_id))
                    promovidos += 1
            if not base:
                continue
            cur.execute("UPDATE documentos SET armazenamento = '' "
                        " WHERE ativo = 1 AND equipamento_id = ? "
                        "   AND TRIM(COALESCE(armazenamento, '')) = ?",
                        (equip_id, base))
            limpos += cur.rowcount
        print(f"  ~ {promovidos} equipamento(s) receberam caminho base; "
              f"{limpos} documento(s) passaram a herdar")

        # 5) marco inicial do historico (so quando a tabela esta vazia) ─────────
        cur.execute("SELECT COUNT(*) FROM documento_historico")
        if cur.fetchone()[0] == 0:
            agora = datetime.now().isoformat(sep=" ", timespec="seconds")
            cur.execute("SELECT id, COALESCE(status, 'Elaborar'), "
                        "       COALESCE(updated_em, criado_em) "
                        "  FROM documentos WHERE ativo = 1")
            linhas = cur.fetchall()
            for doc_id, status, em in linhas:
                cur.execute(
                    "INSERT INTO documento_historico (documento_id, evento, "
                    "status_antigo, status_novo, motivo, em, por) "
                    "VALUES (?, 'status', '', ?, 'Marco inicial (migracao)', ?, 'system')",
                    (doc_id, status, em or agora))
            print(f"  ~ marco inicial criado para {len(linhas)} documento(s)")

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 008 em {db}...")
    upgrade(db)
    print("OK")
