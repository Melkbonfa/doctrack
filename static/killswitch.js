/* killswitch.js — reação do front à trava de emergência.
 *
 * Com o sistema travado, uma navegação normal já cai na tela de bloqueio (o
 * servidor devolve travado.html na própria URL). O que NÃO cai sozinho é a aba
 * que já estava aberta: ela só conversa com o servidor por fetch, e um 423
 * chegaria como "erro ao carregar" em cada módulo, cada um tratando do seu
 * jeito. Este arquivo resolve num lugar só, envolvendo o fetch global.
 *
 * Carregado em base.html fora do bloco `scripts` — todos os módulos
 * sobrescrevem aquele bloco sem chamar super(), então um <script> lá dentro
 * não carregaria em página nenhuma (mesmo motivo do tempos-widget).
 */
(function () {
  "use strict";

  if (window.__dtKillSwitch) return;      // base.html pode ser incluído duas vezes
  window.__dtKillSwitch = true;

  var TRAVADO = 423;
  var redirecionando = false;

  function irParaBloqueio() {
    if (redirecionando) return;
    redirecionando = true;
    // replace e não href: o botão Voltar não deve devolver o usuário a uma
    // página do sistema que não responde mais.
    location.replace("/travado");
  }

  var fetchOriginal = window.fetch;
  if (typeof fetchOriginal !== "function") return;

  window.fetch = function () {
    return fetchOriginal.apply(this, arguments).then(function (resposta) {
      if (resposta && resposta.status === TRAVADO) irParaBloqueio();
      return resposta;
    });
  };

  // Socket aberto: o servidor avisa no instante em que trava, então a aba não
  // precisa esperar a próxima chamada de API para reagir. Só engancha se a
  // página tiver socket — não é o caso de todas.
  document.addEventListener("DOMContentLoaded", function () {
    var sock = window.socket || window.io_socket;
    if (sock && typeof sock.on === "function") {
      sock.on("sistema_travado", irParaBloqueio);
    }
  });
})();
