"""Testes do endurecimento para acesso remoto (DocTrack atrás de túnel).

O que está sendo protegido aqui é uma armadilha específica e silenciosa: com o
`cloudflared` rodando no MESMO servidor que o app, toda requisição chega de
127.0.0.1. Nada quebra visivelmente — o sistema segue no ar, o login funciona —
mas os limites "por IP" de ratelimit.py passam a valer para a equipe inteira
somada, e o audit log registra o mesmo IP para todo mundo.

O caso grave é o kill switch: `DOCTRACK_LIMITE_KILLSWITCH` é 3 tentativas por
IP. Fundidos num IP só, três erros de qualquer pessoa trancam a rota de
desbloqueio para todos — e num incidente real quem atacou queima as três de
propósito para impedir o administrador de destravar.
"""
import pytest

from utils import ip_do_cliente

IP_REAL = "201.17.44.90"        # quem de fato acessou
IP_EDGE = "172.71.150.11"       # um edge da Cloudflare
IP_TUNEL = "127.0.0.1"          # o cloudflared, no mesmo servidor que o app


@pytest.fixture
def req(app):
    """Monta uma requisição com os cabeçalhos que o túnel produz."""
    def _req(headers=None, remote_addr=IP_TUNEL):
        return app.test_request_context(
            "/api/auth/login",
            headers=headers or {},
            environ_base={"REMOTE_ADDR": remote_addr},
        )
    return _req


# ── SEM PROXY DECLARADO ───────────────────────────────────────────────────────

def test_sem_trust_proxy_ignora_o_cabecalho(req, monkeypatch):
    """Cabeçalho é forjável por quem chama. Sem proxy declarado, não se lê.

    Este é o comportamento antigo e ele NÃO pode ter mudado: quem roda o
    DocTrack na LAN, direto, continua protegido de um cliente que inventa o
    próprio IP para escapar do rate limit ou sujar o audit log.
    """
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    with req(headers={"CF-Connecting-IP": "1.2.3.4"}, remote_addr=IP_REAL):
        assert ip_do_cliente() == IP_REAL


def test_sem_trust_proxy_tambem_ignora_x_forwarded_for(req, monkeypatch):
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    with req(headers={"X-Forwarded-For": "1.2.3.4"}, remote_addr=IP_REAL):
        assert ip_do_cliente() == IP_REAL


# ── ATRÁS DO TÚNEL ────────────────────────────────────────────────────────────

def test_com_trust_proxy_usa_o_ip_real_do_cloudflare(req, monkeypatch):
    """É a linha que impede o colapso: sem ela, todos viram 127.0.0.1."""
    monkeypatch.setenv("TRUST_PROXY", "1")
    with req(headers={"CF-Connecting-IP": IP_REAL}, remote_addr=IP_TUNEL):
        assert ip_do_cliente() == IP_REAL


def test_cf_connecting_ip_tem_precedencia_sobre_o_edge(req, monkeypatch):
    """`x_for=1` no ProxyFix lê a ÚLTIMA entrada do X-Forwarded-For, que atrás
    da Cloudflare é o edge — não a pessoa. CF-Connecting-IP é o único que
    carrega quem realmente acessou."""
    monkeypatch.setenv("TRUST_PROXY", "1")
    with req(headers={"CF-Connecting-IP": IP_REAL}, remote_addr=IP_EDGE):
        assert ip_do_cliente() == IP_REAL


def test_sem_cabecalho_da_cloudflare_cai_no_comportamento_anterior(req, monkeypatch):
    """Quem roda atrás de IIS/nginx sem Cloudflare não é afetado: o ProxyFix já
    reescreveu o remote_addr e é ele que vale."""
    monkeypatch.setenv("TRUST_PROXY", "1")
    with req(headers={}, remote_addr=IP_REAL):
        assert ip_do_cliente() == IP_REAL


def test_cabecalho_vazio_nao_apaga_o_ip(req, monkeypatch):
    """Um proxy mal configurado que manda o cabeçalho em branco não pode fazer
    o audit log gravar string vazia."""
    monkeypatch.setenv("TRUST_PROXY", "1")
    with req(headers={"CF-Connecting-IP": "   "}, remote_addr=IP_REAL):
        assert ip_do_cliente() == IP_REAL


# ── AS TRÊS FONTES CONCORDAM ──────────────────────────────────────────────────

def test_audit_log_e_ratelimit_leem_o_mesmo_ip(req, monkeypatch):
    """Se divergirem, investigar um bloqueio significa olhar um dado que não
    corresponde ao que causou o bloqueio."""
    import auth
    import killswitch
    import ratelimit

    monkeypatch.setenv("TRUST_PROXY", "1")
    with req(headers={"CF-Connecting-IP": IP_REAL}, remote_addr=IP_TUNEL):
        assert auth.get_client_ip() == IP_REAL
        assert ratelimit._ip() == IP_REAL
        assert killswitch._ip() == IP_REAL


def test_pessoas_diferentes_nao_compartilham_o_contador(req, monkeypatch):
    """O ponto todo do endurecimento: duas pessoas atrás do MESMO túnel
    precisam cair em chaves de rate limit diferentes."""
    import ratelimit

    monkeypatch.setenv("TRUST_PROXY", "1")
    with req(headers={"CF-Connecting-IP": IP_REAL}, remote_addr=IP_TUNEL):
        chave_a = ratelimit.chaves_killswitch("unlock")
    with req(headers={"CF-Connecting-IP": "189.4.7.22"}, remote_addr=IP_TUNEL):
        chave_b = ratelimit.chaves_killswitch("unlock")

    assert chave_a != chave_b, "duas pessoas caindo na mesma chave de rate limit"
