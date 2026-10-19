<#
.SYNOPSIS
  Extrai um caderno do OneNote desktop para um pacote que o DocTrack importa.

.DESCRIPTION
  SOMENTE LEITURA: usa só GetHierarchy, GetPageContent e Publish (para PDF).
  Nunca chama UpdatePageContent, UpdateHierarchy nem DeleteHierarchy.

  Rode numa máquina com o OneNote do Microsoft 365 (o "OneNote para Windows 10"
  não tem a API COM). Prefira uma CÓPIA LOCAL do caderno: no SharePoint, baixe a
  pasta do caderno e abra o .onetoc2 no OneNote. Aberto direto do SharePoint, o
  OneNote baixa as imagens aos poucos — no L-037 a primeira leitura viu 2 imagens
  de 595 (docs/planos/PLANO_cadernos.md, seção 2.12).

  O pacote gerado:
    manifesto.json        caderno, seções (com grupos), páginas, contagens, avisos
    hierarquia.xml        a árvore como o OneNote devolveu
    paginas\NNNN.xml      XML 2013 de cada página, com as imagens em base64
    originais\NNNN.pdf    PDF da página que tem desenho à mão (tinta não converte)
    anexos\NNNN_KK.ext    arquivos inseridos nas páginas (cópia do cache do OneNote)
    originais_onenote\    os .one/.onetoc2 do caderno, quando ele é uma cópia local

  O DocTrack serve este script embutido no assistente (assistente_onenote.ps1),
  como um .cmd só — ver cadernos/onenote_assistente.py. Por isso ele não usa
  `exit` nem $PSScriptRoot: roda também como corpo de função.

  PowerShell 5.1 lê script sem BOM como ANSI: este arquivo precisa ficar em
  UTF-8 COM BOM.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\onenote\extrair_onenote.ps1 `
      -Caderno "L-037" -Destino "C:\Apps\doctrack-arquivo\onenote\L-037\pacote"
#>
param(
    [Parameter(Mandatory = $true)][string]$Caderno,
    [Parameter(Mandatory = $true)][string]$Destino,
    # ID do caderno no OneNote (o assistente passa): escolhe sem ambiguidade de nome.
    [string]$CadernoId = '',
    # Não copia os .one/.onetoc2 para o pacote.
    [switch]$SemOriginais
)
$ErrorActionPreference = 'Stop'
$NSURI = 'http://schemas.microsoft.com/office/onenote/2013/onenote'

if ((Test-Path -LiteralPath $Destino) -and (Get-ChildItem -LiteralPath $Destino -Force | Select-Object -First 1)) {
    throw "A pasta de destino já tem conteúdo: $Destino. Use uma pasta nova (o pacote é uma foto do momento)."
}
foreach ($sub in 'paginas', 'originais', 'anexos') {
    New-Item -ItemType Directory -Force -Path (Join-Path $Destino $sub) | Out-Null
}

$on = New-Object -ComObject OneNote.Application
[string]$xml = ''
$on.GetHierarchy('', 4, [ref]$xml, 2)          # hsPages, xs2013
[System.IO.File]::WriteAllText((Join-Path $Destino 'hierarquia.xml'), $xml, (New-Object System.Text.UTF8Encoding($false)))
[xml]$doc = $xml
$ns = New-Object System.Xml.XmlNamespaceManager($doc.NameTable)
$ns.AddNamespace('one', $NSURI)

$todosNb = @($doc.SelectNodes('//one:Notebook', $ns))
$achados = @($todosNb | Where-Object { $CadernoId -and $_.ID -eq $CadernoId })
if ($achados.Count -ne 1) { $achados = @($todosNb | Where-Object { $_.name -eq $Caderno }) }
if ($achados.Count -ne 1) { $achados = @($todosNb | Where-Object { $_.name -like "*$Caderno*" }) }
if ($achados.Count -ne 1) {
    $abertos = ($doc.SelectNodes('//one:Notebook', $ns) | ForEach-Object { $_.name }) -join ' | '
    throw "Esperava 1 caderno com '$Caderno' no nome; achei $($achados.Count). Abertos: $abertos"
}
$nb = $achados[0]
$avisos = New-Object System.Collections.ArrayList
if ($nb.path -match '^https?://') {
    [void]$avisos.Add("Caderno aberto direto do SharePoint: imagens podem faltar se a sincronização não terminou. Prefira uma cópia local.")
    Write-Warning $avisos[-1]
}

$secoes = New-Object System.Collections.ArrayList
$paginas = New-Object System.Collections.ArrayList
$cont = @{ paginas = 0; imagens = 0; tinta = 0; anexos = 0; anexos_copiados = 0; pdfs = 0; originais = 0; erros = 0 }
$n = 0

function Grupos-De($no) {
    $nomes = @()
    $p = $no.ParentNode
    while ($p -and $p.LocalName -eq 'SectionGroup') { $nomes = @($p.name) + $nomes; $p = $p.ParentNode }
    return , $nomes
}

$todas = $nb.SelectNodes(".//one:Section[not(ancestor::one:SectionGroup[@isRecycleBin='true'])]", $ns)
$iSec = 0
foreach ($sec in $todas) {
    $iSec++
    if ($sec.encrypted -eq 'true' -and $sec.locked -eq 'true') {
        [void]$avisos.Add("Seção protegida por senha e travada, pulada: $($sec.name)")
        continue
    }
    [void]$secoes.Add([ordered]@{ indice = $iSec; nome = $sec.name; cor = $sec.color; grupos = (Grupos-De $sec) })
    foreach ($p in $sec.SelectNodes('one:Page', $ns)) {
        $n++
        $arq = '{0:D4}.xml' -f $n
        try {
            [string]$px = ''
            $on.GetPageContent($p.ID, [ref]$px, 5, 2)   # piBinaryDataFileType, xs2013
            [System.IO.File]::WriteAllText((Join-Path $Destino "paginas\$arq"), $px, (New-Object System.Text.UTF8Encoding($false)))
            $imgs = ([regex]::Matches($px, '<one:Image\b')).Count
            $tinta = ([regex]::Matches($px, '<one:Ink(Drawing|Word|Paragraph)\b')).Count
            $anexos = ([regex]::Matches($px, '<one:(InsertedFile|MediaFile)\b')).Count
            $cont.imagens += $imgs; $cont.anexos += $anexos; $cont.paginas++
            # Arquivo inserido na página: o XML só traz o caminho do cache local
            # do OneNote. A cópia vai para anexos\ e o manifesto liga as duas
            # pelo `cache` (o importador põe o arquivo no mesmo lugar do texto).
            $listaAnexos = New-Object System.Collections.ArrayList
            if ($anexos -gt 0) {
                [xml]$pdoc = $px
                $pns = New-Object System.Xml.XmlNamespaceManager($pdoc.NameTable)
                $pns.AddNamespace('one', $NSURI)
                $k = 0
                foreach ($el in $pdoc.SelectNodes('//one:InsertedFile | //one:MediaFile', $pns)) {
                    $k++
                    $nomeA = if ($el.preferredName) { $el.preferredName } elseif ($el.pathSource) { Split-Path -Leaf $el.pathSource } else { "anexo$k" }
                    $cache = $el.pathCache
                    if ($cache -and (Test-Path -LiteralPath $cache)) {
                        $arqA = '{0:D4}_{1:D2}{2}' -f $n, $k, [System.IO.Path]::GetExtension($nomeA)
                        Copy-Item -LiteralPath $cache -Destination (Join-Path $Destino "anexos\$arqA")
                        [void]$listaAnexos.Add([ordered]@{ arquivo = $arqA; nome = $nomeA; cache = $cache; origem = $el.pathSource })
                        $cont.anexos_copiados++
                    } else {
                        [void]$avisos.Add("Anexo '$nomeA' da página '$($p.name)' não está no cache do OneNote: abra a página no OneNote (para ele baixar o arquivo) e extraia de novo.")
                    }
                }
            }
            $pdf = $null
            if ($tinta -gt 0) {
                $cont.tinta++
                $pdf = '{0:D4}.pdf' -f $n
                try { $on.Publish($p.ID, (Join-Path $Destino "originais\$pdf"), 3, ''); $cont.pdfs++ }
                catch { [void]$avisos.Add("PDF da página '$($p.name)' falhou: $($_.Exception.Message)"); $pdf = $null }
            }
            [void]$paginas.Add([ordered]@{
                n = $n; arquivo = $arq; secao = $iSec; nome = $p.name
                nivel = [int]($(if ($p.pageLevel) { $p.pageLevel } else { 1 }))
                data = $p.dateTime; modificado = $p.lastModifiedTime
                recolhida = ($p.isCollapsed -eq 'true'); imagens = $imgs; tinta = $tinta; pdf = $pdf
                anexos = $listaAnexos
            })
        } catch {
            $cont.erros++
            [void]$avisos.Add("Página '$($p.name)' não foi lida: $($_.Exception.Message)")
        }
        if ($n % 20 -eq 0) { Write-Host "  ... $n páginas" }
    }
}

# Os .one/.onetoc2 da cópia local vão junto: depois do corte o SharePoint deixa
# de ser usado, e o original fica guardado no caderno do DocTrack.
if (-not $SemOriginais -and $nb.path -and $nb.path -notmatch '^https?://' -and (Test-Path -LiteralPath $nb.path)) {
    $origemNb = (Resolve-Path -LiteralPath $nb.path).Path.TrimEnd('\')
    Get-ChildItem -LiteralPath $origemNb -Recurse -File |
        Where-Object { $_.Extension -in '.one', '.onetoc2' -and $_.FullName -notmatch '\\OneNote_RecycleBin\\' } |
        ForEach-Object {
            $rel = $_.FullName.Substring($origemNb.Length).TrimStart('\')
            $alvo = Join-Path (Join-Path $Destino 'originais_onenote') $rel
            try {
                New-Item -ItemType Directory -Force -Path (Split-Path $alvo) | Out-Null
                Copy-Item -LiteralPath $_.FullName -Destination $alvo
                $cont.originais++
            } catch {
                [void]$avisos.Add("Original '$rel' não foi copiado: $($_.Exception.Message)")
            }
        }
}

$manifesto = [ordered]@{
    formato     = 'doctrack-onenote-1'
    extraido_em = (Get-Date).ToString('s')
    maquina     = $env:COMPUTERNAME
    usuario     = $env:USERNAME
    caderno     = [ordered]@{ nome = $nb.name; cor = $nb.color; caminho = $nb.path }
    secoes      = $secoes
    paginas     = $paginas
    contagens   = $cont
    avisos      = $avisos
}
[System.IO.File]::WriteAllText((Join-Path $Destino 'manifesto.json'),
    ($manifesto | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "Caderno: $($nb.name)"
Write-Host ("Seções: {0} | páginas: {1} | imagens: {2} | anexos: {3} (copiados: {4}) | páginas com tinta: {5} (PDFs: {6}) | originais: {7} | erros: {8}" -f `
    $secoes.Count, $cont.paginas, $cont.imagens, $cont.anexos, $cont.anexos_copiados, $cont.tinta, $cont.pdfs, $cont.originais, $cont.erros)
foreach ($a in $avisos) { Write-Host "AVISO: $a" }
Write-Host "Pacote: $Destino"
