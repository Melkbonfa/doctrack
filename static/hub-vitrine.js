/* hub-vitrine.js — comportamento do hub (/hub) e dos sub-hubs (/hub/<área>).

   Uso (ver templates/hub.html e templates/subhub.html):

     var tela = DTHub.iniciar({
       tipo: 'area' | 'mod',            // cartão de área (hub) ou de módulo (sub-hub)
       itens: [{k, cor, nome, mini, url, icone, cena, desc, chips}],
       chaveUltimo: 'dt_hub_ultimo:pde',// lembra o último escolhido
       padrao: 'docs',                  // escolhido na primeira visita (se visível)
       rotuloCta: function(item){...},
       dica: 'no módulo',
       entrar: function(item, url, chip){...},
       dados: function(item, resumo){ return {stats, pend, badge}; }
     });
     tela.atualizar(resumo);            // quando /api/hub/resumo responder

   Passar o mouse só acende o cartão (CSS). O clique troca a vitrine; clicar
   de novo no escolhido — ou duplo clique, Enter, ou o botão — entra. */
(function(){
'use strict';

var NS = 'http://www.w3.org/2000/svg';
var reduzido = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
var fino = window.matchMedia && matchMedia('(hover:hover) and (pointer:fine)').matches;

function $(s){ return document.querySelector(s); }
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function svg(inner, sw){ return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' + (sw || 1.6) + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + inner + '</svg>'; }
function rep(n, f){ var s = ''; for(var i = 0; i < n; i++) s += f(i); return s; }
var ls = {
  get: function(k){ try { return localStorage.getItem(k); } catch(e){ return null; } },
  set: function(k, v){ try { localStorage.setItem(k, v); } catch(e){} }
};

/* "#a855f7" → "168,85,247" — cor de área que ainda não tem classe no CSS. */
function rgb(hex){
  var h = String(hex || '').replace('#', '');
  if(h.length === 3) h = h.replace(/./g, '$&$&');
  var n = parseInt(h, 16);
  return isNaN(n) || h.length !== 6 ? '34,211,238' : [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(',');
}
function corInline(hex){ return '--m:' + hex + ';--m-rgb:' + rgb(hex) + ';--m-ink:' + hex + ';--m2:' + hex; }

/* ── Cenas (SVG 480×240), decorativas ─────────────────────────────────── */
var CENAS = {
  equip: function(){
    var tr = ['M183 90H140V50H64','M183 110H44','M183 130H120V172H64','M183 150H150V206H96',
              'M297 90H350V46H416','M297 110H436','M297 130H340V180H412','M297 150H322V210H380',
              'M230 63V26H176','M250 63V30H306','M230 177V220','M250 177V214H292'];
    var pads = [[64,50],[44,110],[64,172],[96,206],[416,46],[436,110],[412,180],[380,210],[176,26],[306,30],[230,220],[292,214]];
    var pul = [[0,0,2.6],[2,1.6,2.4],[1,.9,3],[5,.4,2.8],[6,1.2,3.2],[4,2,2.6],[8,.6,2.2],[11,1.8,2.4]];
    return '<g class="ln dim">' + tr.map(function(d){ return '<path d="' + d + '"/>'; }).join('') + '</g>' +
      '<g class="ln">' + pads.map(function(p){ return '<circle class="pap" cx="' + p[0] + '" cy="' + p[1] + '" r="4.5"/>'; }).join('') + '</g>' +
      '<g filter="url(#hv-glow)">' + pul.map(function(p){ return '<path class="pulse" pathLength="100" style="--d:' + p[1] + 's;--t:' + p[2] + 's" d="' + tr[p[0]] + '"/>'; }).join('') + '</g>' +
      '<rect class="ln dim pap" x="84" y="105" width="22" height="10" rx="2"/><rect class="ln dim pap" x="376" y="105" width="22" height="10" rx="2"/>' +
      '<circle class="ln dim spin" cx="240" cy="120" r="82" stroke-dasharray="2 8"/>' +
      '<path class="ln" d="M183 90h12M183 110h12M183 130h12M183 150h12M285 90h12M285 110h12M285 130h12M285 150h12M210 63v12M230 63v12M250 63v12M270 63v12M210 165v12M230 165v12M250 165v12M270 165v12"/>' +
      '<rect class="ln pap" x="195" y="75" width="90" height="90" rx="10"/>' +
      '<rect class="ln core" x="214" y="94" width="52" height="52" rx="6" filter="url(#hv-glow)"/>' +
      '<path class="ln dim" d="M226 120h28M240 106v28"/>' +
      '<text class="tx" x="26" y="231">PCB-01 · REV B</text>';
  },
  docs: function(){
    var sheet = '<rect class="ln pap" width="120" height="150" rx="10"/>' +
      '<rect x="14" y="16" width="50" height="7" rx="3.5" class="acc" opacity=".85"/>' +
      '<rect x="86" y="13" width="20" height="13" rx="4" class="sft"/>' +
      [92,78,86,60,82].map(function(w, i){ return '<rect x="14" y="' + (40 + i * 14) + '" width="' + w + '" height="5" rx="2.5" class="sft2"/>'; }).join('') +
      '<path d="M14 124h92" class="ln dim"/><rect x="14" y="132" width="34" height="5" rx="2.5" class="sft2"/>';
    return '<defs><linearGradient id="hv-g-scan" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--m);stop-opacity:0"/><stop offset="1" style="stop-color:var(--m);stop-opacity:.42"/></linearGradient>' +
      '<clipPath id="hv-c-doc"><rect width="120" height="150" rx="10"/></clipPath></defs>' +
      '<g transform="translate(116 54) rotate(-10 60 75)" opacity=".5"><g class="flt" style="--fd:5.6s;--fdl:-1.2s">' + sheet + '</g></g>' +
      '<g transform="translate(244 48) rotate(8 60 75)" opacity=".6"><g class="flt" style="--fd:6.4s;--fdl:-3s">' + sheet + '</g></g>' +
      '<g transform="translate(180 42)"><g class="flt" style="--fd:4.8s;--fdl:0s">' + sheet +
        '<g clip-path="url(#hv-c-doc)"><g class="scan"><rect y="-24" width="120" height="24" fill="url(#hv-g-scan)"/><rect y="-1" width="120" height="2" class="acc"/></g></g>' +
        '<g transform="translate(94 122)"><g class="stamp" filter="url(#hv-glow)"><circle r="15" class="ln pap" stroke-width="1.8"/><path d="M-6 0l4 4 8-8" class="ln" stroke-width="2.4"/></g></g>' +
      '</g></g>' +
      [[150,0],[200,1.4],[330,.7],[360,2.1],[118,2.8]].map(function(p){ return '<circle class="pt acc" cx="' + p[0] + '" cy="212" r="1.8" style="--d:' + p[1] + 's"/>'; }).join('') +
      '<text class="tx" x="26" y="231">LISTA MESTRA</text>';
  },
  ent: function(){
    var rows = [[96,128,.9],[150,150,.62],[244,104,.3],[310,96,.12],[352,70,0]];
    return '<g class="ln" style="opacity:.14">' + rep(8, function(i){ return '<path d="M' + (100 + i * 42) + ' 40V206"/>'; }) + '</g>' +
      '<g class="tx">' + rep(8, function(i){ return '<text x="' + (100 + i * 42) + '" y="31" text-anchor="middle">S' + (i + 1) + '</text>'; }) + '</g>' +
      rows.map(function(r, i){
        var x = r[0], w = r[1], y = 52 + i * 32, cx = x + w + 11, cy = y + 7;
        return '<circle class="ln dim sft" cx="68" cy="' + cy + '" r="8"/>' +
          '<rect class="ln dim2 sft" x="' + x + '" y="' + y + '" width="' + w + '" height="14" rx="7"/>' +
          (r[2] ? '<rect class="acc gf" x="' + x + '" y="' + y + '" width="' + w + '" height="14" rx="7" style="--p:' + r[2] + ';--dl:' + (i * .12).toFixed(2) + 's"/>' : '') +
          '<path class="ln ' + (i === 0 ? 'ms' : 'dim') + '" d="M' + cx + ' ' + (cy - 6) + 'l6 6-6 6-6-6z"/>';
      }).join('') +
      '<path class="ln" d="M268 40V204" stroke-dasharray="4 4"/>' +
      '<rect x="248" y="208" width="40" height="16" rx="8" class="acc"/><text x="268" y="219.5" text-anchor="middle" class="tx-ink">HOJE</text>';
  },
  missoes: function(){
    function card(x, y){
      return '<g transform="translate(' + x + ' ' + y + ')"><rect class="ln dim2 pap" width="100" height="28" rx="6"/>' +
        '<rect x="10" y="8" width="52" height="4" rx="2" class="sft2"/><rect x="10" y="16" width="32" height="4" rx="2" class="sft"/>' +
        '<circle cx="86" cy="14" r="6" class="sft"/></g>';
    }
    var cols = [[62,'A FAZER'],[182,'FAZENDO'],[302,'FEITO']];
    return cols.map(function(c){
        return '<rect class="ln col" x="' + c[0] + '" y="44" width="116" height="180" rx="10"/>' +
          '<text class="tx" x="' + (c[0] + 8) + '" y="34">' + c[1] + '</text>';
      }).join('') +
      [54,90,126].map(function(y){ return card(70, y); }).join('') +
      [54,90].map(function(y){ return card(190, y); }).join('') +
      [54,90,126].map(function(y){ return card(310, y); }).join('') +
      '<g transform="translate(70 162)"><g class="mv" filter="url(#hv-glow)"><rect class="ln pap" width="100" height="28" rx="6" stroke-width="1.8"/>' +
        '<rect x="10" y="8" width="52" height="4" rx="2" class="acc"/><rect x="10" y="16" width="32" height="4" rx="2" class="sft2"/>' +
        '<circle cx="86" cy="14" r="6" class="acc"/></g></g>';
  },
  custos: function(){
    var h = [54,70,62,88,80,104,96,118,128];
    var d = h.map(function(v, i){ return (i ? 'L' : 'M') + (80 + i * 40) + ' ' + (200 - v); }).join(' ');
    return '<path class="ln dim" d="M56 200H432"/>' +
      '<path class="ln dim" d="M56 64H432" stroke-dasharray="5 5"/><text class="tx" x="432" y="56" text-anchor="end">PREÇO-ALVO</text>' +
      h.map(function(v, i){ return '<rect class="cb ' + (i === 8 ? 'acc' : 'ln dim2 sft') + '" x="' + (68 + i * 40) + '" y="' + (200 - v) + '" width="24" height="' + v + '" rx="4" style="--i:' + i + '"/>'; }).join('') +
      '<path class="ln trend" d="' + d + '" pathLength="100" filter="url(#hv-glow)"/>' +
      '<circle class="acc dotp" cx="400" cy="72" r="4"/>' +
      '<g class="tx">' + rep(9, function(i){ return '<text x="' + (80 + i * 40) + '" y="218" text-anchor="middle">V' + (i + 1) + '</text>'; }) + '</g>';
  },
  tempos: function(){
    var cx = 148, cy = 118, dias = ['SEG','TER','QUA','QUI','SEX'];
    var blocos = [[[0,46],[52,62]], [[0,58],[64,40]], [[0,50],[56,54]], [[0,44],[50,58]], [[0,40],[46,62]]];
    var hoje = Math.min(Math.max((new Date().getDay() + 6) % 7, 0), 4);
    return '<circle class="ln dim" cx="' + cx + '" cy="' + cy + '" r="94" stroke-dasharray="1 6"/>' +
      '<circle class="ln arc" cx="' + cx + '" cy="' + cy + '" r="86" pathLength="100" transform="rotate(-90 ' + cx + ' ' + cy + ')" filter="url(#hv-glow)"/>' +
      '<circle class="ln dim2 pap" cx="' + cx + '" cy="' + cy + '" r="78"/>' +
      rep(12, function(i){ return '<path class="ln' + (i % 3 ? ' dim' : '') + '" d="M' + cx + ' ' + (cy - 74) + 'v' + (i % 3 ? 6 : 10) + '" transform="rotate(' + (i * 30) + ' ' + cx + ' ' + cy + ')"/>'; }) +
      '<path class="ln" d="M' + cx + ' ' + cy + 'V' + (cy - 38) + '" stroke-width="3" transform="rotate(186 ' + cx + ' ' + cy + ')"/>' +
      '<path class="ln hand" d="M' + cx + ' ' + (cy + 10) + 'V' + (cy - 62) + '"/>' +
      '<circle class="acc" cx="' + cx + '" cy="' + cy + '" r="4.5"/>' +
      '<text class="tx" x="' + cx + '" y="231" text-anchor="middle">HOJE</text>' +
      '<text class="tx" x="272" y="44">SEMANA</text>' +
      dias.map(function(dia, i){
        var y = 60 + i * 30, bl = i < hoje ? blocos[i] : i === hoje ? [[0,84]] : [];
        return '<text class="tx' + (i === hoje ? ' tx-a' : '') + '" x="272" y="' + (y + 10) + '">' + dia + '</text>' +
          '<rect class="trk" x="306" y="' + y + '" width="134" height="12" rx="6"/>' +
          bl.map(function(b){ return '<rect class="' + (i === hoje ? 'acc tf' : 'sft2') + '" x="' + (306 + b[0]) + '" y="' + y + '" width="' + b[1] + '" height="12" rx="6"/>'; }).join('');
      }).join('');
  },
  fluxos: function(){
    var xs = [72,184,296,408], y = 100;
    var ic = ['<path d="M-7 7v-4l11-11 4 4-11 11z"/>',
              '<path d="M-10 0c4-6 16-6 20 0-4 6-16 6-20 0z"/><circle r="3"/>',
              '<path d="M-8 0l5 6 11-12"/>',
              '<path d="M0 6V-7M-5-2l5-5 5 5M-8 10h16"/>'];
    var lb = [['ESCRITA','autora'],['DIAGRAMAÇÃO','diagramador'],['REVISÃO','autora'],['APROVADO','lista mestra']];
    return xs.slice(0, 3).map(function(x){ return '<path class="ln dim" d="M' + (x + 27) + ' ' + y + 'H' + (x + 85) + '"/><path class="ln flow" d="M' + (x + 27) + ' ' + y + 'H' + (x + 85) + '"/>'; }).join('') +
      xs.map(function(x, i){
        return '<g transform="translate(' + x + ' ' + y + ')">' +
          '<circle r="25" class="pap"/>' +
          '<g class="lit n' + (i + 1) + '"><circle r="33" class="ln" opacity=".5"/><circle r="25" class="acc" opacity=".22"/></g>' +
          '<circle r="25" class="ln"/><g class="ln" stroke-width="1.8">' + ic[i] + '</g></g>' +
          '<text class="tx" x="' + x + '" y="' + (y + 50) + '" text-anchor="middle">' + lb[i][0] + '</text>' +
          '<text class="tx tx-d" x="' + x + '" y="' + (y + 64) + '" text-anchor="middle">' + lb[i][1] + '</text>';
      }).join('') +
      '<g transform="translate(' + (xs[0] - 10) + ' 38)"><g class="tok" filter="url(#hv-glow)"><path class="ln pap" d="M0 0h14l6 6v18H0z" stroke-width="1.6"/><path class="ln" d="M14 0v6h6M4 12h12M4 17h8"/></g></g>';
  },

  /* Áreas (hub). Equipamentos: aparelho em prancha técnica. */
  pde: function(){
    var onda = 'M160 106H176L181 94L188 120L194 100L199 108H213L218 98L224 114L229 108H241L245 100L250 114L254 108H264';
    return '<g transform="translate(84 112)"><g class="spin" style="--sd:18s"><circle class="ln dim" r="20" stroke-width="5" stroke-dasharray="5 5.47"/></g><circle class="ln pap" r="9"/></g>' +
      '<g transform="translate(62 170)"><g class="spin" style="--sd:12s;animation-direction:reverse"><circle class="ln dim" r="12" stroke-width="4" stroke-dasharray="3.5 3.04"/></g><circle class="ln pap" r="5"/></g>' +
      '<path class="ln dim" d="M140 40H340M140 34v12M340 34v12"/><text class="tx" x="240" y="30" text-anchor="middle">200 MM</text>' +
      '<path class="ln dim" d="M360 58V182M354 58h12M354 182h12"/><text class="tx" x="370" y="124">124</text>' +
      '<rect class="ln pap" x="140" y="58" width="200" height="124" rx="12"/>' +
      '<rect class="ln dim2 sft" x="156" y="74" width="112" height="64" rx="6"/>' +
      '<g class="ln" style="opacity:.12">' + rep(4, function(i){ return '<path d="M' + (178 + i * 22) + ' 78V134"/>'; }) + '<path d="M160 90H264M160 122H264"/></g>' +
      '<path class="ln dim" d="' + onda + '"/>' +
      '<path class="sweep" pathLength="100" d="' + onda + '" filter="url(#hv-glow)"/>' +
      '<g transform="translate(304 94)"><circle class="ln pap" r="14"/><g class="spin" style="--sd:9s"><path class="ln" d="M0 0V-9" stroke-width="2"/><circle r="9" fill="none"/></g></g>' +
      '<g transform="translate(304 134)"><circle class="ln pap" r="10"/><path class="ln dim" d="M0 0L5 -6" stroke-width="2"/></g>' +
      rep(4, function(i){ return '<rect x="' + (156 + i * 29) + '" y="152" width="22" height="10" rx="3" class="' + (i === 0 ? 'acc' : 'sft2') + '"/>'; }) +
      '<circle class="acc dotp" cx="326" cy="70" r="3"/>' +
      '<rect class="ln dim pap" x="160" y="182" width="22" height="7" rx="2"/><rect class="ln dim pap" x="298" y="182" width="22" height="7" rx="2"/>' +
      '<text class="tx" x="26" y="231">EQ · REV B</text>';
  },
  /* Reagentes: dupla hélice de DNA (desenhada por DNA abaixo). */
  pdr: function(){
    var bases = 'ATGCGTAC';
    return '<g class="hv-dna" transform="rotate(-12 240 114)"></g>' +
      [[90,0,4.2],[150,1.6,3.6],[300,.8,4.4],[352,2.4,3.8],[410,1.2,4]].map(function(b){ return '<circle class="bolha acc" cx="' + b[0] + '" cy="206" r="1.8" style="--d:' + b[1] + 's;--bt:' + b[2] + 's"/>'; }).join('') +
      '<g class="tx tx-d">' + rep(8, function(i){ return '<text x="' + (316 + i * 15) + '" y="231">' + bases[i] + '</text>'; }) + '</g>' +
      '<text class="tx" x="26" y="231">REAGENTES · SEQ</text>';
  },
  /* Inovação: ideias chegando de vários pontos e acendendo a lâmpada. */
  inov: function(){
    var c = [240, 86];
    var nos = [[70,52],[56,148],[126,204],[150,28],[332,26],[410,52],[424,146],[356,204]];
    var linhas = nos.map(function(n){
      var dx = c[0] - n[0], dy = c[1] - n[1], d = Math.sqrt(dx * dx + dy * dy), r = 46;
      return 'M' + n[0] + ' ' + n[1] + 'L' + (c[0] - dx / d * r).toFixed(1) + ' ' + (c[1] - dy / d * r).toFixed(1);
    });
    var rot = {0:'IDEIA', 5:'PROTÓTIPO', 7:'PATENTE'};
    return '<g class="ln dim">' + linhas.map(function(d){ return '<path d="' + d + '"/>'; }).join('') + '</g>' +
      '<g filter="url(#hv-glow)">' + linhas.map(function(d, i){ return '<path class="pulse" pathLength="100" style="--d:' + (i * .45).toFixed(2) + 's;--t:' + (2.4 + (i % 3) * .4).toFixed(1) + 's" d="' + d + '"/>'; }).join('') + '</g>' +
      nos.map(function(n, i){
        return '<circle class="ln pap" cx="' + n[0] + '" cy="' + n[1] + '" r="' + (i % 3 === 0 ? 7 : 5) + '"/>' +
          (i % 3 === 0 ? '<circle class="acc" cx="' + n[0] + '" cy="' + n[1] + '" r="2.5"/>' : '') +
          (rot[i] ? '<text class="tx tx-d" x="' + n[0] + '" y="' + (n[1] + (n[1] > 120 ? 20 : -12)) + '" text-anchor="middle">' + rot[i] + '</text>' : '');
      }).join('') +
      '<g transform="translate(240 86)"><g class="spin" style="--sd:40s"><circle class="ln dim" r="58" stroke-dasharray="2 9"/></g></g>' +
      '<circle class="core" cx="240" cy="80" r="22" filter="url(#hv-glow)"/>' +
      '<g transform="translate(180 39) scale(5)"><path class="ln pap" vector-effect="non-scaling-stroke" d="M12 2.5a6.5 6.5 0 0 0-3.8 11.8c.5.4.8 1 .8 1.6V16h6v-.1c0-.6.3-1.2.8-1.6A6.5 6.5 0 0 0 12 2.5z"/></g>' +
      '<circle class="core" cx="240" cy="80" r="12"/>' +
      '<path class="ln" d="M232 119V102l4-6 4 6 4-6 4 6v17" stroke-width="1.4"/>' +
      '<path class="ln" d="M225 129h30M230 146.5h20"/>' +
      '<text class="tx" x="26" y="231">INOVAÇÃO · PIPELINE</text>';
  }
};

/* ── DNA girando ─────────────────────────────────────────────────────────
   Duas fitas senoidais defasadas meia volta; a fase anda com o tempo e a
   hélice gira no próprio eixo. O cosseno da fase é a profundidade: o trecho
   da frente engrossa, clareia e passa para a camada de cima. */
function criaDNA(g, deveRodar){
  var X0 = 46, X1 = 434, CY = 114, A = 42, PER = 156, PASSO = 6, ESP = 13, VOLTA = 7000, TAU = Math.PI * 2;
  function mk(t, c){ var e = document.createElementNS(NS, t); if(c) e.setAttribute('class', c); return e; }
  var tras = mk('g'), meio = mk('g'), frente = mk('g');
  g.appendChild(tras); g.appendChild(meio); g.appendChild(frente);
  var segs = [], pares = [], x;
  [0, 1].forEach(function(s){
    for(x = X0; x < X1; x += PASSO){ var el = mk('line', 'f' + (s + 1)); tras.appendChild(el); segs.push({ el:el, s:s, x:x }); }
  });
  for(x = X0 + ESP / 2; x < X1; x += ESP){
    var p = { x:x, b1:mk('line', 'b1'), b2:mk('line', 'b2'), n1:mk('circle', 'n1'), n2:mk('circle', 'n2') };
    meio.appendChild(p.b1); meio.appendChild(p.b2); tras.appendChild(p.n1); tras.appendChild(p.n2);
    pares.push(p);
  }
  function borda(x){ return Math.max(0, Math.min(1, (x - X0) / 54, (X1 - x) / 54)); }
  function fita(s, x, fase){ var th = x / PER * TAU + fase + (s ? Math.PI : 0); return [CY + A * Math.sin(th), Math.cos(th)]; }
  function camada(el, z){ var alvo = z > 0 ? frente : tras; if(el.parentNode !== alvo) alvo.appendChild(el); }
  function at(el, o){ for(var k in o) el.setAttribute(k, o[k]); }
  function quadro(t){
    var fase = t / VOLTA * TAU;
    segs.forEach(function(sg){
      var a = fita(sg.s, sg.x, fase), b = fita(sg.s, sg.x + PASSO, fase), z = (a[1] + b[1]) / 2, k = (z + 1) / 2;
      at(sg.el, { x1:sg.x, y1:a[0].toFixed(1), x2:sg.x + PASSO, y2:b[0].toFixed(1),
        'stroke-width':(1.2 + 2 * k).toFixed(2), opacity:((.2 + .8 * k) * borda(sg.x + PASSO / 2)).toFixed(3) });
      camada(sg.el, z);
    });
    pares.forEach(function(p){
      var a = fita(0, p.x, fase), b = fita(1, p.x, fase), m = ((a[0] + b[0]) / 2).toFixed(1), e = borda(p.x);
      at(p.b1, { x1:p.x, y1:a[0].toFixed(1), x2:p.x, y2:m, 'stroke-width':2, opacity:(.85 * e).toFixed(3) });
      at(p.b2, { x1:p.x, y1:m, x2:p.x, y2:b[0].toFixed(1), 'stroke-width':2, opacity:(.85 * e).toFixed(3) });
      [[p.n1, a], [p.n2, b]].forEach(function(n){
        var k = (n[1][1] + 1) / 2;
        at(n[0], { cx:p.x, cy:n[1][0].toFixed(1), r:(1.8 + 1.8 * k).toFixed(2), opacity:((.3 + .7 * k) * e).toFixed(3) });
        camada(n[0], n[1][1]);
      });
    });
  }
  var raf = 0, tempo = 0, ultimo = 0;
  function rodando(){ return !reduzido && !document.hidden && deveRodar(); }
  function laco(agora){
    raf = 0;
    if(ultimo) tempo += Math.min(agora - ultimo, 50);
    ultimo = agora; quadro(tempo);
    if(rodando()) raf = requestAnimationFrame(laco); else ultimo = 0;
  }
  quadro(0);
  return function atualiza(){
    if(rodando()){ if(!raf) raf = requestAnimationFrame(laco); }
    else if(raf){ cancelAnimationFrame(raf); raf = 0; ultimo = 0; }
  };
}

/* ── Malha reta de fundo: 20px, linha forte a cada 5 ───────────────────── */
function montaMalha(el){
  var PASSO = 20;
  function desenha(){
    var w = el.clientWidth, h = el.clientHeight;
    var cx = w / 2, cy = h * 0.48, R = Math.sqrt(cx * cx + Math.pow(Math.max(cy, h - cy), 2));
    var n = Math.ceil(R / PASSO), lim = n * PASSO, out = '';
    for(var i = -n; i <= n; i++){
      var c = i * PASSO, cls = 'ml' + (i % 5 === 0 ? ' forte' : '');
      out += '<path class="' + cls + '" d="M' + (cx + c).toFixed(1) + ' ' + (cy - lim).toFixed(1) + 'V' + (cy + lim).toFixed(1) + '"/>' +
             '<path class="' + cls + '" d="M' + (cx - lim).toFixed(1) + ' ' + (cy + c).toFixed(1) + 'H' + (cx + lim).toFixed(1) + '"/>';
    }
    el.innerHTML = '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" focusable="false">' + out + '</svg>';
  }
  desenha();
  var tm;
  window.addEventListener('resize', function(){ clearTimeout(tm); tm = setTimeout(desenha, 150); });
}

/* ── Peso da vitrine ─────────────────────────────────────────────────────
   O lado sob o mouse afunda: a posição segue o mouse por uma mola (chega com
   atraso e balança de leve) e volta ao plano ao sair. Mede o .hv-stage, que
   não inclina, para a medida não tremer junto. Só com mouse. */
function montaPeso(stage, vit){
  var T = { x:0, y:0, vx:0, vy:0, tx:0, ty:0, mx:0, my:0, tmx:0, tmy:0, dentro:false, raf:0 };
  var INCL_X = 12, INCL_Y = 7, MOLA = 0.05, AMORTECE = 0.76;
  var body = document.body;
  function agenda(){ if(!T.raf) T.raf = requestAnimationFrame(passo); }
  function passo(){
    T.raf = 0;
    T.vx = (T.vx + (T.tx - T.x) * MOLA) * AMORTECE;
    T.vy = (T.vy + (T.ty - T.y) * MOLA) * AMORTECE;
    T.x += T.vx; T.y += T.vy;
    T.mx += (T.tmx - T.mx) * 0.06; T.my += (T.tmy - T.my) * 0.06;
    var resto = Math.abs(T.tx - T.x) + Math.abs(T.ty - T.y) + Math.abs(T.vx) + Math.abs(T.vy);
    var restoFundo = Math.abs(T.tmx - T.mx) + Math.abs(T.tmy - T.my);
    if(!T.dentro && resto < 0.0005){
      /* Assentou: tira o transform para o texto voltar a ficar nítido. */
      T.x = T.y = T.vx = T.vy = 0; vit.style.transform = '';
    } else {
      vit.style.transform = 'perspective(1400px) rotateX(' + (-T.y * INCL_X).toFixed(3) + 'deg) rotateY(' + (T.x * INCL_Y).toFixed(3) + 'deg)';
    }
    stage.style.setProperty('--px', T.x.toFixed(4));
    stage.style.setProperty('--py', T.y.toFixed(4));
    body.style.setProperty('--mx', T.mx.toFixed(4));
    body.style.setProperty('--my', T.my.toFixed(4));
    if(resto >= 0.0005 || restoFundo >= 0.0005) agenda();
  }
  if(reduzido) return;
  stage.addEventListener('pointermove', function(e){
    if(e.pointerType !== 'mouse') return;
    var r = stage.getBoundingClientRect();
    T.tx = Math.min(.5, Math.max(-.5, (e.clientX - r.left) / r.width - .5));
    T.ty = Math.min(.5, Math.max(-.5, (e.clientY - r.top) / r.height - .5));
    vit.style.setProperty('--gx', Math.round(e.clientX - r.left) + 'px');
    vit.style.setProperty('--gy', Math.round(e.clientY - r.top) + 'px');
    if(!T.dentro){ T.dentro = true; vit.classList.add('pesando'); }
    agenda();
  });
  stage.addEventListener('pointerleave', function(){
    T.dentro = false; T.tx = T.ty = 0; vit.classList.remove('pesando'); agenda();
  });
  document.addEventListener('pointermove', function(e){
    if(e.pointerType !== 'mouse') return;
    T.tmx = e.clientX / innerWidth - .5; T.tmy = e.clientY / innerHeight - .5;
    agenda();
  });
}

/* ── Tela ─────────────────────────────────────────────────────────────── */
function iniciar(cfg){
  var body = document.body, rail = $('#hv-rail'), stage = $('#hv-stage'), vit = $('#hv-vitrine');
  var info = $('#hv-info'), cena = $('#hv-scene'), luzes = $('#hv-luzes');
  var itens = cfg.itens || [], sel = null, resumo = null, dna = null;

  montaMalha($('#hv-malha'));
  document.addEventListener('visibilitychange', function(){
    body.classList.toggle('hv-pausado', document.hidden);
    if(dna) dna();
  });

  if(!itens.length){ body.classList.add('sem-itens'); $('#hv-vazio').hidden = false; return { atualizar:function(){} }; }

  function item(k){ for(var i = 0; i < itens.length; i++) if(itens[i].k === k) return itens[i]; return null; }
  function corAttr(it){ return it.corInline ? ' style="' + corInline(it.corInline) + '"' : ''; }

  /* Cenas: uma por item, só a visível anima. */
  cena.insertAdjacentHTML('beforeend', itens.map(function(it){
    var f = CENAS[it.cena] || CENAS.docs;
    return '<svg class="scn ' + (it.cor || '') + '" data-scn="' + esc(it.k) + '"' + corAttr(it) + ' viewBox="0 0 480 240" preserveAspectRatio="xMidYMid meet" focusable="false" aria-hidden="true">' + f() + '</svg>';
  }).join(''));
  var g = cena.querySelector('.hv-dna');
  if(g){
    var dono = g.closest('.scn').dataset.scn;
    dna = criaDNA(g, function(){ return sel === dono; });
  }
  if(luzes){
    luzes.innerHTML = itens.map(function(it){ return '<div class="luz ' + (it.cor || '') + '" data-luz="' + esc(it.k) + '"' + corAttr(it) + '></div>'; }).join('');
  }

  rail.classList.add(cfg.tipo === 'area' ? 'areas' : 'mods');
  function desenhaRail(){
    rail.innerHTML = itens.map(function(it){
      var d = cfg.dados(it, resumo) || {}, b = d.badge;
      var miolo = cfg.tipo === 'area'
        ? '<span class="txt"><span class="nm">' + esc(it.nome) + '</span><span class="mini">' + esc(it.mini || '') + '</span></span>'
        : '<span class="nm">' + esc(it.nome) + '</span>';
      return '<li><a class="hv-card ' + cfg.tipo + ' ' + (it.cor || '') + (it.k === sel ? ' sel' : '') + '"' + corAttr(it) +
        ' href="' + esc(it.url) + '" data-k="' + esc(it.k) + '" aria-label="' + esc(it.nome + (b && b.rotulo ? ', ' + b.rotulo : '')) + '">' +
        '<span class="ico" aria-hidden="true">' + svg(it.icone) + '</span>' + miolo +
        (b && b.n ? '<span class="hv-badge' + (b.alerta ? ' alerta' : '') + '" aria-hidden="true">' + b.n + '</span>' : '') + '</a></li>';
    }).join('');
  }

  function statHTML(s){
    var cls = 'v' + (s.alerta ? ' alerta' : '') + (s.hl ? ' hl' : '') + (s.carregando ? ' carregando' : '');
    return '<div class="hv-stat"><span class="' + cls + '">' + esc(s.v) + '</span><span class="l">' + esc(s.l) + '</span>' +
      (s.p != null ? '<span class="bar"><i style="width:' + Math.max(0, Math.min(100, s.p)) + '%"></i></span>' : '') + '</div>';
  }

  function pinta(k, animar){
    var it = item(k); if(!it) return;
    var d = cfg.dados(it, resumo) || {};
    vit.className = 'hv-vitrine ' + (it.cor || '') + (vit.classList.contains('pesando') ? ' pesando' : '');
    vit.setAttribute('style', it.corInline ? corInline(it.corInline) : '');
    stage.className = 'hv-stage ' + (it.cor || '');
    stage.style.cssText = (it.corInline ? corInline(it.corInline) + ';' : '') +
      '--px:' + (stage.style.getPropertyValue('--px') || 0) + ';--py:' + (stage.style.getPropertyValue('--py') || 0);
    $('#v-ico').innerHTML = svg(it.icone, 1.8);
    $('#v-name').textContent = it.nome;
    $('#v-desc').textContent = it.desc || '';
    var stats = d.stats || [], st = $('#v-stats');
    st.style.setProperty('--n', Math.max(1, stats.length));
    st.innerHTML = stats.map(statHTML).join('');
    var at = $('#v-atalhos');
    if(at){
      var chips = it.chips || [];
      at.hidden = !it.temChips;
      $('#v-chips').innerHTML = chips.length ? chips.map(function(c, i){
        return '<a class="hv-chip" href="' + esc(c.url) + '" data-i="' + i + '">' + svg(c.icone, 1.8) + esc(c.label) + '</a>';
      }).join('') : '<span class="nada">Nenhum módulo liberado para o seu perfil.</span>';
    }
    var p = d.pend, pe = $('#v-pend');
    pe.className = 'hv-pend' + (!p ? ' vazio' : p.alerta ? ' alerta' : p.neutro ? ' neutro' : '');
    /* p.html é montado pelas próprias telas, só com números e textos fixos. */
    pe.innerHTML = '<span class="led" aria-hidden="true"></span><span>' + (p ? p.html : esc(d.vazio || 'Nada esperando por você aqui.')) + '</span>';
    $('#v-cta-txt').textContent = cfg.rotuloCta(it);
    $('#v-cta').setAttribute('href', it.url);
    if(animar){ info.classList.remove('swap'); void info.offsetWidth; info.classList.add('swap'); }
  }

  function seleciona(k, inicial){
    if(!inicial && k === sel) return;
    sel = k;
    rail.querySelectorAll('.hv-card').forEach(function(a){ a.classList.toggle('sel', a.dataset.k === k); });
    cena.querySelectorAll('.scn').forEach(function(s){ s.classList.toggle('on', s.dataset.scn === k); });
    if(luzes) luzes.querySelectorAll('.luz').forEach(function(l){ l.classList.toggle('on', l.dataset.luz === k); });
    pinta(k, !inicial);
    if(dna) dna();
  }

  function entra(k, url, chip){
    var it = item(k); if(!it) return;
    ls.set(cfg.chaveUltimo, k);
    var a = rail.querySelector('.hv-card[data-k="' + k + '"]');
    if(a){ a.classList.remove('go'); void a.offsetWidth; a.classList.add('go'); }
    cfg.entrar(it, url || it.url, chip || null);
  }

  /* Eventos: hover/foco só acendem (CSS); clique seleciona; de novo, entra. */
  rail.addEventListener('click', function(e){
    var a = e.target.closest('.hv-card'); if(!a) return;
    if(e.ctrlKey || e.metaKey || e.shiftKey) return;   // nova aba: deixa o link agir
    e.preventDefault();
    if(sel === a.dataset.k) entra(a.dataset.k); else seleciona(a.dataset.k);
  });
  rail.addEventListener('keydown', function(e){
    var cards = Array.prototype.slice.call(rail.querySelectorAll('.hv-card'));
    var i = cards.indexOf(document.activeElement); if(i < 0) return;
    var j = e.key === 'ArrowRight' ? (i + 1) % cards.length : e.key === 'ArrowLeft' ? (i - 1 + cards.length) % cards.length :
            e.key === 'Home' ? 0 : e.key === 'End' ? cards.length - 1 : null;
    if(j != null){ e.preventDefault(); cards[j].focus(); }
  });
  document.addEventListener('keydown', function(e){
    if(e.target !== body) return;
    if(e.key === 'ArrowRight' || e.key === 'ArrowLeft'){
      e.preventDefault();
      var cards = Array.prototype.slice.call(rail.querySelectorAll('.hv-card'));
      var i = cards.findIndex(function(a){ return a.dataset.k === sel; });
      cards[(i + (e.key === 'ArrowRight' ? 1 : -1) + cards.length) % cards.length].focus();
    } else if(e.key === 'Enter'){ entra(sel); }
  });
  $('#v-cta').addEventListener('click', function(e){
    if(e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault(); entra(sel);
  });
  var chipsEl = $('#v-chips');
  if(chipsEl) chipsEl.addEventListener('click', function(e){
    var c = e.target.closest('.hv-chip'); if(!c) return;
    if(e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    var it = item(sel), chip = it && it.chips[+c.dataset.i];
    if(chip) entra(sel, chip.url, chip);
  });
  $('#v-hint').textContent = fino ? 'ou clique duas vezes ' + cfg.dica : 'ou toque de novo ' + cfg.dica;

  montaPeso(stage, vit);

  var ult = ls.get(cfg.chaveUltimo);
  var inicial = item(ult) ? ult : item(cfg.padrao) ? cfg.padrao : itens[0].k;
  desenhaRail();
  seleciona(inicial, true);

  return {
    atualizar: function(r){ resumo = r; desenhaRail(); pinta(sel, false); }
  };
}

/* ── Números (GET /api/hub/resumo) ────────────────────────────────────────
   `r` é a resposta, ou null enquanto carrega. Bloco ausente na resposta =
   perfil sem acesso ou falha no servidor: a vitrine fica sem números. */
function num(v){ return v == null ? '—' : Number(v).toLocaleString('pt-BR'); }
function horas(s){
  if(s == null) return '—';
  var m = Math.floor(s / 60), h = Math.floor(m / 60);
  return h + 'h' + ('0' + (m % 60)).slice(-2);
}
function plural(n, um, varios){ return n + ' ' + (n === 1 ? um : varios); }
function bloco(r, k){
  if(!r) return { carregando:true };
  var m = r.modulos || {};
  return m[k] || null;
}
function tile(v, l, extra){
  var t = { v:v, l:l };
  for(var k in (extra || {})) t[k] = extra[k];
  if(v === '—') t.carregando = true;
  return t;
}

var DESC_MODULO = {
  equip:   'Cadastro dos equipamentos do P&D: fichas técnicas, categorias e a situação de cada um.',
  docs:    'Lista mestra do P&D: elaboração, revisão e aprovação de documentos.',
  ent:     'Projetos e entregáveis da área, com o avanço de cada escopo.',
  missoes: 'Quadro de cartões da equipe: o que está com você e o que já venceu.',
  custos:  'Formação de custo dos produtos: composições, versões e câmbio.',
  tempos:  'Apontamento de horas por projeto e atividade, com cronômetro.',
  fluxos:  'Fluxos de revisão de manuais e ITs: quem escreve, diagrama e revisa.'
};

/* Um módulo do sub-hub. `slug` = área (Projetos e Fluxos são recortados por ela). */
function dadosModulo(k, slug, r){
  var b = bloco(r, k);
  if(!b) return { stats:[], pend:null, vazio:'Sem números deste módulo para o seu perfil.' };
  var c = !!b.carregando, ano = new Date().getFullYear();
  if(k === 'equip'){
    return { stats:[tile(num(b.total), 'equipamentos'), tile(num(b.ativos), 'ativos'), tile(num(b.categorias), 'categorias')] };
  }
  if(k === 'docs'){
    var mp = { stats:[tile(num(b.total), 'documentos'), tile(num(b.andamento), 'em andamento'),
                      tile(num(b.atrasados), 'com prazo vencido', { alerta:b.atrasados > 0 })] };
    if(b.meus){
      mp.pend = { alerta:b.meus_atrasados > 0, html:'<b>' + plural(b.meus, 'documento', 'documentos') + '</b> com você como responsável' +
        (b.meus_atrasados ? ' · <b class="r">' + plural(b.meus_atrasados, 'atrasado', 'atrasados') + '</b>' : '') };
      mp.badge = { n:b.meus, alerta:b.meus_atrasados > 0, rotulo:plural(b.meus, 'documento seu', 'documentos seus') };
    }
    return mp;
  }
  if(k === 'ent'){
    var e = c ? {} : (b[slug] || { projetos:0, avanco_medio:0, atrasados:0 });
    var me = { stats:[tile(num(e.projetos), 'projetos ativos'),
                      tile(e.avanco_medio == null ? '—' : e.avanco_medio + '%', 'avanço médio', { p:e.avanco_medio }),
                      tile(num(e.atrasados), 'entregáveis atrasados', { alerta:e.atrasados > 0 })] };
    if(e.atrasados){
      me.pend = { alerta:true, html:'<b class="r">' + plural(e.atrasados, 'entregável atrasado', 'entregáveis atrasados') + '</b> nos projetos da área' };
      me.badge = { n:e.atrasados, alerta:true, rotulo:plural(e.atrasados, 'entregável atrasado', 'entregáveis atrasados') };
    }
    return me;
  }
  if(k === 'missoes'){
    var mm = { stats:[tile(num(b.meus), 'cartões seus', { hl:b.meus > 0 }),
                      tile(num(b.meus_atrasados), 'atrasados', { alerta:b.meus_atrasados > 0 }),
                      tile(num(b.equipe_andamento), 'em andamento na equipe')] };
    if(b.meus){
      mm.pend = { alerta:b.meus_atrasados > 0, html:'<b>' + plural(b.meus, 'cartão', 'cartões') + '</b> seus' +
        (b.meus_atrasados ? ' · <b class="r">' + plural(b.meus_atrasados, 'atrasado', 'atrasados') + '</b>' : '') };
      mm.badge = { n:b.meus, alerta:b.meus_atrasados > 0, rotulo:plural(b.meus, 'cartão seu', 'cartões seus') };
    }
    return mm;
  }
  if(k === 'custos'){
    return { stats:[tile(num(b.composicoes), 'composições'), tile(num(b.vigentes), 'vigentes'), tile(num(b.rascunhos), 'em rascunho')] };
  }
  if(k === 'tempos'){
    var mt = { stats:[tile(horas(b.hoje_s), 'hoje'), tile(horas(b.semana_s), 'na semana'), tile(num(b.projetos_semana), 'projetos na semana')] };
    if(!c){
      mt.pend = b.em_curso ? { html:'Cronômetro rodando agora' }
              : { neutro:true, html:b.ultimo_fim ? 'Cronômetro parado · último apontamento às ' + esc(b.ultimo_fim) : 'Nenhum apontamento hoje' };
    }
    return mt;
  }
  if(k === 'fluxos'){
    var com = c ? null : ((b.comigo || {})[slug] || 0);
    var mf = { stats:[tile(num(com), 'com você', { hl:com > 0 }), tile(num(b.andamento), 'em andamento'),
                      tile(num(b.concluidos_ano), 'aprovados em ' + ano)] };
    if(com){
      mf.pend = { html:'<b>' + plural(com, 'revisão', 'revisões') + '</b> esperando você' };
      mf.badge = { n:com, rotulo:plural(com, 'revisão esperando você', 'revisões esperando você') };
    }
    return mf;
  }
  return { stats:[] };
}

/* Uma área do hub: soma o que espera pela pessoa e o retrato dos projetos. */
var DESC_AREA = {
  pde:  'Engenharia de equipamentos: cadastro, documentos, projetos e a rotina da equipe.',
  pdr:  'Desenvolvimento de reagentes, no app próprio da área: painel, documentos e cadernos.',
  inov: 'Projetos de inovação da empresa e os fluxos de revisão da área.'
};
function dadosArea(slug, r){
  if(slug === 'pdr') return { stats:[], pend:{ neutro:true, html:'O painel e os documentos ficam no app de Reagentes.' } };
  var carregando = !r;
  var m = (r && r.modulos) || {}, partes = [], soma = 0, atraso = false, stats = [];
  var comigo = m.fluxos ? ((m.fluxos.comigo || {})[slug] || 0) : 0;
  if(slug === 'pde'){
    if(m.docs && m.docs.meus){ soma += m.docs.meus; atraso = atraso || m.docs.meus_atrasados > 0; partes.push('<b>' + plural(m.docs.meus, 'documento', 'documentos') + '</b>'); }
    if(m.missoes && m.missoes.meus){ soma += m.missoes.meus; atraso = atraso || m.missoes.meus_atrasados > 0; partes.push('<b>' + plural(m.missoes.meus, 'cartão', 'cartões') + '</b>'); }
  }
  if(comigo){ soma += comigo; partes.push('<b>' + plural(comigo, 'revisão', 'revisões') + '</b>'); }

  if(slug === 'pde' && (carregando || m.docs || m.missoes || m.fluxos))
    stats.push(tile(carregando ? '—' : num(soma), 'pendências suas', { hl:soma > 0 && !atraso, alerta:atraso }));
  if(slug !== 'pde' && (carregando || m.fluxos))
    stats.push(tile(carregando ? '—' : num(comigo), 'com você', { hl:comigo > 0 }));
  var e = m.ent ? (m.ent[slug] || { projetos:0, avanco_medio:0, atrasados:0 }) : null;
  if(e){
    stats.push(tile(num(e.projetos), 'projetos ativos'));
    stats.push(tile(e.avanco_medio + '%', 'avanço médio', { p:e.avanco_medio }));
  } else if(slug === 'pde' && m.docs){
    stats.push(tile(num(m.docs.andamento), 'documentos em andamento'));
    if(m.equip) stats.push(tile(num(m.equip.ativos), 'equipamentos ativos'));
  }
  var out = { stats:stats.slice(0, 3) };
  if(soma){
    out.pend = { alerta:atraso, html:partes.join(' · ') + ' esperando você' + (atraso ? ' · <b class="r">com atraso</b>' : '') };
    out.badge = { n:soma, alerta:atraso, rotulo:plural(soma, 'pendência sua', 'pendências suas') };
  } else if(e && e.atrasados){
    out.pend = { alerta:true, html:'<b class="r">' + plural(e.atrasados, 'entregável atrasado', 'entregáveis atrasados') + '</b> nos projetos da área' };
  }
  out.vazio = carregando ? 'Carregando…' : 'Nada esperando por você nesta área.';
  return out;
}

window.DTHub = { iniciar: iniciar, svg: svg, esc: esc,
                 dadosModulo: dadosModulo, dadosArea: dadosArea,
                 DESC_MODULO: DESC_MODULO, DESC_AREA: DESC_AREA };
})();
