# PLANO — Catálogo de Consumíveis (aba dentro de Equipamentos)

> Objetivo: uma aba **Consumíveis** no módulo Equipamentos, com um **catálogo global**
> de consumíveis (cada consumível é uma entidade com informações próprias) e um
> **vínculo N:N de compatibilidade** com os equipamentos. Importação inicial a partir
> de duas planilhas + cadastro manual para o que não está listado.

---

## 0. Contexto e decisões de arquitetura (ler antes de codar)

### O que já existe
- `Equipamento` (models.py:278) — entidade central, dedup por **SKU de Venda** normalizado
  (`equipamentos_importer._norm_sku`, ignora zero à esquerda: `01.000404` == `1.000404`).
- `EquipamentoItem` (models.py:391) — tabela `equip_itens`, guarda `consumivel`/`acessorio`
  como **filhos de UM equipamento** (nome + sku + sku_importacao). Rotas em servidor.py:801-855.
- Taxonomia gerenciável: `CategoriaEquipamento` → `FamiliaEquipamento` (models.py:344-372),
  padrão a ser copiado para "tipo de consumível".
- Frontend SPA de página única: `templates/equipamentos.html` (nav lateral com `data-page`,
  páginas `.page` com id `page-<x>`), `static/equipamentos.js` (função `navigate(page)`,
  `abrirFicha`, fichas em modal com abas `fichaSwitch`), `static/equipamentos.css`.
- Import com dry-run: `equipamentos_importer.importar_equipamentos(dryrun=True/False)` +
  rota `/api/equipamentos/import` (servidor.py:710). **Copiar esse padrão.**
- Migrations idempotentes em SQL puro: `migrations/00X_*.py` com `upgrade(db_path)`. Copiar
  o padrão de `006_tipo_projeto_e_modelos.py`.

### Por que NÃO reaproveitar `EquipamentoItem` como está
`EquipamentoItem` é 1→N (um item pertence a um equipamento). O pedido é o inverso: **um
consumível, muitos equipamentos compatíveis**. O mesmo "Tip box 200ul (01.001367)" aparece
em ~10 planilhas de equipamentos diferentes. Precisamos de **catálogo único (dedup por SKU) +
tabela de vínculo N:N**. `EquipamentoItem` de tipo `consumivel` será **migrado** para o novo
catálogo (ver Fase 5); `acessorio` fica como está (fora de escopo).

### Decisão de modelagem (fonte da verdade deste plano)
Três tabelas novas:
1. `consumiveis` — o catálogo (entidade própria).
2. `tipos_consumivel` — taxonomia leve (Ponteira, Placa PCR, Placa de extração, Kit de
   extração, Cartucho, Filme de vedação, Tira/Tip comb, Lâmina, MasterMix/Reagente, Reservatório…).
3. `consumivel_equipamento` — vínculo N:N **com atributos** (o "como" da compatibilidade).

### O atributo-chave do vínculo: `fornecimento`
A planilha 2 classifica cada consumível por equipamento em três baldes recorrentes:
`Exclusivo Loccus` · `Loccus pode fornecer` · `Não fornecido pela Loccus` (+ variações como
"Pode ser utilizado, mas não fornecido"). Isso **não** é atributo do consumível — é da relação
consumível×equipamento (o mesmo consumível pode ser exclusivo em um equipamento e "pode fornecer"
em outro). Logo mora na tabela de vínculo, como enum normalizado.

### Como as duas planilhas se encaixam (analisado)
- **`Lista consumíveis_v3 2 1.xlsx`** — 1 aba por equipamento. Colunas `Modelo · SKU · Observação`,
  agrupadas por faixas de `fornecimento`. Dá o **catálogo + vínculo + fornecimento**. Equipamento
  identificado pelo **título da aba** (casar por nome normalizado). SKU às vezes ausente
  (`?`, `sem cadastro`, `diversos`) → criar consumível "sem SKU" sinalizado p/ revisão manual.
- **`Consumíveis Equipamentos de Automação.xlsx`** — **matrizes de compatibilidade**. Abas `Tips`,
  `Placas de Extração`, `Kits de Extração`, `PCR`, `Tip Comb`: linhas = equipamentos (com SKU na
  col. B), colunas = variantes de consumível (SKU na linha de cabeçalho), célula `x` = compatível.
  Abas `Tips Ref.` / `Tips Ref. (2)` = **ficha técnica das ponteiras** (µL, Com Filtro, Baixa
  Retenção, Estéril, Condutível, Apresentação) → enriquecem os campos próprios do consumível.
  Dá **vínculo fino por variante** + **especificações**. Sem `fornecimento`.
