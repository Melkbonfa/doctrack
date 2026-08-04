"""Migration 012: módulo Custos (formação de custo de produto e projeto).

Cria as quatro tabelas do módulo:

  custo_composicoes — a folha de custo de um produto: identidade, parâmetros e a
                      taxa de câmbio travada (com data, autor e justificativa).
  custo_lancamentos — as linhas, separadas por natureza (NRE × COGS), cada uma
                      com procedência, confiança e a taxa congelada na conversão.
  custo_cotacoes    — série de câmbio (PTAX do BCB ou registro manual), única por
                      (moeda, data, tipo) para que a sincronização diária seja
                      idempotente.
  custo_versoes     — baseline congelado; a v1 é o estimado contra o qual o
                      realizado da DI é medido.

Valores em NUMERIC(14,2) e taxas em NUMERIC(14,6) — divergência deliberada do
resto da base, que usa FLOAT para dinheiro. A aritmética aqui é encadeada
(câmbio × alíquota × rateio × margem) e o erro de ponto flutuante se acumula.

Espelha o que `db.create_all()` faz na subida do servidor, para quem prefere
aplicar no banco antes de trocar o código. Idempotente.

Uso: python migrations/012_modulo_custos.py [db_path]
"""
import sqlite3
import sys
from pathlib import Path


def _tabelas(cur):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in cur.fetchall()}


def _cria(cur, nome, ddl, existentes):
    if nome in existentes:
        print(f"  = {nome} ja existia")
        return False
    cur.execute(ddl)
    print(f"  + {nome} criada")
    return True


DDL_COMPOSICOES = """
CREATE TABLE custo_composicoes (
    id INTEGER PRIMARY KEY,
    codigo VARCHAR(30) DEFAULT '',
    produto VARCHAR(200) NOT NULL,
    sku VARCHAR(50) DEFAULT '',
    projeto_id INTEGER REFERENCES projetos(id),
    equipamento_id INTEGER REFERENCES equipamentos(id),
    fornecedor VARCHAR(200) DEFAULT '',
    tipo VARCHAR(20) DEFAULT 'OEM',
    incoterm VARCHAR(10) DEFAULT 'FOB',
    moeda_base VARCHAR(3) DEFAULT 'USD',
    status VARCHAR(20) DEFAULT 'rascunho' NOT NULL,
    versao INTEGER DEFAULT 1 NOT NULL,
    valor_fob NUMERIC(14, 2) DEFAULT 0,
    qtd_invoice INTEGER DEFAULT 1,
    volume_projetado INTEGER DEFAULT 1,
    preco_venda NUMERIC(14, 2),
    custo_hora_engenharia NUMERIC(14, 2) DEFAULT 0,
    custo_hora_producao NUMERIC(14, 2) DEFAULT 0,
    reserva_cambial_pct NUMERIC(8, 4) DEFAULT 10,
    taxa_planejamento NUMERIC(14, 6) DEFAULT 1,
    taxa_planejamento_data VARCHAR(10) DEFAULT '',
    taxa_planejamento_autor VARCHAR(120) DEFAULT '',
    taxa_planejamento_justificativa TEXT DEFAULT '',
    taxa_realizada NUMERIC(14, 6),
    di_numero VARCHAR(40) DEFAULT '',
    di_data VARCHAR(10) DEFAULT '',
    observacoes TEXT DEFAULT '',
    ativo BOOLEAN DEFAULT 1 NOT NULL,
    criado_em TIMESTAMP,
    criado_por VARCHAR(120) DEFAULT '',
    updated_em TIMESTAMP
)
"""

