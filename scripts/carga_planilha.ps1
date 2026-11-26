# ============================================================================
#  carga_planilha.ps1 - atalho para scripts\carga_planilha.py no servidor
# ----------------------------------------------------------------------------
#  Edicao em massa de modelos e projetos do DocTrack por planilha Excel.
#  Sempre nesta ordem:
#
#    powershell -ExecutionPolicy Bypass -File C:\apps\doctrack\scripts\carga_planilha.ps1 exportar C:\carga\carga.xlsx
#    powershell -ExecutionPolicy Bypass -File C:\apps\doctrack\scripts\carga_planilha.ps1 previa   C:\carga\carga.xlsx
#    powershell -ExecutionPolicy Bypass -File C:\apps\doctrack\scripts\carga_planilha.ps1 aplicar  C:\carga\carga.xlsx -Motivo "Novos modelos PDR" -Por voce@empresa.com
#
#  "aplicar" faz um backup completo do banco ANTES (gerar_backup.ps1) e para
#  se o backup falhar. Regras da planilha: aba LEIA-ME do arquivo exportado.
# ============================================================================
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("exportar", "previa", "aplicar")]
    [string]$Comando,

    [Parameter(Mandatory = $true, Position = 1)]
    [string]$Planilha,

    [string]$Motivo = "",
    [string]$Por = ""
)

$ErrorActionPreference = "Stop"
$Raiz = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Raiz "venv\Scripts\python.exe"
$Script = Join-Path $Raiz "scripts\carga_planilha.py"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not (Test-Path $Python)) { throw "Python do DocTrack nao encontrado em $Python" }
$Planilha = [System.IO.Path]::GetFullPath($Planilha)

if ($Comando -ne "exportar" -and -not (Test-Path $Planilha)) {
    throw "Planilha nao encontrada: $Planilha"
}

if ($Comando -eq "aplicar") {
    if (-not $Motivo) { throw "Informe -Motivo ""por que a mudanca"" (fica no historico)." }
    if (-not $Por)    { throw "Informe -Por com o seu e-mail de admin no DocTrack." }
    Write-Host "1/2 Backup do banco antes de aplicar..." -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Raiz "scripts\gerar_backup.ps1")
    if ($LASTEXITCODE -ne 0) { throw "O backup falhou; nada foi aplicado." }
    Write-Host "2/2 Aplicando a planilha..." -ForegroundColor Cyan
    & $Python $Script aplicar $Planilha --motivo $Motivo --por $Por
} elseif ($Comando -eq "previa") {
    $args_ = @("previa", $Planilha)
    if ($Por) { $args_ += @("--por", $Por) }
    & $Python $Script @args_
} else {
    & $Python $Script exportar $Planilha
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "Terminou com erro (codigo $LASTEXITCODE). Leia as mensagens acima." -ForegroundColor Red
    exit $LASTEXITCODE
}