- As duas são **complementares e sobrepostas por SKU**. O importador dedup por SKU normalizado,
  então importar as duas em qualquer ordem converge (idempotente).

### Pontos de decisão que o dono do produto deve confirmar (não bloqueiam o início)
- **D1.** Consumível sem SKU: criar assim mesmo (chave = nome normalizado + tipo) e marcar
  `pendente_sku=True`? → **Plano assume que sim.**
- **D2.** Migrar `EquipamentoItem(tipo=consumivel)` para o catálogo e depois esconder a aba antiga?
  → **Plano assume: migra na Fase 5, mantém `acessorio` intacto.**
- **D3.** Enum de `fornecimento`: `exclusivo_loccus | pode_fornecer | nao_fornecido | nao_informado`.
  → **Plano assume esses 4.**

---

## FASE 1 — Modelo de dados + migration

**Implementar (copiar padrões existentes):**

1. Em `models.py`, após `EquipamentoItem` (models.py:414), adicionar (copiar o estilo de
   `Equipamento.to_dict` e `CategoriaEquipamento`):

```python
# ── CONSUMÍVEIS (catálogo global + compatibilidade N:N) ──────────────────────
FORNECIMENTO = ["exclusivo_loccus", "pode_fornecer", "nao_fornecido", "nao_informado"]

class TipoConsumivel(db.Model):
    __tablename__ = "tipos_consumivel"
    id    = db.Column(db.Integer, primary_key=True)
    nome  = db.Column(db.String(120), nullable=False, index=True)
    ordem = db.Column(db.Integer, default=0)
    ativo = db.Column(db.Boolean, default=True, nullable=False, index=True)
    def to_dict(self):
        return {"id": self.id, "nome": self.nome or "", "ordem": self.ordem or 0, "ativo": bool(self.ativo)}

class Consumivel(db.Model):
    __tablename__ = "consumiveis"
    id             = db.Column(db.Integer, primary_key=True)
    nome           = db.Column(db.String(200), nullable=False, index=True)  # "Tip box 200ul"
    modelo         = db.Column(db.String(300), default="")   # descrição/modelo da planilha
    sku            = db.Column(db.String(50), default="", index=True)  # SKU de Venda (chave dedup)
    sku_importacao = db.Column(db.String(50), default="")
    tipo_id        = db.Column(db.Integer, db.ForeignKey("tipos_consumivel.id"), nullable=True, index=True)
    fabricante     = db.Column(db.String(200), default="")
    # Especificações (planilha "Tips Ref."); genéricas o suficiente p/ outros tipos
    volume_ul      = db.Column(db.String(40), default="")    # "200", "20", "2,8,15mL"
    apresentacao   = db.Column(db.String(120), default="")   # "24un/cx"
    com_filtro     = db.Column(db.Boolean, default=False)
    baixa_retencao = db.Column(db.Boolean, default=False)
    esteril        = db.Column(db.Boolean, default=False)
    condutivel     = db.Column(db.Boolean, default=False)
    especificacoes = db.Column(db.Text, default="")          # campo livre p/ o resto
    observacoes    = db.Column(db.Text, default="")
    pendente_sku   = db.Column(db.Boolean, default=False, nullable=False, index=True)  # D1
    status         = db.Column(db.String(40), default="Ativo")
    ativo          = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em      = db.Column(db.DateTime, default=datetime.now)
    updated_em     = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    tipo_rel = db.relationship("TipoConsumivel", foreign_keys=[tipo_id], lazy="joined")
    def to_dict(self, com_equip=False):
        d = {...}  # espelhar Equipamento.to_dict; incluir tipo (nome), flags bool, pendente_sku
        if com_equip:
            d["equipamentos"] = [l.to_dict_equip() for l in self.vinculos if l.ativo]
        return d

class ConsumivelEquipamento(db.Model):
    __tablename__ = "consumivel_equipamento"
    __table_args__ = (db.UniqueConstraint("consumivel_id", "equipamento_id", name="uq_cons_equip"),)
    id             = db.Column(db.Integer, primary_key=True)
    consumivel_id  = db.Column(db.Integer, db.ForeignKey("consumiveis.id"), nullable=False, index=True)
    equipamento_id = db.Column(db.Integer, db.ForeignKey("equipamentos.id"), nullable=False, index=True)
    fornecimento   = db.Column(db.String(30), default="nao_informado")  # ver FORNECIMENTO
    obrigatorio    = db.Column(db.Boolean, default=False)
    observacao     = db.Column(db.String(300), default="")
    ativo          = db.Column(db.Boolean, default=True, nullable=False, index=True)
    criado_em      = db.Column(db.DateTime, default=datetime.now)
    consumivel  = db.relationship("Consumivel", backref=db.backref("vinculos", lazy="selectin"))
    equipamento = db.relationship("Equipamento", lazy="joined")
    def to_dict_equip(self):   # visão a partir do consumível
        return {"vinculo_id": self.id, "equipamento_id": self.equipamento_id,
                "equipamento_nome": self.equipamento.nome if self.equipamento else "",
                "equipamento_sku": self.equipamento.sku if self.equipamento else "",
                "fornecimento": self.fornecimento, "obrigatorio": bool(self.obrigatorio),
                "observacao": self.observacao or ""}
    def to_dict_cons(self):    # visão a partir do equipamento
        c = self.consumivel
        return {"vinculo_id": self.id, "consumivel_id": self.consumivel_id,
                "nome": c.nome if c else "", "sku": c.sku if c else "",
                "tipo": (c.tipo_rel.nome if c and c.tipo_rel else ""),
                "fornecimento": self.fornecimento, "obrigatorio": bool(self.obrigatorio)}
```

