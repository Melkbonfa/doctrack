# Fluxo de desenvolvimento e versionamento — DocTrack

Documento de processo. Objetivo: evoluir o app sem criar dificuldade para os
usuários em produção.

## Ambientes

| Ambiente | Onde | Banco | Quem usa |
|---|---|---|---|
| **Produção** | servidor separado | Postgres (`DATABASE_URL`) | usuários reais |
| **Homologação** | esta máquina | SQLite local `doctrack.db` (sem `DATABASE_URL`) | validação interna |

> ⚠️ O app aplica migração de schema **no startup**. Por isso, o ambiente de
> homologação **nunca** deve ter `DATABASE_URL` apontando para o Postgres de
> produção — senão a alteração entra para os usuários ao subir o servidor.
> Sem `DATABASE_URL`, o app usa o SQLite local (`doctrack.db`, ao lado de
> `servidor.py`), isolado.

O `.env` da pasta também conta: `python-dotenv` o carrega na subida. Numa
máquina que tenha um `.env` de produção, limpar a variável na sessão não basta —
rode a homologação a partir de outra pasta (um worktree), com `.env` próprio.

## Como rodar a homologação (local, seguro)

```powershell
# Garanta que NÃO existe DATABASE_URL apontando para produção:
$env:DATABASE_URL = $null
# Backup do banco local antes de testar mudanças de schema:
Copy-Item doctrack.db "doctrack.db.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
# Subir (porta 5000):
python servidor.py
```

`python servidor.py` sobe sempre na porta 5000. Para ter a homologação ao lado
de outro DocTrack na mesma máquina, suba em outra porta com o waitress:

```powershell
.\venv\Scripts\waitress-serve.exe --listen=127.0.0.1:5393 --threads=16 wsgi:app
```

Sob o waitress o tempo real é só polling, como em produção — o que faz desse o
jeito mais fiel de validar. Para ter dados de demonstração em vez de um banco
vazio, veja `scripts/semear_demo.py`.

## Fluxo de mudança

1. **Branch** a partir de `main`: `feat/...`, `fix/...` ou `chore/...`.
2. Implementar, com commits descritivos.
3. Validar na **homologação** (banco isolado), usando o sistema como usuário.
   Vem **antes** do pull request: o que chega ao PR já foi visto funcionando.
4. Atualizar a **documentação** (ver abaixo).
5. Atualizar `CHANGELOG.md` (bloco "Não lançado") e, ao liberar, `VERSION`.
6. Rodar a suíte: `python -m pytest`.
7. Abrir o **pull request** para `main` e fazer o merge.
8. Publicar em produção, seguindo o
   [RUNBOOK](operacao/RUNBOOK.md#publicar-uma-versão-nova): backup, `git pull`,
   restart, conferir o log da subida.

`main` pode estar à frente de produção: o merge não publica nada sozinho.
`/api/version` e `git log -1` no servidor dizem o que está no ar.

## Documentação, no passo 4

A documentação técnica está em [docs/](README.md), em quatro camadas. O que fazer
depende do que você mexeu:

| Você mexeu em | Faça |
|---|---|
| rota, modelo, variável de ambiente | `python scripts/gerar_docs.py` |
| regra de negócio de um módulo | atualize [`funcional/<modulo>.md`](funcional/) |
| algo estrutural (novo mecanismo, nova premissa) | acrescente um ADR em [`arquitetura/decisoes/`](arquitetura/decisoes/) |
| deploy, backup, operação | atualize [`operacao/RUNBOOK.md`](operacao/RUNBOOK.md) |

A primeira linha é obrigatória e verificada: `tests/test_docs_sincronia.py`
falha se a referência gerada estiver defasada. As outras três dependem de
disciplina — nenhum teste sabe se um documento funcional está certo.

> Modelo novo em `models.py` **derruba o gerador** de propósito, até você
> declarar a que domínio ele pertence em `DOMINIOS` (`scripts/gerar_docs.py`).
> É a decisão mais barata de tomar na hora em que o modelo nasce.

## Versionamento (SemVer)

- Versão fica em `VERSION` (lida pelo app em `/api/version`).
- Durante o desenvolvimento usa sufixo `-dev` (ex.: `4.1.0-dev`).
- Ao liberar, remove o `-dev`, move o bloco "Não lançado" do `CHANGELOG.md`
  para a versão datada e cria a tag git:

```bash
git tag -a v4.1.0 -m "Equipamento + 9 tipos de documento"
```

## Migrações de banco

Dois mecanismos coexistem
([ADR-0002](arquitetura/decisoes/ADR-0002-schema-no-startup.md)):

1. **O que roda na subida**, em `servidor.init_app()` — é o que vale em produção:
   - `db.create_all()` cria as tabelas novas;
   - `_sync_schema()` adiciona colunas e índices a tabelas existentes, de forma
     idempotente, em SQLite e PostgreSQL;
   - os backfills de dados, também idempotentes.
2. **`migrations/0NN_*.py`** — scripts SQLite numerados que espelham as mesmas
   mudanças, para quem prefere aplicar no banco antes de trocar o código.
   Numerar em sequência.

Coluna nova num modelo que já existe precisa entrar em `_sync_schema()`:
`create_all()` não altera tabela existente, e o SQLite da homologação esconde o
problema quando o banco é recriado do zero. O mesmo vale para índice de coluna
nova, que `tests/test_schema_sync.py` confere.

Toda migração deve ser **idempotente** (rodar duas vezes não quebra) e
**aditiva**: não há `downgrade`, então a prática é soft delete e coluna nova,
nunca `DROP`.
