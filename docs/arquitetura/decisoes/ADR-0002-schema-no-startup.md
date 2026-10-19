# ADR-0002 — Schema aplicado no startup, migrações espelhadas

**Status:** vigente, com ressalva · **Alcance:** banco, deploy

## Contexto

O projeto nasceu com um desenvolvedor, um servidor e SQLite. Alembic resolveria
o versionamento de schema, mas traz um fluxo (revisões, `upgrade`/`downgrade`,
histórico linear) cujo custo só se paga com mais de uma pessoa mexendo no schema
e mais de um ambiente para reconciliar. O deploy é `git pull` + restart do
serviço, sem passo de migração.

## Decisão

O schema é aplicado **na subida do app**, por `servidor.init_app()`:

1. `db.create_all()` — cria tabelas que não existem;
2. `_sync_schema()` — adiciona colunas novas a tabelas existentes, de forma
   idempotente e cross-dialect (SQLite e PostgreSQL);
3. backfills idempotentes de dados (taxonomia, caminhos, marcos, histórico);
4. `rodar_tarefas_diarias()` — garante a foto do dia.

Em paralelo, `migrations/00N_*.py` guarda scripts numerados que **espelham** as
mesmas mudanças para quem prefere aplicar no banco antes de trocar o código.
São scripts SQLite autônomos, idempotentes.

`init_app()` **não roda no import**. Quem sobe o servidor chama a função
explicitamente ([`wsgi.py`](../../../wsgi.py) e o `__main__` de `servidor.py`);
quem só importa o módulo — pytest, um script solto — não paga nada. Antes disso,
qualquer `import servidor` executava `create_all`, os backfills e escritas de
snapshot contra o banco real do desenvolvedor sem ninguém ter pedido.

## Consequências

**Deploy é `git pull` + restart.** Não há passo de migração para esquecer, e é
o motivo de o fluxo de deploy caber em três linhas.

**Homologação nunca pode apontar para o Postgres de produção.** Se
`DATABASE_URL` estiver apontando para lá, subir o servidor local aplica o schema
em produção. É a armadilha mais perigosa do projeto e está avisada em
[FLUXO_DESENVOLVIMENTO.md](../../FLUXO_DESENVOLVIMENTO.md).

**Toda mudança de schema precisa ser idempotente e aditiva.** Não há `downgrade`.
Remoção de coluna não é suportada pelo mecanismo; a prática é soft delete e
coluna nova, nunca `DROP`.

**Os dois mecanismos podem divergir.** `_sync_schema()` é o que roda de fato em
produção; `migrations/` só vale se alguém o mantiver em dia. Um script numerado
esquecido não quebra produção — o que é ao mesmo tempo a conveniência e o risco.
Esta é a ressalva do status.

**Subida mais lenta.** Os backfills varrem tabelas a cada start. São idempotentes
e rápidos no volume atual (dezenas de milhares de linhas), mas crescem com a base.

## Alternativas descartadas

**Alembic.** A escolha certa se o time crescer ou se surgir um segundo ambiente
persistente. Hoje o custo do fluxo não se paga, e migrar depois é possível:
`alembic stamp head` adota o schema atual como baseline.

**Só os scripts de `migrations/`, sem `_sync_schema()`.** Exigiria um passo
manual em todo deploy — exatamente o passo que a experiência deste repositório
mostra que é esquecido.
