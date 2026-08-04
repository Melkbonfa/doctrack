/* ═══════════════════════════════════════════════════════════════════════════
   custos.js — front do módulo Custos.

   O servidor calcula (custos/core.py) e este arquivo só desenha. Nenhuma
   fórmula de custo é reimplementada aqui de propósito: foi a duplicação de
   fórmula entre abas que tornou a planilha de origem indefensável, e um
   segundo motor em JavaScript recriaria o mesmo problema com mais passos.

   Sem bundler e sem framework, como o resto do projeto. Depende de common.js
   (esc, getToken, salvarResposta, baixarDoServidor) e auth.js (DT_AUTH).
   ═══════════════════════════════════════════════════════════════════════════ */
"use strict";

sessionStorage.setItem("dt_module", "custos");

let META = null;
let COMPS = [];
let ATUAL = null;
let REF = {valor: null, data: null, anterior: null, porMoeda: {}};
let SERIE = {USD: [], EUR: []};

/* ── bandeiras: emoji de bandeira não renderiza no Windows ── */
const FLAGS = (function(){
  let us = "";
  for(let i = 0; i < 6; i++)
    us += '<rect y="' + (1.54 + i * 3.08).toFixed(2) + '" width="28" height="1.54" fill="#fff"/>';
  for(let r = 0; r < 4; r++) for(let c = 0; c < 5; c++)
    us += '<circle cx="' + (1.3 + c * 2.15 + (r % 2 ? 1.07 : 0)).toFixed(2) +
          '" cy="' + (1.5 + r * 2.6).toFixed(2) + '" r=".55" fill="#fff"/>';
  let eu = "";
  for(let k = 0; k < 12; k++){
    const a = k * Math.PI / 6;
    eu += '<circle cx="' + (14 + 6 * Math.sin(a)).toFixed(2) +
          '" cy="' + (10 - 6 * Math.cos(a)).toFixed(2) + '" r=".95" fill="#fc0"/>';
  }
  return {
    USD: '<svg class="cs-fl" viewBox="0 0 28 20"><rect width="28" height="20" fill="#b22234"/>' +
         us + '<rect width="11.2" height="10.8" fill="#3c3b6e"/></svg>',
    EUR: '<svg class="cs-fl" viewBox="0 0 28 20"><rect width="28" height="20" fill="#039"/>' + eu + '</svg>',
    BRL: '<svg class="cs-fl" viewBox="0 0 28 20"><defs><clipPath id="csbr">' +
         '<circle cx="14" cy="10" r="4.5"/></clipPath></defs>' +
         '<rect width="28" height="20" fill="#009b3a"/>' +
         '<polygon points="14,2.6 25.4,10 14,17.4 2.6,10" fill="#fedf00"/>' +
         '<circle cx="14" cy="10" r="4.5" fill="#002776"/>' +
         '<path d="M8 9.2 A 7.5 7.5 0 0 1 20.4 11.4 L20.4 14 L8 14 Z" fill="#fff" clip-path="url(#csbr)"/>' +
         '</svg>'
  };
})();
const fl = (m, cls) => (FLAGS[m] || "").replace('class="cs-fl"', 'class="cs-fl ' + (cls || "") + '"');

/* ── formatação ── */
const brl = v => v == null ? "—"
  : Number(v).toLocaleString("pt-BR", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const pct = v => v == null ? "—"
  : (v * 100).toLocaleString("pt-BR", {minimumFractionDigits: 1, maximumFractionDigits: 1}) + "%";
const taxa = v => v == null ? "—" : Number(v).toFixed(4);
const el = id => document.getElementById(id);

function toast(msg){
  const t = el("toast");
  el("toast-msg").textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 3200);
}

/* ── fetch autenticado (mesmo contrato dos outros módulos) ── */
async function api(url, opts){
  opts = opts || {};
  const h = Object.assign({"Content-Type": "application/json"}, opts.headers || {});
  h["Authorization"] = "Bearer " + getToken();
  let res = await fetch(url, Object.assign({}, opts, {headers: h}));
  if(res.status === 401 && window.DT_AUTH){
    // O backend decide o que este perfil pode ver; o front só obedece.
    const ok = await window.DT_AUTH.refresh();
    if(ok){
      h["Authorization"] = "Bearer " + getToken();
      res = await fetch(url, Object.assign({}, opts, {headers: h}));
    } else {
      window.DT_AUTH.gotoLogin();
      throw new Error("sessão expirada");
    }
  }
  const corpo = await res.json().catch(() => ({}));
  if(!res.ok) throw new Error(corpo.erro || "Falha na requisição (HTTP " + res.status + ")");
  return corpo;
}

/* ═══════════ NAVEGAÇÃO ═══════════ */
const TITULOS = {visao: "Visão geral", composicoes: "Composições", detalhe: "Composição",
                 comparativo: "Comparativo", cotacoes: "Cotações", saude: "Saúde"};

function irPara(pag){
  document.querySelectorAll(".page").forEach(s => s.classList.remove("active"));
  const alvo = el("page-" + pag);
  if(alvo) alvo.classList.add("active");
  document.querySelectorAll(".nav-item").forEach(b =>
    b.classList.toggle("active", b.dataset.page === pag));
  el("breadcrumb-current").textContent = TITULOS[pag] || pag;
  window.scrollTo({top: 0, behavior: "smooth"});
}

/* ═══════════ CÂMBIO ═══════════ */
function fxCard(o){
  let extra = "";
  if(o.plan) extra = '<span class="cs-tag cogs" style="margin-left:auto">orça</span>';
  else if(o.trend != null && Math.abs(o.trend) > 1e-6)
    extra = '<span class="cs-trend ' + (o.trend > 0 ? "up" : "dn") + '">' +
            (o.trend > 0 ? "▲" : "▼") + " " + pct(Math.abs(o.trend)) + "</span>";
  return '<div class="cs-fxc' + (o.plan ? " plan" : "") + '">' +
    '<div class="cs-fxh">' + fl(o.moeda) + '<span class="cs-fxr">' + esc(o.papel) + "</span>" + extra + "</div>" +
    '<div class="cs-fxv">' + taxa(o.valor) + '<span class="c">' + o.moeda + " → BRL</span></div>" +
    '<div class="cs-fxm">' + o.meta + "</div></div>";
}

function metaReferencia(){
  return REF.data
    ? '<span style="color:var(--green)">● sincronizada</span> · PTAX venda de ' + esc(REF.data)
    : '<span style="color:var(--amber)">● nenhuma cotação no banco</span> · a sincronização com o ' +
      'Banco Central roda com as tarefas diárias; em <b>Cotações</b> dá para forçar agora ou ' +
      'registrar à mão';
}

