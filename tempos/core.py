"""
tempos/core.py — Motor do módulo Tempos.

Fonte única do número, no molde de `custos/core.py` e `equipamentos_core.py`: o
servidor calcula, o front só exibe. Nenhuma regra de duração, conflito ou corte é
reimplementada em JavaScript.

Sem importar Flask. Toca o `db` porque validar conflito e resolver o projeto do
alvo são, por natureza, consultas — mas nada aqui conhece `request`, `jsonify` ou
sessão HTTP, e é isso que deixa as mesmas funções servirem à rota e à tarefa
diária do agendador.

## Duas notas de tempo que valem a explicação

**O servidor é o relógio.** As rotas de cronômetro carimbam `datetime.now()` e
ignoram qualquer `inicio` vindo do corpo: um relógio de navegador errado não pode
corromper o dado. O cliente só afirma tempo no lançamento manual e na edição — os
dois únicos caminhos que falam sobre o passado — e ali tudo passa por
`parse_dt` + `validar_intervalo`.

**Naive local, como todo o resto da base.** `models.py` inteiro usa
`datetime.now()` sem fuso; tornar só esta tabela aware faria cada comparação
contra `MissaoCartao.criado_em` precisar de conversão. A consequência é que o
processo precisa rodar no fuso de quem aponta — em contêiner isso significa `TZ`
definido, senão o servidor roda em UTC e um cronômetro das 22h cai no dia
seguinte. Ver a variável TZ no render.yaml.
"""
from datetime import datetime, timedelta

from models import db, Entregavel, MissaoCartao, Projeto, Equipamento

from .models import (
    Apontamento, REF_TIPOS_TEMPO, LIMITE_CRONOMETRO_H, JANELA_RETOMADA_H,
    LIMITE_APONTAMENTO_H, RETROATIVO_DIAS, FOLGA_RELOGIO_S, chave_titulo,
)


# ── PARSE E VALIDAÇÃO ─────────────────────────────────────────────────────────

def parse_dt(valor):
    """ISO -> datetime naive, ou None quando não dá para confiar.

    Aceita 'YYYY-MM-DDTHH:MM' e '...:SS' (com ou sem espaço no lugar do T) e mais
    nada. Sem parse por locale e sem formato "esperto": um campo de data que
    adivinha é um campo que um dia adivinha errado, e aqui o erro vira hora
    trabalhada.
    """
    if not valor:
        return None
    txt = str(valor).strip().replace(" ", "T")
    if txt.endswith("Z"):                 # o front nunca manda, mas um curl manda
        txt = txt[:-1]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def validar_intervalo(inicio, fim, agora=None):
    """Devolve a mensagem de erro, ou None quando o intervalo é aceitável."""
    agora = agora or datetime.now()
    if not inicio:
        return "Informe o início (formato AAAA-MM-DDTHH:MM)"
    if fim is None:
        return None                        # linha aberta: nada a comparar ainda
    if fim <= inicio:
        return "O fim precisa ser depois do início"
    # Folga de 2 min absorve o desvio de relógio de um lançamento feito "agora".
    if fim > agora + timedelta(seconds=FOLGA_RELOGIO_S):
        return "Não dá para apontar tempo no futuro"
    if (fim - inicio) > timedelta(hours=LIMITE_APONTAMENTO_H):
        return (f"Apontamento de mais de {LIMITE_APONTAMENTO_H}h — "
                f"confira os horários (ou divida em lançamentos)")
    if inicio < agora - timedelta(days=RETROATIVO_DIAS):
        return f"Só dá para lançar até {RETROATIVO_DIAS} dias para trás"
    return None


def validar_ref(ref_tipo, ref_id, titulo):
    """Valida o vínculo na gravação — o preço de não ter FK rígida.

    Mesmo contrato do que missoes.py faz com ref_tipo/ref_id do cartão: o vínculo
    solto compra a liberdade de apontar em quatro domínios diferentes, e paga com
    esta função. Sem ela o módulo aceitaria ref_id de entidade inexistente e a
    folha exibiria linhas sem rótulo nenhum.
    """
    if ref_tipo not in REF_TIPOS_TEMPO:
        return f"Alvo inválido (use um de: {', '.join(REF_TIPOS_TEMPO)})"

    if ref_tipo == "livre":
        if not (titulo or "").strip():
            return "Descreva a tarefa — sem vínculo, o título é o único registro"
        return None

    if not ref_id:
        return "Selecione o alvo do apontamento"

    modelo = _MODELOS_REF[ref_tipo]
    if not modelo.query.get(ref_id):
        return "O alvo selecionado não existe mais"
    return None


# ── RESOLUÇÃO DO PROJETO (rollup denormalizado) ───────────────────────────────

