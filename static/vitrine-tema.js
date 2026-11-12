/* vitrine-tema.js — comportamento do visual do hub nas telas de trabalho.

   Par de static/vitrine-tema.css; só age em páginas com `body.vt`. Três coisas:

     1. Fundo: a malha reta do hub (20px, linha forte a cada 5), que desliza de
        leve contra o mouse, e uma luz que acompanha o mouse por baixo dos
        painéis.
     2. Peso: os indicadores grandes (.kpi-ring, ou qualquer [data-vt-peso])
        inclinam sob o mouse com a mesma mola da vitrine do hub e ganham o
        brilho que segue o ponteiro.
     3. Cor por área nas telas que atendem mais de uma (body.vt-por-area).

   Desempenho, como em hub-vitrine.js: cada quadro escreve só `transform` em
   elementos com camada própria. Nada de variável CSS herdada, que recalcularia
   o estilo de uma tabela inteira a cada movimento do mouse.
   Anima mesmo com prefers-reduced-motion (ver "Movimento" em hub-vitrine.css). */
(function(){
'use strict';

var body = document.body;
if(!body || !body.classList.contains('vt')) return;

function px(v){ return v.toFixed(2) + 'px'; }
function div(cls){ var d = document.createElement('div'); d.className = cls; d.setAttribute('aria-hidden', 'true'); return d; }
/* Cada efeito pode ser desligado por uma classe no <body> (vt-sem-malha,
   vt-sem-foco, vt-sem-peso); sem a `vt`, nenhum age. */
function desligado(nome){ return !body.classList.contains('vt') || body.classList.contains('vt-sem-' + nome); }

/* ── Cor por área ─────────────────────────────────────────────────────────
   Cadernos é a mesma tela para Reagentes e para Equipamentos: a cor é a da
   área de onde a pessoa veio (mesma regra de static/cadernos.js). */
if(body.classList.contains('vt-por-area')){
  var area = '';
  try { area = new URLSearchParams(location.search).get('area') || sessionStorage.getItem('dt_area') || ''; } catch(e){}
  area = String(area || 'pdr').toLowerCase();
  if(/^[a-z]+$/.test(area)) body.classList.add('a-' + area);
}

/* ── Malha reta de fundo: 20px, linha forte a cada 5 (igual à do hub) ──── */
function montaMalha(el){
  var PASSO = 20;
  function desenha(){
    var w = el.clientWidth, h = el.clientHeight;
    if(!w || !h) return;
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

var bg = div('vt-bg'), foco = div('vt-foco'), malha = div('vt-malha');
bg.appendChild(foco); bg.appendChild(malha);
body.insertBefore(bg, body.firstChild);
montaMalha(malha);

/* A malha desliza contra o mouse; a luz vai atrás dele. As duas chegam com
   atraso (interpolação), e o laço para sozinho quando assentam. */
var F = { mx:0, my:0, tmx:0, tmy:0, fx:0, fy:0, tfx:0, tfy:0, raf:0, visto:false };
function passoFundo(){
  F.raf = 0;
  F.mx += (F.tmx - F.mx) * 0.06; F.my += (F.tmy - F.my) * 0.06;
  F.fx += (F.tfx - F.fx) * 0.12; F.fy += (F.tfy - F.fy) * 0.12;
  if(!desligado('malha')) malha.style.transform = 'translate3d(' + px(F.mx * -14) + ',' + px(F.my * -10) + ',0)';
  if(!desligado('foco')) foco.style.transform = 'translate3d(' + px(F.fx) + ',' + px(F.fy) + ',0)';
  if(Math.abs(F.tmx - F.mx) + Math.abs(F.tmy - F.my) >= 0.0005 || Math.abs(F.tfx - F.fx) + Math.abs(F.tfy - F.fy) >= 0.3)
    F.raf = requestAnimationFrame(passoFundo);
}
document.addEventListener('pointermove', function(e){
  if(e.pointerType !== 'mouse') return;
  F.tmx = e.clientX / innerWidth - 0.5; F.tmy = e.clientY / innerHeight - 0.5;
  F.tfx = e.clientX; F.tfy = e.clientY;
  if(!F.visto){ F.visto = true; F.fx = F.tfx; F.fy = F.tfy; bg.classList.add('com-mouse'); }
  if(!F.raf) F.raf = requestAnimationFrame(passoFundo);
}, { passive:true });

/* ── Peso dos indicadores ─────────────────────────────────────────────────
   O lado sob o mouse afunda: a posição segue o mouse por uma mola (chega com
   atraso e balança de leve) e volta ao plano ao sair. Só com mouse. As mesmas
   constantes da vitrine do hub; a inclinação é um pouco menor porque a peça é
   menor. O estado nasce no primeiro contato, então vale também para indicador
   criado depois pela tela. */
var SELETOR = '.kpi-ring,[data-vt-peso]';
var INCL_X = 10, INCL_Y = 8, MOLA = 0.05, AMORTECE = 0.76;
var pesos = new WeakMap();

function criaPeso(el){
  var T = { x:0, y:0, vx:0, vy:0, tx:0, ty:0, gx:0, gy:0, dentro:false, raf:0 };
  var brilho = div('vt-brilho'), rect = null;
  function garanteBrilho(){ if(brilho.parentNode !== el) el.appendChild(brilho); }
  function limpa(){ rect = null; }
  window.addEventListener('resize', limpa);
  window.addEventListener('scroll', limpa, { passive:true, capture:true });

  function agenda(){ if(!T.raf) T.raf = requestAnimationFrame(passo); }
  function passo(){
    T.raf = 0;
    T.vx = (T.vx + (T.tx - T.x) * MOLA) * AMORTECE;
    T.vy = (T.vy + (T.ty - T.y) * MOLA) * AMORTECE;
    T.x += T.vx; T.y += T.vy;
    var resto = Math.abs(T.tx - T.x) + Math.abs(T.ty - T.y) + Math.abs(T.vx) + Math.abs(T.vy);
    if(!T.dentro && resto < 0.0005){
      /* Assentou: tira o transform e a camada para o texto voltar a ficar nítido. */
      T.x = T.y = T.vx = T.vy = 0;
      el.style.transform = '';
      el.classList.remove('vt-movendo');
    } else {
      if(!el.classList.contains('vt-movendo')) el.classList.add('vt-movendo');
      el.style.transform = 'perspective(900px) rotateX(' + (-T.y * INCL_X).toFixed(3) + 'deg) rotateY(' + (T.x * INCL_Y).toFixed(3) + 'deg)';
    }
    brilho.style.transform = 'translate3d(' + px(T.gx) + ',' + px(T.gy) + ',0)';
    if(resto >= 0.0005) agenda();
  }
  el.addEventListener('pointermove', function(e){
    if(e.pointerType !== 'mouse' || desligado('peso')) return;
    /* A medida é a da peça PARADA: medir inclinada deslocaria o alvo. */
    if(!rect){ var tr = el.style.transform; el.style.transform = ''; rect = el.getBoundingClientRect(); el.style.transform = tr; }
    var lx = e.clientX - rect.left, ly = e.clientY - rect.top;
    T.tx = Math.min(0.5, Math.max(-0.5, lx / rect.width - 0.5));
    T.ty = Math.min(0.5, Math.max(-0.5, ly / rect.height - 0.5));
    T.gx = lx; T.gy = ly;
    if(!T.dentro){ T.dentro = true; garanteBrilho(); el.classList.add('vt-pesando'); }
    agenda();
  });
  el.addEventListener('pointerleave', function(){
    T.dentro = false; T.tx = T.ty = 0; el.classList.remove('vt-pesando'); agenda();
  });
}
document.addEventListener('pointerover', function(e){
  if(e.pointerType !== 'mouse' || !e.target.closest || desligado('peso')) return;
  var el = e.target.closest(SELETOR);
  if(el && !pesos.has(el)){ pesos.set(el, true); criaPeso(el); }
}, { passive:true });

})();
