"""
cadernos/importacao.py — Grava no banco um caderno extraído do OneNote.

Quem usa:
  * a tela "Importar do OneNote" (rotas /cadernos/api/importacoes): a pessoa
    envia o .zip que o assistente gerou na máquina dela, confere o resumo e
    confirma; a gravação roda como tarefa (ver tarefas.py);
  * scripts/importar_onenote.py, a linha de comando, com as travas de alvo de
    banco (esta máquina é o servidor de produção).

O pacote (formato `doctrack-onenote-1`, gerado por scripts/onenote/extrair_onenote.ps1):

    manifesto.json           caderno, seções (com grupos), páginas, contagens, avisos
    paginas/NNNN.xml         XML 2013 de cada página, imagens em base64 dentro
    originais/NNNN.pdf       PDF da página que tem desenho à mão
    anexos/NNNN_KK.ext       arquivos inseridos nas páginas (cópia do cache do OneNote)
    originais_onenote/...    os .one/.onetoc2 do caderno (quando a cópia era local)

**Reimportar é seguro.** Caderno, seções e páginas são achados pela chave de
origem (`importador_onenote.chave_origem`). Página que nunca foi editada no
DocTrack (versão 1) é atualizada; editada, é pulada e listada no relatório.
"""
import io
import json
import os
import re
import shutil
import tempfile
import time
import uuid as _uuid
import zipfile
from collections import Counter
from datetime import datetime

import arquivos_store
from models import db, User
from utils import norm

from . import core
from .importador_onenote import chave_origem, converter_pagina
from .models import Caderno, CadernoArquivo, CadernoNo, CadernoPagina, CadernoPaginaVersao
from .tarefas import ErroDaTarefa

FORMATO = "doctrack-onenote-1"
EXT_IMAGEM = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
EXT_ORIGINAIS = (".one", ".onetoc2", ".onepkg")
PASTA_ORIGINAIS = "OneNote original"

LIMITE_UPLOAD_MB = int(os.environ.get("DOCTRACK_IMPORT_MAX_MB", "1024"))
LIMITE_DESCOMPACTADO = 8 * 1024 ** 3        # zip-bomba: nada além disso no disco
LIMITE_ENTRADAS = 50000
PASTA_TEMP = os.path.join(tempfile.gettempdir(), "doctrack_importacoes")
VALIDADE_RECEBIDO_HORAS = 6


# ══════════════════════════════════════════════════════════════════════════════
# PACOTE
# ══════════════════════════════════════════════════════════════════════════════

def ler_manifesto(pasta):
    caminho = os.path.join(pasta, "manifesto.json")
    if not os.path.isfile(caminho):
        raise ErroDaTarefa("O pacote não tem manifesto.json. Gere o .zip com o assistente do DocTrack.")
    try:
        with open(caminho, encoding="utf-8-sig") as fh:
            man = json.load(fh)
    except (OSError, ValueError) as e:
        raise ErroDaTarefa(f"manifesto.json ilegível: {e}")
    if man.get("formato") != FORMATO:
        raise ErroDaTarefa(f"Pacote em formato desconhecido ({man.get('formato')!r}). "
                           "Baixe o assistente de novo pela tela de importação.")
    if not man.get("paginas"):
        raise ErroDaTarefa("O pacote não tem nenhuma página.")
    return man


