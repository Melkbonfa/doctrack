<!-- GERADO POR scripts/gerar_docs.py — NÃO EDITE À MÃO.
     Para mudar este arquivo, mude o código e rode:
         python scripts/gerar_docs.py
     tests/test_docs_sincronia.py falha se ele estiver defasado. -->


# Referência da API

300 rotas registradas: **167** de API (`/api/...`) e **133** de página.

A coluna **Acesso** é lida dos decorators no fonte:

| Rótulo | Significa |
|---|---|
| `público` | sem token — alcançável por qualquer um na rede |
| `autenticado` | qualquer usuário logado (`@jwt_required`) |
| lista de papéis | só esses papéis (`@require_role`) |
| `área X + papéis` | precisa da área no cadastro (`@require_area`) |

> Com o kill switch acionado **tudo** aqui responde `423`, menos as rotas de `killswitch.py` e `/api/version`. Ver [ADR-0006](../arquitetura/decisoes/ADR-0006-kill-switch-fora-do-banco.md).


## `auth.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `POST` | `/api/auth/login` | público |  |
| `POST` | `/api/auth/logout` | autenticado | B2: revoga o JTI do token atual (blocklist). |
| `GET` | `/api/auth/me` | autenticado |  |
| `POST` | `/api/auth/primeiro-acesso` | público | Rota pública: o usuário troca o código de ativação pela própria senha. |
| `POST` | `/api/auth/refresh` | autenticado |  |
| `GET` | `/api/users` | admin, gestor |  |
| `POST` | `/api/users` | admin |  |
| `DELETE` | `/api/users/<int:user_id>` | admin | DELETE soft (ativo=False) por padrão. |
| `GET` | `/api/users/<int:user_id>` | autenticado |  |
| `PATCH` | `/api/users/<int:user_id>` | admin |  |
| `POST` | `/api/users/<int:user_id>/reset-senha` | admin | Devolve a conta ao estado de primeiro acesso: limpa a senha e gera um |

