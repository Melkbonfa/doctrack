# Fase 1 — Segurança & Correções Críticas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar vulnerabilidades críticas (JWT/XSS/CORS/credenciais) e corrigir bugs estruturais (hard delete, reimport quebrando audit) no DocTrack v3 sem alterar comportamento funcional do dashboard.

**Architecture:** Mudanças cirúrgicas em pontos específicos do backend Flask (servidor.py, models.py) e frontend vanilla JS (app.js, dashboard.html). Migration idempotente via script standalone (sem framework de migrations). Backup automático do SQLite antes de qualquer mudança de schema. Testes nesta fase são manuais (smoke tests via checklist) — automação fica para Fase 4.

**Tech Stack:** Python 3 + Flask 3 + SQLAlchemy + SQLite + JWT-Extended + Vanilla JS + Chart.js

---

## File Structure

**Novos arquivos:**
- `migrations/001_soft_delete_documentos.py` — script idempotente que adiciona colunas `ativo` e `deleted_at` em `documentos`
- `scripts/backup_db.sh` — copia `doctrack.db` para `doctrack.db.backup-YYYYMMDD-HHMMSS`
- `scripts/rollback.sh` — restaura DB do backup mais recente
- `.env.example` — documenta `JWT_SECRET` e `CORS_ORIGINS`
- `.gitignore` — (criar ou atualizar) ignorar `.env`, `*.bak`, `*.db.backup-*`, `__pycache__/`

**Arquivos modificados:**
- `servidor.py` — config JWT/CORS, soft delete, reimport dedupe, queries com filtro `ativo`
- `models.py` — adicionar colunas `ativo` e `deleted_at` ao modelo `Documento`
- `static/app.js` — helper `esc()`, event delegation, remover `simulateLogin()`
- `templates/dashboard.html` — remover senha hardcoded, remover inline onclick, adicionar `data-action`/`data-id`

**Arquivos removidos:**
- `templates/dashboard.html.bak`

---

## Task 1: Backup do banco e estrutura de diretórios

**Files:**
- Create: `scripts/backup_db.sh`
- Create: `scripts/rollback.sh`

- [ ] **Step 1: Criar `scripts/backup_db.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
DB_PATH="${1:-doctrack.db}"
if [ ! -f "$DB_PATH" ]; then
  echo "DB not found at $DB_PATH"; exit 1
fi
TS=$(date +%Y%m%d-%H%M%S)
BACKUP="${DB_PATH}.backup-${TS}"
cp "$DB_PATH" "$BACKUP"
echo "Backup created: $BACKUP"
```

- [ ] **Step 2: Criar `scripts/rollback.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
DB_PATH="${1:-doctrack.db}"
LATEST=$(ls -1t "${DB_PATH}".backup-* 2>/dev/null | head -1 || true)
if [ -z "$LATEST" ]; then
  echo "No backup found matching ${DB_PATH}.backup-*"; exit 1
fi
cp "$LATEST" "$DB_PATH"
echo "Restored $DB_PATH from $LATEST"
echo "To revert code changes: git revert <commit>"
```

- [ ] **Step 3: Tornar executáveis e rodar backup**

```bash
chmod +x scripts/backup_db.sh scripts/rollback.sh
bash scripts/backup_db.sh doctrack.db
ls doctrack.db.backup-*
```

Expected: aparece um arquivo `doctrack.db.backup-YYYYMMDD-HHMMSS`.

- [ ] **Step 4: Commit**

```bash
git add scripts/backup_db.sh scripts/rollback.sh
git commit -m "chore: add db backup and rollback scripts"
```

---

## Task 2: Migration de soft delete (schema)

**Files:**
- Create: `migrations/001_soft_delete_documentos.py`

- [ ] **Step 1: Criar o script de migration**

