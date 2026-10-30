/* ═══════════════════════════════════════════════════════════════════════════
   fluxos-painel.js — o painel do fluxo de revisão, igual em todas as telas.

   Usado na ficha do documento (app.js) e no popover do entregável
   (entregaveis.js). Uma implementação só: a regra de quem age e o que acontece
   é do servidor (fluxos/core.py); aqui só se desenha o que /fluxos/api/por-ref
   devolve e se mandam as ações.

     DT_FLUXO.montar(host, {ref_tipo, ref_id, aoMudar})
       desenha em `host` e devolve {recarregar}. `aoMudar(fluxo)` é chamado
       depois de qualquer ação que deu certo — a tela hospedeira usa para
       recarregar o status do item, que o fluxo pode ter mudado.
     DT_FLUXO.resumos(ref_tipo, ids)  → Promise<{id: resumo}> (chips de lista)
     DT_FLUXO.chip(resumo)            → HTML do chip "Diagramação · Marcos · R2"

   IIFE com UM global, pelo motivo registrado em tempos-widget.js. Depende de
   common.js (getToken, esc, salvarResposta) e, quando existir, de auth.js.
   ═══════════════════════════════════════════════════════════════════════════ */
(function(){
  "use strict";

  /* ── rede ─────────────────────────────────────────────────────────────── */
  function req(url, opt){
    opt = opt || {};
    var h = opt.headers || {};
    h["Authorization"] = "Bearer " + getToken();
    if(opt.json !== undefined){
      h["Content-Type"] = "application/json";
      opt.body = JSON.stringify(opt.json);
    }
    opt.headers = h;
    return fetch(url, opt).then(function(res){
      if(res.status === 401 && window.DT_AUTH){
        return window.DT_AUTH.refresh().then(function(ok){
          if(!ok){ window.DT_AUTH.gotoLogin(true); throw new Error("Sessão expirada"); }
          h["Authorization"] = "Bearer " + getToken();
          return fetch(url, opt);
        });
      }
      return res;
    }).then(function(res){
      return res.json().catch(function(){ return {}; }).then(function(corpo){
        if(!res.ok){
          var e = new Error(corpo.erro || ("Falha (HTTP " + res.status + ")"));
          e.status = res.status; e.corpo = corpo;
          throw e;
        }
        return corpo;
      });
    });
  }

  var _cache = {};
  function uma(chave, fn){
    if(!_cache[chave]) _cache[chave] = fn().catch(function(e){ delete _cache[chave]; throw e; });
    return _cache[chave];
  }
  function modelos(){ return uma("modelos", function(){ return req("/fluxos/api/modelos").then(function(d){ return d.modelos || []; }); }); }
  function pessoas(){ return uma("pessoas", function(){ return req("/fluxos/api/pessoas").then(function(d){ return d.pessoas || []; }); }); }

  function avisar(msg, erro){
    if(typeof window.showToast === "function") window.showToast(msg, erro ? "error" : "success");
    else if(typeof window.toast === "function") window.toast(msg, !!erro);
    else if(erro) alert(msg);
  }

  function atualizarSino(){
    try{ window.dispatchEvent(new CustomEvent("dt:notificacoes-atualizar")); }catch(e){}
  }

  /* ── arquivos ─────────────────────────────────────────────────────────── */
  var VISUALIZA_NA_ABA = {pdf: 1, png: 1, jpg: 1, jpeg: 1};

  function abrirArquivo(id, ext, nome){
    var url = "/fluxos/api/arquivos/" + id + "/conteudo";
    if(VISUALIZA_NA_ABA[(ext || "").toLowerCase()]){
      // A janela abre AGORA, dentro do clique: aberta depois do fetch, o
      // bloqueador de pop-up a mataria.
      var w = window.open("", "_blank");
      fetch(url, {headers: {"Authorization": "Bearer " + getToken()}})
        .then(function(res){ if(!res.ok) throw new Error("HTTP " + res.status); return res.blob(); })
        .then(function(b){
          var href = URL.createObjectURL(b);
          if(w) w.location.href = href; else window.open(href, "_blank");
          setTimeout(function(){ URL.revokeObjectURL(href); }, 60000);
        })
        .catch(function(){ if(w) w.close(); avisar("Não foi possível abrir o arquivo", true); });
      return;
    }
    fetch(url + "?download=1", {headers: {"Authorization": "Bearer " + getToken()}})
      .then(function(res){ if(!res.ok) throw new Error(); return salvarResposta(res, nome); })
      .catch(function(){ avisar("Não foi possível baixar o arquivo", true); });
  }

  /* ── desenho ──────────────────────────────────────────────────────────── */
  var ICONE_ACAO = {iniciar: "▶", enviar: "→", aprovar: "✓", devolver: "↩",
                    reatribuir: "⇄", cancelar: "✕"};

  function dias(n){ return n === 0 ? "hoje" : n === 1 ? "há 1 dia" : "há " + n + " dias"; }
  function dataBR(iso){ return iso ? iso.split("-").reverse().join("/") : ""; }

  function textoPassagem(p){
    switch(p.acao){
      case "iniciar":    return "iniciou o fluxo" + (p.para_etapa ? " — " + esc(p.para_etapa) : "");
      case "enviar":     return p.para_etapa ? "enviou para <b>" + esc(p.para_etapa) + "</b>"
                                             : "concluiu " + esc(p.de_etapa) + " — fluxo encerrado";
      case "aprovar":    return p.para_etapa ? "aprovou " + esc(p.de_etapa) + " → <b>" + esc(p.para_etapa) + "</b>"
                                             : "aprovou — fluxo concluído";
      case "devolver":   return "devolveu para <b>" + esc(p.para_etapa) + "</b>";
      case "reatribuir": return "trocou a pessoa de um papel";
      case "cancelar":   return "cancelou o fluxo";
    }
    return esc(p.acao);
  }

  function htmlEtapas(f){
    var idx = -1;
    f.etapas.forEach(function(e, i){ if(e.chave === f.etapa_atual) idx = i; });
    var nomes = {};
    f.participantes.forEach(function(p){ nomes[p.papel] = p.pessoa ? p.pessoa.nome : "sem responsável"; });
    return '<ol class="fx-etapas">' + f.etapas.map(function(e, i){
      var cls = f.status === "aprovado" ? "feita" : (i < idx ? "feita" : i === idx ? "atual" : "futura");
      return '<li class="' + cls + '"><span class="fx-etapa-nome">' + esc(e.nome) +
        (e.tipo === "revisao" ? ' <span class="fx-tag">revisão</span>' : '') + '</span>' +
        '<span class="fx-etapa-quem">' + esc(nomes[e.papel] || "") + '</span></li>';
    }).join("") + '</ol>';
  }

  function htmlAcoes(f){
    if(!f.acoes.length) return "";
    var resp = f.responsavel ? f.responsavel.nome : "";
    var temDevolver = f.acoes.some(function(a){ return a.acao === "devolver"; });
    return '<div class="fx-acao">' +
      '<div class="fx-acao-tit">' + (f.em_nome_de
        ? 'Você está agindo <b>em nome de ' + esc(resp) + '</b> — fica registrado.'
        : 'É sua vez: <b>' + esc(f.etapa_nome) + '</b>') + '</div>' +
      '<textarea class="form-input fx-coment" rows="3" placeholder="' +
        (temDevolver ? 'Apontamentos da revisão (obrigatório para devolver)' : 'Comentário (opcional)') +
      '"></textarea>' +
      '<div class="fx-arq-linha"><label class="btn btn-ghost btn-sm fx-arq-btn">Anexar arquivos' +
        '<input type="file" class="fx-arq" multiple hidden></label>' +
        '<span class="fx-arq-lista">Nenhum arquivo</span></div>' +
      '<div class="fx-botoes">' + f.acoes.map(function(a){
        var cls = a.acao === "devolver" ? "btn btn-ghost fx-devolver" : "btn btn-primary";
        return '<button type="button" class="' + cls + '" data-fx="agir" data-acao="' + a.acao + '">' +
          esc(a.rotulo) + '</button>';
      }).join("") + '</div></div>';
  }

  function htmlGerir(f){
    if(!f.pode_gerir) return "";
    return '<details class="fx-gerir"><summary>Gerir fluxo</summary>' +
      '<div class="fx-gerir-linha"><select class="form-input fx-g-papel">' +
        f.participantes.map(function(p){
          return '<option value="' + esc(p.papel) + '">' + esc(p.papel_nome) + ' — ' +
            esc(p.pessoa ? p.pessoa.nome : "sem responsável") + '</option>';
        }).join("") + '</select>' +
        '<select class="form-input fx-g-pessoa"><option value="">Nova pessoa…</option></select></div>' +
      '<input class="form-input fx-g-motivo" placeholder="Motivo (obrigatório)">' +
      '<div class="fx-botoes"><button type="button" class="btn btn-ghost btn-sm" data-fx="reatribuir">Trocar pessoa</button>' +
      '<button type="button" class="btn btn-ghost btn-sm fx-perigo" data-fx="cancelar">Cancelar fluxo</button></div>' +
      '</details>';
  }

  function htmlTrilha(f){
    return '<div class="fx-trilha">' + f.passagens.map(function(p){
      return '<div class="fx-pass fx-' + p.acao + '">' +
        '<span class="fx-pass-ico">' + (ICONE_ACAO[p.acao] || "•") + '</span>' +
        '<div class="fx-pass-corpo"><div><b>' + esc(p.por) + '</b>' +
          (p.em_nome_de ? ' <span class="fx-nome-de">(em nome de ' + esc(p.em_nome_de) + ')</span>' : '') +
          ' ' + textoPassagem(p) +
          (p.rodada > 1 ? ' <span class="fx-tag">rodada ' + p.rodada + '</span>' : '') + '</div>' +
          (p.comentario ? '<div class="fx-pass-coment">' + esc(p.comentario) + '</div>' : '') +
          (p.arquivos.length ? '<div class="fx-pass-arqs">' + p.arquivos.map(function(a){
            return '<button type="button" class="fx-arq-chip" data-fx="arquivo" data-id="' + a.id +
              '" data-ext="' + esc(a.ext) + '" data-nome="' + esc(a.nome) + '">📎 ' + esc(a.nome) + '</button>';
          }).join("") + '</div>' : '') +
          '<div class="fx-pass-em">' + esc(p.em) + '</div>' +
        '</div></div>';
    }).join("") + '</div>';
  }

  function htmlAtivo(f){
    var cab = '<div class="fx-cab"><span class="fx-modelo">' + esc(f.modelo_nome) + '</span>' +
      (f.rodada > 1 ? '<span class="fx-tag forte">rodada ' + f.rodada + '</span>' : '') +
      (f.prazo ? '<span class="fx-tag ' + (f.atrasado ? 'atraso' : '') + '">prazo ' + dataBR(f.prazo) + '</span>' : '') +
      '</div>';
    var agora = f.responsavel
      ? '<div class="fx-agora">Com <b>' + esc(f.responsavel.nome) + '</b> em ' + esc(f.etapa_nome) +
        ' · ' + dias(f.dias_na_etapa) + (f.responsavel.ativo ? '' : ' · <span class="fx-atraso">usuário inativo</span>') + '</div>'
      : '<div class="fx-agora fx-atraso">Etapa sem responsável — a gestão precisa trocar a pessoa.</div>';
    return cab + htmlEtapas(f) + agora + htmlAcoes(f) + htmlGerir(f) + htmlTrilha(f);
  }

  function htmlAnteriores(lista){
    if(!lista.length) return "";
    return '<details class="fx-anteriores"><summary>Fluxos anteriores (' + lista.length + ')</summary>' +
      lista.map(function(r){
        return '<div class="fx-ant">' + esc(r.modelo_nome) + ' · ' +
          (r.status === "aprovado" ? "aprovado" : "cancelado") + ' em ' + esc(r.concluido_em) +
          (r.rodada > 1 ? ' · ' + r.rodada + ' rodadas' : '') +
          ' <button type="button" class="fx-link" data-fx="ver-anterior" data-id="' + r.fluxo_id + '">ver trilha</button></div>';
      }).join("") + '<div class="fx-ant-detalhe"></div></details>';
  }

  /* ── tempo real ───────────────────────────────────────────────────────────
     A página que tem socket repassa cada evento como `dt:evento`
     (socket-client.js; Projetos e Missões fazem o repasse no socket próprio).
     FLUXO_* do item que um painel mostra recarrega aquele painel — a menos que a
     pessoa esteja escrevendo nele: aí aparece um aviso e ela atualiza quando
     quiser, sem perder o comentário ou os arquivos escolhidos. */
  var _paineis = [];
  window.addEventListener("dt:evento", function(ev){
    var e = (ev && ev.detail) || {};
    if(!/^FLUXO_/.test(e.event_type || "")) return;
    var p = e.payload || {};
    _paineis = _paineis.filter(function(c){ return document.body.contains(c.host); });
    _paineis.forEach(function(c){ c.aoEventoExterno(p); });
  });

  /* ── controlador de um host ───────────────────────────────────────────── */
  function montar(host, opts){
    // O popover do entregável reaproveita o mesmo host a cada abertura: montar de
    // novo empilharia ouvintes de clique e cada ação sairia duas vezes.
    if(host.__dtFluxo){ host.__dtFluxo.trocar(opts); return host.__dtFluxo; }
    var estado = {dados: null, arquivos: []};

    function desenhar(){
      var d = estado.dados;
      if(!d){ host.innerHTML = ""; return; }
      var h = '<div class="fx">';
      if(d.ativo) h += htmlAtivo(d.ativo);
      else {
        h += '<div class="fx-vazio">Nenhum fluxo de revisão em andamento.</div>';
        if(d.pode_iniciar) h += '<button type="button" class="btn btn-ghost btn-sm" data-fx="abrir-inicio">Iniciar fluxo de revisão</button><div class="fx-inicio"></div>';
      }
      h += htmlAnteriores(d.anteriores || []) + '</div>';
      host.innerHTML = h;
      estado.arquivos = [];
      if(d.ativo && d.ativo.pode_gerir){
        pessoas().then(function(ps){
          var sel = host.querySelector(".fx-g-pessoa");
          if(sel) sel.innerHTML = '<option value="">Nova pessoa…</option>' + ps.map(function(p){
            return '<option value="' + p.id + '">' + esc(p.nome) + '</option>';
          }).join("");
        }).catch(function(){});
      }
    }

    var seq = 0;
    function recarregar(){
      var meu = ++seq;    // resposta atrasada de um item anterior não pinta por cima
      return req("/fluxos/api/por-ref?ref_tipo=" + opts.ref_tipo + "&ref_id=" + opts.ref_id)
        .then(function(d){ if(meu === seq){ estado.dados = d; desenhar(); } })
        .catch(function(e){
          if(meu !== seq) return;
          // 403 (leitura, ou técnico sem alcance): a seção simplesmente não mostra nada.
          host.innerHTML = e.status === 403 ? "" :
            '<div class="fx-vazio">Não foi possível carregar o fluxo (' + esc(e.message) + ').</div>';
        });
    }

    function depois(f){
      atualizarSino();
      if(typeof opts.aoMudar === "function"){ try{ opts.aoMudar(f); }catch(e){} }
      return recarregar();
    }

    function erroOuConflito(e){
      avisar(e.message, true);
      if(e.status === 409) recarregar();
    }

    function formInicio(){
      var alvo = host.querySelector(".fx-inicio");
      if(!alvo) return;
      alvo.innerHTML = '<div class="fx-vazio">Carregando modelos…</div>';
      Promise.all([modelos(), pessoas()]).then(function(r){
        var ms = r[0], ps = r[1];
        if(!ms.length){ alvo.innerHTML = '<div class="fx-vazio">Nenhum modelo de fluxo cadastrado. Peça à gestão em Fluxos → Modelos.</div>'; return; }
        function papeisHtml(m){
          return m.papeis.map(function(p){
            return '<label class="fx-campo"><span>' + esc(p.nome) + '</span><select class="form-input" data-papel="' + esc(p.chave) + '">' +
              '<option value="">Escolha…</option>' + ps.map(function(x){
                return '<option value="' + x.id + '"' + (x.id === p.padrao_user_id ? ' selected' : '') + '>' + esc(x.nome) + '</option>';
              }).join("") + '</select></label>';
          }).join("");
        }
        function etapasTxt(m){ return m.etapas.map(function(e){ return e.nome; }).join(" → "); }
        alvo.innerHTML = '<div class="fx-form">' +
          '<label class="fx-campo"><span>Modelo</span><select class="form-input fx-i-modelo">' + ms.map(function(m){
            return '<option value="' + m.id + '">' + esc(m.nome) + '</option>'; }).join("") + '</select></label>' +
          '<div class="fx-i-etapas fx-sub">' + esc(etapasTxt(ms[0])) + '</div>' +
          '<div class="fx-i-papeis">' + papeisHtml(ms[0]) + '</div>' +
          '<label class="fx-campo"><span>Prazo (opcional)</span><input type="date" class="form-input fx-i-prazo"></label>' +
          '<label class="fx-campo"><span>Comentário (opcional)</span><input class="form-input fx-i-coment"></label>' +
          '<div class="fx-botoes"><button type="button" class="btn btn-primary btn-sm" data-fx="iniciar">Iniciar</button>' +
          '<button type="button" class="btn btn-ghost btn-sm" data-fx="fechar-inicio">Cancelar</button></div></div>';
        alvo.querySelector(".fx-i-modelo").addEventListener("change", function(ev){
          var m = ms.filter(function(x){ return String(x.id) === ev.target.value; })[0];
          alvo.querySelector(".fx-i-papeis").innerHTML = papeisHtml(m);
          alvo.querySelector(".fx-i-etapas").textContent = etapasTxt(m);
        });
      }).catch(function(e){ alvo.innerHTML = '<div class="fx-vazio">' + esc(e.message) + '</div>'; });
    }

    function iniciar(btn){
      var participantes = {};
      host.querySelectorAll(".fx-i-papeis select").forEach(function(s){
        if(s.value) participantes[s.dataset.papel] = Number(s.value);
      });
      btn.disabled = true;
      req("/fluxos/api/fluxos", {method: "POST", json: {
        ref_tipo: opts.ref_tipo, ref_id: opts.ref_id,
        modelo_id: Number(host.querySelector(".fx-i-modelo").value),
        participantes: participantes,
        prazo: host.querySelector(".fx-i-prazo").value || "",
        comentario: host.querySelector(".fx-i-coment").value || ""
      }}).then(function(d){ avisar("Fluxo iniciado"); return depois(d.fluxo); })
        .catch(function(e){ btn.disabled = false; erroOuConflito(e); });
    }

    function agir(btn){
      var f = estado.dados.ativo;
      var acao = btn.dataset.acao;
      var coment = (host.querySelector(".fx-coment") || {}).value || "";
      if(acao === "devolver" && !coment.trim()){
        avisar("Para devolver, descreva os apontamentos", true);
        host.querySelector(".fx-coment").focus();
        return;
      }
      var etapaExec = f.etapas.some(function(e){ return e.chave === f.etapa_atual && e.tipo === "execucao"; });
      if(etapaExec && !estado.arquivos.length &&
         !confirm("Enviar sem anexar nenhum arquivo?")) return;
      var fd = new FormData();
      fd.append("acao", acao);
      fd.append("comentario", coment);
      fd.append("versao", String(f.versao));
      estado.arquivos.forEach(function(a){ fd.append("arquivos", a, a.name); });
      host.querySelectorAll("[data-fx=agir]").forEach(function(b){ b.disabled = true; });
      req("/fluxos/api/fluxos/" + f.fluxo_id + "/acao", {method: "POST", body: fd})
        .then(function(d){ avisar(btn.textContent.trim() + " — feito"); return depois(d.fluxo); })
        .catch(function(e){
          host.querySelectorAll("[data-fx=agir]").forEach(function(b){ b.disabled = false; });
          erroOuConflito(e);
        });
    }

    function gerir(tipo, btn){
      var f = estado.dados.ativo;
      var motivo = host.querySelector(".fx-g-motivo").value.trim();
      if(!motivo){ avisar("Informe o motivo", true); return; }
      var corpo = {motivo: motivo, versao: f.versao}, url = "/fluxos/api/fluxos/" + f.fluxo_id + "/" + tipo;
      if(tipo === "reatribuir"){
        corpo.papel = host.querySelector(".fx-g-papel").value;
        corpo.user_id = Number(host.querySelector(".fx-g-pessoa").value);
        if(!corpo.user_id){ avisar("Escolha a nova pessoa", true); return; }
      } else if(!confirm("Cancelar este fluxo? O status do item não muda.")) return;
      btn.disabled = true;
      req(url, {method: "POST", json: corpo})
        .then(function(d){ avisar(tipo === "cancelar" ? "Fluxo cancelado" : "Pessoa trocada"); return depois(d.fluxo); })
        .catch(function(e){ btn.disabled = false; erroOuConflito(e); });
    }

    function verAnterior(id){
      var alvo = host.querySelector(".fx-ant-detalhe");
      alvo.innerHTML = '<div class="fx-vazio">Carregando…</div>';
      req("/fluxos/api/fluxos/" + id).then(function(d){ alvo.innerHTML = htmlEtapas(d.fluxo) + htmlTrilha(d.fluxo); })
        .catch(function(e){ alvo.innerHTML = '<div class="fx-vazio">' + esc(e.message) + '</div>'; });
    }

    host.addEventListener("click", function(ev){
      var b = ev.target.closest("[data-fx]");
      if(!b || !host.contains(b)) return;
      var tipo = b.dataset.fx;
      // style e não `hidden`: o display do .btn venceria o atributo.
      if(tipo === "abrir-inicio"){ b.style.display = "none"; formInicio(); }
      else if(tipo === "fechar-inicio"){ desenhar(); }
      else if(tipo === "iniciar") iniciar(b);
      else if(tipo === "agir") agir(b);
      else if(tipo === "reatribuir" || tipo === "cancelar") gerir(tipo, b);
      else if(tipo === "arquivo") abrirArquivo(b.dataset.id, b.dataset.ext, b.dataset.nome);
      else if(tipo === "ver-anterior") verAnterior(b.dataset.id);
      else if(tipo === "atualizar") recarregar();
    });
    host.addEventListener("change", function(ev){
      if(!ev.target.classList.contains("fx-arq")) return;
      estado.arquivos = Array.prototype.slice.call(ev.target.files || []);
      var lista = host.querySelector(".fx-arq-lista");
      if(lista) lista.textContent = estado.arquivos.length
        ? estado.arquivos.map(function(a){ return a.name; }).join(", ") : "Nenhum arquivo";
    });

    function trocar(novas){
      opts = novas;
      estado.dados = null;
      host.innerHTML = '<div class="fx-vazio">Carregando…</div>';
      return recarregar();
    }

    // Para de desenhar (uma resposta atrasada não pinta por cima do que vier).
    function parar(){ seq++; estado.dados = null; }

    function editando(){
      var c = host.querySelector(".fx-coment"), m = host.querySelector(".fx-g-motivo"),
          i = host.querySelector(".fx-inicio");
      return !!((c && c.value.trim()) || estado.arquivos.length || (m && m.value.trim()) ||
                (i && i.innerHTML.trim()));
    }

    var tExterno = null;
    function aoEventoExterno(p){
      if(p.ref_tipo !== opts.ref_tipo || Number(p.ref_id) !== Number(opts.ref_id)) return;
      clearTimeout(tExterno);
      tExterno = setTimeout(function(){
        if(!editando()){ recarregar(); return; }
        if(host.querySelector(".fx-aviso-rt")) return;
        var a = document.createElement("div");
        a.className = "fx-aviso-rt";
        a.innerHTML = '<span>O fluxo mudou enquanto você escrevia.</span>' +
          '<button type="button" class="fx-link" data-fx="atualizar">Atualizar</button>';
        host.insertBefore(a, host.firstChild);
      }, 400);
    }

    host.__dtFluxo = {recarregar: recarregar, trocar: trocar, parar: parar};
    _paineis.push({host: host, aoEventoExterno: aoEventoExterno});
    trocar(opts);
    return host.__dtFluxo;
  }

  /* ── listas ───────────────────────────────────────────────────────────── */
  function resumos(ref_tipo, ids){
    if(!ids || !ids.length) return Promise.resolve({});
    return req("/fluxos/api/por-refs?ref_tipo=" + ref_tipo + "&ids=" + ids.join(","))
      .then(function(d){ return d.resumos || {}; })
      .catch(function(){ return {}; });
  }

  function chip(r){
    if(!r) return "";
    var quem = r.responsavel ? r.responsavel.nome.split(" ")[0] : "sem responsável";
    return '<span class="fx-chip' + (r.atrasado ? ' atraso' : '') + '" title="Fluxo ' + esc(r.modelo_nome) +
      ': ' + esc(r.etapa_nome) + ' com ' + esc(r.responsavel ? r.responsavel.nome : "ninguém") +
      ' · ' + dias(r.dias_na_etapa) + '">⟳ ' + esc(r.etapa_nome) + ' · ' + esc(quem) +
      (r.rodada > 1 ? ' · R' + r.rodada : '') + '</span>';
  }

  /* O host deixa de mostrar um fluxo (ex.: entregável que são 4 checklists). */
  function limpar(host, html){
    if (host.__dtFluxo) host.__dtFluxo.parar();
    host.innerHTML = html || "";
  }

  window.DT_FLUXO = {montar: montar, resumos: resumos, chip: chip, limpar: limpar};
})();
