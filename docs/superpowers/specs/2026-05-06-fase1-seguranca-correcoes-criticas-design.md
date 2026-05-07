# Fase 1 — Segurança & Correções Críticas

**Data:** 2026-05-06
**Projeto:** DocTrack v3 Enterprise
**Status:** Design aprovado — pronto para implementação

## Contexto

Auditoria do DocTrack v3 identificou ~60 problemas distribuídos em 5 categorias (filtros, redundâncias, inconsistências, bugs, UI/UX). O escopo total foi dividido em 4 fases sequenciais. Este spec cobre **apenas a Fase 1**: vulnerabilidades de segurança e bugs estruturais que causam perda de dados ou comprometem a integridade do sistema.

As fases 2-4 (filtros, redesign UI, testes automatizados) terão specs próprios.

## Objetivos

1. Eliminar vulnerabilidades de autenticação e XSS
2. Restringir CORS e remover credenciais hardcoded
3. Garantir que delete de documentos preserve histórico
4. Garantir que reimport não quebre integridade do audit log
5. Limpeza de arquivos legados

## Escopo

### Incluído

| ID | Problema | Arquivo(s) |
|----|----------|------------|
| B1 | JWT secret hardcoded com fallback | servidor.py:31 |
| B5 | Login fallback "demo" no front bypassa auth | static/app.js:25-30 |
| B6 | XSS em interpolação de innerHTML | static/app.js (~20 ocorrências) |
| B7 | XSS via inline onclick com aspas no payload | static/app.js, templates/dashboard.html |
| U3 | Senha admin123 hardcoded no template | templates/dashboard.html:27 |
| B4 | CORS aceita qualquer origem | servidor.py:23 |
| B11 | Hard delete de documentos perde histórico | servidor.py:408, models.py |
| B12 | Audit do DELETE não captura snapshot completo | servidor.py:405-407 |
| B14 | Reimport apaga refs do audit log | servidor.py:626-628 |
| R6 | Arquivo dashboard.html.bak no projeto | templates/dashboard.html.bak |

### Fora de escopo (próximas fases)

- Filtros inconsistentes (Fase 2)
- Consolidação /api/data, /api/documentos, /api/metrics (Fase 2)
- JWT blocklist e refresh tokens curtos (Fase 2)
- Race condition em update de status (Fase 2)
- Redesign UI/UX e acessibilidade (Fase 3)
- Testes automatizados pytest (Fase 4)

## Design técnico

### 1. JWT Secret obrigatório (B1)

```python
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is required")
app.config["JWT_SECRET_KEY"] = JWT_SECRET
```

Adicionar `.env.example`:

```
JWT_SECRET=change-me-to-a-random-string
CORS_ORIGINS=http://localhost:5000
```

### 2. Remover login demo (B5)

Em `static/app.js`, eliminar bloco `if (!response.ok) { simulateLogin() }` e função `simulateLogin()` se existir. Falha de login passa a mostrar toast com erro real do backend.

### 3. Remover senha do template (U3)

Em `templates/dashboard.html`, remover atributo `value="admin123"` do input de senha e qualquer comentário expondo credenciais.

### 4. XSS — escape e event delegation (B6, B7)

**Helper em `static/app.js`:**

```javascript
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
```

Substituir todas as interpolações `${campo}` em template strings que viram innerHTML por `${esc(campo)}`. Lugares afetados (~20):

- `renderRecent` em app.js:175
- `renderDocs` em app.js:219-231
- `renderAudit` em app.js:327-333
- `renderUsers` em app.js:345-352

**Inline onclick** vira event delegation:

```javascript
// Antes:
<button onclick="delDoc(${d.id},'${d.equipamento}')">×</button>

// Depois:
<button data-action="delete-doc" data-id="${d.id}" aria-label="Excluir documento">×</button>

// Listener único na tabela:
tabela.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  const id = btn.dataset.id;
  if (action === 'delete-doc') delDoc(id);
});
```

### 5. CORS restrito (B4)

```python
origins = os.environ.get("CORS_ORIGINS", "http://localhost:5000").split(",")
CORS(app, origins=[o.strip() for o in origins if o.strip()])
```

### 6. Soft delete de documentos (B11, B12)

**Schema migration** (`migrations/001_soft_delete_documentos.py`):

```python
import sqlite3
from datetime import datetime

def upgrade(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(documentos)")
    cols = {row[1] for row in cur.fetchall()}
    if "ativo" not in cols:
        cur.execute("ALTER TABLE documentos ADD COLUMN ativo BOOLEAN DEFAULT 1")
    if "deleted_at" not in cols:
        cur.execute("ALTER TABLE documentos ADD COLUMN deleted_at DATETIME NULL")
    conn.commit()
    conn.close()
```

**Modelo** (`models.py`): adicionar `ativo = db.Column(db.Boolean, default=True, nullable=False)` e `deleted_at = db.Column(db.DateTime, nullable=True)`.

**Rota DELETE** (`servidor.py`):

```python
snapshot = json.dumps(doc.to_dict(), ensure_ascii=False)
doc.ativo = False
doc.deleted_at = datetime.utcnow()
db.session.commit()
log_audit(action="DELETE", entidade="documento",
          documento_id=doc.id,
          valor_antigo=snapshot, valor_novo=None)
```

