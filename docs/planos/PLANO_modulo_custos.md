# Plano — Módulo de Custos

Estado: **fase 1 e 2 implementadas** (esta PR). Fases 3 e 4 mapeadas ao final.

---

## Por que o módulo existe

O custeio de um produto novo vivia numa planilha por projeto, feita à mão. A
planilha de referência — `Planilha_Custos_Projeto_Extracta Station 1600.xlsx` —
responde uma pergunta legítima (*"quanto custa colocar este equipamento importado
na prateleira, e qual a margem?"*), mas a auditoria célula a célula mostrou que
os números não se sustentam. Os achados que definiram o desenho:

| Achado na planilha | Como o módulo responde |
|---|---|
| A cotação exibida está quebrada **e não é usada em nenhum cálculo** — tudo converte por uma constante digitada à mão | Três taxas com papéis distintos: referência (PTAX, nunca calcula), planejamento (travada, é a única que orça) e realizada (da DI) |
| "Custo do projeto" é, em 99,8%, o custo de aterrissar uma unidade | `Lancamento.natureza` separa NRE de COGS; o NRE amortiza sobre `volume_projetado`, o COGS não |
| O esforço interno custa R$ 0 porque o custo/hora nunca foi preenchido | Custo/hora na composição + verificação de saúde que acusa a lacuna como **falha** |
| A coluna "Aplicável?" é decorativa: marcar "Não" não exclui do total | `Lancamento.aplicavel` de fato exclui, com teste que prova |
| Colunas em USD e em R$ calculadas por métodos incompatíveis, divergindo ~13% | Um único motor (`custos/core.py`), no servidor. O front não reimplementa fórmula nenhuma |
| Duas abas que não conversam: resultados copiados como constantes, já divergidos | Um cálculo derivado dos lançamentos, sempre |
| Nada tem data | Taxa travada com data, autor e justificativa; procedência e confiança por lançamento; versionamento de baseline |
| Três indicadores rotulados "ROI", todos errados | Margem de contribuição e payback em unidades, com o nome certo |

**A reserva cambial** incidia sobre tudo, inclusive tributos — que são apurados em
BRL sobre valor já convertido e não têm exposição. Aqui incide só sobre a
exposição real (mercadoria + frete em moeda estrangeira).

---

## O que foi construído

### Estrutura

```
custos/
├── models.py     # Composicao · Lancamento · Cotacao · Versao + vocabulários
├── core.py       # motor de cálculo (Decimal) + diagnóstico de saúde
├── cambio.py     # cliente PTAX do BCB, offline-first
├── routes.py     # blueprint /custos
└── templates/custos/dashboard.html
static/custos.css · static/custos.js
migrations/012_modulo_custos.py
tests/test_custos.py
```

### Duas divergências deliberadas da base

**`Numeric`, não `Float`.** Todo o `models.py` do mestre usa `db.Float` para
dinheiro. Aqui a aritmética é encadeada (câmbio × alíquota × rateio × margem) e o
erro de ponto flutuante se acumula. Valores em `Numeric(14,2)`, taxas em
`Numeric(14,6)`, alíquotas em `Numeric(8,4)`; o cálculo é todo em `Decimal`.

**CSS/JS no 1º nível de `static/`.** `_static_version()` só varre esse nível, então
o cache-busting funciona sem token próprio — o PDR precisou de um `ASSET_V` só
porque seus assets vivem dentro do pacote.

### Acesso

`@require_role("admin", "gestor")` em todas as rotas, agrupado num único
`so_gestao` para que afrouxar o gate por engano numa rota isolada apareça na
revisão. Mesmo corte de `pode_ver_financeiro()` em `entregaveis.py`.

Não usa `require_area("pde")` porque os módulos vizinhos da área (Documentos,
Projetos, Missões, Equipamentos) também não usam — só o PDR usa. Exigir área aqui
trancaria todo gestor cujo `users.areas` está vazio, que é o estado da maioria.

### Câmbio — offline-first

Primeira chamada HTTP externa do DocTrack. As regras estão no docstring de
`cambio.py`, mas em resumo: falha vira `[WARN]` e nunca bloqueia; timeout curto e
sem retry; busca uma **janela** de dias (a PTAX publica no fim da tarde do dia
útil e o agendador dispara sempre antes disso); upsert por `(moeda, data, tipo)`,
no molde do `ProjetoSnapshot`. Desligável com `DOCTRACK_CAMBIO=0` — e a suíte de
testes roda com ela desligada, para não depender de rede.

A URL é montada à mão porque o Olinda é OData e exige `@` e `$` literais: passar
pelo `params=` do `requests` os escapa e a API responde 400.

### Saúde

Oito verificações contínuas com **crédito proporcional** — cada uma contribui pela
fração que passa, ponderada pela gravidade (falha 3, aviso 2, observação 1). Tudo-
ou-nada faria "1 de 4 composições sem preço" pesar igual a "tudo quebrado".

---

## O que fica para depois

**Fase 3 — automações de maior retorno**
1. **Importar o extrato do despachante** — hoje o realizado é digitado linha a
   linha. Um importador no molde do `equipamentos_importer.py` (pandas, `_col()`
   tolerante, dry-run) preencheria tudo de uma vez.
2. **Tabela de alíquotas por NCM** — cadastrar o NCM uma vez em vez de digitar
   cinco alíquotas por composição. As alíquotas padrão de hoje
   (`_ALIQ_PADRAO` em `models.py`) são ponto de partida e precisam ser conferidas.
3. **Custo/hora por perfil com vigência** — hoje o valor vive na composição.
4. **Vincular ao equipamento pelo SKU** — `Equipamento.sku` já é chave de junção
   do importador mestre e do Pareto; dava para herdar fabricante, categoria e NCM.

**Fase 4 — fechar o ciclo**
5. **Rateio automático da DI** — dados os totais e as linhas da invoice, o rateio
   proporcional é puro cálculo.
6. **Calibrar a reserva cambial** com o desvio histórico próprio, por fornecedor e
   rota, em vez do percentual herdado.
7. **Alimentar `Projeto.orcamento`** com o NRE calculado — precisa antes decidir
   quem é dono do número quando os dois discordam.

**Fora de escopo, por decisão:** simulação de cenários (câmbio × MOQ × volume). O
modelo deixa a porta aberta — taxa de planejamento e volume projetado são os dois
botões que uma tela dessas precisaria — mas nada foi construído para isso.

---

## Relação com o PMO

Já existe custo de projeto no DocTrack: `Projeto.orcamento`,
`ProjetoMensal.custo_mes`, `ProjetoBaseline` e as métricas EVM. Isso é **execução
orçamentária** (quanto já se gastou vs. o previsto no tempo). Este módulo é
**formação de custo** (do que o número é feito). São camadas diferentes: a
composição alimenta o orçamento do projeto, não o substitui.
