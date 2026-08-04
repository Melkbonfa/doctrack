"""
event_bus.py
============
Coração da arquitetura event-driven do DocTrack v4.

Toda mutação no sistema (CRUD de documentos, etapas, responsáveis) DEVE
passar por publish_event(). Essa função faz três coisas atomicamente:

    1. Persiste o evento em audit_logs (event store)
    2. Emite via Socket.IO para as rooms apropriadas
    3. Retorna o id do evento (para replay/idempotência)

Regra de ouro: NENHUM endpoint REST deve chamar socketio.emit() direto.
Sempre use publish_event(). Isso mantém o fluxo auditável e desacoplado.

Quando migrar para múltiplas instâncias (Redis), só esta camada muda.
"""

from datetime import datetime, timezone
from typing import Optional, Any
import json
import logging

logger = logging.getLogger("doctrack.event_bus")


# ---------------------------------------------------------------------------
# ENUM de tipos de evento — fonte única de verdade
# ---------------------------------------------------------------------------
class EventType:
    """Padronização de event_types. Use SEMPRE estas constantes."""

    # Documentos
    DOCUMENT_CREATED = "DOCUMENT_CREATED"
    DOCUMENT_UPDATED = "DOCUMENT_UPDATED"
    DOCUMENT_DELETED = "DOCUMENT_DELETED"
    DOCUMENT_STATUS_UPDATED = "DOCUMENT_STATUS_UPDATED"

    # Etapas
    ETAPA_UPDATED = "ETAPA_UPDATED"
    ETAPA_COMPLETED = "ETAPA_COMPLETED"

    # Responsáveis (CRUD novo do v4)
    RESPONSAVEL_ASSIGNED = "RESPONSAVEL_ASSIGNED"
    RESPONSAVEL_REMOVED = "RESPONSAVEL_REMOVED"
    RESPONSAVEL_CHANGED = "RESPONSAVEL_CHANGED"

    # Entregáveis / Projetos
    ENTREGAVEL_CREATED = "ENTREGAVEL_CREATED"
    ENTREGAVEL_UPDATED = "ENTREGAVEL_UPDATED"
    ENTREGAVEL_DELETED = "ENTREGAVEL_DELETED"
    PROJETO_CREATED = "PROJETO_CREATED"
    PROJETO_UPDATED = "PROJETO_UPDATED"
    PROJETO_ARQUIVADO = "PROJETO_ARQUIVADO"
    MENSAL_CREATED = "MENSAL_CREATED"
    MENSAL_UPDATED = "MENSAL_UPDATED"
    MENSAL_DELETED = "MENSAL_DELETED"
    BASELINE_CREATED = "BASELINE_CREATED"

    # Missões (kanban)
    MISSAO_CREATED = "MISSAO_CREATED"
    MISSAO_UPDATED = "MISSAO_UPDATED"
    MISSAO_DELETED = "MISSAO_DELETED"
    MISSAO_COLUNA_CREATED = "MISSAO_COLUNA_CREATED"
    MISSAO_COLUNA_UPDATED = "MISSAO_COLUNA_UPDATED"
    MISSAO_COLUNA_DELETED = "MISSAO_COLUNA_DELETED"
    MISSAO_COLUNA_REORDENADA = "MISSAO_COLUNA_REORDENADA"
    MISSAO_COLUNAS_REORDENADAS = "MISSAO_COLUNAS_REORDENADAS"
    MISSAO_CARTAO_CREATED = "MISSAO_CARTAO_CREATED"
    MISSAO_CARTAO_UPDATED = "MISSAO_CARTAO_UPDATED"
    MISSAO_CARTAO_DELETED = "MISSAO_CARTAO_DELETED"
    MISSAO_CARTAO_MOVIDO = "MISSAO_CARTAO_MOVIDO"
    MISSAO_ARQUIVADA = "MISSAO_ARQUIVADA"
    MISSAO_CARTAO_COMENTADO = "MISSAO_CARTAO_COMENTADO"
    MISSAO_MODELO_CREATED = "MISSAO_MODELO_CREATED"

    # PDR (P&D de reagentes)
    PRODUTO_CREATED = "PRODUTO_CREATED"
    PRODUTO_UPDATED = "PRODUTO_UPDATED"
    PRODUTO_DELETED = "PRODUTO_DELETED"
    APRESENTACAO_CREATED = "APRESENTACAO_CREATED"
    APRESENTACAO_UPDATED = "APRESENTACAO_UPDATED"
    APRESENTACAO_DELETED = "APRESENTACAO_DELETED"
    REIMPORT = "REIMPORT"

    # Custos (formação de custo de produto)
    CUSTO_COMPOSICAO_CREATED = "CUSTO_COMPOSICAO_CREATED"
    CUSTO_COMPOSICAO_UPDATED = "CUSTO_COMPOSICAO_UPDATED"
    CUSTO_COMPOSICAO_DELETED = "CUSTO_COMPOSICAO_DELETED"
    CUSTO_LANCAMENTO_CREATED = "CUSTO_LANCAMENTO_CREATED"
    CUSTO_LANCAMENTO_UPDATED = "CUSTO_LANCAMENTO_UPDATED"
    CUSTO_LANCAMENTO_DELETED = "CUSTO_LANCAMENTO_DELETED"
    CUSTO_VERSAO_CREATED = "CUSTO_VERSAO_CREATED"

    # Sistema / notificações
    NOTIFICATION = "NOTIFICATION"
    USER_CONNECTED = "USER_CONNECTED"
    USER_DISCONNECTED = "USER_DISCONNECTED"

    @classmethod
    def all(cls):
        return [
            v for k, v in cls.__dict__.items()
            if not k.startswith("_") and isinstance(v, str)
        ]