def resolver_projeto(ref_tipo, ref_id, projeto_id_explicito=None):
    """A qual projeto estas horas pertencem. Resolvido UMA vez, na gravação.

    Sem isto, "horas por projeto" é uma travessia de grafo por linha
    (apontamento -> entregável -> projeto) para uma pergunta que a tela de
    Projetos faz a cada abertura. Com isto é um SUM sobre ix_tempo_projeto_inicio.

    É fato congelado, não cache: se um entregável for remanejado daqui a seis
    meses, as horas já lançadas pertencem ao projeto em que foram gastas. Mesma
    leitura de `Lancamento.taxa_aplicada` ficar congelada na linha
    (custos/models.py:312). Recalcular faria total histórico mudar sozinho — não
    "corrigir" isto para uma property.
    """
    if ref_tipo == "projeto":
        return ref_id
    if ref_tipo == "entregavel":
        e = Entregavel.query.get(ref_id)
        return e.projeto_id if e else None        # FK real e NOT NULL (models.py:1682)
    if ref_tipo == "missao_cartao":
        # Um cartão só alcança um projeto quando ele PRÓPRIO aponta para um:
        # REF_TIPOS_CARTAO = [equipamento, projeto, documento] (models.py:1945) e
        # Missao não tem projeto_id (models.py:1977). Na maioria dos cartões dá
        # None — e o relatório mostra isso como balde "sem projeto" em vez de
        # sumir com as horas.
        c = MissaoCartao.query.get(ref_id)
        return c.ref_id if (c and c.ref_tipo == "projeto") else None
    if ref_tipo == "equipamento":
        # Equipamento não pertence a projeto. NÃO inferir por
        # custo_composicoes.projeto_id: aquela tabela é a folha de custo de um
        # produto, e usá-la atribuiria as horas ao projeto sob o qual alguém por
        # acaso o custeou.
        return None
    if ref_tipo == "livre":
        return projeto_id_explicito     # o usuário escolhe, se quiser
    return None


# ── CICLO DE VIDA DO APONTAMENTO ──────────────────────────────────────────────

def abrir(user, ref_tipo="livre", ref_id=None, titulo="", nota="",
          projeto_id=None, sessao_id=None, origem="cronometro",
          inicio=None, fim=None):
    """Monta e adiciona um apontamento. NÃO commita — quem chama decide.

    O commit fica com a rota de propósito: é lá que o IntegrityError do índice
    parcial precisa virar 409, e engolir isso aqui esconderia a corrida.
    """
    ap = Apontamento(
        user_id=user.id,
        ref_tipo=ref_tipo,
        ref_id=(None if ref_tipo == "livre" else ref_id),
        titulo=(titulo or "").strip()[:200],
        titulo_chave=chave_titulo(titulo),
        projeto_id=resolver_projeto(ref_tipo, ref_id, projeto_id),
        inicio=inicio or datetime.now(),
        nota=(nota or "").strip(),
        origem=origem,
        criado_por=user.email,
        sessao_id=sessao_id,
    )
    if fim is not None:
        fechar(ap, fim, "usuario")
    db.session.add(ap)
    # A auto-referência de sessão só é possível depois que o id existe. Um flush
    # aqui é mais barato que um segundo UPDATE depois do commit.
    db.session.flush()
    if ap.sessao_id is None:
        ap.sessao_id = ap.id
    return ap


def fechar(ap, quando=None, motivo="usuario"):
    """Fecha o intervalo e recalcula a duração. Pausar e parar passam aqui.

    Os dois fazem exatamente a mesma escrita e diferem só em `motivo` — é essa
    coluna, e nada mais, que torna a linha elegível a retomada. Um caminho de
    código, uma forma de linha, nenhuma máquina de estado.

    `quando` nunca pode ficar antes do início: um relógio que andou para trás
    (NTP, horário de verão) produziria duração negativa, e ela entraria no SUM.
    """
    fim = quando or datetime.now()
    if fim < ap.inicio:
        fim = ap.inicio
    ap.fim = fim
    ap.duracao_s = int((fim - ap.inicio).total_seconds())
    ap.encerrado_por = motivo
    return ap


def retomar(ap, user):
    """Novo trecho da mesma sessão, herdando o alvo do trecho pausado.

    O cliente manda só o id: título, alvo e projeto são copiados no servidor. É o
    que permite ao widget não guardar estado nenhum entre páginas ou máquinas.
    """
    return abrir(user, ref_tipo=ap.ref_tipo, ref_id=ap.ref_id, titulo=ap.titulo,
                 nota=ap.nota, projeto_id=ap.projeto_id,
                 sessao_id=ap.sessao_id or ap.id, origem="cronometro")


def em_curso(user_id):
    return Apontamento.query.filter_by(user_id=user_id, fim=None).first()


