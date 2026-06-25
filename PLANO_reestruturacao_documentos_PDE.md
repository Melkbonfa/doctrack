# Reestruturação de Documentos — DocTrack PDE (v2)

> **Para workers agênticos:** use `superpowers:executing-plans` para implementar task a task com checkpoints.

**Goal:** (1) Criar a entidade **Equipamento** como fonte única dos dados de identidade (nome, nome original, SKU, ANVISA + registro/validade, fabricante, família). (2) Substituir a divisão PRE/Manuais por **9 tipos de documento** individuais, com abas dedicadas no modal. (3) Tornar `nome_original` (e demais campos do equipamento) pesquisáveis sem poluir o card.

**Arquitetura-alvo:**
- Nova tabela `equipamentos` (1 linha por equipamento). `documentos` ganha `equipamento_id` (FK) e mantém a string `equipamento` para compatibilidade durante a transição.
- Mantém-se o `setor` (`PRE`/`Manuais`) como agrupador de pipeline de status, mas **todo** documento passa a ter `tipo_doc`. Cada equipamento tem 9 documentos (um por tipo).
- IT e Checklist usam o pipeline PRE (4 etapas). Os 7 de fabricante usam o pipeline Manuais (3 etapas).
- Status do card/grid = **pior status** entre os documentos do equipamento.

**Tech Stack:** Python/Flask · SQLAlchemy · PostgreSQL (Render) + SQLite (local) · Vanilla JS (`app.js`).

> **Migração: NÃO usar arquivos `.sql` manuais.** O projeto migra schema sozinho a cada boot via `_sync_schema()` (`servidor.py:1068`) e via o bloco de auto-migração do startup (`servidor.py:1201-1259`). Como o app roda no Render, um `psql` local nunca tocaria a produção. Toda mudança de schema/backfill entra nesses dois mecanismos.

---

## Estado alvo dos tipos

| Aba | tipo_doc | setor | Pipeline |
|---|---|---|---|
| Instrução de Trabalho | `IT` | PRE | Elaborar → Treinamento Piloto → Enviado para Homologação → Homologado |
| Checklist | `Checklist` | PRE | Elaborar → Treinamento Piloto → Enviado para Homologação → Homologado |
| Manual do Usuário PT | `Manual_Usuario` | Manuais | Elaborar → Em andamento → Concluído |
| Manual do Usuário ES | `Manual_ES` | Manuais | idem |
| Manual de Serviço | `Manual_Servico` | Manuais | idem |
| Spare Parts | `Spare_Parts` | Manuais | idem |
| Dossiê | `Dossie` | Manuais | idem |
| Guia de Instalação | `Guia_Instalacao` | Manuais | idem |
| QI/QO/QD | `QIQOQD` | Manuais | idem |

---

## Mapa de arquivos

| Arquivo | O que muda |
|---|---|
| `models.py` | Constantes de tipos atualizadas; novo modelo `Equipamento`; `Documento.equipamento_id` (FK); `to_dict` anexa identidade do equipamento |
| `servidor.py` | `_sync_schema` (coluna FK); bloco de startup (criar tabela + backfill equipamentos + PRE→IT + Checklist/Dossie/Guia); enums; criação POST (PRE cria 2 irmãos, Manuais 7); CRUD de equipamento; busca server-side; categorização de arquivos por `tipo_doc` |
| `static/app.js` | Carregar `/api/equipamentos`; modal com cabeçalho de identidade + 9 abas; `groupByEquip` lê identidade da entidade; status do card = pior status; busca client-side com campos do equipamento; CSS das abas |

---

## Task 1 — Constantes e modelo `Equipamento` em `models.py`

**Arquivos:** Modify `models.py`

- [ ] **1.1 Substituir o bloco de constantes (`models.py:20-38`)**

