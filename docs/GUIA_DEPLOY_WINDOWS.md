# Guia de Instalação do DocTrack no Servidor (Windows + PostgreSQL + LAN)

Este guia é para colocar o dashboard rodando **24 horas** numa máquina Windows,
acessível pela **rede interna** da empresa, usando banco **PostgreSQL**.

> Leia na ordem. Cada passo tem: **O que é**, **Por que** e **O que fazer**.
> Onde aparecer `<algo>`, troque pelo valor real (sem os sinais `< >`).

---

## Antes de começar — o que você vai precisar

- Acesso de **administrador** na máquina servidor (você já tem ✅).
- Saber o **IP do servidor** na rede. Para descobrir, abra o PowerShell e rode:
  ```powershell
  ipconfig
  ```
  Anote o "Endereço IPv4" (algo como `192.168.0.50`). É por ele que as outras
  pessoas vão acessar o dash.

---

## PASSO 1 — Instalar os 2 programas base

**O que é:** dois instaladores que o dash precisa.
**Por que:** sem eles nada roda (Python executa o código, PostgreSQL guarda os dados).

**O que fazer — baixe e instale, nesta ordem:**

1. **Python 3.12** (a versão do projeto está em `.python-version`; 3.11 também funciona)
   - Site: https://www.python.org/downloads/windows/
   - Baixe o "Windows installer (64-bit)" da última 3.12.
   - ⚠️ **MUITO IMPORTANTE:** na primeira tela do instalador, marque a caixinha
     **"Add python.exe to PATH"** antes de clicar em "Install Now".

2. **PostgreSQL** (o banco de dados)
   - Site: https://www.postgresql.org/download/windows/ (instalador da EDB).
   - Durante a instalação ele vai pedir uma **senha para o usuário `postgres`**.
     **Anote essa senha**, vamos precisar dela.
   - Pode aceitar a porta padrão `5432` e desmarcar o "Stack Builder" no final.

> **Depois de instalar, FECHE e ABRA o PowerShell de novo** (para ele "enxergar"
> o Python). Teste digitando `python --version` — deve aparecer `Python 3.12.x`.

> **Não instale o GTK3 Runtime.** Até jul/2026 este guia pedia o GTK3 como terceiro
> item, dizendo que sem ele "a exportação de PDF deixa de funcionar". Não é verdade:
> o PDF é gerado **no navegador** com jsPDF. O caminho que usava GTK
> (`/api/report/pdf` → WeasyPrint) foi **removido do código** na limpeza de jul/2026,
> junto com a função órfã `exportKPIs()` que era sua única chamadora — nenhum botão
> a invocava. Instalar o GTK3 são ~200 MB que não mudam nada.

---

## PASSO 2 — Copiar o código do dash para o servidor

**O que é:** trazer os arquivos do projeto para uma pasta limpa no servidor.
**Por que:** não use a pasta do OneDrive — ela carrega lixo pesado e o arquivo de
senhas. Vamos para `C:\apps\doctrack`.

**Opção A — se o projeto está no Git (recomendado):**
```powershell
mkdir C:\apps
cd C:\apps
git clone <url-do-repositorio> doctrack
```

**Opção B — copiar na mão (pen drive / rede):**
- Crie a pasta `C:\apps\doctrack`.
- Copie para dentro dela: todos os arquivos `.py` da raiz, o `requirements.txt`,
  o `VERSION`, o `.env.example` e as pastas `templates`, `static`, `migrations`,
  `scripts`, `data` e as dos módulos — `pdr`, `custos`, `tempos`, `fluxos`,
  `notificacoes` e `cadernos`. Faltando uma delas, o serviço não sobe.
- **NÃO copie**: `venv`, `node_modules`, `dist`, `backups`, `logs`, `arquivos`,
  o `doctrack.db`, nem o arquivo `.env` (vamos criar um `.env` novo no servidor,
  no passo 4).

> Sem Git, toda atualização futura é repetir essa cópia à mão. Prefira a
> Opção A sempre que o servidor alcançar o repositório.

---

## PASSO 3 — Criar o banco de dados

**O que é:** criar um "espaço" chamado `doctrack` dentro do PostgreSQL e um usuário
para o dash.
**Por que:** o dash precisa de um lugar próprio para gravar os dados.

**O que fazer:** abra o PowerShell e entre no PostgreSQL (vai pedir a senha do
`postgres` que você anotou no Passo 1):
```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres
```
> Se a versão não for a 16, troque `16` pela pasta que existir em
> `C:\Program Files\PostgreSQL\`.

Agora, **dentro do psql** (o prompt muda para `postgres=#`), cole estas 4 linhas,
trocando a senha por uma de sua escolha:
```sql
CREATE DATABASE doctrack;
CREATE USER doctrack_app WITH PASSWORD '<senha-do-app>';
GRANT ALL PRIVILEGES ON DATABASE doctrack TO doctrack_app;
\q
```
A última linha (`\q`) sai do psql. **Anote a `<senha-do-app>`** que você escolheu.

