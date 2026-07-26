"""Testes do endurecimento de segurança e do agendador.

Cobre o limite de tentativas nas duas rotas públicas (login e primeiro acesso),
a política de senha e as tarefas diárias — que antes só rodavam na subida do
servidor, deixando as séries temporais com um único ponto.
"""
import ratelimit


# ── RATE LIMIT ───────────────────────────────────────────────────────────────

def test_login_bloqueia_apos_tentativas_falhas(client):
    """Brute force de senha para em 429, não em tentativa infinita."""
    for _ in range(ratelimit.LIMITE_LOGIN):
        res = client.post("/api/auth/login",
                          json={"email": "admin@test.com", "senha": "errada"})
        assert res.status_code == 401

    res = client.post("/api/auth/login",
                      json={"email": "admin@test.com", "senha": "errada"})
    assert res.status_code == 429
    assert res.headers.get("Retry-After")
    assert "Muitas tentativas" in res.get_json()["erro"]

    # a senha certa também é barrada enquanto o bloqueio vale — é o ponto
    assert client.post("/api/auth/login",
                       json={"email": "admin@test.com",
                             "senha": "admin123"}).status_code == 429


def test_login_correto_nao_conta_como_tentativa(client):
    """Contar acerto puniria o uso normal: quem entra certo não está atacando."""
    for _ in range(ratelimit.LIMITE_LOGIN * 2):
        res = client.post("/api/auth/login",
                          json={"email": "admin@test.com", "senha": "admin123"})
        assert res.status_code == 200


def test_acerto_zera_o_contador_de_falhas(client):
    for _ in range(ratelimit.LIMITE_LOGIN - 1):
        client.post("/api/auth/login",
                    json={"email": "gestor@test.com", "senha": "errada"})
    assert client.post("/api/auth/login",
                       json={"email": "gestor@test.com",
                             "senha": "demo123"}).status_code == 200
    # contador limpo: erra de novo e ainda não bloqueia
    assert client.post("/api/auth/login",
                       json={"email": "gestor@test.com",
                             "senha": "errada"}).status_code == 401


def test_bloqueio_de_um_email_nao_afeta_outro(client):
    """A chave inclui a identidade para um usuário não travar o login do colega."""
    for _ in range(ratelimit.LIMITE_LOGIN + 1):
        client.post("/api/auth/login",
                    json={"email": "admin@test.com", "senha": "errada"})
    assert client.post("/api/auth/login",
                       json={"email": "gestor@test.com",
                             "senha": "demo123"}).status_code == 200


def test_primeiro_acesso_limita_tentativas_de_codigo(client, admin_token, auth_headers):
    """Código de ativação são 8 caracteres que valem uma conta inteira."""
    h = auth_headers(admin_token)
    client.post("/api/users", json={"nome": "Alvo Ativacao",
                                    "email": "alvo@test.com",
                                    "role": "tecnico"}, headers=h)

    for _ in range(ratelimit.LIMITE_ATIVACAO):
        res = client.post("/api/auth/primeiro-acesso",
                          json={"email": "alvo@test.com", "codigo": "ZZZZZZZZ",
                                "senha": "senhaLonga1"})
        assert res.status_code == 400

    res = client.post("/api/auth/primeiro-acesso",
                      json={"email": "alvo@test.com", "codigo": "ZZZZZZZZ",
                            "senha": "senhaLonga1"})
    assert res.status_code == 429


def test_ratelimit_pode_ser_desligado(client, monkeypatch):
    """A rede fabril pode ter um caso de uso legítimo de muitas tentativas."""
    monkeypatch.setenv("DOCTRACK_RATELIMIT", "0")
    for _ in range(ratelimit.LIMITE_LOGIN + 3):
        assert client.post("/api/auth/login",
                           json={"email": "admin@test.com",
                                 "senha": "errada"}).status_code == 401


# ── POLÍTICA DE SENHA ────────────────────────────────────────────────────────

def test_senha_curta_e_rejeitada_na_criacao(client, admin_token, auth_headers):
    """Mínimo passou de 6 para 8 caracteres."""
    from auth import SENHA_MIN
    assert SENHA_MIN >= 8
    res = client.post("/api/users",
                      json={"nome": "Curta", "email": "curta@test.com",
                            "role": "tecnico", "senha": "1234567"},
                      headers=auth_headers(admin_token))
    assert res.status_code == 400
    assert str(SENHA_MIN) in res.get_json()["erro"]


def test_senha_curta_e_rejeitada_na_edicao(client, admin_token, auth_headers):
    h = auth_headers(admin_token)
    users = client.get("/api/users", headers=h).get_json()
    alvo = next(u for u in users if u["email"] == "tecnico@test.com")
    assert client.patch(f"/api/users/{alvo['id']}", json={"senha": "curta1"},
                        headers=h).status_code == 400
    assert client.patch(f"/api/users/{alvo['id']}", json={"senha": "senhaBoa123"},
                        headers=h).status_code == 200


