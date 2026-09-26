/* ==========================================================================
   C15c — AMR Command Center
   Read-only operator view over the existing AMR backend.

   Hard rules this file obeys:
   * It is a VIEW. It never decides safety, never runs navigation, and never
     sends motion. The only writes it can make are the existing replay
     transport calls, which are display-only on the server side. /command stays
     the sole actuator path and this file never touches it.
   * It shows UNAVAILABLE as "n/a". A missing sensor is never drawn as 0, and a
     missing value is never interpolated to make a chart look complete.
   * The backend is authoritative. Every number here came from
     GET /dashboard/state (or the C9/C10/C14b endpoints it embeds).
   ========================================================================== */
"use strict";

var POLL_MS = 1000;

var CC = {
  state: null,
  lastOk: 0,
  filter: "ALL",
  logEvents: [],
  // 2D map view
  map: { zoom: 1, cx: null, cy: null, showRoute: true, showTrail: true,
         showHaz: true, showZones: true },
  // 3D twin view
  twin: { yaw: 0.9, pitch: 0.62, dist: 9, target: [0, 0, 0], follow: false,
          showHaz: true, showRoute: true, gl: null, ok: false, drag: null }
};

/* -- tiny DOM helpers ----------------------------------------------------- */
function $(id) { return document.getElementById(id); }
function txt(id, v) {
  var el = $(id);
  if (el) el.textContent = (v === null || v === undefined || v === "") ? "n/a" : String(v);
}
function isNum(v) { return typeof v === "number" && isFinite(v); }
function na(v, digits) {
  if (!isNum(v)) return "n/a";
  return v.toFixed(digits === undefined ? 2 : digits);
}
function esc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function clock(t) {
  if (!isNum(t)) return "--:--:--";
  var d = new Date(t * 1000);
  return String(d.getHours()).padStart(2, "0") + ":" +
         String(d.getMinutes()).padStart(2, "0") + ":" +
         String(d.getSeconds()).padStart(2, "0");
}
function setChip(id, textId, label, cls) {
  var chip = $(id);
  txt(textId, label);
  if (chip) {
    chip.className = "chip" + (cls ? " " + cls : "");
  }
}
function bar(id, frac, cls) {
  var el = $(id);
  if (!el) return;
  var inner = el.firstElementChild;
  if (!isNum(frac)) {
    inner.style.width = "0%";
    el.className = "bar" + (cls ? " " + cls : "");
    return;
  }
  inner.style.width = Math.max(0, Math.min(1, frac)) * 100 + "%";
  el.className = "bar" + (cls ? " " + cls : "");
}

/* -- data ---------------------------------------------------------------- */
function fetchJSON(path) {
  return fetch(path, { cache: "no-store" }).then(function (r) {
    if (!r.ok) throw new Error(path + " -> " + r.status);
    return r.json();
  });
}

function poll() {
  fetchJSON("/dashboard/state").then(function (s) {
    CC.state = s;
    CC.lastOk = Date.now();
    renderAll(s);
  }).catch(function () {
    // A dropped poll must not blank the console: say so, keep the last data.
    setChip("conn-badge", "conn-text", "DISCONNECTED", "crit");
  });
}

function renderAll(s) {
  renderHeader(s);
  renderRobot(s);
  renderSafety(s);
  renderMission(s);
  renderHazards(s);
  renderLog(s);
  renderCharts(s);
  renderReplay(s);
  renderMap(s);
  renderTwin(s);
  renderCamera(s);
  // C5e: the operations panels, from the `ops` block in this same payload.
  renderOps(s);
  applyEventFilter();
}

function renderHeader(s) {
  var replay = s.replay || {};
  var isReplay = !!replay.active;
  // LIVE vs REPLAY must be unmistakable, so the badge text, its colour and the
  // banner all move together.
  setChip("mode-badge", "mode-text", isReplay ? "REPLAY" : "LIVE",
          isReplay ? "warn" : "info");
  var src = s.source || (s.twin && s.twin.source) || "UNKNOWN";
  setChip("src-badge", "src-text", src, src === "LIVE" ? "ok" : "info");
  var conn = !!(s.system && s.system.connected);
  setChip("conn-badge", "conn-text", conn ? "ONLINE" : "OFFLINE",
          conn ? "ok" : "crit");
  // C15d: SIMULATION must never read as live hardware. The badge names the
  // *backing* of the data, which is a different question from whether the
  // process is reachable (that is the ONLINE chip beside it).
  var simulated = !!s.simulated || src === "SIMULATION";
  setChip("hw-badge", "hw-text",
          simulated ? "SIMULATION" : (src === "LIVE" ? "LIVE HARDWARE" : src),
          simulated ? "warn" : (src === "LIVE" ? "ok" : "info"));
  var sf = s.safety || {};
  var act = sf.action || null;
  var estop = !!sf.emergency_stop;
  setChip("safety-badge", "safety-text", estop ? "E-STOP" : (act || "IDLE"),
          estop ? "crit" : (act === "PROCEED" ? "ok" : "warn"));
  txt("clock-text", clock(s.timestamp));

  var banner = $("sim-banner");
  if (banner) {
    var msg = "";
    if (isReplay) {
      msg = "REPLAY MODE — showing recorded telemetry. The live robot state is " +
            "unaffected and is not modified by replay.";
    } else if (s.simulated || src === "SIMULATION") {
      msg = "SIMULATED DATA — this console is showing mock/simulated telemetry. " +
            "No physical robot, sensor or camera is involved.";
    }
    banner.textContent = msg;
    banner.hidden = !msg;
  }
}

function renderRobot(s) {
  var r = s.robot || {};
  var sys = s.system || {};
  var p = r.position || {};
  var yaw = r.orientation || {};
  var vel = r.velocity || {};
  var nav = s.navigation || {};
  txt("r-id", r.robot_id);
  txt("r-mode", r.mode);
  txt("r-pos", (isNum(p.x) && isNum(p.y))
    ? (p.x.toFixed(2) + " m, " + p.y.toFixed(2) + " m") : "n/a");
  txt("r-yaw", isNum(yaw.yaw) ? yaw.yaw.toFixed(2) + " rad" : "n/a");
  txt("r-speed", isNum(vel.linear) ? vel.linear.toFixed(2) + " m/s" : "n/a");
  txt("r-nav", nav.state);
  var batt = s.battery || {};
  txt("r-batt", isNum(batt.percentage) ? batt.percentage.toFixed(0) + " %" : "n/a");
  txt("r-up", isNum(sys.uptime) ? Math.round(sys.uptime) + " s" : "n/a");
  var rec = s.recording || {};
  txt("r-rec", rec.active ? (rec.recording_id || "active") : "inactive");
}

function renderSafety(s) {
  var sf = s.safety || {};
  var hz = s.hazards || {};
  var act = sf.action || null;
  var estop = !!sf.emergency_stop;
  var active = isNum(hz.active) ? hz.active : 0;
  var critical = isNum(hz.critical) ? hz.critical : 0;
  var blocked = estop || act === "STOP" || act === "WAIT" || critical > 0;
  var warn = !blocked && (act === "TURN" || act === "REPLAN" || active > 0);

  var panel = $("safety-panel");
  var cls = blocked ? "crit" : (warn ? "warn" : "ok");
  if (panel) panel.className = "safety " + cls;
  txt("s-icon", blocked ? "⛔" : (warn ? "⚠" : "●"));
  txt("s-head", estop ? "EMERGENCY STOP — MOTION BLOCKED"
    : (blocked ? "MOTION BLOCKED — " + (act || "HAZARD")
    : (warn ? "CAUTION — " + (act || "HAZARD PRESENT")
    : (act ? "MOTION PERMITTED — " + act : "IDLE — NO ACTIVE HAZARD"))));
  var reasons = sf.reasons || [];
  var why = reasons.length ? reasons.join("; ")
    : (active ? (active + " active hazard(s), " + critical + " critical") : "");
  txt("s-why", why
    ? why
    : "The backend safety layer is authoritative; this panel only displays it.");
  txt("s-action", act);
  txt("s-state", sf.state);
  txt("s-estop", estop ? "ACTIVE" : (sf.availability === "AVAILABLE" ? "armed" : "n/a"));
  txt("s-avoid", (sf.avoidance && (sf.avoidance.action || sf.avoidance)) || "none");
  txt("s-hazcount", active + " active / " + critical + " critical");
}

