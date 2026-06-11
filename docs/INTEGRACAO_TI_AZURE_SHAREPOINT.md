# DocTrack — Plano de provisionamento e integração (para o TI)

**Objetivo:** hospedar o dashboard DocTrack de forma segura dentro do ecossistema Microsoft da empresa,
integrando **login via Entra ID (SSO)** e **acesso aos arquivos (Manuais e ITs) no SharePoint**,
substituindo o file server `P:\` e eliminando a necessidade de abrir portas de entrada em firewall on-premise.

> **Resumo para decisão rápida:** precisamos de **(1)** uma assinatura Azure com cobrança ativa,
> **(2)** um App Service (Linux, tier Basic) + um PostgreSQL gerenciado, **(3)** um App Registration
> no Entra ID com permissões mínimas, e **(4)** as bibliotecas de Manuais/ITs migradas para o SharePoint.

---

## 1. Arquitetura-alvo

```
Usuário (navegador, na rede corporativa)
   │  HTTPS 443 (saída já liberada universalmente)
   ▼
Azure App Service (Linux, Python/Flask)
   ├──► Entra ID            → login SSO (OAuth2/OIDC)
   ├──► Microsoft Graph     → ler/baixar/pré-visualizar arquivos do SharePoint
   └──► Azure Database for PostgreSQL → dados do app (equipamentos, auditoria, usuários)

SharePoint Online (biblioteca de Engenharia: Manuais / ITs)
```

Sem porta de entrada aberta em servidor on-premise. O acesso ao app é restringido por **Access Restrictions (IP)**.

---

## 2. O que precisa ser PROVISIONADO

### 2.1 Assinatura Azure (pré-requisito crítico)
- [ ] Existe uma **assinatura Azure com cobrança ativa** (Pay-As-You-Go / EA / CSP)?
      *Ter M365/Entra NÃO garante isso — a assinatura de infraestrutura é separada.*
- [ ] Há permissão para **criar recursos** (App Service e PostgreSQL) nessa assinatura?
- [ ] Existe um **Resource Group** designado (ou criar um, ex.: `rg-doctrack-prod`)?

### 2.2 App Service (hospedagem do dashboard)
- [ ] **App Service Plan – Linux – tier Basic (B1)** (suficiente: app interno, poucos usuários).
- [ ] Habilitar **WebSockets** (necessário para o realtime / Socket.IO).
- [ ] Habilitar **Always On**.
- [ ] **Access Restrictions:** liberar acesso **somente às faixas de IP públicas da empresa / VPN**
      (precisamos da lista desses ranges — ver seção 4).
- [ ] HTTPS/TLS: o domínio padrão `*.azurewebsites.net` já vem com TLS.
      Se quiser **domínio próprio** (ex.: `doctrack.empresa.com.br`), precisamos de um CNAME no DNS + certificado gerenciado.
- [ ] *(Opcional, maior segurança)* Se a política exigir o app **100% privado** (invisível na internet),
      avaliar **Private Endpoint** — pode exigir tier **Standard/Premium**. Caso contrário, Access Restrictions por IP já é uma proteção forte.

### 2.3 Banco de dados (Azure Database for PostgreSQL)
- [ ] **Flexible Server – tier Burstable B1ms** (econômico e suficiente).
- [ ] **SSL/TLS obrigatório** na conexão.
- [ ] Regra de firewall do banco liberando os **IPs de saída (outbound) do App Service**
      (ou integração de rede privada, se o tier permitir).
- [ ] Nos fornecer a **connection string** (formato `DATABASE_URL` PostgreSQL) — o app já suporta nativamente.

### 2.4 Entra ID — App Registration
Criar **1 App Registration** (pode cobrir as duas funções) com:

**a) Login SSO (permissões delegadas):**
- [ ] `openid`, `profile`, `email`, `User.Read`
- [ ] *(opcional)* `GroupMember.Read.All` — se quisermos mapear papéis (admin/gestor/técnico) por **grupo do Entra**.
- [ ] **Redirect URI** (Web): `https://<nome-do-app>.azurewebsites.net/auth/callback`
      (e o do domínio próprio, se houver).
- [ ] Front-channel logout URL: `https://<nome-do-app>.azurewebsites.net/`

**b) Acesso aos arquivos do SharePoint (permissão de aplicativo / app-only):**
- [ ] **`Sites.Selected` (Application)** — **modelo recomendado (menor privilégio)**.
      Depois de consentida, o app **só** enxerga os sites que o TI liberar explicitamente.
- [ ] **Admin consent** concedido para as permissões acima.
- [ ] Conceder ao app acesso de **leitura** apenas ao(s) **site(s) específico(s)** da Engenharia
      (via Graph `POST /sites/{site-id}/permissions` ou PnP PowerShell).
- [ ] Gerar um **Client Secret** (ou, preferível por segurança, **certificado**) e nos repassar de forma segura.

> *Alternativa (menos recomendada):* `Sites.Read.All (Application)` dá leitura a todo o SharePoint — mais amplo,
> a equipe de segurança tende a preferir `Sites.Selected`.

