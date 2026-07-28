# ============================================================================
#  deploy_windows.ps1 — Instalação do DocTrack como serviço no Windows
# ----------------------------------------------------------------------------
#  O que faz (passo a passo, automatizado):
#    1. Cria o ambiente virtual Python (venv)
#    2. Instala as dependências (requirements.txt)
#    3. Cria o arquivo .env com as senhas/configurações
#    4. Inicializa as tabelas no banco PostgreSQL
#    5. Libera a porta 5000 no Firewall do Windows
#    6. Instala e inicia o serviço "DocTrack" (roda 24h, liga sozinho no boot)
#
#  Como usar (PowerShell COMO ADMINISTRADOR):
#    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#    cd C:\apps\doctrack
#    .\deploy_windows.ps1
#
#  -ComTarefaAgendada troca a thread interna de snapshots por uma Tarefa
#  Agendada do Windows (as duas fazem o mesmo; a thread e o padrao).
# ============================================================================

param(
    [switch]$ComTarefaAgendada
)

$ErrorActionPreference = "Stop"

# Raiz do projeto = pasta pai de scripts/
$Projeto = Split-Path -Parent $PSScriptRoot
$Porta   = 5000
$Servico = "DocTrack"

function Titulo($txt) { Write-Host "`n==== $txt ====" -ForegroundColor Cyan }
function OK($txt)     { Write-Host "  [OK] $txt"      -ForegroundColor Green }
function Aviso($txt)  { Write-Host "  [!]  $txt"      -ForegroundColor Yellow }

Write-Host "`n###############################################" -ForegroundColor Cyan
Write-Host "#   Instalacao do DocTrack - Windows Server   #" -ForegroundColor Cyan
Write-Host "###############################################"

# --- Verifica se está como Administrador ------------------------------------
$admin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    throw "Abra o PowerShell COMO ADMINISTRADOR e rode de novo."
}

# --- Verifica Python --------------------------------------------------------
Titulo "Verificando Python"
try   { $pv = (python --version) 2>&1; OK "Encontrado: $pv" }
catch { throw "Python nao encontrado. Instale o Python 3.11 e marque 'Add to PATH'." }

# --- PASSO 1: ambiente virtual ----------------------------------------------
Titulo "PASSO 1/6 - Criando ambiente virtual (venv)"
if (Test-Path "$Projeto\venv") {
    Aviso "venv ja existe, reaproveitando."
} else {
    python -m venv "$Projeto\venv"
    OK "venv criado."
}
$py  = "$Projeto\venv\Scripts\python.exe"
$pip = "$Projeto\venv\Scripts\pip.exe"

# --- PASSO 2: dependências --------------------------------------------------
Titulo "PASSO 2/6 - Instalando dependencias (pode demorar alguns minutos)"
& $py -m pip install --upgrade pip | Out-Null
& $pip install -r "$Projeto\requirements.txt"
OK "Dependencias instaladas."

# --- PASSO 3: arquivo .env --------------------------------------------------
Titulo "PASSO 3/6 - Configuracao (.env)"
$envFile = "$Projeto\.env"
if (Test-Path $envFile) {
    Aviso ".env ja existe. Nao vou sobrescrever (suas senhas estao preservadas)."
} else {
    # Senha do banco (a que voce criou no psql)
    $secSenha = Read-Host "Digite a senha do usuario 'doctrack_app' do PostgreSQL" -AsSecureString
    $senhaBanco = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secSenha))

    # Caminho dos arquivos de engenharia (Enter para o padrao)
    $fileRoots = Read-Host "Caminho da pasta de arquivos (Enter para 'P:\Engenharia')"
    if ([string]::IsNullOrWhiteSpace($fileRoots)) { $fileRoots = "P:\Engenharia" }

    # Gera JWT_SECRET aleatorio automaticamente
    $jwt = & $py -c "import secrets; print(secrets.token_urlsafe(48))"

    $conteudo = @"
JWT_SECRET=$jwt
DATABASE_URL=postgresql://doctrack_app:$senhaBanco@localhost:5432/doctrack
CORS_ORIGINS=*
DOCTRACK_FILE_ROOTS=$fileRoots
"@
    # UTF-8 SEM BOM, nao 'Set-Content -Encoding UTF8': no PowerShell 5.1 esse
    # parametro grava o BOM (EF BB BF) no inicio do arquivo, e o python-dotenv
    # o le como parte da primeira chave -- a variavel nasce chamada
    # "<BOM>JWT_SECRET" e JWT_SECRET chega vazio. O servico nao percebe (o NSSM
    # injeta as variaveis por conta propria), mas o PASSO 4 abaixo e qualquer
    # 'python servidor.py' morrem em "JWT_SECRET environment variable is
    # required" -- com a mensagem de erro apontando para a senha do banco.
    [System.IO.File]::WriteAllText(
        $envFile, $conteudo, (New-Object System.Text.UTF8Encoding $false))
    OK ".env criado (JWT_SECRET gerado automaticamente)."
}