## `cadernos/routes.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `GET` | `/cadernos` | página (casca) |  |
| `GET` | `/cadernos/` | página (casca) |  |
| `GET` | `/cadernos/api/arquivos` | autenticado | Arquivos (versão atual) de um escopo: ?caderno=&escopo=&ref=. |
| `POST` | `/cadernos/api/arquivos` | autenticado | Envia um arquivo de qualquer extensão para o caderno, uma seção ou página. |
| `DELETE` | `/cadernos/api/arquivos/<uuid_>` | autenticado | Manda o arquivo (todas as versões) para a lixeira. O blob só sai na purga. |
| `PATCH` | `/cadernos/api/arquivos/<uuid_>` | autenticado | Pasta, descrição e se entra na exportação (vale para a família toda). |
| `GET` | `/cadernos/api/arquivos/<uuid_>/conteudo` | autenticado | Serve o arquivo. Imagem e PDF podem abrir no navegador; todo o resto desce |
| `POST` | `/cadernos/api/arquivos/<uuid_>/restaurar` | autenticado | Tira o arquivo (todas as versões) da lixeira. |
| `POST` | `/cadernos/api/arquivos/<uuid_>/versao` | autenticado | Substitui o arquivo por uma versão nova; a anterior continua baixável. |
| `GET` | `/cadernos/api/arquivos/<uuid_>/versoes` | autenticado | Todas as versões do arquivo (a mais nova primeiro). |
| `GET` | `/cadernos/api/busca` | autenticado | Busca por todas as palavras (sem acento, sem caixa) nos cadernos visíveis. |
| `GET` | `/cadernos/api/cadernos` | autenticado | Cadernos que a pessoa enxerga na área. |
| `POST` | `/cadernos/api/cadernos` | autenticado | Cria um caderno. Quem cria vira dono; o modelo define as seções iniciais. |
| `DELETE` | `/cadernos/api/cadernos/<uuid_>` | autenticado | Manda o caderno para a lixeira (some para todos; o dono restaura). |
| `GET` | `/cadernos/api/cadernos/<uuid_>` | autenticado | Caderno, papel da pessoa e (para o dono) os membros. |
| `PATCH` | `/cadernos/api/cadernos/<uuid_>` | autenticado | Nome, cor, descrição, acesso da área, arquivado. |
| `GET` | `/cadernos/api/cadernos/<uuid_>/arvore` | autenticado | Grupos, seções e páginas (sem conteúdo), com quem está editando. |
| `POST` | `/cadernos/api/cadernos/<uuid_>/exportacao/previa` | autenticado | Páginas escolhidas + todos os arquivos que podem ir no pacote, com o que |
| `GET` | `/cadernos/api/cadernos/<uuid_>/exportacoes` | autenticado | Histórico: o que já foi enviado deste caderno, por quem e quando. |
| `POST` | `/cadernos/api/cadernos/<uuid_>/exportacoes` | autenticado | Gera o zip (relatório .docx + imagens + arquivos marcados + LEIA-ME). |
| `PUT` | `/cadernos/api/cadernos/<uuid_>/membros` | autenticado | Substitui a lista de membros explícitos: [{user_id, papel}]. |
| `POST` | `/cadernos/api/cadernos/<uuid_>/nos` | autenticado | Novo grupo de seções ou seção, no fim do nível escolhido. |
| `POST` | `/cadernos/api/cadernos/<uuid_>/restaurar` | autenticado | Tira o caderno da lixeira. |
| `GET` | `/cadernos/api/exportacoes/<uuid_>/zip` | autenticado | Baixa o zip gerado (fica disponível por um dia). Aceita `?token=`. |
| `POST` | `/cadernos/api/importacoes` | autenticado | Recebe o .zip do assistente, valida e devolve o resumo para confirmar. |
| `DELETE` | `/cadernos/api/importacoes/<id_>` | autenticado |  |
| `POST` | `/cadernos/api/importacoes/<id_>/iniciar` | autenticado | Confirma: grava o caderno (tarefa). Reimportar exige ser editor do caderno. |
| `GET` | `/cadernos/api/lixeira` | autenticado | O que foi excluído no caderno nos últimos dias (seções, grupos, páginas, arquivos). |
| `GET` | `/cadernos/api/meta` | autenticado | Quem sou eu, a área, os modelos e as pessoas da área (ficha e membros). |
| `DELETE` | `/cadernos/api/nos/<uuid_>` | autenticado | Manda a seção (ou o grupo, com tudo dentro) para a lixeira. |
| `PATCH` | `/cadernos/api/nos/<uuid_>` | autenticado | Renomeia, muda a cor ou o tipo de página padrão. |
| `POST` | `/cadernos/api/nos/<uuid_>/mover` | autenticado | Reordena entre irmãos e/ou troca de grupo: {parent_uuid\|null, apos_uuid\|null}. |
| `POST` | `/cadernos/api/nos/<uuid_>/restaurar` | autenticado | Tira a seção/grupo da lixeira. |
| `GET` | `/cadernos/api/onenote/assistente` | autenticado | O .cmd que extrai um caderno do OneNote na máquina de quem o tem aberto. |
| `DELETE` | `/cadernos/api/paginas/<uuid_>` | autenticado | Manda a página para a lixeira (as subpáginas sobem um nível). |
| `GET` | `/cadernos/api/paginas/<uuid_>` | autenticado | Conteúdo completo da página (HTML saneado, ficha, versão, trava). |
| `PATCH` | `/cadernos/api/paginas/<uuid_>` | autenticado | Título, data da página e recolher/expandir — sem passar pela trava, |
| `PUT` | `/cadernos/api/paginas/<uuid_>` | autenticado | Grava o conteúdo (autosave). Exige a trava e a versão em que o editor |
| `DELETE` | `/cadernos/api/paginas/<uuid_>/edicao` | autenticado | Solta a trava e fecha a sessão: o estado final vira uma versão. |
| `POST` | `/cadernos/api/paginas/<uuid_>/edicao` | autenticado | Pega a trava. Devolve a página fresca: o editor tem de começar da versão |
| `PUT` | `/cadernos/api/paginas/<uuid_>/edicao` | autenticado | Renova a trava (o front chama a cada ~30 s enquanto o editor está aberto). |
| `POST` | `/cadernos/api/paginas/<uuid_>/edicao/tomar` | autenticado | O dono do caderno toma a edição. O que já foi gravado pela outra pessoa |
| `POST` | `/cadernos/api/paginas/<uuid_>/imagens` | autenticado | Imagem colada ou enviada no editor. Vira arquivo embutido da página. |
| `POST` | `/cadernos/api/paginas/<uuid_>/mover` | autenticado | Move a página e suas subpáginas: {secao_uuid, apos_uuid\|null, nivel\|null}. |
| `POST` | `/cadernos/api/paginas/<uuid_>/nivel` | autenticado | Promove (delta -1) ou rebaixa (+1) a página junto com suas subpáginas. |
| `POST` | `/cadernos/api/paginas/<uuid_>/restaurar` | autenticado | Tira a página da lixeira (volta para o fim da seção; a seção também volta). |
| `GET` | `/cadernos/api/paginas/<uuid_>/versoes` | autenticado | Histórico da página, da mais nova para a mais antiga. |
| `GET` | `/cadernos/api/paginas/<uuid_>/versoes/<int:numero>` | autenticado | Conteúdo de uma versão. |
| `POST` | `/cadernos/api/paginas/<uuid_>/versoes/<int:numero>/restaurar` | autenticado | Volta a página para uma versão. O estado atual vira versão antes — restaurar |
| `POST` | `/cadernos/api/secoes/<uuid_>/paginas` | autenticado | Nova página: no fim, logo após outra (`apos_uuid`) ou como subpágina |
| `GET` | `/cadernos/api/tarefas/<id_>` | autenticado | Progresso de uma exportação/importação (só quem a iniciou vê). |

