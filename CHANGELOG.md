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

### Pastas por grupo de documentos
- **Novo** `EquipamentoPasta`: cada equipamento declara as SUAS pastas de rede
  (nome livre + caminho completo) e cada documento aponta para uma delas. A
  estrutura real separa manuais, IT/checklists e QI/QO/QD em pastas diferentes,
  com caminhos que variam por produto — algo que o modelo anterior, de dois
  níveis (pasta do equipamento × exceção por documento), só expressava marcando
  uma "exceção" em cada documento do grupo.
- `Documento.armazenamento_efetivo` passa a resolver em três níveis: exceção do
  documento → pasta do grupo → caminho do equipamento. `armazenamento_origem`
  diz qual venceu, e é o que a tela usa para parar de chamar de exceção o manual
  que está na pasta de manuais — ou seja, a regra.
- **Novo** CRUD `GET/POST /api/equipamentos/<id>/pastas` e
  `PATCH/DELETE /api/equipamentos/<id>/pastas/<pid>`; `PATCH /api/documentos/<id>`
  aceita `pasta_id`. Remover uma pasta desvincula seus documentos antes do soft
  delete, para não deixá-los apontando para uma pasta que sumiu.
- **Backfill** `_backfill_pastas_equipamento` (boot, idempotente) materializa os
  grupos a partir do que já está gravado: cada caminho efetivo distinto de um
  equipamento vira uma pasta nomeada pela folha do caminho ("Manuais",
  "IT_Checklist"), com "Principal" para a do equipamento. Folhas homônimas sobem
  um nível ("A\\Manuais", "B\\Manuais") — todas as envolvidas, não só a segunda.
  Nenhum documento muda de lugar; só muda de onde o caminho vem.
- **Corrigida** a premissa de `_consolidar_armazenamento`, que afirmava no
  próprio docstring "1 caminho distinto por equipamento em 100% dos casos". A
  medição no banco desmente: 14 equipamentos têm de 2 a 4 pastas distintas.
- "voltar ao grupo" (antes "usar o do equipamento") devolve o documento à pasta
  do grupo dele. Antes copiava o caminho do equipamento, ignorando a pasta e
  mandando o documento para o lugar errado.

### Caminhos de pasta: UNC e unidade mapeada passam a ser o mesmo caminho
- **Corrigido** o "Caminho fora das pastas permitidas" / "pasta não encontrada" em
  pastas que existem: o caminho copiado da barra do Explorer
  (`P:\Engenharia\...`) não era reconhecido como o mesmo diretório da forma UNC
  (`\\loccus-srv03\Projetos$\Engenharia\...`) declarada na allowlist. Mapeamento de
  unidade é por sessão de logon — rodando como serviço Windows o DocTrack não
  enxerga `P:` nenhum, e o `realpath` que deveria traduzir devolvia o literal.
- **Novo** módulo `caminhos.py`, fonte única de verdade: canoniza a entrada
  (traduz o apelido de unidade, absorve aspas do "Copiar como caminho", espaços,
  barra normal, barra final e `..`), resolve o I/O tentando as duas formas e
  devolve ao usuário a forma com letra, que é a que a estação dele abre.
- **Novo** `DOCTRACK_PATH_ALIASES` (formato `P:=\\servidor\share`, separado por
  `;`). Vazio, autodetecta os mapeamentos da sessão via `WNetGetConnectionW` — o
  que não funciona como serviço, então em produção declare explicitamente.
  `DOCTRACK_FILE_ROOTS` não precisa mais listar a UNC e a letra da mesma pasta.
- **Canonizados** na entrada os caminhos gravados por PATCH de documento, PATCH de
  equipamento e importação de planilha; os já existentes são convertidos para UNC
  no boot (`_normalizar_caminhos_armazenados`, idempotente) — o banco tinha as
  duas grafias do mesmo diretório em 59 dos 475 registros preenchidos.
- **Corrigido** o override falso: salvar num documento o mesmo caminho do
  equipamento em outra grafia criava uma exceção que ninguém pediu, porque a
  comparação era por string crua.
- **Corrigido** o diagnóstico (`agente_scanner`), que reportava
  ARQUIVO_NAO_ENCONTRADO para pasta existente gravada na grafia que o processo
  não enxergava.
- A validação da allowlist deixou de usar `realpath` + `commonpath` a cada
  request: `commonpath` levantava `ValueError` entre `P:\...` e `\\srv\...` e o
  `except` virava um 403 mudo, e o `realpath` disparava um round-trip SMB por
  chamada (travando segundos com o share fora do ar). O `realpath` continua como
  checagem extra contra junction apontando para fora do share.

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
