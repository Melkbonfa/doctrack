"""Testes do módulo Tempos (apontamento de horas).

A ordem aqui espelha a de construção: primeiro se prova que o banco sustenta a
invariante do cronômetro único, depois o cálculo, depois o RBAC de dono.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from tempos.models import Apontamento, LIMITE_CRONOMETRO_H


def _uid(email="tecnico@test.com"):
    from models import User
    return User.query.filter_by(email=email).first().id


def _user(email="tecnico@test.com"):
    from models import User
    return User.query.filter_by(email=email).first()


def _ap(user_id, inicio, fim=None, **kw):
    """Apontamento cru, sem passar pelo core — para montar cenário de banco."""
    dur = 0 if fim is None else int((fim - inicio).total_seconds())
    return Apontamento(user_id=user_id, inicio=inicio, fim=fim, duracao_s=dur,
                       ref_tipo=kw.pop("ref_tipo", "livre"),
                       titulo=kw.pop("titulo", "Teste"), **kw)


@pytest.fixture
def alvos(app):
    """Um de cada alvo cronometrável, para os testes de vínculo."""
    from models import db, Projeto, Entregavel, Missao, MissaoColuna, MissaoCartao, Equipamento

    p = Projeto(nome="Projeto Alfa", ativo=True)
    eq = Equipamento(nome="EQ-TEMPO", ativo=True)
    m = Missao(nome="Missao Teste")
    db.session.add_all([p, eq, m])
    db.session.flush()

    e = Entregavel(projeto_id=p.id, tipo="Desenho mecânico")
    col = MissaoColuna(missao_id=m.id, nome="Fazendo", ordem=0)
    db.session.add_all([e, col])
    db.session.flush()

    # Um cartão solto e um cartão que aponta para o projeto — a diferença entre
    # os dois é exatamente o que resolver_projeto tem de distinguir.
    c_solto = MissaoCartao(missao_id=m.id, coluna_id=col.id, titulo="Cartão solto")
    c_proj = MissaoCartao(missao_id=m.id, coluna_id=col.id, titulo="Cartão do projeto",
                          ref_tipo="projeto", ref_id=p.id)
    db.session.add_all([c_solto, c_proj])
    db.session.commit()

    return {"projeto": p.id, "entregavel": e.id, "equipamento": eq.id,
            "cartao_solto": c_solto.id, "cartao_projeto": c_proj.id}


# ══ A INVARIANTE DO CRONÔMETRO ÚNICO ══════════════════════════════════════════

def test_indice_parcial_existe_e_e_unico(app):
    """O índice parcial é a única parte do módulo que depende de um recurso do
    banco em vez de código. Se ele não existir, tudo o mais continua passando e a
    invariante some em produção — por isso é o primeiro teste."""
    from models import db
    from sqlalchemy import inspect

    idx = {i["name"]: i for i in inspect(db.engine).get_indexes("tempo_apontamentos")}
    assert "uq_tempo_em_curso" in idx, \
        "sem uq_tempo_em_curso nada impede dois cronômetros na mesma pessoa"
    assert idx["uq_tempo_em_curso"]["unique"]


def test_dois_cronometros_abertos_na_mesma_pessoa_sao_recusados(app):
    """O 409 da rota depende disto: com 8 threads num processo (render.yaml),
    clique duplo em 'Iniciar' é corrida real e quem resolve é o banco."""
    from models import db

    uid = _uid()
    db.session.add(_ap(uid, datetime.now() - timedelta(hours=1)))
    db.session.commit()

    db.session.add(_ap(uid, datetime.now()))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_o_indice_nao_atrapalha_linhas_fechadas(app):
    """Parcial de verdade: só a linha ABERTA é única. Um dia normal tem várias
    linhas fechadas da mesma pessoa — se o índice pegasse todas, pausar uma vez
    já quebraria o módulo."""
    from models import db

    uid = _uid()
    base = datetime.now() - timedelta(hours=8)
    for i in range(5):
        db.session.add(_ap(uid, base + timedelta(hours=i),
                           base + timedelta(hours=i, minutes=30)))
    db.session.add(_ap(uid, datetime.now()))     # e uma aberta por cima
    db.session.commit()

    assert Apontamento.query.filter_by(user_id=uid).count() == 6
    assert Apontamento.query.filter_by(user_id=uid, fim=None).count() == 1


def test_pessoas_diferentes_podem_ter_cronometros_simultaneos(app):
    from models import db

    db.session.add(_ap(_uid("tecnico@test.com"), datetime.now()))
    db.session.add(_ap(_uid("gestor@test.com"), datetime.now()))
    db.session.commit()

    assert Apontamento.query.filter_by(fim=None).count() == 2


# ══ CORE: RESOLUÇÃO DO PROJETO ════════════════════════════════════════════════

def test_resolver_projeto_cobre_os_cinco_alvos(app, alvos):
    from tempos.core import resolver_projeto

    assert resolver_projeto("projeto", alvos["projeto"]) == alvos["projeto"]
    assert resolver_projeto("entregavel", alvos["entregavel"]) == alvos["projeto"]
    assert resolver_projeto("equipamento", alvos["equipamento"]) is None
    assert resolver_projeto("livre", None, alvos["projeto"]) == alvos["projeto"]


def test_cartao_de_missao_so_alcanca_projeto_quando_aponta_para_um(app, alvos):
    """REF_TIPOS_CARTAO não tem caminho de cartão->projeto e Missao não tem
    projeto_id (models.py:1945 e :1977). Na maioria dos cartões o resultado é
    None, e é por isso que o relatório precisa do balde '(sem projeto)' — sem ele
    as horas do kanban sumiriam da soma por projeto em silêncio."""
    from tempos.core import resolver_projeto

    assert resolver_projeto("missao_cartao", alvos["cartao_solto"]) is None
    assert resolver_projeto("missao_cartao", alvos["cartao_projeto"]) == alvos["projeto"]


def test_projeto_congelado_nao_muda_quando_o_entregavel_e_remanejado(app, alvos):
    """Horas pertencem ao projeto em que foram gastas. Se isto virar uma property
    calculada, total histórico passa a mudar sozinho."""
    from models import db, Projeto, Entregavel
    from tempos import core

    ap = core.abrir(_user(), ref_tipo="entregavel", ref_id=alvos["entregavel"],
                    inicio=datetime.now() - timedelta(hours=2),
                    fim=datetime.now() - timedelta(hours=1))
    db.session.commit()
    assert ap.projeto_id == alvos["projeto"]

    outro = Projeto(nome="Projeto Beta", ativo=True)
    db.session.add(outro)
    db.session.flush()
    Entregavel.query.get(alvos["entregavel"]).projeto_id = outro.id
    db.session.commit()

    assert Apontamento.query.get(ap.id).projeto_id == alvos["projeto"]


# ══ CORE: DURAÇÃO, CONFLITO E A GUARDA ════════════════════════════════════════

def test_fechar_mantem_duracao_igual_ao_intervalo(app):
    from models import db
    from tempos.core import abrir, fechar

    ini = datetime.now() - timedelta(hours=3)
    ap = abrir(_user(), titulo="X", inicio=ini)
    fechar(ap, ini + timedelta(hours=2, minutes=30))
    db.session.commit()

    assert ap.duracao_s == int((ap.fim - ap.inicio).total_seconds()) == 9000


def test_fechar_nunca_produz_duracao_negativa(app):
    """Relógio que anda para trás (NTP, horário de verão) não pode injetar
    duração negativa no SUM."""
    from models import db
    from tempos.core import abrir, fechar

    ini = datetime.now()
    ap = abrir(_user(), titulo="X", inicio=ini)
    fechar(ap, ini - timedelta(hours=1))
    db.session.commit()

    assert ap.duracao_s == 0
    assert ap.fim == ap.inicio


def test_pausar_e_retomar_encadeiam_a_mesma_sessao(app):
    from models import db
    from tempos.core import abrir, fechar, retomar

    u = _user()
    a = abrir(u, titulo="Relatório", inicio=datetime.now() - timedelta(hours=2))
    fechar(a, datetime.now() - timedelta(hours=1), "pausa")
    db.session.commit()

    b = retomar(a, u)
    db.session.commit()

    assert b.sessao_id == a.sessao_id == a.id
    assert b.ref_tipo == a.ref_tipo and b.titulo == a.titulo
    assert b.fim is None


def test_conflita_encontra_sobreposicao_e_ignora_o_proprio(app):
    from models import db
    from tempos.core import conflita

    uid = _uid()
    base = datetime.now() - timedelta(hours=5)
    existente = _ap(uid, base, base + timedelta(hours=2))
    db.session.add(existente)
    db.session.commit()

    assert conflita(uid, base + timedelta(hours=1), base + timedelta(hours=3))
    assert conflita(uid, base + timedelta(hours=3), base + timedelta(hours=4)) is None
    # editar a própria linha não pode colidir consigo mesma
    assert conflita(uid, base, base + timedelta(hours=2),
                    ignorar_id=existente.id) is None


def test_guarda_corta_no_limite_e_nao_no_agora(app):
    """Fechar em `agora` faria o número depender de quando a guarda rodou — na
    segunda o cronômetro de sexta valeria 64h em vez de 12h."""
    from models import db
    from tempos.core import encerrar_abandonados

    uid = _uid()
    ini = datetime.now() - timedelta(hours=40)
    db.session.add(_ap(uid, ini))
    db.session.commit()

    assert encerrar_abandonados() == 1
    ap = Apontamento.query.filter_by(user_id=uid).first()
    assert ap.encerrado_por == "guarda"
    assert ap.duracao_s == LIMITE_CRONOMETRO_H * 3600
    assert ap.fim == ini + timedelta(hours=LIMITE_CRONOMETRO_H)


def test_guarda_e_idempotente(app):
    """Rodar duas vezes não pode mudar o número — o agendador refaz a tarefa se o
    processo reiniciar no meio do dia."""
    from models import db
    from tempos.core import encerrar_abandonados

    db.session.add(_ap(_uid(), datetime.now() - timedelta(hours=40)))
    db.session.commit()

    encerrar_abandonados()
    ap = Apontamento.query.first()
    fim1, dur1 = ap.fim, ap.duracao_s

    assert encerrar_abandonados() == 0
    db.session.refresh(ap)
    assert (ap.fim, ap.duracao_s) == (fim1, dur1)


def test_guarda_nao_toca_cronometro_dentro_do_limite(app):
    from models import db
    from tempos.core import encerrar_abandonados

    db.session.add(_ap(_uid(), datetime.now() - timedelta(hours=2)))
    db.session.commit()

    assert encerrar_abandonados() == 0
    assert Apontamento.query.first().fim is None


# ══ CORE: PARSE E VALIDAÇÃO ═══════════════════════════════════════════════════

def test_parse_dt_aceita_o_que_o_front_manda_e_recusa_o_resto():
    from tempos.core import parse_dt

    assert parse_dt("2026-03-10T14:30") == datetime(2026, 3, 10, 14, 30)
    assert parse_dt("2026-03-10T14:30:15") == datetime(2026, 3, 10, 14, 30, 15)
    assert parse_dt("2026-03-10 14:30") == datetime(2026, 3, 10, 14, 30)
    assert parse_dt("10/03/2026") is None       # sem adivinhação de locale
    assert parse_dt("ontem") is None
    assert parse_dt("") is None


def test_validar_intervalo_barra_futuro_invertido_e_absurdo():
    from tempos.core import validar_intervalo

    agora = datetime(2026, 3, 10, 12, 0)
    ok = validar_intervalo(agora - timedelta(hours=2), agora - timedelta(hours=1), agora)
    assert ok is None

    assert validar_intervalo(agora, agora - timedelta(hours=1), agora)
    assert validar_intervalo(agora, agora + timedelta(hours=3), agora)
    assert validar_intervalo(agora - timedelta(hours=30), agora, agora)
    assert validar_intervalo(agora - timedelta(days=200),
                             agora - timedelta(days=200) + timedelta(hours=1), agora)


# ══ ROTAS: CICLO DO CRONÔMETRO ════════════════════════════════════════════════

def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_ciclo_iniciar_pausar_retomar_parar(client, tecnico_token, alvos):
    h = _h(tecnico_token)

    r = client.post("/tempos/api/iniciar", headers=h,
                    json={"ref_tipo": "projeto", "ref_id": alvos["projeto"]})
    assert r.status_code == 201
    assert r.get_json()["em_curso"] is True

    r = client.get("/tempos/api/atual", headers=h)
    corpo = r.get_json()
    assert corpo["em_curso"] and corpo["servidor_agora"]

    assert client.post("/tempos/api/atual/pausar", headers=h).status_code == 200

    r = client.get("/tempos/api/atual", headers=h)
    corpo = r.get_json()
    assert corpo["em_curso"] is None
    assert corpo["retomavel"] is not None
    pausado = corpo["retomavel"]["id"]

    r = client.post(f"/tempos/api/{pausado}/retomar", headers=h)
    assert r.status_code == 201
    assert r.get_json()["sessao_id"] == corpo["retomavel"]["sessao_id"]

    assert client.post("/tempos/api/atual/parar", headers=h).status_code == 200
    assert client.get("/tempos/api/atual", headers=h).get_json()["em_curso"] is None


def test_iniciar_duas_vezes_devolve_409_e_nao_500(client, tecnico_token):
    """Clique duplo é corrida real com 8 threads num processo. O banco recusa e a
    rota tem de traduzir isso para 409 com o cronômetro corrente no corpo."""
    h = _h(tecnico_token)
    assert client.post("/tempos/api/iniciar", headers=h,
                       json={"titulo": "Primeira"}).status_code == 201

    r = client.post("/tempos/api/iniciar", headers=h, json={"titulo": "Segunda"})
    assert r.status_code == 409
    assert r.get_json()["em_curso"]["titulo"] == "Primeira"


def test_servidor_ignora_o_inicio_mandado_pelo_cliente(client, tecnico_token):
    """Relógio de navegador errado não pode corromper o dado."""
    h = _h(tecnico_token)
    r = client.post("/tempos/api/iniciar", headers=h,
                    json={"titulo": "X", "inicio": "1999-01-01T00:00"})
    assert r.status_code == 201
    assert r.get_json()["inicio_iso"].startswith(str(datetime.now().year))


def test_tarefa_livre_exige_titulo(client, tecnico_token):
    r = client.post("/tempos/api/iniciar", headers=_h(tecnico_token), json={})
    assert r.status_code == 400


def test_alvo_inexistente_e_recusado(client, tecnico_token):
    r = client.post("/tempos/api/iniciar", headers=_h(tecnico_token),
                    json={"ref_tipo": "projeto", "ref_id": 99999})
    assert r.status_code == 400


# ══ ROTAS: LANÇAMENTO MANUAL ══════════════════════════════════════════════════

def _manual(client, token, ini, fim, **kw):
    corpo = {"titulo": kw.pop("titulo", "Reunião"), "inicio": ini, "fim": fim}
    corpo.update(kw)
    return client.post("/tempos/api/apontamentos", headers=_h(token), json=corpo)


def test_lancamento_manual_grava_e_soma(client, tecnico_token):
    ontem = (datetime.now() - timedelta(days=1)).replace(hour=9, minute=0, second=0,
                                                         microsecond=0)
    r = _manual(client, tecnico_token, ontem.strftime("%Y-%m-%dT%H:%M"),
                (ontem + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"))
    assert r.status_code == 201
    assert r.get_json()["duracao_s"] == 7200

    r = client.get("/tempos/api/apontamentos", headers=_h(tecnico_token))
    assert r.get_json()["total_s"] == 7200


def test_lancamento_manual_sobreposto_devolve_409_com_o_conflito(client, tecnico_token):
    ontem = (datetime.now() - timedelta(days=1)).replace(hour=9, minute=0, second=0,
                                                         microsecond=0)
    _manual(client, tecnico_token, ontem.strftime("%Y-%m-%dT%H:%M"),
            (ontem + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"))

    r = _manual(client, tecnico_token,
                (ontem + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
                (ontem + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M"))
    assert r.status_code == 409
    # Dizer QUAL linha conflita é o ponto — "conflita com algo" não ajuda ninguém.
    assert r.get_json()["conflito"]["duracao_s"] == 7200


def test_manual_no_futuro_e_recusado(client, tecnico_token):
    amanha = datetime.now() + timedelta(days=1)
    r = _manual(client, tecnico_token, amanha.strftime("%Y-%m-%dT%H:%M"),
                (amanha + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"))
    assert r.status_code == 400


# ══ ROTAS: RBAC DE DONO (os quatro testes de IDOR) ════════════════════════════

@pytest.fixture
def ap_do_gestor(app):
    """Uma linha que pertence ao gestor — o alvo dos testes de acesso alheio."""
    from models import db

    ini = datetime.now() - timedelta(hours=4)
    ap = _ap(_uid("gestor@test.com"), ini, ini + timedelta(hours=1),
             titulo="Coisa do gestor")
    db.session.add(ap)
    db.session.commit()
    return ap.id


def test_tecnico_nao_le_apontamento_alheio(client, tecnico_token, ap_do_gestor):
    r = client.get(f"/tempos/api/apontamentos/{ap_do_gestor}", headers=_h(tecnico_token))
    assert r.status_code == 403
    # O corpo do 403 não pode devolver nada da linha.
    assert "Coisa do gestor" not in r.get_data(as_text=True)


def test_tecnico_nao_edita_apontamento_alheio(client, tecnico_token, ap_do_gestor):
    r = client.put(f"/tempos/api/apontamentos/{ap_do_gestor}",
                   headers=_h(tecnico_token), json={"nota": "invadido"})
    assert r.status_code == 403


def test_tecnico_nao_exclui_apontamento_alheio(client, tecnico_token, ap_do_gestor):
    r = client.delete(f"/tempos/api/apontamentos/{ap_do_gestor}",
                      headers=_h(tecnico_token))
    assert r.status_code == 403
    assert Apontamento.query.get(ap_do_gestor) is not None


def test_listagem_ignora_o_user_id_pedido_por_quem_nao_e_gestao(client, tecnico_token,
                                                               ap_do_gestor):
    """O teste que pega o bug de verdade. O front é o mesmo para todos os perfis e
    sempre manda user_id; se a rota respeitasse o parâmetro (ou só filtrasse
    'quando não vier'), qualquer técnico leria a folha do time inteiro."""
    from models import db

    ini = datetime.now() - timedelta(hours=2)
    db.session.add(_ap(_uid(), ini, ini + timedelta(minutes=30), titulo="Minha linha"))
    db.session.commit()

    gestor_id = _uid("gestor@test.com")
    r = client.get(f"/tempos/api/apontamentos?user_id={gestor_id}",
                   headers=_h(tecnico_token))
    assert r.status_code == 200
    linhas = r.get_json()["apontamentos"]
    assert linhas and all(a["user_id"] != gestor_id for a in linhas)


def test_export_tem_o_mesmo_escopo_da_listagem(client, tecnico_token, ap_do_gestor):
    """Export mais frouxo que a lista é vazamento pela planilha — por isso os dois
    passam pelo mesmo _query_escopada."""
    gestor_id = _uid("gestor@test.com")
    r = client.get(f"/tempos/api/export/apontamentos.csv?user_id={gestor_id}",
                   headers=_h(tecnico_token))
    assert r.status_code == 200
    assert "Coisa do gestor" not in r.get_data(as_text=True)


def test_gestor_le_e_corrige_a_folha_do_time(client, gestor_token, app):
    from models import db

    ini = datetime.now() - timedelta(hours=3)
    ap = _ap(_uid("tecnico@test.com"), ini, ini + timedelta(hours=1), titulo="Do técnico")
    db.session.add(ap)
    db.session.commit()

    assert client.get(f"/tempos/api/apontamentos/{ap.id}",
                      headers=_h(gestor_token)).status_code == 200
    r = client.put(f"/tempos/api/apontamentos/{ap.id}", headers=_h(gestor_token),
                   json={"nota": "conferido"})
    assert r.status_code == 200
    # A correção do gestor fica visível — aprovação silenciosa é aprovação sem
    # consentimento.
    assert r.get_json()["editado"] is True
    assert r.get_json()["editado_por"] == "gestor@test.com"


def test_gestor_nao_retoma_apontamento_alheio(client, gestor_token, ap_do_gestor, app):
    """Retomar CRIA linha. Gestor retomando o alheio personificaria a pessoa ou
    reatribuiria o trabalho em silêncio — supervisão é ler e corrigir."""
    from models import db

    ini = datetime.now() - timedelta(hours=2)
    ap = _ap(_uid("tecnico@test.com"), ini, ini + timedelta(hours=1),
             titulo="Do técnico", encerrado_por="pausa")
    db.session.add(ap)
    db.session.commit()

    r = client.post(f"/tempos/api/{ap.id}/retomar", headers=_h(gestor_token))
    assert r.status_code == 403


def test_leitura_nao_alcanca_o_modulo(client, leitura_token):
    """`leitura` é auditoria externa: não executa entregas e não precisa saber
    quem gastou quanto em quê."""
    h = _h(leitura_token)
    for metodo, url in ((client.get, "/tempos/api/atual"),
                        (client.get, "/tempos/api/meta"),
                        (client.get, "/tempos/api/apontamentos"),
                        (client.post, "/tempos/api/iniciar"),
                        (client.get, "/tempos/api/resumo"),
                        (client.get, "/tempos/api/export/apontamentos.csv")):
        assert metodo(url, headers=h).status_code == 403, url


def test_rotas_exigem_token(client):
    assert client.get("/tempos/api/atual").status_code == 401
    assert client.get("/tempos/api/apontamentos").status_code == 401


# ══ ROTAS: RESUMO ═════════════════════════════════════════════════════════════

def test_resumo_por_projeto_mostra_o_balde_sem_projeto(client, tecnico_token, alvos, app):
    """Horas de cartão de missão quase nunca resolvem para um projeto. Se elas
    sumissem da soma, o total por projeto subcontaria o kanban em silêncio."""
    from models import db
    from tempos import core

    u = _user()
    base = datetime.now() - timedelta(hours=6)
    core.abrir(u, ref_tipo="projeto", ref_id=alvos["projeto"],
               inicio=base, fim=base + timedelta(hours=1))
    core.abrir(u, ref_tipo="missao_cartao", ref_id=alvos["cartao_solto"],
               inicio=base + timedelta(hours=2), fim=base + timedelta(hours=3))
    db.session.commit()

    r = client.get("/tempos/api/resumo?por=projeto", headers=_h(tecnico_token))
    rotulos = {g["rotulo"] for g in r.get_json()["grupos"]}
    assert "Projeto Alfa" in rotulos
    assert core.SEM_PROJETO in rotulos


def test_por_ref_agrega_sem_revelar_quem_fez(client, tecnico_token, alvos, app):
    from models import db
    from tempos import core

    base = datetime.now() - timedelta(hours=5)
    core.abrir(_user("tecnico@test.com"), ref_tipo="equipamento",
               ref_id=alvos["equipamento"], inicio=base, fim=base + timedelta(hours=1))
    core.abrir(_user("gestor@test.com"), ref_tipo="equipamento",
               ref_id=alvos["equipamento"], inicio=base, fim=base + timedelta(hours=2))
    db.session.commit()

    r = client.get(f"/tempos/api/por-ref?ref_tipo=equipamento&ref_id={alvos['equipamento']}",
                   headers=_h(tecnico_token))
    corpo = r.get_json()
    assert corpo["total_s"] == 10800 and corpo["pessoas"] == 2
    assert "user_id" not in corpo and "apontamentos" not in corpo


# ══ A CURA NA LEITURA ═════════════════════════════════════════════════════════

def test_atual_fecha_o_cronometro_abandonado_da_propria_pessoa(client, tecnico_token, app):
    """O agendador só passa depois da meia-noite, então o timer de sexta só seria
    cortado no sábado. Aqui a pessoa já vê o número certo na segunda de manhã."""
    from models import db

    ini = datetime.now() - timedelta(hours=40)
    db.session.add(_ap(_uid(), ini))
    db.session.commit()

    r = client.get("/tempos/api/atual", headers=_h(tecnico_token))
    assert r.get_json()["em_curso"] is None

    ap = Apontamento.query.first()
    assert ap.encerrado_por == "guarda"
    assert ap.duracao_s == LIMITE_CRONOMETRO_H * 3600


def test_total_bate_com_a_soma_das_linhas_exibidas(client, tecnico_token, app):
    """O total somava `duracao_s` (zero na linha aberta) enquanto a tabela exibia
    o tempo vivo: a folha mostrava uma linha de "40h em curso" e um total de
    12h45 logo acima dela. Divergência assim faz a pessoa parar de confiar no
    número inteiro."""
    from models import db

    base = datetime.now() - timedelta(hours=4)
    db.session.add(_ap(_uid(), base, base + timedelta(hours=1)))
    db.session.add(_ap(_uid(), datetime.now() - timedelta(hours=2)))   # aberta
    db.session.commit()

    corpo = client.get("/tempos/api/apontamentos", headers=_h(tecnico_token)).get_json()
    assert corpo["total_s"] == sum(a["duracao_s"] for a in corpo["apontamentos"])
    assert corpo["total_s"] > 3600          # a linha aberta entra na conta


def test_folha_fecha_cronometro_abandonado_de_outra_pessoa(client, gestor_token, app):
    """A cura de /atual é por dono, então o timer esquecido de um técnico ficava
    aberto na folha do time até a tarefa diária passar — e o gestor via '40h em
    curso' no meio do relatório."""
    from models import db

    db.session.add(_ap(_uid("tecnico@test.com"), datetime.now() - timedelta(hours=40)))
    db.session.commit()

    client.get("/tempos/api/apontamentos", headers=_h(gestor_token))

    ap = Apontamento.query.first()
    assert ap.fim is not None
    assert ap.encerrado_por == "guarda"
    assert ap.duracao_s == LIMITE_CRONOMETRO_H * 3600


