# -*- coding: utf-8 -*-
"""Gera o relatorio tecnico de avaliacao do site staging.loccus.com.br em PDF."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    HRFlowable
)

ROXO = colors.HexColor("#6A1B9A")
ROXO_CLARO = colors.HexColor("#9C27B0")
CINZA = colors.HexColor("#444444")
CINZA_CLARO = colors.HexColor("#EDE7F0")

VERMELHO = colors.HexColor("#C62828")
LARANJA = colors.HexColor("#EF6C00")
AMARELO = colors.HexColor("#F9A825")

styles = getSampleStyleSheet()

def S(name, **kw):
    base = kw.pop("parent", styles["Normal"])
    return ParagraphStyle(name, parent=base, **kw)

st_titulo = S("TituloCapa", fontName="Helvetica-Bold", fontSize=26, textColor=ROXO,
              leading=30, alignment=TA_LEFT, spaceAfter=6)
st_sub = S("SubCapa", fontName="Helvetica", fontSize=13, textColor=CINZA, leading=18)
st_meta = S("Meta", fontName="Helvetica", fontSize=10, textColor=CINZA, leading=15)
st_h1 = S("H1", fontName="Helvetica-Bold", fontSize=15, textColor=ROXO, leading=19,
          spaceBefore=16, spaceAfter=8)
st_h2 = S("H2", fontName="Helvetica-Bold", fontSize=12, textColor=colors.HexColor("#222222"),
          leading=16, spaceBefore=10, spaceAfter=3)
st_body = S("Body", fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#222222"),
            leading=15, alignment=TA_JUSTIFY, spaceAfter=6)
st_label = S("Label", fontName="Helvetica-Bold", fontSize=9, textColor=CINZA, leading=13)
st_cell = S("Cell", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#222222"), leading=12)
st_cell_b = S("CellB", fontName="Helvetica-Bold", fontSize=9, textColor=colors.white, leading=12,
              alignment=TA_CENTER)
st_chip = S("Chip", fontName="Helvetica-Bold", fontSize=8.5, textColor=colors.white,
            leading=11, alignment=TA_CENTER)

def chip(text, cor):
    t = Table([[Paragraph(text, st_chip)]], colWidths=[26*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), cor),
        ("TOPPADDING", (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("ROUNDEDCORNERS", [4,4,4,4]),
    ]))
    return t

story = []

# ----- CAPA -----
story.append(Spacer(1, 40*mm))
story.append(Paragraph("Relatório Técnico de Avaliação", st_titulo))
story.append(Paragraph("Inconsistências de Design e Funcionamento", st_titulo))
story.append(Spacer(1, 6*mm))
story.append(HRFlowable(width="100%", thickness=2, color=ROXO_CLARO, spaceAfter=10))
story.append(Paragraph("Ambiente avaliado: <b>staging.loccus.com.br</b>", st_sub))
story.append(Spacer(1, 30*mm))
capa_meta = [
    ["Objeto", "Site institucional Loccus (ambiente de homologação/staging)"],
    ["Tipo de avaliação", "Inspeção de design (UI/UX) e funcionamento (QA funcional)"],
    ["Métodos", "Análise de HTML/conteúdo + navegação assistida (desktop), console e validação de formulário"],
    ["Data da avaliação", "17/06/2026"],
    ["Páginas avaliadas", "Home (PT/EN), Blog, Contato"],
]
tcapa = Table([[Paragraph(a, st_label), Paragraph(b, st_meta)] for a, b in capa_meta],
              colWidths=[40*mm, 120*mm])
tcapa.setStyle(TableStyle([
    ("VALIGN", (0,0), (-1,-1), "TOP"),
    ("LINEBELOW", (0,0), (-1,-2), 0.5, colors.HexColor("#DDDDDD")),
    ("TOPPADDING", (0,0), (-1,-1), 6),
    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
]))
story.append(tcapa)
story.append(PageBreak())

# ----- RESUMO EXECUTIVO -----
story.append(Paragraph("1. Resumo Executivo", st_h1))
story.append(Paragraph(
    "Esta avaliação verificou o site em ambiente de homologação (<b>staging.loccus.com.br</b>) "
    "quanto a inconsistências de design e de funcionamento. Foram combinadas duas técnicas: "
    "análise direta do HTML/conteúdo de múltiplas páginas e navegação assistida no navegador "
    "(captura de tela, leitura do console JavaScript e teste de validação de formulário).", st_body))
story.append(Paragraph(
    "Foram identificadas <b>12 inconsistências</b>, distribuídas em três níveis de severidade. "
    "Os achados mais relevantes são de natureza editorial e de internacionalização: presença de "
    "<b>texto de preenchimento (“Lorem ipsum”)</b> publicado, <b>banner de site de desenvolvimento do WPML</b>, "
    "<b>variáveis de template não renderizadas</b> no aviso de cookies e <b>tradução incompleta da versão em inglês</b>. "
    "No âmbito funcional, destacam-se um <b>defeito de layout no formulário de contato</b> ao exibir erro de validação "
    "e <b>exceções de JavaScript</b> no carregamento da página inicial.", st_body))
story.append(Paragraph(
    "Recomenda-se tratar os itens de severidade <b>Alta</b> antes da promoção do ambiente para produção, "
    "pois são visíveis ao público e afetam a credibilidade institucional e o SEO.", st_body))

# Quadro de severidade
story.append(Paragraph("Síntese por severidade", st_h2))
sev = [
    [Paragraph("Severidade", st_cell_b), Paragraph("Qtd.", st_cell_b), Paragraph("Itens", st_cell_b)],
    [Paragraph("ALTA", st_chip), Paragraph("3", st_cell), Paragraph("Lorem ipsum publicado; banner WPML de desenvolvimento; variáveis de template no banner de cookies.", st_cell)],
    [Paragraph("MÉDIA", st_chip), Paragraph("5", st_cell), Paragraph("Tradução EN incompleta; bug de layout no formulário; exceções de JS; rota /en/ 404; ausência de hreflang.", st_cell)],
    [Paragraph("BAIXA", st_chip), Paragraph("4", st_cell), Paragraph("Inconsistência tipográfica; cards de Aplicações desalinhados/baixo contraste; datas do blog; imagens sem alt.", st_cell)],
]
tsev = Table(sev, colWidths=[26*mm, 14*mm, 120*mm])
tsev.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), ROXO),
    ("BACKGROUND", (0,1), (0,1), VERMELHO),
    ("BACKGROUND", (0,2), (0,2), LARANJA),
    ("BACKGROUND", (0,3), (0,3), AMARELO),
    ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ("ALIGN", (1,0), (1,-1), "CENTER"),
    ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#DDDDDD")),
    ("ROWBACKGROUNDS", (1,1), (-1,-1), [colors.white, CINZA_CLARO]),
    ("TOPPADDING", (0,0), (-1,-1), 6),
    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ("LEFTPADDING", (0,0), (-1,-1), 6),
    ("RIGHTPADDING", (0,0), (-1,-1), 6),
]))
story.append(tsev)

# ----- METODOLOGIA -----
story.append(Paragraph("2. Escopo e Metodologia", st_h1))
story.append(Paragraph(
    "A avaliação foi conduzida sobre o ambiente de homologação e não incluiu testes de carga, "
    "segurança ou compatibilidade entre múltiplos navegadores. As técnicas empregadas foram:", st_body))
for item in [
    "<b>Análise de conteúdo/HTML:</b> leitura do código e do conteúdo renderizado das páginas Home, Blog e Contato (PT e EN).",
    "<b>Navegação assistida (desktop):</b> percurso visual da página inicial, seções e rodapé, com captura de tela.",
    "<b>Console JavaScript:</b> leitura das mensagens de console durante o carregamento da Home.",
    "<b>Teste funcional de formulário:</b> submissão do formulário de contato em branco para verificar a validação.",
    "<b>Internacionalização:</b> comparação da versão PT com a versão EM (?lang=en).",
]:
    story.append(Paragraph("• " + item, st_body))
story.append(Paragraph(
    "<b>Limitação:</b> a validação de layout responsivo (mobile) não pôde ser confirmada de forma confiável, "
    "pois o redimensionamento de janela não refletiu no viewport durante o teste. Recomenda-se reteste "
    "específico de mobile.", st_body))

story.append(PageBreak())

# ----- DETALHAMENTO -----
story.append(Paragraph("3. Detalhamento dos Achados", st_h1))

def achado(num, titulo, sev_txt, sev_cor, categoria, descricao, evidencia, recomendacao):
    story.append(Paragraph(f"3.{num} &nbsp; {titulo}", st_h2))
    cab = Table([[chip(sev_txt, sev_cor), Paragraph(f"<b>Categoria:</b> {categoria}", st_cell)]],
                colWidths=[30*mm, 130*mm])
    cab.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                             ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story.append(cab)
    bloco = [
        [Paragraph("Descrição", st_label), Paragraph(descricao, st_cell)],
        [Paragraph("Evidência", st_label), Paragraph(evidencia, st_cell)],
        [Paragraph("Recomendação", st_label), Paragraph(recomendacao, st_cell)],
    ]
    tb = Table(bloco, colWidths=[28*mm, 132*mm])
    tb.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("BACKGROUND",(0,0),(0,-1), CINZA_CLARO),
        ("BOX",(0,0),(-1,-1),0.5, colors.HexColor("#DDDDDD")),
        ("INNERGRID",(0,0),(-1,-1),0.5, colors.HexColor("#DDDDDD")),
        ("TOPPADDING",(0,0),(-1,-1),5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),6),
        ("RIGHTPADDING",(0,0),(-1,-1),6),
    ]))
    story.append(tb)
    story.append(Spacer(1, 4*mm))

ach = [
    (1, "Texto “Lorem ipsum” publicado na Home e no Blog", "ALTA", VERMELHO,
     "Conteúdo / Editorial",
     "A seção “Fique por dentro” da Home e o Blog exibem um post real com título “Lorem ipsum dolor” "
     "e corpo de texto de preenchimento, além do post padrão “Hello world!” do WordPress, que nunca foi removido.",
     "Confirmado visualmente na Home e no Blog. Texto: “Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
     "Nulla fermentum arcu metus...”.",
     "Remover/despublicar os posts de exemplo e substituir por conteúdo real antes da publicação."),
    (2, "Banner de “site de desenvolvimento” do WPML", "ALTA", VERMELHO,
     "Configuração / SEO",
     "O conteúdo apresenta o aviso do WPML indicando que o site está registrado como ambiente de desenvolvimento.",
     "Texto presente no HTML: “Este site está registrado em wpml.org como um site de desenvolvimento.”",
     "Aplicar a chave de produção do WPML para remover o banner antes de promover a produção."),
    (3, "Variáveis de template não renderizadas no banner de cookies", "ALTA", VERMELHO,
     "Defeito de renderização",
     "O banner de gestão de cookies exibe marcadores de template em vez dos valores reais.",
     "Ocorrências de {title} (3x) e {vendor_count} (ex.: “Gerenciar {vendor_count} fornecedores”).",
     "Revisar a configuração/integração do plugin de consentimento (Complianz) para que as variáveis sejam preenchidas."),
    (4, "Tradução incompleta da versão em inglês", "MÉDIA", LARANJA,
     "Internacionalização (i18n)",
     "Na versão em inglês (?lang=en), diversos blocos permanecem em português.",
     "Confirmado visualmente: bloco Newsletter (“Newsletter” / “Cadastre-se e receba nossas informações” / “Inscreva-se”), "
     "cabeçalho “Contato” no rodapé, “Loccus® - Todos os direitos reservados.” e botão “LEIA MAIS” do blog.",
     "Completar as strings de tradução (WPML), incluindo widgets de rodapé, newsletter e rótulos de botões."),
    (5, "Defeito de layout no formulário de contato ao validar", "MÉDIA", LARANJA,
     "Funcional / UI",
     "Ao submeter o formulário “Fale Conosco” com erro de validação, o botão ENVIAR é reposicionado para cima e "
     "fica sobreposto à seção “Intenção”, quebrando o layout. A validação destacou apenas o telefone, sem marcar "
     "os campos obrigatórios Nome e E-mail.",
     "Confirmado em teste de submissão em branco: mensagem “Digite um número de telefone.” e “Um ou mais campos "
     "possuem um erro. Verifique e tente novamente.”, com o botão sobreposto.",
     "Corrigir o CSS de exibição das mensagens de erro (evitar reflow que sobrepõe elementos) e garantir validação "
     "consistente de todos os campos obrigatórios."),
    (6, "Exceções de JavaScript no carregamento da Home", "MÉDIA", LARANJA,
     "Funcional / JS",
     "Foram registradas duas exceções de JavaScript no console durante o carregamento da página inicial.",
     "Mensagens do tipo EXCEPTION (objeto) capturadas no console em staging.loccus.com.br.",
     "Investigar a origem das exceções (stack trace) e corrigir, pois podem afetar interações futuras."),
    (7, "Rota /en/ retorna 404", "MÉDIA", LARANJA,
     "Internacionalização / Navegação",
     "O seletor de idioma utiliza query string (?lang=en, ?lang=es). A URL “limpa” /en/ retorna erro 404.",
     "Requisição a /en/ resultou em HTTP 404 Not Found.",
     "Garantir consistência de URLs de idioma e/ou redirecionar /en/ para o formato suportado, evitando links quebrados."),
    (8, "Ausência de tags hreflang", "MÉDIA", LARANJA,
     "SEO multilíngue",
     "O site oferece PT, EN e ES, mas não declara tags hreflang no cabeçalho do documento.",
     "Nenhuma tag &lt;link rel=\"hreflang\"&gt; identificada no &lt;head&gt;.",
     "Adicionar hreflang para cada idioma/variante, melhorando a indexação correta por mecanismos de busca."),
    (9, "Inconsistência tipográfica entre seções", "BAIXA", AMARELO,
     "Design / Identidade visual",
     "Coexistem ao menos três estilos de título: o hero em caixa-alta pesada, títulos de seção em fonte geométrica "
     "(“Matrizes”, “Equipamentos”, “Aplicações”) e títulos como “Fluxo de Trabalho” / marca-d’água "
     "“Sobre nós” em fonte fina e arredondada.",
     "Confirmado visualmente em diferentes seções da Home.",
     "Padronizar a hierarquia tipográfica conforme um guia de estilo único (famílias, pesos e usos)."),
    (10, "Cards de “Aplicações” desalinhados e com baixa legibilidade", "BAIXA", AMARELO,
     "Design / Acessibilidade",
     "As imagens da seção Aplicações ficam escalonadas em alturas diferentes e alguns rótulos brancos sobre fundo "
     "claro têm contraste insuficiente, com texto colado à borda inferior.",
     "Confirmado visualmente (ex.: “Precision Agriculture” e “Forensics and Human Identification”).",
     "Padronizar alturas/alinhamento dos cards e reforçar o contraste do rótulo (overlay/sombra) para WCAG AA."),
    (11, "Datas do blog em formato incomum e data futura", "BAIXA", AMARELO,
     "Conteúdo",
     "As datas do blog usam o formato “02 / 03 / 2026” (com espaços) e há post com data associada a conteúdo de exemplo.",
     "Confirmado visualmente no card de blog.",
     "Padronizar o formato de data e revisar datas/conteúdos de exemplo."),
    (12, "Imagens sem atributo alt", "BAIXA", AMARELO,
     "Acessibilidade / SEO",
     "Imagens do carrossel de produtos e do hero não apresentam texto alternativo.",
     "Identificado na análise de HTML das imagens (carrossel e hero).",
     "Adicionar textos alternativos descritivos a todas as imagens informativas."),
]

for a in ach:
    achado(*a)

# ----- CONCLUSAO -----
story.append(Paragraph("4. Conclusão e Próximos Passos", st_h1))
story.append(Paragraph(
    "O ambiente avaliado encontra-se funcional em sua estrutura principal, com navegação, seletor de idioma "
    "(via query string) e formulário de contato operantes. Contudo, há pendências editoriais e de "
    "internacionalização que devem ser resolvidas antes da promoção a produção, em especial os itens de "
    "severidade Alta, por serem visíveis ao público.", st_body))
story.append(Paragraph("Plano de ação sugerido (por prioridade):", st_h2))
for item in [
    "<b>1. Imediato (severidade Alta):</b> remover conteúdo “Lorem ipsum” e post “Hello world!”; aplicar chave de produção do WPML; corrigir variáveis do banner de cookies.",
    "<b>2. Curto prazo (severidade Média):</b> completar tradução EN; corrigir o layout do formulário e a validação; investigar as exceções de JS; tratar a rota /en/ e adicionar hreflang.",
    "<b>3. Melhoria contínua (severidade Baixa):</b> padronizar tipografia; ajustar cards de Aplicações; padronizar datas; adicionar alt às imagens.",
    "<b>4. Reteste pendente:</b> validar o layout responsivo (mobile), não confirmado nesta avaliação.",
]:
    story.append(Paragraph(item, st_body))

story.append(Spacer(1, 8*mm))
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CCCCCC"), spaceAfter=6))
story.append(Paragraph(
    "Relatório gerado em 17/06/2026 a partir da avaliação do ambiente staging.loccus.com.br. "
    "Documento técnico de uso interno.", st_meta))


def rodape(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(CINZA)
    canvas.drawString(20*mm, 12*mm, "Avaliação técnica – staging.loccus.com.br")
    canvas.drawRightString(190*mm, 12*mm, f"Página {doc.page}")
    canvas.setStrokeColor(colors.HexColor("#DDDDDD"))
    canvas.line(20*mm, 15*mm, 190*mm, 15*mm)
    canvas.restoreState()

doc = SimpleDocTemplate(
    "Relatorio_Tecnico_Avaliacao_staging_loccus.pdf", pagesize=A4,
    leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm,
    title="Relatório Técnico de Avaliação - staging.loccus.com.br",
    author="Equipe TI Loccus")
doc.build(story, onFirstPage=rodape, onLaterPages=rodape)
print("PDF gerado com sucesso.")
