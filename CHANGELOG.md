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

### Correções da Análise de Riscos exigidas antes da QO
A Análise de Riscos da validação (guia ANVISA) marcou estes pontos para
corrigir antes da qualificação de operação. Nenhum deles dependia de decisão
de política da área usuária.

- **Alterado (R-05)** o administrador não define mais a senha de ninguém.
  `POST /api/users` e `PATCH /api/users/<id>` recusam o campo `senha` (400, e a
  edição não aplica nenhum dos outros campos); criar a conta sempre gera código
  de ativação, e trocar a senha é o Resetar senha. A tela de usuários perdeu os
  dois campos de senha. Antes, a senha definida pelo admin era conhecida por
  ele, e as ações da conta deixavam de ser atribuíveis só ao dono.
- **Adicionado (R-06)** o 403 de perfil ou área vai para a trilha como
  `ACESSO_NEGADO`, com e-mail, método + rota, motivo e IP: `require_role`,
  `require_area`, o cadastro de outro usuário, os gates de Cadernos (inclusive o
  404 que esconde um caderno sem acesso) e o gate de dono de Tempos. Uma linha
  por (usuário, rota) a cada 10 minutos, com a rota pela regra do Flask — o
  front provoca esse 403 no uso normal, e uma varredura de ids não multiplica
  linhas. A resposta ao cliente não mudou.
- **Corrigido (R-26)** remover um arquivo de documento ou um anexo de
  equipamento não apaga mais o conteúdo do disco. A linha fica inativa (some da
  tela e não é mais servida) e o blob permanece enquanto houver linha, ativa ou
  inativa, que o referencie. Antes, sem outra referência, o blob era apagado e a
  evidência só voltava pelo backup. Nos Cadernos, a linha na lixeira também
  segura o blob (ainda pode ser restaurada); a purga continua como estava.
- **Alterado (R-50)** exportar caderno exige papel de **editor** no caderno
  (`PAPEL_EXPORTAR`): prévia, gerar e baixar o zip. Antes bastava ler, e o
  perfil leitura exportava. O histórico das exportações continua aberto a quem
  lê o caderno, e a tela só oferece exportar a quem pode.
- **Corrigido (R-46)** desativar, excluir ou mudar o perfil de um usuário corta
  o acesso na hora. Toda requisição autenticada confere no banco que a conta
  existe e está ativa, e o access token com perfil diferente do atual é
  recusado (o front renova pelo refresh e recebe o perfil novo, sem novo
  login). As conexões de tempo real abertas da conta caem junto. Antes, o
  perfil vinha só do JWT, e uma conta desativada seguia com acesso por até
  1 hora.

### Correções de uma varredura geral (SVG, índices, agendador, CRLF, threads)
Uma varredura do app inteiro (lint, rotas, chamadas do front, templates, schema
e logs da produção) não achou nada quebrado, mas achou estes cinco pontos.

- **Corrigido** `.svg` das pastas de rede não abre mais inline em
  `/api/documentos/arquivo`: SVG é documento ativo, e o `<script>` dele rodaria
  na origem do DocTrack com acesso ao token. Desce como download, como já
  faziam os arquivos hospedados e os Cadernos.
- **Corrigido** o `_sync_schema` cria **todo** índice não-UNIQUE do modelo que
  falte numa tabela existente, em vez de uma lista mantida à mão. A lista tinha
  envelhecido: `entregaveis.modelo_chave` e `modelos_entregavel.chave` (migration
  020) ficavam sem índice no PostgreSQL, onde as migrations SQLite não rodam.
  Índice que já existe com outro nome nas mesmas colunas não é duplicado.
- **Corrigido** as tarefas diárias rodavam duas vezes no dia da subida: o
  `init_app` as rodava e a primeira checagem do agendador, 15 min depois, de
  novo. O `init_app` agora marca o dia como feito.
