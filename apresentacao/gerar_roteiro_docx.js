const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, AlignmentType, LevelFormat,
  HeadingLevel, BorderStyle, PageNumber, Header, Footer
} = require("docx");

const CY = "0E7C8B";      // ciano escuro (acento)
const CY_LT = "E6F7FB";   // fundo claro ciano
const INK = "1A2630";     // texto título
const GREY = "5B6B78";

// ---- helpers ----
const H1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  spacing: { before: 320, after: 120 },
  children: [new TextRun({ text })],
});
const H2 = (text, time) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  spacing: { before: 300, after: 60 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: CY, space: 4 } },
  children: [
    new TextRun({ text }),
    ...(time ? [new TextRun({ text: `\t${time}`, color: GREY, bold: false, size: 20 })] : []),
  ],
  tabStops: [{ type: "right", position: 9360 }],
});
const label = (lbl, txt) => new Paragraph({
  spacing: { before: 80, after: 40 },
  children: [
    new TextRun({ text: `${lbl} `, bold: true, color: CY }),
    new TextRun({ text: txt }),
  ],
});
const quote = (txt) => new Paragraph({
  spacing: { before: 60, after: 60 },
  indent: { left: 360 },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: CY, space: 12 } },
  shading: { fill: CY_LT, type: "clear" },
  children: [new TextRun({ text: txt, italics: true })],
});
const tip = (txt, runs) => new Paragraph({
  spacing: { before: 40, after: 40 },
  children: runs || [new TextRun({ text: txt, color: GREY })],
});
const bullet = (runs) => new Paragraph({
  numbering: { reference: "bullets", level: 0 },
  spacing: { after: 40 },
  children: runs,
});
const check = (txt) => new Paragraph({
  numbering: { reference: "checks", level: 0 },
  spacing: { after: 30 },
  children: [new TextRun({ text: txt })],
});

const children = [];

// ===== CAPA =====
children.push(new Paragraph({ spacing: { before: 200, after: 0 },
  children: [new TextRun({ text: "DOCTRACK", bold: true, size: 22, color: CY, characterSpacing: 60 })] }));
children.push(new Paragraph({ spacing: { before: 40, after: 80 },
  children: [new TextRun({ text: "Roteiro de Fala — Apresentação Executiva", bold: true, size: 40, color: INK })] }));
children.push(new Paragraph({
  border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: CY, space: 6 } },
  spacing: { after: 160 }, children: [new TextRun({ text: "" })] }));
children.push(label("Apresentado por:", "Melk Oliveira — Engenharia · P&D Equipamentos"));
children.push(label("Audiência:", "CEO e Diretoria"));
children.push(label("Duração-alvo:", "10–12 min + perguntas"));
children.push(label("Tom:", "confiante, direto ao impacto. Fale de valor para o negócio, não de detalhes técnicos."));
children.push(tip(null, [
  new TextRun({ text: "Dica geral: ", bold: true }),
  new TextRun({ text: "cada slide = uma ideia. Não leia o slide — ele é o apoio visual; você conta a história. Avance com " }),
  new TextRun({ text: "→", bold: true }), new TextRun({ text: " ou espaço; tecle " }),
  new TextRun({ text: "F", bold: true }), new TextRun({ text: " para tela cheia antes de começar." }),
]));