# ══ O WIDGET GLOBAL ═══════════════════════════════════════════════════════════
# Duas armadilhas de template que falham EM SILÊNCIO: a página carrega, nada
# quebra no console, e o cronômetro simplesmente não existe. Só um teste textual
# pega isso — por isso são baratos e valem a pena.

def _ler(rel):
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parent.parent
    return (raiz / rel).read_text(encoding="utf-8")


def test_widget_fica_fora_do_block_scripts_do_base():
    """base.html define {% block scripts %}, mas os CINCO filhos o sobrescrevem
    sem {{ super() }}. Um <script> lá dentro carregaria em ZERO páginas."""
    html = _ler("templates/base.html")
    assert "tempos-widget.js" in html
    assert html.index("tempos-widget.js") > html.rindex("{%- endblock %}"), \
        "o <script> do widget caiu dentro de um block Jinja — não vai carregar"
    assert "tempos-widget.css" in html


def test_projetos_tambem_recebe_o_widget():
    """entregaveis.html (servida em /projetos) NÃO estende base.html: tem <head>
    próprio. Sem as duas linhas na mão, Projetos fica sem cronômetro."""
    html = _ler("templates/entregaveis.html")
    assert "{% extends" not in html          # se um dia passar a estender, remover as linhas
    assert "tempos-widget.js" in html and "tempos-widget.css" in html


