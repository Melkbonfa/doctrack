# Reestruturação de Tipos de Documentos — DocTrack PDE

> **Para workers agênticos:** Use superpowers:executing-plans para implementar task a task com checkpoints.

**Goal:** Substituir a divisão atual PRE/Manuais por 9 tipos de documento individuais com abas dedicadas no modal de equipamento, adicionando o campo "nome original" pesquisável mas oculto no card.

**Arquitetura:** Mantém o setor (`PRE` ou `Manuais`) como agrupador de status, mas adiciona `tipo_doc` obrigatório em todos os documentos (inclusive PRE). Cada equipamento passa a ter exatamente 9 registros de Documento — um por tipo. O campo `nome_original` é adicionado à tabela `documentos` e incluído no blob de busca, mas não exibido no card inicial.

**Tech Stack:** Python/Flask · SQLAlchemy · PostgreSQL · Vanilla JS (app.js) · Alembic-free (migração manual SQL)

---

## Contexto atual (importante para não quebrar nada)

```
setor="PRE"     → 1 doc por equipamento, sem tipo_doc, status: Elaborar → Treinamento Piloto → Enviado para Homologação → Homologado
setor="Manuais" → 5 docs por equipamento (um por tipo_doc): Manual_ES, Manual_Servico, Manual_Usuario, QIQOQD, Spare_Parts
                   status: Elaborar → Em andamento → Concluído
```

## Estado alvo

| Aba | tipo_doc | setor | Status pipeline |
|---|---|---|---|
| Instrução de Trabalho | `IT` | PRE | Elaborar → Treinamento Piloto → Enviado para Homologação → Homologado |
| Checklist | `Checklist` | PRE | Elaborar → Treinamento Piloto → Enviado para Homologação → Homologado |
| Manual do Usuário PT | `Manual_Usuario` | Manuais | Elaborar → Em andamento → Concluído |
| Manual do Usuário ES | `Manual_ES` | Manuais | Elaborar → Em andamento → Concluído |
| Manual de Serviço | `Manual_Servico` | Manuais | Elaborar → Em andamento → Concluído |
| Spare Parts | `Spare_Parts` | Manuais | Elaborar → Em andamento → Concluído |
| Dossiê | `Dossie` | Manuais | Elaborar → Em andamento → Concluído |
| Guia de Instalação | `Guia_Instalacao` | Manuais | Elaborar → Em andamento → Concluído |
| QI/QO/QD | `QIQOQD` | Manuais | Elaborar → Em andamento → Concluído |

**nome_original**: novo campo de texto livre no Documento (mesmo valor para todos os docs do equipamento). Incluso no blob de busca. Não aparece no card da tabela principal.

---

## Mapa de arquivos

| Arquivo | O que muda |
|---|---|
| `models.py` | Novos constants `TIPOS_DOC_PRE`, `TIPOS_DOC_FABRICANTE` atualizado, `TIPOS_DOC_LABELS` completo, coluna `nome_original` no modelo `Documento` |
| `servidor.py` | `init_db` seed, lógica de criação (`/api/documentos`), busca (blob), enums (`/api/enums`), categorização de arquivos (`/api/documentos/arquivos`) |
| `static/app.js` | Modal de equipamento com 9 abas, campo nome_original no form, blob de busca no cliente, exibição de abas no modal de visualização |
| `migrations/001_nome_original_e_tipo_pre.sql` | ALTER TABLE + UPDATE para migrar dados existentes |

---

## Task 1 — Atualizar constants em `models.py`

**Arquivos:**
- Modify: `models.py:20-38`

- [ ] **1.1 Substituir bloco de constantes**

