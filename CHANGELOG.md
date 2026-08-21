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

### Anexos do equipamento: docs agregados e repositório de software/firmware
O card do equipamento só comportava os 12 tipos canônicos de documento. Um laudo
de EMC, um certificado do fabricante ou o instalador do software não são nenhum
deles — e forçá-los num tipo existente sujaria a completude, porque o denominador
do ICE conta tipos, não arquivos. Na prática esses arquivos ficavam só na pasta de
rede, sem nada na plataforma apontando para eles.

- **Adicionado** a aba **Docs agregados** no card do equipamento (módulo
  Documentos): documentos avulsos do equipamento, **fora** da completude. Guardar
  um arquivo ali não mexe no índice de ninguém.
- **Adicionado** a aba **Software e Firmware** — repositório das versões
  liberadas pelo fabricante, para consulta e download. A ordem é pela **data de
  liberação**, não pela do envio: cadastrar hoje a versão do ano passado não a
  coloca no topo. A versão corrente de cada categoria fica destacada.
- **Adicionado** allowlist de binários (`.zip`, `.7z`, `.bin`, `.hex`, `.img`,
  `.dfu`, `.exe`, `.msi`) com teto próprio de 500 MB
  (`DOCTRACK_UPLOAD_BIN_MAX_MB`). É **separada** da allowlist de documentos de
  propósito: só o repositório de software/firmware aceita binário, e o campo
  "Arquivos" de uma IT continua recusando executável. O binário nunca abre
  inline — desce sempre como anexo, com mime genérico.
- **Corrigido** a remoção de arquivo, que consultava só `documento_arquivos` ao
  decidir se o blob virou órfão. Como o armazenamento é endereçado por conteúdo,
  o mesmo PDF enviado nos dois lugares ocupa um arquivo só: remover de um lado
  apagaria o conteúdo que o outro ainda exibe.
- **Alterado** a régua de abas do card, que virou um **rail vertical** à esquerda,
  agrupado em "Documentos" e "Equipamento". A régua horizontal já rolava com 8
  abas e ficou impraticável com 10; em coluna cabem os 12 tipos mais as abas de
  anexo sem rolagem nenhuma, e os pontinhos de status ficam numa coluna alinhada
  — dá para ler o estado do equipamento inteiro de uma vez, o que a régua
  horizontal nunca permitiu. Abaixo de 900px de largura ele volta a ser
  horizontal, mas quebrando em linhas em vez de rolar. As classes são
  compartilhadas com os modais de ficha do equipamento, consumível e projeto: o
  rail é escopado em `.equip-modal-body`, e esses três seguem na régua horizontal.
- **Adicionado** a migration `015_anexos_equipamento.py` e
  `tests/test_equipamento_anexos.py` (19 testes).

### "Código do Doc" virou "Versionamento" nos manuais
Nos manuais o campo nunca guardou código de documento: guarda a versão do manual
do fabricante ("Rev. C", "v2.1"). O rótulo antigo só descrevia o que o campo faz
no setor PRE, onde IT e checklists têm código próprio.

- **Alterado** o rótulo do campo para **Versionamento** em todos os tipos do setor
  Manuais (Manual do Usuário PT/ES, Manual de Serviço, Spare Parts, Dossiê, Guia
  de Instalação, QI/QO/QD). No PRE segue "Código do Doc". A coluna do banco
  (`codigo_doc`) e a API não mudam — nenhum dado precisa ser migrado.

### Exportações — formato, filtros e permissão
Cada módulo ganhou seu export em momento diferente e nenhum olhou para o
anterior. O resultado eram três convenções de planilha, filtros que valiam em
uns e não em outros, e permissões sem critério.

- **Corrigido** o CSV de consumíveis, que saía com **vírgula** enquanto todos os
  outros usam ponto-e-vírgula. O Excel pt-BR abre o arquivo com vírgula numa
  coluna só — o export existia e não servia. A lista de equipamentos dentro da
  célula passou de `; ` para ` | `, senão o campo sairia todo entre aspas.
- **Corrigido** os exports que ignoravam os filtros da tela e devolviam a base
  inteira: **consumíveis** (busca, tipo, "sem SKU"), **projetos** (busca e
  situação) e **PDR** (linha, fornecedor, ANVISA, status, busca). Quem filtrava
  e exportava recebia de volta tudo que tinha acabado de excluir do recorte, e
  refiltrava no Excel.
