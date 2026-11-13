"""Entrada malformada não derruba a API, e o erro sempre volta em JSON.

O front faz `res.json()` em toda resposta de /api/. Uma varredura das rotas com
corpo e parâmetros errados achou dezenas de pontos que respondiam 500 com a
página HTML do werkzeug — a maior parte por um motivo só (corpo JSON que não é
objeto). Estes testes fixam o contrato, não cada rota.
"""
from datetime import datetime, timedelta

import pytest

from models import db, User, RevokedToken


def H(token):
    return {"Authorization": f"Bearer {token}"}


# ── corpo que não é objeto ────────────────────────────────────────────────────

@pytest.mark.parametrize("corpo", ["texto", [1, 2], 5, True])
@pytest.mark.parametrize("metodo,rota", [
    ("POST",  "/api/documentos"),
    ("POST",  "/api/equipamentos"),
    ("POST",  "/api/missoes"),
    ("POST",  "/api/projetos"),
    ("POST",  "/api/users"),
    ("POST",  "/tempos/api/iniciar"),
    ("POST",  "/custos/api/composicoes"),
    ("POST",  "/cadernos/api/cadernos"),
    ("POST",  "/pdr/api/produtos"),
    ("PUT",   "/api/documento/1/status"),
])
def test_corpo_que_nao_e_objeto_responde_400_em_json(client, admin_token, metodo, rota, corpo):
    res = client.open(rota, method=metodo, json=corpo, headers=H(admin_token))
    assert res.status_code == 400
    assert "erro" in res.get_json()


@pytest.mark.parametrize("rota", ["/api/auth/login", "/api/auth/primeiro-acesso",
                                  "/api/kill-switch/unlock"])
def test_rota_publica_tambem_recusa_corpo_que_nao_e_objeto(client, rota):
    res = client.post(rota, json="texto")
    assert res.status_code == 400
    assert "erro" in res.get_json()


def test_corpo_vazio_e_objeto_continuam_passando(client, admin_token):
    # sem corpo: a rota decide (aqui, falta o nome)
    assert client.post("/api/missoes", headers=H(admin_token)).status_code == 400
    # objeto válido segue normalmente
    res = client.post("/api/missoes", json={"nome": "Frente A"}, headers=H(admin_token))
    assert res.status_code in (200, 201)


# ── campos de tipo errado nas rotas públicas ──────────────────────────────────

@pytest.mark.parametrize("corpo", [
    {"email": None, "senha": "x"},
    {"email": 123, "senha": "x"},
    {"email": ["a"], "senha": "x"},
    {"email": "admin@test.com", "senha": 123},
    {"email": "admin@test.com", "senha": None},
])
def test_login_com_campo_de_tipo_errado_e_400(client, corpo):
    res = client.post("/api/auth/login", json=corpo)
    assert res.status_code == 400
    assert "erro" in res.get_json()


@pytest.mark.parametrize("corpo", [
    {"email": None, "codigo": "A1B2C3D4", "senha": "senha-nova-1"},
    {"email": "a@b.com", "codigo": 12345678, "senha": "senha-nova-1"},
    {"email": "a@b.com", "codigo": "A1B2C3D4", "senha": ["x"]},
])
def test_primeiro_acesso_com_campo_de_tipo_errado_e_400(client, corpo):
    res = client.post("/api/auth/primeiro-acesso", json=corpo)
    assert res.status_code == 400


def test_editar_usuario_com_nome_nulo_nao_quebra(client, admin_token):
    with client.application.app_context():
        uid = User.query.filter_by(email="tecnico@test.com").first().id
    res = client.patch(f"/api/users/{uid}", json={"nome": None, "email": 5},
                       headers=H(admin_token))
    assert res.status_code == 200
    assert res.get_json()["usuario"]["nome"] == "Tecnico Test"     # nada mudou


# ── conversões de inteiro ─────────────────────────────────────────────────────

def test_reordenar_com_coluna_invalida_e_400(client, admin_token):
    res = client.post("/api/missoes/reordenar", json={"coluna_id": "x", "ids": []},
                      headers=H(admin_token))
    assert res.status_code == 400


def test_cartao_rapido_com_missao_invalida_e_404_em_json(client, admin_token):
    res = client.post("/api/missoes/cartao-rapido",
                      json={"missao_id": "abc", "titulo": "X"}, headers=H(admin_token))
    assert res.status_code == 404
    assert "erro" in res.get_json()