## `custos/routes.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `GET` | `/custos` | página (casca) |  |
| `GET` | `/custos/` | página (casca) |  |
| `GET` | `/custos/api/composicoes` | admin, gestor |  |
| `POST` | `/custos/api/composicoes` | admin, gestor |  |
| `DELETE` | `/custos/api/composicoes/<int:cid>` | admin, gestor |  |
| `GET` | `/custos/api/composicoes/<int:cid>` | admin, gestor |  |
| `PUT` | `/custos/api/composicoes/<int:cid>` | admin, gestor |  |
| `POST` | `/custos/api/composicoes/<int:cid>/lancamentos` | admin, gestor |  |
| `POST` | `/custos/api/composicoes/<int:cid>/versoes` | admin, gestor |  |
| `GET` | `/custos/api/cotacoes` | admin, gestor |  |
| `POST` | `/custos/api/cotacoes` | admin, gestor | Registro manual — o caminho que mantém o módulo utilizável sem internet. |
| `POST` | `/custos/api/cotacoes/sincronizar` | admin, gestor |  |
| `GET` | `/custos/api/export/composicoes.csv` | admin, gestor |  |
| `GET` | `/custos/api/export/custos.xlsx` | admin, gestor |  |
| `DELETE` | `/custos/api/lancamentos/<int:lid>` | admin, gestor |  |
| `PUT` | `/custos/api/lancamentos/<int:lid>` | admin, gestor |  |
| `GET` | `/custos/api/meta` | admin, gestor |  |
| `GET` | `/custos/api/portfolio` | admin, gestor | Comparativo entre composições e agregado por categoria. |
| `GET` | `/custos/api/saude` | admin, gestor |  |

