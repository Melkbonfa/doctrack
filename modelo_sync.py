"""modelo_sync.py — leva as mudanças de um modelo de entregáveis aos projetos.

Projeto copia o modelo ao nascer; daí em diante as duas listas são
independentes. Este módulo é o caminho controlado de volta: um admin compara o
modelo com os projetos ativos dele (`calcular_previa`), escolhe os projetos e o
destino de cada item que saiu do modelo, informa o motivo e aplica
(`aplicar`). Cada aplicação vira uma MudancaModelo com o antes/depois de tudo
o que mudou.

Comparação de três lados, por entregável e por campo:

    origem  — o que o modelo tinha quando o entregável foi criado ou atualizado
              por ele pela última vez (Entregavel.modelo_origem)
    modelo  — o que o item do modelo tem agora
    projeto — o que o entregável tem agora

    modelo == origem             → o modelo não mexeu neste campo: nada a fazer
    projeto == origem            → só o modelo mudou: atualiza
    projeto == modelo            → os dois chegaram ao mesmo valor: nada visível
    senão                        → o projeto ajustou: MANTÉM e registra "mantido"

Nome e categoria não são editáveis no projeto, então sempre seguem o modelo.
A ordem do projeto não é propagada (quem arrasta no projeto manda nela); item
novo entra no fim da categoria.

Item do modelo que o projeto NÃO tem só é proposto (criar ou vincular) se for
novo para o projeto — fora de `Projeto.modelo_conhecidos`, a lista dos itens
que o projeto já conhecia ao nascer ou na última aplicação. Sem isso, o item
tirado de propósito da lista ao criar o projeto, ou que nunca existiu num
projeto antigo, voltaria a cada prévia.

Sem Flask aqui: as rotas ficam em entregaveis.py e só traduzem
ErroPropagacao em resposta HTTP. Nada commita — quem chama decide.
"""
import hashlib
import json
import unicodedata
from datetime import datetime

from sqlalchemy.orm.attributes import flag_modified

from models import (db, Projeto, Entregavel, EntregavelHistorico, ModeloEntregavel,
                    MudancaModelo, MudancaModeloItem, STATUS_PROJETO_ABERTO)

# Campos que vêm do modelo, na ordem em que a prévia os mostra.
CAMPOS = ("tipo", "categoria", "peso", "responsavel")
# Ação registrada quando o campo é atualizado.
ACAO_DO_CAMPO = {"tipo": "renomeado", "categoria": "categoria",
                 "peso": "peso", "responsavel": "responsavel"}
# Tudo que pode aparecer em MudancaModeloItem.acao.
ACOES = ("criado", "vinculado", "renomeado", "categoria", "peso", "responsavel",
         "mantido", "apagado", "na", "desvinculado")
# Destino de um entregável cujo item saiu do modelo.
DECISOES = ("apagar", "manter", "na")


class ErroPropagacao(Exception):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status


# ── valores comparáveis ──────────────────────────────────────────────────────

def _peso(v):
    try:
        return round(float(v if v is not None else 1.0), 4)
    except (TypeError, ValueError):
        return 1.0


def valores_do_modelo(m):
    return {"tipo": (m.tipo or "").strip(), "categoria": m.categoria or "",
            "peso": _peso(m.peso), "responsavel": (m.responsavel_padrao or "").strip()}


def valores_do_entregavel(e):
    return {"tipo": (e.tipo or "").strip(), "categoria": e.categoria or "",
            "peso": _peso(e.peso), "responsavel": (e.responsaveis or "").strip()}


def _origem(e):
    try:
        o = json.loads(e.modelo_origem or "{}")
    except (TypeError, ValueError):
        o = {}
    if "peso" in o:
        o["peso"] = _peso(o["peso"])
    return o


def vincular(e, m):
    """Liga o entregável ao item e fotografa os valores atuais do modelo."""
    e.modelo_chave = m.chave
    e.modelo_origem = json.dumps(valores_do_modelo(m), ensure_ascii=False)


