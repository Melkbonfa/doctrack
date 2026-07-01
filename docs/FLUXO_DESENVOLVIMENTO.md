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
> Sem `DATABASE_URL`, o app usa o SQLite local (`servidor.py:58`), isolado.

## Como rodar a homologação (local, seguro)

```powershell
# Garanta que NÃO existe DATABASE_URL apontando para produção:
$env:DATABASE_URL = $null
# Backup do banco local antes de testar mudanças de schema:
Copy-Item doctrack.db "doctrack.db.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
# Subir em porta de teste:
python servidor.py
```

## Fluxo de mudança

1. **Branch** a partir de `main`: `feat/...`, `fix/...` ou `chore/...`.
2. Implementar + **commits locais** descritivos (não dar push enquanto valida).
3. Validar na **homologação** (esta máquina, banco isolado).
4. Atualizar `CHANGELOG.md` e `VERSION`.
5. Após aprovação: merge em `main`, tag de versão e deploy para produção.

## Versionamento (SemVer)

- Versão fica em `VERSION` (lida pelo app em `/api/version`).
- Durante o desenvolvimento usa sufixo `-dev` (ex.: `4.1.0-dev`).
- Ao liberar, remove o `-dev`, move o bloco "Não lançado" do `CHANGELOG.md`
  para a versão datada e cria a tag git:

```bash
git tag -a v4.1.0 -m "Equipamento + 9 tipos de documento"
```

## Migrações de banco

Dois mecanismos coexistem (ver `servidor.py`):
- `_sync_schema()` — adiciona colunas idempotentes em produção (Postgres) e local.
- Bloco de startup — cria tabelas/backfill de dados (idempotente).
- `migrations/00N_*.py` — scripts SQLite locais, espelham as mudanças para quem
  roda o banco de arquivo. Numerar em sequência.

Toda migração deve ser **idempotente** (rodar duas vezes não quebra) e
**reversível** quando possível (soft delete em vez de DROP).
