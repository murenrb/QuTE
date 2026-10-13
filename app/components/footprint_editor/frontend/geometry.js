/*
 * Footprint geometry for live editing in the browser.
 *
 * Mirrors core/geometry/footprint.py (the source of truth): width runs east–west
 * at rotation 0, rotation is clockwise in [0, 180), area = width × length and is
 * held fixed while resizing. Local frame: metres around the block centre using
 * the WGS84 radii of curvature there (agrees with the Python azimuthal-
 * equidistant frame to well under 1 cm over a site). Python re-checks every
 * edit on release.
 *
 * Works in the browser (window.FootprintGeometry) and in Node (module.exports),
 * so tests/unit/test_footprint_editor_js.py can compare it with the Python code.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.FootprintGeometry = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var A = 6378137.0; // WGS84 semi-major axis, m
  var E2 = 0.00669437999014; // WGS84 first eccentricity squared
  var DEG = Math.PI / 180;

  // Metres per degree of latitude / longitude at lat0, from the WGS84 radii of
  // curvature (meridional M, prime vertical N) — matches the Python frame.
  function scales(lat0) {
    var s = Math.sin(lat0 * DEG), w = 1 - E2 * s * s;
    var m = (A * (1 - E2)) / Math.pow(w, 1.5), n = A / Math.sqrt(w);
    return [n * Math.cos(lat0 * DEG) * DEG, m * DEG];
  }

  function toLocal(lat, lon, lat0, lon0) {
    var k = scales(lat0);
    return [(lon - lon0) * k[0], (lat - lat0) * k[1]];
  }

  function toLatLon(x, y, lat0, lon0) {
    var k = scales(lat0);
    return [lat0 + y / k[1], lon0 + x / k[0]];
  }

  // Block-local (x along width, y along length) → local east/north, clockwise rotation.
  function rotate(x, y, deg) {
    var t = deg * DEG, c = Math.cos(t), s = Math.sin(t);
    return [x * c + y * s, -x * s + y * c];
  }

  function unrotate(e, n, deg) {
    return rotate(e, n, -deg);
  }

  function normalizeRotation(deg) {
    return ((deg % 180) + 180) % 180;
  }

  function clampWidth(width, area, minAspect, maxAspect) {
    var wMax = Math.sqrt(area / minAspect), wMin = Math.sqrt(area / maxAspect);
    return Math.min(Math.max(width, wMin), wMax);
  }

  /** Corners [lat, lon], same order as footprint_corners() in Python. */
  function corners(fp) {
    var hw = fp.width_m / 2, hl = fp.length_m / 2;
    return [[-hw, hl], [hw, hl], [hw, -hl], [-hw, -hl]].map(function (p) {
      var r = rotate(p[0], p[1], fp.rotation_deg);
      return toLatLon(r[0], r[1], fp.center_lat, fp.center_lon);
    });
  }

  /** Handle positions [lat, lon]: edge midpoints and the rotate knob. */
  function handles(fp, knobOffsetM) {
    var hw = fp.width_m / 2, hl = fp.length_m / 2;
    var local = { e: [hw, 0], w: [-hw, 0], n: [0, hl], s: [0, -hl], rot: [0, hl + knobOffsetM] };
    var out = {};
    Object.keys(local).forEach(function (k) {
      var r = rotate(local[k][0], local[k][1], fp.rotation_deg);
      out[k] = toLatLon(r[0], r[1], fp.center_lat, fp.center_lon);
    });
    return out;
  }

  function translate(fp, fromLatLon, toLatLonPt) {
    return Object.assign({}, fp, {
      center_lat: fp.center_lat + (toLatLonPt[0] - fromLatLon[0]),
      center_lon: fp.center_lon + (toLatLonPt[1] - fromLatLon[1]),
    });
  }

  /**
   * Drag one edge (e/w change width, n/s change length); the opposite edge stays
   * put and the other dimension adjusts so the area is unchanged.
   */
  function resizeEdge(fp, edge, pointLatLon, minAspect, maxAspect) {
    var area = fp.width_m * fp.length_m;
    var p = toLocal(pointLatLon[0], pointLatLon[1], fp.center_lat, fp.center_lon);
    var q = unrotate(p[0], p[1], fp.rotation_deg); // pointer in block-local metres
    var width, length, shift; // shift of the centre along the dragged axis (block-local)
    if (edge === "e" || edge === "w") {
      var sign = edge === "e" ? 1 : -1;
      var fixed = -sign * fp.width_m / 2; // opposite edge
      width = clampWidth(Math.abs(q[0] - fixed), area, minAspect, maxAspect);
      length = area / width;
      shift = [fixed + sign * width / 2, 0];
    } else {
      var sgn = edge === "n" ? 1 : -1;
      var fixedY = -sgn * fp.length_m / 2;
      var rawLength = Math.abs(q[1] - fixedY);
      width = clampWidth(area / rawLength, area, minAspect, maxAspect);
      length = area / width;
      shift = [0, fixedY + sgn * length / 2];
    }
    var d = rotate(shift[0], shift[1], fp.rotation_deg);
    var c = toLatLon(d[0], d[1], fp.center_lat, fp.center_lon);
    return Object.assign({}, fp, {
      center_lat: c[0], center_lon: c[1], width_m: width, length_m: length,
    });
  }

  /** Rotate so the knob points at the pointer; optional snap step in degrees. */
  function rotateTo(fp, pointLatLon, snapDeg) {
    var p = toLocal(pointLatLon[0], pointLatLon[1], fp.center_lat, fp.center_lon);
    var bearing = Math.atan2(p[0], p[1]) / DEG; // clockwise from north
    if (snapDeg) bearing = Math.round(bearing / snapDeg) * snapDeg;
    return Object.assign({}, fp, { rotation_deg: normalizeRotation(bearing) });
  }

  // --- inside-boundary check (warning colour while dragging) -----------------

  function pointInPolygon(pt, poly) {
    var inside = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var a = poly[i], b = poly[j];
      if ((a[1] > pt[1]) !== (b[1] > pt[1]) &&
          pt[0] < ((b[0] - a[0]) * (pt[1] - a[1])) / (b[1] - a[1]) + a[0]) inside = !inside;
    }
    return inside;
  }

  function distToSegment(p, a, b) {
    var dx = b[0] - a[0], dy = b[1] - a[1];
    var t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1);
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
  }

  function properCross(a, b, c, d) {
    function orient(p, q, r) { return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]); }
    var o1 = orient(a, b, c), o2 = orient(a, b, d), o3 = orient(c, d, a), o4 = orient(c, d, b);
    return o1 * o2 < 0 && o3 * o4 < 0;
  }

  /** True if the whole block is inside the boundary (touching within tol counts). */
  function insideBoundary(fp, ring, tolM) {
    if (!ring || ring.length < 3) return true; // nothing to be outside of
    var lat0 = fp.center_lat, lon0 = fp.center_lon;
    var poly = ring.map(function (p) { return toLocal(p[0], p[1], lat0, lon0); });
    var block = corners(fp).map(function (p) { return toLocal(p[0], p[1], lat0, lon0); });
    function near(pt) {
      for (var i = 0; i < poly.length; i++) {
        if (distToSegment(pt, poly[i], poly[(i + 1) % poly.length]) <= tolM) return true;
      }
      return false;
    }
    for (var k = 0; k < 4; k++) {
      if (!pointInPolygon(block[k], poly) && !near(block[k])) return false;
    }
    for (var i = 0; i < 4; i++) {
      for (var j = 0; j < poly.length; j++) {
        if (properCross(block[i], block[(i + 1) % 4], poly[j], poly[(j + 1) % poly.length])) {
          return false; // a concave corner of the parcel cuts into the block
        }
      }
    }
    return true;
  }

  /**
   * Do two convex polygons ([lat, lon] corners) overlap by more than tolM metres?
   * Separating-axis test in a local frame; touching edges do not count.
   */
  function convexOverlap(aLatLon, bLatLon, tolM) {
    var lat0 = aLatLon[0][0], lon0 = aLatLon[0][1];
    var a = aLatLon.map(function (p) { return toLocal(p[0], p[1], lat0, lon0); });
    var b = bLatLon.map(function (p) { return toLocal(p[0], p[1], lat0, lon0); });
    var polys = [a, b];
    for (var k = 0; k < 2; k++) {
      var poly = polys[k];
      for (var i = 0; i < poly.length; i++) {
        var p1 = poly[i], p2 = poly[(i + 1) % poly.length];
        var nx = p1[1] - p2[1], ny = p2[0] - p1[0];
        var len = Math.hypot(nx, ny) || 1;
        nx /= len; ny /= len;
        var aMin = Infinity, aMax = -Infinity, bMin = Infinity, bMax = -Infinity;
        a.forEach(function (q) { var d = q[0] * nx + q[1] * ny; aMin = Math.min(aMin, d); aMax = Math.max(aMax, d); });
        b.forEach(function (q) { var d = q[0] * nx + q[1] * ny; bMin = Math.min(bMin, d); bMax = Math.max(bMax, d); });
        if (Math.min(aMax, bMax) - Math.max(aMin, bMin) <= tolM) return false; // separated
      }
    }
    return true;
  }

  return {
    convexOverlap: convexOverlap,
    toLocal: toLocal, toLatLon: toLatLon, corners: corners, handles: handles,
    translate: translate, resizeEdge: resizeEdge, rotateTo: rotateTo,
    insideBoundary: insideBoundary, clampWidth: clampWidth, normalizeRotation: normalizeRotation,
  };
});
