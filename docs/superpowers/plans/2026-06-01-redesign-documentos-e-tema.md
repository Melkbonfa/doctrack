# Redesign da Aba Documentos + Tema Claro/Escuro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir a tabela da aba Documentos por uma grade de cards de equipamento (um card = um equipamento, reunindo IT/PRE + Manuais), com modal de abas totalmente editável; remover o setor PDE de todo o dashboard; e adicionar um toggle de tema claro/escuro persistente.

**Architecture:** Backend Flask/SQLAlchemy permanece a fonte de dados; a grade e o agrupamento por equipamento são montados no frontend a partir de `allDocs` (já carregado por `GET /api/data`). A remoção do PDE é feita nas constantes de domínio (`models.py`) — `compute_kpis` e os endpoints derivam de `SETORES` automaticamente. O tema é puramente CSS (variáveis sobrescritas em `body.theme-light`) + persistência em `localStorage`.

**Tech Stack:** Python 3 · Flask · SQLAlchemy · pytest (backend). JavaScript puro · Chart.js · HTML/CSS (frontend, sem runner de testes JS — verificação manual rodando o app).

---

## Realidade do toolset (leia antes de começar)

- **Backend é testável** com pytest (`tests/`). As tarefas de backend usam TDD real.
- **Frontend NÃO tem runner de testes JS.** As tarefas de frontend são verificadas rodando o servidor e observando o comportamento no navegador. Os "Expected" dessas tarefas descrevem o que você deve ver na tela, não saída de teste.
- **Rodar os testes** (PowerShell, a partir da raiz do projeto):
  ```powershell
  $env:JWT_SECRET="test-secret-key-for-pytest-32-chars-long"; python -m pytest -q
  ```
- **Rodar o app** (PowerShell): o `.env` já define `JWT_SECRET`. 
  ```powershell
  python servidor.py
  ```
  Depois abrir `http://localhost:5000`, logar com `admin@pde.com` / `admin123`.

## File Structure

| Arquivo | Responsabilidade após a mudança |
|---|---|
| `models.py` | Constantes de domínio sem PDE (`SETORES`, `STATUS_MAP`), `status_global` sem ramo PDE |
| `servidor.py` | Import sem `STATUS_PDE`; `compute_kpis` herda `SETORES` (sem mudança de corpo) |
| `tests/conftest.py` | Seed sem o documento PDE |
| `tests/test_kpis.py` | Expectativas sem chave `PDE` e sem o doc PDE |
| `tests/test_filters.py` | Remoção do teste de setor PDE |
| `static/style.css` | Bloco `body.theme-light` com overrides de variáveis; estilos de `.equip-grid`, `.equip-card`, `.filter-chip`, `.equip-modal-tabs` |
| `templates/dashboard.html` | Toggle de tema na topbar; página Docs reescrita (chips + grade, sem tabs/tabela); modal de equipamento com 2 abas |
| `static/app.js` | Toggle de tema; agrupamento por equipamento; render da grade; chips com contadores; modal de equipamento (abrir/salvar); remoção de PDE dos gráficos e do código de tabela antigo |

---

## Task 1: Remover PDE das constantes de domínio (backend, TDD)

**Files:**
- Modify: `tests/conftest.py:50-61`
- Modify: `tests/test_kpis.py:6-42`
- Modify: `tests/test_filters.py:53-59`
- Modify: `models.py:17-27`, `models.py:128-146`

- [ ] **Step 1: Atualizar o seed de testes — remover o documento PDE**

Em `tests/conftest.py`, substituir a lista `docs` (linhas 50-61) por (sem o terceiro Documento, que era PDE):

```python
        # Seed documentos
        docs = [
            Documento(setor="PRE", equipamento="MAQ-A", documento="POP-001", sku="SKU-A",
                      codigo_doc="COD-A", responsavel="Carlos Mota", status="Homologado",
                      armazenamento="P:/Qualidade/POP-001.pdf"),
            Documento(setor="Manuais", equipamento="MAQ-B", documento="Manual-002", sku="SKU-B",
                      codigo_doc="COD-B", status="Em andamento", tipo_doc="Manual_Usuario",
                      fabricante="Siemens", armazenamento="P:/Tecnico/Manual-002.pdf"),
        ]
```

- [ ] **Step 2: Atualizar `tests/test_kpis.py` para o novo domínio**

Substituir o corpo dos testes que mencionam PDE. Trocar as três asserções relevantes:

Em `test_compute_kpis_basico` (linha 16):
```python
    assert k["por_setor"] == {"PRE": 1, "Manuais": 1}
```

Em `test_compute_kpis_lista_vazia` (linha 28):
```python
    assert k["por_setor"] == {"PRE": 0, "Manuais": 0}
```

Em `test_metrics_endpoint` (linhas 39-42) — agora só há 2 documentos no seed:
```python
    assert m["total"] == 2
    assert m["finalizados"] == 1    # MAQ-A (PRE Homologado -> Finalizado)
    assert m["em_progresso"] == 1   # MAQ-B (Manuais Em andamento -> Em progresso)
    assert m["pendentes"] == 0
```

Em `test_data_endpoint_inclui_kpis` (linha 49):
```python
    assert data["kpis"]["total"] == 2
```

- [ ] **Step 3: Remover o teste de filtro por setor PDE**

Em `tests/test_filters.py`, apagar a função `test_filter_setor_pde` inteira (linhas 53-59).

- [ ] **Step 4: Rodar os testes e confirmar que FALHAM**

Run:
```powershell
$env:JWT_SECRET="test-secret-key-for-pytest-32-chars-long"; python -m pytest tests/test_kpis.py tests/test_filters.py -q
```
Expected: FALHA. `compute_kpis` ainda devolve a chave `"PDE"` em `por_setor` (vindo de `SETORES`), então as asserções de igualdade de dict quebram.

- [ ] **Step 5: Remover PDE das constantes em `models.py`**

Substituir as linhas 17-27 por:

