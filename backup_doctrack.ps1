# backup_doctrack.ps1
# Script de Backup Automatizado e Rotativo para SQLite (DocTrack)
# ============================================================================

# Configuracoes do Backup
$DatabaseFile = "doctrack.db"
$BackupDir = "backups" 
$RetentionCount = 15   

# Obter diretorio atual do script
$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($ScriptPath) {
    Set-Location $ScriptPath
}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "   DocTrack - Iniciando Backup do Banco de Dados" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Verificar se o banco de dados original existe
if (-not (Test-Path $DatabaseFile)) {
    Write-Host "[ERRO] Arquivo do banco de dados nao foi encontrado!" -ForegroundColor Red
    Exit 1
}

# 2. Criar diretorio de backup se nao existir
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -ErrorAction SilentlyContinue | Out-Null
    if ($?) {
        Write-Host "  Diretorio de backups criado com sucesso." -ForegroundColor Yellow
    }
}

# 3. Gerar o nome do arquivo de backup com data e hora
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$BackupFileName = "doctrack_backup_$Timestamp.db"
$BackupPath = Join-Path $BackupDir $BackupFileName

# 4. Executar a copia segura
Copy-Item -Path $DatabaseFile -Destination $BackupPath -Force -ErrorAction SilentlyContinue
if ($?) {
    $msgOk = "  Backup criado com sucesso: $BackupPath"
    Write-Host $msgOk -ForegroundColor Green
} else {
    Write-Host "[ERRO] Falha ao copiar o arquivo do banco de dados!" -ForegroundColor Red
    Exit 1
}

# 5. Aplicar politica de retencao (remover backups mais antigos)
Write-Host ""
$msg1 = "Verificando politica de retencao para manter $RetentionCount backups"
Write-Host $msg1 -ForegroundColor Yellow

# Listar todos os backups correspondentes ordenados do mais recente para o mais antigo
$BackupFiles = Get-ChildItem -Path $BackupDir -Filter "doctrack_backup_*.db" -ErrorAction SilentlyContinue | 
                Sort-Object LastWriteTime -Descending

if ($BackupFiles.Count -gt $RetentionCount) {
    $FilesToDelete = $BackupFiles | Select-Object -Skip $RetentionCount
    foreach ($File in $FilesToDelete) {
        Remove-Item -Path $File.FullName -Force -ErrorAction SilentlyContinue
        if ($?) {
            $msgDel = "  Backup antigo excluido: " + $File.Name
            Write-Host $msgDel -ForegroundColor Gray
        } else {
            $msgWarn = "  [AVISO] Nao foi possivel excluir " + $File.Name
            Write-Host $msgWarn -ForegroundColor Red
        }
    }
    Write-Host "  Politica de retencao aplicada." -ForegroundColor Green
} else {
    $currentCount = if ($BackupFiles) { $BackupFiles.Count } else { 0 }
    $msgLimit = "  Quantidade de backups: $currentCount. Limite de $RetentionCount nao excedido."
    Write-Host $msgLimit -ForegroundColor Gray
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "   Processo de Backup Finalizado!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