function renderHazards(s) {
  var hz = s.hazards || {};
  // C15d: the raw C7 hazard section is an OBJECT ({state, active, recent}),
  // not a list. Reading `hz.items` off a dict returns the built-in `.items`
  // METHOD, which is truthy and then explodes on `.filter` -- so the list is
  // taken from `active`, with `hazard_list.active` as the fallback.
  var raw = (s.hazard_list && s.hazard_list.active) || hz.active_items || [];
  var list = Array.isArray(raw) ? raw : [];
  var placed = hz.placed || 0, unlocated = hz.unlocated || 0;
  txt("haz-count", (isNum(hz.active) ? hz.active : list.length) + " active");
  var el = $("haz-list");
  if (!el) return;
  if (!list || !list.length) {
    el.innerHTML = '<p class="empty-note">No active hazards.</p>';
    return;
  }
  var rows = list.map(function (h) {
    var crit = String(h.severity || "").toUpperCase() === "CRITICAL";
    // The C9/C13 rule, stated in the UI: an image-space bbox is NOT a world
    // position, and we say so rather than pretending otherwise.
    var where;
    if (h.location) {
      where = "world (" + Number(h.location.x).toFixed(2) + ", " +
              Number(h.location.y).toFixed(2) + " m)";
    } else if ((h.metadata || {}).bbox) {
      where = "image-space only — not placed on the map";
    } else {
      where = "no location reported";
    }
    return '<div class="hz-item' + (crit ? " crit" : "") + '">' +
      '<div class="top"><span class="kind">' + esc(h.kind) + "</span>" +
      '<span class="mono dim">' + esc(h.severity || "") + "</span></div>" +
      '<div class="meta">conf ' + (isNum(h.confidence) ? h.confidence.toFixed(2) : "n/a") +
      " &middot; src " + esc(h.source || "unknown") + "</div>" +
      '<div class="where">' + esc(where) + "</div></div>";
  });
  if (unlocated) {
    rows.push('<p class="empty-note">' + unlocated +
      " hazard(s) have no world location and are not drawn on the map.</p>");
  }
  el.innerHTML = rows.join("");
}

function renderLog(s) {
  var hist = s.history || {};
  var evs = (hist.events && hist.events.events) || [];
  CC.logEvents = evs;
  txt("log-count", evs.length + " shown");
  var box = $("log");
  if (!box) return;
  var f = CC.filter;
  var rows = evs.filter(function (e) {
    if (f === "ALL") return true;
    if (f === "INFO" || f === "WARNING" || f === "CRITICAL") {
      return String(e.level).toUpperCase() === f;
    }
    return String(e.category).toUpperCase() === f;
  });
  if (!rows.length) {
    box.innerHTML = '<p class="log-empty">No events match this filter yet.</p>';
    return;
  }
  box.innerHTML = rows.map(function (e) {
    var lvl = String(e.level || "INFO").toUpperCase();
    return '<div class="log-row ' + esc(lvl) + '">' +
      '<span class="t">' + esc(clock(e.t)) + "</span>" +
      '<span class="lvl">' + esc(lvl) + "</span>" +
      '<span class="cat">' + esc(e.category || "") + "</span>" +
      '<span class="msg">' + esc(e.message) + "</span></div>";
  }).join("");
}

function drawChart(canvas, samples, key, colour) {
  if (!canvas) return;
  var dpr = Math.min(2, window.devicePixelRatio || 1);
  var w = Math.max(1, Math.round(canvas.clientWidth * dpr));
  var h = Math.max(1, Math.round(canvas.clientHeight * dpr));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  var g = canvas.getContext("2d");
  g.clearRect(0, 0, w, h);
  var vals = samples.map(function (s) { return s.v[key]; });
  var known = vals.filter(isNum);
  // No real data -> say so. Drawing a flat zero line would be a lie.
  if (known.length < 2) {
    g.fillStyle = "#64768c";
    g.font = (11 * dpr) + "px system-ui, sans-serif";
    g.textAlign = "center";
    g.fillText(known.length ? "1 sample — need more data" : "NOT AVAILABLE",
               w / 2, h / 2);
    return;
  }
  var lo = Math.min.apply(null, known), hi = Math.max.apply(null, known);
  if (hi === lo) { hi = lo + 1; lo -= 1; }
  var pad = (hi - lo) * 0.15;
  lo -= pad; hi += pad;
  g.strokeStyle = "#1b2534";
  g.beginPath(); g.moveTo(0, h - 1); g.lineTo(w, h - 1); g.stroke();
  g.strokeStyle = colour;
  g.lineWidth = 1.6 * dpr;
  g.beginPath();
  var started = false;
  vals.forEach(function (v, i) {
    if (!isNum(v)) { started = false; return; }   // a real gap, not a bridged line
    var x = (i / Math.max(1, vals.length - 1)) * w;
    var y = h - ((v - lo) / (hi - lo)) * h;
    if (!started) { g.moveTo(x, y); started = true; } else { g.lineTo(x, y); }
  });
  g.stroke();
}

function renderCharts(s) {
  var hist = s.history || {};
  var samples = (hist.series && hist.series.samples) || [];
  var metrics = (hist.series && hist.series.metrics) || {};
  var speed = samples.map(function (x) { return x.v.speed; }).filter(isNum);
  txt("c-speed", speed.length ? speed[speed.length - 1].toFixed(2) + " m/s" : "n/a");
  drawChart($("c-speed-c"), samples, "speed", "#3d8bfd");
  var batt = samples.map(function (x) { return x.v.battery; }).filter(isNum);
  txt("c-batt", batt.length ? batt[batt.length - 1].toFixed(0) + " %" : "n/a");
  drawChart($("c-batt-c"), samples, "battery", "#2fbf71");
}

/* -- 2D warehouse map (renders the C9 MapSnapshot, adds no map semantics) --- */
var MAP_W = 1200, MAP_H = 520, MAP_PAD = 40;

function mapBounds(map) {
  var st = (map && map.warehouse) || {};
  var b = st.bounds;
  if (b && isNum(b.x_min) && isNum(b.x_max)) return b;
  // Fall back to the data actually present so the view is never empty.
  var xs = [], ys = [];
  var push = function (p) { if (p && isNum(p.x) && isNum(p.y)) { xs.push(p.x); ys.push(p.y); } };
  ((map && map.robot) ? [map.robot] : []).forEach(push);
  ((map && map.goal) ? [map.goal] : []).forEach(push);
  ((map && map.route) || []).forEach(push);
  ((map && map.path) || []).forEach(push);
  ((st.waypoints) || []).forEach(push);
  if (!xs.length) return null;
  return { x_min: Math.min.apply(null, xs), x_max: Math.max.apply(null, xs),
           y_min: Math.min.apply(null, ys), y_max: Math.max.apply(null, ys) };
}

