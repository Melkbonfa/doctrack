<#
.SYNOPSIS
  Assistente do DocTrack: escolhe um caderno do OneNote, extrai e gera o .zip
  que a tela Cadernos > "Importar do OneNote" recebe.

.DESCRIPTION
  Quem usa não precisa deste repositório: o DocTrack serve o assistente já
  montado como UM arquivo .cmd (este script + extrair_onenote.ps1), em
  Cadernos > Importar do OneNote > "Baixar o assistente". Dois cliques no .cmd e
  ele roda. Ver cadernos/onenote_assistente.py.

  Aqui no repositório ele também roda direto:
     powershell -ExecutionPolicy Bypass -File scripts\onenote\assistente_onenote.ps1

  Só lê o caderno. A única coisa que muda no OneNote é a lista de cadernos
  abertos, quando a pessoa escolhe abrir uma cópia baixada (OpenHierarchy); essa
  cópia é fechada de novo no fim (CloseNotebook). O original no SharePoint não é
  tocado.

  UTF-8 COM BOM (PowerShell 5.1 lê script sem BOM como ANSI).
#>
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

if (-not (Get-Command Extrair-OneNote -ErrorAction SilentlyContinue)) {
    # Rodando do repositório: o extrator é o arquivo ao lado.
    $script:MotorOneNote = Join-Path $PSScriptRoot 'extrair_onenote.ps1'
    function Extrair-OneNote { & $script:MotorOneNote @args }
}

$NS_ONE = 'http://schemas.microsoft.com/office/onenote/2013/onenote'

function Titulo([string]$t) {
    Write-Host ''
    Write-Host $t -ForegroundColor Cyan
}

function Nome-Seguro([string]$s) {
    $s = ($s -replace '[<>:"/\\|?*]', ' ') -replace '\s+', ' '
    $s = $s.Trim().Trim('.')
    if ($s.Length -gt 60) { $s = $s.Substring(0, 60).Trim() }
    if (-not $s) { $s = 'caderno' }
    return $s
}

function Cadernos-Abertos($on) {
    [string]$x = ''
    $on.GetHierarchy('', 2, [ref]$x, 2)          # hsNotebooks, xs2013
    [xml]$d = $x
    $m = New-Object System.Xml.XmlNamespaceManager($d.NameTable)
    $m.AddNamespace('one', $NS_ONE)
    return , @($d.SelectNodes('//one:Notebook', $m))
}

function Janela-No-Topo {
    Add-Type -AssemblyName System.Windows.Forms
    $f = New-Object System.Windows.Forms.Form
    $f.TopMost = $true
    return $f
}

