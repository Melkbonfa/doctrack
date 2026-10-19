# Módulo Tempos — apontamento de horas

## Por que existe

O DocTrack sabia *o que* foi feito (documentos, entregáveis, cartões,
equipamentos) mas não *quanto custou em esforço*. `Entregavel.peso` é estimativa
relativa, `MissaoCartao.dias_ciclo` mede tempo de calendário (da criação à
conclusão) e não tempo de trabalho, e `custos.Lancamento.horas` é número digitado
à mão. Nenhum respondia "quantas horas o time gastou nisso".

O módulo mede: cronômetro (iniciar / pausar / retomar / parar) ou lançamento
manual retroativo, amarrado a **projeto, entregável, cartão de missão,
equipamento** ou a uma **tarefa livre** que não existe na plataforma.

### Por que módulo e não outra plataforma

A alternativa avaliada foi um app separado que se conecta ao DocTrack. Não
compensa: o valor inteiro está no vínculo com as quatro entidades acima, e uma
plataforma separada teria de replicar usuários, JWT, RBAC e o catálogo delas, e
depois sincronizar — custo pago na entrada por zero benefício.

O que era legítimo naquela ideia é que **o cronômetro não pode morar só numa
página**: timer a três cliques de distância ninguém usa, e dado que ninguém
registra não vale nada. Isso se resolveu com o widget global. Como a API nasceu
sob `/tempos/api/*` com o mesmo JWT, um app de bandeja ou PWA no futuro é só mais
um cliente — a porta ficou aberta sem se pagar por ela agora.

### Escopo do MVP

| Decisão | Valor |
|---|---|
| Alvos | projeto · entregável · cartão de missão · equipamento · livre |
| Hora vira dinheiro? | **Não.** Sem custo/hora, sem integração com Custos/EVM |
| Aprovação / fechamento | **Não** |
| Onde fica o cronômetro | Widget global em todos os módulos + página `/tempos/` |

---

## As decisões de desenho

### Pausar fecha o intervalo; retomar abre outro

Uma linha é sempre um intervalo fechado, então `duracao_s == fim - inicio` vale
sempre e todo relatório é um `SUM`. A alternativa (`pausado_em` + segundos
acumulados) criaria um terceiro estado que envenena a invariante do cronômetro
único — pausado conta como "em curso"? Se sim, o índice trava a pessoa durante o
almoço; se não, acumulam-se linhas pausadas esquecidas sem regra de qual
"retomar" alcança. E corrigir "esqueci de voltar do almoço" viraria editar um
acumulador sem referente externo, em vez de um horário conferível num relógio.

O preço — um dia com 4 pausas são 5 linhas — é pago por `sessao_id`, o id do
primeiro trecho da corrente.

Consequência: **pausar e parar são a mesma escrita**, diferindo só em
`encerrado_por`. Um caminho de código (`core.fechar`), nenhuma máquina de estado.

O front não guarda o que retomar — pergunta a `/tempos/api/atual`. Sem
localStorage e sem relógio de cliente: começa no desktop, para pelo celular.

### Cronômetro único garantido no banco

Índice **parcial e único** `uq_tempo_em_curso` em `(user_id) WHERE fim IS NULL`.
SQLite (>= 3.8) e PostgreSQL aceitam a mesma sintaxe. `_sync_schema()` não
consegue expressá-lo (o laço `novos_indices` só emite índice simples de uma
coluna), então há um bloco dedicado em `servidor.py` para o caso de tabela
existente sem o índice — com de-dup **antes** do CREATE, senão a falha viraria um
`[WARN]` engolido e a invariante sumiria de produção sem ninguém perceber.

Na rota, o perdedor da corrida recebe **409, não 500**. É o único ponto do módulo
onde `IntegrityError` é esperado e não bug.

### O servidor é o relógio

As rotas de cronômetro carimbam `datetime.now()` e **ignoram** qualquer `inicio`
vindo do corpo. O cliente só afirma tempo no lançamento manual e na edição, e ali
tudo passa por `core.parse_dt` + `core.validar_intervalo` (ISO estrito, sem
futuro, teto de 16h, retroativo de 90 dias) e por `core.conflita`, que devolve
**qual** linha se sobrepõe.

A exibição também é ancorada: `/atual` devolve `servidor_agora` e o widget calcula
o offset uma vez. Sem isso o dado estaria certo e o usuário veria `-3h 12m`.

