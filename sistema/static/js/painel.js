/* Painel de clientes: recolher (lembrado no navegador) e abrir no celular.
   Carregado no <head> sem defer, para aplicar a escolha antes de desenhar a página. */
(function () {
  var raiz = document.documentElement;
  try {
    if (localStorage.getItem("painelRecolhido") === "1") raiz.classList.add("painel-recolhido");
  } catch (e) { /* navegador sem localStorage: painel aberto */ }

  function atualizarBotoes() {
    var recolhido = raiz.classList.contains("painel-recolhido");
    document.querySelectorAll("[data-recolher-painel]").forEach(function (b) {
      b.setAttribute("aria-expanded", recolhido ? "false" : "true");
    });
    document.querySelectorAll("[data-abrir-painel]").forEach(function (b) {
      b.setAttribute("aria-expanded", raiz.classList.contains("painel-aberto") ? "true" : "false");
    });
  }

  document.addEventListener("click", function (evento) {
    var recolher = evento.target.closest("[data-recolher-painel]");
    if (recolher) {
      var recolhido = raiz.classList.toggle("painel-recolhido");
      try { localStorage.setItem("painelRecolhido", recolhido ? "1" : "0"); } catch (e) { /* ignora */ }
      atualizarBotoes();
      return;
    }
    if (evento.target.closest("[data-abrir-painel]")) {
      raiz.classList.toggle("painel-aberto");
      atualizarBotoes();
      return;
    }
    // No celular, escolher um cliente fecha o painel.
    if (evento.target.closest(".lista-clientes a")) raiz.classList.remove("painel-aberto");
  });

  document.addEventListener("keydown", function (evento) {
    if (evento.key === "Escape" && raiz.classList.contains("painel-aberto")) {
      raiz.classList.remove("painel-aberto");
      atualizarBotoes();
    }
  });

  document.addEventListener("DOMContentLoaded", atualizarBotoes);
  document.addEventListener("htmx:afterSettle", atualizarBotoes);
})();
