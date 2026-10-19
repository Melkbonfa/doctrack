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

from flask import jsonify

from utils import ip_do_cliente

# Limites (tentativas falhas / segundos). Ajustáveis por variável de ambiente
# porque o número certo depende do tamanho da equipe.
LIMITE_LOGIN        = int(os.environ.get("DOCTRACK_LIMITE_LOGIN", "5"))
JANELA_LOGIN        = int(os.environ.get("DOCTRACK_JANELA_LOGIN", "300"))
LIMITE_ATIVACAO     = int(os.environ.get("DOCTRACK_LIMITE_ATIVACAO", "5"))
JANELA_ATIVACAO     = int(os.environ.get("DOCTRACK_JANELA_ATIVACAO", "900"))
# Kill switch: mais apertado que o login. São dois segredos únicos e sem dono —
# não há usuário legítimo que erre a senha de desbloqueio cinco vezes seguidas —
# e a rota de unlock é a única porta aberta com o sistema travado.
LIMITE_KILLSWITCH   = int(os.environ.get("DOCTRACK_LIMITE_KILLSWITCH", "3"))
JANELA_KILLSWITCH   = int(os.environ.get("DOCTRACK_JANELA_KILLSWITCH", "900"))
# Teto por IP: barra a varredura que troca de e-mail a cada tentativa (que
# escaparia do contador por identidade).
LIMITE_IP           = int(os.environ.get("DOCTRACK_LIMITE_IP", "30"))
JANELA_IP           = int(os.environ.get("DOCTRACK_JANELA_IP", "300"))

_tentativas = {}          # chave -> [timestamps das falhas]
_lock = threading.Lock()
_ultima_limpeza = 0.0
# Maior janela já consultada. O limpador não pode descartar uma chave que alguma
# política ainda conta, e enumerar as janelas à mão aqui já custou caro: a do
# kill switch ficou de fora do max() e, configurada acima do teto, tinha o
# contador zerado antes da hora — mais tentativas contra a única porta que
# continua aberta com o sistema travado. Aprender a janela de quem pergunta faz
# a próxima política nascer coberta.
_janela_vista = 0.0


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
    global _janela_vista
    agora = time.time()
    with _lock:
        # JANELA_IP entra sempre: o teto por IP é consultado em toda checagem e
        # sua chave precisa sobreviver mesmo quando a política da vez é curta.
        _janela_vista = max(_janela_vista, janela, JANELA_IP)
        _limpar(agora, _janela_vista)
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
    global _ultima_limpeza, _janela_vista
    with _lock:
        _tentativas.clear()
        _ultima_limpeza = 0.0
        _janela_vista = 0.0


def _ip():
    """Chave de IP dos contadores. NÃO é `request.remote_addr` direto.

    Ver `utils.ip_do_cliente()`: atrás do túnel do Cloudflare o remote_addr é
    127.0.0.1 (o cloudflared roda no mesmo servidor) ou um IP de edge, e os dois
    fundiriam a equipe inteira numa chave só — transformando todo limite "por
    IP" deste módulo num limite global. O caso grave é o do kill switch: três
    tentativas erradas de qualquer um trancariam o desbloqueio para todos.
    """
    return ip_do_cliente() or "-"


def chaves_login(email):
    return (f"login:{(email or '').strip().lower()}:{_ip()}", f"ip:{_ip()}")


def chaves_ativacao(email):
    return (f"ativacao:{(email or '').strip().lower()}:{_ip()}", f"ip:{_ip()}")


def chaves_killswitch(acao):
    """`acao` é "lock" ou "unlock" — contadores separados para que a varredura
    do token do gatilho não consuma as tentativas de quem precisa destravar."""
    return (f"killswitch:{acao}:{_ip()}", f"ip:{_ip()}")


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