### Guarda de cronômetro abandonado

Sexta 17h alguém vai embora; sem guarda, na segunda o apontamento vale 64h e
contamina a soma do projeto. `encerrar_abandonados()` fecha em **`inicio +
LIMITE`** (12h, `DOCTRACK_TEMPO_LIMITE_H`), não em `agora` — o número não depende
de quando a guarda rodou, então rodar hoje, amanhã ou duas vezes produz a mesma
linha. Marca `encerrado_por='guarda'`, a folha pinta em âmbar, o dono corrige.

Roda em três lugares: na tarefa diária, em `/atual` (por dono) e na listagem da
folha (global). O terceiro nasceu da verificação: a cura por dono deixava o timer
esquecido de um técnico aberto na folha do time até a passagem diária, e o gestor
via "40h em curso" no meio do relatório.

### `projeto_id` denormalizado e congelado

Resolvido uma vez na gravação. É **fato congelado, não cache**: se um entregável
for remanejado, as horas já lançadas pertencem ao projeto em que foram gastas —
mesma leitura de `Lancamento.taxa_aplicada` (custos/models.py:312). Recalcular
faria total histórico mudar sozinho.

**Cartão de missão quase nunca alcança um projeto**: `REF_TIPOS_CARTAO`
(models.py:1945) não tem esse caminho e `Missao` não tem `projeto_id`. Por isso o
relatório por projeto tem um balde **"(sem projeto)"** explícito — na verificação
ele ficou com 17h das 24h45, ou seja, sem ele a maior parte das horas sumiria
calada da soma por projeto.

### RBAC de dono — padrão novo nesta base

Os módulos vizinhos são gated só por perfil. Aqui há duas camadas: `@so_membros`
(admin/gestor/técnico; `leitura` fica fora) e o gate de **dono**, um helper e não
um decorator, porque precisa da linha carregada e esconder uma query dentro de um
decorator é o tipo de comportamento invisível que os comentários deste repo
existem para evitar.

O ponto crítico é que a **listagem escopa, não recusa**: para não-gestão o filtro
por `user_id` é incondicional e o parâmetro do cliente é ignorado. Escrever
`if not alvo: filtra por mim` seria o IDOR. Lista, resumo e os dois exports
passam pelo mesmo `_query_escopada` — export mais frouxo que a lista é vazamento
pela planilha.

`/retomar` é só do dono, **sem override de gestão**: retomar *cria* linha, e um
gestor retomando o alheio personificaria a pessoa ou reatribuiria o trabalho em
silêncio. Supervisão é ler e corrigir, não autorar. E toda correção de gestor fica
visível (`editado_por`) — o MVP não tem aprovação, e um gestor reescrevendo horas
caladamente é aprovação com o consentimento removido.

### O widget global

Vive fora do `#app` (que é `display:none` até cada módulo revelar no `boot()`),
é criado por JS, e a primeira coisa que faz é checar o token — é essa guarda que o
faz conviver com a rota de página pública e não flutuar sobre a tela de login.

Três armadilhas que custaram tempo e que **falham em silêncio**:

1. **`{% block scripts %}` do base.html não alcança ninguém** — os cinco filhos
   sobrescrevem sem chamar `super()`. As duas linhas do widget ficam FORA de
   qualquer bloco.
2. **`entregaveis.html` (servida em `/projetos`) não estende o base.html** — tem
   `<head>` próprio e recebeu as duas linhas na mão. Sem isso, Projetos seria o
   único módulo sem cronômetro.
3. **Comentário HTML não é comentário de Jinja** — o comentário que explicava o
   item 1 continha `super()` entre chaves duplas, a expressão foi avaliada e
   **toda** página passou a devolver 500. Daí o teste que renderiza cada rota.

O widget diverge de `custos.js` de propósito no 401: lá o refresh falho chama
`gotoLogin()`, o que é certo para uma página cujo conteúdo inteiro é aquela API.
Num widget, isso ejetaria a pessoa de Equipamentos porque uma requisição do
marcador de tempo falhou. Aqui tenta uma vez e se cala.

### Tempo real econômico

