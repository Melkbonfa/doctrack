# DocTrack fora da Loccus — acesso remoto e uso no celular

Como usar o DocTrack de qualquer lugar, inclusive do celular, sem abrir porta no
firewall da empresa e sem perder metade do sistema no caminho.

---

## O fato que decide a arquitetura

O DocTrack guarda o **caminho** dos documentos, não os arquivos. Os `.docx` e
`.pdf` vivem em `\\loccus-srv03\Projetos$\Engenharia` e só são alcançáveis de
dentro da rede — é o que [`caminhos.py`](../caminhos.py) resolve.

Isso elimina a opção mais óbvia. Subir uma cópia do DocTrack para a nuvem
(Render, Azure, qualquer um) produz um sistema que **não abre um único
documento**. O próprio [`render.yaml`](../render.yaml) já registra isso: aquele
ambiente é uma **demonstração** com dados semeados, não o sistema.

A conclusão é o contrário da intuição: para acessar tudo de fora, o servidor
tem que **continuar dentro**. O que viaja é a conexão, não a aplicação.

```
   celular / casa / cliente                    Loccus
   ┌──────────────────┐                ┌──────────────────────────┐
   │                  │   HTTPS        │  cloudflared (serviço)   │
   │  navegador  ─────┼───────────────▶│         │                │
   │                  │                │         ▼                │
   └──────────────────┘                │  DocTrack :5000          │
                                       │         │                │
        a conexão é de SAÍDA,          │         ▼                │
        criada pelo servidor.          │  \\loccus-srv03\...      │
        Nenhuma porta de entrada       │  (continua alcançável)   │
        é aberta na borda.             └──────────────────────────┘
```

---

## Por que Cloudflare Tunnel, e não as alternativas

| Caminho | Por que não |
|---|---|
| **Abrir a porta 5000 no firewall da borda** | Expõe o app direto à internet, exige o TI, e o DocTrack passa a depender de um IP público fixo. É a opção que mais pede autorização e menos entrega. |
| **VPN corporativa** | Depende inteiramente do TI, exige cliente instalado em cada aparelho, e no celular a experiência é ruim o bastante para as pessoas não usarem. |
| **Cópia na nuvem (Render)** | Perde o módulo Documentos — ver a seção acima. Serve para demonstrar, não para trabalhar. |
| **Tailscale Funnel** | Era a alternativa sem domínio, e **deixou de ser gratuita**: em 2026 o Funnel exige plano Starter ou superior. Para 5-20 pessoas, saiu da mesa. |

**Cloudflare Tunnel** ficou de pé por eliminação e por mérito: conexão de saída
(nenhuma porta aberta), TLS válido de graça, suporte completo a WebSocket — o
Socket.IO do DocTrack passa —, e desde julho/2026 é gratuito sem limite de banda.

O único custo é o **domínio**: um túnel nomeado exige uma zona na Cloudflare.
No Cloudflare Registrar sai a preço de custo, **~US$ 10/ano**, com renovação
pelo mesmo valor. Não vale distorcer a arquitetura para evitar R$ 55 por ano.

> **Para testar hoje, sem domínio:** `cloudflared tunnel --url http://localhost:5000`
> levanta um túnel efêmero num endereço `*.trycloudflare.com`. Serve para provar
> o caminho em cinco minutos, sem conta e sem cartão. **Não serve para
> produção**: a URL muda a cada reinício, não há autenticação nenhuma na frente,
> e o túnel efêmero tem teto de 200 requisições simultâneas.

---

## Instalação

### 1. Domínio e túnel (no painel, uma vez)

1. Registre um domínio na Cloudflare (ou transfira um existente).
2. No dashboard principal: **Networking → Tunnels → Create a tunnel →
   Cloudflared**. Copie o token que aparece (começa com `ey...`).
3. Na aba **Routes** do túnel: **Add route → Published application**, o
   subdomínio escolhido, e em *Service URL* `http://localhost:5000`.

