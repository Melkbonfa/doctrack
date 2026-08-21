"""
arquivos_store.py — Guarda os arquivos que o usuário envia para dentro do DocTrack.

O arquivo hospedado aqui é uma **cópia de conveniência**: o mestre continua no
servidor da engenharia (ver `caminhos.py`) e a Qualidade mantém o sistema dela.
Este módulo só responde por bytes em disco — quem manda em permissão, versão e
auditoria é a camada de rotas.

Endereçamento por conteúdo
--------------------------
O nome do arquivo em disco é o SHA-256 do próprio conteúdo, distribuído em dois
níveis (`ab/cd/abcd...`). Três problemas somem de uma vez:

  * **Path traversal deixa de existir** — nenhum trecho do caminho vem da
    requisição, então não há o que sanear. Contraste com `servir_arquivo`, que
    precisa de allowlist justamente porque o caminho vem do cliente.
  * **Colisão de nome** — dois "Manual.pdf" diferentes não brigam.
  * **Duplicata** — o mesmo conteúdo enviado duas vezes ocupa um blob só. Isso
    não é hipotético: o share já tem `IT - Extracta 16 V1.0.docx` (56 MB) em
    dois lugares.

Como o blob é imutável e compartilhado, `remover()` só apaga quando ninguém mais
aponta para ele — quem sabe disso é o banco, então a decisão chega de fora.
"""
import hashlib
import os
import sys

# ── Pasta de dados (compatível com o executável congelado) ────────────────────
# Mesma lógica do RUN_DIR em servidor.py, repetida aqui de propósito: este módulo
# não importa o servidor (seria circular) e precisa valer sozinho nos testes.
if getattr(sys, "frozen", False):
    _RUN_DIR = os.path.dirname(sys.executable)
else:
    _RUN_DIR = os.path.dirname(os.path.abspath(__file__))

# ATENÇÃO (deploy): esta pasta NÃO pode ficar dentro de `_internal\`. O
# DEPLOY_SERVIDOR.md manda substituir `_internal\` a cada atualização — os
# arquivos enviados sumiriam na primeira. Fica ao lado do .env e do banco.
RAIZ = os.environ.get("DOCTRACK_ARQUIVOS") or os.path.join(_RUN_DIR, "arquivos")

# Teto de upload. Antes disto o app não tinha MAX_CONTENT_LENGTH nenhum: sem
# limite, encher o disco do servidor é um POST. O maior documento real medido no
# share tem 56 MB (uma IT cheia de imagem), daí a folga até 80.
MAX_MB    = int(os.environ.get("DOCTRACK_UPLOAD_MAX_MB", "80"))
MAX_BYTES = MAX_MB * 1024 * 1024

# Allowlist do que pode entrar — é exatamente o que existe no share hoje
# (486 arquivos de escritório medidos nas 33 árvores de equipamento).
EXT_PERMITIDAS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx",
                  ".png", ".jpg", ".jpeg"}

# ── Binários do repositório de software/firmware ─────────────────────────────
# Allowlist SEPARADA de propósito: o instalador e a imagem de firmware entram
# só pela rota do repositório do equipamento. Se `.exe` e `.zip` entrassem em
# EXT_PERMITIDAS, qualquer documento passaria a aceitá-los, e o campo "Arquivos"
# de uma IT viraria porta de entrada de executável sem ninguém decidir isso.
#
# Nada aqui é visualizável (EXT_VISUALIZAVEL não os inclui) nem abre inline: a
# rota que os serve força `as_attachment` e mime genérico. O navegador nunca
# tenta interpretar o conteúdo; o arquivo só desce para o disco de quem baixou.
EXT_BINARIAS = {".zip", ".7z", ".bin", ".hex", ".img", ".dfu", ".exe", ".msi"}

# Teto próprio: instalador e firmware passam dos 80 MB com facilidade (o maior
# documento de escritório medido no share tem 56 MB; um instalador de software
# de equipamento passa de 300 MB sem esforço).
MAX_BIN_MB    = int(os.environ.get("DOCTRACK_UPLOAD_BIN_MAX_MB", "500"))
MAX_BIN_BYTES = MAX_BIN_MB * 1024 * 1024