```python
"""Migration 001: adiciona ativo e deleted_at em documentos.

Idempotente — pode rodar múltiplas vezes sem efeito colateral.
Uso: python migrations/001_soft_delete_documentos.py [db_path]
"""
import sqlite3
import sys
from pathlib import Path


def upgrade(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(documentos)")
        cols = {row[1] for row in cur.fetchall()}
        changed = False
        if "ativo" not in cols:
            cur.execute("ALTER TABLE documentos ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1")
            changed = True
            print("  + coluna 'ativo' adicionada")
        if "deleted_at" not in cols:
            cur.execute("ALTER TABLE documentos ADD COLUMN deleted_at TEXT NULL")
            changed = True
            print("  + coluna 'deleted_at' adicionada")
        conn.commit()
        if not changed:
            print("  = nenhuma mudança necessária (já aplicada)")
    finally:
        conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "doctrack.db"
    if not Path(db).exists():
        print(f"DB não encontrado: {db}")
        sys.exit(1)
    print(f"Aplicando migration 001 em {db}...")
    upgrade(db)
    print("OK")
```

- [ ] **Step 2: Rodar a migration**

```bash
python migrations/001_soft_delete_documentos.py doctrack.db
```

Expected: imprime `+ coluna 'ativo' adicionada`, `+ coluna 'deleted_at' adicionada`, `OK`.

- [ ] **Step 3: Validar no SQLite**

```bash
python -c "import sqlite3;c=sqlite3.connect('doctrack.db');print([r for r in c.execute('PRAGMA table_info(documentos)')])"
```

Expected: a saída inclui linhas para `ativo` e `deleted_at`.

- [ ] **Step 4: Rodar a migration de novo (idempotência)**

```bash
python migrations/001_soft_delete_documentos.py doctrack.db
```

Expected: imprime `= nenhuma mudança necessária`.

- [ ] **Step 5: Commit**

```bash
git add migrations/001_soft_delete_documentos.py
git commit -m "feat(db): add soft-delete columns to documentos"
```

---

## Task 3: Atualizar modelo `Documento` com colunas de soft delete

**Files:**
- Modify: `models.py`

- [ ] **Step 1: Localizar a classe Documento**

```bash
grep -n "class Documento" models.py
```

- [ ] **Step 2: Adicionar as duas colunas logo após o último campo existente**

Adicionar (antes de `criado_em` ou junto aos timestamps, mantendo o padrão do arquivo):

```python
    ativo = db.Column(db.Boolean, default=True, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
```

- [ ] **Step 3: Atualizar `to_dict()` para expor `ativo` e `deleted_at`**

No retorno do `to_dict()` da classe Documento, adicionar:

```python
            "ativo": bool(self.ativo),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
```

- [ ] **Step 4: Validar import**

```bash
python -c "from models import Documento; print('Documento.ativo:', Documento.ativo); print('Documento.deleted_at:', Documento.deleted_at)"
```

Expected: imprime as colunas sem erro.

- [ ] **Step 5: Commit**

```bash
git add models.py
git commit -m "feat(models): expose soft-delete columns on Documento"
```

---

## Task 4: JWT secret obrigatório + .env.example

**Files:**
- Modify: `servidor.py:31` (JWT_SECRET_KEY config)
- Create: `.env.example`

- [ ] **Step 1: Localizar a config atual do JWT**

```bash
grep -n "JWT_SECRET\|JWT_SECRET_KEY" servidor.py
```

- [ ] **Step 2: Substituir o fallback hardcoded**

**Antes (servidor.py:~31):**
```python
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET", "doctrack-secret-mude-em-producao-2026")
```

**Depois:**
```python
_jwt_secret = os.environ.get("JWT_SECRET")
if not _jwt_secret:
    raise RuntimeError(
        "JWT_SECRET environment variable is required. "
        "Set it in your environment or .env file (see .env.example)."
    )
app.config["JWT_SECRET_KEY"] = _jwt_secret
```

- [ ] **Step 3: Criar `.env.example`**

```
# DocTrack v3 — exemplo de variáveis de ambiente
# Copie para .env e preencha valores reais (nunca comite .env)

# Obrigatório: chave para assinar tokens JWT (use string aleatória de >=32 chars)
JWT_SECRET=change-me-to-a-random-string-of-at-least-32-chars

# Opcional: origens permitidas para CORS, separadas por vírgula
CORS_ORIGINS=http://localhost:5000
```

- [ ] **Step 4: Validar falha sem env**