/* ═══════════ VISÃO GERAL ═══════════ */
function renderVisao(){
  const vig = COMPS.filter(c => c.status === "vigente");
  const soma = vig.reduce((a, c) => a + (c.calculo.custo_unitario || 0), 0);
  const nreT = COMPS.reduce((a, c) => a + (c.calculo.nre_realizado || 0), 0);
  const comDesvio = vig.filter(c => c.calculo.desvio_pct != null);
  const desvio = comDesvio.length
    ? comDesvio.reduce((a, c) => a + c.calculo.desvio_pct, 0) / comDesvio.length : null;

  el("v-kpis").innerHTML = [
    {c: "", l: "Composições vigentes", v: vig.length + " de " + COMPS.length,
     f: COMPS.filter(c => c.status === "rascunho").length + " em rascunho"},
    {c: "cogs", l: "Custo aterrissado — soma", v: "R$ " + brl(soma),
     f: "por unidade, todas as vigentes"},
    {c: "nre", l: "NRE registrado no portfólio", v: "R$ " + brl(nreT),
     f: nreT < 1000 ? "horas internas ainda não precificadas" : "custo de desenvolvimento"},
    {c: desvio == null ? "" : (desvio < 0 ? "good" : "bad"),
     l: "Desvio médio orçado → realizado",
     v: desvio == null ? "—" : (desvio > 0 ? "+" : "") + pct(desvio),
     f: desvio == null ? "sem realizado lançado"
        : (desvio < 0 ? "o portfólio fechou abaixo do orçado" : "acima do orçado")}
  ].map(k => '<div class="cs-kpi ' + k.c + '"><span class="l">' + k.l + '</span>' +
             '<div class="v">' + k.v + '</div><div class="f">' + k.f + "</div></div>").join("");

  // Módulo recém-instalado: KPIs zerados sem explicação parecem defeito.
  el("v-inicio").innerHTML = COMPS.length ? "" :
    '<div class="cs-alert info"><span class="i">◈</span><div>' +
    "<b>Nenhuma composição cadastrada ainda.</b>" +
    "Uma composição é a folha de custo de um produto: identidade, taxa de câmbio travada e " +
    "os lançamentos separados em <b>NRE</b> (desenvolvimento, amortiza sobre o volume) e " +
    "<b>COGS</b> (mercadoria e importação, por unidade). Ao criar, a estrutura de custo de " +
    "importação já vem montada — mercadoria, frete, Siscomex, os cinco tributos, despachante " +
    "e reserva cambial — bastando ajustar valores e alíquotas.<br><br>" +
    '<button class="btn btn-primary btn-sm" data-nova="1">+ Criar a primeira composição</button>' +
    "</div></div>";

  const planUsadas = [...new Set(COMPS.map(c => c.taxa_planejamento))];
  const comRealizada = COMPS.find(c => c.taxa_realizada);
  el("v-fx").innerHTML =
    fxCard({moeda: "USD", papel: "Referência · PTAX", valor: REF.valor, meta: metaReferencia(),
            trend: REF.anterior ? (REF.valor - REF.anterior) / REF.anterior : null}) +
    fxCard({moeda: "EUR", papel: "Referência · PTAX",
            valor: (REF.porMoeda.EUR || {}).valor,
            meta: (REF.porMoeda.EUR || {}).data
              ? '<span style="color:var(--green)">● sincronizada</span> · PTAX venda de ' +
                esc(REF.porMoeda.EUR.data)
              : '<span style="color:var(--amber)">● sem sincronização</span> · nenhuma cotação em EUR'}) +
    fxCard({moeda: "USD", papel: "Planejamento em uso", plan: true,
            valor: planUsadas.length === 1 ? planUsadas[0] : null,
            meta: planUsadas.length === 1
              ? "Travada nas " + COMPS.length + " composições"
              : planUsadas.length + " taxas distintas em uso — abra cada composição"}) +
    fxCard({moeda: (comRealizada || {}).moeda_base || "USD", papel: "Realizada · taxa da DI",
            valor: (comRealizada || {}).taxa_realizada,
            meta: comRealizada
              ? "DI " + esc(comRealizada.di_numero || "—") + "<br>Fecha o ciclo contra o baseline."
              : "Nenhuma DI lançada — o desvio não pode ser medido."});
  el("fx-stamp").textContent = REF.data ? "atualizado em " + REF.data : "sem cotação no banco";

  el("v-tab").innerHTML = vig.length ? vig.map(c => {
    const k = c.calculo;
    return '<tr class="click" data-id="' + c.id + '">' +
      "<td><div style=\"font-weight:650\">" + esc(c.produto) + "</div>" +
        '<div class="desc">' + esc(c.codigo) + (c.projeto_nome ? " · " + esc(c.projeto_nome) : "") + "</div></td>" +
      '<td><span class="cs-tag ' + c.tipo.toLowerCase() + '">' + esc(c.tipo) + "</span></td>" +
      "<td>" + esc(c.fornecedor || "—") + "</td>" +
      '<td class="num">' + taxa(c.taxa_planejamento) + "</td>" +
      '<td class="num">' + (k.nre_realizado ? brl(k.nre_realizado) : '<span class="muted">—</span>') + "</td>" +
      '<td class="num">' + brl(k.cogs_orcado) + "</td>" +
      '<td class="num" style="color:var(--cyan-lt);font-weight:700">' +
        (k.cogs_realizado == null ? '<span class="muted">—</span>' : brl(k.cogs_realizado)) + "</td>" +
      '<td class="num ' + (k.desvio == null ? "muted" : (k.desvio > 0 ? "cs-pos" : "cs-neg")) + '">' +
        (k.desvio == null ? "—" : (k.desvio > 0 ? "+" : "") + brl(k.desvio)) + "</td>" +
      '<td class="num" style="font-weight:650;color:' + (k.margem_pct != null ? "var(--green)" : "var(--t4)") + '">' +
        (k.margem_pct != null ? pct(k.margem_pct) : '<span class="cs-tag media">sem preço</span>') + "</td></tr>";
  }).join("") : '<tr><td colspan="9" class="cs-vazio">Nenhuma composição vigente ainda.</td></tr>';
}

/* ═══════════ LISTA ═══════════ */
function renderLista(){
  el("n-comps").textContent = COMPS.length || "";
  el("c-tab").innerHTML = COMPS.length ? COMPS.map(c => {
    const k = c.calculo;
    return '<tr class="click" data-id="' + c.id + '">' +
      "<td><div style=\"font-weight:650\">" + esc(c.produto) + "</div>" +
        '<div class="desc">' + esc(c.fornecedor || "sem fornecedor") + " · " + esc(c.incoterm) + "</div></td>" +
      '<td class="num muted">' + esc(c.sku || "—") + "</td>" +
      "<td>" + esc(c.projeto_nome || "—") + "</td>" +
      '<td><span class="cs-tag ' + c.tipo.toLowerCase() + '">' + esc(c.tipo) + "</span></td>" +
      '<td><span class="cs-tag ' + c.status + '">' + esc(c.status) + "</span></td>" +
      '<td class="num">v' + c.versao + "</td>" +
      '<td class="num" style="font-weight:700;color:var(--cyan-lt)">' + brl(k.custo_unitario) + "</td>" +
      '<td class="num">' + (c.preco_venda ? brl(c.preco_venda)
        : '<span class="cs-tag media">não cadastrado</span>') + "</td>" +
      '<td class="num" style="font-weight:650;color:' + (k.margem_pct != null ? "var(--green)" : "var(--t4)") + '">' +
        (k.margem_pct != null ? pct(k.margem_pct) : "—") + "</td></tr>";
  }).join("") : '<tr><td colspan="9" class="cs-vazio">Nenhuma composição. Crie a primeira em ' +
    '<b>+ Nova composição</b>.</td></tr>';
}

/* ═══════════ DETALHE ═══════════ */
async function abrirComposicao(id){
  ATUAL = await api("/custos/api/composicoes/" + id);
  REF.valor = ATUAL.referencia != null ? ATUAL.referencia : REF.valor;
  REF.data = ATUAL.referencia_data || REF.data;
  renderDetalhe();
  irPara("detalhe");
}

