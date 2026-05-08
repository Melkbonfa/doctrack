/**
 * socket-client.js
 * ================
 * Cliente Socket.IO do DocTrack v4.
 *
 * Responsabilidades:
 *   - Conectar com JWT no handshake
 *   - Reconexão automática com backoff
 *   - Replay de eventos perdidos durante offline (last_event_id)
 *   - EventStore local (cache + dispatch para listeners da UI)
 *   - Heartbeat customizado para detecção precoce de queda
 *
 * Dependência: socket.io-client (CDN ou npm)
 *   <script src="https://cdn.socket.io/4.8.1/socket.io.min.js"></script>
 *
 * Uso:
 *   const dt = new DocTrackSocket({ token: localStorage.getItem('jwt') });
 *   dt.on('DOCUMENT_STATUS_UPDATED', e => updateRow(e.payload.documento_id, e.payload));
 *   dt.connect();
 */

class DocTrackSocket {
  constructor({ token, baseUrl = "" } = {}) {
    this.token = token;
    this.baseUrl = baseUrl;
    this.socket = null;
    this.lastEventId = this._loadLastEventId();
    this.listeners = new Map();   // event_type -> Set<fn>
    this.subscribedRooms = new Set();
    this.connected = false;
    this.heartbeatTimer = null;

    // Lista canônica de eventos do backend (espelha event_bus.EventType)
    this.EVENTS = [
      "DOCUMENT_CREATED", "DOCUMENT_UPDATED", "DOCUMENT_DELETED",
      "DOCUMENT_STATUS_UPDATED", "ETAPA_UPDATED", "ETAPA_COMPLETED",
      "RESPONSAVEL_ASSIGNED", "RESPONSAVEL_REMOVED", "RESPONSAVEL_CHANGED",
      "NOTIFICATION",
    ];
  }

  // -------------------------------------------------------------------------
  // Conexão
  // -------------------------------------------------------------------------
  connect() {
    if (this.socket && this.socket.connected) return;

    this.socket = io(this.baseUrl || undefined, {
      auth: { token: this.token },
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,       // começa em 1s
      reconnectionDelayMax: 10000,   // teto de 10s
      timeout: 20000,
    });

    this.socket.on("connect", () => {
      this.connected = true;
      console.log("[DocTrack] socket conectado:", this.socket.id);
      this._dispatch("__connect__", { sid: this.socket.id });

      // Replay de eventos perdidos enquanto estava offline
      if (this.lastEventId > 0) {
        this.requestReplay(this.lastEventId);
      }

      // Re-inscreve nas rooms que estavam ativas antes da queda
      if (this.subscribedRooms.size > 0) {
        this.socket.emit("subscribe", { rooms: [...this.subscribedRooms] });
      }

      this._startHeartbeat();
    });

    this.socket.on("connected", (data) => {
      console.log("[DocTrack] handshake ok:", data.user.email);
      this._dispatch("__handshake__", data);
    });

    this.socket.on("auth_error", (data) => {
      console.error("[DocTrack] auth error:", data);
      this._dispatch("__auth_error__", data);
      this.socket.disconnect();
    });

    this.socket.on("disconnect", (reason) => {
      this.connected = false;
      this._stopHeartbeat();
      console.warn("[DocTrack] socket desconectado:", reason);
      this._dispatch("__disconnect__", { reason });
    });

    this.socket.on("connect_error", (err) => {
      console.error("[DocTrack] erro de conexão:", err.message);
      this._dispatch("__connect_error__", { message: err.message });
    });

    // Listener catch-all para todos os event_types do backend
    this.EVENTS.forEach((evtType) => {
      this.socket.on(evtType, (event) => this._handleEvent(event));
    });

    // Replay vem num canal próprio
    this.socket.on("replay", (data) => {
      console.log(`[DocTrack] replay: ${data.count} eventos desde ${data.since}`);
      (data.events || []).forEach((e) => this._handleEvent(e, /*fromReplay*/ true));
    });
  }

  disconnect() {
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
    }
    this._stopHeartbeat();
  }

  // -------------------------------------------------------------------------
  // Tratamento de eventos
  // -------------------------------------------------------------------------
  _handleEvent(event, fromReplay = false) {
    if (!event || !event.event_type) return;

    // Idempotência — ignora eventos com id menor ou igual ao último visto
    if (event.event_id && event.event_id <= this.lastEventId && !fromReplay) {
      return;
    }
    if (event.event_id) {
      this.lastEventId = Math.max(this.lastEventId, event.event_id);
      this._saveLastEventId();
    }

    this._dispatch(event.event_type, event);
    this._dispatch("*", event); // listener catch-all opcional
  }

  // -------------------------------------------------------------------------
  // API pública — listeners
  // -------------------------------------------------------------------------
  on(eventType, fn) {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set());
    }
    this.listeners.get(eventType).add(fn);
    return () => this.off(eventType, fn);
  }

  off(eventType, fn) {
    this.listeners.get(eventType)?.delete(fn);
  }

  _dispatch(eventType, data) {
    this.listeners.get(eventType)?.forEach((fn) => {
      try { fn(data); }
      catch (err) { console.error(`[DocTrack] listener ${eventType}:`, err); }
    });
  }

  // -------------------------------------------------------------------------
  // Rooms — subscribe/unsubscribe contextual
  // -------------------------------------------------------------------------
  subscribe(rooms) {
    rooms = Array.isArray(rooms) ? rooms : [rooms];
    rooms.forEach((r) => this.subscribedRooms.add(r));
    if (this.connected) {
      this.socket.emit("subscribe", { rooms });
    }
  }

  unsubscribe(rooms) {
    rooms = Array.isArray(rooms) ? rooms : [rooms];
    rooms.forEach((r) => this.subscribedRooms.delete(r));
    if (this.connected) {
      this.socket.emit("unsubscribe", { rooms });
    }
  }

  // -------------------------------------------------------------------------
  // Replay — pede eventos desde um id específico
  // -------------------------------------------------------------------------
  requestReplay(sinceId) {
    if (!this.connected) return;
    this.socket.emit("replay_request", { since: sinceId });
  }

  // -------------------------------------------------------------------------
  // Heartbeat customizado (Socket.IO já tem o seu, este é redundante mas útil)
  // -------------------------------------------------------------------------
  _startHeartbeat() {
    this._stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.connected) {
        this.socket.emit("ping_app", { t: Date.now() });
      }
    }, 30000);
  }

  _stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  // -------------------------------------------------------------------------
  // Persistência do last_event_id (sobrevive a reload)
  // -------------------------------------------------------------------------
  _loadLastEventId() {
    const v = sessionStorage.getItem("doctrack_last_event_id");
    return v ? parseInt(v, 10) : 0;
  }

  _saveLastEventId() {
    sessionStorage.setItem("doctrack_last_event_id", String(this.lastEventId));
  }
}

// Expor globalmente (para uso no app.js sem bundler)
window.DocTrackSocket = DocTrackSocket;
