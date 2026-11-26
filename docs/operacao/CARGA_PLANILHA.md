# Carga por planilha: modelos e projetos em massa

Use isto para mexer em muitos itens de uma vez: criar um modelo inteiro, revisar
os itens de vários modelos ou trocar o modelo de dezenas de projetos. Mudança
pequena continua mais rápida na tela.

Não edite o banco direto. A tela e este script ligam cada entregável ao item do
modelo, guardam o histórico e a curva-S e registram tudo na auditoria. Um
`UPDATE` feito à mão pula essas três coisas.

## Onde roda

No servidor do DocTrack (LOCCUS-0402), por Conexão de Área de Trabalho Remota,
num PowerShell comum. Não precisa de administrador. Quem roda precisa de:

- login no Windows do servidor com leitura em `C:\apps\doctrack`;
- um usuário **admin** no DocTrack (o e-mail vai no `-Por`).

## Passo a passo

Crie uma pasta de trabalho, por exemplo `C:\carga`, e rode os comandos abaixo
nesta ordem.

**1. Exportar** o que está no banco agora:

```powershell
powershell -ExecutionPolicy Bypass -File C:\apps\doctrack\scripts\carga_planilha.ps1 exportar C:\carga\carga.xlsx
```

**2. Editar** a planilha no Excel (ou pedir ao Claude). A aba **LEIA-ME** traz as
regras e a aba **Listas** os valores aceitos.

**3. Prévia.** Executa tudo e desfaz no fim. Leia o relatório.

```powershell
powershell -ExecutionPolicy Bypass -File C:\apps\doctrack\scripts\carga_planilha.ps1 previa C:\carga\carga.xlsx
```

Se a planilha tiver erro, a prévia lista cada problema com a aba e a linha, e
nada é gravado. O relatório também fica salvo em `C:\carga\carga_previa_<data>.txt`.

**4. Aplicar.** Faz o backup do banco primeiro e, se o backup falhar, não aplica.

```powershell
powershell -ExecutionPolicy Bypass -File C:\apps\doctrack\scripts\carga_planilha.ps1 aplicar C:\carga\carga.xlsx -Motivo "Novos modelos PDR 2027" -Por seu.email@empresa.com
```

Depois de aplicar, atualize a página do DocTrack (F5) para ver o resultado.

## O que cada aba faz

| Aba | O que muda | O que não muda |
|---|---|---|
| Modelos | linha nova cria o modelo (até 20 caracteres); mudar a área muda | renomear e excluir modelo: faça na tela |
| Itens do modelo | cada modelo que aparece na aba é a **lista completa** dele, na ordem das linhas: edita, cria e exclui itens | modelo sem nenhuma linha na aba fica como está |
| Projetos | nome, descrição, SKU, MoSCoW, prioridade, lançamento e **modelo** | status, área e ativo são só informação; projeto fora da aba fica como está |

Sobre a coluna `id`:

- não altere os ids;
- linha nova fica com o id vazio;
- uma linha sem id que tem o mesmo nome de um item que o modelo já tem é tratada
  como esse item, então rodar a mesma planilha duas vezes não duplica nada.

## O que acontece com os projetos

Depois de gravar os modelos, cada modelo alterado é aplicado aos projetos
**abertos** dele, com a mesma regra do botão "Aplicar aos projetos":

- **item novo no modelo**: o projeto ganha um entregável novo;
- **item alterado**: o entregável muda, a menos que o projeto tenha ajustado
  aquele campo por conta própria (o relatório marca isso como "mantido");
- **item que saiu do modelo**: o entregável é apagado. Se já teve andamento
  (status, histórico ou fluxo de revisão), ele vira **N/A** e o passado da
  curva-S fica preservado;
- **projeto que troca de modelo**: os entregáveis com o mesmo nome de um item do
  modelo novo são aproveitados com o andamento que já tinham, e passam a usar a
  categoria e o peso do modelo novo. O resto segue as três regras acima.

Projeto arquivado, concluído ou cancelado não troca de modelo. O relatório avisa
quando isso acontece.

Cada aplicação aparece no histórico do modelo, na tela, com o motivo, e cada
mudança de cadastro fica na auditoria com origem "planilha".

## Pedindo ao Claude para preencher

Envie a planilha exportada e descreva o que você quer. Por exemplo:

> Preencha a aba "Itens do modelo" desta planilha com o novo modelo PDR 2027
> (crie a linha dele na aba Modelos, área pdr). Use só as categorias da aba
> Listas. Não altere a coluna id nem as linhas dos outros modelos. Na aba
> Projetos, troque a coluna "modelo" para PDR 2027 nos projetos X, Y e Z.

Depois rode a **prévia** e confira o relatório antes de aplicar.

## Desfazer

O `aplicar` deixa um backup completo em `C:\apps\doctrack\backups\doctrack_<data>.sql`.
Para voltar atrás, restaure esse arquivo (veja o RUNBOOK), mas lembre que isso
desfaz **tudo** o que foi feito no DocTrack depois do backup. Se o erro for
pequeno, prefira corrigir a planilha e aplicar de novo.