def test_widget_e_iife_sem_vazar_escopo():
    """Na página /tempos/ este arquivo carrega junto de tempos.js. Dois `const` de
    topo com o mesmo nome é SyntaxError que mata OS DOIS scripts e deixa o #app
    escondido — o modo de falha do f7b65e7, invisível no DOM."""
    js = _ler("static/tempos-widget.js").strip()
    assert js.endswith("})();")
    corpo = js[js.index("(function(){"):]
    assert "\nconst " not in corpo and "\nlet " not in corpo, \
        "declaração de topo fora da IIFE colide com tempos.js"


@pytest.mark.parametrize("url", ["/", "/equipamentos", "/missoes", "/projetos",
                                 "/config", "/custos/", "/tempos/", "/hub", "/hub/pde"])
def test_toda_pagina_ainda_renderiza(client, url):
    """O widget é injetado em templates COMPARTILHADOS: um erro no base.html
    derruba os cinco módulos de uma vez, não só Tempos.

    Este teste nasceu de um erro real: o comentário que explicava o widget
    continha uma chamada a super() entre chaves duplas, e comentário de HTML não
    é comentário de Jinja — a expressão foi avaliada e TODA página passou a
    devolver 500. A checagem textual acima não pegava; só renderizar pega."""
    res = client.get(url)
    assert res.status_code == 200, f"{url} quebrou: HTTP {res.status_code}"
    corpo = res.get_data(as_text=True)
    if url not in ("/hub", "/hub/pde"):
        assert "tempos-widget.js" in corpo, f"{url} ficou sem o cronômetro global"


