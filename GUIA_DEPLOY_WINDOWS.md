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

## PASSO 1 — Instalar os 3 programas base

**O que é:** três instaladores que o dash precisa.
**Por que:** sem eles nada roda (Python executa o código, PostgreSQL guarda os dados,
GTK gera os PDFs).

**O que fazer — baixe e instale, nesta ordem:**

1. **Python 3.11**
   - Site: https://www.python.org/downloads/release/python-3119/
   - Baixe o "Windows installer (64-bit)".
   - ⚠️ **MUITO IMPORTANTE:** na primeira tela do instalador, marque a caixinha
     **"Add python.exe to PATH"** antes de clicar em "Install Now".

2. **PostgreSQL** (o banco de dados)
   - Site: https://www.postgresql.org/download/windows/ (instalador da EDB).
   - Durante a instalação ele vai pedir uma **senha para o usuário `postgres`**.
     **Anote essa senha**, vamos precisar dela.
   - Pode aceitar a porta padrão `5432` e desmarcar o "Stack Builder" no final.

3. **GTK3 Runtime** (necessário só para gerar PDF)
   - Site: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases
   - Baixe o `.exe` mais recente e instale com as opções padrão.
   - 💡 Se não instalar isso, o dash funciona normalmente, **só a exportação de
     PDF deixa de funcionar**. Pode deixar para depois se quiser.

> **Depois de instalar, FECHE e ABRA o PowerShell de novo** (para ele "enxergar"
> o Python). Teste digitando `python --version` — deve aparecer `Python 3.11.x`.

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
- Copie para dentro dela **apenas**: todos os arquivos `.py`, e as pastas
  `templates`, `static`, `migrations`, `files`, mais o `requirements.txt`.
- **NÃO copie**: `venv`, `node_modules`, `dist`, nem o arquivo `.env`
  (vamos criar um `.env` novo no servidor, no passo 4).

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

**O que é:** o script `deploy_windows.ps1` faz o trabalho repetitivo: cria o
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
   .\deploy_windows.ps1
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

> Se abrir no servidor mas não em outra máquina, é o **firewall** — o script já
> tenta liberar a porta 5000, mas confirme que rodou como Administrador.

---

## Depois: tarefas do dia a dia

### Atualizar o dash quando houver mudanças
```powershell
cd C:\apps\doctrack
git pull                       # (se usou Git)
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
nssm restart DocTrack
```

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
Rode o script `gerar_backup.ps1` (ele cria um backup do banco em
`C:\apps\doctrack\backups`). Para rodar **todo dia automaticamente**, use o
Agendador de Tarefas do Windows apontando para esse script — peça ajuda que eu
configuro o agendamento.

---

## Resumo rápido (cola de bolso)

| Quero... | Comando |
|---|---|
| Acessar o dash | `http://<IP-do-servidor>:5000` |
| Reiniciar | `nssm restart DocTrack` |
| Ver status | `Get-Service DocTrack` |
| Atualizar código | `git pull` + `nssm restart DocTrack` |
| Fazer backup | `.\gerar_backup.ps1` |
