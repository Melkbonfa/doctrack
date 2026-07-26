# Documentação do DocTrack — por onde começar

Este arquivo existe porque `docs/` acumulou **quatro** guias de implantação, cada um
escrito como se fosse o único, e nenhum dizia qual valia. Quem chegava novo instalava
a pilha errada. A regra agora é: **comece por aqui**.

---

## Como o DocTrack roda em produção hoje

| | |
|---|---|
| **Servidor WSGI** | `waitress`, via `wsgi:app` (nunca `servidor:app` — veja o docstring de [`wsgi.py`](../wsgi.py)) |
| **Serviço Windows** | NSSM, instalado por [`scripts/deploy_windows.ps1`](../scripts/deploy_windows.ps1) |
| **Banco** | PostgreSQL em `localhost:5432/doctrack`, via `DATABASE_URL` no `.env` |
| **Backup** | `pg_dump` diário às 02:00 (tarefa agendada `DocTrack - Backup Diario`) por [`scripts/gerar_backup.ps1`](../scripts/gerar_backup.ps1) |
| **PDF de relatório** | Gerado **no navegador** com jsPDF. Não instale GTK3/WeasyPrint. |

👉 **Guia a seguir: [GUIA_DEPLOY_WINDOWS.md](GUIA_DEPLOY_WINDOWS.md)** — instalação
passo a passo numa máquina nova.

Essa combinação não é escolha deste índice: está afirmada no próprio código —
[`wsgi.py`](../wsgi.py) documenta o entrypoint waitress, [`ratelimit.py`](../ratelimit.py)
justifica o estado em memória com "o app roda em um processo (waitress com threads)",
e o comentário em `templates/config.html` registra que as descrições fixas antigas
"mentiam em produção, que roda waitress sobre PostgreSQL".

---

## Os outros três guias — o que são e quando servem

| Arquivo | Estratégia | Situação |
|---|---|---|
| [DEPLOYMENT.md](DEPLOYMENT.md) | PM2 (Node) + Python | **Histórico.** Foi a primeira implantação. Não há `ecosystem.config.js` no repositório. O Passo 5 (backup PostgreSQL) continua correto e é a referência de restauração. |
| [DEPLOY_SERVIDOR.md](DEPLOY_SERVIDOR.md) | Executável PyInstaller | **Alternativa para servidor sem admin e sem Python.** Empacota SQLite junto — não fala com o PostgreSQL de produção. Use só nesse cenário. |
| [INTEGRACAO_TI_AZURE_SHAREPOINT.md](INTEGRACAO_TI_AZURE_SHAREPOINT.md) | Azure + SSO + SharePoint | **Proposta, não implantada.** Material para conversa com o TI. |

Se você mudar a estratégia vigente, **atualize a tabela acima** e rebaixe a anterior
para "histórico" — foi a ausência disso que criou o problema.

---

## Limites conhecidos do backup

Detalhados em [DEPLOYMENT.md](DEPLOYMENT.md#o-que-o-backup-não-cobre); resumidos aqui
porque são risco operacional, não detalhe de implantação:

1. Os dumps ficam **no mesmo disco do banco**. Uma falha de disco leva os dois.
   Copiar os `.sql` para fora da máquina continua pendente.
2. O banco guarda o **caminho** dos documentos, não os arquivos. Os `.docx`/`.pdf`
   vivem em `\\loccus-srv03\Projetos$\Engenharia` e dependem do backup daquele
   servidor. Restaurar o `pg_dump` traz o sistema de volta, não os documentos.

O [guia de validação ANVISA](referencias/) exige "Backup, Restauração e Recuperação
de Dados" — os dois itens acima são as lacunas a fechar antes de uma auditoria.

---

## Demais documentos

- [FLUXO_DESENVOLVIMENTO.md](FLUXO_DESENVOLVIMENTO.md) — branches, PRs e testes.
- [Documentacao_Geracao_PDF.md](Documentacao_Geracao_PDF.md) — como o relatório PDF é
  montado no cliente.
- `planos/` — planejamento por módulo (consumíveis, equipamentos, entregáveis…).
- `superpowers/plans/` e `superpowers/specs/` — planos e specs datados no nome.
- `mockups/` e `relatorios/` — protótipos de tela e relatórios gerados.
- `referencias/` — normas ANVISA/ISPE que o sistema precisa atender.
