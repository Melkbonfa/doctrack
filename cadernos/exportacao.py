"""
cadernos/exportacao.py — Pacote .zip das páginas para a liderança.

O pacote (PLANO_cadernos.md 2.7):

    <caderno>_<escopo>_<data>.zip
    ├── LEIA-ME.txt        índice: páginas, cada arquivo com tamanho e SHA-256
    ├── Relatorio.docx     capa, testes efetuados, as páginas, arquivos, assinaturas
    ├── imagens/           as figuras do relatório no tamanho original, mesma numeração
    ├── registros/NN - <página>/      arquivos de cada página (inclusive os anexos no texto)
    └── projeto/<seção ou pasta>/     arquivos da seção e do caderno escolhidos

Fluxo em dois passos, como o plano pede ("os arquivos são revistos antes de
gerar"): `previa` lista as páginas e TODOS os arquivos candidatos, já marcados
com o que vem por padrão (o "Exporta" de cada arquivo, mais todo arquivo citado
no texto de uma página exportada); `montar` gera o zip só com o que a pessoa
deixou marcado.

O zip fica numa pasta temporária por `VALIDADE_HORAS` para o download; o rastro
permanente é o registro em `caderno_exportacoes` (páginas, versões, manifesto).
"""
import hashlib
import json
import os
import re
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime

import arquivos_store
from models import db, User

from . import core
from .models import Caderno, CadernoArquivo, CadernoExportacao, CadernoNo, CadernoPagina
from .relatorio_docx import ArquivoRelatorio, PaginaRelatorio, Relatorio, tamanho_legivel
from .tarefas import ErroDaTarefa

PASTA_TEMP = os.path.join(tempfile.gettempdir(), "doctrack_exportacoes")
VALIDADE_HORAS = 24
# Formatos que já vêm comprimidos: guardar sem recomprimir poupa tempo e não
# muda o tamanho.
_JA_COMPRIMIDOS = {".zip", ".7z", ".rar", ".gz", ".bz2", ".xz", ".png", ".jpg", ".jpeg", ".gif",
                   ".webp", ".pdf", ".docx", ".xlsx", ".pptx", ".mp4", ".mov", ".avi", ".mp3",
                   ".one", ".onepkg"}
_RESERVADOS = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
ORIGEM_ROTULO = {"pagina": "Página", "secao": "Seção", "caderno": "Caderno"}