## `documentos.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `PUT` | `/api/documento/<int:doc_id>/status` | admin, gestor, tecnico |  |
| `GET` | `/api/documentos` | autenticado |  |
| `POST` | `/api/documentos` | admin, gestor, tecnico |  |
| `DELETE` | `/api/documentos/<int:doc_id>` | admin, gestor |  |
| `GET` | `/api/documentos/<int:doc_id>` | autenticado |  |
| `PATCH` `PUT` | `/api/documentos/<int:doc_id>` | admin, gestor, tecnico |  |
| `PUT` | `/api/documentos/<int:doc_id>/aplicabilidade` | admin, gestor | Liga/desliga um tipo de documento no escopo do equipamento (N/A). |
| `GET` | `/api/documentos/<int:doc_id>/arquivos` | autenticado | Todos os arquivos já enviados para este documento (o mais novo primeiro, |
| `POST` | `/api/documentos/<int:doc_id>/arquivos` | admin, gestor | Adiciona um arquivo a este documento (multipart/form-data). |
| `GET` | `/api/documentos/<int:doc_id>/historico` | autenticado | Trilha do documento (mais recente primeiro) + tempo no status atual. |
| `POST` | `/api/documentos/abrir-pasta` | autenticado |  |
| `GET` | `/api/documentos/alertas` | autenticado | Fatos acionáveis derivados do que já está no banco. |
| `GET` | `/api/documentos/arquivo` | autenticado | Serve um arquivo individual: PDF/imagens inline (preview no navegador), |
| `GET` | `/api/documentos/arquivos` | autenticado | Lista os arquivos da pasta de armazenamento de um equipamento, |
| `DELETE` | `/api/documentos/arquivos/<int:arq_id>` | admin, gestor | Remove a versão (exclusão lógica: a linha e o blob ficam). |
| `GET` | `/api/documentos/arquivos/<int:arq_id>/conteudo` | autenticado | Serve o arquivo hospedado. PDF/imagem inline (para o visor da plataforma), |
| `GET` | `/api/documentos/diagnostico` | admin, gestor | Consistência entre o cadastro e o que existe de fato (ver `diagnostico.py`). |
| `GET` | `/api/documentos/export` | admin, gestor, tecnico | CSV bruto dos documentos ativos — análise fora do sistema (Excel/BI). |
| `GET` | `/api/documentos/metricas` | autenticado | Métricas de fluxo dos documentos — o mesmo conjunto que Missões já expõe. |
| `GET` | `/api/documentos/responsaveis` | autenticado | Usuários atribuíveis como responsável por um documento. |
| `GET` | `/api/equipamentos/<int:equip_id>/anexos` | autenticado | Anexos do equipamento. `?categoria=` filtra; sem ele, vêm todos. |
| `POST` | `/api/equipamentos/<int:equip_id>/anexos` | admin, gestor | Envia um doc agregado ou uma versão de software/firmware (multipart). |
| `DELETE` | `/api/equipamentos/anexos/<int:anexo_id>` | admin, gestor | Remove o anexo (exclusão lógica: a linha e o blob ficam). |
| `PATCH` | `/api/equipamentos/anexos/<int:anexo_id>` | admin, gestor | Corrige os metadados (título, versão, data, notas) sem reenviar o arquivo. |
| `GET` | `/api/equipamentos/anexos/<int:anexo_id>/conteudo` | autenticado | Serve o anexo. PDF/imagem podem abrir inline; binário, NUNCA. |

## `entregaveis.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `GET` | `/api/categorias-entregavel` | admin, gestor, tecnico | Categorias cadastradas + quanto cada uma é usada — é o que a tela mostra |
| `POST` | `/api/categorias-entregavel` | admin, gestor | Cria uma categoria no fim da lista (vira a última aba do projeto). |
| `DELETE` | `/api/categorias-entregavel/<int:cid>` | admin, gestor | Exclui a categoria. Recusa enquanto houver entregável ou item de modelo |
| `PUT` | `/api/categorias-entregavel/<int:cid>` | admin, gestor | Renomeia a categoria. O nome novo é propagado para os entregáveis |
| `PUT` | `/api/categorias-entregavel/ordem` | admin, gestor | Corpo: {"ids": [...]} com TODAS as categorias, na nova ordem. |
| `DELETE` | `/api/entregaveis/<int:eid>` | admin, gestor |  |
| `PUT` | `/api/entregaveis/<int:eid>` | admin, gestor, tecnico |  |
| `GET` | `/api/entregaveis/<int:eid>/historico` | admin, gestor, tecnico |  |
| `GET` | `/api/entregaveis/export` | admin, gestor |  |
| `GET` | `/api/entregaveis/responsaveis` | admin, gestor, tecnico | Usuários atribuíveis a um entregável (picker do front). |
| `GET` | `/api/entregaveis/resumo` | admin, gestor, tecnico |  |
| `GET` | `/api/modelos` | admin, gestor | Itens de modelo agrupados por tipo de projeto. |
| `POST` | `/api/modelos` | admin, gestor |  |
| `DELETE` | `/api/modelos/<int:mid>` | admin, gestor |  |
| `PUT` | `/api/modelos/<int:mid>` | admin, gestor |  |
| `PUT` | `/api/modelos/ordem` | admin, gestor | Corpo: {"tipo_projeto": "...", "ids": [...]} com TODOS os itens daquele |
| `POST` | `/api/modelos/propagacao` | admin | Corpo: {"tipo": "...", "projetos": {"<id>": "<versao>"}, |
| `GET` | `/api/modelos/propagacao/<int:mid>` | admin, gestor | Uma aplicação com o antes/depois agrupado por projeto. |
| `GET` | `/api/modelos/propagacao/historico` | admin, gestor | Aplicações de um modelo, da mais recente para a mais antiga. |
| `GET` | `/api/modelos/propagacao/previa` | admin | O que aplicar o modelo faria em cada projeto ativo dele. Não grava nada. |
| `GET` | `/api/projetos` | admin, gestor, tecnico |  |
| `POST` | `/api/projetos` | admin, gestor |  |
| `DELETE` | `/api/projetos/<int:pid>` | admin, gestor | Arquiva. `status` no corpo registra POR QUE saiu (concluído × cancelado). |
| `GET` | `/api/projetos/<int:pid>` | admin, gestor, tecnico |  |
| `PUT` | `/api/projetos/<int:pid>` | admin, gestor |  |
| `GET` | `/api/projetos/<int:pid>/baselines` | admin, gestor |  |
| `POST` | `/api/projetos/<int:pid>/baselines` | admin, gestor |  |
| `POST` | `/api/projetos/<int:pid>/entregaveis` | admin, gestor |  |
| `PUT` | `/api/projetos/<int:pid>/entregaveis/ordem` | admin, gestor | Reordena entregáveis do projeto. Corpo: {"ids": [...]} na nova ordem. |
| `GET` | `/api/projetos/<int:pid>/mensal` | admin, gestor |  |
| `PUT` | `/api/projetos/<int:pid>/mensal` | admin, gestor | Cria ou atualiza o CUSTO de uma competência (YYYY-MM). |
| `DELETE` | `/api/projetos/<int:pid>/mensal/<competencia>` | admin, gestor |  |
| `GET` | `/api/projetos/<int:pid>/mudancas-modelo` | admin, gestor | Aplicações de modelo que mexeram neste projeto, com o que mudou nele. |
| `POST` | `/api/projetos/<int:pid>/restaurar` | admin, gestor |  |
| `GET` | `/api/projetos/alertas` | admin, gestor, tecnico | Fatos acionáveis derivados do que já está no banco. |
| `GET` | `/api/tipos-projeto` | admin, gestor, tecnico | Tipos cadastrados + quanto cada um é usado (projetos, inclusive |
| `POST` | `/api/tipos-projeto` | admin, gestor | Cria um tipo. `copiar_de` (opcional) clona o modelo de entregáveis de um |
| `DELETE` | `/api/tipos-projeto/<int:tid>` | admin, gestor | Exclui o tipo e o modelo de entregáveis dele. Recusa enquanto houver |
| `PUT` | `/api/tipos-projeto/<int:tid>` | admin, gestor | Renomeia o tipo e/ou troca a área dele. O nome novo é propagado para os |

## `fluxos/routes.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `GET` | `/fluxos` | página (casca) |  |
| `GET` | `/fluxos/` | página (casca) |  |
| `GET` | `/fluxos/api/arquivos/<int:aid>/conteudo` | admin, gestor, tecnico |  |
| `GET` | `/fluxos/api/comigo` | admin, gestor, tecnico | Os fluxos cuja etapa atual é minha — o estado vivo, não as notificações. |
| `GET` | `/fluxos/api/em-andamento` | admin, gestor, tecnico |  |
| `POST` | `/fluxos/api/fluxos` | admin, gestor, tecnico |  |
| `GET` | `/fluxos/api/fluxos/<int:fid>` | admin, gestor, tecnico |  |
| `POST` | `/fluxos/api/fluxos/<int:fid>/acao` | admin, gestor, tecnico |  |
| `POST` | `/fluxos/api/fluxos/<int:fid>/cancelar` | admin, gestor, tecnico |  |
| `POST` | `/fluxos/api/fluxos/<int:fid>/reatribuir` | admin, gestor, tecnico |  |
| `GET` | `/fluxos/api/modelos` | admin, gestor, tecnico |  |
| `POST` | `/fluxos/api/modelos` | admin, gestor |  |
| `DELETE` | `/fluxos/api/modelos/<int:mid>` | admin, gestor |  |
| `PUT` | `/fluxos/api/modelos/<int:mid>` | admin, gestor |  |
| `GET` | `/fluxos/api/pessoas` | admin, gestor, tecnico |  |
| `GET` | `/fluxos/api/por-ref` | admin, gestor, tecnico |  |
| `GET` | `/fluxos/api/por-refs` | admin, gestor, tecnico |  |

## `killswitch.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `POST` | `/api/kill-switch/lock` | público |  |
| `GET` | `/api/kill-switch/status` | público | Público de propósito: a tela de bloqueio precisa consultá-la travado. |
| `POST` | `/api/kill-switch/unlock` | público |  |
| `GET` | `/travado` | página (casca) |  |

## `missoes.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `GET` | `/api/missoes` | admin, gestor, tecnico |  |
| `POST` | `/api/missoes` | admin, gestor, tecnico |  |
| `DELETE` | `/api/missoes/<int:mid>` | admin, gestor, tecnico | Arquiva por padrão. O DELETE era um `db.session.delete()` em cascata que |
| `GET` | `/api/missoes/<int:mid>` | admin, gestor, tecnico |  |
| `PATCH` | `/api/missoes/<int:mid>` | admin, gestor, tecnico |  |
| `POST` | `/api/missoes/<int:mid>/colunas` | admin, gestor, tecnico |  |
| `GET` | `/api/missoes/<int:mid>/export` | admin, gestor, tecnico | Cartões + métricas + trilha, para dinâmica/BI fora do sistema. |
| `GET` | `/api/missoes/<int:mid>/historico` | admin, gestor, tecnico |  |
| `GET` | `/api/missoes/<int:mid>/metricas` | admin, gestor, tecnico |  |
| `GET` | `/api/missoes/<int:mid>/snapshots` | admin, gestor, tecnico |  |
| `GET` | `/api/missoes/alertas` | admin, gestor, tecnico | Fatos acionáveis derivados do que já está no banco — mesmo formato dos |
| `POST` | `/api/missoes/cartao-rapido` | admin, gestor, tecnico | Cria um cartão já vinculado a uma entidade, sem sair da ficha dela. |
| `GET` | `/api/missoes/cartoes-vinculados` | admin, gestor, tecnico | Cartões (de missões ativas) vinculados às entidades pedidas, em lote: |
| `DELETE` | `/api/missoes/cartoes/<int:cid>` | admin, gestor, tecnico |  |
| `GET` | `/api/missoes/cartoes/<int:cid>` | admin, gestor, tecnico |  |
| `PATCH` | `/api/missoes/cartoes/<int:cid>` | admin, gestor, tecnico |  |
| `POST` | `/api/missoes/cartoes/<int:cid>/comentarios` | admin, gestor, tecnico |  |
| `GET` | `/api/missoes/cartoes/<int:cid>/historico` | admin, gestor, tecnico |  |
| `POST` | `/api/missoes/cartoes/<int:cid>/itens` | admin, gestor, tecnico |  |
| `DELETE` | `/api/missoes/colunas/<int:cid>` | admin, gestor, tecnico | Os cartões migram para outra coluna em vez de serem destruídos junto. |
| `PATCH` | `/api/missoes/colunas/<int:cid>` | admin, gestor, tecnico |  |
| `POST` | `/api/missoes/colunas/<int:cid>/cartoes` | admin, gestor, tecnico |  |
| `DELETE` | `/api/missoes/comentarios/<int:coid>` | admin, gestor, tecnico |  |
| `GET` | `/api/missoes/etiquetas` | admin, gestor, tecnico | Vocabulário das etiquetas já usadas, com frequência. |
| `DELETE` `PATCH` | `/api/missoes/itens/<int:iid>` | admin, gestor, tecnico |  |
| `GET` | `/api/missoes/meus-cartoes` | admin, gestor, tecnico | Cartões (não concluídos, de missões ativas) atribuídos ao usuário logado. |
| `GET` | `/api/missoes/modelos` | admin, gestor, tecnico |  |
| `POST` | `/api/missoes/modelos` | admin, gestor, tecnico | Salva uma missão existente como template ({missao_id, nome, com_cartoes}). |
| `DELETE` | `/api/missoes/modelos/<int:mid>` | admin, gestor |  |
| `GET` | `/api/missoes/refs` | admin, gestor, tecnico | Busca leve por tipo p/ o dropdown de vínculo. ?tipo=equipamento&q=... |
| `POST` | `/api/missoes/reordenar` | admin, gestor, tecnico | Duas formas (tudo numa única transação, ordem = índice da lista): |
| `POST` | `/api/missoes/snapshot` | admin, gestor |  |
| `GET` | `/api/missoes/usuarios` | admin, gestor, tecnico | Só nomes de usuários ativos, para o autocomplete de responsáveis. |

## `notificacoes/routes.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `GET` | `/api/notificacoes` | admin, gestor, tecnico |  |
| `POST` | `/api/notificacoes/<int:nid>/lida` | admin, gestor, tecnico |  |
| `GET` | `/api/notificacoes/contagem` | admin, gestor, tecnico |  |
| `POST` | `/api/notificacoes/lidas` | admin, gestor, tecnico |  |

## `pdr/routes.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `GET` | `/pdr` | página (casca) |  |
| `GET` | `/pdr/` | página (casca) |  |
| `GET` | `/pdr/api/apresentacoes` | área `pdr` |  |
| `POST` | `/pdr/api/apresentacoes` | área `pdr` + admin, gestor |  |
| `DELETE` | `/pdr/api/apresentacoes/<int:aid>` | área `pdr` + admin, gestor |  |
| `GET` | `/pdr/api/apresentacoes/<int:aid>` | área `pdr` |  |
| `PATCH` | `/pdr/api/apresentacoes/<int:aid>` | área `pdr` + admin, gestor, tecnico |  |
| `GET` | `/pdr/api/dashboard` | área `pdr` |  |
| `GET` | `/pdr/api/export/apresentacoes.csv` | área `pdr` | CSV das apresentações conforme os filtros da aba. |
| `GET` | `/pdr/api/meta` | área `pdr` | Vocabulários controlados para preencher selects no frontend. |
| `GET` | `/pdr/api/produtos` | área `pdr` |  |
| `POST` | `/pdr/api/produtos` | área `pdr` + admin, gestor |  |
| `DELETE` | `/pdr/api/produtos/<int:pid>` | área `pdr` + admin, gestor |  |
| `GET` | `/pdr/api/produtos/<int:pid>` | área `pdr` |  |
| `PATCH` | `/pdr/api/produtos/<int:pid>` | área `pdr` + admin, gestor |  |
| `POST` | `/pdr/api/reimport` | área `pdr` + admin |  |

## `servidor.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `GET` | `/` | página (casca) |  |
| `POST` | `/api/admin/tarefas-diarias` | admin | Dispara agora as fotos do dia (equipamentos, missões, projetos). |
| `GET` | `/api/audit` | admin, gestor |  |
| `POST` | `/api/categorias-equipamento` | admin, gestor, tecnico |  |
| `DELETE` `PATCH` | `/api/categorias-equipamento/<int:cid>` | admin, gestor, tecnico |  |
| `GET` | `/api/consumiveis` | autenticado |  |
| `POST` | `/api/consumiveis` | admin, gestor, tecnico |  |
| `DELETE` | `/api/consumiveis/<int:cid>` | admin, gestor |  |
| `GET` | `/api/consumiveis/<int:cid>` | autenticado |  |
| `PATCH` `PUT` | `/api/consumiveis/<int:cid>` | admin, gestor, tecnico |  |
| `GET` | `/api/consumiveis/<int:cid>/descritivo` | autenticado |  |
| `POST` | `/api/consumiveis/<int:cid>/equipamentos` | admin, gestor, tecnico |  |
| `POST` | `/api/consumiveis/descritivo/import` | admin, gestor, tecnico |  |
| `POST` | `/api/consumiveis/descritivo/import-docx` | admin, gestor, tecnico |  |
| `GET` | `/api/consumiveis/export` | admin, gestor, tecnico | CSV do catálogo conforme os filtros da tela. |
| `DELETE` `PATCH` | `/api/consumivel-equipamento/<int:vid>` | admin, gestor, tecnico |  |
| `GET` | `/api/data` | autenticado |  |
| `GET` | `/api/enums` | autenticado |  |
| `DELETE` `PATCH` | `/api/equip-itens/<int:item_id>` | admin, gestor, tecnico |  |
| `GET` | `/api/equip-taxonomia` | autenticado |  |
| `GET` | `/api/equipamentos` | autenticado |  |
| `POST` | `/api/equipamentos` | admin, gestor, tecnico |  |
| `DELETE` | `/api/equipamentos/<int:equip_id>` | admin, gestor |  |
| `GET` | `/api/equipamentos/<int:equip_id>` | autenticado |  |
| `PATCH` `PUT` | `/api/equipamentos/<int:equip_id>` | admin, gestor, tecnico |  |
| `GET` | `/api/equipamentos/<int:equip_id>/consumiveis` | autenticado |  |
| `GET` | `/api/equipamentos/<int:equip_id>/evolucao` | autenticado | Série temporal do equipamento: ICE/IDP por dia + histórico de Pareto. |
| `GET` | `/api/equipamentos/<int:equip_id>/historico` | autenticado | Trilha de alterações do equipamento (o que a aba Histórico da ficha mostra). |
| `GET` | `/api/equipamentos/<int:equip_id>/itens` | autenticado |  |
| `POST` | `/api/equipamentos/<int:equip_id>/itens` | admin, gestor, tecnico |  |
| `GET` | `/api/equipamentos/<int:equip_id>/pastas` | autenticado |  |
| `POST` | `/api/equipamentos/<int:equip_id>/pastas` | admin, gestor, tecnico |  |
| `DELETE` | `/api/equipamentos/<int:equip_id>/pastas/<int:pasta_id>` | admin, gestor | Remove a pasta e devolve os documentos dela ao caminho do equipamento. |
| `PATCH` `PUT` | `/api/equipamentos/<int:equip_id>/pastas/<int:pasta_id>` | admin, gestor, tecnico |  |
| `GET` | `/api/equipamentos/completude` | autenticado | ICE, IDP e sinais de risco de todos os equipamentos, calculados aqui. |
| `GET` | `/api/equipamentos/evolucao` | autenticado | Média da frota por dia — a curva que responde 'o cadastro está avançando?'. |
| `GET` | `/api/equipamentos/export` | admin, gestor, tecnico | CSV conforme os filtros da tela, com os índices que o dashboard calcula. |
| `POST` | `/api/equipamentos/import` | admin, gestor |  |
| `POST` | `/api/equipamentos/import-pareto` | admin, gestor | Importa a aba Pareto 80-20 (Qtd de saídas + Classe ABC) casando por SKU de Venda. |
| `GET` | `/api/equipamentos/importacoes` | admin, gestor |  |
| `GET` | `/api/equipamentos/saude` | autenticado | Problemas de integridade do cadastro que só apareciam rodando script. |
| `POST` | `/api/equipamentos/snapshot` | admin, gestor |  |
| `GET` | `/api/events/replay` | autenticado | O mesmo replay do socket, por HTTP. `?rooms=` repetível, como o pedido |
| `GET` | `/api/export/audit` | admin, gestor |  |
| `POST` | `/api/familias-equipamento` | admin, gestor, tecnico |  |
| `DELETE` `PATCH` | `/api/familias-equipamento/<int:fid>` | admin, gestor, tecnico |  |
| `GET` | `/api/metrics` | autenticado |  |
| `GET` | `/api/status` | admin, gestor | Estado do ambiente — infra real para a tela de Configurações. |
| `GET` | `/api/tipos-consumivel` | autenticado |  |
| `POST` | `/api/tipos-consumivel` | admin, gestor, tecnico |  |
| `DELETE` `PATCH` | `/api/tipos-consumivel/<int:tid>` | admin, gestor, tecnico |  |
| `GET` | `/api/tipos-consumivel/<int:tid>/descritivo-modelo` | autenticado |  |
| `GET` | `/api/version` | público |  |
| `GET` | `/config` | página (casca) |  |
| `GET` | `/configuracoes` | página (casca) |  |
| `GET` | `/entregaveis` | página (casca) |  |
| `GET` | `/equipamentos` | página (casca) |  |
| `GET` | `/hub` | página (casca) |  |
| `GET` | `/hub/<slug>` | página (casca) |  |
| `GET` | `/manifest.webmanifest` | página (casca) |  |
| `GET` | `/missoes` | página (casca) |  |
| `GET` | `/projetos` | página (casca) |  |
| `GET` | `/sw.js` | página (casca) |  |

## `tempos/routes.py`

| Método | Rota | Acesso | O que faz |
|---|---|---|---|
| `GET` | `/tempos` | página (casca) |  |
| `GET` | `/tempos/` | página (casca) |  |
| `POST` | `/tempos/api/<int:ap_id>/retomar` | admin, gestor, tecnico | Só o dono, SEM exceção para gestão. |
| `GET` | `/tempos/api/alvos` | admin, gestor, tecnico | Busca de alvo para o seletor. Sem isto o front teria que baixar os quatro |
| `GET` | `/tempos/api/apontamentos` | admin, gestor, tecnico |  |
| `POST` | `/tempos/api/apontamentos` | admin, gestor, tecnico | Lançamento manual/retroativo — o único caminho, junto do PUT, em que o |
| `DELETE` | `/tempos/api/apontamentos/<int:ap_id>` | admin, gestor, tecnico | Exclusão real, diferente de Composicao (arquiva) e Documento (soft delete). |
| `GET` | `/tempos/api/apontamentos/<int:ap_id>` | admin, gestor, tecnico |  |
| `PUT` | `/tempos/api/apontamentos/<int:ap_id>` | admin, gestor, tecnico |  |
| `GET` | `/tempos/api/atual` | admin, gestor, tecnico |  |
| `POST` | `/tempos/api/atual/parar` | admin, gestor, tecnico |  |
| `POST` | `/tempos/api/atual/pausar` | admin, gestor, tecnico |  |
| `GET` | `/tempos/api/export/apontamentos.csv` | admin, gestor, tecnico |  |
| `GET` | `/tempos/api/export/tempos.xlsx` | admin, gestor, tecnico |  |
| `POST` | `/tempos/api/iniciar` | admin, gestor, tecnico |  |
| `GET` | `/tempos/api/meta` | admin, gestor, tecnico |  |
| `GET` | `/tempos/api/por-ref` | admin, gestor, tecnico | Total de um alvo — o número que as fichas de Missões/Equipamentos/Projetos |
| `GET` | `/tempos/api/resumo` | admin, gestor, tecnico |  |
