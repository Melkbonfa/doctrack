"""Testes da taxonomia de tipos de documento (4 checklists + opcionais)."""


def test_constantes_taxonomia():
    from models import (TIPOS_DOC_PRE, TIPOS_DOC_PADRAO_APLICAVEL, TIPOS_DOC_OPCIONAIS,
                        TIPOS_DOC_TODOS, SETOR_DO_TIPO)
    # PRE = IT + 4 checklists, todos no pipeline de 4 etapas
    assert TIPOS_DOC_PRE == ["IT", "Checklist_Conferencia", "Checklist_BurnIn",
                             "Checklist_Limpeza_Embalagem", "Checklist_Produto"]
    for t in TIPOS_DOC_PRE:
        assert SETOR_DO_TIPO[t] == "PRE"
    # opcionais nascem fora do conjunto aplicável por padrão
    assert set(TIPOS_DOC_OPCIONAIS) == {"Spare_Parts", "Dossie", "QIQOQD"}
    assert not set(TIPOS_DOC_OPCIONAIS) & set(TIPOS_DOC_PADRAO_APLICAVEL)
    assert set(TIPOS_DOC_PADRAO_APLICAVEL) | set(TIPOS_DOC_OPCIONAIS) == set(TIPOS_DOC_TODOS)


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


def test_migracao_renomeia_checklist_e_oculta_opcionais_em_branco(app):
    from models import db, Documento, Equipamento
    from servidor import _migrar_taxonomia_docs

    with app.app_context():
        equip = Equipamento(nome="MAQ-MIG", sku="SKU-MIG", armazenamento_base="P:/Base")
        db.session.add(equip)
        db.session.flush()
        db.session.add_all([
            # Checklist genérico com dados → vira Checklist_Conferencia
            Documento(setor="PRE", equipamento="MAQ-MIG", equipamento_id=equip.id,
                      documento="Checklist - MAQ-MIG", tipo_doc="Checklist",
                      codigo_doc="CHK-1", status="Homologado"),
            # opcional em branco (armazenamento = base do equip) → ocultado
            Documento(setor="Manuais", equipamento="MAQ-MIG", equipamento_id=equip.id,
                      documento="Dossiê - MAQ-MIG", tipo_doc="Dossie",
                      status="Elaborar", armazenamento="P:/Base"),
            # opcional com dado (codigo_doc) → preservado
            Documento(setor="Manuais", equipamento="MAQ-MIG", equipamento_id=equip.id,
                      documento="QI/QO/QD - MAQ-MIG", tipo_doc="QIQOQD",
                      codigo_doc="QQ-9", status="Elaborar"),
        ])
        db.session.commit()

        _migrar_taxonomia_docs()

        docs = {d.tipo_doc: d for d in Documento.query.filter(
            Documento.equipamento == "MAQ-MIG").all()}
        assert "Checklist" not in docs
        chk = docs["Checklist_Conferencia"]
        assert chk.codigo_doc == "CHK-1" and chk.status == "Homologado"
        assert chk.documento == "Checklist de Conferência - MAQ-MIG"
        assert docs["Dossie"].ativo is False           # em branco → ocultado
        assert docs["Dossie"].deleted_at is not None
        assert docs["QIQOQD"].ativo is True            # tinha dado → fica

        # idempotência: rodar de novo não muda nada
        _migrar_taxonomia_docs()
        assert Documento.query.filter_by(tipo_doc="Checklist").count() == 0