function renderDetalhe(){
  const c = ATUAL, k = c.calculo;

  el("d-hero").innerHTML =
    "<h1>" + esc(c.produto) + "</h1>" +
    '<div class="m"><span>' + esc(c.codigo) + "</span><span>·</span>" +
      "<span>" + esc(c.projeto_nome || "sem projeto") + "</span><span>·</span>" +
      "<span>" + esc(c.fornecedor || "sem fornecedor") + "</span><span>·</span>" +
      '<span style="display:inline-flex;align-items:center;gap:7px">' + fl(c.moeda_base, "sm") +
      esc(c.incoterm) + "</span></div>" +
    '<div class="g"><span class="cs-tag lg ' + c.tipo.toLowerCase() + '">' + esc(c.tipo) + "</span>" +
      '<span class="cs-tag lg ' + c.status + '">' + esc(c.status) + "</span>" +
      '<span class="cs-tag lg neutro">v' + c.versao + "</span>" +
      (c.sku ? '<span class="cs-tag lg neutro">SKU ' + esc(c.sku) + "</span>" : "") +
      (c.di_numero ? '<span class="cs-tag lg neutro">DI ' + esc(c.di_numero) + "</span>" : "") + "</div>";

  el("d-ident").innerHTML = [
    ["Composição", esc(c.codigo), 1], ["SKU", esc(c.sku || "—"), 1],
    ["Fornecedor", esc(c.fornecedor || "—")], ["Incoterm", esc(c.incoterm)],
    ["FOB unitário", fl(c.moeda_base, "sm") + " " + brl(c.valor_fob), 1],
    ["Qtd. na invoice", (c.qtd_invoice || 1) + " un", 1],
    ["Volume projetado", (c.volume_projetado || 1) + " un", 1],
    ["Custo hora eng.", "R$ " + brl(c.custo_hora_engenharia), 1],
    ["Custo hora prod.", "R$ " + brl(c.custo_hora_producao), 1],
    ["Reserva cambial", brl(c.reserva_cambial_pct) + "%", 1],
    ["DI", esc(c.di_numero ? c.di_numero + " · " + c.di_data : "—"), 1],
    ["Preço de venda", c.preco_venda ? "R$ " + brl(c.preco_venda)
      : '<span class="cs-tag media">não cadastrado</span>', 1]
  ].map(f => "<div><dt>" + f[0] + "</dt><dd" + (f[2] ? ' class="mono"' : "") + ">" +
             f[1] + "</dd></div>").join("");

  el("d-fx").innerHTML =
    fxCard({moeda: "USD", papel: "Referência · PTAX", valor: REF.valor,
            meta: metaReferencia() + "<br>Nunca entra no cálculo — serve para alertar.",
            trend: REF.anterior ? (REF.valor - REF.anterior) / REF.anterior : null}) +
    fxCard({moeda: c.moeda_base, papel: "Planejamento", valor: c.taxa_planejamento, plan: true,
            meta: "Travada em " + esc(c.taxa_planejamento_data || "—") +
                  (c.taxa_planejamento_autor ? " por " + esc(c.taxa_planejamento_autor) : "") +
                  (c.taxa_planejamento_justificativa
                    ? "<br><i>“" + esc(c.taxa_planejamento_justificativa) + "”</i>" : "")}) +
    fxCard({moeda: c.moeda_base, papel: "Realizada · taxa da DI", valor: c.taxa_realizada,
            meta: c.taxa_realizada
              ? "DI " + esc(c.di_numero || "—") + " · " + esc(c.di_data || "—") +
                "<br>Fecha o ciclo contra o baseline."
              : "Ainda não lançada — o desvio não pode ser medido."});

  const lim = (META && META.limite_desvio_cambio) || 0.03;
  if(REF.valor && c.taxa_planejamento){
    const d = (c.taxa_planejamento - REF.valor) / REF.valor;
    el("d-fx-alert").innerHTML = Math.abs(d) < lim
      ? '<div class="cs-alert ok"><span class="i">✓</span><div><b>Dentro da política.</b>' +
        "A taxa travada está a " + pct(Math.abs(d)) + " da referência de mercado.</div></div>"
      : '<div class="cs-alert warn"><span class="i">⚠</span><div><b>Taxa travada ' +
        pct(Math.abs(d)) + " " + (d > 0 ? "acima" : "abaixo") + " da referência.</b>" +
        (d > 0 ? "A folga embutida protege contra alta e aparece como economia no fechamento."
               : "Sem folga: qualquer alta consome a reserva cambial.") + "</div></div>";
  } else {
    el("d-fx-alert").innerHTML = '<div class="cs-alert info"><span class="i">ℹ</span><div>' +
      "<b>Sem referência para comparar.</b>Sincronize a PTAX ou registre uma cotação manual.</div></div>";
  }

  renderLancamentos();

  el("d-kpis").innerHTML = [
    {c: "nre", l: "NRE — desenvolvimento", v: "R$ " + brl(k.nre_realizado),
     f: c.tipo === "Revenda" ? "revenda não tem desenvolvimento"
        : (k.nre_realizado < 1 ? "nenhuma hora precificada"
           : "R$ " + brl(k.nre_unitario) + "/un em " + k.volume_projetado + " unidades")},
    {c: "cogs", l: "COGS orçado — por unidade", v: "R$ " + brl(k.cogs_orcado),
     f: "à taxa travada de " + taxa(c.taxa_planejamento)},
    {c: "cogs", l: "COGS realizado — por unidade",
     v: k.cogs_realizado == null ? "—" : "R$ " + brl(k.cogs_realizado),
     f: k.cogs_realizado == null ? "nenhum valor lançado ainda"
        : (c.taxa_realizada ? "à taxa da DI de " + taxa(c.taxa_realizada) : "parcial")},
    {c: "", l: "Custo unitário total", v: "R$ " + brl(k.custo_unitario),
     f: k.cogs_realizado == null
        ? "orçado + NRE amortizado — ainda sem DI"
        : "realizado onde lançado, orçado no resto, + NRE amortizado"},
    {c: "good", l: "Margem bruta unitária",
     v: k.margem_valor != null ? "R$ " + brl(k.margem_valor) : "—",
     f: k.margem_pct != null ? pct(k.margem_pct) + " sobre R$ " + brl(c.preco_venda)
        : "preço de venda não cadastrado"},
    {c: "", l: "Payback do desenvolvimento",
     v: k.payback_unidades == null ? "—"
        : (k.payback_unidades < 1 ? "< 1 unidade" : k.payback_unidades.toFixed(1) + " unidades"),
     f: "NRE ÷ margem de contribuição"},
    {c: k.desvio == null ? "" : (k.desvio < 0 ? "good" : (k.desvio > 0 ? "bad" : "")),
     l: "Desvio orçado → realizado",
     v: k.desvio == null ? "—" : (k.desvio > 0 ? "+" : "") + "R$ " + brl(k.desvio),
     f: k.desvio == null ? "nada lançado para comparar"
        : ((k.desvio > 0 ? "acima" : "abaixo") + " do orçado" +
           (k.desvio_pct != null ? " · " + pct(Math.abs(k.desvio_pct)) : "") +
           " — só as linhas com os dois lados")},
    {c: "", l: "Exposição cambial", v: c.moeda_base + " " + brl(k.exposicao_cambial),
     f: "mercadoria + frete · base da reserva"}
  ].map(x => '<div class="cs-kpi ' + x.c + '"><span class="l">' + x.l + '</span>' +
             '<div class="v">' + x.v + '</div><div class="f">' + x.f + "</div></div>").join("");

  renderWaterfall(k);

  el("d-vers").innerHTML = (c.versoes || []).map(v =>
    '<div class="cs-ver"><span class="n">v' + v.numero + '</span><div>' +
    '<div class="b">' + esc(v.motivo || "Versão") + "</div>" +
    '<div class="m">' + esc(v.criado_em) + (v.criado_por ? " · " + esc(v.criado_por) : "") + "</div>" +
    "</div></div>").join("") || '<div class="cs-vazio">Nenhuma versão congelada.</div>';
}