function renderMap(s) {
  var svg = $("m-svg");
  if (!svg) return;
  var map = s.map || {};
  var b = mapBounds(map);
  if (!b) {
    svg.innerHTML = "";
    $("m-empty").hidden = false;
    txt("m-badge", "NO DATA");
    txt("map-note", "");
    return;
  }
  $("m-empty").hidden = true;
  var spanX = Math.max(0.5, b.x_max - b.x_min), spanY = Math.max(0.5, b.y_max - b.y_min);
  var scale = Math.min((MAP_W - 2 * MAP_PAD) / spanX,
                       (MAP_H - 2 * MAP_PAD) / spanY) * CC.map.zoom;
  var offX = CC.map.cx === null ? (b.x_min + b.x_max) / 2 : CC.map.cx;
  var offY = CC.map.cy === null ? (b.y_min + b.y_max) / 2 : CC.map.cy;
  // One world -> screen conversion for the whole view. World y is up, SVG y is
  // down, so the sign flips exactly once, here.
  function X(x) { return MAP_W / 2 + (x - offX) * scale; }
  function Y(y) { return MAP_H / 2 - (y - offY) * scale; }

  var out = [];
  out.push('<rect x="0" y="0" width="' + MAP_W + '" height="' + MAP_H +
           '" fill="#060a11"/>');
  // metric grid
  var step = spanX > 40 ? 5 : (spanX > 12 ? 2 : 1);
  for (var gx = Math.ceil(b.x_min / step) * step; gx <= b.x_max; gx += step) {
    out.push('<line x1="' + X(gx).toFixed(1) + '" y1="0" x2="' + X(gx).toFixed(1) +
             '" y2="' + MAP_H + '" stroke="#141d29" stroke-width="1"/>');
  }
  for (var gy = Math.ceil(b.y_min / step) * step; gy <= b.y_max; gy += step) {
    out.push('<line x1="0" y1="' + Y(gy).toFixed(1) + '" x2="' + MAP_W +
             '" y2="' + Y(gy).toFixed(1) + '" stroke="#141d29" stroke-width="1"/>');
  }
  // data extent — explicitly NOT presented as a surveyed wall
  out.push('<rect x="' + X(b.x_min).toFixed(1) + '" y="' + Y(b.y_max).toFixed(1) +
           '" width="' + (spanX * scale).toFixed(1) + '" height="' + (spanY * scale).toFixed(1) +
           '" fill="none" stroke="#2f4258" stroke-width="1" stroke-dasharray="5 4"/>');
  var st = map.warehouse || {};
  if (CC.map.showZones) {
    (st.zones || []).forEach(function (z) {
      out.push('<rect x="' + X(z.x_min).toFixed(1) + '" y="' + Y(z.y_max).toFixed(1) +
               '" width="' + Math.max(2, (z.x_max - z.x_min) * scale).toFixed(1) +
               '" height="' + Math.max(2, (z.y_max - z.y_min) * scale).toFixed(1) +
               '" fill="#e8a33d" fill-opacity="0.14" stroke="#e8a33d" stroke-width="1"/>');
    });
  }
  (st.waypoints || []).forEach(function (w) {
    if (!isNum(w.x) || !isNum(w.y)) return;
    out.push('<circle cx="' + X(w.x).toFixed(1) + '" cy="' + Y(w.y).toFixed(1) +
             '" r="5" fill="#3d8bfd" fill-opacity="0.85"/>');
    out.push('<text x="' + (X(w.x) + 9).toFixed(1) + '" y="' + (Y(w.y) + 4).toFixed(1) +
             '" fill="#8fa3bd" font-size="11" font-family="monospace">' +
             esc(w.name) + "</text>");
  });
  if (CC.map.showTrail && (map.path || []).length > 1) {
    out.push('<polyline points="' + map.path.map(function (p) {
      return X(p.x).toFixed(1) + "," + Y(p.y).toFixed(1); }).join(" ") +
      '" fill="none" stroke="#5a6b80" stroke-width="2" stroke-dasharray="3 3"/>');
  }
  if (CC.map.showRoute && (map.route || []).length > 1) {
    out.push('<polyline points="' + map.route.map(function (p) {
      return X(p.x).toFixed(1) + "," + Y(p.y).toFixed(1); }).join(" ") +
      '" fill="none" stroke="#3d8bfd" stroke-width="2.5"/>');
  }
  if (map.goal) {
    out.push('<circle cx="' + X(map.goal.x).toFixed(1) + '" cy="' + Y(map.goal.y).toFixed(1) +
             '" r="8" fill="none" stroke="#a855f7" stroke-width="2.5"/>');
  }
  if (CC.map.showHaz) {
    (map.hazards || []).forEach(function (h) {
      // Only placed hazards appear here: MapSnapshot.hazards is populated only
      // for events with a real world location.
      var crit = String(h.severity || "").toUpperCase() === "CRITICAL";
      out.push('<circle cx="' + X(h.x).toFixed(1) + '" cy="' + Y(h.y).toFixed(1) +
               '" r="' + (crit ? 8 : 6) + '" fill="' + (crit ? "#ef4d5a" : "#e8a33d") +
               '" fill-opacity="0.9"><title>' + esc(h.kind) + " " +
               (isNum(h.confidence) ? h.confidence.toFixed(2) : "") + "</title></circle>");
    });
  }
  var rb = map.robot;
  if (rb && isNum(rb.x) && isNum(rb.y)) {
    // The arrow is rotated by the real yaw, so heading is visible at a glance.
    out.push('<g transform="translate(' + X(rb.x).toFixed(1) + "," + Y(rb.y).toFixed(1) +
             ") rotate(" + (-(rb.yaw || 0) * 180 / Math.PI).toFixed(1) + ')">' +
             '<polygon points="13,0 -9,8 -9,-8" fill="#2fbf71" stroke="#0b0f16" ' +
             'stroke-width="1.5"><title>AMR yaw ' + (rb.yaw || 0).toFixed(2) + " rad</title></polygon></g>");
  }
  svg.innerHTML = out.join("");
  txt("m-badge", (s.map.source || "?") + " \u00b7 " + ((map.hazards || []).length) + " hazard(s)");
  txt("map-note", (st.note || "") + (CC.map.showHaz ? "" : " \u00b7 hazards hidden"));
}

/* -- camera (C8 / C13 overlay) ------------------------------------------- */
function renderCamera(s) {
  var c = s.camera || {};
  var st = c.status || "UNAVAILABLE";
  var badge = $("cam-badge");
  var img = $("cam-img");
  var empty = $("cam-empty");
  txt("cam-status", st);
  txt("cam-source", c.source_name || c.device);
  txt("cam-res", (isNum(c.width) && isNum(c.height)) ? (c.width + " \u00d7 " + c.height) : "n/a");
  txt("cam-frame", isNum(c.frame_id) ? "#" + c.frame_id : "n/a");
  txt("cam-time", clock(c.timestamp));
  var hz = s.hazards || {};
  var list = (s.hazard_list && Array.isArray(s.hazard_list.active)
    ? s.hazard_list.active : []);
  var withBox = list.filter(function (h) { return (h.metadata || {}).bbox; });
  txt("cam-det", withBox.length
    ? withBox.length + " (image-space)" : "none");

  if (badge) {
    badge.textContent = st;
    badge.style.color = st === "LIVE" ? "#2fbf71"
      : (st === "SIMULATION" ? "#e8a33d" : "#ef4d5a");
  }
  // C15d: the camera panel must be a real visual area, not a text card.
  //
  // The previous version only fetched /camera/frame when the telemetry said
  // `has_frame`, but has_frame only becomes true *after* something reads a
  // frame -- so the panel could never light up: a deadlock. The frame is now
  // requested whenever the camera is not UNAVAILABLE/ERROR, and the badge
  // reports what actually arrived. A simulated frame is still never presented
  // as live hardware, and a genuinely missing camera is still shown as missing.
  if (st !== "UNAVAILABLE" && st !== "ERROR") {
    if (img) {
      img.hidden = false;
      // onerror fires for a 503, so a dead camera collapses back to the notice.
      img.onerror = function () {
        img.hidden = true;
        if (empty) {
          empty.hidden = false;
          empty.textContent = "No camera frame available right now.";
        }
      };
      img.src = "/camera/frame?t=" + Date.now();
    }
    if (empty) empty.hidden = true;
  } else {
    if (img) { img.hidden = true; img.removeAttribute("src"); }
    if (empty) {
      empty.hidden = false;
      empty.textContent = (c.error ? c.error : st) +
        " — no camera frame. No detections are shown because there is no image.";
    }
  }
  txt("cam-src", c.source || "");
  renderCameraOverlay(list, c);
}

/* Draw bounding boxes over the image. The boxes stay in IMAGE space: they are
   scaled by the image's own pixel size, never converted to world metres. */
function renderCameraOverlay(list, cam) {
  var host = $("cam-overlay");
  if (!host) return;
  var boxes = list.filter(function (h) {
    var b = (h.metadata || {}).bbox;
    return Array.isArray(b) && b.length >= 4 && isNum(cam.width) && isNum(cam.height);
  });
  if (!boxes.length) {
    host.innerHTML = "";
    host.hidden = true;
    return;
  }
  var W = cam.width, H = cam.height;
  host.hidden = false;
  host.innerHTML = boxes.map(function (h) {
    var b = h.metadata.bbox;   // C5 corner form [x1, y1, x2, y2] in pixels
    var x = Math.min(b[0], b[2]), y = Math.min(b[1], b[3]);
    var w = Math.abs(b[2] - b[0]), hgt = Math.abs(b[3] - b[1]);
    var conf = isNum(h.confidence) ? " " + h.confidence.toFixed(2) : "";
    return '<div class="ov-box" style="left:' + (100 * x / W) + "%;top:" +
      (100 * y / H) + "%;width:" + (100 * w / W) + "%;height:" +
      (100 * hgt / H) + '%"><span class="ov-label">' + esc(h.kind) +
      esc(conf) + "</span></div>";
  }).join("");
}

