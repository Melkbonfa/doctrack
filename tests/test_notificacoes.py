"""
Testes do pacote `notificacoes` — a caixa de entrada por pessoa (o sino).

O que se trava aqui:
  * `notificar()` deduplica, pula quem agiu e quem está inativo;
  * cada um só alcança as próprias notificações (a de outra pessoa é 404, não
    403: o id é sequencial e confirmar que ele existe já seria um vazamento);
  * a purga diária só apaga o que já foi lido.
"""
from datetime import datetime, timedelta


def _uid(app, email):
    from models import User
    with app.app_context():
        return User.query.filter_by(email=email).first().id


def _notificar(app, ids, **kw):
    from models import db
    from notificacoes import core
    base = dict(tipo="info", titulo="Manual X", texto="andou", link="/?doc=1",
                origem_tipo="fluxo", origem_id=1)
    base.update(kw)
    with app.app_context():
        n = core.notificar(ids, **base)
        db.session.commit()
        return n


def test_notificar_deduplica_e_pula_quem_agiu(app):
    from notificacoes.models import Notificacao
    tec, ges = _uid(app, "tecnico@test.com"), _uid(app, "gestor@test.com")
    criadas = _notificar(app, [tec, tec, ges], exceto=ges)
    assert criadas == 1
    with app.app_context():
        linhas = Notificacao.query.all()
        assert [n.user_id for n in linhas] == [tec]


def test_notificar_pula_usuario_inativo(app):
    from models import db, User
    from notificacoes.models import Notificacao
    tec = _uid(app, "tecnico@test.com")
    with app.app_context():
        db.session.get(User, tec).ativo = False
        db.session.commit()
    assert _notificar(app, [tec]) == 0
    with app.app_context():
        assert Notificacao.query.count() == 0


def test_lista_e_conta_so_as_minhas(app, client, tecnico_token, gestor_token, auth_headers):
    tec, ges = _uid(app, "tecnico@test.com"), _uid(app, "gestor@test.com")
    _notificar(app, [tec], titulo="para o técnico")
    _notificar(app, [ges], titulo="para o gestor")

    r = client.get("/api/notificacoes", headers=auth_headers(tecnico_token))
    assert r.status_code == 200
    titulos = [n["titulo"] for n in r.get_json()["notificacoes"]]
    assert titulos == ["para o técnico"]

    r = client.get("/api/notificacoes/contagem", headers=auth_headers(tecnico_token))
    assert r.get_json() == {"nao_lidas": 1}


def test_marcar_lida_a_propria(app, client, tecnico_token, auth_headers):
    from notificacoes.models import Notificacao
    tec = _uid(app, "tecnico@test.com")
    _notificar(app, [tec])
    with app.app_context():
        nid = Notificacao.query.first().id

    r = client.post(f"/api/notificacoes/{nid}/lida", headers=auth_headers(tecnico_token))
    assert r.status_code == 200
    r = client.get("/api/notificacoes/contagem", headers=auth_headers(tecnico_token))
    assert r.get_json() == {"nao_lidas": 0}
    r = client.get("/api/notificacoes?nao_lidas=1", headers=auth_headers(tecnico_token))
    assert r.get_json()["notificacoes"] == []


def test_marcar_lida_a_alheia_e_404(app, client, tecnico_token, auth_headers):
    from notificacoes.models import Notificacao
    ges = _uid(app, "gestor@test.com")
    _notificar(app, [ges])
    with app.app_context():
        nid = Notificacao.query.first().id
    r = client.post(f"/api/notificacoes/{nid}/lida", headers=auth_headers(tecnico_token))
    assert r.status_code == 404
    with app.app_context():
        assert Notificacao.query.first().lida_em is None


def test_marcar_todas(app, client, tecnico_token, auth_headers):
    tec, ges = _uid(app, "tecnico@test.com"), _uid(app, "gestor@test.com")
    _notificar(app, [tec])
    _notificar(app, [tec])
    _notificar(app, [ges])
    r = client.post("/api/notificacoes/lidas", headers=auth_headers(tecnico_token))
    assert r.get_json() == {"marcadas": 2}
    from notificacoes.models import Notificacao
    with app.app_context():
        assert Notificacao.query.filter_by(user_id=ges, lida_em=None).count() == 1


def test_leitura_fica_fora(client, leitura_token, auth_headers):
    r = client.get("/api/notificacoes/contagem", headers=auth_headers(leitura_token))
    assert r.status_code == 403


def test_purga_apaga_so_lidas_antigas(app):
    from models import db
    from notificacoes import core
    from notificacoes.models import Notificacao
    tec = _uid(app, "tecnico@test.com")
    for _ in range(3):
        _notificar(app, [tec])
    velho = datetime.now() - timedelta(days=120)
    with app.app_context():
        a, b, c = Notificacao.query.order_by(Notificacao.id).all()
        a.lida_em, a.criada_em = velho, velho          # lida e antiga: sai
        b.criada_em = velho                            # antiga, não lida: fica
        c.lida_em = datetime.now()                     # lida, recente: fica
        db.session.commit()
        assert core.purgar_lidas(dias=90) == 1
        assert Notificacao.query.count() == 2
