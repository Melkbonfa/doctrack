"""
cadernos/onenote_assistente.py — Monta o assistente que a pessoa baixa na tela
"Importar do OneNote": UM arquivo .cmd que roda com dois cliques.

Por que um .cmd e não os .ps1: um .ps1 com dois cliques abre no Bloco de Notas,
e o PowerShell bloqueia script baixado. O .cmd chama o PowerShell com
`-ExecutionPolicy Bypass` só para ele mesmo. E por que um arquivo só: dois
arquivos num zip fazem a pessoa rodar de dentro do zip, sem o segundo arquivo.

O arquivo é um "híbrido": as primeiras linhas são lidas pelo cmd (que pula a
linha `<# :`, que para ele é um rótulo), e para o PowerShell o arquivo inteiro é
um script válido, onde `<# ... #>` é um comentário. O cmd copia o próprio
arquivo para um .ps1 temporário (UTF-8 com BOM) e o roda com `-File`. Não usa
`Invoke-Expression`: "PowerShell + iex" é o padrão que antivírus corporativo
bloqueia. O conteúdo vem dos scripts do repositório, na hora do download — a
fonte é uma só:

    scripts/onenote/extrair_onenote.ps1    → vira a função Extrair-OneNote
    scripts/onenote/assistente_onenote.ps1 → o menu, a extração e o .zip
"""
import os
from datetime import datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRATOR = os.path.join(RAIZ, "scripts", "onenote", "extrair_onenote.ps1")
ASSISTENTE = os.path.join(RAIZ, "scripts", "onenote", "assistente_onenote.ps1")
NOME_ARQUIVO = "Exportar caderno do OneNote (DocTrack).cmd"

# Só ASCII aqui: o cmd lê estas linhas na página de código do console.
CABECALHO = [
    "<# :",
    "@echo off",
    "setlocal",
    "title DocTrack - exportar caderno do OneNote",
    'set "DT_SCRIPT=%~f0"',
    'powershell -NoProfile -ExecutionPolicy Bypass -Command '
    '"$p=Join-Path $env:TEMP (\'doctrack_onenote_\'+[guid]::NewGuid().ToString(\'N\')+\'.ps1\'); '
    '[IO.File]::WriteAllText($p,[IO.File]::ReadAllText($env:DT_SCRIPT,[Text.Encoding]::UTF8),'
    '(New-Object Text.UTF8Encoding $true)); try { & $p } finally { Remove-Item -LiteralPath $p -ErrorAction SilentlyContinue }"',
    "echo.",
    "pause",
    "exit /b",
    "#>",
]


def _ler(caminho):
    with open(caminho, encoding="utf-8-sig") as fh:
        return fh.read()


def montar(agora=None):
    """Bytes do .cmd (UTF-8 sem BOM — o BOM quebraria a primeira linha do cmd;
    o PowerShell lê o arquivo explicitamente como UTF-8)."""
    agora = agora or datetime.now()
    linhas = CABECALHO + [
        f"# Gerado pelo DocTrack em {agora:%d/%m/%Y %H:%M}. Fonte: scripts/onenote/ no repositório.",
        "function Extrair-OneNote {",
        _ler(EXTRATOR),
        "}",
        _ler(ASSISTENTE),
    ]
    texto = "\n".join(linhas)
    # O cmd exige CRLF para ler as linhas com segurança.
    texto = texto.replace("\r\n", "\n").replace("\n", "\r\n")
    return texto.encode("utf-8")