```python
# models.py — substituir linhas 20-38

SETORES = ["PRE", "Manuais"]

STATUS_PRE = ["Elaborar", "Treinamento Piloto", "Enviado para Homologação", "Homologado"]
STATUS_FABRICANTE = ["Elaborar", "Em andamento", "Concluído"]

STATUS_MAP = {
    "PRE": STATUS_PRE,
    "Manuais": STATUS_FABRICANTE,
}

TIPOS_DOC_PRE = ["IT", "Checklist"]

TIPOS_DOC_FABRICANTE = [
    "Manual_Usuario",
    "Manual_ES",
    "Manual_Servico",
    "Spare_Parts",
    "Dossie",
    "Guia_Instalacao",
    "QIQOQD",
]

TIPOS_DOC_LABELS = {
    "IT":              "Instrução de Trabalho",
    "Checklist":       "Checklist",
    "Manual_Usuario":  "Manual do Usuário PT",
    "Manual_ES":       "Manual do Usuário ES",
    "Manual_Servico":  "Manual de Serviço",
    "Spare_Parts":     "Spare Parts",
    "Dossie":          "Dossiê",
    "Guia_Instalacao": "Guia de Instalação",
    "QIQOQD":          "QI/QO/QD",
}
```

- [ ] **1.2 Adicionar coluna `nome_original` ao modelo Documento** (após `armazenamento`, linha ~175)

```python
nome_original   = db.Column(db.String(300), default="")
```

- [ ] **1.3 Adicionar `nome_original` ao `to_dict()`** (dentro do return dict):

```python
"nome_original": self.nome_original or "",
```

- [ ] **1.4 Adicionar `nome_original` ao `CAMPOS_STR`** em `servidor.py` (linha ~553):

```python
CAMPOS_STR = ["equipamento", "sku", "codigo_doc", "documento", "responsavel",
              "status", "tipo_doc", "fabricante", "obs_treinamento",
              "obs_homologacao", "armazenamento", "nome_original"]
```

- [ ] **1.5 Commit**
```
git add models.py servidor.py
git commit -m "feat: adiciona nome_original e reestrutura constants de tipos de documento"
```

---

## Task 2 — Migração SQL do banco

**Arquivos:**
- Create: `migrations/001_nome_original_e_tipo_pre.sql`

- [ ] **2.1 Criar script de migração**

```sql
-- migrations/001_nome_original_e_tipo_pre.sql
-- Adiciona coluna nome_original
ALTER TABLE documentos ADD COLUMN IF NOT EXISTS nome_original VARCHAR(300) DEFAULT '';

-- Marca todos os docs PRE existentes como tipo_doc='IT'
-- (PRE não tinha tipo_doc; agora passa a ter)
UPDATE documentos
SET tipo_doc = 'IT'
WHERE setor = 'PRE'
  AND (tipo_doc IS NULL OR tipo_doc = '')
  AND ativo = TRUE;

-- Cria documento Checklist para cada equipamento que tem IT mas não tem Checklist
INSERT INTO documentos
    (setor, equipamento, sku, codigo_doc, documento, responsavel, status,
     tipo_doc, fabricante, armazenamento, nome_original, ativo, criado_em, updated_em, version)
SELECT
    'PRE',
    d.equipamento,
    d.sku,
    '',
    'Checklist - ' || d.equipamento,
    d.responsavel,
    'Elaborar',
    'Checklist',
    d.fabricante,
    d.armazenamento,
    d.nome_original,
    TRUE,
    NOW(),
    NOW(),
    0
FROM documentos d
WHERE d.setor = 'PRE'
  AND d.tipo_doc = 'IT'
  AND d.ativo = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM documentos c
    WHERE c.equipamento = d.equipamento
      AND c.sku = d.sku
      AND c.tipo_doc = 'Checklist'
      AND c.ativo = TRUE
  );

-- Cria Dossie para cada equipamento que ainda não tem
INSERT INTO documentos
    (setor, equipamento, sku, codigo_doc, documento, responsavel, status,
     tipo_doc, fabricante, armazenamento, nome_original, ativo, criado_em, updated_em, version)
SELECT
    'Manuais',
    d.equipamento,
    d.sku,
    '',
    'Dossiê - ' || d.equipamento,
    '',
    'Elaborar',
    'Dossie',
    d.fabricante,
    d.armazenamento,
    d.nome_original,
    TRUE,
    NOW(),
    NOW(),
    0
FROM documentos d
WHERE d.setor = 'PRE'
  AND d.tipo_doc = 'IT'
  AND d.ativo = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM documentos x
    WHERE x.equipamento = d.equipamento
      AND x.sku = d.sku
      AND x.tipo_doc = 'Dossie'
      AND x.ativo = TRUE
  );

-- Cria Guia_Instalacao para cada equipamento que ainda não tem
INSERT INTO documentos
    (setor, equipamento, sku, codigo_doc, documento, responsavel, status,
     tipo_doc, fabricante, armazenamento, nome_original, ativo, criado_em, updated_em, version)
SELECT
    'Manuais',
    d.equipamento,
    d.sku,
    '',
    'Guia de Instalação - ' || d.equipamento,
    '',
    'Elaborar',
    'Guia_Instalacao',
    d.fabricante,
    d.armazenamento,
    d.nome_original,
    TRUE,
    NOW(),
    NOW(),
    0
FROM documentos d
WHERE d.setor = 'PRE'
  AND d.tipo_doc = 'IT'
  AND d.ativo = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM documentos x
    WHERE x.equipamento = d.equipamento
      AND x.sku = d.sku
      AND x.tipo_doc = 'Guia_Instalacao'
      AND x.ativo = TRUE
  );
```