def extrair_zip(caminho_zip, destino):
    """Descompacta com as travas de sempre (caminho fora da pasta, zip-bomba) e
    devolve a pasta onde está o manifesto (na raiz ou numa pasta única)."""
    if not zipfile.is_zipfile(caminho_zip):
        raise ErroDaTarefa("O arquivo enviado não é um .zip.")
    os.makedirs(destino, exist_ok=True)
    raiz_real = os.path.realpath(destino)
    with zipfile.ZipFile(caminho_zip) as zf:
        infos = zf.infolist()
        if len(infos) > LIMITE_ENTRADAS:
            raise ErroDaTarefa(f"O zip tem {len(infos)} itens; o limite é {LIMITE_ENTRADAS}.")
        if sum(i.file_size for i in infos) > LIMITE_DESCOMPACTADO:
            raise ErroDaTarefa("O zip descompactado passaria de 8 GB.")
        for info in infos:
            nome = info.filename.replace("\\", "/")
            if nome.startswith("/") or re.match(r"^[A-Za-z]:", nome) or ".." in nome.split("/"):
                raise ErroDaTarefa(f"Caminho inválido dentro do zip: {info.filename}")
            alvo = os.path.realpath(os.path.join(destino, *[p for p in nome.split("/") if p]))
            if not (alvo == raiz_real or alvo.startswith(raiz_real + os.sep)):
                raise ErroDaTarefa(f"Caminho inválido dentro do zip: {info.filename}")
            if info.is_dir():
                os.makedirs(alvo, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(alvo), exist_ok=True)
            with zf.open(info) as src, open(alvo, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
    if os.path.isfile(os.path.join(destino, "manifesto.json")):
        return destino
    filhos = [os.path.join(destino, x) for x in os.listdir(destino)]
    pastas = [x for x in filhos if os.path.isdir(x) and os.path.isfile(os.path.join(x, "manifesto.json"))]
    if len(pastas) == 1:
        return pastas[0]
    raise ErroDaTarefa("Não achei o manifesto.json no zip. Envie o .zip gerado pelo assistente, sem mudar nada dentro.")


def resumo_do_manifesto(man):
    c = man.get("contagens") or {}
    return {
        "caderno": (man.get("caderno") or {}).get("nome") or "",
        "secoes": len(man.get("secoes") or []),
        "paginas": len(man.get("paginas") or []),
        "imagens": int(c.get("imagens") or 0),
        "anexos": int(c.get("anexos") or 0),
        "paginas_com_tinta": int(c.get("tinta") or 0),
        "originais": int(c.get("originais") or 0),
        "extraido_em": man.get("extraido_em") or "",
        "maquina": man.get("maquina") or "",
        "avisos": list(man.get("avisos") or []),
        "aberto_do_sharepoint": str((man.get("caderno") or {}).get("caminho") or "").lower().startswith("http"),
    }


def chave_caderno(man):
    return chave_origem("caderno", man["caderno"]["nome"])


def caderno_existente(man):
    return Caderno.query.filter_by(origem_ref=chave_caderno(man), excluido_em=None).first()


def converter(pasta, man, progresso=None):
    convertidas = []
    total = len(man["paginas"])
    for i, pg in enumerate(man["paginas"], 1):
        if progresso:
            progresso(i - 1, total, f"Convertendo página {i} de {total}: {pg.get('nome') or ''}")
        caminho = os.path.join(pasta, "paginas", pg["arquivo"])
        with open(caminho, encoding="utf-8") as fh:
            convertidas.append((pg, converter_pagina(fh.read())))
    return convertidas


def contar(man, convertidas):
    c = Counter()
    avisos = Counter()
    for pg, r in convertidas:
        c["paginas"] += 1
        c["registros_de_teste"] += r.tipo == "registro_teste"
        c["imagens"] += len(r.imagens)
        c["mb_imagens"] += sum(len(i.dados) for i in r.imagens)
        c["anexos"] += len(r.anexos)
        c["tabelas"] += r.tabelas
        c["links_externos"] += r.links_externos
        c["paginas_com_tinta"] += bool(r.tinta)
        for a in r.avisos:
            avisos[a] += 1
    c["mb_imagens"] = round(c["mb_imagens"] / 1048576, 1)
    autores = sorted({a for _, r in convertidas for a in r.autores})
    lista = [f"{a} ({n}x)" if n > 1 else a for a, n in avisos.most_common()]
    lista += [f"Extração: {a}" for a in man.get("avisos") or []]
    return dict(c), autores, lista


# ══════════════════════════════════════════════════════════════════════════════
# GRAVAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def gravar(pasta, man, convertidas, *, dono, area, nome=None, originais=None, progresso=None,
           log=lambda msg: None):
    """Grava caderno, seções, páginas, imagens, anexos e originais. Devolve o
    relatório (dict). Faz commit a cada 10 páginas e no fim."""
    from sqlalchemy import inspect
    if "caderno_paginas" not in inspect(db.engine).get_table_names():
        raise ErroDaTarefa("As tabelas do módulo Cadernos não existem neste banco.")
    contagens, autores, avisos = contar(man, convertidas)

    por_nome = {norm(u.nome): u for u in User.query.filter_by(ativo=True).all()}
    mapa_autores = {n: por_nome.get(norm(n)) for n in autores}
    for n, u in mapa_autores.items():
        log(f"  autor {n!r} → {u.email if u else '(sem usuário: fica como texto)'}")

    ref_cad = chave_caderno(man)
    cad = Caderno.query.filter_by(origem_ref=ref_cad, excluido_em=None).first()
    cor = (man["caderno"].get("cor") or "")
    novo_caderno = cad is None
    if novo_caderno:
        cad = Caderno(uuid=str(_uuid.uuid4()), nome=(nome or man["caderno"]["nome"])[:200], area=area,
                      acesso_area="editor", cor=cor if cor.startswith("#") else "#a855f7",
                      modelo="onenote", descricao=f"Importado do OneNote em {datetime.now():%d/%m/%Y}.",
                      dono_id=dono.id, origem_ref=ref_cad)
        db.session.add(cad)
        db.session.flush()
        log(f"Caderno criado: {cad.nome}")
    else:
        log(f"Caderno já existia: {cad.nome} (reimportação)")

    # Seções (e grupos), na ordem do OneNote.
    secoes = {}
    for ordem, s in enumerate(man["secoes"]):
        parent = None
        caminho = []
        for g in s.get("grupos") or []:
            caminho.append(g)
            ref_g = chave_origem(ref_cad, "grupo", *caminho)
            grupo = CadernoNo.query.filter_by(origem_ref=ref_g, caderno_id=cad.id).first()
            if grupo is None:
                grupo = CadernoNo(uuid=str(_uuid.uuid4()), caderno_id=cad.id, tipo="grupo", nome=g[:200],
                                  parent_id=parent.id if parent else None, ordem=ordem, origem_ref=ref_g)
                db.session.add(grupo)
                db.session.flush()
            parent = grupo
        ref_s = chave_origem(ref_cad, "secao", *caminho, s["nome"])
        no = CadernoNo.query.filter_by(origem_ref=ref_s, caderno_id=cad.id).first()
        tem_registro = any(r.tipo == "registro_teste" for pg, r in convertidas if pg["secao"] == s["indice"])
        if no is None:
            no = CadernoNo(uuid=str(_uuid.uuid4()), caderno_id=cad.id, tipo="secao", nome=s["nome"][:200],
                           parent_id=parent.id if parent else None, ordem=ordem,
                           cor=s["cor"] if str(s.get("cor") or "").startswith("#") else "",
                           tipo_pagina_padrao="registro_teste" if tem_registro else "nota",
                           origem_ref=ref_s)
            db.session.add(no)
            db.session.flush()
        secoes[s["indice"]] = no

    def guardar_bytes(dados, nome_arq, permitidas, limite):
        return arquivos_store.guardar(io.BytesIO(dados), nome_arq, permitidas=permitidas, limite=limite)

    def anexar_arquivo(caminho, escopo, escopo_id, nome_arq, origem, *, uuid_=None, pasta="",
                       exportar=False):
        with open(caminho, "rb") as fh:
            sha, tamanho = arquivos_store.guardar(fh, nome_arq, permitidas=arquivos_store.QUALQUER,
                                                  limite=arquivos_store.MAX_BIN_BYTES)
        novo = uuid_ or str(_uuid.uuid4())
        ext = arquivos_store.ext_de(nome_arq)
        db.session.add(CadernoArquivo(
            uuid=novo, grupo=novo, caderno_id=cad.id, escopo=escopo, escopo_id=escopo_id,
            pasta=pasta[:120], nome_original=nome_arq[:300], ext=ext,
            mime="application/pdf" if ext == ".pdf" else "application/octet-stream",
            sha256=sha, tamanho=tamanho, incluir_exportacao=exportar, origem=origem,
            enviado_por=dono.id))
        return novo

    criadas = atualizadas = 0
    puladas = []
    anexos_ok = anexos_faltando = 0
    por_secao = {}
    total = len(convertidas)
    for k, (pg, r) in enumerate(convertidas, 1):
        if progresso:
            progresso(k - 1, total, f"Gravando página {k} de {total}: {r.titulo}")
        secao = secoes[pg["secao"]]
        ref_p = chave_origem(ref_cad, secao.nome, pg["nome"], pg.get("data") or "")
        p = CadernoPagina.query.filter_by(origem_ref=ref_p, caderno_id=cad.id).first()
        if p is not None and p.versao != 1:
            puladas.append(r.titulo)
            por_secao.setdefault(secao.id, []).append((p, pg))
            continue
        autor = mapa_autores.get(r.autores[0]) if r.autores else None
        if p is None:
            p = CadernoPagina(uuid=str(_uuid.uuid4()), secao_id=secao.id, caderno_id=cad.id, origem_ref=ref_p)
            db.session.add(p)
            criadas += 1
        else:
            # Reimportação de página nunca editada: troca conteúdo, imagens e anexos.
            CadernoArquivo.query.filter(CadernoArquivo.escopo == "pagina", CadernoArquivo.escopo_id == p.id,
                                        CadernoArquivo.origem.in_(("onenote", "onenote_pdf"))).delete(
                synchronize_session=False)
            CadernoPaginaVersao.query.filter_by(pagina_id=p.id).delete()
            atualizadas += 1

        # Anexos do OneNote: o arquivo vem de anexos/ do pacote, ligado pelo cache.
        html_pag = r.html
        entradas = {}
        for e in pg.get("anexos") or []:
            if e.get("cache"):
                entradas[e["cache"].lower()] = e
        db.session.flush()
        pendentes_anexos = []
        for a in r.anexos:
            e = entradas.get((a.cache or "").lower())
            caminho = os.path.join(pasta, "anexos", e["arquivo"]) if e else None
            if caminho and os.path.isfile(caminho):
                pendentes_anexos.append((caminho, a))
                anexos_ok += 1
            else:
                anexos_faltando += 1
                html_pag = re.sub(rf'<a data-arquivo="{a.uuid}">(.*?)</a>',
                                  r'\1 <mark class="marker-silver">[anexo do OneNote que não veio no pacote]</mark>',
                                  html_pag)
                avisos.append(f"Anexo '{a.nome}' da página '{r.titulo}' não veio no pacote.")

        p.tipo, p.titulo, p.conteudo_html = r.tipo, r.titulo, html_pag
        p.ficha_json = json.dumps(r.ficha) if r.ficha else ""
        p.texto_busca = core.montar_texto_busca(r.titulo, html_pag, r.ficha) + " " + norm(r.texto_ocr)
        p.data_pagina = r.data_pagina or r.criado
        p.criado_em = r.criado or r.data_pagina or datetime.now()
        p.atualizado_em = r.modificado or p.criado_em
        p.criado_por = autor.id if autor else None
        p.atualizado_por = autor.id if autor else None
        p.recolhida = bool(pg.get("recolhida"))
        p.origem_autores = ", ".join(r.autores)
        p.versao = 1
        db.session.flush()

        for n, img in enumerate(r.imagens, 1):
            sha, tamanho = guardar_bytes(img.dados, f"imagem{img.ext}", EXT_IMAGEM, arquivos_store.MAX_BYTES)
            db.session.add(CadernoArquivo(
                uuid=img.uuid, grupo=img.uuid, caderno_id=cad.id, escopo="pagina", escopo_id=p.id,
                nome_original=f"imagem-{n:02d}{img.ext}", ext=img.ext, mime=img.mime, sha256=sha,
                tamanho=tamanho, embutido=True, ocr_texto=img.ocr, origem="onenote", enviado_por=dono.id))
        for caminho, a in pendentes_anexos:
            anexar_arquivo(caminho, "pagina", p.id, a.nome, "onenote", uuid_=a.uuid, exportar=True)
        if pg.get("pdf"):
            caminho = os.path.join(pasta, "originais", pg["pdf"])
            if os.path.isfile(caminho):
                anexar_arquivo(caminho, "pagina", p.id, f"{r.titulo[:120]} (original do OneNote).pdf",
                               "onenote_pdf", pasta=PASTA_ORIGINAIS)
        db.session.add(CadernoPaginaVersao(pagina_id=p.id, versao=1, titulo=p.titulo,
                                           conteudo_html=p.conteudo_html, ficha_json=p.ficha_json,
                                           motivo="importacao"))
        por_secao.setdefault(secao.id, []).append((p, pg))
        if (criadas + atualizadas) % 10 == 0:
            db.session.commit()

    # Ordem e nível de cada seção, com as invariantes do core.
    for itens in por_secao.values():
        niveis = core.normalizar_niveis([pg.get("nivel") or 1 for _, pg in itens])
        for ordem, ((p, _), nivel) in enumerate(zip(itens, niveis)):
            p.ordem, p.nivel = ordem, nivel

    # Os .one/.onetoc2: guardados no caderno, fora da exportação.
    n_originais = 0
    if originais and os.path.isdir(originais):
        ja = {(x.pasta, x.nome_original) for x in CadernoArquivo.query.filter_by(
            caderno_id=cad.id, escopo="caderno", excluido_em=None).all()}
        for dirpath, _, arquivos in os.walk(originais):
            rel = os.path.relpath(dirpath, originais)
            sub = PASTA_ORIGINAIS if rel in (".", "") else f"{PASTA_ORIGINAIS}/{rel.replace(os.sep, '/')}"
            if "OneNote_RecycleBin" in rel:
                continue
            for nome_arq in sorted(arquivos):
                if nome_arq.lower().endswith(EXT_ORIGINAIS) and (sub[:120], nome_arq) not in ja:
                    anexar_arquivo(os.path.join(dirpath, nome_arq), "caderno", cad.id, nome_arq, "onenote",
                                   pasta=sub)
                    n_originais += 1

    db.session.commit()
    contagens["anexos_importados"] = anexos_ok
    contagens["anexos_faltando"] = anexos_faltando
    contagens["originais_onenote"] = n_originais
    return {
        "quando": datetime.now().isoformat(timespec="seconds"),
        "caderno": {"uuid": cad.uuid, "nome": cad.nome, "novo": novo_caderno},
        "contagens": contagens,
        "criadas": criadas,
        "atualizadas": atualizadas,
        "puladas_editadas_no_doctrack": puladas,
        "autores": {k: (v.nome if v else None) for k, v in mapa_autores.items()},
        "avisos": avisos,
    }


