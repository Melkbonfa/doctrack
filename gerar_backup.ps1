# ============================================================================
#  gerar_backup.ps1 — Backup do banco PostgreSQL do DocTrack
# ----------------------------------------------------------------------------
#  O que faz:
#    - Gera um arquivo .sql com TODO o conteudo do banco (pg_dump)
#    - Salva em C:\apps\doctrack\backups com a data no nome
#    - Apaga backups com mais de 30 dias (para nao lotar o disco)
#
#  Como usar manualmente:
#    cd C:\apps\doctrack
#    .\gerar_backup.ps1
#
#  Para rodar TODO DIA automaticamente:
#    Use o Agendador de Tarefas do Windows (taskschd.msc), criando uma tarefa
#    diaria que executa:
#      powershell.exe -ExecutionPolicy Bypass -File "C:\apps\doctrack\gerar_backup.ps1"
# ============================================================================

$ErrorActionPreference = "Stop"

# --- Configuracoes (ajuste se necessario) -----------------------------------
$Banco       = "doctrack"
$Usuario     = "doctrack_app"
$PgHost      = "localhost"
$Porta       = 5432
$PastaBackup = "$PSScriptRoot\backups"
$DiasManter  = 30

# Localiza o pg_dump automaticamente (pega a versao mais nova instalada)
$pgDump = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\pg_dump.exe" -ErrorAction SilentlyContinue |
          Sort-Object FullName -Descending | Select-Object -First 1
if (-not $pgDump) {
    throw "pg_dump.exe nao encontrado em C:\Program Files\PostgreSQL\. O PostgreSQL esta instalado?"
}

# --- Le a senha do banco a partir do .env -----------------------------------
$envFile = "$PSScriptRoot\.env"
if (-not (Test-Path $envFile)) { throw ".env nao encontrado em $envFile" }
$linhaDb = Get-Content $envFile | Where-Object { $_ -match "^DATABASE_URL=" }
if ($linhaDb -match "postgresql://[^:]+:([^@]+)@") {
    $env:PGPASSWORD = $Matches[1]
} else {
    throw "Nao consegui extrair a senha do DATABASE_URL no .env"
}

# --- Faz o backup -----------------------------------------------------------
New-Item -ItemType Directory -Force -Path $PastaBackup | Out-Null
$carimbo = Get-Date -Format "yyyy-MM-dd_HHmm"
$arquivo = "$PastaBackup\doctrack_$carimbo.sql"

Write-Host "Gerando backup do banco '$Banco'..." -ForegroundColor Cyan
& $pgDump.FullName -U $Usuario -h $PgHost -p $Porta -d $Banco -f $arquivo

if (Test-Path $arquivo) {
    $tam = [math]::Round((Get-Item $arquivo).Length / 1KB, 1)
    Write-Host "  [OK] Backup salvo: $arquivo ($tam KB)" -ForegroundColor Green
} else {
    throw "O backup nao foi gerado."
}

# --- Limpa backups antigos --------------------------------------------------
$limite = (Get-Date).AddDays(-$DiasManter)
$antigos = Get-ChildItem "$PastaBackup\doctrack_*.sql" |
           Where-Object { $_.LastWriteTime -lt $limite }
if ($antigos) {
    $antigos | Remove-Item -Force
    Write-Host "  [OK] $($antigos.Count) backup(s) com mais de $DiasManter dias removido(s)." -ForegroundColor Green
}

# Limpa a senha da memoria
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