# ══ INTEGRAÇÃO COM OS OUTROS MÓDULOS ══════════════════════════════════════════
# A direção é cartão -> cronômetro, e não o inverso. Apontar a partir do alvo é o
# fluxo natural (o cartão é o plano, o apontamento é o registro contra ele) e é o
# que faz a "tarefa livre" encolher na origem. Ver docs/planos/PLANO_modulo_tempos.md.

@pytest.mark.parametrize("arquivo,ref_tipo", [
    ("static/missoes.js", "missao_cartao"),
    ("static/equipamentos.js", "equipamento"),
    ("static/entregaveis.js", "projeto"),
])
def test_modulos_apontam_tempo_no_alvo_certo(arquivo, ref_tipo):
    js = _ler(arquivo)
    assert "DT_TEMPO.iniciar" in js, f"{arquivo} não dispara o cronômetro"
    assert f'ref_tipo:"{ref_tipo}"' in js, f"{arquivo} usa o ref_tipo errado"
    # Cada um lê o acumulado pelo endpoint agregado, que não revela quem fez o quê.
    assert f"por-ref?ref_tipo={ref_tipo}" in js


@pytest.mark.parametrize("arquivo", ["static/missoes.js", "static/equipamentos.js",
                                     "static/entregaveis.js"])
def test_modulos_nao_duplicam_o_estado_do_cronometro(arquivo):
    """Quem manda no cronômetro é o widget. Um módulo que chamasse /iniciar ou
    /pausar direto teria um segundo estado, divergente do que o widget desenha em
    todas as outras telas."""
    js = _ler(arquivo)
    for rota in ("/tempos/api/iniciar", "/tempos/api/atual"):
        assert rota not in js, f"{arquivo} fala com {rota} por fora do DT_TEMPO"


