# Fase 2 — Filtros & Consolidação de API

**Data:** 2026-05-06
**Projeto:** DocTrack v3 Enterprise
**Status:** Design aprovado — pronto para implementação
**Pré-requisito:** Fase 1 concluída

## Contexto

Fase 1 corrigiu vulnerabilidades de segurança e bugs estruturais. Esta fase ataca a dor central reportada pelo usuário: **filtros inconsistentes** e **redundâncias de código** entre frontend e backend.

## Objetivos

1. Eliminar duplicação de filtros (back + front fazendo o mesmo)
2. Filtros case/acento-insensitive
3. Substituir filtro de status_principal (legado) por status_global (calculado)
4. Consolidar endpoints sobrepostos (`/api/data`, `/api/documentos`, `/api/metrics`)
5. Centralizar enums de domínio (frontend consome `/api/enums`)
6. Fechar brechas de validação (PATCH genérico aceitando enum inválido)
7. Adicionar JWT blocklist e reduzir tempo de vida do access token
8. Optimistic lock em update de status

## Escopo

### Incluído
| ID | Problema | Ação |
|----|----------|------|
| F1 | Filtros duplicados front+back | Filtros só no backend |
| F2/F9 | Case/acento-sensitive | Helper `norm()` Unicode em ambos os lados |
| F3 | Busca textual divergente | Backend único; front passa `q` |
| F4 | Filtro de status_principal | Substituir por filtro de status_global |
| F5 | documento_id sem try/except | Validar; retornar 400 |
| F6 | Audit search incompleto | Incluir valor_antigo/valor_novo |
| F7 | Inconsistência ilike/exato | Documentar contrato: filtros = exato, `q` = textual ilike |
| R1 | 3 endpoints sobrepostos | `/api/data` deprecated com warning; UI migra |
| R2 | KPI duplicado back/front | Front consome `data.kpis` |
| R3 | metrics recalcula etapas | Centralizar em `compute_kpis` |
| R5 | require_role vs require_roles | Padronizar `@require_role` decorator |
| R7 | progresso em 3 lugares | Backend calcula; front consome |
| R9 | Tipos hardcoded | Frontend popula selects via `/api/enums` |
| I1 | status_principal vs global | Marcar legado como deprecated nos endpoints |
| I2 | Padrões de resposta | Envelope `{data, error}` nas rotas refatoradas |
| B2 | JWT sem blocklist | Tabela `revoked_tokens` + handler |
| B3 | Token 8h | Reduzir para 1h |
| B8 | Race condition em status | Coluna `version` + check optimistic |
| B10/B13 | PATCH aceita enum inválido | Validar enums no PATCH |

### Fora de escopo
- Redesign UI/UX e acessibilidade (Fase 3)
- Testes automatizados (Fase 4)

## Design técnico

### 1. Helper `norm()` para normalização Unicode

**Backend (`servidor.py`):**
```python
import unicodedata

def norm(s):
    if s is None:
        return ""
    s = str(s).strip().lower()
    return unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")
```

**Frontend (`static/app.js`):**
```javascript
function norm(s){
  if(s==null)return'';
  return String(s).trim().toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g,'');
}
```

### 2. Refactor `/api/documentos` (filtros centralizados)

```python
@app.route("/api/documentos")
@jwt_required()
def api_documentos():
    q          = norm(request.args.get("q", ""))
    status_g   = request.args.get("status_global", "")
    categoria  = request.args.get("categoria", "")
    origem     = request.args.get("origem", "")
    tipo       = request.args.get("tipo_documento", "")
    subtipo    = request.args.get("subtipo", "")
    equip      = request.args.get("equipamento", "")

    query = Documento.query.filter(Documento.ativo == True)
    # Filtros exatos: igualdade direta
    if categoria: query = query.filter(Documento.categoria == categoria)
    if origem:    query = query.filter(Documento.origem == origem)
    if tipo:      query = query.filter(Documento.tipo_documento == tipo)
    if subtipo:   query = query.filter(Documento.subtipo == subtipo)
    if equip:     query = query.filter(Documento.equipamento == equip)

    docs = [d.to_dict() for d in query.order_by(Documento.equipamento).all()]

    # Filtro status_global é pós-query (atributo computado)
    if status_g:
        docs = [d for d in docs if d.get("status_global") == status_g]

    # Busca textual normalizada em múltiplos campos
    if q:
        def matches(d):
            blob = " ".join([
                norm(d.get("equipamento")),
                norm(d.get("documento")),
                norm(d.get("categoria")),
                norm(d.get("origem")),
                norm(d.get("tipo_documento")),
                norm(d.get("subtipo")),
                norm(d.get("versao")),
                norm(d.get("local")),
            ])
            return q in blob
        docs = [d for d in docs if matches(d)]

    return jsonify(docs), 200
```

