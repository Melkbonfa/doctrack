"""GET /api/hub/resumo — números das vitrines do hub e dos sub-hubs."""
from datetime import datetime, timedelta

from models import (db, User, Documento, Projeto, Entregavel, TipoProjeto,
                    Missao, MissaoColuna, MissaoCartao)


def _resumo(client, auth_headers, token):
    res = client.get("/api/hub/resumo", headers=auth_headers(token))
    assert res.status_code == 200, res.get_json()
    return res.get_json()["modulos"]


def test_exige_login(client):
    assert client.get("/api/hub/resumo").status_code == 401


def test_leitura_so_recebe_os_modulos_que_abre(client, auth_headers, leitura_token):
    m = _resumo(client, auth_headers, leitura_token)
    assert set(m) == {"equip", "docs"}


def test_tecnico_nao_recebe_gestao(client, auth_headers, tecnico_token):
    m = _resumo(client, auth_headers, tecnico_token)
    assert set(m) == {"equip", "docs", "missoes", "tempos", "fluxos"}


def test_gestor_recebe_tudo(client, auth_headers, gestor_token):
    m = _resumo(client, auth_headers, gestor_token)
    assert set(m) == {"equip", "docs", "ent", "missoes", "custos", "tempos", "fluxos"}


def test_documentos_contam_os_vivos_e_os_do_usuario(app, client, auth_headers, tecnico_token):
    ontem = (datetime.now() - timedelta(days=1)).date()
    db.session.add_all([
        Documento(setor="Manuais", equipamento="MAQ-C", documento="Manual-3",
                  status="Em andamento", tipo_doc="Manual_Usuario",
                  responsavel="Tecnico Test", prazo=ontem),
        Documento(setor="Manuais", equipamento="MAQ-D", documento="Manual-4",
                  status="Em andamento", tipo_doc="Manual_Usuario", ativo=False),
    ])
    db.session.commit()
    vivos = Documento.query.filter_by(ativo=True, aplicavel=True).all()

    d = _resumo(client, auth_headers, tecnico_token)["docs"]
    assert d["total"] == len(vivos)           # o inativo fica de fora
    assert d["andamento"] == sum(1 for x in vivos if not x.concluido)
    assert d["meus"] == 1 and d["meus_atrasados"] == 1
    assert d["atrasados"] >= 1


def test_projetos_saem_por_area(app, client, auth_headers, gestor_token):
    db.session.add(TipoProjeto(nome="INOV Teste", area="inov", ordem=99))
    p_inov = Projeto(nome="Ideia", tipo="INOV Teste")
    p_pde = Projeto(nome="Equip X", tipo="")
    db.session.add_all([p_inov, p_pde, Projeto(nome="Velho", ativo=False)])
    db.session.flush()
    ontem = (datetime.now() - timedelta(days=1)).date().isoformat()
    db.session.add_all([
        Entregavel(projeto_id=p_inov.id, tipo="Protótipo", status="concluido"),
        Entregavel(projeto_id=p_inov.id, tipo="Patente", status="pendente", data_fim_prev=ontem),
        Entregavel(projeto_id=p_pde.id, tipo="Manual", status="na"),
    ])
    db.session.commit()

    ent = _resumo(client, auth_headers, gestor_token)["ent"]
    assert ent["inov"] == {"projetos": 1, "atrasados": 1, "avanco_medio": 50}
    # Projeto sem escopo conta como projeto mas não puxa a média para baixo.
    assert ent["pde"]["projetos"] == 1 and ent["pde"]["avanco_medio"] == 0
    assert "Velho" not in str(ent)


def test_missoes_contam_os_cartoes_do_usuario(app, client, auth_headers, tecnico_token):
    m = Missao(nome="Quadro")
    db.session.add(m)
    db.session.flush()
    col = MissaoColuna(missao_id=m.id, nome="Fazendo")
    db.session.add(col)
    db.session.flush()
    ontem = (datetime.now() - timedelta(days=1)).date().isoformat()
    db.session.add_all([
        MissaoCartao(missao_id=m.id, coluna_id=col.id, titulo="Meu", responsaveis="Tecnico Test", prazo=ontem),
        MissaoCartao(missao_id=m.id, coluna_id=col.id, titulo="Dos outros", responsaveis="Gestor Test"),
        MissaoCartao(missao_id=m.id, coluna_id=col.id, titulo="Feito", responsaveis="Tecnico Test", concluido=True),
    ])
    db.session.commit()

    r = _resumo(client, auth_headers, tecnico_token)["missoes"]
    assert r == {"meus": 1, "meus_atrasados": 1, "equipe_andamento": 2}


def test_tempos_somam_so_os_apontamentos_do_proprio_usuario(app, client, auth_headers, tecnico_token):
    from tempos.models import Apontamento
    tec = User.query.filter_by(email="tecnico@test.com").first()
    ges = User.query.filter_by(email="gestor@test.com").first()
    agora = datetime.now().replace(second=0, microsecond=0)
    inicio = agora.replace(hour=0, minute=1)
    db.session.add_all([
        Apontamento(user_id=tec.id, inicio=inicio, fim=inicio + timedelta(hours=1), duracao_s=3600),
        Apontamento(user_id=ges.id, inicio=inicio, fim=inicio + timedelta(hours=2), duracao_s=7200),
    ])
    db.session.commit()

    t = _resumo(client, auth_headers, tecnico_token)["tempos"]
    assert t["hoje_s"] == 3600 and t["semana_s"] >= 3600
    assert t["em_curso"] is False and t["ultimo_fim"] == "01:01"


def test_bloco_quebrado_nao_derruba_a_tela(client, auth_headers, gestor_token, monkeypatch):
    import hub

    def explode(_u):
        raise RuntimeError("boom")
    monkeypatch.setattr(hub, "BLOCOS", [("equip", None, explode)] + hub.BLOCOS[1:])
    m = _resumo(client, auth_headers, gestor_token)
    assert "equip" not in m and "docs" in m


def test_hub_anima_mesmo_com_movimento_reduzido():
    """Decisão de produto: nos PCs da empresa o Windows vem com "Efeitos de
    animação" desligado, e o hub obedecendo a prefers-reduced-motion ficava
    parado para quase todo mundo. Esta checagem impede a volta do corte."""
    import os
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for arq in ("static/hub-vitrine.css", "static/hub-vitrine.js"):
        with open(os.path.join(raiz, arq), encoding="utf-8") as f:
            fonte = f.read()
        assert "@media (prefers-reduced-motion" not in fonte, arq
        assert "matchMedia('(prefers-reduced-motion" not in fonte, arq
