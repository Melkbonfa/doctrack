"""
documentos.py — Blueprint de CRUD de Documentos + acesso a arquivos do equipamento.

Rotas:
  GET    /api/documentos                 — lista (filtro por setor + busca livre)
  GET    /api/documentos/<id>            — detalhe
  POST   /api/documentos                 — criar (gera os 9 tipos canônicos)
  PATCH  /api/documentos/<id>            — editar campos do próprio documento
  DELETE /api/documentos/<id>            — soft delete (admin/gestor)
  PUT    /api/documentos/<id>/aplicabilidade — liga/desliga o tipo no escopo (N/A)
  GET    /api/documentos/metricas        — fluxo: WIP, aging, cycle time, throughput
  GET    /api/documentos/alertas         — o que precisa de atenção hoje
  GET    /api/documentos/<id>/historico  — trilha de status/escopo do documento
  GET    /api/documentos/responsaveis    — usuários atribuíveis (picker)
  GET    /api/documentos/export          — CSV bruto para análise externa
  GET    /api/documentos/diagnostico     — cadastro × arquivos que existem de fato
  POST   /api/documentos/abrir-pasta     — abre a pasta no servidor (acesso local)
  GET    /api/documentos/arquivos        — lista arquivos da pasta do equipamento
  GET    /api/documentos/arquivo         — serve um arquivo (preview/download)
  PUT    /api/documento/<id>/status      — troca de status com checagem de versão

Anexos do EQUIPAMENTO (não de um tipo de documento) — docs agregados e o
repositório de software/firmware. Ver `EquipamentoArquivo`:

  GET    /api/equipamentos/<id>/anexos      — lista (?categoria= filtra)
  POST   /api/equipamentos/<id>/anexos      — envia (admin/gestor)
  PATCH  /api/equipamentos/anexos/<id>      — corrige metadados (admin/gestor)
  GET    /api/equipamentos/anexos/<id>/conteudo — baixa/visualiza
  DELETE /api/equipamentos/anexos/<id>      — soft delete (admin/gestor)

Identidade (equipamento / SKU / fabricante) é canônica no Equipamento e imutável
pelo documento — ver módulo Equipamentos. O caminho da pasta também: o documento
só guarda override (ver Documento.armazenamento_efetivo).
"""
import csv
import io
import os
import json
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import (
    db, Documento, DocumentoHistorico, DocumentoArquivo,
    Equipamento, EquipamentoPasta, EquipamentoArquivo, AuditLog, User,
    SETORES, SETORES_TODOS, STATUS_MAP,
    TIPOS_DOC_PRE, TIPOS_DOC_FABRICANTE, TIPOS_DOC_TODOS, TIPOS_DOC_OPCIONAIS,
    SETOR_DO_TIPO, TIPOS_DOC_LABELS, MOTIVOS_NA, MOTIVO_NA_LIVRE,
)
from auth import require_role, log_action, get_client_ip
from event_bus import EventType
from utils import norm
import caminhos
import arquivos_store
import diagnostico
# Sync Documento → Cartão (import acíclico: missoes.py só importa models/auth)
from missoes import sincronizar_cartoes_documento, emitir_eventos_sync

documentos_bp = Blueprint("documentos", __name__)

# Raízes permitidas para visualizar/baixar arquivos dos equipamentos.
# Configurável via DOCTRACK_FILE_ROOTS (separado por ';'). Basta UMA forma por
# pasta: caminhos.normalizar() traduz a unidade mapeada (P:\Engenharia) para a
# UNC canônica (\\loccus-srv03\Projetos$\Engenharia) antes de comparar.
ARQUIVOS_ROOTS = caminhos.RAIZES_ARQUIVOS

_EXT_INLINE = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".txt"}

# Status terminais dos dois pipelines (STATUS_PRE / STATUS_FABRICANTE) — os que
# `Documento.status_global` traduz para "Finalizado". Usado para decidir quando
# gravar (ou limpar) `concluido_em`.
_STATUS_FINAIS = {"Homologado", "Concluído"}


# preenchido por servidor.py para emitir tempo real sem import circular
_rt = {"socketio": None, "publish_event": None, "AuditLog": None, "EventType": None}


def init_realtime(socketio, publish_event, AuditLog, EventType):
    _rt.update(socketio=socketio, publish_event=publish_event,
               AuditLog=AuditLog, EventType=EventType)


def _emit(event_type, payload, email):
    if _rt["socketio"] and _rt["publish_event"]:
        try:
            _rt["publish_event"](event_type, payload, user_email=email,
                                 db=db, AuditLog=_rt["AuditLog"],
                                 socketio=_rt["socketio"])
        except Exception:
            pass  # tempo real é best-effort; a gravação já foi feita


def _registrar_historico(doc, por, *, evento="status", status_antigo="",
                         status_novo="", aplicavel=None, motivo=""):
    """Enfileira uma linha na trilha do documento (commit fica com o chamador).

    É esta trilha que permite medir tempo de ciclo, aging e throughput — o
    AuditLog genérico não serve de série temporal.
    """
    db.session.add(DocumentoHistorico(
        documento_id=doc.id, evento=evento,
        status_antigo=status_antigo or "", status_novo=status_novo or "",
        aplicavel=aplicavel, motivo=(motivo or "")[:300],
        em=datetime.now(), por=por or ""))


def _parse_data(valor):
    """'YYYY-MM-DD' → date. Devolve (ok, date|None); vazio limpa o campo."""
    if valor in (None, ""):
        return True, None
    try:
        return True, datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except Exception:
        return False, None


def _marcar_troca_status(doc, caller, status_antigo):
    """Atualiza os marcos temporais do documento numa troca de status.

    Sem isto a trilha registrava o evento mas o documento não sabia desde quando
    estava no status atual (aging) nem quando foi concluído (cycle time e
    throughput) — só `updated_em`, que qualquer edição de observação sobrescreve.

    Reabrir um documento concluído LIMPA `concluido_em`: deixar a data ali faria
    o documento contar duas vezes no throughput do mês em que voltou.
    """
    agora = datetime.now()
    doc.entrou_status_em = agora

    era_final = (status_antigo or "") in _STATUS_FINAIS
    virou_final = doc.concluido
    if virou_final and not era_final:
        doc.concluido_em = agora
        doc.concluido_por = caller or ""
    elif era_final and not virou_final:
        doc.concluido_em = None
        doc.concluido_por = ""


def _aplicar_responsaveis(doc, data, caller):
    """Aplica `responsaveis_ids` (N:N) mantendo `responsavel` como texto exibido.

    Os dois campos andam juntos de propósito: o texto é o que a planilha e as
    telas antigas leem, o N:N é o que permite agregar por pessoa. Devolve o erro
    de validação ou None.
    """
    if "responsaveis_ids" not in data:
        return None
    ids = data.get("responsaveis_ids") or []
    if not isinstance(ids, list):
        return "responsaveis_ids deve ser uma lista de ids de usuário"
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return "responsaveis_ids deve conter apenas ids numéricos"
    users = User.query.filter(User.id.in_(ids), User.ativo == True).all() if ids else []
    if len(users) != len(set(ids)):
        return "Um ou mais responsáveis não existem ou estão inativos"
    antigo = doc.responsavel or ""
    doc.responsaveis_users = users
    doc.responsavel = ", ".join(u.nome for u in users)
    if antigo != doc.responsavel:
        log_action(caller, "UPDATE", entidade=doc.documento, campo="responsavel",
                   antigo=antigo, novo=doc.responsavel, documento_id=doc.id,
                   ip=get_client_ip())
    return None


def _validar_motivo_na(data):
    """Valida o motivo de um N/A. Devolve (codigo, detalhe, erro|None).

    Obrigatório de propósito: marcar N/A muda o denominador da completude de
    todo mundo. Código vem da lista fechada (analisável); o texto livre só é
    exigido — e só é usado sozinho — quando o código é 'outro'.
    """
    codigo = (data.get("motivo_na_codigo") or "").strip()
    detalhe = (data.get("motivo_na") or "").strip()[:300]
    if codigo not in MOTIVOS_NA:
        return "", "", (f"Informe o motivo do N/A. Valores aceitos em "
                        f"'motivo_na_codigo': {', '.join(MOTIVOS_NA)}")
    if codigo == MOTIVO_NA_LIVRE and not detalhe:
        return "", "", "Motivo 'Outro' exige a descrição em 'motivo_na'."
    return codigo, detalhe, None


# ── API — CRUD DOCUMENTOS ────────────────────────────────────────────────────
@documentos_bp.route("/api/documentos")
@jwt_required()
def api_documentos():
    q       = norm(request.args.get("q", ""))
    setor   = request.args.get("setor", "")

    query = Documento.query.filter(Documento.ativo == True)
    if setor: query = query.filter(Documento.setor == setor)

    rows = query.order_by(Documento.equipamento).all()
    if q:
        # Busca acento-insensível: monta o blob direto do modelo (equipamento_rel
        # é lazy="joined", sem N+1) e só serializa (to_dict) as linhas que casam,
        # em vez de serializar a tabela inteira a cada tecla.
        def blob(d):
            eq = d.equipamento_rel
            partes = [d.equipamento, d.documento, d.codigo_doc, d.sku, d.responsavel,
                      d.armazenamento, d.tipo_doc, d.fabricante,
                      (eq.nome_original if eq else ""), (eq.anvisa if eq else ""),
                      (eq.familia if eq else "")]
            return norm(" ".join(p or "" for p in partes))
        rows = [d for d in rows if q in blob(d)]
    return jsonify([d.to_dict() for d in rows]), 200