```python
SETORES = ["PRE", "Manuais"]

STATUS_PRE = ["Elaborar", "Treinamento Piloto", "Enviado para Homologação", "Homologado"]
STATUS_FABRICANTE = ["Elaborar", "Em andamento", "Concluído"]

STATUS_MAP = {
    "PRE": STATUS_PRE,
    "Manuais": STATUS_FABRICANTE,
}
```

(Remove `STATUS_PDE` e a entrada `"PDE"` de `STATUS_MAP`.)

- [ ] **Step 6: Limpar o ramo PDE de `status_global`**

Em `models.py`, o método `status_global` (linhas 128-146) tem um ramo `if setor == "PRE": ... else: ...`. O `else` já cobre Manuais corretamente. Nenhuma mudança de lógica é necessária — mas confirme que não há string `"PDE"` no método. (Não há; o ramo `else` trata "Concluído"/"Em andamento".) Deixe como está.

- [ ] **Step 7: Rodar os testes e confirmar que PASSAM**

Run:
```powershell
$env:JWT_SECRET="test-secret-key-for-pytest-32-chars-long"; python -m pytest -q
```
Expected: PASS em toda a suíte. Se `test_workflow.py` ou `test_documentos.py` referenciarem PDE, corrija da mesma forma (não devem — só criam docs PRE/Manuais).

- [ ] **Step 8: Commit**

```bash
git add models.py tests/conftest.py tests/test_kpis.py tests/test_filters.py
git commit -m "feat: remove setor PDE do dominio e ajusta testes"
```

---

## Task 2: Corrigir import de `STATUS_PDE` em servidor.py

**Files:**
- Modify: `servidor.py:49-52`

- [ ] **Step 1: Remover `STATUS_PDE` do import**

Substituir o bloco de import (linhas 49-52) por:

```python
from models import (
    db, bcrypt, User, Documento, AuditLog, RevokedToken, Responsavel,
    SETORES, STATUS_PRE, STATUS_FABRICANTE, STATUS_MAP, TIPOS_DOC_FABRICANTE, TIPOS_DOC_LABELS
)
```

(Remove `STATUS_PDE` da lista — ele não existe mais em `models.py`, então o import quebraria.)

- [ ] **Step 2: Verificar que o servidor importa sem erro**

Run:
```powershell
$env:JWT_SECRET="test-secret-key-for-pytest-32-chars-long"; python -c "import servidor; print('OK')"
```
Expected: imprime `OK` sem `ImportError`.

- [ ] **Step 3: Rodar a suíte completa de novo**

Run:
```powershell
$env:JWT_SECRET="test-secret-key-for-pytest-32-chars-long"; python -m pytest -q
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add servidor.py
git commit -m "fix: remove import de STATUS_PDE em servidor"
```

---

## Task 3: Adicionar variáveis de tema claro no CSS

**Files:**
- Modify: `static/style.css` (após o bloco `:root { ... }`, que termina na linha ~72, antes de `*{box-sizing...}`)

- [ ] **Step 1: Adicionar o bloco `body.theme-light`**

Logo após o fechamento do `:root{...}` (a linha `}` antes de `*{box-sizing:border-box...}`), inserir:

```css
/* ── TEMA CLARO ─────────────────────────────────────────────────────────── */
body.theme-light{
  --bg-void:#eef1f8;
  --bg-base:#f4f6fb;
  --bg-surface:#ffffff;
  --bg-card:#ffffff;
  --bg-elevated:#f1f4fb;
  --bg-hover:#e7ecf7;

  --border-dim:rgba(30,41,99,.10);
  --border-soft:rgba(30,41,99,.16);
  --border-mid:rgba(30,41,99,.26);
  --border-hi:rgba(30,41,99,.40);

  --t1:#1a1f3a;
  --t2:#384063;
  --t3:#5b6488;
  --t4:#8189ad;

  --shadow-sm:0 2px 8px rgba(30,41,99,.08);
  --shadow-md:0 8px 24px rgba(30,41,99,.10);
  --shadow-lg:0 20px 60px rgba(30,41,99,.14);
}
/* No tema claro, suaviza o brilho de fundo radial herdado */
body.theme-light::before{opacity:.35;}
/* Transição suave ao trocar de tema */
body{transition:background-color .2s ease, color .2s ease;}
```

- [ ] **Step 2: Verificação manual**

Run:
```powershell
python servidor.py
```
Abra `http://localhost:5000`, abra o DevTools Console e rode:
```js
document.body.classList.add('theme-light')
```
Expected: o fundo fica claro e o texto escuro, sem quebra de layout. Rode `document.body.classList.remove('theme-light')` para voltar ao escuro. Pare o servidor (Ctrl+C).

- [ ] **Step 3: Commit**

```bash
git add static/style.css
git commit -m "feat: variaveis CSS para tema claro"
```

---

## Task 4: Toggle de tema (botão + persistência)

**Files:**
- Modify: `templates/dashboard.html:90-94` (topbar-actions)
- Modify: `static/app.js` (adicionar funções de tema e chamada na inicialização)

- [ ] **Step 1: Adicionar o botão de toggle na topbar**

Em `templates/dashboard.html`, dentro de `<div class="topbar-actions">` (linha 91-93), adicionar o botão ANTES do avatar:

```html
      <div class="topbar-actions">
        <button id="theme-toggle" class="btn btn-ghost btn-sm" type="button" onclick="toggleTheme()" aria-label="Alternar tema claro/escuro" title="Alternar tema" style="padding:6px 10px;font-size:14px;line-height:1">🌙</button>
        <div class="user-avatar" style="width:32px;height:32px;font-size:12px;cursor:pointer" id="top-avatar" onclick="navigate('settings')">A</div>
      </div>
```

- [ ] **Step 2: Adicionar as funções de tema em `app.js`**

No início de `static/app.js`, logo após a linha `let _currentSetor = 'PRE';` (linha 5), inserir:

```javascript
// ═══ TEMA CLARO/ESCURO ═══
function applyTheme(theme){
  const isLight = theme === 'light';
  document.body.classList.toggle('theme-light', isLight);
  const btn = document.getElementById('theme-toggle');
  if(btn) btn.textContent = isLight ? '☀️' : '🌙';
}
function toggleTheme(){
  const next = document.body.classList.contains('theme-light') ? 'dark' : 'light';
  localStorage.setItem('doctrack_theme', next);
  applyTheme(next);
}
function initTheme(){
  applyTheme(localStorage.getItem('doctrack_theme') || 'dark');
}
```

