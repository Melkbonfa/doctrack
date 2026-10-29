# Estudo — ligar projetos, entregáveis e o resto do DocTrack

Data: 2026-10-26 · Situação: **estudo para decisão**, nada implementado.
Ponto de partida: o branch de fluxos de revisão
([spec](../superpowers/specs/2026-10-26-fluxos-revisao-design.md)) e o
levantamento de ligação entre módulos feito na mesma conversa.

## 1. A pergunta

O objetivo é que tudo esteja interligado: criar um projeto deve fazer nascer o
card do equipamento (em Equipamentos e em Documentos), e o card deve se
completar à medida que os entregáveis do projeto avançam — com documentos,
missões e o fluxo de revisão andando juntos.

A primeira tentativa de desenho tratava entregável como documento. **Não é:**
dos 31 tipos de entregável que a engenharia usa, só 8 são documentos. Um
protótipo, um software, uma etiqueta e um treinamento também são entregáveis, e
cada um se prova pronto de um jeito diferente. Este estudo propõe como ligar
todos eles sem forçar nenhum a parecer documento.

## 2. O que existe hoje

| Ligação | Situação | Evidência |
|---|---|---|
| Projeto → entregáveis | sólida (FK, avanço calculado) | `models.Projeto.avanco` |
| Projeto ↔ equipamento | **não existe**. Os dois têm SKU, mas nada os junta | `Projeto.sku`, `Equipamento.sku` |
| Entregável ↔ documento | **não existe**. "Manual do usuário" no projeto e "Manual do Usuário PT" no Documentos são registros soltos | — |
| Entregável ↔ IDP do equipamento | **duplicado**. Cadastro, Estrutura e Descritivo são marcados à mão no equipamento *e* existem como entregáveis no projeto | `equipamentos_core.ITENS_IDP` |
| Documento → cartão de missão | sólida (o cartão muda de coluna com o status) | `missoes.sincronizar_cartoes_documento` |
| Cartão de missão → entregável | **não existe** (só equipamento, projeto ou documento) | `models.REF_TIPOS_CARTAO` |
| Horas → entregável / projeto | existe; hora em cartão quase nunca chega ao projeto | `tempos/core.resolver_projeto` |
| Custos → projeto e equipamento | existe no banco, invisível na tela de Projetos | `custos/models.Composicao` |
| Fluxo de revisão → documento ou entregável | existe (branch de fluxos), mas são dois fluxos possíveis para a mesma coisa | `fluxos/models.Fluxo` |
| Projeto PDR ↔ produto/KIT do PDR | **não existe** (previsto como "fora do plano") | `PLANO_projetos_unificados.md` |

Três observações que pesam no desenho:

- **O IDP já faz a tradução de que o entregável precisa.** `estado_revisao()`
  converte o status do documento em *Pendente / Em revisão / Revisado / N/A* e
  agrega os 4 checklists num item só. O espelho de status do entregável deve
  reaproveitar essa função, não reinventá-la.
- **Equipamento já guarda artefatos além dos 12 documentos**: anexos
  *agregados* (laudo, certificado, datasheet), o *repositório de software e
  firmware* e os *itens* (acessórios e consumíveis). É onde vários entregáveis
  que não são documento vão morar.
- O `PLANO_projetos_unificados.md` diz que "hoje o projeto se liga a
  equipamento e missão". No código isso não acontece; o plano deve ser
  corrigido junto com esta mudança.

## 3. O catálogo real de entregáveis

Tirado dos cabeçalhos da planilha que originou o módulo
(`Entregáveis - Engenharia (rev fev).xlsm`, abas 2025 e 2026, a mesma lista nas
duas). A categoria é a da planilha e do sistema; a **natureza** é a proposta
deste estudo (seção 4).

