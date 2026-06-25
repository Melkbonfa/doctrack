# Plano — Módulo Equipamentos (entidade central) v1

> Evolução da plataforma DocTrack. Promove **Equipamento** a entidade central e
> reduz a responsabilidade do módulo de Documentos. **Faseado** para subir à
> produção (que está no ar) de forma incremental e reversível.

**Base:** este plano CONTINUA o trabalho da branch `feat/documentos-equipamento-9tipos`,
que já criou a entidade `Equipamento` (tabela `equipamentos`, FK em `documentos`,
backfill no startup e modal). Não recomeça do zero — estende.

---

## Decisões travadas (2026-06-25)

1. **Faseado.** Fase 1 entrega o módulo Equipamentos central + importação dos 155;
   Documentos segue 1:N (9 tipos) por enquanto. M:N + taxonomia configurável vêm na Fase 2.
2. **Navegação:** novo card **"Equipamentos"** no hub `/hub/pde`, ao lado de
   Documentos e Projetos, com página própria (grid + detalhe com abas).
3. **Campos:** core enxuto agora (identidade + o que a planilha preenche + o que já
   existe); campos técnicos/regulatórios avançados entram por fase.

---

## Achados da planilha mestra (`Equipamentos Cadastrados.xlsx`)

- **155 equipamentos**; o sistema tem **45** (derivados de docs). ~**110 são novos**.
- Colunas reais: **SKU de Importação, SKU de Venda, Equipamento, Bloqueio (SIM/NÃO/-), Observações**. Os demais ~25 campos do cadastro nascem vazios.
- **Chave de junção = SKU de Venda** (não o nome). Ex.: master "AMPLIGENE LITE - …"
  tem SKU de Venda `01.000889`, igual ao `equipamentos.sku` já existente. Os **nomes
  divergem** (master é maiúsculo + descrição longa; sistema usa "AmpliGene Lite").
  → casar por SKU reconcilia os 45 e cria só os ~110 que faltam; casar por nome geraria duplicatas.
- A planilha traz dois nomes implícitos: o **longo/descritivo** ≈ Nome Técnico, e o
  **curto** ≈ Nome Comercial. Status às vezes embutido no nome ("OBSOLETO -",
  "DESCONTINUADO -") → vira campo `status`, sai do nome.
- `BLOQUEIO`: 124 NÃO · 24 SIM · 7 "-". `SKU de Importação` preenchido em 110/155.

---

## Arquitetura alvo

```
Equipamento  (entidade central)
   ├── Documentos          (Fase 2: M:N + categorias/tipos configuráveis)
   ├── Registros Regulatórios (Fase 3)
   ├── Fornecedores        (Fase 4)
   ├── Treinamentos        (Fase 4)
   ├── Processos           (Fase 4)
   └── Validações / CAPA   (Fase 4)
```

## Roadmap por versão

| Fase | Versão | Entrega |
|---|---|---|
| **1** | 4.2.0 | Módulo Equipamentos (grid + detalhe c/ abas) · importação dos 155 por SKU · card no hub · histórico/auditoria |
| 2 | 4.3.0 | Documentos vira registro controlado **M:N** + **Categorias/Tipos configuráveis**; remove identidade do doc |
| 3 | 4.4.0 | Regulatório avançado: classe de risco, situação, vencimentos e **alertas automáticos** |
| 4 | 5.0.0 | Fornecedores, Treinamentos, Processos, CAPA, validação CSV (IQ/OQ/PQ), prontidão para auditoria |

---

## FASE 1 — Módulo Equipamentos (detalhada)

### Task 1 — Estender a entidade `Equipamento` (core)

`models.py` — adicionar ao modelo existente (mantendo os atuais
nome, nome_original, sku, anvisa, anvisa_registro, anvisa_validade, fabricante,
familia, armazenamento_base):

```python
codigo_interno   = db.Column(db.String(50), default="")
sku_importacao   = db.Column(db.String(50), default="")   # SKU de Importação
nome_tecnico     = db.Column(db.String(400), default="")  # nome longo/descritivo (master)
descricao        = db.Column(db.Text, default="")         # descritivo livre do equipamento
status           = db.Column(db.String(40), default="Ativo")  # Ativo/Obsoleto/Descontinuado
bloqueado        = db.Column(db.Boolean, default=False, nullable=False)
observacoes      = db.Column(db.Text, default="")         # notas internas (≠ descricao)
# Taxonomia gerenciada (ver Task 1b). Substitui categoria/familia texto-livre.
categoria_id     = db.Column(db.Integer, db.ForeignKey("categorias_equipamento.id"), nullable=True, index=True)
familia_id       = db.Column(db.Integer, db.ForeignKey("familias_equipamento.id"), nullable=True, index=True)
linha_id         = db.Column(db.Integer, db.ForeignKey("linhas_produto.id"), nullable=True, index=True)
```

