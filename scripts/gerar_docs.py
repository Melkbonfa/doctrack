"""gerar_docs.py — deriva a referência técnica a partir do código.

Gera os quatro arquivos de `docs/referencia/`:

    api.md          as rotas HTTP, com método, papel exigido e descrição
    dados.md        dicionário das tabelas + diagramas ER por domínio
    permissoes.md   matriz papel × rota e o mapa de áreas/módulos
    config.md       variáveis de ambiente lidas pelo código

Existe porque documentação de referência escrita à mão apodrece — este
repositório já pagou esse preço duas vezes (os quatro guias de implantação que
não diziam qual valia, e a tabela do README que mandava rodar um script de
backup removido). Tudo que dá para derivar do código é derivado, e
`tests/test_docs_sincronia.py` roda este mesmo gerador em modo `--check`: se o
código mudar e a referência não for regerada, a suíte quebra.

Uso:
    python scripts/gerar_docs.py            # regera os arquivos
    python scripts/gerar_docs.py --check    # falha (exit 1) se estiverem defasados

Três decisões que valem o registro:

1. **As rotas vêm do `url_map`, as permissões vêm do AST.** O `url_map` é a
   verdade sobre o que está no ar (prefixo de blueprint, aliases, métodos), mas
   o papel exigido mora numa closure de `require_role` — ler o fonte é mais
   honesto que escavar `__closure__`.

2. **Os comentários das colunas entram no dicionário de dados.** O
   conhecimento de domínio deste sistema está nos comentários de `models.py`
   ("SKU de Venda (chave de junção)", "data ALVO de conclusão"), não em
   docstrings. Um dicionário sem eles seria uma lista de tipos — inútil.

3. **Classe de modelo não mapeada é erro, não aviso.** `DOMINIOS` precisa
   cobrir toda classe de `models.py`. Um modelo novo derruba o gerador, o que
   força a decisão "a que domínio isto pertence?" na hora em que ela é barata.
"""
import argparse
import ast
import io
import os
import re
import sys
import tokenize
from collections import defaultdict

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(RAIZ, "docs", "referencia")

CABECALHO = (
    "<!-- GERADO POR scripts/gerar_docs.py — NÃO EDITE À MÃO.\n"
    "     Para mudar este arquivo, mude o código e rode:\n"
    "         python scripts/gerar_docs.py\n"
    "     tests/test_docs_sincronia.py falha se ele estiver defasado. -->\n\n"
)


# ── AMBIENTE ──────────────────────────────────────────────────────────────────

def _preparar_ambiente():
    """Prepara o import de `servidor` sem tocar em banco real nem em rede.

    Mesmas travas do conftest: o gerador roda na máquina do desenvolvedor e na
    CI, e em nenhuma das duas ele pode alcançar o Postgres de produção.
    """
    import tempfile

    sentinela = os.path.join(tempfile.gettempdir(), "doctrack_gerar_docs.db")
    os.environ.setdefault("JWT_SECRET", "gerar-docs-secret-key-32-caracteres-ok")
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5000")
    os.environ.setdefault("BCRYPT_LOG_ROUNDS", "4")
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{sentinela}")
    os.environ.setdefault("DOCTRACK_AGENDADOR", "0")
    os.environ.setdefault("DOCTRACK_CAMBIO", "0")
    os.environ.setdefault("DOCTRACK_PATH_ALIASES", r"P:=\\exemplo\Projetos$")
    sys.path.insert(0, RAIZ)


# ── LEITURA DO FONTE ──────────────────────────────────────────────────────────

def _comentarios_por_linha(fonte):
    """{nº da linha: texto do comentário} para um arquivo .py."""
    saida = {}
    leitor = io.StringIO(fonte).readline
    try:
        for tok in tokenize.generate_tokens(leitor):
            if tok.type == tokenize.COMMENT:
                saida[tok.start[0]] = tok.string.lstrip("#").strip()
    except (tokenize.TokenError, IndentationError):
        pass
    return saida


