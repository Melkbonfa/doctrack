"""killswitch.py — trava de emergência do DocTrack.

Um gatilho externo derruba o sistema inteiro; só uma senha-mestra o traz de
volta. O caso de uso é o incidente: credencial vazada, máquina comprometida,
suspeita de acesso indevido — situações em que desligar é mais barato que
investigar com o sistema no ar, e em que quem precisa desligar pode não estar
na frente do servidor.

Como funciona
-------------
    POST /api/kill-switch/lock     (header X-Kill-Token)  → trava tudo
    POST /api/kill-switch/unlock   (senha no corpo)       → destrava
    GET  /api/kill-switch/status                          → público, só o estado
    GET  /travado                                         → a tela de bloqueio

Travado, TODA requisição responde 423 (Locked): API, páginas, WebSocket. Não há
exceção por perfil — nem admin entra, porque a hipótese que motiva a trava é
justamente a de que uma credencial legítima está nas mãos erradas. As únicas
rotas que seguem respondendo são as quatro acima e `/api/version` (health check
do Render; se ela travasse, a plataforma reiniciaria o serviço em laço).

Destravar corta as sessões: `tokens_validos_apos` recebe o instante do
destravamento e todo JWT emitido antes disso é recusado pela blocklist. Todo
mundo loga de novo — inclusive quem quer que estivesse dentro no momento do
incidente.

Os dois segredos
----------------
Ficam em variável de ambiente, como hash bcrypt, nunca no banco:

    DOCTRACK_KILL_TOKEN_HASH   token que dispara a trava
    DOCTRACK_UNLOCK_HASH       senha-mestra que destrava

Fora do banco de propósito: se o motivo da trava for o próprio banco
comprometido, um segredo guardado nele não vale nada. Gere os dois com
`python scripts/kill_switch.py hash`.

Sem os DOIS configurados o gatilho recusa travar (503). É deliberado: travar
sem senha de destravamento cadastrada é destruir o sistema, não protegê-lo.
"""
import os
import threading
import time
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request

from utils import ip_do_cliente
from models import db, bcrypt, SistemaLock
import ratelimit

killswitch_bp = Blueprint("killswitch", __name__)

ENV_TOKEN = "DOCTRACK_KILL_TOKEN_HASH"
ENV_SENHA = "DOCTRACK_UNLOCK_HASH"

# Janela em que o estado lido do banco é reaproveitado. O guardião roda em toda
# requisição, inclusive nas de arquivo estático — sem cache seria um SELECT por
# imagem. 3s é o atraso máximo entre disparar o gatilho e o sistema parar, e
# entre destravar e ele voltar; curto o bastante para uma emergência.
CACHE_TTL = float(os.environ.get("DOCTRACK_LOCK_TTL", "3"))

# Endpoints que continuam respondendo com o sistema travado.
LIBERADOS = frozenset({
    "killswitch.travar_rota",
    "killswitch.destravar_rota",
    "killswitch.status",
    "killswitch.pagina",
    "static",
    "api_version",      # health check do Render (ver healthCheckPath em render.yaml)
})

_LIVRE = {"travado": False, "travado_em": None, "motivo": "", "corte": None}

_cache = None          # (instante_monotonic, estado)
_lock = threading.Lock()
_socketio = None


# ── CONFIGURAÇÃO ──────────────────────────────────────────────────────────────

def _hash_token():
    return (os.environ.get(ENV_TOKEN) or "").strip()


def _hash_senha():
    return (os.environ.get(ENV_SENHA) or "").strip()


def configurado():
    """O kill switch só existe de verdade com os dois segredos no ambiente."""
    return bool(_hash_token() and _hash_senha())


def _confere(hash_guardado, valor):
    """bcrypt.check_password_hash com hash malformado levanta; aqui isso é só
    'não confere' — um hash torto no .env não pode virar erro 500 na única rota
    que destrava o sistema."""
    if not hash_guardado or not valor:
        return False
    try:
        return bcrypt.check_password_hash(hash_guardado, valor)
    except Exception:
        return False


# ── ESTADO ────────────────────────────────────────────────────────────────────

def _linha(criar=False):
    linha = db.session.get(SistemaLock, 1)
    if linha is None and criar:
        linha = SistemaLock(id=1, travado=False)
        db.session.add(linha)
        db.session.commit()
    return linha


def _ler():
    linha = _linha()
    if linha is None or not linha.travado:
        corte = linha.tokens_validos_apos if linha else None
        return dict(_LIVRE, corte=corte)
    return {
        "travado":    True,
        "travado_em": linha.travado_em,
        "motivo":     linha.motivo or "",
        "corte":      linha.tokens_validos_apos,
    }


def invalidar_cache():
    global _cache
    with _lock:
        _cache = None


