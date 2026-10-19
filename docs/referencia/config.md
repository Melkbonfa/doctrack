<!-- GERADO POR scripts/gerar_docs.py — NÃO EDITE À MÃO.
     Para mudar este arquivo, mude o código e rode:
         python scripts/gerar_docs.py
     tests/test_docs_sincronia.py falha se ele estiver defasado. -->


# Variáveis de ambiente

**38** variáveis lidas pelo código. **13** aparecem no `.env.example`.

O `.env.example` é o arquivo para copiar e editar, e explica *por que* cada variável importante existe. Esta tabela é o inventário completo: existe para que nenhuma variável fique só no código.

| Variável | Padrão | Onde é lida | No `.env.example` |
|---|---|---|---|
| `BCRYPT_LOG_ROUNDS` | `"12"` | `servidor.py` | **não** |
| `CADERNOS_LIXEIRA_DIAS` | `"60"` | `cadernos/routes.py` | **não** |
| `CORS_ORIGINS` | `"*"` | `servidor.py` | sim |
| `DATABASE_URL` | `""` | `scripts/migrar_sqlite_para_postgres.py`, `scripts/seed_demo.py`, `scripts/semear_demo.py` (+2) | sim |
| `DOCTRACK_AGENDADOR` | `"1"` | `scheduler.py` | **não** |
| `DOCTRACK_AGENDADOR_INTERVALO` | `"900"` | `scheduler.py` | **não** |
| `DOCTRACK_ARQUIVOS` | **obrigatória** | `arquivos_store.py` | sim |
| `DOCTRACK_AUDIT_RETENCAO_DIAS` | `"0"` | `servidor.py` | **não** |
| `DOCTRACK_CAMBIO` | `"1"` | `custos/cambio.py` | **não** |
| `DOCTRACK_CAMBIO_JANELA` | `"15"` | `custos/cambio.py` | **não** |
| `DOCTRACK_CAMBIO_TIMEOUT` | `"8"` | `custos/cambio.py` | **não** |
| `DOCTRACK_DIAG_TIMEOUT` | `"20"` | `diagnostico.py` | **não** |
| `DOCTRACK_EQUIP_MASTER` | `r"P:\Engenharia\Projetos\1. Produtos\Equipamentos Cadastrados.xlsx",` | `equipamentos_importer.py` | **não** |
| `DOCTRACK_FILE_ROOTS` | `_RAIZ_PADRAO` | `caminhos.py` | sim |
| `DOCTRACK_IMPORT_MAX_MB` | `"1024"` | `cadernos/importacao.py` | **não** |
| `DOCTRACK_JANELA_ATIVACAO` | `"900"` | `ratelimit.py` | **não** |
| `DOCTRACK_JANELA_IP` | `"300"` | `ratelimit.py` | **não** |
| `DOCTRACK_JANELA_KILLSWITCH` | `"900"` | `ratelimit.py` | sim |
| `DOCTRACK_JANELA_LOGIN` | `"300"` | `ratelimit.py` | **não** |
| `DOCTRACK_KILL_TOKEN` | **obrigatória** | `scripts/kill_switch.py` | **não** |
| `DOCTRACK_LIMITE_ATIVACAO` | `"5"` | `ratelimit.py` | **não** |
| `DOCTRACK_LIMITE_IP` | `"30"` | `ratelimit.py` | **não** |
| `DOCTRACK_LIMITE_KILLSWITCH` | `"3"` | `ratelimit.py` | sim |
| `DOCTRACK_LIMITE_LOGIN` | `"5"` | `ratelimit.py` | **não** |
| `DOCTRACK_LOCK_TTL` | `"3"` | `killswitch.py` | sim |
| `DOCTRACK_PATH_ALIASES` | `""` | `caminhos.py` | sim |
| `DOCTRACK_RATELIMIT` | `"1"` | `ratelimit.py` | **não** |
| `DOCTRACK_SEED_DEMO` | `""` | `scripts/seed_demo.py` | **não** |
| `DOCTRACK_SENHA_MIN` | `"8"` | `auth.py` | **não** |
| `DOCTRACK_TEMPO_LIMITE_H` | `""` | `migrations/013_modulo_tempos.py` | **não** |
| `DOCTRACK_UPLOAD_BIN_MAX_MB` | `"500"` | `arquivos_store.py` | sim |
| `DOCTRACK_UPLOAD_MAX_MB` | `"80"` | `arquivos_store.py` | sim |
| `DOCTRACK_URL` | `"http://localhost:5000"` | `scripts/kill_switch.py` | **não** |
| `FLASK_DEBUG` | `"False"` | `servidor.py` | sim |
| `JWT_SECRET` | **obrigatória** | `servidor.py` | sim |
| `PDR_EXCEL_PATH` | `os.path.join(DATA_DIR, "Lista_Mestra_PDR_tratada.xlsx"` | `pdr/importer.py` | **não** |
| `PORT` | `"5099"` | `scripts/preview_server.py` | **não** |
| `TRUST_PROXY` | `""` | `servidor.py`, `utils.py` | sim |