2. Criar `migrations/007_consumiveis.py` copiando `006_tipo_projeto_e_modelos.py`:
   `CREATE TABLE IF NOT EXISTS` para as 3 tabelas + índices + `UNIQUE(consumivel_id, equipamento_id)`.
   Semear `tipos_consumivel` com a lista inicial (Ponteira, Placa PCR, Placa de extração, Kit de
   extração, Cartucho, Filme de vedação, Tira/Tip comb, Lâmina, MasterMix/Reagente, Reservatório,
   Deepwell, Outro). Idempotente.

**Verificação:** `python migrations/007_consumiveis.py doctrack.db` roda 2× sem erro; 
`PRAGMA table_info(consumiveis)` e `PRAGMA table_info(consumivel_equipamento)` mostram as colunas;
`SELECT count(*) FROM tipos_consumivel` > 0.

**Anti-padrões:** não usar `db.create_all()` para produção (o banco é migrado por script SQL);
não pôr `fornecimento` em `consumiveis` (é do vínculo); não FK sem índice.

---

## FASE 2 — API REST (CRUD catálogo + vínculos + taxonomia)

**Implementar (copiar as rotas de equipamentos/itens):**

- `GET /api/consumiveis` — lista com filtros `?tipo_id=&busca=&pendente=` e, por item,
  `n_equip` (contagem de vínculos ativos). Copiar `api_equipamentos` (servidor.py:535).
- `GET /api/consumiveis/<id>` — `to_dict(com_equip=True)`.
- `POST /api/consumiveis` — cria (cadastro manual). `require_role("admin","gestor","tecnico")`.
- `PATCH/PUT /api/consumiveis/<id>` — edita campos próprios (copiar `_aplicar_campos_equip`).
- `DELETE /api/consumiveis/<id>` — soft delete (`ativo=False`), como equipamentos.
- **Vínculos:**
  - `GET  /api/consumiveis/<id>/equipamentos` — vínculos do consumível.
  - `POST /api/consumiveis/<id>/equipamentos` — body `{equipamento_id, fornecimento, obrigatorio, observacao}`.
    Upsert respeitando `uq_cons_equip` (se existir inativo, reativa).
  - `PATCH/DELETE /api/consumivel-equipamento/<vinculo_id>` — edita fornecimento/obrigatorio ou desativa.
  - `GET /api/equipamentos/<id>/consumiveis` — **visão reversa** (para a aba na ficha do equipamento),
    retorna `[to_dict_cons()]`.
- **Taxonomia:** `GET/POST /api/tipos-consumivel`, `PATCH/DELETE /api/tipos-consumivel/<id>`
  (copiar rotas de `categorias-equipamento`, servidor.py:751-799).
- Registrar `Consumivel, TipoConsumivel, ConsumivelEquipamento, FORNECIMENTO` no import de models
  em servidor.py:82. Todo mutador chama `log_action(...)` como as rotas existentes.