- **Corrigido** `test_docs_sincronia` falhava no Windows com o conteúdo idêntico
  (checkout em CRLF por `core.autocrlf`). Novo `.gitattributes` fixa LF em
  `docs/referencia/`.
- **Adicionado** `--threads=32` no `deploy_windows.ps1` e no RUNBOOK. Só com
  polling, cada aba aberta segura uma thread do waitress, e o padrão é 4 — o
  `err.log` da produção já mostrava `Task queue depth`.

### Tempo real sem WebSocket sob o waitress (err.log de 817 MB)
O waitress da produção não faz WebSocket, mas todo cliente abria o Socket.IO
pedindo websocket primeiro: cada aba aberta gerava um traceback
(`Cannot obtain socket from WSGI environment`) no `err.log` antes de cair para
polling. O log da produção chegou a 817 MB disso.

- **Corrigido** o servidor detecta o waitress e passa a aceitar só polling, sem
  anunciar upgrade; pedido de websocket recebe 400, sem traceback. No
  `python servidor.py` e no gunicorn o WebSocket continua. `DOCTRACK_WEBSOCKET`
  força a decisão.
- **Corrigido** os quatro clientes (Projetos, Missões, PDR e o
  `socket-client.js`) começam por polling e só sobem para WebSocket quando o
  servidor anuncia.
- **Adicionado** rotação dos logs do serviço NSSM no `deploy_windows.ps1` (10 MB)
  e, no RUNBOOK, como ligá-la num serviço já instalado.

### Projetos: a prévia de "Aplicar aos projetos" só propõe o que é novo
Na produção, a primeira prévia propôs criar ~1.760 entregáveis que ninguém
tinha pedido: a ligação dos entregáveis antigos exigia nome e categoria iguais
(e os modelos do PDR tinham mudado itens de categoria), e item do modelo que o
projeto não tinha parecia novo mesmo quando o projeto nunca o teve.

- **Corrigido** os entregáveis antigos casam com o modelo pelo nome, ignorando
  categoria, acento e maiúsculas; categoria e nome do projeto ficam.
- **Adicionado** `projetos.modelo_conhecidos` (migration 021): os itens do
  modelo que o projeto já conhecia ao nascer ou na última aplicação. A prévia
  só propõe criar ou vincular o que entrou no modelo depois — o item tirado de
  propósito da lista ao criar o projeto não volta.

### Documentação técnica: quatro camadas, e a metade que se gera sozinha
O sistema tinha documentação farta de *decisão* — planos, specs, um CHANGELOG de
36 KB, docstrings que explicam por que cada coisa é assim — e nenhuma de
*estado*. Dava para descobrir por que uma escolha foi feita em junho, mas não o
que o sistema é hoje sem ler 30 mil linhas de Python.

- **Adicionado** `docs/referencia/` — **gerado do código** por
  `scripts/gerar_docs.py`: as 212 rotas com método e papel exigido, o dicionário
  das 43 tabelas (497 colunas) com os comentários de domínio do próprio
  `models.py` e diagramas ER por domínio, a matriz papel × rota, e o inventário
  de variáveis de ambiente. Nada aqui é escrito à mão.
- **Adicionado** `tests/test_docs_sincronia.py`, que roda o gerador e **quebra a
  suíte** se a referência estiver defasada. Foi a ausência disso que produziu os
  quatro guias de implantação divergentes e a tabela do README mandando rodar um
  script de backup já removido. Inclui um teste que trava a superfície pública
  em seis rotas — uma sétima rota aberta passa a ser decisão consciente, não
  acidente — e um verificador de links internos.
- **Adicionado** `docs/arquitetura/` — visão geral com os diagramas de contexto,
  processo e requisição; `EVENTOS.md` com as rooms e o ciclo de replay; e **10
  ADRs** retroativos para as decisões que continuam governando o sistema:
  caminho-no-banco, schema no startup, o event bus, página-casca, rate limit em
  memória, kill switch, PDF no navegador, agendador embutido, blob por conteúdo
  e o monólito modular.