- **Alterado** os filtros de projeto para um helper único (`_filtrar_projetos`),
  usado pela listagem e pelo export. Estavam só na listagem — era por isso que o
  export não tinha nenhum, e é o que evita divergirem de novo.
- **Corrigido** o nome dos arquivos exportados, agora todos com data. O
  frontend fixava o nome (`"Entregaveis.xlsx"`, `"Missao_<nome>.xlsx"`) e
  descartava o nome datado que o servidor já montava: os exports se
  sobrescreviam na pasta de Downloads.
- **Alterado** a permissão de exportar. **Documentos**, **equipamentos** e
  **consumíveis** liberavam a base completa para qualquer login, inclusive o
  papel `leitura`; passam a exigir técnico pra cima. **Projetos** fica em gestor
  pra cima porque a aba PMO traz orçado/gasto/EAC, e dinheiro já é gestão pra
  cima pelo `pode_ver_financeiro`.
- **Adicionado** `salvarResposta`/`baixarDoServidor` em `static/common.js`,
  substituindo cinco cópias de download espalhadas por `app.js`,
  `consumiveis.js`, `equipamentos.js`, `entregaveis.js` e `missoes.js` — três
  nunca revogavam o object URL e a de projetos revogava antes do clique.
- **Corrigido** o export do PDR, que era um `<a href>` com o **JWT na query
  string** — e portanto no log de acesso do servidor. Virou download
  autenticado por cabeçalho.
- **Adicionado** `tests/test_exports.py` (17 testes), cobrindo formato, filtros
  e permissão dos seis exports; inclui os primeiros testes automatizados do PDR.

### Equipamentos — exportação em PDF do Dashboard e do Desenvolvimento
Projetos e Documentos já saíam em PDF; Equipamentos só tinha CSV da lista, e
levar ICE ou IDP para uma reunião significava tirar print de tela.

- **Adicionado** `Exportar PDF` no Dashboard de Equipamentos: A4 paisagem com
  KPIs por faixa de completude, roscas de categoria e de faixa, completude média
  por dimensão, lacunas mais comuns, evolução do ICE/IDP e o bloco de risco
  documental — e, a partir da página 2, a **worklist inteira**, não só o top 10
  que cabe na tela (nome, SKU, categoria, as três dimensões, ICE, atrasados,
  situação ANVISA e responsável).
- **Adicionado** `Exportar PDF` na aba Desenvolvimento: faixas de IDP,
  distribuição e completude por classe ABC, revisões mais pendentes, a situação
  das 6 revisões estado a estado e a matriz priorizada por Pareto.
- **Adicionado** `static/pdf-report.js` — a moldura (fundo, cartões, legenda com
  quebra de linha, barra de progresso, tabela paginada, rodapé) e a
  rasterização dos gráficos do Chart.js. Os relatórios de Documentos (`app.js`)
  e de Projetos (`entregaveis.js`) nasceram cada um com a sua cópia desses
  helpers e as cópias já divergiram — a de Projetos encolhe a legenda para caber
  no cartão, a de Documentos deixa vazar. Os novos relatórios não abriram a
  terceira cópia; **migrar os dois antigos para o arquivo comum fica pendente**
  (por isso o namespace `PDFRep`: conviver com as cópias locais não colide).
- **Corrigido**, de tabela, o travamento da rasterização em aba de fundo:
  `requestAnimationFrame` é suspenso quando a aba perde o foco, e quem trocasse
  de aba no meio da exportação ficava com o relatório pendurado para sempre. O
  novo helper corre a captura contra um `setTimeout`. Os relatórios antigos
  ainda dependem só do `requestAnimationFrame` (mesma pendência acima).
- **Adicionado** um modal de filtros para cada relatório, com os recortes que
  fazem sentido para ele — e não os da tela. O do **Dashboard** pergunta
  categorias, faixa de ICE, situação do registro ANVISA, "só com documento
  atrasado", "só sem responsável" e a ordem da worklist; o do **IDP** pergunta
  classe ABC, categorias, faixa de IDP, **em qual das 6 revisões há pendência**
  e a ordem da matriz. Todos os grupos são de seleção múltipla: a tela oferece
  um valor por vez ("classe A" ou "todas") e um relatório costuma querer "A e
  B", "só o que tem registro vencido", "só o que está parado em IT".
