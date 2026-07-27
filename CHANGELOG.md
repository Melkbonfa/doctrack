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

### Limpeza geral do projeto
- **Removido** o endpoint `POST /api/report/pdf` e toda a sua cadeia: a função
  órfã `exportKPIs()` (única chamadora, que nenhum botão invocava), a pasta
  `files/` (gerador WeasyPrint) e a dependência `weasyprint` do
  `requirements.txt`. O PDF do dashboard é montado no navegador com jsPDF desde
  a v4 — esse caminho estava morto e ainda pesava no deploy (GTK3, ~200 MB).
- **Removidas** as rotas `GET /socket-client.js` e `GET /app-realtime.js`: os
  arquivos foram para `static/` e passam a ser servidos pela rota estática do
  Flask, com cache-busting que antes não tinham. `audit_log_report.html` foi
  para `templates/`.
- Material fora do escopo do software (apresentações, relatórios gerados,
  planilhas de origem já migradas, scripts pontuais já executados) saiu do
  repositório para `C:\Apps\doctrack-arquivo\`. Repositório: 19 MB → 4,9 MB.
- `.gitignore`: `logs/` e `*-bak`, que estavam desprotegidos.
- `docs/Documentacao_Geracao_PDF.md` marcado como histórico — documentava uma
  geração do PDF (html2pdf.js) que não existe mais.

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

---

## [4.0.0] — baseline (produção atual)

Estado de produção antes desta linha de trabalho: módulos PDE/PDR, autenticação
por convite/primeiro acesso, PMO/EVM, auditoria e configurações.
