"""Migration 020: vínculo entre entregável e item de modelo + histórico de
mudanças de modelo.

Até aqui o projeto copiava o modelo ao nascer e o vínculo se perdia. Para um
admin poder levar uma mudança do modelo aos projetos existentes (ver
modelo_sync.py), cada entregável passa a guardar de que item veio e com que
valores:

  modelos_entregavel.chave      identificador permanente do item (o id pode ser
                                reaproveitado pelo banco depois de um DELETE)
  entregaveis.modelo_chave      chave do item de origem ('' = avulso)
  entregaveis.modelo_origem     JSON com nome/categoria/peso/responsável que o
                                modelo tinha na última criação/aplicação

Os entregáveis existentes são ligados pelo nome (categoria + nome, sem
diferenciar maiúsculas) ao modelo do projeto; o que não casar vira avulso.
Cria também `mudancas_modelo` e `mudancas_modelo_itens` (o histórico).

Espelha o que `db.create_all()` + `servidor._sync_schema()` +
`servidor._vincular_entregaveis_ao_modelo()` fazem na subida do servidor, para
quem prefere aplicar no banco antes de trocar o código. Idempotente.

Uso: python migrations/020_vinculo_modelo.py [db_path]
"""
import json
import secrets
import sqlite3
import sys
from pathlib import Path

DDL = {
    "mudancas_modelo": """
CREATE TABLE mudancas_modelo (
    id INTEGER PRIMARY KEY,
    tipo_projeto VARCHAR(20) NOT NULL,
    motivo VARCHAR(500) NOT NULL,
    feito_por VARCHAR(120),
    feito_em TIMESTAMP,
    n_projetos INTEGER,
    n_alteracoes INTEGER
)""",
    "mudancas_modelo_itens": """
CREATE TABLE mudancas_modelo_itens (
    id INTEGER PRIMARY KEY,
    mudanca_id INTEGER NOT NULL REFERENCES mudancas_modelo (id),
    projeto_id INTEGER,
    projeto_nome VARCHAR(200),
    entregavel_id INTEGER,
    entregavel VARCHAR(120),
    acao VARCHAR(20) NOT NULL,
    campo VARCHAR(20),
    antes VARCHAR(300),
    depois VARCHAR(300)
)""",
}
INDICES = [
    ("ix_mudancas_modelo_tipo_projeto", "mudancas_modelo", "tipo_projeto"),
    ("ix_mudancas_modelo_feito_em", "mudancas_modelo", "feito_em"),
    ("ix_mudancas_modelo_itens_mudanca_id", "mudancas_modelo_itens", "mudanca_id"),
    ("ix_mudancas_modelo_itens_projeto_id", "mudancas_modelo_itens", "projeto_id"),
    ("ix_entregaveis_modelo_chave", "entregaveis", "modelo_chave"),
    ("ix_modelos_entregavel_chave", "modelos_entregavel", "chave"),
]


def _tabelas(cur):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in cur.fetchall()}


def _colunas(cur, tabela):
    cur.execute(f"PRAGMA table_info({tabela})")
    return {r[1] for r in cur.fetchall()}


def _peso(v):
    try:
        return round(float(v if v is not None else 1.0), 4)
    except (TypeError, ValueError):
        return 1.0


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        tabs = _tabelas(cur)
        for tabela, ddl in DDL.items():
            if tabela in tabs:
                print(f"  = {tabela} ja existia")
            else:
                cur.execute(ddl)
                print(f"  + {tabela} criada")

        colunas = [("modelos_entregavel", "chave", "VARCHAR(32)"),
                   ("entregaveis", "modelo_chave", "VARCHAR(32) DEFAULT ''"),
                   ("entregaveis", "modelo_origem", "TEXT")]   # sem default: NULL = a avaliar
        for tabela, nome, ddl in colunas:
            if nome in _colunas(cur, tabela):
                print(f"  = {tabela}.{nome} ja existia")
            else:
                cur.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {ddl}")
                print(f"  + {tabela}.{nome} adicionada")
        for nome_idx, tabela, coluna in INDICES:
            cur.execute(f"CREATE INDEX IF NOT EXISTS {nome_idx} ON {tabela} ({coluna})")

        cur.execute("SELECT id FROM modelos_entregavel WHERE chave IS NULL OR chave = ''")
        sem_chave = [r[0] for r in cur.fetchall()]
        for mid in sem_chave:
            cur.execute("UPDATE modelos_entregavel SET chave = ? WHERE id = ?",
                        (secrets.token_hex(16), mid))
        print(f"  ~ {len(sem_chave)} item(ns) de modelo com chave nova")

        cur.execute("SELECT id, tipo_projeto, categoria, tipo, peso, responsavel_padrao, chave "
                    "FROM modelos_entregavel ORDER BY tipo_projeto, ordem, id")
        modelos = {}
        for mid, tp, cat, nome, peso, resp, chave in cur.fetchall():
            modelos.setdefault(tp, []).append({
                "chave": chave, "tipo": (nome or "").strip(), "categoria": cat or "",
                "peso": _peso(peso), "responsavel": (resp or "").strip()})

        cur.execute("SELECT e.id, e.projeto_id, e.categoria, e.tipo, p.tipo "
                    "FROM entregaveis e JOIN projetos p ON p.id = e.projeto_id "
                    "WHERE e.modelo_origem IS NULL ORDER BY e.projeto_id, e.ordem, e.id")
        pendentes = cur.fetchall()
        ligados = avulsos = 0
        livres_por_projeto = {}
        for eid, pid, cat, nome, tipo_proj in pendentes:
            if pid not in livres_por_projeto:
                cur.execute("SELECT modelo_chave FROM entregaveis WHERE projeto_id = ? "
                            "AND modelo_chave IS NOT NULL AND modelo_chave != ''", (pid,))
                ja = {r[0] for r in cur.fetchall()}
                livres = {}
                for m in modelos.get(tipo_proj or "", []):
                    if m["chave"] not in ja:
                        livres.setdefault((m["categoria"].lower(), m["tipo"].lower()), m)
                livres_por_projeto[pid] = livres
            m = livres_por_projeto[pid].pop(((cat or "").lower(), (nome or "").strip().lower()), None)
            if m:
                origem = {k: m[k] for k in ("tipo", "categoria", "peso", "responsavel")}
                cur.execute("UPDATE entregaveis SET modelo_chave = ?, modelo_origem = ? WHERE id = ?",
                            (m["chave"], json.dumps(origem, ensure_ascii=False), eid))
                ligados += 1
            else:
                cur.execute("UPDATE entregaveis SET modelo_chave = '', modelo_origem = '' "
                            "WHERE id = ?", (eid,))
                avulsos += 1
        print(f"  ~ {ligados} entregavel(is) ligado(s) ao modelo, {avulsos} avulso(s)")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 020 em {db}...")
    upgrade(db)
    print("OK")
