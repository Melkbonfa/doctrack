"""Migration 013: módulo Tempos (apontamento de horas).

Cria a única tabela do módulo:

  tempo_apontamentos — um intervalo de trabalho de uma pessoa, opcionalmente
                       amarrado a projeto/entregável/cartão/equipamento (ou a
                       nada, quando a tarefa não existe na plataforma).

O detalhe que separa esta migration das anteriores é o ÍNDICE PARCIAL E ÚNICO
`uq_tempo_em_curso`: ele é a garantia, no banco, de que ninguém tem dois
cronômetros correndo ao mesmo tempo. SQLite (>= 3.8, 2013) e PostgreSQL aceitam a
mesma sintaxe `CREATE UNIQUE INDEX ... WHERE ...`, então o DDL aqui é literalmente
o mesmo que o SQLAlchemy emite na subida.

A ordem importa: os duplicados são fechados ANTES do CREATE. Se sobrar mais de
uma linha aberta por usuário o CREATE falha, e um banco que já rodou o módulo sem
o índice ficaria permanentemente sem a invariante.

Espelha o que `db.create_all()` faz na subida do servidor, para quem prefere
aplicar no banco antes de trocar o código. Idempotente.

Uso: python migrations/013_modulo_tempos.py [db_path]
"""
import os
import sqlite3
import sys
from pathlib import Path

# Mesmo padrão e mesma variável de tempos/models.LIMITE_CRONOMETRO_H. Lido do
# ambiente e não fixado em 12: a migration roda em SQL puro, sem importar o
# pacote, e um limite diferente configurado em produção faria este script fechar
# as linhas num ponto que o servidor nunca escolheria.
try:
    LIMITE_H = int(os.environ.get("DOCTRACK_TEMPO_LIMITE_H", "") or 12)
except ValueError:
    LIMITE_H = 12


def _tabelas(cur):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in cur.fetchall()}


def _indices(cur):
    cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
    return {r[0] for r in cur.fetchall()}


DDL_APONTAMENTOS = """
CREATE TABLE tempo_apontamentos (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ref_tipo VARCHAR(20) DEFAULT 'livre' NOT NULL,
    ref_id INTEGER,
    titulo VARCHAR(200) DEFAULT '',
    titulo_chave VARCHAR(200) DEFAULT '',
    projeto_id INTEGER REFERENCES projetos(id),
    inicio TIMESTAMP NOT NULL,
    fim TIMESTAMP,
    duracao_s INTEGER DEFAULT 0 NOT NULL,
    origem VARCHAR(12) DEFAULT 'cronometro' NOT NULL,
    encerrado_por VARCHAR(12) DEFAULT '',
    sessao_id INTEGER,
    nota TEXT DEFAULT '',
    criado_em TIMESTAMP,
    criado_por VARCHAR(120) DEFAULT '',
    editado_em TIMESTAMP,
    editado_por VARCHAR(120) DEFAULT ''
)
"""

INDICES = [
    ("ix_tempo_user_inicio", "tempo_apontamentos", "user_id, inicio"),
    ("ix_tempo_ref", "tempo_apontamentos", "ref_tipo, ref_id"),
    ("ix_tempo_projeto_inicio", "tempo_apontamentos", "projeto_id, inicio"),
    ("ix_tempo_sessao", "tempo_apontamentos", "sessao_id"),
]

# O índice que carrega a regra de negócio. Fica separado de INDICES porque é
# UNIQUE e PARCIAL — o formato (nome, tabela, coluna) não o expressa.
DDL_UNICO = ("CREATE UNIQUE INDEX uq_tempo_em_curso "
             "ON tempo_apontamentos (user_id) WHERE fim IS NULL")


