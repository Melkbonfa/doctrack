"""Testes de autenticação JWT, login, logout, blocklist."""
import ratelimit
from models import AuditLog


def test_login_success_returns_token(client):
    res = client.post("/api/auth/login", json={"email": "admin@test.com", "senha": "admin123"})
    assert res.status_code == 200
    data = res.get_json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["usuario"]["role"] == "admin"


def test_login_wrong_password(client):
    res = client.post("/api/auth/login", json={"email": "admin@test.com", "senha": "errada"})
    assert res.status_code == 401
    assert "erro" in res.get_json()


def test_login_email_inexistente(client):
    res = client.post("/api/auth/login", json={"email": "nope@test.com", "senha": "x"})
    assert res.status_code == 401


def test_login_missing_fields(client):
    res = client.post("/api/auth/login", json={})
    assert res.status_code == 400


def test_protected_endpoint_without_token(client):
    res = client.get("/api/documentos")
    assert res.status_code == 401


def test_logout_revokes_token(client, admin_token, auth_headers):
    # Token funciona antes do logout
    r1 = client.get("/api/documentos", headers=auth_headers(admin_token))
    assert r1.status_code == 200

    # Logout
    r2 = client.post("/api/auth/logout", headers=auth_headers(admin_token))
    assert r2.status_code == 200

    # Token não funciona mais
    r3 = client.get("/api/documentos", headers=auth_headers(admin_token))
    assert r3.status_code == 401


def test_jwt_secret_required(monkeypatch):
    """Importar servidor sem JWT_SECRET (env e .env) levanta RuntimeError."""
    import os, sys, importlib
    
    # Backup do módulo servidor original
    orig_servidor = sys.modules.get("servidor")
    
    monkeypatch.delenv("JWT_SECRET", raising=False)
    # Neutralizar load_dotenv para não recuperar o valor de .env
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
    
    sys.modules.pop("servidor", None)
    try:
        importlib.import_module("servidor")
        raised = False
    except RuntimeError:
        raised = True
    finally:
        # Restaurar o módulo servidor original
        if orig_servidor:
            sys.modules["servidor"] = orig_servidor
        else:
            sys.modules.pop("servidor", None)
            
    assert raised, "RuntimeError esperado quando JWT_SECRET ausente"


# ── PRIMEIRO ACESSO / CONVITE / RESET ──────────────────────────────────────────

def _criar_convite(client, admin_token, auth_headers, email="novo@test.com"):
    """Admin cria usuário sem senha e devolve (codigo, user_id)."""
    res = client.post("/api/users", headers=auth_headers(admin_token),
                      json={"nome": "Novo User", "email": email, "role": "tecnico"})
    assert res.status_code == 201, res.get_json()
    data = res.get_json()
    return data["codigo_ativacao"], data["usuario"]["id"], data


def test_create_user_sem_senha_gera_codigo(client, admin_token, auth_headers):
    codigo, uid, data = _criar_convite(client, admin_token, auth_headers)
    assert codigo and len(codigo) >= 6
    assert data["usuario"]["precisa_definir_senha"] is True


def test_criar_usuario_com_senha_e_recusado(client, admin_token, auth_headers):
    """R-05: o admin não define a senha de ninguém — passaria a conhecê-la, e
    as ações daquela conta deixariam de ser atribuíveis só ao dono dela."""
    res = client.post("/api/users", headers=auth_headers(admin_token),
                      json={"nome": "Com Senha", "email": "comsenha@test.com",
                            "role": "tecnico", "senha": "senhaDoAdmin1"})
    assert res.status_code == 400
    assert "código de ativação" in res.get_json()["erro"]
    # Nada foi criado, nem pela metade.
    from models import User
    assert User.query.filter_by(email="comsenha@test.com").first() is None
    assert AuditLog.query.filter_by(acao="CREATE", entidade="comsenha@test.com").count() == 0