@documentos_bp.route("/api/documentos/<int:doc_id>", methods=["GET"])
@jwt_required()
def get_documento(doc_id):
    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc: return jsonify({"erro": "Não encontrado"}), 404
    return jsonify(doc.to_dict()), 200

@documentos_bp.route("/api/documentos", methods=["POST"])
@require_role("admin", "gestor", "tecnico")
def create_documento():
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    setor = data.get("setor")
    if setor not in SETORES:
        return jsonify({"erro": f"Setor inválido. Escolha entre {SETORES}"}), 400

    # Busca SKU existente para manter a integração do equipamento
    equip = (data.get("equipamento") or "").strip()
    sku = (data.get("sku") or "").strip()
    if equip:
        existing = Documento.query.filter(
            Documento.ativo == True,
            Documento.equipamento == equip,
            Documento.sku != ""
        ).first()
        if existing:
            sku = existing.sku

    # get-or-create da entidade Equipamento (fonte única de identidade).
    # Se o equipamento já existe, os documentos herdam a identidade DELE
    # (SKU/fabricante), garantindo espelho; o payload só semeia um equip novo.
    equip_obj = None
    fab = data.get("fabricante", "")
    if equip:
        equip_obj = Equipamento.query.filter_by(nome=equip).first()
        if not equip_obj:
            equip_obj = Equipamento(
                nome=equip, sku=sku,
                fabricante=fab,
                armazenamento_base=caminhos.normalizar(data.get("armazenamento")),
            )
            db.session.add(equip_obj)
            db.session.flush()
        else:
            if sku and not equip_obj.sku:
                equip_obj.sku = sku
            # o caminho é do equipamento: semeia o base se ainda estiver vazio
            if data.get("armazenamento") and not (equip_obj.armazenamento_base or "").strip():
                equip_obj.armazenamento_base = caminhos.normalizar(data["armazenamento"])
            # identidade canônica vem da entidade
            sku = equip_obj.sku or sku
            fab = equip_obj.fabricante or fab
    equip_id = equip_obj.id if equip_obj else None

    # Tipo selecionado (recebe os campos do payload); os demais nascem em branco.
    tipos_setor = TIPOS_DOC_PRE if setor == "PRE" else TIPOS_DOC_FABRICANTE
    selected_tipo = data.get("tipo_doc") or tipos_setor[0]
    if selected_tipo not in TIPOS_DOC_TODOS:
        selected_tipo = tipos_setor[0]

    # Documentos já existentes deste equipamento (qualquer setor), por tipo.
    existentes = {}
    if equip:
        for d in Documento.query.filter(
            Documento.ativo == True, Documento.equipamento == equip
        ).all():
            existentes.setdefault(d.tipo_doc, d)

    doc = existentes.get(selected_tipo)
    criados = []
    # Todos os 12 tipos nascem com o equipamento. Os opcionais nascem em N/A
    # (fora da completude); ligá-los é um toggle na aba Escopo. Se o opcional for
    # o tipo explicitamente selecionado neste POST, ele já nasce aplicável.
    for t in TIPOS_DOC_TODOS:
        if t in existentes:
            continue
        is_sel = (t == selected_tipo)
        label = TIPOS_DOC_LABELS.get(t, t)
        novo = Documento(
            setor=SETOR_DO_TIPO[t],
            equipamento=equip,
            equipamento_id=equip_id,
            sku=sku,
            codigo_doc=data.get("codigo_doc", "") if is_sel else "",
            documento=(data.get("documento") or f"{label} - {equip}") if is_sel else f"{label} - {equip}",
            responsavel=data.get("responsavel", "") if is_sel else "",
            status=data.get("status", "Elaborar") if is_sel else "Elaborar",
            tipo_doc=t,
            fabricante=fab,
            aplicavel=(is_sel or t not in TIPOS_DOC_OPCIONAIS),
            motivo_na_codigo=("" if (is_sel or t not in TIPOS_DOC_OPCIONAIS)
                              else "nao_se_aplica_produto"),
            obs_treinamento=data.get("obs_treinamento", "") if is_sel else "",
            obs_homologacao=data.get("obs_homologacao", "") if is_sel else "",
            # caminho herda do equipamento; só grava override se divergir do base
            armazenamento="",
            # Marco de entrada no status inicial: sem ele o aging de um documento
            # recém-criado começaria sem referência (era o caso de todos).
            entrou_status_em=datetime.now(),
        )
        if is_sel:
            if data.get("data_treinamento"):
                try: novo.data_treinamento = datetime.strptime(data["data_treinamento"], "%Y-%m-%d")
                except: pass
            if data.get("data_homologacao"):
                try: novo.data_homologacao = datetime.strptime(data["data_homologacao"], "%Y-%m-%d")
                except: pass
            ok_prazo, prazo = _parse_data(data.get("prazo"))
            if ok_prazo:
                novo.prazo = prazo
            ok_ini, data_ini = _parse_data(data.get("data_inicio"))
            if ok_ini:
                novo.data_inicio = data_ini
            try:
                peso = float(data.get("peso") or 1.0)
                novo.peso = peso if peso > 0 else 1.0
            except (TypeError, ValueError):
                novo.peso = 1.0
            # Documento pode nascer já em status terminal (importação/retroativo)
            if novo.concluido:
                novo.concluido_em = datetime.now()
                novo.concluido_por = caller or ""
        db.session.add(novo)
        criados.append(novo)
        if is_sel:
            doc = novo

    db.session.flush()          # garante o id de cada documento novo
    # marco inicial da trilha: sem ele o aging não teria data de referência
    for novo in criados:
        _registrar_historico(novo, caller, status_novo=novo.status or "Elaborar",
                             motivo="Documento criado")
    db.session.commit()
    novo_criado = doc is not None
    if doc is None:   # tipo selecionado já existia e nada foi criado
        doc = existentes.get(selected_tipo) or next(iter(existentes.values()), None)

    # Responsáveis tipados só no documento que ACABOU de nascer: quando o tipo já
    # existia este POST não cria nada, e sobrescrever o responsável de um
    # documento em andamento não é o que "criar documento" deveria fazer.
    if novo_criado and doc is not None:
        erro_resp = _aplicar_responsaveis(doc, data, caller)
        if erro_resp:
            return jsonify({"erro": erro_resp}), 400
        db.session.commit()

    log_action(caller, "CREATE", entidade=doc.documento, campo="setor", novo=setor, documento_id=doc.id, ip=get_client_ip())

    _emit(EventType.DOCUMENT_CREATED,
          {"documento_id": doc.id, "documento": doc.to_dict(), "setor": doc.setor, "equipamento": doc.equipamento},
          caller)
    return jsonify({"mensagem": "Documento criado", "documento": doc.to_dict()}), 201

