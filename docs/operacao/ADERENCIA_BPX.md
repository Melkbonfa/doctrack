# Aderência ao Guia de Validação de Sistemas Computadorizados (ANVISA)

Referência: [Guia de Validação de Sistemas Computadorizados](../referencias/),
ANVISA/ISPE Brasil, abril de 2010. As seções citadas (§) são as do guia.

Este documento confronta o que o guia pede com o que o DocTrack **faz hoje**,
conferido no código. Ele não substitui a documentação de validação (ERU,
especificações, Análise de Riscos, protocolos de QI/QO/QD, POPs), que é
controlada e mantida fora do repositório — serve de matéria-prima para ela e de
lista honesta do que falta.

## Como ler o guia

- **É guia, não regulamento.** O próprio texto diz que o cumprimento não é
  compulsório e que cada empresa avalia a aplicabilidade (§1). Por isso este
  documento diz "o guia pede", nunca "a ANVISA exige".
- **O escopo declarado é o de insumos farmacêuticos e medicamentos**, sob Boas
  Práticas de Fabricação e de Laboratório (§1.2). **BPx** é a sigla do guia para
  Boas Práticas, em que o "x" é Fabricação, Laboratório, Distribuição etc. Qual
  regulamento de Boas Práticas se aplica à empresa — o código já cita a
  RDC 665 e a ISO 13485 — é definição da Garantia da Qualidade, não deste
  repositório.
- **O DocTrack se enquadra como GED** (§17.1.5): gerencia documentos de processos
  críticos. Pela avaliação de criticidade (§2), basta gerenciar documentação
  (emissão, revisão, controle de versões) para o sistema ter impacto em BPx e
  precisar de validação. Os Cadernos de laboratório do PDR reforçam o
  enquadramento: guardam registros de teste.

## Vocabulário

A documentação usa os termos do guia (§22):

| Termo | Significado | Em vez de |
|---|---|---|
| ERU | Especificação de Requisitos do Usuário | URS |
| QI · QO · QD | Qualificação de Instalação · de Operação · de Desempenho | IQ · OQ · PQ |
| BPx | Boas Práticas (Fabricação, Laboratório, Distribuição…) | GxP |
| Trilha de auditoria | registro de toda alteração de dado | audit trail |
| Desvio | evento não planejado que põe em risco um produto ou um dado | incidente |

## Situação

- **Atende** — o sistema faz, e há teste ou código que mostra.
- **Parcial** — faz uma parte; a coluna da direita diz qual falta.
- **Não atende** — o sistema não faz.
- **Procedimento** — não é função de software: depende de POP, de registro ou
  de decisão da área usuária e da Garantia da Qualidade.

---

## 1. Requisitos mínimos de sistema validável (§3.1)

O que o guia pede de todo sistema que substitui registro manual ou impresso.

