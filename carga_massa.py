"""carga_massa.py — edição em massa de modelos e projetos por planilha Excel.

Para quem precisa mexer em muitos itens de uma vez (um modelo novo inteiro,
trocar o modelo de dezenas de projetos) sem clicar item por item na tela e sem
escrever direto no banco. Escrever no banco por fora pularia o vínculo
entregável ↔ modelo (`modelo_chave`/`modelo_origem`), os snapshots da curva-S,
o histórico e a auditoria; aqui tudo passa pelas mesmas regras da tela.

Três passos, sempre nesta ordem:

    exportar  gera a planilha com o que está no banco agora
    prévia    lê a planilha editada, executa TUDO numa transação e desfaz no
              fim: mostra exatamente o que o "aplicar" faria, sem gravar nada
    aplicar   a mesma execução, mas grava

Quem usa: a tela Configurações → Carga por planilha (carga_web.py) e, no
servidor, a linha de comando scripts/carga_planilha.py. As duas chamam as
funções deste módulo.

Regras da planilha (repetidas na aba LEIA-ME que o exportar gera):

  Modelos          — modelo, área. Linha nova cria o modelo; mudar a área muda.
                     Modelo que não está na aba fica como está. Renomear e
                     excluir modelo continuam na tela.
  Itens do modelo  — a lista COMPLETA de cada modelo que aparece na aba, na
                     ordem das linhas. Linha com id edita o item; sem id casa
                     pelo nome com um item que o modelo já tem, ou cria; item
                     do banco que sumiu da aba é excluído. Modelo que não
                     aparece na aba fica como está. Rodar a mesma planilha de
                     novo não muda nada.
  Projetos         — muda nome, descrição, SKU, MoSCoW, prioridade, lançamento
                     e o MODELO do projeto. Projeto que não está na aba fica
                     como está. As colunas de status e área são só informação.

Depois de gravar modelos e projetos, cada modelo tocado é aplicado aos seus
projetos abertos com modelo_sync (a mesma regra do botão "Aplicar aos
projetos"): entra o que é novo, muda o que o modelo mudou e o projeto não
tinha ajustado, e o que saiu do modelo é apagado — ou vira N/A quando já teve
andamento (status, histórico ou fluxo), para não reescrever o passado da
curva-S. Projeto que TROCA de modelo antes casa, pelo nome, os entregáveis
antigos com os itens do modelo novo, e quem casou fica com o andamento.

Cada aplicação vira um MudancaModelo (aparece no histórico do modelo, na tela)
e cada mudança de cadastro vira uma linha em audit_logs.
"""
from collections import OrderedDict
from datetime import datetime

ABA_LEIAME = "LEIA-ME"
ABA_MODELOS = "Modelos"
ABA_ITENS = "Itens do modelo"
ABA_PROJETOS = "Projetos"
ABA_LISTAS = "Listas"

COLS_MODELOS = ["modelo", "area"]
COLS_ITENS = ["modelo", "categoria", "entregavel", "peso", "responsavel_padrao",
              "natureza", "alvo", "id"]
COLS_PROJETOS = ["id", "nome", "modelo", "descricao", "sku", "moscow", "prioridade",
                 "lancamento", "status", "area", "ativo"]
# Campos do projeto que a carga muda (além do modelo) e o tamanho de cada coluna.
CAMPOS_PROJETO = OrderedDict([("nome", 200), ("descricao", 400), ("sku", 50),
                              ("moscow", 10), ("prioridade", None), ("lancamento", 40)])
TIPO_PROJETO_MAX = 20
ENTREGAVEL_MAX = 120
RESPONSAVEL_MAX = 200
IP_AUDITORIA = "planilha"


class ErroCarga(Exception):
    """Planilha recusada. `erros` é a lista do que corrigir, com aba e linha."""

    def __init__(self, erros):
        super().__init__("\n".join(erros))
        self.erros = erros


# ── leitura da planilha ──────────────────────────────────────────────────────

def _texto(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).split())


def _inteiro(v):
    """Inteiro de uma célula, None quando vazia. ValueError quando não é número."""
    s = _texto(v)
    if not s:
        return None
    f = float(s.replace(",", "."))
    if not f.is_integer():
        raise ValueError(s)
    return int(f)