- [ ] **Step 3: Aplicar o tema no carregamento da página**

No fim de `static/app.js` (após a função `renderSkeletonTable`, última do arquivo, ~linha 869), adicionar:

```javascript
// Aplica o tema salvo assim que o script carrega (vale para tela de login também)
initTheme();
```

- [ ] **Step 4: Verificação manual**

Run `python servidor.py`, abra `http://localhost:5000`, logue. Clique no botão 🌙 na topbar.
Expected: o tema alterna claro/escuro, o ícone troca entre 🌙 e ☀️, e ao recarregar a página (F5) a preferência é mantida. Pare o servidor.

- [ ] **Step 5: Commit**

```bash
git add templates/dashboard.html static/app.js
git commit -m "feat: toggle de tema claro/escuro persistente"
```

---

## Task 5: Estilos da grade, cards e chips

**Files:**
- Modify: `static/style.css` (adicionar ao final do arquivo)

- [ ] **Step 1: Adicionar estilos da grade ao final de `static/style.css`**

```css
/* ── GRADE DE EQUIPAMENTOS ──────────────────────────────────────────────── */
.equip-toolbar{display:flex;flex-direction:column;gap:12px;margin-bottom:16px;}
.equip-chips{display:flex;gap:8px;flex-wrap:wrap;}
.filter-chip{
  padding:5px 12px;border-radius:var(--r-pill);font-size:11px;cursor:pointer;
  background:var(--bg-elevated);color:var(--t3);border:1px solid var(--border-soft);
  font-family:var(--font-body);transition:all .15s ease;white-space:nowrap;
}
.filter-chip:hover{border-color:var(--border-mid);color:var(--t2);}
.filter-chip.active{background:var(--cyan-brand);color:#fff;border-color:var(--cyan-brand);font-weight:600;}
.filter-chip .chip-count{font-family:var(--font-mono);opacity:.8;margin-left:4px;}

.equip-grid{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;
}
.equip-card{
  background:var(--bg-card);border:1px solid var(--border-soft);border-radius:var(--r2);
  border-top:3px solid var(--border-mid);padding:14px;cursor:pointer;
  transition:transform .12s ease, box-shadow .12s ease, border-color .12s ease;
}
.equip-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-md);border-color:var(--border-mid);}
.equip-card.st-green{border-top-color:var(--green);}
.equip-card.st-amber{border-top-color:var(--amber);}
.equip-card.st-red{border-top-color:var(--red);}
.equip-card-name{font-size:13px;font-weight:700;color:var(--t1);margin-bottom:2px;}
.equip-card-meta{font-size:10px;color:var(--t3);margin-bottom:10px;}
.equip-card-blocks{display:grid;grid-template-columns:1fr 1fr;gap:6px;}
.equip-block{background:var(--bg-elevated);border-radius:8px;padding:8px;text-align:center;}
.equip-block-label{font-size:9px;color:var(--t4);margin-bottom:3px;text-transform:uppercase;letter-spacing:.5px;}
.equip-block-val{font-size:11px;font-weight:700;}
.equip-block-val.muted{color:var(--t4);font-weight:400;}

/* ── MODAL DE EQUIPAMENTO (abas) ────────────────────────────────────────── */
.equip-modal-tabs{display:flex;border-bottom:1px solid var(--border-soft);margin:4px 0 16px;}
.equip-modal-tab{
  flex:1;text-align:center;padding:9px;font-size:12px;cursor:pointer;background:none;border:none;
  color:var(--t3);border-bottom:2px solid transparent;font-family:var(--font-body);
}
.equip-modal-tab.active{color:var(--t1);border-bottom-color:var(--cyan-brand);font-weight:600;}
.equip-tab-panel{display:none;}
.equip-tab-panel.active{display:block;}
.manual-row{background:var(--bg-elevated);border-radius:8px;padding:10px 12px;margin-bottom:8px;}
.manual-row-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}
.manual-row-name{font-size:12px;font-weight:600;color:var(--t1);}
.section-label-line{font-size:10px;color:var(--cyan-lt);letter-spacing:1px;margin:6px 0 10px;text-transform:uppercase;}
```

- [ ] **Step 2: Verificação manual (visual)**

Os estilos só aparecem quando a grade for renderizada (Task 6). Por agora, apenas confirme que o CSS é válido: rode `python servidor.py`, abra a página, abra o DevTools → aba Console.
Expected: nenhum erro de parsing de CSS; a página carrega normalmente. Pare o servidor.

- [ ] **Step 3: Commit**

```bash
git add static/style.css
git commit -m "feat: estilos da grade de equipamentos, chips e modal de abas"
```

---

## Task 6: Reescrever o HTML da página Docs (chips + grade) e do modal

**Files:**
- Modify: `templates/dashboard.html:119-158` (página Docs)
- Modify: `templates/dashboard.html:256-295` (modal de documento → modal de equipamento)

- [ ] **Step 1: Substituir a página Docs**

Trocar todo o bloco `<!-- DOCS PAGE -->` (linhas 119-158) por:

```html
      <!-- DOCS PAGE -->
      <div class="page" id="page-docs">
        <div class="page-header">
          <div><div class="page-title">Documentos</div><div class="page-sub">Visão por equipamento — IT/PRE e Manuais</div></div>
          <div class="page-actions" style="display:flex; gap:10px; align-items:center;">
            <span class="filter-count" id="docs-badge">—</span>
            <button class="btn btn-primary btn-sm" id="btn-add-equip" onclick="openNewEquip()">+ Novo equipamento</button>
          </div>
        </div>

        <div class="card">
          <div class="equip-toolbar">
            <div class="filter-bar" style="margin:0">
              <div class="search-wrap">
                <svg width="14" height="14" fill="none" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/><path d="M21 21l-4.35-4.35" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
                <input class="search-input" id="docs-search" placeholder="Buscar equipamento, SKU, fabricante..." aria-label="Buscar equipamentos">
              </div>
            </div>
            <div class="equip-chips" id="equip-chips"></div>
          </div>
          <div class="equip-grid" id="equip-grid"></div>
        </div>
      </div>
```

