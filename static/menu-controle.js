/* menu-controle.js — o menu de controle único de todas as telas.

   Par de static/menu-controle.css. Os botões só chamam o que a tela já tem:
   toggleTheme() e doLogout() (common.js), o "Atualizar dados" do menu lateral
   e o #logout do hub. Sem sessão (tela de login) o menu não aparece.

   Abre ao passar o mouse e fecha um instante depois que ele sai; no toque,
   um toque abre e tocar fora fecha. O movimento é uma mola quadro a quadro
   (anima mesmo com as animações do Windows desligadas). */
(function(){
'use strict';
if(window.__menuControle) return;
window.__menuControle = true;

var body = document.body, raiz = null, quemEra = '', G = null;
var AREAS = { pde:'P&D Equipamentos', pdr:'P&D Reagentes', inov:'Inovação' };
var IC = {
  volta:'<path d="M15 18l-6-6 6-6"/>',
  atualiza:'<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 4v5h-5"/>',
  lua:'<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  sol:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  config:'<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  sair:'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/>',
  senha:'<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3M14 9l2 2"/>',
  seta:'<path d="M6 9l6 6 6-6"/>'
};
function svg(n, cls){ return '<svg viewBox="0 0 24 24" aria-hidden="true"' + (cls ? ' class="' + cls + '"' : '') + '>' + IC[n] + '</svg>'; }
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){ return { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' }[c]; }); }

function usuario(){ try { return JSON.parse(localStorage.getItem('doctrack_user') || '{}') || {}; } catch(e){ return {}; } }
function temSessao(){ try { return !!localStorage.getItem('doctrack_token'); } catch(e){ return false; } }
function claro(){ return body.classList.contains('theme-light'); }
function iniciais(nome){
  var p = String(nome || '?').replace(/\(.*?\)/g, '').trim().split(/\s+/);
  return ((p[0] || '?')[0] + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase();
}

/* Para onde o "voltar" leva: do módulo para os módulos da área; do sub-hub
   e das configurações para as áreas; no hub não há para onde voltar. */
function contexto(){
  var cam = location.pathname.replace(/\/+$/, '') || '/', area = '';
  try { area = new URLSearchParams(location.search).get('area') || sessionStorage.getItem('dt_area') || ''; } catch(e){}
  if(cam === '/pdr' || cam.indexOf('/pdr/') === 0) area = 'pdr';      // Reagentes é só da área PDR
  area = /^[a-z]+$/.test(area) ? area : 'pde';
  if(cam === '/hub') return {};
  if(cam.indexOf('/hub/') === 0 || cam === '/config') return { volta:'/hub', rotulo:'Áreas' };
  return { volta:'/hub/' + area, rotulo:'Módulos', titulo:'Módulos de ' + (AREAS[area] || area.toUpperCase()) };
}
function podeConfig(u){
  var el = document.getElementById('config-link');
  return el ? !el.hidden : u.role === 'admin';
}

var ACOES = {
  atualiza:function(){
    var b = [].filter.call(document.querySelectorAll('.sidebar-footer .sidebar-refresh'), function(x){ return /Atualizar/i.test(x.textContent); })[0];
    if(b) b.click(); else location.reload();
  },
  tema:function(){
    if(typeof window.toggleTheme === 'function') window.toggleTheme();
    else body.classList.toggle('theme-light');
  },
  /* Trocar a senha pede a senha atual de novo, na tela de login: a sessão é
     encerrada antes, e o e-mail segue no sessionStorage só para preencher. */
  senha:function(){
    var ir = function(){
      try {
        sessionStorage.setItem('dt_trocar_senha', usuario().email || '');
        localStorage.removeItem('doctrack_token');
        localStorage.removeItem('doctrack_refresh');
        localStorage.removeItem('doctrack_user');
      } catch(e){}
      location.href = '/';
    };
    if(window.DT_AUTH) window.DT_AUTH.encerrar().then(ir); else ir();
  },
  sair:function(){
    var l = document.getElementById('logout');          // hub e sub-hub têm a saída deles
    if(l) l.click(); else if(typeof window.doLogout === 'function') window.doLogout();
  }
};

function item(ac, ico, rotulo, extra){
  return '<button type="button" class="vtm-it ' + (extra || '') + '" data-ac="' + ac + '" title="' + esc(rotulo) + '" aria-label="' + esc(rotulo) + '">' + svg(ico) + '<span>' + esc(rotulo) + '</span></button>';
}
function link(href, ico, rotulo, extra, titulo){
  return '<a class="vtm-it ' + (extra || '') + '" href="' + esc(href) + '" title="' + esc(titulo || rotulo) + '">' + svg(ico) + '<span>' + esc(rotulo) + '</span></a>';
}

function monta(){
  if(G && G.raf) cancelAnimationFrame(G.raf);
  G = null;
  if(raiz){ raiz.remove(); raiz = null; }
  var u = usuario(), c = contexto(), h = '';
  quemEra = u.email || '';
  raiz = document.createElement('nav');
  raiz.className = 'vtm';
  raiz.setAttribute('aria-label', 'Controles');

  h += '<div class="vtm-gaveta"><div class="vtm-gaveta-in">';
  if(c.volta) h += link(c.volta, 'volta', c.rotulo, 'vtm-volta', c.titulo) + '<i class="vtm-sep"></i>';
  h += item('atualiza', 'atualiza', 'Atualizar', 'so-ico') + item('tema', claro() ? 'sol' : 'lua', 'Tema', 'tema so-ico');
  if(podeConfig(u)) h += link('/config', 'config', 'Configurações', 'so-ico');
  h += item('senha', 'senha', 'Trocar senha', 'so-ico');
  h += '<i class="vtm-sep"></i>' + item('sair', 'sair', 'Sair', 'sair') + '<i class="vtm-sep"></i></div></div>' +
    '<button type="button" class="vtm-it vtm-chip" data-ac="abre" aria-expanded="false" title="Menu">' +
      '<span class="vtm-quem"><span class="vtm-av">' + esc(iniciais(u.nome)) + '</span><span><b>' + esc(u.nome || 'Sem nome') + '</b><small>' + esc(u.role || '') + '</small></span></span>' +
      svg('seta', 'seta') + '</button>';
  raiz.innerHTML = h;
  raiz.hidden = !temSessao();

  var espera = 0;
  raiz.addEventListener('pointerenter', function(e){ if(e.pointerType === 'mouse'){ clearTimeout(espera); abre(true); } });
  raiz.addEventListener('pointerleave', function(e){ if(e.pointerType === 'mouse'){ clearTimeout(espera); espera = setTimeout(fecha, 350); } });
  raiz.addEventListener('focusin', function(){ clearTimeout(espera); abre(true); });
  raiz.addEventListener('focusout', function(e){ if(!raiz.contains(e.relatedTarget)) fecha(); });

  body.appendChild(raiz);
  body.classList.add('vtm-on');
  var dentro = raiz.querySelector('.vtm-gaveta-in');
  G = { p:0, v:0, alvo:0, raf:0, W:0, gav:raiz.querySelector('.vtm-gaveta'), dentro:dentro,
        its:[].slice.call(dentro.children), seta:raiz.querySelector('.vtm-chip .seta') };
  mede();
}

/* A tela reserva no topo só o espaço do botão fechado. */
function mede(){
  if(!raiz) return;
  var chip = raiz.querySelector('.vtm-chip');
  body.style.setProperty('--vtm-w', ((chip.offsetWidth + 8) || 160) + 'px');
}

/* Uma mola leva o progresso p de 0 a 1 (passa um pouco do ponto e assenta).
   A largura da gaveta acompanha p; cada item entra em cascata, primeiro o
   mais perto do botão, vindo de trás dele. */
function passo(){
  if(!G) return;
  G.raf = 0;
  G.v = (G.v + (G.alvo - G.p) * 0.10) * 0.68;
  G.p += G.v;
  var parado = Math.abs(G.alvo - G.p) < 0.001 && Math.abs(G.v) < 0.001;
  if(parado){ G.p = G.alvo; G.v = 0; }
  var p = G.p, n = G.its.length, reto = Math.min(1, Math.max(0, p));
  G.gav.style.width = Math.max(0, G.W * p).toFixed(1) + 'px';
  G.dentro.style.visibility = p > 0.01 ? 'visible' : 'hidden';
  for(var i = 0; i < n; i++){
    var atraso = 0.5 * (n - 1 - i) / Math.max(1, n - 1);
    var q = Math.min(1, Math.max(0, (p - atraso) / (1 - atraso)));
    q = q * q * (3 - 2 * q);
    G.its[i].style.opacity = q.toFixed(3);
    G.its[i].style.transform = 'translateX(' + ((1 - q) * 26).toFixed(1) + 'px) scale(' + (0.8 + 0.2 * q).toFixed(3) + ')';
  }
  G.seta.style.transform = 'rotate(' + (90 - 180 * reto).toFixed(1) + 'deg)';
  if(!parado) G.raf = requestAnimationFrame(passo);
}
function abre(sim){
  if(!raiz || !G) return;
  raiz.classList.toggle('aberto', sim);
  raiz.querySelector('.vtm-chip').setAttribute('aria-expanded', sim ? 'true' : 'false');
  G.alvo = sim ? 1 : 0;
  G.W = G.dentro.scrollWidth;
  if(!G.raf) G.raf = requestAnimationFrame(passo);
}
function fecha(){ abre(false); }

document.addEventListener('click', function(e){
  if(!raiz) return;
  if(!raiz.contains(e.target)){ fecha(); return; }
  var b = e.target.closest('[data-ac]');
  if(!b) return;
  if(b.dataset.ac === 'abre'){ abre(true); return; }   // no toque, o toque abre
  if(b.dataset.ac !== 'tema') fecha();
  if(ACOES[b.dataset.ac]) ACOES[b.dataset.ac]();
});
document.addEventListener('keydown', function(e){ if(e.key === 'Escape') fecha(); });
window.addEventListener('resize', mede);

/* O tema pode mudar por fora (outra aba): o ícone acompanha. */
new MutationObserver(function(){
  var b = raiz && raiz.querySelector('.tema svg');
  if(b) b.innerHTML = IC[claro() ? 'sol' : 'lua'];
}).observe(body, { attributes:true, attributeFilter:['class'] });

/* Entrar e sair acontecem na própria página (login do Documentos): o menu
   aparece, some ou troca de pessoa sem recarregar. */
setInterval(function(){
  if(!raiz) return;
  if((usuario().email || '') !== quemEra) monta();
  else raiz.hidden = !temSessao();
}, 1000);

monta();
})();
