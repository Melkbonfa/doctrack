/**
 * app.js (trecho realtime — integrar com seu app.js existente)
 * ============================================================
 *
 * Assume que você já tem:
 *   - allDocs (cache local de documentos)
 *   - renderDocsTable() — função que pinta a tabela toda
 *   - localStorage com 'jwt'
 *
 * O que muda neste trecho:
 *   - Substituímos reloads de tabela inteira por updateRow incremental
 *   - UI reage a eventos do socket
 *   - Status de conexão visível (badge no header)
 *   - Notificações como toasts
 */

// ===========================================================================
// 1) BOOTSTRAP DO SOCKET (chamar após login bem-sucedido)
// ===========================================================================
let dt = null;

function initRealtime() {
  const token = localStorage.getItem("jwt");
  if (!token) return;

  dt = new DocTrackSocket({ token });

  // ---- Listeners de UI ----

  // Status da conexão — badge no header
  dt.on("__connect__", () => setConnBadge("online"));
  dt.on("__disconnect__", () => setConnBadge("offline"));
  dt.on("__connect_error__", () => setConnBadge("erro"));
  dt.on("__auth_error__", () => {
    setConnBadge("auth");
    // token inválido/expirado — força novo login
    localStorage.removeItem("jwt");
    location.href = "/login";
  });

  // ---- Eventos de domínio: documentos ----
  dt.on("DOCUMENT_CREATED", (e) => {
    const doc = e.payload.documento;
    if (!doc) return;
    upsertDocInCache(doc);
    insertRowAtTop(doc);
    flashRow(doc.id, "create");
    showToast(`Novo documento: ${doc.titulo || doc.equipamento}`, "info");
  });

  dt.on("DOCUMENT_UPDATED", (e) => {
    const doc = e.payload.documento;
    if (!doc) return;
    upsertDocInCache(doc);
    updateRow(doc.id, doc);
    flashRow(doc.id, "update");
  });

  dt.on("DOCUMENT_STATUS_UPDATED", (e) => {
    // Atualização de etapa específica — só repinta a célula da etapa
    const { documento_id, etapa, new_value, status_global } = e.payload;
    updateCell(documento_id, etapa, new_value);
    if (status_global) updateCell(documento_id, "status_global", status_global);
    flashCell(documento_id, etapa);
  });

  dt.on("DOCUMENT_DELETED", (e) => {
    const id = e.payload.documento_id;
    removeDocFromCache(id);
    removeRow(id);
    showToast(`Documento #${id} removido`, "warn");
  });

  // ---- Eventos de responsáveis ----
  dt.on("RESPONSAVEL_ASSIGNED", (e) => {
    const { documento_id, responsavel } = e.payload;
    addResponsavelInCache(documento_id, responsavel);
    refreshResponsaveisCell(documento_id);
    flashCell(documento_id, "responsaveis");
  });

  dt.on("RESPONSAVEL_REMOVED", (e) => {
    const { documento_id, responsavel } = e.payload;
    removeResponsavelInCache(documento_id, responsavel.id);
    refreshResponsaveisCell(documento_id);
  });

  // ---- Notificações ----
  dt.on("NOTIFICATION", (e) => {
    const { titulo, mensagem, severidade } = e.payload;
    showToast(`${titulo}: ${mensagem}`, severidade || "info");
    pushToNotificationCenter(e);
  });

  // ---- Etapa concluída — pode disparar feedback visual extra ----
  dt.on("ETAPA_COMPLETED", (e) => {
    const { documento_id, etapa } = e.payload;
    flashCell(documento_id, etapa, "success");
  });

  dt.connect();
}


// ===========================================================================
// 2) HELPERS DE CACHE LOCAL (incremental, sem reload)
// ===========================================================================
function upsertDocInCache(doc) {
  const idx = allDocs.findIndex((d) => d.id === doc.id);
  if (idx >= 0) {
    allDocs[idx] = { ...allDocs[idx], ...doc };
  } else {
    allDocs.unshift(doc);
  }
}

