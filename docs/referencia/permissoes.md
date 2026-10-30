<!-- GERADO POR scripts/gerar_docs.py — NÃO EDITE À MÃO.
     Para mudar este arquivo, mude o código e rode:
         python scripts/gerar_docs.py
     tests/test_docs_sincronia.py falha se ele estiver defasado. -->


# Permissões

## Os quatro papéis

| Papel | Alcance |
|---|---|
| `admin` | tudo, incluindo gestão de usuários e exclusões |
| `gestor` | escrita em todos os módulos; sem gestão de usuários |
| `tecnico` | escrita no dia a dia; sem exclusão nem custos |
| `leitura` | consulta apenas |

Papel é global (coluna `users.role`). **Área** é ortogonal a ele (coluna `users.areas`): dá ou nega acesso a um recorte da empresa — ver [`areas.py`](../../areas.py). `admin` ignora a checagem de área.

## Matriz papel × rota

Contagem de rotas que cada papel alcança, por arquivo. Rotas `públicas` e `autenticadas` contam para todos os papéis.

| Arquivo | `admin` | `gestor` | `tecnico` | `leitura` | total |
|---|---|---|---|---|---|
| `auth.py` | 11 | 7 | 6 | 6 | 11 |
| `cadernos/routes.py` | 55 | 55 | 55 | 55 | 55 |
| `custos/routes.py` | 19 | 19 | 2 | 2 | 19 |
| `documentos.py` | 25 | 25 | 17 | 13 | 25 |
| `entregaveis.py` | 44 | 42 | 12 | 0 | 44 |
| `fluxos/routes.py` | 17 | 17 | 14 | 2 | 17 |
| `killswitch.py` | 4 | 4 | 4 | 4 | 4 |
| `missoes.py` | 33 | 33 | 31 | 0 | 33 |
| `notificacoes/routes.py` | 4 | 4 | 4 | 0 | 4 |
| `pdr/routes.py` | 9 | 8 | 3 | 2 | 16 |
| `servidor.py` | 63 | 62 | 52 | 32 | 63 |
| `tempos/routes.py` | 18 | 18 | 18 | 2 | 18 |

## Superfície pública

As **8** rotas de API alcançáveis sem token. Esta lista deve ser curta e conhecida — cada linha é superfície de ataque, e é por causa dela que existe [`ratelimit.py`](../../ratelimit.py).

| Método | Rota | Arquivo |
|---|---|---|
| `POST` | `/api/auth/login` | `auth.py` |
| `POST` | `/api/auth/primeiro-acesso` | `auth.py` |
| `POST` | `/cadernos/api/importacoes/assistente/aviso` | `cadernos/routes.py` |
| `POST` | `/cadernos/api/importacoes/assistente/pacote` | `cadernos/routes.py` |
| `POST` | `/api/kill-switch/lock` | `killswitch.py` |
| `GET` | `/api/kill-switch/status` | `killswitch.py` |
| `POST` | `/api/kill-switch/unlock` | `killswitch.py` |
| `GET` | `/api/version` | `servidor.py` |

### As 22 rotas de página não entram na conta acima

Elas respondem sem token, mas só devolvem HTML vazio: o token é validado no front e **todo dado chega por `/api/*`**, que é gatilhado. Ver [ADR-0004](../arquitetura/decisoes/ADR-0004-pagina-casca-api-gatilhada.md).


## Rotas restritas a `admin`

| Método | Rota | Arquivo |
|---|---|---|
| `POST` | `/api/users` | `auth.py` |
| `DELETE` | `/api/users/<int:user_id>` | `auth.py` |
| `PATCH` | `/api/users/<int:user_id>` | `auth.py` |
| `POST` | `/api/users/<int:user_id>/reset-senha` | `auth.py` |
| `POST` | `/api/modelos/propagacao` | `entregaveis.py` |
| `GET` | `/api/modelos/propagacao/previa` | `entregaveis.py` |
| `POST` | `/pdr/api/reimport` | `pdr/routes.py` |
| `POST` | `/api/admin/tarefas-diarias` | `servidor.py` |

## Áreas e módulos


### P&D Equipamentos (`pde`)

Home: `/hub/pde`

| Módulo | URL | Papel mínimo |
|---|---|---|
| Equipamentos | `/equipamentos` | qualquer membro da área |
| Documentos | `/` | qualquer membro da área |
| Projetos | `/projetos?area=pde` | gestor |
| Missões | `/missoes` | tecnico |
| Custos | `/custos/` | gestor |
| Tempos | `/tempos/` | tecnico |
| Fluxos | `/fluxos/` | tecnico |

### P&D Reagentes (`pdr`)

Home: `/pdr/`

| Módulo | URL | Papel mínimo |
|---|---|---|

### Inovação (`inov`)

Home: `/hub/inov`

| Módulo | URL | Papel mínimo |
|---|---|---|
| Projetos | `/projetos?area=inov` | gestor |
| Fluxos | `/fluxos/` | tecnico |