```python
SETORES = ["PRE", "Manuais"]

STATUS_PRE = ["Elaborar", "Treinamento Piloto", "Enviado para Homologação", "Homologado"]
STATUS_FABRICANTE = ["Elaborar", "Em andamento", "Concluído"]

STATUS_MAP = {"PRE": STATUS_PRE, "Manuais": STATUS_FABRICANTE}

TIPOS_DOC_PRE = ["IT", "Checklist"]
TIPOS_DOC_FABRICANTE = [
    "Manual_Usuario", "Manual_ES", "Manual_Servico",
    "Spare_Parts", "Dossie", "Guia_Instalacao", "QIQOQD",
]
TIPOS_DOC_TODOS = TIPOS_DOC_PRE + TIPOS_DOC_FABRICANTE

# setor de cada tipo (define o pipeline de status)
SETOR_DO_TIPO = {t: "PRE" for t in TIPOS_DOC_PRE}
SETOR_DO_TIPO.update({t: "Manuais" for t in TIPOS_DOC_FABRICANTE})

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

- [ ] **1.2 Novo modelo `Equipamento`** (após o modelo `Documento`)

```python
class Equipamento(db.Model):
    __tablename__ = "equipamentos"

    id              = db.Column(db.Integer, primary_key=True)
    nome            = db.Column(db.String(200), nullable=False, index=True)  # chave de junção
    nome_original   = db.Column(db.String(300), default="")
    sku             = db.Column(db.String(50), default="")
    anvisa          = db.Column(db.String(60), default="")   # nº de registro ANVISA
    anvisa_registro = db.Column(db.String(40), default="")   # data ISO em texto (padrão do projeto)
    anvisa_validade = db.Column(db.String(40), default="")   # data ISO em texto
    fabricante      = db.Column(db.String(200), default="")
    familia         = db.Column(db.String(120), default="")  # categoria p/ filtro no grid
    armazenamento_base = db.Column(db.String(500), default="")
    ativo           = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em       = db.Column(db.DateTime, default=datetime.now)
    updated_em      = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            "id": self.id, "nome": self.nome or "",
            "nome_original": self.nome_original or "", "sku": self.sku or "",
            "anvisa": self.anvisa or "", "anvisa_registro": self.anvisa_registro or "",
            "anvisa_validade": self.anvisa_validade or "", "fabricante": self.fabricante or "",
            "familia": self.familia or "", "armazenamento_base": self.armazenamento_base or "",
            "ativo": bool(self.ativo),
        }