**Queries de listagem**: adicionar `.filter(Documento.ativo == True)` em todas as queries que retornam documentos para o usuário (manter sem filtro em queries internas/administrativas).

### 7. Reimport com dedupe (B14)

Substituir `Documento.query.delete()` por dedupe inteligente em `_import_excel_to_db()`:

```python
existing = {(d.equipamento, d.documento): d for d in Documento.query.all()}
keys_in_excel = set()

for row in df.itertuples():
    key = (row.equipamento, row.documento)
    keys_in_excel.add(key)
    if key in existing:
        # UPDATE no registro existente, preservando id e audit refs
        doc = existing[key]
        for col in CAMPOS_IMPORTAVEIS:
            setattr(doc, col, getattr(row, col, None))
        doc.ativo = True
        doc.deleted_at = None
    else:
        # INSERT novo
        db.session.add(Documento(**row_to_kwargs(row)))

# Itens que sumiram do Excel: soft delete
now = datetime.utcnow()
for key, doc in existing.items():
    if key not in keys_in_excel and doc.ativo:
        doc.ativo = False
        doc.deleted_at = now
```

### 8. Limpeza

- Deletar `templates/dashboard.html.bak`
- Adicionar ao `.gitignore`: `.env`, `.env.local`, `*.bak`, `__pycache__/`, `*.db.backup-*`

## Arquivos afetados

```
servidor.py              (modificações: linhas 23, 31, 405-408, 626-628 + queries de listagem)
models.py                (modificações: classe Documento — 2 colunas novas)
auth.py                  (sem mudanças nesta fase)
static/app.js            (modificações: ~25 pontos — esc(), event delegation, remover simulateLogin)
templates/dashboard.html (modificações: remover value, comentários, inline onclick)
templates/dashboard.html.bak (DELETAR)
.gitignore               (criar/atualizar)
.env.example             (criar)
migrations/001_soft_delete_documentos.py (criar)
scripts/backup_db.sh     (criar — backup automático antes de migration)
```

## Plano de execução

Ordem para minimizar risco:

1. Backup automático de `doctrack.db`
2. Schema migration idempotente
3. Backend: JWT secret, CORS, soft delete, reimport dedupe
4. Frontend: remover demo, helper esc(), event delegation, remover senha do template
5. Limpeza: .bak, .gitignore, .env.example
6. Smoke test manual (checklist abaixo)

## Validação manual

| Passo | Como validar |
|-------|--------------|
| JWT secret | Iniciar sem env → falha com mensagem clara. Setar e iniciar → sobe normalmente. |
| Login demo removido | Parar backend, tentar login no front → toast de erro, não loga. |
| XSS | Criar documento com nome `<img src=x onerror=alert(1)>` → tabela mostra texto literal, sem alert. |
| CORS | curl com `Origin: http://evil.com` → header CORS ausente. |
| Soft delete | DELETE doc → some da listagem; SQL `SELECT * WHERE ativo=0` mostra registro; audit log tem snapshot JSON em valor_antigo. |
| Reimport | Reimportar Excel → ids antigos preservados; audit_logs.documento_id continua válido; itens removidos do Excel ficam com ativo=False. |
| .bak | `ls templates/` → apenas `dashboard.html`. |
| .gitignore | `git status` → não lista `.env`, `*.bak`, `*.db.backup-*`. |

## Critérios de aceite

- [ ] App não inicia sem `JWT_SECRET` no env
- [ ] Login com backend offline mostra erro (sem fallback)
- [ ] Template não contém credenciais hardcoded
- [ ] Payload com `<script>` em qualquer campo é renderizado como texto literal
- [ ] CORS rejeita origens não-listadas
- [ ] DELETE de documento marca `ativo=False` e persiste snapshot completo no audit
- [ ] Reimport preserva ids e audit logs antigos
- [ ] `dashboard.html.bak` removido; `.gitignore` atualizado
- [ ] Todos os passos de validação manual passam

## Rollback

- Backup do `doctrack.db` salvo em `doctrack.db.backup-YYYYMMDD-HHMMSS` antes da migration
- Commits atômicos por correção — cada problema (B1, B5, B6, etc.) tem seu próprio commit, permitindo revert individual
- Script `scripts/rollback.sh`: restaura DB do backup mais recente e exibe instruções para `git revert`

## Riscos

| Risco | Mitigação |
|-------|-----------|
| Migration corrompe DB existente | Backup automático antes; script idempotente; testar em cópia primeiro |
| Reimport dedupe perde dados em edge case (chave duplicada no Excel) | Validar unicidade de (equipamento, documento) no Excel antes do import; reportar conflitos |
| Helper esc() não cobre algum caso | Cobrir os 5 caracteres + null/undefined; revisar todas as ocorrências de innerHTML |
| Event delegation quebra handlers existentes | Manter compatibilidade durante refactor; testar cada tabela após mudança |

## Próxima fase

Após esta fase ser concluída e validada, partimos para **Fase 2 — Filtros & Consolidação de API**, que terá seu próprio spec.