# --- PASSO 4: inicializar banco ---------------------------------------------
Titulo "PASSO 4/6 - Inicializando tabelas no banco"
Push-Location $Projeto
try {
    & $py servidor.py --init
    OK "Banco inicializado."
} catch {
    Aviso "Falha ao inicializar o banco. Confira a senha no .env e se o PostgreSQL esta rodando."
    throw
} finally { Pop-Location }

# --- PASSO 5: firewall ------------------------------------------------------
Titulo "PASSO 5/6 - Liberando a porta $Porta no Firewall"
$regra = Get-NetFirewallRule -DisplayName "DocTrack $Porta" -ErrorAction SilentlyContinue
if ($regra) {
    Aviso "Regra de firewall ja existe."
} else {
    New-NetFirewallRule -DisplayName "DocTrack $Porta" -Direction Inbound `
        -Protocol TCP -LocalPort $Porta -Action Allow | Out-Null
    OK "Porta $Porta liberada na rede."
}

# --- PASSO 6: servico via NSSM ----------------------------------------------
Titulo "PASSO 6/6 - Instalando o servico (roda 24h)"
$nssm = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if (-not $nssm) {
    Aviso "NSSM nao encontrado no PATH."
    Write-Host "  Baixe em https://nssm.cc/download , coloque o nssm.exe numa pasta"
    Write-Host "  do PATH (ex: C:\Windows) e rode este script de novo."
    Write-Host "  -- OU -- inicie manualmente para testar agora:" -ForegroundColor Yellow
    Write-Host "     .\venv\Scripts\waitress-serve.exe --listen=0.0.0.0:$Porta wsgi:app"
    exit 1
}

$waitress = "$Projeto\venv\Scripts\waitress-serve.exe"
New-Item -ItemType Directory -Force -Path "$Projeto\logs" | Out-Null

# Remove servico antigo se existir (reinstalacao limpa).
# Usa Get-Service (cmdlet) em vez de 'nssm status' para nao disparar erro
# fatal quando o servico ainda nao existe na primeira instalacao.
if (Get-Service $Servico -ErrorAction SilentlyContinue) {
    Aviso "Servico ja existe, reinstalando..."
    & $nssm stop $Servico 2>$null
    & $nssm remove $Servico confirm
    Start-Sleep -Seconds 2
}

# wsgi:app (nao servidor:app): a preparacao do banco -- schema, backfills e a
# foto do dia -- saiu do import de servidor.py e virou init_app(), chamado por
# wsgi.py. Apontar para servidor:app sobe o app com o banco sem preparar.
& $nssm install $Servico $waitress
& $nssm set $Servico AppParameters "--listen=0.0.0.0:$Porta wsgi:app"
& $nssm set $Servico AppDirectory $Projeto
& $nssm set $Servico Start SERVICE_AUTO_START
& $nssm set $Servico AppStdout "$Projeto\logs\out.log"
& $nssm set $Servico AppStderr "$Projeto\logs\err.log"
& $nssm start $Servico
OK "Servico '$Servico' instalado e iniciado."

# --- Tarefa agendada (opcional) ---------------------------------------------
# As fotos diarias (ICE/IDP, missoes, projetos) rodam por padrao na thread
# interna do proprio servico. Quem preferir enxergar o agendamento no Windows
# usa -ComTarefaAgendada: registra a tarefa e desliga a thread no .env para as
# duas nao fazerem o mesmo trabalho.
if ($ComTarefaAgendada) {
    Titulo "Extra - Tarefa Agendada das fotos diarias"
    $tarefa = "DocTrack - Snapshot diario"
    if (Get-ScheduledTask -TaskName $tarefa -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $tarefa -Confirm:$false
    }
    $acao    = New-ScheduledTaskAction -Execute $py `
                 -Argument "scripts\snapshot_diario.py" -WorkingDirectory $Projeto
    $gatilho = New-ScheduledTaskTrigger -Daily -At 03:00
    Register-ScheduledTask -TaskName $tarefa -Action $acao -Trigger $gatilho `
        -User "SYSTEM" -RunLevel Highest `
        -Description "Grava as fotos diarias de equipamentos, missoes e projetos." | Out-Null
    if (-not (Select-String -Path $envFile -Pattern "^DOCTRACK_AGENDADOR=" -Quiet)) {
        Add-Content -Path $envFile -Value "DOCTRACK_AGENDADOR=0" -Encoding UTF8
    }
    & $nssm restart $Servico | Out-Null
    OK "Tarefa '$tarefa' registrada para 03:00 (thread interna desligada)."
}

# --- Final ------------------------------------------------------------------
$ip = (Get-NetIPAddress -AddressFamily IPv4 |
       Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.*" } |
       Select-Object -First 1).IPAddress

Write-Host "`n###############################################" -ForegroundColor Green
Write-Host "#            INSTALACAO CONCLUIDA!            #" -ForegroundColor Green
Write-Host "###############################################"
Write-Host "`n  Acesse no servidor:   http://localhost:$Porta"
if ($ip) { Write-Host "  Acesse na rede:       http://${ip}:$Porta" }
Write-Host "`n  Comandos uteis:"
Write-Host "    nssm restart $Servico    (reiniciar)"
Write-Host "    Get-Service $Servico     (ver status)"
Write-Host "    logs em: $Projeto\logs`n"
