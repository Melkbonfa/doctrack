# ADR-0008 — O agendador é uma thread do app, não um cron externo

**Status:** vigente · **Alcance:** séries temporais, indicadores

## Contexto

As séries temporais do sistema — ICE e IDP dos equipamentos, fotos das missões e
dos projetos — precisam de uma medição por dia. O único gancho que existia era a
subida do servidor.

Em produção o serviço fica semanas no ar. O resultado é que as tabelas
`*_snapshot` tinham exatamente **uma** data e os gráficos de evolução desenhavam
um ponto só. Os indicadores existiam; a evolução deles, não.

Cron externo (Agendador de Tarefas do Windows) resolveria — mas nenhum estava
configurado, e depender de um passo manual de deploy é precisamente como se
chegou nessa situação.

## Decisão

Uma thread daemon em [`scheduler.py`](../../../scheduler.py) acorda a cada
`DOCTRACK_AGENDADOR_INTERVALO` segundos (padrão 900) e pergunta "as tarefas de
hoje já rodaram?".

Sem dependência nova — APScheduler não está no `requirements.txt` e a rede
fabril pode não ter saída para instalá-lo. Sem estado em disco: a checagem é por
data, e as tarefas são idempotentes de qualquer forma, então um restart no mesmo
dia não duplica nada.

`servidor.init_app()` roda as tarefas do dia na subida; a thread cuida das
seguintes. Desliga com `DOCTRACK_AGENDADOR=0` (é o que os testes fazem).

Para quem preferir o Agendador de Tarefas do Windows, o mesmo conjunto de
tarefas roda uma vez e sai por `scripts/snapshot_diario.py`.

## Consequências

**Uma segunda instância roda as tarefas duas vezes.** As tarefas são
idempotentes, então o dano é carga, não dado corrompido — mas é mais um ponto
que assume instância única, com [ADR-0005](ADR-0005-ratelimit-em-memoria.md) e
[ADR-0006](ADR-0006-kill-switch-fora-do-banco.md).

**Servidor parado é dia sem foto.** Se o serviço ficar fora de um dia inteiro, a
série tem um buraco que não é preenchido retroativamente — não há como medir
ontem.

**O intervalo não é a frequência das tarefas.** As tarefas são diárias; 900
segundos é só de quanto em quanto tempo a thread verifica se o dia virou.
Confundir os dois leva a "otimizar" o intervalo para 24 h, o que faria a virada
do dia ser detectada com até um dia de atraso.

**A sincronização da PTAX está no mesmo ciclo** e faz chamada externa ao Banco
Central. Por isso os testes desligam com `DOCTRACK_CAMBIO=0`: sem isso, cada
execução da suíte dependeria de a máquina ter internet.

## Alternativas descartadas

**Agendador de Tarefas do Windows.** Continua disponível via
`scripts/snapshot_diario.py` e é a saída se a thread virar problema. Descartado
como padrão porque é um passo de instalação a mais que ninguém tinha feito.

**APScheduler.** Dependência nova para um relógio que checa uma data.

**Celery / worker separado.** Um serviço, um broker e um processo a mais para
uma tarefa por dia.