def _comentario_da_linha(comentarios, linha, linhas_fonte):
    """Comentário que descreve a linha: o da própria linha, ou o bloco acima.

    Um comentário na mesma linha (`sku = ...  # SKU de Venda`) descreve aquela
    coluna. Na falta dele, o bloco de linhas `#` imediatamente acima descreve a
    coluna seguinte — é como os comentários longos de models.py são escritos.
    """
    if linha in comentarios and not _linha_so_comentario(linhas_fonte, linha):
        return comentarios[linha]

    bloco = []
    n = linha - 1
    while n >= 1 and n in comentarios and _linha_so_comentario(linhas_fonte, n):
        if _e_separador(comentarios[n]):
            break   # cabeçalho de seção ("── marcos temporais ──") não é nota de coluna
        bloco.insert(0, comentarios[n])
        n -= 1
    return " ".join(bloco).strip()


def _e_separador(txt):
    """Comentário que só divide seções, não descreve a coluna seguinte."""
    return bool(re.search(r"[─═=\-]{3,}", txt or ""))


def _linha_so_comentario(linhas_fonte, n):
    if n < 1 or n > len(linhas_fonte):
        return False
    return linhas_fonte[n - 1].lstrip().startswith("#")


def _literal(no):
    """Valor de um nó AST quando é literal; None quando não é."""
    try:
        return ast.literal_eval(no)
    except (ValueError, TypeError, SyntaxError):
        return None


def _nome_decorator(no):
    """Nome chamável de um decorator: `require_role`, `app.route`, ..."""
    alvo = no.func if isinstance(no, ast.Call) else no
    partes = []
    while isinstance(alvo, ast.Attribute):
        partes.insert(0, alvo.attr)
        alvo = alvo.value
    if isinstance(alvo, ast.Name):
        partes.insert(0, alvo.id)
    return ".".join(partes)


# ── ROTAS ─────────────────────────────────────────────────────────────────────

ARQUIVOS_DE_ROTA = [
    "servidor.py", "auth.py", "documentos.py", "entregaveis.py", "missoes.py",
    "killswitch.py", "custos/routes.py", "tempos/routes.py", "pdr/routes.py",
    "cadernos/routes.py", "fluxos/routes.py", "notificacoes/routes.py",
]

PAPEIS = ["admin", "gestor", "tecnico", "leitura"]


def _aliases_de_papel(arvore):
    """Decorators locais que só reembrulham require_role.

    `custos/routes.py` define `so_gestao` e `tempos/routes.py` define
    `so_membros`; ambos são `require_role(...)` com outro nome. Resolver isso
    lendo o fonte evita uma tabela fixa aqui que silenciosamente mentiria se a
    definição mudasse.
    """
    aliases = {}
    for no in arvore.body:
        if not isinstance(no, ast.FunctionDef) or len(no.body) != 1:
            continue
        ret = no.body[0]
        if not isinstance(ret, ast.Return) or not isinstance(ret.value, ast.Call):
            continue
        interno = ret.value.func
        if isinstance(interno, ast.Call) and _nome_decorator(interno) == "require_role":
            papeis = [_literal(a) for a in interno.args]
            aliases[no.name] = [p for p in papeis if p]
    return aliases


def _acesso_da_funcao(decorators, aliases):
    """(rótulo de acesso, lista de papéis, área exigida) para uma view."""
    for dec in decorators:
        nome = _nome_decorator(dec)
        args = [_literal(a) for a in dec.args] if isinstance(dec, ast.Call) else []

        if nome == "require_role":
            papeis = [a for a in args if a]
            return ("papel", papeis, None)
        if nome in aliases:
            return ("papel", aliases[nome], None)
        if nome == "require_area":
            papeis = [a for a in args[1:] if a]
            return ("area", papeis, args[0] if args else None)
        if nome == "require_pdr_access":
            papeis = [a for a in args if a]
            return ("area", papeis, "pdr")
        if nome == "jwt_required":
            return ("autenticado", [], None)
    return ("publico", [], None)


