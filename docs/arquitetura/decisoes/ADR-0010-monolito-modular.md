# ADR-0010 — Monólito modular em blueprints, um processo e um banco

**Status:** vigente · **Alcance:** estrutura do código, deploy

## Contexto

O DocTrack começou como um dashboard de documentos e cresceu para oito módulos:
Documentos, Equipamentos, Consumíveis, Projetos/Entregáveis, Missões, PDR,
Custos e Tempos. Módulos novos continuam aparecendo.

O crescimento levantaria naturalmente a questão de separar serviços — cada
módulo com seu deploy e seu banco. O contexto que responde essa pergunta:
usuários na ordem de dezenas, um servidor Windows, e o desenvolvimento feito
essencialmente por uma pessoa.

## Decisão

Um app Flask, um processo, um banco. Cada módulo é um **blueprint**, e os
módulos novos nascem em **pacote próprio** com o mesmo formato:

```
custos/
  __init__.py     exporta o blueprint
  models.py       tabelas prefixadas (custo_*)
  core.py         regra de negócio pura, sem Flask
  routes.py       rotas HTTP
  templates/      templates do módulo
```

`tempos/` e `pdr/` seguem o mesmo desenho. Todos reutilizam o `db` do mestre,
com as tabelas prefixadas para não colidir com o domínio antigo.

Os módulos antigos (`documentos.py`, `entregaveis.py`, `missoes.py`) são
arquivos únicos na raiz — formato anterior, não convertido.

O tempo real é injetado de fora (`init_realtime(socketio, publish_event, ...)`)
para evitar import circular com `servidor.py`.

## Consequências

**Deploy é uma coisa só:** `git pull` + restart. Sem orquestração, sem versão de
API entre serviços, sem transação distribuída.

**Uma consulta cruza domínios sem esforço.** Tempos amarra apontamento a
projeto, entregável, cartão de missão *e* equipamento com quatro chaves
estrangeiras; em serviços separados isso seria quatro chamadas de rede e
consistência eventual.

**Um erro derruba tudo.** Não há isolamento entre módulos: exceção não tratada,
vazamento de memória ou consumo de CPU em um afeta os outros.

**A separação depende de disciplina, não de barreira.** Nada impede
`custos/routes.py` de importar `missoes.py`. O que segura é a convenção —
regra de negócio em `core.py`, sem Flask e sem `request`, testável isolada.

**`servidor.py` e `models.py` acumularam** 3,2 mil e 2,5 mil linhas. `models.py`
concentra 35 classes de seis domínios diferentes — é por isso que o dicionário
de dados precisa de um mapa manual de domínio no gerador. Quebrar os dois é
dívida conhecida e não urgente.

**A premissa de processo único aparece em três lugares** — rate limit,
agendador e cache do kill switch ([ADR-0005](ADR-0005-ratelimit-em-memoria.md),
[0008](ADR-0008-agendador-embutido.md), [0006](ADR-0006-kill-switch-fora-do-banco.md)).
São os três pontos a revisitar se um dia houver uma segunda instância.

## Alternativas descartadas

**Microsserviços por módulo.** Custo de operação (deploy, monitoração,
consistência) desproporcional a dezenas de usuários e um desenvolvedor.

**Bancos separados por módulo.** Acabaria com as chaves estrangeiras
cross-domínio que hoje são o que dá valor ao sistema — um apontamento de tempo
que aponta para um cartão de missão que aponta para um documento de um
equipamento.