---

## PASSO 4 — Configurar e instalar (script automático)

**O que é:** o script `scripts/deploy_windows.ps1` faz o trabalho repetitivo: cria o
ambiente Python, instala as dependências, cria o arquivo de senhas (`.env`),
prepara o banco e instala o serviço que roda 24h.
**Por que:** são muitos comandos — o script evita erro de digitação.

**O que fazer:**
1. Abra o PowerShell **como Administrador** (botão direito → "Executar como
   administrador").
2. Libere a execução de scripts só para esta janela:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```
3. Vá até a pasta e rode o script:
   ```powershell
   cd C:\apps\doctrack
   .\scripts\deploy_windows.ps1
   ```
4. O script vai **perguntar a senha do banco** (a `<senha-do-app>` do Passo 3) e
   vai gerar sozinho a chave de segurança (`JWT_SECRET`). É só seguir o que ele
   pedir na tela.

Quando terminar sem erros vermelhos, o dash já está rodando como serviço.

---

## PASSO 5 — Testar

**No próprio servidor:** abra o navegador em `http://localhost:5000`.

**De outro computador da empresa:** abra `http://<IP-do-servidor>:5000`
(o IP que você anotou lá no começo, ex: `http://192.168.0.50:5000`).

Se abrir a tela de login, **deu certo!** 🎉

### Criar a senha do administrador

O banco novo nasce com **uma** conta, de administrador, **sem senha**. O e-mail
dela é o de `DOCTRACK_ADMIN_EMAIL` no `.env` (defina antes da primeira subida;
sem a variável, é `admin@pde.com`). O código de ativação sai uma única vez no
log da primeira subida:

```powershell
Select-String -Path C:\apps\doctrack\logs\out.log -Pattern "PRIMEIRA CONTA"
```

Na tela de login, clique em **Primeiro acesso ou esqueci a senha**, informe o
e-mail, o código e a senha nova (letra, número e caractere especial). O código
vale 7 dias. Se ele se perder antes de ser usado, não há outro administrador
para resetar: apague o banco recém-criado e suba de novo.

Não existem mais contas de demonstração em produção. Elas só são criadas com
`DOCTRACK_CONTAS_DEMO=1`, que é para desenvolvimento e homologação.

> Se abrir no servidor mas não em outra máquina, é o **firewall** — o script já
> tenta liberar a porta 5000, mas confirme que rodou como Administrador.

---

## Depois: tarefas do dia a dia

### Atualizar o dash quando houver mudanças
A ordem é **backup → `git pull` → restart**. O bloco pronto, que para no
primeiro erro, está no
[RUNBOOK](operacao/RUNBOOK.md#publicar-uma-versão-nova) — use o de lá, para os
dois documentos não divergirem.

### Ligar / desligar / ver status do serviço
```powershell
nssm restart DocTrack    # reiniciar
nssm stop DocTrack       # parar
nssm start DocTrack      # iniciar
Get-Service DocTrack     # ver se está rodando
```

### Ver os logs (se algo der errado)
Os registros ficam em `C:\apps\doctrack\logs\out.log` e `err.log`.

### Backup automático do banco
O script `scripts/gerar_backup.ps1` salva o banco **e** a pasta dos arquivos
enviados em `C:\apps\doctrack\backups`. O `deploy_windows.ps1` **não** agenda
esse backup: registre a tarefa diária uma vez, no PowerShell como Administrador.

```powershell
$acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-ExecutionPolicy Bypass -File "C:\apps\doctrack\scripts\gerar_backup.ps1"'
Register-ScheduledTask -TaskName "DocTrack - Backup Diario" -Action $acao -Trigger (New-ScheduledTaskTrigger -Daily -At 02:00) -User "SYSTEM" -RunLevel Highest
```

Como conferir que ele está rodando, o que ele não cobre e como restaurar estão
no [RUNBOOK](operacao/RUNBOOK.md#backup).

---

## Resumo rápido (cola de bolso)

| Quero... | Comando |
|---|---|
| Acessar o dash | `http://<IP-do-servidor>:5000` |
| Reiniciar | `nssm restart DocTrack` |
| Ver status | `Get-Service DocTrack` |
| Atualizar código | backup + `git pull` + `nssm restart DocTrack` ([RUNBOOK](operacao/RUNBOOK.md#publicar-uma-versão-nova)) |
| Fazer backup | `powershell.exe -ExecutionPolicy Bypass -File .\scripts\gerar_backup.ps1` |