def _views_do_arquivo(caminho_rel):
    """{nome da função: {...}} com acesso e descrição, lidos do fonte."""
    caminho = os.path.join(RAIZ, caminho_rel)
    with open(caminho, encoding="utf-8") as fh:
        fonte = fh.read()
    arvore = ast.parse(fonte)
    aliases = _aliases_de_papel(arvore)

    saida = {}
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        nomes = {_nome_decorator(d) for d in no.decorator_list}
        if not any(n.endswith(".route") for n in nomes):
            continue
        tipo, papeis, area = _acesso_da_funcao(no.decorator_list, aliases)
        doc = ast.get_docstring(no) or ""
        saida[no.name] = {
            "arquivo": caminho_rel,
            "linha": no.lineno,
            "acesso": tipo,
            "papeis": papeis,
            "area": area,
            "descricao": doc.strip().split("\n")[0].strip(),
        }
    return saida


def coletar_rotas():
    """Junta o url_map (verdade sobre o que está no ar) com o AST (permissões)."""
    _preparar_ambiente()
    from servidor import app

    do_fonte = {}
    for rel in ARQUIVOS_DE_ROTA:
        do_fonte[rel] = _views_do_arquivo(rel)

    # blueprint -> arquivo que o define, para desambiguar nomes de função iguais
    bp_para_arquivo = {}
    for nome, bp in app.blueprints.items():
        modulo = bp.import_name.replace(".", "/")
        for rel in ARQUIVOS_DE_ROTA:
            if rel == f"{modulo}.py" or rel.startswith(f"{modulo}/"):
                bp_para_arquivo[nome] = rel
                break

    rotas = []
    for regra in app.url_map.iter_rules():
        endpoint = regra.endpoint
        if endpoint == "static" or endpoint.endswith(".static"):
            continue

        if "." in endpoint:
            bp_nome, func = endpoint.split(".", 1)
            arquivo = bp_para_arquivo.get(bp_nome, "servidor.py")
        else:
            func, arquivo = endpoint, "servidor.py"

        info = do_fonte.get(arquivo, {}).get(func)
        if info is None:  # função definida em outro arquivo (raro): procurar
            for rel, views in do_fonte.items():
                if func in views:
                    info, arquivo = views[func], rel
                    break
        if info is None:
            info = {"arquivo": arquivo, "linha": 0, "acesso": "?", "papeis": [],
                    "area": None, "descricao": ""}

        metodos = sorted(regra.methods - {"HEAD", "OPTIONS"})
        rotas.append({
            "path": str(regra.rule),
            "metodos": metodos,
            "endpoint": endpoint,
            "api": str(regra.rule).startswith("/api/"),
            **info,
        })

    rotas.sort(key=lambda r: (r["arquivo"], r["path"], r["metodos"]))
    return rotas


def _rotulo_acesso(rota):
    if rota["acesso"] == "publico":
        # Rota de página sem decorator não é rota aberta: ela devolve a casca
        # HTML e o token é validado no front, com todo dado vindo depois de
        # `/api/*` — que é gatilhado. Misturar as duas sob a mesma etiqueta
        # esconderia a superfície pública real, que são meia dúzia de rotas.
        return "página (casca)" if not rota["api"] else "público"
    if rota["acesso"] == "autenticado":
        return "autenticado"
    if rota["acesso"] == "area":
        area = f"área `{rota['area']}`"
        return f"{area} + {', '.join(rota['papeis'])}" if rota["papeis"] else area
    return ", ".join(rota["papeis"]) or "—"


# ── TABELAS ───────────────────────────────────────────────────────────────────

