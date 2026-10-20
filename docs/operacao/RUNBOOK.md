# Runbook operacional

O que fazer quando o DocTrack em produção precisa de atenção. Feito para ser
lido às duas da manhã: comandos primeiro, explicação depois.

Para **instalar** numa máquina nova, o documento é outro:
[GUIA_DEPLOY_WINDOWS.md](../GUIA_DEPLOY_WINDOWS.md).

---

## Cartão de identidade da produção

| | |
|---|---|
| Máquina | servidor Windows, `C:\apps\doctrack` |
| Serviço | `DocTrack`, gerido por **NSSM** |
| Servidor WSGI | **waitress**, apontando para `wsgi:app` (nunca `servidor:app`) |
| Porta | 5000 |
| Banco | PostgreSQL em `localhost:5432/doctrack`, usuário `doctrack_app` |
| Arquivos enviados | pasta `DOCTRACK_ARQUIVOS` (padrão: `arquivos\` ao lado do `.env`) |
| Documentos técnicos | `\\loccus-srv03\Projetos$\Engenharia` — **fora** do sistema |
| Logs | `C:\apps\doctrack\logs\out.log` e `err.log` |
| Backups | `C:\apps\doctrack\backups`, diário às 02:00 |
| Acesso externo | túnel Cloudflare (opcional) — [ACESSO_REMOTO.md](../ACESSO_REMOTO.md) |

---

## O básico

Ver se está de pé:

```bash
Get-Service DocTrack
```

Reiniciar:

```bash
nssm restart DocTrack
```

Parar e iniciar:

```bash
nssm stop DocTrack
```

```bash
nssm start DocTrack
```

Ver o log de erro, ao vivo:

```bash
Get-Content C:\apps\doctrack\logs\err.log -Tail 50 -Wait
```

### Tamanho dos logs

O `scripts/deploy_windows.ps1` instala o serviço com rotação: o log gira na
subida e, com o serviço no ar, ao passar de 10 MB (o antigo ganha a data no
nome). Num serviço instalado antes disso, ligue a rotação uma vez — vale a
partir do próximo início do serviço:

```bash
nssm set DocTrack AppRotateFiles 1
```

```bash
nssm set DocTrack AppRotateOnline 1
```

```bash
nssm set DocTrack AppRotateBytes 10485760
```

Os arquivos girados (`err-AAAAMMDDThhmmss.mmm.log`) não são apagados
sozinhos: confira a pasta `logs\` no checklist mensal.

O `err.log` cheio do traceback `Cannot obtain socket from WSGI environment` era
o Socket.IO tentando WebSocket sob o waitress, que não suporta. Hoje o app
detecta o waitress e usa só polling (ver `servidor.websocket_disponivel`;
`DOCTRACK_WEBSOCKET=0/1` força). Se esse traceback voltar, alguma tela está
abrindo o socket com `transports` começando por `"websocket"`.

### Threads do waitress

Só polling tem um custo: cada aba aberta do DocTrack segura **uma thread do
waitress** o tempo todo (o pedido de polling fica parado até 25 s esperando
evento, e a aba logo manda outro). O padrão do waitress é 4 threads — quatro
abas abertas e todo o resto do sistema espera na fila. O sinal no `err.log` é
`WARNING:waitress.queue:Task queue depth is N`.

O `scripts/deploy_windows.ps1` instala com `--threads=32`. Num serviço instalado
antes disso, ajuste uma vez e reinicie (dimensione pelo número de abas abertas
ao mesmo tempo, com folga):

```bash
nssm set DocTrack AppParameters "--listen=0.0.0.0:5000 --threads=32 wsgi:app"
```

```bash
nssm restart DocTrack
```

Confirmar que o app responde (não precisa de login, e funciona até travado):

```bash
curl http://localhost:5000/api/version
```

---

## Publicar uma versão nova

```bash
cd C:\apps\doctrack; git pull; .\venv\Scripts\pip install -r requirements.txt; nssm restart DocTrack
```

Não há passo de migração: o schema é aplicado na subida
([ADR-0002](../arquitetura/decisoes/ADR-0002-schema-no-startup.md)). O que
**precisa** ser conferido depois é o log da subida — os backfills e o
`_sync_schema()` falham em voz alta ali, e o app pode subir mesmo assim.

```bash
Select-String -Path C:\apps\doctrack\logs\err.log -Pattern "ERROR|Traceback" | Select-Object -Last 20
```

**Antes de publicar**, tenha um backup do dia (veja abaixo). Mudança de schema é
aditiva e idempotente por convenção, mas convenção não é garantia.

### Voltar atrás

```bash
cd C:\apps\doctrack; git log --oneline -5
```

```bash
cd C:\apps\doctrack; git checkout <sha-anterior>; nssm restart DocTrack
```

> **Voltar o código não desfaz o schema.** As colunas criadas pela versão nova
> continuam no banco. Como as mudanças são aditivas, a versão antiga convive com
> elas — é justamente por isso que a regra é nunca fazer `DROP`. Se a versão nova
> tiver *escrito dados* incompatíveis, aí o caminho é restaurar o backup.

---

## Backup

Rodar manualmente:

```bash
cd C:\apps\doctrack; .\scripts\gerar_backup.ps1
```

O script gera o `pg_dump` completo, **espelha a pasta de arquivos enviados** e
apaga dumps com mais de 30 dias (o espelho dos arquivos é cumulativo). Roda
sozinho às 02:00 pela tarefa agendada `DocTrack - Backup Diario`.

Conferir que os backups estão de fato acontecendo:

```bash
Get-ChildItem C:\apps\doctrack\backups | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name, Length, LastWriteTime
```

Um `.sql` de tamanho muito menor que o do dia anterior é sinal de dump
interrompido — vale abrir e olhar o fim do arquivo.

### O que o backup NÃO cobre

Três lacunas reais, em ordem de gravidade:

1. **Os documentos técnicos não estão no backup.** O banco guarda o *caminho*;
   os `.docx` e `.pdf` vivem em `\\loccus-srv03\Projetos$\Engenharia` e dependem
   do backup daquele servidor, que é de outra equipe. Restaurar o `pg_dump` traz
   o sistema de volta, **não os documentos**
   ([ADR-0001](../arquitetura/decisoes/ADR-0001-caminho-no-banco.md)).
2. **Os dumps ficam no mesmo disco do banco.** Uma falha de disco leva os dois.
   Copiar os `.sql` para fora da máquina continua pendente.
3. **Banco e arquivos enviados restauram juntos ou não restauram.** O script
   cuida dos dois; uma restauração manual que traga só o `.sql` deixa anexos
   apontando para blobs que não existem.

O guia de validação ANVISA exige "Backup, Restauração e Recuperação de Dados" —
os itens 1 e 2 são as lacunas a fechar antes de uma auditoria.

### Restaurar

```bash
nssm stop DocTrack
```

```bash
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U doctrack_app -h localhost -d doctrack -f "C:\apps\doctrack\backups\<arquivo>.sql"
```

Restaure **também** a pasta de arquivos enviados do mesmo dia, do espelho em
`backups\`, antes de subir o serviço. Depois:

```bash
nssm start DocTrack
```

O passo 5 de [DEPLOYMENT.md](../DEPLOYMENT.md) tem o procedimento detalhado e
continua sendo a referência de restauração, mesmo o resto daquele documento
sendo histórico.

---

## Trava de emergência (kill switch)

Para o incidente em que desligar sai mais barato que investigar com o sistema no
ar. Travado, **tudo** responde `423` — inclusive para admin, inclusive para quem
já estava logado.

**Travar**, de qualquer lugar, sem precisar do repositório nem estar logado:

```bash
curl -X POST https://SEU-SERVIDOR/api/kill-switch/lock -H "X-Kill-Token: SEU_TOKEN" -H "Content-Type: application/json" -d "{\"motivo\":\"credencial vazada\"}"
```

**Destravar**: acesse `/travado` no navegador e informe a senha-mestra, ou:

```bash
cd C:\apps\doctrack; .\venv\Scripts\python scripts\kill_switch.py unlock --url https://SEU-SERVIDOR
```

Destravar **encerra todas as sessões** abertas antes da trava: todo mundo entra
de novo. As duas ações ficam no log de auditoria sob o usuário `kill-switch`.

> As rotas aceitam 3 tentativas falhas por IP a cada 15 min. Atrás do túnel, se
> `TRUST_PROXY` não estiver ligado, **todas as requisições chegam do mesmo IP** e
> três erros de qualquer pessoa trancam a rota de desbloqueio para todo mundo.
> Ver [ADR-0005](../arquitetura/decisoes/ADR-0005-ratelimit-em-memoria.md).

---

## Sintomas

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Tudo responde `423` | kill switch acionado | destravar (acima); ver `audit_logs` sob `kill-switch` para o motivo |
| Serviço não sobe após deploy | erro em `init_app` (schema/backfill) | ler `err.log`; conferir se o `.env` tem `JWT_SECRET` e `DATABASE_URL` |
| App sobe mas nenhuma tela tem dado | `wsgi:app` trocado por `servidor:app` | banco não foi preparado — conferir a linha de comando do NSSM |
| Telas lentas com várias abas abertas; `Task queue depth` no `err.log` | threads do waitress tomadas pelo polling do Socket.IO | subir `--threads` (ver "Threads do waitress", acima) |
| "Fora das pastas permitidas" ao abrir documento | caminho fora de `DOCTRACK_FILE_ROOTS`, ou apelido de unidade não declarado | conferir `DOCTRACK_FILE_ROOTS` e `DOCTRACK_PATH_ALIASES` — use a forma **UNC** |
| Documento cadastrado, arquivo não abre | arquivo movido ou renomeado no share | rodar o diagnóstico (abaixo) |
| Login trancado para todos ao mesmo tempo | rate limit fundido num IP só | ligar `TRUST_PROXY=1` (obrigatório atrás de túnel/proxy) e reiniciar |
| Gráfico de evolução com um ponto só | agendador desligado ou serviço parado há dias | conferir `DOCTRACK_AGENDADOR`; rodar `scripts/snapshot_diario.py` |
| Câmbio desatualizado em Custos | falha na chamada ao Banco Central | conferir saída de internet do servidor e `DOCTRACK_CAMBIO` |
| Tela não atualiza sozinha | WebSocket bloqueado, ou mutação sem `publish_event` | ver console do navegador; ver [EVENTOS.md](../arquitetura/EVENTOS.md) |
| Nada abre de fora da rede | túnel caído | ver o serviço `cloudflared`; [ACESSO_REMOTO.md](../ACESSO_REMOTO.md) |

### Diagnóstico de cadastro × arquivos

Confronta o que está cadastrado com o que existe de fato no share e na
plataforma:

```bash
cd C:\apps\doctrack; .\venv\Scripts\python -c "import diagnostico, wsgi; print(diagnostico.rodar())"
```

Também existe pela interface, em Configurações. O timeout é
`DOCTRACK_DIAG_TIMEOUT` (padrão 20 s) — num share lento, aumente antes de
concluir que algo sumiu.

---

## Verificações periódicas

| Quando | O quê |
|---|---|
| Toda semana | backup do dia existe e tem tamanho coerente |
| Toda semana | `err.log` sem `Traceback` novo |
| Todo mês | uma restauração de teste em banco descartável — backup nunca testado não é backup |
| Todo mês | validade dos registros ANVISA vencendo (aparece no ICE dos equipamentos) |
| Todo mês | pasta `logs\`: apagar os logs girados antigos |
| A cada deploy | log da subida limpo; `/api/version` responde a versão nova |
| A cada mudança de `.env` | conferir contra [`../referencia/config.md`](../referencia/config.md) |

---

## Onde a senha-mestra está guardada

Fora do servidor. Se você está lendo este runbook porque precisa destravar o
sistema e não sabe onde ela está, essa é a falha a corrigir depois do incidente:
o kill switch recusa travar sem `DOCTRACK_UNLOCK_HASH` definido justamente
porque travar sem senha de volta é destruir, não proteger — mas nada obriga
alguém a lembrar onde guardou a senha em claro.