def _desvincular(e):
    e.modelo_chave = ""
    e.modelo_origem = ""


def _texto(v):
    if isinstance(v, float):
        return f"{v:g}"
    return "" if v is None else str(v)


def tem_andamento(e):
    """Já houve trabalho registrado: apagar mudaria o passado do projeto (a
    curva-S lê o histórico, que vai junto com o entregável)."""
    return (e.status or "pendente") != "pendente" or bool(e.historico)


def chave_nome(texto):
    """Nome para casar entregável com item de modelo: sem acento, maiúscula,
    hífen/sublinhado nem espaço sobrando. A categoria fica de fora de propósito:
    o modelo pode ter mudado o item de categoria depois que o projeto nasceu
    (os modelos do PDR levaram vários itens de Documentação para Gestão)."""
    s = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").replace("_", " ").split())


def conhecidos(p, itens):
    """Chaves dos itens do modelo que o projeto já conhecia. Sem a lista (projeto
    criado por fora da tela, antes do backfill), vale o modelo de agora: na
    dúvida, não propõe criar nada."""
    if p.modelo_conhecidos is None:
        return {m.chave for m in itens}
    try:
        return set(json.loads(p.modelo_conhecidos) or [])
    except (TypeError, ValueError):
        return {m.chave for m in itens}


def marcar_conhecidos(p, itens):
    """O projeto passa a conhecer todos os itens de `itens` (o modelo de agora)."""
    p.modelo_conhecidos = json.dumps(sorted(m.chave for m in itens if m.chave))


# ── prévia ───────────────────────────────────────────────────────────────────

def _itens_do_modelo(tipo):
    return (ModeloEntregavel.query.filter_by(tipo_projeto=tipo)
            .order_by(ModeloEntregavel.ordem, ModeloEntregavel.id).all())


def projetos_do_modelo(tipo):
    """Projetos que podem receber a mudança: ativos (não arquivados) e abertos."""
    return (Projeto.query.filter(Projeto.tipo == tipo, Projeto.ativo == True,   # noqa: E712
                                 Projeto.status.in_(STATUS_PROJETO_ABERTO))
            .order_by(Projeto.nome, Projeto.id).all())


def _mudancas_do_projeto(p, itens):
    """Lista do que a aplicação faria em `p`. Cada item é um dict serializável."""
    por_chave = {m.chave: m for m in itens}
    ents = sorted(p.entregaveis, key=lambda e: (e.ordem or 0, e.id))
    ligados = {}
    for e in ents:
        if e.modelo_chave and e.modelo_chave not in ligados:
            ligados[e.modelo_chave] = e
    mudancas = []

    for e in ents:
        if not e.modelo_chave or ligados.get(e.modelo_chave) is not e:
            continue
        m = por_chave.get(e.modelo_chave)
        if m is None:
            mudancas.append({"acao": "remover", "entregavel_id": e.id,
                             "entregavel": e.tipo, "categoria": e.categoria or "",
                             "status": e.status or "pendente",
                             "andamento": tem_andamento(e)})
            continue
        origem, novo, atual = _origem(e), valores_do_modelo(m), valores_do_entregavel(e)
        for campo in CAMPOS:
            base = origem.get(campo, novo[campo])    # origem incompleta = sem mudança
            if novo[campo] == base or novo[campo] == atual[campo]:
                continue
            seguir = campo in ("tipo", "categoria") or atual[campo] == base
            mudancas.append({"acao": ACAO_DO_CAMPO[campo] if seguir else "mantido",
                             "entregavel_id": e.id, "entregavel": e.tipo,
                             "categoria": e.categoria or "", "campo": campo,
                             "antes": _texto(atual[campo]), "depois": _texto(novo[campo])})

    # Itens do modelo NOVOS para o projeto (fora dos conhecidos) que ele não
    # tem: vincula um avulso de mesmo nome (alguém já tinha criado à mão) ou
    # cria. O que o projeto já conhecia e não tem ficou de fora de propósito.
    known = conhecidos(p, itens)
    avulsos = {}
    for e in ents:
        if not e.modelo_chave:
            avulsos.setdefault(chave_nome(e.tipo), e)
    for m in itens:
        if m.chave in ligados or m.chave in known:
            continue
        v = valores_do_modelo(m)
        e = avulsos.pop(chave_nome(v["tipo"]), None)
        if e is not None:
            mudancas.append({"acao": "vincular", "entregavel_id": e.id, "entregavel": e.tipo,
                             "categoria": e.categoria or "", "modelo_chave": m.chave})
        else:
            mudancas.append({"acao": "criar", "entregavel_id": None, "entregavel": v["tipo"],
                             "categoria": v["categoria"], "modelo_chave": m.chave,
                             "peso": v["peso"], "responsavel": v["responsavel"]})
    return mudancas