- [ ] **Step 2: Substituir o modal de documento pelo modal de equipamento**

Trocar todo o bloco `<!-- MODALS DE DOCUMENTO UNIFICADOS ... -->` e seu modal `#modal-doc` (linhas 256-295) por:

```html
<!-- MODAL DE EQUIPAMENTO (abas IT/PRE e Manuais) -->
<div class="modal-overlay" id="modal-equip" role="dialog" aria-modal="true" aria-labelledby="equip-modal-title" aria-hidden="true">
  <div class="modal" style="width:720px" tabindex="-1">
    <div class="modal-title" id="equip-modal-title">Equipamento</div>
    <div class="modal-sub" id="equip-modal-sub"></div>

    <div class="equip-modal-tabs" role="tablist">
      <button type="button" class="equip-modal-tab active" data-tab="pre" onclick="switchEquipTab('pre')">IT / PRE</button>
      <button type="button" class="equip-modal-tab" data-tab="manuais" onclick="switchEquipTab('manuais')">Manuais</button>
    </div>

    <!-- PAINEL IT/PRE -->
    <div class="equip-tab-panel active" id="equip-panel-pre"></div>

    <!-- PAINEL MANUAIS -->
    <div class="equip-tab-panel" id="equip-panel-manuais"></div>

    <div class="modal-footer"><button class="btn btn-ghost" onclick="closeModal('equip')">Fechar</button></div>
  </div>
</div>
```

(Os conteúdos dos painéis são injetados por JS na Task 8, porque dependem dos dados do equipamento aberto.)

- [ ] **Step 3: Verificação manual**

Rode `python servidor.py`, logue, vá em "Todos os Docs".
Expected: a página mostra a barra de busca, uma área de chips vazia e uma grade vazia (ainda sem JS de render — Task 7). Não deve haver erro de layout. As abas antigas (PRE/Manuais/PDE) e a tabela sumiram. Pare o servidor.

- [ ] **Step 4: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat: HTML da pagina Docs com grade+chips e modal de equipamento"
```

---

## Task 7: Agrupamento, render da grade e chips (JS)

**Files:**
- Modify: `static/app.js` — substituir a seção `// ═══ DOCS TABLE ═══` (funções `renderDocs`, `populateFilters`, `filterDocs`, linhas 374-495) por novas funções de grade.

- [ ] **Step 1: Substituir o bloco de tabela por funções de grade**

Em `static/app.js`, localizar o comentário `// ═══ DOCS TABLE ═══` (linha 374) e substituir tudo desde essa linha até o fim da função `filterDocs` (linha 495, o `}` que fecha `filterDocs`) por:

```javascript
// ═══ DOCS — GRADE DE EQUIPAMENTOS ═══
let _equipChip = 'todos';

// Agrupa allDocs por nome de equipamento (PRE + Manuais juntos)
function groupByEquip(){
  const groups = {};
  allDocs.forEach(d => {
    const key = (d.equipamento || '—').trim();
    if(!groups[key]){
      groups[key] = { equipamento: key, sku:'', fabricante:'', pre:null, manuais:[] };
    }
    const g = groups[key];
    if(d.sku && !g.sku) g.sku = d.sku;
    if(d.fabricante && !g.fabricante) g.fabricante = d.fabricante;
    if(d.setor === 'PRE'){ if(!g.pre) g.pre = d; }
    else if(d.setor === 'Manuais'){ g.manuais.push(d); }
  });
  return Object.values(groups).sort((a,b)=>a.equipamento.localeCompare(b.equipamento));
}

function equipManuaisOk(g){ return g.manuais.filter(d=>d.status==='Concluído').length; }

function equipStatusColor(g){
  const ok = equipManuaisOk(g), cnt = g.manuais.length;
  const preElaborar = g.pre && g.pre.status === 'Elaborar';
  const preHomolog  = g.pre && g.pre.status === 'Homologado';
  if(preElaborar || (cnt>0 && ok===0)) return 'red';
  if(preHomolog && cnt>0 && ok===cnt) return 'green';
  return 'amber';
}

function equipMatchesChip(g, chip){
  const ok = equipManuaisOk(g), cnt = g.manuais.length;
  const anyElaborar = (g.pre && g.pre.status==='Elaborar') || g.manuais.some(d=>d.status==='Elaborar');
  const anyProgresso = (g.pre && ['Treinamento Piloto','Enviado para Homologação'].includes(g.pre.status)) || g.manuais.some(d=>d.status==='Em andamento');
  const finalizado = (g.pre && g.pre.status==='Homologado') && cnt>0 && ok===cnt;
  switch(chip){
    case 'todos': return true;
    case 'pendente': return anyElaborar;
    case 'progresso': return anyProgresso && !anyElaborar;
    case 'finalizado': return finalizado;
    case 'pre-pendente': return g.pre && g.pre.status==='Elaborar';
    case 'manuais-incompletos': return ok < (cnt || 5);
    default: return true;
  }
}

function renderChips(groups){
  const chips = [
    {id:'todos', label:'Todos'},
    {id:'pendente', label:'Pendente'},
    {id:'progresso', label:'Em progresso'},
    {id:'finalizado', label:'Finalizado'},
    {id:'pre-pendente', label:'IT/PRE pendente'},
    {id:'manuais-incompletos', label:'Manuais incompletos'},
  ];
  document.getElementById('equip-chips').innerHTML = chips.map(c => {
    const n = groups.filter(g => equipMatchesChip(g, c.id)).length;
    const active = _equipChip === c.id ? ' active' : '';
    return `<button type="button" class="filter-chip${active}" data-chip="${c.id}">${esc(c.label)}<span class="chip-count">${n}</span></button>`;
  }).join('');
}

function renderDocs(){ renderGrid(); }

function renderGrid(){
  const groups = groupByEquip();
  renderChips(groups);

  const q = (document.getElementById('docs-search').value || '').trim().toLowerCase();
  let filtered = groups.filter(g => equipMatchesChip(g, _equipChip));
  if(q){
    filtered = filtered.filter(g =>
      [g.equipamento, g.sku, g.fabricante].join(' ').toLowerCase().includes(q)
    );
  }

  document.getElementById('docs-badge').textContent = filtered.length + ' equip.';

  const grid = document.getElementById('equip-grid');
  if(!filtered.length){
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:var(--t4);padding:32px">Nenhum equipamento encontrado</div>';
    return;
  }
  grid.innerHTML = filtered.map(g => {
    const color = equipStatusColor(g);
    const preTxt = g.pre ? esc(g.pre.status) : '—';
    const preMuted = g.pre ? '' : ' muted';
    const ok = equipManuaisOk(g);
    const manTxt = g.manuais.length ? `${ok} / 5` : '—';
    const manMuted = g.manuais.length ? '' : ' muted';
    const preColor = color==='red' ? 'var(--red)' : color==='green' ? 'var(--green)' : 'var(--amber)';
    return `<div class="equip-card st-${color}" data-equip="${esc(g.equipamento)}" onclick="openEquipModal('${esc(g.equipamento).replace(/'/g,"\\'")}')">
      <div class="equip-card-name">${esc(g.equipamento)}</div>
      <div class="equip-card-meta">${esc(g.sku||'—')}${g.fabricante?' · '+esc(g.fabricante):''}</div>
      <div class="equip-card-blocks">
        <div class="equip-block"><div class="equip-block-label">IT / PRE</div><div class="equip-block-val${preMuted}" style="${g.pre?`color:${preColor}`:''}">${preTxt}</div></div>
        <div class="equip-block"><div class="equip-block-label">Manuais</div><div class="equip-block-val${manMuted}">${manTxt}</div></div>
      </div>
    </div>`;
  }).join('');
}
```