/* -- 3D twin (renders the C10 payload) ------------------------------------ */
/* The legend is static on purpose: it names what the renderer draws, and it
   stays visible even when the scene is empty so the operator can tell an empty
   warehouse apart from a broken panel. */
var T_LEGEND = [
  ["#2fbf71", "Robot body (chassis)"],
  ["#151b24", "Wheels (4)"],
  ["#3893fa", "Camera module"],
  ["#d99e1c", "Sensor mast"],
  ["#ffffff", "Heading indicator (front)"],
  ["#f5a623", "Hazard"],
  ["#38bcf6", "Planned route"],
  ["#a855f7", "Goal"],
  ["#57e389", "Waypoint"]
];

function renderTwinLegend() {
  var el = $("t-legend");
  if (!el) return;
  el.innerHTML = "<b>3D TWIN</b><br>" + T_LEGEND.map(function (row) {
    return '<span class="swatch" style="background:' + row[0] + '"></span>' +
      esc(row[1]);
  }).join("<br>");
}

function renderTwin(s) {
  var tw = s.twin || {};
  txt("twin-src", tw.source || "");
  txt("t-badge", tw.robot ? "POSE OK" : "NO POSE");
  if (!CC.twin.ok) return;
  drawTwin(tw);
}

/* Minimal WebGL renderer. Deliberately dependency-free: WebGL ships in every
   browser, so the Command Center needs no bundler, npm or CDN. The scene
   geometry arrives in renderer coordinates from the C10 payload — the world->3D
   conversion is done once on the server, so the 2D and 3D views cannot disagree. */
var T_VS = "attribute vec3 aPos;attribute vec3 aCol;uniform mat4 uMVP;" +
  "varying vec3 vCol;void main(){vCol=aCol;gl_Position=uMVP*vec4(aPos,1.0);}";
var T_FS = "precision mediump float;varying vec3 vCol;uniform float uAlpha;" +
  "void main(){gl_FragColor=vec4(vCol,uAlpha);}";

function tMul(a, b) {
  var o = new Float32Array(16);
  for (var c = 0; c < 4; c++) for (var r = 0; r < 4; r++) {
    o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] +
                   a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
  }
  return o;
}
function tPersp(fovy, aspect, n, f) {
  var t = 1 / Math.tan(fovy / 2), nf = 1 / (n - f);
  return new Float32Array([t / aspect,0,0,0, 0,t,0,0, 0,0,(f + n) * nf,-1,
                           0,0,2 * f * n * nf,0]);
}
function tLookAt(eye, at, up) {
  var z = tNorm([eye[0]-at[0], eye[1]-at[1], eye[2]-at[2]]);
  var x = tNorm(tCross(up, z)), y = tCross(z, x);
  return new Float32Array([x[0],y[0],z[0],0, x[1],y[1],z[1],0, x[2],y[2],z[2],0,
                           -tDot(x,eye),-tDot(y,eye),-tDot(z,eye),1]);
}
function tCross(a, b) {
  return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
}
function tDot(a, b) { return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }
function tNorm(v) {
  var l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0]/l, v[1]/l, v[2]/l];
}
function tTrans(x, y, z) {
  return new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, x,y,z,1]);
}
function tRotZ(deg) {
  var a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
  return new Float32Array([c,s,0,0, -s,c,0,0, 0,0,1,0, 0,0,0,1]);
}

function initTwin() {
  var canvas = $("t-canvas");
  if (!canvas) return false;
  var gl = null;
  try { gl = canvas.getContext("webgl", { antialias: true, alpha: false }); }
  catch (e) { gl = null; }
  if (!gl) {
    // Honest degradation: say the 3D view is unavailable rather than showing
    // an empty black box.
    var fb = $("t-fallback");
    if (fb) fb.hidden = false;
    canvas.style.display = "none";
    return false;
  }
  function sh(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.error("twin shader:", gl.getShaderInfoLog(s));
      return null;
    }
    return s;
  }
  var vs = sh(gl.VERTEX_SHADER, T_VS), fs = sh(gl.FRAGMENT_SHADER, T_FS);
  if (!vs || !fs) return false;
  var p = gl.createProgram();
  gl.attachShader(p, vs); gl.attachShader(p, fs); gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    console.error("twin link:", gl.getProgramInfoLog(p));
    var fb2 = $("t-fallback");
    if (fb2) fb2.hidden = false;
    return false;
  }
  CC.twin.gl = gl;
  CC.twin.prog = p;
  CC.twin.aPos = gl.getAttribLocation(p, "aPos");
  CC.twin.aCol = gl.getAttribLocation(p, "aCol");
  CC.twin.uMVP = gl.getUniformLocation(p, "uMVP");
  CC.twin.uAlpha = gl.getUniformLocation(p, "uAlpha");
  CC.twin.bufPos = gl.createBuffer();
  CC.twin.bufCol = gl.createBuffer();
  gl.enable(gl.DEPTH_TEST);
  CC.twin.ok = true;
  return true;
}

function tXf(m, v) {
  if (!m) return [v[0], v[1], v[2] || 0];
  return [m[0]*v[0] + m[4]*v[1] + m[8]*(v[2]||0) + m[12],
          m[1]*v[0] + m[5]*v[1] + m[9]*(v[2]||0) + m[13],
          m[2]*v[0] + m[6]*v[1] + m[10]*(v[2]||0) + m[14]];
}
function tTris(tris, col) {
  var pos = [], cr = [];
  for (var i = 0; i < tris.length; i++) for (var j = 0; j < 3; j++) {
    pos.push(tris[i][j][0], tris[i][j][1], tris[i][j][2]);
    cr.push(col[0], col[1], col[2]);
  }
  return { pos: new Float32Array(pos), col: new Float32Array(cr),
           n: tris.length * 3 };
}
function tBox(sx, sy, sz, col, m) {
  var hx = sx/2, hy = sy/2, hz = sz/2;
  var v = [[-hx,-hy,-hz],[hx,-hy,-hz],[hx,hy,-hz],[-hx,hy,-hz],
           [-hx,-hy,hz],[hx,-hy,hz],[hx,hy,hz],[-hx,hy,hz]];
  var f = [[0,1,2,3],[4,7,6,5],[0,4,5,1],[3,2,6,7],[0,3,7,4],[1,5,6,2]];
  var tris = [];
  for (var i = 0; i < f.length; i++) {
    var c = f[i];
    tris.push([tXf(m, v[c[0]]), tXf(m, v[c[1]]), tXf(m, v[c[2]])]);
    tris.push([tXf(m, v[c[0]]), tXf(m, v[c[2]]), tXf(m, v[c[3]])]);
  }
  return tTris(tris, col);
}
function tCyl(r, h, seg, col, m) {
  var tris = [];
  for (var i = 0; i < seg; i++) {
    var a0 = (i / seg) * Math.PI * 2, a1 = ((i + 1) / seg) * Math.PI * 2;
    var p0 = [Math.cos(a0) * r, Math.sin(a0) * r], p1 = [Math.cos(a1) * r, Math.sin(a1) * r];
    tris.push([tXf(m, [p0[0], p0[1], 0]), tXf(m, [p0[0], p0[1], h]), tXf(m, [p1[0], p1[1], 0])]);
    tris.push([tXf(m, [p1[0], p1[1], 0]), tXf(m, [p0[0], p0[1], h]), tXf(m, [p1[0], p1[1], h])]);
  }
  return tTris(tris, col);
}
function tRibbon(pts, col, m, w) {
  var tris = [], w2 = (w || 0.05) / 2, z = 0.015;
  for (var i = 0; i + 1 < pts.length; i++) {
    var a = pts[i], b = pts[i + 1];
    var dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
    var nx = -dy / len * w2, ny = dx / len * w2;
    var q = [[a[0]+nx,a[1]+ny,z],[a[0]-nx,a[1]-ny,z],
             [b[0]-nx,b[1]-ny,z],[b[0]+nx,b[1]+ny,z]];
    tris.push([tXf(m,q[0]), tXf(m,q[1]), tXf(m,q[2])]);
    tris.push([tXf(m,q[0]), tXf(m,q[2]), tXf(m,q[3])]);
  }
  return tTris(tris, col);
}
function tMerge(parts) {
  var pos = [], cr = [], n = 0;
  for (var i = 0; i < parts.length; i++) {
    var p = parts[i];
    if (!p || !p.n) continue;
    for (var k = 0; k < p.pos.length; k++) pos.push(p.pos[k]);
    for (var j = 0; j < p.col.length; j++) cr.push(p.col[j]);
    n += p.n;
  }
  return { pos: new Float32Array(pos), col: new Float32Array(cr), n: n };
}

