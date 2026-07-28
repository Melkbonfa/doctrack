"""
caminhos.py — Fonte única de verdade para caminhos do servidor de arquivos.

O MESMO diretório chega ao sistema em duas formas, conforme quem digitou:

    \\\\loccus-srv03\\Projetos$\\Engenharia\\Projetos\\...   (UNC)
    P:\\Engenharia\\Projetos\\...                          (unidade mapeada)

Mapeamento de unidade é por SESSÃO DE LOGON: o DocTrack rodando como serviço
Windows (LocalSystem) não enxerga `P:` nenhum, por mais que o Explorer do usuário
enxergue. Por isso a forma canônica — a que se grava no banco e a que a allowlist
compara — é a UNC, e a forma com letra existe só para exibir/copiar ao usuário,
que é quem tem o mapeamento.

Antes deste módulo cada ponto do sistema comparava a string crua: o caminho colado
como `P:\\...` batia num 403 "fora das pastas permitidas" quando DOCTRACK_FILE_ROOTS
listava só a UNC, e `os.path.exists` sobre a forma errada devolvia "arquivo não
encontrado" para pasta que existe. O banco acabou com os dois formatos misturados.

Uso típico:
    normalizar(entrada)          -> forma canônica para gravar/comparar
    validar(caminho, RAIZES)     -> canônico se dentro da allowlist, senão None
    resolver(caminho)            -> variante que EXISTE no disco (para I/O), ou None
    para_exibicao(caminho)       -> forma com letra, para o usuário copiar
"""
import ctypes
import ntpath
import os
import re

# Toda a álgebra de caminho usa ntpath explicitamente (e não os.path): a regra é
# do Windows independentemente de onde o processo roda, e assim os testes valem
# igual em qualquer plataforma. os.path fica só para tocar no filesystem.

_RE_LETRA = re.compile(r"^([A-Za-z]):(?=[\\/]|$)")
_RE_ALIAS_ENV = re.compile(r"^\s*([A-Za-z]):?\s*=\s*(.+?)\s*$")

# Raiz padrão quando DOCTRACK_FILE_ROOTS não está definido. Só a UNC: a forma com
# letra passa a ser coberta pela tradução de apelido, não por duplicar a raiz.
_RAIZ_PADRAO = r"\\loccus-srv03\Projetos$\Engenharia"


def _limpar(caminho):
    """Higieniza a entrada crua sem traduzir apelido.

    Absorve o que o usuário realmente cola: o "Copiar como caminho" do Explorer
    devolve o caminho entre aspas, o Ctrl+C da barra de endereço traz espaço nas
    pontas, e caminho vindo de planilha às vezes tem barra normal.
    """
    s = str(caminho or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    if not s:
        return ""
    # normpath já converte '/' → '\', colapsa separadores repetidos, resolve '.'
    # e '..' (é o que impede um `P:\Engenharia\..\..\Windows` furar a allowlist)
    # e preserva o '\\' inicial do UNC.
    s = ntpath.normpath(s)
    while len(s) > 3 and s.endswith("\\"):
        s = s[:-1]
    return s


def _aliases_do_env():
    """Apelidos declarados em DOCTRACK_PATH_ALIASES: 'P:=\\\\srv\\share;Z:=\\\\srv2\\outro'."""
    pares = []
    for item in os.environ.get("DOCTRACK_PATH_ALIASES", "").split(";"):
        m = _RE_ALIAS_ENV.match(item)
        if not m:
            continue
        unc = _limpar(m.group(2))
        if unc.startswith("\\\\"):
            pares.append((m.group(1).upper() + ":", unc))
    return pares


def _aliases_do_windows():
    """Apelidos que o Windows conhece NESTA sessão de logon.

    Usa WNetGetConnectionW em vez de parsear `net use`: a saída do `net use` é
    traduzida (esta máquina responde em português) e a posição das colunas varia,
    então o parse quebraria em outra instalação.

    Serve para desenvolvimento e para o app rodando na sessão do usuário. Num
    serviço Windows isto devolve lista vazia — daí a configuração ter prioridade.
    """
    if os.name != "nt":
        return []
    try:
        from ctypes import wintypes
        mpr = ctypes.WinDLL("mpr", use_last_error=True)
        mpr.WNetGetConnectionW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
                                           ctypes.POINTER(wintypes.DWORD)]
        mpr.WNetGetConnectionW.restype = wintypes.DWORD
    except Exception:
        return []

    pares = []
    for letra in "DEFGHIJKLMNOPQRSTUVWXYZ":
        try:
            buf = ctypes.create_unicode_buffer(1024)
            tam = wintypes.DWORD(1024)
            if mpr.WNetGetConnectionW(letra + ":", buf, ctypes.byref(tam)) != 0:
                continue
            unc = _limpar(buf.value)
            if unc.startswith("\\\\"):
                pares.append((letra + ":", unc))
        except Exception:
            continue
    return pares


def carregar_aliases():
    """Mapa letra → UNC. Configuração vence; autodetecção só complementa.

    A ordem importa: o serviço em produção precisa traduzir `P:` mesmo sem ter o
    mapeamento, e uma máquina de desenvolvimento precisa funcionar sem ninguém
    editar o .env. Um apelido declarado no .env nunca é sobrescrito pelo que a
    sessão local por acaso tiver montado naquela letra.
    """
    mapa = {}
    for letra, unc in _aliases_do_env():
        mapa[letra] = unc
    for letra, unc in _aliases_do_windows():
        mapa.setdefault(letra, unc)
    return mapa