- [ ] **Step 2: Ligar o clique nos chips e a busca**

Em `static/app.js`, no listener `document.body.addEventListener('click', ...)` (linha 58-69), adicionar um tratamento para chips no início do handler, logo após `const btn=e.target.closest('[data-action]');` deve haver outro closest. Substituir o handler inteiro (linhas 58-69) por:

```javascript
document.body.addEventListener('click',(e)=>{
  const chip=e.target.closest('.filter-chip');
  if(chip){ _equipChip = chip.dataset.chip; renderGrid(); return; }
  const btn=e.target.closest('[data-action]');
  if(!btn)return;
  const action=btn.dataset.action;
  const id=btn.dataset.id;
  switch(action){
    case 'edit-user': openEditUser(parseInt(id)); break;
    case 'delete-user': confirmDeleteUser(parseInt(id), btn.dataset.name||''); break;
  }
});
```

(Removidos `edit-doc` e `delete-doc` — não há mais botões de tabela.)

- [ ] **Step 3: Apontar a busca de docs para `renderGrid`**

Em `static/app.js`, no listener `input` (linhas 83-90), trocar `const fn=e.target.id==='docs-search'?filterDocs:filterAudit;` por:

```javascript
    const fn=e.target.id==='docs-search'?renderGrid:filterAudit;
```

- [ ] **Step 4: Remover o setup de tabs e chamadas a `populateFilters` da inicialização**

Em `initApp` (linhas 92-115), remover o bloco `// Setup tabs` (linhas 99-108) inteiro. O `initApp` deve ficar (trecho relevante):

```javascript
async function initApp(){
  updateUserUI();
  renderSkeletonTable('dash-table',5,5);
  await loadEnums();
  await loadData();

  renderDashboard();renderDocs();renderAudit();renderUsers();
  makeSortable();
  showToast('Bem-vindo ao DocTrack v4.0','success');
  document.getElementById('sync-label').textContent='Conectado · '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
  const ls=document.getElementById('last-sync');if(ls)ls.textContent=new Date().toLocaleString('pt-BR',{hour:'2-digit',minute:'2-digit',day:'2-digit',month:'2-digit'});
}
```

(Removida a linha `renderSkeletonTable('docs-tbody',6,8);` — esse elemento não existe mais.)

- [ ] **Step 5: Verificação manual**

Rode `python servidor.py`, logue, vá em "Todos os Docs".
Expected: a grade mostra um card por equipamento, com borda colorida (verde/amarelo/vermelho), bloco IT/PRE com o status e bloco Manuais com `X / 5`. Os chips aparecem com contadores; clicar em um chip filtra a grade. A busca filtra por nome/SKU/fabricante. Pare o servidor.

- [ ] **Step 6: Commit**

```bash
git add static/app.js
git commit -m "feat: grade de equipamentos com agrupamento, chips e busca"
```

---

## Task 8: Abrir o modal de equipamento populado (JS)

**Files:**
- Modify: `static/app.js` — substituir as funções de modal de doc antigas (`configureDocModal`, `openModal`, `openEditDoc`, linhas 562-640) por funções do modal de equipamento.

- [ ] **Step 1: Substituir as funções do modal antigo**

Localizar `function configureDocModal(setor)` (linha 562) e substituir desde essa linha até o fim de `openEditDoc` (linha 640, o `}` que fecha `openEditDoc`) por o código abaixo.

> ⚠️ Esse intervalo inclui a antiga função `openModal`, que ainda é usada pelo botão "+ Novo Usuário" (`onclick="openModal('add-user')"` em `dashboard.html`). Por isso o bloco abaixo já inclui um `openModal` enxuto que apenas delega para `openBaseModal`.