function baseDaLinha(l, c){
  if(l.tipo_calculo === "percentual")
    return '<input class="cs-aliq" type="number" step="0.5" min="0" data-aliq="' + l.id +
           '" value="' + l.aliquota + '"><span class="muted" style="margin-left:5px">%</span>';
  if(l.tipo_calculo === "fob")
    return '<span style="display:inline-flex;align-items:center;gap:6px;justify-content:flex-end">' +
           fl(c.moeda_base, "sm") + brl(c.valor_fob) + "</span>";
  if(l.tipo_calculo === "reserva") return brl(l.aliquota) + "% s/ exposição";
  if(l.tipo_calculo === "horas")
    return brl(l.horas) + "h × R$ " +
           brl(l.perfil_hora === "eng" ? c.custo_hora_engenharia : c.custo_hora_producao);
  if(l.valor_moeda)
    return '<span style="display:inline-flex;align-items:center;gap:6px;justify-content:flex-end">' +
           fl(l.moeda, "sm") + brl(l.valor_moeda) + "</span>";
  return "—";
}

function renderLancamentos(){
  const c = ATUAL, k = c.calculo;
  const porId = {};
  (k.linhas || []).forEach(x => porId[x.id] = x);
  const nre = (c.lancamentos || []).filter(l => l.natureza === "nre");
  const cogs = (c.lancamentos || []).filter(l => l.natureza !== "nre");

  const linha = l => {
    const x = porId[l.id] || {};
    const d = x.desvio;
    const cls = d == null ? "muted" : (d > 0.5 ? "cs-pos" : (d < -0.5 ? "cs-neg" : "muted"));
    return '<tr class="' + (l.aplicavel ? "" : "off") + '">' +
      '<td><label class="cs-sw"><input type="checkbox" data-ap="' + l.id + '"' +
        (l.aplicavel ? " checked" : "") + ' aria-label="aplicável"><span></span></label></td>' +
      "<td><div style=\"font-weight:650\">" + esc(l.subcategoria) + "</div>" +
        '<div class="desc">' + esc(l.categoria) + (l.descricao ? " · " + esc(l.descricao) : "") +
        (l.observacao ? " <i>· " + esc(l.observacao) + "</i>" : "") + "</div></td>" +
      "<td>" + (l.procedencia
        ? '<span class="cs-tag neutro">' + esc((META.procedencias_labels || {})[l.procedencia] || l.procedencia) + "</span>"
        : '<span class="muted">—</span>') + "</td>" +
      "<td>" + (l.confianca ? '<span class="cs-tag ' + l.confianca + '">' + esc(l.confianca) + "</span>"
        : '<span class="muted">—</span>') + "</td>" +
      '<td class="num muted">' + baseDaLinha(l, c) + "</td>" +
      '<td class="num">' + brl(x.orcado) + "</td>" +
      '<td class="num">' + (x.realizado == null ? '<span class="muted">—</span>' : brl(x.realizado)) + "</td>" +
      '<td class="num ' + cls + '">' + (d == null ? "—" : (d > 0 ? "+" : "") + brl(d)) + "</td>" +
      '<td><div class="cs-acts">' +
        '<button class="cs-ib" data-ed="' + l.id + '" title="Editar">✎</button>' +
        '<button class="cs-ib d" data-rm="' + l.id + '" title="Excluir">🗑</button></div></td></tr>';
  };
  const tot = (rot, o, r, d) =>
    '<tr class="tot"><td></td><td>' + rot + '</td><td colspan="3"></td>' +
    '<td class="num">' + brl(o) + '</td><td class="num">' + brl(r) + "</td>" +
    '<td class="num ' + (d == null ? "" : (d > 0 ? "cs-pos" : "cs-neg")) + '">' +
    (d == null ? "" : (d > 0 ? "+" : "") + brl(d)) + "</td><td></td></tr>";

  let html = "";
  html += '<tr class="grp nre"><td colspan="9">NRE · custo não recorrente do projeto — amortiza sobre o volume</td></tr>';
  html += nre.length ? nre.map(linha).join("") + tot("Total NRE (projeto)", k.nre_orcado, k.nre_realizado, null)
                     : '<tr><td colspan="9" class="cs-vazio">Sem lançamentos de NRE.</td></tr>';
  html += '<tr class="grp cogs"><td colspan="9">COGS · custo recorrente por unidade — não amortiza</td></tr>';
  html += cogs.map(linha).join("") + tot("Total COGS (por unidade)", k.cogs_orcado, k.cogs_realizado, k.desvio);
  el("d-lanc").innerHTML = html;
}

function renderWaterfall(k){
  const itens = (k.linhas || [])
    .filter(x => x.natureza !== "nre" && x.realizado != null && Math.abs(x.desvio) > 0.5)
    .map(x => ({n: x.subcategoria, d: x.desvio}))
    .sort((a, b) => Math.abs(b.d) - Math.abs(a.d));
  if(!itens.length){
    el("d-wf").innerHTML = '<div class="cs-vazio">Sem realizado lançado — nada a comparar ainda.</div>';
    return;
  }
  const max = Math.max(...itens.map(i => Math.abs(i.d)), Math.abs(k.desvio), 1);
  const linha = (n, d, cor, base) => {
    const w = Math.abs(d) / max * 50, p = d > 0;
    return '<div class="cs-wfr' + (base ? " base" : "") + '"><div>' + esc(n) + "</div>" +
      '<div class="cs-wft"><div class="cs-wfz" style="left:50%"></div>' +
      '<div class="cs-wfb" style="' + (p ? "left:50%" : "right:50%") + ";width:" + w + "%;background:" +
      (cor || (p ? "var(--red)" : "var(--green)")) + '"></div></div>' +
      '<div class="num ' + (p ? "cs-pos" : "cs-neg") + '">' + (p ? "+" : "") + brl(d) + "</div></div>";
  };
  el("d-wf").innerHTML = itens.map(i => linha(i.n, i.d)).join("") +
    linha("Desvio total", k.desvio, "#8b5cf6", true);
}

/* ═══════════ COMPARATIVO ═══════════ */
async function renderComparativo(){
  const d = await api("/custos/api/portfolio");
  const max = Math.max(...d.itens.map(i => i.custo_unitario || 0), 1);
  el("k-bars").innerHTML = d.itens.length ? d.itens.map(i => {
    const cogs = i.cogs_efetivo || 0, nre = i.nre_unitario || 0;
    const seg = (v, cor) => '<div class="cs-fill" style="width:' + (v / max * 100) + "%;background:" + cor + '"></div>';
    return '<div class="cs-bar"><div><div style="font-weight:650">' + esc(i.produto) + "</div>" +
      '<div class="desc" style="font-size:11px;color:var(--t4)">' + esc(i.tipo) + " · " +
      i.qtd_invoice + " un · FOB " + brl(i.valor_fob) + "</div></div>" +
      '<div class="cs-track">' + seg(cogs, "var(--cyan-brand)") + seg(nre, "#8b5cf6") + "</div>" +
      '<div class="num">R$ ' + brl(i.custo_unitario) + "</div></div>";
  }).join("") : '<div class="cs-vazio">Nenhuma composição para comparar.</div>';
  el("k-bars").insertAdjacentHTML("afterend", "");

  el("k-tab").innerHTML = d.itens.map(i =>
    '<tr class="click" data-id="' + i.id + '"><td style="font-weight:650">' + esc(i.produto) +
    '<div class="desc">' + esc(i.sku || i.codigo) + "</div></td>" +
    '<td><span class="cs-tag ' + i.tipo.toLowerCase() + '">' + esc(i.tipo) + "</span></td>" +
    '<td class="num">' + i.qtd_invoice + '</td><td class="num">' + brl(i.valor_fob) + "</td>" +
    '<td class="num">' + (i.cogs_realizado == null
      ? '<span class="muted">—</span>' : brl(i.cogs_realizado)) + "</td>" +
    '<td class="num">' + (i.nre_unitario ? brl(i.nre_unitario) : '<span class="muted">—</span>') + "</td>" +
    '<td class="num" style="font-weight:700;color:var(--cyan-lt)">' + brl(i.custo_unitario) + "</td>" +
    '<td class="num">' + (i.preco_venda ? brl(i.preco_venda)
      : '<span class="cs-tag media">não cadastrado</span>') + "</td>" +
    '<td class="num" style="font-weight:650;color:' + (i.margem_pct != null ? "var(--green)" : "var(--t4)") + '">' +
      (i.margem_pct != null ? pct(i.margem_pct) : "—") + "</td></tr>").join("") ||
    '<tr><td colspan="9" class="cs-vazio">Sem dados.</td></tr>';

  const cores = ["var(--cyan-brand)", "var(--amber)", "#8b5cf6", "var(--pink)", "var(--teal)"];
  const mx = d.categorias.length ? d.categorias[0].valor : 1;
  el("k-cat").innerHTML = d.categorias.length ? d.categorias.map((c, i) =>
    '<div class="cs-bar"><div style="font-weight:650">' + esc(c.categoria) + "</div>" +
    '<div class="cs-track"><div class="cs-fill" style="width:' + (c.valor / mx * 100) +
    "%;background:" + cores[i % cores.length] + '"></div></div>' +
    '<div class="num">R$ ' + brl(c.valor) + '<div class="desc" style="color:var(--t4)">' +
    pct(c.pct) + "</div></div></div>").join("")
    : '<div class="cs-vazio">Sem lançamentos aplicáveis.</div>';
}

