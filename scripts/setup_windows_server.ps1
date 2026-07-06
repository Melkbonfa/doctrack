# setup_windows_server.ps1
# Script de Configuracao Automatizada para Windows Server - DocTrack Dashboard
# ============================================================================

$ErrorActionPreference = "Stop"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "   DocTrack - Iniciando Configuracao do Servidor" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Verificar pre-requisitos
Write-Host ""
Write-Host "[1/5] Verificando pre-requisitos..." -ForegroundColor Yellow

$pythonInstalled = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonInstalled) {
    Write-Error "Python nao esta instalado ou nao esta no PATH do sistema. Por favor, instale o Python 3.10+ e tente novamente."
}
Write-Host "  Python encontrado: $(python --version)" -ForegroundColor Green

$npmInstalled = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npmInstalled) {
    Write-Error "Node.js/NPM nao esta instalado. Por favor, instale o Node.js LTS e tente novamente."
}
Write-Host "  Node.js/NPM encontrado: $(node -v)" -ForegroundColor Green

# 1.1 Verificar e instalar o GTK3 Runtime (necessário para WeasyPrint / geração de PDF)
$gtkPath = "C:\Program Files\GTK3-Runtime Win64\bin"
if (-not (Test-Path $gtkPath)) {
    Write-Host "  GTK3 Runtime (necessario para geracao de PDF) nao encontrado." -ForegroundColor Yellow
    $gtkInstallerLocal = "tools\gtk3-runtime-installer.exe"
    $gtkInstallerTemp = "$env:TEMP\gtk3-runtime-installer.exe"
    $gtkInstaller = $gtkInstallerTemp

    if (-not (Test-Path $gtkInstallerLocal) -and (Test-Path "gtk3-runtime-installer.exe")) {
        $gtkInstallerLocal = "gtk3-runtime-installer.exe"
    }
    
    if (Test-Path $gtkInstallerLocal) {
        Write-Host "  Instalador local '$gtkInstallerLocal' encontrado. Usando arquivo local para instalacao..." -ForegroundColor Green
        $gtkInstaller = $gtkInstallerLocal
    } else {
        Write-Host "  Baixando GTK3 Runtime silenciosamente..." -ForegroundColor Yellow
        $gtkUrl = "https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases/download/2022-01-04/gtk3-runtime-3.24.31-2022-01-04-ts-patched-x64.exe"
        
        # Configurar protocolo TLS 1.2 para conexao segura
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        
        # Download do instalador com User-Agent simulando navegador
        Invoke-WebRequest -Uri $gtkUrl -OutFile $gtkInstallerTemp -UserAgent "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" -UseBasicParsing
    }
    
    Write-Host "  Instalando GTK3 Runtime (aguarde alguns segundos)..." -ForegroundColor Yellow
    
    # Executar o instalador silenciosamente
    Start-Process -FilePath $gtkInstaller -ArgumentList "/S" -Wait
    
    if (Test-Path $gtkPath) {
        Write-Host "  GTK3 Runtime instalado com sucesso." -ForegroundColor Green
    } else {
        Write-Host "  [AVISO] Nao foi possivel confirmar a instalacao automatica. O PDF pode apresentar erros." -ForegroundColor Red
    }
} else {
    Write-Host "  GTK3 Runtime encontrado." -ForegroundColor Green
}



# 2. Criar ambiente virtual Python
Write-Host ""
Write-Host "[2/5] Configurando ambiente virtual Python (venv)..." -ForegroundColor Yellow
if (-not (Test-Path "venv")) {
    python -m venv venv
    Write-Host "  Ambiente virtual 'venv' criado." -ForegroundColor Green
} else {
    Write-Host "  Ambiente virtual 'venv' ja existente." -ForegroundColor Gray
}

Write-Host "  Instalando/Atualizando dependencias..." -ForegroundColor Yellow
& .\venv\Scripts\python.exe -m pip install --upgrade pip
& .\venv\Scripts\pip.exe install -r requirements.txt
Write-Host "  Dependencias Python instaladas." -ForegroundColor Green

# 3. Configurar arquivo .env
Write-Host ""
Write-Host "[3/5] Configurando variaveis de ambiente (.env)..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    # Gerar uma chave JWT_SECRET segura de forma automatica
    $randomBytes = New-Object Byte[] 32
    $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::Create()
    $rng.GetBytes($randomBytes)
    $jwtSecret = [System.Convert]::ToBase64String($randomBytes)
    
    $envContent = @"
# Variaveis de ambiente de Producao - Geradas automaticamente
JWT_SECRET=$jwtSecret
CORS_ORIGINS=*
FLASK_DEBUG=False
"@
    Set-Content -Path ".env" -Value $envContent
    Write-Host "  Arquivo .env criado com chave JWT_SECRET gerada aleatoriamente." -ForegroundColor Green
} else {
    Write-Host "  Arquivo .env ja existente." -ForegroundColor Gray
}

# 4. Inicializar o Banco de Dados (se necessario)
Write-Host ""
Write-Host "[4/5] Verificando banco de dados..." -ForegroundColor Yellow
if (-not (Test-Path "doctrack.db")) {
    Write-Host "  Banco de dados nao encontrado. Inicializando..." -ForegroundColor Yellow
    & .\venv\Scripts\python.exe servidor.py --init
    Write-Host "  Banco de dados doctrack.db criado e semeado com sucesso." -ForegroundColor Green
} else {
    Write-Host "  Banco de dados 'doctrack.db' ja existente. Nenhuma acao necessária." -ForegroundColor Gray
}

# 5. Configurar e Iniciar com o PM2
Write-Host ""
Write-Host "[5/5] Registrando a aplicacao no PM2..." -ForegroundColor Yellow

# Verificar se PM2 está instalado globalmente
$pm2Installed = Get-Command pm2 -ErrorAction SilentlyContinue
if (-not $pm2Installed) {
    Write-Host "  PM2 nao esta instalado globalmente. Instalando via NPM..." -ForegroundColor Yellow
    npm install -g pm2
    Write-Host "  PM2 instalado globalmente." -ForegroundColor Green
}

# Parar servico se ja estiver rodando para atualizar (desativa temporariamente o travamento por erros nativos)
$oldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& pm2 stop "doctrack-dashboard" 2>&1 | Out-Null
& pm2 delete "doctrack-dashboard" 2>&1 | Out-Null
$ErrorActionPreference = $oldPreference

# Iniciar usando o interpretador do venv com caminhos absolutos (necessario para o PM2 no Windows)
Write-Host "  Iniciando aplicacao no PM2..." -ForegroundColor Yellow
$absScript = (Resolve-Path "servidor.py").Path
$absInterpreter = (Resolve-Path ".\venv\Scripts\python.exe").Path
& pm2 start "$absScript" --name "doctrack-dashboard" --interpreter "$absInterpreter"

# Salvar lista do PM2 para persistência
& pm2 save

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "   Configuracao do DocTrack concluida com sucesso!" -ForegroundColor Green
Write-Host "   Acesse localmente em: http://localhost:5000" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