function removeDocFromCache(id) {
  const idx = allDocs.findIndex((d) => d.id === id);
  if (idx >= 0) allDocs.splice(idx, 1);
}

function addResponsavelInCache(docId, resp) {
  const doc = allDocs.find((d) => d.id === docId);
  if (!doc) return;
  doc.responsaveis = doc.responsaveis || [];
  if (!doc.responsaveis.find((r) => r.id === resp.id)) {
    doc.responsaveis.push(resp);
  }
}

function removeResponsavelInCache(docId, respId) {
  const doc = allDocs.find((d) => d.id === docId);
  if (!doc || !doc.responsaveis) return;
  doc.responsaveis = doc.responsaveis.filter((r) => r.id !== respId);
}


// ===========================================================================
// 3) HELPERS DE DOM — atualização granular (NÃO repinta a tabela toda)
// ===========================================================================
function getRow(id) {
  return document.querySelector(`tr[data-doc-id="${id}"]`);
}

function updateRow(id, doc) {
  const row = getRow(id);
  if (!row) {
    // Linha não existe ainda — talvez filtro a esconda. Insere se faz sentido.
    insertRowAtTop(doc);
    return;
  }
  // Atualiza só as células que mudaram
  ["equipamento", "origem", "titulo",
   "etapa_elaboracao", "etapa_revisao1", "etapa_revisao2", "etapa_aprovacao",
   "status_global"].forEach((field) => {
    updateCellValue(row, field, doc[field]);
  });
  refreshResponsaveisCell(id);
}

function updateCell(docId, field, value) {
  const row = getRow(docId);
  if (!row) return;
  updateCellValue(row, field, value);
}

function updateCellValue(row, field, value) {
  const cell = row.querySelector(`[data-field="${field}"]`);
  if (!cell) return;
  if (cell.textContent !== String(value ?? "")) {
    cell.textContent = value ?? "";
  }
}

function refreshResponsaveisCell(docId) {
  const row = getRow(docId);
  if (!row) return;
  const cell = row.querySelector('[data-field="responsaveis"]');
  if (!cell) return;
  const doc = allDocs.find((d) => d.id === docId);
  cell.innerHTML = (doc?.responsaveis || [])
    .map((r) => `<span class="resp-pill" title="${r.role}">${r.user_nome || r.user_email}</span>`)
    .join("");
}

function insertRowAtTop(doc) {
  const tbody = document.querySelector("#docs-table tbody");
  if (!tbody) return;
  const tr = renderDocRow(doc); // usa sua função existente de render de linha
  tbody.prepend(tr);
}

function removeRow(id) {
  const row = getRow(id);
  if (row) row.remove();
}


// ===========================================================================
// 4) FEEDBACK VISUAL — flash sutil quando algo muda em tempo real
// ===========================================================================
function flashRow(id, kind = "update") {
  const row = getRow(id);
  if (!row) return;
  row.classList.add(`flash-${kind}`);
  setTimeout(() => row.classList.remove(`flash-${kind}`), 1500);
}

function flashCell(docId, field, kind = "update") {
  const row = getRow(docId);
  if (!row) return;
  const cell = row.querySelector(`[data-field="${field}"]`);
  if (!cell) return;
  cell.classList.add(`flash-${kind}`);
  setTimeout(() => cell.classList.remove(`flash-${kind}`), 1200);
}


// ===========================================================================
// 5) UI: badge de status + toasts + central de notificações
// ===========================================================================
function setConnBadge(state) {
  const badge = document.getElementById("conn-badge");
  if (!badge) return;
  const labels = {
    online: { text: "● Online", cls: "ok" },
    offline: { text: "● Reconectando…", cls: "warn" },
    erro: { text: "● Sem conexão", cls: "err" },
    auth: { text: "● Sessão expirada", cls: "err" },
  };
  const cfg = labels[state] || labels.offline;
  badge.textContent = cfg.text;
  badge.className = `conn-badge ${cfg.cls}`;
}

function showToast(msg, severidade = "info") {
  const host = document.getElementById("toast-host") || createToastHost();
  const el = document.createElement("div");
  el.className = `toast toast-${severidade}`;
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => el.classList.add("show"), 10);
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 300);
  }, 4000);
}