### 3. Frontend: filtros via params, sem `filterDocs()` local

```javascript
async function renderDocs(){
  populateFilters();
  const params = new URLSearchParams();
  const q = document.getElementById('docs-search').value.trim();
  if(q) params.set('q', q);
  ['cat','origem','tipo','subtipo'].forEach(k=>{
    const v=document.getElementById('docs-filter-'+k).value;
    if(v) params.set({cat:'categoria',origem:'origem',tipo:'tipo_documento',subtipo:'subtipo'}[k], v);
  });
  const sg = document.getElementById('docs-filter-status-global').value;
  if(sg) params.set('status_global', sg);

  const res = await apiFetch('/documentos?'+params.toString());
  const data = res && res.ok ? await res.json() : [];
  renderDocsTable(data);
}
```

### 4. Filtro UI: status_global em vez de status_principal

No HTML do dashboard:
```html
<!-- Substituir #docs-filter-status por: -->
<select id="docs-filter-status-global" class="filter-select">
  <option value="">Todos status</option>
  <option value="Pendente">Pendente</option>
  <option value="Em progresso">Em progresso</option>
  <option value="Finalizado">Finalizado</option>
</select>
```

### 5. Consolidação de endpoints

**`/api/data`** — manter por compat, mas adicionar header `X-Deprecated: use /api/documentos + /api/metrics`. UI migra para os dois novos.

**`/api/metrics`** — adotar `compute_kpis` como única fonte. Reescrever:
```python
@app.route("/api/metrics")
@jwt_required()
def api_metrics():
    docs = [d.to_dict() for d in Documento.query.filter(Documento.ativo == True).all()]
    return jsonify(compute_kpis(docs)), 200
```

E ampliar `compute_kpis` para incluir os campos extras que `/api/metrics` retornava (etapas com Pendente/Em andamento/Concluído por chave).

### 6. Frontend consome `data.kpis` em vez de recalcular

`renderDashboard()` passa a receber as métricas já prontas:
```javascript
async function loadData(){
  const res = await apiFetch('/data');
  if(res && res.ok){
    const data = await res.json();
    allDocs = data.items || [];
    lastKpis = data.kpis || null;
  }
}
function renderDashboard(){
  if(!lastKpis){ /* fallback: computar local */ }
  // usar lastKpis.cat_counts, lastKpis.origem_counts, lastKpis.global_counts, etc.
}
```

### 7. Endpoint `/api/enums` consumido pelos modais

Frontend popula selects de `tipo_documento`, `subtipo` e estágios via `_enums` carregado em `loadEnums()`.

### 8. Padronizar `@require_role`

Substituir todos os blocos:
```python
ok, err, code = require_roles("admin", "gestor")
if not ok: return err, code
```
Por decorator:
```python
@require_role("admin", "gestor")
def rota(...): ...
```

Remover helper `require_roles` redundante.

### 9. Validação de enums no PATCH

```python
ENUM_VALIDATORS = {
    "etapa_elaboracao":  ETAPA_STATUS,
    "etapa_revisao1":    ETAPA_STATUS,
    "etapa_diagramacao": ETAPA_STATUS,
    "etapa_revisao2":    ETAPA_STATUS,
    "tipo_documento":    TIPOS_DOCUMENTO,
    "subtipo":           SUBTIPOS_DOCUMENTO,
}

for campo in CAMPOS:
    if campo in data:
        novo = data[campo]
        if campo in ENUM_VALIDATORS and novo and novo not in ENUM_VALIDATORS[campo]:
            return jsonify({"erro": f"Valor inválido para {campo}: '{novo}'"}), 400
        # ... resto
```

### 10. JWT blocklist + tempo de vida

**Migration `002_jwt_blocklist.py`:**
```sql
CREATE TABLE IF NOT EXISTS revoked_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  jti TEXT UNIQUE NOT NULL,
  revoked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_revoked_jti ON revoked_tokens(jti);
```

**Modelo:**
```python
class RevokedToken(db.Model):
    __tablename__ = "revoked_tokens"
    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(64), unique=True, nullable=False, index=True)
    revoked_at = db.Column(db.DateTime, default=datetime.utcnow)
```