def test_criar_usuario_com_senha_vazia_tambem_e_recusado(client, admin_token, auth_headers):
    """O campo em si é recusado: a tela antiga mandava a chave só quando havia
    senha, então quem a manda é cliente fora do fluxo atual."""
    res = client.post("/api/users", headers=auth_headers(admin_token),
                      json={"nome": "Vazia", "email": "vazia@test.com",
                            "role": "tecnico", "senha": ""})
    assert res.status_code == 400


def test_editar_usuario_com_senha_e_recusado_inteiro(client, admin_token, auth_headers):
    """PATCH com senha não aplica nada: nem a senha, nem os outros campos."""
    from models import User
    h = auth_headers(admin_token)
    alvo = User.query.filter_by(email="tecnico@test.com").first()
    res = client.patch(f"/api/users/{alvo.id}", headers=h,
                       json={"nome": "Nome Trocado", "senha": "senhaDoAdmin1"})
    assert res.status_code == 400
    assert "Resetar senha" in res.get_json()["erro"]

    assert User.query.filter_by(email="tecnico@test.com").first().nome == "Tecnico Test"
    assert client.post("/api/auth/login", json={"email": "tecnico@test.com",
                                                "senha": "senhaDoAdmin1"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "tecnico@test.com",
                                                "senha": "demo123"}).status_code == 200
    assert AuditLog.query.filter_by(acao="UPDATE", entidade="tecnico@test.com").count() == 0


def test_editar_usuario_sem_senha_continua_funcionando(client, admin_token, auth_headers):
    from models import User
    alvo = User.query.filter_by(email="tecnico@test.com").first()
    res = client.patch(f"/api/users/{alvo.id}", headers=auth_headers(admin_token),
                       json={"nome": "Nome Trocado", "role": "tecnico"})
    assert res.status_code == 200
    assert res.get_json()["usuario"]["nome"] == "Nome Trocado"


def test_login_bloqueado_conta_pendente(client, admin_token, auth_headers):
    _criar_convite(client, admin_token, auth_headers, email="pend@test.com")
    res = client.post("/api/auth/login", json={"email": "pend@test.com", "senha": "qualquer"})
    assert res.status_code == 403
    assert res.get_json().get("precisa_definir_senha") is True


def test_primeiro_acesso_com_codigo_correto(client, admin_token, auth_headers):
    codigo, _uid, _ = _criar_convite(client, admin_token, auth_headers, email="ok@test.com")
    res = client.post("/api/auth/primeiro-acesso",
                      json={"email": "ok@test.com", "codigo": codigo, "senha": "novaSenha1"})
    assert res.status_code == 200, res.get_json()
    assert "access_token" in res.get_json()
    # Agora o login normal funciona
    login = client.post("/api/auth/login", json={"email": "ok@test.com", "senha": "novaSenha1"})
    assert login.status_code == 200


def test_primeiro_acesso_codigo_errado(client, admin_token, auth_headers):
    _criar_convite(client, admin_token, auth_headers, email="bad@test.com")
    res = client.post("/api/auth/primeiro-acesso",
                      json={"email": "bad@test.com", "codigo": "ZZZZZZZZ", "senha": "novaSenha1"})
    assert res.status_code == 400


def test_primeiro_acesso_senha_curta(client, admin_token, auth_headers):
    codigo, _uid, _ = _criar_convite(client, admin_token, auth_headers, email="short@test.com")
    res = client.post("/api/auth/primeiro-acesso",
                      json={"email": "short@test.com", "codigo": codigo, "senha": "123"})
    assert res.status_code == 400


