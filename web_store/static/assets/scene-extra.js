(function () {
  "use strict";

  // حالت‌های سه‌بعدی سبک (Canvas 2D با پرسپکتیو دستی، بدون WebGL و بدون کتابخانه):
  // globe | network | tunnel | waves. فقط وقتی ادمین یکی از این‌ها را انتخاب کند بارگذاری می‌شود.

  var TAU = Math.PI * 2;
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
      return [d[0], d[1], d[2]];
    } catch (e) {
      return fallback;
    }
  }

  function readTheme() {
    var cs = getComputedStyle(document.documentElement);
    var a = cssColor(cs.getPropertyValue("--accent").trim() || "#8E7BFF", [142, 123, 255]);
    var b = cssColor(cs.getPropertyValue("--accent-2").trim() || "#35E6CB", [53, 230, 203]);
    var bg = cssColor(cs.getPropertyValue("--bg").trim() || "#070A1A", [7, 10, 26]);
    var light = (bg[0] * 299 + bg[1] * 587 + bg[2] * 114) / 1000 > 140;
    return { a: a, b: b, light: light };
  }

  function rgba(c, a) {
    return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + Math.max(0, Math.min(1, a)).toFixed(3) + ")";
  }
  function mixc(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t].map(Math.round);
  }

  // تعداد عناصر روی گوشی کمتر است
  function budget(full) {
    return window.innerWidth < 720 ? Math.round(full * 0.55) : full;
  }

  /* ----------------------------------------------------------------------------
     هر حالت یک سازنده است: (api) → { frame(t, dt), resize() }
     api: ctx, W, H (پیکسل CSS)، cx, cy (مرکز بصری)، ptr {x,y در بازه‌ی -1..1}، th (تم)
  ---------------------------------------------------------------------------- */

  function rotY(x, y, z, a) { var c = Math.cos(a), s = Math.sin(a); return [c * x + s * z, y, -s * x + c * z]; }
  function rotX(x, y, z, a) { var c = Math.cos(a), s = Math.sin(a); return [x, c * y - s * z, s * y + c * z]; }

  function modeGlobe(api) {
    var N = budget(900);
    var pts = [];
    var gold = Math.PI * (3 - Math.sqrt(5));
    for (var i = 0; i < N; i++) {
      var y = 1 - (i / (N - 1)) * 2;
      var r = Math.sqrt(1 - y * y);
      var th = gold * i;
      pts.push([Math.cos(th) * r, y, Math.sin(th) * r]);
    }
    // شهرهای تقریبی (lat, lon) برای مسیرهای اتصال
    var cities = [[51.5, -0.1], [35.7, 51.4], [40.7, -74], [35.7, 139.7], [52.5, 13.4], [25.2, 55.3], [-33.9, 151.2], [1.35, 103.8], [48.9, 2.3], [37.8, -122.4], [-23.5, -46.6], [55.7, 37.6]];
    function ll(lat, lon) {
      var la = lat * Math.PI / 180, lo = lon * Math.PI / 180;
      return [Math.cos(la) * Math.sin(lo), Math.sin(la), Math.cos(la) * Math.cos(lo)];
    }
    var cv = cities.map(function (c) { return ll(c[0], c[1]); });
    var arcs = [];
    function newArc() {
      var a = (Math.random() * cv.length) | 0, b = (Math.random() * cv.length) | 0;
      if (a === b) b = (b + 1) % cv.length;
      return { a: cv[a], b: cv[b], t: -Math.random() * 0.6, sp: 0.18 + Math.random() * 0.22 };
    }
    for (var k = 0; k < (window.innerWidth < 720 ? 4 : 7); k++) arcs.push(newArc());

    var yaw = 0.6, pitch = 0.35, vy = 0.0;
    var drag = null;

    function slerp(a, b, t) {
      var d = Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
      var om = Math.acos(d), so = Math.sin(om);
      if (so < 1e-4) return a;
      var s1 = Math.sin((1 - t) * om) / so, s2 = Math.sin(t * om) / so;
      return [a[0] * s1 + b[0] * s2, a[1] * s1 + b[1] * s2, a[2] * s1 + b[2] * s2];
    }

    return {
      down: function (x, y) { drag = { x: x, y: y }; },
      move: function (x, y) {
        if (!drag) return;
        yaw += (x - drag.x) * 0.006;
        pitch = Math.max(-0.9, Math.min(0.9, pitch + (y - drag.y) * 0.004));
        drag.x = x; drag.y = y;
      },
      up: function () { drag = null; },
      frame: function (t, dt) {
        var c = api.ctx, th = api.th;
        if (!drag) yaw += dt * 0.00014;
        var R = Math.min(api.W * 0.36, api.H * 0.29);
        var cx = api.cx, cy = api.H * 0.36;
        // هاله
        var g = c.createRadialGradient(cx, cy, R * 0.6, cx, cy, R * 1.35);
        g.addColorStop(0, rgba(th.a, th.light ? 0.10 : 0.16));
        g.addColorStop(1, rgba(th.a, 0));
        c.fillStyle = g;
        c.fillRect(0, 0, api.W, api.H);

        var P = 3.2;
        function proj(v) {
          var q = rotY(v[0], v[1], v[2], yaw);
          q = rotX(q[0], q[1], q[2], pitch);
          var w = P / (P - q[2]);
          return [cx + q[0] * R * w, cy - q[1] * R * w, q[2], w];
        }
        var i, p, a;
        for (i = 0; i < pts.length; i++) {
          p = proj(pts[i]);
          a = p[2] > 0 ? 0.35 + 0.55 * p[2] : 0.05 + 0.1 * (1 + p[2]);
          c.fillStyle = rgba(mixc(th.a, th.b, (p[0] - (cx - R)) / (2 * R)), a * (th.light ? 0.9 : 1));
          var sz = (p[2] > 0 ? 1.7 : 1.0) * p[3];
          c.fillRect(p[0] - sz / 2, p[1] - sz / 2, sz, sz);
        }
        // مسیرها و بسته‌های داده
        c.lineWidth = 1.4;
        for (i = 0; i < arcs.length; i++) {
          var ar = arcs[i];
          ar.t += dt * 0.001 * ar.sp;
          if (ar.t > 1.25) { arcs[i] = ar = newArc(); }
          var steps = 28, prev = null, lift = 0.22;
          for (var s = 0; s <= steps; s++) {
            var u = s / steps;
            var v = slerp(ar.a, ar.b, u);
            var h = 1 + lift * Math.sin(Math.PI * u);
            var q = proj([v[0] * h, v[1] * h, v[2] * h]);
            if (prev && q[2] > -0.15 && prev[2] > -0.15) {
              c.strokeStyle = rgba(th.b, 0.28 * (th.light ? 1.3 : 1));
              c.beginPath(); c.moveTo(prev[0], prev[1]); c.lineTo(q[0], q[1]); c.stroke();
            }
            prev = q;
          }
          var tt = Math.max(0, Math.min(1, ar.t));
          if (ar.t >= 0 && ar.t <= 1) {
            var vv = slerp(ar.a, ar.b, tt), hh = 1 + lift * Math.sin(Math.PI * tt);
            var pp = proj([vv[0] * hh, vv[1] * hh, vv[2] * hh]);
            if (pp[2] > -0.15) {
              var gl = c.createRadialGradient(pp[0], pp[1], 0, pp[0], pp[1], 9);
              gl.addColorStop(0, rgba(th.b, 0.95));
              gl.addColorStop(1, rgba(th.b, 0));
              c.fillStyle = gl;
              c.fillRect(pp[0] - 9, pp[1] - 9, 18, 18);
            }
          }
        }
        // نقطه‌ی شهرها
        for (i = 0; i < cv.length; i++) {
          p = proj(cv[i]);
          if (p[2] < 0) continue;
          c.fillStyle = rgba(th.b, 0.9);
          c.beginPath(); c.arc(p[0], p[1], 2.2 * p[3], 0, TAU); c.fill();
        }
      }
    };
  }

  function modeNetwork(api) {
    var N = budget(60);
    var nodes = [];
    for (var i = 0; i < N; i++) {
      nodes.push({ x: (Math.random() - 0.5) * 2.4, y: (Math.random() - 0.5) * 1.5, z: (Math.random() - 0.5) * 2.0, k: Math.random() });
    }
    var links = [];
    var maxD = 0.6;
    for (i = 0; i < N; i++) {
      for (var j = i + 1; j < N; j++) {
        var dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y, dz = nodes[i].z - nodes[j].z;
        if (dx * dx + dy * dy + dz * dz < maxD * maxD) links.push({ a: i, b: j, ph: Math.random(), sp: 0.12 + Math.random() * 0.2 });
      }
    }
    var yaw = 0, px = 0, py = 0;
    return {
      frame: function (t, dt) {
        var c = api.ctx, th = api.th;
        yaw += dt * 0.00011;
        px += (api.ptr.x - px) * 0.05;
        py += (api.ptr.y - py) * 0.05;
        var S = Math.min(api.W, api.H * 1.5) * 0.42;
        var cx = api.cx, cy = api.cy - api.H * 0.05;
        var P = 3.4;
        var pr = new Array(N);
        for (var i = 0; i < N; i++) {
          var n = nodes[i];
          var q = rotY(n.x, n.y, n.z, yaw + px * 0.5);
          q = rotX(q[0], q[1], q[2], 0.25 + py * 0.3);
          var w = P / (P - q[2]);
          pr[i] = [cx + q[0] * S * w, cy - q[1] * S * w, q[2], w];
        }
        c.lineWidth = 1;
        var L, a, b, da;
        for (i = 0; i < links.length; i++) {
          L = links[i]; a = pr[L.a]; b = pr[L.b];
          da = 0.05 + 0.15 * ((a[2] + b[2]) * 0.25 + 0.5);
          c.strokeStyle = rgba(th.a, da * (th.light ? 1.5 : 1));
          c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.stroke();
          L.ph += dt * 0.001 * L.sp; if (L.ph > 1) L.ph -= 1;
          var x = a[0] + (b[0] - a[0]) * L.ph, y = a[1] + (b[1] - a[1]) * L.ph;
          c.fillStyle = rgba(th.b, 0.85 * da * 3);
          c.fillRect(x - 1.3, y - 1.3, 2.6, 2.6);
        }
        for (i = 0; i < N; i++) {
          var p = pr[i];
          var al = 0.35 + 0.6 * (p[2] * 0.5 + 0.5);
          c.fillStyle = rgba(mixc(th.a, th.b, nodes[i].k), al);
          c.beginPath(); c.arc(p[0], p[1], (1.6 + nodes[i].k * 2.2) * p[3], 0, TAU); c.fill();
        }
      }
    };
  }

  function modeTunnel(api) {
    var N = budget(22);
    var rings = [];
    for (var i = 0; i < N; i++) rings.push({ z: i / N, rot: Math.random() * TAU, k: Math.random() });
    var stars = [];
    for (i = 0; i < budget(120); i++) stars.push({ a: Math.random() * TAU, r: 0.15 + Math.random() * 0.9, z: Math.random(), sp: 0.5 + Math.random() });
    var px = 0, py = 0;
    return {
      frame: function (t, dt) {
        var c = api.ctx, th = api.th;
        px += (api.ptr.x - px) * 0.05;
        py += (api.ptr.y - py) * 0.05;
        var vx = api.cx + px * api.W * 0.08, vy = api.cy - api.H * 0.08 + py * api.H * 0.06;
        var R = Math.max(api.W, api.H) * 0.75;
        var speed = dt * 0.00028;
        var i, r, z, s, k;
        for (i = 0; i < rings.length; i++) {
          r = rings[i];
          r.z -= speed; r.rot += dt * 0.0002;
          if (r.z <= 0.02) { r.z += 1; r.k = Math.random(); }
          z = r.z;
          s = Math.pow(1 - z, 2.4); // نزدیک = بزرگ
          var rad = R * (0.04 + s * 1.2);
          var al = Math.min(1, (1 - z) * 2.5) * Math.min(1, z * 8) * (th.light ? 0.85 : 0.7);
          c.lineWidth = 1 + s * 2.5;
          c.strokeStyle = rgba(mixc(th.a, th.b, r.k), al * 0.75);
          c.beginPath();
          for (var v = 0; v < 6; v++) {
            var ang = r.rot + v * TAU / 6;
            var x = vx + Math.cos(ang) * rad, y = vy + Math.sin(ang) * rad * 0.62;
            if (v) c.lineTo(x, y); else c.moveTo(x, y);
          }
          c.closePath(); c.stroke();
        }
        c.lineWidth = 1.2;
        for (i = 0; i < stars.length; i++) {
          k = stars[i];
          k.z -= speed * 1.6 * k.sp;
          if (k.z <= 0.02) { k.z = 1; k.a = Math.random() * TAU; k.r = 0.15 + Math.random() * 0.9; }
          var s1 = Math.pow(1 - k.z, 2.4), s2 = Math.pow(1 - Math.min(1, k.z + 0.05), 2.4);
          var r1 = R * (0.04 + s1 * 1.2) * k.r, r2 = R * (0.04 + s2 * 1.2) * k.r;
          var ca = Math.cos(k.a), sa = Math.sin(k.a) * 0.62;
          c.strokeStyle = rgba(th.b, Math.min(1, s1 * 1.6) * (th.light ? 0.8 : 0.65));
          c.beginPath(); c.moveTo(vx + ca * r2, vy + sa * r2); c.lineTo(vx + ca * r1, vy + sa * r1); c.stroke();
        }
      }
    };
  }

  function modeWaves(api) {
    var COLS = window.innerWidth < 720 ? 34 : 56;
    var ROWS = window.innerWidth < 720 ? 22 : 32;
    var rip = { x: 0, y: 0, on: 0 };
    return {
      frame: function (t, dt) {
        var c = api.ctx, th = api.th;
        var time = t * 0.0006;
        if (api.ptr.active) { rip.x = api.ptr.x; rip.y = api.ptr.y; rip.on = Math.min(1, rip.on + dt * 0.004); }
        else rip.on = Math.max(0, rip.on - dt * 0.002);
        var horizon = api.cy - api.H * 0.12;
        var camH = 1.25, depthN = 0.9, depthF = 5.2;
        var spanX = 6.0;
        for (var r = ROWS - 1; r >= 0; r--) {
          var zz = depthN + (r / (ROWS - 1)) * (depthF - depthN);
          var sc = api.H * 0.95 / zz;
          var rowA = (1 - r / (ROWS - 1));
          var prev = null;
          c.lineWidth = 1;
          for (var q = 0; q < COLS; q++) {
            var u = q / (COLS - 1) - 0.5;
            var wx = u * spanX * (0.55 + zz * 0.22);
            var h = Math.sin(wx * 1.1 + time * 2.2) * 0.42 + Math.cos(zz * 1.6 - time * 1.8 + wx * 0.4) * 0.34;
            if (rip.on > 0.01) {
              var dx = (wx / 3.2) - rip.x * 1.1, dz = (zz / 5.2 * 2 - 1) + rip.y * 0.8;
              var d = Math.sqrt(dx * dx + dz * dz);
              h += Math.sin(d * 9 - time * 6) * Math.exp(-d * 2.4) * 0.35 * rip.on;
            }
            var sx = api.cx + wx * sc * 0.5;
            var sy = horizon + (camH - h) * sc * 0.5 + (api.H * 0.04);
            if (prev) {
              c.strokeStyle = rgba(mixc(th.a, th.b, q / (COLS - 1)), (0.1 + rowA * 0.5) * (th.light ? 1.1 : 1));
              c.beginPath(); c.moveTo(prev[0], prev[1]); c.lineTo(sx, sy); c.stroke();
            }
            if (r % 2 === 0) {
              c.fillStyle = rgba(th.b, 0.15 + rowA * 0.6);
              c.fillRect(sx - 1, sy - 1, 2, 2);
            }
            prev = [sx, sy];
          }
        }
      }
    };
  }

  var MODES = { globe: modeGlobe, network: modeNetwork, tunnel: modeTunnel, waves: modeWaves };

  function mount(mode, opts) {
    var build = MODES[mode];
    var scene = opts.scene, stage = opts.stage, canvas = opts.canvas;
    if (!build || !scene || !stage || !canvas) return null;
    var ctx = null;
    try { ctx = canvas.getContext("2d"); } catch (e) { ctx = null; }
    if (!ctx) return null;

    var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    var api = { ctx: ctx, W: 0, H: 0, cx: 0, cy: 0, th: readTheme(), ptr: { x: 0, y: 0, active: false } };
    var impl = null;
    var raf = 0, dead = false, visible = true, last = 0, slow = 0, t0 = performance.now();
    var io = null, ro = null, mo = null;
    var dpr = 1;

    function layout() {
      var r = stage.getBoundingClientRect();
      api.W = Math.max(1, Math.round(r.width));
      api.H = Math.max(1, Math.round(r.height));
      dpr = Math.min(window.devicePixelRatio || 1, api.W < 720 ? 1.5 : 1.75);
      canvas.width = Math.round(api.W * dpr);
      canvas.height = Math.round(api.H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      api.cx = api.W / 2;
      // مرکز بصری کمی بالاتر از وسط؛ متن پایین صفحه است
      api.cy = api.H * 0.42;
    }

    function draw(now) {
      var dt = last ? Math.min(64, now - last) : 16;
      last = now;
      ctx.clearRect(0, 0, api.W, api.H);
      try { impl.frame(now - t0, dt); } catch (e) { stop(); return false; }
      return dt;
    }

    function tick(now) {
      raf = 0;
      if (dead) return;
      if (!canvas.isConnected) { destroy(); return; }
      if (!visible || document.hidden) { last = 0; return; }
      var dt = draw(now);
      if (dt === false) return;
      // دستگاه خیلی کند: انیمیشن را متوقف کن و فریم ثابت بگذار (سایت سنگین نشود)
      slow = dt > 45 ? slow + 1 : Math.max(0, slow - 1);
      if (slow > 90) { return; }
      raf = requestAnimationFrame(tick);
    }

    function kick() {
      if (dead || raf || reduced) return;
      last = 0;
      raf = requestAnimationFrame(tick);
    }

    function stop() { if (raf) cancelAnimationFrame(raf); raf = 0; }

    function pos(e) {
      var r = stage.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height };
    }
    function onMove(e) {
      var p = pos(e);
      api.ptr.x = (p.x / p.w) * 2 - 1;
      api.ptr.y = (p.y / p.h) * 2 - 1;
      api.ptr.active = true;
      if (impl.move) impl.move(p.x, p.y);
    }
    function onDown(e) { var p = pos(e); if (impl.down) impl.down(p.x, p.y); onMove(e); }
    function onUp() { if (impl.up) impl.up(); }
    function onLeave() { api.ptr.active = false; api.ptr.x = 0; api.ptr.y = 0; onUp(); }
    function onVis() { if (!document.hidden) kick(); }
    function onTheme() { api.th = readTheme(); if (reduced) { draw(performance.now()); } }
    function onResize() { layout(); if (reduced || !raf) draw(performance.now()); }

    function destroy() {
      if (dead) return;
      dead = true;
      stop();
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVis);
      stage.removeEventListener("pointermove", onMove);
      stage.removeEventListener("pointerdown", onDown);
      stage.removeEventListener("pointerup", onUp);
      stage.removeEventListener("pointerleave", onLeave);
      if (io) io.disconnect();
      if (ro) ro.disconnect();
      if (mo) mo.disconnect();
    }

    layout();
    impl = build(api);
    scene.classList.add("flat", "is-3d");
    scene.setAttribute("data-mode", mode);
    canvas.style.touchAction = "pan-y";

    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVis);
    stage.addEventListener("pointermove", onMove, { passive: true });
    stage.addEventListener("pointerdown", onDown, { passive: true });
    stage.addEventListener("pointerup", onUp, { passive: true });
    stage.addEventListener("pointerleave", onLeave);
    if (window.ResizeObserver) { ro = new ResizeObserver(onResize); ro.observe(stage); }
    if (window.IntersectionObserver) {
      io = new IntersectionObserver(function (en) { visible = en[0].isIntersecting; if (visible) kick(); });
      io.observe(scene);
    }
    if (window.MutationObserver) {
      mo = new MutationObserver(onTheme);
      mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }

    if (reduced) draw(performance.now()); else kick();
    return { setWord: function () {}, destroy: destroy };
  }

  window.ShopVPNScenes = { mount: mount, modes: Object.keys(MODES) };
})();
