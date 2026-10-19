# Documentação do DocTrack — por onde começar

Este índice é a porta de entrada. Se você está chegando agora, leia
[**arquitetura/VISAO_GERAL.md**](arquitetura/VISAO_GERAL.md) primeiro — ele
responde o que o sistema é e aponta para todo o resto.

---

## As quatro camadas

A documentação é organizada por **o que a pergunta é**, não por quem escreveu.

| Camada | Responde | Onde | Como se mantém |
|---|---|---|---|
| **Referência** | quais rotas, tabelas, colunas, variáveis existem | [`referencia/`](referencia/) | **gerada do código** |
| **Arquitetura** | como o sistema é montado e por que | [`arquitetura/`](arquitetura/) | à mão, muda devagar |
| **Operação** | o que fazer quando dói | [`operacao/`](operacao/) | à mão |
| **Funcional** | o que cada módulo significa | [`funcional/`](funcional/) | à mão, junto com a regra |

### Referência — gerada, nunca editada à mão

| Arquivo | Conteúdo |
|---|---|
| [referencia/api.md](referencia/api.md) | todas as rotas, com método, acesso exigido e descrição |
| [referencia/dados.md](referencia/dados.md) | dicionário das tabelas + diagramas ER por domínio |
| [referencia/permissoes.md](referencia/permissoes.md) | matriz papel × rota, superfície pública, áreas |
| [referencia/config.md](referencia/config.md) | toda variável de ambiente lida pelo código |

Regerar depois de mexer em rota, modelo ou variável de ambiente:

```bash
python scripts/gerar_docs.py
```

`tests/test_docs_sincronia.py` **quebra a suíte** se estiverem defasados. Foi
esta pasta que acumulou quatro guias de implantação divergentes e uma tabela
mandando rodar um script de backup já removido — a camada gerada existe para que
isso não volte a acontecer com a parte que dá para automatizar.

### Arquitetura

- [arquitetura/VISAO_GERAL.md](arquitetura/VISAO_GERAL.md) — comece aqui
- [arquitetura/EVENTOS.md](arquitetura/EVENTOS.md) — tempo real, rooms, replay
- [arquitetura/decisoes/](arquitetura/decisoes/) — **10 ADRs**: por que cada
  coisa estrutural é como é

### Operação

- [operacao/RUNBOOK.md](operacao/RUNBOOK.md) — subir, derrubar, publicar,
  restaurar, destravar, e a tabela de sintomas
- [GUIA_DEPLOY_WINDOWS.md](GUIA_DEPLOY_WINDOWS.md) — instalar numa máquina nova
- [ACESSO_REMOTO.md](ACESSO_REMOTO.md) — túnel Cloudflare e PWA

### Funcional

Um documento por módulo — ver o índice em [funcional/](funcional/):
[Documentos](funcional/documentos.md) ·
[Equipamentos](funcional/equipamentos.md) ·
[Consumíveis](funcional/consumiveis.md) ·
[Projetos](funcional/projetos-entregaveis.md) ·
[Missões](funcional/missoes.md) ·
[Custos](funcional/custos.md) ·
[Tempos](funcional/tempos.md) ·
[PDR](funcional/pdr.md) ·
[Acesso e usuários](funcional/acesso-usuarios.md)

---

## Como o DocTrack roda em produção hoje

| | |
|---|---|
| **Servidor WSGI** | `waitress`, via `wsgi:app` (nunca `servidor:app` — veja o docstring de [`wsgi.py`](../wsgi.py)) |
| **Serviço Windows** | NSSM, instalado por [`scripts/deploy_windows.ps1`](../scripts/deploy_windows.ps1) |
| **Banco** | PostgreSQL em `localhost:5432/doctrack`, via `DATABASE_URL` no `.env` |
| **Backup** | `pg_dump` diário às 02:00 (tarefa `DocTrack - Backup Diario`) por [`scripts/gerar_backup.ps1`](../scripts/gerar_backup.ps1) |
| **PDF de relatório** | Gerado **no navegador** com jsPDF. Não instale GTK3/WeasyPrint — ver [ADR-0007](arquitetura/decisoes/ADR-0007-pdf-no-navegador.md) |