var T_COL = {
  floor: [0.09, 0.12, 0.17], chassis: [0.13, 0.77, 0.37],
  wheel: [0.08, 0.09, 0.12], camera: [0.22, 0.56, 0.98],
  route: [0.22, 0.74, 0.97], goal: [0.66, 0.33, 0.97],
  hazard: [0.96, 0.65, 0.15], hazardCrit: [0.94, 0.27, 0.27],
  waypoint: [0.34, 0.85, 0.55]
};

function drawTwin(tw) {
  var gl = CC.twin.gl, canvas = $("t-canvas");
  if (!gl || !canvas) return;
  var dpr = Math.min(2, window.devicePixelRatio || 1);
  var w = Math.max(1, Math.round(canvas.clientWidth * dpr));
  var h = Math.max(1, Math.round(canvas.clientHeight * dpr));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  gl.viewport(0, 0, w, h);
  gl.clearColor(0.024, 0.039, 0.067, 1);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

  var parts = [];
  var f = tw.floor || {};
  if (f.available && (f.corners || []).length === 4) {
    var c = f.corners;
    var lo0 = Math.min(c[0][0], c[2][0]), lo1 = Math.min(c[0][1], c[2][1]);
    var hi0 = Math.max(c[0][0], c[2][0]), hi1 = Math.max(c[0][1], c[2][1]);
    parts.push(tBox(hi0 - lo0, hi1 - lo1, 0.02, T_COL.floor,
                    tTrans((lo0 + hi0) / 2, (lo1 + hi1) / 2, -0.01)));
  }
  (tw.waypoints || []).forEach(function (p) {
    parts.push(tCyl(0.12, 0.02, 12, T_COL.waypoint,
                    tTrans(p.position[0], p.position[1], 0)));
  });
  if (CC.twin.showRoute && (tw.route || []).length > 1) {
    parts.push(tRibbon(tw.route, T_COL.route, null, 0.07));
  }
  if (tw.goal) {
    parts.push(tCyl(0.15, 0.03, 14, T_COL.goal,
                    tTrans(tw.goal.position[0], tw.goal.position[1], 0)));
  }
  // Only world-located hazards reach the twin (C9/C13 rule), same as the map.
  if (CC.twin.showHaz) {
    (tw.hazards || []).forEach(function (hz) {
      parts.push(tCyl(0.1, hz.critical ? 0.45 : 0.3, 12,
                      hz.critical ? T_COL.hazardCrit : T_COL.hazard,
                      tTrans(hz.position[0], hz.position[1], 0)));
    });
  }
  var rb = tw.robot;
  if (rb && rb.position) {
    var m = tMul(tTrans(rb.position[0], rb.position[1], 0),
                 tRotZ(rb.rotation_z_deg || 0));
    var mo = rb.model || {};
    var ch = mo.chassis || { size: [0.6, 0.4, 0.28], center_z: 0.22 };
    parts.push(tBox(ch.size[0], ch.size[1], ch.size[2], T_COL.chassis,
                    tMul(m, tTrans(0, 0, ch.center_z))));
    (mo.wheels || []).forEach(function (wl) {
      parts.push(tCyl(wl.radius, wl.width, 10, T_COL.wheel,
                      tMul(m, tTrans(wl.position[0], wl.position[1], wl.position[2]))));
    });
    if (mo.camera) {
      parts.push(tBox(mo.camera.size[0], mo.camera.size[1], mo.camera.size[2],
                      T_COL.camera, tMul(m, tTrans(mo.camera.position[0],
                                      mo.camera.position[1], mo.camera.position[2]))));
    }
    if (mo.sensor) {
      parts.push(tCyl(mo.sensor.radius, mo.sensor.height, 10, [0.85, 0.62, 0.11],
                      tMul(m, tTrans(mo.sensor.position[0], mo.sensor.position[1],
                                      mo.sensor.position[2]))));
    }
    // Forward indicator: proves heading even viewed from directly above.
    parts.push(tBox(0.16, 0.05, 0.03, [1, 1, 1],
                    tMul(m, tTrans(ch.size[0] / 2 + 0.06, 0, ch.center_z))));
  }
  var mesh = tMerge(parts);
  if (!mesh.n) return;
  gl.bindBuffer(gl.ARRAY_BUFFER, CC.twin.bufPos);
  gl.bufferData(gl.ARRAY_BUFFER, mesh.pos, gl.DYNAMIC_DRAW);
  gl.enableVertexAttribArray(CC.twin.aPos);
  gl.vertexAttribPointer(CC.twin.aPos, 3, gl.FLOAT, false, 0, 0);
  gl.bindBuffer(gl.ARRAY_BUFFER, CC.twin.bufCol);
  gl.bufferData(gl.ARRAY_BUFFER, mesh.col, gl.DYNAMIC_DRAW);
  gl.enableVertexAttribArray(CC.twin.aCol);
  gl.vertexAttribPointer(CC.twin.aCol, 3, gl.FLOAT, false, 0, 0);

  var t = CC.twin.target;
  // "Follow" tracks the AMR; otherwise the view frames the data extent. Both
  // only move the *camera* — the robot's pose comes from telemetry, never here.
  var rb2 = tw.robot;
  if (CC.twin.follow && rb2 && rb2.position) {
    t = [rb2.position[0], rb2.position[1], 0.35];
    CC.twin.dist = 4.0;
  } else if (f.available && (f.corners || []).length === 4) {
    var fc = f.corners;
    var span = Math.max(Math.abs(fc[2][0] - fc[0][0]), Math.abs(fc[2][1] - fc[0][1]), 2);
    t = [(fc[0][0] + fc[2][0]) / 2, (fc[0][1] + fc[2][1]) / 2, 0.2];
    if (!CC.twin.follow) CC.twin.dist = Math.max(4.0, span * 1.8);
  }
  CC.twin.target = t;
  var eye = [t[0] + CC.twin.dist * Math.cos(CC.twin.pitch) * Math.cos(CC.twin.yaw),
             t[1] + CC.twin.dist * Math.cos(CC.twin.pitch) * Math.sin(CC.twin.yaw),
             t[2] + CC.twin.dist * Math.sin(CC.twin.pitch)];
  var mvp = tMul(tPersp(50 * Math.PI / 180, w / Math.max(1, h), 0.1, 200),
                 tLookAt(eye, t, [0, 0, 1]));
  gl.useProgram(CC.twin.prog);
  gl.uniformMatrix4fv(CC.twin.uMVP, false, mvp);
  gl.uniform1f(CC.twin.uAlpha, 1.0);
  gl.drawArrays(gl.TRIANGLES, 0, mesh.n);
}

/* -- replay (C14/C14b, display-only) -------------------------------------- */
function renderReplay(s) {
  var r = s.replay || {};
  var loaded = !!r.recording_id;
  ["rp-play", "rp-pause", "rp-restart", "rp-unload"].forEach(function (id) {
    var el = $(id);
    if (el) el.disabled = !loaded;
  });
  txt("rp-state", r.state);
  txt("rp-id", r.recording_id || "none");
  txt("rp-pos", isNum(r.elapsed_s) ? r.elapsed_s.toFixed(1) + " s" : "n/a");
  txt("rp-dur", isNum(r.duration_s) ? r.duration_s.toFixed(1) + " s" : "n/a");
  txt("rp-frame", isNum(r.index) && isNum(r.frames)
    ? (r.index + 1) + " / " + r.frames : "n/a");
  var scrub = $("rp-scrub");
  if (scrub) {
    var pct = isNum(r.progress) ? Math.max(0, Math.min(1, r.progress)) * 100 : 0;
    scrub.firstElementChild.style.width = pct + "%";
    scrub.setAttribute("aria-valuenow", Math.round(pct));
  }
}

