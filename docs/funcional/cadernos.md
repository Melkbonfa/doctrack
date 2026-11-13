# Módulo Cadernos

Código: [`cadernos/`](../../cadernos/) — `core.py` (regra pura) · `models.py` ·
`routes.py` · `importacao.py` e `importador_onenote.py` (entrada do OneNote) ·
`exportacao.py` e `relatorio_docx.py` (pacote para a liderança) · `tarefas.py`
(trabalho demorado) · tela `static/cadernos.js`. Montado em `/cadernos`, aberto
pela barra lateral do PDR.
Plano e pesquisa: [`PLANO_cadernos.md`](../planos/PLANO_cadernos.md).

## O que resolve

Os cadernos de laboratório do PDR viviam no OneNote, com os arquivos dos testes
espalhados no SharePoint. O módulo traz os dois para dentro do DocTrack: o texto
das páginas, os arquivos presos a elas e o pacote que vai para a liderança.

## Estrutura

```
Caderno → grupo de seções (opcional, aninhável) → seção → páginas (nível 1 a 3)
```

É a mesma organização do OneNote, de propósito — quem migra reconhece o que vê.

**Subpágina não é filha numa árvore.** As páginas de uma seção são uma lista
ordenada, e a subpágina é a página com nível maior logo abaixo de outra. Mover
uma página leva a série dela junto; excluir uma página faz as subpáginas subirem
um nível. As invariantes (a primeira tem nível 1, nenhuma pula nível, máximo 3)
são corrigidas em toda escrita, em vez de recusadas.

Um caderno nasce de um **modelo**: "Projeto PDR", com as seções das fases do
projeto (Desenvolvimento, as validações, Estabilidade, Transferência), ou "Em
branco". A seção define o tipo padrão das páginas criadas nela:

| Tipo de página | O que é |
|---|---|
| Nota | texto livre |
| Registro de teste | a estrutura do registro de teste homologado do PDR, com uma **ficha** estruturada no topo (projeto, número, responsáveis, datas, resultado) |

## Quem pode o quê

O papel é **por caderno**, não só pelo perfil da pessoa. A primeira regra que
decide, vence:

1. admin é dono de tudo;
2. quem criou o caderno é dono;
3. quem foi posto como membro tem o papel que recebeu (leitor, editor ou dono);
4. sem a área do caderno, nada;
5. gestor da área é dono dos cadernos de equipe;
6. o resto da área recebe o **acesso da área** definido no caderno.

O acesso da área é `editor` por padrão — o caderno de laboratório é da equipe.
`leitor` deixa a área só ler, e `nenhum` faz o caderno **privado**: só dono e
membros entram, e nem o gestor da área o vê. O perfil `leitura` (auditoria)
nunca passa de leitor, em caderno nenhum.

| Ação | Papel mínimo |
|---|---|
| Ler, buscar, baixar arquivo | leitor |
| Escrever páginas, enviar arquivos, exportar | editor |
| Renomear o caderno, mudar o acesso, definir membros, excluir e restaurar o caderno, tomar a edição de outra pessoa | dono |

Toda recusa — inclusive o 404 de um caderno a que a pessoa não tem acesso — vai
para a trilha de auditoria como `ACESSO_NEGADO`.

## Edição

- **Uma pessoa edita a página por vez.** Abrir o editor pega a trava; o front a
  renova enquanto o editor está aberto, e ela expira sozinha em 2 minutos sem
  renovação. Aba fechada ou máquina que dormiu não deixam a página presa.
- **O dono pode tomar a edição.** O que a outra pessoa já tinha gravado fica.
- **Uma versão por sessão de edição.** O autosave grava o conteúdo; ao soltar a
  trava, o estado final vira uma versão. Restaurar uma versão antiga guarda o
  estado atual como versão antes — restaurar nunca perde nada.
- **O servidor guarda HTML saneado**, nunca o que chegou do editor: só as tags,
  atributos e estilos de uma lista passam. É a parte crítica de segurança do
  módulo (`core.sanear_html`).
