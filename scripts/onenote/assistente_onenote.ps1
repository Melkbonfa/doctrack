<#
.SYNOPSIS
  Assistente do DocTrack: escolhe um caderno do OneNote, extrai e manda para a
  tela Cadernos > "Importar do OneNote".

.DESCRIPTION
  Quem usa não precisa deste repositório: o DocTrack serve o assistente já
  montado como UM arquivo .cmd (este script + extrair_onenote.ps1), em
  Cadernos > Importar do OneNote > "Baixar o assistente". Dois cliques no .cmd e
  ele roda. Ver cadernos/onenote_assistente.py.

  Baixado da tela, o .cmd traz $DT_SERVIDOR e $DT_TICKET: o assistente conta a
  etapa para a tela (que mostra o andamento) e, no fim, MANDA o pacote sozinho —
  a pessoa só volta ao navegador para conferir e confirmar. Sem esses valores, ou
  se o envio falhar, o .zip fica na Área de Trabalho para enviar à mão.

  O caderno baixado do SharePoint ("Baixar" na pasta do caderno) é achado
  sozinho na pasta Downloads: é a primeira opção do menu, e Enter a escolhe.

  Aqui no repositório ele também roda direto (sem envio):
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

# Envio direto ao DocTrack: só o .cmd baixado da tela traz os dois valores.
# Os avisos desligam sozinhos se o DocTrack não responder, para a extração não
# esperar a rede a cada página. Hashtable, e não $script:: o aviso também é
# chamado de dentro do extrator, que rodando do repositório é outro script (e
# lá $script: seria o escopo dele).
$Envio = [bool]($DT_SERVIDOR -and $DT_TICKET)
$DT_AVISOS = @{ ligado = $Envio; ultimo = [datetime]::MinValue }
# O PowerShell 5.1 não liga o TLS 1.2 sozinho (vale se o DocTrack estiver em https).
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

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