- [ ] **2.2 Executar a migração**

```powershell
psql -U doctrack_app -d doctrack -f migrations/001_nome_original_e_tipo_pre.sql
```

Resultado esperado: `ALTER TABLE`, `UPDATE X`, `INSERT X`, `INSERT X`, `INSERT X` sem erros.

- [ ] **2.3 Verificar**

```sql
SELECT tipo_doc, COUNT(*) FROM documentos WHERE ativo=TRUE GROUP BY tipo_doc ORDER BY tipo_doc;
```

Deve mostrar todos os 9 tipos.

- [ ] **2.4 Commit**
```
git add migrations/
git commit -m "feat: migration SQL — nome_original + Checklist/Dossie/Guia_Instalacao por equipamento"
```

---

## Task 3 — Atualizar `servidor.py`: enums, criação e busca

**Arquivos:**
- Modify: `servidor.py`

- [ ] **3.1 Atualizar import de constants** (linha ~75):

```python
from models import (
    db, bcrypt, User, Documento, AuditLog, RevokedToken, Responsavel,
    SETORES, STATUS_PRE, STATUS_FABRICANTE, STATUS_MAP,
    TIPOS_DOC_PRE, TIPOS_DOC_FABRICANTE, TIPOS_DOC_LABELS
)
```

- [ ] **3.2 Atualizar `/api/enums`** — substituir `tipos_doc_fabricante` por lista unificada:

```python
return jsonify({
    ...
    "tipos_doc_pre":        TIPOS_DOC_PRE,
    "tipos_doc_fabricante": TIPOS_DOC_FABRICANTE,
    "tipos_doc_labels":     TIPOS_DOC_LABELS,
    ...
})
```

- [ ] **3.3 Atualizar lógica de criação de equipamento** (`/api/documentos` POST, bloco `setor == "Manuais"`):

```python
# Substituir tipos_exigidos e lógica de criação automática dos irmãos
if setor == "PRE":
    tipos_exigidos = TIPOS_DOC_PRE
    selected_tipo  = data.get("tipo_doc", "IT")
else:  # Manuais
    tipos_exigidos = TIPOS_DOC_FABRICANTE
    selected_tipo  = data.get("tipo_doc", "")
```

O bloco que cria os documentos irmãos (quando não existem) já itera sobre `tipos_exigidos` — basta garantir que `TIPOS_DOC_PRE` esteja sendo usado para PRE.

- [ ] **3.4 Atualizar blob de busca** (linha ~403):

```python
blob = " ".join(norm(str(d.get(f, ""))) for f in (
    "equipamento", "documento", "codigo_doc", "sku",
    "responsavel", "armazenamento", "tipo_doc", "fabricante", "nome_original"
))
```

- [ ] **3.5 Atualizar categorização de arquivos** (`/api/documentos/arquivos`, linha ~757):