def test_por_ref_e_o_unico_endpoint_de_tempos_exposto_aos_modulos():
    """`por-ref` devolve só agregado (total, linhas, pessoas). É o que permite
    mostrar o acumulado numa ficha sem vazar a folha de ninguém."""
    js = _ler("static/missoes.js") + _ler("static/equipamentos.js") + _ler("static/entregaveis.js")
    import re
    rotas = set(re.findall(r"/tempos/api/[a-z\-]+", js))
    assert rotas == {"/tempos/api/por-ref"}, f"rotas inesperadas nos módulos: {rotas}"


def test_pagina_de_tempos_revela_o_app():
    """A regressão do commit f7b65e7: sem o boot que revela o #app, a página
    carrega inteira e fica invisível."""
    js = _ler("static/tempos.js")
    assert 'getElementById("app").style.display' in js
    assert "if(!token())" in js
    assert "if(!PODE_USAR)" in js


# ── REGRESSÕES DA REVISÃO ─────────────────────────────────────────────────────

def test_editar_so_o_titulo_preserva_o_projeto_da_tarefa_livre(client,
                                                               tecnico_token, app):
    """Corrigir o título não pode levar as horas embora do relatório do projeto.

    O PUT recalculava o rollup a cada edição que tocasse título/alvo. Para
    ref_tipo='livre', `resolver_projeto` devolve o projeto_id DO CORPO — que numa
    edição só de título não vem — então o vínculo escolhido na criação virava
    None em silêncio.
    """
    from models import db, Projeto

    with app.app_context():
        p = Projeto(nome="Projeto do apontamento livre", ativo=True)
        db.session.add(p)
        db.session.commit()
        pid = p.id

    h = _h(tecnico_token)
    ontem = datetime.now() - timedelta(days=1)
    res = client.post("/tempos/api/apontamentos", headers=h, json={
        "ref_tipo": "livre", "titulo": "Reuniao", "projeto_id": pid,
        "inicio": ontem.replace(hour=9, minute=0).strftime("%Y-%m-%dT%H:%M"),
        "fim": ontem.replace(hour=10, minute=0).strftime("%Y-%m-%dT%H:%M"),
    })
    assert res.status_code == 201, res.get_json()
    ap_id = res.get_json()["id"]
    assert res.get_json()["projeto_id"] == pid

    res = client.put(f"/tempos/api/apontamentos/{ap_id}", headers=h,
                     json={"titulo": "Reuniao de kickoff"})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["projeto_id"] == pid, "editar o título apagou o projeto"