function createToastHost() {
  const host = document.createElement("div");
  host.id = "toast-host";
  document.body.appendChild(host);
  return host;
}

function pushToNotificationCenter(event) {
  // Hook para integrar com sua sininho/dropdown de notificações
  // Ex: store.notifications.unshift({ id: event.event_id, ...event.payload });
}


// ===========================================================================
// 6) ASSINATURA CONTEXTUAL DE ROOMS
// ===========================================================================
// Quando o usuário abre a página de um documento específico:
function openDocumentDetails(docId) {
  // ... seu código de abrir modal/drawer ...
  dt?.subscribe(`doc:${docId}`);
}

function closeDocumentDetails(docId) {
  dt?.unsubscribe(`doc:${docId}`);
}

// Quando filtra por origem/categoria:
function onOrigemFilterChange(origem) {
  // desinscreve da anterior, inscreve na nova
  if (window.__lastCategoria) dt?.unsubscribe(`categoria:${window.__lastCategoria}`);
  if (origem) dt?.subscribe(`categoria:${origem}`);
  window.__lastCategoria = origem;
}


// ===========================================================================
// 7) AÇÕES DE EDIÇÃO (PUT) — agora sem precisar recarregar
// ===========================================================================
async function salvarDocumento(docId, payload) {
  // payload deve incluir 'versao' do cliente para versionamento otimista
  const res = await fetch(`/api/documentos/${docId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${localStorage.getItem("jwt")}`,
    },
    body: JSON.stringify(payload),
  });

  if (res.status === 409) {
    const data = await res.json();
    showToast("Outro usuário editou este documento. Recarregando…", "warn");
    // Atualiza com a versão atual recebida e fecha o modal
    upsertDocInCache(data.documento);
    updateRow(docId, data.documento);
    return null;
  }

  if (!res.ok) {
    showToast("Erro ao salvar", "err");
    return null;
  }

  const doc = await res.json();
  // NÃO precisa atualizar a UI manualmente aqui — o evento DOCUMENT_UPDATED
  // já vai chegar via socket e atualizar tudo. Mas como o usuário que salvou
  // também recebe (está em role:gestor ou doc:N), a UI atualiza igual.
  return doc;
}


// ===========================================================================
// 8) CSS sugerido (cole no style.css) — mantém o tema cyberpunk do v3
// ===========================================================================
/*

.conn-badge {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 12px;
  font-family: var(--font-mono);
  letter-spacing: .3px;
}
.conn-badge.ok   { color: var(--cyan);   border: 1px solid var(--cyan); }
.conn-badge.warn { color: var(--amber);  border: 1px solid var(--amber); }
.conn-badge.err  { color: var(--danger); border: 1px solid var(--danger); }

@keyframes flashUpdate {
  0%   { background: rgba(0, 230, 255, 0.18); }
  100% { background: transparent; }
}
@keyframes flashCreate {
  0%   { background: rgba(0, 255, 140, 0.22); }
  100% { background: transparent; }
}
@keyframes flashSuccess {
  0%   { background: rgba(120, 255, 90, 0.25); }
  100% { background: transparent; }
}
.flash-update  { animation: flashUpdate 1.4s ease-out; }
.flash-create  { animation: flashCreate 1.4s ease-out; }
.flash-success { animation: flashSuccess 1.2s ease-out; }

#toast-host {
  position: fixed;
  top: 70px;
  right: 24px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toast {
  background: var(--panel);
  border: 1px solid var(--border);
  border-left: 3px solid var(--cyan);
  color: var(--text);
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 13px;
  min-width: 240px;
  opacity: 0;
  transform: translateX(20px);
  transition: opacity .25s, transform .25s;
}
.toast.show { opacity: 1; transform: translateX(0); }
.toast-warn { border-left-color: var(--amber); }
.toast-err  { border-left-color: var(--danger); }

.resp-pill {
  display: inline-block;
  padding: 2px 8px;
  margin: 2px;
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: rgba(120,80,255,0.08);
}

*/
