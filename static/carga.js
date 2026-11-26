// ═══════════════════════════════════════════════════════════════════════════
//  CARGA.JS — Configurações → Carga por planilha (só admin)
//  Baixar → editar no Excel → enviar (prévia, nada gravado) → aplicar.
//  O servidor guarda a planilha da prévia e devolve um token; o Aplicar manda
//  só o token, então grava exatamente o que foi visto na prévia.
//  Depende de config.js (apiFetch, showToast, confirmModal) e common.js
//  (esc, getToken, salvarResposta).
// ═══════════════════════════════════════════════════════════════════════════
(function(){
  let _token = null, _ocupado = false, _ligado = false;

  const $ = id => document.getElementById(id);

  // apiFetch de config.js força Content-Type JSON; o upload precisa que o
  // navegador monte o multipart, então este fetch só leva o Authorization.
  async function enviarArquivo(url, form){
    const req = () => fetch('/api' + url, {method:'POST', body: form,
                                           headers: {'Authorization': 'Bearer ' + getToken()}});
    let res = await req();
    if(res.status === 401 && window.DT_AUTH && await window.DT_AUTH.refresh()) res = await req();
    if(res.status === 401){ if(window.DT_AUTH) window.DT_AUTH.gotoLogin(true); return null; }
    return res;
  }

  function classeLinha(l){
    if(l.startsWith('+ ')) return 'add';
    if(l.startsWith('- ')) return l.includes('N/A') ? 'na' : 'del';
    return '';
  }
  function classeChip(r){
    if(/N\/A/.test(r)) return 'warn';
    if(/apagad|excluíd/.test(r)) return 'del';
    return '';
  }

  function htmlRelatorio(rel){
    if(rel.vazio) return '<p class="carga-txt">Nada a mudar: o DocTrack já está igual à planilha.</p>';
    let h = '<div class="carga-resumo">' + rel.resumo.map(r =>
      `<span class="carga-chip ${classeChip(r.rotulo)}"><b>${r.n}</b>${esc(r.rotulo)}</span>`).join('') + '</div>';
    if(rel.avisos.length){
      h += '<div class="carga-avisos"><b>Atenção</b><ul>' +
           rel.avisos.map(a => `<li>${esc(a)}</li>`).join('') + '</ul></div>';
    }
    const total = rel.secoes.reduce((n, s) => n + s.linhas.length, 0);
    h += rel.secoes.map(s => `
      <details class="carga-secao"${total <= 40 ? ' open' : ''}>
        <summary>${esc(s.titulo)} <span class="n">${s.linhas.length}</span></summary>
        <ul class="carga-linhas">${s.linhas.map(l => `<li class="${classeLinha(l)}">${esc(l)}</li>`).join('')}</ul>
      </details>`).join('');
    return h;
  }

  function mostrar(html){ $('carga-resultado').innerHTML = html; }

  function mostrarErros(arquivo, corpo){
    const erros = (corpo && corpo.erros) || [];
    const meta = (arquivo ? esc(arquivo) + ' · ' : '') + 'Corrija a planilha e envie de novo.';
    mostrar(`<div class="card">
      <div class="carga-cab"><div><div class="card-title">${esc((corpo && corpo.erro) || 'Não foi possível ler a planilha')}</div>
        <div class="carga-meta">${meta}</div></div></div>
      ${erros.length ? '<div class="carga-erros"><ul>' + erros.map(e => `<li>${esc(e)}</li>`).join('') + '</ul></div>' : ''}
    </div>`);
  }

  function mostrarPrevia(corpo){
    _token = corpo.token;
    const rel = corpo.relatorio;
    mostrar(`<div class="card">
      <div class="carga-cab"><div><div class="card-title">Prévia — nada foi gravado ainda</div>
        <div class="carga-meta">${esc(corpo.arquivo)}${_token ? ` · vale por ${corpo.valida_min} minutos` : ''}</div></div>
        <button class="btn btn-ghost btn-sm" type="button" id="carga-btn-descartar">Descartar</button></div>
      ${htmlRelatorio(rel)}
      ${_token ? `<div class="carga-aplicar">
        <div class="form-group"><label class="form-label" for="carga-motivo">Motivo da carga (fica no histórico dos modelos)</label>
          <input class="form-input" id="carga-motivo" maxlength="500" placeholder="Ex.: Novos modelos PDR 2027"></div>
        <button class="btn btn-primary" type="button" id="carga-btn-aplicar">Aplicar no DocTrack</button>
        <p class="carga-nota">Antes de gravar, o sistema faz um backup completo do banco. Se o backup falhar, nada é aplicado.</p>
      </div>` : ''}
    </div>`);
  }

  function mostrarAplicado(corpo){
    _token = null;
    mostrar(`<div class="card carga-ok">
      <div class="carga-cab"><div><div class="card-title">Carga aplicada</div>
        <div class="carga-meta">${esc(corpo.arquivo)} · ${esc(corpo.aplicado_em)} · motivo: ${esc(corpo.motivo)}</div>
        <div class="carga-meta">Backup feito antes: ${esc(corpo.backup)}</div></div>
        <button class="btn btn-ghost btn-sm" type="button" id="carga-btn-descartar">Fechar</button></div>
      ${htmlRelatorio(corpo.relatorio)}
    </div>`);
  }

  function ocupado(sim, texto){
    _ocupado = sim;
    $('carga-drop').classList.toggle('busy', sim);
    $('carga-drop-txt').innerHTML = sim ? esc(texto) : 'Arraste a planilha aqui ou <u>clique para escolher</u>';
  }

  async function baixar(){
    const btn = $('carga-btn-baixar');
    btn.disabled = true; btn.textContent = 'Gerando…';
    try{
      const res = await apiFetch('/carga/planilha');
      if(!res || !res.ok) throw new Error();
      await salvarResposta(res, 'DocTrack_carga.xlsx');
    }catch(e){ showToast('Não foi possível gerar a planilha', 'error'); }
    finally{ btn.disabled = false; btn.textContent = 'Baixar planilha'; }
  }

  async function enviar(arquivo){
    if(!arquivo || _ocupado) return;
    if(!/\.xlsx$/i.test(arquivo.name)){ showToast('Envie a planilha no formato .xlsx', 'error'); return; }
    ocupado(true, 'Calculando a prévia de ' + arquivo.name + '…');
    mostrar('');
    try{
      const form = new FormData();
      form.append('arquivo', arquivo);
      const res = await enviarArquivo('/carga/previa', form);
      if(!res) return;
      const corpo = await res.json().catch(() => ({}));
      if(res.status === 422){ mostrarErros(arquivo.name, corpo); return; }
      if(!res.ok){ showToast(corpo.erro || 'Não foi possível calcular a prévia', 'error'); return; }
      mostrarPrevia(corpo);
    }catch(e){ showToast('Não foi possível enviar a planilha', 'error'); }
    finally{ ocupado(false); $('carga-arquivo').value = ''; }
  }

  async function aplicar(){
    const motivo = ($('carga-motivo').value || '').trim();
    if(motivo.length < 5){
      showToast('Escreva o motivo da carga (pelo menos 5 caracteres)', 'error');
      $('carga-motivo').focus(); return;
    }
    const ok = await confirmModal('Aplicar a carga?',
      'As mudanças da prévia serão gravadas no DocTrack e aplicadas aos projetos. Um backup do banco é feito antes.');
    if(!ok) return;
    const btn = $('carga-btn-aplicar');
    btn.disabled = true; btn.textContent = 'Fazendo backup e aplicando…';
    try{
      const res = await apiFetch('/carga/aplicar', {method:'POST', body: JSON.stringify({token: _token, motivo})});
      if(!res) return;
      const corpo = await res.json().catch(() => ({}));
      if(res.status === 422){ mostrarErros('', corpo); return; }
      if(!res.ok){ showToast(corpo.erro || 'Não foi possível aplicar', 'error'); return; }
      mostrarAplicado(corpo);
      showToast('Carga aplicada', 'success');
    }catch(e){ showToast('Não foi possível aplicar', 'error'); }
    finally{ if(document.body.contains(btn)){ btn.disabled = false; btn.textContent = 'Aplicar no DocTrack'; } }
  }

  function ligar(){
    if(_ligado) return;
    _ligado = true;
    $('carga-btn-baixar').addEventListener('click', baixar);
    $('carga-arquivo').addEventListener('change', e => enviar(e.target.files[0]));
    const drop = $('carga-drop');
    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', e => enviar(e.dataTransfer.files[0]));
    $('carga-resultado').addEventListener('click', e => {
      if(e.target.id === 'carga-btn-aplicar') aplicar();
      if(e.target.id === 'carga-btn-descartar'){ _token = null; mostrar(''); }
    });
  }

  window.cargaAbrir = function(){ ligar(); };
  // config.js carrega antes e pode já ter aberto a aba (link com #carga).
  if($('page-carga') && $('page-carga').classList.contains('active')) ligar();
})();
