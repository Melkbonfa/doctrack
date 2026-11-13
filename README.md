# DocTrack — gestão do P&D da Loccus

Sistema web interno da Loccus para a gestão do P&D: documentos técnicos,
equipamentos, consumíveis, projetos e entregáveis, missões, fluxos de revisão,
custos, horas, o PDR e os cadernos de laboratório. Backend em Flask (Python) com
frontend em templates Jinja + JavaScript, tempo real via Socket.IO e banco SQLite
(desenvolvimento) ou PostgreSQL (produção).

## Módulos

| Módulo | Descrição |
|---|---|
| **Hub** | Tela de entrada (`/hub`) e sub-hubs por área (`/hub/<área>`), com os números de cada módulo recortados pelo perfil de quem entra |
| **Documentos** | Documentos técnicos por equipamento (12 tipos), com pipelines de etapas, workflow de status, versões e auditoria |
| **Equipamentos** | Entidade central: taxonomia (categoria/família/linha), dados regulatórios/fabricante, acessórios e anexos |
| **Consumíveis** | Catálogo global com compatibilidade N:N por equipamento, tipos de consumível configuráveis e descritivo técnico com import/export por Word (.docx) |
| **Projetos e Entregáveis** | Projetos das três áreas (PDE, PDR, INOV) com entregáveis por categoria, modelos por tipo de projeto, visão mensal (PMO) e ligação projeto ↔ equipamento ↔ documento |
| **Missões** | Kanban de missões e cartões, com sincronização com os documentos vinculados. Técnico para cima |
| **Fluxos de revisão** | `/fluxos`: o item (documento ou entregável) passa de mão em mão por etapas de execução e revisão, com rodadas, anexos e avisos no sino. Técnico para cima |
| **Custos** | `/custos`: formação de custo de produto e projeto — NRE e COGS separados, câmbio com três papéis (referência PTAX, planejamento travada, realizada da DI), versionamento de baseline e comparativo de portfólio. Só admin/gestor |
| **Tempos** | `/tempos`: apontamento de horas por pessoa, amarrado a projeto, entregável, cartão de missão, equipamento ou tarefa livre. Cronômetro global em todos os módulos, lançamento manual retroativo, folha e relatórios. Técnico para cima |
| **PDR** | `/pdr`: dashboard de P&D Reagentes, para quem tem a área PDR |
| **Cadernos** | `/cadernos`: cadernos de laboratório do PDR (substitui o OneNote) — editor completo, versões de página, arquivos de qualquer extensão, importação do OneNote e exportação para a liderança |
| **Acesso e usuários** | Autenticação JWT, quatro papéis, permissões por área, código de ativação no primeiro acesso e trilha de auditoria |

O que cada módulo significa e quais regras impõe está em
[docs/funcional/](docs/funcional/).

## Como rodar (desenvolvimento)

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python servidor.py
```

O app sobe em `http://localhost:5000`. Configure variáveis em `.env`
(use `.env.example` como base). Sem `DATABASE_URL` ele usa o SQLite local
(`doctrack.db`) — e é assim que o desenvolvimento deve rodar: o schema é
aplicado na subida, então apontar para o PostgreSQL de produção altera o banco
dos usuários. Ver [docs/FLUXO_DESENVOLVIMENTO.md](docs/FLUXO_DESENVOLVIMENTO.md).

Testes:

```powershell
.\venv\Scripts\python -m pytest
```

## Estrutura do projeto

