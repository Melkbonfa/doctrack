"""
diagnostico.py — Confronto entre o que o cadastro afirma e o que existe de fato.

Substitui o `agente_scanner`, que nasceu quando o arquivo só podia estar na rede
e verificava uma única coisa: se a string de caminho batia com algum diretório.

Hoje um documento tem DUAS fontes de arquivo, independentes entre si:

  * a **pasta de rede** (`armazenamento_efetivo`) — onde mora o mestre;
  * a **cópia hospedada na plataforma** (`DocumentoArquivo` → blob no
    `arquivos_store`), que não tem caminho de rede nenhum.

Ter uma das duas basta. Por isso nada aqui é avaliado isoladamente: "sem caminho
de rede" só vira apontamento quando também não há cópia hospedada — senão todo
documento que passou a viver na plataforma apareceria como problema.

O que se verifica, e por quê:

  PASTA_AUSENTE      o caminho cadastrado não existe mais (pasta movida/renomeada)
  PASTA_VAZIA        a pasta existe e não tem nada dentro — "Homologado" no
                     sistema não prova que alguém depositou o arquivo lá
  ARQUIVO_SUMIDO     o banco referencia um blob que não está mais em disco. É o
                     risco que o `arquivos_store` documenta: se a pasta de
                     arquivos cair dentro de `_internal\\`, um deploy a apaga e
                     nada no sistema acusa
  FINALIZADO_SEM_ARQUIVO   consta como pronto e não há arquivo em fonte alguma
  SEM_ARQUIVO        ainda em elaboração e sem arquivo — esperado, fica em 'info'

Custo de I/O
------------
Cada consulta é um round-trip SMB. Duas precauções, porque a herança de pasta faz
os 9 documentos de um equipamento compartilharem o MESMO caminho:

  1. cada caminho distinto é consultado uma única vez (`_SondaDeRede`);
  2. há um orçamento de tempo. Estourado, para de tocar na rede e devolve
     `rede_indisponivel` — com o share fora do ar, reportar "300 pastas sumiram"
     é pior do que não reportar nada.

Os apontamentos vêm AGRUPADOS pela causa (um caminho que sumiu é uma linha, não
uma por documento afetado): sem isso, um punhado de equipamentos quebrados enche
o relatório e esconde todo o resto.
"""
import os
import time
from datetime import datetime

import arquivos_store
import caminhos

# Orçamento total das consultas à rede, em segundos. Um `os.path.exists` sobre
# share indisponível bloqueia em timeout SMB (segundos), e são centenas de
# caminhos: sem teto, a rota fica pendurada até o proxy derrubar a conexão.
ORCAMENTO_S = float(os.environ.get("DOCTRACK_DIAG_TIMEOUT", "20"))

# A partir de quantos caminhos distintos uma falha de 100% passa a ser lida como
# "o share caiu" em vez de "as pastas sumiram". Abaixo disso a amostra é pequena
# demais para a inferência.
_MIN_AMOSTRA_REDE = 3

# Lixo que o Windows/macOS deixa numa pasta e que não conta como conteúdo.
_IGNORADOS = {"thumbs.db", "desktop.ini", ".ds_store"}

_ORDEM_SEVERIDADE = {"error": 0, "warning": 1, "info": 2}


class _SondaDeRede:
    """Consulta o filesystem com cache por caminho e orçamento de tempo.

    O cache não é otimização opcional: o caminho efetivo é herdado do grupo ou do
    equipamento, então dezenas de documentos apontam para o mesmo diretório e a
    versão anterior fazia até 4 `os.path.exists` por documento sobre ele.
    """

    def __init__(self, orcamento_s=ORCAMENTO_S):
        self._cache = {}
        self._fim = time.monotonic() + max(orcamento_s, 0.0)
        self.esgotou = False

    @property
    def consultados(self):
        return dict(self._cache)

    def estado(self, caminho):
        """'ok' | 'vazia' | 'ausente' | 'nao_verificado' (orçamento estourado)."""
        chave = caminhos.normalizar(caminho).lower()
        if chave in self._cache:
            return self._cache[chave]
        if self.esgotou or time.monotonic() >= self._fim:
            self.esgotou = True
            return "nao_verificado"

        estado = self._medir(caminho)
        self._cache[chave] = estado
        return estado

    @staticmethod
    def _medir(caminho):
        # resolver() tenta a UNC e a unidade mapeada: o processo pode enxergar
        # só uma das duas formas, e tratar isso como ausência era o falso
        # positivo mais comum do scanner antigo.
        real = caminhos.resolver(caminho)
        if not real:
            return "ausente"
        try:
            if not os.path.isdir(real):
                return "ok"      # caminho aponta para o arquivo em si, não à pasta
            for entrada in os.scandir(real):
                if entrada.is_dir():
                    return "ok"
                if entrada.name.lower() not in _IGNORADOS:
                    return "ok"
            return "vazia"
        except OSError:
            # Existe mas não abriu (permissão, share instável). Não é ausência —
            # acusar seria mandar o gestor procurar uma pasta que está lá.
            return "ok"


def _doc_resumo(doc):
    """Só o que a tela precisa para identificar e agir sobre o documento."""
    return {
        "id": doc.get("id"),
        "equipamento": doc.get("equipamento") or "—",
        "documento": doc.get("documento") or "",
        "tipo_doc_label": doc.get("tipo_doc_label") or doc.get("tipo_doc") or "—",
        "setor": doc.get("setor") or "",
        "status": doc.get("status") or "",
    }