## Lidas pelo código e ausentes do `.env.example`

Cada uma destas muda comportamento em produção sem estar no arquivo que o operador copia. Não é erro por si só (várias são chaves de teste), mas é a lista para revisar.

- `BCRYPT_LOG_ROUNDS` — padrão `"12"`, em `servidor.py`
- `CADERNOS_LIXEIRA_DIAS` — padrão `"60"`, em `cadernos/routes.py`
- `DOCTRACK_AGENDADOR` — padrão `"1"`, em `scheduler.py`
- `DOCTRACK_AGENDADOR_INTERVALO` — padrão `"900"`, em `scheduler.py`
- `DOCTRACK_AUDIT_RETENCAO_DIAS` — padrão `"0"`, em `servidor.py`
- `DOCTRACK_CAMBIO` — padrão `"1"`, em `custos/cambio.py`
- `DOCTRACK_CAMBIO_JANELA` — padrão `"15"`, em `custos/cambio.py`
- `DOCTRACK_CAMBIO_TIMEOUT` — padrão `"8"`, em `custos/cambio.py`
- `DOCTRACK_DIAG_TIMEOUT` — padrão `"20"`, em `diagnostico.py`
- `DOCTRACK_EQUIP_MASTER` — padrão `r"P:\Engenharia\Projetos\1. Produtos\Equipamentos Cadastrados.xlsx",`, em `equipamentos_importer.py`
- `DOCTRACK_IMPORT_MAX_MB` — padrão `"1024"`, em `cadernos/importacao.py`
- `DOCTRACK_JANELA_ATIVACAO` — padrão `"900"`, em `ratelimit.py`
- `DOCTRACK_JANELA_IP` — padrão `"300"`, em `ratelimit.py`
- `DOCTRACK_JANELA_LOGIN` — padrão `"300"`, em `ratelimit.py`
- `DOCTRACK_KILL_TOKEN` — obrigatória, em `scripts/kill_switch.py`
- `DOCTRACK_LIMITE_ATIVACAO` — padrão `"5"`, em `ratelimit.py`
- `DOCTRACK_LIMITE_IP` — padrão `"30"`, em `ratelimit.py`
- `DOCTRACK_LIMITE_LOGIN` — padrão `"5"`, em `ratelimit.py`
- `DOCTRACK_RATELIMIT` — padrão `"1"`, em `ratelimit.py`
- `DOCTRACK_SEED_DEMO` — padrão `""`, em `scripts/seed_demo.py`
- `DOCTRACK_SENHA_MIN` — padrão `"8"`, em `auth.py`
- `DOCTRACK_TEMPO_LIMITE_H` — padrão `""`, em `migrations/013_modulo_tempos.py`
- `DOCTRACK_URL` — padrão `"http://localhost:5000"`, em `scripts/kill_switch.py`
- `PDR_EXCEL_PATH` — padrão `os.path.join(DATA_DIR, "Lista_Mestra_PDR_tratada.xlsx"`, em `pdr/importer.py`
- `PORT` — padrão `"5099"`, em `scripts/preview_server.py`