```
├── servidor.py               # App Flask principal (rotas, API, Socket.IO, schema na subida)
├── wsgi.py                   # Entrypoint de produção (waitress aponta para wsgi:app)
├── models.py                 # Modelos SQLAlchemy
├── auth.py                   # Autenticação, RBAC e log de auditoria
├── ratelimit.py              # Limite de tentativas falhas (login, ativação, kill switch)
├── killswitch.py             # Trava de emergência: desliga o sistema por gatilho externo
├── areas.py                  # Definição das áreas e dos módulos de cada sub-hub
├── hub.py                    # Números das vitrines do hub e dos sub-hubs
├── documentos.py             # Módulo Documentos (CRUD + arquivos do equipamento)
├── entregaveis.py            # Módulo Projetos e Entregáveis
├── modelo_sync.py            # Aplicar mudanças do modelo de entregáveis aos projetos
├── vinculos.py               # Ligações projeto ↔ equipamento ↔ documento
├── missoes.py                # Módulo Missões (kanban)
├── event_bus.py              # Barramento de eventos (tempo real + trilha)
├── scheduler.py              # Agendador embutido (fotos diárias dos indicadores)
├── caminhos.py               # Allowlist de pastas e apelidos de unidade (P: ↔ UNC)
├── arquivos_store.py         # Arquivos enviados, endereçados pelo SHA-256
├── equipamentos_core.py      # Indicadores de equipamento (ICE/IDP)
├── equipamentos_importer.py  # Importador da planilha mestra de equipamentos
├── pareto_importer.py        # Importador do Pareto ABC
├── diagnostico.py            # Cadastro × arquivos que existem de fato (rede + plataforma)
├── utils.py                  # Utilitários compartilhados
├── templates/                # Templates Jinja
├── static/                   # CSS/JS do frontend
├── pdr/                      # Módulo PDR (blueprint com templates/static próprios)
├── custos/                   # Módulo Custos (models · core de cálculo · câmbio · routes)
├── tempos/                   # Módulo Tempos (models · core · routes; o widget global fica em static/)
├── fluxos/                   # Módulo Fluxos de revisão (models · máquina de estados · routes)
├── notificacoes/             # Caixa de entrada por pessoa (o sino)
├── cadernos/                 # Módulo Cadernos (editor, versões, arquivos, importação e exportação)
├── migrations/               # Migrações de schema numeradas (espelho do que roda na subida)
├── tests/                    # Testes pytest
├── scripts/                  # Scripts operacionais (deploy, backup, build, importações)
├── docs/                     # Documentação (comece por docs/README.md)
│   ├── referencia/           # GERADA do código (scripts/gerar_docs.py)
│   ├── arquitetura/          # Visão geral, eventos e os ADRs
│   ├── operacao/             # Runbook e aderência ao guia de validação da ANVISA
│   ├── funcional/            # Um documento por módulo
│   ├── planos/               # Planos por módulo (PLANO_*.md)
│   ├── superpowers/          # Planos e specs datados (AAAA-MM-DD-*.md)
│   ├── mockups/              # Mockups HTML de telas
│   └── referencias/          # Material de referência externo
├── data/                     # Planilhas de dados de entrada
├── logs/                     # Logs do serviço NSSM (fora do git)
├── backups/                  # Backups do banco (fora do git)
└── tools/                    # Instaladores auxiliares (fora do git)
```