def _linhas(wb, aba, colunas, erros):
    """[(nº da linha no Excel, {coluna: valor})], sem as linhas vazias. A ordem
    das colunas não importa, só o cabeçalho; coluna obrigatória faltando é erro."""
    if aba not in wb.sheetnames:
        return None
    ws = wb[aba]
    linhas = list(ws.iter_rows(values_only=True))
    if not linhas:
        return []
    cab = [_texto(c).lower() for c in linhas[0]]
    faltam = [c for c in colunas if c not in cab]
    if faltam:
        erros.append(f"[{aba}] faltam as colunas: {', '.join(faltam)}")
        return []
    idx = {c: cab.index(c) for c in colunas}
    out = []
    for n, lin in enumerate(linhas[1:], start=2):
        lin = list(lin) + [None] * (len(cab) - len(lin))
        valores = {c: lin[i] for c, i in idx.items()}
        if all(_texto(v) == "" for v in valores.values()):
            continue
        out.append((n, valores))
    return out


def ler_planilha(caminho):
    """{aba: linhas | None}. None = a aba não existe (e então nada dela muda).
    `caminho` pode ser o caminho do arquivo ou o arquivo aberto (BytesIO)."""
    from openpyxl import load_workbook
    from zipfile import BadZipFile
    try:
        wb = load_workbook(caminho, data_only=True, read_only=True)
    except (BadZipFile, KeyError, OSError, ValueError):
        raise ErroCarga(["O arquivo não é uma planilha .xlsx válida. Salve no Excel como "
                         "'Pasta de Trabalho do Excel (.xlsx)' e envie de novo."])
    erros = []
    dados = {ABA_MODELOS: _linhas(wb, ABA_MODELOS, COLS_MODELOS, erros),
             ABA_ITENS: _linhas(wb, ABA_ITENS, COLS_ITENS, erros),
             ABA_PROJETOS: _linhas(wb, ABA_PROJETOS, ["id", "nome", "modelo"], erros)}
    wb.close()
    if erros:
        raise ErroCarga(erros)
    return dados


# ── relatório ────────────────────────────────────────────────────────────────

class Relatorio:
    def __init__(self):
        self.secoes = OrderedDict()
        self.avisos = []
        self.contagem = OrderedDict()
        self._titulos = {}

    def projeto(self, pid, nome):
        """Título da seção de um projeto. Fica o nome da primeira vez que ele
        aparece: um projeto renomeado pela carga não vira duas seções."""
        return self._titulos.setdefault(pid, f"Projeto {pid} · {nome}")

    def add(self, secao, linha, conta=None):
        self.secoes.setdefault(secao, []).append(linha)
        if conta:
            self.contagem[conta] = self.contagem.get(conta, 0) + 1

    def aviso(self, linha):
        self.avisos.append(linha)

    def como_dict(self):
        """Para a tela: resumo, avisos e seções na mesma ordem do texto."""
        return {"resumo": [{"rotulo": k, "n": v} for k, v in self.contagem.items()],
                "avisos": list(self.avisos),
                "secoes": [{"titulo": t, "linhas": list(l)} for t, l in self.secoes.items()],
                "vazio": not self.contagem}

    def texto(self, titulo):
        out = [titulo, "=" * len(titulo), ""]
        if self.contagem:
            out.append("Resumo:")
            out += [f"  {k}: {v}" for k, v in self.contagem.items()]
            out.append("")
        else:
            out += ["Nada a mudar: o banco já está igual à planilha.", ""]
        if self.avisos:
            out.append("Avisos:")
            out += [f"  ! {a}" for a in self.avisos]
            out.append("")
        for secao, linhas in self.secoes.items():
            out.append(secao)
            out += [f"  {l}" for l in linhas]
            out.append("")
        return "\n".join(out)


# ── processamento (dentro de app_context; não commita) ───────────────────────

def _auditar(email, user_id, entidade, campo, antigo="", novo=""):
    from models import db, AuditLog
    db.session.add(AuditLog(
        usuario_email=email or "system", usuario_id=user_id, acao="PROJETO_UPDATED",
        entidade=entidade[:200], campo=campo[:80], valor_antigo=str(antigo or ""),
        valor_novo=str(novo or ""), ip=IP_AUDITORIA, timestamp=datetime.now()))


def _fmt(v):
    if isinstance(v, float):
        return f"{v:g}"
    return "" if v is None else str(v)