- **Adicionado** `docs/operacao/RUNBOOK.md` — subir, publicar, voltar atrás,
  restaurar, destravar, e uma tabela de sintoma → causa → o que fazer. O que
  estava espalhado por quatro guias.
- **Adicionado** `docs/funcional/` — um documento por módulo com as regras de
  negócio e as máquinas de estado. É a camada que não sai do código nem dos
  planos: os planos dizem o que *ia* ser feito, não o que ficou.
- **Corrigido** o README, que anunciava **9 tipos** de documento desde antes de
  a reestruturação levar para 12 (5 do PRE + 7 de Manuais). O número certo já
  estava no código e num comentário de `equipamentos_core.py`, que corrigira o
  denominador do ICE justamente por causa disso.
- **Documentado**, como efeito colateral do inventário de configuração, que
  **23 variáveis de ambiente** que o código lê não estão no `.env.example` —
  entre elas `DOCTRACK_AGENDADOR`, `DOCTRACK_AUDIT_RETENCAO_DIAS` e os quatro
  limites de tentativa de `ratelimit.py`. Listadas em
  `docs/referencia/config.md`; fechar a lista fica para outra rodada.

### Ambiente de demonstração no Render
- **Adicionado** `render.yaml`: instância pública de amostra com Postgres
  descartável, separada do servidor interno.
- **Adicionado** `scripts/seed_demo.py`: preenche Entregáveis, Missões e
  Consumíveis, que sobem vazios num banco novo. Idempotente; só roda na demo.
- **Adicionado** `.python-version` (o Render usa para escolher o Python).

### Celular: a navegação que faltava e os botões que estavam fora da tela
Segundo passe de celular, medido no navegador a 375px tela por tela — as sete
páginas do app, cada aba e cada modal. O primeiro passe (abaixo) arrumou a
página; este arruma os **controles**, e o que ele encontrou não era acabamento.

- **Corrigido** a gaveta lateral em **Tempos**, **Custos** e **PDR**, onde ela
  nunca abriu. A gaveta é declarada em template e ligada em JavaScript, e as duas
  metades moravam em arquivos diferentes: Tempos e Custos tinham o ☰ na tela sem
  nada por trás dele, e o PDR — que tem `<head>` e corpo próprios — tinha a
  `<nav>` e o CSS do botão, mas nunca o botão. No aparelho os três módulos eram
  becos sem saída: sem navegação, sem "Voltar aos módulos", sem "Sair".
- **Corrigido** a gaveta de **Equipamentos** e **Missões**, que abria e não
  fechava ao tocar num item — ficava cobrindo a página que o toque acabara de
  trocar.
- **Adicionado** `static/nav-mobile.js`, dono único da gaveta, carregado por
  `_pwa_head.html` (o único parcial que alcança as sete páginas: o PDR não
  carrega `common.js`). Substitui **quatro** cópias da mesma função, que já
  tinham divergido. Fecha por delegação de evento, e não item a item no
  carregamento: em Missões os itens da gaveta **são** as missões e nascem depois
  do fetch, então a versão antiga nunca ligava nenhum deles.
- **Corrigido** cinco barras de ação que não quebram linha. Como a trava de
  `overflow-x:hidden` do primeiro passe recorta o que passa da borda, o botão
  não ficava feio — ficava **inalcançável**. Medido, botão a botão: "+ Novo
  equipamento" terminava em 476px numa tela de 375; "Resetar senha", "Desativar"
  e "Excluir" de **toda** linha de usuário, entre 464 e 622px; "Fechar" e
  "Editar" da ficha do equipamento; a aba "Modelos" de Projetos; e seis dos sete
  botões da missão na barra do topo, o último em 695px.
