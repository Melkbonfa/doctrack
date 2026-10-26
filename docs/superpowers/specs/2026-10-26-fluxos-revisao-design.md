# Fluxos de revisão (escrita → diagramação → revisão) — design

Data: 2026-10-26
Módulos afetados: novo `fluxos/`, novo `notificacoes/`, Documentos, Projetos/Entregáveis

## Problema

Um manual hoje passa de mão em mão fora do sistema. A autora escreve o texto em
português e manda para o diagramador. Ele diagrama e devolve para a revisão. Se
houver apontamentos, o manual volta para a diagramação, e assim até aprovar. O
DocTrack enxerga só o começo e o fim (*Elaborar → Em andamento → Concluído*).
Ninguém sabe com quem o manual está, quantas voltas ele deu, nem qual PDF foi
revisado em cada rodada.

O que já existe e este design aproveita:

- O manual já é um `Documento` (Manual do Usuário PT/ES, Manual de Serviço, Guia
  de Instalação) com status, responsáveis, histórico e lock otimista.
- Arquivos endereçados por conteúdo em `arquivos_store` (ADR-0009), com
  allowlist e teto de 80 MB.
- `sincronizar_cartoes_documento` (missoes.py) move o cartão do kanban quando o
  status do documento muda.
- O tipo de evento `NOTIFICATION` já é roteado para `user:{id}` em
  `event_bus._resolve_rooms` — mas **nada o publica**. Não há caixa de entrada,
  e o toast só chega a quem está com a tela aberta.

## Decisões

| Questão | Decisão |
| --- | --- |
| Onde o fluxo se aplica | Em **documentos** e em **entregáveis** — um mecanismo só |
| Etapas | **Modelos de fluxo** cadastrados por admin/gestor |
| Apontamentos de revisão | **Comentário + arquivo** por passagem (o PDF marcado no Acrobat/Word) |
| Aviso | **Sino no DocTrack**, persistido no banco. E-mail e Teams ficam fora |
| Onde mora o código | Pacotes novos `fluxos/` e `notificacoes/` (ADR-0010) |
| Quem age | O responsável pela etapa atual. Admin/gestor podem agir **em nome de**, registrado |
| Fluxos ativos | **Um por documento/entregável**. Os anteriores ficam no histórico |
| Efeito no status | Iniciar → *em andamento*. Aprovar → *concluído*. O % do entregável não é tocado |

Alternativas descartadas:

- **Em cima do Missões** (quadro por modelo, cartão por manual, devolver = arrastar
  de volta). A coluna não tem dono, então "com quem está" seria ambíguo quando
  cada manual tem outra autora. Além disso, o cartão não tem anexos nem se liga a
  entregável, e o controle passaria da ficha do documento para um quadro com
  dezenas de cartões.
- **Estender `Documento` e `Entregavel` cada um por si.** A mesma máquina de
  estados ficaria escrita duas vezes, e as duas versões divergiriam.

## Conceitos

**Modelo de fluxo.** Define *papéis* e *etapas*. Exemplo, o modelo "Manual":

    papéis:  autor, diagramador (padrão: Marcos)
    etapas:  Escrita (autor, execução)
             → Diagramação (diagramador, execução)
             → Revisão (autor, revisão, devolve para Diagramação)

- Uma etapa de **execução** tem uma saída: *Enviar para <próxima>*, ou
  *Concluir* se for a última. Concluir é gravado como `enviar` sem etapa de
  destino e encerra o fluxo como `aprovado`.
- Uma etapa de **revisão** tem duas saídas: *Aprovar* (próxima etapa, ou fim se
  for a última) e *Devolver* (volta para `devolve_para`, padrão a etapa
  anterior, e soma 1 à rodada).
- Validação do modelo: pelo menos uma etapa; chaves únicas; todo papel citado
  existe; revisão nunca é a primeira etapa; `devolve_para` aponta para uma
  etapa **anterior**.

