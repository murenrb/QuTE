/*
 * Time-of-use tariff painter (docs/models/utility.md, D-043). Plain JS + the
 * Streamlit component message protocol. Python owns the tariff; this sends one
 * event per user action: paint / update / add / delete.
 */
(function () {
  "use strict";
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var args = null, active = null, painting = false, stroke = [];
  var grid = document.getElementById("grid");
  var ratesBody = document.getElementById("rates");

  function send(type, data) {
    window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type: type }, data), "*");
  }
  function emit(value) {
    value.event_id = Date.now() + "-" + Math.random().toString(36).slice(2, 8);
    send("streamlit:setComponentValue", { value: value, dataType: "json" });
  }
  function resize() { send("streamlit:setFrameHeight", { height: document.body.scrollHeight + 4 }); }
  function colorOf(id) {
    var c = args.categories.find(function (x) { return x.id === id; });
    return c ? c.color : "#ffffff";
  }

  // --- rates --------------------------------------------------------------------
  function renderRates() {
    ratesBody.innerHTML = "";
    args.categories.forEach(function (c) {
      var tr = document.createElement("tr");
      var sw = document.createElement("span");
      sw.className = "swatch" + (c.id === active ? " active" : "");
      sw.style.background = c.color;
      sw.title = "Paint with " + c.name;
      sw.onclick = function () { active = c.id; renderRates(); };
      var name = input("name", c.name, "text"), en = input("num", c.energy, "number"),
          de = input("num", c.demand, "number");
      en.step = "0.01"; en.min = "0"; de.step = "0.5"; de.min = "0";
      [name, en, de].forEach(function (el) {
        el.onchange = function () {
          var energy = parseFloat(en.value), demand = parseFloat(de.value);
          if (!name.value.trim() || isNaN(energy) || isNaN(demand) || energy < 0 || demand < 0) return;
          emit({ kind: "update", id: c.id, name: name.value.trim(), energy: energy, demand: demand });
        };
      });
      var del = document.createElement("button");
      del.className = "del"; del.textContent = "×"; del.title = "Delete this rate";
      del.disabled = args.categories.length <= 1;
      del.onclick = function () { emit({ kind: "delete", id: c.id }); };
      [sw, name, en, de, del].forEach(function (el) {
        var td = document.createElement("td"); td.appendChild(el); tr.appendChild(td);
      });
      ratesBody.appendChild(tr);
    });
  }
  function input(cls, value, type) {
    var el = document.createElement("input");
    el.className = cls; el.type = type; el.value = value;
    return el;
  }
  document.getElementById("add").onclick = function () { emit({ kind: "add" }); };

  // --- grid ---------------------------------------------------------------------
  function paintCell(td) {
    var m = +td.dataset.m, h = +td.dataset.h;
    td.style.background = colorOf(active);
    if (!stroke.some(function (p) { return p[0] === m && p[1] === h; })) stroke.push([m, h]);
  }
  function finishStroke() {
    if (!painting) return;
    painting = false;
    if (stroke.length) emit({ kind: "paint", category: active, cells: stroke });
    stroke = [];
  }
  function renderGrid() {
    grid.innerHTML = "";
    var head = document.createElement("tr");
    var corner = document.createElement("th"); corner.className = "corner"; head.appendChild(corner);
    for (var h = 0; h < 24; h++) {
      (function (h) {
        var th = document.createElement("th"); th.textContent = h; th.title = "Paint hour " + h + " in every month";
        th.onclick = function () {
          var cells = []; for (var m = 0; m < 12; m++) cells.push([m, h]);
          emit({ kind: "paint", category: active, cells: cells });
        };
        head.appendChild(th);
      })(h);
    }
    grid.appendChild(head);
    args.schedule.forEach(function (row, m) {
      var tr = document.createElement("tr");
      var th = document.createElement("th"); th.className = "month"; th.textContent = MONTHS[m];
      th.title = "Paint all of " + MONTHS[m];
      th.onclick = function () {
        var cells = []; for (var h = 0; h < 24; h++) cells.push([m, h]);
        emit({ kind: "paint", category: active, cells: cells });
      };
      tr.appendChild(th);
      row.forEach(function (cid, h) {
        var td = document.createElement("td");
        td.dataset.m = m; td.dataset.h = h; td.style.background = colorOf(cid);
        td.title = MONTHS[m] + " " + h + ":00";
        td.onmousedown = function (e) { e.preventDefault(); painting = true; stroke = []; paintCell(td); };
        td.onmouseenter = function () { if (painting) paintCell(td); };
        tr.appendChild(td);
      });
      grid.appendChild(tr);
    });
  }
  document.addEventListener("mouseup", finishStroke);

  window.addEventListener("message", function (ev) {
    var d = ev.data;
    if (!d || d.type !== "streamlit:render") return;
    args = d.args;
    if (!args.categories.some(function (c) { return c.id === active; })) active = args.cheapest;
    if (painting) return; // don't redraw mid-stroke
    renderRates(); renderGrid(); resize();
  });
  send("streamlit:componentReady", { apiVersion: 1 });
})();
