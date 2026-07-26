"""Migration 010: evolução do módulo de Missões.

Missões era o único módulo que nunca recebeu esse passo: gravava estado, não
gravava processo. Sem `criado_em` nem trilha, nada de fluxo era calculável —
nem a idade de um cartão.

Espelha o que `_sync_schema()` faz na subida do servidor, para quem prefere
aplicar no banco antes de trocar o código.

  1) missao_colunas.limite_wip     — limite de trabalho em progresso (0 = sem)
  2) colunas novas em missao_cartoes — criado_em, concluido_em/por,
     entrou_coluna_em, data_inicio, peso, recorrencia
  3) índice (ref_tipo, ref_id)     — cartoes-vinculados é chamado a cada ficha
     aberta no dashboard e fazia full scan
  4) missao_cartao_responsaveis    — N:N cartão ↔ usuário (o ILIKE por nome
     casava "Ana" com "Mariana" e se perdia ao renomear o usuário)
  5) missao_cartao_historico       — série temporal do fluxo (cycle time, aging,
     throughput, tempo por coluna)
  6) missao_snapshot               — foto diária dos indicadores
  7) missao_cartao_itens / _comentarios — checklist e comentários (Planner)
  8) missao_modelos                — templates de missão
  9) backfills: marcos temporais deduzidos, responsáveis ligados por nome exato
     e marco inicial da trilha

Idempotente. Uso: python migrations/010_missoes_evolucao.py [db_path]
"""
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


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        tabs = _tabelas(cur)
        if "missao_cartoes" not in tabs:
            print("  ! tabelas de missoes ainda nao existem (rode o servidor uma vez)")
            return

        # 1-2) colunas novas ───────────────────────────────────────────────────
        _add_col(cur, "missao_colunas", "limite_wip", "INTEGER DEFAULT 0")
        # SQLite nao aceita DEFAULT nao-constante em ADD COLUMN: os marcos
        # temporais nascem nulos e sao preenchidos no backfill abaixo.
        novo_criado = _add_col(cur, "missao_cartoes", "criado_em", "TIMESTAMP")
        _add_col(cur, "missao_cartoes", "concluido_em", "TIMESTAMP")
        _add_col(cur, "missao_cartoes", "concluido_por", "VARCHAR(120) DEFAULT ''")
        _add_col(cur, "missao_cartoes", "entrou_coluna_em", "TIMESTAMP")
        _add_col(cur, "missao_cartoes", "data_inicio", "VARCHAR(40) DEFAULT ''")
        _add_col(cur, "missao_cartoes", "peso", "FLOAT DEFAULT 1")
        _add_col(cur, "missao_cartoes", "recorrencia", "VARCHAR(20) DEFAULT ''")

        # 3) indice do vinculo ─────────────────────────────────────────────────
        cur.execute("CREATE INDEX IF NOT EXISTS ix_missao_cartoes_ref "
                    "ON missao_cartoes (ref_tipo, ref_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_missao_cartoes_criado_em "
                    "ON missao_cartoes (criado_em)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_missao_cartoes_concluido_em "
                    "ON missao_cartoes (concluido_em)")
        print("  = indices de missao_cartoes prontos")

        # 4) responsaveis N:N ──────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS missao_cartao_responsaveis (
                cartao_id INTEGER NOT NULL REFERENCES missao_cartoes(id) ON DELETE CASCADE,
                user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                PRIMARY KEY (cartao_id, user_id)
            )
        """)

        # 5) trilha temporal do cartao ─────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS missao_cartao_historico (
                id                INTEGER PRIMARY KEY,
                cartao_id         INTEGER NOT NULL REFERENCES missao_cartoes(id) ON DELETE CASCADE,
                missao_id         INTEGER NOT NULL REFERENCES missoes(id),
                evento            TEXT DEFAULT 'campo',
                coluna_origem_id  INTEGER,
                coluna_destino_id INTEGER,
                campo             TEXT DEFAULT '',
                valor_antigo      TEXT DEFAULT '',
                valor_novo        TEXT DEFAULT '',
                origem            TEXT DEFAULT 'manual',
                em                TIMESTAMP,
                por               TEXT DEFAULT ''
            )
        """)
        for ddl in (
            "CREATE INDEX IF NOT EXISTS ix_mchist_cartao ON missao_cartao_historico (cartao_id)",
            "CREATE INDEX IF NOT EXISTS ix_mchist_missao ON missao_cartao_historico (missao_id)",
            "CREATE INDEX IF NOT EXISTS ix_mchist_em     ON missao_cartao_historico (em)",
            "CREATE INDEX IF NOT EXISTS ix_mchist_evento ON missao_cartao_historico (evento)",
        ):
            cur.execute(ddl)
        print("  = missao_cartao_historico pronta")

        # 6) foto diaria ───────────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS missao_snapshot (
                id              INTEGER PRIMARY KEY,
                missao_id       INTEGER NOT NULL REFERENCES missoes(id),
                data            TEXT NOT NULL,
                total           INTEGER DEFAULT 0,
                abertos         INTEGER DEFAULT 0,
                concluidos      INTEGER DEFAULT 0,
                atrasados       INTEGER DEFAULT 0,
                wip             INTEGER DEFAULT 0,
                sem_responsavel INTEGER DEFAULT 0,
                peso_total      FLOAT DEFAULT 0,
                peso_concluido  FLOAT DEFAULT 0,
                criado_em       TIMESTAMP,
                CONSTRAINT uq_missao_snapshot_dia UNIQUE (missao_id, data)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_msnap_data ON missao_snapshot (data)")
        print("  = missao_snapshot pronta")

        # 7) checklist e comentarios ───────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS missao_cartao_itens (
                id        INTEGER PRIMARY KEY,
                cartao_id INTEGER NOT NULL REFERENCES missao_cartoes(id) ON DELETE CASCADE,
                texto     TEXT NOT NULL,
                feito     BOOLEAN DEFAULT 0,
                ordem     INTEGER DEFAULT 0,
                criado_em TIMESTAMP
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_mcitem_cartao "
                    "ON missao_cartao_itens (cartao_id)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS missao_cartao_comentarios (
                id        INTEGER PRIMARY KEY,
                cartao_id INTEGER NOT NULL REFERENCES missao_cartoes(id) ON DELETE CASCADE,
                texto     TEXT NOT NULL,
                por       TEXT DEFAULT '',
                em        TIMESTAMP
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_mccom_cartao "
                    "ON missao_cartao_comentarios (cartao_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_mccom_em "
                    "ON missao_cartao_comentarios (em)")
        print("  = checklist e comentarios prontos")

        # 8) modelos de missao ─────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS missao_modelos (
                id         INTEGER PRIMARY KEY,
                nome       TEXT NOT NULL,
                descricao  TEXT DEFAULT '',
                accent     TEXT DEFAULT '',
                estrutura  TEXT DEFAULT '[]',
                criado_por TEXT DEFAULT '',
                criado_em  TIMESTAMP
            )
        """)
        print("  = missao_modelos pronta")

        # ── Backfill: marcos temporais ────────────────────────────────────────
        # A criacao real nao existe em lugar nenhum; `atualizado_em` e o limite
        # superior conhecido e nao inventa data futura.
        cur.execute("UPDATE missao_cartoes SET criado_em = atualizado_em "
                    "WHERE criado_em IS NULL")
        n_criado = cur.rowcount
        cur.execute("UPDATE missao_cartoes SET entrou_coluna_em = "
                    "COALESCE(atualizado_em, criado_em) WHERE entrou_coluna_em IS NULL")
        cur.execute("UPDATE missao_cartoes SET concluido_em = atualizado_em "
                    "WHERE concluido = 1 AND concluido_em IS NULL")
        n_conc = cur.rowcount
        cur.execute("UPDATE missao_cartoes SET peso = 1 WHERE peso IS NULL")
        if n_criado or n_conc:
            print(f"  ~ marcos temporais preenchidos: {n_criado} criacao(oes), "
                  f"{n_conc} conclusao(oes)")

        # ── Backfill: responsaveis texto → usuarios ───────────────────────────
        cur.execute("SELECT COUNT(*) FROM missao_cartao_responsaveis")
        if cur.fetchone()[0] == 0:
            cur.execute("SELECT id, nome FROM users WHERE ativo = 1")
            # nome completo, comparacao exata: o CSV do cartao e preenchido pelo
            # seletor de usuarios, entao bate 1:1. Adivinhar por primeiro nome
            # aqui reintroduziria a colisao que a tabela veio corrigir.
            por_nome = {}
            for uid, nome in cur.fetchall():
                chave = (nome or "").strip().lower()
                if chave:
                    por_nome.setdefault(chave, []).append(uid)
            cur.execute("SELECT id, responsaveis FROM missao_cartoes "
                        "WHERE responsaveis IS NOT NULL AND responsaveis != ''")
            ligados = 0
            for cid, texto in cur.fetchall():
                achou = False
                for parte in (texto or "").split(","):
                    cands = por_nome.get(parte.strip().lower()) or []
                    if len(cands) == 1:
                        cur.execute("INSERT OR IGNORE INTO missao_cartao_responsaveis "
                                    "(cartao_id, user_id) VALUES (?, ?)", (cid, cands[0]))
                        achou = True
                if achou:
                    ligados += 1
            print(f"  ~ {ligados} cartao(oes) com responsaveis vinculados a usuarios")

        # ── Backfill: marco inicial da trilha ─────────────────────────────────
        cur.execute("SELECT COUNT(*) FROM missao_cartao_historico")
        if cur.fetchone()[0] == 0:
            agora = datetime.now().isoformat(sep=" ", timespec="seconds")
            cur.execute("SELECT id, missao_id, coluna_id, COALESCE(titulo, ''), "
                        "       COALESCE(criado_em, atualizado_em) "
                        "  FROM missao_cartoes")
            linhas = cur.fetchall()
            for cid, mid, col, titulo, em in linhas:
                cur.execute(
                    "INSERT INTO missao_cartao_historico (cartao_id, missao_id, evento, "
                    "coluna_destino_id, campo, valor_antigo, valor_novo, origem, em, por) "
                    "VALUES (?, ?, 'criado', ?, 'titulo', '', ?, 'migracao', ?, 'system')",
                    (cid, mid, col, titulo, em or agora))
            print(f"  ~ marco inicial criado para {len(linhas)} cartao(oes)")

        conn.commit()
    finally:
        conn.close()

    print("  i a primeira foto diaria e gravada na subida do servidor "
          "(_snapshot_missoes_do_dia)")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 010 em {db}...")
    upgrade(db)
    print("OK")