/* ═══════════ COTAÇÕES ═══════════ */
async function renderCotacoes(){
  const d = await api("/custos/api/cotacoes?limite=200");
  SERIE = {USD: [], EUR: []};
  d.cotacoes.forEach(c => { if(SERIE[c.moeda]) SERIE[c.moeda].push(c); });
  const u = SERIE.USD, e = SERIE.EUR;

  el("s-lg").innerHTML =
    "<span>" + fl("USD", "sm") + '<i style="background:var(--cyan)"></i>USD — PTAX venda</span>' +
    "<span>" + fl("EUR", "sm") + '<i style="background:var(--pink)"></i>EUR — PTAX venda</span>' +
    '<span><i style="background:var(--amber)"></i>Taxa de planejamento em uso</span>';

  const plan = COMPS.length ? COMPS[0].taxa_planejamento : null;
  if(!u.length){
    el("spark").innerHTML = '<text x="450" y="86" text-anchor="middle" fill="#8f9dd6">' +
      "Sem cotação sincronizada — o registro manual segue disponível.</text>";
    el("s-stamp").textContent = "";
  } else {
    const W = 900, H = 172, P = 28;
    const vals = u.concat(e).map(p => p.valor).concat(plan ? [plan] : []);
    const lo = Math.min(...vals) * 0.985, hi = Math.max(...vals) * 1.015;
    const X = (i, n) => P + i * (W - 2 * P) / Math.max(1, n - 1);
    const Y = v => H - 20 - (v - lo) / (hi - lo) * (H - 40);
    const path = a => a.map((p, i) => (i ? "L" : "M") + X(i, a.length).toFixed(1) + " " + Y(p.valor).toFixed(1)).join(" ");
    const area = a => path(a) + " L" + X(a.length - 1, a.length).toFixed(1) + " " + (H - 20) +
                      " L" + X(0, a.length) + " " + (H - 20) + " Z";
    let g = '<defs><linearGradient id="csgu" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="#22d3ee" stop-opacity=".3"/><stop offset="1" stop-color="#22d3ee" stop-opacity="0"/>' +
      '</linearGradient><linearGradient id="csge" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="#ec4899" stop-opacity=".26"/><stop offset="1" stop-color="#ec4899" stop-opacity="0"/>' +
      "</linearGradient></defs>";
    [0, .25, .5, .75, 1].forEach(f => {
      const y = 18 + f * (H - 40);
      g += '<line class="gl" x1="' + P + '" y1="' + y.toFixed(1) + '" x2="' + (W - P) + '" y2="' + y.toFixed(1) + '"/>';
    });
    if(plan){
      const yp = Y(plan);
      g += '<line class="plan" x1="' + P + '" y1="' + yp.toFixed(1) + '" x2="' + (W - P) + '" y2="' + yp.toFixed(1) + '"/>' +
           '<text x="' + (W - P - 2) + '" y="' + (yp - 6).toFixed(1) + '" text-anchor="end" fill="#f59e0b">planejamento ' +
           taxa(plan) + "</text>";
    }
    g += '<path d="' + area(u) + '" fill="url(#csgu)"/><path class="ln" d="' + path(u) + '" stroke="#22d3ee"/>';
    if(e.length) g += '<path d="' + area(e) + '" fill="url(#csge)"/><path class="ln" d="' + path(e) + '" stroke="#ec4899"/>';
    g += '<text x="' + P + '" y="' + (H - 4) + '">' + esc(u[0].data) + "</text>" +
         '<text x="' + (W - P) + '" y="' + (H - 4) + '" text-anchor="end">' + esc(u[u.length - 1].data) + "</text>";
    el("spark").innerHTML = g;
    el("s-stamp").textContent = u.length + " dia(s) útil(eis) · fonte " + esc(u[u.length - 1].fonte);
  }

  const linhas = d.cotacoes.slice().reverse().slice(0, 24);
  el("s-tab").innerHTML = linhas.length ? linhas.map(c =>
    '<tr><td class="num">' + esc(c.data) + "</td>" +
    '<td><span style="display:inline-flex;align-items:center;gap:8px">' + fl(c.moeda, "sm") +
      "<b>" + c.moeda + "</b></span></td>" +
    '<td><span class="cs-tag neutro">' + esc(c.tipo) + "</span></td>" +
    '<td class="num" style="font-weight:700;color:var(--cyan-lt)">' + taxa(c.valor) + "</td>" +
    '<td><span class="cs-tag neutro">' + esc(c.fonte) + "</span></td>" +
    '<td class="muted">' + esc(c.obtido_em) + "</td></tr>").join("")
    : '<tr><td colspan="6" class="cs-vazio">Nenhuma cotação no banco.</td></tr>';

  el("s-note").innerHTML = d.habilitado
    ? "A PTAX publica só em dia útil, no fim da tarde. Por isso a sincronização busca uma " +
      "<b>janela</b> de dias e faz upsert por (moeda, data, tipo) — rodar duas vezes no mesmo " +
      "dia não duplica nada."
    : "<b>Sincronização automática desligada</b> (<code>DOCTRACK_CAMBIO=0</code>). " +
      "O registro manual continua disponível e o módulo segue utilizável.";
}

/* ═══════════ SAÚDE ═══════════ */
const COR_SEV = {falha: "var(--red)", aviso: "var(--amber)", obs: "var(--t3)"};
const corIndice = s => s >= 85 ? "var(--green)" : (s >= 60 ? "var(--amber)" : "var(--red)");

function anelSvg(s){
  const r = 22, C = 2 * Math.PI * r, on = C * s / 100;
  return '<svg class="cs-ring" viewBox="0 0 54 54"><circle class="bg" cx="27" cy="27" r="' + r + '"/>' +
    '<circle class="fg" cx="27" cy="27" r="' + r + '" stroke="' + corIndice(s) +
    '" stroke-dasharray="' + on.toFixed(1) + " " + C.toFixed(1) + '"/>' +
    '<text x="27" y="32.5">' + s + "</text></svg>";
}

