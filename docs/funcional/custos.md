# Módulo Custos

Código: [`custos/`](../../custos/) — `models.py` · `core.py` (cálculo) ·
`cambio.py` (PTAX) · `routes.py` · tela `static/custos.js`
Montado em `/custos`.

## O que resolve

Formação de custo de produto e de projeto: quanto custa colocar um equipamento
importado no mercado, com que margem, e o que acontece com essa conta quando o
dólar se mexe.

## A distinção central: NRE × COGS

Toda linha da folha tem uma **natureza**, e ela não é um rótulo cosmético:

| Natureza | O que é | Como entra na conta |
|---|---|---|
| **NRE** | custo não recorrente do projeto — desenvolvimento, ferramental, homologação | **amortiza** sobre o volume projetado |
| **COGS** | custo recorrente por unidade — a mercadoria e o que vem com ela | não amortiza nunca |

Somar os dois numa coluna só produziria um "custo do projeto" que é, na prática,
o custo de uma unidade — e todo indicador derivado dele (margem, payback) sairia
errado.

`Lancamento.aplicavel` exclui a linha do total de fato, sem apagá-la.

## Como cada linha é calculada

`TIPOS_CALCULO` define de onde sai o valor:

| Tipo | Valor |
|---|---|
| `fob` | o valor FOB unitário da composição (a mercadoria) |
| `montante` | valor fixo, na moeda da linha |
| `horas` | horas × custo/hora do perfil (`eng` ou `prod`) |
| `percentual` | alíquota sobre o FOB em BRL — tributos de importação |
| `reserva` | percentual sobre a exposição em moeda estrangeira |

Categorias fixas — **Parceiro OEM**, **Integração Local**, **Regulatório**,
**Logística e Tributos**, **Comercial**. Fechadas de propósito: comparar
composições entre si exige vocabulário compartilhado, e texto livre
inviabilizaria a visão de portfólio por categoria.

Cada linha carrega ainda **procedência** e **confiança** (`baixa`/`media`/`alta`)
— um custo estimado e um custo cotado não valem a mesma coisa numa decisão.

## Os três papéis do câmbio

Confundi-los é o erro mais caro do módulo:

| Papel | Onde | Para que serve |
|---|---|---|
| **Referência** | `custo_cotacoes` (PTAX do BCB) | a série histórica: o que o mercado fez |
| **Planejamento** | `Composicao.taxa_planejamento` — **travada** | a única taxa que orça |
| **Realizada** | `Composicao.taxa_realizada`, com número e data da DI | fecha o ciclo contra o planejado |

A taxa de planejamento é travada e carrega **quem decidiu, quando e por quê**
(`taxa_planejamento_autor`, `_data`, `_justificativa`). Sem isso ela vira um
número herdado que ninguém defende numa reunião.

A PTAX é sincronizada diariamente do Banco Central (API Olinda) — a **primeira
chamada HTTP externa do sistema**. As regras dela:

- **falhar é normal e nunca bloqueia** — a rede fabril pode não ter saída; o
  módulo é utilizável com taxa manual e a busca é conveniência;
- **timeout curto, sem retry** — uma tarefa diária travada seguraria as outras;
- **busca uma janela, não "hoje"** — a PTAX só publica em dia útil, no fim da
  tarde, e o agendador dispara logo após a virada do dia;
- **consolida por data**, ficando com o fechamento;
- **upsert por (moeda, data, tipo)**, o que torna rodar duas vezes inofensivo.

Desligável com `DOCTRACK_CAMBIO=0`.

## Versionamento

`custo_versoes` congela a baseline. Os campos que a compõem:

    taxa_planejamento · preco_venda · volume_projetado

Mexer em qualquer um deles versiona — mesmo contrato do baseline de projetos, e
pelo mesmo motivo: são eles que definem contra o que o realizado será medido.

Status da composição: `rascunho` · `vigente` · `arquivada`.
Tipo: `OEM` · `Revenda`.

## Vínculos

`projeto_id` e `equipamento_id` são **opcionais**: uma composição pode nascer
antes de o projeto existir, e revenda pode não ter projeto nenhum.

## Dinheiro é `Numeric`, não `Float`

Divergência deliberada em relação ao resto do sistema. Aqui a aritmética é
encadeada — câmbio × alíquota × rateio × margem — e o erro de ponto flutuante se
acumula ao longo da cadeia. Um custo unitário que fecha em `114732.41999999999`
não é defensável numa reunião.

- valores: `Numeric(14,2)`
- taxas de câmbio: `Numeric(14,6)`
- alíquotas: `Numeric(8,4)`

O cálculo vive em `custos/core.py` e é todo em `Decimal`.

## Quem pode o quê

**Só admin e gestor**, em tudo — inclusive na leitura. Custo de produto,
margem e preço de venda não são dado de time.

## Pontos de atenção

- **Tabelas prefixadas `custo_`** para não colidir com o domínio antigo.
- **O cálculo é do servidor** (`core.py`), sem Flask e sem `request` — testável
  isolado. Não reimplemente margem no JavaScript.
- **`reserva_cambial_pct` é 10% por padrão.** É premissa, não constante física;
  mudá-la muda o custo de toda composição nova.
- **`LIMITE_DESVIO_CAMBIO`** marca quando a taxa realizada se afastou demais da
  planejada — é o alarme de que a baseline não vale mais.
