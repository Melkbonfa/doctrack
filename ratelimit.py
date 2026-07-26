"""ratelimit.py — limite de tentativas para as rotas públicas de autenticação.

`/api/auth/login` e `/api/auth/primeiro-acesso` são as duas portas abertas do
sistema e não tinham limite nenhum: dava para varrer senhas e, pior, códigos de
ativação (8 caracteres que valem uma conta) na velocidade da rede. O bcrypt em
12 rounds tornava isso lento, mas lento não é impedido.

Só tentativa FALHA conta. Contar acerto puniria o uso normal — quem entra certo
não está atacando — e a contagem por (rota, identidade, ip) evita que um usuário
bloqueie o login de outro do mesmo escritório.

Estado em memória, de propósito: o app roda em um processo (waitress com
threads), então um dicionário resolve sem trazer Redis para uma rede fabril.
Consequência aceita e explícita: reiniciar o serviço zera os contadores.
"""
import os
import threading
import time

from flask import jsonify, request

# Limites (tentativas falhas / segundos). Ajustáveis por variável de ambiente
# porque o número certo depende do tamanho da equipe.
LIMITE_LOGIN        = int(os.environ.get("DOCTRACK_LIMITE_LOGIN", "5"))
JANELA_LOGIN        = int(os.environ.get("DOCTRACK_JANELA_LOGIN", "300"))
LIMITE_ATIVACAO     = int(os.environ.get("DOCTRACK_LIMITE_ATIVACAO", "5"))
JANELA_ATIVACAO     = int(os.environ.get("DOCTRACK_JANELA_ATIVACAO", "900"))
# Teto por IP: barra a varredura que troca de e-mail a cada tentativa (que
# escaparia do contador por identidade).
LIMITE_IP           = int(os.environ.get("DOCTRACK_LIMITE_IP", "30"))
JANELA_IP           = int(os.environ.get("DOCTRACK_JANELA_IP", "300"))

_tentativas = {}          # chave -> [timestamps das falhas]
_lock = threading.Lock()
_ultima_limpeza = 0.0


def habilitado():
    return os.environ.get("DOCTRACK_RATELIMIT", "1").lower() not in ("0", "false", "no")


def _limpar(agora, janela_maxima):
    """Descarta chaves sem tentativa recente (o dicionário não pode crescer para
    sempre com e-mails inventados por um atacante)."""
    global _ultima_limpeza
    if agora - _ultima_limpeza < 60:
        return
    _ultima_limpeza = agora
    for chave in [k for k, ts in _tentativas.items()
                  if not ts or agora - ts[-1] > janela_maxima]:
        _tentativas.pop(chave, None)


def _contar(chave, janela, agora):
    ts = [t for t in _tentativas.get(chave, []) if agora - t < janela]
    if ts:
        _tentativas[chave] = ts
    else:
        _tentativas.pop(chave, None)
    return ts


def bloqueado(chave, limite, janela):
    """Devolve (bloqueado, segundos_para_liberar)."""
    if not habilitado():
        return False, 0
    agora = time.time()
    with _lock:
        _limpar(agora, max(JANELA_LOGIN, JANELA_ATIVACAO, JANELA_IP))
        ts = _contar(chave, janela, agora)
        if len(ts) < limite:
            return False, 0
        return True, max(1, int(janela - (agora - ts[0])))


def registrar_falha(chave):
    if not habilitado():
        return
    agora = time.time()
    with _lock:
        _tentativas.setdefault(chave, []).append(agora)


def limpar_chave(chave):
    """Tentativa bem-sucedida zera o contador daquela identidade."""
    with _lock:
        _tentativas.pop(chave, None)


def resetar():
    """Zera todo o estado — usado pelas fixtures de teste."""
    global _ultima_limpeza
    with _lock:
        _tentativas.clear()
        _ultima_limpeza = 0.0


def _ip():
    return request.remote_addr or "-"


def chaves_login(email):
    return (f"login:{(email or '').strip().lower()}:{_ip()}", f"ip:{_ip()}")


def chaves_ativacao(email):
    return (f"ativacao:{(email or '').strip().lower()}:{_ip()}", f"ip:{_ip()}")


def checar(chaves, limite, janela):
    """Checa a chave da identidade e o teto por IP. Devolve a resposta 429
    pronta quando bloqueado, ou None quando pode seguir."""
    identidade, por_ip = chaves
    for chave, lim, jan in ((identidade, limite, janela), (por_ip, LIMITE_IP, JANELA_IP)):
        travado, espera = bloqueado(chave, lim, jan)
        if travado:
            resp = jsonify({
                "erro": f"Muitas tentativas. Tente novamente em "
                        f"{max(1, espera // 60)} minuto(s).",
                "retry_after": espera,
            })
            resp.status_code = 429
            resp.headers["Retry-After"] = str(espera)
            return resp
    return None