Essa combinação não é escolha deste índice: está afirmada no próprio código —
[`wsgi.py`](../wsgi.py) documenta o entrypoint waitress, [`ratelimit.py`](../ratelimit.py)
justifica o estado em memória com "o app roda em um processo (waitress com threads)",
e o comentário em `templates/config.html` registra que as descrições fixas antigas
"mentiam em produção, que roda waitress sobre PostgreSQL".

---

## Os outros três guias de implantação — o que são e quando servem

| Arquivo | Estratégia | Situação |
|---|---|---|
| [DEPLOYMENT.md](DEPLOYMENT.md) | PM2 (Node) + Python | **Histórico.** Foi a primeira implantação. Não há `ecosystem.config.js` no repositório. O Passo 5 (backup PostgreSQL) continua correto e é a referência de restauração. |
| [DEPLOY_SERVIDOR.md](DEPLOY_SERVIDOR.md) | Executável PyInstaller | **Alternativa para servidor sem admin e sem Python.** Empacota SQLite junto — não fala com o PostgreSQL de produção. Use só nesse cenário. |
| [INTEGRACAO_TI_AZURE_SHAREPOINT.md](INTEGRACAO_TI_AZURE_SHAREPOINT.md) | Azure + SSO + SharePoint | **Proposta, não implantada.** Material para conversa com o TI. |

Se você mudar a estratégia vigente, **atualize a tabela acima** e rebaixe a
anterior para "histórico" — foi a ausência disso que criou o problema.

---

## Limites conhecidos do backup

Detalhados no [RUNBOOK](operacao/RUNBOOK.md#o-que-o-backup-não-cobre); resumidos
aqui porque são risco operacional, não detalhe de implantação:

1. Os dumps ficam **no mesmo disco do banco**. Uma falha de disco leva os dois.
   Copiar os `.sql` para fora da máquina continua pendente.
2. O banco guarda o **caminho** dos documentos, não os arquivos. Os `.docx`/`.pdf`
   vivem em `\\loccus-srv03\Projetos$\Engenharia` e dependem do backup daquele
   servidor. Restaurar o `pg_dump` traz o sistema de volta, não os documentos —
   ver [ADR-0001](arquitetura/decisoes/ADR-0001-caminho-no-banco.md).

O [guia de validação ANVISA](referencias/) exige "Backup, Restauração e Recuperação
de Dados" — os dois itens acima são as lacunas a fechar antes de uma auditoria.

---

## Demais documentos

- [FLUXO_DESENVOLVIMENTO.md](FLUXO_DESENVOLVIMENTO.md) — branches, PRs e testes.
- [Documentacao_Geracao_PDF.md](Documentacao_Geracao_PDF.md) — **histórico**: a
  primeira das três gerações do relatório PDF.
- `planos/` — planejamento por módulo. Dizem o que **ia** ser feito; para o que
  **ficou**, veja [`funcional/`](funcional/).
- `superpowers/plans/` e `superpowers/specs/` — planos e specs datados no nome.
- `mockups/` — protótipos de tela.
- `referencias/` — normas ANVISA/ISPE que o sistema precisa atender.

---

## O que esta documentação **não** cobre

**Documentação de validação (CSV/ANVISA).** URS, especificação funcional, IQ/OQ/PQ,
matriz de rastreabilidade e controle de mudança formal não existem. A
matéria-prima está aqui — a suíte de testes serve de base para o OQ, `audit_logs`
é trilha de auditoria, o CHANGELOG é controle de mudança — mas amarrar
requisito → teste → evidência é um trabalho à parte, e maior que este.

**Manual do usuário final.** Toda esta documentação é técnica.
