// Systronaut control plane -- minimal vanilla JS (CSP: script-src 'self').
// Loaded from templates/base.html. No external deps. Forms work without JS.
// User phase: code prep only — no deploy.
(function () {
  "use strict";

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

  function wireHvFilter() {
    var input = document.getElementById("hv-filter");
    var table = document.getElementById("hv-table");
    if (!input || !table) return;
    var rows = table.querySelectorAll("tbody tr");
    input.addEventListener("input", function () {
      var q = (input.value || "").toLowerCase().trim();
      rows.forEach(function (row) {
        var hay = (row.getAttribute("data-filter") || row.textContent || "").toLowerCase();
        row.style.display = !q || hay.indexOf(q) !== -1 ? "" : "none";
      });
    });
  }

  function drawLineChart(canvas, color) {
    if (!canvas || !canvas.getContext) return;
    var raw = canvas.getAttribute("data-series") || "";
    var ymax = parseFloat(canvas.getAttribute("data-ymax") || "100") || 100;
    var values = raw.split(",").map(function (s) { return parseFloat(s) || 0; });
    if (!values.length) values = [0];
    var ctx = canvas.getContext("2d");
    var dpr = window.devicePixelRatio || 1;
    var cssW = canvas.clientWidth || canvas.width;
    var cssH = canvas.clientHeight || canvas.height;
    canvas.width = Math.floor(cssW * dpr);
    canvas.height = Math.floor(cssH * dpr);
    ctx.scale(dpr, dpr);
    var padL = 36, padR = 8, padT = 12, padB = 20;
    var w = cssW - padL - padR;
    var h = cssH - padT - padB;
    ctx.clearRect(0, 0, cssW, cssH);
    ctx.strokeStyle = "#e6eaf1";
    ctx.lineWidth = 1;
    for (var g = 0; g <= 4; g++) {
      var gy = padT + (h * g) / 4;
      ctx.beginPath();
      ctx.moveTo(padL, gy);
      ctx.lineTo(padL + w, gy);
      ctx.stroke();
      ctx.fillStyle = "#8a94a6";
      ctx.font = "11px sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(String(Math.round(ymax * (1 - g / 4))), padL - 6, gy + 3);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    values.forEach(function (v, i) {
      var x = padL + (w * i) / Math.max(1, values.length - 1);
      var y = padT + h - (Math.min(v, ymax) / ymax) * h;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  function wireCharts() {
    drawLineChart(document.getElementById("chart-cpu"), "#3b6cff");
    drawLineChart(document.getElementById("chart-mem"), "#e8a317");
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireNetMode();
    wireOsSelection();
    wireHvFilter();
    wireCharts();
  });
})();