- **Corrigido** a folha inferior dos **dezenove** modais que nascem com
  `style="max-width:96vw"` no HTML: estilo inline vence seletor, então a folha
  ficava com 7,5px de sobra de cada lado e os cantos arredondados de cima
  flutuando longe da borda.
- **Corrigido** os alvos de toque do rodapé do hub e do sub-hub — 16px de altura,
  e são os únicos controles das duas telas de entrada do sistema.
- **Adicionado** `tests/test_nav_mobile.py` (8 testes): um exige o botão e o
  fundo escuro no HTML de toda página que tem gaveta, o outro exige que quem os
  liga continue sendo um só. `tests/test_pwa.py` passou a cobrir também
  `/custos`, `/tempos` e `/pdr`, que faltavam na lista.

### Acesso de fora da Loccus: túnel do Cloudflare e app de celular (PWA)
O DocTrack só existia dentro da rede: `waitress` em `http://<ip>:5000`, sem TLS.
A opção óbvia — subir uma cópia para a nuvem — está descartada pelo próprio
código: o banco guarda o **caminho** dos documentos, e os arquivos vivem em
`\\loccus-srv03\Projetos$\Engenharia` (ver `caminhos.py`). Uma cópia hospedada
fora não abre um único documento. Então o que viaja é a conexão, não a
aplicação: o servidor continua exatamente onde está.

- **Adicionado** `scripts/setup_cloudflared.ps1` — instala o `cloudflared` como
  serviço do Windows e confere o `.env` antes de publicar. A conexão é de
  **saída**: nenhuma porta de entrada aberta na borda, nenhum IP público. O
  script **não baixa** o binário de propósito; ele verifica e instrui.
- **Adicionado** build PWA: `manifest.webmanifest`, service worker, ícones,
  tela offline e o parcial `templates/_pwa_head.html`. O app instala na tela
  inicial do celular — mesmo deploy, sem loja, sem build separado.
- **Adicionado** `docs/ACESSO_REMOTO.md` com o caminho completo, e
  `tests/test_pwa.py` + `tests/test_acesso_remoto.py` (29 testes).

- **Corrigido** (segurança) o IP do cliente, agora em `utils.ip_do_cliente()`,
  fonte única para audit log, rate limit e kill switch. O `cloudflared` roda na
  **mesma máquina** que o app, então sem `TRUST_PROXY` toda requisição chega de
  `127.0.0.1` — e o dano não é o log impreciso. Os limites de `ratelimit.py` são
  **por IP**: fundidos num IP só, viram **globais**. `DOCTRACK_LIMITE_KILLSWITCH`
  é 3, então três tentativas erradas de **qualquer um** trancariam a rota de
  desbloqueio para **todos** — e num incidente real o atacante queima as três de
  propósito para impedir o administrador de destravar. Passa a ler
  `CF-Connecting-IP`, o único cabeçalho que sobrevive ao túnel: o `x_for=1` do
  ProxyFix lê a última entrada do `X-Forwarded-For`, que atrás da Cloudflare é o
  edge, não a pessoa. Sem `TRUST_PROXY` nada muda — cabeçalho continua ignorado.

- **Corrigido** a conversão de tabela em cartão no celular, que **nunca havia
  funcionado**. `style.css` transforma cada linha em cartão a partir de 780px,
  mas `table{min-width:1200px}` é global e `min-width` vence `max-width`: os
  cartões nasciam com 1200px dentro de um container de 345px, com 855px de cada
  um fora da tela. Medido no navegador, não deduzido.
- **Corrigido** as onze tabelas montadas em JS que ficam fora de `.tbl-wrap`
  (das doze do sistema, só a do dashboard tem o wrapper): estouravam a largura
  da página e faziam o corpo rolar na horizontal. Agora rolam dentro da própria
  caixa.
- **Corrigido** o zoom automático do iOS: `.form-input` (14px), `.search-input`
  (13px) e `.filter-sel` (12px) estavam abaixo dos 16px em que o Safari do
  iPhone dá zoom sozinho a cada toque num campo, e sai do zoom ao desfocar — a
  tela pulava a cada interação.