def test_pdr_filtro_por_produto_invalido_e_400(client, admin_token):
    res = client.get("/pdr/api/apresentacoes?produto_id=x", headers=H(admin_token))
    assert res.status_code == 400


# ── erros HTTP da API em JSON ─────────────────────────────────────────────────

def test_rota_de_api_inexistente_responde_json(client, admin_token):
    res = client.get("/api/nao-existe", headers=H(admin_token))
    assert res.status_code == 404
    assert res.get_json() == {"erro": "Não encontrado"}


def test_metodo_nao_permitido_responde_json(client, admin_token):
    res = client.delete("/api/auth/login", headers=H(admin_token))
    assert res.status_code == 405
    assert "erro" in res.get_json()


def test_pagina_inexistente_continua_html(client):
    res = client.get("/pagina-que-nao-existe")
    assert res.status_code == 404
    assert not res.is_json


def test_excecao_nao_tratada_vira_500_em_json_sem_vazar_detalhe(client, admin_token, monkeypatch):
    import hub

    def explode(*_a, **_k):
        raise RuntimeError("segredo interno")

    # o resumo do hub isola bloco por bloco; quebra-se a rota inteira pela
    # função que identifica quem chama
    monkeypatch.setattr(hub, "get_jwt_identity", explode)
    res = client.get("/api/hub/resumo", headers=H(admin_token))
    assert res.status_code == 500
    corpo = res.get_json()
    assert "erro" in corpo
    assert "segredo interno" not in res.get_data(as_text=True)


# ── o admin não se tranca para fora ───────────────────────────────────────────

def _admin_id(client):
    with client.application.app_context():
        return User.query.filter_by(email="admin@test.com").first().id


def test_admin_nao_desativa_a_propria_conta_pela_edicao(client, admin_token):
    res = client.patch(f"/api/users/{_admin_id(client)}", json={"ativo": False},
                       headers=H(admin_token))
    assert res.status_code == 400
    assert client.get("/api/users", headers=H(admin_token)).status_code == 200


def test_admin_nao_rebaixa_o_proprio_perfil(client, admin_token):
    res = client.patch(f"/api/users/{_admin_id(client)}", json={"role": "leitura"},
                       headers=H(admin_token))
    assert res.status_code == 400
    assert client.get("/api/users", headers=H(admin_token)).status_code == 200


def test_admin_ainda_edita_o_proprio_nome(client, admin_token):
    res = client.patch(f"/api/users/{_admin_id(client)}",
                       json={"nome": "Admin Renomeado", "role": "admin", "ativo": True},
                       headers=H(admin_token))
    assert res.status_code == 200
    assert res.get_json()["usuario"]["nome"] == "Admin Renomeado"


# ── blocklist de tokens não cresce para sempre ────────────────────────────────

def test_tarefa_diaria_descarta_so_os_tokens_revogados_ja_vencidos(app):
    import servidor

    db.session.add(RevokedToken(jti="velho", revoked_at=datetime.now() - timedelta(days=30)))
    db.session.add(RevokedToken(jti="recente", revoked_at=datetime.now() - timedelta(days=2)))
    db.session.commit()

    assert servidor._purgar_tokens_revogados() == 1
    assert [t.jti for t in RevokedToken.query.all()] == ["recente"]


# ── scripts não ficam para trás quando o modelo muda ──────────────────────────

def test_scripts_so_importam_de_models_o_que_existe():
    """`scripts/semear_demo.py` ficou meses quebrado: importava LinhaProduto,
    removido numa refatoração de Equipamentos, e nada rodava o script para
    avisar. Aqui basta o nome importado não existir para a suíte falhar."""
    import ast
    import glob
    import os

    import models

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    faltando = []
    for caminho in glob.glob(os.path.join(raiz, "scripts", "*.py")):
        with open(caminho, encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        for no in ast.walk(arvore):
            if isinstance(no, ast.ImportFrom) and no.module == "models":
                faltando += [f"{os.path.basename(caminho)}: {a.name}"
                             for a in no.names if not hasattr(models, a.name)]
    assert not faltando, f"scripts importam de models nomes que não existem: {faltando}"