# Classe de modelo -> domínio. models.py concentra 35 classes de seis domínios
# diferentes, então o agrupamento não sai do nome do módulo. Classe ausente aqui
# derruba o gerador de propósito (ver docstring do arquivo).
DOMINIOS = {
    "User": "acesso", "AuditLog": "acesso", "RevokedToken": "acesso",
    "SistemaLock": "acesso", "ImportacaoLog": "acesso",

    "Documento": "documentos", "DocumentoHistorico": "documentos",
    "DocumentoArquivo": "documentos",

    "Equipamento": "equipamentos", "EquipamentoPasta": "equipamentos",
    "EquipamentoArquivo": "equipamentos", "EquipamentoHistorico": "equipamentos",
    "EquipamentoSnapshot": "equipamentos", "CategoriaEquipamento": "equipamentos",
    "FamiliaEquipamento": "equipamentos", "EquipamentoItem": "equipamentos",
    "ParetoHistorico": "equipamentos",

    "TipoConsumivel": "consumiveis", "Consumivel": "consumiveis",
    "ConsumivelEquipamento": "consumiveis",

    "Projeto": "projetos", "Entregavel": "projetos",
    "EntregavelHistorico": "projetos", "ModeloEntregavel": "projetos",
    "TipoProjeto": "projetos",
    "CategoriaEntregavel": "projetos",
    "MudancaModelo": "projetos", "MudancaModeloItem": "projetos",
    "ProjetoMensal": "projetos", "ProjetoSnapshot": "projetos",
    "ProjetoBaseline": "projetos",

    "Missao": "missoes", "MissaoColuna": "missoes", "MissaoCartao": "missoes",
    "MissaoCartaoHistorico": "missoes", "MissaoSnapshot": "missoes",
    "MissaoCartaoItem": "missoes", "MissaoCartaoComentario": "missoes",
    "MissaoModelo": "missoes",

    "Composicao": "custos", "Lancamento": "custos", "Cotacao": "custos",
    "Versao": "custos",

    "Apontamento": "tempos",

    "Produto": "pdr", "Apresentacao": "pdr", "PdrDocumento": "pdr",

    "Caderno": "cadernos", "CadernoMembro": "cadernos", "CadernoNo": "cadernos",
    "CadernoPagina": "cadernos", "CadernoPaginaVersao": "cadernos",
    "CadernoArquivo": "cadernos", "CadernoExportacao": "cadernos",

    "FluxoModelo": "fluxos", "Fluxo": "fluxos", "FluxoParticipante": "fluxos",
    "FluxoPassagem": "fluxos", "FluxoArquivo": "fluxos", "Notificacao": "fluxos",
}

TITULOS_DOMINIO = {
    "acesso": "Acesso, auditoria e estado do sistema",
    "documentos": "Documentos",
    "equipamentos": "Equipamentos e taxonomia",
    "consumiveis": "Consumíveis",
    "projetos": "Projetos e entregáveis",
    "missoes": "Missões (kanban)",
    "custos": "Custos",
    "tempos": "Tempos",
    "pdr": "PDR (P&D de reagentes)",
    "cadernos": "Cadernos de laboratório",
    "fluxos": "Fluxos de revisão e notificações",
}

ORDEM_DOMINIOS = ["acesso", "equipamentos", "documentos", "consumiveis",
                  "projetos", "missoes", "fluxos", "custos", "tempos", "pdr",
                  "cadernos"]


def _colunas_comentadas(arquivo):
    """{classe: {coluna: comentário}} lido do fonte de um arquivo de modelos."""
    caminho = os.path.join(RAIZ, arquivo)
    with open(caminho, encoding="utf-8") as fh:
        fonte = fh.read()
    linhas = fonte.splitlines()
    comentarios = _comentarios_por_linha(fonte)
    arvore = ast.parse(fonte)

    saida = {}
    for no in arvore.body:
        if not isinstance(no, ast.ClassDef):
            continue
        por_coluna = {}
        for item in no.body:
            if not isinstance(item, ast.Assign) or not item.targets:
                continue
            alvo = item.targets[0]
            if not isinstance(alvo, ast.Name):
                continue
            if not isinstance(item.value, ast.Call):
                continue
            if _nome_decorator(item.value) not in ("db.Column", "Column"):
                continue
            txt = _comentario_da_linha(comentarios, item.lineno, linhas)
            if txt:
                por_coluna[alvo.id] = txt
        saida[no.name] = por_coluna
    return saida


