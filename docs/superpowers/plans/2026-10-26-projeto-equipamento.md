# Ondas A e B — projeto ↔ equipamento e entregável = documento

> Executado inline, com TDD no servidor. Desenho:
> [`../../planos/ESTUDO_ligacoes_entregaveis.md`](../../planos/ESTUDO_ligacoes_entregaveis.md)
> (seções 4 a 7). Decisão do usuário: **ciclo do projeto** para equipamento que
> já existe. Branch `feat/projeto-equipamento`, empilhado sobre o de fluxos.

**Objetivo:** criar um projeto do PDE cria (ou liga) o equipamento com os 12
documentos; o entregável de natureza *documento controlado* passa a espelhar o
documento — status, fluxo de revisão e sino são um só nas duas telas.

**Regra central (vinculos.py):** o artefato é calculado — equipamento do projeto
+ natureza/alvo do item do modelo (ou do próprio entregável) → documento(s). O
status do entregável é gravado por sincronização a partir do documento, com
histórico, e só conta como pronto o que foi concluído depois do início do
projeto.

## Tarefas

1. **Schema.** `projetos.equipamento_id` (FK, índice); `natureza` e `alvo` em
   `modelos_entregavel` e `entregaveis`. `_sync_schema` + `migrations/022`.
   Relação `Projeto.equipamento`; `to_dict` com natureza/alvo e equipamento.
2. **`vinculos.py`** (regra pura sobre os objetos): `NATUREZAS`, alvos de
   documento (12 tipos + "checklists"), `natureza_alvo`, `documentos_do`,
   `inicio_do_projeto`, `estado_do_documento`, `espelho` (agregação dos
   checklists + ciclo do projeto), `artefato_do`, `sincronizar_entregavel`,
   `sincronizar_do_documento`, `sincronizar_projeto`, `previa_vinculo`,
   `criar_equipamento_para`. Testes em `tests/test_vinculos.py`.
3. **API do projeto.** Criar/editar com `equipamento_id` ou
   `criar_equipamento` (só área PDE; SKU já usado → 409 com sugestão).
   `GET /api/projetos/equipamentos-opcoes`, `GET /api/projetos/<id>/vinculo-previa`,
   `GET /api/projetos/por-documento/<doc_id>`. Entregável ganha `artefato` no
   detalhe do projeto. `PUT` do entregável ligado recusa mudar status/percentual
   (409). Item do modelo aceita `natureza`/`alvo` e ressincroniza os projetos.
4. **Ganchos.** Troca de status do documento (rota de status, PATCH genérico,
   fluxo) e N/A do Escopo ressincronizam os entregáveis ligados; criação do
   projeto e "Aplicar o modelo" sincronizam o projeto.
5. **Fluxo unificado.** Iniciar fluxo num entregável ligado → 409 (o fluxo é o
   do documento). `por-refs` de entregável devolve o fluxo do documento. Iniciar
   fluxo num documento *Concluído* (Manuais/PDE) reabre para *Em andamento* —
   é o novo ciclo.
6. **Telas.** Projetos: campo Equipamento no formulário (sugestão por SKU,
   prévia ao trocar), equipamento ↗ no modal, marca 📄 na linha, popover com o
   documento, o ciclo e o fluxo do documento; natureza/documento no item do
   modelo. Equipamentos e Documentos: projeto(s) ↗ no card; ficha do documento
   com "entregável do projeto ↗".
7. **Docs** (funcional de projetos, equipamentos, documentos, fluxos; correção do
   PLANO_projetos_unificados; referência; CHANGELOG) e suíte inteira.
8. **Homologação** (5390) com o modelo OEM já com naturezas e um projeto ligado.