def estado():
    """Estado atual da trava, com cache curto. Nunca levanta."""
    global _cache
    agora = time.monotonic()
    with _lock:
        atual = _cache
    if atual and agora - atual[0] < CACHE_TTL:
        return atual[1]

    try:
        lido = _ler()
    except Exception:
        # Banco fora do ar não pode DESTRAVAR o sistema — senão derrubar o banco
        # viraria a forma mais fácil de burlar o gatilho. Mantém o último estado
        # conhecido; sem nenhum, segue liberado (o app já está quebrado de
        # qualquer jeito, e travar aqui esconderia a falha real).
        try:
            db.session.rollback()
        except Exception:
            pass
        return atual[1] if atual else _LIVRE

    with _lock:
        _cache = (agora, lido)
    return lido


def travado():
    return estado()["travado"]


def _corte_de_sessao(travado_em):
    """Instante a partir do qual um token ainda vale, dado quando a trava caiu.

    Ancorado na TRAVA e não no destravamento, e arredondado para CIMA no
    segundo. O motivo é o `iat` do JWT ter resolução de um segundo: ancorar no
    destravamento faria o corte cair no mesmo segundo do primeiro login pós-
    liberação, que seria recusado junto com os tokens antigos — o sistema
    voltaria sem deixar ninguém entrar. Ancorado na trava, o corte já ficou no
    passado quando alguém destrava, e o arredondamento para cima garante que
    nem o token emitido no mesmo segundo da trava sobreviva.

    Nada é emitido entre a trava e o destravamento (o login responde 423), então
    esta janela não deixa passar nenhum token.
    """
    if travado_em.microsecond:
        return travado_em.replace(microsecond=0) + timedelta(seconds=1)
    return travado_em


def travar(motivo="", origem=""):
    linha = _linha(criar=True)
    linha.travado    = True
    linha.travado_em = datetime.now()
    linha.motivo     = (motivo or "").strip()[:300]
    linha.origem     = (origem or "")[:60]
    db.session.commit()
    invalidar_cache()
    _avisar("sistema_travado", {"motivo": linha.motivo})
    return linha


def destravar():
    linha = _linha(criar=True)
    agora = datetime.now()
    linha.travado             = False
    linha.destravado_em       = agora
    linha.tokens_validos_apos = _corte_de_sessao(linha.travado_em or agora)
    db.session.commit()
    invalidar_cache()
    _avisar("sistema_destravado", {})
    return linha


# ── REVOGAÇÃO DE SESSÕES ──────────────────────────────────────────────────────

def token_cortado(jwt_payload):
    """True quando o token é anterior à última trava já liberada.

    Ligado à blocklist do flask-jwt-extended (ver servidor.check_revoked), então
    vale para access e refresh token, em toda rota, sem precisar tocar em nenhuma.
    """
    corte = estado().get("corte")
    if not corte:
        return False
    iat = jwt_payload.get("iat")
    if not iat:
        # Token sem iat não é comparável com o corte; recusa, porque o corte
        # existe justamente para não confiar no que foi emitido antes dele.
        return True
    try:
        # iat é epoch UTC; fromtimestamp devolve local naive — a mesma base de
        # datetime.now() usada em todo o resto do sistema.
        return datetime.fromtimestamp(iat) < corte
    except Exception:
        return True


# ── GUARDIÃO (roda em toda requisição) ────────────────────────────────────────

def _resposta_travada(info):
    payload = {
        "erro": "Sistema travado por medida de segurança. "
                "É necessária a senha de desbloqueio.",
        "travado": True,
        "motivo": info.get("motivo") or "",
        "desbloqueio": "/travado",
    }
    caminho = request.path or ""
    if caminho.startswith("/api/") or caminho.startswith("/socket.io"):
        return jsonify(payload), 423
    # Página: devolve a tela de bloqueio na própria URL pedida (sem redirect, o
    # endereço fica intacto e um F5 depois do desbloqueio volta para onde o
    # usuário estava).
    return render_template("travado.html", info=info), 423


def guardiao():
    """`before_request` do app. Devolve resposta para barrar, ou None para seguir."""
    if request.method == "OPTIONS":
        return None                       # preflight do CORS, senão o unlock não sai
    if request.endpoint in LIBERADOS:
        return None
    info = estado()
    if not info["travado"]:
        return None
    return _resposta_travada(info)


# ── REALTIME ──────────────────────────────────────────────────────────────────

def init_realtime(socketio):
    """Recebe o socketio do servidor para avisar as abas abertas na hora."""
    global _socketio
    _socketio = socketio


def _avisar(evento, dados):
    if _socketio is None:
        return
    try:
        _socketio.emit(evento, dados)
    except Exception:
        pass                              # avisar é cortesia; travar não pode falhar por isso


# ── ROTAS ─────────────────────────────────────────────────────────────────────

def _ip():
    """Mesma fonte do audit log e do rate limit (ver utils.ip_do_cliente).

    Aqui o valor vai para a coluna `origem` da trava e para o audit log: é o
    registro de quem disparou e de quem destravou. Num incidente é a primeira
    coisa que alguém vai olhar, e 127.0.0.1 não responde a pergunta nenhuma.
    """
    return ip_do_cliente()