> Material fora do escopo do software (apresentações, relatórios gerados, planilhas
> de origem já migradas e scripts pontuais já executados) saiu do repositório na
> limpeza de jul/2026 e está em `C:\Apps\doctrack-arquivo\`.

## Documentação

Comece por **[docs/README.md](docs/README.md)**. A documentação técnica está em
quatro camadas:

| Camada | Responde | Onde |
|---|---|---|
| Referência | quais rotas, tabelas, colunas e variáveis existem | [docs/referencia/](docs/referencia/) — **gerada do código** |
| Arquitetura | como o sistema é montado e por quê | [docs/arquitetura/](docs/arquitetura/) (inclui 10 ADRs) |
| Operação | o que fazer quando dói | [docs/operacao/RUNBOOK.md](docs/operacao/RUNBOOK.md) |
| Validação | o que o guia da ANVISA pede e o que o sistema atende | [docs/operacao/ADERENCIA_BPX.md](docs/operacao/ADERENCIA_BPX.md) |
| Funcional | o que cada módulo significa | [docs/funcional/](docs/funcional/) |

Mexeu em rota, modelo ou variável de ambiente? Regere a referência:

```powershell
.\venv\Scripts\python scripts\gerar_docs.py
```

`tests/test_docs_sincronia.py` quebra a suíte se ela estiver defasada.

## Deploy

Produção roda em servidor Windows próprio (`C:\apps\doctrack`):
merge na `main` → backup → `git pull` no servidor → restart do serviço.
A pilha de produção é **waitress + NSSM + PostgreSQL**. O passo a passo de
publicar, voltar atrás e restaurar está no
[RUNBOOK](docs/operacao/RUNBOOK.md); o [docs/README.md](docs/README.md) diz qual
dos guias de implantação vale hoje e o que os outros três são.

Scripts úteis (rodar a partir da raiz do projeto):

| Ação | Comando |
|---|---|
| Deploy/atualização no servidor | `.\scripts\deploy_windows.ps1` |
| Backup do banco (PostgreSQL) | `.\scripts\gerar_backup.ps1` |
| Build executável (PyInstaller) | `.\scripts\build_exe.ps1` |
| Publicar para fora da rede (túnel) | `.\scripts\setup_cloudflared.ps1` |
| Regerar a referência técnica | `.\venv\Scripts\python scripts\gerar_docs.py` |

> `scripts\backup_doctrack.ps1` foi removido junto com a migração para o PostgreSQL.
> Esta tabela ainda o listava; seguir a linha antiga gerava um backup vazio, porque o
> script copiava o `doctrack.db` do SQLite. Use `gerar_backup.ps1`.

## Acesso de fora da rede (e pelo celular)

O acesso de fora é **opcional** e, quando ligado, é feito por **túnel do
Cloudflare**: a conexão parte do servidor para fora, então nenhuma porta de
entrada é aberta na borda da Loccus e nenhum IP público é exposto. Sem o túnel
o sistema atende só a rede interna. O servidor **continua dentro da rede** — e isso não é
detalhe: o banco guarda o *caminho* dos documentos, não os arquivos (eles vivem
em `\\loccus-srv03\Projetos$\Engenharia`), então uma cópia hospedada fora não abriria documento nenhum.

```powershell
.\scripts\setup_cloudflared.ps1 -Token "ey..." -Hostname "doctrack.seudominio.com"
```

Com HTTPS no ar, o app fica **instalável no celular** (PWA): "Adicionar à tela
de início" e ele abre em tela cheia, com ícone próprio. Mesmo deploy, sem loja e
sem build separado. O passe de celular é focado em **consulta**; edição pesada
segue no desktop.

Guia completo, incluindo o que muda no `.env` ao publicar (`TRUST_PROXY=1` deixa
de ser opcional): **[docs/ACESSO_REMOTO.md](docs/ACESSO_REMOTO.md)**.

## Trava de emergência (kill switch)

Um gatilho externo desliga o sistema inteiro; só a senha-mestra o traz de volta.
É para o incidente — credencial vazada, máquina comprometida, suspeita de acesso
indevido — em que desligar sai mais barato que investigar com o sistema no ar.

Travado, **tudo** responde `423`: API, páginas e WebSocket, inclusive para admin
e para quem já estava logado. Só continuam de pé as rotas do próprio kill switch
e `/api/version` (health check). Destravar encerra todas as sessões abertas
antes da trava: todo mundo entra de novo.

**Instalação** (uma vez, por servidor):

```powershell
.\venv\Scripts\python scripts\kill_switch.py hash
```

Ele pede o token do gatilho e a senha-mestra e imprime os dois hashes bcrypt
para colar no `.env` (`DOCTRACK_KILL_TOKEN_HASH` e `DOCTRACK_UNLOCK_HASH`).
Nenhum dos dois vai para o banco — se o motivo da trava for o banco
comprometido, um segredo guardado nele não vale nada. Sem as duas variáveis o
gatilho recusa travar: travar sem senha de volta é destruir, não proteger.
Guarde a senha-mestra fora do servidor.

**Disparar**, de qualquer lugar (não precisa do repositório nem de estar logado):

```bash
curl -X POST https://SEU-SERVIDOR/api/kill-switch/lock -H "X-Kill-Token: SEU_TOKEN" -H "Content-Type: application/json" -d "{\"motivo\":\"credencial vazada\"}"
```

**Liberar**: acesse `/travado` no navegador e informe a senha-mestra (ou
`.\venv\Scripts\python scripts\kill_switch.py unlock --url https://SEU-SERVIDOR`).

As duas rotas são limitadas a 3 tentativas falhas por IP a cada 15 min, e as
duas ações ficam no log de auditoria sob o usuário `kill-switch`.

## Versionamento

A versão vigente fica em [VERSION](VERSION) e o histórico em
[CHANGELOG.md](CHANGELOG.md) (Keep a Changelog + SemVer).
