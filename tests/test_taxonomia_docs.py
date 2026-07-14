"""Testes da taxonomia de tipos de documento (4 checklists + opcionais)."""


def test_constantes_taxonomia():
    from models import (TIPOS_DOC_PRE, TIPOS_DOC_OPCIONAIS, TIPOS_DOC_TODOS,
                        SETOR_DO_TIPO)
    # PRE = IT + 4 checklists, todos no pipeline de 4 etapas
    assert TIPOS_DOC_PRE == ["IT", "Checklist_Conferencia", "Checklist_BurnIn",
                             "Checklist_Limpeza_Embalagem", "Checklist_Produto"]
    for t in TIPOS_DOC_PRE:
        assert SETOR_DO_TIPO[t] == "PRE"
    # os 12 tipos existem sempre; estes 3 é que nascem em N/A
    assert len(TIPOS_DOC_TODOS) == 12
    assert set(TIPOS_DOC_OPCIONAIS) == {"Spare_Parts", "Dossie", "QIQOQD"}
    assert set(TIPOS_DOC_OPCIONAIS) < set(TIPOS_DOC_TODOS)


def test_post_cria_12_tipos_com_opcionais_em_na(client, admin_token, auth_headers):
    """Equipamento novo nasce com os 12 documentos: 9 aplicáveis + 3 opcionais N/A."""
    from models import TIPOS_DOC_TODOS, TIPOS_DOC_OPCIONAIS
    h = auth_headers(admin_token)
    res = client.post("/api/documentos",
                      json={"setor": "PRE", "equipamento": "MAQ-OPT", "sku": "SKU-OPT"},
                      headers=h)
    assert res.status_code == 201
    docs = [d for d in client.get("/api/documentos", headers=h).get_json()
            if d["equipamento"] == "MAQ-OPT"]
    por_tipo = {d["tipo_doc"]: d for d in docs}
    assert set(por_tipo) == set(TIPOS_DOC_TODOS)          # os 12 existem
    for t in TIPOS_DOC_OPCIONAIS:
        assert por_tipo[t]["aplicavel"] is False          # opcionais em N/A
    for t in set(TIPOS_DOC_TODOS) - set(TIPOS_DOC_OPCIONAIS):
        assert por_tipo[t]["aplicavel"] is True


def test_post_com_opcional_selecionado_nasce_aplicavel(client, admin_token, auth_headers):
    """Criar explicitamente um opcional (botão do modal) já o marca como aplicável."""
    h = auth_headers(admin_token)
    res = client.post("/api/documentos",
                      json={"setor": "Manuais", "equipamento": "MAQ-OPT2",
                            "tipo_doc": "Dossie", "codigo_doc": "DOS-1"},
                      headers=h)
    assert res.status_code == 201
    doc = res.get_json()["documento"]
    assert doc["tipo_doc"] == "Dossie"
    assert doc["aplicavel"] is True
    docs = [d for d in client.get("/api/documentos", headers=h).get_json()
            if d["equipamento"] == "MAQ-OPT2"]
    por_tipo = {d["tipo_doc"]: d for d in docs}
    assert por_tipo["Spare_Parts"]["aplicavel"] is False   # os outros opcionais nascem N/A
    assert por_tipo["QIQOQD"]["aplicavel"] is False


def test_migracao_renomeia_checklist_e_marca_opcionais_em_branco_como_na(app):
    from models import db, Documento, Equipamento
    from servidor import _migrar_taxonomia_docs
    from datetime import datetime

    with app.app_context():
        equip = Equipamento(nome="MAQ-MIG", sku="SKU-MIG", armazenamento_base="P:/Base")
        db.session.add(equip)
        db.session.flush()
        db.session.add_all([
            # Checklist genérico com dados → vira Checklist_Conferencia
            Documento(setor="PRE", equipamento="MAQ-MIG", equipamento_id=equip.id,
                      documento="Checklist - MAQ-MIG", tipo_doc="Checklist",
                      codigo_doc="CHK-1", status="Homologado"),
            # opcional em branco (armazenamento = base do equip) → N/A, mas ativo
            Documento(setor="Manuais", equipamento="MAQ-MIG", equipamento_id=equip.id,
                      documento="Dossiê - MAQ-MIG", tipo_doc="Dossie",
                      status="Elaborar", armazenamento="P:/Base"),
            # opcional com dado (codigo_doc) → aplicável
            Documento(setor="Manuais", equipamento="MAQ-MIG", equipamento_id=equip.id,
                      documento="QI/QO/QD - MAQ-MIG", tipo_doc="QIQOQD",
                      codigo_doc="QQ-9", status="Elaborar"),
            # opcional apagado (soft delete) → a migração NÃO ressuscita
            Documento(setor="Manuais", equipamento="MAQ-MIG", equipamento_id=equip.id,
                      documento="Spare Parts - MAQ-MIG", tipo_doc="Spare_Parts",
                      status="Elaborar", ativo=False, deleted_at=datetime.now()),
        ])
        db.session.commit()

        _migrar_taxonomia_docs()

        docs = {d.tipo_doc: d for d in Documento.query.filter(
            Documento.equipamento == "MAQ-MIG").all()}
        assert "Checklist" not in docs
        chk = docs["Checklist_Conferencia"]
        assert chk.codigo_doc == "CHK-1" and chk.status == "Homologado"
        assert chk.documento == "Checklist de Conferência - MAQ-MIG"
        assert chk.aplicavel is True

        dossie = docs["Dossie"]
        assert dossie.ativo is True and dossie.aplicavel is False   # em branco → N/A
        assert docs["QIQOQD"].aplicavel is True                     # tinha dado → aplica

        spare = docs["Spare_Parts"]
        assert spare.ativo is False                  # apagado continua apagado
        assert spare.deleted_at is not None

        # idempotência: rodar de novo não muda nada
        _migrar_taxonomia_docs()
        assert Documento.query.filter_by(tipo_doc="Checklist").count() == 0
        assert Documento.query.filter_by(tipo_doc="Dossie").count() == 1
        assert docs["Dossie"].aplicavel is False       # não alterna de volta
        assert docs["QIQOQD"].aplicavel is True
        assert docs["Spare_Parts"].ativo is False


