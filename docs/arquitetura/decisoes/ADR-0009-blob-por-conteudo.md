# ADR-0009 — O arquivo enviado é endereçado pelo SHA-256 do conteúdo

**Status:** vigente · **Alcance:** uploads, segurança, espaço em disco

## Contexto

Além dos documentos que vivem no share ([ADR-0001](ADR-0001-caminho-no-banco.md)),
o usuário pode **enviar** uma cópia para dentro da plataforma: o anexo de um
documento, um laudo pendurado no equipamento, um instalador de firmware.

Guardar isso com o nome original traz três problemas conhecidos: o nome vem da
requisição (path traversal), dois arquivos diferentes podem se chamar
`Manual.pdf`, e o mesmo conteúdo enviado duas vezes ocupa espaço duas vezes —
o que não é hipotético, já que o share tem o mesmo `IT - Extracta 16 V1.0.docx`
de 56 MB em dois lugares.

## Decisão

O nome do arquivo em disco é o **SHA-256 do próprio conteúdo**, distribuído em
dois níveis de pasta (`ab/cd/abcd...`). Implementado em
[`arquivos_store.py`](../../../arquivos_store.py). O nome original vai para o
banco, como metadado.

Os três problemas somem juntos:

- **Path traversal deixa de existir.** Nenhum trecho do caminho vem da
  requisição, então não há o que sanear. Contraste com o endpoint que serve
  arquivo *do share*, que precisa de allowlist justamente porque o caminho vem
  do cliente.
- **Colisão de nome** deixa de ser possível.
- **Duplicata** ocupa um blob só.

## Consequências

**O blob é imutável e compartilhado.** Remover um anexo não pode apagar o
arquivo em disco sem antes verificar que ninguém mais aponta para ele. Quem sabe
disso é o banco, então `remover()` recebe a decisão de fora — e a consulta é nas
**três** tabelas que referenciam blobs (`documento_arquivos`,
`equipamento_arquivos` e `caderno_arquivos`), porque o mesmo PDF enviado em mais
de um lugar é um arquivo só. Em `caderno_arquivos` segura o blob toda linha fora
da lixeira, ativa ou não, porque a versão anterior de um arquivo do caderno
continua baixável. Ver `documentos._sha_orfao`.

**O módulo Cadernos aceita qualquer extensão** (`arquivos_store.QUALQUER`): é
onde o PDR guarda programas e arquivos de equipamento. Lá a proteção não é a
allowlist, e sim servir tudo que não é imagem/PDF como download com mime
genérico — o mesmo tratamento dado ao firmware.

**A pasta de arquivos é backup separado do banco.** Banco sem os arquivos — ou
o contrário — é um backup que não restaura. Está avisado no `.env.example` e no
[RUNBOOK](../../operacao/RUNBOOK.md).

**No executável empacotado, a pasta não pode ficar dentro de `_internal\`**, que
é substituída a cada atualização: os arquivos enviados sumiriam na primeira.
Fica ao lado do `.env` e do banco (`DOCTRACK_ARQUIVOS`).

**O upload custa um hash completo do conteúdo.** Irrelevante nos tamanhos em
jogo (o teto é 80 MB, ou 500 MB no repositório de firmware).

**A pasta não é legível por humanos.** Ninguém acha um arquivo navegando por
ela; só pelo sistema. É consequência aceita — a pasta não é interface.

## Alternativas descartadas

**Nome original saneado + sufixo numérico.** Resolve colisão, não resolve
duplicata, e mantém o saneamento de caminho como superfície de erro permanente.

**UUID por upload.** Resolve traversal e colisão, não resolve duplicata — e
duplicata era um problema concreto e medido neste acervo.

**Guardar no banco (BLOB).** Simplifica o backup para uma coisa só, mas infla o
`pg_dump` com centenas de MB de binário e põe o servidor de aplicação no caminho
de todo byte servido.