@documentos_bp.route("/api/documentos/<int:doc_id>", methods=["PATCH", "PUT"])
@require_role("admin", "gestor", "tecnico")
def update_documento(doc_id):
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc: return jsonify({"erro": "Não encontrado"}), 404

    # Identidade (equipamento / SKU / fabricante) é IMUTÁVEL pelo documento:
    # a fonte única é a entidade Equipamento — editável só no módulo Equipamentos,
    # que propaga para os documentos vinculados. Aqui só se editam campos do
    # próprio documento (status, responsável, código, datas, obs, caminho).
    CAMPOS_STR = ["codigo_doc", "documento", "responsavel", "status",
                  "obs_treinamento", "obs_homologacao", "armazenamento"]

    # status só pode assumir um valor válido para o setor do documento (mesma
    # regra da rota /status). Sem isto, um PATCH grava qualquer string em status
    # e quebra os KPIs / status_global. Só valida quando o valor muda, para não
    # rejeitar um edit de outro campo em documentos com status legado.
    status_mudou = ("status" in data and str(data.get("status")) != str(doc.status))
    if status_mudou:
        setor_status = STATUS_MAP.get(doc.setor, [])
        if data.get("status") not in setor_status:
            return jsonify({"erro": f"Status inválido para o setor {doc.setor}. Use: {', '.join(setor_status)}"}), 400

    # Prazo é validado AQUI, antes de qualquer escrita: log_action() faz commit,
    # então rejeitar mais adiante gravaria os campos já processados e devolveria
    # 400 — um PATCH pela metade.
    prazo_novo = doc.prazo
    if "prazo" in data:
        ok_prazo, prazo_novo = _parse_data(data.get("prazo"))
        if not ok_prazo:
            return jsonify({"erro": "Prazo inválido. Use o formato AAAA-MM-DD."}), 400

    # tipo_doc foi retirado dos campos editáveis: é imutável — parte do invariante
    # dos 9 tipos por equipamento e da coerência com SETOR_DO_TIPO (trocar o tipo
    # não moveria o setor junto). O tipo nasce fixo na criação.

    status_antigo = doc.status

    # O caminho da pasta pertence ao EQUIPAMENTO: gravar o mesmo valor nas 12
    # linhas era o que fazia uma aba divergir das outras. Aqui, salvar o caminho
    # herdado não cria override (fica vazio = continua herdando); só um caminho
    # DIFERENTE do base vira exceção deste documento.
    # Grupo (pasta) do documento. Vem antes do caminho livre porque escolher a
    # pasta é o caminho normal e ela já resolve o endereço.
    if "pasta_id" in data:
        bruto = data.get("pasta_id")
        if bruto in (None, "", 0, "0"):
            doc.pasta_id = None
        else:
            # O id vem do cliente: `int()` cru transformava qualquer coisa não
            # numérica em ValueError não tratado — 500 onde a resposta certa é
            # a mesma de uma pasta inexistente.
            try:
                pasta_id_novo = int(bruto)
            except (TypeError, ValueError):
                return jsonify({"erro": "Pasta inválida para este equipamento"}), 400
            pasta = EquipamentoPasta.query.filter(
                EquipamentoPasta.id == pasta_id_novo,
                EquipamentoPasta.ativo == True).first()
            # a pasta tem que ser DO equipamento do documento: aceitar a de outro
            # deixaria um documento apontando para a pasta de outro produto
            if not pasta or pasta.equipamento_id != doc.equipamento_id:
                return jsonify({"erro": "Pasta inválida para este equipamento"}), 400
            if doc.pasta_id != pasta.id:
                log_action(caller, "UPDATE", entidade=doc.documento, campo="pasta",
                           antigo=(doc.pasta_rel.nome if doc.pasta_rel else ""),
                           novo=pasta.nome, documento_id=doc.id, ip=get_client_ip())
            doc.pasta_id = pasta.id
            # escolher a pasta desfaz uma exceção anterior — senão o caminho
            # livre continuaria vencendo e a troca de pasta não teria efeito
            doc.armazenamento = ""
            data.pop("armazenamento", None)

    if "armazenamento" in data:
        # Canoniza antes de comparar: sem isto o mesmo diretório colado como
        # `P:\...` não batia com o gravado em UNC e virava uma exceção falsa.
        # Salvar um caminho que já é o da pasta ou o do equipamento NÃO cria
        # exceção — continua herdando de quem já o fornecia.
        base = caminhos.normalizar(doc.equipamento_rel.armazenamento_base
                                   if doc.equipamento_rel else "")
        da_pasta = caminhos.normalizar(doc.pasta_rel.caminho if doc.pasta_rel else "")
        val = caminhos.normalizar(data.get("armazenamento"))
        data["armazenamento"] = val
        if val and val in (base, da_pasta):
            data["armazenamento"] = ""
        elif val and not base and not da_pasta and doc.equipamento_rel:
            # equipamento ainda sem caminho: promove este a base do equipamento
            doc.equipamento_rel.armazenamento_base = val
            log_action(caller, "UPDATE", entidade=f"Equipamento: {doc.equipamento}",
                       campo="armazenamento_base", antigo="", novo=val, ip=get_client_ip())
            data["armazenamento"] = ""

    for campo in CAMPOS_STR:
        if campo in data:
            antigo = getattr(doc, campo); novo = data[campo]
            if str(antigo) != str(novo):
                log_action(caller, "UPDATE", entidade=doc.documento, campo=campo, antigo=antigo, novo=novo, documento_id=doc.id, ip=get_client_ip())
                setattr(doc, campo, novo)

    if "data_treinamento" in data:
        try:
            doc.data_treinamento = datetime.strptime(data["data_treinamento"], "%Y-%m-%d") if data["data_treinamento"] else None
        except: pass
    if "data_homologacao" in data:
        try:
            doc.data_homologacao = datetime.strptime(data["data_homologacao"], "%Y-%m-%d") if data["data_homologacao"] else None
        except: pass
    if "prazo" in data and prazo_novo != doc.prazo:
        log_action(caller, "UPDATE", entidade=doc.documento, campo="prazo",
                   antigo=(doc.prazo.isoformat() if doc.prazo else ""),
                   novo=(prazo_novo.isoformat() if prazo_novo else ""),
                   documento_id=doc.id, ip=get_client_ip())
        doc.prazo = prazo_novo

    if "data_inicio" in data:
        ok_ini, data_ini = _parse_data(data.get("data_inicio"))
        if not ok_ini:
            return jsonify({"erro": "Data de início inválida. Use o formato AAAA-MM-DD."}), 400
        if data_ini != doc.data_inicio:
            log_action(caller, "UPDATE", entidade=doc.documento, campo="data_inicio",
                       antigo=(doc.data_inicio.isoformat() if doc.data_inicio else ""),
                       novo=(data_ini.isoformat() if data_ini else ""),
                       documento_id=doc.id, ip=get_client_ip())
            doc.data_inicio = data_ini

    if "peso" in data:
        try:
            peso = float(data.get("peso") or 1.0)
        except (TypeError, ValueError):
            return jsonify({"erro": "Peso deve ser numérico"}), 400
        if peso <= 0:
            return jsonify({"erro": "Peso deve ser maior que zero"}), 400
        doc.peso = peso

    erro_resp = _aplicar_responsaveis(doc, data, caller)
    if erro_resp:
        return jsonify({"erro": erro_resp}), 400

    doc.updated_em = datetime.now()
    doc.version = (doc.version or 0) + 1
    if status_mudou:
        _marcar_troca_status(doc, caller, status_antigo)
        _registrar_historico(doc, caller, status_antigo=status_antigo,
                             status_novo=doc.status)
    # documento é a fonte da verdade: se o status mudou, move os cartões
    # vinculados no kanban (mesma transação; eventos emitidos após o commit)
    eventos_sync = sincronizar_cartoes_documento(doc, caller) if status_mudou else []
    db.session.commit()
    _emit(EventType.DOCUMENT_UPDATED,
          {"documento_id": doc.id, "documento": doc.to_dict(), "setor": doc.setor, "equipamento": doc.equipamento},
          caller)
    emitir_eventos_sync(eventos_sync, caller)
    return jsonify({"mensagem": "Documento atualizado", "documento": doc.to_dict()}), 200

@documentos_bp.route("/api/documentos/<int:doc_id>", methods=["DELETE"])
@require_role("admin", "gestor")
def delete_documento(doc_id):
    caller = get_jwt_identity()
    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc: return jsonify({"erro": "Não encontrado"}), 404
    nome = doc.documento
    snapshot_data = json.dumps(doc.snapshot())
    doc.ativo = False; doc.deleted_at = datetime.now(); db.session.commit()
    log_action(caller, "DELETE", entidade=nome, campo="*", antigo=snapshot_data, documento_id=doc.id, ip=get_client_ip())
    _emit(EventType.DOCUMENT_DELETED,
          {"documento_id": doc_id, "setor": doc.setor, "equipamento": doc.equipamento},
          caller)
    return jsonify({"mensagem": f"Documento '{nome}' excluído"}), 200

@documentos_bp.route("/api/documentos/<int:doc_id>/aplicabilidade", methods=["PUT"])
@require_role("admin", "gestor")
def update_aplicabilidade(doc_id):
    """Liga/desliga um tipo de documento no escopo do equipamento (N/A).

    Fora do PATCH genérico de propósito: o PATCH é tecnico+ (edita status e campos
    do documento); mexer no escopo muda o denominador da completude de todo mundo,
    então fica restrito a admin/gestor. Marcar N/A NÃO altera o status nem toca nos
    cartões de missão vinculados — o documento só sai da conta.

    Marcar N/A EXIGE motivo (`motivo_na_codigo` da lista fechada MOTIVOS_NA);
    enquanto era opcional, os 47 N/A do banco tinham zero motivos preenchidos.
    """
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    if "aplicavel" not in data:
        return jsonify({"erro": "Informe 'aplicavel' (true/false)"}), 400

    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc:
        return jsonify({"erro": "Não encontrado"}), 404

    novo = bool(data.get("aplicavel"))
    antigo = bool(doc.aplicavel)
    # motivo só existe enquanto o documento está em N/A; religar limpa
    if novo:
        codigo, motivo = "", ""
    else:
        codigo, motivo, erro = _validar_motivo_na(data)
        if erro:
            return jsonify({"erro": erro, "motivos": MOTIVOS_NA}), 400

    if (novo == antigo and motivo == (doc.motivo_na or "")
            and codigo == (doc.motivo_na_codigo or "")):
        return jsonify({"mensagem": "Nada a alterar", "documento": doc.to_dict()}), 200

    doc.aplicavel = novo
    doc.motivo_na_codigo = codigo
    doc.motivo_na = motivo
    doc.updated_em = datetime.now()
    doc.version = (doc.version or 0) + 1
    _registrar_historico(doc, caller, evento="escopo", aplicavel=novo,
                         status_antigo=doc.status, status_novo=doc.status,
                         motivo=doc.motivo_na_label)
    db.session.commit()

    log_action(caller, "UPDATE", entidade=doc.documento, campo="aplicavel",
               antigo="Aplica" if antigo else "N/A",
               novo=("Aplica" if novo else f"N/A — {doc.motivo_na_label}"),
               documento_id=doc.id, ip=get_client_ip())
    _emit(EventType.DOCUMENT_UPDATED,
          {"documento_id": doc.id, "documento": doc.to_dict(),
           "setor": doc.setor, "equipamento": doc.equipamento},
          caller)
    return jsonify({"mensagem": "Escopo atualizado", "documento": doc.to_dict()}), 200