```javascript
// ═══ MODAL DE EQUIPAMENTO ═══
let _equipCtx = null; // { equipamento, pre, manuais: {tipo: doc} }

// Wrapper mantido para o modal de usuário (e quaisquer outros modais simples)
function openModal(id){ openBaseModal(id); }

const _PRE_STATUS = ['Elaborar','Treinamento Piloto','Enviado para Homologação','Homologado'];
const _MAN_STATUS = ['Elaborar','Em andamento','Concluído'];
const _MAN_TIPOS = [
  ['Manual_ES','Manual ES'],
  ['Manual_Usuario','Manual do Usuário'],
  ['QIQOQD','QI/QO/QD'],
  ['Manual_Servico','Manual de Serviço'],
  ['Spare_Parts','Spare Parts'],
];

function _dateToInput(br){ // "dd/mm/yyyy" -> "yyyy-mm-dd"
  if(!br) return '';
  const p = br.split('/');
  return p.length===3 ? `${p[2]}-${p[1]}-${p[0]}` : '';
}

function switchEquipTab(tab){
  document.querySelectorAll('.equip-modal-tab').forEach(b=>b.classList.toggle('active', b.dataset.tab===tab));
  document.getElementById('equip-panel-pre').classList.toggle('active', tab==='pre');
  document.getElementById('equip-panel-manuais').classList.toggle('active', tab==='manuais');
}

function openEquipModal(equipName){
  const docs = allDocs.filter(d => (d.equipamento||'').trim() === equipName);
  const pre = docs.find(d => d.setor==='PRE') || null;
  const manuais = {};
  docs.filter(d=>d.setor==='Manuais').forEach(d=>{ manuais[d.tipo_doc] = d; });
  const fabricante = (docs.find(d=>d.fabricante)||{}).fabricante || '';
  const sku = (docs.find(d=>d.sku)||{}).sku || '';
  _equipCtx = { equipamento: equipName, pre, manuais, fabricante, sku };

  document.getElementById('equip-modal-title').textContent = equipName;
  document.getElementById('equip-modal-sub').textContent = (sku?('SKU '+sku):'') + (fabricante?(' · '+fabricante):'');

  renderEquipPrePanel();
  renderEquipManuaisPanel();
  switchEquipTab('pre');
  openBaseModal('equip');
}

function renderEquipPrePanel(){
  const p = _equipCtx.pre;
  const panel = document.getElementById('equip-panel-pre');
  if(!p){
    panel.innerHTML = `<div style="text-align:center;padding:24px;color:var(--t3)">
      <p style="margin-bottom:12px">Este equipamento ainda não tem documento IT/PRE.</p>
      <button class="btn btn-primary btn-sm" onclick="createPreDoc()">Criar documento IT/PRE</button>
    </div>`;
    return;
  }
  const statusOpts = _PRE_STATUS.map(s=>`<option value="${esc(s)}" ${p.status===s?'selected':''}>${esc(s)}</option>`).join('');
  panel.innerHTML = `
    <div class="g2">
      <div class="form-group"><label class="form-label">Equipamento</label><input class="form-input" id="ep-equipamento" value="${esc(p.equipamento)}"></div>
      <div class="form-group"><label class="form-label">SKU</label><input class="form-input" id="ep-sku" value="${esc(p.sku)}"></div>
    </div>
    <div class="g2">
      <div class="form-group"><label class="form-label">Código do Doc</label><input class="form-input" id="ep-codigo" value="${esc(p.codigo_doc)}"></div>
      <div class="form-group"><label class="form-label">Responsável</label><input class="form-input" id="ep-responsavel" value="${esc(p.responsavel)}"></div>
    </div>
    <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="ep-status">${statusOpts}</select></div>
    <div class="g2">
      <div class="form-group"><label class="form-label">Data Treinamento Piloto</label><input class="form-input" type="date" id="ep-data_treinamento" value="${_dateToInput(p.data_treinamento)}"></div>
      <div class="form-group"><label class="form-label">Data Envio Homologação</label><input class="form-input" type="date" id="ep-data_homologacao" value="${_dateToInput(p.data_homologacao)}"></div>
    </div>
    <div class="g2">
      <div class="form-group"><label class="form-label">Obs. Treinamento</label><input class="form-input" id="ep-obs_treinamento" value="${esc(p.obs_treinamento)}"></div>
      <div class="form-group"><label class="form-label">Obs. Homologação</label><input class="form-input" id="ep-obs_homologacao" value="${esc(p.obs_homologacao)}"></div>
    </div>
    <div class="form-group"><label class="form-label">Armazenamento (Caminho na Rede)</label><input class="form-input" id="ep-armazenamento" value="${esc(p.armazenamento)}"></div>
    <div class="modal-footer" style="margin-top:8px"><button class="btn btn-primary" onclick="saveEquipPre()">Salvar alterações</button></div>
  `;
}

function renderEquipManuaisPanel(){
  const panel = document.getElementById('equip-panel-manuais');
  const hasManuais = Object.keys(_equipCtx.manuais).length > 0;
  if(!hasManuais){
    panel.innerHTML = `<div style="text-align:center;padding:24px;color:var(--t3)">
      <p style="margin-bottom:12px">Este equipamento ainda não tem documentos de Manuais.</p>
      <button class="btn btn-primary btn-sm" onclick="createManuais()">Criar manuais para este equipamento</button>
    </div>`;
    return;
  }
  const rows = _MAN_TIPOS.map(([tipo, label]) => {
    const d = _equipCtx.manuais[tipo];
    if(!d) return '';
    const statusOpts = _MAN_STATUS.map(s=>`<option value="${esc(s)}" ${d.status===s?'selected':''}>${esc(s)}</option>`).join('');
    return `<div class="manual-row">
      <div class="manual-row-head"><span class="manual-row-name">${esc(label)}</span></div>
      <div class="g2">
        <div class="form-group"><label class="form-label">Código</label><input class="form-input" id="em-cod-${tipo}" value="${esc(d.codigo_doc)}"></div>
        <div class="form-group"><label class="form-label">Status</label><select class="form-input" id="em-st-${tipo}">${statusOpts}</select></div>
      </div>
    </div>`;
  }).join('');
  panel.innerHTML = `
    <div class="section-label-line">Dados do fabricante (compartilhados)</div>
    <div class="g2">
      <div class="form-group"><label class="form-label">Fabricante</label><input class="form-input" id="em-fabricante" value="${esc(_equipCtx.fabricante)}"></div>
      <div class="form-group"><label class="form-label">Armazenamento base</label><input class="form-input" id="em-armazenamento" value="${esc((Object.values(_equipCtx.manuais)[0]||{}).armazenamento||'')}"></div>
    </div>
    <div class="section-label-line">Documentos por tipo</div>
    ${rows}
    <div class="modal-footer" style="margin-top:8px"><button class="btn btn-primary" onclick="saveEquipManuais()">Salvar alterações</button></div>
  `;
}
```