def test_put_recusa_horario_malformado_em_vez_de_ignorar(client, tecnico_token):
    """Data ilegível tem que virar 400, não 200 com o valor antigo.

    O PUT fazia `parse_dt(...) or valor_atual`: um horário impossível voltava 200
    e a pessoa via a correção "salva" com o número errado intacto — o pior par
    possível num módulo cujo produto é o número.
    """
    h = _h(tecnico_token)
    ontem = datetime.now() - timedelta(days=1)
    res = client.post("/tempos/api/apontamentos", headers=h, json={
        "ref_tipo": "livre", "titulo": "Bancada",
        "inicio": ontem.replace(hour=9, minute=0).strftime("%Y-%m-%dT%H:%M"),
        "fim": ontem.replace(hour=11, minute=0).strftime("%Y-%m-%dT%H:%M"),
    })
    ap_id = res.get_json()["id"]

    res = client.put(f"/tempos/api/apontamentos/{ap_id}", headers=h,
                     json={"fim": "31/02/2026 25:61"})
    assert res.status_code == 400, res.get_json()

    # E o campo ausente continua sendo "não mexer", não um erro.
    res = client.put(f"/tempos/api/apontamentos/{ap_id}", headers=h,
                     json={"nota": "so a nota"})
    assert res.status_code == 200, res.get_json()


