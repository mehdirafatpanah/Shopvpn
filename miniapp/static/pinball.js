(function () {
  "use strict";

  const W = 400;
  const H = 720;
  const BALL_R = 8;
  const FLIPPER_R = 7;
  const GRAVITY = 650;
  const MAX_SPEED = 1500;
  const STEP = 1 / 240;
  const LANE_X = 370;
  const LANE_REST_Y = 680;
  const LANE_WALL_X = 354;
  const BALLS_PER_GAME = 3;
  const BEST_KEY = "sv-pinball-best";

  function buildTable() {
    const segments = [];
    const seg = (x1, y1, x2, y2, o) => segments.push(Object.assign({ x1, y1, x2, y2, e: 0.45, kick: 0, score: 0, id: "" }, o || {}));

    const arcCx = 200, arcCy = 200, arcR = 186, arcN = 36;
    for (let i = 0; i < arcN; i++) {
      const a1 = Math.PI + (Math.PI * i) / arcN;
      const a2 = Math.PI + (Math.PI * (i + 1)) / arcN;
      seg(arcCx + arcR * Math.cos(a1), arcCy + arcR * Math.sin(a1), arcCx + arcR * Math.cos(a2), arcCy + arcR * Math.sin(a2), { e: 0.3, arc: true });
    }
    seg(14, 200, 14, 570);
    seg(386, 200, 386, 702);
    seg(LANE_WALL_X, 140, LANE_WALL_X, 702);
    seg(LANE_WALL_X, 140, 326, 182);
    seg(LANE_WALL_X, 90, LANE_WALL_X, 140, { gate: true, e: 0.3 });
    seg(LANE_WALL_X + 1, 702, 386, 702);
    seg(14, 570, 94, 640);
    seg(LANE_WALL_X, 570, 274, 640);

    const slings = [
      { a: [14, 490], b: [14, 560], c: [70, 590] },
      { a: [LANE_WALL_X, 490], b: [LANE_WALL_X, 560], c: [298, 590] },
    ];
    slings.forEach((s, i) => {
      seg(s.a[0], s.a[1], s.c[0], s.c[1], { e: 0.5, kick: 520, score: 10, id: "sling" + i });
      seg(s.b[0], s.b[1], s.c[0], s.c[1], { e: 0.4 });
      seg(s.a[0], s.a[1], s.b[0], s.b[1], { e: 0.4 });
    });

    const bumpers = [
      { x: 130, y: 250, r: 22, score: 100 },
      { x: 238, y: 250, r: 22, score: 100 },
      { x: 184, y: 330, r: 22, score: 150 },
    ];
    const posts = [
      { x: 60, y: 420, r: 5 },
      { x: 308, y: 420, r: 5 },
      { x: 100, y: 650, r: 7 },
      { x: 268, y: 650, r: 7 },
      { x: 90, y: 160, r: 5 },
      { x: 278, y: 160, r: 5 },
    ];
    const flippers = [
      { px: 100, py: 650, len: 66, rest: 0.42, up: -0.5, dir: 1 },
      { px: 268, py: 650, len: 66, rest: 0.42, up: -0.5, dir: -1 },
    ].map((f) => Object.assign(f, { angle: f.rest, pressed: false, aDot: 0 }));

    return { segments, slings, bumpers, posts, flippers };
  }

  function createEngine(options) {
    const opts = options || {};
    const rng = opts.random || Math.random;
    const table = buildTable();
    const state = {
      phase: "ready",
      score: 0,
      ballsLeft: BALLS_PER_GAME,
      power: 0,
      charging: false,
      ball: { x: LANE_X, y: LANE_REST_Y, vx: 0, vy: 0 },
      flash: {},
      events: [],
      idle: 0,
      launchGrace: 0,
    };

    function emit(type, data) {
      state.events.push(Object.assign({ type }, data || {}));
    }

    function resetBallToLane() {
      state.ball.x = LANE_X;
      state.ball.y = LANE_REST_Y;
      state.ball.vx = 0;
      state.ball.vy = 0;
      state.power = 0;
      state.charging = false;
      state.idle = 0;
      state.phase = "ready";
    }

    function newGame() {
      state.score = 0;
      state.ballsLeft = BALLS_PER_GAME;
      resetBallToLane();
      emit("newgame");
    }

    function chargeStart() {
      if (state.phase === "ready") state.charging = true;
    }

    function chargeRelease() {
      if (state.phase !== "ready" || !state.charging) {
        state.charging = false;
        return;
      }
      const p = Math.min(Math.max(state.power, 0), 1);
      state.ball.vx = 0;
      state.ball.vy = -(980 + 440 * p);
      state.ball.y = LANE_REST_Y;
      state.charging = false;
      state.power = 0;
      state.phase = "play";
      state.idle = 0;
      state.launchGrace = 0.6;
      emit("launch", { power: p });
    }

    function setFlipper(side, pressed) {
      const f = table.flippers[side];
      if (f.pressed !== pressed) {
        f.pressed = pressed;
        if (pressed && state.phase === "play") emit("flip", { side });
      }
    }

    function addScore(points, x, y) {
      state.score += points;
      emit("score", { points, x, y });
    }

    function reflect(b, nx, ny, e, surfVx, surfVy) {
      const rvx = b.vx - surfVx;
      const rvy = b.vy - surfVy;
      const vn = rvx * nx + rvy * ny;
      if (vn >= 0) return 0;
      const j = -(1 + e) * vn;
      b.vx += j * nx;
      b.vy += j * ny;
      return -vn;
    }

    function collideSegment(b, s) {
      if (s.gate && b.vx <= 0) return false;
      const dx = s.x2 - s.x1;
      const dy = s.y2 - s.y1;
      const l2 = dx * dx + dy * dy;
      let t = ((b.x - s.x1) * dx + (b.y - s.y1) * dy) / l2;
      t = Math.max(0, Math.min(1, t));
      const cx = s.x1 + dx * t;
      const cy = s.y1 + dy * t;
      let ex = b.x - cx;
      let ey = b.y - cy;
      const d2 = ex * ex + ey * ey;
      if (d2 >= BALL_R * BALL_R) return false;
      let d = Math.sqrt(d2);
      if (d < 1e-6) {
        const len = Math.sqrt(l2);
        ex = -dy / len;
        ey = dx / len;
        d = 0;
      } else {
        ex /= d;
        ey /= d;
      }
      b.x = cx + ex * BALL_R;
      b.y = cy + ey * BALL_R;
      const impact = reflect(b, ex, ey, s.e, 0, 0);
      if (impact > 0) {
        const tx = -ey;
        const ty = ex;
        const vt = b.vx * tx + b.vy * ty;
        b.vx -= tx * vt * 0.004;
        b.vy -= ty * vt * 0.004;
        if (s.kick && impact > 30) {
          const vn = b.vx * ex + b.vy * ey;
          if (vn < s.kick) {
            b.vx += ex * (s.kick - vn);
            b.vy += ey * (s.kick - vn);
          }
          addScore(s.score, b.x, b.y);
          state.flash[s.id] = 0.18;
          emit("kick", { id: s.id });
        } else if (impact > 160) {
          emit("wall");
        }
      }
      return true;
    }

    function collideCircle(b, c, e, kick, scoreVal, id) {
      const ex0 = b.x - c.x;
      const ey0 = b.y - c.y;
      const rr = BALL_R + c.r;
      const d2 = ex0 * ex0 + ey0 * ey0;
      if (d2 >= rr * rr) return;
      const d = Math.sqrt(d2) || 1e-6;
      const nx = ex0 / d;
      const ny = ey0 / d;
      b.x = c.x + nx * rr;
      b.y = c.y + ny * rr;
      const impact = reflect(b, nx, ny, e, 0, 0);
      if (impact <= 0) return;
      if (kick) {
        const vn = b.vx * nx + b.vy * ny;
        if (vn < kick) {
          b.vx += nx * (kick - vn);
          b.vy += ny * (kick - vn);
        }
        addScore(scoreVal, c.x, c.y - c.r);
        state.flash[id] = 0.2;
        emit("bump", { id });
      } else if (impact > 160) {
        emit("wall");
      }
    }

    function flipperTip(f) {
      return {
        x: f.px + f.dir * f.len * Math.cos(f.angle),
        y: f.py + f.len * Math.sin(f.angle),
      };
    }

    function collideFlipper(b, f) {
      const tip = flipperTip(f);
      const dx = tip.x - f.px;
      const dy = tip.y - f.py;
      const l2 = dx * dx + dy * dy;
      let t = ((b.x - f.px) * dx + (b.y - f.py) * dy) / l2;
      t = Math.max(0, Math.min(1, t));
      const cx = f.px + dx * t;
      const cy = f.py + dy * t;
      const ex0 = b.x - cx;
      const ey0 = b.y - cy;
      const rr = BALL_R + FLIPPER_R;
      const d2 = ex0 * ex0 + ey0 * ey0;
      if (d2 >= rr * rr) return;
      const d = Math.sqrt(d2) || 1e-6;
      const nx = ex0 / d;
      const ny = ey0 / d;
      b.x = cx + nx * rr;
      b.y = cy + ny * rr;
      const s = t * f.len;
      const svx = f.aDot * (-f.dir * Math.sin(f.angle)) * s;
      const svy = f.aDot * Math.cos(f.angle) * s;
      const impact = reflect(b, nx, ny, 0.32, svx, svy);
      if (impact > 160) emit("flipperHit");
    }

    function updateFlippers(dt) {
      table.flippers.forEach((f) => {
        const target = f.pressed ? f.up : f.rest;
        const speed = f.pressed ? 22 : 13;
        const prev = f.angle;
        if (f.angle < target) f.angle = Math.min(target, f.angle + speed * dt);
        else if (f.angle > target) f.angle = Math.max(target, f.angle - speed * dt);
        f.aDot = (f.angle - prev) / dt;
      });
    }

    function step(dt) {
      Object.keys(state.flash).forEach((k) => {
        state.flash[k] -= dt;
        if (state.flash[k] <= 0) delete state.flash[k];
      });
      updateFlippers(dt);
      const b = state.ball;

      if (state.phase === "ready") {
        if (state.charging) state.power = Math.min(1, state.power + dt * 1.3);
        b.x = LANE_X;
        b.y = LANE_REST_Y + state.power * 26;
        b.vx = 0;
        b.vy = 0;
        return;
      }
      if (state.phase !== "play") return;

      if (state.launchGrace > 0) state.launchGrace -= dt;
      b.vy += GRAVITY * dt;
      const sp0 = Math.hypot(b.vx, b.vy);
      if (sp0 > MAX_SPEED) {
        b.vx *= MAX_SPEED / sp0;
        b.vy *= MAX_SPEED / sp0;
      }
      b.x += b.vx * dt;
      b.y += b.vy * dt;

      for (let pass = 0; pass < 2; pass++) {
        for (let i = 0; i < table.segments.length; i++) collideSegment(b, table.segments[i]);
        for (let i = 0; i < table.posts.length; i++) collideCircle(b, table.posts[i], 0.5, 0, 0, "");
        for (let i = 0; i < table.bumpers.length; i++) collideCircle(b, table.bumpers[i], 0.6, 560, table.bumpers[i].score, "b" + i);
        for (let i = 0; i < table.flippers.length; i++) collideFlipper(b, table.flippers[i]);
      }

      const speed = Math.hypot(b.vx, b.vy);
      const inLane = b.x > LANE_WALL_X && b.y > 400;
      if (speed < 14) state.idle += dt;
      else state.idle = 0;

      if (inLane && state.launchGrace <= 0 && b.y > LANE_REST_Y - 6 && speed < 40) {
        resetBallToLane();
        emit("relaunch");
        return;
      }
      if (!inLane && state.idle > 2.2) {
        b.vx += (rng() - 0.5) * 360;
        b.vy -= 260 + rng() * 120;
        state.idle = 0;
        emit("nudge");
      }
      if (b.y > H + 24) {
        state.ballsLeft -= 1;
        emit("drain", { ballsLeft: state.ballsLeft });
        if (state.ballsLeft <= 0) {
          state.phase = "over";
          emit("gameover", { score: state.score });
        } else {
          resetBallToLane();
        }
      }
    }

    function update(dtSeconds) {
      let remaining = Math.min(dtSeconds, 0.05);
      while (remaining > 1e-9) {
        const dt = Math.min(STEP, remaining);
        step(dt);
        remaining -= dt;
      }
    }

    function drainEvents() {
      const e = state.events;
      state.events = [];
      return e;
    }

    return {
      table,
      state,
      update,
      newGame,
      chargeStart,
      chargeRelease,
      setFlipper,
      drainEvents,
      flipperTip,
      constants: { W, H, BALL_R, FLIPPER_R, LANE_X, LANE_REST_Y, BALLS_PER_GAME },
    };
  }

  function readBest() {
    try {
      const v = parseInt(localStorage.getItem(BEST_KEY) || "0", 10);
      return isFinite(v) && v > 0 ? v : 0;
    } catch (_) {
      return 0;
    }
  }

  function writeBest(v) {
    try {
      localStorage.setItem(BEST_KEY, String(v));
    } catch (_) {}
  }

  function mount(root, options) {
    const opts = options || {};
    const tg = window.Telegram && window.Telegram.WebApp;
    const fmt = (n) => Number(n).toLocaleString("fa-IR");
    const engine = createEngine();
    const st = engine.state;
    let best = readBest();
    let rafId = 0;
    let lastTs = 0;
    let destroyed = false;
    let popups = [];
    let lastHaptic = 0;
    const pointers = new Map();
    const keys = new Set();

    root.innerHTML = `
      <div class="pb-wrap">
        <div class="pb-hud">
          <div class="pb-stat"><span>امتیاز</span><b data-pb="score">${fmt(0)}</b></div>
          <div class="pb-stat"><span>توپ</span><b data-pb="balls"></b></div>
          <div class="pb-stat"><span>رکورد</span><b data-pb="best">${fmt(best)}</b></div>
        </div>
        <div class="pb-stage" data-pb="stage">
          <canvas class="pb-canvas" data-pb="canvas"></canvas>
          <div class="pb-hint" data-pb="hint">نگه دار و رها کن تا توپ پرتاب شود</div>
          <div class="pb-over" data-pb="over" hidden>
            <div class="pb-over-card">
              <div class="pb-over-title">پایان بازی</div>
              <div class="pb-over-score" data-pb="finalScore"></div>
              <div class="pb-over-best" data-pb="newBest" hidden>🏆 رکورد جدید!</div>
              <button class="btn" type="button" data-pb="again">🔄 بازی دوباره</button>
            </div>
          </div>
        </div>
        <div class="pb-help">بعد از پرتاب، لمس نیمه‌ی چپ یا راست صفحه فلیپر همان طرف را می‌زند</div>
      </div>`;

    const q = (k) => root.querySelector(`[data-pb="${k}"]`);
    const canvas = q("canvas");
    const stage = q("stage");
    const ctx = canvas.getContext("2d");
    const elScore = q("score");
    const elBalls = q("balls");
    const elBest = q("best");
    const elHint = q("hint");
    const elOver = q("over");
    const elFinal = q("finalScore");
    const elNewBest = q("newBest");

    const cs = getComputedStyle(document.documentElement);
    const css = (name, fb) => (cs.getPropertyValue(name) || "").trim() || fb;
    const col = {
      cyan: css("--cyan", "#7ef9ff"),
      pink: css("--pink", "#ff2f92"),
      violet: css("--violet", "#b06bff"),
      amber: css("--amber", "#ffcf6b"),
      orange: css("--orange", "#ff8a3d"),
    };

    let scale = 1;
    let dpr = 1;

    function resize() {
      const parent = root.getBoundingClientRect();
      const stageTop = stage.getBoundingClientRect().top;
      const tabbar = document.getElementById("tabbar");
      const tabH = tabbar ? tabbar.getBoundingClientRect().height : 0;
      const helpEl = root.querySelector(".pb-help");
      const helpH = helpEl ? helpEl.getBoundingClientRect().height + 8 : 0;
      const availH = Math.max(280, window.innerHeight - stageTop - tabH - helpH - 10);
      const availW = Math.max(200, parent.width || window.innerWidth - 24);
      const cssH = Math.min(availH, availW * (H / W));
      const cssW = cssH * (W / H);
      dpr = Math.min(window.devicePixelRatio || 1, 2.5);
      canvas.style.width = cssW + "px";
      canvas.style.height = cssH + "px";
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      scale = cssW / W;
    }

    const hudCache = { score: -1, best: -1, balls: -1 };

    function updateHud() {
      if (hudCache.score !== st.score) {
        hudCache.score = st.score;
        elScore.textContent = fmt(st.score);
      }
      const shownBest = Math.max(best, st.score);
      if (hudCache.best !== shownBest) {
        hudCache.best = shownBest;
        elBest.textContent = fmt(shownBest);
      }
      if (hudCache.balls !== st.ballsLeft) {
        hudCache.balls = st.ballsLeft;
        let dots = "";
        for (let i = 0; i < engine.constants.BALLS_PER_GAME; i++) dots += i < st.ballsLeft ? "●" : "○";
        elBalls.textContent = dots;
      }
    }

    function haptic(kind) {
      const now = performance.now();
      if (now - lastHaptic < 70) return;
      lastHaptic = now;
      try {
        if (!tg || !tg.HapticFeedback) return;
        if (kind === "drain") tg.HapticFeedback.notificationOccurred("warning");
        else tg.HapticFeedback.impactOccurred(kind === "bump" ? "medium" : "light");
      } catch (_) {}
    }

    function applyFlippers() {
      let left = keys.has("left");
      let right = keys.has("right");
      pointers.forEach((side) => {
        if (side === 0) left = true;
        else right = true;
      });
      engine.setFlipper(0, left);
      engine.setFlipper(1, right);
    }

    function showOver() {
      elFinal.textContent = fmt(st.score);
      const isBest = st.score > best;
      if (isBest) {
        best = st.score;
        writeBest(best);
      }
      elNewBest.hidden = !isBest;
      elOver.hidden = false;
      elHint.hidden = true;
      updateHud();
    }

    function handleEvents() {
      engine.drainEvents().forEach((ev) => {
        if (ev.type === "score") {
          popups.push({ text: "+" + ev.points, x: ev.x, y: ev.y, life: 0.8 });
        } else if (ev.type === "launch") {
          elHint.hidden = true;
        } else if (ev.type === "bump" || ev.type === "kick") {
          haptic("bump");
        } else if (ev.type === "flip") {
          haptic("light");
        } else if (ev.type === "drain") {
          haptic("drain");
          if (st.score > best) {
            best = st.score;
            writeBest(best);
          }
        } else if (ev.type === "relaunch" || ev.type === "newgame") {
          elHint.hidden = false;
        } else if (ev.type === "gameover") {
          showOver();
        }
      });
    }

    function pathSegments(list) {
      list.forEach((s) => {
        ctx.moveTo(s.x1, s.y1);
        ctx.lineTo(s.x2, s.y2);
      });
    }

    function draw() {
      ctx.setTransform(scale * dpr, 0, 0, scale * dpr, 0, 0);
      const bg = ctx.createLinearGradient(0, 0, 0, H);
      bg.addColorStop(0, "#0b0624");
      bg.addColorStop(1, "#16093a");
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);

      ctx.strokeStyle = "rgba(255,255,255,0.035)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = 0; x <= W; x += 40) {
        ctx.moveTo(x, 0);
        ctx.lineTo(x, H);
      }
      for (let y = 0; y <= H; y += 40) {
        ctx.moveTo(0, y);
        ctx.lineTo(W, y);
      }
      ctx.stroke();

      const tbl = engine.table;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.shadowColor = col.cyan;
      ctx.shadowBlur = 10;
      ctx.strokeStyle = col.cyan;
      ctx.lineWidth = 3;
      ctx.beginPath();
      pathSegments(tbl.segments.filter((s) => !s.id && !s.gate));
      ctx.stroke();
      ctx.shadowBlur = 0;

      ctx.strokeStyle = col.amber;
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      pathSegments(tbl.segments.filter((s) => s.gate));
      ctx.stroke();
      ctx.setLineDash([]);

      tbl.slings.forEach((s, i) => {
        const on = st.flash["sling" + i] > 0;
        ctx.beginPath();
        ctx.moveTo(s.a[0], s.a[1]);
        ctx.lineTo(s.c[0], s.c[1]);
        ctx.lineTo(s.b[0], s.b[1]);
        ctx.closePath();
        ctx.fillStyle = on ? col.amber : "rgba(176,107,255,0.28)";
        ctx.fill();
        ctx.shadowColor = on ? col.amber : col.violet;
        ctx.shadowBlur = on ? 18 : 8;
        ctx.strokeStyle = on ? col.amber : col.violet;
        ctx.lineWidth = 3;
        ctx.stroke();
        ctx.shadowBlur = 0;
      });

      tbl.posts.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = "#e9defc";
        ctx.fill();
      });

      tbl.bumpers.forEach((bp, i) => {
        const on = st.flash["b" + i] > 0;
        const g = ctx.createRadialGradient(bp.x - 6, bp.y - 6, 2, bp.x, bp.y, bp.r);
        g.addColorStop(0, on ? "#fff7d6" : "#ffd0ea");
        g.addColorStop(1, on ? col.amber : col.pink);
        ctx.shadowColor = on ? col.amber : col.pink;
        ctx.shadowBlur = on ? 28 : 12;
        ctx.beginPath();
        ctx.arc(bp.x, bp.y, bp.r, 0, Math.PI * 2);
        ctx.fillStyle = g;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.lineWidth = 3;
        ctx.strokeStyle = "rgba(255,255,255,0.75)";
        ctx.beginPath();
        ctx.arc(bp.x, bp.y, bp.r - 6, 0, Math.PI * 2);
        ctx.stroke();
      });

      const plungerY = engine.constants.LANE_REST_Y + st.power * 26 + BALL_R;
      ctx.fillStyle = "rgba(255,255,255,0.12)";
      ctx.fillRect(LANE_WALL_X + 4, plungerY + 6, 28, 702 - plungerY - 8);
      ctx.fillStyle = col.orange;
      ctx.fillRect(LANE_WALL_X + 6, plungerY, 24, 5);
      ctx.strokeStyle = "rgba(255,255,255,0.35)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      const coils = 6;
      for (let i = 0; i <= coils; i++) {
        const y = plungerY + 8 + ((702 - plungerY - 12) * i) / coils;
        ctx.moveTo(LANE_WALL_X + 9, y);
        ctx.lineTo(LANE_WALL_X + 27, y);
      }
      ctx.stroke();

      if (st.phase === "ready") {
        ctx.fillStyle = "rgba(255,255,255,0.1)";
        ctx.fillRect(392, 560, 4, 140);
        ctx.fillStyle = st.power > 0.85 ? col.pink : col.cyan;
        ctx.fillRect(392, 700 - 140 * st.power, 4, 140 * st.power);
      }

      tbl.flippers.forEach((f) => {
        const tip = engine.flipperTip(f);
        const g = ctx.createLinearGradient(f.px, f.py, tip.x, tip.y);
        g.addColorStop(0, col.violet);
        g.addColorStop(1, f.pressed ? col.amber : col.cyan);
        ctx.shadowColor = f.pressed ? col.amber : col.cyan;
        ctx.shadowBlur = f.pressed ? 16 : 8;
        ctx.strokeStyle = g;
        ctx.lineWidth = FLIPPER_R * 2;
        ctx.beginPath();
        ctx.moveTo(f.px, f.py);
        ctx.lineTo(tip.x, tip.y);
        ctx.stroke();
        ctx.shadowBlur = 0;
      });

      if (st.phase !== "over") {
        const b = st.ball;
        const bg2 = ctx.createRadialGradient(b.x - 3, b.y - 3, 1, b.x, b.y, BALL_R);
        bg2.addColorStop(0, "#ffffff");
        bg2.addColorStop(1, "#8f9bb8");
        ctx.shadowColor = "rgba(255,255,255,0.8)";
        ctx.shadowBlur = 10;
        ctx.beginPath();
        ctx.arc(b.x, b.y, BALL_R, 0, Math.PI * 2);
        ctx.fillStyle = bg2;
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      ctx.font = "700 16px Rajdhani, Vazirmatn, sans-serif";
      ctx.textAlign = "center";
      popups.forEach((p) => {
        ctx.globalAlpha = Math.max(0, Math.min(1, p.life / 0.5));
        ctx.fillStyle = col.amber;
        ctx.fillText(p.text, p.x, p.y - (0.8 - p.life) * 40);
      });
      ctx.globalAlpha = 1;
    }

    function frame(ts) {
      if (destroyed) return;
      if (!root.isConnected) {
        destroy();
        return;
      }
      const dt = lastTs ? (ts - lastTs) / 1000 : 0;
      lastTs = ts;
      engine.update(dt);
      popups.forEach((p) => (p.life -= dt));
      popups = popups.filter((p) => p.life > 0);
      handleEvents();
      updateHud();
      draw();
      rafId = requestAnimationFrame(frame);
    }

    function sideOf(e) {
      const r = canvas.getBoundingClientRect();
      return e.clientX - r.left < r.width / 2 ? 0 : 1;
    }

    function onDown(e) {
      if (st.phase === "over") return;
      e.preventDefault();
      try {
        canvas.setPointerCapture(e.pointerId);
      } catch (_) {}
      if (st.phase === "ready") {
        engine.chargeStart();
        return;
      }
      pointers.set(e.pointerId, sideOf(e));
      applyFlippers();
    }

    function onUp(e) {
      e.preventDefault();
      if (st.phase === "ready") engine.chargeRelease();
      pointers.delete(e.pointerId);
      applyFlippers();
    }

    function keyName(e) {
      if (e.code === "ArrowLeft" || e.code === "KeyZ" || e.code === "KeyA") return "left";
      if (e.code === "ArrowRight" || e.code === "Slash" || e.code === "KeyD" || e.code === "KeyL") return "right";
      if (e.code === "Space" || e.code === "ArrowDown") return "plunger";
      return "";
    }

    function onKeyDown(e) {
      const k = keyName(e);
      if (!k || st.phase === "over") return;
      e.preventDefault();
      if (k === "plunger") {
        if (st.phase === "ready") engine.chargeStart();
        return;
      }
      if (st.phase === "play") {
        keys.add(k);
        applyFlippers();
      }
    }

    function onKeyUp(e) {
      const k = keyName(e);
      if (!k) return;
      if (k === "plunger") {
        if (st.phase === "ready") engine.chargeRelease();
        return;
      }
      keys.delete(k);
      applyFlippers();
    }

    function onVisibility() {
      lastTs = 0;
      if (document.hidden) {
        pointers.clear();
        keys.clear();
        applyFlippers();
      }
    }

    function again() {
      elOver.hidden = true;
      popups = [];
      pointers.clear();
      keys.clear();
      applyFlippers();
      engine.newGame();
      handleEvents();
      updateHud();
    }

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", resize);
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("keyup", onKeyUp);
      document.removeEventListener("visibilitychange", onVisibility);
      try {
        if (tg && tg.enableVerticalSwipes) tg.enableVerticalSwipes();
      } catch (_) {}
    }

    canvas.style.touchAction = "none";
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointercancel", onUp);
    canvas.addEventListener("contextmenu", (e) => e.preventDefault());
    q("again").addEventListener("click", again);
    window.addEventListener("resize", resize);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("keyup", onKeyUp);
    document.addEventListener("visibilitychange", onVisibility);
    try {
      if (tg && tg.disableVerticalSwipes) tg.disableVerticalSwipes();
    } catch (_) {}

    resize();
    updateHud();
    rafId = requestAnimationFrame(frame);
    requestAnimationFrame(resize);
    if (opts.onReady) opts.onReady();

    return { destroy, engine };
  }

  const api = { createEngine, mount };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.ShopVPNPinball = api;
})();