def test_migracao_nao_ressuscita_documento_apagado(app):
    """Soft delete é decisão de alguém — a migração nunca desfaz.

    Regressão real: uma versão desta migração reativava todo opcional em branco
    que estivesse inativo. Isso ressuscitava, a cada boot, documentos excluídos de
    propósito (exclusão manual, cascade do equipamento, deduplicação) — e desfazia
    qualquer limpeza de duplicatas.
    """
    from datetime import datetime
    from models import db, Documento, Equipamento
    from servidor import _migrar_taxonomia_docs

    with app.app_context():
        equip = Equipamento(nome="MAQ-DEL", sku="SKU-DEL")
        db.session.add(equip)
        db.session.flush()
        # duplicata em branco que alguém desativou numa limpeza
        apagado = Documento(setor="Manuais", equipamento="MAQ-DEL", equipamento_id=equip.id,
                            documento="Dossiê - MAQ-DEL (duplicata)", tipo_doc="Dossie",
                            status="Elaborar", ativo=False, deleted_at=datetime.now())
        # o sobrevivente do mesmo tipo, ativo
        vivo = Documento(setor="Manuais", equipamento="MAQ-DEL", equipamento_id=equip.id,
                         documento="Dossiê - MAQ-DEL", tipo_doc="Dossie", status="Elaborar")
        db.session.add_all([apagado, vivo])
        db.session.commit()

        for _ in range(2):                            # dois boots
            _migrar_taxonomia_docs()

        assert apagado.ativo is False                 # continua apagado
        assert Documento.query.filter_by(tipo_doc="Dossie", ativo=True).count() == 1
        assert vivo.aplicavel is False                # em branco → N/A


def test_migracao_mais_backfill_nao_duplica_documentos(app):
    """Boots repetidos mantêm 1 documento ATIVO por (equipamento, tipo).

    Regressão real: quando a migração desativava o opcional em branco e o backfill
    o recriava, cada boot somava uma linha nova — no banco de dev deu até 9 cópias
    de "Dossiê" no mesmo equipamento. O invariante que prende o par é este: por mais
    boots que rodem, existe exatamente 1 documento ativo de cada tipo.
    """
    from datetime import datetime
    from models import db, Documento, Equipamento, TIPOS_DOC_TODOS, TIPOS_DOC_OPCIONAIS
    from servidor import _migrar_taxonomia_docs, _ensure_docs_for_equip

    with app.app_context():
        equip = Equipamento(nome="MAQ-DUP", sku="SKU-DUP")
        db.session.add(equip)
        db.session.flush()
        # estado deixado pela versão anterior da migração: opcionais ocultados
        for t in TIPOS_DOC_OPCIONAIS:
            db.session.add(Documento(
                setor="Manuais", equipamento="MAQ-DUP", equipamento_id=equip.id,
                documento=f"{t} - MAQ-DUP", tipo_doc=t, status="Elaborar",
                ativo=False, deleted_at=datetime.now()))
        db.session.commit()

        for _ in range(3):                       # três boots seguidos
            _migrar_taxonomia_docs()
            _ensure_docs_for_equip(equip)
            db.session.commit()

        ativos = {}
        for d in Documento.query.filter(Documento.equipamento_id == equip.id,
                                        Documento.ativo == True).all():
            ativos.setdefault(d.tipo_doc, []).append(d)

        assert set(ativos) == set(TIPOS_DOC_TODOS)            # os 12 tipos
        assert all(len(v) == 1 for v in ativos.values()), \
            {t: len(v) for t, v in ativos.items() if len(v) > 1}
        # o backfill repôs os opcionais apagados como UMA linha nova em N/A
        for t in TIPOS_DOC_OPCIONAIS:
            assert ativos[t][0].aplicavel is False
        for t in set(TIPOS_DOC_TODOS) - set(TIPOS_DOC_OPCIONAIS):
            assert ativos[t][0].aplicavel is True