// ===== SLIDES =====
const slides = [
  { t: "Slide 1 — Capa", time: "≈30s", msg: "abrir com confiança e enquadrar o tema.",
    q: "Bom dia. Nesse último ano, meu trabalho na engenharia evoluiu de organizar documentos para construir uma base que pode mudar como a empresa enxerga seus projetos. É isso que quero mostrar hoje, de forma bem objetiva.",
    tip: "Faça uma pausa. Deixe a capa respirar." },
  { t: "Slide 2 — A jornada", time: "≈60s", msg: "comecei entendendo antes de mudar; construí sobre o que já existia.",
    q: "Quando entrei, minha prioridade foi entender o ambiente e o fluxo de documentos. O Guilherme já tinha começado a padronização — meu papel foi otimizar isso para eliminar retrabalho e, a partir daí, produzir documentos em escala. Essa jornada passou por quatro fases: diagnóstico, otimização, produção e, por fim, a plataforma.",
    tip: "Aponte para a linha do tempo enquanto fala. Crédito ao Guilherme demonstra maturidade." },
  { t: "Slide 3 — O problema", time: "≈45s", msg: "havia um custo real escondido na desorganização.",
    q: "O problema que eu via era concreto: retrabalho por falta de modelo, ausência de padrão entre documentos e nenhuma visão única do projeto. Isso custa tempo de engenharia e dificulta auditoria.",
    tip: "Conecte com dinheiro/tempo — é o que a diretoria ouve." },
  { t: "Slide 4 — Três pilares", time: "≈50s", msg: "atuei em três frentes complementares.",
    q: "Minha contribuição se organizou em três frentes: primeiro, um fluxo padronizado de elaboração de IT; segundo, o controle documental, que virou o DocTrack; e terceiro, a contribuição técnica em eletroeletrônica e programação.",
    tip: "É o “mapa” da apresentação — o resto detalha cada pilar." },
  { t: "Slide 5 — Resultados em números", time: "≈50s", msg: "entrega concreta e mensurável.",
    q: "Em números: mais de 115 documentos técnicos elaborados — entre ITs, checklists, guias rápidos, instruções específicas e relatórios técnicos. Um fluxo de IT padronizado e uma plataforma de gestão criada do zero.",
    tip: "Enfatize: “esses 115 documentos viraram patrimônio de conhecimento da empresa — não ficam na cabeça de uma pessoa.”" },
  { t: "Slide 6 — A plataforma (DocTrack) na prática", time: "≈70s", msg: "não é um repositório de arquivos, é controle e visão. Este slide já mostra uma visão do dashboard.",
    q: "Esse é o DocTrack na prática. No topo, os indicadores: total de documentos, percentual de conclusão, o que está em revisão. Abaixo, a distribuição por categoria e o pipeline de etapas. Tudo isso atualiza em tempo real, com rastreabilidade e log de auditoria de cada documento.",
    tip: "Aponte para os elementos enquanto fala (KPIs → rosca → pipeline). Se puder, abra a plataforma real por 20–30s logo depois — é o momento de maior impacto." },
  { t: "Slide 7 — Contribuição técnica", time: "≈50s", msg: "também entrego melhorias diretas no produto.",
    q: "Além dos documentos, atuo em eletroeletrônica e programação. Um exemplo prático: implementei a opção de idioma no Ampligene Lite — um botão que alterna a interface entre português e inglês, ampliando o alcance do produto com uma entrega pequena, mas de impacto direto.",
    tipRuns: [
      new TextRun({ text: "Interativo: ", bold: true, color: CY }),
      new TextRun({ text: "clique no botão " }),
      new TextRun({ text: "PT / EN", bold: true }),
      new TextRun({ text: " no slide — a prévia troca de idioma ao vivo, exatamente como no produto. À direita roda, em loop suave (vai-e-volta), o vídeo da vista explodida do Ampligene; deixe-o falar por si." }),
    ] },
  { t: "Slide 8 — A visão", time: "≈60s", msg: "o melhor ainda está por vir; isto é um trampolim.",
    q: "A plataforma foi pensada para evoluir. Hoje ela controla documentos. O próximo nível é a gestão de projetos: ver tudo de um projeto em um só lugar — ITs, checklists, manuais e documentos de fabricantes. Uma visão 360º do projeto.",
    tip: "Este é o slide que vende o futuro. Fale com energia." },
  { t: "Slide 9 — IA: acelerar processos", time: "≈60s", msg: "a IA não é promessa distante — ela já construiu isto e pode acelerar o dia a dia.",
    q: "Quero chamar atenção para um ponto: esta plataforma foi construída com apoio de inteligência artificial, em semanas. Isso mostra a velocidade que a IA traz. O próximo passo é colocar essa mesma inteligência a serviço da engenharia: perguntar diretamente a um manual e ter a resposta em segundos, gerar o rascunho de uma IT a partir de um modelo, classificar documentos sozinha, alertar sobre pendências e até redigir o relatório de status. São horas de trabalho que viram minutos.",
    tip: "Linguagem que o gerente pediu: o que é possível com IA e como ela acelera processos. Conecte com tempo de engenharia economizado." },
  { t: "Slide 10 — Valor além da engenharia", time: "≈50s", msg: "o mesmo motor serve a empresa toda.",
    q: "E o valor não fica só na engenharia. A mesma lógica de padronização, rastreabilidade e visão consolidada serve produção, qualidade e governança. É conhecimento retido como ativo da empresa — base, inclusive, para certificações.",
    tip: "Aqui você fala a língua do CEO/CFO: ativo, governança, escala." },
  { t: "Slide 11 — Encerramento", time: "≈30s", msg: "fechar com síntese e abrir o diálogo.",
    q: "Resumindo: em um ano, organizei o fluxo documental, criei conhecimento técnico em escala e construí a plataforma que pode unificar a gestão de projetos da empresa. Foi um ano que virou base para o futuro. Obrigado — estou à disposição para perguntas.",
    tip: "Pare. Deixe o silêncio convidar perguntas." },
];