`publish_event` grava uma linha em `audit_logs` por evento. 20 pessoas × 6 ciclos
por dia × 2 eventos seriam ~60 mil linhas/ano de puro ruído de UI. Só as mutações
de folha (manual, edição, exclusão) emitem; iniciar/pausar/parar/retomar não. A
sincronia entre abas sai por `localStorage` + evento `storage` — custo zero e
funciona até no `config.html`, que não carrega socket.io. Os eventos `TEMPO_*`
vão só para `user:{id}`: um feed ao vivo de quem começou o quê para `role:gestor`
transformaria o barramento num canal de vigilância que ninguém escopou.

---

## Fuso horário — dívida que este módulo tornou visível

A base é naive local em todo lugar e o `render.yaml` não definia `TZ`: o contêiner
roda UTC e as pessoas em BRT. Isso já distorcia `date.today()` nos snapshots
diários; com apontamento de hora um cronômetro das 22h cairia no dia seguinte na
folha. Corrigido com `TZ=America/Sao_Paulo` no `render.yaml`. **Não** tornar este
módulo aware — seria a única tabela aware num `models.py` de 2401 linhas naive.

---

## Integração com os outros módulos: a direção importa

Botão **"Apontar tempo"** no cartão de missão, na ficha de leitura do equipamento
e no modal do projeto. Cada um chama `DT_TEMPO.iniciar({ref_tipo, ref_id, titulo})`
e lê o acumulado em `GET /tempos/api/por-ref` — que devolve só agregado (total,
linhas, pessoas) e nunca quem fez o quê. Nenhum módulo fala com `/iniciar` ou
`/atual` por fora do widget: haveria um segundo estado de cronômetro, divergente
do que o widget desenha em todas as outras telas. Há teste travando isso.

Em Entregáveis o botão ficou **no projeto, não por entregável**: a aba lista
dezenas de linhas e um botão em cada uma poluiria a tela sem ganho. Quem precisa
da granularidade fina escolhe o entregável no próprio módulo de Tempos.

### O caminho inverso foi avaliado e RECUSADO

A ideia era: ao criar uma tarefa livre, abrir automaticamente um cartão em
Missões. Recusada — vale registrar, porque alguém vai sugerir de novo.

1. **A direção está invertida.** Kanban é plano (o que se pretende fazer); o
   apontamento é registro (o que já aconteceu). Cartão nascido de um lançamento
   fechado nasce concluído — um card em "Done" que ninguém planejou.
2. **Não há resposta para "qual missão, qual coluna".** `MissaoCartao.missao_id` e
   `coluna_id` são ambos `NOT NULL` (models.py:2070-2073). Automatizar exigiria
   inventar uma missão-caixa-de-entrada por pessoa: conceito novo, sem dono.
3. **O board inundaria.** "Reunião de alinhamento semanal" viraria 52 cartões/ano.

**Não há precedente no repositório para criar cartão automaticamente.**
`sincronizar_cartoes_documento` (missoes.py:213) só *move* cartões que alguém já
criou; a única criação automática é `_reagendar_recorrente`, e ali o cartão foi
autorado por uma pessoa uma vez.

O botão a partir do alvo resolve o mesmo problema pela origem: se apontar no
cartão é mais fácil que criar tarefa livre, a tarefa livre encolhe sozinha — em
vez de tratar o sintoma depois do fato.

## Fora do MVP, e por que sai barato depois

- **Horas viram dinheiro** (Custos/EVM). O ponto de junção já existe:
  `GET /tempos/api/resumo?por=projeto` é exatamente o número que
  `custos.Lancamento.tipo_calculo="horas"` recebe digitado hoje, e que
  `Projeto.pmo_metrics()` usa como AC via `_custo_atual`. Falta só a taxa — que
  foi decisão adiada, não encanamento faltando.
- **Aprovação / fechamento de competência**: `ADD COLUMN status` em
  `_sync_schema()` mais o gate no `PUT`/`DELETE`. O campo não nasceu no modelo de
  propósito: aberto/fechado já é `fim IS NULL`, e duas fontes de verdade para o
  mesmo fato dão bug.
- **Promover tarefa livre a cartão, sob demanda** — botão na linha da tarefa livre
  que cria o cartão com a pessoa escolhendo missão e coluna. Considerado e não
  feito agora; continua sendo a válvula de escape natural se, depois de rodar,
  ficar claro que tarefas livres viram trabalho recorrente que precisa de plano.