```python
# Substitui classificação hardcoded IT/Checklist/Outros por tipo_doc do documento
# A rota já recebe ?caminho=...; adicionar ?tipo_doc= opcional para categorizar
# Se tipo_doc não informado, mantém a heurística atual de nome de arquivo
```

- [ ] **3.6 Commit**

```
git add servidor.py
git commit -m "feat: servidor — enums, busca e criação para 9 tipos de documento"
```

---

## Task 4 — Atualizar `app.js`: modal com 9 abas

**Arquivos:**
- Modify: `static/app.js`

- [ ] **4.1 Atualizar `_MAN_TIPOS` e adicionar `_PRE_TIPOS`**

```js
const _PRE_TIPOS = [
  ['IT',        'Instrução de Trabalho'],
  ['Checklist', 'Checklist'],
];

const _MAN_TIPOS = [
  ['Manual_Usuario',  'Manual do Usuário PT'],
  ['Manual_ES',       'Manual do Usuário ES'],
  ['Manual_Servico',  'Manual de Serviço'],
  ['Spare_Parts',     'Spare Parts'],
  ['Dossie',          'Dossiê'],
  ['Guia_Instalacao', 'Guia de Instalação'],
  ['QIQOQD',          'QI/QO/QD'],
];
```

- [ ] **4.2 Atualizar `switchEquipTab`** para suportar 9 abas (IT, Checklist, Manual_Usuario, Manual_ES, Manual_Servico, Spare_Parts, Dossie, Guia_Instalacao, QIQOQD):

```js
function switchEquipTab(tab) {
  document.querySelectorAll('.equip-modal-tab')
    .forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.equip-panel')
    .forEach(p => p.classList.toggle('active', p.dataset.panel === tab));
}
```

- [ ] **4.3 Atualizar `renderEquipModal`** para gerar abas dinamicamente a partir de `_PRE_TIPOS` + `_MAN_TIPOS`:

```js
function renderEquipModal(docs) {
  const allTipos = [..._PRE_TIPOS, ..._MAN_TIPOS];
  const tabs = allTipos.map(([tipo, label]) =>
    `<button class="equip-modal-tab" data-tab="${tipo}" onclick="switchEquipTab('${tipo}')">${label}</button>`
  ).join('');

  const panels = allTipos.map(([tipo]) => {
    const doc = docs.find(d => d.tipo_doc === tipo) || null;
    return `<div class="equip-panel" data-panel="${tipo}">${renderTipoPanel(tipo, doc)}</div>`;
  }).join('');

  return `<div class="equip-modal-tabs">${tabs}</div><div class="equip-panels">${panels}</div>`;
}
```

- [ ] **4.4 Criar `renderTipoPanel(tipo, doc)`** — renderiza o painel de um tipo específico com status, responsável, obs, etc. Usa `_PRE_STATUS` se `tipo ∈ _PRE_TIPOS`, senão `_MAN_STATUS`.

```js
function renderTipoPanel(tipo, doc) {
  const isPreTipo = _PRE_TIPOS.some(([t]) => t === tipo);
  const statusOpts = isPreTipo ? _PRE_STATUS : _MAN_STATUS;
  const status = doc?.status || 'Elaborar';
  // ... renderiza formulário / pills de status / campo obs
}
```

- [ ] **4.5 Adicionar campo `nome_original` no formulário de novo equipamento**

```js
// No form de criação (seção onde equipamento/sku são preenchidos), adicionar:
`<label>Nome Original do Equipamento
  <input id="eq-nome-original" type="text" placeholder="Ex: Gentier 96E" />
</label>`
// Incluir no payload de criação:
nome_original: document.getElementById('eq-nome-original').value.trim()
```

- [ ] **4.6 Garantir que `nome_original` NÃO aparece no card da tabela principal**

O card atual (linha ~698) exibe: equipamento, documento, setor, status_global, sku. Não adicionar `nome_original` aqui.

- [ ] **4.7 Incluir `nome_original` na busca client-side**

```js
// No blob de matches (função que filtra `docsView`):
const blob = [d.equipamento, d.documento, d.sku, d.codigo_doc,
              d.responsavel, d.fabricante, d.nome_original].join(' ').toLowerCase();
```

