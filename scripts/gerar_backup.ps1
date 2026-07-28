# ============================================================================
#  gerar_backup.ps1 — Backup do banco PostgreSQL do DocTrack
# ----------------------------------------------------------------------------
#  O que faz:
#    - Gera um arquivo .sql com TODO o conteudo do banco (pg_dump)
#    - Espelha a pasta dos arquivos enviados para a plataforma (DOCTRACK_ARQUIVOS)
#    - Salva em C:\apps\doctrack\backups com a data no nome
#    - Apaga DUMPS com mais de 30 dias (o espelho de arquivos e cumulativo)
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
$Raiz        = Split-Path -Parent $PSScriptRoot   # raiz do projeto (pasta pai de scripts/)
$PastaBackup = "$Raiz\backups"
$DiasManter  = 30

# Localiza o pg_dump automaticamente (pega a versao mais nova instalada)
$pgDump = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\pg_dump.exe" -ErrorAction SilentlyContinue |
          Sort-Object FullName -Descending | Select-Object -First 1
if (-not $pgDump) {
    throw "pg_dump.exe nao encontrado em C:\Program Files\PostgreSQL\. O PostgreSQL esta instalado?"
}

# --- Le a senha do banco a partir do .env -----------------------------------
$envFile = "$Raiz\.env"
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

# --- Copia os arquivos enviados para a plataforma ---------------------------
# O banco guarda so o SHA-256 de cada arquivo; os bytes ficam em disco. Salvar
# um sem o outro produz um backup que nao restaura: dump sem os blobs aponta
# para arquivos inexistentes, e os blobs sozinhos sao nomes em hash sem sentido.
#
# O espelho e CUMULATIVO de proposito (/E e nao /MIR): como o nome do arquivo e
# o hash do conteudo, um blob nunca muda. Nunca apagando, qualquer dump dos
# ultimos 30 dias continua encontrando todos os blobs que referencia — sem
# precisar de uma copia completa por dia.
$linhaArq = Get-Content $envFile | Where-Object { $_ -match "^DOCTRACK_ARQUIVOS=" }
if ($linhaArq) {
    $PastaArquivos = ($linhaArq -replace "^DOCTRACK_ARQUIVOS=", "").Trim().Trim('"')
} else {
    $PastaArquivos = "$Raiz\arquivos"
}

if (Test-Path $PastaArquivos) {
    $EspelhoArq = "$PastaBackup\arquivos"
    Write-Host "Copiando arquivos enviados ($PastaArquivos)..." -ForegroundColor Cyan
    # /E subdiretorios (inclusive vazios) | /XD _tmp ignora parciais de upload
    # /NFL /NDL /NJH /NJS silencia a listagem, deixando so o resumo
    & robocopy $PastaArquivos $EspelhoArq /E /XD "_tmp" /R:2 /W:2 /NFL /NDL /NJH /NJS | Out-Null
    # Robocopy usa 0-7 para sucesso (8+ e falha real) — nao trate como exit code comum
    if ($LASTEXITCODE -ge 8) {
        throw "Falha ao copiar os arquivos enviados (robocopy retornou $LASTEXITCODE)."
    }
    $qtd = (Get-ChildItem $EspelhoArq -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object).Count
    $gb  = [math]::Round(((Get-ChildItem $EspelhoArq -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum / 1GB), 2)
    Write-Host "  [OK] Arquivos no espelho: $qtd ($gb GB) em $EspelhoArq" -ForegroundColor Green
} else {
    Write-Host "  [--] Nenhum arquivo enviado ainda ($PastaArquivos nao existe)." -ForegroundColor DarkGray
}

# --- Limpa backups antigos --------------------------------------------------
# So os dumps do banco. O espelho de arquivos NAO e podado: e ele que garante
# que um dump de 30 dias atras ainda ache os blobs que referencia.
$limite = (Get-Date).AddDays(-$DiasManter)
$antigos = Get-ChildItem "$PastaBackup\doctrack_*.sql" |
           Where-Object { $_.LastWriteTime -lt $limite }
if ($antigos) {
    $antigos | Remove-Item -Force
    Write-Host "  [OK] $($antigos.Count) backup(s) com mais de $DiasManter dias removido(s)." -ForegroundColor Green
}

# Limpa a senha da memoria
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
