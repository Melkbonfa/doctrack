"""Lacunas do guia de validação da ANVISA fechadas no código.

Cada bloco fixa uma linha de docs/operacao/ADERENCIA_BPX.md: senha com
composição e validade, troca da própria senha, saída na trilha, contas-padrão
sem senha fixa, e a rede de segurança que impede escrita sem rastro.
"""
from datetime import datetime, timedelta

import pytest

import auth
from models import db, User, AuditLog, RevokedToken


def H(token):
    return {"Authorization": f"Bearer {token}"}


def _login(client, email, senha="demo123"):
    return client.post("/api/auth/login", json={"email": email, "senha": senha})


def _acoes(email=None):
    q = AuditLog.query.order_by(AuditLog.id)
    if email:
        q = q.filter_by(usuario_email=email)
    return [l.acao for l in q.all()]


# ── composição da senha (§21.2) ───────────────────────────────────────────────

@pytest.mark.parametrize("senha", ["somenteletras", "12345678", "letras1234", "!!!!!!!!", "a1!"])
def test_senha_sem_letra_numero_e_especial_e_recusada(senha):
    assert auth.erro_de_senha(senha)


@pytest.mark.parametrize("senha", ["senha-nova-1", "Abc12345!", "çã1_boaa"])
def test_senha_com_os_tres_tipos_passa(senha):
    assert auth.erro_de_senha(senha) is None


def test_composicao_pode_ser_desligada(monkeypatch):
    monkeypatch.setattr(auth, "SENHA_COMPOSICAO", False)
    assert auth.erro_de_senha("somenteletras") is None
    assert auth.erro_de_senha("curta")              # o tamanho continua valendo


# ── trocar a própria senha ────────────────────────────────────────────────────

def _trocar(client, email="tecnico@test.com", atual="demo123", nova="nova-Senha-1"):
    return client.post("/api/auth/trocar-senha",
                       json={"email": email, "senha_atual": atual, "senha_nova": nova})


def test_trocar_senha_entra_com_a_nova_e_grava_na_trilha(client):
    res = _trocar(client)
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["access_token"]
    assert _login(client, "tecnico@test.com", "demo123").status_code == 401
    assert _login(client, "tecnico@test.com", "nova-Senha-1").status_code == 200
    assert "PASSWORD_CHANGE" in _acoes("tecnico@test.com")


def test_trocar_senha_exige_a_senha_atual_e_conta_no_limite_do_login(client):
    for _ in range(5):
        assert _trocar(client, atual="errada").status_code == 401
    # o contador é o mesmo do login: a rota não é um segundo lugar para testar senha
    assert _trocar(client, atual="errada").status_code == 429
    assert _login(client, "tecnico@test.com").status_code == 429
    assert "LOGIN_FALHA" in _acoes("tecnico@test.com")


@pytest.mark.parametrize("nova,trecho", [
    ("curta1!", "pelo menos"), ("semnumero!!", "caractere especial"), ("demo123", "pelo menos"),
])
def test_trocar_senha_recusa_senha_nova_fraca(client, nova, trecho):
    res = _trocar(client, nova=nova)
    assert res.status_code == 400
    assert trecho in res.get_json()["erro"]


def test_trocar_senha_recusa_repetir_a_atual(client):
    assert _trocar(client, nova="nova-Senha-1").status_code == 200
    res = _trocar(client, atual="nova-Senha-1", nova="nova-Senha-1")
    assert res.status_code == 400
    assert "diferente" in res.get_json()["erro"]


def test_trocar_senha_nao_diz_se_o_email_tem_conta(client):
    a = _trocar(client, email="ninguem@test.com")
    b = _trocar(client, atual="errada")
    assert a.status_code == b.status_code == 401
    assert a.get_json() == b.get_json()


# ── validade da senha (§21.2) ─────────────────────────────────────────────────

def _envelhecer(email, dias):
    u = User.query.filter_by(email=email).first()
    u.senha_definida_em = datetime.now() - timedelta(days=dias)
    db.session.commit()


def test_definir_senha_grava_a_data(client):
    u = User.query.filter_by(email="tecnico@test.com").first()
    u.set_senha("qualquer-1")
    assert datetime.now() - u.senha_definida_em < timedelta(seconds=5)


