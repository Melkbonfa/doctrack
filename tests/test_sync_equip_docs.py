"""Invariante de sincronia entre os módulos Documentos e Equipamentos.

Regra: um documento ATIVO sempre pertence a um equipamento ATIVO. Quebrá-la produz
o card órfão — documento visível em Documentos, equipamento invisível em
Equipamentos —, que foi a divergência encontrada em jul/2026 (18 equipamentos,
139 documentos presos a entidades já excluídas).
"""
from datetime import datetime

from models import db, Documento, Equipamento


def _orfaos():
    """Documentos ativos presos a um equipamento inativo."""
    return db.session.query(Documento).join(
        Equipamento, Documento.equipamento_id == Equipamento.id).filter(
        Documento.ativo == True, Equipamento.ativo == False).all()


def test_delete_equipamento_desativa_documentos(client, admin_token, auth_headers, app):
    """Excluir o equipamento leva junto seus documentos — sem cascade sobram órfãos."""
    h = auth_headers(admin_token)
    eq = client.post("/api/equipamentos", json={"nome": "SyncDel"}, headers=h).get_json()["equipamento"]

    with app.app_context():
        assert Documento.query.filter_by(equipamento_id=eq["id"], ativo=True).count() > 0

    assert client.delete(f'/api/equipamentos/{eq["id"]}', headers=h).status_code == 200

    with app.app_context():
        assert Documento.query.filter_by(equipamento_id=eq["id"], ativo=True).count() == 0
        assert _orfaos() == []


def test_backfill_revincula_documento_preso_a_equipamento_excluido(client, admin_token,
                                                                   auth_headers, app):
    """Documento ativo apontando para equipamento excluído volta para o ativo homônimo.

    Reproduz a divergência real: o equipamento é desativado sem cascade (como faziam
    as exclusões anteriores a jul/2026) e o documento continua ativo. O backfill tem
    de devolvê-lo a um equipamento ATIVO, nunca deixá-lo preso ao excluído.
    """
    from servidor import _backfill_equipamentos

    h = auth_headers(admin_token)
    eq = client.post("/api/equipamentos", json={"nome": "SyncOrfao"}, headers=h).get_json()["equipamento"]

    with app.app_context():
        # Desativa SÓ o equipamento — os documentos seguem ativos (o bug histórico).
        morto = db.session.get(Equipamento, eq["id"])
        morto.ativo = False
        db.session.commit()
        assert len(_orfaos()) > 0, "cenário não montado: deveria haver órfãos"

        _backfill_equipamentos()

        assert _orfaos() == [], "backfill deixou documentos presos a equipamento inativo"
        # Os documentos foram devolvidos a um equipamento ativo de mesmo nome.
        vivo = Equipamento.query.filter_by(nome="SyncOrfao", ativo=True).first()
        assert vivo is not None
        assert vivo.id != morto.id
        assert Documento.query.filter_by(equipamento_id=vivo.id, ativo=True).count() > 0


def test_backfill_nao_reata_documento_a_equipamento_inativo(client, admin_token,
                                                            auth_headers, app):
    """Um documento novo nunca deve ser vinculado a um equipamento já excluído.

    Antes da correção, a busca por nome ignorava o flag `ativo` e o documento era
    silenciosamente preso à entidade morta.
    """
    from servidor import _backfill_equipamentos

    with app.app_context():
        morto = Equipamento(nome="SyncMorto", ativo=False)
        db.session.add(morto)
        db.session.flush()

        db.session.add(Documento(setor="PRE", equipamento="SyncMorto", tipo_doc="IT",
                                 documento="IT - SyncMorto", status="Elaborar"))
        db.session.commit()

        _backfill_equipamentos()

        doc = Documento.query.filter_by(documento="IT - SyncMorto", ativo=True).first()
        assert doc.equipamento_id != morto.id, "documento foi preso ao equipamento excluído"
        assert db.session.get(Equipamento, doc.equipamento_id).ativo is True
        assert _orfaos() == []