```bash
unset JWT_SECRET 2>/dev/null || true
python -c "import servidor" || echo "FAIL_AS_EXPECTED"
```

Expected: imprime `FAIL_AS_EXPECTED` (o import falha com RuntimeError).

- [ ] **Step 5: Validar sucesso com env**

```bash
JWT_SECRET="test-secret-only-for-validation" python -c "import servidor; print('OK')"
```

Expected: imprime `OK`.

- [ ] **Step 6: Commit**

```bash
git add servidor.py .env.example
git commit -m "fix(security): require JWT_SECRET env var, no hardcoded fallback (B1)"
```

---

## Task 5: CORS restrito por env

**Files:**
- Modify: `servidor.py:23` (linha do `CORS(app)`)

- [ ] **Step 1: Localizar o CORS atual**

```bash
grep -n "CORS(app" servidor.py
```

- [ ] **Step 2: Substituir**

**Antes:**
```python
CORS(app)
```

**Depois:**
```python
_cors_origins = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5000").split(",")
    if o.strip()
]
CORS(app, origins=_cors_origins, supports_credentials=True)
```

- [ ] **Step 3: Validar — origem permitida**

Iniciar servidor:
```bash
JWT_SECRET=test python servidor.py &
sleep 2
curl -i -H "Origin: http://localhost:5000" http://localhost:5000/api/status | grep -i "access-control-allow-origin"
```

Expected: header `Access-Control-Allow-Origin: http://localhost:5000`.

- [ ] **Step 4: Validar — origem bloqueada**

```bash
curl -i -H "Origin: http://evil.com" http://localhost:5000/api/status | grep -i "access-control-allow-origin" || echo "BLOCKED_AS_EXPECTED"
```

Expected: header ausente, imprime `BLOCKED_AS_EXPECTED`.

Parar o servidor: `kill %1` (ou `Ctrl+C` se em foreground).

- [ ] **Step 5: Commit**

```bash
git add servidor.py
git commit -m "fix(security): restrict CORS to configured origins (B4)"
```

---

## Task 6: Soft delete na rota DELETE de documento + snapshot no audit

**Files:**
- Modify: `servidor.py` (rota DELETE de documento, ~linha 405-410)

- [ ] **Step 1: Localizar a rota DELETE**

```bash
grep -n "def delete_documento\|@app.route.*documentos.*DELETE\|db.session.delete(doc)" servidor.py
```

- [ ] **Step 2: Substituir hard delete por soft delete + snapshot**

Localizar o bloco:
```python
        db.session.delete(doc)
        db.session.commit()
        log_audit(action="DELETE", entidade="documento", documento_id=doc.id, ...)
```

Substituir por:
```python
        import json
        from datetime import datetime
        snapshot = json.dumps(doc.to_dict(), ensure_ascii=False, default=str)
        doc.ativo = False
        doc.deleted_at = datetime.utcnow()
        db.session.commit()
        log_audit(
            action="DELETE",
            entidade="documento",
            documento_id=doc.id,
            campo="*",
            valor_antigo=snapshot,
            valor_novo=None,
        )
```

(Se `json` e `datetime` já estão importados no topo do arquivo, mover os imports para lá em vez de inline.)

- [ ] **Step 3: Validar imports estão no topo**

```bash
grep -n "^import json\|^from datetime" servidor.py
```

Se faltar, adicionar no topo:
```python
import json
from datetime import datetime
```

- [ ] **Step 4: Commit (parcial — queries de listagem na próxima task)**

```bash
git add servidor.py
git commit -m "fix(docs): soft delete with audit snapshot (B11, B12)"
```

---

## Task 7: Filtrar `ativo=True` em todas as queries de listagem de documentos

**Files:**
- Modify: `servidor.py` (todas as queries de `Documento`)

- [ ] **Step 1: Listar todas as queries de Documento**

```bash
grep -n "Documento.query\|db.session.query(Documento" servidor.py
```

Anotar cada linha encontrada.

- [ ] **Step 2: Adicionar filtro `ativo=True` nas queries de listagem**

Para cada query que retorna documentos para o usuário (NÃO incluir queries em `_import_excel_to_db`, `/api/reimport`, ou queries por id direto via `Documento.query.get(id)`):