function Quando([datetime]$d) {
    $hoje = (Get-Date).Date
    if ($d.Date -eq $hoje) { return 'hoje ' + $d.ToString('HH:mm') }
    if ($d.Date -eq $hoje.AddDays(-1)) { return 'ontem ' + $d.ToString('HH:mm') }
    return $d.ToString('dd/MM HH:mm')
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

# ── O caderno baixado do SharePoint ───────────────────────────────────────────

function Pasta-Downloads {
    try {
        $p = (New-Object -ComObject Shell.Application).NameSpace('shell:Downloads').Self.Path
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    } catch {}
    return (Join-Path $env:USERPROFILE 'Downloads')
}

function Zips-De-Caderno {
    # Os .zip das últimas duas semanas na pasta Downloads com um caderno do
    # OneNote dentro (o "Baixar" do SharePoint). O mais novo primeiro.
    $pasta = Pasta-Downloads
    if (-not (Test-Path -LiteralPath $pasta)) { return , @() }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $limite = (Get-Date).AddDays(-14)
    $achados = @()
    $recentes = Get-ChildItem -LiteralPath $pasta -File -Filter '*.zip' |
        Where-Object { $_.LastWriteTime -ge $limite } | Sort-Object LastWriteTime -Descending | Select-Object -First 30
    foreach ($f in $recentes) {
        try {
            $z = [System.IO.Compression.ZipFile]::OpenRead($f.FullName)
            try { $tem = [bool]($z.Entries | Where-Object { $_.FullName -match '\.(onetoc2|one)$' } | Select-Object -First 1) }
            finally { $z.Dispose() }
            if ($tem) { $achados += $f }
        } catch {}
        if ($achados.Count -ge 5) { break }
    }
    return , $achados
}

function Descompactar([string]$zip) {
    $pasta = Join-Path $env:TEMP ('DocTrack-OneNote\' + (Nome-Seguro ([IO.Path]::GetFileNameWithoutExtension($zip))) + '-' + (Get-Date -Format 'yyyyMMddHHmmss'))
    Write-Host "Descompactando em $pasta ..."
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $pasta)
    return $pasta
}

function Escolher-Copia {
    # Opção [A]: a pessoa aponta o zip ou a pasta. Devolve a pasta, ou $null.
    Add-Type -AssemblyName System.Windows.Forms
    Write-Host ''
    Write-Host 'No SharePoint, abra a pasta do caderno e use "Baixar": vem um .zip.'
    $r = (Read-Host 'Escolher o [Z]ip baixado ou uma [P]asta já descompactada? (Z/P)').Trim()
    if ($r -match '^[pP]') {
        $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
        $dlg.Description = 'Pasta do caderno baixada do SharePoint'
        if ($dlg.ShowDialog((Janela-No-Topo)) -ne 'OK') { return $null }
        return $dlg.SelectedPath
    }
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Filter = 'Zip (*.zip)|*.zip'
    $dlg.Title = 'Zip do caderno baixado do SharePoint'
    $dlg.InitialDirectory = Pasta-Downloads
    if ($dlg.ShowDialog((Janela-No-Topo)) -ne 'OK') { return $null }
    return (Descompactar $dlg.FileName)
}

function Abrir-Pasta($on, [string]$pasta) {
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

# ── Conversa com o DocTrack (ticket no cabeçalho, sem login) ──────────────────

function Ler-Resposta($req) {
    # @{ status; corpo; erro } — também quando o DocTrack responde com erro.
    try { $resp = $req.GetResponse() }
    catch {
        $ex = $_.Exception
        while ($ex -and -not ($ex -is [System.Net.WebException])) { $ex = $ex.InnerException }
        if (-not $ex -or -not $ex.Response) { throw }
        $resp = $ex.Response
    }
    try {
        $texto = (New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)).ReadToEnd()
        $j = $null
        try { $j = $texto | ConvertFrom-Json } catch {}
        $erro = if ($j -and $j.erro) { [string]$j.erro } else { '' }
        return @{ status = [int]$resp.StatusCode; corpo = $j; erro = $erro }
    } finally { $resp.Close() }
}

function Novo-Pedido([string]$caminho, [int]$prazoMs) {
    $req = [System.Net.HttpWebRequest]::Create($DT_SERVIDOR + $caminho)
    $req.Method = 'POST'
    $req.Timeout = $prazoMs
    $req.ReadWriteTimeout = $prazoMs
    $req.Headers.Add('X-DocTrack-Ticket', $DT_TICKET)
    $req.ServicePoint.Expect100Continue = $false
    if ($req.Proxy) { $req.Proxy.Credentials = [System.Net.CredentialCache]::DefaultNetworkCredentials }
    return $req
}

function Avisar-DocTrack([string]$etapa, [long]$feito = 0, [long]$total = 0, [string]$erro = '', [switch]$Ja) {
    # Conta à tela do DocTrack o que está acontecendo: no máximo um aviso por
    # segundo (menos com -Ja ou erro). Falha aqui nunca para a extração.
    if (-not $DT_AVISOS.ligado) { return $null }
    if (-not $Ja -and -not $erro -and ((Get-Date) - $DT_AVISOS.ultimo).TotalSeconds -lt 1) { return $null }
    $DT_AVISOS.ultimo = Get-Date
    $bytes = [System.Text.Encoding]::UTF8.GetBytes((@{ etapa = $etapa; feito = $feito; total = $total; erro = $erro } | ConvertTo-Json -Compress))
    try {
        $req = Novo-Pedido '/cadernos/api/importacoes/assistente/aviso' 8000
        $req.ContentType = 'application/json; charset=utf-8'
        $req.ContentLength = $bytes.Length
        $s = $req.GetRequestStream()
        $s.Write($bytes, 0, $bytes.Length)
        $s.Close()
        return Ler-Resposta $req
    } catch {
        $DT_AVISOS.ligado = $false
        return @{ status = 0; corpo = $null; erro = $_.Exception.Message }
    }
}

function Enviar-Pacote([string]$zip) {
    # O .zip vai no corpo, em blocos de 1 MB, com o andamento aqui e na tela.
    $tam = (Get-Item -LiteralPath $zip).Length
    $req = Novo-Pedido '/cadernos/api/importacoes/assistente/pacote' (60 * 60 * 1000)
    $req.ContentType = 'application/zip'
    $req.ContentLength = $tam
    $req.AllowWriteStreamBuffering = $false
    $entrada = [System.IO.File]::OpenRead($zip)
    try {
        $saida = $req.GetRequestStream()
        $buf = New-Object byte[] (1MB)
        $feito = 0
        while (($lidos = $entrada.Read($buf, 0, $buf.Length)) -gt 0) {
            $saida.Write($buf, 0, $lidos)
            $feito += $lidos
            $txt = 'Enviando ao DocTrack: {0:N1} de {1:N1} MB' -f ($feito / 1MB), ($tam / 1MB)
            Write-Progress -Activity 'DocTrack' -Status $txt -PercentComplete ([int](100 * $feito / [math]::Max(1, $tam)))
            [void](Avisar-DocTrack $txt $feito $tam)
        }
        $saida.Close()
    } finally {
        $entrada.Close()
        Write-Progress -Activity 'DocTrack' -Completed
    }
    Write-Host 'Enviado. O DocTrack está conferindo o pacote...'
    return Ler-Resposta $req
}

# ══════════════════════════════════════════════════════════════════════════════
Titulo 'DocTrack - exportar um caderno do OneNote'
if ($Envio) {
    Write-Host 'Lê um caderno do OneNote e manda para o DocTrack, que mostra o resumo na'
    Write-Host 'tela "Importar do OneNote" para você conferir. O caderno não é alterado.'
    $r = Avisar-DocTrack 'Assistente aberto: escolhendo o caderno' -Ja
    if ($r.status -ne 200) {
        Write-Host ''
        if ($r.status -eq 0) {
            Write-Host "Não consegui falar com o DocTrack ($DT_SERVIDOR)." -ForegroundColor Yellow
        } else {
            Write-Host $(if ($r.erro) { $r.erro } else { "O DocTrack recusou o assistente (HTTP $($r.status))." }) -ForegroundColor Yellow
        }
        Write-Host 'Dá para seguir: no fim o pacote fica na Área de Trabalho para enviar à mão.'
        if ((Read-Host 'Continuar assim? (s/N)') -notmatch '^[sS]') { return }
        $Envio = $false
        $DT_AVISOS.ligado = $false
    }
} else {
    Write-Host 'Lê um caderno do OneNote e gera um .zip para a tela'
    Write-Host 'Cadernos > Importar do OneNote, no DocTrack. O caderno não é alterado.'
}

try {
    try { $on = New-Object -ComObject OneNote.Application }
    catch {
        throw ('Não consegui falar com o OneNote. Precisa ser o OneNote do Microsoft 365 ' +
               '(o "OneNote para Windows 10" não tem essa integração). Abra o OneNote e rode de novo.')
    }

    $zips = Zips-De-Caderno
    $abertoPorNos = $null
    $escolhido = $null
    while (-not $escolhido) {
        $lista = Cadernos-Abertos $on
        $opcoes = @()
        if ($zips.Count) {
            Titulo 'Baixados do SharePoint (pasta Downloads)'
            foreach ($z in $zips) {
                $opcoes += @{ zip = $z }
                Write-Host ('  [{0}] {1}   ({2:N1} MB, {3})' -f $opcoes.Count, $z.Name, ($z.Length / 1MB), (Quando $z.LastWriteTime))
            }
        }
        Titulo 'Cadernos abertos no OneNote'
        foreach ($nb in $lista) {
            $opcoes += @{ nb = $nb }
            $onde = if ($nb.path -match '^https?://') { 'online (SharePoint/OneDrive)' } else { "cópia local: $($nb.path)" }
            Write-Host ('  [{0}] {1}   ({2})' -f $opcoes.Count, $nb.name, $onde)
        }
        Write-Host '  [A] Abrir outra cópia baixada do SharePoint (zip ou pasta)'
        Write-Host '  [S] Sair'
        $r = (Read-Host $(if ($zips.Count) { 'Escolha (Enter = 1)' } else { 'Escolha' })).Trim()
        if (-not $r -and $zips.Count) { $r = '1' }
        if ($r -match '^[sS]$') {
            [void](Avisar-DocTrack '' -erro 'O assistente foi fechado sem exportar.')
            return
        }
        $pasta = $null
        if ($r -match '^[aA]$') { $pasta = Escolher-Copia }
        else {
            $n = 0
            if ([int]::TryParse($r, [ref]$n) -and $n -ge 1 -and $n -le $opcoes.Count) {
                $o = $opcoes[$n - 1]
                if ($o.zip) { $pasta = Descompactar $o.zip.FullName } else { $escolhido = $o.nb }
            } else { Write-Host 'Opção inválida.' -ForegroundColor Yellow }
        }
        if ($pasta) {
            [void](Avisar-DocTrack 'Abrindo a cópia baixada no OneNote' -Ja)
            $novo = Abrir-Pasta $on $pasta
            $abertoPorNos = $novo
            $todos = Cadernos-Abertos $on
            $escolhido = $todos | Where-Object { $_.ID -eq $novo } | Select-Object -First 1
        }
    }

    if ($escolhido.path -match '^https?://') {
        Write-Host ''
        Write-Host 'ATENÇÃO: este caderno está aberto direto do SharePoint/OneDrive.' -ForegroundColor Yellow
        Write-Host 'Assim o OneNote baixa as imagens aos poucos e o pacote pode sair sem parte delas'
        Write-Host '(no primeiro teste do L-037 saíram 2 imagens de 595). O recomendado é baixar a'
        Write-Host 'pasta do caderno no SharePoint: ela aparece no topo desta lista.'
        if ((Read-Host 'Continuar mesmo assim? (s/N)') -notmatch '^[sS]') {
            [void](Avisar-DocTrack '' -erro 'O assistente foi fechado sem exportar.')
            return
        }
    }

    $base = Join-Path ([Environment]::GetFolderPath('Desktop')) 'DocTrack-OneNote'
    $nome = Nome-Seguro $escolhido.name
    $carimbo = Get-Date -Format 'yyyy-MM-dd_HHmm'
    $destino = Join-Path $base "$nome $carimbo"
    $zip = Join-Path $base "$nome $carimbo (DocTrack).zip"

    Titulo "Extraindo: $($escolhido.name)"
    [void](Avisar-DocTrack "Extraindo: $($escolhido.name)" -Ja)
    try {
        Extrair-OneNote -Caderno $escolhido.name -CadernoId $escolhido.ID -Destino $destino -AoProgredir {
            param($n, $total, $pagina)
            [void](Avisar-DocTrack ('Extraindo a página {0} de {1}: {2}' -f $n, $total, $pagina) $n $total)
        }
        Write-Host ''
        Write-Host 'Compactando...'
        [void](Avisar-DocTrack 'Compactando o pacote' -Ja)
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::CreateFromDirectory($destino, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    } finally {
        if ($abertoPorNos) { try { $on.CloseNotebook($abertoPorNos, $true) } catch {} }
    }
} catch {
    [void](Avisar-DocTrack '' -erro $_.Exception.Message)
    throw
}

$mb = [math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 1)
if ($Envio) {
    Titulo 'Enviando ao DocTrack'
    try { $r = Enviar-Pacote $zip }
    catch { $r = @{ status = 0; corpo = $null; erro = $_.Exception.Message } }
    if ($r.status -eq 201) {
        Titulo 'Pronto'
        Write-Host 'O caderno chegou ao DocTrack. Volte ao navegador: a tela "Importar do OneNote"' -ForegroundColor Green
        Write-Host 'já mostra o resumo para você conferir e confirmar.' -ForegroundColor Green
        Write-Host "(Cópia do pacote: $zip ($mb MB). Pode apagar depois da importação.)"
        return
    }
    $motivo = if ($r.erro) { $r.erro } else { "HTTP $($r.status)" }
    Write-Host ''
    Write-Host "Não deu para enviar ao DocTrack: $motivo" -ForegroundColor Yellow
    $DT_AVISOS.ligado = $true
    [void](Avisar-DocTrack '' -erro "O envio falhou: $motivo. O pacote ficou na Área de Trabalho para enviar à mão.")
}

Titulo 'Pronto'
Write-Host "Pacote: $zip ($mb MB)" -ForegroundColor Green
Write-Host 'Agora, no DocTrack: Cadernos > Importar do OneNote > envie esse arquivo.'
Write-Host "(A pasta $destino pode ser apagada depois da importação.)"
Start-Process explorer.exe "/select,`"$zip`""
