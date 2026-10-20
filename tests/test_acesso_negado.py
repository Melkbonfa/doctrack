"""ACESSO_NEGADO: o 403 de perfil ou área vai para a trilha (Análise de Riscos, R-06).

A validação de sistema computadorizado pede o registro das tentativas de acesso
não autorizadas. As falhas de login e de ativação já eram gravadas; faltava quem
já está dentro tentando o que o perfil ou a área não alcança.

O que estes testes fixam:

  * a linha leva e-mail, método + rota, motivo e IP, e a resposta ao cliente
    não muda;
  * deduplicação por (usuário, rota) dentro de `JANELA_ACESSO_NEGADO`, com a
    rota tomada pela regra do Flask — uma varredura de ids não multiplica linhas;
  * os gates próprios de Cadernos e Tempos gravam do mesmo jeito, inclusive o
    404 que esconde um caderno sem acesso.
"""
from datetime import datetime, timedelta

import pytest

import arquivos_store
from auth import JANELA_ACESSO_NEGADO
from models import db, AuditLog, User

IP = "10.20.30.40"


def H(token):
    return {"Authorization": f"Bearer {token}"}


def _get(client, rota, token, ip=IP):
    return client.get(rota, headers=H(token), environ_base={"REMOTE_ADDR": ip})


def _negados():
    return AuditLog.query.filter_by(acao="ACESSO_NEGADO").order_by(AuditLog.id).all()


# ── require_role / require_area ───────────────────────────────────────────────

def test_403_de_perfil_grava_email_rota_metodo_motivo_e_ip(client, leitura_token):
    res = _get(client, "/api/users", leitura_token)
    assert res.status_code == 403
    assert res.get_json() == {"erro": "Acesso negado para este perfil"}   # resposta igual

    [linha] = _negados()
    assert linha.usuario_email == "leitura@test.com"
    assert linha.usuario_id == User.query.filter_by(email="leitura@test.com").first().id
    assert linha.entidade == "GET /api/users"
    assert linha.campo == "motivo"
    assert linha.valor_novo == "perfil leitura (exige admin, gestor)"
    assert linha.ip == IP


def test_403_de_area_grava_a_area_que_faltou(client, tecnico_token):
    """O técnico do seed não tem área nenhuma: o PDR o recusa."""
    res = _get(client, "/pdr/api/meta", tecnico_token)
    assert res.status_code == 403
    assert res.get_json() == {"erro": "Sem acesso a esta área"}
    [linha] = _negados()
    assert linha.entidade == "GET /pdr/api/meta"
    assert linha.valor_novo == "sem a área pdr"


def test_mesma_rota_repetida_grava_uma_linha_so(client, leitura_token):
    """O front provoca este 403 no uso normal; sem a deduplicação, cada tela
    aberta viraria linha de auditoria."""
    for _ in range(5):
        assert _get(client, "/api/users", leitura_token).status_code == 403
    assert len(_negados()) == 1


def test_rota_com_id_deduplica_pela_regra_e_nao_pelo_caminho(client, tecnico_token):
    """Uma varredura de ids não pode gerar uma linha por requisição."""
    for uid in range(1, 6):
        assert client.patch(f"/api/users/{uid}", json={"nome": "x"},
                            headers=H(tecnico_token)).status_code == 403
    [linha] = _negados()
    assert linha.entidade == "PATCH /api/users/<int:user_id>"


def test_outra_rota_outro_metodo_e_outro_usuario_sao_outras_linhas(
        client, leitura_token, tecnico_token):
    _get(client, "/api/users", leitura_token)
    client.post("/api/users", json={}, headers=H(leitura_token))
    _get(client, "/api/users", tecnico_token)
    assert sorted((l.usuario_email, l.entidade) for l in _negados()) == [
        ("leitura@test.com", "GET /api/users"),
        ("leitura@test.com", "POST /api/users"),
        ("tecnico@test.com", "GET /api/users"),
    ]


def test_depois_da_janela_grava_de_novo(client, leitura_token):
    _get(client, "/api/users", leitura_token)
    [primeira] = _negados()
    primeira.timestamp = datetime.now() - JANELA_ACESSO_NEGADO - timedelta(seconds=1)
    db.session.commit()

    _get(client, "/api/users", leitura_token)
    assert len(_negados()) == 2


def test_janela_e_curta():
    """Curta o bastante para a trilha mostrar que a pessoa insistiu."""
    assert timedelta(0) < JANELA_ACESSO_NEGADO <= timedelta(minutes=15)


def test_ver_cadastro_de_outro_grava(client, tecnico_token):
    admin = User.query.filter_by(email="admin@test.com").first()
    res = client.get(f"/api/users/{admin.id}", headers=H(tecnico_token))
    assert res.status_code == 403
    [linha] = _negados()
    assert linha.entidade == "GET /api/users/<int:user_id>"
    assert linha.valor_novo == "perfil tecnico (só o próprio cadastro)"