- **Imagem colada vira arquivo.** O texto guarda só a referência ao arquivo; o
  endereço é montado no navegador com a sessão de quem lê, então nenhum token
  vai para o banco nem para o histórico.

## Arquivos

Arquivos de **qualquer extensão** — dados brutos, laudos, planilhas, programas —
presos à página, à seção ou ao caderno. Ficam no mesmo blob store dos
documentos, endereçados pelo conteúdo
([ADR-0009](../arquitetura/decisoes/ADR-0009-blob-por-conteudo.md)).

- Enviar uma **versão nova** substitui a vigente; as anteriores continuam
  baixáveis.
- Imagem e PDF podem abrir no navegador; todo o resto desce como download.
- Cada arquivo tem a marca **Exporta**, que decide se ele entra por padrão no
  pacote para a liderança.

## Lixeira

Excluir caderno, grupo, seção, página ou arquivo manda para a lixeira. O que
está lá pode ser restaurado; o expurgo definitivo acontece depois de 60 dias
(`CADERNOS_LIXEIRA_DIAS`), na tarefa diária. Só o expurgo apaga o arquivo do
disco.

## Importar do OneNote

O OneNote só entrega o conteúdo completo na máquina de quem tem o caderno
aberto. Por isso a importação tem um **assistente**: um `.cmd` baixado da
própria tela, que roda na máquina da pessoa.

1. Na tela "Importar do OneNote", a pessoa baixa o assistente e o caderno
   exportado do SharePoint.
2. O assistente acha o caderno na pasta Downloads, extrai as páginas e **manda
   o pacote sozinho** para o DocTrack. A tela acompanha a etapa ao vivo.
3. A pessoa confere o resumo e confirma. A gravação roda como tarefa, com
   barra de progresso.

O assistente não usa o login da pessoa. Ele carrega um **ticket de uso único**,
válido por 6 horas, que só permite contar a etapa e depositar um pacote na área
de espera — gravar continua exigindo a pessoa logada. São essas as duas rotas
do módulo que respondem sem token (ver
[`permissoes.md`](../referencia/permissoes.md)). Enviar o `.zip` à mão continua
existindo como plano B, e abre sozinho quando o assistente para com erro.

**Reimportar é seguro.** Caderno, seções e páginas são reconhecidos pela origem.
Página que nunca foi editada no DocTrack é atualizada; página editada é pulada
e listada no relatório da importação.

Pela linha de comando existe `scripts/importar_onenote.py`, com travas próprias
contra gravar no banco errado.

## Exportar para a liderança

Um `.zip` com o relatório Word no formato do PDR, as imagens no tamanho
original, os arquivos de cada página e um LEIA-ME com o índice e o SHA-256 de
cada arquivo.

É em dois passos: a **prévia** lista as páginas escolhidas e todos os arquivos
candidatos, já marcados com o que entra por padrão (os que têm "Exporta" e todo
arquivo citado no texto de uma página exportada); a pessoa revisa e só então o
pacote é gerado. O zip fica disponível para download por um dia. O registro do
que foi exportado — páginas, versões e manifesto — é permanente e aparece no
histórico do caderno.

## Pontos de atenção

- **Sem tempo real.** O módulo não usa o barramento de eventos: a trava de
  edição é o que evita duas pessoas na mesma página, e a árvore mostra quem
  está editando quando é recarregada.
- **Tarefas ficam em memória.** Exportação e importação rodam numa thread do
  próprio processo. Se o serviço reiniciar no meio, a tarefa some e a pessoa
  refaz; nada fica pela metade, porque as duas só gravam o resultado no fim.
  É mais um ponto que depende da premissa de processo único
  ([ADR-0010](../arquitetura/decisoes/ADR-0010-monolito-modular.md)).
- **Os arquivos entram no backup pelo espelho da pasta de arquivos enviados**,
  como os dos documentos. Banco e arquivos restauram juntos — ver o
  [RUNBOOK](../operacao/RUNBOOK.md#o-que-o-backup-não-cobre).
