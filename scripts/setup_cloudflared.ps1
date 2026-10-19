# ============================================================================
#  setup_cloudflared.ps1 — Publica o DocTrack para fora da Loccus, por túnel
# ----------------------------------------------------------------------------
#  O QUE ESTE SCRIPT FAZ, e o que ele deliberadamente NÃO faz.
#
#  Faz: instala o `cloudflared` como serviço do Windows, apontando para o
#  DocTrack que já roda em localhost:5000, e confere o que costuma estar errado
#  no .env quando o app deixa de ser só-LAN.
#
#  NÃO faz: baixar o cloudflared. Instalar binário de fora por script é
#  exatamente o tipo de coisa que não deve acontecer sem alguém olhando — e
#  este roda num servidor de produção. O script verifica se já existe e, se
#  não, imprime o comando para você rodar conscientemente.
#
#  POR QUE TÚNEL, E NÃO ABRIR PORTA NO FIREWALL:
#    * a conexão é de SAÍDA. Nenhuma porta de entrada é aberta na borda da
#      Loccus, nenhum IP público é exposto, nada a pedir para o TI;
#    * o servidor CONTINUA DENTRO DA REDE. É esta a razão de fundo: o DocTrack
#      guarda o CAMINHO dos documentos, não os arquivos — eles vivem em
#      \\loccus-srv03\Projetos$\Engenharia (ver caminhos.py). Uma cópia na
#      nuvem perderia o módulo Documentos inteiro. Aqui não perde nada;
#    * TLS de verdade, com certificado válido, que é pré-requisito para o PWA:
#      o navegador só registra service worker em contexto seguro.
#
#  ANTES DE RODAR — os três passos que são no painel, não aqui:
#    1. ter um domínio na conta Cloudflare (Registrar próprio, ~US$10/ano);
#    2. dashboard principal → Networking → Tunnels → Create a tunnel →
#       Cloudflared. Copie o token que a tela mostra (começa com "ey...");
#    3. na aba Routes do túnel: Add route → Published application → subdomínio
#       escolhido, Service URL `http://localhost:5000`.
#
#  (Em fev/2026 a gestão de túneis saiu do painel Zero Trust para o principal, e
#  a aba "Public Hostname" virou "Routes". O caminho antigo ainda existe em
#  Zero Trust → Networks → Connectors; os dois levam ao mesmo lugar.)
#
#  Como usar (PowerShell COMO ADMINISTRADOR, no servidor):
#    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#    cd C:\apps\doctrack
#    .\scripts\setup_cloudflared.ps1 -Token "ey..." -Hostname "doctrack.seudominio.com"
#
#  -SomenteVerificar roda só a conferência do .env, sem instalar nada.
# ============================================================================

param(
    [string]$Token,
    [string]$Hostname,
    [switch]$SomenteVerificar
)

$ErrorActionPreference = "Stop"

$Projeto = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Projeto ".env"

function Titulo($txt) { Write-Host "`n==== $txt ====" -ForegroundColor Cyan }
function OK($txt)     { Write-Host "  [OK] $txt"   -ForegroundColor Green }
function Aviso($txt)  { Write-Host "  [!]  $txt"   -ForegroundColor Yellow }
function Erro($txt)   { Write-Host "  [X]  $txt"   -ForegroundColor Red }

Write-Host "`n###############################################" -ForegroundColor Cyan
Write-Host "#   DocTrack - acesso remoto por tunel        #" -ForegroundColor Cyan
Write-Host "###############################################"

# --- Administrador ----------------------------------------------------------
$admin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin -and -not $SomenteVerificar) {
    throw "Abra o PowerShell COMO ADMINISTRADOR e rode de novo (instalar servico exige)."
}

# ============================================================================
#  1. CONFERÊNCIA DO .env
# ----------------------------------------------------------------------------
#  Esta seção existe porque as três variáveis abaixo são inofensivas numa rede
#  fabril fechada e deixam de ser no instante em que o app fica alcançável de
#  fora. Nenhuma delas dá erro: o sistema sobe igual, só menos seguro.
# ============================================================================
Titulo "Conferindo o .env para exposicao externa"

