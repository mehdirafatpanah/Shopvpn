(function () {
  "use strict";

  var STR = {
    fa: {
      q: "کدوم پلن مناسب توئه؟",
      all: "همه پلن‌ها", allSub: "لیست کامل و فیلتر",
      guide: "راهنمای اتصال", guideSub: "روی هر دستگاه",
      prev: "پلن قبلی", next: "پلن بعدی", scroll: "SCROLL TO ENTER",
      chips: ["اندروید", "آیفون", "ویندوز", "مک", "لینوکس"]
    },
    en: {
      q: "Which plan fits you?",
      all: "All plans", allSub: "Full list and filters",
      guide: "Setup guide", guideSub: "On any device",
      prev: "Previous plan", next: "Next plan", scroll: "SCROLL TO ENTER",
      chips: ["Android", "iPhone", "Windows", "Mac", "Linux"]
    }
  };

  var VERT_MESH = [
    "attribute vec3 aPos;",
    "attribute vec3 aNrm;",
    "attribute float aSeed;",
    "uniform mat4 uVP;",
    "varying vec3 vW;",
    "varying vec3 vN;",
    "varying float vS;",
    "void main() {",
    "  vW = aPos;",
    "  vN = aNrm;",
    "  vS = aSeed;",
    "  gl_Position = uVP * vec4(aPos, 1.0);",
    "}"
  ].join("\n");

  var FRAG_MESH = [
    "#ifdef GL_FRAGMENT_PRECISION_HIGH",
    "precision highp float;",
    "#else",
    "precision mediump float;",
    "#endif",
    "uniform vec3 uCam;",
    "uniform vec3 uC1;",
    "uniform vec3 uC2;",
    "uniform float uTime;",
    "uniform float uFocus;",
    "uniform float uLight;",
    "varying vec3 vW;",
    "varying vec3 vN;",
    "varying float vS;",
    "void main() {",
    "  vec3 N = normalize(vN);",
    "  vec3 V = normalize(uCam - vW);",
    "  if (dot(N, V) < 0.0) N = -N;",
    "  float nv = clamp(dot(N, V), 0.0, 1.0);",
    "  float fr = pow(1.0 - nv, 2.0);",
    "  vec3 L = normalize(vec3(0.5, 0.8, 0.6));",
    "  float dif = max(dot(N, L), 0.0);",
    "  float spec = pow(max(dot(reflect(-L, N), V), 0.0), 18.0);",
    "  float h = vW.y * 0.28 + uTime * 0.07 + vS * 2.0 + dot(N, vec3(0.4, 0.2, 0.6));",
    "  vec3 irid = 0.5 + 0.5 * cos(6.2831 * (h + vec3(0.0, 0.33, 0.67)));",
    "  vec3 base = mix(vec3(0.035, 0.04, 0.11), vec3(0.14, 0.12, 0.30), dif) + irid * 0.10 * (0.4 + fr);",
    "  vec3 rim = mix(uC2, uC1, 0.5 + 0.5 * sin(h * 5.0)) * fr * 1.35;",
    "  float gl = step(0.9, vS);",
    "  vec3 col = base + rim + spec * uC2 * 0.7;",
    "  col += gl * mix(uC1, uC2, clamp(vS * 10.0 - 9.0, 0.0, 1.0)) * 0.55 * (0.5 + 0.5 * sin(uTime * 1.5 + vS * 60.0));",
    "  col = mix(col, col * 0.85, uLight);",
    "  float a = 1.0 - smoothstep(2.6, 6.0, abs(vW.y - uFocus));",
    "  gl_FragColor = vec4(col * a, a);",
    "}"
  ].join("\n");

  var VERT_PTS = [
    "attribute vec3 aP;",
    "attribute vec2 aS;",
    "uniform mat4 uVP;",
    "uniform float uTime;",
    "uniform float uYMin;",
    "uniform float uYRange;",
    "uniform float uDpr;",
    "varying float vK;",
    "void main() {",
    "  float yy = aP.y + uTime * (0.05 + aS.y * 0.12);",
    "  yy = mod(yy - uYMin, uYRange) + uYMin;",
    "  gl_Position = uVP * vec4(aP.x, yy, aP.z, 1.0);",
    "  gl_PointSize = max(1.0, (1.5 + 3.5 * aS.x) * uDpr * (5.0 / max(gl_Position.w, 0.5)));",
    "  vK = aS.x;",
    "}"
  ].join("\n");

  var FRAG_PTS = [
    "precision mediump float;",
    "uniform vec3 uC1;",
    "uniform vec3 uC2;",
    "varying float vK;",
    "void main() {",
    "  vec2 c = gl_PointCoord - 0.5;",
    "  float d = dot(c, c) * 4.0;",
    "  if (d > 1.0) discard;",
    "  float a = (1.0 - d) * (1.0 - d) * 0.85;",
    "  gl_FragColor = vec4(mix(uC1, uC2, vK) * a, a);",
    "}"
  ].join("\n");

  var SEG = 16;
  var STEP = 0.74;
  var SPAN = (SEG - 1) * STEP;

  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function smooth(a, b, v) { var k = clamp((v - a) / (b - a), 0, 1); return k * k * (3 - 2 * k); }
  function rng(seed) { var s = seed >>> 0; return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }

  function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function norm(a) { var l = Math.sqrt(dot(a, a)) || 1; return [a[0] / l, a[1] / l, a[2] / l]; }
  function perspective(fovy, aspect, near, far) {
    var f = 1 / Math.tan(fovy / 2);
    var nf = 1 / (near - far);
    return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
  }
  function lookAt(e, c, u) {
    var z = norm(sub(e, c));
    var x = norm(cross(u, z));
    var y = cross(z, x);
    return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, e), -dot(y, e), -dot(z, e), 1];
  }
  function mul(a, b) {
    var o = new Array(16);
    for (var c = 0; c < 4; c++) {
      for (var r = 0; r < 4; r++) {
        o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
      }
    }
    return o;
  }

  function buildMesh() {
    var r = rng(7);
    var out = [];
    function tri(p, q, s, seed) {
      var n = norm(cross(sub(q, p), sub(s, p)));
      [p, q, s].forEach(function (v) { out.push(v[0], v[1], v[2], n[0], n[1], n[2], seed); });
    }
    var RING = 9;
    var prof = [[0.30, 0.34], [0.62, 0.20], [0.86, 0.04], [0.66, -0.16], [0.32, -0.30]];
    var rings = [];
    for (var s = 0; s < SEG; s++) {
      var cy = -s * STEP;
      var cx = Math.sin(s * 0.55) * 0.22;
      var cz = Math.cos(s * 0.41) * 0.18;
      var tw = r() * 6.2832;
      prof.forEach(function (p) {
        var ring = [];
        for (var i = 0; i < RING; i++) {
          var a = tw + (i / RING) * 6.2832;
          var rad = p[0] * (0.82 + r() * 0.36) * (i % 2 ? 0.92 : 1);
          ring.push([cx + Math.cos(a) * rad, cy + p[1] + (r() - 0.5) * 0.06, cz + Math.sin(a) * rad * 0.9]);
        }
        rings.push(ring);
      });
    }
    for (var k = 0; k < rings.length - 1; k++) {
      for (var j = 0; j < RING; j++) {
        var j2 = (j + 1) % RING;
        var a0 = rings[k][j], a1 = rings[k][j2], b0 = rings[k + 1][j], b1 = rings[k + 1][j2];
        tri(a0, a1, b1, r());
        tri(a0, b1, b0, r());
      }
    }
    for (var n = 0; n < 70; n++) {
      var y = -r() * SPAN;
      var ang = r() * 6.2832;
      var d = 1.3 + r() * 1.4;
      var c = [Math.sin(y * 0.74) * 0.22 + Math.cos(ang) * d, y, Math.sin(ang) * d];
      var u = [(r() - 0.5) * 0.6, (r() - 0.5) * 0.4, (r() - 0.5) * 0.6];
      var v = [(r() - 0.5) * 0.35, (r() - 0.5) * 0.7, (r() - 0.5) * 0.35];
      var p0 = [c[0] - u[0] - v[0], c[1] - u[1] - v[1], c[2] - u[2] - v[2]];
      var p1 = [c[0] + u[0] - v[0], c[1] + u[1] - v[1], c[2] + u[2] - v[2]];
      var p2 = [c[0] + u[0] + v[0], c[1] + u[1] + v[1], c[2] + u[2] + v[2]];
      var p3 = [c[0] - u[0] + v[0], c[1] - u[1] + v[1], c[2] - u[2] + v[2]];
      var sd = r();
      tri(p0, p1, p2, sd);
      tri(p0, p2, p3, sd);
    }
    return new Float32Array(out);
  }

  function buildPoints(count) {
    var r = rng(21);
    var out = new Float32Array(count * 5);
    for (var i = 0; i < count; i++) {
      out[i * 5] = (r() - 0.5) * 7;
      out[i * 5 + 1] = -r() * (SPAN + 3) + 1.5;
      out[i * 5 + 2] = (r() - 0.5) * 7;
      out[i * 5 + 3] = r();
      out[i * 5 + 4] = r();
    }
    return out;
  }

  var colorCtx = null;
  function parseColor(value, fallback) {
    try {
      if (!colorCtx) {
        var c = document.createElement("canvas");
        c.width = c.height = 1;
        colorCtx = c.getContext("2d", { willReadFrequently: true });
      }
      colorCtx.clearRect(0, 0, 1, 1);
      colorCtx.fillStyle = "#000";
      colorCtx.fillStyle = String(value || "").trim() || fallback;
      colorCtx.fillRect(0, 0, 1, 1);
      var d = colorCtx.getImageData(0, 0, 1, 1).data;
      return [d[0] / 255, d[1] / 255, d[2] / 255];
    } catch (e) {
      return [0.55, 0.48, 1];
    }
  }
  function readTheme() {
    var cs = getComputedStyle(document.documentElement);
    var bg = parseColor(cs.getPropertyValue("--bg"), "#070A1A");
    return {
      c1: parseColor(cs.getPropertyValue("--accent"), "#8E7BFF"),
      c2: parseColor(cs.getPropertyValue("--accent-2"), "#35E6CB"),
      light: (bg[0] * 0.2126 + bg[1] * 0.7152 + bg[2] * 0.0722) > 0.55
    };
  }

  var supportedCache = null;
  function supported() {
    if (supportedCache !== null) return supportedCache;
    var ok = false;
    try {
      var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (!reduced) {
        var c = document.createElement("canvas");
        var g = c.getContext("webgl") || c.getContext("experimental-webgl");
        ok = !!g;
        if (g) {
          var ext = g.getExtension("WEBGL_lose_context");
          if (ext) ext.loseContext();
        }
      }
    } catch (e) { ok = false; }
    supportedCache = ok;
    return ok;
  }

  var SCRAMBLE = "!<>-_\\/[]{}=+*^?#01ABCDEFGHJKLMNPQRSTUVWXYZ";
  function scramble(node, text) {
    var token = node._scr = (node._scr || 0) + 1;
    var t0 = performance.now();
    var dur = 420;
    (function frame(now) {
      if (node._scr !== token) return;
      var k = Math.min(1, ((now || performance.now()) - t0) / dur);
      var s = "";
      for (var i = 0; i < text.length; i++) {
        s += (k > (i / text.length) * 0.7 + 0.3 || text.charAt(i) === " ") ? text.charAt(i) : SCRAMBLE.charAt((Math.random() * SCRAMBLE.length) | 0);
      }
      node.textContent = s;
      if (k < 1) requestAnimationFrame(frame);
      else node.textContent = text;
    })();
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function mount(opts) {
    var host = opts.host;
    var lang = opts.lang === "en" ? "en" : "fa";
    var S = STR[lang];
    var t = opts.t;
    var fmt = opts.fmt;
    if (!host || !supported()) return null;

    var canvas = el("canvas", "cin-gl");
    canvas.setAttribute("aria-hidden", "true");
    var gl = canvas.getContext("webgl", { antialias: true, alpha: true, premultipliedAlpha: true }) || canvas.getContext("experimental-webgl");
    if (!gl) return null;

    var section = el("section", "cin");
    var stick = el("div", "cin-stick");
    var hud = el("div", "cin-hud");
    hud.setAttribute("aria-hidden", "true");
    for (var ci = 1; ci <= 4; ci++) hud.appendChild(el("i", "c c" + ci));
    var meta = el("div", "cin-meta");
    var metaBrand = el("span", null, "");
    var metaSec = el("span", null, "SEC 01 // INTRO");
    meta.setAttribute("aria-hidden", "true");
    meta.appendChild(metaBrand);
    meta.appendChild(metaSec);

    var h1 = el("h1", null, t("hero_title"));
    var lead = el("p", "lead", t("hero_sub"));
    var cta = el("div", "cta");
    var a1 = el("a", "btn", t("hero_cta"));
    a1.href = "#/plans";
    var a2 = el("a", "btn ghost", t("hero_cta2"));
    a2.href = "#/guide";
    cta.appendChild(a1);
    cta.appendChild(a2);
    var chips = el("div", "cin-chips");
    S.chips.forEach(function (c) { chips.appendChild(el("span", "cin-chip", c)); });
    var hint = el("div", "cin-hint", S.scroll);
    hint.setAttribute("aria-hidden", "true");
    var heroSt = el("div", "cin-st cin-hero");
    var heroCopy = el("div", "cin-copy");
    heroCopy.appendChild(h1);
    heroCopy.appendChild(lead);
    heroCopy.appendChild(cta);
    heroCopy.appendChild(chips);
    heroSt.appendChild(heroCopy);
    heroSt.appendChild(hint);

    var plansSt = el("div", "cin-st cin-plans");
    plansSt.hidden = true;
    var pager = el("div", "cin-pager");
    var btnPrev = el("button", null, "<<");
    btnPrev.type = "button";
    btnPrev.setAttribute("aria-label", S.prev);
    var btnNext = el("button", null, ">>");
    btnNext.type = "button";
    btnNext.setAttribute("aria-label", S.next);
    var pgMid = el("span", "pg");
    var pgI = el("b");
    var pgN = el("span");
    var pgName = el("i");
    pgMid.appendChild(pgI);
    pgMid.appendChild(document.createTextNode(" / "));
    pgMid.appendChild(pgN);
    pgMid.appendChild(pgName);
    pager.appendChild(btnPrev);
    pager.appendChild(pgMid);
    pager.appendChild(btnNext);
    var deck = el("div", "cin-deck");
    var ui = el("div", "cin-ui");
    var q = el("h2", "cin-q", S.q);
    var list = el("ol", "cin-list");
    var links = el("div", "cin-links");
    var l1 = el("a", "cin-link");
    l1.href = "#/plans";
    l1.appendChild(el("b", null, S.all));
    l1.appendChild(el("small", null, S.allSub));
    var l2 = el("a", "cin-link");
    l2.href = "#/guide";
    l2.appendChild(el("b", null, S.guide));
    l2.appendChild(el("small", null, S.guideSub));
    links.appendChild(l1);
    links.appendChild(l2);
    ui.appendChild(q);
    ui.appendChild(list);
    ui.appendChild(links);
    plansSt.appendChild(pager);
    plansSt.appendChild(deck);
    plansSt.appendChild(ui);

    stick.appendChild(canvas);
    stick.appendChild(hud);
    stick.appendChild(heroSt);
    stick.appendChild(plansSt);
    stick.appendChild(meta);
    section.appendChild(stick);
    host.appendChild(section);

    var plans = [];
    var cards = [];
    var rows = [];
    var heroVh = 90;
    var plansVh = 0;
    var cur = -1;
    var progress = 0;
    var target = 0;
    var dead = false;
    var raf = 0;
    var theme = readTheme();
    var themeTick = 0;
    var W = 0, H = 0, dpr = 1;
    var t0 = performance.now();

    function compile(type, src) {
      var s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error("shader");
      return s;
    }
    function program(vs, fs) {
      var p = gl.createProgram();
      gl.attachShader(p, compile(gl.VERTEX_SHADER, vs));
      gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error("link");
      return p;
    }

    var pm, pp, meshBuf, meshCount, ptsBuf, ptsCount, loc = {};
    try {
      pm = program(VERT_MESH, FRAG_MESH);
      pp = program(VERT_PTS, FRAG_PTS);
      var mesh = buildMesh();
      meshCount = mesh.length / 7;
      meshBuf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, meshBuf);
      gl.bufferData(gl.ARRAY_BUFFER, mesh, gl.STATIC_DRAW);
      var small = window.innerWidth < 720;
      var weak = (navigator.deviceMemory && navigator.deviceMemory <= 2) || (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4);
      ptsCount = small || weak ? 450 : 800;
      ptsBuf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, ptsBuf);
      gl.bufferData(gl.ARRAY_BUFFER, buildPoints(ptsCount), gl.STATIC_DRAW);
      loc.m = {
        aPos: gl.getAttribLocation(pm, "aPos"), aNrm: gl.getAttribLocation(pm, "aNrm"), aSeed: gl.getAttribLocation(pm, "aSeed"),
        uVP: gl.getUniformLocation(pm, "uVP"), uCam: gl.getUniformLocation(pm, "uCam"), uC1: gl.getUniformLocation(pm, "uC1"),
        uC2: gl.getUniformLocation(pm, "uC2"), uTime: gl.getUniformLocation(pm, "uTime"), uFocus: gl.getUniformLocation(pm, "uFocus"),
        uLight: gl.getUniformLocation(pm, "uLight")
      };
      loc.p = {
        aP: gl.getAttribLocation(pp, "aP"), aS: gl.getAttribLocation(pp, "aS"),
        uVP: gl.getUniformLocation(pp, "uVP"), uTime: gl.getUniformLocation(pp, "uTime"), uYMin: gl.getUniformLocation(pp, "uYMin"),
        uYRange: gl.getUniformLocation(pp, "uYRange"), uDpr: gl.getUniformLocation(pp, "uDpr"),
        uC1: gl.getUniformLocation(pp, "uC1"), uC2: gl.getUniformLocation(pp, "uC2")
      };
    } catch (e) {
      host.removeChild(section);
      return null;
    }
    gl.clearColor(0, 0, 0, 0);

    function resize() {
      var w = stick.clientWidth;
      var hh = stick.clientHeight;
      var d = Math.min(window.devicePixelRatio || 1, window.innerWidth < 720 ? 1.5 : 1.75);
      if (w === W && hh === H && d === dpr) return;
      W = w; H = hh; dpr = d;
      canvas.width = Math.max(1, Math.round(W * dpr));
      canvas.height = Math.max(1, Math.round(H * dpr));
      gl.viewport(0, 0, canvas.width, canvas.height);
    }

    function draw(now) {
      var time = (now - t0) / 1000;
      var aspect = W / Math.max(1, H);
      var pCtl = progress;
      var focus = -pCtl * SPAN * 0.94;
      var R = aspect < 1 ? 5.2 / Math.pow(Math.max(aspect, 0.3), 0.9) : 5.0;
      var pos = cardPos;
      var th = 0.5 + pCtl * 2.4 + pos * 0.12 + Math.sin(time * 0.15) * 0.05;
      var cam = [Math.sin(th) * R, focus + 0.9 + (1 - smooth(0, 0.2, pCtl)) * 0.7, Math.cos(th) * R];
      var lift = (1 - smooth(0, 0.18, pCtl)) * (aspect < 1 ? 2.6 : 0.9);
      var tgt = [0, focus - 0.25 - lift, 0];
      var vp = mul(perspective(0.74, aspect, 0.1, 60), lookAt(cam, tgt, [0, 1, 0]));

      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      gl.depthFunc(gl.LEQUAL);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      gl.useProgram(pm);
      gl.bindBuffer(gl.ARRAY_BUFFER, meshBuf);
      gl.enableVertexAttribArray(loc.m.aPos);
      gl.vertexAttribPointer(loc.m.aPos, 3, gl.FLOAT, false, 28, 0);
      gl.enableVertexAttribArray(loc.m.aNrm);
      gl.vertexAttribPointer(loc.m.aNrm, 3, gl.FLOAT, false, 28, 12);
      gl.enableVertexAttribArray(loc.m.aSeed);
      gl.vertexAttribPointer(loc.m.aSeed, 1, gl.FLOAT, false, 28, 24);
      gl.uniformMatrix4fv(loc.m.uVP, false, new Float32Array(vp));
      gl.uniform3f(loc.m.uCam, cam[0], cam[1], cam[2]);
      gl.uniform3f(loc.m.uC1, theme.c1[0], theme.c1[1], theme.c1[2]);
      gl.uniform3f(loc.m.uC2, theme.c2[0], theme.c2[1], theme.c2[2]);
      gl.uniform1f(loc.m.uTime, time);
      gl.uniform1f(loc.m.uFocus, focus);
      gl.uniform1f(loc.m.uLight, theme.light ? 1 : 0);
      gl.drawArrays(gl.TRIANGLES, 0, meshCount);
      gl.disableVertexAttribArray(loc.m.aNrm);
      gl.disableVertexAttribArray(loc.m.aSeed);

      gl.disable(gl.DEPTH_TEST);
      if (theme.light) gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      else gl.blendFunc(gl.ONE, gl.ONE);
      gl.useProgram(pp);
      gl.bindBuffer(gl.ARRAY_BUFFER, ptsBuf);
      gl.enableVertexAttribArray(loc.p.aP);
      gl.vertexAttribPointer(loc.p.aP, 3, gl.FLOAT, false, 20, 0);
      gl.enableVertexAttribArray(loc.p.aS);
      gl.vertexAttribPointer(loc.p.aS, 2, gl.FLOAT, false, 20, 12);
      gl.uniformMatrix4fv(loc.p.uVP, false, new Float32Array(vp));
      gl.uniform1f(loc.p.uTime, time);
      gl.uniform1f(loc.p.uYMin, -(SPAN + 1.5));
      gl.uniform1f(loc.p.uYRange, SPAN + 3);
      gl.uniform1f(loc.p.uDpr, dpr);
      gl.uniform3f(loc.p.uC1, theme.c1[0], theme.c1[1], theme.c1[2]);
      gl.uniform3f(loc.p.uC2, theme.c2[0], theme.c2[1], theme.c2[2]);
      gl.drawArrays(gl.POINTS, 0, ptsCount);
      gl.disableVertexAttribArray(loc.p.aP);
      gl.disableVertexAttribArray(loc.p.aS);
      gl.disableVertexAttribArray(loc.m.aPos);
    }

    var cardPos = 0;

    function rangePx() { return Math.max(1, section.offsetHeight - stick.offsetHeight); }
    function heroFrac() { return heroVh / (heroVh + plansVh); }

    function scrollToIndex(i) {
      if (!plans.length) return;
      var n = plans.length;
      var hf = heroFrac();
      var p0 = hf + 0.03;
      var p1 = 1 - 0.04;
      var p = n > 1 ? p0 + (i / (n - 1)) * (p1 - p0) : p0;
      var top = section.getBoundingClientRect().top + window.pageYOffset;
      window.scrollTo({ top: top + p * rangePx(), behavior: "smooth" });
    }

    function setCurrent(i) {
      if (i === cur || !plans.length) return;
      cur = i;
      pgI.textContent = pad2(i + 1);
      scramble(pgName, plans[i].name || "");
      rows.forEach(function (r, k) { r.classList.toggle("on", k === i); });
      cards.forEach(function (c, k) { c.classList.toggle("on", k === i); });
    }
    function pad2(n) { return (n < 10 ? fmt(0) : "") + fmt(n); }

    function layoutCards(pos) {
      var dw = deck.clientWidth;
      for (var i = 0; i < cards.length; i++) {
        var d = i - pos;
        var ad = Math.abs(d);
        var x = d * dw * 0.7;
        var rot = clamp(d, -1.6, 1.6) * -26;
        var z = -Math.min(ad, 2) * 150;
        var sc = 1 - Math.min(ad, 2) * 0.1;
        var op = 1 - Math.min(ad, 1.7) * 0.5;
        var c = cards[i];
        c.style.transform = "translate(-50%,-50%) translate3d(" + x.toFixed(1) + "px,0," + z.toFixed(1) + "px) rotateY(" + rot.toFixed(1) + "deg) scale(" + sc.toFixed(3) + ")";
        c.style.opacity = op.toFixed(3);
        c.style.filter = ad < 0.05 ? "none" : "blur(" + (Math.min(ad, 1) * 2.2).toFixed(1) + "px)";
        c.style.zIndex = String(100 - Math.round(ad * 10));
        c.style.pointerEvents = ad < 0.35 ? "auto" : "none";
      }
    }

    function station(node, vis) {
      node.style.opacity = vis.toFixed(3);
      node.style.visibility = vis < 0.02 ? "hidden" : "visible";
      node.style.pointerEvents = vis > 0.6 ? "auto" : "none";
    }

    function update() {
      var rect = section.getBoundingClientRect();
      var range = rangePx();
      target = clamp(-rect.top / range, 0, 1);
      progress += (target - progress) * 0.14;
      if (Math.abs(target - progress) < 0.0004) progress = target;

      var hf = heroFrac();
      var n = plans.length;
      var heroVis = n ? 1 - smooth(hf - 0.09, hf - 0.03, progress) : 1;
      var plansVis = n ? smooth(hf - 0.01, hf + 0.05, progress) : 0;
      heroSt.style.transform = "translateY(" + ((1 - heroVis) * -24).toFixed(1) + "px)";
      station(heroSt, heroVis);
      station(plansSt, plansVis);
      hint.style.opacity = String(1 - smooth(0, 0.04, progress));
      metaSec.textContent = plansVis > 0.5 ? "SEC 02 // PLANS" : "SEC 01 // INTRO";

      if (n) {
        var p0 = hf + 0.03;
        var p1 = 1 - 0.04;
        var raw = n > 1 ? clamp((progress - p0) / (p1 - p0), 0, 1) * (n - 1) : 0;
        var f = Math.floor(raw);
        var fr = raw - f;
        cardPos = f + smooth(0.25, 0.75, fr);
        layoutCards(cardPos);
        setCurrent(clamp(Math.round(cardPos), 0, n - 1));
      } else {
        cardPos = 0;
      }
    }

    function tick(now) {
      if (dead) return;
      if (!host.isConnected) { destroy(); return; }
      raf = requestAnimationFrame(tick);
      var rect = section.getBoundingClientRect();
      if (rect.bottom < -50 || rect.top > window.innerHeight + 50) return;
      if (++themeTick % 45 === 0) theme = readTheme();
      resize();
      update();
      draw(now);
    }

    function destroy() {
      if (dead) return;
      dead = true;
      cancelAnimationFrame(raf);
      try {
        var ext = gl.getExtension("WEBGL_lose_context");
        if (ext) ext.loseContext();
      } catch (e) { /* ignore */ }
    }

    canvas.addEventListener("webglcontextlost", function (ev) { ev.preventDefault(); destroy(); }, false);
    btnPrev.addEventListener("click", function () { scrollToIndex(clamp(cur - 1, 0, plans.length - 1)); });
    btnNext.addEventListener("click", function () { scrollToIndex(clamp(cur + 1, 0, plans.length - 1)); });

    function buildCard(p, i) {
      var gb = Number(p.volume_gb || 0);
      var days = Number(p.duration_days || 0);
      var tagNode = el("div", "cin-tag");
      tagNode.appendChild(document.createTextNode("[ "));
      tagNode.appendChild(el("bdi", null, gb > 0 ? fmt(gb) + " " + t("plan_gb") : t("plan_unlimited")));
      tagNode.appendChild(document.createTextNode(" \u00b7 "));
      tagNode.appendChild(el("bdi", null, days > 0 ? fmt(days) + " " + t("plan_days") : t("plan_unlimited")));
      tagNode.appendChild(document.createTextNode(" ]"));
      var card = el("article", "cin-card");
      card.style.setProperty("--ch", String(170 + ((i * 41) % 140)));
      card.appendChild(tagNode);
      var name = el("h3");
      var bdi = el("bdi", null, p.name || "");
      name.appendChild(bdi);
      card.appendChild(name);
      if (p.description) card.appendChild(el("p", "cin-desc", p.description));
      var foot = el("div", "cin-foot");
      var price = el("div", "cin-price num");
      if (p.original_price && p.original_price > p.price) price.appendChild(el("s", null, fmt(p.original_price)));
      price.appendChild(el("b", null, fmt(p.price)));
      price.appendChild(el("small", null, t("currency")));
      foot.appendChild(price);
      var go = el("a", "btn small", t("buy"));
      go.href = "#/buy/" + p.id;
      foot.appendChild(go);
      card.appendChild(foot);
      return card;
    }

    function setPlans(items) {
      plans = (items || []).filter(function (p) { return p && p.id != null; });
      cards = [];
      rows = [];
      deck.textContent = "";
      list.textContent = "";
      cur = -1;
      var n = plans.length;
      plansVh = n ? 45 * n + 30 : 0;
      section.style.setProperty("--rng", String(heroVh + plansVh));
      plansSt.hidden = !n;
      if (!n) return;
      pgN.textContent = pad2(n);
      plans.forEach(function (p, i) {
        var c = buildCard(p, i);
        cards.push(c);
        deck.appendChild(c);
        var li = el("li");
        var b = el("button");
        b.type = "button";
        b.appendChild(el("bdi", null, p.name || ""));
        b.appendChild(el("span", "ar", "->"));
        b.addEventListener("click", function () { scrollToIndex(i); });
        li.appendChild(b);
        list.appendChild(li);
        rows.push(b);
      });
      layoutCards(0);
      setCurrent(0);
    }

    function setWord(word) {
      var w = String(word || "");
      metaBrand.textContent = (/^[\x20-\x7e]+$/.test(w) ? w : "SHOP").toUpperCase() + " // STORE";
    }

    section.style.setProperty("--rng", String(heroVh));
    setWord(opts.word);
    resize();
    raf = requestAnimationFrame(tick);

    return {
      setPlans: setPlans,
      setWord: setWord,
      setLead: function (text) { if (text) lead.textContent = text; },
      destroy: destroy
    };
  }

  window.ShopVPNCinema = { supported: supported, mount: mount };
})();
