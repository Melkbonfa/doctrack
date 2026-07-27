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
├── areas.py                  # Definição das áreas/setores
├── documentos.py             # Blueprint do módulo Documentos (CRUD + arquivos do equipamento)
├── entregaveis.py            # Blueprint do módulo Entregáveis
├── event_bus.py              # Barramento de eventos (tempo real)
├── equipamentos_importer.py  # Importador da planilha mestra de equipamentos
├── agente_scanner.py         # Agente de varredura (assistente do dash)
├── utils.py                  # Utilitários compartilhados
├── templates/                # Templates Jinja + audit_log_report.html
├── static/                   # CSS/JS do frontend (inclui socket-client.js e app-realtime.js)
├── pdr/                      # Módulo PDR (blueprint com templates/static próprios)
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

## Versionamento

A versão vigente fica em [VERSION](VERSION) e o histórico em
[CHANGELOG.md](CHANGELOG.md) (Keep a Changelog + SemVer).
