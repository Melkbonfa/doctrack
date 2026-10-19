# ADR-0004 — A página é casca; o controle de acesso está na API

**Status:** vigente · **Alcance:** front, segurança, leitura da referência de rotas

## Contexto

O sistema é multi-página: cada tela é um template Jinja e um arquivo JS. A
autenticação é JWT, guardado no cliente e enviado no cabeçalho `Authorization`.

Isso cria uma escolha para as rotas que servem HTML: elas exigem token — o que
significaria autenticação por cookie de sessão, um segundo mecanismo ao lado do
JWT — ou não exigem?

## Decisão

**As rotas de página não exigem token.** Elas devolvem a casca HTML, sem nenhum
dado. O JS carrega, valida o token no cliente e busca tudo por `/api/*`, que é
gatilhado por `@jwt_required` ou `@require_role`. Sem token válido, a página
redireciona para o login e nenhum dado chega a ser pedido.

Um mecanismo de autenticação só, em uma camada só.

## Consequências

**A referência de rotas engana quem lê rápido.** Dezenas de rotas aparecem sem
exigência de papel. Por isso `docs/referencia/api.md` as etiqueta como
`página (casca)` em vez de `público`, e `permissoes.md` conta a superfície
pública separando as duas — são seis rotas de API abertas, não dezenas.

**Um anônimo na rede consegue enumerar as telas que existem.** Ele vê a casca:
os nomes dos módulos, a estrutura da interface. Nenhum dado, nenhum nome de
usuário, nenhum documento. Risco aceito conscientemente para uma rede interna.

**Todo endpoint de dado novo precisa do seu decorator.** Não há gate de página
para servir de rede de segurança: uma rota `/api/*` sem decorator é dado aberto.
É o que o teste `test_rotas_publicas_sao_as_esperadas` protege — a lista de
rotas abertas é fixa e uma sétima quebra a suíte.

**O front precisa tratar 401/403 em toda chamada.** É `static/auth.js` que
centraliza isso.

## Alternativas descartadas

**Cookie de sessão nas páginas + JWT na API.** Dois mecanismos de autenticação,
duas formas de expirar, dois lugares para revogar no logout, e CSRF entrando no
escopo por causa do cookie.

**Renderizar dados no template.** Acabaria com a casca, mas jogaria fora o
modelo de atualização em tempo real (a tela deixaria de ser preenchida por JSON
que o Socket.IO sabe atualizar) e duplicaria em Jinja regras que hoje existem
uma vez só na API.