# ── MÉTRICAS DE FLUXO ────────────────────────────────────────────────────────
# `documento_historico` existe desde a migration 008 com o propósito declarado
# de medir tempo de ciclo, aging e throughput — e até aqui era escrita a cada
# troca de status e lida apenas para listar a trilha de UM documento na ficha.
# O módulo de Missões já tinha a implementação completa (_metricas_missao); esta
# é a mesma leitura aplicada ao maior conjunto de dados do sistema.

def _percentil(valores, p):
    """Percentil por interpolação linear (p em 0..1). O p85 do cycle time é a
    promessa realista de prazo; a média sozinha esconde a cauda."""
    if not valores:
        return None
    vs = sorted(valores)
    k = (len(vs) - 1) * p
    baixo = int(k)
    alto = min(baixo + 1, len(vs) - 1)
    return round(vs[baixo] + (vs[alto] - vs[baixo]) * (k - baixo), 1)


def _tempo_por_status(docs):
    """Tempo médio de permanência em cada status, em dias.

    Intervalos fechados vêm da trilha (um evento de status até o seguinte do
    mesmo documento); o trecho ainda aberto entra pelo `entrou_status_em` do
    documento parado. É a leitura que aponta onde o fluxo trava — se
    "Enviado para Homologação" tem média de 90 dias, o gargalo não é elaborar.
    """
    ids = [d.id for d in docs]
    acc = {}
    if not ids:
        return acc

    eventos = (DocumentoHistorico.query
               .filter(DocumentoHistorico.documento_id.in_(ids),
                       db.func.coalesce(DocumentoHistorico.evento, "status") == "status")
               .order_by(DocumentoHistorico.documento_id, DocumentoHistorico.em)
               .all())
    por_doc = {}
    for ev in eventos:
        por_doc.setdefault(ev.documento_id, []).append(ev)

    for evs in por_doc.values():
        for atual, seguinte in zip(evs, evs[1:]):
            status = (atual.status_novo or "").strip()
            if not status or not atual.em or not seguinte.em:
                continue
            alvo = acc.setdefault(status, {"dias": 0.0, "n": 0})
            alvo["dias"] += (seguinte.em - atual.em).total_seconds() / 86400.0
            alvo["n"] += 1

    agora = datetime.now()
    for d in docs:
        if d.concluido:
            continue          # trecho aberto só existe em documento em curso
        base = d.entrou_status_em or d.criado_em
        status = (d.status or "").strip()
        if not base or not status:
            continue
        alvo = acc.setdefault(status, {"dias": 0.0, "n": 0})
        alvo["dias"] += (agora - base).total_seconds() / 86400.0
        alvo["n"] += 1

    return {s: {"media": round(v["dias"] / v["n"], 1) if v["n"] else 0.0,
                "amostras": v["n"]}
            for s, v in acc.items()}


@documentos_bp.route("/api/documentos/metricas", methods=["GET"])
@jwt_required()
def metricas_documentos():
    """Métricas de fluxo dos documentos — o mesmo conjunto que Missões já expõe.

    ?dias=N     janela do throughput e do cycle time (padrão 30, máx 365)
    ?setor=     restringe a um setor
    ?equipamento_id=  restringe a um equipamento

    Escopo: documentos ativos e APLICÁVEIS. Os N/A saem da conta de fluxo (não
    são backlog nem pendência, é a mesma regra dos KPIs) e aparecem agregados
    em `motivos_na` — o motivo era coletado numa lista fechada e analisável
    desde o início e nunca havia sido somado em lugar nenhum.
    """
    dias = max(1, min(request.args.get("dias", default=30, type=int) or 30, 365))
    setor = request.args.get("setor", "")
    equipamento_id = request.args.get("equipamento_id", type=int)

    base = Documento.query.filter(Documento.ativo == True)
    if setor:
        base = base.filter(Documento.setor == setor)
    if equipamento_id:
        base = base.filter(Documento.equipamento_id == equipamento_id)

    docs = base.filter(Documento.aplicavel == True).all()
    nao_aplicaveis = base.filter(Documento.aplicavel == False).all()

    corte = datetime.now() - timedelta(days=dias)
    abertos = [d for d in docs if not d.concluido]
    concluidos = [d for d in docs if d.concluido]
    # WIP = o que está efetivamente em curso (nem parado no início, nem pronto).
    wip = sum(1 for d in abertos if d.status_global == "Em progresso")

    tempos = _tempo_por_status(docs)
    por_status = {}
    for d in docs:
        status = (d.status or "Elaborar").strip()
        reg = por_status.setdefault(status, {"status": status, "total": 0, "abertos": 0})
        reg["total"] += 1
        if not d.concluido:
            reg["abertos"] += 1
    for status, reg in por_status.items():
        reg["dias_medios"] = tempos.get(status, {}).get("media", 0.0)
        reg["amostras"] = tempos.get(status, {}).get("amostras", 0)

    carga = {}
    for d in abertos:
        nomes = d.responsaveis_nomes or ["(sem responsável)"]
        for n in nomes:
            reg = carga.setdefault(n, {"nome": n, "abertos": 0, "atrasados": 0,
                                       "peso": 0.0, "parados": 0})
            reg["abertos"] += 1
            reg["peso"] += (d.peso if d.peso is not None else 1.0)
            if d.atrasado:
                reg["atrasados"] += 1
            if d.dias_no_status >= 30:
                reg["parados"] += 1
    for reg in carga.values():
        reg["peso"] = round(reg["peso"], 1)

    # Concluído antes de existir instrumentação não tem data de conclusão (ver
    # _data_conclusao_real em servidor.py). Eles contam no total e no avanço,
    # mas ficam FORA de throughput e cycle time — e o número deles vai na
    # resposta para a tela poder dizer que a série ainda não cobre tudo, em vez
    # de exibir um p85 calculado sobre meia dúzia de casos como se fosse geral.
    sem_data = sum(1 for d in concluidos if not d.concluido_em)
    janela = [d for d in concluidos if d.concluido_em and d.concluido_em >= corte]
    semanas = {}
    for d in janela:
        iso = d.concluido_em.date().isocalendar()
        rotulo = f"{iso[0]}-S{iso[1]:02d}"
        semanas[rotulo] = semanas.get(rotulo, 0) + 1
    ciclos = [d.dias_ciclo for d in janela if d.dias_ciclo is not None]

    peso_total = sum((d.peso if d.peso is not None else 1.0) for d in docs)
    peso_feito = sum((d.peso if d.peso is not None else 1.0) for d in concluidos)

    motivos = {}
    for d in nao_aplicaveis:
        codigo = (d.motivo_na_codigo or "").strip() or "(sem motivo)"
        reg = motivos.setdefault(codigo, {"codigo": codigo,
                                          "label": MOTIVOS_NA.get(codigo, codigo),
                                          "n": 0})
        reg["n"] += 1

    aging = sorted(abertos, key=lambda d: d.dias_no_status, reverse=True)[:8]

    return jsonify({
        "janela_dias": dias,
        "setor": setor,
        "totais": {
            "total": len(docs),
            "abertos": len(abertos),
            "concluidos": len(concluidos),
            "atrasados": sum(1 for d in abertos if d.atrasado),
            "sem_responsavel": sum(1 for d in abertos if not d.responsaveis_nomes),
            "sem_prazo": sum(1 for d in abertos if not d.prazo),
            "wip": wip,
            "nao_aplicaveis": len(nao_aplicaveis),
        },
        "avanco": {
            "por_documento": round(100 * len(concluidos) / len(docs)) if docs else 0,
            # Ponderado: um manual de 300 páginas não vale o mesmo que um checklist.
            "ponderado": round(100 * peso_feito / peso_total) if peso_total else 0,
            "peso_total": round(peso_total, 1),
            "peso_concluido": round(peso_feito, 1),
        },
        "por_status": sorted(por_status.values(), key=lambda r: (-r["total"], r["status"])),
        "por_setor": {s: sum(1 for d in docs if d.setor == s)
                      for s in sorted({d.setor for d in docs})},
        "por_responsavel": sorted(carga.values(), key=lambda r: (-r["abertos"], r["nome"])),
        "throughput": {
            "concluidos": len(janela),
            "sem_data": sem_data,
            "por_semana": [{"semana": k, "n": semanas[k]} for k in sorted(semanas)],
        },
        "cycle_time": {
            "amostra": len(ciclos),
            "media": round(sum(ciclos) / len(ciclos), 1) if ciclos else None,
            "p50": _percentil(ciclos, 0.50),
            "p85": _percentil(ciclos, 0.85),
        },
        # equipamento_id acompanha o nome porque a ficha do dashboard é aberta
        # pelo equipamento (não existe modal de um documento isolado).
        "aging": [{"documento_id": d.id, "documento": d.documento,
                   "equipamento": d.equipamento, "equipamento_id": d.equipamento_id,
                   "status": d.status or "",
                   "setor": d.setor, "dias": d.dias_no_status,
                   "responsaveis": ", ".join(d.responsaveis_nomes)} for d in aging],
        "motivos_na": sorted(motivos.values(), key=lambda m: (-m["n"], m["codigo"])),
    }), 200