> Em fev/2026 a gestão de túneis saiu do painel Zero Trust para o principal, e a
> aba "Public Hostname" virou "Routes". Guias mais antigos mandam para
> *Zero Trust → Networks → Connectors*, que ainda existe e leva ao mesmo lugar.

### 2. No servidor

```powershell
winget install --id Cloudflare.cloudflared
```

```powershell
.\scripts\setup_cloudflared.ps1 -Token "ey..." -Hostname "doctrack.seudominio.com"
```

O script instala o `cloudflared` como serviço do Windows, confere o `.env` e
testa o caminho de fora para dentro. Para só conferir a configuração, sem
instalar nada: `.\scripts\setup_cloudflared.ps1 -SomenteVerificar`.

### 3. Segunda porta (Cloudflare Access)

Recomendado para uma equipe. **Zero Trust → Access → Applications → Add an
application → Self-hosted**, o mesmo hostname, política por e-mail da equipe.
Grátis até 50 usuários, e funciona como segundo fator: uma senha do DocTrack
vazada ainda não passa pelo Access.

> ⚠️ **Libere `/api/kill-switch/lock` do Access.** A trava de emergência precisa
> funcionar sem login, de qualquer aparelho — inclusive quando o problema *é* o
> login. Uma trava que depende do sistema de autenticação não serve para o
> incidente em que a autenticação caiu.
>
> Não é uma exceção dentro da política: o Access não aceita caminho por
> política. É uma **segunda aplicação**, mais específica, que por isso é avaliada
> antes da primeira — *Add an application → Self-hosted*, URL
> `seu-hostname/api/kill-switch/lock`, política **Action = Bypass, Include =
> Everyone**.

---

## O que muda no `.env` ao publicar

Três variáveis são inofensivas numa rede fabril fechada e deixam de ser no
instante em que o app fica alcançável de fora. Nenhuma delas dá erro — o
sistema sobe igual, só menos seguro. O `setup_cloudflared.ps1` confere as três.

| Variável | Valor | Por quê |
|---|---|---|
| `TRUST_PROXY` | `1` | **A mais importante.** Ver abaixo. |
| `CORS_ORIGINS` | `https://seu-hostname` | `*` desabilita credenciais em CORS e deixa o Socket.IO aberto a qualquer origem. |
| `DOCTRACK_KILL_TOKEN_HASH` + `DOCTRACK_UNLOCK_HASH` | gerados | Sem os dois, a trava de emergência recusa travar — e ela é a defesa que mais importa com a porta aberta. Gere com `python scripts\kill_switch.py hash`. |

### Por que `TRUST_PROXY=1` deixou de ser opcional

O `cloudflared` roda **na mesma máquina** que o DocTrack. Sem `TRUST_PROXY`,
toda requisição chega de `127.0.0.1` — e o problema não é o log impreciso.

Os limites de tentativa de [`ratelimit.py`](../ratelimit.py) são **por IP**.
Com todo mundo fundido num IP só, eles viram limites **globais**:

- `DOCTRACK_LIMITE_IP` (30 falhas / 5 min) passa a valer para a equipe inteira
  somada, e não por pessoa;
- `DOCTRACK_LIMITE_KILLSWITCH` (3 falhas / 15 min) é o caso grave: três
  tentativas erradas de **qualquer um** trancam a rota de desbloqueio para
  **todos**. Num incidente real, quem atacou queima as três de propósito e o
  administrador legítimo fica sem como destravar o sistema.

Com `TRUST_PROXY=1`, [`utils.ip_do_cliente()`](../utils.py) lê o cabeçalho
`CF-Connecting-IP` — o único que carrega o IP real de quem acessou e sobrevive
ao túnel. O `X-Forwarded-For` sozinho não resolve: o `x_for=1` do ProxyFix lê a
última entrada dele, que atrás da Cloudflare é o edge, não a pessoa.

---

## O celular

O DocTrack é instalável como app (PWA) — sem loja, sem build separado, mesmo
deploy. No navegador do aparelho, "Adicionar à tela de início": ele passa a
abrir em tela cheia, com ícone próprio, e a sessão dura os 7 dias do refresh
token.

