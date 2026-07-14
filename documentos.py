"""
documentos.py — Blueprint de CRUD de Documentos + acesso a arquivos do equipamento.

Rotas:
  GET    /api/documentos                 — lista (filtro por setor + busca livre)
  GET    /api/documentos/<id>            — detalhe
  POST   /api/documentos                 — criar (gera os 9 tipos canônicos)
  PATCH  /api/documentos/<id>            — editar campos do próprio documento
  DELETE /api/documentos/<id>            — soft delete (admin/gestor)
  POST   /api/documentos/abrir-pasta     — abre a pasta no servidor (acesso local)
  GET    /api/documentos/arquivos        — lista arquivos da pasta do equipamento
  GET    /api/documentos/arquivo         — serve um arquivo (preview/download)
  PUT    /api/documento/<id>/status      — troca de status com checagem de versão

Identidade (equipamento / SKU / fabricante) é canônica no Equipamento e imutável
pelo documento — ver módulo Equipamentos.
"""
import os
import json
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import (
    db, Documento, Equipamento, AuditLog,
    SETORES, STATUS_MAP,
    TIPOS_DOC_PRE, TIPOS_DOC_FABRICANTE, TIPOS_DOC_TODOS, TIPOS_DOC_OPCIONAIS,
    SETOR_DO_TIPO, TIPOS_DOC_LABELS,
)
from auth import require_role, log_action, get_client_ip
from event_bus import EventType
from utils import norm
# Sync Documento → Cartão (import acíclico: missoes.py só importa models/auth)
from missoes import sincronizar_cartoes_documento, emitir_eventos_sync

documentos_bp = Blueprint("documentos", __name__)

# Raízes permitidas para visualizar/baixar arquivos dos equipamentos.
# Configurável via DOCTRACK_FILE_ROOTS (separado por ';'). Inclui tanto a forma
# UNC (\\loccus-srv03\Projetos$\Engenharia) quanto a letra de unidade mapeada
# (P:\Engenharia), pois os caminhos podem estar gravados em qualquer um dos
# formatos e um serviço Windows só enxerga o caminho UNC.
ARQUIVOS_ROOTS = [
    r.strip() for r in os.environ.get(
        "DOCTRACK_FILE_ROOTS",
        r"\\loccus-srv03\Projetos$\Engenharia;P:\Engenharia",
    ).split(";") if r.strip()
]

_EXT_INLINE = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".txt"}


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
                armazenamento_base=data.get("armazenamento", ""),
            )
            db.session.add(equip_obj)
            db.session.flush()
        else:
            if sku and not equip_obj.sku:
                equip_obj.sku = sku
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
            obs_treinamento=data.get("obs_treinamento", "") if is_sel else "",
            obs_homologacao=data.get("obs_homologacao", "") if is_sel else "",
            armazenamento=data.get("armazenamento", "") if is_sel else (equip_obj.armazenamento_base if equip_obj else ""),
        )
        if is_sel:
            if data.get("data_treinamento"):
                try: novo.data_treinamento = datetime.strptime(data["data_treinamento"], "%Y-%m-%d")
                except: pass
            if data.get("data_homologacao"):
                try: novo.data_homologacao = datetime.strptime(data["data_homologacao"], "%Y-%m-%d")
                except: pass
        db.session.add(novo)
        if is_sel:
            doc = novo

    db.session.commit()
    if doc is None:   # tipo selecionado já existia e nada foi criado
        doc = existentes.get(selected_tipo) or next(iter(existentes.values()), None)

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

    # tipo_doc foi retirado dos campos editáveis: é imutável — parte do invariante
    # dos 9 tipos por equipamento e da coerência com SETOR_DO_TIPO (trocar o tipo
    # não moveria o setor junto). O tipo nasce fixo na criação.

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

    doc.updated_em = datetime.now()
    doc.version = (doc.version or 0) + 1
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

    caminho_norm = os.path.normpath(caminho)

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

    # 2. Resolve o caminho (busca o arquivo/pasta ou o ancestral mais próximo existente)
    caminho_final = None
    tipo_abertura = "direto"

    if os.path.exists(caminho_norm):
        caminho_final = caminho_norm
        tipo_abertura = "direto"
    else:
        parent = os.path.dirname(caminho_norm)
        while parent:
            if not parent.strip():
                break
            if os.path.exists(parent) and os.path.isdir(parent):
                caminho_final = parent
                tipo_abertura = "ancestral"
                break
            next_parent = os.path.dirname(parent)
            if next_parent == parent:
                if os.path.exists(parent) and os.path.isdir(parent):
                    caminho_final = parent
                    tipo_abertura = "raiz"
                break
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
        # Se for acesso remoto, não abre no servidor, mas retorna o caminho resolvido para o cliente copiar
        return jsonify({
            "mensagem": "Acesso remoto detectado. Caminho resolvido pronto para cópia.",
            "caminho_aberto": caminho_final,
            "caminho_original": caminho,
            "local": False,
            "tipo": tipo_abertura
        }), 200

# ── API — VISUALIZAR ARQUIVOS DO EQUIPAMENTO ──────────────────────────────────
def _validar_caminho_arquivo(caminho):
    """Resolve o caminho e garante que está dentro de uma raiz permitida.
    Retorna o caminho real (absoluto) ou None se inválido/fora das raízes."""
    if not caminho:
        return None
    try:
        real = os.path.realpath(os.path.abspath(caminho))
    except Exception:
        return None
    nreal = os.path.normcase(real)
    for root in ARQUIVOS_ROOTS:
        try:
            nroot = os.path.normcase(os.path.realpath(os.path.abspath(root)))
            if os.path.commonpath([nreal, nroot]) == nroot:
                return real
        except ValueError:
            continue  # caminhos em drives diferentes
        except Exception:
            continue
    return None

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
    if not os.path.isdir(pasta):
        return jsonify({"erro": "Pasta não encontrada ou inacessível"}), 404

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
                    "caminho": full,
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
    return jsonify({"pasta": pasta, "arquivos": arquivos}), 200

@documentos_bp.route("/api/documentos/arquivo", methods=["GET"])
@jwt_required()
def servir_arquivo():
    """Serve um arquivo individual: PDF/imagens inline (preview no navegador),
    demais formatos como download. Restrito às raízes permitidas."""
    caminho = (request.args.get("caminho") or "").strip()
    if not caminho:
        return jsonify({"erro": "Caminho não fornecido"}), 400
    real = _validar_caminho_arquivo(caminho)
    if not real:
        return jsonify({"erro": "Caminho fora das pastas permitidas"}), 403
    if not os.path.isfile(real):
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
