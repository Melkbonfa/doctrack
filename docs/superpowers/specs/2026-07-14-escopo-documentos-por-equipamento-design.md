# Escopo de documentos por equipamento (N/A) — design

Data: 2026-07-14
Módulos afetados: Documentos, Equipamentos, Dashboard

## Problema

Todo equipamento nasce hoje com os 9 tipos de documento obrigatórios
(`TIPOS_DOC_AUTO`) e pode receber 3 opcionais sob demanda (Spare Parts, Dossiê,
QI/QO/QD). Não existe a noção de "este documento não se aplica a este
equipamento": um Manual ES que o produto nunca terá fica eternamente em
"Elaborar", pinta o card de vermelho e entra no denominador dos KPIs. A
completude, portanto, não mede nada — ela pune equipamentos por documentos que
não deveriam existir.

O módulo Equipamentos já resolve o mesmo problema no IDP: o estado `N/A` tira o
item do denominador (`ESTADOS_REVISAO`, `idp()` em `static/equipamentos.js`).
Este design leva a mesma ideia para os documentos.

## Decisões

| Questão | Decisão |
| --- | --- |
| Semântica do "não tem" | `N/A` reversível — o documento continua existindo, fora do denominador |
| Onde se edita | Aba **Escopo** no modal do equipamento (Documentos), substituindo a aba "+ Adicionar" |
| Escopo padrão | Todo equipamento nasce com os 12 documentos; os 3 opcionais nascem `N/A` |
| Alcance da regra | Card, chips, KPIs do dashboard, relatórios e IDP contam só os aplicáveis |
| Permissão | `admin` e `gestor` marcam N/A; `tecnico` continua editando status e campos |
| Motivo do N/A | Campo de texto opcional |
| Escopo herdado por família | Fora deste escopo (possível fase 2) |

## Modelo de dados

Duas colunas novas em `documentos`:

- `aplicavel BOOLEAN DEFAULT TRUE NOT NULL` — falso = "não se aplica a este equipamento".
- `motivo_na VARCHAR(300) DEFAULT ''` — justificativa livre, exibida na aba Escopo e no audit log.

Ambas entram em `Documento.to_dict()` e no migrador de colunas de `servidor.py`
(dicionário `novas_colunas`, chave `documentos`).

Alternativas descartadas:

- **Status "N/A" no pipeline** — o status é linear e alimenta stepper,
  `status_global` e a sincronização com os cartões de missão; um valor fora do
  fluxo contamina os três e destrói o status real que o documento já tinha.
- **Tabela `equip_doc_escopo`** — cria uma segunda fonte de verdade sobre "este
  equipamento tem esse documento?" e custa join em toda listagem. Se o escopo por
  família virar prioridade, chega-se lá a partir da coluna, com uma tabela de
  *template* que apenas semeia `aplicavel` na criação.

### Backfill e criação

- Documentos existentes: `aplicavel = TRUE` (inclusive os opcionais já criados —
  existirem significa que se aplicam).
- `_ensure_docs_for_equip` (servidor.py) e a criação em `documentos.py` passam a
  gerar os **12** tipos: os obrigatórios com `aplicavel=True`, `TIPOS_DOC_OPCIONAIS`
  com `aplicavel=False`.
- `TIPOS_DOC_AUTO` some: com os 12 tipos sempre criados, o que a lista distinguia
  ("quais são auto-criados") deixou de existir. A criação decide pelo
  `TIPOS_DOC_OPCIONAIS`.

### Migração — o que NÃO fazer (aprendido na implementação)

A versão anterior de `_migrar_taxonomia_docs` fazia soft delete dos opcionais em
branco. Com os 12 tipos sempre criados, isso vira um ciclo: a migração oculta, o
backfill (que só enxerga os ativos) recria, o boot seguinte oculta de novo — cada
boot soma uma linha. No banco de dev isso produziu até 9 cópias de "Dossiê" no
mesmo equipamento.

A correção óbvia — "então a migração ressuscita o que ela mesma ocultou" — é pior:
um `ativo=False` não diz *quem* apagou. Ressuscitar todo opcional em branco inativo
desfaz, a cada boot, exclusões manuais, o cascade de equipamento excluído e qualquer
deduplicação. Verificado na prática: ela reativou 2495 duplicatas recém-limpas.

Regra final: **a migração só marca N/A nos documentos ATIVOS e nunca toca em
`ativo`.** Se um tipo ficar sem documento ativo, o backfill cria UMA linha nova em
N/A. Isso preserva os dois invariantes ao mesmo tempo — 1 documento ativo por
(equipamento × tipo), e soft delete é decisão de quem apagou.

## API

Rota nova, fora do `PATCH` genérico de documento (que é `tecnico`+):

```
PUT /api/documentos/<id>/aplicabilidade      (admin, gestor)
body: { "aplicavel": bool, "motivo_na": str }
```

Grava, registra no audit log (`UPDATE`, campo `aplicavel`) e emite
`DOCUMENT_UPDATED` no tempo real. Religar um documento (`aplicavel=True`) preserva
status, código, responsável e caminho de armazenamento — o bit é a única coisa que
muda. Marcar `N/A` **não** mexe no status nem toca nos cartões de missão vinculados.

## Regra de completude

Denominador = documentos aplicáveis. Completude do equipamento = finalizados /
aplicáveis. Pontos a alterar:

- `compute_kpis` (servidor.py:174) — ignora `aplicavel=False` em todas as contagens.
- `equipStatusColor` / `equipMatchesChip` (static/app.js) — cor e chips olham só os
  aplicáveis. Equipamento com todos os aplicáveis finalizados fica verde mesmo com
  N/A pendurados.
- IDP (static/equipamentos.js) — os itens derivados de documentos (IT, checklists,
  manual) respeitam o N/A do documento, como já fazem com o N/A das revisões manuais.
- Equipamento com **todos** os tipos em N/A: card neutro (cinza) e fora do
  denominador dos KPIs, espelhando o `idp()` que devolve `null` nesse caso.

## UI — aba Escopo

A aba "+ Adicionar" do modal do equipamento (`renderAddOpcionaisPanel`) é
substituída pela aba **Escopo**:

- Cabeçalho com a completude: "6 de 9 aplicáveis concluídos · 3 N/A".
- Lista dos 12 tipos, agrupados por setor (PRE / Manuais), cada um com toggle
  **Aplica / Não se aplica** e o status atual do documento ao lado.
- Ao desmarcar, aparece o campo de motivo (opcional). O motivo fica visível na
  linha do tipo quando ele está N/A.
- Tipos em N/A somem das abas de documento (nada a editar) e aparecem esmaecidos
  na aba Escopo, prontos para religar.
- `tecnico` e `leitura` veem a aba em modo leitura, com os toggles desabilitados.

## Testes

Estender `tests/test_taxonomia_docs.py` e `tests/test_documentos.py`:

1. Equipamento novo nasce com 12 documentos, sendo os 3 opcionais `aplicavel=False`.
2. `PUT /api/documentos/<id>/aplicabilidade` com perfil `tecnico` → 403; com `gestor` → 200.
3. `compute_kpis` não conta documentos `aplicavel=False` (total, finalizados e pct).
4. Religar um documento N/A preserva status, código e responsável gravados antes.
5. Marcar N/A não altera o status do documento nem move cartões de missão.