def test_reset_senha_admin(client, admin_token, auth_headers):
    # Técnico do seed já tem senha; admin reseta
    users = client.get("/api/users", headers=auth_headers(admin_token)).get_json()
    tecnico = next(u for u in users if u["email"] == "tecnico@test.com")
    res = client.post(f"/api/users/{tecnico['id']}/reset-senha", headers=auth_headers(admin_token))
    assert res.status_code == 200
    codigo = res.get_json()["codigo_ativacao"]
    # Senha antiga não funciona mais
    assert client.post("/api/auth/login",
                       json={"email": "tecnico@test.com", "senha": "demo123"}).status_code == 403
    # Usuário redefine via primeiro acesso
    assert client.post("/api/auth/primeiro-acesso",
                       json={"email": "tecnico@test.com", "codigo": codigo,
                             "senha": "outraSenha1"}).status_code == 200
    assert client.post("/api/auth/login",
                       json={"email": "tecnico@test.com", "senha": "outraSenha1"}).status_code == 200


def test_reset_senha_requer_admin(client, tecnico_token, auth_headers):
    res = client.post("/api/users/1/reset-senha", headers=auth_headers(tecnico_token))
    assert res.status_code == 403


def test_delete_permanente_remove_usuario(client, admin_token, auth_headers):
    _codigo, uid, _ = _criar_convite(client, admin_token, auth_headers, email="del@test.com")
    res = client.delete(f"/api/users/{uid}?permanente=true", headers=auth_headers(admin_token))
    assert res.status_code == 200
    assert "permanentemente" in res.get_json()["mensagem"]
    # Some do da listagem e não loga mais
    users = client.get("/api/users", headers=auth_headers(admin_token)).get_json()
    assert all(u["email"] != "del@test.com" for u in users)
    login = client.post("/api/auth/login", json={"email": "del@test.com", "senha": "x"})
    assert login.status_code == 401


def test_delete_permanente_com_auditoria_vinculada(client, admin_token, auth_headers):
    """Usuário com log de auditoria próprio (FIRST_ACCESS) deve excluir sem violar FK."""
    codigo, uid, _ = _criar_convite(client, admin_token, auth_headers, email="aud@test.com")
    # Gera um AuditLog com usuario_id = aud@test.com
    client.post("/api/auth/primeiro-acesso",
                json={"email": "aud@test.com", "codigo": codigo, "senha": "senhaForte1"})
    res = client.delete(f"/api/users/{uid}?permanente=true", headers=auth_headers(admin_token))
    assert res.status_code == 200


def test_delete_permanente_self_bloqueado(client, admin_token, auth_headers):
    users = client.get("/api/users", headers=auth_headers(admin_token)).get_json()
    admin = next(u for u in users if u["email"] == "admin@test.com")
    res = client.delete(f"/api/users/{admin['id']}?permanente=true", headers=auth_headers(admin_token))
    assert res.status_code == 400


def test_delete_soft_continua_padrao(client, admin_token, auth_headers):
    _codigo, uid, _ = _criar_convite(client, admin_token, auth_headers, email="soft@test.com")
    res = client.delete(f"/api/users/{uid}", headers=auth_headers(admin_token))
    assert res.status_code == 200
    assert "desativado" in res.get_json()["mensagem"]
    # Continua existindo, apenas inativo
    users = client.get("/api/users", headers=auth_headers(admin_token)).get_json()
    alvo = next(u for u in users if u["email"] == "soft@test.com")
    assert alvo["ativo"] is False


# ── AUDITORIA DAS TENTATIVAS RECUSADAS ─────────────────────────────────────────
# A validação de sistema computadorizado exige registrar as tentativas de acesso
# de quem não está autorizado. Antes só o login certo ia para audit_logs; a
# falha ficava no contador em memória do rate limit e sumia no reinício.

IP_ATACANTE = "10.66.6.6"


def _post(client, rota, ip=IP_ATACANTE, **corpo):
    return client.post(rota, json=corpo, environ_base={"REMOTE_ADDR": ip})


def _linhas(acao):
    return AuditLog.query.filter_by(acao=acao).order_by(AuditLog.id).all()


def _nenhuma_coluna_contem(segredo):
    """O segredo digitado não pode aparecer em nenhum campo de nenhuma linha."""
    for linha in AuditLog.query.all():
        for coluna in AuditLog.__table__.columns:
            valor = getattr(linha, coluna.name)
            assert segredo not in str(valor or ""), \
                f"segredo gravado em audit_logs.{coluna.name} ({linha.acao})"


