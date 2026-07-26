"""Migration 007: evolução do módulo de Projetos.

Espelha o que `_sync_schema()` faz na subida do servidor, para quem prefere
aplicar no banco antes de trocar o código.

  1) projetos.status              — ciclo de vida (planejado…cancelado)
  2) entregaveis.peso             — esforço relativo (avanço ponderado / EVM)
  3) entregaveis.data_inicio_prev / data_fim_prev — plano por tarefa (atrasos)
  4) modelos_entregavel.peso      — peso padrão do template
  5) entregavel_responsaveis      — N:N entregável ↔ usuário
  6) entregavel_historico         — trilha de status (curva-S fiel)
  7) projeto_snapshot             — foto diária dos indicadores
  8) projeto_baseline             — linha de base versionada (+ v1 retroativa)

Backfills: status deduzido dos arquivados pelo avanço, responsáveis ligados
pelo primeiro nome (só quando não há ambiguidade) e baseline v1 para todos.

Idempotente. Uso: python migrations/007_projetos_evolucao.py [db_path]
"""
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def _cols(cur, tabela):
    cur.execute(f"PRAGMA table_info({tabela})")
    return {row[1] for row in cur.fetchall()}


def _tabelas(cur):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in cur.fetchall()}


def _add_col(cur, tabela, nome, ddl):
    if nome in _cols(cur, tabela):
        print(f"  = {tabela}.{nome} ja existia")
        return False
    cur.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {ddl}")
    print(f"  + {tabela}.{nome} adicionada")
    return True


