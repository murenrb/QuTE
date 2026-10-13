/*
 * Site map editor (docs/gui.md → Map, D-030, D-041). Locked map; one object is
 * interactive, depending on `mode`:
 *
 * block   — the data center or a scaled-in-inputs module block:
 *             drag the body   → move
 *             drag an edge    → resize that side, the other adjusts (area fixed)
 *             drag the ◆ knob → rotate (hold Shift to snap to 15°)
 *           Red, live, when any part leaves the boundary or overlaps another block.
 * polygon — a scaled-in-map module area: a handle at every corner; drag one to
 *           reshape. On release Python snaps the new outline to the free land.
 *
 * Every edit is sent on release; Python re-validates it and stays the source of
 * truth. Talks to Streamlit with the plain component message protocol (no build).
 */
(function () {
  "use strict";
  var G = window.FootprintGeometry;
  var SNAP_DEG = 15;
  var KNOB_OFFSET_PX = 26;
  var HANDLE_PX = 10;
  var MIN_HANDLE_BLOCK_PX = 36; // smaller blocks hide edge handles so a drag always moves
  // The edited object lives in its own pane above the other objects, which are
  // redrawn on every render and would otherwise cover it and catch the mouse.
  var EDIT_PANE = "editPane";
  var FT_PER_M = 1 / 0.3048;

  var args = null; // latest args from Python
  var map = null, boundaryLayer = null, contextLayer = null, editLayer = null;
  var interacting = false;
  var shiftDown = false;
  var editor = null; // the active mode's editor ({update(args)})

  // --- Streamlit protocol ----------------------------------------------------
  function send(type, data) {
    window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type: type }, data), "*");
  }
  function setValue(value) { send("streamlit:setComponentValue", { value: value, dataType: "json" }); }
  function setHeight(h) { send("streamlit:setFrameHeight", { height: h }); }
  function eventId() { return Date.now() + "-" + Math.random().toString(36).slice(2, 8); }

  window.addEventListener("message", function (ev) {
    var d = ev.data;
    if (d && d.type === "streamlit:render") onRender(d.args);
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Shift") shiftDown = true; });
  document.addEventListener("keyup", function (e) { if (e.key === "Shift") shiftDown = false; });

  // --- helpers -----------------------------------------------------------------
  function metresPerPixel() {
    var lat = map.getCenter().lat;
    return (40075016.686 * Math.cos(lat * Math.PI / 180)) / Math.pow(2, map.getZoom() + 8);
  }
  function ll(p) { return L.latLng(p[0], p[1]); }
  function labelIcon(text, color) {
    var px = (args && args.label_font_px) || 10;
    return L.divIcon({
      className: "", iconSize: [0, 0], iconAnchor: [0, 0],
      html: '<div class="map-label" style="font-size:' + px + "px;color:" + color + '">' +
        text + "</div>",
    });
  }
  function upperLeft(latlons) { // corner nearest the screen's upper-left
    var o = latlons[0], best = latlons[0], bestScore = -Infinity;
    latlons.forEach(function (p) {
      var xy = G.toLocal(p[0], p[1], o[0], o[1]);
      if (xy[1] - xy[0] > bestScore) { bestScore = xy[1] - xy[0]; best = p; }
    });
    return best;
  }
  function select(owner) {
    setValue({ kind: "select", owner: owner, event_id: eventId() });
  }
  function handleMarker(className, sizePx) {
    return L.marker([0, 0], {
      draggable: true, keyboard: false, zIndexOffset: 1000,
      icon: L.divIcon({ className: className, iconSize: [sizePx, sizePx] }),
    }).addTo(editLayer);
  }

  // --- block mode ----------------------------------------------------------------
  function blockEditor() {
    var fp = null, body = null, knobLine = null, readout = null, label = null, handles = {};

    function colour() {
      var corners = G.corners(fp);
      var clear = (args.others || []).every(function (o) {
        return !G.convexOverlap(corners, o.corners, args.overlap_tolerance_m);
      });
      var inside = G.insideBoundary(fp, args.boundary, args.edge_tolerance_m);
      return inside && clear ? args.colors.ok : args.colors.outside;
    }
    function readoutText() {
      return Math.round(fp.width_m * FT_PER_M).toLocaleString() + " × " +
        Math.round(fp.length_m * FT_PER_M).toLocaleString() + " ft · " +
        Math.round(fp.rotation_deg) + "°";
    }
    function commit() {
      setValue({
        kind: "block", target: args.target, event_id: eventId(),
        center_lat: fp.center_lat, center_lon: fp.center_lon,
        width_m: fp.width_m, length_m: fp.length_m, rotation_deg: fp.rotation_deg,
      });
    }
    function redraw(skip) {
      var c = colour();
      body.setLatLngs(G.corners(fp).map(ll));
      body.setStyle({ color: c, fillColor: c });
      var mpp = metresPerPixel();
      var h = G.handles(fp, KNOB_OFFSET_PX * mpp);
      Object.keys(handles).forEach(function (k) { if (k !== skip) handles[k].setLatLng(ll(h[k])); });
      // Tiny blocks: hide the edge handles so grabbing the block moves it.
      var small = Math.min(fp.width_m, fp.length_m) / mpp < MIN_HANDLE_BLOCK_PX;
      ["e", "w", "n", "s"].forEach(function (k) {
        handles[k].setOpacity(small ? 0 : 1);
        if (small) handles[k].dragging.disable(); else handles[k].dragging.enable();
        var el = handles[k].getElement();
        if (el) el.style.pointerEvents = small ? "none" : "";
      });
      label.setLatLng(ll(upperLeft(G.corners(fp))));
      label.setIcon(labelIcon(args.label || "", c));
      knobLine.setLatLngs([ll(h.n), ll(h.rot)]);
      readout.setLatLng(ll([fp.center_lat, fp.center_lon]));
      readout.setIcon(L.divIcon({
        className: "", iconSize: [0, 0],
        html: interacting ? '<div class="fp-readout">' + readoutText() + "</div>" : "",
      }));
    }
    function makeHandle(key, className, sizePx) {
      var m = handleMarker(className, sizePx);
      m.on("dragstart", function () { interacting = true; });
      m.on("drag", function (e) {
        var p = [e.latlng.lat, e.latlng.lng];
        fp = key === "rot"
          ? G.rotateTo(fp, p, shiftDown ? SNAP_DEG : null)
          : G.resizeEdge(fp, key, p, args.min_aspect, args.max_aspect);
        redraw(key);
      });
      m.on("dragend", function () { interacting = false; redraw(); commit(); });
      return m;
    }

    body = L.polygon([[0, 0]], {
      weight: 2, fillOpacity: 0.35, className: "fp-body", pane: EDIT_PANE,
    }).addTo(editLayer);
    knobLine = L.polyline([], { color: "#1a1a1a", weight: 1, interactive: false }).addTo(editLayer);
    readout = L.marker([0, 0], {
      interactive: false, keyboard: false, icon: L.divIcon({ className: "", iconSize: [0, 0] }),
    }).addTo(editLayer);
    label = L.marker([0, 0], { interactive: false, keyboard: false }).addTo(editLayer);
    handles = {
      e: makeHandle("e", "fp-handle ew", HANDLE_PX), w: makeHandle("w", "fp-handle ew", HANDLE_PX),
      n: makeHandle("n", "fp-handle ns", HANDLE_PX), s: makeHandle("s", "fp-handle ns", HANDLE_PX),
      rot: makeHandle("rot", "fp-knob", HANDLE_PX + 2),
    };
    var start = null;
    body.on("mousedown", function (e) {
      L.DomEvent.stop(e);
      interacting = true;
      start = { pointer: [e.latlng.lat, e.latlng.lng], fp: fp };
      map.on("mousemove", onMove);
      document.addEventListener("mouseup", onUp, { once: true });
    });
    function onMove(e) {
      fp = G.translate(start.fp, start.pointer, [e.latlng.lat, e.latlng.lng]);
      redraw();
    }
    function onUp() {
      map.off("mousemove", onMove);
      interacting = false;
      redraw();
      commit();
    }
    return {
      update: function (a) {
        if (!interacting) { fp = a.footprint; redraw(); }
      },
    };
  }

  // --- polygon mode --------------------------------------------------------------
  function polygonEditor() {
    var pieces = []; // [{exterior: [[lat,lon]...], holes: [...]}]
    var shapes = [], markers = [];

    function commit() {
      setValue({
        kind: "polygon", target: args.target, event_id: eventId(),
        rings: pieces.map(function (p) { return p.exterior; }),
      });
    }
    function rings(piece) { return [piece.exterior.map(ll)].concat(piece.holes.map(function (h) { return h.map(ll); })); }
    function build() {
      editLayer.clearLayers();
      shapes = []; markers = [];
      var color = args.colors.edit;
      if (pieces.length) {
        var big = pieces.reduce(function (a, b) { return b.exterior.length > a.exterior.length ? b : a; });
        L.marker(ll(upperLeft(big.exterior)), {
          interactive: false, keyboard: false, icon: labelIcon(args.label || "", color),
        }).addTo(editLayer);
      }
      pieces.forEach(function (piece, i) {
        shapes.push(L.polygon(rings(piece), {
          color: color, fillColor: color, weight: 2, fillOpacity: 0.3, interactive: false,
          pane: EDIT_PANE,
        }).addTo(editLayer));
        piece.exterior.forEach(function (v, j) {
          var m = handleMarker("fp-handle vertex", HANDLE_PX);
          m.setLatLng(ll(v));
          m.on("dragstart", function () { interacting = true; });
          m.on("drag", function (e) {
            piece.exterior[j] = [e.latlng.lat, e.latlng.lng];
            shapes[i].setLatLngs(rings(piece));
          });
          m.on("dragend", function () { interacting = false; commit(); });
          markers.push(m);
        });
      });
    }
    return {
      update: function (a) {
        if (interacting) return;
        pieces = (a.pieces || []).map(function (p) {
          return { exterior: p.exterior.map(function (v) { return v.slice(); }), holes: p.holes || [] };
        });
        build();
      },
    };
  }

  // --- map ---------------------------------------------------------------------------
  function createMap(a) {
    var el = document.getElementById("map");
    el.style.height = a.height + "px";
    document.documentElement.style.setProperty("--map-outline", a.colors.outline);
    map = L.map(el, {
      dragging: false, scrollWheelZoom: false, doubleClickZoom: false, touchZoom: false,
      boxZoom: false, keyboard: false, zoomControl: false, attributionControl: true,
    });
    L.tileLayer(a.tiles_url, {
      maxNativeZoom: a.max_native_zoom, maxZoom: a.max_zoom, attribution: a.attribution,
    }).addTo(map);
    L.control.scale().addTo(map);
    // Same center + zoom as the Location tab (D-031). Fitting bounds instead can
    // round down a whole zoom level when this panel is a pixel smaller.
    if (a.center && a.zoom !== null && a.zoom !== undefined) map.setView(a.center, a.zoom);
    else if (a.view) map.fitBounds([[a.view[0], a.view[1]], [a.view[2], a.view[3]]]);
    else map.setView(a.fallback_center, a.fallback_zoom);

    boundaryLayer = L.polygon([], {
      color: a.colors.boundary, weight: 2, fillOpacity: 0.04, interactive: false,
    }).addTo(map);
    var editPane = map.createPane(EDIT_PANE);
    editPane.style.zIndex = 450; // above overlays (400), below markers (600)
    // The pane's SVG spans the whole map: let clicks through to the objects below;
    // Leaflet re-enables pointer events on the edited shape itself (interactive path).
    editPane.style.pointerEvents = "none";
    contextLayer = L.layerGroup().addTo(map); // other areas and blocks, read-only
    editLayer = L.layerGroup().addTo(map);
    editor = a.mode === "polygon" ? polygonEditor() : blockEditor();
    setHeight(a.height);
    map.invalidateSize(); // iframe may have resized after creation; keeps the center fixed
  }

  function addLabel(text, at, color) {
    if (!text || !at) return;
    L.marker(ll(at), { interactive: false, keyboard: false, icon: labelIcon(text, color) })
      .addTo(contextLayer);
  }
  function drawContext(a) {
    contextLayer.clearLayers();
    // Other objects: read-only here; clicking one selects it (opens its tab/module).
    (a.areas || []).forEach(function (area) {
      L.polygon(area.rings.map(function (r) { return r.map(ll); }), {
        color: area.color, fillColor: area.color, weight: 1.5, fillOpacity: 0.3,
        className: "map-select",
      }).on("click", function () { select(area.owner); }).addTo(contextLayer);
      addLabel(area.label, area.label_at, area.color);
    });
    (a.others || []).forEach(function (o) {
      L.polygon(o.corners.map(ll), {
        color: o.color, fillColor: o.color, weight: 2, fillOpacity: 0.35, className: "map-select",
      }).on("click", function () { select(o.owner); }).addTo(contextLayer);
      addLabel(o.label, o.label_at, o.color);
    });
    if (a.property_label) addLabel(a.property_label.text, a.property_label.at, a.colors.boundary);
  }

  function onRender(a) {
    args = a;
    if (!map) createMap(a);
    boundaryLayer.setLatLngs((a.boundary || []).map(ll));
    drawContext(a);
    editor.update(a);
  }

  send("streamlit:componentReady", { apiVersion: 1 });
})();