# ---------------------------------------------------------------------------
# Roteamento de rooms — qual evento vai para quem
# ---------------------------------------------------------------------------
def _resolve_rooms(event_type: str, payload: dict) -> list[str]:
    """
    Decide para quais rooms um evento deve ser distribuído.

    Estratégia:
      - 'role:admin'   -> recebe TUDO (auditoria total)
      - 'role:gestor'  -> recebe eventos de documentos e responsáveis
      - 'categoria:X'  -> usuários acompanhando aquela categoria/origem
      - 'equipamento:Y'-> usuários acompanhando um equipamento específico
      - 'doc:N'        -> usuários com a tela do doc N aberta

    Isso evita broadcast geral e prepara o terreno para escalar.
    """
    rooms = ["role:admin"]  # admin sempre recebe tudo

    if event_type.startswith("DOCUMENT_") or event_type.startswith("ETAPA_") \
            or event_type.startswith("RESPONSAVEL_"):
        rooms.append("role:gestor")

        # Segmentação fina por contexto do documento
        if payload.get("setor"):
            rooms.append(f"setor:{payload['setor']}")
        if payload.get("equipamento"):
            rooms.append(f"equipamento:{payload['equipamento']}")
        if payload.get("documento_id"):
            rooms.append(f"doc:{payload['documento_id']}")

    # Projetos / entregáveis / PMO: módulo é gestor+. O técnico também recebe
    # porque atualiza os entregáveis sob sua responsabilidade; o front filtra
    # pelo projeto aberto. Sem isto, o backend emitia para ninguém além do admin.
    if (event_type.startswith("PROJETO_") or event_type.startswith("ENTREGAVEL_")
            or event_type.startswith("MENSAL_") or event_type.startswith("BASELINE_")):
        rooms.append("role:gestor")
        rooms.append("role:tecnico")
        if payload.get("projeto_id"):
            rooms.append(f"projeto:{payload['projeto_id']}")

    # PDR: produtos / apresentações vão para gestor + técnico (e a sala da apres.)
    if event_type.startswith("PRODUTO_") or event_type.startswith("APRESENTACAO_"):
        rooms.append("role:gestor")
        rooms.append("role:tecnico")
        if payload.get("apresentacao_id"):
            rooms.append(f"apres:{payload['apresentacao_id']}")

    # Missões (kanban): módulo é técnico+ — broadcast para os papéis com acesso;
    # o front filtra pelo missao_id do payload (sem sala por missão no MVP).
    if event_type.startswith("MISSAO_"):
        rooms.append("role:gestor")
        rooms.append("role:tecnico")

    if event_type == EventType.NOTIFICATION:
        # Notificações vão para o destinatário específico (ou broadcast)
        if payload.get("target_user_id"):
            rooms.append(f"user:{payload['target_user_id']}")
        else:
            rooms = ["role:admin", "role:gestor", "role:tecnico"]

    # Remove duplicatas mantendo ordem
    return list(dict.fromkeys(rooms))


