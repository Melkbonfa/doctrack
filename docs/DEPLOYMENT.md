# Guia de Implantação — Windows Server (DocTrack)

Este manual detalha o passo a passo para implantar a plataforma DocTrack em um ambiente Windows Server corporativo. A aplicação rodará em segundo plano (background) gerenciada pelo **PM2** e o banco de dados será mantido localmente em SQLite com backups rotativos automatizados.

---

## 🛠️ Requisitos Prévios no Servidor

Antes de iniciar, garanta que os seguintes softwares estão instalados no Windows Server:

1. **Python 3.10 ou superior:**
   - Faça o download em [python.org](https://www.python.org/downloads/windows/).
   - **IMPORTANTE:** Durante a instalação, marque a caixa **"Add python.exe to PATH"** na tela inicial do instalador.
2. **Node.js LTS (v18 ou v20+):**
   - Faça o download em [nodejs.org](https://nodejs.org/).
   - A instalação padrão do Node.js também instala o gerenciador de pacotes `npm` automaticamente.
3. **Liberar Execução de Scripts no PowerShell:**
   - Como Administrador, abra o PowerShell e execute o comando abaixo para permitir a execução dos scripts locais de setup:
     ```powershell
     Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine
     ```

---

## 📥 Passo 1: Copiar os Arquivos do Projeto
Crie uma pasta no servidor dedicada para a aplicação (ex: `C:\inetpub\wwwroot\dashboard_IT` ou `C:\doctrack`) e copie todos os arquivos do projeto para dentro desta pasta.

---

## 🚀 Passo 2: Executar o Script de Configuração

1. Abra o **PowerShell** (com privilégios de Administrador).
2. Navegue até a pasta do projeto:
   ```powershell
   cd C:\caminho\para\a-pasta-do-projeto
   ```
3. Execute o script de configuração:
   ```powershell
   .\scripts\setup_windows_server.ps1
   ```

**O que este script fará de forma automática:**
- Criará um ambiente virtual Python (`venv`) isolado.
- Instalará todas as bibliotecas necessárias (Flask, Pandas, SocketIO, etc.).
- Gerará um arquivo `.env` seguro com chave única para o token de autenticação (`JWT_SECRET`).
- Criará o banco de dados local `doctrack.db` inicializado e semeado.
- Iniciará o painel em segundo plano usando o gerenciador **PM2**.

---

## 🖧 Passo 3: Liberar o Acesso na Rede Local (Firewall)

Por padrão, o Windows Server bloqueia conexões externas na porta da aplicação (`5000`). Para permitir que outros computadores da sua rede corporativa acessem o dashboard:

Execute o comando a seguir no **PowerShell (como Administrador)** para criar uma regra de entrada no Firewall do Windows:

```powershell
New-NetFirewallRule -DisplayName "DocTrack Dashboard (Porta 5000)" -Direction Inbound -LocalPort 5000 -Protocol TCP -Action Allow
```

A partir desse momento, qualquer computador na mesma rede local poderá acessar o dashboard abrindo o navegador no endereço:
`http://[IP_DO_SERVIDOR]:5000`

---

## 🔄 Passo 4: Configurar o PM2 para Iniciar com o Windows (Boot do Servidor)

Para garantir que a aplicação inicie automaticamente se o Windows Server for reiniciado física ou virtualmente, configure o PM2 como um serviço de inicialização do Windows:

1. No terminal do PowerShell, instale o utilitário de inicialização:
   ```powershell
   npm install -g pm2-windows-startup
   ```
2. Registre-o no sistema operacional:
   ```powershell
   pm2-startup install
   ```
3. Salve o estado atual dos processos no PM2 para que ele saiba o que deve reiniciar:
   ```powershell
   pm2 save
   ```

*Nota: Se o servidor reiniciar, o Windows executará o serviço do PM2 que, por sua vez, ligará o dashboard DocTrack na porta 5000.*

---

## 💾 Passo 5: Agendar Backup Diário do Banco de Dados

Criamos o script `scripts/backup_doctrack.ps1` que realiza cópias rotativas do banco de dados na pasta `backups/` dentro do projeto, guardando os últimos 15 dias.

Para agendar a execução automática desse backup todos os dias às **22:00**:

1. Abra o **Agendador de Tarefas do Windows (Task Scheduler)**.
2. No menu direito, clique em **Criar Tarefa Básica... (Create Basic Task...)**.
3. **Nome:** `DocTrack - Backup Diário do Banco`
4. **Disparador (Trigger):** Diário (Daily) -> Defina o horário desejado (ex: `22:00:00`).
5. **Ação:** Iniciar um programa (Start a program).
6. No campo **Programa/script:** digite `powershell.exe`
7. No campo **Adicionar argumentos (opcional):** digite:
   ```plaintext
   -ExecutionPolicy Bypass -File "C:\caminho\completo\do-projeto\scripts\backup_doctrack.ps1"
   ```
8. No campo **Iniciar em (opcional):** digite o caminho completo da pasta do projeto (ex: `C:\caminho\completo\do-projeto`).
9. Finalize a criação. Nas propriedades da tarefa criada, marque a opção **"Executar estando o usuário conectado ou não"** e selecione a opção **"Executar com privilégios mais altos"**.

---

## 🩺 Monitoramento e Comandos Úteis do PM2

Comandos que você pode rodar a qualquer momento a partir da pasta do projeto para gerenciar a aplicação:

* **Ver o status do servidor (Ativo/Inativo/CPU/Memória):**
  ```powershell
  pm2 status
  ```
* **Acessar os Logs de erro em tempo real:**
  ```powershell
  pm2 logs doctrack-dashboard
  ```
* **Reiniciar a aplicação manualmente:**
  ```powershell
  pm2 restart doctrack-dashboard
  ```
* **Parar a execução temporariamente:**
  ```powershell
  pm2 stop doctrack-dashboard
  ```