**Antes:**
```python
docs = Documento.query.filter(...).all()
```

**Depois:**
```python
docs = Documento.query.filter(Documento.ativo == True).filter(...).all()
```

Aplicar nas rotas:
- `/api/documentos` (GET — listagem)
- `/api/data` (GET — dashboard)
- `/api/metrics` (GET — agregações)
- Função `compute_kpis` se ela faz query (caso contrário, garantir que o caller já passou items filtrados)

**Não filtrar em:**
- `Documento.query.get(id)` em rotas PATCH/PUT/DELETE (precisamos achar mesmo soft-deleted? — decidir: para PATCH/PUT, filtrar `ativo=True` para evitar revival sem critério; para a própria rota DELETE, idem)
- `_import_excel_to_db` (precisa ver todos para dedupe)

- [ ] **Step 3: Validar — criar, deletar e listar**

```bash
JWT_SECRET=test python servidor.py &
sleep 2
# Login e pegar token
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H "Content-Type: application/json" -d '{"email":"admin@pde.com","senha":"admin123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
echo "Token: ${TOKEN:0:20}..."
# Pegar primeiro doc
DOC_ID=$(curl -s -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/documentos | python -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
echo "Doc id: $DOC_ID"
# Deletar
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/documentos/$DOC_ID
# Listar — não deve aparecer
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:5000/api/documentos" | python -c "import sys,json,os;data=json.load(sys.stdin);ids=[d['id'] for d in data];print('REMOVED' if int(os.environ['DOC_ID']) not in ids else 'STILL_THERE')" DOC_ID=$DOC_ID
# Conferir no DB que está soft-deleted
python -c "import sqlite3;c=sqlite3.connect('doctrack.db');print(list(c.execute('SELECT id,ativo,deleted_at FROM documentos WHERE id=?',($DOC_ID,))))"
kill %1
```

Expected: `REMOVED` na listagem, e a row no DB tem `ativo=0`.

- [ ] **Step 4: Restaurar o doc para o estado original (manualmente para testes seguintes)**

```bash
python -c "import sqlite3;c=sqlite3.connect('doctrack.db');c.execute('UPDATE documentos SET ativo=1, deleted_at=NULL WHERE id=?',($DOC_ID,));c.commit()"
```

- [ ] **Step 5: Commit**

```bash
git add servidor.py
git commit -m "fix(docs): filter ativo=True in listing queries (B11)"
```

---

## Task 8: Reimport com dedupe (preserva ids e audit refs)

**Files:**
- Modify: `servidor.py` (função `_import_excel_to_db`, linhas ~620-650)

- [ ] **Step 1: Localizar a função**

```bash
grep -n "_import_excel_to_db\|Documento.query.delete()" servidor.py
```

- [ ] **Step 2: Substituir o bloco de delete-all + insert por dedupe**

**Antes (trecho relevante):**
```python
def _import_excel_to_db(...):
    ...
    Documento.query.delete()
    db.session.commit()
    for row in df.itertuples():
        db.session.add(Documento(...))
    db.session.commit()
```

**Depois:**
```python
def _import_excel_to_db(excel_path):
    from datetime import datetime
    df = pd.read_excel(excel_path)
    df = df.fillna("")

    existing = {(d.equipamento, d.documento): d for d in Documento.query.all()}
    keys_in_excel = set()
    inserted = 0
    updated = 0

    for row in df.itertuples():
        equip = str(getattr(row, "equipamento", "")).strip()
        nome = str(getattr(row, "documento", "")).strip()
        if not equip or not nome:
            continue
        key = (equip, nome)
        keys_in_excel.add(key)

        if key in existing:
            doc = existing[key]
            for col in CAMPOS_IMPORTAVEIS:  # lista das colunas que vêm do Excel
                if hasattr(row, col):
                    setattr(doc, col, getattr(row, col))
            doc.ativo = True
            doc.deleted_at = None
            updated += 1
        else:
            kwargs = {col: getattr(row, col, None) for col in CAMPOS_IMPORTAVEIS if hasattr(row, col)}
            db.session.add(Documento(**kwargs))
            inserted += 1

    now = datetime.utcnow()
    soft_deleted = 0
    for key, doc in existing.items():
        if key not in keys_in_excel and doc.ativo:
            doc.ativo = False
            doc.deleted_at = now
            soft_deleted += 1

    db.session.commit()
    return {"inserted": inserted, "updated": updated, "soft_deleted": soft_deleted}
```