if (-not (Test-Path $EnvFile)) {
    throw ".env nao encontrado em $EnvFile. Rode o deploy_windows.ps1 primeiro."
}
$envTexto = Get-Content $EnvFile -Raw
$pendencias = @()

function ValorDoEnv($chave) {
    $m = [regex]::Match($envTexto, "(?m)^\s*$chave\s*=\s*(.*)$")
    if ($m.Success) { return $m.Groups[1].Value.Trim() }
    return $null
}

# --- TRUST_PROXY ------------------------------------------------------------
# Sem isto, o audit log grava 127.0.0.1 para TODO MUNDO: o cloudflared roda
# nesta mesma maquina, entao e dele que a conexao chega. Pior que o log
# impreciso: os limites "por IP" de ratelimit.py passam a valer para a equipe
# inteira somada. Tres tentativas erradas de qualquer um trancariam a rota de
# desbloqueio do kill switch para todos (ver utils.ip_do_cliente).
$trust = ValorDoEnv "TRUST_PROXY"
if ($trust -notin @("1", "true", "t", "True")) {
    $pendencias += "TRUST_PROXY=1  # sem isto todo acesso vira 127.0.0.1 no audit log e no rate limit"
    Erro "TRUST_PROXY nao esta ligado"
} else {
    OK "TRUST_PROXY ligado"
}

# --- CORS_ORIGINS -----------------------------------------------------------
# "*" desabilita credenciais em CORS (ver o comentario em servidor.py) e mantem
# o SocketIO aberto a qualquer origem. Numa LAN isolada passa; publicado, nao.
$cors = ValorDoEnv "CORS_ORIGINS"
if ([string]::IsNullOrWhiteSpace($cors) -or $cors -eq "*") {
    $sugestao = if ($Hostname) { "https://$Hostname" } else { "https://SEU-HOSTNAME" }
    $pendencias += "CORS_ORIGINS=$sugestao  # trocar o '*' pela origem real"
    Erro "CORS_ORIGINS esta em '*' (aceitavel so em rede fechada)"
} else {
    OK "CORS_ORIGINS restrito a: $cors"
}

# --- Kill switch ------------------------------------------------------------
# Este e o unico item que ja estava previsto para acesso externo: o gatilho foi
# feito para ser disparado do celular. Publicar o app sem ele configurado joga
# fora a defesa que mais importa quando a porta esta aberta para a internet.
$kill   = ValorDoEnv "DOCTRACK_KILL_TOKEN_HASH"
$unlock = ValorDoEnv "DOCTRACK_UNLOCK_HASH"
if ([string]::IsNullOrWhiteSpace($kill) -or [string]::IsNullOrWhiteSpace($unlock)) {
    $pendencias += "DOCTRACK_KILL_TOKEN_HASH / DOCTRACK_UNLOCK_HASH  # gere com: .\venv\Scripts\python scripts\kill_switch.py hash"
    Aviso "Kill switch NAO configurado - a trava de emergencia esta indisponivel"
} else {
    OK "Kill switch configurado"
}

if ($pendencias.Count -gt 0) {
    Write-Host "`n  Ajuste no $EnvFile antes de publicar:" -ForegroundColor Yellow
    foreach ($p in $pendencias) { Write-Host "    $p" -ForegroundColor Yellow }
    Write-Host "  Depois: Restart-Service DocTrack`n" -ForegroundColor Yellow
} else {
    OK "Nenhuma pendencia de configuracao"
}

if ($SomenteVerificar) {
    Write-Host "`n  (-SomenteVerificar: nada foi instalado.)`n"
    return
}

# ============================================================================
#  2. O BINÁRIO
# ============================================================================
Titulo "Procurando o cloudflared"

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    Erro "cloudflared nao encontrado no PATH."
    Write-Host @"

  Instale-o conscientemente, com UM dos comandos abaixo, e rode este script
  de novo. (Este script nao baixa binario sozinho de proposito: e um servidor
  de producao, e download automatico nao e coisa para acontecer sem alguem
  olhando.)

    winget install --id Cloudflare.cloudflared

  ou baixe o .msi oficial de:

    https://github.com/cloudflare/cloudflared/releases/latest