| Categoria | Entregável | Natureza proposta |
|---|---|---|
| Produto | Validação Técnica | Validação |
| Produto | Protótipo | Validação |
| Produto | Modelo Definitivo | Validação |
| Produto | Render (3D) | Peça de comunicação |
| Produto | Etiquetas | Peça de comunicação |
| Produto | Software Neutro | Software |
| Produto | Software Loccus Inglês | Software |
| Produto | Software Português | Software |
| Produto | Embalagem | Peça de comunicação |
| Produto | Validação Consumíveis | Validação |
| Produto | Acessórios | Validação |
| Sistema | Descrição Técnica | Cadastro |
| Sistema | Estrutura Mecânica | Cadastro |
| Sistema | Cadastro Produto | Cadastro |
| Sistema | Cadastro Acessórios | Cadastro |
| Sistema | Cadastro Consumíveis | Cadastro |
| Documentação | Manual original | Documento do fabricante |
| Documentação | Manual do Usuário Loccus | Documento controlado |
| Documentação | Manual do Usuário Loccus Espanhol | Documento controlado |
| Documentação | Manual de Serviços | Documento controlado |
| Documentação | QI/QO/QD versão Original | Documento do fabricante |
| Documentação | QI/QO/QD versão Loccus | Documento controlado |
| Documentação | IT | Documento controlado |
| Documentação | Checklists | Documento controlado (4 documentos) |
| Capacitação | Treinamento Manutenção | Capacitação |
| Capacitação | Treinamento Assessoria | Capacitação |
| Capacitação | Apresentação do Produto | Peça de comunicação |
| Capacitação | Treinamento Produção | Capacitação |
| Marketing | Marca | Peça de comunicação |
| Marketing | Catálogos | Peça de comunicação |
| Marketing | Vídeo DEMO | Peça de comunicação |

Totais: 6 documentos controlados, 2 do fabricante, 7 peças de comunicação,
3 softwares, 5 de cadastro, 5 de validação e 3 de capacitação.

Duas coisas saltam da tabela:

- **Categoria não é natureza.** "Apresentação do Produto" está em Capacitação mas
  é uma peça de arte; "Etiquetas" e "Embalagem" estão em Produto e também são.
  A natureza precisa ser um atributo próprio, não derivado da categoria.
- **O vai e volta de revisão não é exclusivo dos manuais.** Na planilha, a mesma
  pessoa que diagrama os manuais responde por Etiquetas, Embalagem, Software
  Loccus, Marca e Catálogos. O fluxo de revisão serve a todas as peças de
  comunicação, não só aos documentos.

## 4. A ideia central: todo entregável tem uma natureza

A **natureza** diz três coisas sobre o entregável:

1. **com o que ele se liga** (o *artefato*: o objeto real que o trabalho produz);
2. **como se prova que está pronto**;
3. **quem manda no status**.

| Natureza | Artefato (onde o trabalho mora) | Pronto quando | Fluxo de revisão padrão |
|---|---|---|---|
| **Documento controlado** | o documento do equipamento em Documentos (1 documento, ou os 4 checklists) | documento Concluído / Homologado | o do documento (Escrita → Diagramação → Revisão; IT com o pipeline PRE) |
| **Documento do fabricante** | anexo *agregado* do equipamento, com subtipo (Manual original, QI/QO/QD original) | arquivo anexado e conferido | Recebimento → Conferência |
| **Peça de comunicação** | arquivos do próprio entregável; o final aprovado é publicado nos anexos do equipamento | fluxo aprovado | Briefing → Criação → Revisão (devolve para Criação) |
| **Software** | repositório de software/firmware do equipamento, com variante (Neutro, EN, PT) | versão liberada no repositório | Desenvolvimento → Validação → Liberação |
| **Cadastro** | campos e itens do equipamento: IDP (`rev_cadastro`, `rev_estrutura`, `rev_descritivo`), acessórios (`equip_itens`), consumíveis compatíveis | item do IDP *Revisado* / cadastro completo | Preenchimento → Revisão (opcional) |
| **Validação** | evidência (relatório, laudo) + as atividades no Missões + páginas de caderno, se houver | evidência aprovada no fluxo | Execução → Relatório → Aprovação |
| **Capacitação** | registro do treinamento (data, participantes) + evidência (lista de presença) | registro com evidência | Preparação → Realização → Registro |