@documentos_bp.route("/api/documentos/alertas", methods=["GET"])
@jwt_required()
def alertas_documentos():
    """Fatos acionáveis derivados do que já está no banco.

    Mesmo formato dos alertas de projetos e de missões
    ({tipo, severidade, titulo, detalhe}) para que o front consuma os três com
    o mesmo componente.

    ?dias_parado=N (padrão 30 — documento é mais lento que cartão de kanban)
    ?setor=  restringe a um setor
    """
    dias_parado = max(1, request.args.get("dias_parado", default=30, type=int) or 30)
    setor = request.args.get("setor", "")

    q = Documento.query.filter(Documento.ativo == True, Documento.aplicavel == True)
    if setor:
        q = q.filter(Documento.setor == setor)
    docs = q.all()

    itens = []

    def add(doc, tipo, sev, titulo, detalhe):
        itens.append({
            "tipo": tipo, "severidade": sev, "titulo": titulo, "detalhe": detalhe,
            "documento_id": doc.id, "documento": (doc.documento or "").strip(),
            "equipamento": doc.equipamento or "",
            "equipamento_id": doc.equipamento_id, "setor": doc.setor or "",
            "status": doc.status or "",
        })

    hoje = datetime.now().date()
    for d in docs:
        if d.concluido:
            continue
        if d.atrasado:
            add(d, "documento_vencido", "critico", "Prazo vencido",
                f"previsto para {d.prazo.strftime('%d/%m/%Y')} · "
                f"{(hoje - d.prazo).days} dia(s) em atraso")
        if not d.responsaveis_nomes:
            add(d, "documento_sem_responsavel", "atencao", "Sem responsável",
                "ninguém atribuído — o documento não tem a quem cobrar")
        if d.dias_no_status >= dias_parado:
            add(d, "documento_parado", "atencao", "Sem movimentação",
                f"parado há {d.dias_no_status} dia(s) em \"{d.status}\"")
        if not d.prazo and d.status_global == "Em progresso":
            add(d, "documento_sem_prazo", "info", "Em andamento sem prazo",
                "trabalho em curso sem data alvo — nunca vai constar como atrasado")
        if not d.armazenamento_efetivo:
            add(d, "documento_sem_pasta", "info", "Sem pasta definida",
                "nem o documento nem o equipamento têm caminho de armazenamento")

    ordem = {"critico": 0, "atencao": 1, "info": 2}
    itens.sort(key=lambda a: (ordem.get(a["severidade"], 9), a["equipamento"],
                              a["documento"]))
    return jsonify({
        "alertas": itens,
        "total": len(itens),
        "criticos": sum(1 for i in itens if i["severidade"] == "critico"),
    }), 200


@documentos_bp.route("/api/documentos/<int:doc_id>/historico", methods=["GET"])
@jwt_required()
def historico_documento(doc_id):
    """Trilha do documento (mais recente primeiro) + tempo no status atual.

    `dias_no_status` é o aging: sem ele não dá para distinguir backlog novo de
    documento parado há dois anos — os dois aparecem como "Elaborar".
    """
    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc:
        return jsonify({"erro": "Não encontrado"}), 404
    linhas = (DocumentoHistorico.query
              .filter(DocumentoHistorico.documento_id == doc_id)
              .order_by(DocumentoHistorico.em.desc(), DocumentoHistorico.id.desc())
              .limit(100).all())
    ultimo_status = next((h for h in linhas if (h.evento or "status") == "status"), None)
    desde = ultimo_status.em if ultimo_status else (doc.updated_em or doc.criado_em)
    dias = (datetime.now() - desde).days if desde else None
    return jsonify({
        "documento_id": doc_id,
        "status": doc.status or "",
        "desde": desde.strftime("%d/%m/%Y %H:%M") if desde else "",
        "dias_no_status": dias,
        "historico": [h.to_dict() for h in linhas],
    }), 200


@documentos_bp.route("/api/documentos/responsaveis", methods=["GET"])
@jwt_required()
def listar_responsaveis_doc():
    """Usuários atribuíveis como responsável por um documento.

    `Documento.responsavel` é texto livre e estava preenchido em 2 de 522 linhas;
    o picker devolve gente real para o campo parar de ser digitação livre.
    """
    users = (User.query.filter(User.ativo == True)
             .order_by(User.nome).all())
    return jsonify([{"id": u.id, "nome": u.nome, "email": u.email, "role": u.role}
                    for u in users]), 200


@documentos_bp.route("/api/documentos/export", methods=["GET"])
@require_role("admin", "gestor", "tecnico")
def export_documentos():
    """CSV bruto dos documentos ativos — análise fora do sistema (Excel/BI).

    Aceita os mesmos filtros da listagem (`setor`, `q`) para exportar o recorte
    que está na tela. Sem isto, o único export do módulo era o PDF de KPIs.
    """
    q = norm(request.args.get("q", ""))
    setor = request.args.get("setor", "")
    query = Documento.query.filter(Documento.ativo == True)
    if setor:
        query = query.filter(Documento.setor == setor)
    rows = query.order_by(Documento.equipamento, Documento.tipo_doc).all()
    if q:
        rows = [d for d in rows
                if q in norm(" ".join(str(x or "") for x in
                                      (d.equipamento, d.documento, d.codigo_doc,
                                       d.sku, d.responsavel, d.tipo_doc, d.fabricante)))]

    cols = [
        ("equipamento", "Equipamento"), ("sku", "SKU"), ("fabricante", "Fabricante"),
        ("familia", "Família"), ("anvisa", "ANVISA"),
        ("setor", "Setor"), ("tipo_doc", "Tipo"), ("tipo_doc_label", "Tipo (rótulo)"),
        ("codigo_doc", "Código"), ("documento", "Documento"),
        ("status", "Status"), ("status_global", "Status global"),
        ("responsavel", "Responsável"),
        ("aplicavel", "Aplicável"), ("motivo_na_label", "Motivo N/A"),
        ("prazo", "Prazo"), ("dias_para_prazo", "Dias p/ prazo"), ("atrasado", "Atrasado"),
        ("data_treinamento", "Data treinamento"), ("data_homologacao", "Data homologação"),
        ("armazenamento_efetivo", "Armazenamento"),
        ("criado_em", "Criado em"), ("updated_em", "Atualizado em"),
    ]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([rotulo for _, rotulo in cols])
    for d in rows:
        j = d.to_dict()
        w.writerow([("Sim" if j.get(c) is True else "Não" if j.get(c) is False
                     else ("" if j.get(c) is None else j.get(c))) for c, _ in cols])
    out = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    return send_file(out, mimetype="text/csv", as_attachment=True,
                     download_name=f"documentos_{datetime.now():%Y%m%d}.csv")


@documentos_bp.route("/api/documentos/diagnostico", methods=["GET"])
@require_role("admin", "gestor")
def diagnostico_documentos():
    """Consistência entre o cadastro e o que existe de fato (ver `diagnostico.py`).

    Confronta as DUAS fontes de arquivo — a pasta de rede e a cópia hospedada na
    plataforma — porque ter uma das duas basta. O caminho considerado é o
    EFETIVO (herdado do grupo ou do equipamento), não a exceção da linha.

    Fora do escopo, de propósito: documento inativo e documento marcado N/A não
    devem ter arquivo, então acusá-los seria ruído garantido.
    """
    docs = (Documento.query
            .filter(Documento.ativo == True, Documento.aplicavel == True)
            .all())
    entrada = [{
        "id":             d.id,
        "equipamento":    d.equipamento or "",
        "documento":      d.documento or "",
        "tipo_doc_label": d.tipo_doc_label,
        "setor":          d.setor or "",
        "status":         d.status or "",
        "concluido":      d.concluido,
        "caminho":        d.armazenamento_efetivo,
        "arquivos":       [{"id": a.id, "sha256": a.sha256,
                            "nome": a.nome_original or ""}
                           for a in d.arquivos_ativos],
    } for d in docs]
    return jsonify(diagnostico.diagnosticar(entrada)), 200