"@ -ForegroundColor Yellow
    throw "cloudflared ausente."
}
OK "cloudflared encontrado em $($cf.Source)"

# ============================================================================
#  3. O SERVIÇO
# ============================================================================
Titulo "Instalando o tunel como servico"

if (-not $Token) {
    throw "Faltou -Token. Pegue em: Networking > Tunnels > seu tunel > Install connector."
}

# `cloudflared service install <token>` cria o servico "Cloudflared" e ja o
# deixa iniciando junto com o Windows. O token carrega, ele proprio, a
# identidade do tunel e a configuracao de rotas — nada de arquivo de config.
$existente = Get-Service -Name "Cloudflared" -ErrorAction SilentlyContinue
if ($existente) {
    Aviso "Servico Cloudflared ja existe - removendo para reinstalar com o token novo"
    & cloudflared service uninstall | Out-Null
    Start-Sleep -Seconds 2
}

& cloudflared service install $Token
if ($LASTEXITCODE -ne 0) { throw "cloudflared service install falhou (codigo $LASTEXITCODE)." }
OK "Servico instalado"

Start-Sleep -Seconds 3
$svc = Get-Service -Name "Cloudflared" -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -ne "Running") { Start-Service "Cloudflared" }
$svc = Get-Service -Name "Cloudflared" -ErrorAction SilentlyContinue
if ($svc) { OK "Servico Cloudflared: $($svc.Status)" } else { Aviso "Servico nao encontrado apos instalar" }

# ============================================================================
#  4. VERIFICAÇÃO
# ============================================================================
Titulo "Verificando"

# O app local precisa estar de pe: o tunel so encaminha, nao serve nada.
try {
    $local = Invoke-WebRequest -Uri "http://localhost:5000/api/version" -UseBasicParsing -TimeoutSec 10
    OK "DocTrack respondendo em localhost:5000 (HTTP $($local.StatusCode))"
} catch {
    Erro "DocTrack NAO responde em localhost:5000 - o tunel nao tera o que servir."
    Aviso "Verifique: Get-Service DocTrack"
}

if ($Hostname) {
    # Pela internet, de fora para dentro: e o teste que prova o caminho inteiro.
    # /api/version e a rota certa para isto — publica e barata, e a mesma que o
    # health check usa (ver render.yaml).
    Write-Host "  Aguardando o tunel subir..." -ForegroundColor Gray
    Start-Sleep -Seconds 8
    try {
        $remoto = Invoke-WebRequest -Uri "https://$Hostname/api/version" -UseBasicParsing -TimeoutSec 25
        OK "Acessivel de fora: https://$Hostname (HTTP $($remoto.StatusCode))"
    } catch {
        Aviso "Ainda nao respondeu em https://$Hostname - $($_.Exception.Message)"
        Aviso "Normal nos primeiros minutos (DNS/rota). Confira o Public Hostname no painel."
    }
}

Write-Host "`n###############################################" -ForegroundColor Green
Write-Host "#   Tunel configurado                         #" -ForegroundColor Green
Write-Host "###############################################"
Write-Host @"

  PROXIMOS PASSOS

  1. Ajuste as pendencias do .env listadas acima e reinicie:
         Restart-Service DocTrack

  2. Ponha uma segunda porta na frente (recomendado para 5-20 pessoas):
         Zero Trust > Access > Applications > Add an application
         Self-hosted, o mesmo hostname, politica por e-mail da equipe.
     E gratis ate 50 usuarios e vale como 2o fator: mesmo com uma senha do
     DocTrack vazada, o atacante ainda precisa passar pelo Access.

  3. IMPORTANTE - libere a rota do kill switch. NAO e uma excecao dentro da
     politica: o Access nao aceita caminho por politica. E uma SEGUNDA
     aplicacao, mais especifica, que vence a primeira:
         Add an application > Self-hosted
         URL: SEU-HOSTNAME/api/kill-switch/lock
         Policy: Action = Bypass, Include = Everyone
     O gatilho de emergencia precisa funcionar sem login, de qualquer
     aparelho, inclusive quando o problema E o login.

  4. No celular: abra https://$Hostname, entre, e use "Adicionar a tela de
     inicio". O DocTrack instala como app (ver static/manifest.webmanifest).

"@