def coletar_tabelas():
    """[{classe, tabela, dominio, arquivo, colunas:[...]}] de todos os modelos."""
    _preparar_ambiente()
    import servidor  # noqa: F401  (registra todos os modelos no metadata)
    from models import db

    comentarios = {}
    for arq in ("models.py", "custos/models.py", "tempos/models.py", "pdr/models.py",
                "cadernos/models.py", "fluxos/models.py", "notificacoes/models.py"):
        comentarios.update(_colunas_comentadas(arq))

    tabelas = []
    nao_mapeadas = []
    for mapper in db.Model.registry.mappers:
        cls = mapper.class_
        nome = cls.__name__
        dominio = DOMINIOS.get(nome)
        if dominio is None:
            nao_mapeadas.append(nome)
            continue

        cols = []
        for col in mapper.local_table.columns:
            fks = sorted(f"{fk.column.table.name}.{fk.column.name}"
                         for fk in col.foreign_keys)
            padrao = ""
            if col.default is not None:
                arg = getattr(col.default, "arg", None)
                padrao = "(dinâmico)" if callable(arg) else repr(arg)
            cols.append({
                "nome": col.name,
                "tipo": str(col.type),
                "nulo": bool(col.nullable),
                "pk": bool(col.primary_key),
                "unico": bool(col.unique),
                "indice": bool(col.index),
                "fks": fks,
                "padrao": padrao,
                "comentario": comentarios.get(nome, {}).get(col.name, ""),
            })

        tabelas.append({
            "classe": nome,
            "tabela": mapper.local_table.name,
            "dominio": dominio,
            "colunas": cols,
        })

    if nao_mapeadas:
        raise SystemExit(
            "Modelos sem domínio em DOMINIOS (scripts/gerar_docs.py): "
            + ", ".join(sorted(nao_mapeadas))
            + "\nAdicione cada um ao dicionário DOMINIOS e regere a documentação."
        )

    tabelas.sort(key=lambda t: (ORDEM_DOMINIOS.index(t["dominio"]), t["tabela"]))
    return tabelas


# ── VARIÁVEIS DE AMBIENTE ─────────────────────────────────────────────────────

RE_ENV = re.compile(
    r"os\.(?:environ\.get|getenv)\(\s*[\"']([A-Z_0-9]+)[\"']\s*(?:,\s*(.+?))?\s*\)"
)


def coletar_env():
    """[{nome, padrao, arquivos, documentada}] de tudo que o código lê do ambiente."""
    achados = defaultdict(lambda: {"padroes": set(), "arquivos": set()})

    for base, dirs, arqs in os.walk(RAIZ):
        dirs[:] = [d for d in dirs if d not in
                   ("venv", ".git", "__pycache__", "node_modules", ".claude",
                    ".pytest_cache", "backups", "logs")]
        for arq in arqs:
            if not arq.endswith(".py"):
                continue
            caminho = os.path.join(base, arq)
            rel = os.path.relpath(caminho, RAIZ).replace("\\", "/")
            if rel.startswith("tests/"):
                continue
            with open(caminho, encoding="utf-8", errors="replace") as fh:
                for m in RE_ENV.finditer(fh.read()):
                    nome, padrao = m.group(1), (m.group(2) or "").strip()
                    achados[nome]["padroes"].add(padrao)
                    achados[nome]["arquivos"].add(rel)

    exemplo = ""
    caminho_exemplo = os.path.join(RAIZ, ".env.example")
    if os.path.exists(caminho_exemplo):
        with open(caminho_exemplo, encoding="utf-8") as fh:
            exemplo = fh.read()

    saida = []
    for nome, dados in sorted(achados.items()):
        padroes = sorted(p for p in dados["padroes"] if p)
        saida.append({
            "nome": nome,
            "padrao": padroes[0] if padroes else "",
            "obrigatoria": not padroes,
            "arquivos": sorted(dados["arquivos"]),
            "documentada": bool(re.search(rf"^#?\s*{nome}=", exemplo, re.M)),
        })
    return saida


# ── RENDERIZAÇÃO ──────────────────────────────────────────────────────────────

def _md_escape(txt):
    return (txt or "").replace("|", "\\|").replace("\n", " ").strip()


