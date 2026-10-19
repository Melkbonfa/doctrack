# Tempo real e trilha de eventos

Como uma mudança feita por uma pessoa aparece na tela das outras, e por que o
mesmo mecanismo serve de trilha de auditoria.

Código: [`event_bus.py`](../../event_bus.py),
[`static/socket-client.js`](../../static/socket-client.js),
[`static/app-realtime.js`](../../static/app-realtime.js).
Decisão: [ADR-0003](decisoes/ADR-0003-event-bus-e-audit-log.md).

---

## A regra

**Nenhuma rota chama `socketio.emit()` direto.** Toda mutação passa por
`publish_event()`, que faz três coisas numa chamada:

1. persiste o evento em `audit_logs` (que é o *event store*);
2. emite via Socket.IO para as rooms que interessam;
3. devolve o evento com id e timestamp.

Quebrar essa regra produz um efeito que só aparece depois: a tela atualiza mas
o evento não existe na trilha, então o replay de quem estava offline pula
aquela mudança e a auditoria não a registra.

```mermaid
sequenceDiagram
    participant R as rota /api/*
    participant E as publish_event()
    participant DB as audit_logs
    participant S as Socket.IO
    participant C as outros navegadores

    R->>R: grava a mudança no banco
    R->>E: publish_event(TIPO, payload, user…)
    E->>DB: INSERT (event store + auditoria)
    E->>E: _resolve_rooms(tipo, payload)
    E->>S: emit("event", …) nas rooms
    S-->>C: aplica na tela sem recarregar
    E-->>R: {id, timestamp, …}
```

---

## Rooms: quem recebe o quê

`_resolve_rooms()` decide o destino a partir do prefixo do tipo de evento e do
conteúdo do payload. Não há broadcast geral.

| Room | Quem entra | Recebe |
|---|---|---|
| `role:admin` | todo admin conectado | **tudo** |
| `role:gestor` | gestores | documentos, etapas, responsáveis, projetos, missões, PDR |
| `role:tecnico` | técnicos | projetos/entregáveis, missões, PDR |
| `setor:<X>` | quem abriu o setor | eventos de documento daquele setor |
| `equipamento:<Y>` | quem abriu o equipamento | eventos daquele equipamento |
| `doc:<N>` | quem está com a ficha aberta | eventos daquele documento |
| `projeto:<N>` | quem abriu o projeto | eventos daquele projeto |
| `apres:<N>` | quem abriu a apresentação PDR | eventos daquela apresentação |
| `user:<N>` | a própria pessoa | os apontamentos de tempo dela, notificações dirigidas |

Duas assimetrias que são de propósito, não esquecimento:

**Tempos não emite para gestor.** Um feed ao vivo de quem começou o quê seria um
canal de vigilância que ninguém pediu. Supervisão se faz pelas rotas de resumo,
sob demanda. (O admin recebe de qualquer forma, porque `role:admin` é semeado em
toda chamada.)

**Missões não tem sala por missão.** O backend emite para os papéis com acesso e
o front filtra pelo `missao_id` do payload. Simplificação assumida no MVP do
módulo.

---

## O ciclo do cliente

```mermaid
stateDiagram-v2
    [*] --> Conectando
    Conectando --> Autenticando: connect
    Autenticando --> Conectado: token válido
    Autenticando --> Recusado: auth_error / sistema_travado
    Conectado --> Inscrito: subscribe(rooms)
    Inscrito --> Inscrito: event
    Inscrito --> Reconectando: queda de rede
    Reconectando --> Recuperando: replay_request(since=último id)
    Recuperando --> Inscrito: replay
    Recusado --> [*]
```

Eventos que o cliente envia:

| Evento | Efeito |
|---|---|
| `subscribe` | entra nas rooms pedidas (só prefixos `setor:`, `equipamento:`, `doc:`) |
| `unsubscribe` | sai das rooms |
| `replay_request` | pede o que perdeu desde um id (limite de 500 eventos) |
| `ping_app` | diagnóstico de conexão |
| `join_apresentacao` | entra na sala de uma apresentação PDR |

Eventos que o servidor envia: `connected`, `subscribed`, `event`, `replay`,
`pong_app`, `auth_error`, `sistema_travado`.

> **O handshake do Socket.IO não passa pelo `before_request` do Flask**, então o
> guardião do kill switch é checado explicitamente em `on_connect`. Sem essa
> checagem, o tempo real continuaria entregando eventos com o sistema travado —
> ver [ADR-0006](decisoes/ADR-0006-kill-switch-fora-do-banco.md).

---

## Tipos de evento

A lista canônica é a classe `EventType` em [`event_bus.py`](../../event_bus.py) —
use sempre as constantes, nunca a string. Um tipo fora da lista é aceito mas
registra `WARNING` no log, o que é o sintoma de um `publish_event` escrito à mão.

Famílias, pelo prefixo:

| Prefixo | Domínio |
|---|---|
| `DOCUMENT_`, `ETAPA_`, `RESPONSAVEL_` | Documentos |
| `PROJETO_`, `ENTREGAVEL_`, `MENSAL_`, `BASELINE_` | Projetos e entregáveis |
| `MISSAO_` | Missões |
| `PRODUTO_`, `APRESENTACAO_`, `REIMPORT` | PDR |
| `CUSTO_` | Custos |
| `TEMPO_` | Tempos |
| `NOTIFICATION`, `USER_` | Sistema |

**Tempos publica só as mutações de folha** — iniciar, pausar, retomar e parar o
cronômetro não passam pelo barramento. Se passassem, cada ciclo viraria duas
linhas em `audit_logs` e o event store encheria de ruído de interface.

---

## Por que a trilha e o event store são a mesma tabela

`audit_logs` responde às duas perguntas com o mesmo dado: "quem mudou o quê e
quando" (auditoria) e "o que aconteceu depois do id N" (replay). Duas tabelas
significariam duas escritas por mutação e a possibilidade permanente de
divergirem — e é justamente a divergência que destruiria o valor das duas.

O custo é que a tabela cresce com o uso e mistura granularidades. Existe
`DOCTRACK_AUDIT_RETENCAO_DIAS` para poda, desligado por padrão (`0`).
Ligar isso tem uma consequência que precisa ser decidida com consciência:
**podar a trilha encurta a janela de replay junto**, e num sistema sob validação
apagar trilha de auditoria é uma decisão regulatória, não de manutenção.

---

## Como acrescentar um evento novo

1. Adicione a constante em `EventType` (`event_bus.py`).
2. Se ele precisa de room própria, trate o prefixo em `_resolve_rooms()`.
3. Chame `publish_event()` na rota que faz a mutação, **depois** do commit.
4. Trate o tipo no front, em `static/app-realtime.js`.
5. Rode `python scripts/gerar_docs.py` se mexeu em rota ou modelo.