def test_resumo_por_alvo_nao_consulta_o_banco_uma_vez_por_linha(client,
                                                                tecnico_token, app):
    """`agregar(por='alvo')` chamava `ap.rotulo()` sem mapa: 1 query por linha.

    No teto da rota (5.000 linhas) isso é uma tempestade de consultas para montar
    um resumo. `core.mapa_refs` resolve em 1 query por TIPO de alvo.
    """
    from sqlalchemy import event

    from models import db, Projeto

    with app.app_context():
        ids = []
        for i in range(12):
            p = Projeto(nome=f"Proj resumo {i}", ativo=True)
            db.session.add(p)
            db.session.flush()
            ids.append(p.id)
        db.session.commit()

    h = _h(tecnico_token)
    base = (datetime.now() - timedelta(days=2)).replace(hour=6, minute=0,
                                                        second=0, microsecond=0)
    for i, pid in enumerate(ids):
        ini = base + timedelta(hours=i)
        res = client.post("/tempos/api/apontamentos", headers=h, json={
            "ref_tipo": "projeto", "ref_id": pid, "titulo": f"T{i}",
            "inicio": ini.strftime("%Y-%m-%dT%H:%M"),
            "fim": (ini + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M"),
        })
        assert res.status_code == 201, res.get_json()

    contador = {"n": 0}

    def _conta(conn, cursor, stmt, params, context, many):
        if stmt.lstrip().upper().startswith("SELECT"):
            contador["n"] += 1

    with app.app_context():
        event.listen(db.engine, "before_cursor_execute", _conta)
        try:
            res = client.get("/tempos/api/resumo?por=alvo", headers=h)
        finally:
            event.remove(db.engine, "before_cursor_execute", _conta)

    assert res.status_code == 200, res.get_json()
    assert len(res.get_json()["grupos"]) == 12
    assert contador["n"] < 12, (
        f"N+1: {contador['n']} SELECTs para agregar 12 linhas por alvo")


def test_por_ref_soma_no_banco_e_mantem_o_numero(client, tecnico_token, app):
    """A rota agrega com SUM/COUNT em vez de materializar o histórico do alvo.

    Ela é chamada a cada abertura de ficha em Missões/Equipamentos/Projetos, e
    carregar todas as linhas do alvo cresce sem teto com a idade do sistema. A
    linha ABERTA continua somada em Python — `duracao_viva` é relógio correndo.
    """
    from models import db, Projeto, User

    with app.app_context():
        p = Projeto(nome="Alvo por-ref", ativo=True)
        db.session.add(p)
        db.session.commit()
        pid = p.id
        tec = User.query.filter_by(email="tecnico@test.com").first().id
        ges = User.query.filter_by(email="gestor@test.com").first().id

        base = datetime.now() - timedelta(days=3)
        db.session.add(_ap(tec, base, base + timedelta(hours=1),      # 3600s
                           ref_tipo="projeto", ref_id=pid, projeto_id=pid))
        db.session.add(_ap(tec, base + timedelta(hours=2),            # 1800s
                           base + timedelta(hours=2, minutes=30),
                           ref_tipo="projeto", ref_id=pid, projeto_id=pid))
        # aberta, de OUTRA pessoa, começada há 10 min -> ~600s vivos
        db.session.add(_ap(ges, datetime.now() - timedelta(minutes=10), None,
                           ref_tipo="projeto", ref_id=pid, projeto_id=pid))
        db.session.commit()

    res = client.get(f"/tempos/api/por-ref?ref_tipo=projeto&ref_id={pid}",
                     headers=_h(tecnico_token))
    assert res.status_code == 200, res.get_json()
    d = res.get_json()
    assert d["linhas"] == 3, d
    assert d["pessoas"] == 2, d
    assert 5900 <= d["total_s"] <= 6100, d          # 3600 + 1800 + ~600 vivos


def test_por_ref_de_alvo_sem_apontamento_devolve_zero(client, tecnico_token, app):
    """O coalesce do SUM: sem linhas, o agregado é 0 e não None."""
    from models import db, Projeto

    with app.app_context():
        p = Projeto(nome="Alvo sem horas", ativo=True)
        db.session.add(p)
        db.session.commit()
        pid = p.id

    res = client.get(f"/tempos/api/por-ref?ref_tipo=projeto&ref_id={pid}",
                     headers=_h(tecnico_token))
    assert res.status_code == 200
    d = res.get_json()
    assert (d["total_s"], d["linhas"], d["pessoas"]) == (0, 0, 0), d