# ══════════════════════════════════════════════════════════════════════════════
# PELA TELA: pacote recebido → confirmação → tarefa
# ══════════════════════════════════════════════════════════════════════════════

_recebidos = {}          # id → {"user_id", "area", "pasta", "raiz", "quando"}


def _limpar_recebidos(agora=None):
    agora = agora or time.time()
    for k in [k for k, v in _recebidos.items() if agora - v["quando"] > VALIDADE_RECEBIDO_HORAS * 3600]:
        shutil.rmtree(_recebidos.pop(k)["pasta"], ignore_errors=True)
    # Sobras de um serviço que reiniciou no meio.
    if os.path.isdir(PASTA_TEMP):
        vivos = {v["pasta"] for v in _recebidos.values()}
        for nome in os.listdir(PASTA_TEMP):
            caminho = os.path.join(PASTA_TEMP, nome)
            try:
                if caminho not in vivos and agora - os.path.getmtime(caminho) > VALIDADE_RECEBIDO_HORAS * 3600:
                    shutil.rmtree(caminho, ignore_errors=True)
            except OSError:
                pass


def receber(arquivo_enviado, user_id, area):
    """Guarda e valida o .zip enviado. Devolve (id, manifesto)."""
    os.makedirs(PASTA_TEMP, exist_ok=True)
    _limpar_recebidos()
    pasta = tempfile.mkdtemp(prefix="imp_", dir=PASTA_TEMP)
    try:
        caminho_zip = os.path.join(pasta, "pacote.zip")
        arquivo_enviado.save(caminho_zip)
        raiz = extrair_zip(caminho_zip, os.path.join(pasta, "pacote"))
        os.remove(caminho_zip)
        man = ler_manifesto(raiz)
    except Exception:
        shutil.rmtree(pasta, ignore_errors=True)
        raise
    id_ = str(_uuid.uuid4())
    _recebidos[id_] = {"user_id": user_id, "area": area, "pasta": pasta, "raiz": raiz, "quando": time.time()}
    return id_, man