```

- [ ] **1.3 `Documento`: adicionar FK** (`models.py:~169`, junto às colunas)

```python
equipamento_id = db.Column(db.Integer, db.ForeignKey("equipamentos.id"), nullable=True, index=True)
```

> Mantém `equipamento` (string) — é a chave usada hoje em toda a base; o `equipamento_id` é adicional para a junção limpa.

- [ ] **1.4 `Documento.to_dict`: anexar identidade do equipamento** (após `"equipamento"`)

```python
"equipamento_id": self.equipamento_id,
# Identidade vem da entidade (fonte única). Fallback "" se ainda não vinculado.
"nome_original": (self.equipamento_rel.nome_original if self.equipamento_rel else ""),
"anvisa":        (self.equipamento_rel.anvisa if self.equipamento_rel else ""),
"familia":       (self.equipamento_rel.familia if self.equipamento_rel else ""),
```

…com o relacionamento no modelo:

```python
equipamento_rel = db.relationship("Equipamento", foreign_keys=[equipamento_id], lazy="joined")
```

> `lazy="joined"` evita N+1 ao serializar listas de documentos.

- [ ] **1.5 Commit** — `feat: entidade Equipamento + constantes de 9 tipos de documento`

---

## Task 2 — Schema e backfill no startup (substitui a "migração SQL")

**Arquivos:** Modify `servidor.py`

- [ ] **2.1 `_sync_schema` (`servidor.py:1080`): adicionar a coluna FK em `documentos`**

```python
novas_colunas = {
    # ... entradas existentes ...
    "documentos": [
        ("equipamento_id", "INTEGER"),
    ],
}
```

> A tabela `equipamentos` em si é criada por `db.create_all()` (já chamado em `servidor.py:1203`). `_sync_schema` só cobre colunas novas em tabelas que já existiam.

- [ ] **2.2 Bloco de startup (`servidor.py:1201-1259`): estender o backfill**

A. **Backfill da entidade Equipamento** — para cada `equipamento` distinto em `documentos`, criar (se faltar) a linha em `equipamentos` copiando `sku`/`fabricante`/`armazenamento` do doc mais informativo, e setar `documento.equipamento_id`. Idempotente.

B. **PRE → IT** — todo doc `setor='PRE'` sem `tipo_doc` vira `tipo_doc='IT'`.

C. **Criar tipos faltantes por equipamento** — generalizar o loop que hoje só cobre Manuais (`servidor.py:1220`): iterar sobre `TIPOS_DOC_TODOS` e criar o que faltar, usando `SETOR_DO_TIPO[t]` para definir o `setor` e `STATUS` inicial `"Elaborar"`. Isso cobre Checklist (PRE), Dossiê e Guia de Instalação (Manuais) de uma vez. Trocar a lista hardcoded `["Manual_ES", ...]` por `TIPOS_DOC_TODOS`.

> Resultado: ao subir o servidor (local ou Render), todo equipamento existente passa a ter os 9 docs + 1 linha em `equipamentos`, com status novos = `Elaborar` (decisão confirmada). Tudo reversível (soft delete já existente).

- [ ] **2.3 Verificar localmente** após `nssm restart DocTrack`:
  - `SELECT COUNT(*) FROM equipamentos;` == nº de equipamentos distintos.
  - `SELECT tipo_doc, COUNT(*) FROM documentos WHERE ativo GROUP BY tipo_doc;` mostra os 9 tipos.
  - Nenhum `documentos.equipamento_id` nulo entre os ativos.

- [ ] **2.4 Commit** — `feat: backfill no startup — entidade Equipamento + 9 tipos por equipamento`

---

## Task 3 — `servidor.py`: enums, criação, CRUD de equipamento, busca, arquivos

**Arquivos:** Modify `servidor.py`

- [ ] **3.1 Import de constantes (`servidor.py:75`)**

```python
from models import (
    db, bcrypt, User, Documento, Equipamento, AuditLog, RevokedToken, Responsavel,
    SETORES, STATUS_PRE, STATUS_FABRICANTE, STATUS_MAP,
    TIPOS_DOC_PRE, TIPOS_DOC_FABRICANTE, TIPOS_DOC_TODOS,
    SETOR_DO_TIPO, TIPOS_DOC_LABELS,
)
```

- [ ] **3.2 `/api/enums` (`servidor.py:885`)** — expor `tipos_doc_pre`, `tipos_doc_fabricante`, `tipos_doc_labels`, `setor_do_tipo`, `familias` (distinct de `equipamentos.familia`).

- [ ] **3.3 Reescrever criação no POST `/api/documentos` (`servidor.py:437-500`)**

> ⚠️ Correção do plano original: o ramo PRE (`else`, `servidor.py:477`) **NÃO** cria irmãos hoje — cria 1 doc só. É preciso reescrever para ambos os setores criarem os irmãos. Generalizar:

```python
tipos_exigidos = TIPOS_DOC_PRE if setor == "PRE" else TIPOS_DOC_FABRICANTE
selected_tipo  = data.get("tipo_doc") or tipos_exigidos[0]
# garantir Equipamento (get-or-create por nome) e usar equip.id em todos os docs
# criar o doc selecionado + os irmãos faltantes do mesmo setor
```

> Ao criar PRE, criam-se IT + Checklist. Ao criar Manuais, os 7. Vincular todos ao `equipamento_id`.

- [ ] **3.4 Endpoints de Equipamento (novos)**
  - `GET /api/equipamentos` — lista `Equipamento.to_dict()` (ativos). Suporta `?q=` (busca por nome/nome_original/sku/anvisa).
  - `PATCH /api/equipamentos/<id>` — edita identidade (admin/gestor/técnico). Audita via `log_action`.

- [ ] **3.5 Busca server-side (`servidor.py:403`)** — incluir campos do equipamento no blob:

```python
blob = " ".join(norm(str(d.get(f, ""))) for f in (
    "equipamento", "documento", "codigo_doc", "sku", "responsavel",
    "armazenamento", "tipo_doc", "fabricante", "nome_original", "anvisa", "familia"))