**Servidor:**
```python
@jwt.token_in_blocklist_loader
def check_revoked(jwt_header, jwt_payload):
    jti = jwt_payload["jti"]
    return db.session.query(RevokedToken.id).filter_by(jti=jti).first() is not None
```

**Logout em `auth.py`:**
```python
@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    jti = get_jwt()["jti"]
    db.session.add(RevokedToken(jti=jti))
    db.session.commit()
    return jsonify({"mensagem": "Logout realizado"}), 200
```

**Tempo de vida:**
```python
app.config["JWT_ACCESS_TOKEN_EXPIRES"]  = timedelta(hours=1)   # era 8h
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=7)    # era 30d
```

### 11. Optimistic lock em status

Adicionar coluna `version INTEGER DEFAULT 0` em Documento. No update de etapa/status:
```python
expected_version = data.get("version")
if expected_version is not None and doc.version != expected_version:
    return jsonify({
        "erro": "Documento foi atualizado por outro usuário. Recarregue.",
        "current_version": doc.version,
    }), 409
doc.version += 1
```

Frontend lê `version` e envia de volta no PUT.

### 12. F5: validar documento_id no audit

```python
doc_id_raw = request.args.get("documento_id", "")
if doc_id_raw:
    try:
        doc_id_int = int(doc_id_raw)
    except (ValueError, TypeError):
        return jsonify({"erro": "documento_id deve ser numérico"}), 400
    query = query.filter(AuditLog.documento_id == doc_id_int)
```

### 13. F6: audit search inclui valores

```python
if q:
    qn = norm(q)
    result = [l for l in result if (
        qn in norm(l["usuario"]) or
        qn in norm(l["entidade"]) or
        qn in norm(l["campo"]) or
        qn in norm(l.get("valor_antigo","")) or
        qn in norm(l.get("valor_novo",""))
    )]
```

## Arquivos afetados

```
servidor.py                              (rotas /api/documentos, /api/metrics, /api/audit, PATCH, decorators)
models.py                                (RevokedToken model + Documento.version)
auth.py                                  (logout endpoint, decorator @require_role já existe)
static/app.js                            (norm(), filterDocs simplificado, lastKpis, populate via _enums)
templates/dashboard.html                 (substituir #docs-filter-status por status-global)
migrations/002_jwt_blocklist.py          (novo)
migrations/003_documento_version.py      (novo)
```

## Plano de execução

1. Migrations 002, 003 (idempotentes)
2. Modelos: RevokedToken, Documento.version
3. Backend: norm(), filtros consolidados, /api/metrics via compute_kpis, blocklist, optimistic lock, PATCH validation, audit fixes
4. Frontend: norm(), filtros via params, status_global filter, consumo de enums
5. Template: substituir filtro de status
6. Smoke test

## Validação manual

| Item | Como validar |
|------|--------------|
| Filtros case/acento | Filtrar "homologação" → encontra "Homologacao" |
| Filtro status_global | Selecionar "Em progresso" → só docs em progresso |
| Busca em audit | Buscar texto que existe em valor_antigo → aparece |
| documento_id inválido | `?documento_id=abc` → 400 |
| Tipos no modal | Abrir modal de criar doc → selects populados |
| JWT blocklist | Logout → token antigo retorna 401 |
| Token de 1h | Decodificar JWT → exp em 1h |
| PATCH enum inválido | `PATCH /documentos/1 {"etapa_elaboracao":"Foo"}` → 400 |
| Optimistic lock | Update concorrente com version errado → 409 |
| KPI consistente | Página dashboard reflete exatamente os números do backend |

## Critérios de aceite

- [ ] Backend é única fonte para filtros
- [ ] Busca normalizada (case/acento-insensitive)
- [ ] Filtro de status_global substitui status_principal na UI
- [ ] /api/metrics deriva de compute_kpis (sem duplicação)
- [ ] Frontend consome data.kpis (sem recalculo)
- [ ] Modais usam /api/enums para popular tipos/subtipos
- [ ] @require_role usado em todas as rotas; require_roles removido
- [ ] PATCH genérico valida enums
- [ ] JWT blocklist funciona; access token = 1h
- [ ] Optimistic lock retorna 409 em conflito
- [ ] Audit search inclui valores antigos/novos
- [ ] documento_id inválido retorna 400

## Rollback

- Backup automático do DB antes das migrations 002 e 003
- Cada bloco lógico em commit separado
- Migrations idempotentes; downgrade manual pela facilidade do SQLite

## Próxima fase

Fase 3 — Redesign UI/UX & Acessibilidade.
