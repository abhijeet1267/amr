/* ==========================================================================
   Phase C — Applications Hub

   Hard rules this file obeys:
   * It is a DIRECTORY. It issues GET requests only — there is no POST here,
     and no code path that reaches /command, the hazard latch or the replay
     transport. Opening a card opens an existing page; this page commands
     nothing.
   * The backend is authoritative. Every status string is printed verbatim as
     received; this file groups and filters, it never invents or upgrades a
     status. A card whose URL is null says "no interface" rather than becoming
     a dead link.
   * A failed read is reported as a failed read. Cards that could not be
     refreshed are labelled STALE with the time of the last good read, because
     an old status presented as current is worse than no status at all.
   ========================================================================== */
"use strict";

/* The registry only changes when the robot's conditions change (camera
   attached, server restarted), so 30s is honest here — this page is not a
   1 Hz instrument like the console, and it must not pretend to be. */
var POLL_MS = 30000;

var HUB = {
  payload: null,
  lastOk: 0,
  failed: false,
  filter: { category: "ALL", platform: "ALL", onlyOpen: false }
};

/* Status → chip colour. Decoration only: the status TEXT is always rendered,
   so a colour-blind operator (or a bright factory floor) loses nothing. */
var STATUS_CLASS = {
  "AVAILABLE": "ok",
  "MOCK": "warn",
  "PARTIAL": "warn",
  "HARDWARE REQUIRED": "warn",
  "BUILD NOT AVAILABLE": "warn",
  "NOT INSTALLED": "warn",
  "DEVELOPMENT": "warn",
  "COMING SOON": "warn",
  "OFFLINE": "crit"
};

/* -- tiny DOM helpers (same shape as the console's) ----------------------- */
function $(id) { return document.getElementById(id); }
function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}
function clockAt(ms) {
  var d = new Date(ms);
  return String(d.getHours()).padStart(2, "0") + ":" +
         String(d.getMinutes()).padStart(2, "0") + ":" +
         String(d.getSeconds()).padStart(2, "0");
}
function statusClass(status) { return STATUS_CLASS[status] || "info"; }
function titleCase(s) {
  return String(s || "").replace(/(^|[\s-_])([a-z])/g, function (m, a, b) {
    return (a ? " " : "") + b.toUpperCase();
  });
}

/* -- card ----------------------------------------------------------------- */
function metaRow(dl, label, value, plain) {
  if (value === null || value === undefined || value === "") return;
  dl.appendChild(el("dt", null, label));
  dl.appendChild(el("dd", plain ? "plain" : null, value));
}

function card(app) {
  var cls = statusClass(app.status);
  var node = el("article", "card app-card s-" + cls);
  /* Machine-readable hooks, so the DOM itself states why a card looks the way
     it does — a test (or a curious operator) can read the reason without
     parsing prose. */
  node.setAttribute("data-app-id", app.id || "");
  node.setAttribute("data-status", app.status || "");
  node.setAttribute("data-category", app.category || "");
  node.setAttribute("data-platforms", (app.platforms || []).join(" "));
  node.setAttribute("data-openable", app.url ? "yes" : "no");

  var head = el("div", "app-head");
  head.appendChild(el("h3", null, app.name || app.id));
  var chip = el("span", "chip " + cls);
  chip.appendChild(el("span", "dot"));
  chip.appendChild(el("span", null, app.status || "UNKNOWN"));
  head.appendChild(chip);
  node.appendChild(head);

  node.appendChild(el("p", "app-desc", app.description || ""));
  if (app.detail) {
    node.appendChild(el("p", "app-detail" + (cls === "ok" ? " s-ok" : ""), app.detail));
  }

  var flags = el("p", "app-flags");
  if (app.read_only === false) {
    flags.appendChild(el("span", "flag warn", "can command motion"));
  } else {
    flags.appendChild(el("span", "flag", "read-only"));
  }
  if (app.requires_robot) flags.appendChild(el("span", "flag", "needs robot"));
  if (app.requires_camera) flags.appendChild(el("span", "flag", "needs camera"));
  if (app.requires_hardware) flags.appendChild(el("span", "flag", "needs hardware"));
  node.appendChild(flags);

  var dl = el("dl", "app-meta");
  metaRow(dl, "Category", titleCase(app.category), true);
  metaRow(dl, "Platforms", (app.platforms || []).join(", "), true);
  metaRow(dl, "API", app.api_base);
  metaRow(dl, "Launch", app.launch_command);
  /* Only shown when the runtime contradicted the file: the operator sees both
     halves of the decision instead of a status with no history. */
  if (app.declared_status && app.declared_status !== app.status) {
    metaRow(dl, "Declared", app.declared_status, true);
  }
  if (app.reason && app.reason !== "declared") {
    metaRow(dl, "Reason", app.reason);
  }
  node.appendChild(dl);

  var actions = el("div", "app-actions");
  if (app.url) {
    var open = el("a", "app-open", "Open \u2192");
    open.href = app.url;
    open.setAttribute("aria-label", "Open " + (app.name || app.id));
    actions.appendChild(open);
  } else {
    /* Deliberately not a link. An entry with no URL is an API, not a screen. */
    actions.appendChild(el("span", "app-none", "API \u2014 no interface"));
  }
  node.appendChild(actions);
  return node;
}