// The ONLY writes this page makes. They are the existing replay transport, which
// is display-only on the server: it advances a reader over a recorded file and
// never touches the robot. /command is deliberately not called from here.
function replayPost(action, extra) {
  var body = Object.assign({ action: action }, extra || {});
  return fetch("/replay/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(function (r) { return r.json(); })
    .then(poll)
    .catch(function () { /* transport failure must not break the console */ });
}

function loadRecordings() {
  return fetchJSON("/replay/recordings").then(function (d) {
    var sel = $("rec-select");
    if (!sel) return;
    var list = (d && (d.recordings || d.items)) || [];
    sel.innerHTML = "";
    if (!list.length) {
      sel.innerHTML = '<option value="">No recordings yet</option>';
      return;
    }
    list.forEach(function (r) {
      var id = r.recording_id || r.id || r.name;
      var o = document.createElement("option");
      o.value = id;
      var bits = [id];
      if (isNum(r.frames)) bits.push(r.frames + " frames");
      if (isNum(r.duration_s)) bits.push(r.duration_s.toFixed(0) + "s");
      o.textContent = bits.join(" \u00b7 ");
      sel.appendChild(o);
    });
  }).catch(function () { /* no recordings directory is a valid state */ });
}

/* -- controls ------------------------------------------------------------- */
function on(id, fn) {
  var el = $(id);
  if (el) el.addEventListener("click", fn);
}
function redraw() {
  if (!CC.state) return;
  renderMap(CC.state);
  renderTwin(CC.state);
}
function toggleBtn(id, key, obj) {
  on(id, function () {
    obj[key] = !obj[key];
    this.setAttribute("aria-pressed", obj[key] ? "true" : "false");
    redraw();
  });
}
function setView(yaw, pitch) {
  CC.twin.yaw = yaw; CC.twin.pitch = pitch;
  redraw();
}

function initControls() {
  // 3D view — orbit/zoom only. Nothing here can move the robot.
  on("t-reset", function () {
    CC.twin.yaw = 0.9; CC.twin.pitch = 0.62; CC.twin.dist = 9;
    CC.twin.target = [0, 0, 0];
    redraw();
  });
  on("t-iso", function () { setView(0.9, 0.62); });
  on("t-top", function () { setView(0, 1.5); });
  on("t-front", function () { setView(0, 0.15); });
  on("t-follow", function () {
    CC.twin.follow = !CC.twin.follow;
    this.setAttribute("aria-pressed", CC.twin.follow ? "true" : "false");
    redraw();
  });
  toggleBtn("t-haz", "showHaz", CC.twin);
  toggleBtn("t-path", "showRoute", CC.twin);

  var canvas = $("t-canvas");
  if (canvas) {
    canvas.addEventListener("wheel", function (e) {
      e.preventDefault();
      CC.twin.dist = Math.max(1.2, Math.min(40,
        CC.twin.dist * (e.deltaY < 0 ? 0.9 : 1.1)));
      redraw();
    }, { passive: false });
    canvas.addEventListener("pointerdown", function (e) {
      CC.twin.drag = { x: e.clientX, y: e.clientY };
      if (canvas.setPointerCapture) canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", function (e) {
      if (!CC.twin.drag) return;
      CC.twin.yaw -= (e.clientX - CC.twin.drag.x) * 0.01;
      CC.twin.pitch = Math.max(0.08, Math.min(1.5,
        CC.twin.pitch + (e.clientY - CC.twin.drag.y) * 0.008));
      CC.twin.drag = { x: e.clientX, y: e.clientY };
      redraw();
    });
    var endDrag = function (e) {
      CC.twin.drag = null;
      if (canvas.hasPointerCapture && canvas.hasPointerCapture(e.pointerId)) {
        canvas.releasePointerCapture(e.pointerId);
      }
    };
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);
  }

  // Map view — pan/zoom of the *view* only.
  on("m-fit", function () {
    CC.map.zoom = 1; CC.map.cx = null; CC.map.cy = null;
    if (CC.state) renderMap(CC.state);
  });
  on("m-center", function () {
    var rb = (CC.state && CC.state.map && CC.state.map.robot) || null;
    if (rb && isNum(rb.x)) {
      CC.map.cx = rb.x; CC.map.cy = rb.y; CC.map.zoom = 2.5;
      if (CC.state) renderMap(CC.state);
    }
  });
  on("m-in", function () {
    CC.map.zoom = Math.min(6, CC.map.zoom * 1.25);
    if (CC.state) renderMap(CC.state);
  });
  on("m-out", function () {
    CC.map.zoom = Math.max(0.4, CC.map.zoom / 1.25);
    if (CC.state) renderMap(CC.state);
  });
  toggleBtn("m-route", "showRoute", CC.map);
  toggleBtn("m-trail", "showTrail", CC.map);
  toggleBtn("m-haz", "showHaz", CC.map);
  toggleBtn("m-zones", "showZones", CC.map);

  document.querySelectorAll(".filters button[data-f]").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll(".filters button[data-f]").forEach(function (o) {
        o.setAttribute("aria-pressed", "false");
      });
      b.setAttribute("aria-pressed", "true");
      CC.filter = b.getAttribute("data-f");
      if (CC.state) renderLog(CC.state);
    });
  });

  on("rec-load", function () {
    var sel = $("rec-select");
    if (sel && sel.value) replayPost("load", { recording_id: sel.value });
  });
  on("rp-play", function () { replayPost("play"); });
  on("rp-pause", function () { replayPost("pause"); });
  on("rp-restart", function () { replayPost("restart"); });
  on("rp-unload", function () { replayPost("unload"); });
  document.querySelectorAll("button[data-speed]").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll("button[data-speed]").forEach(function (o) {
        o.setAttribute("aria-pressed", "false");
      });
      b.setAttribute("aria-pressed", "true");
      replayPost("speed", { speed: parseFloat(b.getAttribute("data-speed")) });
    });
  });
}

/* -- C5e — operations panels ------------------------------------------------ */
/* Every value here comes from the `ops` block the server already put in the
   same /dashboard/state response. A missing value is rendered "n/a" and is
   never turned into 0. */
function stCell(state) {
  return '<span class="st-' + esc(String(state || "UNKNOWN").replace(/\s+/g, "_"))
    + '">' + esc(state || "UNKNOWN") + "</span>";
}

function rank(state) {
  return { HEALTHY: 0, DEGRADED: 1, WARNING: 2, FAULT: 3 }[state] || 0;
}

function renderOps(s) {
  var ops = s.ops;
  if (!ops) return;
  renderIdentity(ops.identity);
  renderHealth(ops.health);
  renderSensors(ops.sensors);
  renderSystem(ops, s);
  renderTimeline(ops.mission);
  renderNav(ops.navigation);
  renderHazCentre(ops.hazards);
  renderPerf(ops.performance, s);
  renderAlerts(ops.alerts);
}

function renderIdentity(id) {
  if (!id) return;
  txt("ident-id", id.robot_id);
  txt("ident-mode", id.mode);
  txt("ident-mission", id.mission);
  txt("ident-state", id.state);
}

function renderHealth(h) {
  if (!h) return;
  var overall = h.overall || "UNKNOWN";
  txt("h-state", overall);
  txt("health-overall", overall);
  // Show the reason of the *worst* component, so the verdict is never bare.
  var worst = null;
  h.components.forEach(function (c) {
    if (!worst || rank(c.state) > rank(worst.state)) worst = c;
  });
  txt("h-why", worst ? worst.component + ": " + worst.reason : "no data");
  var el = $("h-state");
  if (el) el.className = "health-big st-" + String(overall).replace(/\s+/g, "_");
  var body = $("health-rows");
  if (body) {
    body.innerHTML = h.components.map(function (c) {
      return "<tr><td>" + esc(c.component) + "</td><td>" + stCell(c.state) +
        "</td><td>" + esc(c.reason || "") + "</td></tr>";
    }).join("") || '<tr><td colspan="3">n/a</td></tr>';
  }
  // There is intentionally no score bar; say why instead of drawing a number
  // the project has no weighting to justify.
  txt("health-note", h.score === null ? (h.score_note || "") : "");
}