**Onde a natureza fica:** no **item do modelo de entregáveis**, junto com o
**alvo** (qual documento, qual campo do IDP, qual variante de software). O
entregável herda do modelo e pode sobrescrever quando é avulso. Assim, ajustar o
modelo OEM uma vez liga todos os projetos OEM, e "Aplicar o modelo aos projetos"
já sabe propagar.

**O vínculo é calculado, não guardado.** O artefato sai de *equipamento do
projeto + natureza + alvo*. Não há FK do entregável para o documento: trocar o
equipamento do projeto, ou o alvo no modelo, leva tudo junto sem nada para
dessincronizar.

## 5. O eixo projeto ↔ produto

O artefato de quase todas as naturezas mora no **produto**. Por isso a primeira
ligação a fazer é projeto ↔ produto.

**PDE — projeto ↔ equipamento.**
- **Projeto novo da área PDE:** escolhe o equipamento ou cria um na hora. A
  sugestão vem pelo SKU, e o equipamento novo nasce com os 12 documentos (já é
  assim). É o "card nasce com o projeto".
- **Projeto antigo:** ganha "Ligar equipamento", com prévia do que muda.
- **Mais de um projeto pode apontar para o mesmo equipamento.** Exemplos: a
  versão 2 de um produto, ou OEM e Revenda do mesmo item. Isso cria o problema
  da seção 7.1.

**PDR — projeto ↔ produto/KIT do PDR.** Mesmo princípio. A natureza *documento
controlado* do PDR aponta para os 4 documentos da apresentação (especificação,
descritivo, IT, manual), e "pronto" usa o conjunto `STATUS_OK` que o módulo já
define.

**Inovação.** Sem produto obrigatório. As naturezas *peça de comunicação* e
*validação* funcionam só com o próprio entregável, porque o artefato delas não
depende de equipamento.

**O card se completando.** O card do equipamento ganha "Desenvolvimento: N%
(projeto X ↗)", que é o avanço do projeto ligado. Os índices de hoje continuam
com o que medem: o ICE mede o cadastro, o IDP mede os seis itens de revisão.
Com o espelho da seção 6, o IDP e o projeto passam a contar a mesma história,
porque leem os mesmos artefatos.

## 6. Quem manda no status: uma regra só

> **O artefato manda; o entregável espelha.**

O entregável é a **visão de gestão**: peso, prazo previsto, responsável, curva-S
e EVM continuam no projeto. O **estado do trabalho** vem do artefato.

| Natureza | Pendente | Em progresso | Concluído | N/A |
|---|---|---|---|---|
| Documento controlado | documento no início do pipeline | etapas intermediárias (% pela etapa) | Concluído / Homologado (checklists: todos) | documento fora do escopo |
| Documento do fabricante | sem anexo do subtipo | anexado, não conferido | conferido | marcado N/A |
| Peça de comunicação / Validação / Capacitação | sem fluxo | fluxo andando (% pela etapa) | fluxo aprovado | marcado N/A |
| Software | sem versão | fluxo andando | versão liberada | marcado N/A |
| Cadastro | IDP *Pendente* | IDP *Em revisão* | IDP *Revisado* | IDP *N/A* |

**Como o espelho é feito:**

- **Gravando, não calculando na leitura.** Avanço, EVM, snapshots, curva-S,
  alertas e exports leem `entregavel.status` em dezenas de lugares. Recalcular em
  cada um seria frágil. O status é gravado por sincronização, como o cartão de
  missão já faz, e cada mudança entra no `entregavel_historico`, então a curva-S
  continua fiel.
- **Pontos de disparo:**
  - troca de status do documento (`aplicar_status_documento`, o PATCH genérico
    e o N/A do Escopo);
  - mudança manual no IDP;
  - anexo ou versão de software enviados;
  - passagem e encerramento de fluxo.
- **Mexer pelo projeto mexe no artefato.** No popover do entregável ligado, o
  status vira o do artefato. Mudar ali muda o documento ou o IDP, pelo mesmo
  caminho da tela de origem. O `PUT` do entregável recusa status e percentual
  quando há artefato, com uma mensagem dizendo onde mexer.