def recebido(id_, user_id):
    r = _recebidos.get(id_)
    return r if r and r["user_id"] == user_id else None


def descartar(id_):
    r = _recebidos.pop(id_, None)
    if r:
        shutil.rmtree(r["pasta"], ignore_errors=True)


def executar(tarefa, id_recebido, user_id, nome=None, ip=""):
    """Corpo da tarefa de importação (fora da requisição: ver tarefas.py)."""
    from auth import log_action
    rec = _recebidos.get(id_recebido)
    if not rec:
        raise ErroDaTarefa("O pacote enviado expirou. Envie o .zip de novo.")
    try:
        dono = db.session.get(User, user_id)
        man = ler_manifesto(rec["raiz"])
        convertidas = converter(rec["raiz"], man, progresso=tarefa.progresso)
        originais = os.path.join(rec["raiz"], "originais_onenote")
        relatorio = gravar(rec["raiz"], man, convertidas, dono=dono, area=rec["area"], nome=nome,
                           originais=originais, progresso=tarefa.progresso)
        tarefa.progresso(len(convertidas), len(convertidas), "Pronto")
        r = relatorio
        log_action(dono.email, "IMPORT", entidade=f"caderno:{r['caderno']['nome']}", campo="onenote",
                   novo=f"{r['criadas']} criadas, {r['atualizadas']} atualizadas, "
                        f"{len(r['puladas_editadas_no_doctrack'])} puladas", ip=ip)
        return {"relatorio": relatorio}
    finally:
        descartar(id_recebido)