def _auditar(acao, campo="", novo=""):
    """Grava no audit log sem depender de usuário logado (não há um: o gatilho é
    externo). Falha aqui não pode impedir a trava."""
    try:
        from auth import log_action
        log_action("kill-switch", acao, entidade="sistema",
                   campo=campo, novo=novo, ip=_ip())
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _barrado(acao, chaves, resposta):
    """Tentativa barrada pelo limite: audita (uma vez por bloqueio, ver
    auth.auditar_bloqueio) e devolve o 429 intacto."""
    try:
        from auth import auditar_bloqueio
        auditar_bloqueio("KILL_SWITCH_BLOQUEADO", "kill-switch", chaves,
                         ratelimit.LIMITE_KILLSWITCH, ratelimit.JANELA_KILLSWITCH,
                         rotulo=f"limite do {acao}", entidade="sistema")
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    return resposta


@killswitch_bp.route("/api/kill-switch/status", methods=["GET"])
def status():
    """Público de propósito: a tela de bloqueio precisa consultá-la travado."""
    info = estado()
    return jsonify({
        "travado":     info["travado"],
        "desde":       info["travado_em"].isoformat() if info["travado_em"] else None,
        "motivo":      info["motivo"],
        "configurado": configurado(),
    }), 200


@killswitch_bp.route("/api/kill-switch/lock", methods=["POST"])
def travar_rota():
    chaves = ratelimit.chaves_killswitch("lock")
    barrado = ratelimit.checar(chaves, ratelimit.LIMITE_KILLSWITCH,
                               ratelimit.JANELA_KILLSWITCH)
    if barrado is not None:
        return _barrado("lock", chaves, barrado)

    if not configurado():
        return jsonify({
            "erro": f"Kill switch não configurado: defina {ENV_TOKEN} e "
                    f"{ENV_SENHA} no ambiente (python scripts/kill_switch.py hash).",
        }), 503

    dados = request.get_json(silent=True) or {}
    token = request.headers.get("X-Kill-Token") or dados.get("token") or ""
    if not _confere(_hash_token(), token):
        for chave in chaves:
            ratelimit.registrar_falha(chave)
        # Nunca o token digitado — só o fato (ver auth, TENTATIVAS RECUSADAS).
        _auditar("KILL_SWITCH_LOCK_FALHA", campo="motivo", novo="token inválido")
        return jsonify({"erro": "Token inválido"}), 401

    ratelimit.limpar_chave(chaves[0])
    linha = travar(motivo=dados.get("motivo", ""), origem=_ip())
    _auditar("KILL_SWITCH_LOCK", campo="motivo", novo=linha.motivo)
    return jsonify({
        "mensagem": "Sistema travado. Só a senha de desbloqueio libera.",
        "travado":  True,
        "desde":    linha.travado_em.isoformat(),
        "motivo":   linha.motivo,
    }), 200


@killswitch_bp.route("/api/kill-switch/unlock", methods=["POST"])
def destravar_rota():
    chaves = ratelimit.chaves_killswitch("unlock")
    barrado = ratelimit.checar(chaves, ratelimit.LIMITE_KILLSWITCH,
                               ratelimit.JANELA_KILLSWITCH)
    if barrado is not None:
        return _barrado("unlock", chaves, barrado)

    dados = request.get_json(silent=True) or {}
    senha = dados.get("senha") or ""
    if not _confere(_hash_senha(), senha):
        for chave in chaves:
            ratelimit.registrar_falha(chave)
        _auditar("KILL_SWITCH_UNLOCK_FALHA", campo="motivo",
                 novo="senha de desbloqueio incorreta")
        return jsonify({"erro": "Senha de desbloqueio incorreta"}), 401

    ratelimit.limpar_chave(chaves[0])

    # Com o sistema já liberado não há nada a destravar, e destravar mesmo assim
    # tem um efeito colateral grave: `_corte_de_sessao` cairia sobre `agora`
    # (nunca houve `travado_em`) e o corte derrubaria TODA sessão viva do sistema
    # — um apagão geral disparado por uma rota chamada sem motivo. A leitura vem
    # da linha, não de `estado()`: o cache de 3s pode estar velho, e aqui errar
    # significa recusar o destravamento de um sistema que está travado de fato.
    linha = _linha()
    if linha is None or not linha.travado:
        return jsonify({
            "mensagem": "O sistema já estava liberado. Nada foi alterado.",
            "travado":  False,
        }), 200

    destravar()
    _auditar("KILL_SWITCH_UNLOCK")
    return jsonify({
        "mensagem": "Sistema liberado. Todas as sessões anteriores foram encerradas.",
        "travado":  False,
    }), 200


@killswitch_bp.route("/travado", methods=["GET"])
def pagina():
    info = estado()
    return render_template("travado.html", info=info), (423 if info["travado"] else 200)
