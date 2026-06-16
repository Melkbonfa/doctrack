# build_exe.ps1 - Compila o DocTrack num executavel de PASTA UNICA (sem admin, sem Python no destino)
# Uso:  .\build_exe.ps1
# Saida: dist\DocTrack\  (copie a pasta inteira para o servidor e rode DocTrack.exe)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "   DocTrack - Build (PyInstaller, pasta unica)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

$py = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "venv nao encontrado. Rode: python -m venv venv ; .\venv\Scripts\pip install -r requirements.txt" }

# 1) Garante PyInstaller
Write-Host "[1/4] Verificando PyInstaller..." -ForegroundColor Yellow
& $py -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) { & $py -m pip install pyinstaller }

# 2) Compila
Write-Host "[2/4] Compilando (pode levar 1-2 min)..." -ForegroundColor Yellow
& $py -m PyInstaller DocTrack.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { Write-Error "Falha na compilacao." }

$out = Join-Path $root "dist\DocTrack"

# 3) Banco ja populado ao lado do .exe (gravavel)
Write-Host "[3/4] Copiando banco de dados..." -ForegroundColor Yellow
if (Test-Path (Join-Path $root "doctrack.db")) {
    Copy-Item (Join-Path $root "doctrack.db") (Join-Path $out "doctrack.db") -Force
    Write-Host "  doctrack.db copiado." -ForegroundColor Green
} else {
    Write-Host "  [AVISO] doctrack.db nao encontrado na raiz; o .exe iniciara com banco vazio." -ForegroundColor Yellow
}

# 4) .env ao lado do .exe (JWT_SECRET aleatorio). Nao sobrescreve se ja existir.
Write-Host "[4/4] Gerando .env..." -ForegroundColor Yellow
$envFile = Join-Path $out ".env"
if (-not (Test-Path $envFile)) {
    $bytes = New-Object Byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = [System.Convert]::ToBase64String($bytes)
    $lines = @(
        "JWT_SECRET=$secret",
        "CORS_ORIGINS=*",
        "FLASK_DEBUG=False",
        "# Pasta(s) de documentos do modulo de Documentos (separe varias com ';')",
        "DOCTRACK_FILE_ROOTS=P:\Engenharia"
    )
    Set-Content -Path $envFile -Value $lines -Encoding ascii
    Write-Host "  .env criado com JWT_SECRET aleatorio." -ForegroundColor Green
} else {
    Write-Host "  .env ja existente; mantido." -ForegroundColor Gray
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  Pronto. Pacote em: $out" -ForegroundColor Green
Write-Host "  Copie a pasta DocTrack para o servidor e rode DocTrack.exe" -ForegroundColor Green
Write-Host "  Acesso local: http://localhost:5000" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
