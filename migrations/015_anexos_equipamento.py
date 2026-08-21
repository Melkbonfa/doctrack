"""Migration 015: anexos do equipamento (docs agregados + software/firmware).

Cria a tabela `equipamento_arquivos` — arquivos pendurados no EQUIPAMENTO, e não
em um dos 12 tipos de documento:

  * categoria 'agregado'            — laudo, certificado, datasheet
  * categoria 'software'/'firmware' — repositório de versões do fabricante

Nada é migrado de `documento_arquivos`: as duas tabelas coexistem e respondem por
coisas diferentes. O blob em disco, esse sim, é compartilhado — o mesmo PDF
enviado nos dois lugares ocupa um arquivo só, e por isso a remoção consulta as
DUAS tabelas antes de apagar (ver `documentos._sha_orfao`).

Espelha o que `db.create_all()` faz na subida do servidor, para quem prefere
aplicar no banco antes de trocar o código. Idempotente.

Uso: python migrations/015_anexos_equipamento.py [db_path]
"""
import sqlite3
import sys
from pathlib import Path


def _tabelas(cur):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in cur.fetchall()}


DDL_ANEXOS = """
CREATE TABLE equipamento_arquivos (
    id INTEGER PRIMARY KEY,
    equipamento_id INTEGER NOT NULL REFERENCES equipamentos(id),
    categoria VARCHAR(20) DEFAULT 'agregado' NOT NULL,
    titulo VARCHAR(200) DEFAULT '',
    versao_rotulo VARCHAR(60) DEFAULT '',
    data_release VARCHAR(10) DEFAULT '',
    notas TEXT DEFAULT '',
    sha256 VARCHAR(64) NOT NULL,
    nome_original VARCHAR(300) DEFAULT '' NOT NULL,
    ext VARCHAR(10) DEFAULT '',
    mime VARCHAR(120) DEFAULT '',
    tamanho INTEGER DEFAULT 0,
    enviado_por VARCHAR(120) DEFAULT '',
    enviado_em TIMESTAMP,
    ativo BOOLEAN DEFAULT 1 NOT NULL
)
"""

INDICES = [
    ("ix_equip_arq_equipamento", "equipamento_arquivos", "equipamento_id"),
    ("ix_equip_arq_categoria",   "equipamento_arquivos", "categoria"),
    # sha256 é consultado a cada remoção (o blob só sai quando fica órfão).
    ("ix_equip_arq_sha",         "equipamento_arquivos", "sha256"),
    ("ix_equip_arq_enviado",     "equipamento_arquivos", "enviado_em"),
    ("ix_equip_arq_ativo",       "equipamento_arquivos", "ativo"),
]


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        tabs = _tabelas(cur)
        if "equipamentos" not in tabs:
            print("  ! equipamentos ainda nao existe (rode o servidor uma vez)")
            return

        if "equipamento_arquivos" in tabs:
            print("  = equipamento_arquivos ja existia")
        else:
            cur.execute(DDL_ANEXOS)
            print("  + equipamento_arquivos criada")

        for nome, tabela, colunas in INDICES:
            cur.execute(f"CREATE INDEX IF NOT EXISTS {nome} ON {tabela}({colunas})")
        print(f"  = {len(INDICES)} indice(s) garantidos")

        conn.commit()
    finally:
        conn.close()

    print("  i as duas abas novas aparecem no card do equipamento (modulo Documentos)")
    print("  i binario de software/firmware tem teto proprio: "
          "DOCTRACK_UPLOAD_BIN_MAX_MB (padrao 500)")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 015 em {db}...")
    upgrade(db)
    print("OK")