def processar(dados, email, motivo):
    """Aplica a planilha na sessão atual. Valida tudo antes de escrever: com
    qualquer erro levanta ErroCarga e nada foi mexido. Devolve o Relatorio."""
    import modelo_sync
    import vinculos
    from areas import AREA_SLUGS
    from models import (db, User, Projeto, TipoProjeto, ModeloEntregavel,
                        CategoriaEntregavel, MOSCOW, STATUS_PROJETO_ABERTO)
    from entregaveis import _parse_peso

    rel = Relatorio()
    erros = []
    user = User.query.filter_by(email=email).first() if email else None
    uid = user.id if user else None

    tipos_db = {t.nome.lower(): t for t in TipoProjeto.query.all()}
    cats = [c.nome for c in CategoriaEntregavel.query
            .order_by(CategoriaEntregavel.ordem, CategoriaEntregavel.id)]
    cat_por_lower = {c.lower(): c for c in cats}

    # 1) MODELOS (cadastro) ───────────────────────────────────────────────────
    modelos_plan = OrderedDict()      # nome canônico -> área
    for n, v in dados[ABA_MODELOS] or []:
        nome, area = _texto(v["modelo"]), _texto(v["area"]).lower()
        onde = f"[{ABA_MODELOS} linha {n}]"
        if not nome:
            erros.append(f"{onde} modelo vazio")
            continue
        if len(nome) > TIPO_PROJETO_MAX:
            erros.append(f"{onde} '{nome}' passa de {TIPO_PROJETO_MAX} caracteres")
            continue
        if area not in AREA_SLUGS:
            erros.append(f"{onde} área '{area}' inválida. Use: {', '.join(AREA_SLUGS)}")
            continue
        existente = tipos_db.get(nome.lower())
        nome = existente.nome if existente else nome
        if nome in modelos_plan:
            erros.append(f"{onde} modelo '{nome}' repetido na aba")
            continue
        modelos_plan[nome] = area
    nomes_modelo = {t.nome for t in tipos_db.values()} | set(modelos_plan)
    canonico = {n.lower(): n for n in nomes_modelo}

    # 2) ITENS DO MODELO ──────────────────────────────────────────────────────
    itens_plan = OrderedDict()        # modelo -> [dict]
    ids_vistos = set()
    todos_itens = {m.id: m for m in ModeloEntregavel.query.all()}
    for n, v in dados[ABA_ITENS] or []:
        onde = f"[{ABA_ITENS} linha {n}]"
        modelo = canonico.get(_texto(v["modelo"]).lower())
        if not modelo:
            erros.append(f"{onde} modelo '{_texto(v['modelo'])}' não existe "
                         f"(crie na aba {ABA_MODELOS})")
            continue
        try:
            mid = _inteiro(v["id"])
        except ValueError:
            erros.append(f"{onde} id '{_texto(v['id'])}' não é número")
            continue
        atual = None
        if mid is not None:
            atual = todos_itens.get(mid)
            if atual is None:
                erros.append(f"{onde} id {mid} não existe (apague o id para criar um item novo)")
                continue
            if atual.tipo_projeto != modelo:
                erros.append(f"{onde} id {mid} é do modelo '{atual.tipo_projeto}', não de "
                             f"'{modelo}' (apague o id para criar uma cópia)")
                continue
            if mid in ids_vistos:
                erros.append(f"{onde} id {mid} repetido")
                continue
            ids_vistos.add(mid)
        nome = _texto(v["entregavel"])
        if not nome:
            erros.append(f"{onde} entregável vazio")
            continue
        if len(nome) > ENTREGAVEL_MAX:
            erros.append(f"{onde} entregável passa de {ENTREGAVEL_MAX} caracteres")
            continue
        cat_txt = _texto(v["categoria"])
        categoria = cat_por_lower.get(cat_txt.lower())
        if categoria is None and atual is not None and cat_txt == (atual.categoria or ""):
            categoria = cat_txt           # dado legado não trava, igual à tela
        if categoria is None:
            erros.append(f"{onde} categoria '{cat_txt}' não cadastrada. Use: {', '.join(cats)} "
                         "(categoria nova se cria na tela de Modelos)")
            continue
        peso = _parse_peso(_texto(v["peso"]))
        if peso is None:
            erros.append(f"{onde} peso '{_texto(v['peso'])}' deve ser um número maior que zero")
            continue
        resp = _texto(v["responsavel_padrao"])
        if len(resp) > RESPONSAVEL_MAX:
            erros.append(f"{onde} responsável passa de {RESPONSAVEL_MAX} caracteres")
            continue
        natureza, alvo, err = vinculos.validar_natureza_alvo(_texto(v["natureza"]).lower(),
                                                             _texto(v["alvo"]))
        if err:
            erros.append(f"{onde} {err} (veja a aba {ABA_LISTAS})")
            continue
        itens_plan.setdefault(modelo, []).append(dict(
            linha=n, id=mid, atual=atual, tipo=nome, categoria=categoria, peso=peso,
            responsavel_padrao=resp, natureza=natureza, alvo=alvo))
    # Linha sem id com o nome de um item que o modelo JÁ tem (e que nenhuma
    # linha com id reivindicou) é esse item, não um novo. Sem isto, rodar a
    # mesma planilha duas vezes — ou uma planilha sem a coluna id preenchida —
    # excluiria e recriaria os itens, e com eles os entregáveis dos projetos.
    for modelo, linhas in itens_plan.items():
        por_nome = {}
        for m in sorted(todos_itens.values(), key=lambda x: (x.ordem or 0, x.id)):
            if m.tipo_projeto == modelo and m.id not in ids_vistos:
                por_nome.setdefault(modelo_sync.chave_nome(m.tipo), m)
        for it in linhas:
            if it["atual"] is None:
                m = por_nome.pop(modelo_sync.chave_nome(it["tipo"]), None)
                if m is not None:
                    it["atual"], it["id"] = m, m.id
                    ids_vistos.add(m.id)
    for modelo, linhas in itens_plan.items():
        vistos = {}
        for it in linhas:
            k = modelo_sync.chave_nome(it["tipo"])
            if k in vistos:
                erros.append(f"[{ABA_ITENS} linha {it['linha']}] '{it['tipo']}' repete o "
                             f"entregável da linha {vistos[k]} no modelo '{modelo}'")
            vistos[k] = it["linha"]

    # 3) PROJETOS ─────────────────────────────────────────────────────────────
    projetos_plan = []
    pids = set()
    for n, v in dados[ABA_PROJETOS] or []:
        onde = f"[{ABA_PROJETOS} linha {n}]"
        try:
            pid = _inteiro(v["id"])
        except ValueError:
            pid = None
        if pid is None:
            erros.append(f"{onde} sem id válido (projeto novo se cria na tela)")
            continue
        if pid in pids:
            erros.append(f"{onde} projeto {pid} repetido")
            continue
        pids.add(pid)
        p = db.session.get(Projeto, pid)
        if p is None:
            erros.append(f"{onde} projeto {pid} não existe")
            continue
        novos = {}
        for campo, tam in CAMPOS_PROJETO.items():
            if campo not in v:
                continue
            bruto = v[campo]
            if campo == "prioridade":
                try:
                    novos[campo] = _inteiro(bruto) or 0
                except ValueError:
                    erros.append(f"{onde} prioridade '{_texto(bruto)}' não é número")
                continue
            s = _texto(bruto)
            if campo == "nome" and not s:
                erros.append(f"{onde} nome vazio")
                continue
            if campo == "moscow" and s:
                s = {m.lower(): m for m in MOSCOW}.get(s.lower(), s)
                if s not in MOSCOW:
                    erros.append(f"{onde} MoSCoW '{s}' inválido. Use: {', '.join(MOSCOW)}")
                    continue
            if tam and len(s) > tam:
                erros.append(f"{onde} {campo} passa de {tam} caracteres")
                continue
            novos[campo] = s
        modelo_txt = _texto(v["modelo"])
        modelo = canonico.get(modelo_txt.lower()) if modelo_txt else ""
        if modelo_txt and not modelo:
            erros.append(f"{onde} modelo '{modelo_txt}' não existe (crie na aba {ABA_MODELOS})")
            continue
        if not modelo and p.tipo:
            erros.append(f"{onde} o modelo do projeto não pode ficar vazio")
            continue
        projetos_plan.append((p, novos, modelo))

    if erros:
        raise ErroCarga(erros)

    # ── a partir daqui só escreve ─────────────────────────────────────────────
    for nome, area in modelos_plan.items():
        t = tipos_db.get(nome.lower())
        if t is None:
            ordem = (db.session.query(db.func.max(TipoProjeto.ordem)).scalar() or 0) + 1
            db.session.add(TipoProjeto(nome=nome, area=area, ordem=ordem))
            rel.add("Modelos", f"+ {nome} (área {area})", "modelos criados")
            _auditar(email, uid, f"Tipo de projeto · {nome}", "tipo_criado", novo=nome)
        elif (t.area or "") != area:
            rel.add("Modelos", f"~ {nome}: área {t.area} -> {area}", "modelos com área alterada")
            _auditar(email, uid, f"Tipo de projeto · {nome}", "area", t.area, area)
            t.area = area
    db.session.flush()

    modelos_tocados = set()
    for modelo, linhas in itens_plan.items():
        secao = f"Itens do modelo {modelo}"
        ficam = {it["id"] for it in linhas if it["id"]}
        antes = ModeloEntregavel.query.filter_by(tipo_projeto=modelo).all()
        for m in antes:
            if m.id not in ficam:
                rel.add(secao, f"- {m.categoria} · {m.tipo}", "itens de modelo excluídos")
                _auditar(email, uid, f"Modelo {modelo} · {m.tipo}", "modelo_excluido")
                db.session.delete(m)
                modelos_tocados.add(modelo)
        for ordem, it in enumerate(linhas):
            campos = dict(tipo=it["tipo"], categoria=it["categoria"], peso=it["peso"],
                          responsavel_padrao=it["responsavel_padrao"],
                          natureza=it["natureza"], alvo=it["alvo"])
            m = it["atual"]
            if m is None:
                db.session.add(ModeloEntregavel(tipo_projeto=modelo, ordem=ordem, **campos))
                rel.add(secao, f"+ {it['categoria']} · {it['tipo']} (peso {it['peso']:g})",
                        "itens de modelo criados")
                _auditar(email, uid, f"Modelo {modelo} · {it['tipo']}", "modelo_criado")
                modelos_tocados.add(modelo)
                continue
            difs = []
            for campo, novo in campos.items():
                antigo = getattr(m, campo)
                antigo = (antigo or "") if campo != "peso" else (antigo if antigo is not None else 1.0)
                if (round(float(antigo), 4) != round(float(novo), 4) if campo == "peso"
                        else antigo != novo):
                    difs.append(f"{campo}: {_fmt(antigo) or '(vazio)'} -> {_fmt(novo) or '(vazio)'}")
                    _auditar(email, uid, f"Modelo {modelo} · {it['tipo']}", campo, antigo, novo)
                    setattr(m, campo, novo)
            if difs:
                rel.add(secao, f"~ {m.tipo}: " + "; ".join(difs), "itens de modelo editados")
                modelos_tocados.add(modelo)
            if (m.ordem or 0) != ordem:
                m.ordem = ordem
                if not difs:
                    rel.add(secao, f"~ {m.tipo}: só a posição", "itens de modelo reordenados")
                modelos_tocados.add(modelo)
    db.session.flush()

    # Projetos: campos simples e troca de modelo.
    trocaram = {}                     # projeto -> modelo antigo
    for p, novos, modelo in projetos_plan:
        secao = rel.projeto(p.id, p.nome)
        for campo, novo in novos.items():
            antigo = getattr(p, campo)
            antigo = (antigo or 0) if campo == "prioridade" else (antigo or "")
            if antigo != novo:
                rel.add(secao, f"~ {campo}: {_fmt(antigo) or '(vazio)'} -> {_fmt(novo) or '(vazio)'}",
                        "campos de projeto alterados")
                _auditar(email, uid, f"Projeto:{p.nome}", campo, antigo, novo)
                setattr(p, campo, novo)
        if modelo and modelo != (p.tipo or ""):
            aberto = p.ativo and p.status in STATUS_PROJETO_ABERTO
            if not aberto:
                rel.aviso(f"projeto {p.id} '{p.nome}' está arquivado/concluído: o modelo NÃO "
                          f"foi trocado ({p.tipo or '(vazio)'} -> {modelo} ignorado)")
                continue
            rel.add(secao, f"~ modelo: {p.tipo or '(vazio)'} -> {modelo}", "projetos com modelo trocado")
            _auditar(email, uid, f"Projeto:{p.nome}", "tipo", p.tipo or "", modelo)
            trocaram[p] = p.tipo or ""
            p.tipo = modelo
    db.session.flush()

    # Projeto que trocou de modelo: o entregável ligado ao modelo antigo que tem
    # o mesmo nome de um item do novo passa para o item novo e fica com o
    # andamento. Categoria e peso vêm do modelo novo (é a troca que se pediu);
    # o responsável do projeto, se houver, fica.
    for p, antigo in trocaram.items():
        itens = modelo_sync._itens_do_modelo(p.tipo)
        chaves_novas = {m.chave for m in itens}
        livres = {}
        for m in itens:
            livres.setdefault(modelo_sync.chave_nome(m.tipo), m)
        for e in p.entregaveis:
            if e.modelo_chave in chaves_novas:
                livres.pop(modelo_sync.chave_nome(e.tipo), None)
        secao = rel.projeto(p.id, p.nome)
        for e in sorted(p.entregaveis, key=lambda x: (x.ordem or 0, x.id)):
            if not e.modelo_chave or e.modelo_chave in chaves_novas:
                continue
            m = livres.pop(modelo_sync.chave_nome(e.tipo), None)
            if m is None:
                continue
            difs = []
            if (e.categoria or "") != (m.categoria or ""):
                difs.append(f"categoria {e.categoria} -> {m.categoria}")
                e.categoria = m.categoria
            if modelo_sync._peso(e.peso) != modelo_sync._peso(m.peso):
                difs.append(f"peso {_fmt(e.peso)} -> {_fmt(m.peso)}")
                e.peso = modelo_sync._peso(m.peso)
            if (e.tipo or "").strip() != (m.tipo or "").strip():
                difs.append(f"nome '{e.tipo}' -> '{m.tipo}'")
                e.tipo = m.tipo.strip()
            if not (e.responsaveis or "").strip() and (m.responsavel_padrao or "").strip():
                e.responsaveis = m.responsavel_padrao.strip()
            modelo_sync.vincular(e, m)
            modelo_sync._preservar_atualizado_em(e)
            rel.add(secao, f"= {e.tipo}: passa para o modelo {p.tipo} mantendo o andamento "
                           f"({e.status or 'pendente'})" + (f" — {'; '.join(difs)}" if difs else ""),
                    "entregáveis reaproveitados na troca de modelo")
    db.session.flush()

    # 4) PROPAGAÇÃO — modelo_sync, a mesma regra do "Aplicar aos projetos".
    afetados = sorted(modelos_tocados | {p.tipo for p in trocaram})
    projetos_tocados = set(trocaram)
    rotulo = {"criar": "+ criado", "vincular": "= ligado ao modelo (avulso de mesmo nome)",
              "renomeado": "~ renomeado", "categoria": "~ categoria", "peso": "~ peso",
              "responsavel": "~ responsável", "mantido": "· mantido (ajuste do projeto)"}
    for tipo in afetados:
        previa = modelo_sync.calcular_previa(tipo)
        selecao, decisoes = {}, {}
        for pp in previa["projetos"]:
            if not pp["mudancas"]:
                continue
            selecao[pp["id"]] = pp["versao"]
            secao = rel.projeto(pp['id'], pp['nome'])
            for c in pp["mudancas"]:
                if c["acao"] == "remover":
                    if c["andamento"]:
                        decisoes[c["entregavel_id"]] = "na"
                        rel.add(secao, f"- {c['entregavel']}: saiu do modelo, tinha andamento "
                                       f"({c['status']}) -> vira N/A", "entregáveis que viraram N/A")
                    else:
                        rel.add(secao, f"- {c['entregavel']}: saiu do modelo -> apagado",
                                "entregáveis apagados")
                    continue
                txt = f"{rotulo[c['acao']]} {c['entregavel']}"
                if c.get("campo"):
                    txt += f" ({c['campo']}: {c['antes'] or '(vazio)'} -> {c['depois'] or '(vazio)'})"
                conta = {"criar": "entregáveis criados", "vincular": "entregáveis ligados ao modelo",
                         "mantido": "ajustes de projeto mantidos"}.get(c["acao"], "entregáveis atualizados")
                rel.add(secao, txt, conta)
        if selecao:
            mud = modelo_sync.aplicar(tipo, selecao, decisoes, motivo, email)
            projetos_tocados |= {db.session.get(Projeto, pid) for pid in selecao}
            rel.add("Aplicações de modelo", f"{tipo}: {mud.n_alteracoes} alteração(ões) em "
                                            f"{mud.n_projetos} projeto(s)")

    # Quem trocou de modelo e não precisou de propagação passa a conhecer o
    # modelo novo (aplicar já faz isso para quem passou por ele).
    for p in trocaram:
        modelo_sync.marcar_conhecidos(p, modelo_sync._itens_do_modelo(p.tipo))

    # Natureza/alvo e itens criados: o vínculo com o documento é calculado.
    abertos = set(projetos_tocados)
    for tipo in afetados:
        abertos |= set(modelo_sync.projetos_do_modelo(tipo))
    for p in sorted(abertos, key=lambda x: x.id):
        for e, antigo in vinculos.sincronizar_projeto(p, email):
            rel.add(rel.projeto(p.id, p.nome),
                    f"~ {e.tipo}: status {antigo} -> {e.status} (documento ligado)",
                    "status vindos do documento")
            _auditar(email, uid, f"{p.nome} · {e.tipo}", "status", antigo, e.status)
    db.session.flush()
    for p in projetos_tocados:
        p.registrar_snapshot()

    if rel.contagem:
        _auditar(email, uid, "Carga por planilha", "carga_planilha",
                 novo=f"{motivo} — " + ", ".join(f"{k}: {v}" for k, v in rel.contagem.items()))
    db.session.flush()
    return rel


