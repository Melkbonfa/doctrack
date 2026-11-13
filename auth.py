"""
auth.py — Autenticação JWT e CRUD de usuários com RBAC
Rotas:
  POST /api/auth/login
  POST /api/auth/refresh
  POST /api/auth/trocar-senha
  GET  /api/auth/me
  GET  /api/users
  POST /api/users
  GET  /api/users/<id>
  PATCH /api/users/<id>
  DELETE /api/users/<id>
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token, decode_token,
    jwt_required, get_jwt_identity, get_jwt
)
from datetime import datetime, timedelta
from functools import wraps
import os

from models import db, User, AuditLog, RevokedToken
from areas import dump_areas, parse_areas, AREA_SLUGS
from utils import ip_do_cliente
import ratelimit

auth_bp = Blueprint("auth", __name__)

# Mínimo de caracteres para uma senha nova. Eram 6 — curto o bastante para
# caber num ataque de dicionário e abaixo de qualquer recomendação atual.
# Só afeta senhas NOVAS; as existentes continuam valendo até a próxima troca.
SENHA_MIN = int(os.environ.get("DOCTRACK_SENHA_MIN", "8"))
ERRO_SENHA_CURTA = f"Senha deve ter pelo menos {SENHA_MIN} caracteres"

# Composição e validade da senha — o guia de validação da ANVISA recomenda senha
# com letras, números e caracteres especiais, renovada periodicamente, e que a
# senha vencida impeça o acesso até ser trocada (§21.2). As duas regras só
# alcançam senha NOVA ou login futuro: ninguém é derrubado por elas.
#   DOCTRACK_SENHA_COMPOSICAO=0     desliga a regra de composição
#   DOCTRACK_SENHA_VALIDADE_DIAS=0  senha não vence
SENHA_COMPOSICAO = (os.environ.get("DOCTRACK_SENHA_COMPOSICAO", "1").strip().lower()
                    not in ("0", "false", "nao", ""))
SENHA_VALIDADE_DIAS = int(os.environ.get("DOCTRACK_SENHA_VALIDADE_DIAS", "180") or 0)
ERRO_SENHA_COMPOSICAO = ("A senha deve ter pelo menos uma letra, um número e um "
                         "caractere especial (ex.: ! @ # - _)")


def erro_de_senha(senha):
    """Por que `senha` não serve como senha nova; None se serve."""
    if len(senha) < SENHA_MIN:
        return ERRO_SENHA_CURTA
    if SENHA_COMPOSICAO and not (
            any(c.isalpha() for c in senha) and any(c.isdigit() for c in senha)
            and any(not c.isalnum() and not c.isspace() for c in senha)):
        return ERRO_SENHA_COMPOSICAO
    return None


def senha_vencida(user):
    """A senha passou da validade. Conta sem data não vence — a subida do
    servidor preenche a data das contas anteriores à regra."""
    if SENHA_VALIDADE_DIAS <= 0 or not user.senha_definida_em:
        return False
    return datetime.now() > user.senha_definida_em + timedelta(days=SENHA_VALIDADE_DIAS)

# A senha só nasce no primeiro acesso, digitada pelo próprio usuário. Se o admin
# pudesse defini-la (no cadastro ou na edição), passaria a conhecê-la, e o que
# fosse feito com aquela conta deixaria de ser atribuível só ao dono dela.
# Criar a conta e resetar a senha geram código de ativação; não há outro caminho.
ERRO_SENHA_PELO_ADMIN = ("O administrador não define senha. A conta recebe um código "
                         "de ativação e o usuário cria a própria senha no primeiro "
                         "acesso; para trocar, use Resetar senha.")


# ── HELPERS ──────────────────────────────────────────────────────────────────

def log_action(user_email, acao, entidade="", campo="", antigo="", novo="",
               ip="", documento_id=None):
    """Grava uma entrada no audit log com rastreabilidade completa."""
    user = User.query.filter_by(email=user_email).first()
    entry = AuditLog(
        usuario_id=user.id if user else None,
        usuario_email=user_email,
        documento_id=documento_id,
        acao=acao,
        entidade=entidade,
        campo=campo,
        valor_antigo=str(antigo) if antigo is not None else "",
        valor_novo=str(novo) if novo is not None else "",
        ip=ip,
    )
    db.session.add(entry)
    db.session.commit()


def _exige(roles):
    return "exige " + ", ".join(roles)


def _txt(data, campo):
    """Campo de texto do corpo, sem espaço nas pontas. `null`, número ou lista
    viram "" em vez de AttributeError — login e primeiro acesso são rotas
    públicas, e um `{"email": null}` não pode ser 500."""
    valor = data.get(campo)
    return valor.strip() if isinstance(valor, str) else ""


def require_role(*roles):
    """Decorator: exige que o usuário tenha um dos roles listados."""
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            identity = get_jwt_identity()          # email do usuário
            claims   = get_jwt()                    # claims extras (role)
            # O perfil da claim é o do banco: token com perfil divergente nem
            # chega aqui (ver "REVOGAÇÃO IMEDIATA").
            role     = claims.get("role", "")
            if role not in roles:
                return negar_acesso(f"perfil {role or '—'} ({_exige(roles)})")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_area(slug, *roles):
    """Exige acesso a uma Área de P&D e, opcionalmente, um dos perfis informados.

    Acesso: admin (sempre) ou usuário com `slug` em `areas`.
    Se `roles` for informado, também exige que o perfil esteja na lista
    (usado nas rotas de escrita / módulos como Projetos). Sem `roles`, basta o acesso.
    """
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            email = get_jwt_identity()
            user  = User.query.filter_by(email=email, ativo=True).first()
            if not user or not user.tem_area(slug):
                return negar_acesso(f"sem a área {slug}", "Sem acesso a esta área")
            if roles and user.role not in roles:
                return negar_acesso(f"perfil {user.role} ({_exige(roles)})")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_pdr_access(*roles):
    """Compat: acesso à área PDR (P&D de reagentes)."""
    return require_area("pdr", *roles)


# ── REVOGAÇÃO IMEDIATA ────────────────────────────────────────────────────────
#
# O perfil viaja nas claims do JWT, e require_role decide por ele sem ir ao
# banco. Sem a checagem abaixo, uma conta desativada (ou rebaixada) seguia
# usando o access token até ele vencer — até 1 hora — e o refresh só recusava
# na renovação seguinte.
#
# `sessao_revogada` roda em TODA requisição autenticada: servidor.py a chama do
# token_in_blocklist_loader, que o flask-jwt-extended consulta antes de deixar
# o token passar. Recusa:
#   * qualquer token (access ou refresh) de conta que não existe mais ou está
#     inativa — o e-mail trocado cai aqui também, porque a identidade do token
#     é o e-mail;
#   * o access token cujo perfil diverge do atual. O front recebe 401, renova
#     pelo refresh e ganha um token com o perfil do banco, sem novo login. O
#     refresh não é comparado: /api/auth/refresh já lê o perfil do banco.
#
# Sem cache, de propósito: é uma consulta pela chave única de users por
# requisição, do mesmo tamanho da consulta à blocklist que já existia, e um
# cache reabriria a janela que esta checagem fecha (ou exigiria invalidação
# entre processos).

def sessao_revogada(jwt_payload):
    user = (User.query.with_entities(User.ativo, User.role)
            .filter_by(email=jwt_payload.get("sub")).first())
    if user is None or not user.ativo:
        return True
    return jwt_payload.get("type") == "access" and jwt_payload.get("role") != user.role


# Quem mais precisa saber que o acesso de uma conta mudou. O tempo real
# (servidor.py) registra aqui o corte das conexões Socket.IO abertas, que não
# passam pelo JWT a cada evento: sem isso, a aba aberta de uma conta desativada
# continuaria recebendo os eventos da sala do perfil antigo.
_cortes_de_sessao = []


def ao_cortar_sessao(fn):
    """Registra `fn(user_id)`, chamada depois do commit que desativa, exclui
    ou muda o perfil da conta."""
    _cortes_de_sessao.append(fn)
    return fn


def _cortar_sessoes(user_id):
    for fn in _cortes_de_sessao:
        try:
            fn(user_id)
        except Exception as e:
            print(f"[WARN] Corte de sessão do usuário {user_id} falhou — {e}")


def get_client_ip():
    """IP de quem chamou, para o audit log.

    Delega para `utils.ip_do_cliente()` — a mesma função que o rate limit usa.
    As duas coisas PRECISAM concordar: se o audit log registra um IP e o
    contador de tentativas conta outro, a investigação de um bloqueio olha para
    um dado que não corresponde ao que causou o bloqueio.
    """
    return ip_do_cliente()


# ── TENTATIVAS DE ACESSO RECUSADAS ────────────────────────────────────────────
#
# A validação de sistema computadorizado pede que o sistema registre as
# tentativas de acesso de quem não está autorizado. O rate limit vê todas, mas
# o contador dele mora em memória e some no reinício; a trilha que sobrevive é
# audit_logs.
#
# Entra toda tentativa em que um segredo foi conferido e não bateu (senha,
# código de ativação, token e senha do kill switch) e o bloqueio pelo limite.
# Todas já contam no rate limit, então o volume que um atacante gera aqui é o
# mesmo teto que o limite lhe dá — gravar o que o limite não conta abriria a
# auditoria para ser inundada.
#
# Também entra o 403 de perfil ou área (ACESSO_NEGADO, logo abaixo): quem já
# está dentro tentando o que o perfil não alcança.
#
# Fica de fora, de propósito:
#   * o segredo digitado — nem a senha, nem o código, nem trecho deles;
#   * o 401 de JWT vencido, que acontece a cada expiração e o front renova
#     sozinho.


# ── ACESSO NEGADO (403 de perfil ou área) ─────────────────────────────────────
#
# Quem bate num 403 de perfil ou de área já está autenticado e identificado, e
# o próprio front provoca esse 403 no uso normal: a seção que o perfil leitura
# não pode ver some da tela ao receber 403. Não há limite de tentativas que
# segure esse volume, então gravar toda resposta faria cada tela aberta virar
# linha de auditoria, e o registro de um abuso de verdade ficaria enterrado no
# ruído do uso legítimo.
#
# Por isso a deduplicação: uma linha por (usuário, rota) a cada
# JANELA_ACESSO_NEGADO. "Rota" é o método mais a regra do Flask
# ("PATCH /api/users/<int:user_id>"), não o caminho com o id: a recusa por
# perfil vale para qualquer id daquela rota, e deduplicar pelo caminho deixaria
# uma varredura de ids gravar uma linha por requisição. O que se perde é a
# contagem dentro da janela; o que fica é quem tentou o quê, de onde e quando.
#
# A memória de "já registrado" é a própria auditoria, como no bloqueio do
# limite: sobrevive ao reinício e vale para todas as threads do waitress.

JANELA_ACESSO_NEGADO = timedelta(minutes=10)


def _rota_atual():
    regra = request.url_rule.rule if request.url_rule is not None else request.path
    return f"{request.method} {regra}"[:200]


def registrar_acesso_negado(motivo, email=None):
    """Grava ACESSO_NEGADO (deduplicado). Nunca muda a resposta: se a gravação
    falhar, a recusa continua a mesma.

    Só pode ser chamada antes de qualquer escrita da requisição: `log_action`
    faz commit da sessão, e o que estivesse pendente iria junto.
    """
    try:
        email = (email or get_jwt_identity() or "")[:120]
        rota = _rota_atual()
        ja = AuditLog.query.filter(
            AuditLog.acao == "ACESSO_NEGADO",
            AuditLog.usuario_email == email,
            AuditLog.entidade == rota,
            AuditLog.timestamp >= datetime.now() - JANELA_ACESSO_NEGADO,
        ).first()
        if ja is not None:
            return
        log_action(email, "ACESSO_NEGADO", entidade=rota, campo="motivo",
                   novo=motivo, ip=get_client_ip())
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Auditoria: ACESSO_NEGADO não gravado — {e}")


def negar_acesso(motivo, mensagem="Acesso negado para este perfil"):
    """O 403 de perfil/área com o registro na trilha. `motivo` vai só para a
    auditoria; ao cliente vai `mensagem`, a mesma de antes."""
    registrar_acesso_negado(motivo)
    return jsonify({"erro": mensagem}), 403


def _auditar_tentativa(email, acao, motivo="", entidade=""):
    """Grava uma tentativa recusada. Nunca muda a resposta: se a gravação
    falhar, a tentativa continua recusada com a mesma mensagem de sempre."""
    try:
        # usuario_email é varchar(120) e o e-mail vem do corpo da requisição,
        # com o tamanho que quem ataca quiser. Estourar a coluna no PostgreSQL
        # viraria 500 — que diz algo diferente de "e-mail ou senha incorretos".
        log_action((email or "")[:120], acao, entidade=entidade,
                   campo="motivo" if motivo else "", novo=motivo,
                   ip=get_client_ip())
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Auditoria: {acao} não gravado — {e}")


def auditar_bloqueio(acao, email, chaves, limite, janela,
                     rotulo="limite por e-mail", entidade=""):
    """Registra a tentativa barrada pelo limite (429): uma linha por bloqueio,
    não uma por requisição.

    Enquanto o bloqueio dura, cada nova tentativa leva 429 sem que o segredo
    seja nem conferido. Gravar todas faria do próprio limite o jeito mais
    barato de inundar audit_logs — a tabela que mais cresce, sem retenção por
    padrão. As falhas que levaram ao bloqueio já estão gravadas uma a uma;
    esta linha marca que ele aconteceu e que alguém insistiu.

    `chaves` e `limite`/`janela` são os mesmos passados a `ratelimit.checar`:
    servem para saber qual dos dois contadores barrou — o da identidade
    (`rotulo`) ou o teto por IP — porque é por contador que se deduplica. Por
    IP, o e-mail fica fora da comparação: senão uma varredura que troca de
    e-mail a cada tentativa geraria uma linha por requisição de novo.

    A memória de "este bloqueio já foi registrado" é a própria auditoria: no
    máximo uma linha por contador a cada janela do limite.
    """
    email = (email or "")[:120]
    ip = get_client_ip()
    try:
        por_identidade = ratelimit.bloqueado(chaves[0], limite, janela)[0]
        motivo = rotulo if por_identidade else "limite por IP"
        desde = datetime.now() - timedelta(
            seconds=janela if por_identidade else ratelimit.JANELA_IP)
        ja = AuditLog.query.filter(AuditLog.acao == acao, AuditLog.ip == ip,
                                   AuditLog.valor_novo == motivo,
                                   AuditLog.timestamp >= desde)
        if por_identidade:
            ja = ja.filter(AuditLog.usuario_email == email)
        if ja.first() is not None:
            return
    except Exception:
        # Sem como deduplicar, registra: na dúvida, uma linha a mais.
        db.session.rollback()
        motivo = rotulo
    _auditar_tentativa(email, acao, motivo, entidade=entidade)


# ── LOGIN ─────────────────────────────────────────────────────────────────────

@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data  = request.get_json(silent=True) or {}
    email = _txt(data, "email").lower()
    senha = data.get("senha")

    if not email or not senha or not isinstance(senha, str):
        return jsonify({"erro": "Email e senha são obrigatórios"}), 400

    # Limite de tentativas antes de tocar o banco: o bcrypt é a parte caríssima
    # da requisição, então checar depois seria pagar o custo do ataque.
    chaves = ratelimit.chaves_login(email)
    travado = ratelimit.checar(chaves, ratelimit.LIMITE_LOGIN, ratelimit.JANELA_LOGIN)
    if travado is not None:
        auditar_bloqueio("LOGIN_BLOQUEADO", email, chaves,
                         ratelimit.LIMITE_LOGIN, ratelimit.JANELA_LOGIN)
        return travado

    user = User.query.filter_by(email=email, ativo=True).first()

    # Conta pendente de primeiro acesso/reset: orienta a definir a senha.
    # Fora da auditoria: nenhuma senha foi conferida (qualquer uma cai aqui) e
    # esta recusa não conta no limite. A tentativa que vale para quem ataca uma
    # conta pendente — adivinhar o código — é a do primeiro acesso, e essa grava.
    if user and user.precisa_definir_senha:
        return jsonify({
            "erro": "Esta conta ainda não tem senha. Use o código de ativação para definir sua senha no primeiro acesso.",
            "precisa_definir_senha": True,
        }), 403

    if not user or not user.check_senha(senha):
        for chave in chaves:
            ratelimit.registrar_falha(chave)
        # O motivo fica só na auditoria; ao cliente a mensagem é uma só, para
        # não dizer se o e-mail tem conta.
        _auditar_tentativa(email, "LOGIN_FALHA",
                           "senha incorreta" if user else "e-mail sem conta ativa")
        return jsonify({"erro": "Email ou senha incorretos"}), 401

    ratelimit.limpar_chave(chaves[0])

    # Senha certa, mas vencida: não entra. A troca é em /api/auth/trocar-senha,
    # que confere a senha atual de novo.
    if senha_vencida(user):
        _auditar_tentativa(email, "LOGIN_SENHA_VENCIDA",
                           f"senha com mais de {SENHA_VALIDADE_DIAS} dias")
        return jsonify({
            "erro": "Sua senha venceu. Defina uma nova para entrar.",
            "senha_vencida": True,
        }), 403

    # Atualiza último login
    user.ultimo_login = datetime.now()
    db.session.commit()

    # Cria tokens com role como claim extra
    additional = {"role": user.role, "nome": user.nome}
    access_token  = create_access_token(identity=user.email, additional_claims=additional)
    refresh_token = create_refresh_token(identity=user.email, additional_claims=additional)

    log_action(user.email, "LOGIN", ip=get_client_ip())

    return jsonify({
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "usuario": user.to_dict(),
    }), 200


@auth_bp.route("/api/auth/logout", methods=["POST"])
@jwt_required()
def logout():
    """Encerra a sessão: revoga o access token da chamada e, se o front mandar,
    o refresh token junto — sem isso a sessão "encerrada" podia ser reaberta
    com o refresh por até 7 dias. A saída vai para a trilha, com o motivo
    quando não foi a pessoa que saiu (`inatividade`)."""
    identidade = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    jtis = {get_jwt().get("jti")}
    rt = data.get("refresh_token")
    if isinstance(rt, str) and rt:
        try:
            claims = decode_token(rt)
            if claims.get("sub") == identidade and claims.get("type") == "refresh":
                jtis.add(claims.get("jti"))
        except Exception:
            pass          # refresh vencido, revogado ou inválido: nada a revogar
    try:
        for jti in filter(None, jtis):
            if not RevokedToken.query.filter_by(jti=jti).first():
                db.session.add(RevokedToken(jti=jti))
        db.session.commit()
    except Exception:
        db.session.rollback()
    motivo = "inatividade" if _txt(data, "motivo") == "inatividade" else ""
    try:
        log_action(identidade, "LOGOUT", campo="motivo" if motivo else "",
                   novo=motivo, ip=get_client_ip())
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Auditoria: LOGOUT não gravado — {e}")
    return jsonify({"mensagem": "Logout realizado"}), 200


@auth_bp.route("/api/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    claims   = get_jwt()
    user = User.query.filter_by(email=identity, ativo=True).first()
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404
    additional   = {"role": user.role, "nome": user.nome}
    access_token = create_access_token(identity=identity, additional_claims=additional)
    return jsonify({"access_token": access_token}), 200


@auth_bp.route("/api/auth/me", methods=["GET"])
@jwt_required()
def me():
    identity = get_jwt_identity()
    user = User.query.filter_by(email=identity).first()
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404
    return jsonify(user.to_dict()), 200


# ── TROCAR A PRÓPRIA SENHA ────────────────────────────────────────────────────

@auth_bp.route("/api/auth/trocar-senha", methods=["POST"])
def trocar_senha():
    """Rota pública: e-mail + senha atual + senha nova.

    Pública porque é também a saída de quem está com a senha vencida e, por
    isso, não consegue um token. Quem prova a identidade é a senha atual, sob o
    mesmo limite de tentativas do login — os dois contam no mesmo contador,
    senão esta rota seria um segundo lugar para testar senha.
    """
    data  = request.get_json(silent=True) or {}
    email = _txt(data, "email").lower()
    atual = data.get("senha_atual")
    nova  = data.get("senha_nova")

    if (not email or not atual or not nova
            or not isinstance(atual, str) or not isinstance(nova, str)):
        return jsonify({"erro": "E-mail, senha atual e senha nova são obrigatórios"}), 400
    erro = erro_de_senha(nova)
    if erro:
        return jsonify({"erro": erro}), 400
    if nova == atual:
        return jsonify({"erro": "A senha nova deve ser diferente da atual"}), 400

    chaves = ratelimit.chaves_login(email)
    travado = ratelimit.checar(chaves, ratelimit.LIMITE_LOGIN, ratelimit.JANELA_LOGIN)
    if travado is not None:
        auditar_bloqueio("LOGIN_BLOQUEADO", email, chaves,
                         ratelimit.LIMITE_LOGIN, ratelimit.JANELA_LOGIN)
        return travado

    user = User.query.filter_by(email=email, ativo=True).first()
    if not user or not user.check_senha(atual):
        for chave in chaves:
            ratelimit.registrar_falha(chave)
        _auditar_tentativa(email, "LOGIN_FALHA",
                           "senha incorreta na troca de senha" if user
                           else "e-mail sem conta ativa")
        return jsonify({"erro": "Email ou senha incorretos"}), 401

    ratelimit.limpar_chave(chaves[0])
    user.set_senha(nova)
    user.ultimo_login = datetime.now()
    db.session.commit()

    log_action(user.email, "PASSWORD_CHANGE", entidade=user.email, ip=get_client_ip())

    additional = {"role": user.role, "nome": user.nome}
    return jsonify({
        "mensagem": "Senha alterada com sucesso",
        "access_token":  create_access_token(identity=user.email, additional_claims=additional),
        "refresh_token": create_refresh_token(identity=user.email, additional_claims=additional),
        "usuario": user.to_dict(),
    }), 200


# ── PRIMEIRO ACESSO (definir a própria senha) ──────────────────────────────────

@auth_bp.route("/api/auth/primeiro-acesso", methods=["POST"])
def primeiro_acesso():
    """Rota pública: o usuário troca o código de ativação pela própria senha.

    Usada tanto no convite (admin cria a conta) quanto após um reset de senha.
    """
    data   = request.get_json(silent=True) or {}
    email  = _txt(data, "email").lower()
    codigo = _txt(data, "codigo")
    senha  = data.get("senha")

    if not email or not codigo or not senha or not isinstance(senha, str):
        return jsonify({"erro": "E-mail, código e nova senha são obrigatórios"}), 400
    erro = erro_de_senha(senha)
    if erro:
        return jsonify({"erro": erro}), 400

    # Um código de ativação é 8 caracteres que valem uma conta inteira — é o
    # alvo mais atraente do sistema e o que mais precisava de limite.
    chaves = ratelimit.chaves_ativacao(email)
    travado = ratelimit.checar(chaves, ratelimit.LIMITE_ATIVACAO, ratelimit.JANELA_ATIVACAO)
    if travado is not None:
        auditar_bloqueio("ATIVACAO_BLOQUEADA", email, chaves,
                         ratelimit.LIMITE_ATIVACAO, ratelimit.JANELA_ATIVACAO)
        return travado

    user = User.query.filter_by(email=email, ativo=True).first()

    # Mensagens distintas para orientar o usuário (ferramenta interna).
    # As três recusas contam no limite e vão para a auditoria. Antes só o código
    # errado contava: e-mail sem pendência e código vencido respondiam na hora e
    # sem limite, então uma varredura de e-mails nesta rota não deixava rastro —
    # e gravá-la sem contar abriria a auditoria a inundação.
    falha = None
    if not user or not user.precisa_definir_senha or not user.ativacao_codigo_hash:
        falha = ("sem primeiro acesso pendente",
                 "Não há primeiro acesso pendente para este e-mail. Confira o e-mail digitado.")
    elif user.ativacao_expira and datetime.now() > user.ativacao_expira:
        falha = ("código expirado",
                 "Código de ativação expirado. Peça um novo ao administrador.")
    elif not user.check_codigo(codigo):
        falha = ("código incorreto", "Código de ativação incorreto.")
    if falha:
        motivo, mensagem = falha
        for chave in chaves:
            ratelimit.registrar_falha(chave)
        _auditar_tentativa(email, "ATIVACAO_FALHA", motivo)
        return jsonify({"erro": mensagem}), 400

    ratelimit.limpar_chave(chaves[0])
    user.set_senha(senha)          # também limpa o código e o estado pendente
    user.ultimo_login = datetime.now()
    db.session.commit()

    log_action(user.email, "FIRST_ACCESS", entidade=user.email, ip=get_client_ip())

    # Já autentica o usuário para entrar direto
    additional = {"role": user.role, "nome": user.nome}
    access_token  = create_access_token(identity=user.email, additional_claims=additional)
    refresh_token = create_refresh_token(identity=user.email, additional_claims=additional)

    return jsonify({
        "mensagem": "Senha definida com sucesso",
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "usuario": user.to_dict(),
    }), 200


# ── LISTAR USUÁRIOS ────────────────────────────────────────────────────────────

@auth_bp.route("/api/users", methods=["GET"])
@require_role("admin", "gestor")
def list_users():
    caller_email = get_jwt_identity()
    user = User.query.filter_by(email=caller_email).first()
    
    if user and user.role == "admin":
        users = User.query.order_by(User.nome).all()
    else:
        users = User.query.filter_by(ativo=True).order_by(User.nome).all()
        
    return jsonify([u.to_dict() for u in users]), 200


# ── CRIAR USUÁRIO ──────────────────────────────────────────────────────────────

@auth_bp.route("/api/users", methods=["POST"])
@require_role("admin")
def create_user():
    caller_email = get_jwt_identity()
    data  = request.get_json(silent=True) or {}

    nome  = _txt(data, "nome")
    email = _txt(data, "email").lower()
    role  = _txt(data, "role") or "tecnico"

    # Validações
    if "senha" in data:
        # Recusa em vez de ignorar: quem ainda manda senha (tela antiga em
        # cache, script) precisa saber que ela não foi aplicada.
        return jsonify({"erro": ERRO_SENHA_PELO_ADMIN}), 400
    if not nome or not email:
        return jsonify({"erro": "Nome e email são obrigatórios"}), 400
    if role not in ("admin", "gestor", "tecnico", "leitura"):
        return jsonify({"erro": "Role inválido. Use: admin, gestor, tecnico, leitura"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"erro": "Este e-mail já está cadastrado"}), 409

    user = User(nome=nome, email=email, role=role)

    # Áreas de acesso (lista de slugs). Admin acessa todas por padrão da lógica;
    # para os demais, vale exatamente o que foi selecionado no cadastro.
    user.areas = dump_areas(data.get("areas") or [])
    # Compat: mantém a flag legada coerente com a área PDR selecionada.
    user.pode_pdr = "pdr" in parse_areas(user.areas)

    # Convite: o usuário define a própria senha no primeiro acesso.
    codigo = user.gerar_codigo_ativacao()

    db.session.add(user)
    db.session.commit()

    log_action(caller_email, "CREATE", entidade=email,
               campo="role", novo=role, ip=get_client_ip())

    return jsonify({
        "mensagem": "Usuário criado com sucesso",
        "usuario": user.to_dict(),
        # Mostrado uma única vez para o admin repassar ao usuário
        "codigo_ativacao": codigo,
        "validade_dias":   User.ATIVACAO_VALIDADE_DIAS,
    }), 201


# ── BUSCAR USUÁRIO POR ID ──────────────────────────────────────────────────────

@auth_bp.route("/api/users/<int:user_id>", methods=["GET"])
@jwt_required()
def get_user(user_id):
    caller_email = get_jwt_identity()
    claims = get_jwt()
    caller_role = claims.get("role", "")

    user = User.query.get(user_id)
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404

    # Técnico e leitura só podem ver o próprio perfil
    if caller_role in ("tecnico", "leitura") and user.email != caller_email:
        return negar_acesso(f"perfil {caller_role} (só o próprio cadastro)", "Acesso negado")

    return jsonify(user.to_dict()), 200


# ── EDITAR USUÁRIO ─────────────────────────────────────────────────────────────

@auth_bp.route("/api/users/<int:user_id>", methods=["PATCH"])
@require_role("admin")
def update_user(user_id):
    caller_email = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    user = User.query.get(user_id)
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404

    # Antes de qualquer campo: a edição é recusada inteira, nada fica aplicado
    # pela metade. Trocar a senha é o reset (/reset-senha), que gera código.
    if "senha" in data:
        return jsonify({"erro": ERRO_SENHA_PELO_ADMIN}), 400

    # Mesma guarda do DELETE: o admin não se desativa nem se rebaixa. Sem ela o
    # PATCH era o caminho para ficar sem administrador nenhum — o único perfil
    # que cria conta, reseta senha e devolve o próprio acesso.
    if user.email == caller_email:
        if "ativo" in data and not bool(data["ativo"]):
            return jsonify({"erro": "Você não pode desativar a própria conta"}), 400
        if "role" in data and _txt(data, "role") != user.role:
            return jsonify({"erro": "Você não pode mudar o próprio perfil"}), 400

    changes = []

    if "nome" in data:
        novo_nome = _txt(data, "nome")
        if novo_nome and novo_nome != user.nome:
            changes.append(("nome", user.nome, novo_nome))
            user.nome = novo_nome

    if "email" in data:
        novo_email = _txt(data, "email").lower()
        if novo_email and novo_email != user.email:
            existente = User.query.filter_by(email=novo_email).first()
            if existente and existente.id != user_id:
                return jsonify({"erro": "Este e-mail já está em uso"}), 409
            changes.append(("email", user.email, novo_email))
            user.email = novo_email

    if "role" in data:
        novo_role = _txt(data, "role")
        if novo_role not in ("admin", "gestor", "tecnico", "leitura"):
            return jsonify({"erro": "Role inválido"}), 400
        if novo_role != user.role:
            changes.append(("role", user.role, novo_role))
            user.role = novo_role

    if "ativo" in data:
        novo_ativo = bool(data["ativo"])
        if novo_ativo != user.ativo:
            changes.append(("ativo", user.ativo, novo_ativo))
            user.ativo = novo_ativo

    if "areas" in data:
        novas = dump_areas(data["areas"] or [])
        if novas != (user.areas or ""):
            changes.append(("areas", user.areas or "", novas))
            user.areas = novas
            user.pode_pdr = "pdr" in parse_areas(novas)   # compat com a flag legada
    elif "pode_pdr" in data:
        # Compat: edição antiga que ainda manda só a flag do PDR.
        novo_pdr = bool(data["pode_pdr"])
        if novo_pdr != bool(user.pode_pdr):
            changes.append(("pode_pdr", user.pode_pdr, novo_pdr))
            user.pode_pdr = novo_pdr
            atuais = parse_areas(user.areas)
            if novo_pdr and "pdr" not in atuais:
                atuais.append("pdr")
            elif not novo_pdr and "pdr" in atuais:
                atuais.remove("pdr")
            user.areas = dump_areas(atuais)

    db.session.commit()

    # Os tokens já valem pelo estado novo (ver sessao_revogada); aqui caem as
    # conexões de tempo real, que entraram nas salas do perfil antigo.
    if any(campo in ("ativo", "role") for campo, _a, _n in changes):
        _cortar_sessoes(user.id)

    # Audit log — uma entrada por campo alterado
    for campo, antigo, novo in changes:
        log_action(caller_email, "UPDATE", entidade=user.email,
                   campo=campo, antigo=antigo, novo=novo, ip=get_client_ip())

    return jsonify({"mensagem": "Usuário atualizado", "usuario": user.to_dict()}), 200


# ── DESATIVAR (soft) OU EXCLUIR (permanente) USUÁRIO ───────────────────────────

@auth_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@require_role("admin")
def delete_user(user_id):
    """DELETE soft (ativo=False) por padrão.

    Com ?permanente=true remove o cadastro de vez — só de conta que nunca
    deixou linha na trilha de auditoria; as outras respondem 409.
    """
    caller_email = get_jwt_identity()
    permanente = str(request.args.get("permanente", "")).lower() in ("1", "true", "yes")

    user = User.query.get(user_id)
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404

    # Protege: não deixa o admin se auto-excluir/desativar
    if user.email == caller_email:
        return jsonify({"erro": "Você não pode excluir ou desativar a própria conta"}), 400

    if not permanente:
        user.ativo = False
        db.session.commit()
        _cortar_sessoes(user.id)
        log_action(caller_email, "DELETE", entidade=user.email, ip=get_client_ip())
        return jsonify({"mensagem": f"Usuário {user.email} desativado com sucesso"}), 200

    # Exclusão permanente só de conta que nunca agiu no sistema (cadastro feito
    # por engano). Quem já tem linha na trilha fica: apagar o cadastro liberaria
    # o e-mail para outra pessoa, e as duas se confundiriam na auditoria — o
    # guia de validação pede exclusão lógica e ID nunca reutilizado (§16.3).
    usado = AuditLog.query.filter(
        (AuditLog.usuario_id == user.id) | (AuditLog.usuario_email == user.email)
    ).first()
    if usado:
        return jsonify({"erro": "Esta conta já tem registros na trilha de auditoria "
                                "e não pode ser excluída em definitivo. Desative-a."}), 409

    email, uid = user.email, user.id

    db.session.delete(user)
    db.session.commit()
    _cortar_sessoes(uid)

    log_action(caller_email, "DELETE", entidade=email,
               campo="permanente", novo="true", ip=get_client_ip())

    return jsonify({"mensagem": f"Usuário {email} excluído permanentemente"}), 200


# ── RESETAR SENHA (gera novo código de primeiro acesso) ────────────────────────

@auth_bp.route("/api/users/<int:user_id>/reset-senha", methods=["POST"])
@require_role("admin")
def reset_senha(user_id):
    """Devolve a conta ao estado de primeiro acesso: limpa a senha e gera um
    novo código de ativação que o usuário troca pela nova senha."""
    caller_email = get_jwt_identity()

    user = User.query.get(user_id)
    if not user:
        return jsonify({"erro": "Usuário não encontrado"}), 404

    codigo = user.gerar_codigo_ativacao()
    db.session.commit()

    log_action(caller_email, "PASSWORD_RESET", entidade=user.email, ip=get_client_ip())

    return jsonify({
        "mensagem": f"Senha de {user.email} resetada. Repasse o código de ativação.",
        "codigo_ativacao": codigo,
        "validade_dias":   User.ATIVACAO_VALIDADE_DIAS,
        "usuario":         user.to_dict(),
    }), 200