**Requer HTTPS.** O navegador só registra service worker em contexto seguro, e
é o túnel que fornece isso — na LAN em `http://` puro a instalação simplesmente
não é oferecida (e o app funciona normal, só sem instalar).

O que compõe a build:

| Arquivo | Papel |
|---|---|
| [`static/manifest.webmanifest`](../static/manifest.webmanifest) | Nome, ícones, cor, `start_url` (`/hub`) e os atalhos de Tempos/Missões/Equipamentos. |
| [`static/sw.js`](../static/sw.js) | Service worker. Servido em **`/sw.js`**, nunca de `/static/` — o escopo de um worker é o diretório de onde ele veio. |
| [`static/pwa.js`](../static/pwa.js) | Registra o worker e oferece a instalação (só em tela estreita). |
| [`static/mobile.css`](../static/mobile.css) | O passe de celular. |
| [`static/offline.html`](../static/offline.html) | Tela de "sem conexão". Autossuficiente: nada de externo. |
| [`templates/_pwa_head.html`](../templates/_pwa_head.html) | O bloco de `<head>`, incluído por `base.html` e pelos quatro templates de `<head>` próprio. |
| [`scripts/gerar_icones_pwa.py`](../scripts/gerar_icones_pwa.py) | Gera os PNGs a partir da marca. Roda só quando a marca muda. |

### O cache não toca em dado de negócio

O service worker cacheia **`/static/*` e nada mais**. `/api/*` nunca passa por
ele, em nenhuma hipótese. Duas razões, e a segunda é a que importa:

1. dado de negócio servido do cache é dado velho apresentado como atual — num
   sistema sob validação ANVISA isso é defeito, não otimização;
2. um cache no caminho **esconderia a trava de emergência**. Travado, tudo
   responde 423; se o worker respondesse do cache, a tela de bloqueio nunca
   apareceria.

Por isso o worker também **nunca** usa o cache como reserva para resposta de
*erro* do servidor — só para falha de *rede*. E ao ver um 423 ele apaga o que
tiver guardado. Verificado no navegador: com o sistema travado, a navegação
devolve a tela de bloqueio, a casca do app não é servida, e os caches são
purgados — com o worker ativo no caminho o tempo todo.

### O escopo do passe de celular

Foi feito para **consulta**: dashboards, fichas, documentos e listas legíveis no
aparelho. Edição pesada continua sendo trabalho de desktop, por escolha.

O que [`mobile.css`](../static/mobile.css) fecha, e por que cada item existe:

- **Tabelas.** Doze `<table>` do sistema nascem em JS e só uma fica dentro de
  `.tbl-wrap`. As outras onze estouravam a largura da página. Agora rolam
  dentro da própria caixa.
- **O cartão de 1200px.** `style.css` converte cada linha em cartão a partir de
  780px — mas `table{min-width:1200px}` é global e `min-width` vence
  `max-width`, então os cartões nasciam com 1200px dentro de um container de
  345px. **A conversão em cartões nunca funcionou num aparelho de verdade**;
  855px de cada cartão ficavam fora da tela. Corrigido.
- **Zoom do iOS.** Os campos estavam em 12–14px, abaixo dos 16px em que o
  Safari do iPhone dá zoom sozinho a cada toque.
- **Área segura.** Entalhe e barra de gestos do iPhone, no app instalado.
- **Alvos de toque** de 44px, e **modal como folha inferior**.

Nada disso vale no desktop: o arquivo é inerte acima de 900px.

---

## Verificação

```powershell
.\venv\Scripts\python -m pytest tests\test_pwa.py tests\test_acesso_remoto.py
```

`test_pwa.py` protege o que quebra em silêncio — o worker sair da raiz, as
rotas do PWA virarem exceção do kill switch, um template deixar de incluir o
parcial. `test_acesso_remoto.py` protege a extração de IP, incluindo a garantia
de que duas pessoas atrás do mesmo túnel não compartilham contador de tentativa.
