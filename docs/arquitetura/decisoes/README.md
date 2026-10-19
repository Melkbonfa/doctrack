# Decisões de arquitetura (ADRs)

Registro das decisões que continuam governando o sistema. Não é histórico de
mudanças — para isso existe o [CHANGELOG](../../../CHANGELOG.md). É a resposta
para "por que isto é assim?", escrita para quem vai mexer no código e está
prestes a "consertar" algo que é deliberado.

Estes dez ADRs foram escritos **retroativamente**, em ago/2026, a partir do
código e dos comentários já existentes. As decisões são mais antigas que os
documentos; o que é novo é estarem escritas em um lugar só.

| # | Decisão | Alcance |
|---|---|---|
| [0001](ADR-0001-caminho-no-banco.md) | O banco guarda o caminho, não o arquivo | deploy, backup, acesso remoto |
| [0002](ADR-0002-schema-no-startup.md) | Schema aplicado no startup, migrações espelhadas | banco, deploy |
| [0003](ADR-0003-event-bus-e-audit-log.md) | `audit_logs` é trilha e event store ao mesmo tempo | tempo real, auditoria |
| [0004](ADR-0004-pagina-casca-api-gatilhada.md) | Página é casca; o gate está na API | front, segurança |
| [0005](ADR-0005-ratelimit-em-memoria.md) | Rate limit em memória de processo | segurança, escala |
| [0006](ADR-0006-kill-switch-fora-do-banco.md) | Segredos do kill switch fora do banco | segurança, operação |
| [0007](ADR-0007-pdf-no-navegador.md) | PDF montado no navegador | relatórios, deploy |
| [0008](ADR-0008-agendador-embutido.md) | Agendador é uma thread, não cron externo | séries temporais |
| [0009](ADR-0009-blob-por-conteudo.md) | Arquivo enviado é endereçado pelo SHA-256 | uploads, segurança |
| [0010](ADR-0010-monolito-modular.md) | Monólito modular em blueprints | estrutura do código |

## Formato

Cada ADR tem quatro seções: **contexto** (o que existia e doía), **decisão**
(o que foi feito), **consequências** (o que isso custa, incluindo o que quebra)
e **alternativas** (o que foi descartado e por quê). Curto de propósito — ADR
que ninguém lê não protege decisão nenhuma.

Ao tomar uma decisão estrutural nova, acrescente um arquivo numerado e uma linha
na tabela. Ao reverter uma, **não apague o ADR**: marque-o como substituído e
aponte para o novo. O valor está justamente em saber o que já foi tentado.