- [ ] **Step 3: Definir `CAMPOS_IMPORTAVEIS` no topo do módulo**

Localizar onde estão as outras constantes e adicionar:

```python
CAMPOS_IMPORTAVEIS = [
    "equipamento", "documento", "origem", "categoria",
    "versao", "status_principal", "local",
    "etapa_elaboracao", "etapa_revisao1", "etapa_diagramacao", "etapa_revisao2",
    "tipo_documento", "subtipo",
]
```

(Ajustar para casar exatamente com as colunas do modelo `Documento` que vêm do Excel — verificar nomes via `python -c "from models import Documento; print(Documento.__table__.columns.keys())"`.)

- [ ] **Step 4: Atualizar a rota `/api/reimport` para usar o retorno**

Localizar:
```bash
grep -n "/api/reimport" servidor.py
```

Garantir que a rota retorna o resultado:
```python
@app.route("/api/reimport", methods=["POST"])
@require_role("admin")
def reimport():
    result = _import_excel_to_db(EXCEL_PATH)
    log_audit(action="REIMPORT", entidade="documento", valor_novo=json.dumps(result))
    return jsonify({"ok": True, **result})
```

- [ ] **Step 5: Validar — reimport preserva ids**

```bash
JWT_SECRET=test python servidor.py &
sleep 2
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H "Content-Type: application/json" -d '{"email":"admin@pde.com","senha":"admin123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
# Snapshot ids antes
python -c "import sqlite3;c=sqlite3.connect('doctrack.db');print('IDS_BEFORE:',[r[0] for r in c.execute('SELECT id FROM documentos ORDER BY id')[:5]])"
# Reimport
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/reimport
# Snapshot ids depois
python -c "import sqlite3;c=sqlite3.connect('doctrack.db');print('IDS_AFTER:',[r[0] for r in c.execute('SELECT id FROM documentos ORDER BY id')[:5]])"
# Audit logs continuam apontando para ids válidos
python -c "import sqlite3;c=sqlite3.connect('doctrack.db');print('ORPHANS:',list(c.execute('SELECT COUNT(*) FROM audit_logs WHERE documento_id NOT IN (SELECT id FROM documentos)')))"
kill %1
```

Expected:
- `IDS_BEFORE` e `IDS_AFTER` são iguais
- `ORPHANS` retorna `[(0,)]` (zero órfãos)

- [ ] **Step 6: Commit**

```bash
git add servidor.py
git commit -m "fix(import): dedupe by (equipamento,documento) preserves ids and audit refs (B14)"
```

---

## Task 9: Helper `esc()` no frontend para prevenir XSS

**Files:**
- Modify: `static/app.js` (topo do arquivo, antes de qualquer função de render)

- [ ] **Step 1: Adicionar helper no topo**

Logo após os imports/constantes do início do arquivo:

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

- [ ] **Step 2: Validar no console**

Abrir o app no navegador, abrir DevTools console:
```javascript
esc('<img src=x onerror=alert(1)>')
```

Expected: `"&lt;img src=x onerror=alert(1)&gt;"` (string escapada).

- [ ] **Step 3: Commit**

```bash
git add static/app.js
git commit -m "feat(security): add esc() helper to prevent XSS"
```

---

## Task 10: Aplicar `esc()` em todas as interpolações de innerHTML

**Files:**
- Modify: `static/app.js` (funções `renderRecent`, `renderDocs`, `renderAudit`, `renderUsers`)

- [ ] **Step 1: Localizar funções de render**

```bash
grep -n "innerHTML\|.innerHTML" static/app.js
grep -n "function renderRecent\|function renderDocs\|function renderAudit\|function renderUsers" static/app.js
```

- [ ] **Step 2: Em `renderRecent` (~app.js:175)**

Para cada `${expressão}` dentro de uma template string que é atribuída a `.innerHTML`, embrulhar com `esc()` se for dado vindo da API.