ALIASES = {}
# UNC mais longo primeiro: com P:=\\srv\Projetos$ e Q:=\\srv\Projetos$\Eng, um
# caminho sob Eng deve exibir Q: (o apelido mais específico), não P:.
_ALIASES_POR_UNC = []


def definir_aliases(mapa):
    """Troca o mapa de apelidos em uso (mantém ALIASES e a ordem de busca em sincronia).

    Existe para os testes poderem fixar um mapa próprio: carregado do ambiente,
    o mapa depende de quais unidades a máquina tem montadas e a suíte passaria
    ou falharia conforme a estação.
    """
    global ALIASES, _ALIASES_POR_UNC
    ALIASES = {k.upper(): _limpar(v) for k, v in (mapa or {}).items()}
    _ALIASES_POR_UNC = sorted(ALIASES.items(), key=lambda kv: -len(kv[1]))


# Carregado uma vez no import: mapeamento de unidade não muda em runtime, e
# consultar a rede a cada request custaria um round-trip SMB por chamada.
definir_aliases(carregar_aliases())


def normalizar(caminho):
    """Forma canônica: UNC, sem aspas, sem barra final, com apelido traduzido.

    É idempotente — pode ser aplicada em cima do próprio resultado. Caminho que
    não casa com nenhum apelido (C:\\..., outro share) volta só higienizado.
    """
    s = _limpar(caminho)
    if not s:
        return ""
    m = _RE_LETRA.match(s)
    if m:
        unc = ALIASES.get(m.group(1).upper() + ":")
        if unc:
            return _limpar(unc + s[2:])
    return s


def para_exibicao(caminho):
    """Forma com letra mapeada — o que o usuário cola no Explorer dele.

    Devolver a UNC para o usuário funciona, mas expõe o nome do share
    administrativo e não é o que ele reconhece; a letra é a linguagem dele.
    """
    s = normalizar(caminho)
    if not s:
        return ""
    baixo = s.lower()
    for letra, unc in _ALIASES_POR_UNC:
        u = unc.lower()
        if baixo == u:
            return letra + "\\"
        if baixo.startswith(u + "\\"):
            return letra + s[len(unc):]
    return s


def variantes(caminho):
    """Formas a tentar no filesystem, da mais provável para a menos.

    O servidor pode enxergar só uma das duas: como serviço só a UNC resolve;
    numa sessão sem credencial no share, às vezes só a letra já autenticada
    resolve. Tentar as duas é o que evita o falso "pasta não encontrada".
    """
    canonico = normalizar(caminho)
    if not canonico:
        return ()
    exib = para_exibicao(canonico)
    return (canonico,) if exib == canonico else (canonico, exib)


def resolver(caminho):
    """Primeira variante que existe no disco, pronta para I/O. None se nenhuma."""
    for v in variantes(caminho):
        try:
            if os.path.exists(v):
                return v
        except OSError:
            continue
    return None


def existe(caminho):
    return resolver(caminho) is not None


def dentro_das_raizes(caminho, raizes):
    """Canônico se o caminho cai sob alguma raiz permitida, senão None.

    Comparação puramente textual sobre a forma canônica — sem realpath e sem
    commonpath. commonpath levantava ValueError entre `P:\\...` e `\\\\srv\\...`
    (drives diferentes), e o `except` transformava isso num 403 mudo; realpath
    disparava um round-trip SMB por request e travava segundos com o share fora
    do ar. Os '..' já foram eliminados por _limpar.
    """
    alvo = normalizar(caminho)
    if not alvo:
        return None
    baixo = alvo.lower()
    for raiz in (raizes or []):
        r = normalizar(raiz).lower()
        if not r:
            continue
        if baixo == r or baixo.startswith(r.rstrip("\\") + "\\"):
            return alvo
    return None


def validar(caminho, raizes):
    """Canônico se autorizado, None se fora da allowlist.

    Depois da checagem textual, confere o realpath como defesa contra junction
    ou symlink DENTRO do share apontando para fora dele. Falha de resolução
    (share indisponível, serviço sem o mapeamento) não invalida o caminho — foi
    justamente confiar cegamente no realpath que barrava a forma com letra.
    """
    alvo = dentro_das_raizes(caminho, raizes)
    if not alvo:
        return None
    try:
        real = normalizar(os.path.realpath(alvo))
    except OSError:
        return alvo
    if real.lower() != alvo.lower() and not dentro_das_raizes(real, raizes):
        return None
    return alvo


def carregar_raizes():
    """Raízes permitidas (DOCTRACK_FILE_ROOTS, separadas por ';'), canonizadas.

    Não é mais preciso listar a UNC e a letra da mesma pasta: normalizar()
    traduz o apelido antes da comparação, então uma entrada cobre as duas formas.
    """
    bruto = os.environ.get("DOCTRACK_FILE_ROOTS", _RAIZ_PADRAO)
    return [normalizar(r) for r in bruto.split(";") if r.strip()]


RAIZES_ARQUIVOS = carregar_raizes()
