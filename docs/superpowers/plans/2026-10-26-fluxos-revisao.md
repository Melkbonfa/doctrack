# Fluxos de revisão — plano de implementação

> Executado inline nesta sessão, tarefa a tarefa, com TDD nas partes de servidor.
> Spec: [`../specs/2026-10-26-fluxos-revisao-design.md`](../specs/2026-10-26-fluxos-revisao-design.md).

**Objetivo:** fluxo escrita → diagramação → revisão (com devoluções) em
documentos e entregáveis, com anexos por passagem e um sino de notificações.

**Arquitetura:** dois pacotes novos no formato de `tempos/` (ADR-0010).
`notificacoes/` é genérico (tabela + `notificar()` + rotas). `fluxos/` traz a
máquina de estados pura em `core.py` (sem Flask), modelos com etapas em JSON
copiadas para a instância, rotas e página. Documentos e Entregáveis ganham
helpers de troca de status reaproveitados pelo fluxo, e a mesma trava aparece no
N/A, na exclusão e em `modelo_sync.tem_andamento`.

**Stack:** Flask + SQLAlchemy (SQLite em teste, Postgres em produção), pytest,
JS sem framework (IIFE com um global, como `tempos-widget.js`).

**Desvio da spec, registrado nela:** a notificação **não** passa por
`publish_event`. O `replay_request` devolve a trilha de `audit_logs` inteira para
qualquer conexão, sem filtrar por sala, e uma notificação pessoal gravada ali
vazaria no replay de outra pessoa. O sino consulta `/api/notificacoes/contagem`
(a cada 30 s, ao focar a aba e logo depois de uma ação do próprio usuário). Os
eventos `FLUXO_*`, que não são pessoais, seguem pelo barramento.

Comando de teste (o worktree não tem venv próprio):

    C:/Apps/doctrack/venv/Scripts/python.exe -m pytest -q -p no:cacheprovider <alvo>

---

### Tarefa 1 — `notificacoes/`

**Arquivos:** criar `notificacoes/{__init__,models,core,routes}.py`,
`tests/test_notificacoes.py`. Modificar `servidor.py` (registrar o blueprint e a
purga diária), `scripts/gerar_docs.py` (arquivo de rota, de modelo e domínio
`notificacoes`).

- `Notificacao` (`notificacoes`): `user_id` FK CASCADE, `tipo` (`acao`|`info`),
  `titulo`, `texto`, `link`, `origem_tipo`, `origem_id`, `criada_em`, `lida_em`.
  Índice `(user_id, lida_em, criada_em)`.
- `core.notificar(user_ids, *, tipo, titulo, texto, link, origem_tipo, origem_id,
  exceto=None)`: deduplica, ignora `exceto` e usuário inativo, só faz `add`
  (o commit é do chamador).
- `core.purgar_lidas(dias=90)` → quantidade apagada.
- Rotas (`require_role("admin","gestor","tecnico")`): `GET /api/notificacoes`
  (`nao_lidas`, `limite` ≤ 100), `GET /api/notificacoes/contagem`,
  `POST /api/notificacoes/<id>/lida` (a de outra pessoa → 404),
  `POST /api/notificacoes/lidas`.
- Testes: `notificar` deduplica e respeita `exceto`; listar só as minhas; contar;
  marcar a minha; marcar a alheia → 404; marcar todas; `leitura` → 403; purga
  apaga só as lidas antigas.

### Tarefa 2 — `fluxos/core.py` (máquina de estados pura)

**Arquivos:** criar `fluxos/core.py`, `tests/test_fluxos_core.py`.

- `validar_modelo(papeis, etapas)` → `(papeis_norm, etapas_norm, erro)`. Regras:
  ≥ 1 etapa, chaves únicas, papel existente, revisão nunca é a primeira,
  `devolve_para` aponta para uma etapa anterior (padrão: a imediatamente anterior).
- `acoes_possiveis(etapas, etapa_atual)` → `["enviar"]` ou `["aprovar","devolver"]`.
- `transicao(etapas, etapa_atual, acao)` → `(para_etapa | None, encerra: bool,
  soma_rodada: bool)`. Ação inválida → `ValueError`.
- `rotulo_acao(etapas, etapa_atual, acao)` → "Enviar para Diagramação",
  "Concluir", "Aprovar", "Devolver para Diagramação".
- `destinatarios(participantes, etapas, para_etapa, iniciador_id, ator_id)` →
  `(ids_acao, ids_info)`, deduplicados, sem o ator.
- Testes: um caso por regra de validação; enviar avança; enviar na última
  encerra; aprovar avança/encerra; devolver volta e soma rodada; ação errada para
  o tipo de etapa → erro; Giullia com dois papéis recebe uma notificação só.

### Tarefa 3 — `fluxos/models.py` + modelo semeado

**Arquivos:** criar `fluxos/models.py`, `fluxos/__init__.py`. Modificar
`servidor.py` (semear o modelo "Manual" no `init_app`, se não houver nenhum).