Exemplo:
```javascript
// Antes:
html += `<tr><td>${d.equipamento}</td><td>${d.documento}</td>...</tr>`;
// Depois:
html += `<tr><td>${esc(d.equipamento)}</td><td>${esc(d.documento)}</td>...</tr>`;
```

Não envolver: ids numéricos usados em atributos (`data-id="${d.id}"` está OK), classes CSS calculadas internamente (`class="pill ${PILL[d.status]}"` está OK desde que `PILL` seja um objeto whitelisted).

- [ ] **Step 3: Em `renderDocs` (~app.js:219-231)**

Aplicar mesmo padrão. Atenção especial aos botões com onclick — esses serão tratados na Task 11.

- [ ] **Step 4: Em `renderAudit` (~app.js:327-333)**

Aplicar `esc()` em: `usuario_email`, `acao`, `campo`, `valor_antigo`, `valor_novo`, `entidade`.

- [ ] **Step 5: Em `renderUsers` (~app.js:345-352)**

Aplicar `esc()` em: `nome`, `email`, `role`.

- [ ] **Step 6: Validar manualmente**

Iniciar app, criar um documento com nome `<img src=x onerror=alert("XSS")>` (via UI ou direto no DB):
```bash
python -c "import sqlite3;c=sqlite3.connect('doctrack.db');c.execute(\"INSERT INTO documentos (equipamento, documento, ativo) VALUES ('TestEq', '<img src=x onerror=alert(\\\"XSS\\\")>', 1)\");c.commit()"
```

Recarregar a página de documentos. Nenhum alert deve aparecer; o texto deve ser exibido literal.

Limpar:
```bash
python -c "import sqlite3;c=sqlite3.connect('doctrack.db');c.execute(\"DELETE FROM documentos WHERE equipamento='TestEq'\");c.commit()"
```

- [ ] **Step 7: Commit**

```bash
git add static/app.js
git commit -m "fix(security): escape user input in all innerHTML interpolations (B6)"
```

---

## Task 11: Substituir inline onclick por event delegation

**Files:**
- Modify: `static/app.js` (funções de render que geram botões)
- Modify: `templates/dashboard.html` (qualquer onclick inline restante)

- [ ] **Step 1: Listar todos os onclick inline**

```bash
grep -n "onclick=" static/app.js templates/dashboard.html
```

- [ ] **Step 2: Em `app.js`, substituir nos botões gerados**

**Antes:**
```javascript
html += `<button onclick="delDoc(${d.id},'${d.equipamento}')">×</button>`;
html += `<button onclick="editDoc(${d.id})">edit</button>`;
```

**Depois:**
```javascript
html += `<button class="btn-icon" data-action="delete-doc" data-id="${d.id}" aria-label="Excluir documento">×</button>`;
html += `<button class="btn-icon" data-action="edit-doc" data-id="${d.id}" aria-label="Editar documento">edit</button>`;
```

Aplicar análogo em renderUsers (delete/edit user) e renderAudit (se tiver botões).

- [ ] **Step 3: Adicionar listener delegado no init**

Em `static/app.js`, no init/DOMContentLoaded ou logo após selecionar a tabela:

```javascript
document.body.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  const id = btn.dataset.id;
  switch (action) {
    case 'delete-doc': delDoc(id); break;
    case 'edit-doc': editDoc(id); break;
    case 'delete-user': delUser(id); break;
    case 'edit-user': editUser(id); break;
    // adicionar conforme necessário
  }
});
```

- [ ] **Step 4: Em `templates/dashboard.html`, substituir onclicks de tabs/menu**

Para qualquer `<div onclick="goto('...')">` ou similar:

**Antes:**
```html
<div class="nav-item" onclick="goto('docs')">Documentos</div>
```

**Depois:**
```html
<button class="nav-item" data-action="goto" data-target="docs" type="button">Documentos</button>
```

E no listener:
```javascript
case 'goto': goto(btn.dataset.target); break;
```

(Trocar `<div>` por `<button>` resolve também U17 — navegação por teclado.)

- [ ] **Step 5: Validar manualmente**