function renderSensors(rows) {
  var body = $("sensor-rows");
  if (!body || !rows) return;
  body.innerHTML = rows.map(function (r) {
    // No value -> "n/a", never 0: a sensor reading 0 and one that is
    // unconnected must never look the same.
    return "<tr><td>" + esc(r.sensor) + "</td><td>" + stCell(r.state) +
      "</td><td>" + esc(r.source || "n/a") + "</td><td>" +
      (r.value === null || r.value === undefined ? "n/a" : esc(String(r.value))) +
      "</td></tr>";
  }).join("") || '<tr><td colspan="4">no sensors reported</td></tr>';
}

function renderSystem(ops, s) {
  var list = $("system-layers");
  if (list && ops.system) {
    list.innerHTML = ops.system.map(function (l) {
      return "<li><b>" + esc(l.layer) + "</b><span>" + stCell(l.state) +
        "</span><em>" + esc(l.detail || "") + "</em></li>";
    }).join("");
  }
  var perf = ops.performance || {};
  txt("sys-updated", clock(s.timestamp));
  txt("sys-hz", perf.dashboard_hz ? perf.dashboard_hz + " Hz" : "n/a");
  txt("sys-backend", (s.system && s.system.status) || "n/a");
  var rec = s.recording || {};
  txt("sys-rec", rec.active ? ("ACTIVE " + (rec.recording_id || ""))
    : (rec.available === false ? "unavailable" : "idle"));
}

function renderTimeline(m) {
  var list = $("mission-timeline");
  if (list && m && m.timeline) {
    list.innerHTML = m.timeline.map(function (s) {
      return '<li class="st-' + esc(s.state) + '">' + esc(s.step) +
        (s.at ? "<small>" + clock(s.at) + "</small>" : "") + "</li>";
    }).join("");
  }
  var st = (m && m.statistics) || {};
  txt("ms-time", isNum(st.elapsed_s) ? Math.round(st.elapsed_s) + " s" : "n/a");
  txt("ms-tasks", isNum(st.tasks_total)
    ? (st.tasks_completed || 0) + " / " + st.tasks_total : "n/a");
  txt("ms-prog", isNum(st.mission_progress)
    ? Math.round(st.mission_progress * 100) + "%" : "n/a");
  txt("ms-haz", isNum(st.hazards_observed) ? st.hazards_observed : "n/a");
  txt("ms-avoid", isNum(st.avoidances) ? st.avoidances : "n/a");
  txt("ms-err", isNum(st.tasks_failed) ? st.tasks_failed : "n/a");
}

function renderNav(nv) {
  if (!nv) return;
  txt("nv-state", nv.state || "n/a");
  txt("nv-target", nv.target || "none");
  // The runtime exposes no measured range to the goal, so this stays n/a
  // rather than showing a straight-line guess presented as a measurement.
  txt("nv-dist", isNum(nv.distance_m) ? nv.distance_m.toFixed(2) + " m" : "n/a");
  txt("nv-head", isNum(nv.heading_deg)
    ? nv.heading_deg.toFixed(1) + "\u00b0" : "n/a");
  txt("nv-planner", nv.planner || "n/a");
  txt("nv-avoid", nv.avoidance || "CLEAR");
  txt("nv-points", isNum(nv.route_points) ? nv.route_points : "n/a");
}

function renderHazCentre(h) {
  if (!h) return;
  var cur = h.current;
  txt("haz-state", cur ? (cur.severity || "ACTIVE") : "NO ACTIVE HAZARD");
  if (cur) {
    // The bbox is image-space pixels and is labelled as such; it is never
    // presented as a world position.
    txt("haz-detail", cur.kind +
      (isNum(cur.confidence) ? "  conf " + cur.confidence.toFixed(2) : "") +
      (cur.source ? "  src " + cur.source : "") +
      (cur.bbox_image_px
        ? "  bbox " + cur.bbox_image_px.join(",") + " px [" +
          cur.coordinate_space + "-space]"
        : "  no world location"));
  } else {
    txt("haz-detail", "no hazard reported by the hazard manager");
  }
  var list = $("haz-recent");
  if (list && h.recent) {
    list.innerHTML = h.recent.slice(0, 25).map(function (e) {
      return "<li>" + clock(e.t) + "  " + stCell(e.level) + "  " +
        esc(e.category || "") + "  " + esc(e.message || "") + "</li>";
    }).join("") || '<li class="mini">no hazard events yet</li>';
  }
}

function renderPerf(p, s) {
  if (!p) return;
  txt("pf-hz", isNum(p.dashboard_hz) ? p.dashboard_hz + " Hz" : "n/a");
  txt("pf-rate", isNum(p.observed_series_hz) ? p.observed_series_hz + " Hz" : "n/a");
  txt("pf-api", isNum(p.api_latency_ms) ? p.api_latency_ms + " ms" : "n/a");
  txt("pf-fps", isNum(p.camera_fps) ? p.camera_fps + " fps" : "n/a");
  txt("pf-ifps", isNum(p.inference_fps) ? p.inference_fps + " fps" : "n/a");
  txt("pf-ilat", isNum(p.inference_latency_ms) ? p.inference_latency_ms + " ms" : "n/a");
  txt("pf-speed", isNum(p.replay_speed) ? p.replay_speed + "x" : "n/a");
  var cam = s.camera || {};
  txt("cd-frame", cam.has_frame ? "YES" : "NO");
  txt("cd-dim", (isNum(cam.width) && isNum(cam.height))
    ? cam.width + " \u00d7 " + cam.height : "n/a");
  // C15b deliberately supports a camera with no inference model, so "not
  // configured" is a normal state here rather than a fault.
  txt("cd-det", "not configured");
  var n = 0;
  var hl = s.hazard_list;
  if (hl && Array.isArray(hl.active)) {
    n = hl.active.filter(function (x) {
      return x && x.metadata && Array.isArray(x.metadata.bbox);
    }).length;
  }
  txt("cd-count", n);
  txt("cd-last", clock(cam.timestamp));
}

/* -- C5e — event search ----------------------------------------------------- */
/* The C15c log is still the single renderer; this only filters what it already
   produced, so there is no second event stream. */
function currentEvents() {
  var ev = CC.state && CC.state.history && CC.state.history.events;
  return (ev && Array.isArray(ev.events)) ? ev.events : [];
}

function applyEventFilter() {
  var q = (($("ev-search") || {}).value || "").toLowerCase();
  var cat = ($("ev-cat") || {}).value || "";
  var lvl = ($("ev-level") || {}).value || "";
  var rows = currentEvents().filter(function (e) {
    if (cat && String(e.category || "") !== cat) return false;
    if (lvl && String(e.level || "") !== lvl) return false;
    if (q && String(e.message || "").toLowerCase().indexOf(q) < 0) return false;
    return true;
  });
  var host = $("log");
  if (host) {
    host.innerHTML = rows.length ? rows.map(function (e, i) {
      return '<div class="log-row" data-ev="' + i + '"><span class="mono">' +
        clock(e.t) + "</span>" + stCell(e.level) + "  " +
        esc(e.category || "") + "  " + esc(e.message || "") + "</div>";
    }).join("") : '<p class="mini">no events match this filter</p>';
    host.querySelectorAll(".log-row").forEach(function (row) {
      row.addEventListener("click", function () {
        showEventDetail(rows[Number(row.getAttribute("data-ev"))]);
      });
    });
  }
  var shown = currentEvents().length;
  txt("ev-count", rows.length + " of " + shown + " events");
}

