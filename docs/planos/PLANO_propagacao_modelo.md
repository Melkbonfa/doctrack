# PLANO — Aplicar mudanças do modelo aos projetos existentes

> **Objetivo.** Quando um modelo de entregáveis muda, um **administrador** pode
> levar a mudança aos projetos em andamento, passando por um **pop-up de controle
> de mudança** (prévia, escolha, motivo, confirmação). Cada aplicação fica num
> **histórico**.
>
> Pedido em 2026-10-19. Prototipado e aprovado num ambiente isolado (banco
> SQLite temporário, sem tocar a produção) antes deste PR.
>
> Depende de duas frentes que vão no mesmo PR porque ainda não estavam na
> `main`: a **ordem dos entregáveis** (migration 018) e as **categorias de
> entregável cadastráveis** (migration 019).

## 1. Como era

O projeto **copia** os itens do modelo ao nascer e o vínculo se perde. Editar o
modelo só vale para projetos novos. A única forma de ligar entregável e item
seria pelo nome, que quebra ao renomear.

## 2. Decisões (tomadas com o usuário)

| Pergunta | Decisão |
|---|---|
| Quem aplica | Só **admin**. Gestor continua editando o modelo e lê o histórico. |
| Quais projetos | Ativos e abertos (planejado, execução, suspenso) do modelo, **todos marcados**; o admin desmarca. Arquivados, concluídos e cancelados ficam fora. |
| Item que saiu do modelo, com andamento | **Admin decide caso a caso**: apagar (perde o histórico), manter como avulso ou marcar N/A. Sem andamento: apagar por padrão (pode trocar). |
| Projeto ajustou peso/responsável e o modelo também mudou | **Vale o do projeto** — aparece como "mantido". |
| Abordagem | Botão explícito **Aplicar aos projetos…** com comparação de três lados (e não um pop-up a cada edição, nem sincronizar por nome). |

## 3. Como funciona

### Dados (migration 020)

- `modelos_entregavel.chave` — identificador permanente do item. Não se usa o
  `id` porque o banco pode reaproveitar o id de um item excluído.
- `entregaveis.modelo_chave` — de qual item veio (`""` = avulso, nunca tocado).
- `entregaveis.modelo_origem` — JSON com nome, categoria, peso e responsável
  que o modelo tinha na última criação/aplicação. `NULL` só em linha anterior
  ao recurso; a subida resolve.
- `mudancas_modelo` — uma linha por aplicação: modelo, motivo, quem, quando,
  totais.
- `mudancas_modelo_itens` — uma linha por alteração (ou "mantido"): projeto,
  entregável (id e nome, porque pode ter sido apagado), ação, campo, antes,
  depois.

Dados existentes: `servidor._vincular_entregaveis_ao_modelo()` (e a migration
020, para SQLite) ligam cada entregável ao item de mesma categoria + nome do
modelo do projeto, gravando os valores **atuais** do modelo como origem. Onde o
projeto já tinha peso diferente, conta como ajuste do projeto. O que não casa
vira avulso.

### Comparação de três lados (`modelo_sync._mudancas_do_projeto`)

| Situação do campo | Resultado |
|---|---|
| modelo = origem | nada (o modelo não mexeu) |
| modelo = projeto | nada visível (chegaram ao mesmo valor) |
| projeto = origem | **atualiza** |
| senão | **mantido** (ajuste do projeto) |

Nome e categoria não são editáveis no projeto: sempre seguem o modelo. A
**ordem** do projeto não é propagada; item novo entra no fim da categoria.
Item do modelo que o projeto não tem: **vincular** se houver avulso de mesmo
nome e categoria; senão **criar**. Entregável ligado a item que não existe mais
no modelo (inclusive porque o projeto trocou de modelo): **saiu do modelo**.

### Fluxo

1. `GET /api/modelos/propagacao/previa?tipo=` (admin) — prévia por projeto, com
   uma `versao` (hash das mudanças).
2. Pop-up: projetos com checkbox, mudanças por projeto, destino dos removidos,
   motivo (≥ 5 caracteres), caixa "Confirmo a aplicação de N alterações em M
   projetos…". O botão só libera com tudo preenchido e diz o que falta.
3. `POST /api/modelos/propagacao` (admin) — recalcula a prévia; se a `versao`
   de algum projeto mudou, recusa com **409** e a tela refaz a prévia. Valida
   tudo antes de escrever; aplica numa transação só; grava o histórico, a foto
   do dia do projeto e uma linha na auditoria.
4. `GET /api/modelos/propagacao/historico?tipo=`, `GET /api/modelos/propagacao/<id>`
   e `GET /api/projetos/<id>/mudancas-modelo` (admin/gestor).

Aplicar não carimba `atualizado_em` (o alerta de projeto parado continua vendo
a inércia), como já fazem renomear categoria e reordenar.

## 4. O que foi verificado

- `tests/test_propagacao_modelo.py` — 19 testes: vínculo na criação (inclusive
  pela lista do modal), comparação de três lados, "mantido", vincular avulso,
  remoção com e sem andamento e as três decisões, alcance (escolhidos x
  inelegíveis), prévia desatualizada (409), motivo, permissões
  (gestor 403 / técnico 403), histórico com antes/depois, projeto que trocou de
  modelo, backfill pelo nome e idempotência.
- Suíte completa da branch (sobre a `main`): 540 testes passando.
- Servidor de teste com banco "antigo" (sem as colunas novas): a subida criou
  as colunas e ligou 25 entregáveis, deixando os avulsos de fora. Na tela,
  como admin: prévia, decisão N/A, projeto desmarcado, motivo, confirmação,
  histórico. Como gestor: sem o botão, prévia bloqueada, histórico visível.
  Largura de celular sem rolagem horizontal.
- Migration 020 num SQLite antigo, rodada duas vezes (idempotente).

## 5. Fora do escopo (de propósito)

- **Desfazer** uma aplicação. O histórico tem o antes/depois, mas apagar
  entregável leva o histórico dele junto. Se for preciso, é outra frente.
- Propagar **ordem** e **datas previstas** (são do projeto).
- Aviso automático de "modelo com mudanças pendentes" na aba Modelos (exigiria
  calcular a prévia de todos os modelos a cada abertura).
- Histórico do modelo **dentro do modal do projeto**: a rota
  `/api/projetos/<id>/mudancas-modelo` existe, a tela ainda não usa.

## 6. Para levar à produção

1. A pasta de produção (`C:\apps\doctrack`) roda código que ainda não está na
   `main` (cadernos, tempos, kill switch, PWA…). A ordem dos entregáveis, as
   categorias e as setinhas já estão lá sem commit; a propagação ainda não.
   Não basta dar `git pull`: as mudanças locais conflitam. A ida para lá
   precisa ser combinada à parte.
2. Backup do PostgreSQL antes de reiniciar o serviço.
3. Reiniciar o serviço DocTrack: `_sync_schema` cria as colunas e o backfill
   liga os entregáveis pelo nome (veja no `logs\out.log` a linha
   "vínculo com o modelo").
4. Abrir a prévia de cada modelo **antes** de aplicar qualquer coisa: logo após
   o deploy ela deve vir quase vazia. O que aparecer são diferenças de nome
   (ex.: maiúsculas) entre o projeto e o modelo.