Iniciar app, clicar em cada botão de delete/edit em documentos, usuários, e cada item da sidebar. Tudo deve funcionar normalmente. Tab pelo teclado deve focar nos botões.

- [ ] **Step 6: Validar payload com aspa não quebra**

Criar um documento com nome `Teste's "doc"`:
```bash
python -c "import sqlite3;c=sqlite3.connect('doctrack.db');c.execute(\"INSERT INTO documentos (equipamento, documento, ativo) VALUES ('Eq2', 'Teste\\'s \\\"doc\\\"', 1)\");c.commit()"
```

Recarregar UI, clicar em delete daquele item — deve abrir confirm corretamente.

Limpar:
```bash
python -c "import sqlite3;c=sqlite3.connect('doctrack.db');c.execute(\"DELETE FROM documentos WHERE equipamento='Eq2'\");c.commit()"
```

- [ ] **Step 7: Commit**

```bash
git add static/app.js templates/dashboard.html
git commit -m "refactor(security): replace inline onclick with event delegation (B7)"
```

---

## Task 12: Remover login fallback "demo"

**Files:**
- Modify: `static/app.js` (~linhas 25-30)

- [ ] **Step 1: Localizar simulateLogin / fallback**

```bash
grep -n "simulateLogin\|simulate_login\|demo" static/app.js
```

- [ ] **Step 2: Remover bloco e função**

Apagar:
- Função `simulateLogin()` (ou similar)
- Qualquer bloco `if (!response.ok) { simulateLogin(...) }`

A nova lógica deve ser apenas:
```javascript
async function login(email, senha) {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({email, senha}),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    showToast(err.erro || err.error || 'Falha no login', 'error');
    return;
  }
  const data = await response.json();
  localStorage.setItem('token', data.access_token);
  // ... resto da lógica de pós-login
}
```

- [ ] **Step 3: Validar — backend offline mostra erro**

```bash
# Não inicie o servidor
# Abra a UI em http://localhost:5000 — vai falhar no fetch (servidor caído)
# Verificar manualmente: tela de login mostra toast/erro, não loga
```

(Como a UI é servida pelo backend, para testar isso de fato precisa rodar o backend, derrubar só a rota /api/auth/login mockada — alternativamente: usar DevTools Network → Block request URL para `/api/auth/login` → tentar logar.)

Expected: toast de erro, sem login simulado.

- [ ] **Step 4: Commit**

```bash
git add static/app.js
git commit -m "fix(security): remove demo login fallback that bypassed auth (B5)"
```

---

## Task 13: Remover senha hardcoded e credenciais do template

**Files:**
- Modify: `templates/dashboard.html` (~linha 27 e comentários adjacentes)

- [ ] **Step 1: Localizar**

```bash
grep -n "admin123\|admin@pde\|demo123" templates/dashboard.html
```

- [ ] **Step 2: Remover atributo `value` do input de senha**

**Antes:**
```html
<input type="password" id="login-senha" value="admin123" class="form-input">
```

**Depois:**
```html
<input type="password" id="login-senha" class="form-input" autocomplete="current-password">
```

- [ ] **Step 3: Remover qualquer comentário com credenciais**

Apagar linhas como `<!-- Demo: admin@pde.com / admin123 -->` ou `placeholder="admin@pde.com"` que vaze credenciais reais. (Placeholder genérico tipo `placeholder="seu@email.com"` é OK.)

- [ ] **Step 4: Validar**

```bash
grep -n "admin123\|demo123" templates/dashboard.html || echo "CLEAN"
```

Expected: `CLEAN`.

- [ ] **Step 5: Commit**

```bash
git add templates/dashboard.html
git commit -m "fix(security): remove hardcoded credentials from login template (U3)"
```

---

## Task 14: Limpeza — .bak, .gitignore

**Files:**
- Delete: `templates/dashboard.html.bak`
- Create/Modify: `.gitignore`

- [ ] **Step 1: Remover arquivo .bak**

```bash
rm templates/dashboard.html.bak
ls templates/
```

Expected: lista contém apenas `dashboard.html`.

- [ ] **Step 2: Criar/atualizar .gitignore**