/* -- filtering ------------------------------------------------------------- */
function matches(app) {
  var f = HUB.filter;
  if (f.category !== "ALL" && app.category !== f.category) return false;
  if (f.platform !== "ALL" && (app.platforms || []).indexOf(f.platform) < 0) return false;
  if (f.onlyOpen && !app.url) return false;
  return true;
}

var PLATFORM_ORDER = ["web", "android", "ios", "macos", "windows", "linux"];

function platformList(apps) {
  var seen = [];
  apps.forEach(function (a) {
    (a.platforms || []).forEach(function (p) {
      if (seen.indexOf(p) < 0) seen.push(p);
    });
  });
  seen.sort(function (a, b) {
    var ia = PLATFORM_ORDER.indexOf(a), ib = PLATFORM_ORDER.indexOf(b);
    if (ia < 0) ia = PLATFORM_ORDER.length;
    if (ib < 0) ib = PLATFORM_ORDER.length;
    return ia - ib || a.localeCompare(b);
  });
  return seen;
}

function renderFilters(payload) {
  var apps = payload.applications || [];
  var cats = payload.categories || [];

  /* Keep a selection that still exists; otherwise fall back to ALL rather than
     showing an empty page the operator cannot explain. */
  if (HUB.filter.category !== "ALL" && cats.indexOf(HUB.filter.category) < 0) {
    HUB.filter.category = "ALL";
  }
  var host = $("hub-categories");
  host.textContent = "";
  var all = [["ALL", "All", apps.length]];
  cats.forEach(function (c) {
    var n = apps.filter(function (a) { return a.category === c; }).length;
    all.push([c, titleCase(c), n]);
  });
  all.forEach(function (entry) {
    var b = el("button", "filter-btn");
    b.type = "button";
    b.setAttribute("data-cat", entry[0]);
    b.setAttribute("aria-pressed", HUB.filter.category === entry[0] ? "true" : "false");
    b.appendChild(el("span", null, entry[1] + " "));
    b.appendChild(el("span", "n", entry[2]));
    b.addEventListener("click", function () {
      HUB.filter.category = entry[0];
      render();
    });
    host.appendChild(b);
  });

  var plats = platformList(apps);
  if (HUB.filter.platform !== "ALL" && plats.indexOf(HUB.filter.platform) < 0) {
    HUB.filter.platform = "ALL";
  }
  var sel = $("hub-platforms");
  sel.textContent = "";
  sel.appendChild(el("option", null, "All platforms"));
  sel.firstChild.value = "ALL";
  plats.forEach(function (p) {
    var o = el("option", null, titleCase(p));
    o.value = p;
    sel.appendChild(o);
  });
  sel.value = HUB.filter.platform;
}

