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
            # opcional já ocultado por uma migração anterior → volta ativo, em N/A
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
        assert spare.ativo is True and spare.aplicavel is False     # ressuscitado em N/A
        assert spare.deleted_at is None

        # idempotência: rodar de novo não muda nada
        _migrar_taxonomia_docs()
        assert Documento.query.filter_by(tipo_doc="Checklist").count() == 0
        assert Documento.query.filter_by(tipo_doc="Dossie").count() == 1
        assert docs["Dossie"].aplicavel is False       # não alterna de volta
        assert docs["QIQOQD"].aplicavel is True
        assert docs["Spare_Parts"].ativo is True and docs["Spare_Parts"].aplicavel is False


def test_migracao_mais_backfill_nao_duplica_documentos(app):
    """Migração + _ensure_docs_for_equip: 1 documento ativo por tipo, sem duplicatas.

    Os opcionais que a versão antiga da migração soft-deletou voltam ativos em N/A;
    se continuassem inativos, o backfill (que só enxerga os ativos) criaria uma
    segunda linha do mesmo tipo.
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

        for _ in range(2):                       # dois boots seguidos
            _migrar_taxonomia_docs()
            _ensure_docs_for_equip(equip)
            db.session.commit()

        todos, ativos = {}, {}
        for d in Documento.query.filter(Documento.equipamento_id == equip.id).all():
            todos.setdefault(d.tipo_doc, []).append(d)
            if d.ativo:
                ativos.setdefault(d.tipo_doc, []).append(d)

        assert set(ativos) == set(TIPOS_DOC_TODOS)            # os 12 tipos
        assert all(len(v) == 1 for v in ativos.values())      # exatamente 1 ativo por tipo
        # e nenhuma linha órfã: o opcional ocultado foi RESSUSCITADO, não recriado
        assert all(len(v) == 1 for v in todos.values()), \
            {t: len(v) for t, v in todos.items() if len(v) > 1}
        for t in TIPOS_DOC_OPCIONAIS:
            d = ativos[t][0]
            assert d.aplicavel is False and d.deleted_at is None
        for t in set(TIPOS_DOC_TODOS) - set(TIPOS_DOC_OPCIONAIS):
            assert ativos[t][0].aplicavel is True