- **Ligar o que estava solto passa por prévia.** Ao ligar um projeto antigo a um
  equipamento, a tela lista os entregáveis cujo status vai mudar, por exemplo
  "Manual do usuário: concluído no projeto, Elaborar no documento". A pessoa
  confirma antes de o documento passar a mandar.

## 7. Os casos difíceis

### 7.1 Projeto novo sobre equipamento que já existe

Se a versão 2 de um produto liga ao equipamento da versão 1, o Manual do Usuário
já está *Concluído*. Espelhando o status sem mais nada, o entregável nasce
concluído, o que está errado: o projeto novo precisa de uma revisão do manual.

**Proposta: ciclo do projeto.** Para o projeto, o artefato só conta como pronto
se foi concluído **depois do início do projeto**. Para documentos isso usa
`documento.concluido_em`; para os fluxos, `fluxo.concluido_em`. Antes disso, o
entregável aparece como *pendente*, com a nota "documento concluído em dd/mm —
iniciar revisão?". Iniciar o fluxo reabre o documento para *Em andamento*. Hoje
o fluxo só tira o documento de *Elaborar*, então isso é uma mudança pequena nas
regras do fluxo.

### 7.2 Um entregável, vários artefatos

"Checklists" são 4 documentos. A regra é a do IDP: todos prontos → concluído;
algum andando → em progresso. Se um checklist estiver N/A, sai da conta.

### 7.3 Um artefato, vários entregáveis

Dois projetos sobre o mesmo equipamento espelham o mesmo documento. Com o ciclo
do projeto (7.1), cada um avalia "pronto para mim" pela própria data de início,
sem conflito.

### 7.4 Fluxo duplicado

Hoje o branch de fluxos permite um fluxo no entregável e outro no documento para
o mesmo trabalho. Com o vínculo, quando o entregável tem artefato, o painel do
entregável mostra **o fluxo do artefato** e o servidor recusa iniciar um
segundo. Fluxo no próprio entregável fica só para as naturezas cujo artefato é o
próprio fluxo (comunicação, validação, capacitação).

### 7.5 Escopo do equipamento

Ligar um projeto não deve marcar documentos como N/A sozinho, porque o N/A exige
motivo e muda os índices de todo mundo. A tela de ligação pode **sugerir** o
escopo ("o modelo deste projeto não tem QI/QO/QD — marcar N/A?") e a pessoa
confirma.

### 7.6 O que não fazer

- **Tabela polimórfica de vínculos** (entregável ↔ qualquer coisa, com FK
  genérica): seria uma segunda fonte de verdade e precisaria de faxina a cada
  exclusão. O vínculo calculado (seção 4) não tem o que dessincronizar.
- **Criar um quadro de missão por projeto automaticamente:** com dezenas de
  projetos, o Missões vira uma lista de quadros mortos. Melhor como opção na
  criação do projeto.
- **Copiar arquivos entre módulos:** os blobs já são endereçados por conteúdo
  (ADR-0009). Publicar no equipamento é criar uma linha apontando para o mesmo
  sha256, como o fluxo já faz ao aprovar documento.

## 8. O fluxo de revisão, revisitado

- **Um motor só, modelos por natureza.** O motor do branch de fluxos já serve.
  O que falta é o campo "Aplica-se a" no modelo de fluxo (naturezas e alvos),
  para o início sugerir o modelo certo: Manual para documentos de manual, Arte
  para peças de comunicação, Software, Validação, IT.
- **O fluxo mora no artefato quando ele existe** (o documento); nos outros
  casos, no entregável. O painel aparece nas duas telas e o sino é o mesmo.
- **Aprovar publica no artefato.**
  - documento: os arquivos finais entram na lista de arquivos (já é assim);
  - peça de comunicação: vai para os anexos do equipamento, numa categoria nova
    de arte;
  - software: vira versão no repositório, com a variante;
  - validação: o relatório vira anexo agregado (laudo).
- **Atividades.** O cartão de missão ganha vínculo com o **entregável** (estava
  no levantamento, onda 2). As atividades de uma validação ("montar bancada",
  "rodar 3 ciclos") ficam visíveis no popover do entregável, e as horas
  apontadas nelas chegam ao projeto pelo entregável.