# ---------------------------------------------------------------------------
# Função central — TODA mutação chama isto
# ---------------------------------------------------------------------------
def _fmt_valor(v):
    """Serializa valor_antigo/valor_novo. Texto vai cru (o relatório de auditoria
    mostra 'pendente', não '"pendente"'); o resto vira JSON."""
    if v is None:
        return None
    return v if isinstance(v, str) else json.dumps(v, default=str)


def publish_event(
    event_type: str,
    payload: dict,
    user_id: Optional[int] = None,
    user_email: Optional[str] = None,
    *,
    db,                # SQLAlchemy session (passado para evitar import circular)
    AuditLog,          # Modelo (idem)
    socketio,          # Instância Flask-SocketIO (idem)
    campo: str = "",   # campo alterado (auditoria legível)
    ip: str = "",      # IP de origem — só persistido, nunca emitido no socket
) -> dict:
    """
    Publica um evento no sistema. Retorna o evento completo (com id e timestamp).

    Exemplo de uso:
        publish_event(
            EventType.DOCUMENT_STATUS_UPDATED,
            payload={
                "documento_id": 10,
                "etapa": "Etapa_Revisao1",
                "old_value": "Em andamento",
                "new_value": "Concluído",
                "origem": "Engenharia",
                "equipamento": "EQP-007",
            },
            user_id=current_user.id,
            user_email=current_user.email,
            db=db, AuditLog=AuditLog, socketio=socketio,
        )
    """
    if event_type not in EventType.all():
        logger.warning(f"Evento desconhecido: {event_type}")

    timestamp = datetime.now()

    # 1) PERSISTÊNCIA — audit_logs vira event store
    log = AuditLog(
        usuario_email=user_email or "system",
        usuario_id=user_id,
        acao=event_type,
        entidade=payload.get("entidade", "documento"),
        campo=campo or payload.get("campo", "") or "",
        ip=ip,
        documento_id=payload.get("documento_id") or payload.get("id"),
        valor_antigo=_fmt_valor(payload.get("old_value")),
        valor_novo=_fmt_valor(payload.get("new_value")),
        payload_json=json.dumps(payload, default=str),
        timestamp=timestamp,
    )
    db.session.add(log)
    db.session.commit()  # garante id persistido antes do emit

    # 2) MONTAGEM DO EVENTO
    event = {
        "event_id": log.id,
        "event_type": event_type,
        "timestamp": timestamp.isoformat(),
        "user_id": user_id,
        "user_email": user_email,
        "payload": payload,
    }

    # 3) DISTRIBUIÇÃO — para cada room relevante
    rooms = _resolve_rooms(event_type, payload)
    for room in rooms:
        socketio.emit(event_type, event, room=room)

    # Também emite num canal genérico 'event' para listeners catch-all
    # (útil pra dashboards de auditoria que querem ver tudo)
    socketio.emit("event", event, room="role:admin")

    logger.info(f"[event_bus] {event_type} → rooms={rooms} event_id={log.id}")

    return event


# ---------------------------------------------------------------------------
# Replay — quando cliente reconecta, manda eventos perdidos
# ---------------------------------------------------------------------------
def get_events_since(last_event_id: int, *, db, AuditLog, limit: int = 100) -> list[dict]:
    """
    Retorna eventos com id > last_event_id, ordenados cronologicamente.
    Usado pelo handshake do socket para sincronizar clientes que reconectam.
    """
    rows = (
        AuditLog.query
        .filter(AuditLog.id > last_event_id)
        .order_by(AuditLog.id.asc())
        .limit(limit)
        .all()
    )

    events = []
    for r in rows:
        try:
            payload = json.loads(r.payload_json) if r.payload_json else {}
        except (TypeError, json.JSONDecodeError):
            payload = {}

        events.append({
            "event_id": r.id,
            "event_type": r.acao,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "user_id": r.usuario_id,
            "user_email": r.usuario_email,
            "payload": payload,
        })
    return events
