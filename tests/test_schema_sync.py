"""`_sync_schema` leva a um banco que já existia os índices que o modelo declara.

Banco novo não precisa disto (create_all cria a tabela com tudo). O caso coberto
é o de produção: tabela antiga, coluna nova por ALTER TABLE — que vem sem o
índice — e migrations de índice que só rodam em SQLite. Foi assim que
`entregaveis.modelo_chave` e `modelos_entregavel.chave` ficaram sem índice no
Postgres enquanto a migration 020 os criava no SQLite.
"""
from sqlalchemy import inspect, text


def _indices_comuns():
    """{nome: (tabela, colunas)} de todo índice não-UNIQUE declarado nos modelos."""
    from models import db
    return {i.name: (t.name, tuple(c.name for c in i.columns))
            for t in db.metadata.tables.values() for i in t.indexes if not i.unique}


def _indices_no_banco():
    from models import db
    insp = inspect(db.engine)
    return {i["name"]: (t, tuple(i["column_names"]))
            for t in insp.get_table_names() for i in insp.get_indexes(t)}


def test_recria_todo_indice_do_modelo_que_falta(app):
    import servidor
    from models import db

    esperados = _indices_comuns()
    for nome in esperados:
        db.session.execute(text(f"DROP INDEX IF EXISTS {nome}"))
    db.session.commit()
    assert not set(esperados) & set(_indices_no_banco())

    servidor._sync_schema()

    faltando = set(esperados) - set(_indices_no_banco())
    assert not faltando, f"_sync_schema não recriou: {sorted(faltando)}"


def test_nao_duplica_indice_que_existe_com_outro_nome(app):
    """As migrations SQLite criaram índices com nome próprio (ix_hist_em,
    ix_eqsnap_data…). Recriar com o nome do modelo daria dois índices iguais na
    mesma coluna — custo de escrita dobrado sem ganho nenhum."""
    import servidor
    from models import db

    db.session.execute(text("DROP INDEX ix_entregaveis_modelo_chave"))
    db.session.execute(text("CREATE INDEX ix_legado_modelo_chave ON entregaveis (modelo_chave)"))
    db.session.commit()

    servidor._sync_schema()

    no_banco = _indices_no_banco()
    assert "ix_legado_modelo_chave" in no_banco
    assert "ix_entregaveis_modelo_chave" not in no_banco