**Fluxo.** É a instância ligada a um documento ou entregável. Ao iniciar, o fluxo
**copia** as etapas do modelo. Editar o modelo depois não mexe nos fluxos em
andamento, a mesma regra de "editar o modelo não altera projetos já criados".
Cada papel recebe uma pessoa; o padrão do modelo vem pré-preenchido.

**Passagem.** Cada ação vira uma linha imutável: iniciar, enviar, aprovar,
devolver, reatribuir ou cancelar. A linha guarda de qual etapa para qual, a
rodada, o comentário, quem fez, em nome de quem e os arquivos. É a linha do
tempo do fluxo e a fonte de "tempo em cada etapa" e "quantas voltas deu".

## Ciclo (o caso Giullia/Marcos)

1. No Manual do Usuário PT do equipamento, alguém clica **Iniciar fluxo**,
   escolhe "Manual", confirma Giullia como autora e Marcos como diagramador e,
   se quiser, define um prazo. Etapa: Escrita, rodada 1.
   Giullia recebe *"É sua vez: Escrita"*.
2. Giullia anexa o .docx → **Enviar para Diagramação**. Marcos recebe *"É sua
   vez"*.
3. Marcos anexa o PDF → **Enviar para Revisão**. Giullia recebe *"É sua vez"*.
4. Giullia **devolve** (comentário obrigatório, PDF marcado opcional). O manual
   volta para a Diagramação na rodada 2, e Marcos recebe *"Voltou para você,
   rodada 2"*.
5. Os passos 3 e 4 se repetem até Giullia **aprovar**. O fluxo fica `aprovado`
   e todos os participantes recebem *"Aprovado"*.

## Modelo de dados

Só tabelas novas. Nenhuma coluna nova em tabela existente, então `create_all()`
basta e não há script em `migrations/`.

**`fluxo_modelos`**

| Coluna | Nota |
|---|---|
| `id`, `nome` (único sem diferenciar maiúsculas, ≤ 80), `descricao` | |
| `papeis` | JSON `[{chave, nome, padrao_user_id}]` |
| `etapas` | JSON `[{chave, nome, papel, tipo: execucao\|revisao, devolve_para}]` |
| `ativo` | arquivar em vez de excluir. Modelo com fluxo não se exclui |
| `criado_em/por`, `atualizado_em/por` | |

JSON e não tabela filha: são poucas linhas, editadas sempre juntas e copiadas
inteiras para a instância. Ninguém consulta "fluxos cuja etapa 2 é X". Mesmo
racional de `projetos.modelo_conhecidos`.

**`fluxos`**

| Coluna | Nota |
|---|---|
| `ref_tipo` (`documento`\|`entregavel`) + `ref_id` | vínculo tipado sem FK rígida, como `MissaoCartao` e `Apontamento` |
| `modelo_id` (FK), `modelo_nome` | o nome fica congelado |
| `titulo` | congelado: "Manual do Usuário PT · Analisador X1" |
| `etapas` | JSON copiado do modelo |
| `etapa_atual` | chave da etapa |
| `status` | `andamento` · `aprovado` · `cancelado` |
| `rodada` | começa em 1 e soma a cada devolução |
| `prazo` | `Date`, opcional |
| `iniciado_por_id` (FK users), `iniciado_em`, `entrou_etapa_em`, `concluido_em` | |
| `versao` | lock otimista; versão velha → 409 |

Índice **parcial único** `(ref_tipo, ref_id) WHERE status='andamento'`, com
`sqlite_where` **e** `postgresql_where` (mesma armadilha documentada em
`tempos/models.py`). É o banco que garante um fluxo ativo por item.

**`fluxo_participantes`** — `fluxo_id`, `papel`, `user_id` (FK). Único em
`(fluxo_id, papel)`.

**`fluxo_passagens`** — `fluxo_id`, `acao`, `de_etapa`, `para_etapa`, `rodada`,
`comentario`, `por_id` (FK), `em_nome_de_id` (FK, nulo quando a própria pessoa
agiu), `em`.