async function renderSaude(){
  const d = await api("/custos/api/saude");
  if(d.vazio){
    // Sem composições não há índice — mostrar um número aqui daria a impressão
    // de que o módulo foi avaliado e passou.
    el("v-saude").innerHTML =
      '<svg class="cs-ring" viewBox="0 0 54 54"><circle class="bg" cx="27" cy="27" r="22"/>' +
      '<text x="27" y="32.5" style="font-size:13px;fill:var(--t4)">—</text></svg>' +
      '<div class="cs-sb"><div class="cs-st">Saúde do módulo</div>' +
      '<div class="cs-sp"><span class="cs-pill">' + esc(d.mensagem) + "</span></div></div>";
    el("n-saude").textContent = "";
    el("sd-kpis").innerHTML = "";
    el("sd-lista").innerHTML = '<div class="cs-vazio">' + esc(d.mensagem) +
      "<br>As verificações aparecem assim que a primeira composição existir.</div>";
    return;
  }
  const pil = (q, sev, lbl) => q
    ? '<span class="cs-pill"><i style="background:' + COR_SEV[sev] + '"></i>' + q + " " + lbl + "</span>" : "";
  const pills = pil(d.falhas, "falha", d.falhas === 1 ? "falha" : "falhas") +
                pil(d.avisos, "aviso", d.avisos === 1 ? "aviso" : "avisos") +
                pil(d.observacoes, "obs", d.observacoes === 1 ? "observação" : "observações");
  el("v-saude").innerHTML = anelSvg(d.indice) +
    '<div class="cs-sb"><div class="cs-st">Saúde do módulo</div><div class="cs-sp">' +
    (pills || '<span class="cs-pill"><i style="background:var(--green)"></i>tudo em ordem</span>') +
    '<span class="cs-pill"><i style="background:var(--green)"></i>' + d.ok + " de " + d.total +
    " verificações ok</span></div></div>" +
    '<span class="cs-sgo">ver detalhes →</span>';
  el("n-saude").textContent = (d.total - d.ok) || "";

  el("sd-kpis").innerHTML = [
    {c: "", l: "Índice de saúde", v: d.indice + "%", cor: corIndice(d.indice),
     f: d.indice >= 85 ? "número defensável"
        : (d.indice >= 60 ? "revisar os avisos antes de apresentar" : "há lacunas materiais")},
    {c: d.falhas ? "bad" : "good", l: "Falhas", v: d.falhas, f: "comprometem o número"},
    {c: d.avisos ? "" : "good", l: "Avisos", v: d.avisos, f: "pedem decisão ou cadastro"},
    {c: "", l: "Observações", v: d.observacoes, f: "melhoram a rastreabilidade"}
  ].map(x => '<div class="cs-kpi ' + x.c + '"><span class="l">' + x.l + "</span>" +
             '<div class="v"' + (x.cor ? ' style="color:' + x.cor + '"' : "") + ">" + x.v + "</div>" +
             '<div class="f">' + x.f + "</div></div>").join("");

  const linha = c =>
    '<div class="cs-chk' + (c.ok ? " ok" : "") + '">' +
    '<span class="d" style="background:' + (c.ok ? "var(--green)" : COR_SEV[c.severidade]) + '"></span>' +
    '<div class="t"><b>' + esc(c.titulo) + "</b><span>" + esc(c.detalhe) + "</span></div>" +
    (c.quantidade ? '<span class="q">' + c.quantidade + "</span>" : "") +
    (c.ok ? "" : '<span class="a" data-ir="' + c.alvo + '">resolver →</span>') + "</div>";
  const bloco = (tit, arr) => arr.length ? '<div class="cs-grp">' + tit + "</div>" + arr.map(linha).join("") : "";
  const v = d.verificacoes;
  el("sd-lista").innerHTML =
    bloco("Falhas", v.filter(c => !c.ok && c.severidade === "falha")) +
    bloco("Avisos", v.filter(c => !c.ok && c.severidade === "aviso")) +
    bloco("Observações", v.filter(c => !c.ok && c.severidade === "obs")) +
    bloco("Em ordem", v.filter(c => c.ok));
}

/* ═══════════ MODAIS ═══════════ */
function abrirModal(id){ el(id).style.display = "flex"; }
function fecharModal(id){ el(id).style.display = "none"; }

const campo = (id, lbl, val, tipo, hint, full) =>
  '<div class="' + (full ? "full" : "") + '"><label for="' + id + '">' + lbl + "</label>" +
  '<input class="form-input" id="' + id + '" type="' + (tipo || "text") + '"' +
  (tipo === "number" ? ' step="any"' : "") + ' value="' + esc(val == null ? "" : val) + '">' +
  (hint ? '<span class="hint">' + hint + "</span>" : "") + "</div>";

const seletor = (id, lbl, opts, val, hint, full) =>
  '<div class="' + (full ? "full" : "") + '"><label for="' + id + '">' + lbl + "</label>" +
  '<select class="form-input" id="' + id + '">' + opts.map(o =>
    '<option value="' + esc(o[0]) + '"' + (String(val) === String(o[0]) ? " selected" : "") + ">" +
    esc(o[1]) + "</option>").join("") + "</select>" +
  (hint ? '<span class="hint">' + hint + "</span>" : "") + "</div>";

let EDIT = null;

function editarLancamento(id){
  const novo = id == null;
  const l = novo ? {natureza: "cogs", categoria: META.categorias[1], subcategoria: "",
                    descricao: "", tipo_calculo: "montante", moeda: "BRL", valor_moeda: 0,
                    horas: 0, perfil_hora: "eng", aliquota: 0, procedencia: "estimativa",
                    confianca: "media", observacao: "", realizado_valor_brl: null}
                 : ATUAL.lancamentos.find(x => x.id === id);
  if(!l) return;
  EDIT = {id: id, novo: novo};
  el("ml-tit").textContent = novo ? "Novo lançamento" : "Editar lançamento";
  el("ml-del").style.display = novo ? "none" : "";

  el("ml-body").innerHTML =
    seletor("ml-nat", "Natureza", META.naturezas.map(n => [n, META.naturezas_labels[n]]),
            l.natureza, "Define se o custo amortiza sobre o volume") +
    seletor("ml-cat", "Categoria", META.categorias.map(c => [c, c]), l.categoria) +
    campo("ml-sub", "Subcategoria", l.subcategoria, "text", "Nome que aparece na linha", true) +
    campo("ml-desc", "Descrição", l.descricao, "text", "", true) +
    seletor("ml-tipo", "Forma de cálculo", [
      ["montante", "Montante fixo"], ["horas", "Horas × custo/hora"],
      ["percentual", "% sobre o FOB"], ["reserva", "% sobre a exposição cambial"]
    ], l.tipo_calculo) +
    seletor("ml-moeda", "Moeda", META.moedas.map(m => [m, m]), l.moeda) +
    campo("ml-valor", "Valor na moeda", l.valor_moeda, "number", "Convertido pela taxa travada") +
    campo("ml-horas", "Horas", l.horas, "number") +
    seletor("ml-perfil", "Perfil de hora", META.perfis_hora.map(p => [p, META.perfis_hora_labels[p]]), l.perfil_hora) +
    campo("ml-aliq", "Alíquota (%)", l.aliquota, "number") +
    seletor("ml-proc", "Procedência", META.procedencias.map(p => [p, META.procedencias_labels[p]]),
            l.procedencia, "De onde veio o número") +
    seletor("ml-conf", "Confiança", META.confiancas.map(c => [c, c]), l.confianca) +
    campo("ml-real", "Realizado (R$)", l.realizado_valor_brl, "number", "Preencher quando a DI chegar") +
    '<div class="full"><label for="ml-obs">Observação</label>' +
    '<textarea class="form-input" id="ml-obs">' + esc(l.observacao || "") + "</textarea></div>";

  const visib = () => {
    const t = el("ml-tipo").value;
    const mostra = (id, cond) => el(id).parentElement.style.display = cond ? "" : "none";
    mostra("ml-valor", t === "montante");
    mostra("ml-moeda", t === "montante");
    mostra("ml-horas", t === "horas");
    mostra("ml-perfil", t === "horas");
    mostra("ml-aliq", t === "percentual" || t === "reserva");
  };
  el("ml-tipo").addEventListener("change", visib);
  visib();
  abrirModal("mo-lanc");
  setTimeout(() => el("ml-sub").focus(), 60);
}