def test_login_falha_grava_email_e_ip(client):
    res = _post(client, "/api/auth/login", email="admin@test.com", senha="errada")
    assert res.status_code == 401

    [linha] = _linhas("LOGIN_FALHA")
    assert linha.usuario_email == "admin@test.com"
    assert linha.usuario_id is not None              # a conta alvo fica ligada
    assert linha.ip == IP_ATACANTE
    assert linha.valor_novo == "senha incorreta"


def test_login_falha_email_sem_conta_grava_o_email_informado(client):
    res = _post(client, "/api/auth/login", email="Fantasma@Test.com ", senha="x")
    assert res.status_code == 401

    [linha] = _linhas("LOGIN_FALHA")
    assert linha.usuario_email == "fantasma@test.com"
    assert linha.usuario_id is None
    assert linha.ip == IP_ATACANTE
    assert linha.valor_novo == "e-mail sem conta ativa"


def test_login_falha_nao_revela_se_o_email_existe(client):
    """O motivo vai só para a auditoria; o cliente vê a mesma resposta."""
    com_conta = _post(client, "/api/auth/login", email="admin@test.com", senha="x")
    sem_conta = _post(client, "/api/auth/login", email="nope@test.com", senha="x")
    assert com_conta.status_code == sem_conta.status_code == 401
    assert com_conta.get_json() == sem_conta.get_json() == {"erro": "Email ou senha incorretos"}


def test_login_sucesso_continua_gravando_login(client):
    res = _post(client, "/api/auth/login", email="admin@test.com", senha="admin123")
    assert res.status_code == 200

    [linha] = _linhas("LOGIN")
    assert linha.usuario_email == "admin@test.com"
    assert linha.ip == IP_ATACANTE
    assert _linhas("LOGIN_FALHA") == []


def test_senha_digitada_nao_vai_para_a_auditoria(client):
    senha = "Chute-Muito-Especifico-42"
    _post(client, "/api/auth/login", email="admin@test.com", senha=senha)
    _post(client, "/api/auth/login", email="nope@test.com", senha=senha)
    assert len(_linhas("LOGIN_FALHA")) == 2
    _nenhuma_coluna_contem(senha)


def test_email_gigante_nao_estoura_a_coluna(client):
    """usuario_email é varchar(120): no PostgreSQL estourar seria um 500."""
    email = "a" * 500 + "@test.com"
    res = _post(client, "/api/auth/login", email=email, senha="x")
    assert res.status_code == 401
    [linha] = _linhas("LOGIN_FALHA")
    assert len(linha.usuario_email) == 120


def test_bloqueio_grava_uma_linha_e_nao_uma_por_requisicao(client):
    """Cada 429 virando linha faria do limite o jeito de inundar a auditoria."""
    for _ in range(ratelimit.LIMITE_LOGIN):
        assert _post(client, "/api/auth/login", email="admin@test.com",
                     senha="errada").status_code == 401
    for _ in range(4):
        assert _post(client, "/api/auth/login", email="admin@test.com",
                     senha="errada").status_code == 429

    assert len(_linhas("LOGIN_FALHA")) == ratelimit.LIMITE_LOGIN
    [bloqueio] = _linhas("LOGIN_BLOQUEADO")
    assert bloqueio.usuario_email == "admin@test.com"
    assert bloqueio.ip == IP_ATACANTE
    assert bloqueio.valor_novo == "limite por e-mail"


def test_bloqueio_de_outro_ip_e_outra_linha(client):
    for ip in (IP_ATACANTE, "10.66.6.7"):
        for _ in range(ratelimit.LIMITE_LOGIN + 2):
            _post(client, "/api/auth/login", ip=ip, email="admin@test.com", senha="x")
    assert sorted(l.ip for l in _linhas("LOGIN_BLOQUEADO")) == [IP_ATACANTE, "10.66.6.7"]


