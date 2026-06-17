// Systronaut control plane -- minimal vanilla JS (CSP: script-src 'self').
// No external dependencies. Progressive enhancement only; forms work without JS.
(function () {
  "use strict";

  // Toggle static-network fields based on the network mode selector.
  function wireNetMode() {
    var sel = document.querySelector("[name=net_mode]");
    var staticFields = document.getElementById("static-net");
    if (!sel || !staticFields) return;
    function sync() {
      staticFields.style.display = sel.value === "static" ? "block" : "none";
    }
    sel.addEventListener("change", sync);
    sync();
  }

  // Reflect the chosen OS into a contextual hint line.
  function wireOsSelection() {
    var tiles = document.querySelectorAll("input[name=os_key]");
    var hint = document.getElementById("os-hint");
    if (!tiles.length) return;
    tiles.forEach(function (t) {
      t.addEventListener("change", function () {
        if (hint) hint.textContent = t.getAttribute("data-notes") || "";
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireNetMode();
    wireOsSelection();
  });
})();