function Abrir-Copia($on) {
    Add-Type -AssemblyName System.Windows.Forms
    Write-Host ''
    Write-Host 'No SharePoint, abra a pasta do caderno e use "Baixar": vem um .zip.'
    $r = (Read-Host 'Escolher o [Z]ip baixado ou uma [P]asta já descompactada? (Z/P)').Trim()
    if ($r -match '^[pP]') {
        $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
        $dlg.Description = 'Pasta do caderno baixada do SharePoint'
        if ($dlg.ShowDialog((Janela-No-Topo)) -ne 'OK') { return $null }
        $pasta = $dlg.SelectedPath
    } else {
        $dlg = New-Object System.Windows.Forms.OpenFileDialog
        $dlg.Filter = 'Zip (*.zip)|*.zip'
        $dlg.Title = 'Zip do caderno baixado do SharePoint'
        if ($dlg.ShowDialog((Janela-No-Topo)) -ne 'OK') { return $null }
        $pasta = Join-Path $env:TEMP ('DocTrack-OneNote\' + (Nome-Seguro ([IO.Path]::GetFileNameWithoutExtension($dlg.FileName))) + '-' + (Get-Date -Format 'yyyyMMddHHmmss'))
        Write-Host "Descompactando em $pasta ..."
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($dlg.FileName, $pasta)
    }
    $toc = Get-ChildItem -LiteralPath $pasta -Recurse -File -Filter '*.onetoc2' | Select-Object -First 1
    if ($toc) { $pasta = $toc.DirectoryName }
    else {
        $one = Get-ChildItem -LiteralPath $pasta -Recurse -File -Filter '*.one' | Select-Object -First 1
        if (-not $one) { throw "Não achei arquivos do OneNote (.one) em $pasta." }
        $pasta = $one.DirectoryName
    }
    [string]$id = ''
    $on.OpenHierarchy($pasta, '', [ref]$id, 0)    # cftNone: só abre, não cria nada
    Write-Host "Aberto no OneNote: $pasta" -ForegroundColor Green
    return $id
}

# ══════════════════════════════════════════════════════════════════════════════
Titulo 'DocTrack - exportar um caderno do OneNote'
Write-Host 'Lê um caderno do OneNote e gera um .zip para a tela'
Write-Host 'Cadernos > Importar do OneNote, no DocTrack. O caderno não é alterado.'

try { $on = New-Object -ComObject OneNote.Application }
catch {
    throw ('Não consegui falar com o OneNote. Precisa ser o OneNote do Microsoft 365 ' +
           '(o "OneNote para Windows 10" não tem essa integração). Abra o OneNote e rode de novo.')
}

$abertoPorNos = $null
$escolhido = $null
while (-not $escolhido) {
    $lista = Cadernos-Abertos $on
    Titulo 'Cadernos abertos no OneNote'
    for ($i = 0; $i -lt $lista.Count; $i++) {
        $nb = $lista[$i]
        $onde = if ($nb.path -match '^https?://') { 'online (SharePoint/OneDrive)' } else { "cópia local: $($nb.path)" }
        Write-Host ('  [{0}] {1}   ({2})' -f ($i + 1), $nb.name, $onde)
    }
    Write-Host '  [A] Abrir uma cópia baixada do SharePoint (zip ou pasta)'
    Write-Host '  [S] Sair'
    $r = (Read-Host 'Escolha').Trim()
    if ($r -match '^[sS]$') { return }
    if ($r -match '^[aA]$') {
        $novo = Abrir-Copia $on
        if ($novo) {
            $abertoPorNos = $novo
            $todos = Cadernos-Abertos $on
            $escolhido = $todos | Where-Object { $_.ID -eq $novo } | Select-Object -First 1
        }
        continue
    }
    $n = 0
    if ([int]::TryParse($r, [ref]$n) -and $n -ge 1 -and $n -le $lista.Count) { $escolhido = $lista[$n - 1] }
    else { Write-Host 'Opção inválida.' -ForegroundColor Yellow }
}

if ($escolhido.path -match '^https?://') {
    Write-Host ''
    Write-Host 'ATENÇÃO: este caderno está aberto direto do SharePoint/OneDrive.' -ForegroundColor Yellow
    Write-Host 'Assim o OneNote baixa as imagens aos poucos e o pacote pode sair sem parte delas'
    Write-Host '(no primeiro teste do L-037 saíram 2 imagens de 595). O recomendado é a opção [A]:'
    Write-Host 'baixar a pasta do caderno no SharePoint e abrir a cópia.'
    if ((Read-Host 'Continuar mesmo assim? (s/N)') -notmatch '^[sS]') { return }
}

$base = Join-Path ([Environment]::GetFolderPath('Desktop')) 'DocTrack-OneNote'
$nome = Nome-Seguro $escolhido.name
$carimbo = Get-Date -Format 'yyyy-MM-dd_HHmm'
$destino = Join-Path $base "$nome $carimbo"
$zip = Join-Path $base "$nome $carimbo (DocTrack).zip"

Titulo "Extraindo: $($escolhido.name)"
try {
    Extrair-OneNote -Caderno $escolhido.name -CadernoId $escolhido.ID -Destino $destino
    Write-Host ''
    Write-Host 'Compactando...'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($destino, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
} finally {
    if ($abertoPorNos) { try { $on.CloseNotebook($abertoPorNos, $true) } catch {} }
}

$mb = [math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 1)
Titulo 'Pronto'
Write-Host "Pacote: $zip ($mb MB)" -ForegroundColor Green
Write-Host 'Agora, no DocTrack: Cadernos > Importar do OneNote > envie esse arquivo.'
Write-Host "(A pasta $destino pode ser apagada depois da importação.)"
Start-Process explorer.exe "/select,`"$zip`""