def render_api(rotas):
    api = [r for r in rotas if r["api"]]
    paginas = [r for r in rotas if not r["api"]]

    L = [CABECALHO, "# Referência da API\n",
         f"{len(rotas)} rotas registradas: **{len(api)}** de API (`/api/...`) e "
         f"**{len(paginas)}** de página.\n",
         "A coluna **Acesso** é lida dos decorators no fonte:\n",
         "| Rótulo | Significa |", "|---|---|",
         "| `público` | sem token — alcançável por qualquer um na rede |",
         "| `autenticado` | qualquer usuário logado (`@jwt_required`) |",
         "| lista de papéis | só esses papéis (`@require_role`) |",
         "| `área X + papéis` | precisa da área no cadastro (`@require_area`) |",
         "",
         "> Com o kill switch acionado **tudo** aqui responde `423`, menos as rotas "
         "de `killswitch.py` e `/api/version`. Ver [ADR-0006](../arquitetura/decisoes/"
         "ADR-0006-kill-switch-fora-do-banco.md).\n"]

    por_arquivo = defaultdict(list)
    for r in rotas:
        por_arquivo[r["arquivo"]].append(r)

    for arquivo in sorted(por_arquivo):
        L.append(f"\n## `{arquivo}`\n")
        L.append("| Método | Rota | Acesso | O que faz |")
        L.append("|---|---|---|---|")
        for r in sorted(por_arquivo[arquivo], key=lambda x: x["path"]):
            metodos = " ".join(f"`{m}`" for m in r["metodos"])
            desc = _md_escape(r["descricao"])
            L.append(f"| {metodos} | `{r['path']}` | {_rotulo_acesso(r)} | {desc} |")

    return "\n".join(L) + "\n"


def render_permissoes(rotas):
    L = [CABECALHO, "# Permissões\n",
         "## Os quatro papéis\n",
         "| Papel | Alcance |", "|---|---|",
         "| `admin` | tudo, incluindo gestão de usuários e exclusões |",
         "| `gestor` | escrita em todos os módulos; sem gestão de usuários |",
         "| `tecnico` | escrita no dia a dia; sem exclusão nem custos |",
         "| `leitura` | consulta apenas |",
         "",
         "Papel é global (coluna `users.role`). **Área** é ortogonal a ele "
         "(coluna `users.areas`): dá ou nega acesso a um recorte da empresa "
         "— ver [`areas.py`](../../areas.py). `admin` ignora a checagem de área.\n",
         "## Matriz papel × rota\n",
         "Contagem de rotas que cada papel alcança, por arquivo. "
         "Rotas `públicas` e `autenticadas` contam para todos os papéis.\n"]

    por_arquivo = defaultdict(lambda: defaultdict(int))
    for r in rotas:
        for papel in PAPEIS:
            if r["acesso"] in ("publico", "autenticado") or papel in r["papeis"]:
                por_arquivo[r["arquivo"]][papel] += 1

    L.append("| Arquivo | " + " | ".join(f"`{p}`" for p in PAPEIS) + " | total |")
    L.append("|---|" + "---|" * (len(PAPEIS) + 1))
    for arquivo in sorted(por_arquivo):
        total = len([r for r in rotas if r["arquivo"] == arquivo])
        celulas = " | ".join(str(por_arquivo[arquivo][p]) for p in PAPEIS)
        L.append(f"| `{arquivo}` | {celulas} | {total} |")

    abertas = [x for x in rotas if x["acesso"] == "publico" and x["api"]]
    cascas = [x for x in rotas if x["acesso"] == "publico" and not x["api"]]

    L.append("\n## Superfície pública\n")
    L.append(f"As **{len(abertas)}** rotas de API alcançáveis sem token. Esta lista "
             "deve ser curta e conhecida — cada linha é superfície de ataque, e é "
             "por causa dela que existe [`ratelimit.py`](../../ratelimit.py).\n")
    L.append("| Método | Rota | Arquivo |")
    L.append("|---|---|---|")
    for r in abertas:
        metodos = " ".join(f"`{m}`" for m in r["metodos"])
        L.append(f"| {metodos} | `{r['path']}` | `{r['arquivo']}` |")

    L.append(f"\n### As {len(cascas)} rotas de página não entram na conta acima\n")
    L.append("Elas respondem sem token, mas só devolvem HTML vazio: o token é "
             "validado no front e **todo dado chega por `/api/*`**, que é gatilhado. "
             "Ver [ADR-0004](../arquitetura/decisoes/"
             "ADR-0004-pagina-casca-api-gatilhada.md).\n")

    L.append("\n## Rotas restritas a `admin`\n")
    L.append("| Método | Rota | Arquivo |")
    L.append("|---|---|---|")
    for r in [x for x in rotas if x["papeis"] == ["admin"]]:
        metodos = " ".join(f"`{m}`" for m in r["metodos"])
        L.append(f"| {metodos} | `{r['path']}` | `{r['arquivo']}` |")

    L.append("\n## Áreas e módulos\n")
    _preparar_ambiente()
    from areas import AREAS
    for area in AREAS:
        L.append(f"\n### {area['nome']} (`{area['slug']}`)\n")
        L.append(f"Home: `{area['home']}`\n")
        L.append("| Módulo | URL | Papel mínimo |")
        L.append("|---|---|---|")
        for mod in area.get("modulos", []):
            papel = mod.get("role") or "qualquer membro da área"
            L.append(f"| {mod['label']} | `{mod['url']}` | {papel} |")

    return "\n".join(L) + "\n"