def test_bloqueio_por_ip_nao_multiplica_trocando_de_email(client):
    """A varredura que troca de e-mail a cada tentativa bate no teto por IP —
    e trocar de e-mail não pode gerar uma linha de bloqueio por requisição."""
    for i in range(ratelimit.LIMITE_IP):
        assert _post(client, "/api/auth/login", email=f"varre{i}@test.com",
                     senha="x").status_code == 401
    for i in range(5):
        assert _post(client, "/api/auth/login", email=f"outro{i}@test.com",
                     senha="x").status_code == 429

    [bloqueio] = _linhas("LOGIN_BLOQUEADO")
    assert bloqueio.valor_novo == "limite por IP"
    assert bloqueio.ip == IP_ATACANTE


def test_ativacao_codigo_errado_grava_sem_o_codigo(client, admin_token, auth_headers):
    _criar_convite(client, admin_token, auth_headers, email="alvo@test.com")
    chute = "QK7ZP2XW"
    res = _post(client, "/api/auth/primeiro-acesso",
                email="alvo@test.com", codigo=chute, senha="senhaLonga1")
    assert res.status_code == 400
    assert res.get_json() == {"erro": "Código de ativação incorreto."}

    [linha] = _linhas("ATIVACAO_FALHA")
    assert linha.usuario_email == "alvo@test.com"
    assert linha.ip == IP_ATACANTE
    assert linha.valor_novo == "código incorreto"
    _nenhuma_coluna_contem(chute)
    _nenhuma_coluna_contem("senhaLonga1")


def test_ativacao_sem_pendencia_grava_e_conta_no_limite(client):
    """Antes esta recusa não contava no limite: uma varredura de e-mails no
    primeiro acesso não custava nada e não deixava rastro."""
    for _ in range(ratelimit.LIMITE_ATIVACAO):
        res = _post(client, "/api/auth/primeiro-acesso",
                    email="ninguem@test.com", codigo="AAAAAAAA", senha="senhaLonga1")
        assert res.status_code == 400
        assert "Não há primeiro acesso pendente" in res.get_json()["erro"]
    assert _post(client, "/api/auth/primeiro-acesso", email="ninguem@test.com",
                 codigo="AAAAAAAA", senha="senhaLonga1").status_code == 429

    falhas = _linhas("ATIVACAO_FALHA")
    assert len(falhas) == ratelimit.LIMITE_ATIVACAO
    assert {l.valor_novo for l in falhas} == {"sem primeiro acesso pendente"}
    assert all(l.usuario_email == "ninguem@test.com" and l.ip == IP_ATACANTE
               for l in falhas)
    [bloqueio] = _linhas("ATIVACAO_BLOQUEADA")
    assert bloqueio.usuario_email == "ninguem@test.com"


def test_ativacao_codigo_expirado_grava(client, admin_token, auth_headers):
    from datetime import datetime, timedelta
    from models import db, User

    codigo, uid, _ = _criar_convite(client, admin_token, auth_headers, email="velho@test.com")
    user = db.session.get(User, uid)
    user.ativacao_expira = datetime.now() - timedelta(days=1)
    db.session.commit()

    res = _post(client, "/api/auth/primeiro-acesso",
                email="velho@test.com", codigo=codigo, senha="senhaLonga1")
    assert res.status_code == 400
    assert "expirado" in res.get_json()["erro"]
    [linha] = _linhas("ATIVACAO_FALHA")
    assert linha.valor_novo == "código expirado"
    _nenhuma_coluna_contem(codigo)


def test_403_de_perfil_vai_para_a_auditoria_como_acesso_negado(client, leitura_token,
                                                               auth_headers):
    """Antes ficava de fora; desde o R-06 entra, deduplicado por usuário e rota.
    Os detalhes estão em tests/test_acesso_negado.py."""
    assert client.get("/api/users", headers=auth_headers(leitura_token)).status_code == 403
    assert len(_linhas("ACESSO_NEGADO")) == 1