def _versao(mudancas):
    """Impressão digital da prévia de um projeto. A aplicação recalcula e
    compara: se o modelo ou o projeto mudou depois que o admin revisou, a
    aplicação recusa em vez de fazer algo que ninguém viu."""
    bruto = json.dumps(mudancas, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:16]


def _resumo(mudancas):
    r = {}
    for c in mudancas:
        r[c["acao"]] = r.get(c["acao"], 0) + 1
    return r


def calcular_previa(tipo):
    itens = _itens_do_modelo(tipo)
    projetos = []
    for p in projetos_do_modelo(tipo):
        mudancas = _mudancas_do_projeto(p, itens)
        projetos.append({
            "id": p.id, "nome": p.nome, "status": p.status,
            "mudancas": mudancas, "resumo": _resumo(mudancas),
            "alteracoes": sum(1 for c in mudancas if c["acao"] != "mantido"),
            "decisoes_pendentes": sum(1 for c in mudancas
                                      if c["acao"] == "remover" and c["andamento"]),
            "versao": _versao(mudancas),
        })
    return {"tipo": tipo, "itens_modelo": len(itens), "projetos": projetos,
            "com_alteracao": sum(1 for p in projetos if p["alteracoes"])}


# ── aplicação ────────────────────────────────────────────────────────────────

def _preservar_atualizado_em(e):
    """Propagar não é mexer no entregável: sem isto o onupdate carimbaria
    `atualizado_em` e o alerta de projeto parado deixaria de ver a inércia.
    Mesmo cuidado de editar_categoria e reordenar_entregaveis."""
    flag_modified(e, "atualizado_em")