**`fluxo_arquivos`** — `passagem_id`, `sha256`, `nome_original`, `ext`, `mime`,
`tamanho`. São **imutáveis**: fazem parte do registro da rodada. Arquivo errado
se corrige na passagem seguinte.

**`notificacoes`** (pacote `notificacoes/`, genérico)

| Coluna | Nota |
|---|---|
| `user_id` | FK, `ondelete=CASCADE` (mesmo motivo de `tempo_apontamentos`) |
| `tipo` | `acao` (é sua vez) · `info` (andamento) |
| `titulo`, `texto`, `link` | o link é relativo e abre o item |
| `origem_tipo`, `origem_id` | `fluxo` + id |
| `criada_em`, `lida_em` | `lida_em` nulo = não lida |

Índice `(user_id, lida_em, criada_em)`. A tarefa diária do agendador apaga as
**lidas** com mais de 90 dias.

## Regras

**Quem pode agir.** Enviar, aprovar e devolver: o participante do papel da etapa
atual, ou admin/gestor (grava `em_nome_de_id` = o responsável). Reatribuir e
cancelar: admin, gestor ou quem iniciou, com motivo obrigatório. Iniciar e ver:
técnico para cima. `leitura` recebe 403 e o painel fica escondido, como no
Missões.

**Quem vê um fluxo de entregável.** Admin/gestor, os participantes e o técnico
que já enxerga aquele projeto no modo restrito. Um participante sempre vê o
fluxo do qual participa.

**Arquivos.** Allowlist `EXT_PERMITIDAS` e teto `MAX_MB`, as mesmas dos
documentos. O arquivo-fonte do InDesign continua no share (ADR-0001): o que se
revisa é o PDF. Enviar sem anexo é permitido, mas a tela pede confirmação.

**Devolver exige comentário.** Os outros comentários são opcionais.

**Concorrência.** Toda ação manda a `versao`. Se não bater, a resposta é 409 com
o fluxo atual, e a tela redesenha.

**Transação.** Passagem, arquivos, troca de etapa, sincronização de status e
notificações entram num commit só. Os eventos saem depois do commit, como em
`update_status`. O blob é gravado antes do commit; um blob órfão é inofensivo
porque o nome vem do conteúdo.

### Sincronização de status

Para isso sair do mesmo caminho da tela, a lógica de troca de status é extraída
para funções reutilizáveis. O fluxo nunca grava `status` direto.

- **Documentos.** De `documentos.update_status` sai
  `aplicar_status_documento(doc, novo, caller)`: histórico, marcos temporais,
  `sincronizar_cartoes_documento` e eventos. A rota passa a usá-la também.
  - Setor **Manuais/PDE**: iniciar leva *Elaborar → Em andamento*. Aprovar leva
    para *Concluído*. O cartão do kanban vem junto pela sincronização que já
    existe.
  - Setor **PRE**: não é tocado. O pipeline dele tem marcos externos
    (treinamento, homologação) que o fluxo não conhece.
  - Na aprovação, os arquivos da **última passagem de execução** entram em
    `documento_arquivos` (próximo número de versão, mesmo `sha256`, sem cópia em
    disco), com a observação "Aprovado no fluxo #N, rodada R".
- **Entregáveis.** De `entregaveis.py` sai o equivalente, com
  `EntregavelHistorico`. Iniciar leva *pendente → em_progresso*. Aprovar leva
  para *concluído*, com `data_conclusao` = hoje se estiver vazia. Entregável
  `na` não inicia fluxo. Nada disso conta como "mexer no projeto" para o alerta
  de projeto parado (o histórico registra quem e quando).
- **Cancelar** não mexe no status.

### Proteções no que já existe

- Marcar um documento como N/A, ou excluí-lo, com fluxo ativo → **409**:
  *"há um fluxo em andamento; cancele antes"*. O mesmo vale para excluir um
  entregável.
- `modelo_sync.tem_andamento` passa a contar fluxo ativo. Assim, "Aplicar o
  modelo aos projetos" nunca apaga em silêncio um entregável que está em
  revisão.
- Responsável desativado: o fluxo não para sozinho. A lista "Em andamento"
  sinaliza *responsável inativo* e o gestor reatribui.