> A coluna `familia` (String) existente vira legado; migrar para `familia_id`. `categoria`/`linha` passam a ser FKs.

Convenções de nome:
- `nome` (existente) = **Nome Comercial / chave de junção** com os documentos. Não é sobrescrito pela importação.
- `nome_original` (existente) permanece (nome comercial alternativo do fabricante).
- `nome_tecnico` = a string longa da planilha.
- `descricao` = **descritivo livre** (aplicação/princípio/diferenciais), editável no card. Distinto de `nome_tecnico` e de `observacoes` (internas).
- `sku` (existente) = **SKU de Venda** (chave de junção). Novo `sku_importacao`.

Campos técnicos/regulatórios avançados (modelo, tecnologia, aplicação, princípio,
classe de risco, situação regulatória, responsável regulatório, condições de
armazenamento/transporte) ficam para a Fase 1.5/3 — não criar vazios agora.

`_sync_schema` (`servidor.py`): adicionar as colunas novas em `equipamentos`
(o mecanismo idempotente cross-dialect já existe).

### Task 1b — Taxonomia gerenciada (Categorias · Famílias · Linhas)

**Decisão:** família **aninhada na categoria** (uma família pertence a uma categoria).
Linha é lista plana independente. Editável sem código (como a aba "Modelos" do Projetos).

```python
class CategoriaEquipamento(db.Model):     # categorias_equipamento
    id, nome, ordem, ativo
    familias = relationship("FamiliaEquipamento", ...)   # 1:N

class FamiliaEquipamento(db.Model):       # familias_equipamento
    id, categoria_id (FK), nome, ordem, ativo            # aninhada na categoria

class LinhaProduto(db.Model):             # linhas_produto
    id, nome, ordem, ativo                               # lista plana independente
```

- O **vínculo** equipamento → categoria/família/linha é definido **na ficha do card**
  (Lista de Equipamentos), não nesta tela. Ao escolher a categoria, o select de
  família filtra para as famílias daquela categoria.
- A tela "Categorias" gerencia só as **listas** (CRUD + contagem de uso). Excluir
  item em uso pede confirmação e desvincula.
- Seed inicial a partir das categorias/famílias que já existirem nos dados.

### Task 2 — Importador da planilha mestra (idempotente, por SKU)

Novo `equipamentos_importer.py` (espelha o padrão de `pdr/importer.py`):

- Lê de `DOCTRACK_EQUIP_MASTER` (default = caminho na rede `P:\…\Equipamentos Cadastrados.xlsx`) **ou** de upload.
- Para cada linha com `SKU de Venda`:
  - **existe** Equipamento com `sku == sku_venda` → atualiza `sku_importacao`,
    `nome_tecnico`, `bloqueado`, `observacoes` (NÃO sobrescreve `nome`).
  - **não existe** → cria Equipamento novo (`nome` = nome curto melhor-esforço ou a
    string master para curadoria posterior; `nome_tecnico` = master; sem documentos).
  - sem `SKU de Venda` → entra no **relatório de inconsistências** (não cria).
- Heurística de status: nome com "OBSOLETO"/"DESCONTINUADO" → `status`; `BLOQUEIO=SIM` → `bloqueado=True`.
- **Dry-run + commit**: `POST /api/equipamentos/import?dryrun=1` devolve prévia
  (a criar / a atualizar / inconsistências) antes de aplicar.
- **Manual** (botão na tela), **não** roda no boot — evita surpresa em produção.

### Task 3 — API do módulo

- `GET /api/equipamentos` — estender com filtros (`categoria`, `familia`, `linha`,
  `status`, `bloqueado`), ordenação e busca (já inclui nome/nome_original/sku/anvisa/família).
- `GET /api/equipamentos/<id>` — registro completo + contagem de documentos vinculados.
- `POST /api/equipamentos` — cadastro manual.
- `PATCH /api/equipamentos/<id>` — já existe; cobrir os campos novos.
- `GET /api/equipamentos/export` — CSV conforme filtros.
- `POST /api/equipamentos/import` — importação (Task 2).
- Auditoria: `log_action` em create/update; alimenta a aba Histórico.

### Task 4 — Navegação e telas (3 sub-visões)