/* -- rendering ------------------------------------------------------------- */
function render() {
  var payload = HUB.payload;
  if (!payload) return;
  renderFilters(payload);

  var groups = $("hub-groups");
  groups.textContent = "";
  var shown = 0;
  var total = (payload.applications || []).length;

  (payload.categories || []).forEach(function (cat) {
    var inCat = (payload.applications || []).filter(function (a) {
      return a.category === cat && matches(a);
    });
    if (!inCat.length) return;  /* no empty headings, ever */
    var section = el("section", "group");
    section.setAttribute("data-category", cat);
    var h = el("h2", null, titleCase(cat) + " ");
    h.appendChild(el("span", "count", inCat.length));
    section.appendChild(h);
    var grid = el("div", "grid");
    inCat.forEach(function (app) { grid.appendChild(card(app)); });
    section.appendChild(grid);
    groups.appendChild(section);
    shown += inCat.length;
  });

  $("hub-empty").hidden = shown > 0;
  $("hub-count-text").textContent = String(payload.count === undefined
    ? total : payload.count);
  $("hub-hint").textContent = shown === total
    ? total + " interface" + (total === 1 ? "" : "s")
    : "showing " + shown + " of " + total;
  $("hub-stamp").textContent = "source GET /applications/state \u00b7 last read " +
    (HUB.lastOk ? clockAt(HUB.lastOk) : "\u2014");
  paintFreshness();
}

function paintFreshness() {
  var chip = $("hub-fresh");
  var text = "LIVE";
  chip.className = "chip";
  if (HUB.failed) {
    text = HUB.lastOk ? "STALE" : "UNREACHABLE";
    chip.className = "chip " + (HUB.lastOk ? "stale" : "dead");
  }
  $("hub-fresh-text").textContent = text;
}

function note(msg) {
  var banner = $("hub-banner");
  banner.textContent = msg || "";
  banner.hidden = !msg;
}

/* -- read: GET only -------------------------------------------------------- */
function load() {
  return fetch("/applications/state", { headers: { "Accept": "application/json" } })
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (data) {
      HUB.payload = data;
      HUB.lastOk = Date.now();
      HUB.failed = false;
      note("");
      render();
    })
    .catch(function (err) {
      HUB.failed = true;
      note("Could not read /applications/state (" + err.message + "). " +
        (HUB.lastOk
          ? "The cards below are from the last successful read at " +
            clockAt(HUB.lastOk) + " \u2014 they are not current."
          : "No statuses are known, so none are shown. Nothing here is " +
            "assumed to be working."));
      if (HUB.lastOk) render(); else paintFreshness();
    });
}

/* -- theme ---------------------------------------------------------------- */
/* The same localStorage key as the console, so the two pages agree. Purely a
   presentation preference, never a backend change. */
function applyTheme() {
  var light = false;
  try { light = localStorage.getItem("amr-theme") === "light"; } catch (e) { }
  document.body.classList.toggle("light", light);
  var icon = $("hub-theme-icon");
  if (icon) icon.textContent = light ? "\u263c" : "\u263e";
}

/* -- boot ----------------------------------------------------------------- */
function init() {
  $("hub-refresh").addEventListener("click", function () { load(); });
  $("hub-platforms").addEventListener("change", function (ev) {
    HUB.filter.platform = ev.target.value;
    render();
  });
  $("hub-only-open").addEventListener("change", function (ev) {
    HUB.filter.onlyOpen = !!ev.target.checked;
    render();
  });
  var themeBtn = $("hub-theme");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var light = !document.body.classList.contains("light");
      try { localStorage.setItem("amr-theme", light ? "light" : "dark"); } catch (e) { }
      applyTheme();
    });
  }
  /* Ticking the clock is the only thing on a timer here; the payload itself is
     refreshed on demand and every POLL_MS seconds. */
  setInterval(function () {
    var c = $("hub-clock");
    if (c) c.textContent = clockAt(Date.now());
  }, 1000);
  setInterval(load, POLL_MS);
  /* Coming back to a stale tab should re-read rather than show yesterday. */
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) load();
  });
  applyTheme();
  load();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