def test_senha_vencida_nao_entra_e_a_troca_resolve(client, monkeypatch):
    monkeypatch.setattr(auth, "SENHA_VALIDADE_DIAS", 90)
    _envelhecer("tecnico@test.com", 91)

    res = _login(client, "tecnico@test.com")
    assert res.status_code == 403
    assert res.get_json()["senha_vencida"] is True
    assert "access_token" not in res.get_json()
    assert "LOGIN_SENHA_VENCIDA" in _acoes("tecnico@test.com")

    assert _trocar(client).status_code == 200
    assert _login(client, "tecnico@test.com", "nova-Senha-1").status_code == 200


def test_senha_dentro_da_validade_entra(client, monkeypatch):
    monkeypatch.setattr(auth, "SENHA_VALIDADE_DIAS", 90)
    _envelhecer("tecnico@test.com", 89)
    assert _login(client, "tecnico@test.com").status_code == 200


def test_validade_zero_desliga(client, monkeypatch):
    monkeypatch.setattr(auth, "SENHA_VALIDADE_DIAS", 0)
    _envelhecer("tecnico@test.com", 5000)
    assert _login(client, "tecnico@test.com").status_code == 200


def test_senha_errada_em_conta_vencida_nao_revela_o_vencimento(client, monkeypatch):
    monkeypatch.setattr(auth, "SENHA_VALIDADE_DIAS", 90)
    _envelhecer("tecnico@test.com", 91)
    res = _login(client, "tecnico@test.com", "errada")
    assert res.status_code == 401
    assert "senha_vencida" not in res.get_json()


# ── saída (§3.1) ──────────────────────────────────────────────────────────────

def test_logout_grava_na_trilha_e_revoga_o_refresh(client):
    sessao = _login(client, "tecnico@test.com").get_json()
    res = client.post("/api/auth/logout", headers=H(sessao["access_token"]),
                      json={"refresh_token": sessao["refresh_token"]})
    assert res.status_code == 200
    assert _acoes("tecnico@test.com")[-1] == "LOGOUT"
    # a sessão encerrada não reabre pelo refresh
    assert client.post("/api/auth/refresh",
                       headers=H(sessao["refresh_token"])).status_code == 401
    assert client.get("/api/documentos", headers=H(sessao["access_token"])).status_code == 401


def test_logout_por_inatividade_registra_o_motivo(client):
    sessao = _login(client, "tecnico@test.com").get_json()
    client.post("/api/auth/logout", headers=H(sessao["access_token"]),
                json={"refresh_token": sessao["refresh_token"], "motivo": "inatividade"})
    linha = AuditLog.query.filter_by(acao="LOGOUT").one()
    assert (linha.campo, linha.valor_novo) == ("motivo", "inatividade")


def test_logout_nao_revoga_o_refresh_de_outra_pessoa(client):
    meu = _login(client, "tecnico@test.com").get_json()
    alheio = _login(client, "gestor@test.com").get_json()
    client.post("/api/auth/logout", headers=H(meu["access_token"]),
                json={"refresh_token": alheio["refresh_token"]})
    assert client.post("/api/auth/refresh",
                       headers=H(alheio["refresh_token"])).status_code == 200


def test_logout_sem_corpo_continua_funcionando(client, tecnico_token):
    assert client.post("/api/auth/logout", headers=H(tecnico_token)).status_code == 200
    assert RevokedToken.query.count() == 1


def test_version_informa_o_limite_de_inatividade(client):
    corpo = client.get("/api/version").get_json()
    assert isinstance(corpo["inatividade_min"], int)


# ── contas-padrão (§21.2) ─────────────────────────────────────────────────────

def _esvaziar_usuarios():
    AuditLog.query.delete()
    User.query.delete()
    db.session.commit()


