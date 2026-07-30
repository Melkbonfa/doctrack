/* common.js — helpers compartilhados por todos os módulos do front.
 *
 * Estas funções estavam copiadas em app.js, config.js, entregaveis.js,
 * equipamentos.js, missoes.js, hub.html e subhub.html — sete cópias de `esc`,
 * cinco do par de tema, quatro do acesso ao token. As cópias já tinham
 * divergido entre si (duas implementações diferentes de `esc`, `applyTheme`
 * escrevendo rótulos diferentes no botão), e é assim que uma correção de
 * segurança em uma delas deixa de valer nas outras.
 *
 * Carregado ANTES de auth.js e do JS do módulo em todos os templates.
 */

// ═══ ESCAPE DE HTML ═══
// Implementação por textContent: o browser faz o escape, então não há lista de
// caracteres para esquecer. Substitui as duas versões que existiam (uma por
// regex em app.js/config.js, uma por textContent nos outros módulos).
function esc(str){
  const d = document.createElement('div');
  d.textContent = str == null ? '' : str;
  return d.innerHTML;
}

// Mínimo de caracteres de uma senha nova. Espelha auth.SENHA_MIN no backend —
// o servidor é quem decide, isto só evita a ida ao servidor para errar.
const SENHA_MIN = 8;

// ═══ NORMALIZAÇÃO DE TEXTO (busca sem acento/caixa) ═══
function norm(s){
  if(s == null) return '';
  return String(s).trim().toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');
}

// ═══ TOKEN JWT ═══
const TOKEN_KEY = 'doctrack_token';
function getToken(){ return localStorage.getItem(TOKEN_KEY) || ''; }
function setToken(t){ localStorage.setItem(TOKEN_KEY, t); }
function clearToken(){
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem('doctrack_refresh');
  localStorage.removeItem('doctrack_user');
}
// Alias histórico: entregaveis.js, equipamentos.js e missoes.js chamam token().
function token(){ return getToken(); }

// Logout local. config.js sobrescreve com uma versão que também chama
// /api/auth/logout para revogar o JTI no servidor — é a de lá que vale naquela
// página, e é o comportamento desejado.
function doLogout(){
  clearToken();
  window.location.href = '/';
}

// ═══ DOWNLOAD AUTENTICADO ═══
// Um <a href> simples não manda header, então os módulos ou punham o token na
// query (vaza no log de acesso do servidor) ou faziam o próprio fetch+blob.
// Estava copiado em app.js, consumiveis.js, equipamentos.js, entregaveis.js e
// missoes.js — cinco cópias, três delas sem revogar o object URL.
//
// O nome do arquivo vem do Content-Disposition da resposta. As cópias fixavam o
// nome no front ("Entregaveis.xlsx"), descartando o nome datado que o servidor
// já montava: os exports se sobrescreviam na pasta de Downloads.
function nomeDoContentDisposition(res, fallback){
  const cd = res.headers.get('Content-Disposition') || '';
  // filename*=UTF-8''… tem precedência sobre filename="…" (RFC 6266), e é a
  // forma que o Flask usa quando o nome tem acento.
  let m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if(m){ try{ return decodeURIComponent(m[1].trim()); }catch(e){ /* cai no filename simples */ } }
  m = /filename="?([^";\n]+)"?/i.exec(cd);
  return m ? m[1].trim() : fallback;
}

// Salva uma resposta já obtida. Separado do fetch de propósito: app.js baixa
// pelo apiFetch, que renova o token no 401 — se este helper fizesse o próprio
// fetch, o export seria o único ponto do módulo sem essa renovação.
async function salvarResposta(res, fallback){
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = href;
  a.download = nomeDoContentDisposition(res, fallback);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

// Atalho para os módulos que não têm wrapper de fetch próprio. Lança em erro de
// rede ou HTTP — quem chama decide a mensagem. Checar res.ok importa: sem isso
// um 401 baixa o corpo de erro JSON com o nome do arquivo esperado.
async function baixarDoServidor(url, fallback){
  const res = await fetch(url, {headers: {'Authorization': 'Bearer ' + getToken()}});
  if(!res.ok) throw new Error('Falha ao exportar (HTTP ' + res.status + ')');
  await salvarResposta(res, fallback);
}

// ═══ TEMA CLARO/ESCURO ═══
// O botão do hub/subhub mostra "🌙 Tema" e o dos módulos apenas "🌙". Em vez de
// duas implementações, o rótulo extra vem de data-label no próprio botão.
function applyTheme(theme){
  const isLight = theme === 'light';
  document.body.classList.toggle('theme-light', isLight);
  const btn = document.getElementById('theme-toggle');
  if(btn){
    const sufixo = btn.dataset.label ? ' ' + btn.dataset.label : '';
    btn.textContent = (isLight ? '☀️' : '🌙') + sufixo;
  }
}

// Cada módulo repinta o que precisa depois da troca: as cores de eixo dos
// gráficos são lidas na hora de desenhar, então trocar o tema exige redesenhar.
// Quem precisa disso define window.onThemeChange (ver equipamentos.js,
// missoes.js, entregaveis.js).
function toggleTheme(){
  const next = document.body.classList.contains('theme-light') ? 'dark' : 'light';
  localStorage.setItem('doctrack_theme', next);
  applyTheme(next);
  if(typeof window.onThemeChange === 'function'){
    try { window.onThemeChange(next); } catch(e){ /* repintar é best-effort */ }
  }
}

function initTheme(){
  applyTheme(localStorage.getItem('doctrack_theme') || 'dark');
}

// Aplica o tema salvo assim que o script carrega, antes de a página pintar —
// era o que cada módulo fazia na própria linha de topo.
initTheme();