def aplicar(tipo, selecao, decisoes, motivo, email):
    """Aplica a prévia aos projetos escolhidos. Valida tudo antes de escrever.

    selecao  — {projeto_id: versao} vindo da prévia que o admin revisou
    decisoes — {entregavel_id: "apagar"|"manter"|"na"} para itens que saíram do
               modelo; obrigatória quando o item tem andamento, senão o padrão
               é apagar
    Devolve a MudancaModelo (já na sessão, sem commit).
    """
    motivo = (motivo or "").strip()
    if len(motivo) < 5:
        raise ErroPropagacao("informe o motivo da mudança (mínimo 5 caracteres)")
    if len(motivo) > 500:
        raise ErroPropagacao("motivo muito longo (máximo 500 caracteres)")
    if not isinstance(selecao, dict) or not selecao:
        raise ErroPropagacao("escolha ao menos um projeto")
    try:
        selecao = {int(k): str(v) for k, v in selecao.items()}
        decisoes = {int(k): str(v) for k, v in (decisoes or {}).items()}
    except (TypeError, ValueError):
        raise ErroPropagacao("projetos/decisões em formato inválido")
    if any(d not in DECISOES for d in decisoes.values()):
        raise ErroPropagacao(f"decisão inválida. Use: {', '.join(DECISOES)}")

    itens = _itens_do_modelo(tipo)
    por_chave = {m.chave: m for m in itens}
    elegiveis = {p.id: p for p in projetos_do_modelo(tipo)}

    plano = []
    for pid, versao in selecao.items():
        p = elegiveis.get(pid)
        if p is None:
            raise ErroPropagacao(f"o projeto {pid} não está mais elegível (arquivado, "
                                 "concluído ou trocou de modelo). Gere a prévia de novo.", 409)
        mudancas = _mudancas_do_projeto(p, itens)
        if _versao(mudancas) != versao:
            raise ErroPropagacao(f"'{p.nome}' mudou desde a prévia (alguém editou o "
                                 "modelo ou o projeto). Gere a prévia de novo.", 409)
        for c in mudancas:
            if c["acao"] == "remover" and c["andamento"] and c["entregavel_id"] not in decisoes:
                raise ErroPropagacao(f"decida o destino de '{c['entregavel']}' em "
                                     f"'{p.nome}': ele tem andamento registrado")
        plano.append((p, mudancas))
    if not any(mudancas for _, mudancas in plano):
        raise ErroPropagacao("os projetos escolhidos já estão em dia com o modelo")

    mud = MudancaModelo(tipo_projeto=tipo, motivo=motivo, feito_por=email or "",
                        feito_em=datetime.now())
    db.session.add(mud)
    n_projetos = n_alteracoes = 0

    for p, mudancas in plano:
        ents = {e.id: e for e in p.entregaveis}
        prox_ordem = max((e.ordem or 0 for e in p.entregaveis), default=-1) + 1
        mexeu = False

        def registra(acao, nome, eid=None, campo="", antes="", depois=""):
            mud.itens.append(MudancaModeloItem(
                projeto_id=p.id, projeto_nome=p.nome, entregavel_id=eid,
                entregavel=(nome or "")[:120], acao=acao, campo=campo,
                antes=_texto(antes)[:300], depois=_texto(depois)[:300]))

        for c in mudancas:
            acao, e = c["acao"], ents.get(c.get("entregavel_id"))
            if acao == "mantido":
                registra("mantido", c["entregavel"], c["entregavel_id"], c["campo"],
                         c["antes"], c["depois"])
                continue
            mexeu = True
            n_alteracoes += 1
            if acao in ("renomeado", "categoria", "peso", "responsavel"):
                registra(acao, c["entregavel"], e.id, c["campo"], c["antes"], c["depois"])
                if acao == "renomeado":
                    e.tipo = c["depois"]
                elif acao == "categoria":
                    e.categoria = c["depois"]
                elif acao == "peso":
                    e.peso = float(c["depois"])
                else:
                    e.responsaveis = c["depois"]
                _preservar_atualizado_em(e)
            elif acao == "vincular":
                vincular(e, por_chave[c["modelo_chave"]])
                _preservar_atualizado_em(e)
                registra("vinculado", e.tipo, e.id)
            elif acao == "criar":
                m = por_chave[c["modelo_chave"]]
                novo = Entregavel(projeto_id=p.id, tipo=m.tipo.strip(), categoria=m.categoria,
                                  status="pendente", peso=_peso(m.peso),
                                  responsaveis=(m.responsavel_padrao or "").strip(),
                                  ordem=prox_ordem, atualizado_por=email or "")
                prox_ordem += 1
                vincular(novo, m)
                p.entregaveis.append(novo)
                db.session.flush()
                registra("criado", novo.tipo, novo.id, depois=novo.categoria)
            elif acao == "remover":
                decisao = decisoes.get(c["entregavel_id"], "apagar")
                if decisao == "apagar":
                    registra("apagado", e.tipo, e.id, antes=e.status or "pendente")
                    p.entregaveis.remove(e)   # delete-orphan leva o histórico junto
                elif decisao == "na":
                    registra("na", e.tipo, e.id, campo="status",
                             antes=e.status or "pendente", depois="na")
                    if e.status != "na":
                        db.session.add(EntregavelHistorico(
                            entregavel_id=e.id, status_antigo=e.status or "",
                            status_novo="na", percentual=None,
                            em=datetime.now(), por=email or ""))
                    e.status, e.percentual, e.data_conclusao = "na", None, ""
                    _desvincular(e)
                    _preservar_atualizado_em(e)
                else:
                    registra("desvinculado", e.tipo, e.id)
                    _desvincular(e)
                    _preservar_atualizado_em(e)

        # A origem de quem continua ligado passa a ser o modelo de agora: a
        # próxima prévia só mostra o que mudar daqui para frente. Os "mantidos"
        # também — o admin já viu e decidiu que o ajuste do projeto fica.
        for e in p.entregaveis:
            m = por_chave.get(e.modelo_chave) if e.modelo_chave else None
            if m is not None and _origem(e) != valores_do_modelo(m):
                vincular(e, m)
                if e.id is not None:
                    _preservar_atualizado_em(e)
        # O que o modelo tem agora passa a ser conhecido: o que o admin viu e
        # não levou (projeto desmarcado não entra aqui) não volta na próxima.
        marcar_conhecidos(p, itens)

        if mexeu:
            n_projetos += 1
            db.session.flush()
            p.registrar_snapshot()

    mud.n_projetos, mud.n_alteracoes = n_projetos, n_alteracoes
    db.session.flush()
    return mud


