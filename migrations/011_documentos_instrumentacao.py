"""Migration 011: instrumentação do módulo de Documentos.

Documento era o modelo menos instrumentado do sistema apesar de ser o maior
conjunto de dados. Gravava estado (status atual) e quase nenhum processo:
`updated_em` é sobrescrito a cada save, então "quanto tempo levou de Elaborar a
Homologado", "há quantos dias está parado" e "quantos foram concluídos em
março" não eram respondíveis sem varrer a trilha inteira. Missões (010) e
Entregáveis (007) já tinham recebido este passo.

Espelha o que `_sync_schema()` + `_backfill_marcos_documentos()` fazem na subida
do servidor, para quem prefere aplicar no banco antes de trocar o código.

  1) colunas novas em documentos  — concluido_em/por, entrou_status_em,
     data_inicio, peso
  2) documento_responsaveis       — N:N documento ↔ usuário (era o único módulo
     onde responsabilidade continuava sendo texto digitado)
  3) índice em audit_logs.timestamp — /api/audit ordena por esta coluna e fazia
     full scan + sort na tabela que mais cresce
  4) backfill dos marcos a partir de documento_historico (a trilha já registrava
     as trocas de status desde a migration 008 — só ninguém lia)

Idempotente. Uso: python migrations/011_documentos_instrumentacao.py [db_path]
"""
import sqlite3
import sys
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


# Status terminal por setor — mesma regra de Documento.status_global.
STATUS_FINAL = ("Homologado", "Concluído", "Concluido")


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        tabs = _tabelas(cur)
        if "documentos" not in tabs:
            print("  ! tabela documentos ainda nao existe (rode o servidor uma vez)")
            return

        # 1) colunas novas ────────────────────────────────────────────────────
        # SQLite nao aceita DEFAULT nao-constante em ADD COLUMN: os marcos
        # nascem nulos e sao preenchidos no backfill abaixo.
        _add_col(cur, "documentos", "concluido_em", "TIMESTAMP")
        _add_col(cur, "documentos", "concluido_por", "VARCHAR(120) DEFAULT ''")
        _add_col(cur, "documentos", "entrou_status_em", "TIMESTAMP")
        _add_col(cur, "documentos", "data_inicio", "DATE")
        _add_col(cur, "documentos", "peso", "FLOAT DEFAULT 1")

        cur.execute("CREATE INDEX IF NOT EXISTS ix_documentos_concluido_em "
                    "ON documentos (concluido_em)")

        # 2) responsaveis N:N ─────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documento_responsaveis (
                documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                PRIMARY KEY (documento_id, user_id)
            )
        """)
        print("  = documento_responsaveis pronta")

        # 3) indice da auditoria ──────────────────────────────────────────────
        if "audit_logs" in tabs:
            cur.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_timestamp "
                        "ON audit_logs (timestamp)")
            print("  = ix_audit_logs_timestamp pronto")

        # 4) backfill dos marcos ──────────────────────────────────────────────
        # entrou_status_em: a ultima troca de status registrada na trilha; sem
        # trilha, cai em updated_em/criado_em (o limite superior conhecido — nao
        # inventa data futura).
        if "documento_historico" in tabs:
            cur.execute("""
                UPDATE documentos
                   SET entrou_status_em = COALESCE(
                       (SELECT MAX(h.em) FROM documento_historico h
                         WHERE h.documento_id = documentos.id
                           AND COALESCE(h.evento, 'status') = 'status'),
                       updated_em, criado_em)
                 WHERE entrou_status_em IS NULL
            """)
            print(f"  ~ entrou_status_em preenchido em {cur.rowcount} documento(s)")

            # concluido_em SÓ de transicao real (status_antigo preenchido). O
            # marco de migracao gravado por _backfill_historico_documentos tem
            # status_antigo='' e a data de updated_em; aceita-lo aqui inventaria
            # throughput -- todos os documentos ja concluidos apareceriam como
            # "concluidos nos ultimos 30 dias" com tempo de ciclo zero.
            # Concluido antes de existir instrumentacao = data DESCONHECIDA.
            marcadores = ",".join("?" for _ in STATUS_FINAL)
            cur.execute(f"""
                UPDATE documentos
                   SET concluido_em =
                       (SELECT MAX(h.em) FROM documento_historico h
                         WHERE h.documento_id = documentos.id
                           AND h.status_novo IN ({marcadores})
                           AND COALESCE(h.status_antigo, '') != '')
                 WHERE concluido_em IS NULL
                   AND status IN ({marcadores})
            """, STATUS_FINAL + STATUS_FINAL)
            print(f"  ~ concluido_em preenchido em {cur.rowcount} documento(s) concluido(s)")

            # Corrige bancos que passaram por uma versao anterior desta migration,
            # que aceitava o marco de migracao como data de conclusao.
            cur.execute(f"""
                UPDATE documentos
                   SET concluido_em = NULL, concluido_por = ''
                 WHERE concluido_em IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM documento_historico h
                                    WHERE h.documento_id = documentos.id
                                      AND h.status_novo IN ({marcadores})
                                      AND COALESCE(h.status_antigo, '') != '')
            """, STATUS_FINAL)
            if cur.rowcount:
                print(f"  ~ data de conclusao sintetica removida de {cur.rowcount} documento(s)")
        else:
            cur.execute("UPDATE documentos SET entrou_status_em = "
                        "COALESCE(updated_em, criado_em) WHERE entrou_status_em IS NULL")
            print(f"  ~ entrou_status_em preenchido em {cur.rowcount} documento(s) (sem trilha)")

        cur.execute("UPDATE documentos SET peso = 1 WHERE peso IS NULL")

        # Responsaveis: liga o texto livre aos usuarios reais por nome COMPLETO
        # exato. Casar por primeiro nome reintroduziria a colisao que o N:N veio
        # corrigir ("Ana" casando com "Mariana").
        cur.execute("SELECT COUNT(*) FROM documento_responsaveis")
        if cur.fetchone()[0] == 0:
            cur.execute("SELECT id, nome FROM users WHERE ativo = 1")
            por_nome = {}
            for uid, nome in cur.fetchall():
                chave = (nome or "").strip().lower()
                if chave:
                    por_nome.setdefault(chave, []).append(uid)
            cur.execute("SELECT id, responsavel FROM documentos "
                        "WHERE responsavel IS NOT NULL AND responsavel != ''")
            ligados = 0
            for did, texto in cur.fetchall():
                achou = False
                for parte in (texto or "").split(","):
                    cands = por_nome.get(parte.strip().lower()) or []
                    if len(cands) == 1:
                        cur.execute("INSERT OR IGNORE INTO documento_responsaveis "
                                    "(documento_id, user_id) VALUES (?, ?)",
                                    (did, cands[0]))
                        achou = True
                if achou:
                    ligados += 1
            print(f"  ~ {ligados} documento(s) com responsavel vinculado a usuario")

        conn.commit()
    finally:
        conn.close()

    print("  i as metricas de fluxo ficam em GET /api/documentos/metricas")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 011 em {db}...")
    upgrade(db)
    print("OK")
