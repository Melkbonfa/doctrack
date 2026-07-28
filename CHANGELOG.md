# Changelog

Todas as mudanças relevantes do DocTrack são registradas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto adota [Versionamento Semântico](https://semver.org/lang/pt-BR/):
`MAJOR.MINOR.PATCH`.

- **MAJOR** — mudança incompatível (ex.: quebra de API ou de schema sem migração).
- **MINOR** — nova funcionalidade compatível com versões anteriores.
- **PATCH** — correção de bug compatível.

Sufixo `-dev` indica versão em desenvolvimento (ainda não validada em homologação).

## [Não lançado]

### Módulo Equipamentos — Fase 1 (backend)
- Entidade `Equipamento` estendida: nome_tecnico, descricao (descritivo livre),
  codigo_interno, sku_importacao, status, bloqueado, observacoes e taxonomia
  (categoria_id / familia_id / linha_id).
- Taxonomia gerenciável: `categorias_equipamento`, `familias_equipamento`
  (família aninhada na categoria) e `linhas_produto`.
- Importador da planilha mestra (`equipamentos_importer.py`): casa por **SKU de Venda**
  com fallback por nome (existentes sem SKU), deriva nome/descrição, dry-run + commit,
  relatório de inconsistências. Reconciliou 45 existentes e criou os novos sem duplicar.
- API: `GET/POST/PATCH /api/equipamentos` (filtros categoria/família/linha/status/bloqueado),
  `GET /api/equipamentos/<id>`, `/export` (CSV), `/import`; e CRUD da taxonomia
  (`/api/equip-taxonomia`, `/api/categorias-equipamento`, `/api/familias-equipamento`, `/api/linhas-produto`).

### Adicionado
- Entidade **Equipamento** como fonte única de identidade (nome, nome original,
  SKU, ANVISA + registro/validade, fabricante, família, armazenamento base).
- Documentos passam a ter **9 tipos** por equipamento: IT, Checklist (pipeline PRE,
  4 etapas) + Manual do Usuário PT/ES, Manual de Serviço, Spare Parts, Dossiê,
  Guia de Instalação, QI/QO/QD (pipeline Manuais, 3 etapas).
- Modal de equipamento maior, com cabeçalho de identidade + 9 abas por tipo.
- Busca por nome original, ANVISA e família.
- Endpoints `GET /api/equipamentos` e `PATCH /api/equipamentos/<id>`.
- `GET /api/version` e arquivo `VERSION`.

### Alterado
- Cor/status do card no grid passa a refletir o **pior status** entre os
  documentos do equipamento (antes vinha só do documento PRE).
- Migração automática no startup cria a tabela `equipamentos`, vincula
  documentos e completa os tipos faltantes (idempotente, reversível por soft delete).

### Removido
- **Linha de produto** do equipamento (ficha, filtro da lista, aba de taxonomia,
  export, busca e rotas `/api/linhas-produto`): agrupamento transversal que na
  prática repetia a **Família**.
- **Código interno**, **Modelo**, **Tecnologia** e **Aplicação** da aba Técnico
  do equipamento (ficha, visualização, export e busca).
- Remoção só de modelo/API/UI: as colunas (`linha_id`, `codigo_interno`,
  `modelo`, `tecnologia`, `aplicacao`) e a tabela `linhas_produto` continuam no
  banco, sem uso, para não exigir migração destrutiva.

---

## [4.0.0] — baseline (produção atual)

Estado de produção antes desta linha de trabalho: módulos PDE/PDR, autenticação
por convite/primeiro acesso, PMO/EVM, auditoria e configurações.