```

E adicionar `nome_original`, `anvisa`, `familia` ao `CAMPOS_STR` se forem editáveis via PATCH de documento (provavelmente **não** — são do equipamento; manter o PATCH de documento sem eles).

- [ ] **3.6 Categorização de arquivos (`servidor.py:731-787`)** — aceitar `?tipo_doc=` opcional; quando presente, rotular a `categoria` com o `TIPOS_DOC_LABELS[tipo_doc]`. Sem o parâmetro, manter a heurística atual (IT/Checklist/Outros por nome de arquivo).

- [ ] **3.7 Seed do Excel (`servidor.py:270`)** — trocar `cols_tipos` hardcoded para mapear todas as colunas conhecidas e, ao final do seed, deixar o backfill da Task 2.2 completar os tipos/equipamentos faltantes (evita lógica duplicada).

- [ ] **3.8 Commit** — `feat: servidor — equipamentos, criação 9 tipos, busca e arquivos por tipo`

---

## Task 4 — `app.js`: identidade + 9 abas

**Arquivos:** Modify `static/app.js`

- [ ] **4.1 Carregar equipamentos** — em `refreshAll`/boot, `GET /api/equipamentos` → `allEquip` (mapa por nome). Usar para enriquecer grupos e o cabeçalho do modal.

- [ ] **4.2 Constantes de tipos** — adicionar `_PRE_TIPOS` e atualizar `_MAN_TIPOS` (`app.js:1010`) com os 7; `_TODOS_TIPOS = [..._PRE_TIPOS, ..._MAN_TIPOS]`. Reusar `_PRE_STATUS`/`_MAN_STATUS` (`app.js:1008-1009`).

- [ ] **4.3 `groupByEquip` (`app.js:913`)** — em vez de `pre` (objeto único), guardar `docsByTipo` (mapa tipo→doc) e anexar `equip = allEquip[nome]`. Remover a suposição "PRE = 1 doc".

- [ ] **4.4 Status do card = pior status (`equipStatusColor`, `app.js:931`)** — calcular a partir de **todos** os docs do grupo: vermelho se qualquer um em `Elaborar`; verde só se todos finalizados (IT/Checklist=`Homologado` e os 7=`Concluído`); âmbar caso contrário. Ajustar `equipMatchesChip` (`app.js:940`) na mesma lógica (remover `g.pre.status`).

- [ ] **4.5 `switchEquipTab` + render do modal (`app.js:1024-1144`)** — substituir os 2 painéis fixos (`equip-panel-pre`/`-manuais`) por:
  - **Cabeçalho de identidade** (lê de `g.equip`): nome, nome_original (subtítulo), badges SKU/ANVISA/fabricante/família, bolinha de pior status, botão "Editar identidade" → PATCH `/api/equipamentos/<id>`.
  - **9 abas roláveis** geradas de `_TODOS_TIPOS`; cada painel via `renderTipoPanel(tipo, doc)` usando `_PRE_STATUS` se `tipo ∈ _PRE_TIPOS`, senão `_MAN_STATUS`.
  - Reaproveitar os campos do painel PRE atual (código, responsável, datas, obs, armazenamento, Ver arquivos) por tipo.

- [ ] **4.6 Funções de save** — reescrever `saveEquipPre`/`saveEquipManuais`/`createPreDoc`/`createManuais` (`app.js:1151+`) para o novo formato por-tipo; o "Ver arquivos" passa `?tipo_doc=` (Task 3.6).

- [ ] **4.7 Busca client-side (`renderGrid`, `app.js:980`)** — incluir campos do equipamento:

```js
[g.equipamento, g.sku, g.fabricante,
 g.equip?.nome_original, g.equip?.anvisa, g.equip?.familia].join(' ').toLowerCase()
```

- [ ] **4.8 Card do grid (`app.js:993`)** — manter enxuto (nome + SKU). **Não** exibir `nome_original`/ANVISA no card; eles aparecem só no cabeçalho do modal. (Opcional: badge de família para filtro visual.)

- [ ] **4.9 CSS das abas** — `.equip-modal-tabs { display:flex; overflow-x:auto; gap:4px; }`, `.equip-modal-tab { flex-shrink:0; white-space:nowrap; }`, estilo de aba ativa, cabeçalho de identidade.

- [ ] **4.10 Commit** — `feat: modal com identidade do equipamento + 9 abas; status do card = pior status`

---

## Task 5 — Teste manual

- [ ] 5.1 `nssm restart DocTrack` (Admin) e conferir logs de backfill.
- [ ] 5.2 Abrir equipamento existente → 9 abas + cabeçalho com SKU/ANVISA/família.
- [ ] 5.3 Editar identidade (ANVISA/nome_original) → persiste e some do card, aparece no cabeçalho.
- [ ] 5.4 Buscar por `nome_original`/ANVISA/família → encontra o equipamento.
- [ ] 5.5 IT/Checklist com pipeline de 4 etapas; os 7 com 3 etapas.
- [ ] 5.6 Card fica vermelho com algum `Elaborar`, verde só com tudo finalizado (pior status).
- [ ] 5.7 Criar equipamento novo → 1 linha em `equipamentos` + 9 docs.

---

## Decisões já confirmadas

1. Modelo de dados: **tabela `Equipamento` própria** (fonte única de identidade).
2. Campos de identidade agora: nome, nome_original, **SKU**, **ANVISA (nº)**, **registro/validade ANVISA**, **fabricante**, **família/categoria**, armazenamento_base.
3. Status do card/grid: **pior status** entre os documentos do equipamento.
4. `nome_original` (e identidade) é **do equipamento**, não do documento.
5. Checklist usa o **mesmo pipeline do IT** (4 etapas).
6. Documentos novos (Checklist/Dossiê/Guia) nascem em **`Elaborar`** para equipamentos existentes.