- [ ] **4.8 Exibir `nome_original` dentro do modal do equipamento** (header do modal, discreto):

```js
// No cabeçalho do modal de detalhes do equipamento, após o nome principal:
${doc.nome_original ? `<span class="equip-nome-original">${esc(doc.nome_original)}</span>` : ''}
```

- [ ] **4.9 Commit**

```
git add static/app.js
git commit -m "feat: modal de equipamento com 9 abas de tipo de documento + campo nome_original"
```

---

## Task 5 — CSS para as novas abas

**Arquivos:**
- Modify: `static/app.js` (estilos inline ou arquivo CSS existente)

- [ ] **5.1 Garantir scroll horizontal nas abas** (9 abas não cabem em linha sem quebrar):

```css
.equip-modal-tabs {
  display: flex;
  overflow-x: auto;
  gap: 4px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border);
}
.equip-modal-tab {
  flex-shrink: 0;
  padding: 6px 14px;
  border-radius: 6px 6px 0 0;
  font-size: 12px;
  white-space: nowrap;
}
.equip-modal-tab.active {
  background: var(--accent);
  color: #fff;
}
.equip-nome-original {
  font-size: 11px;
  color: var(--t3);
  margin-left: 8px;
}
```

- [ ] **5.2 Commit**

```
git add static/app.js
git commit -m "style: abas do modal de equipamento com scroll horizontal"
```

---

## Task 6 — Atualizar `init_db` para novos equipamentos

**Arquivos:**
- Modify: `servidor.py` — função `init_db` (bloco de seed)

- [ ] **6.1 Garantir que o seed do Excel cria os 9 tipos** ao importar um novo equipamento:

No bloco de seed (linha ~270), `cols_tipos` já mapeia algumas colunas do Excel para tipos. Adicionar as novas:

```python
cols_tipos = {
    "Manuais ES":          "Manual_ES",
    "Manual ES":           "Manual_ES",
    "Manual de Serviço":   "Manual_Servico",
    "Manual do Usuário":   "Manual_Usuario",
    "QI/QO/QD":            "QIQOQD",
    "Spare Parts":         "Spare_Parts",
    "Dossiê":              "Dossie",
    "Guia de Instalação":  "Guia_Instalacao",
}
```

Garantir que, após seed, também sejam criados `Checklist`, `Dossie` e `Guia_Instalacao` para equipamentos que vieram do Excel sem essas colunas (usar insert-if-not-exists pattern já existente).

- [ ] **6.2 Commit**

```
git add servidor.py
git commit -m "feat: seed Excel cobre 9 tipos de documento incluindo Dossie e Guia_Instalacao"
```

---

## Task 7 — Teste manual e verificação

- [ ] **7.1** Reiniciar serviço: `nssm restart DocTrack` (como Administrador)

- [ ] **7.2** Abrir um equipamento existente → verificar 9 abas no modal

- [ ] **7.3** Criar novo equipamento → verificar que os 9 documentos são criados no banco

- [ ] **7.4** Buscar pelo `nome_original` na barra de pesquisa → deve encontrar o equipamento

- [ ] **7.5** Confirmar que `nome_original` não aparece no card da tabela principal

- [ ] **7.6** Verificar pills de status: IT/Checklist usam pipeline PRE (4 etapas), demais usam pipeline Manuais (3 etapas)

---

## Decisões pendentes / pontos a confirmar com o usuário

1. **Checklist tem o mesmo pipeline de status do IT** (Elaborar → Treinamento Piloto → Enviado para Homologação → Homologado) ou um pipeline diferente?

2. **Dossiê e Guia de Instalação** — têm caminho de pasta padrão no servidor de arquivos, ou o campo `armazenamento` é preenchido manualmente caso a caso?

3. **Equipamentos existentes** — ao rodar a migração, Checklist, Dossiê e Guia de Instalação serão criados com status `Elaborar` para todos. Isso está correto, ou alguns já estão em andamento e devem ser verificados manualmente?

4. **nome_original** — deve ser editável individualmente por documento, ou quando editado em qualquer aba propaga automaticamente para todos os 9 docs do equipamento?
