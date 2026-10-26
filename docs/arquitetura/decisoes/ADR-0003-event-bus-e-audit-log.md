# ADR-0003 — `audit_logs` é trilha de auditoria e event store ao mesmo tempo

**Status:** vigente · **Alcance:** tempo real, auditoria, replay

## Contexto

O sistema precisava de duas coisas que parecem diferentes:

1. **Trilha de auditoria** — quem mudou o quê, quando, de que valor para qual.
   Exigência do domínio: o acervo documental é regulado, e "o status mudou
   sozinho" não é resposta aceitável.
2. **Atualização em tempo real** — várias pessoas mexem nos mesmos documentos e
   no mesmo kanban, e recarregar a página para descobrir o que o colega fez é
   como se criam conflitos de edição.

Implementadas em separado, seriam duas escritas por mutação, dois lugares para
esquecer de escrever, e a certeza de divergirem com o tempo.

## Decisão

Uma função central, `publish_event()` em [`event_bus.py`](../../../event_bus.py),
faz as duas coisas na mesma chamada: grava em `audit_logs` e emite via
Socket.IO. **Nenhuma rota chama `socketio.emit()` direto.**

`audit_logs` passa a ser o *event store*: o id sequencial é a posição no fluxo,
então um cliente que ficou offline pede `replay_request(since=<último id>)` e
recebe o que perdeu. Não há estado de sessão no servidor.

> **Atualização (2026-10):** "o que perdeu" é o que ele teria recebido ao vivo.
> O replay passou a filtrar pelas salas da conexão com o mesmo `_resolve_rooms`
> do envio; antes devolvia a tabela inteira, inclusive linhas de `log_action` e
> eventos de sala restrita. Ver [EVENTOS.md](../EVENTOS.md).

Os tipos de evento são constantes de `EventType` — fonte única. As rooms de
destino saem de `_resolve_rooms()`, a partir do prefixo do tipo e do payload.

## Consequências

**Quem esquece de chamar `publish_event()` cria um bug silencioso triplo:** a
tela dos outros não atualiza, a auditoria não registra, e o replay pula a
mudança. Não há erro — só ausência.

**A ordem importa:** `publish_event()` vem *depois* do commit. Emitir antes
manda para as outras telas uma mudança que ainda pode falhar.

**A tabela cresce com o uso e mistura granularidades** — uma mudança de status
e um lote de importação são a mesma linha. Existe
`DOCTRACK_AUDIT_RETENCAO_DIAS` para poda, desligado por padrão. Ligar encurta a
janela de replay junto, e num sistema sob validação apagar trilha é decisão
regulatória, não de manutenção.

**Migrar para múltiplas instâncias mexe só nesta camada.** Socket.IO precisaria
de um broker (Redis) para propagar entre processos; o event store já é o banco,
que é compartilhado. É o ponto único de mudança — e por isso o desenho vale a
disciplina que ele exige.

**O handshake do WebSocket não passa pelo `before_request`.** Consequência
descoberta na prática: o kill switch precisou de checagem explícita em
`on_connect`, senão o tempo real seguiria entregando eventos com o sistema
travado.

## Alternativas descartadas

**Duas tabelas separadas.** Duas escritas por mutação e divergência garantida —
e é a divergência que destruiria o valor das duas.

**Emitir direto das rotas, auditar por trigger de banco.** Trigger não enxerga
quem fez a mudança (o app conecta com um usuário só) nem o contexto de
requisição, que é justamente o dado que a auditoria precisa.