- **Corrigido** alvos de toque abaixo de 44px, a área segura do iPhone (entalhe
  e barra de gestos) no app instalado, e o modal, que ocupava 90% da largura com
  margem de topo e virava caixa espremida no celular — agora é folha inferior.

O service worker **não cacheia `/api/*`** em hipótese nenhuma, e nunca usa o
cache como reserva para resposta de **erro** do servidor (só para falha de
rede). É o que mantém a trava de emergência honesta: travado, tudo responde 423,
e um cache no caminho esconderia exatamente o que a trava existe para mostrar.
Ao ver um 423 o worker apaga o que tiver guardado. Verificado no navegador com o
sistema travado de verdade.

### Módulo Cadernos: cadernos de laboratório do PDR
Os cadernos de laboratório viviam no OneNote, com os arquivos dos testes
espalhados no SharePoint.

- **Adicionado** módulo Cadernos (`/cadernos`, aberto pela barra do PDR):
  cadernos → grupos de seções → seções → páginas, editor completo (CKEditor 5),
  versões de página, membros por caderno e lixeira com expurgo em 60 dias.
- **Adicionado** arquivos de qualquer extensão presos à página, à seção ou ao
  caderno, com versões, no mesmo blob store dos documentos.
- **Adicionado** importação dos cadernos do OneNote (scripts em
  `scripts/onenote/` e `scripts/importar_onenote.py`) e exportação para a
  liderança em `.zip` com relatório Word (`python-docx`).

### Auditoria: tentativas de acesso recusadas
A validação de sistema computadorizado exige registrar as tentativas de acesso
de quem não está autorizado. Só o login certo ia para `audit_logs`; a falha
ficava no contador em memória do limite de tentativas e sumia no reinício.

- **Adicionado** as ações `LOGIN_FALHA`, `ATIVACAO_FALHA`,
  `KILL_SWITCH_LOCK_FALHA` e `KILL_SWITCH_UNLOCK_FALHA`, com o e-mail digitado
  (mesmo sem conta), o IP e o motivo. O segredo digitado nunca é gravado, e a
  resposta ao cliente não muda.
- **Adicionado** `LOGIN_BLOQUEADO`, `ATIVACAO_BLOQUEADA` e
  `KILL_SWITCH_BLOQUEADO` para a tentativa barrada pelo limite (429) — uma
  linha por bloqueio, não uma por requisição.
- **Alterado** no primeiro acesso, e-mail sem pendência e código vencido passam
  a contar no limite de tentativas (antes só o código errado contava). A
  mensagem é a mesma; o que muda é que a varredura de e-mails nessa rota agora
  esbarra no 429.