def retomavel(user_id, agora=None):
    """A pausa que ainda pode ser retomada, ou None.

    Três condições, e a última é o que torna a resposta não ambígua:
      * fechada como 'pausa' (parar de vez não é retomável — comece outro);
      * dentro da janela (uma pausa de ontem não é a tarefa de hoje);
      * sem trecho posterior na mesma sessão — senão a corrente inteira apareceria
        como retomável e "retomar" não teria alvo único.
    """
    agora = agora or datetime.now()
    cand = (Apontamento.query
            .filter(Apontamento.user_id == user_id,
                    Apontamento.encerrado_por == "pausa",
                    Apontamento.fim.isnot(None),
                    Apontamento.fim >= agora - timedelta(hours=JANELA_RETOMADA_H))
            .order_by(Apontamento.fim.desc())
            .first())
    if not cand:
        return None
    posterior = (Apontamento.query
                 .filter(Apontamento.sessao_id == (cand.sessao_id or cand.id),
                         Apontamento.inicio > cand.inicio)
                 .first())
    return None if posterior else cand


def conflita(user_id, inicio, fim, ignorar_id=None):
    """O apontamento que se sobrepõe a este intervalo, ou None.

    Sobreposição não é bloqueada no banco: PostgreSQL exigiria EXCLUDE com
    btree_gist e o SQLite não tem equivalente, então os dois dialetos passariam a
    discordar sobre que dado é legal. Fica no app, e devolve a linha conflitante
    para a rota poder dizer QUAL — "conflita com algo" não ajuda ninguém.

    Uma linha aberta conta como ocupando até agora; `coalesce` é padrão nos dois
    bancos.
    """
    q = Apontamento.query.filter(
        Apontamento.user_id == user_id,
        Apontamento.inicio < fim,
        db.func.coalesce(Apontamento.fim, datetime.now()) > inicio,
    )
    if ignorar_id:
        q = q.filter(Apontamento.id != ignorar_id)
    return q.order_by(Apontamento.inicio).first()


def encerrar_abandonados(user_id=None, agora=None):
    """Fecha cronômetros esquecidos além do limite. Devolve quantos.

    Sexta 17h alguém vai embora. Sem isto, na segunda o apontamento vale 64 horas
    — e como o número entra na soma do projeto, o relatório inteiro fica
    indefensável por causa de um clique esquecido.

    Fecha em `inicio + LIMITE`, não em `agora`: assim o resultado não depende de
    quando a guarda rodou, e rodar hoje, amanhã, ou as duas vezes, produz
    exatamente a mesma linha. É o que torna a etapa idempotente no sentido que
    importa aqui — não só "não duplica", mas "não muda o número".

    A linha fica com encerrado_por='guarda' e a folha a pinta em âmbar: o sistema
    corta e sinaliza, em vez de adivinhar uma duração e esconder o palpite. Quem
    corrige é o dono.
    """
    agora = agora or datetime.now()
    corte = agora - timedelta(hours=LIMITE_CRONOMETRO_H)
    q = Apontamento.query.filter(Apontamento.fim.is_(None),
                                 Apontamento.inicio < corte)
    if user_id:
        q = q.filter(Apontamento.user_id == user_id)

    achados = q.all()
    for ap in achados:
        fechar(ap, ap.inicio + timedelta(hours=LIMITE_CRONOMETRO_H), "guarda")
    if achados:
        db.session.commit()
    return len(achados)


# ── AGREGAÇÃO ─────────────────────────────────────────────────────────────────

# Como o balde sem projeto aparece no relatório. Explícito de propósito: horas de
# cartão de missão quase nunca resolvem para um projeto (ver resolver_projeto), e
# omiti-las faria o total por projeto subcontar o trabalho do kanban em silêncio.
SEM_PROJETO = "(sem projeto)"

AGRUPAMENTOS = ["dia", "alvo", "projeto", "pessoa"]

# Modelos por ref_tipo, e como extrair rótulo/ativo de cada um. Tabela em vez de
# cadeia de `elif` porque `mapa_refs` e `validar_ref` precisam da MESMA lista: um
# alvo novo em REF_TIPOS_TEMPO que esqueça de aparecer aqui vira KeyError na
# gravação, e não uma linha sem rótulo descoberta meses depois no relatório.
_MODELOS_REF = {
    "projeto":       Projeto,
    "entregavel":    Entregavel,
    "missao_cartao": MissaoCartao,
    "equipamento":   Equipamento,
}


def _rotulo_de(tipo, obj):
    if tipo == "projeto":
        return {"label": obj.nome, "ativo": bool(obj.ativo)}
    if tipo == "entregavel":
        return {"label": (obj.tipo or "").strip(), "ativo": True}
    if tipo == "missao_cartao":
        return {"label": (obj.titulo or "").strip(), "ativo": True}
    return {"label": obj.nome, "ativo": bool(obj.ativo)}