# ── exportar ─────────────────────────────────────────────────────────────────

LEIAME = """Carga por planilha do DocTrack — leia antes de editar

1. Edite só as abas Modelos, Itens do modelo e Projetos. A aba Listas mostra os valores aceitos.
2. Não mexa na coluna id. Linha nova = deixe o id vazio. Não copie linhas com id de um modelo para outro.
   Linha sem id com o mesmo nome de um item que o modelo já tem é tratada como esse item (não duplica).
3. Itens do modelo: cada modelo que aparece na aba é a lista COMPLETA dele, na ordem das linhas.
   Apagar a linha = excluir o item do modelo. Modelo que você não quer mexer: apague TODAS as linhas dele
   (assim ele fica como está). Entregável repetido dentro do mesmo modelo é recusado.
4. Modelos: linha nova cria um modelo (até 20 caracteres) na área indicada. Renomear e excluir modelo é na tela.
5. Projetos: dá para mudar nome, descrição, SKU, MoSCoW, prioridade, lançamento e modelo.
   Status, área e ativo são só informação. Projeto que você não quer mexer pode sair da aba.
6. Depois de gravar, cada modelo mexido é aplicado aos projetos abertos dele (igual ao botão "Aplicar aos projetos"):
   - item novo do modelo -> entregável novo no projeto
   - item que mudou -> muda no projeto, a menos que o projeto tenha ajustado aquele campo
   - item que saiu -> entregável apagado; se já teve andamento (status, histórico ou fluxo), vira N/A
   - projeto que troca de modelo aproveita os entregáveis de mesmo nome, com o andamento deles
7. Envie a planilha na tela Configurações > Carga por planilha: ela mostra a PRÉVIA primeiro
   (nada é gravado) e só grava quando você clica em Aplicar.
"""