- **Card "Equipamentos"** em `templates/subhub.html` (área pde), `data-module="equip"`,
  ao lado de Documentos e Projetos. Rota `/equipamentos` → `templates/equipamentos.html`
  + `static/equipamentos.js` (espelha Projetos/entregáveis). Sidebar com 3 itens:
  **Dashboard · Equipamentos · Categorias**.
  Mockups de referência: `mockup_dashboard_equipamentos.html`,
  `mockup_equipamentos_lista.html`, `mockup_equipamentos_categorias.html`.

- **4a — Dashboard (completude / ICE):**
  - **ICE** por equipamento = média simples de 3 sub-índices (0–100%):
    **Cadastro** (campos de identidade preenchidos), **Regulatório** (ANVISA nº/registro/
    validade não vencida/classe de risco), **Documental** (% dos 9 tipos em status
    **final** — Homologado/Concluído; integra com o pipeline de Documentos).
  - Bloqueados/Obsoletos **fora do cálculo por padrão**, com toggle para incluir.
  - KPIs (ICE médio, # completos, # pendência regulatória, # doc incompleta) ·
    donut por faixa (Completo ≥85 / Parcial 50–84 / Inicial <50) · barras por dimensão ·
    **lacunas mais comuns** · **worklist** (menos completos). Filtros iguais aos outros.

- **4b — Equipamentos (lista + ficha):**
  - Grid de **cards** (padrão do Documentos) com identidade + **anel de ICE** no card.
  - Pesquisa, filtros (categoria/família/linha/status/bloqueado), exportação,
    **Importar planilha** e **Novo equipamento** (admin/gestor).
  - **Ficha editável** (abas): **Geral** (código interno, SKUs, nome comercial/técnico,
    **descritivo**, categoria→família dependentes, linha, status, bloqueado, observações) ·
    **Técnico** (fabricante + avançados quando existirem) · **Regulatório** (ANVISA + Fase 3) ·
    **Documentos** (reusa modal de 9 abas, filtra por `equipamento_id`) · **Histórico** (AuditLog).

- **4c — Categorias (config da taxonomia):** Task 1b — gerencia Categorias (→ Famílias
  aninhadas) e Linhas; o vínculo por equipamento é feito na ficha (4b).

### Task 5 — Permissões, versão e validação

- Papéis: admin/gestor/tecnico editam; leitor só lê (reaproveita `require_role`).
- `VERSION` → `4.2.0-dev`; entrada no `CHANGELOG.md`.
- Validar em homologação (banco SQLite local): importar os 155, conferir que os 45
  existentes foram reconciliados por SKU (sem duplicar) e ~110 criados; abrir um
  equipamento e navegar as abas.

---

## FASE 2 — Documentos como registro controlado (resumo)

- Tabelas novas configuráveis: `categorias_documento`, `tipos_documento` (tipo
  pertence a categoria). Seed inicial: Manual, IFU, Registro, Certificado,
  Especificação, Procedimento, Relatório, Validação (IQ/OQ/PQ/CSV), Treinamento.
- `documentos`: adicionar revisão, vigência, vencimento, data de aprovação, arquivo,
  categoria_id, tipo_id. Tabela de junção `documento_equipamento` (**M:N**).
- Backfill: cada `documentos.equipamento_id` atual vira 1 vínculo M:N; os "9 tipos
  fixos" viram um **conjunto esperado** (checklist) por equipamento, opcional.
- Remover do documento os dados de equipamento (passam a ser derivados do vínculo).

## FASE 3 — Regulatório avançado

Classe de risco, situação regulatória, nº de processo, responsável regulatório;
controle de vencimentos com **alertas automáticos** (e-mail/painel).

## FASE 4 — Expansão

Fornecedores, Treinamentos, Processos, matriz de impacto, gestão de mudanças, CAPA,
integração com validação de sistemas computadorizados (alinhado a RDC 665 / ISO 13485).

---

## Benefícios

Separação produto × documento · menor redundância · rastreabilidade · aderência
regulatória · base escalável. Cada fase é isolada, reversível e sobe à produção sem
interromper os usuários.

## Pontos a confirmar antes de implementar a Fase 1

1. **Nome comercial dos ~110 novos:** importar com `nome` = string master (curadoria
   manual depois) ou tentar derivar um nome curto automaticamente?
2. **Origem da planilha na importação:** ler direto do caminho de rede `P:\…` (o
   servidor de produção enxerga via UNC) ou exigir upload do arquivo na tela?
3. **Card "Equipamentos":** entra para todos os perfis ou só gestor/admin no começo?
