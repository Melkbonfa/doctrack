# Módulo Projetos e Entregáveis (PMO)

Código: [`entregaveis.py`](../../entregaveis.py),
[`modelo_sync.py`](../../modelo_sync.py) · modelos `Projeto`,
`Entregavel`, `EntregavelHistorico`, `ModeloEntregavel`, `MudancaModelo`,
`MudancaModeloItem`, `ProjetoMensal`, `ProjetoSnapshot`, `ProjetoBaseline` ·
tela `static/entregaveis.js`

## O que resolve

Acompanhar projetos de desenvolvimento de produto pelos seus entregáveis, com
uma visão mensal de PMO: o que foi planejado, o que foi executado, quanto
custou, e se o projeto está adiantado ou atrasado em relação ao que foi
aprovado.

> A URL antiga `/entregaveis` continua funcionando como alias de `/projetos`,
> para não quebrar links salvos.

## Projeto

| Campo | Valores |
|---|---|
| `tipo` | o **modelo** do projeto (`PDE RUO`, `PDR IVD`, `INOV`…, além dos antigos `OEM`/`Revenda`) — define a área e a lista de entregáveis aplicada. Obrigatório em projeto novo |
| `status` | `planejado` · `execucao` · `suspenso` · `concluido` · `cancelado` |
| `moscow` | `Must` · `Should` · `Could` · `Wont` |
| `ativo` | arquivamento — **ortogonal ao status** |

A separação entre `status` e `ativo` é deliberada: um projeto arquivado pode ter
terminado bem (`concluido`) ou morrido no meio (`cancelado`), e sem a coluna de
status as duas coisas eram indistinguíveis.

Abertos são `planejado`, `execucao` e `suspenso`.

## Entregáveis

Cada projeto tem entregáveis agrupados em categorias. Banco novo nasce com
**Produto**, **Sistema**, **Documentação**, **Capacitação** e **Marketing**;
admin/gestor criam outras pela opção "+ Nova categoria…" do seletor de
categoria, ou no card **Categorias de entregável** da aba Modelos. Ali também
se muda a ordem (que é a das abas no projeto), renomeia (o nome novo vale para
os entregáveis e modelos que já usam) e exclui — só categoria sem uso, e nunca
a última.

Status: `na` · `pendente` · `em_progresso` · `concluido`.

O avanço do projeto é calculado a partir dos entregáveis — não é digitado.

**Ordem.** Admin/gestor arrastam os entregáveis para definir a ordem dentro de
cada categoria, no modal do projeto ou na ficha do Dashboard (no celular, com
toque longo). A ordem vale para todas as telas e para os exports. Projeto novo
nasce na ordem do modelo; entregável adicionado depois entra no fim. Arrastar
não muda a categoria nem conta como atualização do entregável (o alerta de
projeto parado não é enganado por uma arrumação de lista).

**Modelos de entregável** (`modelos_entregavel`) são a lista padrão por tipo de
projeto: criar um projeto OEM já traz os entregáveis que todo OEM tem. Editar o
modelo não altera projetos já criados — até um admin **aplicar o modelo aos
projetos** (abaixo). Admin/gestor ordenam os itens do modelo com ↑/↓, dentro da
categoria; é a ordem que o projeto novo herda.

**Aplicar o modelo aos projetos** (só admin; ver
[`modelo_sync.py`](../../modelo_sync.py)). Cada entregável que veio do modelo
guarda de que item veio e com que valores (nome, categoria, peso, responsável).
O botão **Aplicar aos projetos…** da aba Modelos abre um controle de mudança:

- lista os projetos **ativos e abertos** do modelo (arquivados, concluídos e
  cancelados ficam fora), todos marcados; o admin desmarca os que não devem mudar;
- mostra, por projeto, o que vai acontecer: item **novo** (entra no fim da
  categoria), **vincular** (o projeto já tinha um avulso de mesmo nome),
  **renomear**, **categoria**, **peso**, **responsável** e **saiu do modelo**;
- onde o projeto ajustou peso ou responsável, **o valor do projeto fica** e a
  linha aparece como "mantido";
- item que saiu do modelo: sem andamento é apagado (pode-se trocar); **com
  andamento o admin escolhe** — apagar (perde o histórico), manter como avulso
  ou marcar N/A;
- exige **motivo** e a caixa de confirmação com o total de alterações.

Se o modelo ou um projeto mudar entre a prévia e a confirmação, a aplicação é
recusada e a prévia é refeita. Cada aplicação fica no **Histórico** do modelo
(quem, quando, motivo e o antes/depois de cada projeto; gestor também lê) e na
auditoria geral. Aplicar não conta como atualização do entregável (o alerta de
projeto parado não é enganado). A ordem do projeto não é propagada.

Entregáveis anteriores a este recurso foram ligados ao modelo **pelo nome**
(categoria + nome) na subida do servidor; o que não casou ficou avulso, e
avulso nunca é tocado pela aplicação.

**Tipos de projeto** (`tipos_projeto`) são cadastráveis: `OEM` e `Revenda` vêm
semeados, e admin/gestor criam outros na aba **Modelos** (ou pelo "+ novo tipo"
do formulário de projeto), opcionalmente copiando o modelo de um tipo existente.

- O projeto e o modelo guardam o **nome** do tipo, não o id. Renomear um tipo
  propaga o nome novo para os projetos (inclusive arquivados) e para o modelo.
- Tipo **em uso não é excluído** — arquivados contam. Troca-se o tipo dos
  projetos antes. Excluir um tipo leva junto o modelo de entregáveis dele.
