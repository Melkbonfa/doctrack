/* ═══════════════════════════════════════════════════════════════════════════
   nav-mobile.js — dono único da gaveta lateral no celular.

   Por que existe
   --------------
   A gaveta (`.sidebar` + `#sidebar-toggle` + `#sidebar-backdrop`) é declarada
   em base.html e desenhada em style.css:890, mas quem a fazia ABRIR era o JS de
   cada módulo — quatro cópias da mesma função, e três módulos sem cópia
   nenhuma. Medido no navegador a 375px:

     • Tempos e Custos  — o ☰ estava na tela e não fazia nada. A gaveta ficava
       em translateX(-100%) para sempre: sem navegação, sem "Voltar aos
       módulos", sem "Sair". O módulo inteiro era um beco sem saída no celular.
     • PDR              — o <nav class="sidebar"> existe e pdr/static/style.css
       já traz todo o CSS do ☰, mas o botão nunca foi posto no HTML.
     • Equipamentos e Missões — abriam, mas não fechavam ao tocar num item: a
       gaveta cobria a página que o toque acabara de trocar.
     • Documentos e Configurações — corretos. São de onde este arquivo tira o
       comportamento de referência.

   Duas decisões que valem a explicação:

   1. DELEGAÇÃO, não `querySelectorAll` no load. A cópia de app.js liga o
      fechamento item a item, no carregamento. Isso já não servia para Missões,
      onde os itens da gaveta SÃO as missões e nascem depois, em renderSidebar()
      — a lista chega do servidor. Um listener no documento pega os dois casos.

   2. Carregado por `_pwa_head.html`, não por common.js. É o único parcial que
      alcança as sete páginas: PDR tem <head> próprio e não carrega common.js
      (nem auth.js — ver o <script> de sessão no topo daquele template).

   Vem com `defer` no <head>, então roda DEPOIS dos scripts de módulo no fim do
   <body> — que é o que permite este arquivo ser o dono único sem disputar
   listener com ninguém. As cópias antigas foram removidas de app.js,
   config.js, equipamentos.js e missoes.js.
   ═══════════════════════════════════════════════════════════════════════════ */
(function(){
  "use strict";

  /* Mesmo corte de style.css:890, onde a sidebar vira gaveta. Acima disto ela é
     coluna fixa e o ☰ nem aparece. */
  var CORTE = 900;

  function iniciar(){
    var gaveta = document.getElementById("sidebar-nav");
    /* Hub, sub-hub e Projetos não têm gaveta — são páginas de uma coluna só. */
    if(!gaveta) return;

    var botao = document.getElementById("sidebar-toggle");
    var fundo = document.getElementById("sidebar-backdrop");

    function alternar(abrir){
      var vai = (abrir === undefined) ? !gaveta.classList.contains("open") : abrir;
      gaveta.classList.toggle("open", vai);
      if(fundo) fundo.classList.toggle("open", vai);
      if(botao){
        botao.setAttribute("aria-expanded", String(vai));
        botao.setAttribute("aria-label", vai ? "Fechar menu" : "Abrir menu");
      }
    }

    if(botao) botao.addEventListener("click", function(){ alternar(); });
    if(fundo) fundo.addEventListener("click", function(){ alternar(false); });

    /* Fechar ao tocar num item. Delegação pelo motivo 1 do cabeçalho: em
       Missões os itens são as missões e só existem depois do fetch.
       Só no celular: no desktop a gaveta é a coluna fixa e não há o que fechar. */
    document.addEventListener("click", function(ev){
      if(window.innerWidth > CORTE) return;
      if(!gaveta.classList.contains("open")) return;
      var alvo = ev.target.closest ? ev.target.closest(".nav-item") : null;
      if(alvo && gaveta.contains(alvo)) alternar(false);
    });

    /* Esc fecha — e sem roubar a tecla de um modal aberto por cima da gaveta,
       que tem o próprio tratador em cada módulo. */
    document.addEventListener("keydown", function(ev){
      if(ev.key !== "Escape") return;
      if(document.querySelector(".modal-overlay.open")) return;
      if(gaveta.classList.contains("open")) alternar(false);
    });

    /* Girar o aparelho para paisagem pode cruzar os 900px. Sem isto a classe
       `open` fica pendurada e o backdrop cobre a tela inteira num layout que
       já não tem gaveta. */
    window.addEventListener("resize", function(){
      if(window.innerWidth > CORTE && gaveta.classList.contains("open")) alternar(false);
    });
  }

  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