# ── vínculo dos dados anteriores ─────────────────────────────────────────────

def vincular_legado():
    """Prepara os dados anteriores ao vínculo. Roda na subida; idempotente.

    1. Item de modelo sem `chave` ganha uma.
    2. Entregável com `modelo_origem` NULL (anterior ao vínculo) vira avulso
       provisório — o passo 3 decide se ele casa com o modelo.
    3. Projeto com `modelo_conhecidos` NULL (anterior a isto) passa uma vez:
       cada avulso dele casa com um item ainda livre do modelo do projeto pelo
       NOME (chave_nome: sem categoria, acento, maiúscula). Casou: liga e
       fotografa os valores ATUAIS do modelo como origem — categoria, nome ou
       peso que o projeto tinha diferente contam como do projeto e ficam. Por
       fim o projeto passa a conhecer o modelo inteiro de agora, então a prévia
       só vai propor o que entrar no modelo daqui para frente.

    Depois desse passo o projeto nunca mais é reavaliado: um avulso criado à mão
    depois, com o mesmo nome de um item novo do modelo, não é ligado em
    silêncio — a prévia oferece "vincular" e o admin vê.
    Devolve (itens_de_modelo_com_chave_nova, entregaveis_ligados, projetos_avaliados).
    """
    import secrets
    sem_chave = ModeloEntregavel.query.filter(
        (ModeloEntregavel.chave == None) | (ModeloEntregavel.chave == "")).all()   # noqa: E711
    for m in sem_chave:
        m.chave = secrets.token_hex(16)
    if sem_chave:
        db.session.flush()

    for e in Entregavel.query.filter(Entregavel.modelo_origem == None).all():   # noqa: E711
        _desvincular(e)
        _preservar_atualizado_em(e)

    modelos = {}
    ligados = 0
    projetos = Projeto.query.filter(Projeto.modelo_conhecidos == None).all()   # noqa: E711
    for p in projetos:
        tipo = p.tipo or ""
        if tipo not in modelos:
            modelos[tipo] = _itens_do_modelo(tipo) if tipo else []
        itens = modelos[tipo]
        ja_ligados = {e.modelo_chave for e in p.entregaveis if e.modelo_chave}
        livres = {}
        for m in itens:
            if m.chave not in ja_ligados:
                livres.setdefault(chave_nome(m.tipo), m)
        for e in sorted(p.entregaveis, key=lambda x: (x.ordem or 0, x.id)):
            if e.modelo_chave:
                continue
            m = livres.pop(chave_nome(e.tipo), None)
            if m is not None:
                vincular(e, m)
                _preservar_atualizado_em(e)
                ligados += 1
        marcar_conhecidos(p, itens)
    db.session.flush()
    return len(sem_chave), ligados, len(projetos)
