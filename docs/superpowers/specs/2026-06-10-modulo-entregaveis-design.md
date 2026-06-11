# Design — Módulo de Entregáveis por Projeto (DocTrack)

**Data:** 2026-06-10
**Status:** aprovado em brainstorming (pendente revisão final do spec)
**Restrição:** NÃO commitar nada deste trabalho no git por enquanto — desenvolvimento e teste apenas local, até validação do usuário.

## Objetivo

Substituir a planilha `files/Entregáveis - Engenharia (rev fev).xlsm` (aba **"Controle Projetos 2026"**) por um módulo dentro do DocTrack para acompanhar entregáveis de cada projeto de engenharia, com visualização de atividades e responsáveis.

## Decisões tomadas

| Decisão | Escolha |
|---|---|
| Fonte da verdade | O dashboard. Importação única da planilha; depois tudo é editado no módulo. A planilha vira arquivo histórico (não é alterada). |
| Escopo da importação | Apenas a aba "Controle Projetos 2026". Outras abas (2025, Embalagens, Plásticos, Solicitações) ficam fora por ora. |
| Medição de progresso | Status (`na` / `pendente` / `em_progresso` / `concluido`) + percentual opcional quando em progresso. |
| Quem edita | Cada responsável atualiza o seu, em modo **flexível**: qualquer usuário `tecnico`+ pode editar qualquer entregável; o log de auditoria registra quem mudou o quê. |
| Layout | **B — Cards de projeto + drill-down** (validado visualmente). |
| Export | Botão "Exportar Excel" gera planilha limpa e formatada (openpyxl), sem fórmulas quebradas. |
| Arquitetura | **A — Módulo integrado**: mesma aplicação Flask e mesmo `doctrack.db`, blueprint próprio e página própria `/entregaveis`. Reusa JWT, papéis, log de auditoria, Socket.IO e o tema visual. |

## Modelo de dados (tabelas novas em `models.py`)

### `Projeto`
- `id`, `nome` (ex.: "Librarian 340"), `descricao`, `sku`, `moscow` (Must/Should/Could), `prioridade` (int), `consumivel` (bool), `lancamento` (data ou ano em texto), `ano` (int, 2026), `ativo` (bool, para arquivar)

### `Entregavel`
- `id`, `projeto_id` (FK), `tipo` (ex.: "Manual do Usuário PT", "Protótipo"), `categoria` (Produto / Sistema / Documentação / Capacitação / Marketing)
- `status`: `na` | `pendente` | `em_progresso` | `concluido`
- `percentual` (int 0–100, usado quando `em_progresso`)
- `responsaveis` (string, ex.: "Guilherme/Melk", vinda da planilha; vínculo com usuários reais pode vir depois)
- `atualizado_por` (email), `atualizado_em` (datetime)

### Avanço do projeto — calculado, nunca armazenado
Média sobre entregáveis aplicáveis (status ≠ `na`):
- `concluido` = 100 · `pendente` = 0 · `em_progresso` = `percentual`

### Conversão na importação (valor da célula → status)
- `1` → `concluido`
- `0` → `pendente`
- `NA` / `na` / `N/A` / vazio → `na`
- `0 < x < 1` → `em_progresso` com `percentual = round(x*100)`

## Importação

Script `importar_entregaveis.py` (rodado uma vez, manualmente):
1. Lê a aba "Controle Projetos 2026" com openpyxl (`data_only=True`).
2. Linha 2 = tipos de entregáveis (colunas); linha 3 = responsáveis padrão por coluna; linhas 4+ = projetos.
3. Captura colunas de metadados: Ordem, MoSCoW, Prioridade, Entregáveis (nome), Descrição, Consumível?, SKU, Lançamentos.
4. Ignora colunas de fórmula quebradas (`#REF!`, `#VALUE!`, `#DIV/0!`) e colunas de % mensal — o avanço passa a ser calculado pelo sistema.
5. Imprime resumo (X projetos, Y entregáveis, Z células ignoradas) para conferência.

## API (blueprint novo `entregaveis.py`)

| Endpoint | Método | Permissão | Função |
|---|---|---|---|
| `/api/projetos` | GET | leitura+ | Lista com avanço calculado; filtros MoSCoW/status/busca/responsável |
| `/api/projetos/<id>` | GET | leitura+ | Detalhe com entregáveis agrupados por categoria |
| `/api/projetos` | POST | admin/gestor | Criar projeto |
| `/api/projetos/<id>` | PUT/DELETE | admin/gestor | Editar / arquivar |
| `/api/entregaveis/<id>` | PUT | tecnico+ | Atualizar status/percentual/responsáveis (auditado) |
| `/api/entregaveis/resumo` | GET | leitura+ | Agregados para KPIs e visão por responsável |
| `/api/entregaveis/export` | GET | leitura+ | Excel limpo formatado |

- Toda edição grava no log de auditoria existente (quem, campo, valor antigo → novo) e emite evento Socket.IO para atualização em tempo real.

## Interface — página `/entregaveis`

Template novo (`templates/entregaveis.html`) + JS próprio (`static/entregaveis.js`) + reuso do tema escuro/ciano. Link "Entregáveis" no menu do dashboard e link de volta.

### Tela principal (cards)
- KPIs do ano: nº projetos, avanço médio, pendentes, concluídos
- Filtros: MoSCoW, faixa de avanço, busca por nome, responsável
- Cards: nome, badge MoSCoW, barra de avanço com %, lançamento, contagem de pendentes
- Ordenação: prioridade (padrão), avanço, nome

### Drill-down (detalhe do projeto)
- Cabeçalho: nome, descrição, SKU, lançamento, donut de avanço
- Entregáveis agrupados por categoria; linha = tipo · responsáveis · status com cor (cinza NA / vermelho pendente / amarelo em progresso com % / verde concluído) · última atualização
- Edição inline via popover (status/percentual/responsáveis); salvar → recalcula barra e emite tempo real
- Botão "Exportar Excel"

## Tratamento de erros
- Percentual fora de 0–100 → 400
- Status `concluido` ignora/zera percentual
- Token expirado → redireciona para login (comportamento atual)
- Importação idempotente-segura: aborta se já existirem projetos do ano 2026 (evita duplicar), a menos que receba flag `--substituir`

## Testes (pytest, padrão da pasta `tests/`)
- Cálculo de avanço com mistura de NA/pendente/progresso/concluído
- Conversão de valores da importação (1, 0, NA, 0.85)
- Permissões por papel em cada endpoint
- Validação de percentual e transições de status
- Export retorna xlsx válido

## Fora de escopo (por ora)
- Outras abas da planilha (2025, Embalagens, Plásticos, Solicitações de cadastro)
- Vínculo formal responsável ↔ conta de usuário (responsáveis ficam como texto)
- Sincronização contínua com o Excel (importação é única)
- Notificações de pendência/atraso
