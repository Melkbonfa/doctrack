# DocTrack — Dashboard de Gestão de Documentos e Projetos de TI

Sistema web interno da Loccus para gestão de documentos técnicos, equipamentos,
consumíveis, entregáveis de projetos e PDR. Backend em Flask (Python) com frontend em
templates Jinja + JavaScript, tempo real via Socket.IO e banco SQLite
(desenvolvimento) ou PostgreSQL (produção).

## Módulos

| Módulo | Descrição |
|---|---|
| **Documentos** | Blueprint próprio: documentos técnicos por equipamento (9 tipos), com pipelines de etapas, workflow de status, versões e auditoria |
| **Equipamentos** | Entidade central: taxonomia (categoria/família/linha), dados regulatórios/fabricante e acessórios |
| **Consumíveis** | Catálogo global com compatibilidade N:N por equipamento, tipos de consumível configuráveis e descritivo técnico com import/export por Word (.docx) |
| **Entregáveis** | Acompanhamento de entregáveis de projetos por categoria, com visão mensal (PMO) |
| **PDR** | Dashboard PDR integrado como blueprint interno (`/pdr`), acesso por flag de usuário |
| **Custos** | Blueprint próprio (`/custos`): formação de custo de produto e projeto — NRE e COGS separados, câmbio com três papéis (referência PTAX, planejamento travada, realizada da DI), versionamento de baseline e comparativo de portfólio. Só admin/gestor |
| **Tempos** | Blueprint próprio (`/tempos`): apontamento de horas por pessoa, amarrado a projeto, entregável, cartão de missão, equipamento ou tarefa livre. Cronômetro global presente em todos os módulos (iniciar/pausar/retomar/parar), lançamento manual retroativo, folha e relatórios. Técnico para cima |
| **Auth/RBAC** | Autenticação JWT, papéis e permissões por área, convite com código no primeiro acesso |

## Como rodar (desenvolvimento)

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python servidor.py
```

O app sobe em `http://localhost:5000`. Configure variáveis em `.env`
(use `.env.example` como base). Testes:

```powershell
.\venv\Scripts\python -m pytest
```

## Estrutura do projeto

```
├── servidor.py               # App Flask principal (rotas, API, Socket.IO)
├── models.py                 # Modelos SQLAlchemy
├── auth.py                   # Autenticação, RBAC e log de auditoria
├── killswitch.py             # Trava de emergência: desliga o sistema por gatilho externo
├── areas.py                  # Definição das áreas/setores
├── documentos.py             # Blueprint do módulo Documentos (CRUD + arquivos do equipamento)
├── entregaveis.py            # Blueprint do módulo Entregáveis
├── event_bus.py              # Barramento de eventos (tempo real)
├── equipamentos_importer.py  # Importador da planilha mestra de equipamentos
├── diagnostico.py            # Cadastro × arquivos que existem de fato (rede + plataforma)
├── utils.py                  # Utilitários compartilhados
├── templates/                # Templates Jinja + audit_log_report.html
├── static/                   # CSS/JS do frontend (inclui socket-client.js e app-realtime.js)
├── pdr/                      # Módulo PDR (blueprint com templates/static próprios)
├── custos/                   # Módulo Custos (models · core de cálculo · câmbio · routes)
├── tempos/                   # Módulo Tempos (models · core · routes; o widget global fica em static/)
├── migrations/               # Migrações de schema numeradas
├── tests/                    # Testes pytest
├── scripts/                  # Scripts operacionais (deploy, backup, build, importações)
├── docs/                     # Documentação
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

## Deploy

Produção roda em servidor Windows próprio (`C:\apps\doctrack`):
merge na `main` → `git pull` no servidor → restart do serviço.
A pilha de produção é **waitress + NSSM + PostgreSQL**. Comece por
[docs/README.md](docs/README.md), que diz qual dos guias de implantação vale hoje
e o que os outros três são.

Scripts úteis (rodar a partir da raiz do projeto):

| Ação | Comando |
|---|---|
| Deploy/atualização no servidor | `.\scripts\deploy_windows.ps1` |
| Backup do banco (PostgreSQL) | `.\scripts\gerar_backup.ps1` |
| Build executável (PyInstaller) | `.\scripts\build_exe.ps1` |

> `scripts\backup_doctrack.ps1` foi removido junto com a migração para o PostgreSQL.
> Esta tabela ainda o listava; seguir a linha antiga gerava um backup vazio, porque o
> script copiava o `doctrack.db` do SQLite. Use `gerar_backup.ps1`.

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