@documentos_bp.route("/api/documentos/abrir-pasta", methods=["POST"])
@jwt_required()
def abrir_pasta():
    data = request.get_json(silent=True) or {}
    caminho = (data.get("caminho") or "").strip()
    if not caminho:
        return jsonify({"erro": "Caminho não fornecido"}), 400

    import os
    import subprocess
    import socket

    # Canoniza ANTES de qualquer checagem: é aqui que `P:\...` colado da barra de
    # endereço do Explorer vira a UNC que a allowlist e o serviço reconhecem.
    caminho_norm = caminhos.normalizar(caminho)

    # 0. Segurança: só caminhos dentro das raízes permitidas (mesma allowlist
    # das rotas de arquivos). Sem isto, qualquer usuário autenticado poderia
    # sondar caminhos arbitrários do servidor (C:\Users, D:\backups) pelo loop
    # de resolução de ancestral, ou apontar para um share UNC de terceiro
    # (\\atacante\share) e forçar o servidor a autenticar via SMB.
    if not _validar_caminho_arquivo(caminho_norm):
        return jsonify({"erro": "Caminho fora das pastas permitidas"}), 403

    # 1. Determina se o cliente está na mesma máquina física que o servidor
    client_ip = request.remote_addr
    is_local = False
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        is_local = True
    else:
        try:
            hostname = socket.gethostname()
            server_ips = socket.gethostbyname_ex(hostname)[2]
            # Adiciona IPs conhecidos de loopback
            server_ips.extend(["127.0.0.1", "::1"])
            if client_ip in server_ips:
                is_local = True
        except:
            pass

    # 2. Resolve o caminho (busca o arquivo/pasta ou o ancestral mais próximo
    # existente). `caminhos.resolver` tenta a UNC e a unidade mapeada: a pasta
    # existe mesmo quando ESTE processo só enxerga uma das duas formas.
    caminho_final = None
    tipo_abertura = "direto"

    achado = caminhos.resolver(caminho_norm)
    if achado:
        caminho_final = achado
        tipo_abertura = "direto"
    else:
        parent = os.path.dirname(caminho_norm)
        while parent:
            if not parent.strip():
                break
            achado = caminhos.resolver(parent)
            if achado and os.path.isdir(achado):
                caminho_final = achado
                tipo_abertura = "ancestral"
                break
            next_parent = os.path.dirname(parent)
            if next_parent == parent:
                break            # chegou à raiz do volume sem achar diretório
            parent = next_parent

    if not caminho_final:
        return jsonify({"erro": f"Caminho não encontrado ou inacessível: {caminho}"}), 404

    # 2b. Revalida o ancestral resolvido: a subida por dirname pode ter escalado
    # acima da raiz permitida (ex.: pai existente fora do allowlist).
    if not _validar_caminho_arquivo(caminho_final):
        return jsonify({"erro": "Caminho fora das pastas permitidas"}), 403

    # 3. Executa a abertura física se for acesso local
    if is_local:
        try:
            if os.path.isdir(caminho_final):
                os.startfile(caminho_final)
            else:
                subprocess.Popen(["explorer", f"/select,{caminho_final}"])
            return jsonify({
                "mensagem": "Pasta aberta com sucesso",
                "caminho_aberto": caminho_final,
                "local": True,
                "tipo": tipo_abertura
            }), 200
        except Exception as e:
            return jsonify({"erro": f"Erro ao abrir pasta: {str(e)}"}), 500
    else:
        # Acesso remoto: não abre no servidor, devolve o caminho para o cliente
        # colar. Na forma COM LETRA (P:\...) — é o mapeamento da estação dele que
        # vai abrir a pasta, e colar a UNC do share administrativo costuma pedir
        # credencial de novo.
        return jsonify({
            "mensagem": "Acesso remoto detectado. Caminho resolvido pronto para cópia.",
            "caminho_aberto": caminhos.para_exibicao(caminho_final),
            "caminho_unc": caminhos.normalizar(caminho_final),
            "caminho_original": caminho,
            "local": False,
            "tipo": tipo_abertura
        }), 200

# ── API — VISUALIZAR ARQUIVOS DO EQUIPAMENTO ──────────────────────────────────
def _validar_caminho_arquivo(caminho):
    """Caminho na forma canônica se estiver dentro de uma raiz permitida, senão None.

    Lê ARQUIVOS_ROOTS do módulo (e não a constante de `caminhos`) para os testes
    poderem trocar a allowlist por uma pasta temporária via patch.
    """
    return caminhos.validar(caminho, ARQUIVOS_ROOTS)

@documentos_bp.route("/api/documentos/arquivos", methods=["GET"])
@jwt_required()
def listar_arquivos():
    """Lista os arquivos da pasta de armazenamento de um equipamento,
    classificando por IT / Checklist / Outros (até 2 níveis de subpasta)."""
    caminho = (request.args.get("caminho") or "").strip()
    if not caminho:
        return jsonify({"erro": "Caminho não fornecido"}), 400
    pasta = _validar_caminho_arquivo(caminho)
    if not pasta:
        return jsonify({"erro": "Caminho fora das pastas permitidas"}), 403
    # `pasta` é a forma canônica (para comparar); `real` é a variante que este
    # processo consegue de fato abrir — nem sempre a mesma.
    real = caminhos.resolver(pasta)
    if not real or not os.path.isdir(real):
        return jsonify({"erro": "Pasta não encontrada ou inacessível"}), 404
    pasta = real

    arquivos = []
    try:
        for base, dirs, files in os.walk(pasta):
            depth = base[len(pasta):].count(os.sep)
            if depth >= 2:
                dirs[:] = []
                continue
            for nome in files:
                full = os.path.join(base, nome)
                ext = os.path.splitext(nome)[1].lower()
                low = nome.lower()
                if low.startswith(("it.", "it ", "it-", "it_")):
                    cat = "IT"
                elif low.startswith("rsq") or "checklist" in low or "check list" in low:
                    cat = "Checklist"
                else:
                    cat = "Outros"
                try:
                    st = os.stat(full)
                    tamanho = st.st_size
                    mod = datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M")
                except Exception:
                    tamanho, mod = 0, ""
                arquivos.append({
                    "nome": nome,
                    # canônico: o cliente devolve este valor em /arquivo e ele
                    # precisa validar independentemente da forma que abrimos aqui
                    "caminho": caminhos.normalizar(full),
                    "rel": os.path.relpath(full, pasta),
                    "ext": ext.lstrip("."),
                    "tamanho": tamanho,
                    "modificado": mod,
                    "categoria": cat,
                    "inline": ext in _EXT_INLINE,
                })
                if len(arquivos) >= 300:
                    break
            if len(arquivos) >= 300:
                break
    except Exception as e:
        return jsonify({"erro": f"Erro ao listar arquivos: {str(e)}"}), 500

    ordem = {"IT": 0, "Checklist": 1, "Outros": 2}
    arquivos.sort(key=lambda a: (ordem.get(a["categoria"], 3), a["nome"].lower()))
    # devolve a pasta na forma com letra: é ela que o usuário reconhece e cola
    return jsonify({"pasta": caminhos.para_exibicao(pasta), "arquivos": arquivos}), 200

@documentos_bp.route("/api/documentos/arquivo", methods=["GET"])
@jwt_required()
def servir_arquivo():
    """Serve um arquivo individual: PDF/imagens inline (preview no navegador),
    demais formatos como download. Restrito às raízes permitidas."""
    caminho = (request.args.get("caminho") or "").strip()
    if not caminho:
        return jsonify({"erro": "Caminho não fornecido"}), 400
    alvo = _validar_caminho_arquivo(caminho)
    if not alvo:
        return jsonify({"erro": "Caminho fora das pastas permitidas"}), 403
    real = caminhos.resolver(alvo)
    if not real or not os.path.isfile(real):
        return jsonify({"erro": "Arquivo não encontrado"}), 404
    ext = os.path.splitext(real)[1].lower()
    inline = (ext in _EXT_INLINE) and request.args.get("download") != "1"
    try:
        return send_file(
            real,
            as_attachment=not inline,
            download_name=os.path.basename(real),
            conditional=True,
        )
    except Exception as e:
        return jsonify({"erro": f"Erro ao abrir arquivo: {str(e)}"}), 500

# ── API — ARQUIVOS HOSPEDADOS NA PLATAFORMA ───────────────────────────────────
# Diferente do bloco acima: lá o arquivo mora na rede e o caminho vem do cliente
# (daí a allowlist); aqui o arquivo foi ENVIADO para o DocTrack e o caminho é
# derivado do SHA gravado no banco — o cliente nunca escolhe caminho nenhum.
#
# Permissão: enviar/substituir/remover é de admin+gestor (a hierarquia que o
# sistema já tem). Ler e baixar é de qualquer autenticado — quem acessa o
# DocTrack já acessa as pastas da rede, então restringir download seria teatro.

def _sha_orfao(sha, ignorar_id=None, ignorar_anexo_id=None):
    """True se nenhuma linha ATIVA ainda aponta para este blob (dedup por conteúdo).

    Linha inativa não segura o blob: ela sobrevive só para o histórico (quem
    enviou, quando, com que nome) e o conteúdo é justamente o que se quis
    apagar. Quem tentar baixá-la recebe 404 em `servir_arquivo_doc`.

    As DUAS tabelas contam. O blob é endereçado por conteúdo e compartilhado
    entre elas: o mesmo PDF enviado como anexo de documento e como doc agregado
    do equipamento ocupa um único arquivo em disco. Olhar só uma tabela faria a
    remoção de um lado apagar o conteúdo que o outro ainda exibe.
    """
    q = DocumentoArquivo.query.filter_by(sha256=sha, ativo=True)
    if ignorar_id is not None:
        q = q.filter(DocumentoArquivo.id != ignorar_id)
    if q.first() is not None:
        return False

    qa = EquipamentoArquivo.query.filter_by(sha256=sha, ativo=True)
    if ignorar_anexo_id is not None:
        qa = qa.filter(EquipamentoArquivo.id != ignorar_anexo_id)
    return qa.first() is None