def nome_seguro(texto, limite=80):
    """Pedaço de caminho que o Explorer do Windows aceita."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(texto or ""))
    s = re.sub(r"\s+", " ", s).strip().strip(". ")
    if len(s) > limite:
        s = s[:limite].rstrip(". ")
    if not s:
        s = "sem nome"
    if s.split(".")[0].lower() in _RESERVADOS:
        s = "_" + s
    return s


def caminho_zip(uuid_):
    return os.path.join(PASTA_TEMP, f"{uuid_}.zip")


def _purgar_antigos(agora=None):
    agora = agora or time.time()
    if not os.path.isdir(PASTA_TEMP):
        return
    for nome in os.listdir(PASTA_TEMP):
        caminho = os.path.join(PASTA_TEMP, nome)
        try:
            if os.path.isfile(caminho) and agora - os.path.getmtime(caminho) > VALIDADE_HORAS * 3600:
                os.remove(caminho)
        except OSError:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# SELEÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def secoes_em_ordem(cad):
    """Seções visíveis do caderno na ordem da árvore (grupos abertos em ordem)."""
    nos = CadernoNo.query.filter_by(caderno_id=cad.id, excluido_em=None).all()
    filhos = {}
    for n in nos:
        filhos.setdefault(n.parent_id, []).append(n)
    saida = []

    def descer(parent_id):
        for n in sorted(filhos.get(parent_id, []), key=lambda x: (x.ordem or 0, x.id)):
            if n.tipo == "secao":
                saida.append(n)
            else:
                descer(n.id)

    descer(None)        # nó cujo pai está na lixeira não é alcançado: some junto
    return saida


def paginas_em_ordem(cad, uuids=None):
    """Páginas não excluídas, na ordem do caderno. `uuids` filtra (ordem do caderno
    vale mesmo se a lista vier em outra ordem)."""
    filtro = set(uuids) if uuids is not None else None
    saida = []
    for s in secoes_em_ordem(cad):
        for p in (CadernoPagina.query.filter_by(secao_id=s.id, excluido_em=None)
                  .order_by(CadernoPagina.ordem, CadernoPagina.id).all()):
            if filtro is None or p.uuid in filtro:
                saida.append(p)
    return saida


def rotulo_escopo(cad, paginas):
    todas = paginas_em_ordem(cad)
    if len(paginas) == 1:
        return f"Página {paginas[0].titulo}"
    if [p.id for p in paginas] == [p.id for p in todas]:
        return "Caderno completo"
    secoes = {p.secao_id for p in paginas}
    if len(secoes) == 1:
        sid = next(iter(secoes))
        da_secao = [p.id for p in todas if p.secao_id == sid]
        if [p.id for p in paginas] == da_secao:
            return f"Seção {db.session.get(CadernoNo, sid).nome}"
    return f"Seleção de {len(paginas)} páginas"


@dataclass
class Candidato:
    arquivo: CadernoArquivo
    origem: str          # pagina | secao | caderno
    local: str           # título da página, nome da seção, "Caderno"
    destino: str         # caminho dentro do zip
    marcado: bool        # vem marcado por padrão
    no_texto: bool       # citado no texto de uma página exportada

    def to_dict(self):
        a = self.arquivo
        return {"uuid": a.uuid, "nome": a.nome_original, "origem": self.origem,
                "origem_rotulo": ORIGEM_ROTULO[self.origem], "local": self.local,
                "destino": self.destino, "tamanho": int(a.tamanho or 0), "pasta": a.pasta or "",
                "marcado": self.marcado, "no_texto": self.no_texto, "versao": a.versao}


def _vigentes(**filtro):
    return (CadernoArquivo.query.filter_by(ativo=True, embutido=False, excluido_em=None, **filtro)
            .order_by(CadernoArquivo.pasta, CadernoArquivo.nome_original).all())


def candidatos(cad, paginas):
    """Todos os arquivos que podem entrar no pacote destas páginas."""
    # Anexos no texto: o link aponta para uma versão; vale a vigente da família.
    refs = set()
    for p in paginas:
        refs.update(core.anexos_no_html(p.conteudo_html))
    grupos_no_texto = set()
    if refs:
        grupos_no_texto = {g for (g,) in db.session.query(CadernoArquivo.grupo)
                           .filter(CadernoArquivo.uuid.in_(refs),
                                   CadernoArquivo.caderno_id == cad.id).all()}

    usados = set()

    def destino_livre(caminho):
        base, ext = os.path.splitext(caminho)
        n, final = 2, caminho
        while final.lower() in usados:
            final = f"{base} ({n}){ext}"
            n += 1
        usados.add(final.lower())
        return final

    def pasta(a):
        return "/".join(nome_seguro(x, 60) for x in (a.pasta or "").replace("\\", "/").split("/") if x.strip())

    saida = []
    largura = max(2, len(str(len(paginas))))
    for i, p in enumerate(paginas, 1):
        dir_pag = f"registros/{i:0{largura}d} - {nome_seguro(p.titulo, 70)}"
        for a in _vigentes(caderno_id=cad.id, escopo="pagina", escopo_id=p.id):
            sub = pasta(a)
            no_texto = a.grupo in grupos_no_texto
            saida.append(Candidato(a, "pagina", p.titulo,
                                   destino_livre("/".join(x for x in (dir_pag, sub, nome_seguro(a.nome_original, 120)) if x)),
                                   bool(a.incluir_exportacao) or no_texto, no_texto))
    for sid in dict.fromkeys(p.secao_id for p in paginas):
        secao = db.session.get(CadernoNo, sid)
        for a in _vigentes(caderno_id=cad.id, escopo="secao", escopo_id=sid):
            no_texto = a.grupo in grupos_no_texto
            saida.append(Candidato(a, "secao", secao.nome,
                                   destino_livre("/".join(x for x in ("projeto", nome_seguro(secao.nome, 60), pasta(a),
                                                                      nome_seguro(a.nome_original, 120)) if x)),
                                   bool(a.incluir_exportacao) or no_texto, no_texto))
    for a in _vigentes(caderno_id=cad.id, escopo="caderno", escopo_id=cad.id):
        no_texto = a.grupo in grupos_no_texto
        saida.append(Candidato(a, "caderno", "Caderno",
                               destino_livre("/".join(x for x in ("projeto", pasta(a), nome_seguro(a.nome_original, 120)) if x)),
                               bool(a.incluir_exportacao) or no_texto, no_texto))
    return saida


def previa(cad, paginas):
    secoes = {s.id: s.nome for s in secoes_em_ordem(cad)}
    imagens = []
    for p in paginas:
        imagens.extend(core.imagens_no_html(p.conteudo_html))
    tam_img = 0
    if imagens:
        tam_img = sum(int(t or 0) for (t,) in db.session.query(CadernoArquivo.tamanho)
                      .filter(CadernoArquivo.uuid.in_(imagens)).all())
    return {
        "escopo": rotulo_escopo(cad, paginas),
        "paginas": [{"uuid": p.uuid, "titulo": p.titulo, "secao": secoes.get(p.secao_id, ""),
                     "tipo": p.tipo} for p in paginas],
        "imagens": len(imagens),
        "tamanho_imagens": tam_img,
        "arquivos": [c.to_dict() for c in candidatos(cad, paginas)],
    }


# ══════════════════════════════════════════════════════════════════════════════
# O ZIP
# ══════════════════════════════════════════════════════════════════════════════

def _nomes_usuarios(ids):
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    return {u.id: u.nome for u in User.query.filter(User.id.in_(ids)).all()}


def _imagem_de(cad):
    def ler(uuid_):
        a = CadernoArquivo.query.filter_by(uuid=uuid_, caderno_id=cad.id).first()
        if not a:
            return None
        caminho = arquivos_store.caminho_de(a.sha256)
        if not os.path.isfile(caminho):
            return None
        with open(caminho, "rb") as fh:
            return fh.read(), (a.ext or "").lower()
    return ler


def montar(cad, paginas, selecionados, usuario, agora=None, progresso=None):
    """Gera o zip e grava o registro da exportação. `selecionados` = uuids dos
    arquivos que a pessoa deixou marcados na prévia (os outros são ignorados,
    inclusive uuid que não é candidato destas páginas)."""
    agora = agora or datetime.now()
    os.makedirs(PASTA_TEMP, exist_ok=True)
    _purgar_antigos()

    escolhidos = [c for c in candidatos(cad, paginas) if c.arquivo.uuid in set(selecionados or [])]
    por_grupo = {c.arquivo.grupo: c for c in escolhidos}
    secoes = {s.id: s.nome for s in secoes_em_ordem(cad)}
    ids = []
    for p in paginas:
        f = core.ficha_de_json(p.ficha_json)
        ids += [p.criado_por, f.get("resp_teste_id"), f.get("resp_execucao_id")]
    nomes = _nomes_usuarios(ids + [usuario.id])

    def link_de(uuid_):
        a = CadernoArquivo.query.filter_by(uuid=uuid_, caderno_id=cad.id).first()
        c = por_grupo.get(a.grupo) if a else None
        return c.destino if c else None

    pags_rel = []
    for p in paginas:
        f = core.ficha_de_json(p.ficha_json)
        pags_rel.append(PaginaRelatorio(
            titulo=p.titulo, secao=secoes.get(p.secao_id, ""), tipo=p.tipo, html=p.conteudo_html or "",
            versao=p.versao, data_pagina=p.data_pagina, ficha=f,
            resp_teste=nomes.get(f.get("resp_teste_id")) or f.get("resp_teste_nome") or "",
            resp_execucao=nomes.get(f.get("resp_execucao_id")) or f.get("resp_execucao_nome") or "",
            autores=p.origem_autores or nomes.get(p.criado_por, ""),
        ))
    escopo = rotulo_escopo(cad, paginas)
    arqs_rel = [ArquivoRelatorio(c.destino, int(c.arquivo.tamanho or 0),
                                 f"{ORIGEM_ROTULO[c.origem]}: {c.local}") for c in escolhidos]
    rel = Relatorio(caderno=cad.nome, escopo=escopo, emitido_por=usuario.nome, emitido_em=agora,
                    imagem_de=_imagem_de(cad), link_de=link_de)
    docx = rel.gerar(pags_rel, arqs_rel, progresso=progresso)
    if progresso:
        progresso(etapa="Compactando o relatório, as imagens e os arquivos…")

    exp = CadernoExportacao(caderno_id=cad.id, criado_por=usuario.id, criado_em=agora, escopo=escopo)
    db.session.add(exp)
    db.session.flush()

    # Figuras: o original de cada uma, com o número que tem no relatório.
    largura = max(2, len(str(len(paginas))))
    entradas = []          # (caminho no zip, caminho no disco | None, bytes | None, tamanho, sha256)
    entradas.append(("Relatorio.docx", None, docx, len(docx), hashlib.sha256(docx).hexdigest()))
    vistos = set()
    imagens = [(f"imagens/Figura {fig.numero:03d} - {nome_seguro(fig.legenda or paginas[fig.pagina - 1].titulo, 60)}",
                fig.uuid) for fig in rel.figuras]
    for k, (uuid_, idx) in enumerate(rel.sem_legenda, 1):
        imagens.append((f"imagens/outras/{idx:0{largura}d} - {nome_seguro(paginas[idx - 1].titulo, 50)} - {k}", uuid_))
    for base, uuid_ in imagens:
        a = CadernoArquivo.query.filter_by(uuid=uuid_, caderno_id=cad.id).first()
        if not a or base in vistos:
            continue
        vistos.add(base)
        caminho = arquivos_store.caminho_de(a.sha256)
        if os.path.isfile(caminho):
            entradas.append((base + (a.ext or ""), caminho, None, int(a.tamanho or 0), a.sha256))
    for c in escolhidos:
        caminho = arquivos_store.caminho_de(c.arquivo.sha256)
        if os.path.isfile(caminho):
            entradas.append((c.destino, caminho, None, int(c.arquivo.tamanho or 0), c.arquivo.sha256))

    leia_me = _leia_me(cad, escopo, paginas, secoes, usuario, agora, exp.uuid, entradas, escolhidos, rel)
    nome_zip = f"{nome_seguro(cad.nome, 60)}_{nome_seguro(escopo, 40)}_{agora:%Y-%m-%d}.zip"
    final = caminho_zip(exp.uuid)
    parcial = final + ".part"
    with zipfile.ZipFile(parcial, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("LEIA-ME.txt", leia_me.encode("utf-8-sig"))
        for nome, disco, dados, _, _ in entradas:
            modo = zipfile.ZIP_STORED if os.path.splitext(nome)[1].lower() in _JA_COMPRIMIDOS else zipfile.ZIP_DEFLATED
            if dados is not None:
                zf.writestr(zipfile.ZipInfo(nome, date_time=agora.timetuple()[:6]), dados, compress_type=modo)
            else:
                zf.write(disco, nome, compress_type=modo)
    os.replace(parcial, final)

    exp.nome_zip = nome_zip
    exp.tamanho = os.path.getsize(final)
    exp.paginas_json = json.dumps([{"uuid": p.uuid, "titulo": p.titulo, "versao": p.versao} for p in paginas],
                                  ensure_ascii=False)
    exp.manifesto_json = json.dumps([{"caminho": n, "tamanho": t, "sha256": h} for n, _, _, t, h in entradas],
                                    ensure_ascii=False)
    db.session.commit()
    return exp


def _leia_me(cad, escopo, paginas, secoes, usuario, agora, exp_uuid, entradas, escolhidos, rel):
    registros = sum(p.tipo == "registro_teste" for p in paginas)
    origem = {c.destino: f"{ORIGEM_ROTULO[c.origem]}: {c.local}" for c in escolhidos}
    enviado = {c.destino: c.arquivo for c in escolhidos}
    nomes = _nomes_usuarios([a.enviado_por for a in enviado.values()])
    largura = max(2, len(str(len(paginas))))
    L = [
        "PACOTE DE EXPORTAÇÃO — DocTrack · Cadernos de laboratório",
        "",
        f"Caderno:    {cad.nome}",
        f"Escopo:     {escopo}",
        f"Gerado em:  {agora:%d/%m/%Y %H:%M} por {usuario.nome} ({usuario.email})",
        f"Registro:   {exp_uuid}",
        "",
        "CONTEÚDO",
        f"  Relatorio.docx  relatório com {len(paginas)} página(s), {registros} registro(s) de teste e "
        f"{len(rel.figuras)} figura(s)",
        "  imagens/        as figuras do relatório no tamanho original, com a mesma numeração",
        "  registros/      arquivos de cada página (dados brutos, laudos, arquivos de equipamento)",
        "  projeto/        arquivos das seções e do caderno escolhidos para o pacote",
        "",
        "PÁGINAS",
    ]
    for i, p in enumerate(paginas, 1):
        L.append(f"  {i:0{largura}d}  {p.titulo}  ({secoes.get(p.secao_id, '')}, versão {p.versao})")
    L += ["", "ARQUIVOS  (caminho | tamanho | origem | enviado por, em | SHA-256)"]
    for nome, _, _, tam, sha in entradas:
        a = enviado.get(nome)
        quem = f"{nomes.get(a.enviado_por, '—')}, {a.enviado_em:%d/%m/%Y}" if a and a.enviado_em else "—"
        L.append(f"  {nome}")
        L.append(f"      {tamanho_legivel(tam)} | {origem.get(nome, 'gerado na exportação' if nome == 'Relatorio.docx' else 'imagem da página')}"
                 f" | {quem} | {sha}")
    L += ["", "Para conferir um arquivo, no PowerShell:",
          "  Get-FileHash -Algorithm SHA256 <arquivo>",
          "O resultado deve ser igual ao SHA-256 listado acima.", ""]
    return "\r\n".join(L)


def executar(tarefa, caderno_id, pagina_uuids, selecionados, user_id, ip=""):
    """Corpo da tarefa de exportação (roda fora da requisição: ver tarefas.py)."""
    from auth import log_action
    cad = db.session.get(Caderno, caderno_id)
    usuario = db.session.get(User, user_id)
    paginas = paginas_em_ordem(cad, pagina_uuids)
    if not paginas:
        raise ErroDaTarefa("As páginas escolhidas não existem mais (foram para a lixeira?).")
    tarefa.progresso(0, len(paginas), "Montando o relatório…")
    exp = montar(cad, paginas, selecionados, usuario, progresso=tarefa.progresso)
    log_action(usuario.email, "EXPORT", entidade=f"caderno:{cad.nome}", campo="exportacao",
               novo=f"{exp.nome_zip} ({len(paginas)} páginas)", ip=ip)
    return {"exportacao": exp.to_dict()}