def mapa_refs(apontamentos):
    """Rótulos dos alvos de uma lista: 1 query por TIPO, não 1 por linha.

    Mora no core, e não na rota, porque `agregar` também precisa dele: quando
    ficava só em routes.py, agrupar por alvo chamava `ap.rotulo()` sem mapa e
    voltava a fazer uma consulta por linha — 5.000 consultas no teto da rota de
    resumo. Aqui, quem agrega não tem como esquecer.
    """
    por_tipo = {}
    for ap in apontamentos:
        if ap.ref_tipo != "livre" and ap.ref_id:
            por_tipo.setdefault(ap.ref_tipo, set()).add(ap.ref_id)

    achados = {}
    for tipo, ids in por_tipo.items():
        modelo = _MODELOS_REF.get(tipo)
        if modelo is None:
            continue
        for obj in modelo.query.filter(modelo.id.in_(ids)).all():
            achados[(tipo, obj.id)] = _rotulo_de(tipo, obj)

    return {ap.id: achados.get((ap.ref_tipo, ap.ref_id), {"label": "", "ativo": True})
            for ap in apontamentos}


def segundos(ap):
    """Quantos segundos esta linha representa. FONTE ÚNICA para soma e agregação.

    Numa linha fechada é `duracao_s`; numa aberta é o relógio correndo. Sem esta
    função, o total somava `duracao_s` (zero na linha aberta) enquanto a tabela
    exibia o tempo vivo — a soma no topo não batia com as linhas logo abaixo dela,
    que é o tipo de divergência que faz a pessoa parar de confiar no número.
    """
    return ap.duracao_viva


def agregar(apontamentos, por="dia", refs=None):
    """Soma as durações agrupadas. Devolve lista ordenada do maior para o menor
    (exceto por dia, que sai em ordem cronológica — é uma série, não um ranking).

    `refs` é o mapa de `mapa_refs`. Quando o agrupamento é por alvo e ele não vem
    pronto, é computado AQUI — sem isso `ap.rotulo()` consulta o banco uma vez por
    linha, e o teto de 5.000 linhas da rota de resumo vira 5.000 consultas. Quem
    já tem o mapa (a rota, o export) passa o seu e não paga de novo.
    """
    if por not in AGRUPAMENTOS:
        por = "dia"
    if por == "alvo" and refs is None:
        refs = mapa_refs(apontamentos)

    nomes_projeto = {}
    if por == "projeto":
        ids = {a.projeto_id for a in apontamentos if a.projeto_id}
        if ids:
            nomes_projeto = {p.id: p.nome
                             for p in Projeto.query.filter(Projeto.id.in_(ids)).all()}

    baldes = {}
    for ap in apontamentos:
        if por == "dia":
            chave = ap.inicio.date().isoformat() if ap.inicio else ""
            rotulo = chave
        elif por == "pessoa":
            chave = ap.user_id
            rotulo = ap.usuario.nome if ap.usuario else f"#{ap.user_id}"
        elif por == "projeto":
            chave = ap.projeto_id or 0
            rotulo = nomes_projeto.get(ap.projeto_id, SEM_PROJETO)
        else:                                     # alvo
            chave = (ap.ref_tipo, ap.ref_id, ap.titulo_chave)
            rotulo = ap.rotulo(refs.get(ap.id) if refs else None)

        b = baldes.setdefault(chave, {"chave": chave if por != "alvo" else None,
                                      "rotulo": rotulo, "duracao_s": 0, "linhas": 0,
                                      "ref_tipo": ap.ref_tipo, "ref_id": ap.ref_id})
        b["duracao_s"] += segundos(ap)
        b["linhas"] += 1

    saida = list(baldes.values())
    if por == "dia":
        saida.sort(key=lambda b: b["rotulo"])
    else:
        saida.sort(key=lambda b: b["duracao_s"], reverse=True)
    return saida


def alvos_recentes(user_id, limite=8):
    """Últimos alvos distintos da pessoa — o atalho de um clique do widget.

    Sem isto, iniciar um cronômetro custa escolher tipo + alvo toda vez, e a
    fricção de começar é exatamente o que faz o dado não existir.
    """
    vistos, saida = set(), []
    linhas = (Apontamento.query
              .filter_by(user_id=user_id)
              .order_by(Apontamento.inicio.desc())
              .limit(limite * 6).all())
    for ap in linhas:
        chave = (ap.ref_tipo, ap.ref_id, ap.titulo_chave)
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append({"ref_tipo": ap.ref_tipo, "ref_id": ap.ref_id,
                      "titulo": ap.titulo or "", "rotulo": ap.rotulo(),
                      "projeto_id": ap.projeto_id})
        if len(saida) >= limite:
            break
    return saida