children.push(H1("Roteiro por slide"));
for (const s of slides) {
  children.push(H2(s.t, s.time));
  children.push(label("Mensagem:", s.msg));
  children.push(quote(`“${s.q}”`));
  children.push(s.tipRuns ? tip(null, s.tipRuns) : tip(s.tip));
}

// ===== PERGUNTAS =====
children.push(H1("Possíveis perguntas e respostas"));
const qa = [
  ["“Quanto tempo levou para construir o DocTrack?”",
   "Foi evoluindo junto com o trabalho do dia a dia — começou como planilha de controle e cresceu conforme a necessidade. É fruto de aprendizado contínuo, sem parar a entrega de documentos."],
  ["“Quem mais usa / depende disso hoje?”",
   "Hoje é a engenharia. Mas foi desenhado para escalar — por isso falo de levar para outras áreas."],
  ["“E se você sair? Fica refém de uma pessoa?”",
   "Justamente o contrário: a plataforma e os 115+ documentos existem para tirar o conhecimento da cabeça das pessoas e deixá-lo registrado e rastreável. É redução de dependência, não aumento."],
  ["“Qual o próximo passo concreto?”",
   "Consolidar a visão de projeto 360º. Posso trazer uma proposta detalhada de prioridades e prazos se houver interesse."],
  ["“Tem algum custo envolvido?”",
   "Hoje roda de forma enxuta. Quando fizer sentido escalar para a empresa, trago os números com calma — prefiro mostrar o valor primeiro."],
];
for (const [q, a] of qa) {
  children.push(new Paragraph({ spacing: { before: 140, after: 30 }, children: [new TextRun({ text: q, bold: true, color: INK })] }));
  children.push(quote(a));
}

// ===== CHECKLIST =====
children.push(H1("Checklist antes de apresentar"));
[
  "Abrir o .html e pressionar F (tela cheia)",
  "Testar avançar/voltar com as setas",
  "Conferir se o nome na capa está correto",
  "Ter o PDF como backup (caso o navegador falhe)",
  "Manter o arquivo de vídeo na mesma pasta do .html",
  "Se for mostrar o DocTrack ao vivo, deixá-lo já aberto em outra aba",
].forEach(c => children.push(check(c)));

// ===== DOC =====
const doc = new Document({
  creator: "Melk Oliveira",
  title: "Roteiro de Fala — DocTrack",
  styles: {
    default: { document: { run: { font: "Calibri", size: 22, color: "222222" } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, font: "Calibri", color: CY },
        paragraph: { spacing: { before: 320, after: 140 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 25, bold: true, font: "Calibri", color: INK },
        paragraph: { spacing: { before: 260, after: 60 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 540, hanging: 280 } } } }] },
      { reference: "checks", levels: [{ level: 0, format: LevelFormat.BULLET, text: "☐", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] },
    ],
  },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({
      alignment: AlignmentType.RIGHT,
      border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "DDDDDD", space: 4 } },
      children: [new TextRun({ text: "DocTrack · Roteiro de Fala", color: GREY, size: 16 })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Página ", color: GREY, size: 16 }),
        new TextRun({ children: [PageNumber.CURRENT], color: GREY, size: 16 })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync("Roteiro_de_Fala.docx", buf);
  console.log("OK -> Roteiro_de_Fala.docx (" + (buf.length/1024).toFixed(0) + " KB)");
});