## Notificações

Em cada passagem:

- quem passa a ter a etapa recebe `acao`: *"É sua vez: Revisão — Manual do
  Usuário PT · Analisador X1"* (ou *"Voltou para você — rodada 2"*);
- os outros participantes e quem iniciou recebem `info`: *"Marcos enviou para
  Revisão"*;
- quem agiu não recebe nada sobre a própria ação, e cada pessoa recebe no máximo
  uma notificação por passagem (Giullia tem dois papéis no modelo "Manual").

Entrega: grava a linha em `notificacoes` e publica `NOTIFICATION` para
`target_user_id` via `publish_event`. Quem está com uma tela de socket aberta vê
o toast na hora. Para todo o resto, o sino consulta a contagem.

## Telas

**Sino (global).** `static/notificacoes-widget.js` + `.css`, injetado por JS como
o cronômetro e incluído **fora** de blocos Jinja em `base.html`,
`entregaveis.html`, `hub.html` e `subhub.html` (as armadilhas registradas em
PLANO_modulo_tempos.md valem aqui). Mostra um badge com as não lidas. A
contagem é consultada ao carregar, a cada 60 s e quando a aba volta ao foco.
O painel tem duas partes:

- **Com você agora** — fluxos cuja etapa atual é sua (`/fluxos/api/comigo`). É o
  estado vivo, não depende de notificação.
- **Avisos** — as notificações. Clicar marca como lida e abre o link. Há também
  "Marcar todas como lidas".

**Painel do fluxo (componente único).** `static/fluxos-painel.js` expõe
`DT_FLUXO.montar(host, {ref_tipo, ref_id, titulo})`, usado nas duas telas:

- sem fluxo ativo: botão **Iniciar fluxo** (modelo, pessoas por papel, prazo) e
  a lista recolhida dos fluxos anteriores;
- com fluxo ativo: as etapas em sequência, com a atual destacada, o responsável e
  "há N dias", o selo da rodada, os botões da ação de quem pode agir (comentário
  + arquivos) e a linha do tempo das passagens com os anexos (PDF e imagem abrem
  inline, .docx pelo visualizador que já existe).

**Documentos.** Nova seção **Fluxo** no `renderTipoPanel` (app.js), entre
Arquivos e Missões vinculadas. O link `/?doc=<id>` já abre o documento e é o que
vai na notificação.

**Projetos.**
- Na linha do entregável, um chip *"Diagramação · Marcos · R2"*. Vem de uma
  chamada em lote (`por-refs`) ao abrir o projeto.
- No popover do entregável, a seção Fluxo.
- Entra aqui o deep-link `/projetos?projeto=<id>&entregavel=<id>`, que abre o
  modal e o popover. É o item A1 do levantamento de ligação entre módulos e é o
  link da notificação.

**Página `/fluxos/`.** Card nos hubs PDE e Inovação, papel técnico. Duas abas:

- **Em andamento** (técnico+): item, etapa, com quem, há quantos dias, rodada,
  prazo, sinal de atraso e de responsável inativo.
- **Modelos** (admin/gestor): criar, editar, arquivar e ordenar etapas.

Um modelo "Manual (escrita → diagramação → revisão)" é semeado se não houver
nenhum.

## API

