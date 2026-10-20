# Módulo Equipamentos

Código: rotas em [`servidor.py`](../../servidor.py) · cálculo em
[`equipamentos_core.py`](../../equipamentos_core.py) · importador em
[`equipamentos_importer.py`](../../equipamentos_importer.py) · tela
`static/equipamentos.js`

## O que resolve

O equipamento é a **entidade central do sistema**. Documentos pertencem a ele,
consumíveis são compatíveis com ele, projetos o produzem, custos o precificam e
apontamentos de tempo podem apontar para ele.

O módulo responde três perguntas: o que temos cadastrado, o quanto o cadastro
está completo, e o quanto o produto está desenvolvido.

## Taxonomia

Três níveis, independentes do fabricante:

```mermaid
flowchart LR
    C["Categoria<br/>categorias_equipamento"] --> F["Família<br/>familias_equipamento"] --> E["Equipamento<br/>equipamentos"]
    E --> I["Itens/acessórios<br/>equip_itens"]
```

`sku` (SKU de Venda) é a **chave de junção** do sistema: é por ele que a
planilha mestra, o Pareto e os documentos se casam com o equipamento. Por isso é
indexado e por isso a checagem de duplicidade consulta por ele a cada gravação.

## ICE — Índice de Completude do Equipamento

Média simples de **três subíndices**. Mede a qualidade do *cadastro*, não do
produto.

| Subíndice | O que conta |
|---|---|
| **Cadastro** | SKU de Venda, SKU de Importação, nome técnico, fabricante, categoria, família |
| **Regulatório** | classificação (RUO/IVD) + registro, data e validade ANVISA |
| **Documental** | documentos finalizados ÷ documentos aplicáveis |

Três regras que não são óbvias:

**Validade ANVISA vencida não conta como preenchida.** Um registro vencido em
2023 dava 100% de regulatório na versão antiga — justamente na dimensão de
risco. Hoje o campo só conta se a data estiver válida.

**RUO não precisa de registro.** Equipamento de uso em pesquisa (`RUO`) tem só a
classificação no denominador regulatório; exigir número ANVISA dele penalizaria
um cadastro correto.

**Sem documentos carregados, o denominador documental são os 12 tipos.** Todo
equipamento nasce com os 12, então não há divisão por zero nem 100% falso.

Situação da validade: `ok` · `vencendo` (90 dias ou menos) · `vencido` ·
`sem_data`.

> **Situação do registro e classe de risco ficam fora do ICE de propósito.**
> Incluí-las derrubaria o índice da frota inteira de uma vez e tornaria
> ilegível o efeito de cada correção.

## IDP — Índice de Desenvolvimento de Produto

Seis itens de revisão. Três são marcados à mão no equipamento, três são
derivados do status dos documentos:

| Item | Origem |
|---|---|
| Cadastro | manual (`rev_cadastro`) |
| Estrutura | manual (`rev_estrutura`) |
| Descritivo | manual (`rev_descritivo`) |
| IT | derivado do documento `IT` |
| Checklists | derivado dos 4 checklists |
| Manual usuário | derivado do documento `Manual_Usuario` |

Cada item tem quatro estados: `Pendente` · `Em revisão` · `Revisado` · `N/A`.

    IDP = Revisados ÷ (6 − N/A) × 100

O `N/A` sai do denominador. O índice conta **só** "Revisado" — "Em revisão" não
conta como meio ponto.

## Onde o ICE e o IDP são calculados

No **servidor**, em `equipamentos_core.py`, com funções puras: recebem o
equipamento e a lista de documentos dele, sem tocar em `db.session` nem em
`request`.

Isso é deliberado. Antes os dois índices só existiam em
`static/equipamentos.js`, o que obrigava o cliente a baixar **todos** os
documentos do sistema só para dividir finalizados por aplicáveis, e faria
qualquer relatório reimplementar a mesma regra.

## Evolução

`equipamento_snapshot` guarda uma foto diária do ICE, dos seus três subíndices
e do IDP. É a série que alimenta os gráficos de evolução — e depende do
agendador estar de pé
([ADR-0008](../arquitetura/decisoes/ADR-0008-agendador-embutido.md)).

`equipamento_historico` é a trilha de-para de cada mudança, separada da série.

## Pastas e arquivos

**`equipamento_pastas`** materializa os grupos de pasta do share: manuais numa,
IT e checklists em outra, QI/QO/QD em outra. É o nível que faltava — antes só
havia "a pasta do equipamento", e qualquer exceção exigia override em cada
documento.

**`equipamento_arquivos`** são arquivos pendurados no *equipamento*, não em um
dos 12 tipos de documento. Duas categorias:

- **agregado** — laudo, certificado, datasheet;
- **software / firmware** — repositório de versões do fabricante, com teto de
  upload próprio (`DOCTRACK_UPLOAD_BIN_MAX_MB`, padrão 500 MB, porque instalador
  e imagem passam dos 80 MB com facilidade).

As duas tabelas de arquivo coexistem e não se misturam, mas **compartilham o
blob em disco**: o mesmo PDF enviado nos dois lugares ocupa um arquivo só
([ADR-0009](../arquitetura/decisoes/ADR-0009-blob-por-conteudo.md)).

**Remover um anexo não apaga o conteúdo.** A linha fica inativa (some da lista
e não é mais servida) e o blob continua em disco enquanto houver linha, ativa
ou inativa, que o referencie — é evidência anexada, e antes só voltava pelo
backup (Análise de Riscos, R-26). O mesmo vale para os arquivos de documento.

## Importação

`equipamentos_importer.py` lê a planilha mestra (`DOCTRACK_EQUIP_MASTER`) e
casa por SKU de Venda. `pareto_importer.py` traz o histórico de Pareto.
Todo lote fica registrado em `importacao_log`.

## Quem pode o quê

| Ação | Papel |
|---|---|
| Ver | qualquer membro da área PDE |
| Criar, editar, criar pasta | técnico para cima |
| Excluir equipamento ou pasta | admin e gestor |
| Reimportar planilha | admin e gestor |

## Pontos de atenção

- **As datas do equipamento são texto**, não `Date` — padrão herdado do projeto,
  porque chegam de origens diferentes (`YYYY-MM-DD` do formulário, `dd/mm/yyyy`
  das planilhas). `parse_data()` aceita quatro formatos.
- **Criar um equipamento cria 12 documentos** (`_ensure_docs_for_equip`). Não é
  efeito colateral inesperado: é o modelo.
- **Duplicidade é checada por SKU a cada gravação**, e existe
  `scripts/dedup_equipamentos.py` para o que já entrou duplicado.