- **Adicionado** contador de prévia que recalcula a cada clique
  (`N equipamento(s) no relatório`) e desabilita o botão quando a combinação não
  seleciona ninguém — o erro aparece antes de gerar, não depois.
- **Alterado:** os grupos abrem semeados com o que está selecionado na tela, mas
  a partir daí é o modal que manda; o PDF não lê mais os selects da página, para
  não haver dois filtros somados sem ninguém perceber. A regra de cada grupo é
  literal (vale o que está marcado, e desmarcar tudo dá zero) com uma exceção
  declarada na própria tela: em "revisão pendente em", vazio não restringe,
  porque ali o grupo acrescenta uma condição em vez de definir o escopo.
- `riscoLinhas()` saiu de dentro de `renderRisco()` para o relatório imprimir as
  mesmas quatro linhas de risco que a tela.
- Os dois botões seguem as convenções fixadas em **Exportações — formato,
  filtros e permissão**: exigem **técnico pra cima** (o PDF é montado no
  navegador, então não há rota para barrar — o gate é o botão, escondido para o
  papel `leitura` como o resto das exportações da tela) e o arquivo sai **com
  data** (`DocTrack_Equipamentos_IDP_20260730.pdf`), senão gerar duas vezes
  sobrescrevia o anterior no Downloads.

### Cache-busting dos estáticos ignorava os JS/CSS dos módulos
- **Corrigido** `_static_version()`, que calculava o token a partir de uma
  **lista fixa de seis arquivos** (`app.js`, `auth.js`, `common.js`,
  `style.css`, `socket-client.js`, `app-realtime.js`). Nenhum módulo estava na
  lista: uma correção em `equipamentos.js`, `missoes.js`, `entregaveis.js`,
  `config.js` ou nos CSS deles saía com o mesmo `?v=`, e o navegador continuava
  servindo a versão antiga do cache até alguém dar Ctrl+F5. Agora varre
  `static/` (primeiro nível — `vendor/` é de terceiros e muda com o deploy).

### Diagnóstico de documentos — reescrito
O diagnóstico nasceu quando o arquivo só podia estar na rede e verificava uma
única coisa: se a string de caminho batia com algum diretório. Depois que os
arquivos passaram a ser hospedados na plataforma, ele passou a mentir.

- **Corrigido** o falso positivo que afetava todo documento hospedado na
  plataforma. O upload nunca preenche `armazenamento` — cria um
  `DocumentoArquivo` —, e o diagnóstico olhava só o caminho de rede: documento
  com o PDF anexado era reportado como "sem local de armazenamento". Agora as
  duas fontes são confrontadas e **ter uma das duas basta**.