**Verificação:** com token, `curl` cria tipo → cria consumível → vincula a 2 equipamentos →
`GET /api/consumiveis/<id>` traz os 2; `GET /api/equipamentos/<eqid>/consumiveis` traz o consumível;
`DELETE` do vínculo remove só o vínculo (consumível permanece).

**Anti-padrões:** não deletar consumível ao remover vínculo; não permitir vínculo duplicado
(confiar na UniqueConstraint + checagem prévia); não expor mutação sem `require_role`.

---

## FASE 3 — Importador das duas planilhas (dry-run + aplicar)

**Implementar** `consumiveis_importer.py` copiando o esqueleto de `equipamentos_importer.py`
(`_norm`, `_norm_sku`, `_s`, `_col`, relatório `{a_criar, a_atualizar, vinculos, inconsistencias}`,
assinatura `importar_consumiveis(path/file_bytes, dryrun=True)`). **Dois parsers, um upsert comum:**

- `_parse_lista_por_equipamento(wb)` (planilha `Lista consumíveis_v3`): itera abas; título da aba
  → nome do equipamento (casar por `_norm(nome)` contra `Equipamento`); lê blocos de cabeçalho
  `Modelo · SKU · Observação` e mapeia a faixa de `fornecimento` pela última linha "Exclusivo
  Loccus"/"Loccus pode fornecer"/"Não fornecido…" vista acima. Emite `(consumivel{nome,modelo,sku,obs},
  equip_match, fornecimento)`.
- `_parse_matriz(wb)` (planilha `Consumíveis Equipamentos de Automação`): para as abas-matriz
  (`Tips`, `Placas de Extração`, `Kits de Extração`, `PCR`, `Tip Comb`): SKU do consumível na linha
  de cabeçalho (pode ter múltiplos SKUs por célula separados por `\n` → dividir), SKU do equipamento
  na coluna B; célula `x`/`x*` → vínculo `fornecimento=nao_informado`. Para `Tips Ref.`/`Tips Ref. (2)`:
  não gera vínculo — **enriquece** o consumível (µL, com_filtro, baixa_retencao, esteril, condutivel,
  apresentacao) casando por SKU.
- **Upsert comum `_upsert_consumivel(...)`:** dedup por `_norm_sku(sku)`; se sem SKU válido, dedup por
  `_norm(nome)+tipo` e marca `pendente_sku=True` (D1). Inferir `tipo_id` por heurística do nome/aba
  (ponteira/tip→Ponteira, placa pcr→Placa PCR, kit→Kit de extração, cartucho→Cartucho, filme→Filme…).
  Vínculo idempotente (não duplica; atualiza `fornecimento` se vier mais específico que `nao_informado`).
  Equipamento não encontrado → `inconsistencias` (não cria equipamento).
- Rota `POST /api/consumiveis/import` (copiar `/api/equipamentos/import`, servidor.py:710): aceita
  `?fonte=lista|matriz` + arquivo, `dryrun` no body; retorna a prévia.

**Verificação:** rodar dry-run das duas planilhas reais e conferir contagens no relatório
(ex.: "Tip box 200ul 01.001367" aparece 1× no catálogo com N vínculos, não N vezes). Aplicar em
cópia do banco (`doctrack.db.bak-*`), reimportar → segundo run mostra `a_criar=0`.

**Anti-padrões:** não assumir cabeçalho fixo (usar `_col`/varredura, as abas variam); não tratar
`x*` diferente de `x` (ambos = compatível); não criar equipamento a partir do consumível; não
duplicar consumível por variação de zero à esquerda no SKU.

---

## FASE 4 — UI: aba Consumíveis, ficha e vínculos

**Implementar em `templates/equipamentos.html`, `static/equipamentos.js`, `static/equipamentos.css`:**

1. **Nav:** novo `<button class="nav-item" data-page="consumiveis">` na seção "Equipamentos"
   (após "Todos os equipamentos", templates/equipamentos.html:44). Ícone em SVG inline.
2. **Página `page-consumiveis`** (copiar estrutura de `page-lista`, html:106): header com badge
   de contagem, botões "Exportar CSV", "Importar planilha", "+ Novo consumível"; toolbar com busca
   + filtro por tipo + toggle "só pendentes de SKU"; grid `#cons-grid`. Card mostra nome, SKU,
   chip do tipo, e **"N equipamentos compatíveis"**.