@documentos_bp.route("/api/documentos/<int:doc_id>/arquivos", methods=["GET"])
@jwt_required()
def listar_arquivos_doc(doc_id):
    """Todos os arquivos já enviados para este documento (o mais novo primeiro,
    inclusive os removidos — ativo=False — para fins de histórico)."""
    doc = db.session.get(Documento, doc_id)
    if not doc or not doc.ativo:
        return jsonify({"erro": "Documento não encontrado"}), 404
    itens = (DocumentoArquivo.query
             .filter_by(documento_id=doc.id)
             .order_by(DocumentoArquivo.versao.desc())
             .all())
    return jsonify({"arquivos": [a.to_dict() for a in itens]}), 200


@documentos_bp.route("/api/documentos/<int:doc_id>/arquivos", methods=["POST"])
@require_role("admin", "gestor")
def enviar_arquivo_doc(doc_id):
    """Adiciona um arquivo a este documento (multipart/form-data).

    Adiciona, não substitui: um documento comporta vários arquivos convivendo
    (manual PT e ES, IT e o checklist dela). Para trocar um, remove-se e
    envia-se o novo.
    """
    caller = get_jwt_identity()
    doc = db.session.get(Documento, doc_id)
    if not doc or not doc.ativo:
        return jsonify({"erro": "Documento não encontrado"}), 404

    enviado = request.files.get("arquivo")
    if not enviado or not (enviado.filename or "").strip():
        return jsonify({"erro": "Nenhum arquivo enviado"}), 400

    nome = os.path.basename(enviado.filename.strip())
    if not arquivos_store.extensao_ok(nome):
        permitidas = ", ".join(sorted(e.lstrip(".") for e in arquivos_store.EXT_PERMITIDAS))
        return jsonify({"erro": f"Formato não aceito. Aceitos: {permitidas}"}), 415

    try:
        sha, tamanho = arquivos_store.guardar(enviado.stream, nome)
    except arquivos_store.ArquivoGrandeDemais:
        return jsonify({"erro": f"Arquivo maior que {arquivos_store.MAX_MB} MB"}), 413
    except OSError as e:
        return jsonify({"erro": f"Erro ao gravar o arquivo: {str(e)}"}), 500

    # Sequencial de envio dentro do documento (conta também os removidos, para
    # nunca repetir número na trilha de auditoria).
    ultimo = max((a.versao or 0 for a in (doc.arquivos or [])), default=0)

    arq = DocumentoArquivo(
        documento_id=doc.id,
        versao=ultimo + 1,
        sha256=sha,
        nome_original=nome,
        ext=arquivos_store.ext_de(nome),
        mime=arquivos_store.mime_de(nome),
        tamanho=tamanho,
        observacao=(request.form.get("observacao") or "").strip()[:300],
        enviado_por=caller,
    )
    db.session.add(arq)
    db.session.flush()

    log_action(caller, "UPLOAD", entidade=doc.documento, campo="arquivo",
               antigo="", novo=nome, documento_id=doc.id, ip=get_client_ip())
    db.session.refresh(doc)
    return jsonify({"documento": doc.to_dict(), "arquivo": arq.to_dict()}), 201


@documentos_bp.route("/api/documentos/arquivos/<int:arq_id>/conteudo", methods=["GET"])
@jwt_required()
def servir_arquivo_doc(arq_id):
    """Serve o arquivo hospedado. PDF/imagem inline (para o visor da plataforma),
    o resto como download. `?download=1` força o download em qualquer formato."""
    arq = db.session.get(DocumentoArquivo, arq_id)
    if not arq:
        return jsonify({"erro": "Arquivo não encontrado"}), 404
    # A linha inativa sobrevive para o histórico, o conteúdo não. Sem este
    # teste, um arquivo removido cujo blob ficou vivo por dedup (outro
    # documento com o mesmo conteúdo) continuaria baixável pelo id antigo.
    if not arq.ativo:
        return jsonify({"erro": "Arquivo removido"}), 404
    # O caminho vem do SHA gravado, nunca da requisição.
    real = arquivos_store.caminho_de(arq.sha256)
    if not os.path.isfile(real):
        return jsonify({"erro": "Arquivo não está mais disponível no servidor"}), 404
    inline = (arquivos_store.abre_inline(arq.nome_original)
              and request.args.get("download") != "1")
    try:
        return send_file(
            real,
            as_attachment=not inline,
            download_name=arq.nome_original or f"documento{arq.ext or ''}",
            mimetype=arq.mime or None,
            conditional=True,
        )
    except Exception as e:
        return jsonify({"erro": f"Erro ao abrir arquivo: {str(e)}"}), 500


@documentos_bp.route("/api/documentos/arquivos/<int:arq_id>", methods=["DELETE"])
@require_role("admin", "gestor")
def remover_arquivo_doc(arq_id):
    """Remove a versão. Soft delete primeiro; o blob só sai se ficar órfão.

    A ordem importa: em Windows o `os.remove` pode falhar se alguém estiver
    baixando o arquivo naquele instante. Marcando inativo antes, a falha física
    deixa no máximo um blob órfão — nunca uma linha apontando para o vazio.
    """
    caller = get_jwt_identity()
    arq = db.session.get(DocumentoArquivo, arq_id)
    if not arq:
        return jsonify({"erro": "Arquivo não encontrado"}), 404
    if not arq.ativo:
        return jsonify({"erro": "Arquivo já removido"}), 404
    doc = db.session.get(Documento, arq.documento_id)
    doc_id, nome, sha = arq.documento_id, arq.nome_original, arq.sha256

    # Soft delete: a linha fica para o histórico e para segurar o número de
    # versão (apagá-la fazia o próximo envio voltar a ser v1, repetindo número
    # numa trilha de auditoria).
    arq.ativo = False

    # log_action é quem faz o commit — o blob só sai DEPOIS dele. Na ordem
    # inversa, um commit que falhasse deixaria a linha viva apontando para um
    # arquivo que já não existe; assim, o pior caso é um blob órfão.
    log_action(caller, "DELETE", entidade=(doc.documento if doc else ""),
               campo="arquivo", antigo=nome, novo="",
               documento_id=doc_id, ip=get_client_ip())
    if _sha_orfao(sha, ignorar_id=arq_id):
        arquivos_store.remover(sha)

    if doc is not None:
        db.session.refresh(doc)
        return jsonify({"documento": doc.to_dict()}), 200
    return jsonify({"ok": True}), 200


# ── API — STATUS FLOW ─────────────────────────────────────────────────────────
@documentos_bp.route("/api/documento/<int:doc_id>/status", methods=["PUT"])
@require_role("admin", "gestor", "tecnico")
def update_status(doc_id):
    caller = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    novo = data.get("status", "")
    expected_version = data.get("version")

    doc = Documento.query.filter(Documento.ativo == True, Documento.id == doc_id).first()
    if not doc: return jsonify({"erro": "Não encontrado"}), 404

    if expected_version is not None and doc.version != expected_version:
        return jsonify({"erro": "Documento alterado por outro usuário.", "current_version": doc.version, "documento": doc.to_dict()}), 409

    setor_status_list = STATUS_MAP.get(doc.setor, [])
    if novo not in setor_status_list:
        return jsonify({"erro": f"Status inválido para o setor {doc.setor}. Use: {', '.join(setor_status_list)}"}), 400

    antigo = doc.status
    doc.status = novo
    doc.updated_em = datetime.now()
    doc.version = (doc.version or 0) + 1
    if novo != antigo:
        _marcar_troca_status(doc, caller, antigo)
        _registrar_historico(doc, caller, status_antigo=antigo, status_novo=novo)
    # documento é a fonte da verdade: move os cartões vinculados no kanban
    # (mesma transação; eventos emitidos após o commit)
    eventos_sync = sincronizar_cartoes_documento(doc, caller) if novo != antigo else []
    db.session.commit()
    log_action(caller, "STATUS_CHANGE", entidade=doc.documento, campo="status", antigo=antigo, novo=novo, documento_id=doc.id, ip=get_client_ip())
    _emit(EventType.DOCUMENT_STATUS_UPDATED,
          {"documento_id": doc.id, "old_value": antigo, "new_value": novo, "status_global": doc.status_global, "setor": doc.setor, "equipamento": doc.equipamento},
          caller)
    emitir_eventos_sync(eventos_sync, caller)
    return jsonify({"mensagem": f"Status atualizado", "documento": doc.to_dict()}), 200


# ── API — ANEXOS DO EQUIPAMENTO (docs agregados + software/firmware) ─────────
# Ficam aqui, e não no bloco de equipamentos do servidor.py, porque tudo que
# torna estas rotas delicadas — allowlist de extensão, blob endereçado por
# conteúdo, dedup, soft delete — já mora neste módulo. Separá-las significaria
# manter duas cópias da mesma regra de arquivo.

def _anexo_ordenavel(a):
    """Chave de ordenação 'mais novo primeiro' (usada com reverse=True).

    Para software/firmware o que vale é a data de liberação do FABRICANTE, não a
    de upload: quem cadastra hoje a versão do ano passado não pode empurrá-la
    para o topo do repositório. Sem data de release, a linha cai para o fim
    (string vazia é menor que qualquer data ISO) e o desempate é o envio.
    """
    return (a.data_release or "", a.enviado_em or datetime.min)


def _anexos_do(equip_id, categoria=None):
    q = EquipamentoArquivo.query.filter_by(equipamento_id=equip_id, ativo=True)
    if categoria:
        q = q.filter_by(categoria=categoria)
    return sorted(q.all(), key=_anexo_ordenavel, reverse=True)