def test_acesso_permitido_e_401_nao_gravam(client, admin_token):
    assert client.get("/api/users", headers=H(admin_token)).status_code == 200
    assert client.get("/api/users").status_code == 401
    assert _negados() == []


def test_falha_ao_gravar_nao_muda_a_resposta(client, leitura_token, monkeypatch):
    import auth

    def quebra(*a, **kw):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(auth, "log_action", quebra)
    res = _get(client, "/api/users", leitura_token)
    assert res.status_code == 403
    assert res.get_json() == {"erro": "Acesso negado para este perfil"}


# ── Cadernos ──────────────────────────────────────────────────────────────────

@pytest.fixture
def cadernos(app, tmp_path, monkeypatch):
    """Caderno do técnico na área PDR; leitura e gestor com a área."""
    monkeypatch.setattr(arquivos_store, "RAIZ", str(tmp_path / "arquivos"))
    for email in ("tecnico@test.com", "leitura@test.com"):
        User.query.filter_by(email=email).first().areas = "pdr"
    db.session.commit()


def _caderno(client, token, **extra):
    corpo = {"area": "pdr", "nome": "Projeto L-037", "modelo": "projeto_pdr", **extra}
    res = client.post("/cadernos/api/cadernos", json=corpo, headers=H(token))
    assert res.status_code == 201, res.get_json()
    return res.get_json()["caderno"]["uuid"]


def test_cadernos_papel_insuficiente_grava(client, tecnico_token, leitura_token, cadernos):
    cad = _caderno(client, tecnico_token)
    nos = client.get(f"/cadernos/api/cadernos/{cad}/arvore", headers=H(tecnico_token)).get_json()["nos"]
    secao = next(n["uuid"] for n in nos if n["tipo"] == "secao")

    res = client.post(f"/cadernos/api/secoes/{secao}/paginas", json={},
                      headers=H(leitura_token))
    assert res.status_code == 403
    [linha] = _negados()
    assert linha.usuario_email == "leitura@test.com"
    assert linha.entidade == "POST /cadernos/api/secoes/<uuid_>/paginas"
    assert linha.valor_novo == "papel leitor no caderno Projeto L-037 (exige editor)"


def test_cadernos_sem_acesso_responde_404_mas_grava(client, tecnico_token, gestor_token, cadernos):
    """O 404 esconde do cliente que o caderno existe; a trilha registra a tentativa."""
    cad = _caderno(client, tecnico_token, nome="Privado", acesso_area="nenhum")
    res = client.get(f"/cadernos/api/cadernos/{cad}", headers=H(gestor_token))
    assert res.status_code == 404
    assert res.get_json() == {"erro": "Não encontrado"}
    [linha] = _negados()
    assert linha.usuario_email == "gestor@test.com"
    assert linha.valor_novo == "sem acesso ao caderno Privado"


def test_cadernos_caderno_inexistente_nao_grava(client, tecnico_token, cadernos):
    assert client.get("/cadernos/api/cadernos/nao-existe",
                      headers=H(tecnico_token)).status_code == 404
    assert _negados() == []


def test_cadernos_leitura_nao_cria_e_grava(client, leitura_token, cadernos):
    res = client.post("/cadernos/api/cadernos", json={"area": "pdr", "nome": "X"},
                      headers=H(leitura_token))
    assert res.status_code == 403
    assert res.get_json() == {"erro": "Seu perfil não cria cadernos"}
    [linha] = _negados()
    assert linha.valor_novo == "perfil leitura não cria cadernos"


def test_cadernos_meta_sem_a_area_grava(client, gestor_token, cadernos):
    res = client.get("/cadernos/api/meta?area=pdr", headers=H(gestor_token))
    assert res.status_code == 403
    [linha] = _negados()
    assert linha.entidade == "GET /cadernos/api/meta"
    assert linha.valor_novo == "sem a área pdr"


# ── Tempos ────────────────────────────────────────────────────────────────────

def test_tempos_apontamento_de_outro_grava(client, tecnico_token):
    from tempos.models import Apontamento
    gestor = User.query.filter_by(email="gestor@test.com").first()
    inicio = datetime.now() - timedelta(hours=2)
    ap = Apontamento(user_id=gestor.id, inicio=inicio, fim=inicio + timedelta(hours=1),
                     duracao_s=3600, ref_tipo="livre", titulo="Do gestor")
    db.session.add(ap)
    db.session.commit()

    res = client.get(f"/tempos/api/apontamentos/{ap.id}", headers=H(tecnico_token))
    assert res.status_code == 403
    assert res.get_json() == {"erro": "Este apontamento é de outro usuário"}
    [linha] = _negados()
    assert linha.entidade == "GET /tempos/api/apontamentos/<int:ap_id>"
    assert linha.valor_novo == f"apontamento #{ap.id} de outro usuário"


def test_tempos_perfil_leitura_grava_pelo_require_role(client, leitura_token):
    assert client.get("/tempos/api/atual", headers=H(leitura_token)).status_code == 403
    [linha] = _negados()
    assert linha.valor_novo == "perfil leitura (exige admin, gestor, tecnico)"
