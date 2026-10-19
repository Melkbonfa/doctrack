# ADR-0001 — O banco guarda o caminho, não o arquivo

**Status:** vigente · **Alcance:** deploy, backup, acesso remoto, segurança

## Contexto

Os documentos técnicos da Loccus já existiam antes do DocTrack e já viviam em
`\\loccus-srv03\Projetos$\Engenharia`. A Qualidade mantém o sistema dela, a
engenharia trabalha nos `.docx` direto no share, e várias pessoas editam
arquivos por lá sem passar por sistema nenhum.

Importar tudo para dentro do DocTrack teria significado ou congelar cópias que
envelheceriam no mesmo dia, ou assumir a guarda do acervo inteiro — com o
backup, o versionamento e a responsabilidade que vêm junto.

## Decisão

O banco guarda o **caminho** para o arquivo no share. Colunas como
`documentos.armazenamento`, `equipamento_pastas.caminho` e
`equipamento_arquivos.caminho` são endereços, não conteúdo. O DocTrack lê e
escreve no share em tempo real; a fonte da verdade continua sendo o share.

A exceção deliberada é o **upload de conveniência** (`arquivos_store.py`): o
usuário pode subir uma cópia para dentro da plataforma. Ela é explicitamente
cópia, não mestre — ver [ADR-0009](ADR-0009-blob-por-conteudo.md).

Como o mesmo diretório chega ao sistema em duas formas (`P:\...` do Explorer e
a UNC), [`caminhos.py`](../../../caminhos.py) canoniza tudo para UNC antes de
gravar ou comparar. Mapeamento de unidade é por sessão de logon e o serviço
Windows não enxerga `P:` nenhum.

## Consequências

**O servidor não pode sair da rede.** Uma instância hospedada fora não abriria
documento nenhum. É por isso que a publicação externa é por túnel Cloudflare,
com o servidor onde está — ver [ACESSO_REMOTO.md](../../ACESSO_REMOTO.md).

**Restaurar o `pg_dump` não traz os documentos de volta.** Traz o sistema: os
cadastros, o histórico, os índices. Os arquivos dependem do backup do
`loccus-srv03`, que é de outra equipe. Esta é a lacuna mais séria do plano de
recuperação e está registrada no [RUNBOOK](../../operacao/RUNBOOK.md).

**Toda leitura de arquivo precisa de allowlist.** O caminho chega do cliente,
então sem `DOCTRACK_FILE_ROOTS` validando a raiz haveria path traversal direto
para qualquer coisa que o serviço enxergue. `caminhos.validar()` é obrigatório
em todo endpoint que serve arquivo.

**Um caminho pode apontar para nada.** Arquivo movido ou renomeado no share
produz cadastro válido sem arquivo — e é exatamente para isso que existe
[`diagnostico.py`](../../../diagnostico.py), que confronta cadastro × disco.

## Alternativas descartadas

**Importar os arquivos para o banco (BLOB) ou para uma pasta gerida.** Assume a
guarda do acervo e cria duas verdades no dia seguinte, porque a engenharia
continuaria editando no share.

**SharePoint como backend.** Existe uma proposta escrita
([INTEGRACAO_TI_AZURE_SHAREPOINT.md](../../INTEGRACAO_TI_AZURE_SHAREPOINT.md)),
nunca implantada. Resolveria o acesso externo e o backup de uma vez, mas depende
do TI e de uma migração do acervo — decisão de organização, não de software.