### 2.5 SharePoint — biblioteca de Engenharia (Caminho A: migrar do `P:\`)
- [ ] Confirmar o **site e a biblioteca de documentos** que receberão Manuais e ITs.
- [ ] Migrar o conteúdo de `P:\Engenharia\...` para essa biblioteca
      — recomendado usar a **SharePoint Migration Tool (SPMT)** (gratuita), **preservando a estrutura de pastas**
      (precisamos da estrutura para mapear cada equipamento ao seu local).
- [ ] Nos fornecer, por fim: **URL do site**, **nome da biblioteca** e (se possível) os **IDs** de site/drive.

### 2.6 Segredos
- [ ] Armazenar `Client Secret`, `DATABASE_URL` e o `SECRET_KEY` do app em **Azure Key Vault**
      (ou, no mínimo, nas **App Settings** do App Service como variáveis de ambiente — nunca no código).

---

## 3. Conectividade de saída (verificar se há restrições)
O App Service precisa alcançar (HTTPS/443):
- [ ] `login.microsoftonline.com` (autenticação)
- [ ] `graph.microsoft.com` (arquivos do SharePoint)
- [ ] o endpoint do **PostgreSQL** provisionado

*(No Azure isso normalmente é liberado por padrão; confirmar apenas se houver política de egress restritiva.)*

---

## 4. O que precisamos RECEBER do TI (valores concretos)
| Item | Para quê |
|---|---|
| **Tenant ID** | Autenticação Entra |
| **Client ID** do App Registration | SSO + Graph |
| **Client Secret** (ou certificado) | Autenticação app-only no Graph |
| **DATABASE_URL** (PostgreSQL) | Conexão do app ao banco |
| **URL do site + biblioteca** do SharePoint (e IDs de site/drive, se possível) | Localizar Manuais/ITs |
| **Faixas de IP públicas da empresa/VPN** | Access Restrictions do App Service |
| **Hostname desejado** (`*.azurewebsites.net` ou domínio próprio) | Redirect URIs e DNS |

---

## 5. Divisão de responsabilidades
| Etapa | Responsável |
|---|---|
| Confirmar assinatura Azure e permissões | **TI** |
| Criar App Service + PostgreSQL + Access Restrictions | **TI** |
| Criar App Registration + permissões + admin consent + `Sites.Selected` | **TI** |
| Migrar `P:\` → SharePoint (SPMT) | **TI** (com nosso apoio no mapeamento) |
| Adaptar o app (SSO, Graph, PostgreSQL) e fazer o deploy | **Desenvolvimento (nós)** |
| Testes na rede corporativa e cutover | **Conjunto** |

---

## 6. Ordem sugerida (dependências)
> **Atenção:** ao mover o app para o Azure, ele **deixa de enxergar o `P:\`**. Por isso a migração para o
> SharePoint deve estar pronta **antes/junto** do cutover de hospedagem.

1. **TI:** confirmar assinatura Azure + criar App Registration (Tenant/Client ID/Secret).
2. **TI (+ apoio):** migrar a biblioteca de Engenharia do `P:\` para o SharePoint, preservando a estrutura.
3. **Dev:** integrar SSO (Entra), leitura de arquivos via Graph e migrar o banco para PostgreSQL.
4. **TI:** provisionar App Service (B1) + PostgreSQL (B1ms) + Access Restrictions por IP.
5. **Dev:** deploy no App Service, configurar segredos (Key Vault/App Settings).
6. **Conjunto:** testar pela rede corporativa, validar permissões e fazer o cutover.

---

## 7. Justificativa de menor privilégio (para a equipe de segurança)
- O app usa **`Sites.Selected`**: tem acesso **apenas** aos sites do SharePoint explicitamente liberados — nunca a todo o ambiente.
- O acesso de rede é **restrito por IP** às faixas corporativas (não fica exposto à internet pública).
- Segredos ficam no **Key Vault**; conexões usam **TLS** (HTTPS para Graph/login e SSL no banco).
- Login centralizado no **Entra ID** (herda MFA, políticas de acesso condicional e desprovisionamento automático ao desligamento do colaborador).

---

## 8. Custo estimado (aproximado)
| Recurso | Tier | Custo/mês (aprox.) |
|---|---|---|
| App Service Plan (Linux) | B1 (Basic) | ~US$ 13 |
| Azure Database for PostgreSQL | Flexible, Burstable B1ms | ~US$ 12–15 |
| Entra App Registration | — | grátis |
| Key Vault | — | centavos |
| **Total** | | **~US$ 25–30/mês** |

*Valores aproximados, variam por região/câmbio e uso.*

---

## 9. Pergunta-chave para destravar o projeto
> *"Temos uma **assinatura Azure com cobrança ativa** onde eu possa criar um **App Service (Linux, Basic)**
> e um **Azure Database for PostgreSQL (Flexible Server)**, aplicar **Access Restrictions por IP**, e registrar
> um **App no Entra ID** com permissão **`Sites.Selected`** (consentida por admin)?"*

Se **sim** → seguimos para o plano de deploy detalhado.
Se **não há assinatura de cobrança** → é o único bloqueio real; o TI a ativa e seguimos.
