# ADR-0005 — Rate limit em memória de processo

**Status:** vigente · **Alcance:** segurança, escala

## Contexto

`/api/auth/login` e `/api/auth/primeiro-acesso` são as duas portas abertas do
sistema e não tinham limite nenhum. Dava para varrer senhas e — pior — códigos
de ativação, que são 8 caracteres que valem uma conta inteira, na velocidade da
rede. O bcrypt em 12 rounds tornava isso lento, mas lento não é impedido.

## Decisão

Contador em memória de processo, em [`ratelimit.py`](../../../ratelimit.py).
Sem Redis, sem tabela, sem dependência nova.

Três regras que valem tanto quanto o mecanismo:

- **Só tentativa falha conta.** Contar acerto puniria o uso normal — quem entra
  certo não está atacando.
- **A contagem é por (rota, identidade, IP).** Só por IP, um usuário trancaria o
  login de todos os colegas do mesmo escritório; só por identidade, dava para
  trancar a conta de alguém de propósito.
- **As rotas do kill switch são mais apertadas** (3 tentativas / 15 min) que o
  login (5 / 5 min), porque a senha-mestra é o último recurso.

Isso só é correto porque **o app roda em um processo** — waitress com threads.
As threads compartilham o dicionário.

## Consequências

**Uma segunda instância quebra o mecanismo.** Cada processo teria seu contador,
e o limite efetivo viraria N × o configurado. É um dos três pontos que assumem
instância única (com [ADR-0008](ADR-0008-agendador-embutido.md) e o cache do
kill switch).

**Restart zera os contadores.** Um atacante com acesso a derrubar o serviço
contorna o limite — mas quem consegue derrubar o serviço já tem problema maior.

**Atrás de proxy, `TRUST_PROXY=1` deixa de ser opcional.** O cloudflared roda na
mesma máquina que o app: sem confiar em `X-Forwarded-For`, toda requisição chega
de `127.0.0.1` e os limites *por IP* viram limites **globais**. Três tentativas
erradas de qualquer pessoa trancariam a rota de desbloqueio do kill switch para
todo mundo. Está avisado em [ACESSO_REMOTO.md](../../ACESSO_REMOTO.md) e no
`.env.example`.

## Alternativas descartadas

**Redis.** Resolve o multi-instância e a persistência, mas adiciona um serviço
para instalar, monitorar e reiniciar num servidor Windows que hoje tem app e
banco — para um sistema de dezenas de usuários.

**Tabela no banco.** Uma escrita por tentativa de login, incluindo as falhas que
um ataque produz em rajada: o mecanismo de defesa viraria o vetor de carga.

**`flask-limiter`.** Dependência nova para o que cabe em 150 linhas, e o padrão
dela (contar toda requisição, não só a falha) é justamente o que se quis evitar.
