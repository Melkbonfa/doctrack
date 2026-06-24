# ============================================================================
#  migrar_sqlite_para_postgres.py
# ----------------------------------------------------------------------------
#  Copia TODOS os dados do banco local (SQLite, doctrack.db) para o
#  PostgreSQL de producao (lido do DATABASE_URL no .env).
#
#  O destino (PostgreSQL) e ESPELHADO pela origem: cada tabela e esvaziada
#  (TRUNCATE ... RESTART IDENTITY CASCADE) e recarregada com os dados do
#  SQLite, preservando os IDs e as relacoes. As sequencias sao reajustadas
#  no final.
#
#  Como usar (NO SERVIDOR, dentro de C:\apps\doctrack):
#    1. Copie o doctrack.db da sua maquina para esta pasta.
#    2. Previa (so leitura, nao altera nada):
#         .\venv\Scripts\python.exe migrar_sqlite_para_postgres.py
#    3. Executar de verdade:
#         .\venv\Scripts\python.exe migrar_sqlite_para_postgres.py --go
#
#  Origem alternativa: passe o caminho do .db como 1o argumento.
# ============================================================================
import os
import sys
from datetime import datetime, date

from dotenv import load_dotenv
from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.types import Boolean, DateTime, Date

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"))

# 1o argumento (que nao seja a flag) = caminho do SQLite de origem
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
SQLITE_PATH = _args[0] if _args else os.path.join(BASE, "doctrack.db")
EXECUTAR = "--go" in sys.argv

PG_URL = os.environ.get("DATABASE_URL", "")

# Ordem que respeita as chaves estrangeiras (pais antes dos filhos).
# Tabelas ausentes em qualquer um dos lados sao ignoradas com aviso.
ORDEM = [
    "users",
    "projetos",
    "documentos",
    "modelos_entregavel",
    "responsaveis",
    "entregaveis",
    "projeto_mensal",
    "audit_logs",
    "revoked_tokens",
]


def erro(msg):
    print(f"\n[ERRO] {msg}")
    sys.exit(1)


if not os.path.exists(SQLITE_PATH):
    erro(f"Arquivo de origem nao encontrado: {SQLITE_PATH}")
if not PG_URL:
    erro("DATABASE_URL nao definido no .env")
if not PG_URL.startswith("postgresql"):
    erro(f"DATABASE_URL nao aponta para PostgreSQL: {PG_URL.split('@')[0]}...")

src = create_engine(f"sqlite:///{SQLITE_PATH}")
dst = create_engine(PG_URL)

src_md = MetaData()
src_md.reflect(bind=src)
dst_md = MetaData()
dst_md.reflect(bind=dst)


def coerce(value, coltype):
    """Ajusta valores do SQLite (0/1, strings de data) para os tipos do PostgreSQL."""
    if value is None:
        return None
    if isinstance(coltype, Boolean):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "t", "yes", "sim")
        return bool(value)
    if isinstance(coltype, (DateTime, Date)):
        if isinstance(value, str):
            v = value.strip()
            if not v:
                return None
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(v, fmt)
                    # Date puro (nao DateTime) -> devolve só a data
                    if isinstance(coltype, Date) and not isinstance(coltype, DateTime):
                        return dt.date()
                    return dt
                except ValueError:
                    continue
            return v  # deixa o driver tentar
    return value


# --- Previa / contagem ------------------------------------------------------
print("=" * 64)
print("  MIGRACAO SQLite -> PostgreSQL")
print("=" * 64)
print(f"  Origem  (SQLite)    : {SQLITE_PATH}")
print(f"  Destino (PostgreSQL): {PG_URL.split('@')[-1]}")
print("-" * 64)
print(f"  {'tabela':<22}{'origem':>10}{'destino':>10}")
print("-" * 64)

tabelas = []
with src.connect() as sc, dst.connect() as dc:
    for nome in ORDEM:
        if nome not in src_md.tables:
            print(f"  {nome:<22}{'(ausente na origem)':>20}")
            continue
        if nome not in dst_md.tables:
            print(f"  {nome:<22}{'(ausente no destino)':>20}")
            continue
        n_src = sc.execute(text(f"SELECT count(*) FROM {nome}")).scalar()
        n_dst = dc.execute(text(f"SELECT count(*) FROM {nome}")).scalar()
        print(f"  {nome:<22}{n_src:>10}{n_dst:>10}")
        tabelas.append(nome)

print("-" * 64)

if not EXECUTAR:
    print("\n  PREVIA (nada foi alterado).")
    print("  Para EXECUTAR a migracao (apaga o destino e recarrega):")
    print(f"    python {os.path.basename(__file__)} --go\n")
    sys.exit(0)

# --- Execucao ---------------------------------------------------------------
print("\n  Executando migracao (--go)...\n")

with src.connect() as sc, dst.begin() as conn:
    # Esvazia tudo de uma vez (CASCADE resolve a ordem das FKs).
    conn.execute(text(
        "TRUNCATE TABLE " + ", ".join(tabelas) + " RESTART IDENTITY CASCADE"
    ))

    for nome in tabelas:
        s_tbl = src_md.tables[nome]
        d_tbl = dst_md.tables[nome]
        comuns = [c.name for c in d_tbl.columns if c.name in s_tbl.columns]

        linhas = sc.execute(s_tbl.select()).mappings().all()
        if not linhas:
            print(f"  {nome:<22} 0 linhas")
            continue

        dados = [
            {c: coerce(r[c], d_tbl.c[c].type) for c in comuns}
            for r in linhas
        ]
        conn.execute(d_tbl.insert(), dados)
        print(f"  {nome:<22} {len(dados)} inseridas")

    # Reajusta as sequencias (proximo id = max+1) para tabelas com 'id'.
    print("\n  Reajustando sequencias...")
    for nome in tabelas:
        if "id" in dst_md.tables[nome].columns:
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{nome}', 'id'), "
                f"GREATEST((SELECT COALESCE(MAX(id), 1) FROM {nome}), 1))"
            ))

print("\n  [OK] Migracao concluida. Reinicie o servico: nssm restart DocTrack\n")