def _avanco(cur, projeto_id):
    """Avanço ponderado do projeto, na mesma regra do models.Projeto.avanco."""
    cur.execute("SELECT status, percentual, COALESCE(peso, 1) FROM entregaveis "
                "WHERE projeto_id = ?", (projeto_id,))
    soma = base = 0.0
    for status, pct, peso in cur.fetchall():
        if status == "na":
            continue
        peso = peso if peso and peso > 0 else 1.0
        base += peso
        if status == "concluido":
            soma += peso * 100
        elif status == "em_progresso":
            soma += peso * (pct or 0)
    return round(soma / base) if base else 0


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        tabs = _tabelas(cur)

        # 1-4) colunas novas ───────────────────────────────────────────────────
        novo_status = _add_col(cur, "projetos", "status",
                               "TEXT NOT NULL DEFAULT 'execucao'")
        _add_col(cur, "entregaveis", "peso", "REAL DEFAULT 1")
        _add_col(cur, "entregaveis", "data_inicio_prev", "TEXT DEFAULT ''")
        _add_col(cur, "entregaveis", "data_fim_prev", "TEXT DEFAULT ''")
        if "modelos_entregavel" in tabs:
            _add_col(cur, "modelos_entregavel", "peso", "REAL DEFAULT 1")

        # 5) responsáveis N:N ──────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entregavel_responsaveis (
                entregavel_id INTEGER NOT NULL REFERENCES entregaveis(id) ON DELETE CASCADE,
                user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                PRIMARY KEY (entregavel_id, user_id)
            )
        """)

        # 6) histórico de status ───────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entregavel_historico (
                id            INTEGER PRIMARY KEY,
                entregavel_id INTEGER NOT NULL REFERENCES entregaveis(id),
                status_antigo TEXT DEFAULT '',
                status_novo   TEXT DEFAULT '',
                percentual    INTEGER,
                em            TIMESTAMP,
                por           TEXT DEFAULT ''
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_hist_entregavel "
                    "ON entregavel_historico (entregavel_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_hist_em ON entregavel_historico (em)")

        # 7) snapshots diários ─────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projeto_snapshot (
                id           INTEGER PRIMARY KEY,
                projeto_id   INTEGER NOT NULL REFERENCES projetos(id),
                data         TEXT NOT NULL,
                avanco       INTEGER DEFAULT 0,
                pct_previsto INTEGER,
                spi          REAL,
                cpi          REAL,
                ac           REAL,
                bac          REAL,
                criado_em    TIMESTAMP,
                UNIQUE (projeto_id, data)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_snap_projeto "
                    "ON projeto_snapshot (projeto_id)")

        # 8) linha de base versionada ──────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projeto_baseline (
                id               INTEGER PRIMARY KEY,
                projeto_id       INTEGER NOT NULL REFERENCES projetos(id),
                versao           INTEGER NOT NULL DEFAULT 1,
                data_inicio_prev TEXT DEFAULT '',
                data_fim_prev    TEXT DEFAULT '',
                orcamento        REAL DEFAULT 0,
                motivo           TEXT DEFAULT '',
                criado_por       TEXT DEFAULT '',
                criado_em        TIMESTAMP,
                UNIQUE (projeto_id, versao)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_baseline_projeto "
                    "ON projeto_baseline (projeto_id)")
        print("  = tabelas de historico/snapshot/baseline prontas")

        # ── Backfill: ciclo de vida dos arquivados ────────────────────────────
        if novo_status:
            cur.execute("UPDATE projetos SET status = 'execucao' WHERE ativo = 1")
            cur.execute("SELECT id FROM projetos WHERE ativo = 0")
            arqs = [r[0] for r in cur.fetchall()]
            for pid in arqs:
                st = "concluido" if _avanco(cur, pid) >= 100 else "cancelado"
                cur.execute("UPDATE projetos SET status = ? WHERE id = ?", (st, pid))
            print(f"  ~ status deduzido para {len(arqs)} projeto(s) arquivado(s)")

        # ── Backfill: linha de base v1 ────────────────────────────────────────
        cur.execute("""
            SELECT p.id, p.data_inicio_prev, p.data_fim_prev, p.orcamento
              FROM projetos p
             WHERE NOT EXISTS (SELECT 1 FROM projeto_baseline b WHERE b.projeto_id = p.id)
        """)
        agora = datetime.now().isoformat(sep=" ", timespec="seconds")
        pend = cur.fetchall()
        for pid, ini, fim, orc in pend:
            cur.execute(
                "INSERT INTO projeto_baseline (projeto_id, versao, data_inicio_prev, "
                "data_fim_prev, orcamento, motivo, criado_por, criado_em) "
                "VALUES (?, 1, ?, ?, ?, ?, 'system', ?)",
                (pid, ini or "", fim or "", orc or 0.0,
                 "Linha de base inicial (migração)", agora))
        if pend:
            print(f"  ~ linha de base v1 criada para {len(pend)} projeto(s)")

        # ── Backfill: responsáveis texto → usuários ───────────────────────────
        cur.execute("SELECT COUNT(*) FROM entregavel_responsaveis")
        if cur.fetchone()[0] == 0:
            cur.execute("SELECT id, nome FROM users WHERE ativo = 1")
            por_primeiro = {}
            for uid, nome in cur.fetchall():
                chave = (nome or "").strip().split(" ")[0].lower()
                if chave:
                    por_primeiro.setdefault(chave, []).append(uid)

            cur.execute("SELECT id, responsaveis FROM entregaveis "
                        "WHERE responsaveis IS NOT NULL AND responsaveis != ''")
            ligados = 0
            for eid, texto in cur.fetchall():
                achados = []
                for parte in re.split(r"[/,;e&]| e ", (texto or "").lower()):
                    cands = por_primeiro.get(parte.strip()) or []
                    # nome ambiguo (dois "Carlos") nao e adivinhado: fica so texto
                    if len(cands) == 1 and cands[0] not in achados:
                        achados.append(cands[0])
                for uid in achados:
                    cur.execute("INSERT OR IGNORE INTO entregavel_responsaveis "
                                "(entregavel_id, user_id) VALUES (?, ?)", (eid, uid))
                if achados:
                    ligados += 1
            print(f"  ~ {ligados} entregavel(is) com responsaveis vinculados a usuarios")

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 007 em {db}...")
    upgrade(db)
    print("OK")