class _Agrupador:
    """Junta documentos que sofrem do MESMO problema pela mesma causa."""

    def __init__(self):
        self._grupos = {}

    def add(self, tipo, chave, doc, **extra):
        g = self._grupos.get((tipo, chave))
        if g is None:
            g = self._grupos[(tipo, chave)] = {"tipo": tipo, "documentos": [], **extra}
        g["documentos"].append(_doc_resumo(doc))

    def issues(self):
        saida = []
        for g in self._grupos.values():
            g["qtd"] = len(g["documentos"])
            saida.append(g)
        saida.sort(key=lambda i: (_ORDEM_SEVERIDADE.get(i["severidade"], 9),
                                  -i["qtd"], i.get("caminho") or ""))
        return saida


def diagnosticar(documentos, orcamento_s=ORCAMENTO_S):
    """Relatório de inconsistências. `documentos` é uma lista de dicts:

        {id, equipamento, documento, tipo_doc_label, setor, status, concluido,
         caminho, arquivos: [{id, sha256, nome}]}

    Recebe dicts (e não models) de propósito: o confronto com o filesystem é
    testável sem banco, e a rota fica responsável só por montar a entrada.
    """
    sonda = _SondaDeRede(orcamento_s)
    grupos = _Agrupador()

    stats = {
        "documentos": len(documentos),
        "com_caminho": 0,
        "com_arquivo_hospedado": 0,
        "sem_nenhuma_fonte": 0,
        "pastas_verificadas": 0,
        "pastas_ausentes": 0,
        "pastas_vazias": 0,
        "arquivos_sumidos": 0,
        "documentos_afetados": 0,
        "ok": 0,
    }

    pendentes_de_pasta = []      # (doc, caminho, estado) — só emite depois
    afetados = set()
    blobs_sumidos = set()        # por sha: um blob perdido afeta vários documentos

    for doc in documentos:
        caminho = (doc.get("caminho") or "").strip()
        arquivos = doc.get("arquivos") or []
        if caminho:
            stats["com_caminho"] += 1
        if arquivos:
            stats["com_arquivo_hospedado"] += 1

        # 1. Blob referenciado no banco que não está mais em disco. Agrupa por
        # sha256 porque o store deduplica por conteúdo: um blob perdido derruba
        # todos os documentos que apontam para ele.
        for arq in arquivos:
            sha = (arq.get("sha256") or "").strip()
            if sha and not arquivos_store.existe(sha):
                grupos.add("ARQUIVO_SUMIDO", sha, doc,
                           severidade="error", titulo="Arquivo sumiu da plataforma",
                           detalhe=f"o envio '{arq.get('nome') or sha[:12]}' consta no "
                                   f"cadastro, mas o conteúdo não está mais em disco",
                           caminho="")
                blobs_sumidos.add(sha)
                afetados.add(doc.get("id"))

        # 2. Nenhuma das duas fontes. Documento em elaboração ainda não ter
        # arquivo é o curso normal das coisas — vira 'info', não alarme. O que
        # não fecha é o documento dado como pronto sem arquivo em lugar algum.
        if not caminho and not arquivos:
            stats["sem_nenhuma_fonte"] += 1
            afetados.add(doc.get("id"))
            if doc.get("concluido"):
                grupos.add("FINALIZADO_SEM_ARQUIVO", doc.get("equipamento") or "", doc,
                           severidade="error", titulo="Finalizado sem arquivo",
                           detalhe="consta como concluído, mas não há caminho de rede "
                                   "nem cópia hospedada",
                           caminho="")
            else:
                grupos.add("SEM_ARQUIVO", doc.get("equipamento") or "", doc,
                           severidade="info", titulo="Ainda sem arquivo",
                           detalhe="em elaboração, sem caminho de rede nem cópia hospedada",
                           caminho="")
            continue

        # 3. Estado da pasta de rede. Guardado para emitir depois: se a rede
        # estiver fora, estes apontamentos não valem nada.
        if caminho:
            estado = sonda.estado(caminho)
            if estado in ("ausente", "vazia"):
                pendentes_de_pasta.append((doc, caminho, estado))

    medidos = sonda.consultados
    stats["pastas_verificadas"] = len(medidos)
    ausentes = sum(1 for e in medidos.values() if e == "ausente")

    # Todos os caminhos falharem é evidência de share fora do ar, não de centenas
    # de pastas apagadas no mesmo dia. Nesse caso a checagem de rede é descartada
    # inteira — a da plataforma continua valendo, que ela não depende do share.
    rede_indisponivel = bool(
        sonda.esgotou
        or (len(medidos) >= _MIN_AMOSTRA_REDE and ausentes == len(medidos))
    )

    if not rede_indisponivel:
        stats["pastas_ausentes"] = ausentes
        stats["pastas_vazias"] = sum(1 for e in medidos.values() if e == "vazia")
        for doc, caminho, estado in pendentes_de_pasta:
            exibicao = caminhos.para_exibicao(caminho)
            afetados.add(doc.get("id"))
            if estado == "ausente":
                grupos.add("PASTA_AUSENTE", caminhos.normalizar(caminho).lower(), doc,
                           severidade="error", titulo="Pasta não encontrada",
                           detalhe="o caminho cadastrado não existe mais na rede",
                           caminho=exibicao)
            else:
                grupos.add("PASTA_VAZIA", caminhos.normalizar(caminho).lower(), doc,
                           severidade="warning", titulo="Pasta vazia",
                           detalhe="a pasta existe, mas não há nenhum arquivo dentro",
                           caminho=exibicao)

    stats["arquivos_sumidos"] = len(blobs_sumidos)
    stats["documentos_afetados"] = len(afetados)
    stats["ok"] = stats["documentos"] - stats["documentos_afetados"]

    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "rede_indisponivel": rede_indisponivel,
        "orcamento_estourado": sonda.esgotou,
        "stats": stats,
        "issues": grupos.issues(),
    }
