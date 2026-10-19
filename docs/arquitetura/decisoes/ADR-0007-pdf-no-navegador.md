# ADR-0007 — O relatório PDF é montado no navegador

**Status:** vigente (terceira geração) · **Alcance:** relatórios, deploy

## Contexto

O relatório executivo precisa sair em PDF A4 paisagem, com gráficos. Houve três
gerações:

1. `html2pdf.js` no cliente — a original, documentada em
   [Documentacao_Geracao_PDF.md](../../Documentacao_Geracao_PDF.md);
2. **WeasyPrint no servidor** (`/api/report/pdf`) — removido em jul/2026;
3. **jsPDF no cliente** — o atual (`gerarRelatorioPDF()` em
   [`static/app.js`](../../../static/app.js)).

A geração no servidor foi tentada de verdade e revertida. O motivo é de
implantação: WeasyPrint no Windows exige GTK3, que é uma instalação nativa
separada, frágil de reproduzir numa máquina nova e sem relação com o resto da
pilha. O deploy do DocTrack é `git pull` + restart; um binário nativo fora do
`requirements.txt` quebra essa promessa.

## Decisão

O PDF é montado no navegador com **jsPDF**, servido de `static/vendor/`. Os
gráficos vêm do Chart.js já renderizado na tela.

Nenhuma dependência nativa no servidor. **Não instale GTK3 nem WeasyPrint** —
está avisado em [docs/README.md](../../README.md) porque a instalação já foi
tentada em servidor novo por causa de documentação velha.

Nada vem de CDN: as bibliotecas ficam em `static/vendor/` porque o app roda em
rede fabril, que pode não ter saída externa. A CSP do app não permite CDN.

## Consequências

**A máquina do usuário faz o trabalho.** Num relatório grande, o navegador
trava por alguns segundos. Aceitável para um relatório sob demanda; seria
inaceitável para geração em lote.

**Não dá para gerar PDF sem navegador.** Nenhum agendamento, nenhum envio
automático por e-mail, nenhuma rota de API que devolva o arquivo pronto. Se isso
virar requisito, a decisão precisa ser revista — e a alternativa realista passa
a ser um serviço de renderização, não WeasyPrint de volta.

**O layout depende de dimensões fixas em pixels** (1123×794 para A4 paisagem),
para não variar com a resolução do monitor. É a parte do documento de 2026 que
continua valendo.

**A documentação da primeira geração ainda não foi reescrita** para o jsPDF.
Está marcada como histórica no topo do arquivo.

## Alternativas descartadas

**WeasyPrint / GTK3 no servidor.** Já foi implantado e removido — ver acima.

**Headless Chrome no servidor.** Resolve o layout com fidelidade total, mas põe
um Chromium para instalar e atualizar no servidor Windows, com consumo de
memória por render. Desproporcional para um relatório sob demanda.