def _fechar_duplicados(cur):
    """Deixa no máximo um apontamento aberto por pessoa: sobra o mais recente.

    Só faz sentido num banco que rodou o módulo sem o índice (checkout parcial,
    dump restaurado pela metade). Os fechados recebem encerrado_por='guarda',
    exatamente como o corte diário de cronômetro abandonado — a pessoa vê a linha
    sinalizada na folha e corrige, em vez de o sistema inventar uma duração.

    Duas etapas, na mesma ordem e com os mesmos números de `_sync_schema`
    (servidor.py) — os dois caminhos preparam o MESMO banco para o MESMO índice,
    e divergir faria o resultado depender de por onde o módulo entrou:

      1. o abandonado de verdade (passou do limite) fecha em `inicio + LIMITE`,
         igual a core.encerrar_abandonados;
      2. o que ainda sobrar aberto para a mesma pessoa fecha em `inicio`, com
         duração ZERO.

    Zero, e não o limite, no passo 2: a linha excedente é espúria e somar 12h de
    trabalho que ninguém fez contamina o relatório justamente com o tipo de número
    indefensável que o módulo existe para evitar. Fechar em `inicio + LIMITE` uma
    linha aberta há cinco minutos ainda gravaria um `fim` no futuro.
    """
    # Passo 1: os que realmente passaram do limite.
    cur.execute(f"""
        UPDATE tempo_apontamentos
           SET fim = datetime(inicio, '+{LIMITE_H} hours'),
               duracao_s = {LIMITE_H} * 3600,
               encerrado_por = 'guarda'
         WHERE fim IS NULL
           AND inicio < datetime('now', 'localtime', '-{LIMITE_H} hours')
    """)
    cortados = cur.rowcount or 0

    # Passo 2: o que sobrou aberto além do mais recente de cada pessoa.
    cur.execute("""
        SELECT id, user_id FROM tempo_apontamentos
        WHERE fim IS NULL ORDER BY user_id, inicio DESC
    """)
    vistos, orfaos = set(), []
    for apid, uid in cur.fetchall():
        if uid in vistos:
            orfaos.append(apid)
        else:
            vistos.add(uid)
    for apid in orfaos:
        cur.execute("""
            UPDATE tempo_apontamentos
               SET fim = inicio,
                   duracao_s = 0,
                   encerrado_por = 'guarda'
             WHERE id = ?
        """, (apid,))
    return cortados, len(orfaos)


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        tabs = _tabelas(cur)
        if "users" not in tabs or "projetos" not in tabs:
            print("  ! users/projetos ainda nao existem (rode o servidor uma vez)")
            return

        if "tempo_apontamentos" in tabs:
            print("  = tempo_apontamentos ja existia")
        else:
            cur.execute(DDL_APONTAMENTOS)
            print("  + tempo_apontamentos criada")

        for nome, tabela, colunas in INDICES:
            cur.execute(f"CREATE INDEX IF NOT EXISTS {nome} ON {tabela}({colunas})")
        print(f"  = {len(INDICES)} indice(s) garantidos")

        # O parcial e unico, por ultimo e com o de-dup antes.
        if "uq_tempo_em_curso" in _indices(cur):
            print("  = uq_tempo_em_curso ja existia")
        else:
            cortados, dups = _fechar_duplicados(cur)
            if cortados:
                print(f"  ! {cortados} cronometro(s) abandonado(s) fechado(s) "
                      f"no limite de {LIMITE_H}h como 'guarda'")
            if dups:
                print(f"  ! {dups} cronometro(s) aberto(s) duplicado(s) fechado(s) "
                      f"com duracao zero antes de criar o indice unico")
            cur.execute(DDL_UNICO)
            print("  + uq_tempo_em_curso criado (parcial: WHERE fim IS NULL)")

        conn.commit()
    finally:
        conn.close()

    print("  i o modulo aparece no sub-hub de P&D Equipamentos para tecnico+")
    print("  i o corte de cronometro abandonado roda junto das tarefas diarias "
          "(ajuste com DOCTRACK_TEMPO_LIMITE_H, padrao 12h)")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB nao encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 013 em {db}...")
    upgrade(db)
    print("OK")