Montada em `/fluxos`:

    GET    /fluxos/                                página (casca)
    GET    /fluxos/api/modelos                     técnico+ (lista ativos)
    POST   /fluxos/api/modelos                     admin, gestor
    PUT    /fluxos/api/modelos/<id>                admin, gestor
    DELETE /fluxos/api/modelos/<id>                admin, gestor (arquiva)
    GET    /fluxos/api/por-ref?ref_tipo=&ref_id=   ativo + anteriores
    GET    /fluxos/api/por-refs?ref_tipo=&ids=     resumo em lote (chips)
    GET    /fluxos/api/em-andamento                lista da página
    GET    /fluxos/api/comigo                      o que espera por mim
    POST   /fluxos/api/fluxos                      iniciar
    GET    /fluxos/api/fluxos/<id>                 detalhe + passagens + arquivos
    POST   /fluxos/api/fluxos/<id>/acao            multipart: acao, comentario, versao, arquivos[]
    POST   /fluxos/api/fluxos/<id>/reatribuir      {papel, user_id, motivo, versao}
    POST   /fluxos/api/fluxos/<id>/cancelar        {motivo, versao}
    GET    /fluxos/api/arquivos/<id>/conteudo      inline se visualizável

    GET    /api/notificacoes?nao_lidas=&limite=    as minhas
    GET    /api/notificacoes/contagem              {nao_lidas}
    POST   /api/notificacoes/<id>/lida             só a própria (a de outra pessoa → 404)
    POST   /api/notificacoes/lidas                 todas as minhas

Todas as rotas de API são autenticadas. As seis rotas públicas de
`test_rotas_publicas_sao_as_esperadas` continuam sendo seis.

Eventos novos em `event_bus.EventType`: `FLUXO_INICIADO`, `FLUXO_MOVIDO`,
`FLUXO_CONCLUIDO` e `FLUXO_CANCELADO`, roteados para `role:gestor` +
`role:tecnico`, como os do Missões.

## Código

    notificacoes/  __init__.py · models.py · core.py (notificar) · routes.py
    fluxos/        __init__.py · models.py · core.py (máquina de estados pura)
                   routes.py · templates/fluxos/dashboard.html
    static/        notificacoes-widget.js/.css · fluxos-painel.js/.css · fluxos.js

`fluxos/core.py` não importa Flask. Validação do modelo, próxima etapa, quem
pode agir e quem notificar são funções puras, testáveis sem banco.

## Testes

- `tests/test_fluxos_core.py`: validação do modelo; enviar, aprovar e devolver;
  a rodada sobe só ao devolver; concluir na última etapa; `devolve_para`; quem
  pode agir; deduplicação de destinatários.
- `tests/test_fluxos_api.py`:
  - iniciar em documento e em entregável; segundo fluxo ativo → 409; técnico
    não participante → 403; gestor em nome de → grava `em_nome_de_id`; versão
    velha → 409;
  - extensão → 415; tamanho → 413; devolver sem comentário → 400;
  - notificações para as pessoas certas e nada para quem agiu; `comigo`;
  - documento Manuais sincroniza e o cartão vinculado se move; documento PRE não
    é tocado; aprovar copia os arquivos para `documento_arquivos`;
  - N/A e exclusão bloqueados com fluxo ativo; `tem_andamento` com fluxo;
    `leitura` → 403.
- `tests/test_notificacoes.py`: listar, contar, marcar; a notificação de outra
  pessoa → 404.
- Os testes existentes que renderizam cada página e conferem a referência
  gerada (`test_docs_sincronia`) passam depois de rodar
  `scripts/gerar_docs.py`.
- **Instância de teste manual**, fora da produção: script no scratchpad que sobe
  o worktree com SQLite temporário em outra porta, semeia gestor, uma autora e
  um diagramador de teste, um equipamento com documentos, um projeto com
  entregáveis e o modelo "Manual".

## Documentação

`docs/funcional/fluxos.md` (novo), a linha nova em `docs/funcional/README.md`,
os eventos em `docs/arquitetura/EVENTOS.md`, a correção de
`docs/funcional/missoes.md` sobre a ficha do equipamento, `docs/referencia/*`
regenerado e o CHANGELOG.

## Fora deste escopo

- E-mail e Teams. A tabela `notificacoes` é o ponto de extensão: um envio por
  e-mail lê dela quando o TI liberar uma conta.
- Lista de apontamentos item a item.
- Prazo por etapa / SLA, e gráficos de tempo por etapa (os dados já ficam nas
  passagens).
- Etapas em paralelo e aprovação por mais de uma pessoa.
- Documentos do PDR e páginas de Cadernos.
- Alertas de Documentos, Projetos e Missões no sino (fica para depois, sobre a
  mesma tabela).
