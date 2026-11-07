(function () {
  "use strict";

  var I18N = window.SV_I18N;
  var lang = document.documentElement.lang === "en" ? "en" : "fa";
  var T = I18N[lang];
  var NS = "http://www.w3.org/2000/svg";
  var root = document.documentElement;
  var PLAT_ORDER = ["android", "ios", "windows", "mac", "linux"];
  var APP_FALLBACK = {
    android: [
      { n: "v2rayNG", rec: 1, add: "v2rayng://install-sub?url=", dl: "https://github.com/2dust/v2rayNG/releases" },
      { n: "Hiddify", add: "hiddify://import/", dl: "https://github.com/hiddify/hiddify-app/releases" }
    ],
    ios: [
      { n: "Streisand", rec: 1, add: "streisand://import/", dl: "https://apps.apple.com/app/streisand/id6450534064" },
      { n: "Hiddify", add: "hiddify://import/", dl: "https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532" }
    ],
    windows: [{ n: "Hiddify", rec: 1, add: "hiddify://import/", dl: "https://github.com/hiddify/hiddify-app/releases" }],
    mac: [{ n: "Streisand", rec: 1, add: "streisand://import/", dl: "https://apps.apple.com/app/streisand/id6450534064" }],
    linux: [{ n: "Hiddify", rec: 1, add: "hiddify://import/", dl: "https://github.com/hiddify/hiddify-app/releases" }]
  };
  var appsP = null;
  function loadApps() {
    if (!appsP) {
      appsP = api("/api/web/apps").then(function (d) { return d && d.apps ? d.apps : APP_FALLBACK; }).catch(function () { appsP = null; return APP_FALLBACK; });
    }
    return appsP;
  }
  function detectPlatform() {
    var ua = navigator.userAgent || "";
    if (/iPhone|iPad|iPod/.test(ua)) return "ios";
    if (/Android/.test(ua)) return "android";
    if (/Windows/.test(ua)) return "windows";
    if (/Macintosh|Mac OS X/.test(ua)) return navigator.maxTouchPoints > 1 ? "ios" : "mac";
    if (/Linux|X11/.test(ua)) return "linux";
    return "android";
  }
  function safeHref(u) {
    u = String(u || "");
    return /^[a-z][a-z0-9+.\-]*:\/\//i.test(u) && !/^(javascript|data|vbscript|file):/i.test(u) ? u : "#";
  }
  function appLink(a, link) {
    if (!a.add) return safeHref(a.dl);
    if (a.fmt === "sr") {
      var b = "";
      try { b = btoa(unescape(encodeURIComponent(link))); } catch (e) { noop(); }
      return safeHref(a.add + b + "?remark=" + encodeURIComponent(S.brand.name || ""));
    }
    return safeHref(a.add + encodeURIComponent(link));
  }
  function addAppButtons(row, link, before, label) {
    if (!/^https?:\/\//i.test(link)) return;
    loadApps().then(function (apps) {
      var list = (apps[detectPlatform()] || []).filter(function (a) { return a.add; }).slice(0, 3);
      list.forEach(function (a) {
        row.insertBefore(h("a", { class: "btn small" + (label ? "" : " ghost"), href: appLink(a, link), text: label ? t("done_add", { app: a.n }) : a.n }), before || null);
      });
      row.insertBefore(h("button", { class: "btn small ghost", type: "button", text: t("app_all"), onclick: function () { appsSheet(link); } }), before || null);
    });
  }
  function appCard(a, link) {
    var row = h("div", { class: "row" });
    if (link && a.add) row.appendChild(h("a", { class: "btn small", href: appLink(a, link), text: t("app_add") }));
    if (a.dl) row.appendChild(h("a", { class: "btn small ghost", href: safeHref(a.dl), target: "_blank", rel: "noopener noreferrer", text: t("app_download") }));
    return h("div", { class: "app-card" + (a.rec ? " rec" : "") },
      h("div", { class: "row between" }, h("h3", { text: a.n }), a.rec ? h("span", { class: "badge ok", text: t("app_rec") }) : null),
      a.d && lang === "fa" ? h("p", { text: a.d }) : null, row);
  }
  function platTabs(active, onPick) {
    var tabs = h("div", { class: "tabs", role: "tablist" });
    PLAT_ORDER.forEach(function (k) {
      tabs.appendChild(h("button", { type: "button", role: "tab", "aria-selected": String(k === active), text: t("plat_" + k), onclick: function () { onPick(k); } }));
    });
    return tabs;
  }
  function appsSheet(link) {
    var box = h("div", { class: "stack" }, spinnerBlock());
    openSheet(t("apps_sheet_title"), box);
    loadApps().then(function (apps) {
      var active = detectPlatform();
      var tabsHost = h("div");
      var list = h("div", { class: "app-list" });
      function draw() {
        tabsHost.textContent = "";
        tabsHost.appendChild(platTabs(active, function (k) { active = k; draw(); }));
        list.textContent = "";
        (apps[active] || []).forEach(function (a) { list.appendChild(appCard(a, link)); });
        if (!list.firstChild) list.appendChild(h("p", { class: "mute", text: t("apps_none") }));
      }
      draw();
      box.textContent = "";
      box.appendChild(h("p", { class: "mute small-t", text: t("apps_sheet_hint") }));
      box.appendChild(tabsHost);
      box.appendChild(list);
    });
  }
  var S = {
    token: "",
    user: null,
    catalog: null,
    cfg: { turnstile_site_key: "", email_enabled: false },
    brand: { name: "ShopVPN", logo: "", tagline: "", color: "" },
    next: ""
  };
  var timers = [];
  var ts = { token: "", loading: false, queue: [] };

  function t(key, vars) {
    var s = T[key];
    if (s == null) s = I18N.fa[key];
    if (s == null) return key;
    if (typeof s !== "string") return s;
    if (vars) Object.keys(vars).forEach(function (k) { s = s.split("{" + k + "}").join(vars[k]); });
    return s;
  }
  function $(id) { return document.getElementById(id); }
  function noop() {}

  var store = {
    get: function (k) { try { return localStorage.getItem(k) || ""; } catch (e) { return ""; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) { noop(); } },
    del: function (k) { try { localStorage.removeItem(k); } catch (e) { noop(); } }
  };
  S.token = store.get("sv-token");

  function add(node, kid) {
    if (kid == null || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(function (k) { add(node, k); }); return; }
    node.appendChild(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  function h(tag, props) {
    var n = document.createElement(tag);
    props = props || {};
    Object.keys(props).forEach(function (k) {
      var v = props[k];
      if (v == null || v === false) return;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k === "value") n.value = v;
      else if (k === "style") Object.keys(v).forEach(function (s) { n.style[s] = v[s]; });
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), v);
      else if (v === true) n.setAttribute(k, "");
      else n.setAttribute(k, v);
    });
    for (var i = 2; i < arguments.length; i++) add(n, arguments[i]);
    return n;
  }
  function svg(tag, attrs) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    for (var i = 2; i < arguments.length; i++) add(n, arguments[i]);
    return n;
  }

  function fmt(n) { return new Intl.NumberFormat(lang === "fa" ? "fa-IR" : "en-US").format(n); }
  function money(n) { return fmt(n) + " " + t("currency"); }
  function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }
  function reducedMotion() { return window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches; }
  function networkNotice() {
    if (navigator.onLine) { toast(t("network_back") || "Connection restored", "ok"); }
    else { toast(t("network_offline") || "You are offline", "warn"); }
  }
  window.addEventListener("online", networkNotice);
  window.addEventListener("offline", networkNotice);

  function every(fn, ms) { var id = setInterval(fn, ms); timers.push(id); return id; }
  function later(fn, ms) { var id = setTimeout(fn, ms); timers.push(id); return id; }
  function stopTimers() {
    timers.forEach(function (id) { clearInterval(id); clearTimeout(id); });
    timers = [];
  }

  function toast(msg, kind) {
    var n = h("div", { class: "toast" + (kind ? " " + kind : ""), role: "status", text: msg });
    $("toasts").appendChild(n);
    later(function () { n.classList.add("out"); }, 1850);
    later(function () { n.remove(); }, 2250);
  }
  function skeletonCards(count) {
    var box = h("div", { class: "skeleton-grid", "aria-hidden": "true" });
    for (var i = 0; i < (count || 3); i++) {
      box.appendChild(h("div", { class: "skeleton-card card" },
        h("i", { class: "sk sk-line wide" }), h("i", { class: "sk sk-line" }),
        h("i", { class: "sk sk-block" }), h("i", { class: "sk sk-line short" }),
        h("i", { class: "sk sk-btn" })));
    }
    return box;
  }
  function copyText(text) {
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); toast(t("copied")); } catch (e) { noop(); }
      ta.remove();
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { toast(t("copied")); }, fallback);
    } else fallback();
  }

  function api(path, opts) {
    opts = opts || {};
    var headers = { "X-Language": lang };
    if (S.token) headers["X-Web-Token"] = S.token;
    if (ts.token && (/^\/api\/web\/email\/(start|verify)$/.test(path) || path === "/api/orders")) {
      headers["X-Turnstile-Token"] = ts.token;
      ts.token = "";
    }
    var body;
    if (opts.form) body = opts.form;
    else if (opts.body) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
    var controller = window.AbortController ? new AbortController() : null;
    var timeout = controller ? window.setTimeout(function () { controller.abort(); }, opts.timeout || 15000) : null;
    return fetch(path, { method: opts.method || "GET", headers: headers, body: body, cache: "no-store", credentials: "same-origin", signal: controller ? controller.signal : undefined }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) {
          var det = d && d.detail;
          var e = new Error(typeof det === "string" ? det : (det && det.message) || r.statusText);
          e.status = r.status;
          e.detail = det;
          throw e;
        }
        return d;
      });
    }).catch(function (e) {
      if (e && e.name === "AbortError") {
        var te = new Error(t("network_timeout") || "Request timed out");
        te.code = "TIMEOUT";
        throw te;
      }
      throw e;
    }).finally(function () {
      if (timeout) window.clearTimeout(timeout);
    });
  }
  function fetchBlob(path, opts) {
    opts = opts || {};
    var headers = { "X-Web-Token": S.token, "X-Language": lang };
    var controller = window.AbortController ? new AbortController() : null;
    var timeout = controller ? window.setTimeout(function () { controller.abort(); }, opts.timeout || 15000) : null;
    return fetch(path, {
      headers: headers,
      cache: "no-store",
      credentials: "same-origin",
      signal: controller ? controller.signal : undefined
    }).then(function (r) {
      if (!r.ok) {
        var e = new Error("blob");
        e.status = r.status;
        throw e;
      }
      return r.blob();
    }).catch(function (e) {
      if (e && e.name === "AbortError") {
        var te = new Error(t("network_timeout") || "Request timed out");
        te.code = "TIMEOUT";
        throw te;
      }
      throw e;
    }).finally(function () {
      if (timeout) window.clearTimeout(timeout);
    });
  }

  function loadTurnstile(cb) {
    if (!S.cfg.turnstile_site_key) { cb(false); return; }
    if (window.turnstile) { cb(true); return; }
    ts.queue.push(cb);
    if (ts.loading) return;
    ts.loading = true;
    var s = document.createElement("script");
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    s.async = true;
    s.onload = function () { var q = ts.queue; ts.queue = []; q.forEach(function (f) { f(true); }); };
    s.onerror = function () { var q = ts.queue; ts.queue = []; ts.loading = false; q.forEach(function (f) { f(false); }); };
    document.head.appendChild(s);
  }
  function turnstileBox() {
    var box = h("div", { class: "turnstile" });
    if (!S.cfg.turnstile_site_key) return box;
    requestAnimationFrame(function () {
      loadTurnstile(function (ok) {
        if (!ok || !box.isConnected) return;
        ts.token = "";
        box._wid = window.turnstile.render(box, {
          sitekey: S.cfg.turnstile_site_key,
          callback: function (v) { ts.token = v || ""; },
          "expired-callback": function () { ts.token = ""; },
          "error-callback": function () { ts.token = ""; }
        });
      });
    });
    return box;
  }
  function removeTurnstile(box) {
    if (window.turnstile && box && box._wid != null) { try { window.turnstile.remove(box._wid); } catch (e) { noop(); } box._wid = null; }
    ts.token = "";
  }
  function resetTurnstile(box) {
    ts.token = "";
    if (window.turnstile && box && box._wid != null) { try { window.turnstile.reset(box._wid); } catch (e) { noop(); } }
  }

  function luminance(hex) {
    var c = [1, 3, 5].map(function (i) {
      var v = parseInt(hex.slice(i, i + 2), 16) / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  function readableOn(hex) {
    var l = luminance(hex);
    var dark = (l + 0.05) / (luminance("#070A1A") + 0.05);
    var light = (1.05) / (l + 0.05);
    return dark >= light ? "#070A1A" : "#FFFFFF";
  }
  function applyBrand(b) {
    b = b || {};
    if (b.store_name) S.brand.name = b.store_name;
    if (b.logo != null) S.brand.logo = b.logo;
    if (b.tagline != null) S.brand.tagline = b.tagline;
    var name = S.brand.name || "ShopVPN";
    $("brandName").textContent = name;
    $("footName").textContent = name;
    $("brand").setAttribute("aria-label", name);
    var logo = $("brandLogo");
    if (S.brand.logo) { logo.src = S.brand.logo; logo.hidden = false; $("brandMark").hidden = true; }
    else { logo.hidden = true; $("brandMark").hidden = false; }
    $("footTag").textContent = S.brand.tagline || "";
    var color = String(b.primary_color || "").trim();
    if (/^#[0-9a-fA-F]{6}$/.test(color)) {
      root.style.setProperty("--accent", color);
      root.style.setProperty("--on-accent", readableOn(color));
    }
    var sup = String(b.support_url || "");
    var supLink = $("supportLink");
    if (/^https?:\/\//i.test(sup)) { supLink.href = sup; supLink.hidden = false; }
    var bot = String(b.bot_url || "");
    var botLink = $("botLink");
    if (/^https?:\/\//i.test(bot)) { botLink.href = bot; botLink.hidden = false; }
    if (b.theme === "dark" || b.theme === "light") root.setAttribute("data-theme", b.theme);
  }

  function setUser(u) {
    S.user = u || null;
    $("loginBtn").hidden = !!u;
    $("accountBtn").hidden = !u;
    $("logoutBtn").hidden = !u;
  }
  function doLogout() {
    api("/api/web/logout", { method: "POST" }).catch(noop).then(function () { stopTimers(); dropToken(); go("#/"); });
  }
  function dropToken() { S.token = ""; store.del("sv-token"); setUser(null); }
  function loadSession() {
    if (!S.token) { setUser(null); return Promise.resolve(); }
    return api("/api/web/session").then(setUser).catch(function (e) {
      if (e.status === 401 || e.status === 403) dropToken(); else setUser(null);
    });
  }
  var catalogP = null;
  function loadCatalog() {
    if (!catalogP) {
      catalogP = api("/api/web/catalog").then(function (d) { S.catalog = d; applyBrand(d); return d; });
      catalogP.catch(function () { catalogP = null; });
    }
    return catalogP;
  }
  var cfgP = null;
  function loadConfig() {
    if (!cfgP) cfgP = api("/api/web/security-config").then(function (c) { S.cfg = c || S.cfg; return S.cfg; }).catch(function () { cfgP = null; return S.cfg; });
    return cfgP;
  }

  function mount(node, title) {
    var v = $("view");
    v.classList.remove("page-enter");
    void v.offsetWidth;
    v.textContent = "";
    v.appendChild(node);
    v.classList.add("page-enter");
    var base = S.brand.name || "ShopVPN";
    document.title = title ? title + " | " + base : base;
    window.scrollTo(0, 0);
  }
  function spinnerBlock() {
    return h("div", { class: "center", role: "status" }, h("span", { class: "spinner" }), h("span", { class: "mute", text: t("loading") }));
  }
  function alertBox(msg, info) { return h("div", { class: "alert" + (info ? " info" : ""), role: "alert", text: msg }); }
  function kv(k, v, ltr) { return h("div", { class: "kv" }, h("span", { class: "mute", text: k }), h("b", { class: "num" + (ltr ? " ltr" : ""), text: v })); }
  function copyBox(text) {
    return h("div", { class: "copy-box" },
      h("code", { text: text }),
      h("button", { class: "btn small ghost", type: "button", text: t("copy"), onclick: function () { copyText(text); } }));
  }
  function statusBadge(status) {
    var cls = status === "approved" ? "ok" : (status === "rejected" || status === "cancelled" ? "bad" : "warn");
    var label = T["st_" + status] || status;
    return h("span", { class: "badge " + cls, text: label });
  }

  function fail(e, notice, retry) {
    notice.textContent = "";
    if (e.status === 401) { dropToken(); S.next = location.hash; go("#/login"); return; }
    var d = e.detail;
    if (e.status === 403 && d && typeof d === "object" && d.code === "force_join") {
      notice.appendChild(h("div", { class: "card stack" },
        h("h3", { text: t("fj_title") }),
        h("p", { class: "mute", text: d.message || "" }),
        h("div", { class: "row" },
          (d.channels && d.channels.length ? d.channels : [{ channel: d.channel, join_link: d.join_link }])
            .filter(function (c) { return c.join_link; })
            .map(function (c, i, all) {
              return h("a", { class: "btn", href: c.join_link, target: "_blank", rel: "noopener",
                text: t("fj_join") + (all.length > 1 ? " " + (c.channel || (i + 1)) : "") });
            }),
          h("button", { class: "btn ghost", type: "button", text: t("fj_retry"), onclick: function () { notice.textContent = ""; if (retry) retry(); } }))));
      return;
    }
    if (e.status === 403 && d && typeof d === "object" && d.code === "terms_required") {
      notice.appendChild(h("div", { class: "card stack" },
        h("h3", { text: t("terms_title") }),
        h("p", { class: "mute", style: { whiteSpace: "pre-line" }, text: d.text || "" }),
        h("button", {
          class: "btn", type: "button", text: t("terms_accept"),
          onclick: function () {
            api("/api/terms/accept", { method: "POST" }).then(function () { notice.textContent = ""; if (retry) retry(); }).catch(function (x) { fail(x, notice, retry); });
          }
        })));
      return;
    }
    notice.appendChild(alertBox(e.status ? e.message : t("net_err")));
  }

  function tunnelPoint(u) {
    function bez(p0, c1, c2, p1, k) {
      var m = 1 - k;
      return [
        m * m * m * p0[0] + 3 * m * m * k * c1[0] + 3 * m * k * k * c2[0] + k * k * k * p1[0],
        m * m * m * p0[1] + 3 * m * m * k * c1[1] + 3 * m * k * k * c2[1] + k * k * k * p1[1]
      ];
    }
    if (u < 0.5) return bez([48, 120], [130, 20], [210, 20], [250, 90], u * 2);
    return bez([250, 90], [290, 160], [370, 160], [432, 60], (u - 0.5) * 2);
  }
  function buildTunnel(stopCount) {
    var d = "M48 120C130 20 210 20 250 90S370 160 432 60";
    var g = svg("linearGradient", { id: "tg", x1: "0", x2: "1", y1: "0", y2: "0" },
      svg("stop", { offset: "0", class: "s1" }), svg("stop", { offset: "1", class: "s2" }));
    var s = svg("svg", { viewBox: "0 0 480 180", role: "img", "aria-label": t("tunnel_label") }, svg("defs", {}, g));
    s.appendChild(svg("path", { class: "track", d: d }));
    s.appendChild(svg("path", { class: "flow", d: d }));
    var stops = [];
    for (var i = 0; i < stopCount; i++) {
      var p = tunnelPoint((i + 1) / (stopCount + 1));
      var c = svg("circle", { class: "stop", cx: p[0].toFixed(1), cy: p[1].toFixed(1), r: "9" });
      stops.push({ el: c, x: p[0], y: p[1] });
      s.appendChild(c);
    }
    s.appendChild(svg("circle", { class: "node", cx: "48", cy: "120", r: "24" }));
    s.appendChild(svg("rect", { class: "glyph", x: "40", y: "108", width: "16", height: "24", rx: "3" }));
    s.appendChild(svg("circle", { class: "node", cx: "432", cy: "60", r: "26" }));
    s.appendChild(svg("circle", { class: "glyph", cx: "432", cy: "60", r: "12" }));
    s.appendChild(svg("path", { class: "glyph", d: "M420 60h24M432 48c-6 6-6 18 0 24M432 48c6 6 6 18 0 24" }));
    var packet = svg("circle", { class: "packet", cx: "0", cy: "0", r: "7" });
    packet.style.transform = "translate(48px,120px)";
    s.appendChild(packet);
    return {
      node: s,
      select: function (idx) {
        stops.forEach(function (st, k) { st.el.setAttribute("class", "stop" + (k <= idx ? " on" : "")); });
        var st = stops[idx];
        if (st) packet.style.transform = "translate(" + st.x.toFixed(1) + "px," + st.y.toFixed(1) + "px)";
      }
    };
  }

  function allProducts(c) {
    var out = [];
    (c.categories || []).forEach(function (cat) { cat.products.forEach(function (p) { out.push(p); }); });
    return out;
  }
  function discountPercent(p) {
    return p.original_price && p.original_price > p.price ? Math.round((1 - p.price / p.original_price) * 100) : 0;
  }

  function buildHero() {
    var lead = h("p", { class: "lead", text: t("hero_sub") });
    var quick = h("div", { class: "quick" });
    var tunnelHost = h("div", { class: "tunnel" });
    var node = h("section", { class: "wrap hero" },
      h("div", null,
        h("h1", { text: t("hero_title") }),
        lead,
        h("div", { class: "cta" },
          h("a", { class: "btn", href: "#/plans", text: t("hero_cta") }),
          h("a", { class: "btn ghost", href: "#/guide", text: t("hero_cta2") }))),
      tunnelHost);
    tunnelHost.appendChild(buildTunnel(3).node);
    return {
      node: node,
      bind: function (c) {
        if (c.tagline) lead.textContent = c.tagline;
        var list = allProducts(c).filter(function (p) { return p.in_stock; }).slice(0, 4);
        if (!list.length) return;
        var tun = buildTunnel(list.length);
        tunnelHost.textContent = "";
        tunnelHost.appendChild(tun.node);
        tunnelHost.appendChild(quick);
        var sel = 0;
        var seg = h("div", { class: "seg", role: "group", "aria-label": t("quick_label") });
        var priceEl = h("div", { class: "price num" });
        var cta = h("a", { class: "btn", text: t("buy_now") });
        function draw() {
          var p = list[sel];
          Array.prototype.forEach.call(seg.children, function (b, k) { b.setAttribute("aria-pressed", String(k === sel)); });
          priceEl.textContent = "";
          priceEl.appendChild(document.createTextNode(fmt(p.price)));
          priceEl.appendChild(h("small", { text: t("currency") }));
          cta.href = "#/buy/" + p.id;
          tun.select(sel);
        }
        list.forEach(function (p, k) {
          seg.appendChild(h("button", { type: "button", text: p.name, title: p.name, onclick: function () { sel = k; draw(); } }));
        });
        quick.appendChild(seg);
        quick.appendChild(h("div", { class: "quick-go" }, priceEl, cta));
        draw();
      }
    };
  }

  function planCard(p, featured) {
    var off = discountPercent(p);
    var days = Number(p.duration_days || 0);
    var gb = Number(p.volume_gb || 0);
    var specs = h("div", { class: "plan-specs" });
    if (gb > 0) specs.appendChild(h("span", null, h("b", { class: "num", text: fmt(gb) }), " ", t("plan_gb")));
    else specs.appendChild(h("span", null, h("b", { text: t("plan_unlimited") })));
    if (days > 0) specs.appendChild(h("span", null, h("b", { class: "num", text: fmt(days) }), " ", t("plan_days")));
    else specs.appendChild(h("span", null, h("b", { text: t("plan_unlimited") })));
    return h("article", { class: "plan plan-premium" + (p.in_stock ? "" : " off") + (featured ? " featured" : "") },
      h("div", { class: "plan-topline" },
        h("span", { class: "plan-status" }, h("i"), h("span", { text: p.in_stock ? t("plan_stock") : t("plan_unavailable") })),
        off ? h("span", { class: "badge ok num", text: fmt(off) + "% " + t("off") }) : null),
      featured ? h("span", { class: "plan-featured", text: t("plan_best") }) : null,
      h("div", { class: "plan-title-row" }, h("h3", { text: p.name }), h("span", { class: "plan-value", text: t("plan_value") })),
      h("p", { class: "desc", text: p.description || "" }),
      specs,
      h("div", { class: "plan-bottom" },
        h("div", { class: "plan-price" },
          off ? h("div", { class: "old num" }, money(p.original_price)) : null,
          h("div", { class: "price num" }, fmt(p.price), h("small", { text: t("currency") }))),
        p.in_stock
          ? h("a", { class: "btn", href: "#/buy/" + p.id, text: t("buy") })
          : h("span", { class: "badge bad", text: t("sold_out") })));
  }
  function fillPlans(box, c) {
    box.textContent = "";
    var cats = c.categories || [];
    if (!cats.length) { box.appendChild(alertBox(t("plans_empty"), true)); return; }
    var active = "all";
    var sort = "value";
    var chips = h("div", { class: "chips", role: "tablist" });
    var controls = h("div", { class: "catalog-controls" });
    var count = h("span", { class: "catalog-count" });
    var sortWrap = h("label", { class: "sort-control" }, h("span", { text: t("sort_label") }));
    var sortSelect = h("select", { class: "input", "aria-label": t("sort_label") });
    [["value", t("sort_value")], ["low", t("sort_low")], ["high", t("sort_high")]].forEach(function (x) { sortSelect.appendChild(h("option", { value: x[0], text: x[1] })); });
    sortSelect.value = sort;
    sortSelect.addEventListener("change", function () { sort = sortSelect.value; draw(); });
    sortWrap.appendChild(sortSelect);
    controls.appendChild(count);
    controls.appendChild(sortWrap);
    var grid = h("div", { class: "plans" });
    var locFilter = null;
    var filterBar = h("div", { class: "catalog-count" });
    if (window.__svNetmapFilter) window.removeEventListener("sv:netmap-filter", window.__svNetmapFilter);
    window.__svNetmapFilter = function (ev) {
      var d = ev && ev.detail;
      locFilter = d && d.ids && d.ids.length ? { ids: d.ids.map(String), label: d.label || "" } : null;
      active = "all";
      draw();
    };
    window.addEventListener("sv:netmap-filter", window.__svNetmapFilter);
    function draw() {
      chips.textContent = "";
      [{ id: "all", name: t("all") }].concat(cats).forEach(function (cat) {
        chips.appendChild(h("button", {
          class: "chip", type: "button", role: "tab", "aria-selected": String(active === cat.id), text: cat.name,
          onclick: function () { active = cat.id; draw(); }
        }));
      });
      var items = [];
      cats.forEach(function (cat) {
        if (active !== "all" && active !== cat.id) return;
        (cat.products || []).forEach(function (p) { items.push(p); });
      });
      items.sort(function (a, b) {
        if (sort === "low") return Number(a.price) - Number(b.price);
        if (sort === "high") return Number(b.price) - Number(a.price);
        var av = Number(a.price) / Math.max(1, Number(a.volume_gb || 0));
        var bv = Number(b.price) / Math.max(1, Number(b.volume_gb || 0));
        return (discountPercent(b) - discountPercent(a)) || (av - bv);
      });
      if (locFilter) items = items.filter(function (p) { return locFilter.ids.indexOf(String(p.id)) > -1; });
      filterBar.textContent = "";
      if (locFilter) {
        filterBar.appendChild(h("button", { class: "chip", type: "button", text: (lang === "fa" ? "فقط " : "Only ") + locFilter.label + "  ✕", onclick: function () { locFilter = null; draw(); } }));
      }
      count.textContent = fmt(items.length) + " " + (lang === "fa" ? "پلن" : "plans");
      grid.textContent = "";
      var featuredId = items.length ? items[0].id : null;
      items.forEach(function (p) { grid.appendChild(planCard(p, p.id === featuredId && items.length > 1)); });
    }
    draw();
    if (cats.length > 1) box.appendChild(chips);
    box.appendChild(controls);
    box.appendChild(filterBar);
    box.appendChild(grid);
  }

  function howSection() {
    function step(n, title, desc) {
      return h("div", { class: "flow-step" }, h("span", { class: "dot num", text: fmt(n) }), h("div", null, h("h3", { text: title }), h("p", { text: desc })));
    }
    return h("section", { class: "sec wrap", "aria-labelledby": "howH" },
      h("h2", { id: "howH", text: t("how_title") }),
      h("div", { class: "flow-steps" },
        step(1, t("how1_t"), t("how1_d")),
        step(2, t("how2_t"), t("how2_d")),
        step(3, t("how3_t"), t("how3_d"))));
  }
  function faqList(limit) {
    var items = T.faq.slice(0, limit || T.faq.length);
    return h("div", { class: "faq" }, items.map(function (qa) { return h("details", null, h("summary", { text: qa[0] }), h("p", { text: qa[1] })); }));
  }
  function faqSection() {
    return h("section", { class: "sec wrap", "aria-labelledby": "faqH" },
      h("h2", { id: "faqH", text: t("faq_title") }),
      faqList(4),
      h("p", { style: { marginTop: "16px" } }, h("a", { class: "btn ghost", href: "#/faq", text: t("faq_all") })));
  }


  function storefrontHighlights() {
    var faMode = lang === "fa";
    var data = faMode ? {
      eyebrow:"چرا ShopVPN؟", title:"یک فروشگاه VPN که برای خرید سریع ساخته شده", sub:"همه‌چیز ساده است: پلن را انتخاب کن، پرداخت کن و سرویس را همان لحظه تحویل بگیر.",
      cards:[
        ["⚡","تحویل فوری","بعد از تأیید پرداخت، لینک اشتراک مستقیم داخل حساب تو قرار می‌گیرد."],
        ["🛡️","حریم خصوصی","لینک اشتراک شخصی است و فقط برای حساب خودت نمایش داده می‌شود."],
        ["↻","به‌روزرسانی آسان","یک لینک اشتراک کافی است؛ کانفیگ‌های سرویس را از همان‌جا به‌روز کن."],
        ["◉","پشتیبانی واقعی","اگر پرداخت یا اتصال مشکلی داشت، از داخل حساب تیکت بفرست."]
      ]
    } : {
      eyebrow:"WHY SHOPVPN", title:"A VPN store built for fast, simple buying", sub:"Choose a plan, pay, and get your subscription without unnecessary steps.",
      cards:[
        ["⚡","Instant delivery","After payment is confirmed, your subscription link appears in your account."],
        ["🛡️","Privacy first","Your private subscription link is only exposed inside your account."],
        ["↻","Easy updates","Use one subscription link and keep your configs up to date."],
        ["◉","Human support","If payment or connection gets stuck, open a support ticket from your account."]
      ]
    };
    return h("section", { class:"sec wrap premium-highlights", "aria-labelledby":"whyShopvpn" },
      h("div", { class:"section-kicker", text:data.eyebrow }),
      h("h2", { id:"whyShopvpn", text:data.title }),
      h("p", { class:"sub", text:data.sub }),
      h("div", { class:"highlight-grid" }, data.cards.map(function(c){
        return h("article", {class:"highlight-card"}, h("div",{class:"highlight-icon",text:c[0]}), h("h3",{text:c[1]}), h("p",{text:c[2]}));
      }))
    );
  }

  function deviceSection() {
    var faMode = lang === "fa";
    var title = faMode ? "روی دستگاه خودت، بدون دردسر" : "Works across the devices you already use";
    var sub = faMode ? "اندروید، آیفون، ویندوز، مک و لینوکس؛ راهنمای اتصال برای هرکدام آماده است." : "Android, iPhone, Windows, Mac and Linux — with a simple setup guide for each.";
    var devices = faMode ? [["Android","اندروید"],["iOS","آیفون و آیپد"],["Windows","ویندوز"],["macOS","مک"],["Linux","لینوکس"]] : [["Android","Android"],["iOS","iPhone & iPad"],["Windows","Windows"],["macOS","Mac"],["Linux","Linux"]];
    return h("section", {class:"sec wrap device-section", "aria-labelledby":"deviceTitle"},
      h("div", {class:"device-copy"}, h("div",{class:"section-kicker",text:faMode?"همه‌جا آماده‌ای":"READY EVERYWHERE"}), h("h2",{id:"deviceTitle",text:title}), h("p",{class:"sub",text:sub}), h("a",{class:"btn ghost",href:"#/guide",text:faMode?"دیدن راهنمای اتصال":"View connection guide"})),
      h("div",{class:"device-grid"},devices.map(function(d,i){return h("div",{class:"device-card"},h("span",{class:"device-logo",text:["A","⌁","W","","L"][i]}),h("b",{text:d[0]}),h("small",{text:d[1]}));}))
    );
  }

  function testimonialSection() {
    var faMode = lang === "fa";
    var title = faMode ? "تجربه‌ای که بعد از خرید باید داشته باشی" : "The experience after you click buy";
    var quotes = faMode ? [
      ["سارا", "خرید خیلی سریع انجام شد و لینک اشتراک را همان لحظه داخل حساب دیدم."],
      ["محمد", "راهنمای اتصال واضح بود؛ روی گوشی و لپ‌تاپ بدون دردسر وصل شدم."],
      ["رضا", "اینکه سفارش، سرویس و تمدید همه در یک حساب هستند خیلی کاربردی است."]
    ] : [
      ["Sara", "Checkout was quick and my subscription link appeared in the account right away."],
      ["Mohammad", "The setup guide was clear. I connected on both phone and laptop without friction."],
      ["Reza", "Having orders, services and renewals in one account makes everything much easier."]
    ];
    return h("section", {class:"sec wrap testimonial-section", "aria-labelledby":"socialProofTitle"},
      h("div",{class:"row between"},h("div",null,h("div",{class:"section-kicker",text:faMode?"نظر کاربران":"CUSTOMER NOTES"}),h("h2",{id:"socialProofTitle",text:title})),h("div",{class:"rating-pill"},"★ 4.9/5")),
      h("div",{class:"quote-grid"},quotes.map(function(q){return h("article",{class:"quote-card"},h("div",{class:"stars",text:"★★★★★"}),h("p",{text:"“"+q[1]+"”"}),h("b",{text:q[0]}));}))
    );
  }

  function finalCtaSection() {
    var faMode = lang === "fa";
    return h("section", {class:"wrap final-cta", "aria-labelledby":"finalCtaTitle"},
      h("div",null,h("div",{class:"section-kicker",text:faMode?"آماده‌ای؟":"READY WHEN YOU ARE"}),h("h2",{id:"finalCtaTitle",text:faMode?"پلن مناسب خودت را انتخاب کن":"Pick your plan and get connected"}),h("p",{text:faMode?"بدون پیچیدگی، بدون مراحل اضافه؛ از همین‌جا شروع کن.":"No unnecessary steps. Start from the plan that fits you."})),
      h("a",{class:"btn",href:"#/plans",text:faMode?"مشاهده پلن‌ها":"Explore plans"})
    );
  }

  function homePage(scrollToPlans) {
    var hero = buildHero();
    var plansBox = h("div");
    var plans = h("section", { class: "sec wrap", id: "plans", "aria-labelledby": "plansH" },
      h("h2", { id: "plansH", text: t("plans_title") }),
      h("p", { class: "sub", text: t("plans_sub") }),
      plansBox);
    var networkMap = window.ShopVPNNetworkMap && window.ShopVPNNetworkMap.create ? window.ShopVPNNetworkMap.create() : null;
    mount(h("div", null, hero.node, networkMap, storefrontHighlights(), plans, deviceSection(), howSection(), testimonialSection(), faqSection(), finalCtaSection()), "");
    plansBox.appendChild(skeletonCards(3));
    loadCatalog().then(function (c) {
      fillPlans(plansBox, c);
      hero.bind(c);
      if (scrollToPlans) plans.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth" });
    }).catch(function () {
      plansBox.textContent = "";
      plansBox.appendChild(alertBox(t("plans_err")));
      plansBox.appendChild(h("button", { class: "btn ghost", type: "button", text: t("retry"), onclick: function () { homePage(scrollToPlans); } }));
    });
    if (scrollToPlans) later(function () { plans.scrollIntoView({ behavior: "auto" }); }, 30);
  }

  function pageShell(title, sub, content) {
    return h("div", { class: "wrap page" }, h("h1", { text: title }), sub ? h("p", { class: "sub", text: sub }) : null, content);
  }
  function faqPage() {
    mount(pageShell(t("faq_title"), t("faq_page_sub"), faqList()), t("faq_title"));
  }
  function guidePage() {
    var active = detectPlatform();
    var tabsHost = h("div");
    var body = h("div", { class: "stack" });
    function steps(k) { return (T.guide && T.guide[k]) || I18N.fa.guide[k] || []; }
    function section(title, node) { return h("section", { class: "stack" }, h("h2", { text: title }), node); }
    function draw() {
      tabsHost.textContent = "";
      tabsHost.appendChild(platTabs(active, function (k) { active = k; draw(); }));
      body.textContent = "";
      body.appendChild(section(t("guide_steps_t"), h("ol", { class: "mute stack guide-steps" }, steps(active).map(function (x) { return h("li", { text: x }); }))));
      var appsBox = h("div", { class: "app-list" }, spinnerBlock());
      body.appendChild(section(t("guide_apps_t"), appsBox));
      loadApps().then(function (apps) {
        appsBox.textContent = "";
        (apps[active] || []).forEach(function (a) { appsBox.appendChild(appCard(a, "")); });
        if (!appsBox.firstChild) appsBox.appendChild(h("p", { class: "mute", text: t("apps_none") }));
      });
      body.appendChild(section(t("guide_tips_t"), h("ul", { class: "mute guide-list" }, T.guide_tips.map(function (x) { return h("li", { text: x }); }))));
      body.appendChild(section(t("guide_errors"), h("ul", { class: "guide-list" }, T.guide_err.map(function (e) { return h("li", null, h("b", { text: e[0] + ": " }), e[1]); }))));
    }
    draw();
    var what = h("div", { class: "card guide-what" }, h("h2", { text: t("guide_what_t") }), h("p", { class: "mute", text: t("guide_what") }));
    mount(pageShell(t("guide_title"), t("guide_sub"), h("div", { class: "stack", style: { marginTop: "24px" } }, what, tabsHost, body)), t("guide_title"));
  }
  function termsPage() {
    var content = h("div", { class: "prose" }, T.terms.map(function (sec) {
      return h("section", null, h("h2", { text: sec[0] }), h("ul", null, sec[1].map(function (li) { return h("li", { text: li }); })));
    }));
    mount(pageShell(t("terms_title"), t("terms_page_sub"), content), t("terms_title"));
  }

  function loginPanel(onDone) {
    var statusBox = h("div", { class: "stack", "aria-live": "polite" });
    var tgBtn = h("button", { class: "btn block", type: "button", text: t("login_tg") });
    var visHandler = null;
    function finish(r) {
      S.token = r.token;
      store.set("sv-token", S.token);
      setUser(r.user);
      loadSession().then(onDone);
    }
    function stopWatch() {
      if (visHandler) { document.removeEventListener("visibilitychange", visHandler); visHandler = null; }
    }
    function expired() {
      stopTimers();
      stopWatch();
      statusBox.textContent = "";
      statusBox.appendChild(alertBox(t("login_expired")));
      statusBox.appendChild(h("button", { class: "btn ghost block", type: "button", text: t("login_retry"), onclick: start }));
    }
    function start() {
      var w = null;
      try { w = window.open("", "_blank"); if (w) w.opener = null; } catch (e) { w = null; }
      tgBtn.setAttribute("aria-busy", "true");
      tgBtn.disabled = true;
      statusBox.textContent = "";
      api("/api/web/login/start", { method: "POST" }).then(function (d) {
        tgBtn.removeAttribute("aria-busy");
        tgBtn.disabled = false;
        if (w) { try { w.location.href = d.link; } catch (e) { noop(); } }
        statusBox.appendChild(h("div", { class: "row" }, h("span", { class: "spinner" }), h("span", { text: t("login_wait") })));
        statusBox.appendChild(h("p", { class: "mute small-t", text: t("login_hint") }));
        statusBox.appendChild(h("a", { class: "btn ghost block", href: d.link, target: "_blank", rel: "noopener", text: t("login_open") }));
        var deadline = Date.now() + d.expires_in * 1000;
        function poll() {
          if (Date.now() > deadline) { expired(); return; }
          api("/api/web/login/poll", { method: "POST", body: { poll: d.poll } }).then(function (r) {
            if (r.status === "ok") { stopTimers(); stopWatch(); finish(r); }
            else if (r.status === "expired") expired();
          }).catch(noop);
        }
        every(poll, 2000);
        stopWatch();
        visHandler = function () { if (!document.hidden) poll(); };
        document.addEventListener("visibilitychange", visHandler);
      }).catch(function (e) {
        if (w) { try { w.close(); } catch (x) { noop(); } }
        tgBtn.removeAttribute("aria-busy");
        tgBtn.disabled = false;
        statusBox.appendChild(alertBox(e.status ? e.message : t("login_err")));
      });
    }
    tgBtn.addEventListener("click", start);
    var panel = h("div", { class: "stack" }, tgBtn, statusBox);
    loadConfig().then(function (cfg) {
      if (!cfg.email_enabled) return;
      var email = h("input", { class: "input ltr", type: "email", autocomplete: "email", maxlength: "254", placeholder: "name@example.com" });
      var code = h("input", { class: "input ltr", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6", placeholder: "123456" });
      var msg = h("div", { "aria-live": "polite" });
      var tsStart = turnstileBox();
      var tsCur = tsStart;
      var tsFresh = false;
      var tsVerify = h("div");
      var sendBtn = h("button", { class: "btn ghost block", type: "button", text: t("email_send") });
      var verifyBtn = h("button", { class: "btn block", type: "button", text: t("email_verify") });
      var codeWrap = h("div", { class: "stack", hidden: true }, h("label", { class: "field" }, h("span", { text: t("email_code") }), code), tsVerify, verifyBtn);
      sendBtn.addEventListener("click", function () {
        var v = email.value.trim();
        if (!v) { msg.textContent = ""; msg.appendChild(alertBox(t("email_required"))); return; }
        sendBtn.disabled = true;
        api("/api/web/email/start", { method: "POST", body: { email: v } }).then(function () {
          msg.textContent = "";
          msg.appendChild(alertBox(t("email_sent"), true));
          codeWrap.hidden = false;
          if (tsCur === tsStart) {
            removeTurnstile(tsStart);
            tsStart.remove();
            tsCur = turnstileBox();
            tsFresh = true;
            tsVerify.textContent = "";
            tsVerify.appendChild(tsCur);
          }
        }).catch(function (e) {
          msg.textContent = "";
          msg.appendChild(alertBox(e.status ? e.message : t("login_err")));
        }).then(function () {
          if (tsFresh) tsFresh = false; else resetTurnstile(tsCur);
          sendBtn.disabled = false;
        });
      });
      verifyBtn.addEventListener("click", function () {
        verifyBtn.disabled = true;
        api("/api/web/email/verify", { method: "POST", body: { email: email.value.trim(), code: code.value.trim() } }).then(function (r) {
          stopTimers();
          finish(r);
        }).catch(function (e) {
          msg.textContent = "";
          msg.appendChild(alertBox(e.status ? e.message : t("email_bad")));
          resetTurnstile(tsCur);
          verifyBtn.disabled = false;
        });
      });
      panel.appendChild(h("details", { class: "faq-d", open: true }, h("summary", { text: t("email_toggle") }),
        h("div", { class: "stack", style: { paddingBottom: "16px" } },
          h("label", { class: "field" }, h("span", { text: t("email_label") }), email), tsStart, sendBtn, msg, codeWrap)));
    });
    return panel;
  }

  function loginPage() {
    function done() {
      var n = S.next;
      S.next = "";
      go(n && n.indexOf("#/login") !== 0 ? n : "#/account");
    }
    if (S.token && S.user) { done(); return; }
    var buying = S.next.indexOf("#/buy") === 0;
    var card = h("div", { class: "card stack", style: { maxWidth: "480px", marginInline: "auto" } },
      h("h1", { style: { fontSize: "26px" }, text: buying ? t("buy_login") : t("login_title") }),
      h("p", { class: "mute", text: t("login_sub") }),
      loginPanel(done));
    mount(h("div", { class: "wrap page" }, card), t("login_title"));
  }

  function payFlow(box, res, opts) {
    var id = res.order_id;
    var notice = h("div", { role: "alert" });
    function step(n) { if (opts.onStep) opts.onStep(n); }
    function panel(title, kids) {
      box.textContent = "";
      box.appendChild(h("div", { class: "card stack" }, h("h2", { style: { fontSize: "22px" }, text: title }), kids, notice));
    }
    function rejected() {
      panel(t("pay_waiting"), alertBox(t("rejected")));
    }
    function watch(onTick) {
      var started = Date.now();
      var n = 0;
      every(function () {
        if (Date.now() - started > 45 * 60 * 1000) return;
        if (onTick) onTick(++n);
        api("/api/web/orders/" + id).then(function (o) {
          if (o.status === "approved") { stopTimers(); opts.onApproved(id); }
          else if (o.status === "rejected" || o.status === "cancelled") { stopTimers(); rejected(); }
        }).catch(noop);
      }, 4000);
    }
    function waiting(title, extra) {
      step(2);
      panel(title, h("div", { class: "stack" }, h("div", { class: "center" }, h("span", { class: "spinner" }), h("p", { class: "mute", text: t("pay_wait_hint") })), extra));
    }
    function gatewayWait(r) {
      var url = r.payment_url || r.invoice_url || r.pay_url || "";
      var row = h("div", { class: "row" });
      if (url && /^https?:\/\//i.test(url)) {
        row.appendChild(h("a", { class: "btn", href: url, target: "_blank", rel: "noopener", text: t("pay_open") }));
        try { window.open(url, "_blank", "noopener"); } catch (e) { noop(); }
      }
      if (r.bot_url && /^https?:\/\//i.test(r.bot_url)) row.appendChild(h("a", { class: "btn ghost", href: r.bot_url, target: "_blank", rel: "noopener", text: t("pay_bot") }));
      waiting(t("pay_waiting"), row);
      watch();
    }
    function manualCard() {
      step(2);
      var kids = h("div", { class: "stack" }, kv(t("c_amount"), money(res.final_price)));
      if (!res.card_number) { kids.appendChild(alertBox(t("c_nocard"))); panel(t("m_card"), kids); return; }
      kids.appendChild(h("div", { class: "stack" }, h("span", { class: "mute small-t", text: t("c_card") }), copyBox(String(res.card_number))));
      if (res.card_holder) kids.appendChild(kv(t("c_holder"), res.card_holder));
      var file = h("input", { type: "file", accept: "image/*" });
      var drop = h("label", { class: "drop" }, h("span", { class: "mute", text: t("c_pick") }), file);
      var send = h("button", { class: "btn block", type: "button", text: t("c_send"), disabled: true });
      file.addEventListener("change", function () {
        var f = file.files && file.files[0];
        send.disabled = !f;
        if (!f) return;
        drop.classList.add("has");
        drop.textContent = "";
        var img = h("img", { alt: t("c_receipt") });
        img.src = URL.createObjectURL(f);
        drop.appendChild(img);
        drop.appendChild(file);
      });
      send.addEventListener("click", function () {
        var f = file.files && file.files[0];
        if (!f) return;
        var fd = new FormData();
        fd.append("photo", f);
        send.disabled = true;
        send.setAttribute("aria-busy", "true");
        api("/api/orders/" + id + "/receipt", { method: "POST", form: fd }).then(function () {
          waiting(t("pay_waiting"), alertBox(t("c_sent"), true));
          watch();
        }).catch(function (e) { send.disabled = false; send.removeAttribute("aria-busy"); fail(e, notice, manualCard); });
      });
      kids.appendChild(h("div", { class: "stack" }, h("span", { class: "mute small-t", text: t("c_receipt") }), drop));
      kids.appendChild(send);
      panel(t("m_card"), kids);
    }
    function cardAuto(r) {
      step(2);
      var timeEl = h("div", { class: "timer", "aria-live": "off" });
      var kids = h("div", { class: "stack" },
        kv(t("c_amount"), money(r.amount_toman)),
        h("div", { class: "stack" }, h("span", { class: "mute small-t", text: t("c_card") }), copyBox(String(r.card_number || ""))));
      if (r.card_holder) kids.appendChild(kv(t("c_holder"), r.card_holder));
      if (r.bank_name) kids.appendChild(kv(t("c_bank"), r.bank_name));
      kids.appendChild(alertBox(t("c_exact"), true));
      kids.appendChild(h("div", { class: "center" }, h("span", { class: "mute small-t", text: t("c_left") }), timeEl, h("span", { class: "spinner" })));
      panel(t("m_auto"), kids);
      var stamp = String(r.expires_at || "");
      var end = stamp ? new Date(stamp.replace(" ", "T") + (/[zZ]|[+-]\d\d:?\d\d$/.test(stamp) ? "" : "Z")).getTime() : 0;
      function tick() {
        var s = Math.max(0, Math.round((end - Date.now()) / 1000));
        timeEl.textContent = end ? Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0") : "";
      }
      tick();
      every(tick, 1000);
      watch(function (n) {
        if (n % 2 === 0 && r.invoice_id) {
          api("/api/card-auto-invoice/" + r.invoice_id + "/status").then(function (s) {
            if (s.status === "expired") { stopTimers(); panel(t("m_auto"), alertBox(t("c_expired"))); }
          }).catch(noop);
        }
      });
    }
    function methods() {
      step(2);
      var list = h("div", { class: "methods" });
      var added = 0;
      box.textContent = "";
      box.appendChild(h("div", { class: "card stack" },
        h("h2", { style: { fontSize: "22px" }, text: t("methods_title") }), kv(t("total"), money(res.final_price)), list, notice));
      function addMethod(label, hint, run) {
        var b = h("button", { class: "method", type: "button" }, h("span", null, label, h("small", { text: hint })));
        b.addEventListener("click", function () {
          b.disabled = true;
          notice.textContent = "";
          run(function () { b.disabled = false; });
        });
        list.appendChild(b);
        added++;
      }
      function viaInvoice(path) {
        return function (done) {
          api(path, { method: "POST" }).then(gatewayWait).catch(function (e) { done(); fail(e, notice, methods); });
        };
      }
      if (res.card_to_card_enabled) addMethod(t("m_card"), t("m_card_h"), function (done) { manualCard(); done(); });
      if (res.card_to_card_auto_enabled) {
        addMethod(t("m_auto"), t("m_auto_h"), function (done) {
          api("/api/orders/" + id + "/card-auto-invoice", { method: "POST" }).then(cardAuto).catch(function (e) { done(); fail(e, notice, methods); });
        });
      }
      if (res.crypto_enabled) addMethod(t("m_crypto"), t("m_crypto_h"), viaInvoice("/api/orders/" + id + "/crypto-invoice"));
      if (res.abangateway_enabled) addMethod("AbanGateway", t("m_online_h"), viaInvoice("/api/orders/" + id + "/abangateway-invoice"));
      if (res.blupal_enabled) addMethod("Blupal", t("m_online_h"), viaInvoice("/api/orders/" + id + "/blupal-invoice"));
      if (res.noapay_enabled) addMethod("NoaPay", t("m_online_h"), viaInvoice("/api/orders/" + id + "/noapay-invoice"));
      (res.extra_gateways || []).forEach(function (g) {
        addMethod((g.icon ? g.icon + " " : "") + g.title, t("m_online_h"), viaInvoice("/api/orders/" + id + "/extra-invoice/" + encodeURIComponent(g.key)));
      });
      var q = "/api/gateways?amount=" + encodeURIComponent(res.final_price) + (opts.product ? "&product_id=" + encodeURIComponent(opts.product.id) : "");
      api(q).then(function (gs) {
        (gs || []).forEach(function (g) { addMethod(g.name, t("m_online_h"), viaInvoice("/api/orders/" + id + "/custom-invoice/" + encodeURIComponent(g.key))); });
      }).catch(noop).then(function () {
        if (!added) notice.appendChild(alertBox(t("m_none")));
      });
    }
    methods();
  }

  function deliveryView(box, orderId, attempt, opts) {
    attempt = attempt || 0;
    opts = opts || {};
    api("/api/web/orders/" + orderId).then(function (o) {
      if (o.status === "approved" && !o.links.length && attempt < 5) {
        later(function () { deliveryView(box, orderId, attempt + 1, opts); }, 2000);
        return;
      }
      if (opts.onStep) opts.onStep(3);
      var card = h("div", { class: "card stack" });
      card.appendChild(h("div", { class: "center" },
        svg("svg", { class: "success-mark", viewBox: "0 0 72 72", "aria-hidden": "true" }, svg("circle", { cx: "36", cy: "36", r: "32" }), svg("path", { d: "M22 37l10 10 18-21" })),
        h("h2", { style: { fontSize: "26px" }, text: t("done_title") })));
      card.appendChild(kv(o.product_name || "", o.quantity > 1 ? "× " + fmt(o.quantity) : ""));
      if (o.expires_at) card.appendChild(kv(t("done_exp"), String(o.expires_at).slice(0, 10), true));
      if (!o.links.length) card.appendChild(alertBox(t("done_empty"), true));
      o.links.forEach(function (link, i) {
        var qrHost = h("div", { class: "row" });
        var qrBtn = h("button", { class: "btn small ghost", type: "button", text: t("qr_show") });
        qrBtn.addEventListener("click", function () {
          if (qrHost.firstChild) { qrHost.textContent = ""; qrBtn.textContent = t("qr_show"); return; }
          var img = h("img", { class: "qr", alt: "QR", width: "180", height: "180" });
          qrHost.appendChild(img);
          qrBtn.textContent = t("qr_hide");
          fetchBlob("/api/web/orders/" + orderId + "/qr/" + i).then(function (bl) { img.src = URL.createObjectURL(bl); }).catch(function () { qrHost.textContent = ""; });
        });
        var row = h("div", { class: "row" });
        row.appendChild(qrBtn);
        addAppButtons(row, link, qrBtn, true);
        card.appendChild(h("div", { class: "stack" }, h("span", { class: "mute small-t", text: t("done_link") }), copyBox(link), row, qrHost));
      });
      card.appendChild(h("p", { class: "mute small-t", text: t("done_hint") }));
      card.appendChild(h("a", { class: "btn ghost", href: "#/account", text: t("done_account") }));
      if (opts.onDelivered) opts.onDelivered(card);
      box.textContent = "";
      box.appendChild(card);
    }).catch(function (e) {
      var n = h("div");
      box.textContent = "";
      box.appendChild(n);
      fail(e, n, function () { deliveryView(box, orderId, 0, opts); });
    });
  }

  function buyPage(parts) {
    if (!S.token) { S.next = location.hash; go("#/login"); return; }
    var id = parseInt(parts[0], 10);
    var labels = [t("st_details"), t("st_pay"), t("st_done")];
    var stepper = h("ol", { class: "stepper", "aria-label": t("summary") }, labels.map(function (l) { return h("li", { text: l }); }));
    function setStep(n) {
      Array.prototype.forEach.call(stepper.children, function (li, k) {
        if (k + 1 === n) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
        li.className = k + 1 < n ? "done" : "";
      });
    }
    var body = h("div");
    var aside = h("aside");
    setStep(1);
    mount(h("div", { class: "wrap buy" }, h("div", { class: "stack" }, stepper, body), aside), t("buy"));
    body.appendChild(spinnerBlock());

    loadCatalog().then(function (c) {
      var p = allProducts(c).filter(function (x) { return x.id === id; })[0];
      if (!p) {
        body.textContent = "";
        body.appendChild(h("div", { class: "card stack" }, alertBox(t("not_found")), h("a", { class: "btn ghost", href: "#/plans", text: t("nav_plans") })));
        return;
      }
      details(p);
    }).catch(function (e) {
      body.textContent = "";
      var n = h("div");
      body.appendChild(n);
      fail(e, n, function () { buyPage(parts); });
    });

    function summary(p, qty, total, saved) {
      aside.textContent = "";
      aside.appendChild(h("div", { class: "card stack" },
        h("h2", { style: { fontSize: "18px" }, text: t("summary") }),
        kv(p.name, qty > 1 ? "× " + fmt(qty) : ""),
        kv(t("unit_price"), money(p.price)),
        saved > 0 ? kv(t("saved"), money(saved)) : null,
        h("div", { class: "kv" }, h("span", { text: t("total") }), h("b", { class: "price num", text: money(total) }))));
    }

    function details(p) {
      var qty = 1;
      var tier = null;
      var seq = 0;
      var qtyOut = h("output", { class: "num", text: fmt(1) });
      var code = h("input", { class: "input ltr", type: "text", autocomplete: "off", maxlength: "64" });
      var notice = h("div", { role: "alert" });
      var tsBox = turnstileBox();
      var go1 = h("button", { class: "btn block", type: "button", text: t("continue_pay") });
      function refresh() {
        var base = p.price * qty;
        var total = tier != null ? tier : base;
        summary(p, qty, total, base - total);
      }
      function setQty(n) {
        qty = Math.min(10, Math.max(1, n));
        qtyOut.textContent = fmt(qty);
        var mine = ++seq;
        api("/api/tier-quote?product_id=" + p.id + "&quantity=" + qty).then(function (i) {
          if (mine !== seq) return;
          tier = i && i.total_after != null ? Number(i.total_after) : null;
          refresh();
        }).catch(function () { if (mine === seq) { tier = null; refresh(); } });
        tier = null;
        refresh();
      }
      var off = discountPercent(p);
      body.textContent = "";
      var days = Number(p.duration_days || 0);
      var gb = Number(p.volume_gb || 0);
      var productSpecs = h("div", { class: "checkout-specs" },
        h("div", null, h("span", { text: t("plan_gb") }), h("b", { text: gb > 0 ? fmt(gb) : t("plan_unlimited") })),
        h("div", null, h("span", { text: t("plan_days") }), h("b", { text: days > 0 ? fmt(days) : t("plan_unlimited") })),
        h("div", null, h("span", { text: t("plan_stock") }), h("b", { text: p.in_stock ? "✓" : "—" })));
      body.appendChild(h("div", { class: "card stack checkout-product" },
        h("div", { class: "checkout-product-head" },
          h("div", null, h("span", { class: "eyebrow", text: t("plan_value") }), h("h1", { style: { fontSize: "30px" }, text: p.name })),
          off ? h("span", { class: "badge ok num", text: fmt(off) + "% " + t("off") }) : null),
        p.description ? h("p", { class: "mute", style: { whiteSpace: "pre-line" }, text: p.description }) : null,
        productSpecs,
        h("div", { class: "row between" }, h("span", { text: t("qty") }),
          h("div", { class: "qty" },
            h("button", { type: "button", "aria-label": "-", text: "\u2212", onclick: function () { setQty(qty - 1); } }), qtyOut,
            h("button", { type: "button", "aria-label": "+", text: "+", onclick: function () { setQty(qty + 1); } }))),
        h("label", { class: "field" }, h("span", { text: t("code") }), code),
        tsBox, notice, go1));
      go1.addEventListener("click", function () {
        notice.textContent = "";
        go1.disabled = true;
        go1.setAttribute("aria-busy", "true");
        api("/api/orders", { method: "POST", body: { product_id: p.id, quantity: qty, discount_code: code.value.trim() || null } }).then(function (res) {
          try { history.replaceState(null, "", "#/order/" + res.order_id); } catch (e) { noop(); }
          var flowOpts = { product: p, onStep: setStep, onApproved: function (oid) { deliveryView(body, oid, 0, { onStep: setStep }); } };
          summary(p, qty, res.final_price, 0);
          if (res.status === "approved") deliveryView(body, res.order_id, 0, { onStep: setStep });
          else payFlow(body, res, flowOpts);
        }).catch(function (e) {
          go1.disabled = false;
          go1.removeAttribute("aria-busy");
          fail(e, notice, null);
        }).then(function () { resetTurnstile(tsBox); });
      });
      setQty(1);
    }
  }

  function orderPage(parts) {
    if (!S.token) { S.next = location.hash; go("#/login"); return; }
    var id = parseInt(parts[0], 10);
    var box = h("div");
    mount(h("div", { class: "wrap page", style: { maxWidth: "640px" } }, h("h1", { text: t("order_title") }), h("div", { class: "stack", style: { marginTop: "24px" } }, box)), t("order_title"));
    box.appendChild(h("div", { class: "card stack pending-card" }, skeletonCards(2)));
    function check() {
      api("/api/web/orders/" + id).then(function (o) {
        if (o.status === "approved") { stopTimers(); deliveryView(box, id, 0, {}); return; }
        box.textContent = "";
        if (o.status === "rejected" || o.status === "cancelled") {
          stopTimers();
          box.appendChild(h("div", { class: "card stack" }, alertBox(t("rejected")), h("a", { class: "btn ghost", href: "#/account/support", text: t("tab_support") })));
          return;
        }
        box.appendChild(h("div", { class: "card stack" },
          h("div", { class: "center" }, h("span", { class: "spinner" }), h("p", { class: "mute", text: t("order_pending") })),
          kv(o.product_name || "", money(o.final_price))));
      }).catch(function (e) {
        stopTimers();
        var n = h("div");
        box.textContent = "";
        box.appendChild(n);
        fail(e, n, check);
      });
    }
    check();
    every(check, 5000);
  }

  function openSheet(title, node, onClose) {
    var dlg = $("sheet");
    $("sheetTitle").textContent = title;
    var b = $("sheetBody");
    b.textContent = "";
    b.appendChild(node);
    function closed() {
      dlg.removeEventListener("close", closed);
      stopTimers();
      if (onClose) onClose();
    }
    dlg.addEventListener("close", closed);
    if (!dlg.open) dlg.showModal();
    return dlg;
  }
  function closeSheet() { var dlg = $("sheet"); if (dlg.open) dlg.close(); }

  function usageBlock(s, badges) {
    var usage = h("div", { class: "stack" });
    api("/api/sub-info?link=" + encodeURIComponent(s.link)).then(function (i) {
      if (!i || !i.ok) {
        if (s.expires_at) usage.appendChild(h("p", { class: "mute small-t num", text: t("svc_expiry") + ": " + String(s.expires_at).slice(0, 10) }));
        return;
      }
      var used = (i.upload || 0) + (i.download || 0);
      var gb = function (n) { return (n / 1073741824).toFixed(n >= 10737418240 ? 0 : 1); };
      if (i.total > 0) {
        var pct = Math.min(100, Math.round(used * 100 / i.total));
        var bar = h("div", { class: "bar" + (pct >= 90 ? " hot" : ""), role: "progressbar", "aria-valuenow": String(pct), "aria-valuemin": "0", "aria-valuemax": "100" }, h("i", { style: { width: pct + "%" } }));
        usage.appendChild(bar);
        usage.appendChild(h("p", { class: "mute small-t num", text: t("svc_used") + ": " + gb(used) + " / " + gb(i.total) + " GB" }));
      } else {
        usage.appendChild(h("p", { class: "mute small-t num", text: t("svc_used") + ": " + gb(used) + " GB \u00b7 " + t("svc_unlimited") }));
      }
      if (i.expire) {
        var left = Math.ceil((i.expire * 1000 - Date.now()) / 86400000);
        if (left <= 0) badges.appendChild(h("span", { class: "badge bad", text: t("badge_expired") }));
        usage.appendChild(h("p", { class: "mute small-t num", text: t("svc_expiry") + ": " + new Date(i.expire * 1000).toISOString().slice(0, 10) + (left > 0 ? " \u00b7 " + t("svc_left", { n: fmt(left) }) : "") }));
      }
    }).catch(noop);
    return usage;
  }

  function renewSheet(s, reload) {
    var box = h("div", { class: "stack" }, spinnerBlock());
    openSheet(t("renew_title"), box, reload);
    function success() {
      box.textContent = "";
      box.appendChild(h("div", { class: "center" }, alertBox(t("renew_ok"), true), h("button", { class: "btn", type: "button", text: t("close"), onclick: closeSheet })));
    }
    api("/api/custom-configs/" + s.id + "/renewal-full-plans").then(function (plans) {
      box.textContent = "";
      if (!plans.length) { box.appendChild(alertBox(t("renew_none"), true)); return; }
      var notice = h("div", { role: "alert" });
      var list = h("div", { class: "methods" });
      plans.forEach(function (p) {
        var label = p.name + " \u00b7 " + (p.volume_gb ? fmt(p.volume_gb) + " GB / " : "") + fmt(p.duration_days) + " " + t("days");
        var hint = money(p.price) + (p.discount_percent ? " (" + fmt(p.discount_percent) + "% " + t("off") + ")" : "");
        var b = h("button", { class: "method", type: "button" }, h("span", null, label, h("small", { text: hint })));
        b.addEventListener("click", function () {
          b.disabled = true;
          api("/api/custom-configs/" + s.id + "/renew-full", { method: "POST", body: { product_id: p.id } }).then(function (res) {
            if (res.status === "approved") success();
            else payFlow(box, res, { product: null, onApproved: success });
          }).catch(function (e) { b.disabled = false; fail(e, notice, null); });
        });
        list.appendChild(b);
      });
      box.appendChild(list);
      box.appendChild(notice);
    }).catch(function (e) {
      box.textContent = "";
      var n = h("div");
      box.appendChild(n);
      fail(e, n, null);
    });
  }

  function serviceCard(s, renewEnabled, reload) {
    var badges = h("div", { class: "row svc-badges" });
    if (s.is_test) badges.appendChild(h("span", { class: "badge", text: t("badge_test") }));
    if (!s.enabled) badges.appendChild(h("span", { class: "badge bad", text: t("badge_off") }));
    var qrHost = h("div", { class: "qr-host" });
    var qrBtn = h("button", { class: "btn small ghost", type: "button", text: t("qr_show") });
    qrBtn.addEventListener("click", function () {
      if (qrHost.firstChild) { qrHost.textContent = ""; qrBtn.textContent = t("qr_show"); return; }
      var img = h("img", { class: "qr", alt: "QR", width: "180", height: "180" });
      qrHost.appendChild(img);
      qrBtn.textContent = t("qr_hide");
      fetchBlob("/api/web/qr?link=" + encodeURIComponent(s.link)).then(function (bl) { img.src = URL.createObjectURL(bl); }).catch(function () { qrHost.textContent = ""; });
    });
    var actions = h("div", { class: "row svc-actions" }, h("button", { class: "btn small", type: "button", text: t("copy"), onclick: function () { copyText(s.link); } }), qrBtn);
    var renewBtn = null;
    if (s.can_renew && renewEnabled) { renewBtn = h("button", { class: "btn small ghost", type: "button", text: t("svc_renew"), onclick: function () { renewSheet(s, reload); } }); actions.appendChild(renewBtn); }
    addAppButtons(actions, s.link, renewBtn, false);

    var usage = usageBlock(s, badges);
    var title = h("div", { class: "svc-title" }, h("div", { class: "svc-icon", text: "⌁" }), h("div", null,
      h("h3", { text: s.name }), h("p", { class: "mute small-t", text: s.enabled ? t("svc_active") : t("svc_inactive") })));
    var link = h("div", { class: "svc-link num", title: s.link, text: s.link });
    return h("article", { class: "card svc svc-premium" },
      h("div", { class: "svc-top" }, title, badges),
      h("div", { class: "svc-content" }, usage, link),
      actions, qrHost);
  }

  function dashboardSummary(box, services) {
    var active = services.filter(function (s) { return s.enabled && !s.is_test; }).length;
    var expiring = services.filter(function (s) {
      if (!s.expires_at) return false;
      var days = Math.ceil((new Date(s.expires_at).getTime() - Date.now()) / 86400000);
      return days >= 0 && days <= 7;
    }).length;
    box.appendChild(h("div", { class: "dash-stats" },
      h("div", { class: "dash-stat" }, h("span", { class: "dash-stat-icon" }, "◈"), h("div", null, h("b", { text: fmt(services.length) }), h("span", { class: "mute", text: t("dash_services") }))),
      h("div", { class: "dash-stat" }, h("span", { class: "dash-stat-icon" }, "✓"), h("div", null, h("b", { text: fmt(active) }), h("span", { class: "mute", text: t("dash_active") }))),
      h("div", { class: "dash-stat" }, h("span", { class: "dash-stat-icon" }, "◷"), h("div", null, h("b", { text: fmt(expiring) }), h("span", { class: "mute", text: t("dash_expiring") })))
    ));
  }

  function servicesPanel(box) {
    box.appendChild(spinnerBlock());
    function load() {
      api("/api/web/services").then(function (r) {
        box.textContent = "";
        if (!r.services.length) {
          box.appendChild(h("div", { class: "empty-state card" }, h("div", { class: "empty-icon", text: "⌁" }), h("h3", { text: t("svc_none") }), h("p", { class: "mute", text: t("dash_empty_text") }), h("a", { class: "btn", href: "#/plans", text: t("svc_buy") })));
          return;
        }
        dashboardSummary(box, r.services);
        box.appendChild(h("div", { class: "section-head" }, h("div", null, h("h2", { text: t("dash_my_services") }), h("p", { class: "mute", text: t("dash_services_sub") })), h("a", { class: "btn small ghost", href: "#/plans", text: t("dash_add") })));
        var grid = h("div", { class: "service-grid" });
        r.services.forEach(function (s) { grid.appendChild(serviceCard(s, r.renew_enabled, function () { box.textContent = ""; box.appendChild(spinnerBlock()); load(); })); });
        box.appendChild(grid);
      }).catch(function (e) { box.textContent = ""; var n = h("div"); box.appendChild(n); fail(e, n, load); });
    }
    load();
  }

  function ordersPanel(box) {
    box.appendChild(spinnerBlock());
    api("/api/orders").then(function (list) {
      box.textContent = "";
      if (!list.length) { box.appendChild(h("div", { class: "card center" }, h("p", { class: "mute", text: t("ord_none") }))); return; }
      var wrap = h("div", { class: "list" });
      list.slice().reverse().forEach(function (o) {
        var inner = [h("div", null, h("b", { text: o.product_name + (o.quantity > 1 ? " \u00d7 " + fmt(o.quantity) : "") }), h("div", { class: "mute small-t num", text: "#" + fmt(o.id) + " \u00b7 " + money(o.final_price) })), statusBadge(o.status)];
        wrap.appendChild(o.is_custom_config ? h("div", { class: "list-item" }, inner) : h("a", { class: "list-item", href: "#/order/" + o.id, style: { textDecoration: "none" } }, inner));
      });
      box.appendChild(wrap);
    }).catch(function (e) { box.textContent = ""; var n = h("div"); box.appendChild(n); fail(e, n, null); });
  }

  function ticketSheet(id, reload) {
    var thread = h("div", { class: "thread" });
    var msg = h("textarea", { class: "input", maxlength: "2000" });
    var send = h("button", { class: "btn", type: "button", text: t("tk_send") });
    var close = h("button", { class: "btn ghost", type: "button", text: t("tk_close") });
    var row = h("div", { class: "row" }, send, close);
    var notice = h("div", { role: "alert" });
    var last = 0;
    var box = h("div", { class: "stack" }, thread, msg, row, notice);
    function load() {
      api("/api/tickets/" + id + "/messages?since_id=" + last).then(function (r) {
        $("sheetTitle").textContent = "#" + id + " " + r.ticket.subject;
        r.messages.forEach(function (x) {
          if (x.id > last) last = x.id;
          thread.appendChild(h("div", { class: "msg" + (x.sender === "user" ? " me" : "") }, x.message, h("small", { class: "num", text: String(x.created_at || "").slice(0, 16).replace("T", " ") })));
        });
        if (r.messages.length) thread.scrollTop = thread.scrollHeight;
        if (r.ticket.status === "closed") { msg.hidden = true; row.hidden = true; }
      }).catch(function (e) { if (e.status === 401) fail(e, notice, null); });
    }
    send.addEventListener("click", function () {
      if (!msg.value.trim()) return;
      send.disabled = true;
      api("/api/tickets/" + id + "/messages", { method: "POST", body: { message: msg.value } }).then(function () { msg.value = ""; send.disabled = false; load(); }).catch(function (e) { send.disabled = false; fail(e, notice, null); });
    });
    close.addEventListener("click", function () { api("/api/tickets/" + id + "/close", { method: "POST" }).then(function () { load(); }).catch(noop); });
    openSheet("#" + id, box, reload);
    load();
    every(load, 8000);
  }
  function newTicketSheet(reload) {
    var subject = h("input", { class: "input", type: "text", maxlength: "150" });
    var msg = h("textarea", { class: "input", maxlength: "2000" });
    var notice = h("div", { role: "alert" });
    var send = h("button", { class: "btn block", type: "button", text: t("tk_send") });
    send.addEventListener("click", function () {
      send.disabled = true;
      api("/api/tickets", { method: "POST", body: { subject: subject.value, message: msg.value } }).then(function (r) {
        closeSheet();
        ticketSheet(r.id, reload);
      }).catch(function (e) { send.disabled = false; fail(e, notice, null); });
    });
    openSheet(t("tk_new"), h("div", { class: "stack" },
      h("label", { class: "field" }, h("span", { text: t("tk_subject") }), subject),
      h("label", { class: "field" }, h("span", { text: t("tk_message") }), msg), notice, send), reload);
  }
  function supportPanel(box) {
    function load() {
      box.textContent = "";
      box.appendChild(spinnerBlock());
      api("/api/tickets").then(function (list) {
        box.textContent = "";
        box.appendChild(h("div", null, h("button", { class: "btn", type: "button", text: t("tk_new"), onclick: function () { newTicketSheet(load); } })));
        if (!list.length) { box.appendChild(h("p", { class: "mute", text: t("tk_none") })); return; }
        var wrap = h("div", { class: "list" });
        list.forEach(function (k) {
          wrap.appendChild(h("button", { class: "list-item", type: "button", onclick: function () { ticketSheet(k.id, load); } },
            h("span", { text: "#" + fmt(k.id) + " " + k.subject }),
            h("span", { class: "badge " + (k.status === "closed" ? "" : "ok"), text: k.status === "closed" ? t("tk_closed") : t("tk_open") })));
        });
        box.appendChild(wrap);
      }).catch(function (e) { box.textContent = ""; var n = h("div"); box.appendChild(n); fail(e, n, load); });
    }
    load();
  }

  function mergeSheet() {
    var notice = h("div", { role: "alert" });
    var made = h("div", { class: "stack" });
    var prev = h("div", { class: "stack" });
    var gen = h("button", { class: "btn block", type: "button", text: t("merge_gen") });
    var input = h("input", { class: "input ltr", type: "text", inputmode: "numeric", maxlength: "8", autocomplete: "off", placeholder: "12345678" });
    var check = h("button", { class: "btn ghost block", type: "button", text: t("merge_check") });
    function finished() {
      dropToken();
      var b = $("sheetBody");
      b.textContent = "";
      b.appendChild(h("div", { class: "stack" }, h("h3", { text: t("merge_done") }), h("p", { class: "mute", text: t("merge_done_text") }), h("a", { class: "btn", href: "#/login", text: t("login") })));
    }
    gen.addEventListener("click", function () {
      gen.disabled = true;
      notice.textContent = "";
      api("/api/web/merge/code", { method: "POST" }).then(function (r) {
        made.textContent = "";
        made.appendChild(copyBox(r.code));
        made.appendChild(h("p", { class: "mute small-t", text: t("merge_send_bot") }));
        every(function () {
          api("/api/web/session").catch(function (e) { if (e.status === 401 || e.status === 403) { stopTimers(); finished(); } });
        }, 3000);
      }).catch(function (e) { gen.disabled = false; fail(e, notice, null); });
    });
    check.addEventListener("click", function () {
      var code = input.value.trim();
      notice.textContent = "";
      prev.textContent = "";
      if (!/^[0-9]{8}$/.test(code)) { notice.appendChild(alertBox(t("merge_bad_code"))); return; }
      api("/api/web/merge/preview", { method: "POST", body: { code: code } }).then(function (r) {
        var ok = h("button", { class: "btn block", type: "button", text: t("merge_confirm") });
        ok.addEventListener("click", function () {
          ok.disabled = true;
          api("/api/web/merge/confirm", { method: "POST", body: { code: code } }).then(finished).catch(function (e) { ok.disabled = false; fail(e, notice, null); });
        });
        prev.appendChild(h("p", { text: t("merge_confirm_text", { email: r.email, tg: r.telegram }) }));
        prev.appendChild(h("p", { class: "mute small-t", text: t("merge_irreversible") }));
        prev.appendChild(ok);
      }).catch(function (e) { fail(e, notice, null); });
    });
    openSheet(t("merge_title"), h("div", { class: "stack" },
      h("p", { class: "mute", text: t("merge_intro") }), gen, made,
      h("label", { class: "field" }, h("span", { text: t("merge_enter") }), input), check, prev, notice));
  }

  function settingsPanel(box) {
    var who = S.user ? (S.user.first_name || S.user.username || "") : "";
    var card = h("div", { class: "card stack" },
      h("h3", { text: t("settings_account") }),
      who ? h("p", { class: "mute", text: who + (S.user && S.user.username ? "  @" + S.user.username : "") }) : null);
    if (S.user && S.user.is_email_account) {
      card.appendChild(h("button", { class: "btn ghost", type: "button", text: t("merge_title"), onclick: mergeSheet }));
    }
    card.appendChild(h("button", {
      class: "btn danger", type: "button", text: t("logout"),
      onclick: doLogout
    }));
    box.appendChild(card);
  }

  function accountPage(parts) {
    if (!S.token) { S.next = location.hash; go("#/login"); return; }
    var tabs = ["services", "orders", "support", "settings"];
    var tab = tabs.indexOf(parts[0]) >= 0 ? parts[0] : "services";
    var wallet = h("div", { class: "wallet num", text: "\u2026" });
    var name = S.user ? (S.user.first_name || S.user.username || "") : "";
    var bar = h("div", { class: "tabs", role: "tablist" }, tabs.map(function (k) {
      return h("button", { type: "button", role: "tab", "aria-selected": String(k === tab), text: t("tab_" + k), onclick: function () { go("#/account/" + k); } });
    }));
    var panel = h("div", { class: "stack" });
    mount(h("div", { class: "wrap page stack account-page" },
      h("div", { class: "card acct-head acct-hero" },
        h("div", { class: "acct-copy" }, h("span", { class: "eyebrow", text: t("dash_overview") }), h("h1", { text: t("acct_hello", { name: name }) }), h("p", { class: "mute", text: t("dash_welcome") })),
        h("div", { class: "wallet-box" }, h("span", { class: "mute", text: t("acct_wallet") }), wallet),
        h("div", { class: "acct-actions" }, h("a", { class: "btn", href: "#/plans", text: t("dash_buy") }), h("a", { class: "btn ghost", href: "#/account/orders", text: t("dash_orders") }))),
      bar, panel), t("nav_account"));
    api("/api/me").then(function (m) { wallet.textContent = money(m.wallet_credit || 0); }).catch(function (e) { wallet.textContent = ""; if (e.status === 401) fail(e, h("div"), null); });
    if (tab === "services") servicesPanel(panel);
    else if (tab === "orders") ordersPanel(panel);
    else if (tab === "support") supportPanel(panel);
    else settingsPanel(panel);
  }

  function parseHash() {
    var raw = location.hash.replace(/^#/, "") || "/";
    var parts = raw.split("?")[0].split("/").filter(Boolean);
    return parts;
  }
  var NAV = { "": "home", plans: "plans", buy: "plans", order: "account", account: "account", login: "account", guide: "guide", faq: "faq" };
  function setNav(name) {
    Array.prototype.forEach.call(document.querySelectorAll("[data-nav]"), function (a) {
      if (a.getAttribute("data-nav") === NAV[name]) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }
  function route() {
    stopTimers();
    closeSheet();
    var parts = parseHash();
    var name = parts[0] || "";
    var rest = parts.slice(1);
    setNav(name);
    if (name === "") homePage(false);
    else if (name === "plans") homePage(true);
    else if (name === "buy") buyPage(rest);
    else if (name === "order") orderPage(rest);
    else if (name === "account") accountPage(rest);
    else if (name === "login") loginPage();
    else if (name === "guide") guidePage();
    else if (name === "faq") faqPage();
    else if (name === "terms") termsPage();
    else homePage(false);
  }

  function applyStatic() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-i18n]"), function (n) { n.textContent = t(n.getAttribute("data-i18n")); });
    Array.prototype.forEach.call(document.querySelectorAll("[data-i18n-label]"), function (n) {
      var label = t(n.getAttribute("data-i18n-label"));
      n.setAttribute("aria-label", label);
      n.setAttribute("title", label);
    });
    $("langBtn").textContent = t("lang_btn");
    $("themeBtn").textContent = "\u25D0";
    $("sheetClose").textContent = "\u00d7";
  }
  function isDark() {
    var th = root.getAttribute("data-theme");
    if (th) return th === "dark";
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function init() {
    applyStatic();
    $("themeBtn").addEventListener("click", function () {
      var next = isDark() ? "light" : "dark";
      root.setAttribute("data-theme", next);
      store.set("sv-theme", next);
    });
    $("logoutBtn").addEventListener("click", doLogout);
    $("langBtn").addEventListener("click", function () { location.href = (lang === "fa" ? "/en/" : "/") + location.hash; });
    $("sheetClose").addEventListener("click", closeSheet);
    if (new URLSearchParams(location.search).get("preview") === "1") {
      window.addEventListener("message", function (ev) {
        if (!ev.data || ev.data.type !== "shopvpn-web-store-preview") return;
        applyBrand(ev.data.payload || {});
      });
    }
    window.addEventListener("hashchange", route);
    loadConfig();
    loadCatalog().catch(noop);
    loadSession().then(route);
  }
  init();
})();