`FluxoModelo`, `Fluxo` (índice parcial único `(ref_tipo, ref_id) WHERE
status='andamento'` com `sqlite_where` **e** `postgresql_where`),
`FluxoParticipante`, `FluxoPassagem`, `FluxoArquivo`, com os campos da spec e
`to_dict()`.

### Tarefa 4 — helpers de status em Documentos e Entregáveis

**Arquivos:** modificar `documentos.py`, `entregaveis.py`, `modelo_sync.py`.
Testes em `tests/test_fluxos_api.py` (Tarefa 5).

- `documentos.aplicar_status_documento(doc, novo, caller)` → eventos de sync.
  Faz versão, marcos, histórico e `sincronizar_cartoes_documento`, sem commit.
  `update_status` passa a usá-la.
- `entregaveis.efeitos_status(e, novo)` — o bloco if/elif de datas/percentual,
  extraído de `atualizar_entregavel`, que passa a chamá-lo.
  `entregaveis.aplicar_status_entregavel(e, novo, email)` = efeitos + histórico +
  `atualizado_*` + snapshot, sem commit.
- Travas: `update_aplicabilidade` (marcar N/A), `delete_documento` e
  `excluir_entregavel` → 409 com fluxo ativo. `tem_andamento` → True com fluxo
  ativo.

### Tarefa 5 — `fluxos/routes.py`

**Arquivos:** criar `fluxos/routes.py`,
`fluxos/templates/fluxos/dashboard.html`, `tests/test_fluxos_api.py`.
Modificar `servidor.py` (blueprint + `init_realtime`), `event_bus.py` (eventos
`FLUXO_*` e roteamento) e `areas.py` (card "Fluxos" em PDE e INOV).

Rotas da spec. Pontos que os testes cobrem:
- iniciar: documento (Manuais → *Em andamento*; PRE intacto) e entregável
  (*pendente → em_progresso*); entregável `na` → 400; segundo ativo → 409;
  participante inexistente → 400; `leitura` → 403.
- ação: não participante → 403; gestor em nome de → `em_nome_de_id`; versão velha
  → 409; devolver sem comentário → 400; extensão → 415; arquivo grande → 413
  (teto baixado por monkeypatch); notificações certas e nada para quem agiu.
- aprovar: documento → *Concluído*, cartão vinculado vai para "done" e os
  arquivos entram em `documento_arquivos` com o mesmo sha; entregável →
  *concluido*.
- reatribuir / cancelar: motivo obrigatório, só gestão ou o iniciador.
- `comigo`, `por-ref`, `por-refs`, `em-andamento`, conteúdo de arquivo
  (o participante baixa, `leitura` não).
- travas da Tarefa 4: N/A e exclusão → 409; `tem_andamento`.

### Tarefa 6 — Front: sino

**Arquivos:** criar `static/notificacoes-widget.js` e `.css`. Incluir fora de
blocos em `templates/base.html`, `templates/entregaveis.html`,
`templates/hub.html` e `templates/subhub.html`.

Botão flutuante acima do cronômetro, com badge. Painel com "Com você agora"
(`/fluxos/api/comigo`) e "Avisos". Consulta a contagem ao carregar, a cada 30 s e
no `visibilitychange`. Escuta `dt:notificacoes-atualizar` (disparado pelo painel
do fluxo depois de uma ação). Cala com 401 sem refresh, e com 403 (`leitura`).

### Tarefa 7 — Front: painel do fluxo + Documentos + Projetos

**Arquivos:** criar `static/fluxos-painel.js` e `.css`. Modificar
`static/app.js` (seção Fluxo em `renderTipoPanel`), `static/entregaveis.js`
(chip na linha, seção no popover, deep-link `?projeto=&entregavel=`),
`templates/dashboard.html` e `templates/entregaveis.html` (incluir os assets).

`DT_FLUXO.montar(host, {ref_tipo, ref_id, titulo})` e
`DT_FLUXO.resumos(ref_tipo, ids)`.

### Tarefa 8 — Página `/fluxos/`

**Arquivos:** criar `static/fluxos.js`, `static/fluxos.css`. Abas "Em andamento"
e "Modelos" (editor de papéis e etapas).

### Tarefa 9 — Documentação e referência

`docs/funcional/fluxos.md`, `docs/funcional/README.md`,
`docs/arquitetura/EVENTOS.md`, a correção em `docs/funcional/missoes.md`,
`python scripts/gerar_docs.py`, CHANGELOG e o ajuste na spec (notificação sem
barramento). A suíte inteira deve passar.

### Tarefa 10 — Instância de teste

Script no scratchpad: SQLite temporário, porta 5380, `init_app()`, semeia gestor,
autora, diagramador e técnico de fora; um equipamento com documentos; um projeto
com entregáveis. Entrada em `.claude/launch.json` (do worktree). Verificação no
navegador: o ciclo completo, com uma devolução, entrando como cada pessoa.