async function salvarLancamento(){
  const corpo = {
    natureza: el("ml-nat").value, categoria: el("ml-cat").value,
    subcategoria: el("ml-sub").value.trim(), descricao: el("ml-desc").value.trim(),
    tipo_calculo: el("ml-tipo").value, moeda: el("ml-moeda").value,
    valor_moeda: el("ml-valor").value || 0, horas: el("ml-horas").value || 0,
    perfil_hora: el("ml-perfil").value, aliquota: el("ml-aliq").value || 0,
    procedencia: el("ml-proc").value, confianca: el("ml-conf").value,
    observacao: el("ml-obs").value.trim(),
    realizado_valor_brl: el("ml-real").value === "" ? null : el("ml-real").value
  };
  if(!corpo.subcategoria){ toast("Informe a subcategoria."); return; }
  try{
    if(EDIT.novo)
      await api("/custos/api/composicoes/" + ATUAL.id + "/lancamentos",
                {method: "POST", body: JSON.stringify(corpo)});
    else
      await api("/custos/api/lancamentos/" + EDIT.id, {method: "PUT", body: JSON.stringify(corpo)});
    fecharModal("mo-lanc");
    toast("Lançamento «" + corpo.subcategoria + "» " + (EDIT.novo ? "criado" : "atualizado") + ".");
    await recarregar();
  }catch(e){ toast(e.message); }
}

async function excluirLancamento(id){
  const l = ATUAL.lancamentos.find(x => x.id === id);
  if(!l || !confirm("Excluir o lançamento «" + l.subcategoria + "»?")) return;
  try{
    await api("/custos/api/lancamentos/" + id, {method: "DELETE"});
    toast("Lançamento «" + l.subcategoria + "» excluído.");
    await recarregar();
  }catch(e){ toast(e.message); }
}

function editarComposicao(c){
  const novo = !c;
  c = c || {produto: "", sku: "", fornecedor: "", tipo: "OEM", incoterm: "FOB",
            moeda_base: "USD", status: "rascunho", valor_fob: 0, qtd_invoice: 1,
            volume_projetado: 1, preco_venda: "", custo_hora_engenharia: 0,
            custo_hora_producao: 0, reserva_cambial_pct: 10,
            taxa_planejamento: REF.valor || 1, taxa_planejamento_justificativa: "",
            taxa_realizada: "", di_numero: "", di_data: "", projeto_id: ""};
  EDIT = {comp: novo ? null : c.id};
  el("mc-tit").textContent = novo ? "Nova composição" : "Editar composição";
  el("mc-body").innerHTML =
    campo("mc-produto", "Produto", c.produto, "text", "", true) +
    campo("mc-sku", "SKU", c.sku) +
    campo("mc-forn", "Fornecedor", c.fornecedor) +
    seletor("mc-proj", "Projeto", [["", "— sem projeto —"]].concat(
      META.projetos.map(p => [p.id, p.nome])), c.projeto_id || "") +
    seletor("mc-tipo", "Tipo", META.tipos.map(t => [t, t]), c.tipo,
            "OEM tem NRE; Revenda não") +
    seletor("mc-status", "Status", META.status.map(s => [s, s]), c.status) +
    seletor("mc-incoterm", "Incoterm", META.incoterms.map(i => [i, i]), c.incoterm) +
    seletor("mc-moeda", "Moeda base", META.moedas_estrangeiras.map(m => [m, m]), c.moeda_base) +
    campo("mc-fob", "FOB unitário", c.valor_fob, "number", "na moeda base") +
    campo("mc-qtd", "Qtd. na invoice", c.qtd_invoice, "number") +
    campo("mc-vol", "Volume projetado", c.volume_projetado, "number", "amortiza o NRE") +
    campo("mc-preco", "Preço de venda (R$)", c.preco_venda, "number") +
    campo("mc-ceng", "Custo hora engenharia", c.custo_hora_engenharia, "number", "R$/h") +
    campo("mc-cprod", "Custo hora produção", c.custo_hora_producao, "number", "R$/h") +
    campo("mc-res", "Reserva cambial (%)", c.reserva_cambial_pct, "number",
          "só sobre exposição em moeda estrangeira") +
    campo("mc-taxa", "Taxa de planejamento", c.taxa_planejamento, "number",
          "travada: é a única que orça") +
    campo("mc-taxareal", "Taxa realizada (DI)", c.taxa_realizada, "number") +
    campo("mc-di", "Número da DI", c.di_numero) +
    campo("mc-didata", "Data da DI", c.di_data, "date") +
    '<div class="full"><label for="mc-just">Justificativa da taxa travada</label>' +
    '<textarea class="form-input" id="mc-just">' + esc(c.taxa_planejamento_justificativa || "") +
    "</textarea><span class=\"hint\">Por que esta taxa, e não a de mercado. É o que torna a folga " +
    "uma decisão registrada em vez de um número herdado.</span></div>";
  abrirModal("mo-comp");
  setTimeout(() => el("mc-produto").focus(), 60);
}

async function salvarComposicao(){
  const corpo = {
    produto: el("mc-produto").value.trim(), sku: el("mc-sku").value.trim(),
    fornecedor: el("mc-forn").value.trim(), projeto_id: el("mc-proj").value || null,
    tipo: el("mc-tipo").value, status: el("mc-status").value,
    incoterm: el("mc-incoterm").value, moeda_base: el("mc-moeda").value,
    valor_fob: el("mc-fob").value || 0, qtd_invoice: el("mc-qtd").value || 1,
    volume_projetado: el("mc-vol").value || 1,
    preco_venda: el("mc-preco").value === "" ? null : el("mc-preco").value,
    custo_hora_engenharia: el("mc-ceng").value || 0,
    custo_hora_producao: el("mc-cprod").value || 0,
    reserva_cambial_pct: el("mc-res").value || 0,
    taxa_planejamento: el("mc-taxa").value,
    taxa_realizada: el("mc-taxareal").value === "" ? null : el("mc-taxareal").value,
    di_numero: el("mc-di").value.trim(), di_data: el("mc-didata").value,
    taxa_planejamento_justificativa: el("mc-just").value.trim()
  };
  if(!corpo.produto){ toast("Informe o produto."); return; }
  try{
    if(EDIT.comp){
      await api("/custos/api/composicoes/" + EDIT.comp, {method: "PUT", body: JSON.stringify(corpo)});
      toast("Composição atualizada.");
      await carregarTudo();
      await abrirComposicao(EDIT.comp);
    } else {
      const nova = await api("/custos/api/composicoes", {method: "POST", body: JSON.stringify(corpo)});
      toast("Composição «" + nova.produto + "» criada com a estrutura padrão.");
      await carregarTudo();
      await abrirComposicao(nova.id);
    }
    fecharModal("mo-comp");
  }catch(e){ toast(e.message); }
}

function registrarCotacao(){
  el("mt-body").innerHTML =
    seletor("mt-moeda", "Moeda", META.moedas_estrangeiras.map(m => [m, m]), "USD", "", true) +
    campo("mt-data", "Data", new Date().toISOString().slice(0, 10), "date", "", true) +
    campo("mt-valor", "Valor", "", "number", "quantos reais por 1 unidade da moeda", true);
  abrirModal("mo-cot");
  setTimeout(() => el("mt-valor").focus(), 60);
}

