(function () {
  "use strict";

  var VERT = [
    "attribute vec3 aA;",
    "attribute vec3 aB;",
    "attribute vec4 aS;",
    "uniform float uMix;",
    "uniform float uAsm;",
    "uniform float uTime;",
    "uniform float uPpu;",
    "uniform float uSB;",
    "uniform float uSize;",
    "uniform float uDpr;",
    "uniform vec2 uRes;",
    "uniform vec2 uCenter;",
    "uniform vec2 uRot;",
    "uniform vec3 uPtr;",
    "uniform vec3 uC1;",
    "uniform vec3 uC2;",
    "varying vec3 vC;",
    "varying float vA;",
    "void main() {",
    "  float m = smoothstep(aS.x * 0.4, aS.x * 0.4 + 0.6, uMix);",
    "  vec3 p = mix(aA, aB * uSB, m);",
    "  float arc = sin(3.14159265 * m);",
    "  p += arc * (vec3(aS.y, aS.z, aS.w) - 0.5) * vec3(0.9, 0.6, 1.8);",
    "  vec3 sc = (fract(aS.xyz * vec3(7.13, 3.71, 5.29) + aS.yzx * 1.7) - 0.5) * vec3(5.2, 3.6, 4.4);",
    "  float a = smoothstep(aS.w * 0.45, aS.w * 0.45 + 0.55, uAsm);",
    "  p = mix(sc, p, a);",
    "  p += 0.006 * vec3(sin(uTime * 1.3 + aS.x * 40.0), cos(uTime * 1.1 + aS.y * 40.0), sin(uTime * 0.9 + aS.z * 40.0));",
    "  float cy = cos(uRot.x);",
    "  float sy = sin(uRot.x);",
    "  p = vec3(cy * p.x + sy * p.z, p.y, -sy * p.x + cy * p.z);",
    "  float cx = cos(uRot.y);",
    "  float sx = sin(uRot.y);",
    "  p = vec3(p.x, cx * p.y - sx * p.z, sx * p.y + cx * p.z);",
    "  float w = 3.4 / (3.4 - p.z);",
    "  vec2 sp = p.xy * w * uPpu;",
    "  vec2 d = sp - uPtr.xy;",
    "  float r = uPtr.z;",
    "  float f = exp(-dot(d, d) / (2.0 * r * r));",
    "  sp += normalize(d + vec2(0.0001)) * f * r * 0.5;",
    "  gl_Position = vec4((sp + uCenter) / (uRes * 0.5), 0.0, 1.0);",
    "  gl_PointSize = max(1.0, uSize * (0.65 + aS.w * 0.9) * w * uDpr);",
    "  float k = clamp(p.x * 0.5 + 0.5, 0.0, 1.0);",
    "  vC = mix(uC1, uC2, k);",
    "  vA = clamp(0.62 + 0.5 * p.z, 0.3, 1.0) * mix(0.3, 1.0, a);",
    "}"
  ].join("\n");

  var FRAG = [
    "precision mediump float;",
    "varying vec3 vC;",
    "varying float vA;",
    "void main() {",
    "  vec2 c = gl_PointCoord - 0.5;",
    "  float d = dot(c, c) * 4.0;",
    "  if (d > 1.0) discard;",
    "  float a = (1.0 - d) * (1.0 - d) * vA;",
    "  gl_FragColor = vec4(vC * a, a);",
    "}"
  ].join("\n");

  var SHIELD = "M50 4 L92 20 V58 C92 86 74 106 50 116 C26 106 8 86 8 58 V20 Z";
  var CHECK = "M30 60 L45 76 L72 44";

  var colorCtx = null;
  function cssColor(value, fallback) {
    try {
      if (!colorCtx) {
        var c = document.createElement("canvas");
        c.width = c.height = 1;
        colorCtx = c.getContext("2d", { willReadFrequently: true });
      }
      colorCtx.clearRect(0, 0, 1, 1);
      colorCtx.fillStyle = "#000";
      colorCtx.fillStyle = value;
      colorCtx.fillRect(0, 0, 1, 1);
      var d = colorCtx.getImageData(0, 0, 1, 1).data;
      return [d[0] / 255, d[1] / 255, d[2] / 255];
    } catch (e) {
      return fallback;
    }
  }

  function readTheme() {
    var cs = getComputedStyle(document.documentElement);
    var bg = cssColor(cs.getPropertyValue("--bg").trim() || "#070A1A", [0.03, 0.04, 0.1]);
    var lum = 0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2];
    return {
      c1: cssColor(cs.getPropertyValue("--accent").trim() || "#8E7BFF", [0.56, 0.48, 1]),
      c2: cssColor(cs.getPropertyValue("--accent-2").trim() || "#35E6CB", [0.2, 0.9, 0.8]),
      light: lum > 0.55
    };
  }

  function buildMask(w, h, draw) {
    var cv = document.createElement("canvas");
    cv.width = w;
    cv.height = h;
    var cx = cv.getContext("2d", { willReadFrequently: true });
    draw(cx, w, h);
    var data = cx.getImageData(0, 0, w, h).data;
    var fill = [];
    var edge = [];
    var minX = w, maxX = 0, minY = h, maxY = 0;
    for (var y = 1; y < h - 1; y++) {
      for (var x = 1; x < w - 1; x++) {
        var i = y * w + x;
        if (data[i * 4 + 3] < 140) continue;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
        fill.push(i);
        if (data[(i - 1) * 4 + 3] < 140 || data[(i + 1) * 4 + 3] < 140 || data[(i - w) * 4 + 3] < 140 || data[(i + w) * 4 + 3] < 140) edge.push(i);
      }
    }
    return { w: w, fill: fill, edge: edge, minX: minX, maxX: maxX, minY: minY, maxY: maxY };
  }

  function splitWord(word) {
    var parts = word.split(/\s+/).filter(Boolean);
    if (parts.length === 1) {
      var m = word.match(/^(.+?[a-z])([A-Z].*)$/);
      return m ? [m[1], m[2]] : [word];
    }
    if (parts.length === 2) return parts;
    var half = word.length / 2;
    var acc = 0;
    var cut = 1;
    for (var i = 0; i < parts.length - 1; i++) {
      acc += parts[i].length + 1;
      cut = i + 1;
      if (acc >= half) break;
    }
    return [parts.slice(0, cut).join(" "), parts.slice(cut).join(" ")];
  }

  function drawWord(lines) {
    var rtl = /[\u0590-\u08FF]/.test(lines.join(""));
    return function (cx, w, h) {
      var size = 240;
      var family = "Vazirmatn, \"Segoe UI\", Tahoma, Arial, sans-serif";
      cx.direction = rtl ? "rtl" : "ltr";
      cx.textAlign = "center";
      cx.textBaseline = "middle";
      cx.font = "800 " + size + "px " + family;
      var widest = 0;
      lines.forEach(function (l) { widest = Math.max(widest, cx.measureText(l).width); });
      var fit = Math.min((w - 80) / widest, (h - 60) / (size * 0.95 * lines.length));
      if (fit < 1) {
        size = Math.max(60, Math.floor(size * fit));
        cx.font = "800 " + size + "px " + family;
      }
      cx.fillStyle = "#fff";
      lines.forEach(function (l, i) {
        cx.fillText(l, w / 2, h / 2 + (i - (lines.length - 1) / 2) * size * 0.95);
      });
    };
  }

  function drawShield(cx, w, h) {
    cx.save();
    cx.scale(w / 100, h / 120);
    cx.fillStyle = "#fff";
    cx.fill(new Path2D(SHIELD));
    cx.globalCompositeOperation = "destination-out";
    cx.lineWidth = 9;
    cx.lineCap = "round";
    cx.lineJoin = "round";
    cx.stroke(new Path2D(CHECK));
    cx.restore();
  }

  function pick(mask, edgeShare) {
    var list = Math.random() < edgeShare && mask.edge.length ? mask.edge : mask.fill;
    var i = list[(Math.random() * list.length) | 0];
    return [(i % mask.w) + Math.random() - 0.5, ((i / mask.w) | 0) + Math.random() - 0.5];
  }

  function shapeWord(mask, count, out, offset, stride, maxH) {
    var bw = mask.maxX - mask.minX + 1;
    var bh = mask.maxY - mask.minY + 1;
    var scale = Math.min(2 / bw, maxH / bh);
    var cx = (mask.minX + mask.maxX) / 2;
    var cy = (mask.minY + mask.maxY) / 2;
    for (var n = 0; n < count; n++) {
      var p = pick(mask, 0.46);
      var x = (p[0] - cx) * scale;
      var y = -(p[1] - cy) * scale;
      var o = n * stride + offset;
      out[o] = x;
      out[o + 1] = y;
      out[o + 2] = (Math.random() - 0.5) * 0.2 + Math.sin(x * 3.2) * 0.035;
    }
  }

  function shapeShield(mask, count, out, offset, stride) {
    var bh = mask.maxY - mask.minY + 1;
    var scale = 0.9 / bh;
    var cx = (mask.minX + mask.maxX) / 2;
    var cy = (mask.minY + mask.maxY) / 2;
    for (var n = 0; n < count; n++) {
      var p = pick(mask, 0.42);
      var x = (p[0] - cx) * scale;
      var y = -(p[1] - cy) * scale;
      var dome = Math.max(0, 1 - (x * x) / 0.24 - (y * y) / 0.5);
      var o = n * stride + offset;
      out[o] = x;
      out[o + 1] = y;
      out[o + 2] = (Math.random() - 0.5) * 0.14 + dome * 0.26;
    }
  }

  function pointBudget() {
    var small = window.innerWidth < 720;
    var weak = (navigator.deviceMemory && navigator.deviceMemory <= 2) || (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4);
    var n = small ? 14000 : 24000;
    return weak ? Math.round(n * 0.6) : n;
  }

  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function smooth(a, b, v) { var t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); }

  function mount(opts) {
    var scene = opts.scene;
    var stage = opts.stage;
    var canvas = opts.canvas;
    var copy = opts.copy;
    if (!scene || !stage || !canvas) return null;

    var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    var count = pointBudget();
    var drawCount = count;
    var stride = 10;
    var data = new Float32Array(count * stride);
    var shieldMask = null;
    var wordText = "";
    var wordUnits = 0.62;
    var stacked = false;
    var gl = null;
    var ctx2 = null;
    var prog = null;
    var buf = null;
    var loc = {};
    var theme = readTheme();
    var W = 0, H = 0, dpr = 1;
    var ppu = 200, sB = 1, cx = 0, cy = 0;
    var progress = 0, progressTarget = 0;
    var ptr = { x: 0, y: 0, tx: 0, ty: 0, on: false, nx: 0, ny: 0 };
    var t0 = performance.now();
    var raf = 0;
    var visible = true;
    var dead = false;
    var lastNow = 0;
    var slow = 0;
    var ro = null;
    var io = null;
    var mo = null;
    var mq = null;

    function seeds() {
      for (var n = 0; n < count; n++) {
        var o = n * stride + 6;
        data[o] = Math.random();
        data[o + 1] = Math.random();
        data[o + 2] = Math.random();
        data[o + 3] = Math.random();
      }
    }

    function buildShield() {
      shieldMask = buildMask(400, 480, drawShield);
      shapeShield(shieldMask, count, data, 3, stride);
    }

    function buildWord(word) {
      wordText = word;
      var lines = window.innerWidth < 720 ? splitWord(word) : [word];
      stacked = window.innerWidth < 720;
      wordUnits = lines.length > 1 ? 1.1 : 0.62;
      var mask = buildMask(1400, lines.length > 1 ? 760 : 380, drawWord(lines));
      if (!mask.fill.length) return;
      shapeWord(mask, count, data, 0, stride, wordUnits);
    }

    function upload() {
      if (!gl || !buf) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    }

    function compile(type, src) {
      var s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error("shader");
      return s;
    }

    function initGL() {
      prog = gl.createProgram();
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
      gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error("link");
      gl.useProgram(prog);
      buf = gl.createBuffer();
      upload();
      var names = ["uMix", "uAsm", "uTime", "uPpu", "uSB", "uSize", "uDpr", "uRes", "uCenter", "uRot", "uPtr", "uC1", "uC2"];
      names.forEach(function (n) { loc[n] = gl.getUniformLocation(prog, n); });
      [["aA", 0], ["aB", 3], ["aS", 6]].forEach(function (a) {
        var l = gl.getAttribLocation(prog, a[0]);
        gl.enableVertexAttribArray(l);
        gl.vertexAttribPointer(l, a[0] === "aS" ? 4 : 3, gl.FLOAT, false, stride * 4, a[1] * 4);
      });
      gl.disable(gl.DEPTH_TEST);
      gl.enable(gl.BLEND);
      gl.clearColor(0, 0, 0, 0);
    }

    function applyBlend() {
      if (!gl) return;
      if (theme.light) gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      else gl.blendFunc(gl.ONE, gl.ONE);
    }

    function layout() {
      var rect = stage.getBoundingClientRect();
      W = Math.max(1, Math.round(rect.width));
      H = Math.max(1, Math.round(rect.height));
      dpr = Math.min(window.devicePixelRatio || 1, W < 720 ? 1.75 : 2);
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      var header = document.querySelector(".top");
      if (header) scene.style.setProperty("--hdr", header.offsetHeight + "px");
      var top = 8;
      var copyH = copy ? copy.offsetHeight + 24 : 200;
      var avail = Math.max(180, H - top - copyH - 16);
      ppu = Math.min(W * (W < 720 ? 0.44 : 0.4), 520);
      if (wordUnits * ppu > avail) ppu = avail / wordUnits;
      var shieldPx = Math.min(avail * 0.94, W * 0.72, 560);
      sB = clamp(shieldPx / (0.9 * ppu), 0.5, 3.2);
      cx = 0;
      cy = H / 2 - (top + avail / 2);
      if (gl) gl.viewport(0, 0, canvas.width, canvas.height);
      slow = 0;
    }

    function updateProgress() {
      var rect = scene.getBoundingClientRect();
      var total = Math.max(1, rect.height - H);
      progressTarget = clamp(-rect.top / total, 0, 1);
      scene.setAttribute("data-s", progressTarget > 0.02 ? "1" : "0");
    }

    function frameState(now) {
      var time = reduced ? 0 : (now - t0) / 1000;
      var asm = reduced ? 1 : smooth(0, 1, clamp((now - t0 - 150) / 2300, 0, 1));
      if (reduced) {
        progress = progressTarget;
        ptr.x = ptr.y = 0;
      } else {
        progress += (progressTarget - progress) * 0.12;
        ptr.x += (ptr.tx - ptr.x) * 0.08;
        ptr.y += (ptr.ty - ptr.y) * 0.08;
      }
      var mix = clamp((progress - 0.1) / 0.62, 0, 1);
      var yaw = Math.sin(mix * Math.PI) * 0.75 + ptr.x * 0.3 + (reduced ? 0 : Math.sin(time * 0.45) * 0.06);
      var pitch = -ptr.y * 0.16 + 0.04;
      return { time: time, asm: asm, mix: mix, yaw: yaw, pitch: pitch };
    }

    function drawGL(s) {
      if (!gl || gl.isContextLost()) return;
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(loc.uMix, s.mix);
      gl.uniform1f(loc.uAsm, s.asm);
      gl.uniform1f(loc.uTime, s.time);
      gl.uniform1f(loc.uPpu, ppu);
      gl.uniform1f(loc.uSB, sB);
      gl.uniform1f(loc.uSize, clamp(ppu * 0.0092, 2, 4.4) * (theme.light ? 1.15 : 1));
      gl.uniform1f(loc.uDpr, dpr);
      gl.uniform2f(loc.uRes, W, H);
      gl.uniform2f(loc.uCenter, cx, cy);
      gl.uniform2f(loc.uRot, s.yaw, s.pitch);
      var pr = ptr.on && !reduced ? 70 : 60;
      gl.uniform3f(loc.uPtr, ptr.on && !reduced ? ptr.nx - cx : -100000, ptr.on && !reduced ? ptr.ny - cy : -100000, pr);
      gl.uniform3f(loc.uC1, theme.c1[0], theme.c1[1], theme.c1[2]);
      gl.uniform3f(loc.uC2, theme.c2[0], theme.c2[1], theme.c2[2]);
      gl.drawArrays(gl.POINTS, 0, drawCount);
    }

    function draw2D(s) {
      ctx2.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx2.clearRect(0, 0, W, H);
      var n = Math.min(drawCount, 3600);
      var cyw = Math.cos(s.yaw);
      var syw = Math.sin(s.yaw);
      var rgb = function (c) { return "rgb(" + ((c[0] * 255) | 0) + "," + ((c[1] * 255) | 0) + "," + ((c[2] * 255) | 0) + ")"; };
      var col1 = rgb(theme.c1);
      var col2 = rgb(theme.c2);
      ctx2.globalAlpha = 0.85;
      for (var i = 0; i < n; i++) {
        var o = i * stride;
        var m = smooth(data[o + 6] * 0.4, data[o + 6] * 0.4 + 0.6, s.mix);
        var x = data[o] + (data[o + 3] * sB - data[o]) * m;
        var y = data[o + 1] + (data[o + 4] * sB - data[o + 1]) * m;
        var z = data[o + 2] + (data[o + 5] * sB - data[o + 2]) * m;
        var rx = cyw * x + syw * z;
        var rz = -syw * x + cyw * z;
        var w = 3.4 / (3.4 - rz);
        ctx2.fillStyle = rx > 0 ? col2 : col1;
        ctx2.fillRect(W / 2 + cx + rx * w * ppu, H / 2 - cy - y * w * ppu, 2, 2);
      }
    }

    function render(now) {
      var s = frameState(now);
      if (gl) drawGL(s);
      else if (ctx2) draw2D(s);
    }

    function govern(now) {
      if (lastNow) {
        var dt = now - lastNow;
        if (dt > 34) slow++;
        else if (slow > 0) slow--;
        if (slow > 45 && drawCount > 6000) {
          drawCount = Math.max(6000, Math.round(drawCount * 0.75));
          slow = 0;
        }
      }
      lastNow = now;
    }

    function loop(now) {
      raf = 0;
      if (dead) return;
      if (!canvas.isConnected) return destroy();
      if (!visible || document.hidden) { lastNow = 0; return; }
      govern(now);
      render(now);
      if (!reduced) raf = requestAnimationFrame(loop);
    }

    function kick() {
      if (dead || raf || !visible) return;
      raf = requestAnimationFrame(loop);
    }

    function onScroll() {
      if (!canvas.isConnected) return destroy();
      updateProgress();
      kick();
    }

    function onResize() {
      if (!canvas.isConnected) return destroy();
      if ((window.innerWidth < 720) !== stacked) {
        buildWord(wordText);
        upload();
      }
      layout();
      updateProgress();
      kick();
    }

    function onPointer(e) {
      if (reduced) return;
      var rect = stage.getBoundingClientRect();
      var x = e.clientX - rect.left;
      var y = e.clientY - rect.top;
      ptr.on = true;
      ptr.nx = x - W / 2;
      ptr.ny = H / 2 - y;
      ptr.tx = clamp(x / W - 0.5, -0.5, 0.5) * 2;
      ptr.ty = clamp(y / H - 0.5, -0.5, 0.5) * 2;
      kick();
    }

    function onLeave() {
      ptr.on = false;
      ptr.tx = 0;
      ptr.ty = 0;
      kick();
    }

    function onVisibility() {
      if (!document.hidden) kick();
    }

    function onTheme() {
      theme = readTheme();
      applyBlend();
      kick();
    }

    function onLost(e) {
      e.preventDefault();
    }

    function onRestored() {
      try {
        initGL();
        applyBlend();
        layout();
        kick();
      } catch (err) {
        gl = null;
      }
    }

    function destroy() {
      if (dead) return;
      dead = true;
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
      stage.removeEventListener("pointermove", onPointer);
      stage.removeEventListener("pointerdown", onPointer);
      stage.removeEventListener("pointerleave", onLeave);
      canvas.removeEventListener("webglcontextlost", onLost);
      canvas.removeEventListener("webglcontextrestored", onRestored);
      if (ro) ro.disconnect();
      if (io) io.disconnect();
      if (mo) mo.disconnect();
      if (mq && mq.removeEventListener) mq.removeEventListener("change", onTheme);
      if (gl) {
        var ext = gl.getExtension("WEBGL_lose_context");
        if (ext) ext.loseContext();
      }
      gl = null;
    }

    function setWord(word) {
      word = String(word || "").trim() || "ShopVPN";
      if (word === wordText || dead) return;
      buildWord(word);
      upload();
      kick();
    }

    try {
      gl = canvas.getContext("webgl", { alpha: true, antialias: false, premultipliedAlpha: true, powerPreference: "default" }) ||
        canvas.getContext("experimental-webgl", { alpha: true, antialias: false, premultipliedAlpha: true });
    } catch (e) {
      gl = null;
    }

    seeds();
    buildShield();
    buildWord(String(opts.word || "").trim() || "ShopVPN");

    if (gl) {
      try {
        initGL();
        applyBlend();
      } catch (e) {
        gl = null;
      }
    }
    if (!gl) {
      try {
        ctx2 = canvas.getContext("2d");
      } catch (e) {
        ctx2 = null;
      }
      if (!ctx2) {
        scene.setAttribute("data-s", "0");
        return { setWord: function () {}, destroy: destroy };
      }
    }

    layout();
    updateProgress();
    progress = progressTarget;

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);
    stage.addEventListener("pointermove", onPointer, { passive: true });
    stage.addEventListener("pointerdown", onPointer, { passive: true });
    stage.addEventListener("pointerleave", onLeave);
    canvas.addEventListener("webglcontextlost", onLost);
    canvas.addEventListener("webglcontextrestored", onRestored);

    if (window.ResizeObserver) {
      ro = new ResizeObserver(function () { onResize(); });
      ro.observe(stage);
    }
    if (window.IntersectionObserver) {
      io = new IntersectionObserver(function (entries) {
        visible = entries[0].isIntersecting;
        if (visible) { lastNow = 0; kick(); }
      });
      io.observe(scene);
    }
    if (window.MutationObserver) {
      mo = new MutationObserver(onTheme);
      mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }
    if (window.matchMedia) {
      mq = matchMedia("(prefers-color-scheme: light)");
      if (mq.addEventListener) mq.addEventListener("change", onTheme);
    }

    t0 = performance.now();
    kick();
    return { setWord: setWord, destroy: destroy };
  }

  window.ShopVPNHeroScene = { mount: mount };
})();