DDL_LANCAMENTOS = """
CREATE TABLE custo_lancamentos (
    id INTEGER PRIMARY KEY,
    composicao_id INTEGER NOT NULL REFERENCES custo_composicoes(id),
    ordem INTEGER DEFAULT 0,
    natureza VARCHAR(10) DEFAULT 'cogs' NOT NULL,
    categoria VARCHAR(60) DEFAULT '',
    subcategoria VARCHAR(120) DEFAULT '',
    descricao VARCHAR(300) DEFAULT '',
    observacao TEXT DEFAULT '',
    aplicavel BOOLEAN DEFAULT 1 NOT NULL,
    tipo_calculo VARCHAR(20) DEFAULT 'montante' NOT NULL,
    moeda VARCHAR(3) DEFAULT 'BRL',
    valor_moeda NUMERIC(14, 2) DEFAULT 0,
    horas NUMERIC(10, 2) DEFAULT 0,
    perfil_hora VARCHAR(10) DEFAULT '',
    aliquota NUMERIC(8, 4) DEFAULT 0,
    taxa_aplicada NUMERIC(14, 6),
    taxa_data VARCHAR(10) DEFAULT '',
    taxa_fonte VARCHAR(20) DEFAULT '',
    valor_brl NUMERIC(14, 2) DEFAULT 0,
    procedencia VARCHAR(20) DEFAULT 'estimativa',
    confianca VARCHAR(10) DEFAULT 'media',
    realizado_valor_brl NUMERIC(14, 2),
    realizado_data VARCHAR(10) DEFAULT '',
    realizado_doc VARCHAR(60) DEFAULT '',
    ativo BOOLEAN DEFAULT 1 NOT NULL,
    criado_em TIMESTAMP,
    updated_em TIMESTAMP
)
"""

DDL_COTACOES = """
CREATE TABLE custo_cotacoes (
    id INTEGER PRIMARY KEY,
    moeda VARCHAR(3) NOT NULL,
    data DATE NOT NULL,
    tipo VARCHAR(20) DEFAULT 'ptax_venda' NOT NULL,
    valor NUMERIC(14, 6) NOT NULL,
    fonte VARCHAR(20) DEFAULT 'bcb_olinda',
    obtido_em TIMESTAMP,
    CONSTRAINT uq_custo_cotacao UNIQUE (moeda, data, tipo)
)
"""

DDL_VERSOES = """
CREATE TABLE custo_versoes (
    id INTEGER PRIMARY KEY,
    composicao_id INTEGER NOT NULL REFERENCES custo_composicoes(id),
    numero INTEGER NOT NULL,
    motivo VARCHAR(300) DEFAULT '',
    snapshot_json TEXT DEFAULT '',
    criado_por VARCHAR(120) DEFAULT '',
    criado_em TIMESTAMP
)
"""

INDICES = [
    ("ix_custo_composicoes_codigo", "custo_composicoes", "codigo"),
    ("ix_custo_composicoes_produto", "custo_composicoes", "produto"),
    ("ix_custo_composicoes_sku", "custo_composicoes", "sku"),
    ("ix_custo_composicoes_status", "custo_composicoes", "status"),
    ("ix_custo_composicoes_ativo", "custo_composicoes", "ativo"),
    ("ix_custo_composicoes_projeto_id", "custo_composicoes", "projeto_id"),
    ("ix_custo_composicoes_equipamento_id", "custo_composicoes", "equipamento_id"),
    ("ix_custo_lancamentos_composicao_id", "custo_lancamentos", "composicao_id"),
    ("ix_custo_lancamentos_natureza", "custo_lancamentos", "natureza"),
    ("ix_custo_lancamentos_categoria", "custo_lancamentos", "categoria"),
    ("ix_custo_cotacoes_moeda", "custo_cotacoes", "moeda"),
    ("ix_custo_cotacoes_data", "custo_cotacoes", "data"),
    ("ix_custo_versoes_composicao_id", "custo_versoes", "composicao_id"),
]


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        tabs = _tabelas(cur)
        if "projetos" not in tabs or "equipamentos" not in tabs:
            print("  ! projetos/equipamentos ainda nao existem (rode o servidor uma vez)")
            return

        criadas = 0
        criadas += _cria(cur, "custo_composicoes", DDL_COMPOSICOES, tabs)
        criadas += _cria(cur, "custo_lancamentos", DDL_LANCAMENTOS, tabs)
        criadas += _cria(cur, "custo_cotacoes", DDL_COTACOES, tabs)
        criadas += _cria(cur, "custo_versoes", DDL_VERSOES, tabs)

        for nome, tabela, coluna in INDICES:
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {nome} ON {tabela}({coluna})")
        print(f"  = {len(INDICES)} indice(s) garantidos")

        conn.commit()
        if not criadas:
            print("  = nada a fazer, schema ja estava em dia")
    finally:
        conn.close()

    print("  i o modulo aparece no sub-hub de P&D Equipamentos para admin/gestor")
    print("  i a sincronizacao da PTAX roda junto das tarefas diarias "
          "(desligue com DOCTRACK_CAMBIO=0)")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 012 em {db}...")
    upgrade(db)
    print("OK")