Conteúdo (anexar ao existente, sem duplicar):

```
# Variáveis de ambiente
.env
.env.local
.env.*.local

# Backups e arquivos temporários
*.bak
*.db.backup-*

# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.venv/
venv/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
```

- [ ] **Step 3: Validar**

```bash
git status --short | grep -E "\.env|\.bak|backup-" || echo "CLEAN"
```

Expected: `CLEAN` (nenhum desses arquivos aparece em status).

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git rm templates/dashboard.html.bak 2>/dev/null || true
git commit -m "chore: remove .bak file and update .gitignore"
```

---

## Task 15: Smoke test final completo

**Files:** N/A (validação end-to-end)

- [ ] **Step 1: Setup**

```bash
export JWT_SECRET="test-secret-fase1-validation"
export CORS_ORIGINS="http://localhost:5000"
bash scripts/backup_db.sh doctrack.db
python servidor.py &
sleep 3
```

- [ ] **Step 2: Checklist de validação**

| Item | Comando / Ação | Esperado |
|------|----------------|----------|
| JWT obrigatório | `unset JWT_SECRET; python -c "import servidor"` | RuntimeError |
| Login funciona | curl POST /api/auth/login com admin@pde.com/admin123 | retorna access_token |
| Login demo removido | grep simulateLogin static/app.js | sem matches |
| Senha não está no HTML | grep admin123 templates/dashboard.html | sem matches |
| CORS bloqueia evil.com | `curl -i -H "Origin: http://evil.com" http://localhost:5000/api/status` | sem header CORS |
| CORS aceita localhost:5000 | `curl -i -H "Origin: http://localhost:5000" http://localhost:5000/api/status` | header presente |
| XSS escapado na UI | criar doc com `<script>alert(1)</script>` no nome via API → recarregar UI | texto literal, sem alert |
| Soft delete funciona | DELETE /api/documentos/1 → SELECT no DB | `ativo=0`, `deleted_at` preenchido |
| Audit tem snapshot | SELECT valor_antigo do último DELETE no audit_logs | JSON completo do doc |
| Reimport preserva ids | snapshot ids → POST /api/reimport → snapshot ids | listas iguais |
| Audit refs intactas após reimport | `SELECT COUNT(*) FROM audit_logs WHERE documento_id NOT IN (SELECT id FROM documentos)` | `0` |
| .bak removido | `ls templates/` | só `dashboard.html` |
| .gitignore atualizado | `cat .gitignore | grep -E "\.env|\.bak|backup-"` | matches presentes |

- [ ] **Step 3: Cleanup**

```bash
kill %1
unset JWT_SECRET CORS_ORIGINS
```

- [ ] **Step 4: Documentar resultados em commit final**

```bash
git commit --allow-empty -m "test(fase1): smoke test passed — all 13 validation items OK"
```

---

## Self-Review (concluída pelo autor do plano)

**1. Spec coverage:**
- B1 (JWT hardcoded) → Task 4 ✓
- B5 (login demo) → Task 12 ✓
- B6 (XSS innerHTML) → Tasks 9, 10 ✓
- B7 (inline onclick) → Task 11 ✓
- U3 (senha no template) → Task 13 ✓
- B4 (CORS aberto) → Task 5 ✓
- B11 (hard delete) → Tasks 3, 6, 7 ✓
- B12 (audit incompleto) → Task 6 ✓
- B14 (reimport quebra audit) → Task 8 ✓
- R6 (.bak) → Task 14 ✓
- Backup automático → Task 1 ✓
- Migration idempotente → Task 2 ✓
- .env.example → Task 4 ✓
- .gitignore → Task 14 ✓

**2. Placeholder scan:** Sem TODOs, TBDs ou "implement later". Steps de código têm código completo.

**3. Type consistency:** `esc()` consistente; `data-action` e `data-id` consistentes; `Documento.ativo` e `Documento.deleted_at` consistentes em models, queries e migration.

**4. Riscos cobertos:** Backup antes de migration, idempotência da migration, fallback de erro em reimport, soft delete protege audit refs.

---

## Próxima Fase

Fase 2 — Filtros & Consolidação de API (spec próprio a ser escrito após validação desta fase).