def _mermaid_do_dominio(tabelas_dominio, nomes_globais):
    """Diagrama ER de um domínio; FKs para fora viram nota, não caixa."""
    nomes_locais = {t["tabela"] for t in tabelas_dominio}
    L = ["```mermaid", "erDiagram"]
    arestas, externas = [], []

    for t in tabelas_dominio:
        for col in t["colunas"]:
            for fk in col["fks"]:
                destino = fk.split(".")[0]
                if destino in nomes_locais:
                    arestas.append(f'    {destino} ||--o{{ {t["tabela"]} : "{col["nome"]}"')
                elif destino in nomes_globais:
                    externas.append((t["tabela"], col["nome"], destino))

    for t in tabelas_dominio:
        L.append(f"    {t['tabela']} {{")
        for col in t["colunas"]:
            marca = "PK" if col["pk"] else ("FK" if col["fks"] else "")
            tipo = re.sub(r"[^A-Za-z0-9]", "_", col["tipo"].split("(")[0]) or "campo"
            L.append(f"        {tipo} {col['nome']} {marca}".rstrip())
        L.append("    }")

    L.extend(sorted(set(arestas)))
    L.append("```")

    if externas:
        L.append("\n**Ligações para fora deste domínio:**\n")
        L.append("| Daqui | Coluna | Aponta para |")
        L.append("|---|---|---|")
        for origem, col, destino in sorted(set(externas)):
            L.append(f"| `{origem}` | `{col}` | `{destino}` |")

    return "\n".join(L)


def render_dados(tabelas):
    total_cols = sum(len(t["colunas"]) for t in tabelas)
    L = [CABECALHO, "# Dicionário de dados\n",
         f"**{len(tabelas)}** tabelas, **{total_cols}** colunas, "
         f"agrupadas em **{len(ORDEM_DOMINIOS)}** domínios.\n",
         "Os textos da coluna *Nota* são os comentários do próprio `models.py` — "
         "é onde o conhecimento de domínio deste sistema está escrito.\n",
         "> **O banco não guarda arquivo.** Colunas como `documentos.armazenamento` "
         "e `equipamento_arquivos.caminho` guardam o *caminho* para "
         "`\\\\loccus-srv03\\Projetos$\\Engenharia`. É a decisão que governa deploy, "
         "backup e acesso remoto — ver "
         "[ADR-0001](../arquitetura/decisoes/ADR-0001-caminho-no-banco.md).\n",
         "## Índice\n"]

    por_dominio = defaultdict(list)
    for t in tabelas:
        por_dominio[t["dominio"]].append(t)

    for dom in ORDEM_DOMINIOS:
        if dom in por_dominio:
            nomes = ", ".join(f"`{t['tabela']}`" for t in por_dominio[dom])
            L.append(f"- **{TITULOS_DOMINIO[dom]}** ({len(por_dominio[dom])}): {nomes}")

    nomes_globais = {t["tabela"] for t in tabelas}

    for dom in ORDEM_DOMINIOS:
        if dom not in por_dominio:
            continue
        L.append(f"\n---\n\n## {TITULOS_DOMINIO[dom]}\n")
        L.append(_mermaid_do_dominio(por_dominio[dom], nomes_globais))

        for t in por_dominio[dom]:
            L.append(f"\n### `{t['tabela']}`\n")
            L.append(f"Modelo `{t['classe']}`. {len(t['colunas'])} colunas.\n")
            L.append("| Coluna | Tipo | Nulo | Chave | Padrão | Nota |")
            L.append("|---|---|---|---|---|---|")
            for col in t["colunas"]:
                chaves = []
                if col["pk"]:
                    chaves.append("PK")
                for fk in col["fks"]:
                    chaves.append(f"FK → `{fk}`")
                if col["unico"]:
                    chaves.append("único")
                if col["indice"]:
                    chaves.append("índice")
                L.append(
                    f"| `{col['nome']}` | {col['tipo']} | "
                    f"{'sim' if col['nulo'] else 'não'} | {' '.join(chaves) or '—'} | "
                    f"{'`' + col['padrao'] + '`' if col['padrao'] else '—'} | "
                    f"{_md_escape(col['comentario'])} |"
                )

    return "\n".join(L) + "\n"