# O que o navegador abre sem baixar. `.docx` entra porque o front o renderiza
# client-side (docx.renderAsync), não porque o navegador saiba abri-lo.
EXT_INLINE       = {".pdf", ".png", ".jpg", ".jpeg"}
EXT_VISUALIZAVEL = EXT_INLINE | {".docx"}

_MIMES = {
    ".pdf":  "application/pdf",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".doc":  "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls":  "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_CHUNK = 1024 * 1024


class ArquivoGrandeDemais(Exception):
    """Passou do teto da chamada durante a gravação (o parcial já foi descartado)."""


class ExtensaoNaoPermitida(Exception):
    """Extensão fora de EXT_PERMITIDAS."""


def ext_de(nome):
    """Extensão em minúsculas, com ponto. `''` quando não há."""
    return os.path.splitext(str(nome or ""))[1].lower()


def extensao_ok(nome, permitidas=None):
    """True se a extensão está na allowlist. `permitidas` troca o conjunto —
    é assim que a rota do repositório aceita binário sem afrouxar as demais."""
    return ext_de(nome) in (permitidas if permitidas is not None else EXT_PERMITIDAS)


def mime_de(nome):
    return _MIMES.get(ext_de(nome), "application/octet-stream")


def pode_visualizar(nome):
    return ext_de(nome) in EXT_VISUALIZAVEL


def abre_inline(nome):
    """True quando o próprio navegador exibe (PDF/imagem) — .docx não conta."""
    return ext_de(nome) in EXT_INLINE


def caminho_de(sha):
    """Caminho absoluto do blob. Lê RAIZ do módulo para os testes poderem trocá-la."""
    sha = str(sha or "").lower()
    return os.path.join(RAIZ, sha[:2], sha[2:4], sha)


def existe(sha):
    return bool(sha) and os.path.isfile(caminho_de(sha))


def guardar(stream, nome="", permitidas=None, limite=None):
    """Grava o conteúdo de `stream` e devolve `(sha256, tamanho)`.

    Valida a extensão de `nome` antes de tocar no disco. Escreve num `.tmp` e só
    então move para o nome definitivo: um upload interrompido no meio nunca deixa
    para trás um blob truncado com nome válido — que seria indistinguível de um
    arquivo íntegro, já que o nome é o hash do conteúdo esperado.

    Se o blob já existir (mesmo conteúdo enviado antes), não regrava.

    `permitidas` e `limite` sobrescrevem allowlist e teto por chamada: cada rota
    diz o que aceita, em vez de existir um único teto global que a rota mais
    permissiva acabaria ditando para todas.
    """
    if nome and not extensao_ok(nome, permitidas):
        raise ExtensaoNaoPermitida(ext_de(nome))
    teto = MAX_BYTES if limite is None else int(limite)

    tmp_dir = os.path.join(RAIZ, "_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp = os.path.join(tmp_dir, f"up-{os.getpid()}-{id(stream):x}.tmp")

    h = hashlib.sha256()
    tamanho = 0
    try:
        with open(tmp, "wb") as saida:
            while True:
                pedaco = stream.read(_CHUNK)
                if not pedaco:
                    break
                tamanho += len(pedaco)
                # Checa durante a gravação, e não só pelo MAX_CONTENT_LENGTH do
                # Flask: o header Content-Length é do cliente, o que chegou é fato.
                if tamanho > teto:
                    raise ArquivoGrandeDemais(tamanho)
                h.update(pedaco)
                saida.write(pedaco)

        sha = h.hexdigest()
        destino = caminho_de(sha)
        if os.path.isfile(destino):
            os.remove(tmp)          # dedup: o conteúdo já está guardado
        else:
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            os.replace(tmp, destino)
        return sha, tamanho
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def remover(sha):
    """Apaga o blob. Devolve True se apagou.

    Só chame depois de confirmar no banco que nenhuma outra linha referencia este
    SHA — o blob é compartilhado por dedup. Falha de I/O não levanta: em Windows
    o arquivo pode estar aberto por um download em curso, e nesse caso o certo é
    deixar o blob órfão para trás em vez de derrubar a operação do usuário.
    """
    if not sha:
        return False
    try:
        os.remove(caminho_de(sha))
        return True
    except OSError:
        return False