- **Adicionado** `ARQUIVO_SUMIDO`: blob referenciado pelo banco que não está
  mais em disco. Era o ponto cego que ninguém cobria — e é o risco que o próprio
  `arquivos_store` documenta (a pasta de arquivos dentro de `_internal\` é
  apagada no primeiro deploy). Agrupa por `sha256`, porque o store deduplica por
  conteúdo e um blob perdido derruba todos os documentos que o referenciam.
- **Adicionado** `PASTA_VAZIA`: a pasta existe e não tem nada dentro. Verificar
  só a existência do diretório nunca respondeu a pergunta que motivou a tela —
  "Homologado" no sistema não prova que alguém depositou o arquivo lá. Na
  primeira execução contra o share real apareceram 7 pastas `IT_Checklist`
  vazias.
- **Alterado** o peso de "sem arquivo": documento em elaboração ainda não ter
  arquivo é o curso normal das coisas (`info`); o que não fecha é o que consta
  como concluído e não tem arquivo em fonte alguma (`error`).
- **Alterado** os apontamentos, que agora vêm **agrupados pela causa**. A
  herança de pasta faz os 9 documentos de um equipamento compartilharem o mesmo
  caminho: uma pasta que sumiu era uma linha por documento, e um punhado de
  equipamentos quebrados enchia o relatório e escondia todo o resto. Medido no
  share real: 489 documentos, 194 afetados, **26 linhas**.
- **Corrigido** o custo de I/O. Cada consulta é um round-trip SMB e a versão
  anterior fazia até 4 por documento — inclusive sobre o mesmo diretório, dezenas
  de vezes. Agora cada caminho distinto é consultado uma vez (368 documentos com
  caminho → **33 consultas**, uma por árvore de equipamento).
- **Adicionado** orçamento de tempo (`DOCTRACK_DIAG_TIMEOUT`, 20s) e detecção de
  share fora do ar. Sem teto, o timeout SMB de centenas de caminhos deixava a
  rota pendurada; e com o share caído *todo* caminho responde "não existe" — a
  checagem de rede passa a ser descartada inteira, com aviso na tela, em vez de
  reportar centenas de pastas apagadas que estão lá.
- **Removido** o efeito colateral de um GET criar diretórios no servidor:
  `scan_documents` chamava `ensure_directory_structure()`, que montava a árvore
  `documentos/{Tecnico,Qualidade,Engenharia}/...` na raiz do app — estrutura
  legada, vazia, sem relação com o armazenamento real. E `get_directory_tree()`
  varria essa árvore para a rota descartar o resultado com um `pop`.
- **Removido** `agente_scanner.py`, substituído por `diagnostico.py`. Fora as 20
  linhas que a rota usava, o módulo era código morto (`discover_files`,
  `save_discovery_report`, `run_scan`, `ScanResult`, `KEYWORD_MAP`) e a stat
  `diretorio_incorreto` nunca saía de zero porque nada a emitia. O novo módulo
  recebe dicts em vez de models: o confronto com o filesystem é testável sem
  banco (`tests/test_diagnostico.py`).

### Audit Log — exportação em PDF
- **Corrigido** o botão **PDF** do relatório de auditoria, que não gerava nada.
  `templates/audit_log_report.html` era o último arquivo do projeto ainda
  carregando biblioteca de CDN (`cdnjs.cloudflare.com/.../jspdf.umd.min.js`), e a
  CSP do app é `script-src 'self'` — justamente porque ele roda em rede fabril
  que pode não ter saída externa. O navegador bloqueava o script, `window.jspdf`
  ficava `undefined` e `exportPDF()` parava na linha de guarda. Passa a usar
  `/static/vendor/jspdf.umd.min.js`, a **mesma versão 2.5.1** que já é servida em
  `dashboard.html` e `entregaveis.html`.
- **Corrigido** a data do PDF gerado, fixa em `26/05/2026`. A substituição
  server-side casa `exportado em` minúsculo e não alcançava o `Exportado em` do
  bloco JavaScript; agora a data é calculada em runtime.
- **Removido** o CSS de ícones Tabler (também CDN, também bloqueado pela CSP: os
  ícones nunca chegaram a aparecer) e o markup que dependia dele. O botão de
  limpar datas, que era um "×" invisível seguido de "Datas", passa a dizer
  "Limpar datas".

### Integridade das entregas acima (varredura)
- **Corrigido** `PATCH /api/documentos/<id>` com `pasta_id` não numérico: o
  `int()` cru levantava `ValueError` não tratado e devolvia 500. Agora responde
  400, o mesmo de uma pasta inexistente.
- **Corrigido** `DELETE /api/documentos/arquivos/<aid>`, que apagava a linha em
  vez de marcá-la inativa. O hard delete anulava três coisas do próprio
  desenho: o histórico prometido por `GET .../arquivos` (a linha sumia), o
  número de versão (apagar o v1 fazia o próximo envio voltar a ser v1) e a
  ordem segura de remoção (o blob saía do disco antes do commit, que é o caso
  que o soft delete existia para evitar). O blob agora só é apagado depois do
  commit e só quando nenhuma linha **ativa** ainda o referencia; a linha
  inativa deixa de ser baixável (404), inclusive quando o blob sobreviveu por
  dedup.
- **Corrigido** N+1 em `/api/equipamentos`: `Equipamento.to_dict()` serializa as
  pastas, e o backref estava em `lazy="select"` — uma consulta por equipamento
  da lista. Passa a `selectin`, como já era o caso em `DocumentoArquivo`.
- **Removido** o código morto deixado pela saída da seção "Pasta na rede" da aba
  do documento: o `saveTipoDoc` continuou lendo `et-pasta-*` e `et-arm-*`, que
  o painel já não renderiza (devolviam `undefined`, chave que o `JSON.stringify`
  descarta — sem efeito em produção, mas apontando para uma seção inexistente).
  Saíram junto os órfãos da mesma seção: `abrirArquivos` e a cadeia dela
  (`renderArquivosLista`, `abrirArquivo`, `_downloadArquivo`, `visualizarDocx`),
  o modal `modal-arquivos` e as regras `.arm-hint`, `.armazenamento-row` e
  `.arquivo-acao`. A resolução de caminho em 3 níveis segue no backend e a
  gestão de pastas, na ficha do equipamento.
- **Corrigido** `documentos.pasta_id` sem índice em banco já existente: o
  `_sync_schema` adicionava a coluna mas não estava na lista de índices novos.
- Removido um ramo inalcançável na subida por ancestral de
  `/api/documentos/abrir-pasta` (repetia um teste que já havia falhado).

### Arquivos hospedados na plataforma
- **Novo** upload de arquivos direto no DocTrack: cada documento comporta
  **vários arquivos convivendo** (manual PT e ES, IT e checklist), visualizáveis
  dentro da plataforma. São **cópias de conveniência** — o mestre continua no
  servidor da engenharia e a Qualidade mantém o sistema dela; por isso autor e
  data de envio ficam sempre visíveis na linha do arquivo (não há sincronização
  com o mestre, e é essa informação que impede alguém ler cópia velha sem saber).
- **Novo** `DocumentoArquivo` (tabela `documento_arquivos`) + módulo
  `arquivos_store.py`: blob **endereçado por conteúdo** (nome em disco =
  SHA-256), o que elimina path traversal por construção, deduplica conteúdo
  idêntico e nunca deixa parcial de upload com nome válido (grava em `_tmp` e
  move). Allowlist de extensão (pdf/office/imagem) e teto de upload
  (`DOCTRACK_UPLOAD_MAX_MB`, padrão 80 MB) — antes o app não tinha
  `MAX_CONTENT_LENGTH` nenhum.
- **Novo** API: `GET/POST /api/documentos/<id>/arquivos`,
  `GET /api/documentos/arquivos/<aid>/conteudo` (inline para PDF/imagem,
  `?download=1` força download) e `DELETE /api/documentos/arquivos/<aid>`.
  Adicionar/remover é de **admin+gestor** (a hierarquia já existente); ler e
  baixar é de qualquer autenticado — quem acessa o DocTrack já acessa as pastas
  de rede, restringir download seria teatro. Upload e remoção auditados
  (`UPLOAD`/`DELETE` no AuditLog).
- Aba do documento reorganizada: a seção **Pasta na rede** (seletor de pasta +
  caminho + "Ver arquivos") saiu da aba — os arquivos da plataforma assumem o
  papel; a resolução de caminhos em 3 níveis continua no backend e na ficha do
  equipamento. Ações do arquivo em botões próprios (Visualizar/Baixar/Remover)
  e visor embutido no modal existente (iframe para PDF/imagem, render
  client-side para .docx).
- `X-Frame-Options` de `DENY` para `SAMEORIGIN` + `frame-ancestors 'self'` no
  CSP: o visor enquadra o próprio endpoint de conteúdo em `<iframe>`, e DENY
  bloqueia até em mesma origem; contra clickjacking de terceiros, SAMEORIGIN
  protege igual.
- `scripts/gerar_backup.ps1` agora espelha a pasta de arquivos
  (`DOCTRACK_ARQUIVOS`) junto do `pg_dump` — banco sem os blobs aponta para
  arquivos inexistentes, e blobs sem o banco são hashes sem significado. O
  espelho é cumulativo (blob nunca muda de conteúdo, então nunca precisa ser
  apagado). `.gitignore` cobre `arquivos/` (dados, não código).

### Pastas por grupo de documentos
- **Novo** `EquipamentoPasta`: cada equipamento declara as SUAS pastas de rede
  (nome livre + caminho completo) e cada documento aponta para uma delas. A
  estrutura real separa manuais, IT/checklists e QI/QO/QD em pastas diferentes,
  com caminhos que variam por produto — algo que o modelo anterior, de dois
  níveis (pasta do equipamento × exceção por documento), só expressava marcando
  uma "exceção" em cada documento do grupo.
- `Documento.armazenamento_efetivo` passa a resolver em três níveis: exceção do
  documento → pasta do grupo → caminho do equipamento. `armazenamento_origem`
  acompanha dizendo qual dos três venceu, para que consumir a API não exija
  reimplementar a precedência — nem confundir com exceção o manual que está na
  pasta de manuais, que é a regra.
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
- Limpar o campo `armazenamento` de um documento passa a devolvê-lo à pasta do
  grupo dele. Antes o caminho do equipamento era copiado para o campo,
  ignorando a pasta e mandando o documento para o lugar errado.

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