- **Quadro do projeto (opcional).** Na criação do projeto, a opção "criar quadro
  de missão" monta um cartão por entregável ligado. Os cartões de documento
  andam sozinhos pela sincronização que já existe; os demais, pelo fluxo.

## 9. Navegação: os caminhos de volta

| Onde | Ganha |
|---|---|
| Projeto (modal) | equipamento ↗ · composição de custo ↗ · horas do projeto · quadro de missão ↗ |
| Entregável (popover) | artefato ↗ (documento, versão, anexo, item do IDP) · fluxo · atividades |
| Equipamento (card, nas duas telas) | projeto(s) ↗ · "Desenvolvimento N%" |
| Documento (ficha) | "entregável do projeto X ↗" |
| Sino | o mesmo para tudo: o aviso aponta para onde o trabalho mora |

O deep-link `/projetos?projeto=&entregavel=` do branch de fluxos e o `/?doc=` que
já existe cobrem a maioria desses caminhos.

## 10. Mudanças de dados (estimativa)

| Tabela | Coluna nova | Para quê |
|---|---|---|
| `projetos` | `equipamento_id` (FK, nula) | o eixo PDE |
| `projetos` | `pdr_produto_id` (FK, nula) | o eixo PDR (onda F) |
| `modelos_entregavel` | `natureza`, `alvo` | a natureza e o alvo do item |
| `entregaveis` | `natureza`, `alvo` (nulos = herda do modelo) | avulsos e exceções |
| `equipamento_arquivos` | `subtipo` | Manual original, QI/QO/QD original, arte, variante do software |
| `missao_cartoes` | `entregavel_id` (nula) | atividades do entregável |

Todas são colunas novas em tabelas existentes: entram no `_sync_schema` **e**
num script numerado em `migrations/` (ADR-0002). Nenhuma tabela nova é
necessária para o núcleo. A regra fica num módulo `vinculos.py`, com funções
puras (`artefato_do`, `estado_do_artefato`, `sincronizar`), no padrão de
`equipamentos_core.py`.

## 11. Roteiro em ondas

Cada onda entrega algo usável sozinha.

| Onda | Entrega | Depende de | Tamanho |
|---|---|---|---|
| **A** | Projeto ↔ equipamento (criar ou escolher, sugestão por SKU, caminhos de volta) · natureza e alvo no modelo de entregáveis, só cadastro | fluxos | M |
| **B** | Natureza *documento controlado*: espelho de status, fluxo do documento no entregável, ciclo do projeto (7.1), prévia ao ligar | A | M |
| **C** | Natureza *cadastro*: o IDP como artefato, fim da marcação dupla, acessórios e consumíveis | A | P |
| **D** | *Peça de comunicação* e *software*: fluxo no entregável que publica no equipamento (anexo de arte, versão no repositório) · "Aplica-se a" no modelo de fluxo | B | M |
| **E** | *Validação* e *capacitação*: evidência, cartão de missão ligado ao entregável, quadro do projeto opcional, páginas de caderno como evidência | D | M |
| **F** | PDR: projeto ↔ produto/KIT, documentos do PDR como natureza documento | B | M |

A **onda A + B** já entrega o que motivou o estudo: o projeto cria o card, o
manual do projeto é o manual do Documentos, e o fluxo e o sino são um só.

## 12. Decisões que dependem de você

1. **Projeto novo sobre equipamento existente** (7.1): o entregável começa
   pendente até uma revisão concluída dentro do projeto (recomendado), ou herda
   o status atual do documento?
2. **Lista de naturezas** (seção 4): as 7 cobrem o trabalho real? Falta alguma,
   por exemplo regulatório (registro ANVISA), que hoje não aparece na planilha
   mas existe no equipamento?
3. **IDP** (5 e C): o IDP continua com os 6 itens atuais, ou passa a refletir
   todos os entregáveis do projeto ligado?
4. **Categoria de anexo para arte** (8): os finais de Etiquetas, Embalagem,
   Catálogos etc. vão para o equipamento ou ficam só no projeto?
5. **Quadro de missão por projeto** (8): opção na criação, ou nunca?
6. **Ordem das ondas:** começar por A + B, como proposto?