3. **JS:** estender `navigate(page)` e `loadAll()` (equipamentos.js:70,81) para incluir consumíveis;
   `renderConsumiveis()` (espelhar `renderLista`, js:179); `abrirFichaConsumivel(id)` em modal com abas
   (copiar `abrirFicha`/`fichaSwitch`, js:201-227): **aba "Dados"** (campos próprios) + **aba
   "Equipamentos compatíveis"** (lista de vínculos com seletor de `fornecimento`, toggle obrigatório,
   botão remover, e um "+ vincular equipamento" com busca no `EQUIP` já carregado).
4. **Ficha do equipamento (reversa):** na aba "Consumíveis" existente (js:217, `tabs`), trocar a
   fonte de `EquipamentoItem` por `GET /api/equipamentos/<id>/consumiveis` (catálogo), com link
   "abrir no catálogo" e ação "vincular consumível existente". (Manter a aba "Acessórios" como está.)
5. **Modal de importação:** copiar `#modal-import` (html:182) para `#modal-import-cons` com um
   seletor de fonte (Lista por equipamento / Matriz de compatibilidade) e o mesmo fluxo
   prever→aplicar de `rodarImport` (js).
6. **Config → tipos de consumível:** reaproveitar a página `page-cat` ou adicionar um bloco
   "Tipos de consumível" (copiar CRUD de categorias no JS).

**Verificação (preview_*):** subir o servidor, abrir `/equipamentos`, clicar em "Consumíveis":
grid carrega; abrir ficha de um consumível mostra os equipamentos vinculados; vincular/desvincular
reflete na hora; abrir a ficha de um equipamento mostra os consumíveis compatíveis. Testar busca,
filtro por tipo e toggle de pendentes. `preview_console_logs` sem erros.

**Anti-padrões:** não recarregar tudo a cada ação (atualizar só a lista afetada, como o JS atual);
não deixar botões de escrita visíveis para role sem permissão (`podeEditar`, js:6).

---

## FASE 5 — Migração dos consumíveis legados + verificação final

1. **Migração de dados** (dentro de `migrations/007` ou script `scripts/migrar_itens_para_consumivel.py`):
   para cada `EquipamentoItem` ativo com `tipo='consumivel'`: upsert em `consumiveis` (dedup por SKU
   normalizado / nome) e criar `ConsumivelEquipamento(consumivel, equipamento, fornecimento='nao_informado')`.
   Idempotente. Após validar, esconder a origem antiga de consumíveis na UI (aba passa a ler o catálogo;
   `acessorio` intacto). **Não apagar** `equip_itens` — só parar de usar `tipo='consumivel'`.
2. **Exportação:** `GET /api/consumiveis/export` (CSV, copiar `export_equipamentos`, servidor.py:695):
   uma linha por consumível + coluna com lista de equipamentos compatíveis (ou CSV do vínculo à parte).
3. **Bateria final de verificação:**
   - Migration roda 2× sem duplicar (grep de contagens antes/depois).
   - `grep -rn "EquipamentoItem" static/ templates/` — nenhum uso remanescente para consumíveis na UI.
   - Import das 2 planilhas + migração legada convergem: reexecutar tudo → `a_criar=0`, sem vínculos
     duplicados (`SELECT consumivel_id,equipamento_id,count(*) FROM consumivel_equipamento GROUP BY 1,2 HAVING count(*)>1` vazio).
   - Fluxo ponta a ponta no preview (Fase 4) + `tests/` se houver suíte de API (copiar padrão de teste
     de equipamentos, se existir).
4. **Backup antes de aplicar em produção:** gerar `doctrack.db.bak-pre-consumiveis-*` (padrão dos
   backups existentes) antes de rodar a migration no servidor.

---

## Resumo das entregas por fase
| Fase | Entrega | Arquivos |
|------|---------|----------|
| 1 | Modelo + migration | `models.py`, `migrations/007_consumiveis.py` |
| 2 | API CRUD + vínculos + taxonomia | `servidor.py` |
| 3 | Importador das 2 planilhas | `consumiveis_importer.py`, `servidor.py` |
| 4 | UI (aba, ficha, vínculos, import, config) | `templates/equipamentos.html`, `static/equipamentos.js`, `static/equipamentos.css` |
| 5 | Migração legada + export + verificação | `migrations/007` ou `scripts/…`, `servidor.py` |

**Dependências entre fases:** 1 → 2 → (3, 4 em paralelo) → 5. Cada fase é executável em um
contexto novo lendo este arquivo + os arquivos citados por linha.