def test_banco_vazio_ganha_so_um_admin_sem_senha(app, monkeypatch, capsys):
    import servidor
    monkeypatch.delenv("DOCTRACK_CONTAS_DEMO", raising=False)
    monkeypatch.setenv("DOCTRACK_ADMIN_EMAIL", "Primeiro@Empresa.com")
    _esvaziar_usuarios()

    servidor.init_db()

    contas = User.query.all()
    assert [u.email for u in contas] == ["primeiro@empresa.com"]
    admin = contas[0]
    assert admin.role == "admin" and admin.precisa_definir_senha
    assert not admin.check_senha("admin123")
    # o código sai uma vez no log, e é ele que ativa a conta
    saida = capsys.readouterr().out
    codigo = [l for l in saida.splitlines() if "código de ativação" in l][0].split()[-1]
    assert admin.check_codigo(codigo)


def test_banco_com_usuarios_nao_ganha_conta_nenhuma(app, monkeypatch):
    import servidor
    monkeypatch.delenv("DOCTRACK_CONTAS_DEMO", raising=False)
    antes = {u.email for u in User.query.all()}
    servidor.init_db()
    assert {u.email for u in User.query.all()} == antes


def test_contas_de_demonstracao_so_a_pedido(app, monkeypatch):
    import servidor
    monkeypatch.setenv("DOCTRACK_CONTAS_DEMO", "1")
    _esvaziar_usuarios()
    servidor.init_db()
    emails = {u.email for u in User.query.all()}
    assert "admin@pde.com" in emails and "auditora@iso.com" in emails


# ── rede de segurança da trilha (§21.3) ───────────────────────────────────────

def test_escrita_que_nao_grava_na_trilha_ganha_linha_generica(client, admin_token):
    antes = AuditLog.query.count()
    res = client.post("/api/categorias-equipamento", json={"nome": "Categoria Rede"},
                      headers=H(admin_token))
    assert res.status_code == 201, res.get_json()
    novas = AuditLog.query.order_by(AuditLog.id).all()[antes:]
    assert len(novas) == 1
    linha = novas[0]
    assert (linha.usuario_email, linha.acao) == ("admin@test.com", "ESCRITA")
    assert linha.entidade == "POST /api/categorias-equipamento"
    assert (linha.campo, linha.valor_novo) == ("rota", "/api/categorias-equipamento")
    assert linha.usuario_id is not None and linha.timestamp is not None


def test_rota_com_registro_proprio_nao_ganha_linha_duplicada(client, admin_token):
    antes = AuditLog.query.count()
    res = client.post("/api/users", headers=H(admin_token),
                      json={"nome": "Nova Pessoa", "email": "nova@test.com", "role": "tecnico"})
    assert res.status_code == 201, res.get_json()
    acoes = [l.acao for l in AuditLog.query.order_by(AuditLog.id).all()[antes:]]
    assert "ESCRITA" not in acoes and len(acoes) >= 1


def test_escrita_recusada_e_leitura_nao_geram_linha(client, admin_token, leitura_token):
    antes = AuditLog.query.filter_by(acao="ESCRITA").count()
    client.get("/api/documentos", headers=H(admin_token))
    assert client.post("/api/categorias-equipamento", json={},
                       headers=H(admin_token)).status_code == 400
    assert client.post("/api/categorias-equipamento", json={"nome": "X"},
                       headers=H(leitura_token)).status_code == 403
    assert AuditLog.query.filter_by(acao="ESCRITA").count() == antes


def test_rotas_de_sessao_ficam_fora_da_rede(client):
    sessao = _login(client, "tecnico@test.com").get_json()
    client.post("/api/auth/refresh", headers=H(sessao["refresh_token"]))
    assert "ESCRITA" not in _acoes()


def test_toda_escrita_bem_sucedida_deixa_rastro(client, admin_token):
    """A garantia em si: qualquer POST/PUT/PATCH/DELETE de API que dá certo
    aumenta a trilha, grave a rota ou não."""
    chamadas = [
        ("POST", "/api/missoes", {"nome": "Frente Rastro"}),
        ("POST", "/api/categorias-equipamento", {"nome": "Categoria Rastro"}),
        ("POST", "/api/tipos-consumivel", {"nome": "Tipo Rastro"}),
    ]
    for metodo, rota, corpo in chamadas:
        antes = AuditLog.query.count()
        res = client.open(rota, method=metodo, json=corpo, headers=H(admin_token))
        assert 200 <= res.status_code < 300, (rota, res.get_json())
        assert AuditLog.query.count() > antes, f"{metodo} {rota} não deixou rastro"
