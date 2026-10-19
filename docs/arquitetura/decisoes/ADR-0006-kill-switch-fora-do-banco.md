# ADR-0006 — Os segredos do kill switch ficam fora do banco

**Status:** vigente · **Alcance:** segurança, operação

## Contexto

Existe uma classe de incidente — credencial vazada, máquina comprometida,
suspeita de acesso indevido — em que desligar o sistema sai mais barato que
investigar com ele no ar. E quem precisa desligar pode não estar na frente do
servidor: pode ser fim de semana, pode ser pelo celular.

Um "modo manutenção" comum não serve: ele normalmente deixa o admin passar, e o
cenário em questão é justamente aquele em que não se confia em quem está
logado — inclusive num admin.

## Decisão

Um gatilho externo derruba o sistema inteiro; só a senha-mestra o traz de volta.
Implementado em [`killswitch.py`](../../../killswitch.py).

Travado, **tudo** responde `423`: API, páginas e WebSocket, inclusive para admin
e para quem já estava logado. Só continuam de pé as rotas do próprio kill switch
e `/api/version` (health check). Destravar encerra toda sessão anterior à trava.

**Os dois segredos vivem no `.env`, como hash bcrypt** — `DOCTRACK_KILL_TOKEN_HASH`
e `DOCTRACK_UNLOCK_HASH` — e nunca no banco. Se o motivo da trava for o banco
comprometido, um segredo guardado nele não vale nada.

Sem as duas variáveis definidas, o gatilho **recusa travar**: travar sem senha
de volta é destruir o sistema, não protegê-lo.

## Consequências

**A senha-mestra tem que ser guardada fora do servidor.** Perdê-la com o sistema
travado significa editar o `.env` na máquina — que é exatamente o acesso que o
incidente pode ter tirado.

**O guardião roda em todo request** (`before_request`), então o estado da trava
é consultado a cada chamada, inclusive de estático. Daí o cache de
`DOCTRACK_LOCK_TTL` segundos (padrão 3): é o atraso máximo entre disparar o
gatilho e o sistema parar. Baixar aumenta a carga no banco.

**O cache é de processo** — mais um ponto que assume instância única, junto com
[ADR-0005](ADR-0005-ratelimit-em-memoria.md) e
[ADR-0008](ADR-0008-agendador-embutido.md).

**O WebSocket precisou de checagem própria.** O handshake do Socket.IO não passa
pelo `before_request` do Flask; sem a checagem explícita em `on_connect`, o
tempo real seguiria entregando eventos com o sistema travado.

**As rotas do kill switch são públicas por necessidade.** Precisam funcionar
justamente quando ninguém consegue logar. São a superfície mais sensível do
sistema, e por isso têm o limite de tentativa mais apertado (3 / 15 min).

## Alternativas descartadas

**Flag no banco, sem senha.** Não protege do cenário principal (banco ou
credencial comprometidos) e permite que quem entrou destrave.

**Parar o serviço Windows.** Exige acesso à máquina — indisponível justamente
no fim de semana em que o incidente aparece — e não encerra as sessões: ao
voltar, os tokens antigos continuam valendo.