| O guia pede | Situação | Como está hoje |
|---|---|---|
| Entrada e modificação de dados só por pessoa autorizada | Atende | Login individual, papel e área em toda rota de API; a matriz é gerada do código ([permissoes.md](../referencia/permissoes.md)) e um teste trava a lista de rotas abertas |
| Registrar tentativas de acesso não autorizadas | Atende | `LOGIN_FALHA`, `ATIVACAO_FALHA`, os bloqueios por limite e `ACESSO_NEGADO` vão para `audit_logs` com e-mail, IP e motivo ([acesso-usuarios.md](../funcional/acesso-usuarios.md#tentativas-de-acesso-recusadas)); `tests/test_audit.py`, `tests/test_acesso_negado.py` |
| Registrar os acessos autorizados, com usuário, data e hora | Atende | Cada entrada grava `LOGIN` e cada saída grava `LOGOUT` — com o motivo quando foi o sistema que encerrou (`inatividade`) —, com e-mail, data, hora e IP. A renovação silenciosa do token dentro da mesma sessão não é gravada; `tests/test_bpx.py` |
| Manter registro de toda entrada e alteração de dado | Parcial | Ver [Trilha de auditoria](#3-trilha-de-auditoria-e-registros-eletrônicos-213) |
| Poder imprimir os dados guardados | Atende | Relatórios em PDF e exportações em CSV/XLSX dos módulos; a trilha sai em lista, CSV e PDF; os Cadernos exportam relatório Word |
| Inviolabilidade dos dados históricos e da rastreabilidade | Parcial | Não existe rota que edite ou apague linha da trilha. Mas a proteção é só da aplicação — ver [Trilha de auditoria](#3-trilha-de-auditoria-e-registros-eletrônicos-213) |
| Backup em intervalos regulares, guardado por tempo definido, **em local separado e seguro** | Parcial | Diário às 02:00, 30 dias de retenção. **Os dumps ficam no mesmo disco do banco** — ver [Backup](#5-backup-restauração-e-recuperação-de-desastre-166-e-167) |

---

## 2. Controle de acesso e senhas (§16.3, §21.1 e §21.2)

| O guia pede | Situação | Como está hoje |
|---|---|---|
| Acesso individual por nome; nenhuma conta ou senha coletiva | Atende | Uma conta por e-mail, e o administrador não conhece a senha de ninguém (R-05). Banco sem usuário nenhum ganha **um** administrador sem senha, com código de ativação impresso uma vez no log da subida. As contas de demonstração com senha fixa só existem com `DOCTRACK_CONTAS_DEMO=1`, que não se usa em produção. **Instalação anterior a esta mudança pode ainda ter `admin@pde.com` e as contas de demonstração com a senha antiga** — conferir uma vez ([RUNBOOK](RUNBOOK.md#verificações-periódicas)) |
| Privilégios documentados e parametrizados por atribuição | Atende | Quatro papéis, três áreas e papel por caderno; documentados em [acesso-usuarios.md](../funcional/acesso-usuarios.md) e na matriz gerada |
| Testes que provem que as transações críticas só saem para quem pode | Atende | A suíte cobre papel × rota; é a base do QO |
| Senha provisória, trocada obrigatoriamente no primeiro acesso | Atende | Vai além: não há senha provisória. A conta nasce com um **código de ativação** de uso único e com validade, e a senha é digitada só pelo dono |
| Senha guardada cifrada e ilegível ao digitar | Atende | bcrypt, 12 rounds; campo de senha mascarado |
| Senha com letras, números e caracteres especiais | Atende | Toda senha nova exige o tamanho mínimo (`DOCTRACK_SENHA_MIN`, padrão 8) e pelo menos uma letra, um número e um caractere especial (`DOCTRACK_SENHA_COMPOSICAO`). Senha já existente continua valendo até a próxima troca |
| Renovação periódica; senha vencida impede o acesso | Atende | A senha vence em `DOCTRACK_SENHA_VALIDADE_DIAS` (padrão 180). Vencida, o login responde 403 e a tela leva à troca, que pede a senha atual. As contas que já existiam começam a contar da data da atualização. A pessoa também troca a própria senha quando quiser, pelo menu ou pela tela de login |
| Bloquear depois de tentativas frustradas, e registrar | Atende | 5 falhas em 5 minutos bloqueiam por (rota, identidade, IP); cada bloqueio vira linha na trilha. O bloqueio é temporário e o contador vive em memória — zera no reinício do serviço ([ADR-0005](../arquitetura/decisoes/ADR-0005-ratelimit-em-memoria.md)) |
| Detectar tentativas repetidas de acesso não autorizado | Atende | As mesmas linhas da trilha; não há alerta ativo — alguém precisa olhar |
| Desconexão automática por inatividade | Atende | Sem mouse, teclado ou toque por `DOCTRACK_INATIVIDADE_MIN` minutos (padrão 30), a sessão é encerrada: os tokens são revogados no servidor e a saída vai para a trilha com o motivo. A contagem vale para todas as abas juntas. **Quem mede é o navegador** — o servidor não recusa sozinho um token de sessão parada |
| Conta de quem saiu é desativada ou excluída **logicamente**; o ID não é reutilizado | Atende | Desativar (`ativo=False`) corta a sessão na hora e segura o e-mail. A exclusão permanente só passa para conta que **nunca deixou linha na trilha** (cadastro feito por engano); para as outras responde 409 |
| POP de concessão de acesso, fluxo de aprovação, arquivo das requisições, auditoria periódica dos acessos | Procedimento | O sistema registra na trilha quem criou, editou, desativou e resetou cada conta. O pedido e a aprovação acontecem fora dele |
| Segurança física e de rede (acesso remoto, antivírus) | Procedimento | O que é do sistema está em [ACESSO_REMOTO.md](../ACESSO_REMOTO.md) e no [RUNBOOK](RUNBOOK.md); o servidor e a rede são da TI |

### Assinatura eletrônica (§21.2)

**O DocTrack não tem assinatura eletrônica.** O guia pede que toda função
crítica de BPx reautentique a pessoa no momento em que ela conclui o registro;
aqui, qualquer ação vale pela sessão já aberta.

Consequências práticas:

- **Aprovar uma etapa de um Fluxo de revisão não é assinar.** É um registro de
  quem clicou, com data e hora — e admin e gestor podem aprovar em nome do
  responsável da etapa.
- **O relatório exportado dos Cadernos traz um campo de assinaturas para ser
  assinado fora do sistema**, à mão ou na ferramenta que a empresa adotar.
- Se algum registro do DocTrack vier a substituir um documento assinado, isso é
  funcionalidade nova, com POP próprio — não ajuste de configuração.

---

## 3. Trilha de auditoria e registros eletrônicos (§21.3)

O guia define trilha de auditoria como o registro de **qualquer** alteração de
dado, com data, hora, usuário, campo alterado, valor original, valor novo e o
ponto de acesso de onde ela partiu.

| O guia pede | Situação | Como está hoje |
|---|---|---|
| Data, hora, usuário, campo, valor original, valor novo, ponto de acesso | Atende | São as colunas de `audit_logs`: `timestamp`, `usuario_email`, `campo`, `valor_antigo`, `valor_novo`, `ip` ([dados.md](../referencia/dados.md)) |
| Registrar **qualquer** alteração de dado | Parcial | Toda escrita de API que dá certo deixa linha na trilha: se a rota não gravou a dela, uma rede de segurança grava `ESCRITA`, com usuário, data, hora, IP e a rota ([ADR-0003](../arquitetura/decisoes/ADR-0003-event-bus-e-audit-log.md)). **Essa linha genérica não traz campo, valor antigo nem valor novo** — o detalhe continua dependendo de cada rota, e é desigual: Documentos, Usuários, Custos, Missões e Cadernos detalham; no PDR e nos cadastros auxiliares quase tudo cai na linha genérica. O autosave das páginas dos Cadernos fica fora da trilha: o histórico é o das versões da página |
| Dado inacessível para modificação | Parcial | Pela aplicação, ninguém altera a trilha — nem o administrador. No banco, o usuário do serviço tem permissão de escrita na tabela, e quem tem a senha do banco altera sem deixar rastro |
| Recuperar a informação pelo período de retenção | Parcial | A trilha é guardada inteira (`DOCTRACK_AUDIT_RETENCAO_DIAS=0`). **O período de retenção não está definido**; ligar a poda é decisão regulatória, não de manutenção |
| Recuperar mesmo depois da descontinuidade do sistema (§20) | Procedimento | Não há plano de descontinuidade. Os dados saem por `pg_dump` (SQL legível) e pelas exportações; os arquivos, da pasta de arquivos enviados |
| Hora confiável | Parcial | É a hora local do relógio do servidor, sem fuso gravado. Depende de o Windows estar sincronizado |

Fica de fora da trilha, por decisão registrada em
[acesso-usuarios.md](../funcional/acesso-usuarios.md): o 401 de token vencido,
e a contagem de recusas repetidas dentro da janela de deduplicação.

---

## 4. Controle de mudanças e administração (§16.1, §16.2 e §16.9)

| O guia pede | Situação | Como está hoje |
|---|---|---|
| Toda mudança registrada, com a extensão da verificação proporcional ao risco | Parcial | Toda mudança entra por *pull request*, com a suíte de testes, e é descrita no [CHANGELOG](../../CHANGELOG.md) ([FLUXO_DESENVOLVIMENTO.md](../FLUXO_DESENVOLVIMENTO.md)). A versão no ar é a do arquivo `VERSION`, exposta em `/api/version`; o commit em produção é o do `git pull` do deploy. **Não há avaliação de impacto em BPx registrada por mudança** |
| Aprovação por equipe multidisciplinar, com a Garantia da Qualidade | Procedimento | O repositório registra quem escreveu e quem integrou; a aprovação da GQ acontece fora dele |
| Mudança emergencial registrada e avaliada depois | Procedimento | Tecnicamente é o mesmo caminho (PR e deploy); o POP precisa dizer o que conta como emergência |
| Um responsável pela administração do sistema | Procedimento | O RUNBOOK descreve as tarefas; o nome do responsável e do substituto é do POP |
| Plano de manutenção | Parcial | [Verificações periódicas](RUNBOOK.md#verificações-periódicas) no RUNBOOK. No-break e condições ambientais do servidor são da TI |

---

## 5. Backup, restauração e recuperação de desastre (§16.6 e §16.7)

| O guia pede | Situação | Como está hoje |
|---|---|---|
| Tipo e periodicidade documentados | Atende | `pg_dump` completo mais espelho da pasta de arquivos enviados, todo dia às 02:00 ([RUNBOOK](RUNBOOK.md#backup)) |
| Número de gravações e tempo de guarda | Atende | Dumps de 30 dias; o espelho dos arquivos é cumulativo |
| Local de guarda separado, com controle de acesso | Não atende | Os dumps ficam em `backups\`, **no mesmo disco do banco**. Uma falha de disco leva os dois |
| O que fazer quando o backup falha | Parcial | O RUNBOOK ensina a detectar (`LastTaskResult`, tamanho do dump). **Ninguém é avisado**: depende de alguém olhar |
| Verificação periódica do backup | Parcial | Conferência semanal prevista no RUNBOOK; sem registro de que foi feita |
| Simulação de restauração | Parcial | Prevista todo mês no RUNBOOK, com o procedimento descrito; sem registro de execução |
| Restauração com aprovação e avaliação de impacto | Procedimento | O RUNBOOK tem os comandos; quem autoriza é matéria de POP |
| Sincronização de sistemas interdependentes | Parcial | Banco e arquivos enviados restauram juntos pelo script. **Os documentos técnicos do share não estão no backup do DocTrack**: o banco guarda o caminho ([ADR-0001](../arquitetura/decisoes/ADR-0001-caminho-no-banco.md)), e eles dependem do backup de outro servidor, de outra equipe |
| Dado perdido tratado como desvio | Procedimento | — |
| Plano de recuperação de desastre: contingência, impacto de ficar fora do ar, responsabilidades, hardware e software necessários | Parcial | A reinstalação numa máquina nova está em [GUIA_DEPLOY_WINDOWS.md](../GUIA_DEPLOY_WINDOWS.md) e a restauração no RUNBOOK. Contingência (como a área trabalha sem o sistema) e responsabilidades são do POP |

---

## 6. O que é só procedimento (§16.4, §16.5, §16.8, §16.10 e §20)

Nada disto é função do software, mas o sistema fornece insumo para cada um.

| O guia pede | O que o DocTrack fornece |
|---|---|
| Treinamento periódico de usuários e suporte, com registro (§16.4) | Nada. Não há manual do usuário final; a documentação deste repositório é técnica |
| Desvios investigados e documentados (§16.5) | `err.log` e a trilha de auditoria servem de evidência; a tabela de sintomas do RUNBOOK ajuda no diagnóstico. O registro do desvio é feito fora |
| Revisão periódica (§16.8): validação, mudanças, desvios, acessos, backup, estado do servidor, estado da trilha | CHANGELOG (mudanças), lista de usuários e trilha (acessos), tarefa agendada e pasta `backups\` (backup), [Verificações periódicas](RUNBOOK.md#verificações-periódicas) (servidor e trilha) |
| Arquivamento da documentação de validação (§16.10) | Os rascunhos ficam fora do controle de versão (`docs/oficiais/`, ignorada pelo git). O arquivo oficial é o do sistema da qualidade |
| Plano de descontinuidade (§20) | Não existe. Ver a linha de recuperação de dados na [seção 3](#3-trilha-de-auditoria-e-registros-eletrônicos-213) |

---

## Lacunas, por ordem de risco

As que são do **software**:

1. **Detalhe da trilha desigual entre os módulos** (§21.3): nenhuma escrita
   fica mais sem rastro, mas onde a rota não registra a alteração a linha diz
   só quem, quando e qual rota — sem campo, valor antigo e valor novo. O
   próximo passo é dar registro próprio às rotas do PDR e dos cadastros
   auxiliares, que são as que mais caem na linha genérica (`ESCRITA`).
2. **A inatividade é medida no navegador** (§16.3, §21.2): protege a aba
   esquecida aberta, não um token copiado para fora do navegador.
3. **A trilha não é protegida no banco** contra quem tem a credencial do
   serviço (§21.3).
4. **Sem assinatura eletrônica** (§21.2) — só é lacuna se algum registro do
   sistema precisar valer como documento assinado.

As que são de **infraestrutura**:

5. **Backup no mesmo disco do banco** (§3.1, §16.6).
6. **Falha de backup não avisa ninguém** (§16.6).
7. **Documentos técnicos do share fora do backup do sistema** (§16.6).

Fechadas no código, com teste em `tests/test_bpx.py`: contas-padrão com senha
fixa, desconexão por inatividade, composição e validade da senha, troca da
própria senha, saída na trilha, reuso de e-mail pela exclusão permanente e
escrita sem rastro.

As que são de **procedimento** — todos os POPs da seção 6, mais o período de
retenção dos registros, o registro das verificações periódicas e das
simulações de restauração, e a avaliação de impacto em BPx por mudança.

## Como manter este documento

Ele é escrito à mão e descreve o código de hoje. Uma mudança que feche ou abra
uma lacuna atualiza a linha correspondente **no mesmo pull request** — é a
regra que já vale para a documentação funcional. A coluna "Como está hoje" só
recebe o que foi conferido no código ou num teste, nunca intenção.