- O nome tem no máximo 20 caracteres e é único sem diferenciar maiúsculas.
- O `tipo` da composição no módulo Custos (`OEM`/`Revenda`) é outro conceito —
  decide se há NRE — e não acompanha este cadastro.

## Um módulo para todas as áreas

Projetos serve PDE, PDR e INOV. O que separa uma área da outra é o **modelo**
do projeto — na tela, "tipo" se chama modelo.

- Cada modelo tem uma **área** (`tipos_projeto.area`, slug de
  [`areas.py`](../../areas.py)). A área do projeto é **derivada** do modelo, não
  guardada no projeto: não há como existir um `PDR RUO` marcado como PDE.
  Trocar a área de um modelo leva junto todos os projetos dele.
- Projeto antigo **sem modelo** (`tipo = ""`) conta como **PDE**
  (`AREA_PROJETO_LEGADO`) — até a unificação o módulo só existia lá. Continua
  editável; projeto novo exige modelo, e quem já tem modelo não volta a ficar
  sem.
- O **filtro de modelos**, acima das abas, recorta Dashboard, PMO, Projetos, o
  sino e os exports. Na API são `?tipo=` e `?area=` repetíveis, somados por
  união, em `/api/projetos`, `/api/projetos/alertas`, `/api/entregaveis/resumo`
  e `/api/entregaveis/export`. Uma área sem nenhum modelo devolve **vazio**, e
  não o portfólio inteiro.
- Os cards de Projetos nos hubs (PDE, INOV) e o link na sidebar do PDR abrem
  `/projetos?area=<slug>`. A URL acompanha o filtro; a última escolha fica no
  `localStorage` do navegador.

> O filtro é **recorte de visão, não controle de acesso**. Quem vê o quê
> continua decidido só pelo papel (ver *Perfis* abaixo). Separar por área no
> servidor está descrito como trabalho futuro em
> [`PLANO_projetos_unificados.md`](../planos/PLANO_projetos_unificados.md).

## Linha de base: replanejar ≠ maquiar

O ponto mais importante do módulo. Três campos formam a **baseline**:

    data_inicio_prev · data_fim_prev · orcamento

Mexer em qualquer um deles **não sobrescreve** o valor: cria uma versão nova em
`projeto_baseline`, com autor e motivo, e preserva a anterior.

Sem isso, replanejar seria indistinguível de ajustar o alvo até o indicador
ficar verde. Com isso, a pergunta "quantas vezes este projeto foi replanejado?"
tem resposta.

## Visão mensal e EVM

`projeto_mensal` guarda um registro por `(projeto, competência)`, onde
competência é `YYYY-MM`. Os percentuais são **acumulados** até o mês — é a
curva-S:

| Campo | Significa |
|---|---|
| `pct_previsto` | % planejado acumulado |
| `pct_realizado` | % executado acumulado |
| `custo_mes` | R$ gastos **no** mês (incremental) |
| `custo_acumulado` | R$ acumulados (AC) — derivado |

Daí saem os índices de Earned Value:

- **SPI** — desempenho de prazo (executado ÷ previsto)
- **CPI** — desempenho de custo (valor agregado ÷ custo real)

Semáforo: **≥ 0,95** ok · **0,85 – 0,95** atenção · **< 0,85** crítico.

> Cuidado ao ler `custo_mes` e `custo_acumulado` juntos: um é incremental e o
> outro derivado. Somar a coluna acumulada dá um número sem significado.

## Evolução

`projeto_snapshot` guarda uma foto diária de avanço, previsto, SPI, CPI, AC e
BAC. Existe porque, sem ela, todo indicador seria recalculado com as datas de
**hoje** — mexer no cronograma reescreveria o passado, e não haveria série
temporal de SPI/CPI.

## Perfis: o modo restrito do técnico

O módulo é de gestão. O técnico entra em **modo restrito**:

- enxerga apenas os projetos onde tem entregáveis atribuídos;
- **não vê nenhum valor em R$** — orçamento, custo mensal, AC, BAC;
- só altera status e percentual dos entregáveis que são dele.

| Ação | Papel |
|---|---|
| Ver tudo, criar/editar projeto, lançar custo, congelar baseline | admin e gestor |
| Ver os próprios entregáveis e atualizá-los, sem valores | técnico |
| Nada | leitura |

## Alertas e exportação

`/api/projetos/alertas` devolve fatos acionáveis: atrasos, estouros de orçamento
e projetos parados. `/api/entregaveis/export` gera Excel com os entregáveis e
uma aba de PMO.

Nos exports, **concluído é o que o gestor marcou em Situação**, não o que o
avanço calcula. É comum dar um projeto como concluído com 99%, porque sobrou um
entregável que não vai mais ser feito. O PDF do portfólio conta, filtra e
desenha a rosca pela situação, e o Excel traz a coluna Situação com o rótulo da
tela. O avanço % continua em sua própria coluna.

## Pontos de atenção

- **As datas do projeto são texto ISO**, não `Date` — padrão herdado. `_parse_iso`
  aceita `2026-06-15`, `2026-06`, `15/06/2026` e `2026`.
- **Excluir projeto é arquivar** (`ativo=False`), com rota de restauração.
- **`custo_acumulado` é derivado**: recalculado a partir de `custo_mes`, não
  digitado. Escrevê-lo direto cria inconsistência silenciosa na curva-S.
- **Editar a baseline sem motivo** gera um motivo automático descrevendo os
  campos alterados — a versão nunca fica sem justificativa.
