# Hub, sub-hubs e a casca visual

Código: [`hub.py`](../../hub.py) (os números) · [`areas.py`](../../areas.py)
(áreas e módulos) · telas `templates/hub.html` e `templates/subhub.html` com
`static/hub-vitrine.js` · camada visual dos módulos em `static/vitrine-tema.*` ·
menu em `static/menu-controle.*`.
Protótipos aprovados: [`mockup_hub_principal.html`](../mockups/mockup_hub_principal.html)
e [`mockup_hub_engenharia.html`](../mockups/mockup_hub_engenharia.html).

## O que resolve

É a primeira tela depois do login. Diz à pessoa onde ela pode entrar e, antes de
entrar, o que a espera em cada lugar.

- **Hub** (`/hub`) — uma vitrine por **área** (P&D Equipamentos, P&D Reagentes,
  Inovação).
- **Sub-hub** (`/hub/<área>`) — uma vitrine por **módulo** da área.

As áreas, os módulos de cada uma e o perfil mínimo de cada cartão saem de
`areas.py`, que é a fonte única. P&D Reagentes não tem sub-hub: o cartão leva
direto ao app do PDR, que tem a própria barra lateral.

## Como se usa

- Clicar num cartão da fileira **só troca a vitrine**. Clicar em qualquer parte
  da vitrine — ou apertar Enter com o cartão em foco — **entra**.
- No hub, os atalhos **"Ir direto para"** levam ao módulo sem passar pelo
  sub-hub. Área sem módulos em `areas.py` não mostra atalhos.
- A vitrine tem a mesma altura para todos os itens, para a tela não pular ao
  trocar de cartão.

## Os números

As duas telas pedem tudo numa chamada só, `GET /api/hub/resumo`. Cada bloco
segue **o mesmo corte de perfil do módulo que resume** — o que o perfil não
abre, não sai dali:

| Bloco | Quem recebe | O que traz |
|---|---|---|
| Equipamentos | todos | total, ativos, categorias |
| Documentos | todos | total, em andamento, atrasados, e os da própria pessoa |
| Missões | técnico para cima | cartões da pessoa, os atrasados dela, andamento da equipe |
| Tempos | técnico para cima | horas de hoje e da semana — **só as da própria pessoa** |
| Fluxos | técnico para cima | o que está com a pessoa agora (por área), em andamento, concluídos no ano |
| Projetos | admin e gestor | por área: projetos ativos, avanço médio, entregáveis atrasados |
| Custos | admin e gestor | composições, vigentes, rascunhos |

Duas regras que não são óbvias:

- **"Meus documentos" é por nome.** O responsável do documento é texto livre
  ("Ana", "Ana / Bruno"); conta o documento em andamento cujo responsável cita o
  nome da pessoa. Nome com menos de três letras não conta nada.
- **Um bloco que falha sai ausente**, e o erro vai para o log. Um número
  quebrado não pode derrubar a primeira tela depois do login.

O técnico entra em Projetos em modo restrito, mas o resumo não reproduz esse
recorte: o bloco de Projetos só existe para a gestão.

## Movimento

As telas animam **mesmo com "reduzir movimento" ligado no sistema**. É
deliberado: nos PCs da empresa o Windows costuma vir com os efeitos de animação
desligados, e respeitar a preferência deixava a tela de entrada parada para
quase todo mundo. Só a aba em segundo plano pausa tudo. `tests/test_hub.py`
impede que o corte volte.

Tudo é SVG e CSS, sem dependência externa — a CSP do sistema não permite CDN.

## O visual do hub nas telas de trabalho

Os módulos usam a mesma linguagem visual do hub por uma **camada opcional**:
a classe `vt` no `<body>` liga `static/vitrine-tema.css`, e a classe ao lado
dela (`m-docs`, `m-equip`… `a-pdr`) dá ao módulo a cor do cartão dele no hub.
Sem a classe `vt`, nada muda.

A camada entra por `templates/_vitrine_head.html`, incluído por `base.html` e,
à mão, pelos templates que têm `<head>` próprio. A ordem importa: depois do CSS
do módulo (a camada precisa vencê-lo) e antes de `_pwa_head.html` (o passe de
celular vence todo mundo).

## Menu de controle

Um só menu no canto superior direito do hub, dos sub-hubs e dos módulos: o botão
da pessoa logada, que ao passar o mouse (ou tocar) mostra voltar, atualizar,
tema, configurações (só admin) e sair, sempre na mesma ordem.

Os controles antigos de cada tela **continuam no DOM**, só escondidos quando o
menu monta: os scripts dos módulos ainda escrevem neles. Remover um deles quebra
o módulo, não o menu.

## Pontos de atenção

- **Sem tempo real.** Os números são os do momento em que a tela abriu. O sino
  segue com a consulta própria dele (ver [fluxos.md](fluxos.md#notificações-o-sino)).
- **Módulo novo precisa de três coisas** para aparecer direito: a entrada em
  `areas.py`, um bloco em `hub.py` (se tiver números) e a cor dele na camada
  visual.