@documentos_bp.route("/api/equipamentos/<int:equip_id>/anexos", methods=["GET"])
@jwt_required()
def listar_anexos_equipamento(equip_id):
    """Anexos do equipamento. `?categoria=` filtra; sem ele, vêm todos.

    Uma chamada só devolve as duas abas (agregados e repositório) — o modal abre
    com os dois painéis prontos em vez de disparar um fetch por aba.
    """
    equip = db.session.get(Equipamento, equip_id)
    if not equip or not equip.ativo:
        return jsonify({"erro": "Equipamento não encontrado"}), 404

    categoria = (request.args.get("categoria") or "").strip()
    if categoria and categoria not in EquipamentoArquivo.CATEGORIAS:
        return jsonify({"erro": "Categoria inválida"}), 400

    itens = _anexos_do(equip.id, categoria or None)
    return jsonify({"anexos": [a.to_dict() for a in itens]}), 200


@documentos_bp.route("/api/equipamentos/<int:equip_id>/anexos", methods=["POST"])
@require_role("admin", "gestor")
def enviar_anexo_equipamento(equip_id):
    """Envia um doc agregado ou uma versão de software/firmware (multipart).

    A allowlist depende da categoria: 'agregado' aceita o mesmo que um documento
    (PDF/Office/imagem) e nada mais; 'software' e 'firmware' aceitam TAMBÉM os
    binários (ver `arquivos_store.EXT_BINARIAS`), com teto próprio de tamanho.
    Aceitar binário em 'agregado' faria a categoria virar a porta larga por onde
    tudo entra.
    """
    # ANTES de qualquer leitura do corpo (ler `request.form` já dispara o parse):
    # esta é a única rota que aceita meio giga, e o teto do app segue em 80 MB.
    # A categoria só se conhece depois do parse, então o corpo entra sob o teto
    # grande e o teto certo é aplicado na gravação, em `guardar(limite=...)` —
    # e a rota é de admin/gestor, não de qualquer autenticado.
    request.max_content_length = arquivos_store.MAX_BIN_BYTES

    caller = get_jwt_identity()
    equip = db.session.get(Equipamento, equip_id)
    if not equip or not equip.ativo:
        return jsonify({"erro": "Equipamento não encontrado"}), 404

    categoria = (request.form.get("categoria") or "agregado").strip()
    if categoria not in EquipamentoArquivo.CATEGORIAS:
        return jsonify({"erro": "Categoria inválida"}), 400

    enviado = request.files.get("arquivo")
    if not enviado or not (enviado.filename or "").strip():
        return jsonify({"erro": "Nenhum arquivo enviado"}), 400

    versionada = categoria in EquipamentoArquivo.CATEGORIAS_VERSIONADAS
    permitidas = (arquivos_store.EXT_PERMITIDAS | arquivos_store.EXT_BINARIAS
                  if versionada else arquivos_store.EXT_PERMITIDAS)
    limite = arquivos_store.MAX_BIN_BYTES if versionada else arquivos_store.MAX_BYTES
    limite_mb = arquivos_store.MAX_BIN_MB if versionada else arquivos_store.MAX_MB

    nome = os.path.basename(enviado.filename.strip())
    if not arquivos_store.extensao_ok(nome, permitidas):
        aceitos = ", ".join(sorted(e.lstrip(".") for e in permitidas))
        return jsonify({"erro": f"Formato não aceito. Aceitos: {aceitos}"}), 415

    data_release = (request.form.get("data_release") or "").strip()
    ok_data, _ = _parse_data(data_release)
    if not ok_data:
        return jsonify({"erro": "Data de liberação inválida (use AAAA-MM-DD)"}), 400

    try:
        sha, tamanho = arquivos_store.guardar(enviado.stream, nome,
                                              permitidas=permitidas, limite=limite)
    except arquivos_store.ArquivoGrandeDemais:
        return jsonify({"erro": f"Arquivo maior que {limite_mb} MB"}), 413
    except OSError as e:
        return jsonify({"erro": f"Erro ao gravar o arquivo: {str(e)}"}), 500

    anexo = EquipamentoArquivo(
        equipamento_id=equip.id,
        categoria=categoria,
        titulo=(request.form.get("titulo") or "").strip()[:200],
        versao_rotulo=(request.form.get("versao_rotulo") or "").strip()[:60] if versionada else "",
        data_release=data_release if versionada else "",
        notas=(request.form.get("notas") or "").strip(),
        sha256=sha,
        nome_original=nome,
        ext=arquivos_store.ext_de(nome),
        mime=arquivos_store.mime_de(nome),
        tamanho=tamanho,
        enviado_por=caller,
    )
    db.session.add(anexo)
    db.session.flush()

    log_action(caller, "UPLOAD", entidade=equip.nome, campo=f"anexo:{categoria}",
               antigo="", novo=nome, ip=get_client_ip())
    return jsonify({"anexo": anexo.to_dict()}), 201


@documentos_bp.route("/api/equipamentos/anexos/<int:anexo_id>", methods=["PATCH"])
@require_role("admin", "gestor")
def editar_anexo_equipamento(anexo_id):
    """Corrige os metadados (título, versão, data, notas) sem reenviar o arquivo.

    O binário não muda: errar o rótulo da versão é o erro provável, e reenviar
    300 MB por causa de um "v2.4.1" digitado como "v2.41" seria absurdo.
    """
    caller = get_jwt_identity()
    anexo = db.session.get(EquipamentoArquivo, anexo_id)
    if not anexo or not anexo.ativo:
        return jsonify({"erro": "Anexo não encontrado"}), 404

    data = request.get_json(silent=True) or {}
    versionada = anexo.categoria in EquipamentoArquivo.CATEGORIAS_VERSIONADAS

    if "data_release" in data and versionada:
        valor = (data.get("data_release") or "").strip()
        ok_data, _ = _parse_data(valor)
        if not ok_data:
            return jsonify({"erro": "Data de liberação inválida (use AAAA-MM-DD)"}), 400
        anexo.data_release = valor
    if "titulo" in data:
        anexo.titulo = (data.get("titulo") or "").strip()[:200]
    if "versao_rotulo" in data and versionada:
        anexo.versao_rotulo = (data.get("versao_rotulo") or "").strip()[:60]
    if "notas" in data:
        anexo.notas = (data.get("notas") or "").strip()

    log_action(caller, "UPDATE", entidade=(anexo.titulo or anexo.nome_original),
               campo=f"anexo:{anexo.categoria}", ip=get_client_ip())
    return jsonify({"anexo": anexo.to_dict()}), 200


@documentos_bp.route("/api/equipamentos/anexos/<int:anexo_id>/conteudo", methods=["GET"])
@jwt_required()
def servir_anexo_equipamento(anexo_id):
    """Serve o anexo. PDF/imagem podem abrir inline; binário, NUNCA.

    O `as_attachment` forçado no binário não é detalhe de conforto: com mime
    genérico e Content-Disposition de anexo, o navegador não tem como interpretar
    o conteúdo — ele desce para o disco e a decisão de executá-lo é de quem
    baixou, fora da plataforma.
    """
    anexo = db.session.get(EquipamentoArquivo, anexo_id)
    if not anexo or not anexo.ativo:
        return jsonify({"erro": "Anexo não encontrado"}), 404

    real = arquivos_store.caminho_de(anexo.sha256)
    if not os.path.isfile(real):
        return jsonify({"erro": "Arquivo não está mais disponível no servidor"}), 404

    binario = arquivos_store.ext_de(anexo.nome_original) in arquivos_store.EXT_BINARIAS
    inline = (not binario
              and arquivos_store.abre_inline(anexo.nome_original)
              and request.args.get("download") != "1")
    try:
        return send_file(
            real,
            as_attachment=not inline,
            download_name=anexo.nome_original or f"anexo{anexo.ext or ''}",
            mimetype=("application/octet-stream" if binario else (anexo.mime or None)),
            conditional=True,
        )
    except Exception as e:
        return jsonify({"erro": f"Erro ao abrir arquivo: {str(e)}"}), 500


@documentos_bp.route("/api/equipamentos/anexos/<int:anexo_id>", methods=["DELETE"])
@require_role("admin", "gestor")
def remover_anexo_equipamento(anexo_id):
    """Remove o anexo. Soft delete primeiro; o blob só sai se ficar órfão —
    mesma ordem (e mesmo motivo) do `remover_arquivo_doc`."""
    caller = get_jwt_identity()
    anexo = db.session.get(EquipamentoArquivo, anexo_id)
    if not anexo:
        return jsonify({"erro": "Anexo não encontrado"}), 404
    if not anexo.ativo:
        return jsonify({"erro": "Anexo já removido"}), 404

    equip = db.session.get(Equipamento, anexo.equipamento_id)
    nome, sha, categoria = anexo.nome_original, anexo.sha256, anexo.categoria
    anexo.ativo = False

    log_action(caller, "DELETE", entidade=(equip.nome if equip else ""),
               campo=f"anexo:{categoria}", antigo=nome, novo="", ip=get_client_ip())
    if _sha_orfao(sha, ignorar_anexo_id=anexo_id):
        arquivos_store.remover(sha)

    return jsonify({"ok": True}), 200