def exportar(caminho):
    """Grava a planilha com o estado atual. `caminho` pode ser um arquivo aberto
    (BytesIO). Precisa de app_context."""
    import vinculos
    from areas import AREA_SLUGS, get_area
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    from models import (TipoProjeto, ModeloEntregavel, Projeto, CategoriaEntregavel,
                        MOSCOW, AREA_PROJETO_LEGADO)

    wb = Workbook()
    ws = wb.active
    ws.title = ABA_LEIAME
    for i, linha in enumerate(LEIAME.splitlines(), start=1):
        ws.cell(row=i, column=1, value=linha)
    ws["A1"].font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 120

    cab_font, cab_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2F5496")
    info_fill = PatternFill("solid", fgColor="E7E6E6")

    def aba(nome, colunas, larguras, info=()):
        w = wb.create_sheet(nome)
        w.append(colunas)
        for i, c in enumerate(colunas, start=1):
            cel = w.cell(row=1, column=i)
            cel.font, cel.fill = cab_font, (info_fill if c in info else cab_fill)
            if c in info:
                cel.font = Font(bold=True, color="595959")
            w.column_dimensions[cel.column_letter].width = larguras.get(c, 14)
        w.freeze_panes = "A2"
        return w

    tipos = TipoProjeto.query.order_by(TipoProjeto.ordem, TipoProjeto.id).all()
    wm = aba(ABA_MODELOS, COLS_MODELOS, {"modelo": 22, "area": 16})
    for t in tipos:
        wm.append([t.nome, t.area or AREA_PROJETO_LEGADO])

    wi = aba(ABA_ITENS, COLS_ITENS, {"modelo": 14, "categoria": 18, "entregavel": 48,
                                      "peso": 8, "responsavel_padrao": 24, "natureza": 16,
                                      "alvo": 26, "id": 8}, info=("id",))
    ordem_tipo = {t.nome: i for i, t in enumerate(tipos)}
    itens = sorted(ModeloEntregavel.query.all(),
                   key=lambda m: (ordem_tipo.get(m.tipo_projeto, 999), m.tipo_projeto,
                                  m.ordem or 0, m.id))
    for m in itens:
        wi.append([m.tipo_projeto, m.categoria or "", (m.tipo or "").strip(),
                   m.peso if m.peso is not None else 1.0, m.responsavel_padrao or "",
                   m.natureza or "", m.alvo or "", m.id])

    area_tipo = {t.nome: (t.area or AREA_PROJETO_LEGADO) for t in tipos}
    wp = aba(ABA_PROJETOS, COLS_PROJETOS,
             {"id": 7, "nome": 40, "modelo": 14, "descricao": 40, "sku": 14, "moscow": 10,
              "prioridade": 10, "lancamento": 14, "status": 12, "area": 12, "ativo": 8},
             info=("id", "status", "area", "ativo"))
    for p in Projeto.query.order_by(Projeto.ativo.desc(), Projeto.nome, Projeto.id).all():
        wp.append([p.id, p.nome, p.tipo or "", p.descricao or "", p.sku or "", p.moscow or "",
                   p.prioridade or 0, p.lancamento or "", p.status,
                   area_tipo.get(p.tipo or "", AREA_PROJETO_LEGADO), "sim" if p.ativo else "não"])

    wl = wb.create_sheet(ABA_LISTAS)
    cats = [c.nome for c in CategoriaEntregavel.query.order_by(CategoriaEntregavel.ordem,
                                                               CategoriaEntregavel.id)]
    colunas = [
        ("area", [(a, (get_area(a) or {}).get("nome", a)) for a in AREA_SLUGS]),
        ("categoria", [(c, "") for c in cats]),
        ("natureza", [(n, r) for n, r in vinculos.NATUREZAS if n]),
        ("alvo (só natureza documento)", vinculos.alvos_documento()),
        ("moscow", [(m, "") for m in MOSCOW]),
    ]
    for j, (titulo, valores) in enumerate(colunas):
        col = j * 2 + 1
        wl.cell(row=1, column=col, value=titulo).font = Font(bold=True)
        wl.cell(row=1, column=col + 1, value="descrição").font = Font(bold=True, color="595959")
        for i, (val, desc) in enumerate(valores, start=2):
            wl.cell(row=i, column=col, value=val)
            wl.cell(row=i, column=col + 1, value=desc)
        wl.column_dimensions[wl.cell(row=1, column=col).column_letter].width = 26
        wl.column_dimensions[wl.cell(row=1, column=col + 1).column_letter].width = 28
    for c in wl[1]:
        c.alignment = Alignment(wrap_text=True)

    def lista(ws_alvo, letra, col_listas, n):
        """Lista suspensa na coluna, apontando para a aba Listas. Não bloqueia
        (a validação de verdade é no script), só ajuda a digitar."""
        dv = DataValidation(type="list", allow_blank=True, showErrorMessage=False,
                            formula1=f"={ABA_LISTAS}!${col_listas}$2:${col_listas}${n + 1}")
        ws_alvo.add_data_validation(dv)
        dv.add(f"{letra}2:{letra}5000")

    lista(wm, "B", "A", len(AREA_SLUGS))
    lista(wi, "B", "C", max(len(cats), 1))
    lista(wi, "F", "E", len([n for n, _ in vinculos.NATUREZAS if n]))
    lista(wi, "G", "G", len(vinculos.alvos_documento()))
    lista(wp, "F", "I", len(MOSCOW))
    wb.active = 1
    wb.save(caminho)
    return {"modelos": len(tipos), "itens": len(itens), "projetos": wp.max_row - 1}