- [ ] **Step 2: Verificação manual**

Rode `python servidor.py`, logue, vá em "Todos os Docs", clique num card.
Expected: o modal abre com o nome do equipamento no topo, abas "IT / PRE" e "Manuais". A aba IT/PRE mostra os campos preenchidos (status, datas, obs, armazenamento). A aba Manuais lista os 5 tipos com código e status. Trocar de aba funciona. (Os botões "Salvar" ainda não fazem nada — Task 9.) Pare o servidor.

- [ ] **Step 3: Commit**

```bash
git add static/app.js
git commit -m "feat: abrir modal de equipamento com abas IT/PRE e Manuais populadas"
```

---

## Task 9: Salvar IT/PRE e Manuais; criar docs faltantes (JS)

**Files:**
- Modify: `static/app.js` — substituir a função `saveDoc` antiga (linhas 642-681) por novas funções de salvamento.

- [ ] **Step 1: Substituir `saveDoc` pelas novas funções de salvamento**

Localizar `async function saveDoc()` (linha 642) e substituir a função inteira (até seu `}` na linha 681) por:

```javascript
async function _patchDoc(id, payload){
  const res = await apiFetch(`/documentos/${id}`, {method:'PATCH', body:JSON.stringify(payload)});
  return res;
}

async function saveEquipPre(){
  const p = _equipCtx.pre;
  if(!p) return;
  const payload = {
    equipamento: document.getElementById('ep-equipamento').value,
    sku: document.getElementById('ep-sku').value,
    codigo_doc: document.getElementById('ep-codigo').value,
    responsavel: document.getElementById('ep-responsavel').value,
    status: document.getElementById('ep-status').value,
    data_treinamento: document.getElementById('ep-data_treinamento').value,
    data_homologacao: document.getElementById('ep-data_homologacao').value,
    obs_treinamento: document.getElementById('ep-obs_treinamento').value,
    obs_homologacao: document.getElementById('ep-obs_homologacao').value,
    armazenamento: document.getElementById('ep-armazenamento').value,
  };
  try{
    const res = await _patchDoc(p.id, payload);
    if(res && res.ok){ showToast('IT/PRE salvo','success'); closeModal('equip'); await refreshAll(); }
    else { const e = await res.json().catch(()=>({})); showToast(e.erro||'Erro ao salvar','error'); }
  }catch(e){ showToast('Erro de rede','error'); }
}

async function saveEquipManuais(){
  const fabricante = document.getElementById('em-fabricante').value;
  const armazenamento = document.getElementById('em-armazenamento').value;
  const tipos = Object.keys(_equipCtx.manuais);
  try{
    for(const tipo of tipos){
      const d = _equipCtx.manuais[tipo];
      const payload = {
        fabricante,
        armazenamento,
        codigo_doc: document.getElementById('em-cod-'+tipo).value,
        status: document.getElementById('em-st-'+tipo).value,
      };
      const res = await _patchDoc(d.id, payload);
      if(!res || !res.ok){ const e = res ? await res.json().catch(()=>({})) : {}; showToast(e.erro||'Erro ao salvar manuais','error'); return; }
    }
    showToast('Manuais salvos','success'); closeModal('equip'); await refreshAll();
  }catch(e){ showToast('Erro de rede','error'); }
}

// Cria o documento IT/PRE para o equipamento aberto
async function createPreDoc(){
  const payload = { setor:'PRE', equipamento:_equipCtx.equipamento, documento:`IT/Checklist - ${_equipCtx.equipamento}`, sku:_equipCtx.sku };
  try{
    const res = await apiFetch('/documentos', {method:'POST', body:JSON.stringify(payload)});
    if(res && res.ok){ showToast('IT/PRE criado','success'); closeModal('equip'); await refreshAll(); }
    else { showToast('Erro ao criar IT/PRE','error'); }
  }catch(e){ showToast('Erro de rede','error'); }
}

// Cria os 5 manuais para o equipamento aberto (backend gera os 5 a partir de um POST Manuais)
async function createManuais(){
  const payload = { setor:'Manuais', equipamento:_equipCtx.equipamento, documento:`Manual ES - ${_equipCtx.equipamento}`, tipo_doc:'Manual_ES', sku:_equipCtx.sku, fabricante:_equipCtx.fabricante };
  try{
    const res = await apiFetch('/documentos', {method:'POST', body:JSON.stringify(payload)});
    if(res && res.ok){ showToast('Manuais criados','success'); closeModal('equip'); await refreshAll(); }
    else { showToast('Erro ao criar manuais','error'); }
  }catch(e){ showToast('Erro de rede','error'); }
}

function openNewEquip(){
  // Novo equipamento = criar primeiro o IT/PRE com nome digitado
  const nome = prompt('Nome do novo equipamento:');
  if(!nome || !nome.trim()) return;
  apiFetch('/documentos', {method:'POST', body:JSON.stringify({setor:'PRE', equipamento:nome.trim(), documento:`IT/Checklist - ${nome.trim()}`})})
    .then(async res => {
      if(res && res.ok){ showToast('Equipamento criado','success'); await refreshAll(); }
      else { showToast('Erro ao criar equipamento','error'); }
    })
    .catch(()=>showToast('Erro de rede','error'));
}
```

- [ ] **Step 2: Verificação manual — editar**

Rode `python servidor.py`, logue como admin, vá em "Todos os Docs", clique num card existente.
Expected: na aba IT/PRE, mude o Status e clique "Salvar alterações" → toast de sucesso, modal fecha, o card reflete o novo status/cor. Na aba Manuais, mude um status para "Concluído" e salve → o bloco Manuais do card atualiza o `X / 5`. Pare o servidor.

- [ ] **Step 3: Verificação manual — criar**

Com o servidor rodando, clique "+ Novo equipamento", digite um nome, confirme.
Expected: aparece um novo card. Ao abrir esse card, a aba Manuais oferece "Criar manuais para este equipamento"; ao clicar, os 5 manuais passam a existir (bloco vira `0 / 5`). Pare o servidor.