- 403 de perfil/área e 401 de token vencido ficam fora, de propósito: ver
  [acesso-usuarios.md](docs/funcional/acesso-usuarios.md#tentativas-de-acesso-recusadas).
- **Adicionado** o IP de origem na tela de auditoria e no relatório exportado
  (lista, CSV, PDF e busca). Ele sempre foi gravado, mas `/api/audit` e o export
  não o devolviam.
- **Corrigido** injeção de script no relatório exportado. O relatório montava o
  HTML com os valores crus, e o export embutia o JSON num `<script>` sem escapar
  `<`. Com as tentativas recusadas, o e-mail digitado por quem nem tem conta
  passou a ir para a auditoria, e algo como `</script><script>…` rodaria no
  navegador do admin, numa página que leva o JWT na URL. Os valores agora são
  escapados nos dois lados.
- **Corrigido** as ações do kill switch (`KILL_SWITCH_*`) apareciam sob o
  módulo "Documentos" na tela de auditoria; agora ficam em "Sistema".
- **Removido** `models.ACOES_AUDIT`. Ninguém a lia, e ela tinha 18 das mais de
  50 ações que o sistema grava. Os eventos de tempo real já têm catálogo em
  `event_bus.EventType`, e uma terceira lista mantida à mão voltaria a
  desatualizar.

### Trava de emergência (kill switch)
Não havia como desligar o sistema. Numa suspeita de credencial vazada, as opções
eram derrubar o serviço no servidor (e perder o acesso à própria tela que mostra
o que aconteceu) ou desativar usuário por usuário — lento e incompleto, porque o
JWT já emitido continuava valendo até expirar.

- **Adicionado** gatilho externo `POST /api/kill-switch/lock`, autenticado por um
  token próprio no header `X-Kill-Token`. Não passa por login: quem precisa
  desligar pode estar sem acesso à conta, longe do servidor, ou justamente
  desconfiando de uma sessão ativa.
- **Adicionado** o efeito da trava: **toda** requisição responde `423` — API,
  páginas e WebSocket —, sem exceção por perfil. Nem admin entra, porque a
  hipótese que motiva a trava é a de que uma credencial legítima está nas mãos
  erradas. Seguem respondendo apenas as rotas do próprio kill switch e
  `/api/version`; se o health check travasse, o Render reiniciaria o serviço em
  laço e a trava viraria um ciclo de reboot.
- **Adicionado** desbloqueio por senha-mestra em `/travado`, que **encerra todas
  as sessões** abertas antes da trava (corte por `iat` ligado à blocklist do
  JWT). Sem isso, quem estivesse dentro no momento do incidente voltaria com o
  token intacto.
- **Adicionado** `scripts/kill_switch.py` (gera os hashes, dispara e libera) e a
  migration `014_kill_switch.py`. Os dois segredos moram em variável de ambiente
  como hash bcrypt, nunca no banco: se o motivo da trava for o banco
  comprometido, um segredo guardado nele não vale nada. Sem os dois configurados
  o gatilho recusa travar — travar sem senha de volta é destruir, não proteger.

### Módulo Tempos: apontamento de horas
O DocTrack sabia o que foi feito, mas não quanto custou em esforço: o peso do
entregável é estimativa e os dias de ciclo do cartão são tempo de calendário.

- **Adicionado** módulo Tempos (`/tempos`, técnico para cima): cronômetro
  (iniciar, pausar, retomar, parar) ou lançamento manual retroativo, amarrado a
  projeto, entregável, cartão de missão, equipamento ou tarefa livre.
- **Adicionado** widget global do cronômetro em todas as telas e "Apontar tempo"
  no projeto, no cartão de missão e na ficha do equipamento.
- **Adicionado** guarda diária que corta cronômetro esquecido no limite
  operacional (marcado para o dono corrigir) e índice único que impede dois
  cronômetros em curso para a mesma pessoa (migration 013).
- **Corrigido** `esc()` do front não escapava aspas: texto do usuário dentro de
  atributo (`title="..."`) permitia XSS armazenado.

### Projetos: aplicar mudanças do modelo aos projetos existentes
Editar um modelo só valia para projetos novos: os em andamento ficavam com a
lista antiga e não havia como atualizá-los sem refazer item por item.

- **Adicionado** botão **Aplicar aos projetos…** na aba Modelos (só admin):
  pop-up de controle de mudança com a prévia por projeto, escolha dos projetos,
  decisão caso a caso para item com andamento que saiu do modelo (apagar,
  manter como avulso ou N/A), motivo obrigatório e confirmação explícita.
- **Adicionado** comparação de três lados (origem × modelo × projeto): onde o
  projeto ajustou peso ou responsável, o valor do projeto é mantido.
- **Adicionado** histórico de aplicações por modelo (admin/gestor), com o
  antes/depois de cada projeto, e registro na auditoria.
- **Adicionado** vínculo entregável → item de modelo (`modelos_entregavel.chave`,
  `entregaveis.modelo_chave`/`modelo_origem`) e tabelas `mudancas_modelo` /
  `mudancas_modelo_itens` (migration 020; o servidor cria na subida e liga os
  entregáveis existentes pelo nome).
- **Corrigido** o "+ Novo projeto" perdia o peso dos itens do modelo: o projeto
  nascia com peso 1 em tudo.

### Projetos: ordem dos itens do modelo
Na aba Modelos, só as categorias tinham ↑/↓; os itens de cada modelo ficavam
na ordem em que foram cadastrados.

- **Adicionado** ↑/↓ em cada item do modelo, movendo dentro da mesma
  categoria (os itens das outras não saem do lugar). É a ordem que o projeto
  novo herda; projetos já criados não mudam.
- **Adicionado** rota `PUT /api/modelos/ordem` (admin/gestor), que recebe
  todos os itens do modelo na nova ordem.

### Projetos: categorias de entregável cadastráveis
As categorias (Produto, Sistema, Documentação, Capacitação, Marketing) eram
fixas no código. Não havia como criar uma nova.

- **Adicionado** admin/gestor criam categorias pela opção "+ Nova categoria…"
  no próprio seletor de categoria (novo entregável, entregáveis iniciais do
  projeto, itens de modelo). A categoria criada já fica escolhida.
- **Adicionado** card "Categorias de entregável" na aba Modelos: uso de cada
  uma, ordem (↑/↓, que é a ordem das abas no projeto), renomear (propaga para
  entregáveis e modelos sem contar como atualização) e excluir (só sem uso, e
  nunca a última).
- **Adicionado** tabela `categorias_entregavel` (migration 019; o servidor cria
  e semeia na subida, com as cinco padrão mais qualquer nome já em uso) e as
  rotas `/api/categorias-entregavel`. Entregável e item de modelo passam a
  recusar categoria fora do cadastro.

### Projetos: ordem dos entregáveis por arrasto
Os entregáveis apareciam na ordem em que foram cadastrados, sem como mudar.

- **Adicionado** admin/gestor arrastam um entregável para mudar a posição dele
  dentro da categoria, no modal do projeto e na ficha do Dashboard. No
  celular, o arrasto começa com um toque longo.
- **Adicionado** coluna `entregaveis.ordem` (migration 018; o servidor cria na
  subida) e a rota `PUT /api/projetos/<id>/entregaveis/ordem`. Entregáveis que
  já existem ficam na ordem de hoje; projeto novo herda a ordem do modelo.
- **Corrigido** recarregar o modal do projeto (depois de uma edição ou por
  tempo real) voltava sempre para a primeira aba.

### Projetos: exports pela situação, não pelo avanço
O PDF do portfólio decidia se um projeto estava concluído pelo avanço: só com
100%. Um projeto que o gestor deu como **Concluído** no campo Situação, com 99%,
aparecia como "em progresso".

- **Alterado** o relatório em PDF conta os projetos pela situação escolhida no
  projeto. Os KPIs passam a ser Concluídos e Em execução, e a rosca vira
  "Situação dos Projetos", com Planejado, Em execução, Suspenso, Concluído e
  Cancelado. O filtro "Concluídos (100%) / Pendentes (< 100%)" vira um filtro
  por situação, com a opção Abertos, e já abre com a situação filtrada na aba
  Projetos.
- **Adicionado** a coluna Situação no detalhamento do PDF, e a situação no
  cabeçalho da ficha em PDF de um projeto. O avanço % continua em sua coluna.
- **Alterado** no Excel, a coluna "Status" das abas principal e PMO passa a se
  chamar "Situação" e traz o rótulo da tela ("Em execução"), e não o código
  (`execucao`).

### Projetos unificados: PDE, PDR e INOV no mesmo módulo
Projetos só existia no hub do PDE. O gestor das três áreas precisava de uma
visão única, com um jeito de recortar por departamento. O que separa uma área da
outra passa a ser o **modelo** do projeto (`PDE RUO`, `PDE IVD`, `PDR RUO`,
`PDR IVD`, `INOV`…), que é o tipo de projeto cadastrável. Plano em
`docs/planos/PLANO_projetos_unificados.md`.

- **Adicionado** a área do modelo (`tipos_projeto.area`). A área do projeto vem
  do modelo, e não é guardada no projeto. Os tipos que já existem nascem `pde`.
  Não é obrigatório rodar `migrations/017_area_tipo_projeto.py`: a subida do
  servidor cria a coluna.
- **Adicionado** a área **INOV** (Inovação), com sub-hub e o card de Projetos.
  A sidebar do PDR ganhou um link para Projetos. Os três caminhos abrem a tela já
  filtrada pela área de origem (`/projetos?area=<slug>`).
- **Adicionado** um filtro de modelos acima das abas, que vale para Dashboard,
  PMO, Projetos, o sino de alertas e os exports (Excel e PDF). Os chips ficam
  agrupados por área: o da área marca todos os modelos dela, e dá para somar
  modelos de áreas diferentes (ex.: `PDE IVD` + `PDR IVD` = todos os IVD). A URL
  acompanha o filtro e a última escolha fica guardada no navegador.
- **Adicionado** a etiqueta do modelo, na cor da área, no card, na ficha, no
  modal do projeto e na lista de risco do PMO. O projeto antigo sem modelo
  aparece como "PDE · Sem modelo", tracejado.
- **Adicionado** `?tipo=` e `?area=` repetíveis em `/api/projetos`,
  `/api/projetos/alertas`, `/api/entregaveis/resumo` e `/api/entregaveis/export`.
  Alertas e resumo antes ignoravam qualquer filtro. O projeto sem modelo conta
  como PDE, e uma área sem nenhum modelo devolve vazio, e não o portfólio
  inteiro.
- **Adicionado** as colunas Modelo e Área nas três abas do Excel.
- **Alterado** projeto novo passa a exigir modelo, e um projeto que já tem
  modelo não pode voltar a ficar sem. O projeto antigo sem modelo continua
  editável. Na tela, "tipo" passa a se chamar "modelo". Criar e editar um
  modelo pede a área.
- **Não muda**: as permissões. O filtro recorta a visão, mas não controla
  acesso: gestor e admin continuam vendo tudo, e o técnico continua vendo só
  onde tem entregável atribuído.

### Projetos: tipos de projeto cadastráveis
Os tipos eram uma lista fixa no código (`OEM` e `Revenda`), repetida no Python,
no JavaScript e no HTML. Um terceiro tipo exigia mexer nos três e publicar.

- **Adicionado** o cadastro de tipos de projeto (tabela `tipos_projeto`). Na aba
  **Modelos** do módulo Projetos, admin e gestor criam (**+ Novo tipo**),
  renomeiam e excluem tipos; cada tipo tem o seu modelo de entregáveis. O
  formulário de projeto ganhou um atalho **+ novo tipo** ao lado do campo.
- **Adicionado** "copiar de" na criação: o tipo novo pode nascer com o modelo de
  entregáveis de um tipo existente, em vez de vazio.
- **Adicionado** `/api/tipos-projeto` (GET/POST/PUT/DELETE). Renomear propaga o
  nome para os projetos (inclusive arquivados) e para o modelo; excluir é
  recusado (409) enquanto houver projeto usando o tipo.
- **Adicionado** `migrations/016_tipos_projeto.py`. Não é obrigatório rodar: a
  subida do servidor cria a tabela e semeia `OEM`, `Revenda` e qualquer tipo já
  gravado em projetos ou modelos.
- **Alterado** editar um projeto cujo tipo não está no cadastro deixa de ser
  recusado quando o tipo não mudou — o formulário reenvia todos os campos.
- **Não muda** o `tipo` da composição no módulo Custos (`OEM`/`Revenda`), que
  decide se há NRE e é um conceito à parte.

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