function showEventDetail(e) {
  var box = $("ev-detail");
  if (!box || !e) return;
  var meta = e.detail && typeof e.detail === "object" ? e.detail : null;
  box.innerHTML =
    "<div><b>Type:</b> " + esc(e.category || "n/a") + "</div>" +
    "<div><b>Timestamp:</b> " + clock(e.t) + "</div>" +
    "<div><b>Level:</b> " + esc(e.level || "n/a") + "</div>" +
    "<div><b>Message:</b> " + esc(e.message || "n/a") + "</div>" +
    // Any coordinate carried by an event is image-space unless the runtime
    // explicitly says otherwise; the label makes that explicit.
    (meta ? "<div><b>Detail:</b> " + esc(JSON.stringify(meta)) +
      " <em>[image-space]</em></div>" : "");
  box.hidden = false;
}

function initEventSearch() {
  // Populate the category filter from the categories the stream really emits.
  var sel = $("ev-cat");
  if (sel && sel.options.length <= 1) {
    (CATEGORIES || []).forEach(function (c) {
      var o = document.createElement("option");
      o.value = c; o.textContent = c;
      sel.appendChild(o);
    });
  }
  ["ev-search", "ev-cat", "ev-level"].forEach(function (id) {
    var el = $(id);
    if (!el) return;
    el.addEventListener("input", applyEventFilter);
    el.addEventListener("change", applyEventFilter);
  });
}

/* -- C5e — theme, shortcuts, alert popover --------------------------------- */
/* Theme is a presentation preference stored in localStorage only. It never
   changes backend behaviour, and a stored preference is a normal thing for a
   single-operator console. */
function applyTheme(name) {
  var light = name === "light";
  document.body.classList.toggle("light", light);
  var icon = $("theme-icon");
  if (icon) icon.innerHTML = light ? "&#9788;" : "&#9789;";
  try { localStorage.setItem("amr-theme", light ? "light" : "dark"); } catch (e) { }
  if (CC.state) renderTwin(CC.state);
}

function initTheme() {
  var stored = null;
  try { stored = localStorage.getItem("amr-theme"); } catch (e) { }
  applyTheme(stored || "dark");
  var btn = $("theme-btn");
  if (btn) {
    btn.addEventListener("click", function () {
      applyTheme(document.body.classList.contains("light") ? "dark" : "light");
    });
  }
}

function initShortcuts() {
  document.addEventListener("keydown", function (e) {
    // Never steal keys from a field the operator is typing in.
    var t = e.target || {};
    if (t.tagName === "INPUT" || t.tagName === "SELECT" ||
        t.tagName === "TEXTAREA") return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var n = Number(e.key);
    // Number keys select a view; no key is ever bound to a motor command.
    if (n >= 1 && n <= 8 && VIEW_KEYS[n]) {
      setView(VIEW_KEYS[n]);
      return;
    }
    if (e.key === "t" || e.key === "T") {
      applyTheme(document.body.classList.contains("light") ? "dark" : "light");
    } else if (e.key === "f" || e.key === "F") {
      toggleFullscreen();
    }
  });
}

function toggleFullscreen() {
  var el = document.documentElement;
  if (!document.fullscreenElement) {
    if (el.requestFullscreen) el.requestFullscreen();
  } else if (document.exitFullscreen) {
    document.exitFullscreen();
  }
}

function initAlertCenter() {
  var bell = $("alert-bell");
  var pop = $("alert-center");
  function close() {
    if (pop) pop.hidden = true;
    if (bell) bell.setAttribute("aria-expanded", "false");
  }
  if (bell && pop) {
    bell.addEventListener("click", function () {
      var open = pop.hidden;
      pop.hidden = !open;
      bell.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  var x = $("alert-close");
  if (x) x.addEventListener("click", close);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") close();
  });
}

function renderAlerts(list) {
  if (!list) return;
  var html = list.length ? list.map(function (a) {
    return '<li class="sev-' + esc(a.severity) + '"><span class="cat">' +
      esc(a.category) + "</span>" + esc(a.message) + "</li>";
  }).join("") : '<li class="mini">no alerts</li>';
  ["alert-list", "alert-list-pop"].forEach(function (id) {
    var el = $(id);
    if (el) el.innerHTML = html;
  });
  var badge = $("alert-count");
  if (badge) {
    // Unread is browser state only; nothing is persisted server-side.
    badge.textContent = String(list.length);
    badge.hidden = list.length === 0;
  }
}

/* Client-side only. The brief allows either separate routes or client-side
   views; this chooses the latter so there is still exactly one page, one poll
   and no duplicated backend logic. The same panels are shown either way. */

/* C5e: which panels belong to which view. "overview" keeps everything, so the
   landing screen still shows the whole robot at a glance. */
var VIEW_SECTIONS = {
  overview: null,                 // null = show every panel
  twin: ["twin"],
  camera: ["camera"],
  map: ["map", "nav"],
  mission: ["mission", "timeline"],
  telemetry: ["telemetry", "perf"],
  safety: ["safety", "hazcentre"],
  sensors: ["sensors", "system"],
  hazards: ["hazcentre"],
  replay: ["replay"],
  events: ["events"],
  diagnostics: ["health", "system", "perf", "alerts"]
};
var VIEW_KEYS = ["overview", "twin", "camera", "map", "mission", "telemetry",
                 "safety", "sensors", "hazards", "replay", "events",
                 "diagnostics"];

function setView(name) {
  var main = $("main");
  var wanted = (VIEW_SECTIONS[name] === undefined) ? "overview" : name;
  if (main) {
    main.className = "view-" + wanted;
    main.setAttribute("data-view", wanted);
  }
  // Both the top tabs and the sidebar drive this one function, so the two
  // navigation surfaces can never disagree about which view is active.
  document.querySelectorAll("button[data-view]").forEach(function (b) {
    var on = b.getAttribute("data-view") === wanted;
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  var keep = VIEW_SECTIONS[wanted];
  document.querySelectorAll("[data-section]").forEach(function (sec) {
    // Overview shows everything; a focused view shows only its own panels.
    sec.style.display = (keep === null ||
      keep.indexOf(sec.getAttribute("data-section")) >= 0) ? "" : "none";
  });
  CC.view = wanted;
  // The canvases must be re-measured after a layout change, or the focused
  // view renders at the old (overview) pixel size.
  window.requestAnimationFrame(function () { if (CC.state) renderTwin(CC.state); });
}

function initViews() {
  document.querySelectorAll("button[data-view]").forEach(function (b) {
    b.addEventListener("click", function () { setView(b.getAttribute("data-view")); });
  });
  // A hash keeps a focused view linkable and survives a reload.
  function fromHash() {
    var n = (location.hash || "").replace("#", "");
    setView(VIEW_KEYS.indexOf(n) >= 0 ? n : "overview");
  }
  fromHash();
  window.addEventListener("hashchange", fromHash);
}

/* -- bootstrap ------------------------------------------------------------ */
/* The C5e event filters mirror the categories the server's event stream really
   emits (amr.telemetry.series.CATEGORIES), restated here so the page does not
   have to fetch the list before the first render. */
var CATEGORIES = ["MISSION", "SAFETY", "HAZARD", "VISION", "NAVIGATION",
                  "CAMERA", "SYSTEM"];

initControls();
initViews();
initTwin();
initTheme();          // C5e: dark by default, preference only
initEventSearch();    // C5e: filters the existing log, no second stream
initShortcuts();      // C5e: view keys + theme + fullscreen, never a command
initAlertCenter();    // C5e
renderTwinLegend();
loadRecordings();
poll();
// One timer for the whole page. No second telemetry loop, no duplicate fetch.
setInterval(poll, POLL_MS);
setInterval(loadRecordings, 15000);








function renderMission(s) {
  var m = s.mission || {};
  txt("m-state", m.state);
  txt("m-phase", m.phase);
  txt("m-task", m.current_task);
  txt("m-ttype", m.current_task_type);
  txt("m-dest", m.destination);
  txt("m-total", m.total_tasks);
  txt("m-done", m.completed_tasks);
  txt("m-fail", m.failed_tasks);
  var frac = m.mission_progress;
  if (!isNum(frac) && isNum(m.task_progress)) frac = m.task_progress;
  bar("m-bar", frac, m.state === "FAILED" ? "crit" : null);
  txt("m-bar-lo", (m.completed_tasks || 0) + " / " +
    (isNum(m.total_tasks) ? m.total_tasks : 0));
  txt("m-bar-hi", isNum(frac) ? Math.round(frac * 100) + "%" : "no data");
}