# ── TAREFAS DIÁRIAS ──────────────────────────────────────────────────────────

def test_tarefas_diarias_gravam_a_foto_do_dia(app):
    """Antes só a subida do servidor gravava snapshot: as tabelas tinham UMA
    data e os gráficos de evolução desenhavam um ponto só."""
    from datetime import date
    from models import db, EquipamentoSnapshot, Equipamento
    from servidor import rodar_tarefas_diarias

    with app.app_context():
        db.session.add(Equipamento(nome="EQ-SNAP", ativo=True))
        db.session.commit()
        assert EquipamentoSnapshot.query.count() == 0

        resultado = rodar_tarefas_diarias()
        assert set(resultado) == {"equipamentos", "missoes", "projetos", "auditoria"}
        hoje = date.today().isoformat()
        assert EquipamentoSnapshot.query.filter_by(data=hoje).count() >= 1


def test_tarefas_diarias_sao_idempotentes_no_dia(app):
    from models import db, EquipamentoSnapshot, Equipamento
    from servidor import rodar_tarefas_diarias

    with app.app_context():
        db.session.add(Equipamento(nome="EQ-SNAP2", ativo=True))
        db.session.commit()
        rodar_tarefas_diarias()
        n = EquipamentoSnapshot.query.count()
        rodar_tarefas_diarias()
        assert EquipamentoSnapshot.query.count() == n


def test_retencao_de_auditoria_desligada_por_padrao(app):
    """Auditoria é registro de conformidade: apagar por conta própria seria pior
    que a tabela crescer. Só limpa quando a política é declarada."""
    from datetime import datetime, timedelta
    from models import db, AuditLog
    from servidor import _purgar_auditoria

    with app.app_context():
        db.session.add(AuditLog(usuario_email="velho@test.com", acao="LOGIN",
                                timestamp=datetime.now() - timedelta(days=800)))
        db.session.commit()
        assert _purgar_auditoria() == 0
        assert AuditLog.query.filter_by(usuario_email="velho@test.com").count() == 1


def test_retencao_de_auditoria_quando_configurada(app, monkeypatch):
    from datetime import datetime, timedelta
    from models import db, AuditLog
    from servidor import _purgar_auditoria

    monkeypatch.setenv("DOCTRACK_AUDIT_RETENCAO_DIAS", "365")
    with app.app_context():
        db.session.add(AuditLog(usuario_email="velho@test.com", acao="LOGIN",
                                timestamp=datetime.now() - timedelta(days=800)))
        db.session.add(AuditLog(usuario_email="novo@test.com", acao="LOGIN",
                                timestamp=datetime.now()))
        db.session.commit()
        assert _purgar_auditoria() == 1
        assert AuditLog.query.filter_by(usuario_email="velho@test.com").count() == 0
        assert AuditLog.query.filter_by(usuario_email="novo@test.com").count() == 1


def test_agendador_roda_uma_vez_por_dia(app):
    """A checagem por data é o que torna o restart do serviço inofensivo."""
    import scheduler
    chamadas = []
    scheduler._ultimo_dia = None
    assert scheduler.rodar_uma_vez(app, lambda: chamadas.append(1)) is True
    assert scheduler.rodar_uma_vez(app, lambda: chamadas.append(1)) is False
    assert scheduler.rodar_uma_vez(app, lambda: chamadas.append(1), forcar=True) is True
    assert len(chamadas) == 2
    scheduler._ultimo_dia = None


def test_agendador_sobrevive_a_tarefa_que_explode(app):
    """Tarefa que falha não pode derrubar a thread — no dia seguinte tenta de novo."""
    import scheduler

    def explode():
        raise RuntimeError("falha proposital")

    scheduler._ultimo_dia = None
    assert scheduler.rodar_uma_vez(app, explode) is False
    scheduler._ultimo_dia = None


# ── IMPORT SEM EFEITO COLATERAL ──────────────────────────────────────────────

def test_importar_servidor_nao_prepara_banco():
    """`import servidor` rodava create_all, um UPDATE em documentos, todos os
    backfills e escritas de snapshot contra o banco real — inclusive no pytest.
    Agora isso é init_app(), chamado só por quem sobe o servidor."""
    import servidor
    assert callable(servidor.init_app)
    assert callable(servidor.rodar_tarefas_diarias)
    # wsgi.py é o entrypoint que faz a preparação explicitamente
    import pathlib
    wsgi = pathlib.Path(servidor.__file__).parent / "wsgi.py"
    assert "init_app()" in wsgi.read_text(encoding="utf-8")