async function salvarCotacao(){
  try{
    await api("/custos/api/cotacoes", {method: "POST", body: JSON.stringify({
      moeda: el("mt-moeda").value, data: el("mt-data").value, valor: el("mt-valor").value
    })});
    fecharModal("mo-cot");
    toast("Cotação registrada.");
    await carregarTudo();
    await renderCotacoes();
  }catch(e){ toast(e.message); }
}

/* ═══════════ AÇÕES DE TOPO ═══════════ */
const BTN_EXPORT =
  '<button class="btn btn-ghost btn-sm" data-exp="csv">⭳ CSV</button>' +
  '<button class="btn btn-ghost btn-sm" data-exp="xlsx">⭳ XLSX</button>' +
  '<button class="btn btn-ghost btn-sm" data-exp="print">🖨 Relatório</button>';

function montarAcoes(){
  const nova = '<button class="btn btn-primary btn-sm" data-nova="1">+ Nova composição</button>';
  el("acoes-visao").innerHTML = BTN_EXPORT + nova;
  el("acoes-comps").innerHTML = BTN_EXPORT + nova;
  el("acoes-comparativo").innerHTML = BTN_EXPORT;
  el("acoes-saude").innerHTML = '<button class="btn btn-ghost btn-sm" data-exp="print">🖨 Relatório</button>';
  el("acoes-cotacoes").innerHTML =
    '<button class="btn btn-ghost btn-sm" data-cot="manual">Registrar manual</button>' +
    '<button class="btn btn-primary btn-sm" data-cot="sync">Sincronizar agora</button>';
}

function filtrosQuery(){
  const p = new URLSearchParams();
  const q = el("f-busca").value.trim(), s = el("f-status").value, t = el("f-tipo").value;
  if(q) p.set("q", q);
  if(s) p.set("status", s);
  if(t) p.set("tipo", t);
  return p.toString() ? "?" + p.toString() : "";
}

async function exportar(fmt){
  if(fmt === "print"){ window.print(); return; }
  const url = fmt === "csv"
    ? "/custos/api/export/composicoes.csv" + filtrosQuery()
    : "/custos/api/export/custos.xlsx" + filtrosQuery();
  try{
    // O nome datado vem do servidor (Content-Disposition); o fallback é só rede de segurança.
    await baixarDoServidor(url, "custos." + fmt);
    toast("Exportação concluída.");
  }catch(e){ toast(e.message); }
}

/* ═══════════ CARGA ═══════════ */
async function carregarTudo(){
  try{
    if(!META){
      META = await api("/custos/api/meta");
      el("f-status").innerHTML = '<option value="">Todos os status</option>' +
        META.status.map(s => '<option value="' + s + '">' + s + "</option>").join("");
      el("f-tipo").innerHTML = '<option value="">Todos os tipos</option>' +
        META.tipos.map(t => '<option value="' + t + '">' + t + "</option>").join("");
      montarAcoes();
    }
    const d = await api("/custos/api/composicoes" + filtrosQuery());
    COMPS = d.composicoes;
    REF.valor = d.referencia;
    REF.data = d.referencia_data;
    REF.porMoeda = d.referencias || {};
    renderVisao();
    renderLista();
    await renderSaude();
  }catch(e){
    toast(e.message);
  }
}

async function recarregar(){
  const id = ATUAL && ATUAL.id;
  await carregarTudo();
  if(id) await abrirComposicao(id);
}

/* ═══════════ EVENTOS ═══════════ */
document.addEventListener("click", async ev => {
  const nav = ev.target.closest(".nav-item[data-page]");
  if(nav){
    const p = nav.dataset.page;
    irPara(p);
    if(p === "comparativo") renderComparativo().catch(e => toast(e.message));
    if(p === "cotacoes") renderCotacoes().catch(e => toast(e.message));
    if(p === "saude") renderSaude().catch(e => toast(e.message));
    return;
  }
  const fechar = ev.target.closest("[data-fechar]");
  if(fechar){ fecharModal(fechar.dataset.fechar); return; }
  const exp = ev.target.closest("[data-exp]");
  if(exp){ exportar(exp.dataset.exp); return; }
  if(ev.target.closest("[data-nova]")){ editarComposicao(null); return; }
  if(ev.target.closest("#b-editar-comp")){ editarComposicao(ATUAL); return; }
  if(ev.target.closest("#b-novo-lanc")){ editarLancamento(null); return; }
  const cot = ev.target.closest("[data-cot]");
  if(cot){
    if(cot.dataset.cot === "manual") registrarCotacao();
    else {
      cot.disabled = true;
      try{
        const r = await api("/custos/api/cotacoes/sincronizar", {method: "POST"});
        toast(typeof r.resultado === "string" ? r.resultado
              : Object.entries(r.resultado).map(([m, v]) => m + ": " + v).join(" · "));
        await carregarTudo();
        await renderCotacoes();
      }catch(e){ toast(e.message); }
      cot.disabled = false;
    }
    return;
  }
  const ir = ev.target.closest("[data-ir]");
  if(ir){
    const alvo = ir.dataset.ir === "composicoes" ? "composicoes" : "cotacoes";
    irPara(alvo);
    if(alvo === "cotacoes") renderCotacoes().catch(e => toast(e.message));
    return;
  }
  const ed = ev.target.closest("[data-ed]");
  if(ed){ editarLancamento(+ed.dataset.ed); return; }
  const rm = ev.target.closest("[data-rm]");
  if(rm){ excluirLancamento(+rm.dataset.rm); return; }
  const strip = ev.target.closest("#v-saude");
  if(strip){ irPara("saude"); renderSaude().catch(e => toast(e.message)); return; }
  const tr = ev.target.closest("tr.click");
  if(tr && tr.dataset.id){ abrirComposicao(+tr.dataset.id).catch(e => toast(e.message)); }
});

document.addEventListener("change", async ev => {
  const ap = ev.target.closest("[data-ap]");
  if(ap){
    try{
      await api("/custos/api/lancamentos/" + ap.dataset.ap,
                {method: "PUT", body: JSON.stringify({aplicavel: ap.checked})});
      await recarregar();
    }catch(e){ toast(e.message); ap.checked = !ap.checked; }
  }
});

// Alíquota edita direto na linha — mas só grava no blur, para não disparar uma
// requisição por tecla digitada.
document.addEventListener("blur", async ev => {
  const a = ev.target.closest && ev.target.closest("[data-aliq]");
  if(!a) return;
  const l = ATUAL && ATUAL.lancamentos.find(x => x.id === +a.dataset.aliq);
  if(!l || String(l.aliquota) === String(a.value)) return;
  try{
    await api("/custos/api/lancamentos/" + a.dataset.aliq,
              {method: "PUT", body: JSON.stringify({aliquota: a.value})});
    await recarregar();
  }catch(e){ toast(e.message); }
}, true);

document.addEventListener("keydown", ev => {
  if(ev.key === "Escape") document.querySelectorAll(".modal-overlay").forEach(m => m.style.display = "none");
});

el("ml-save").addEventListener("click", salvarLancamento);
el("ml-del").addEventListener("click", () => { const id = EDIT.id; fecharModal("mo-lanc"); excluirLancamento(id); });
el("mc-save").addEventListener("click", salvarComposicao);
el("mt-save").addEventListener("click", salvarCotacao);

let _tf = null;
["f-busca", "f-status", "f-tipo"].forEach(id =>
  el(id).addEventListener("input", () => {
    clearTimeout(_tf);
    _tf = setTimeout(() => carregarTudo(), 280);
  }));

document.addEventListener("DOMContentLoaded", () => {
  if(typeof initTheme === "function") initTheme();
  carregarTudo();
});
if(document.readyState !== "loading"){
  if(typeof initTheme === "function") initTheme();
  carregarTudo();
}
