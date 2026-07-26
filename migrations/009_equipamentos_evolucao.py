"""Migration 009: evolução do módulo de Equipamentos.

Espelha o que `_sync_schema()` + os backfills de boot fazem na subida do
servidor, para quem prefere aplicar no banco antes de trocar o código.

  1) colunas novas em equipamentos — responsavel (a worklist dizia o que estava
     incompleto sem dizer para quem cobrar), classe_risco, situacao_regulatoria,
     modelo, tecnologia e aplicacao (descritores previstos no plano)
  2) índice em equipamentos.sku + importacao_log — o SKU é a chave de junção do
     importador mestre, do Pareto e dos documentos, e a checagem de duplicidade
     consulta por ele; o log guarda o relatório completo de cada importação
  3) equipamento_historico     — trilha de-para (campo, antigo, novo, quem)
  4) equipamento_snapshot      — foto diária de ICE/IDP (série temporal)
  5) pareto_historico          — retrato de cada import do Pareto (tendência de
     demanda; antes o import sobrescrevia e zerava sem guardar nada)
  6) marco inicial do histórico + primeira foto dos índices

Idempotente. Uso: python migrations/009_equipamentos_evolucao.py [db_path]
"""
import sqlite3
import sys
from datetime import date, datetime
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

        # 1-2) colunas novas + indice da chave de juncao ───────────────────────
        for coluna in ("responsavel", "classe_risco", "situacao_regulatoria",
                       "modelo", "tecnologia", "aplicacao"):
            _add_col(cur, "equipamentos", coluna, "TEXT DEFAULT ''")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_equipamentos_sku "
                    "ON equipamentos (sku)")
        print("  = indice equipamentos.sku pronto")

        # registro das execucoes de importacao (relatorio completo em JSON)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS importacao_log (
                id              INTEGER PRIMARY KEY,
                origem          TEXT NOT NULL,
                por             TEXT DEFAULT '',
                em              TIMESTAMP,
                criados         INTEGER DEFAULT 0,
                atualizados     INTEGER DEFAULT 0,
                sem_match       INTEGER DEFAULT 0,
                inconsistencias INTEGER DEFAULT 0,
                relatorio       TEXT DEFAULT ''
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_importlog_em "
                    "ON importacao_log (em)")
        print("  = importacao_log pronta")

        # 3) trilha de-para ────────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS equipamento_historico (
                id             INTEGER PRIMARY KEY,
                equipamento_id INTEGER NOT NULL REFERENCES equipamentos(id),
                evento         TEXT DEFAULT 'update',
                campo          TEXT DEFAULT '',
                valor_antigo   TEXT DEFAULT '',
                valor_novo     TEXT DEFAULT '',
                em             TIMESTAMP,
                por            TEXT DEFAULT ''
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_eqhist_equipamento "
                    "ON equipamento_historico (equipamento_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_eqhist_em "
                    "ON equipamento_historico (em)")
        print("  = equipamento_historico pronta")

        # 4) foto diaria dos indices ───────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS equipamento_snapshot (
                id             INTEGER PRIMARY KEY,
                equipamento_id INTEGER NOT NULL REFERENCES equipamentos(id),
                data           TEXT NOT NULL,
                ice            INTEGER DEFAULT 0,
                cad            INTEGER DEFAULT 0,
                reg            INTEGER DEFAULT 0,
                doc            INTEGER DEFAULT 0,
                idp            INTEGER,
                docs_finais    INTEGER DEFAULT 0,
                docs_alvo      INTEGER DEFAULT 0,
                docs_atrasados INTEGER DEFAULT 0,
                criado_em      TIMESTAMP,
                CONSTRAINT uq_snapshot_equip_data UNIQUE (equipamento_id, data)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_eqsnap_data "
                    "ON equipamento_snapshot (data)")
        print("  = equipamento_snapshot pronta")

        # 5) historico do Pareto ───────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pareto_historico (
                id             INTEGER PRIMARY KEY,
                equipamento_id INTEGER NOT NULL REFERENCES equipamentos(id),
                data           TEXT NOT NULL,
                classe         TEXT DEFAULT '',
                qtd_saidas     INTEGER DEFAULT 0,
                criado_em      TIMESTAMP
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_paretohist_equipamento "
                    "ON pareto_historico (equipamento_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_paretohist_data "
                    "ON pareto_historico (data)")
        print("  = pareto_historico pronta")

        # Semente do historico do Pareto com o retrato atual, para a primeira
        # importacao ja ter contra o que comparar.
        cur.execute("SELECT COUNT(*) FROM pareto_historico")
        if cur.fetchone()[0] == 0:
            hoje = date.today().isoformat()
            cur.execute("SELECT id, COALESCE(pareto_classe, ''), COALESCE(qtd_saidas, 0) "
                        "  FROM equipamentos "
                        " WHERE ativo = 1 AND (COALESCE(pareto_classe,'') != '' "
                        "                      OR COALESCE(qtd_saidas,0) != 0)")
            linhas = cur.fetchall()
            for equip_id, classe, qtd in linhas:
                cur.execute("INSERT INTO pareto_historico (equipamento_id, data, "
                            "classe, qtd_saidas, criado_em) VALUES (?, ?, ?, ?, ?)",
                            (equip_id, hoje, classe, qtd, datetime.now()))
            print(f"  ~ retrato inicial do Pareto para {len(linhas)} equipamento(s)")

        # 6) marco inicial do historico (so quando a tabela esta vazia) ─────────
        cur.execute("SELECT COUNT(*) FROM equipamento_historico")
        if cur.fetchone()[0] == 0:
            agora = datetime.now().isoformat(sep=" ", timespec="seconds")
            cur.execute("SELECT id, COALESCE(nome, ''), "
                        "       COALESCE(updated_em, criado_em) "
                        "  FROM equipamentos WHERE ativo = 1")
            linhas = cur.fetchall()
            for equip_id, nome, em in linhas:
                cur.execute(
                    "INSERT INTO equipamento_historico (equipamento_id, evento, "
                    "campo, valor_antigo, valor_novo, em, por) "
                    "VALUES (?, 'create', 'nome', '', ?, ?, 'system')",
                    (equip_id, nome, em or agora))
            print(f"  ~ marco inicial criado para {len(linhas)} equipamento(s)")

        conn.commit()
    finally:
        conn.close()

    print("  i a primeira foto de ICE/IDP e gravada na subida do servidor "
          "(_snapshot_do_dia)")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 009 em {db}...")
    upgrade(db)
    print("OK")