def render_config(variaveis):
    faltando = [v for v in variaveis if not v["documentada"]]
    L = [CABECALHO, "# Variáveis de ambiente\n",
         f"**{len(variaveis)}** variáveis lidas pelo código. "
         f"**{len(variaveis) - len(faltando)}** aparecem no `.env.example`.\n",
         "O `.env.example` é o arquivo para copiar e editar, e explica *por que* "
         "cada variável importante existe. Esta tabela é o inventário completo: "
         "existe para que nenhuma variável fique só no código.\n",
         "| Variável | Padrão | Onde é lida | No `.env.example` |",
         "|---|---|---|---|"]

    for v in variaveis:
        padrao = "**obrigatória**" if v["obrigatoria"] else f"`{v['padrao']}`"
        arquivos = ", ".join(f"`{a}`" for a in v["arquivos"][:3])
        if len(v["arquivos"]) > 3:
            arquivos += f" (+{len(v['arquivos']) - 3})"
        L.append(f"| `{v['nome']}` | {padrao} | {arquivos} | "
                 f"{'sim' if v['documentada'] else '**não**'} |")

    if faltando:
        L.append("\n## Lidas pelo código e ausentes do `.env.example`\n")
        L.append("Cada uma destas muda comportamento em produção sem estar no "
                 "arquivo que o operador copia. Não é erro por si só (várias são "
                 "chaves de teste), mas é a lista para revisar.\n")
        for v in faltando:
            padrao = "obrigatória" if v["obrigatoria"] else f"padrão `{v['padrao']}`"
            L.append(f"- `{v['nome']}` — {padrao}, em {', '.join(f'`{a}`' for a in v['arquivos'])}")

    return "\n".join(L) + "\n"


# ── ESCRITA ───────────────────────────────────────────────────────────────────

def gerar():
    rotas = coletar_rotas()
    tabelas = coletar_tabelas()
    variaveis = coletar_env()
    return {
        "api.md": render_api(rotas),
        "dados.md": render_dados(tabelas),
        "permissoes.md": render_permissoes(rotas),
        "config.md": render_config(variaveis),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="não escreve; sai com 1 se a documentação estiver defasada")
    args = ap.parse_args()

    arquivos = gerar()
    os.makedirs(DESTINO, exist_ok=True)

    defasados = []
    for nome, conteudo in arquivos.items():
        caminho = os.path.join(DESTINO, nome)
        atual = None
        if os.path.exists(caminho):
            with open(caminho, encoding="utf-8", newline="") as fh:
                atual = fh.read()
        if atual == conteudo:
            continue
        if args.check:
            defasados.append(nome)
        else:
            with open(caminho, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(conteudo)
            print(f"escrito  docs/referencia/{nome}")

    if args.check:
        if defasados:
            print("Documentação de referência defasada: " + ", ".join(defasados))
            print("Rode: python scripts/gerar_docs.py")
            return 1
        print("Documentação de referência em dia.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