- [ ] **Step 4: Commit**

```bash
git add static/app.js
git commit -m "feat: salvar IT/PRE e Manuais e criar docs faltantes pelo modal"
```

---

## Task 10: Remover PDE e referências de tabela do dashboard/JS

**Files:**
- Modify: `static/app.js` — `CAT_COLORS` (linha 7), `updateUserUI` visibility (linhas 128-132), funções órfãs.
- Modify: `templates/dashboard.html` — botões de add antigos já removidos na Task 6; conferir.

- [ ] **Step 1: Remover PDE do mapa de cores e a variável `_currentSetor`**

Em `static/app.js` linha 7, trocar:
```javascript
const CAT_COLORS={'PRE':'#22d3ee','Manuais':'#06b6d4'};
```
(Remove a entrada `'PDE':'#ec4899'`.)

E remover a declaração órfã da linha 5 (`let _currentSetor = 'PRE';`) — não é mais usada por nada (a grade não tem setor ativo).

- [ ] **Step 2: Corrigir `updateUserUI` — remover referências a botões inexistentes**

Em `static/app.js`, o bloco de visibilidade (linhas 128-132) referencia `btn-add-doc-pre/fab/pde`, que não existem mais. Substituir o bloco `if(rl==='leitura'){...}` por:

```javascript
  if(rl==='leitura') {
    const b = document.getElementById('btn-add-equip');
    if(b) b.style.display='none';
  }
```

- [ ] **Step 3: Remover funções órfãs de status inline e delete de doc**

As funções `renderStatusSelect`, `getStatusClass`, `changeStatus`, `delDoc` (linhas 497-560) eram usadas só pela tabela antiga. A grade não as usa. Remover essas 4 funções inteiras (da linha 497 até o `}` final de `delDoc` na linha 560).

Também remover o handler de `change` para `select.etapa-select` no listener de `change` (linhas 72-77): substituir o listener `document.body.addEventListener('change', ...)` (linhas 71-81) por:

```javascript
document.body.addEventListener('change',(e)=>{
  if(e.target&&e.target.id==='audit-filter-action'){filterAudit();return}
});
```

(Removidos o tratamento de `etapa-select` e o filtro `docs-filter-status`, que não existem mais.)

- [ ] **Step 4: Verificação manual — dashboard sem PDE**

Rode `python servidor.py`, logue. Veja o Dashboard.
Expected: o gráfico "Distribuição por Categoria" mostra só PRE e Manuais (sem fatia PDE). Nenhum erro no Console do navegador. A aba "Todos os Docs" continua funcionando (grade, chips, modal). Pare o servidor.

- [ ] **Step 5: Verificação — sem referências quebradas**

Run:
```powershell
Select-String -Path static/app.js -Pattern "etapa-select|docs-filter-status|btn-add-doc|filterDocs|populateFilters|configureDocModal|openEditDoc|_currentSetor|docs-thead|docs-tbody"
```
Expected: nenhum resultado (todas as referências à tabela antiga foram removidas). Se aparecer alguma, remova-a.

- [ ] **Step 6: Commit**

```bash
git add static/app.js
git commit -m "chore: remove PDE dos graficos e codigo orfao da tabela antiga"
```

---

## Task 11: Verificação end-to-end

**Files:** nenhum (apenas validação).

- [ ] **Step 1: Suíte de testes backend**

Run:
```powershell
$env:JWT_SECRET="test-secret-key-for-pytest-32-chars-long"; python -m pytest -q
```
Expected: PASS em tudo.

- [ ] **Step 2: Fluxo completo no navegador**

Rode `python servidor.py`, logue como `admin@pde.com`/`admin123`. Verifique, em sequência:

1. **Tema:** clicar 🌙/☀️ alterna e persiste após F5.
2. **Dashboard:** gráficos só com PRE e Manuais.
3. **Grade:** um card por equipamento, borda colorida correta, blocos IT/PRE e Manuais.
4. **Chips:** contadores corretos; clicar filtra; "Manuais incompletos" mostra só quem tem < 5 concluídos.
5. **Busca:** filtra por nome/SKU/fabricante.
6. **Modal — editar IT/PRE:** muda status, salva, card atualiza.
7. **Modal — editar Manuais:** muda status de um tipo para "Concluído", salva, `X / 5` atualiza.
8. **Novo equipamento:** cria, aparece na grade, consegue criar manuais.
9. **Perfil leitura:** logar como `auditora@iso.com`/`demo123` → botão "+ Novo equipamento" some; cards abrem mas (opcional) o backend recusa PATCH com 403 — toast de erro é esperado.

Expected: todos os passos funcionam sem erro no Console.

- [ ] **Step 3: Commit final (se houver ajustes)**

```bash
git add -A
git commit -m "test: verificacao end-to-end do redesign de Documentos e tema"
```

---

## Notas de decisão

- **Agrupamento por nome de equipamento** (não por `equipamento+sku`): garante "um card por equipamento" de forma robusta, mesmo se PRE e Manuais tiverem SKU dessincronizado. O SKU exibido vem de qualquer doc do grupo que tenha valor. (A spec citava chave composta; esta é uma simplificação mais segura e equivalente na prática, já que o backend propaga SKU entre docs do mesmo equipamento.)
- **Salvamento por aba:** a aba IT/PRE faz 1 PATCH no doc PRE; a aba Manuais faz 1 PATCH por tipo (até 5), incluindo `fabricante`/`armazenamento` — o backend já sincroniza esses campos entre os 5 docs do grupo (`update_documento`, ramo `setor=="Manuais"`).
- **Sem exclusão:** conforme decidido, o modal só edita; não há botão de excluir equipamento/documento.
- **PDE nos dados:** documentos PDE pré-existentes continuam no banco mas, como `SETORES` não os inclui, não entram em `compute_kpis` nem aparecem na grade (que monta cards de PRE/Manuais). A reimportação do Excel ainda cria docs PDE; eles ficam invisíveis. Limpeza física do PDE no banco/Excel está fora do escopo.
