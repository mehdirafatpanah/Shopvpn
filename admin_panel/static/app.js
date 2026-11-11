/*‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍*/
'use strict';

/* ============================================================ state === */
let ME = null;
let CURRENT_TAB = 'dashboard';
let SUPPORT_POLL_TIMER = null;
function stopSupportPoll() { if (SUPPORT_POLL_TIMER) { clearInterval(SUPPORT_POLL_TIMER); SUPPORT_POLL_TIMER = null; } }

/* ============================================================= theme === */
// هر آیتم یک تم کامل رو توصیف می‌کنه: نه فقط رنگ، بلکه چیدمان/کارت/نمودار.
// وقتی تم جدیدی پیاده بشه، فقط کافیه یک آیتم اینجا با ready:true اضافه بشه
// و بلوک CSS مربوطه با سلکتور html[data-theme="..."] در style.css اضافه بشه.
const THEMES = [
  {
    id: 'enterprise',
    name: 'ShopVPN Enterprise',
    desc: 'رسمی، منسجم و مناسب پنل مدیریتی حرفه‌ای',
    ready: true,
    supportsMode: true,
    defaultMode: 'light',
    swatch: ['#0F1B33', '#4F63D8', '#F7F9FC'],
  },
  {
    id: 'bento',
    name: 'Bento Grid',
    desc: 'کارت‌های نامنظم چندسایز مثل ویجت‌های اپل',
    ready: true,
    supportsMode: true,
    defaultMode: 'light',
    swatch: ['#0A84FF', '#30D158', '#FF9F0A'],
  },
  {
    id: 'brutalist',
    name: 'Neo-brutalist',
    desc: 'کادر ضخیم، بی‌سایه، تایپوگرافی بولد',
    ready: true,
    supportsMode: true,
    defaultMode: 'light',
    swatch: ['#FFE600', '#000000', '#FFFFFF'],
  },
  {
    id: 'cyberpunk',
    name: 'Cyberpunk',
    desc: 'ترمینال نئون، اسکن‌لاین، منوی بالای صفحه',
    ready: true,
    supportsMode: false,
    defaultMode: 'dark',
    swatch: ['#FF2A6D', '#00FFF0', '#05050A'],
  },
  {
    id: 'streetops',
    name: 'Street Ops',
    desc: 'HUD الهام‌گرفته از بازی‌های شهر باز — نوار سلامت، ستاره‌ی تحت‌تعقیب، منوی پایین صفحه',
    ready: true,
    supportsMode: false,
    defaultMode: 'dark',
    swatch: ['#FFB020', '#22D3EE', '#14161C'],
  },
  {
    id: 'android',
    name: 'Android متریال',
    desc: 'متریال دیزاین ۳ گوگل — درست مثل اپ‌های واقعی اندروید: کشوی ناوبری، نوار بالای اپ، FAB، کارت‌های برجسته',
    ready: true,
    supportsMode: true,
    defaultMode: 'light',
    swatch: ['#6750A4', '#EADDFF', '#1D1B20'],
  },
];
const DEFAULT_THEME = 'enterprise';

function loadTheme() {
  const fallbackMode = (THEMES.find(t => t.id === DEFAULT_THEME) || {}).defaultMode || 'dark';
  try {
    const t = JSON.parse(localStorage.getItem('sv-theme')) || {};
    return { theme: t.theme || DEFAULT_THEME, mode: t.mode || fallbackMode };
  } catch (e) { return { theme: DEFAULT_THEME, mode: fallbackMode }; }
}
// هر تم حالت روشن/تیره‌ی دلخواه خودش رو جدا به خاطر می‌سپاره — با defaultMode
// خود تم به عنوان مقدار اول، پیش از اینکه کاربر چیزی انتخاب کرده باشه.
function getModeForTheme(themeId) {
  try {
    const map = JSON.parse(localStorage.getItem('sv-theme-modes')) || {};
    if (map[themeId]) return map[themeId];
  } catch (e) {}
  const meta = THEMES.find(t => t.id === themeId);
  return (meta && meta.defaultMode) || 'dark';
}
function rememberModeForTheme(themeId, mode) {
  let map = {};
  try { map = JSON.parse(localStorage.getItem('sv-theme-modes')) || {}; } catch (e) {}
  map[themeId] = mode;
  try { localStorage.setItem('sv-theme-modes', JSON.stringify(map)); } catch (e) {}
}
function applyThemeChoice(themeId, mode) {
  const meta = THEMES.find(t => t.id === themeId) || THEMES[0];
  const finalTheme = meta.ready ? meta.id : DEFAULT_THEME;
  const finalMode = mode || getModeForTheme(finalTheme);
  document.documentElement.setAttribute('data-theme', finalTheme);
  document.documentElement.setAttribute('data-mode', finalMode);
  localStorage.setItem('sv-theme', JSON.stringify({ theme: finalTheme, mode: finalMode }));
  rememberModeForTheme(finalTheme, finalMode);
  if (typeof syncTopbarModeToggle === 'function') syncTopbarModeToggle();
}
// دکمه‌ی تعویض حالت روشن/تیره در نوار بالا؛ فقط برای تم‌هایی که ازش
// پشتیبانی می‌کنن نمایش داده می‌شه (بقیه‌ی تم‌ها فقط یک حالت تیره دارن).
function syncTopbarModeToggle() {
  const btn = document.getElementById('topbar-mode-toggle');
  if (!btn) return;
  const cur = loadTheme();
  const meta = THEMES.find(t => t.id === cur.theme);
  if (!meta || !meta.supportsMode) { btn.style.display = 'none'; return; }
  btn.style.display = '';
  const isDark = cur.mode === 'dark';
  btn.textContent = isDark ? '☀️' : '🌙';
  btn.title = isDark ? 'رفتن به حالت روشن' : 'رفتن به حالت تیره';
}
// نگه‌داری سازگاری با کدهای قدیمی‌تر که فقط applyTheme(mode) صدا می‌زنن
function applyTheme(mode) { applyThemeChoice(loadTheme().theme, mode); }
{ const t0 = loadTheme(); applyThemeChoice(t0.theme, t0.mode); }

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* ============================================================= icons === */
const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="7" rx="1.5"></rect><rect x="14" y="3" width="7" height="7" rx="1.5"></rect><rect x="14" y="14" width="7" height="7" rx="1.5"></rect><rect x="3" y="14" width="7" height="7" rx="1.5"></rect>',
  orders: '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path>',
  topups: '<rect x="1" y="4" width="22" height="16" rx="2.5"></rect><line x1="1" y1="10" x2="23" y2="10"></line>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path>',
  catalog: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line>',
  discounts: '<path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82Z"></path><circle cx="7" cy="7" r="1.4"></circle>',
  tickets: '<path d="M21 11.5a8.38 8.38 0 0 1-4.5 7.4 8.5 8.5 0 0 1-7.6-.1L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 8-8.5h.5a8.48 8.48 0 0 1 8 8v.5Z"></path>',
  broadcast: '<path d="m3 11 18-5v12L3 14v-3z"></path><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"></path>',
  support: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>',
  resellers: '<rect x="2" y="7" width="20" height="14" rx="2.5"></rect><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path>',
  panels: '<rect x="2" y="3" width="20" height="7" rx="2"></rect><rect x="2" y="14" width="20" height="7" rx="2"></rect><line x1="6" y1="6.5" x2="6.01" y2="6.5"></line><line x1="6" y1="17.5" x2="6.01" y2="17.5"></line>',
  settings: '<circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"></path>',
  logs: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="8" y1="13" x2="16" y2="13"></line><line x1="8" y1="17" x2="16" y2="17"></line>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"></path>',
  system: '<ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>',
  webadmins: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"></path>',
  account: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line>',
  revenue: '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline>',
  check: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>',
  empty: '<path d="M22 12h-6l-2 3h-4l-2-3H2"></path><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"></path>',
  buttons: '<rect x="3" y="4" width="7" height="7" rx="2"></rect><rect x="14" y="4" width="7" height="7" rx="2"></rect><rect x="3" y="15" width="7" height="7" rx="2"></rect><rect x="14" y="15" width="7" height="7" rx="2"></rect>',
  bottexts: '<line x1="4" y1="6" x2="20" y2="6"></line><line x1="4" y1="12" x2="20" y2="12"></line><line x1="4" y1="18" x2="14" y2="18"></line>',
  banners: '<rect x="3" y="3" width="18" height="18" rx="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline>',
  globe: '<circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>',
  terminal: '<polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line>',
  layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline>',
  sliders: '<line x1="4" y1="21" x2="4" y2="14"></line><line x1="4" y1="10" x2="4" y2="3"></line><line x1="12" y1="21" x2="12" y2="12"></line><line x1="12" y1="8" x2="12" y2="3"></line><line x1="20" y1="21" x2="20" y2="16"></line><line x1="20" y1="12" x2="20" y2="3"></line><line x1="1" y1="14" x2="7" y2="14"></line><line x1="9" y1="8" x2="15" y2="8"></line><line x1="17" y1="16" x2="23" y2="16"></line>',
  send: '<line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>',
  search: '<circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>',
};
const svg = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ''}</svg>`;
const fmt = n => (n === null || n === undefined) ? '—' : Number(n).toLocaleString('fa-IR');
const fmtDate = iso => {
  if (!iso) return '—';
  const d = new Date(iso.replace(' ', 'T') + (iso.includes('Z') ? '' : 'Z'));
  if (isNaN(d)) return '—';
  const o = { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false };
  return d.toLocaleString('fa-IR', o).replace(/[,،]/g, '').replace(/\s+/g, ' ');
};
// برای تاریخ‌های خالص بدون ساعت (مثل start_date/end_date بازه‌ی آمار که به
// شکل 'YYYY-MM-DD' میلادی از سرور میاد) — به تاریخ شمسی تبدیل می‌کنه.
const fmtDateOnly = iso => {
  if (!iso) return '—';
  try {
    return new Date(iso + 'T00:00:00Z').toLocaleDateString('fa-IR', { timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit' });
  } catch (e) { return iso; }
};
const esc = s => (s ?? '').toString().replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* ==================================================== micro-animation === */
// شمارش انیمیشنی اعداد هنگام بارگذاری کارت‌ها
function animateCount(el, target, duration = 900) {
  if (!el) return;
  const start = 0;
  const t0 = performance.now();
  function tick(now) {
    const p = Math.min((now - t0) / duration, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(Math.round(start + (target - start) * eased));
    if (p < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}
// پر شدن حلقه‌های سیگنال بعد از mount (برای انیمیشن conic-gradient)
function activateRings(root) {
  requestAnimationFrame(() => {
    setTimeout(() => {
      $$('.ring[data-pct], .res-ring[data-pct]', root).forEach(r => { r.style.setProperty('--pct', r.dataset.pct); });
    }, 60);
  });
}
// رشد میله‌های نمودار بعد از mount
function activateBars(root) {
  requestAnimationFrame(() => {
    setTimeout(() => {
      $$('.spark i[data-h]', root).forEach(b => { b.style.height = b.dataset.h + '%'; });
    }, 60);
  });
}
// پر شدن نوار‌های افقی (تفکیک درآمد / پرفروش‌ترین‌ها)
function activateBarFills(root) {
  requestAnimationFrame(() => {
    setTimeout(() => {
      $$('.bar-fill[data-w]', root).forEach(b => { b.style.width = b.dataset.w + '%'; });
    }, 60);
  });
}
// انیمیشن گیج SVG (سلامت سیستم)
function activateGauge(root, pct) {
  const ring = $('#gaugeRing', root);
  if (!ring) return;
  const c = 2 * Math.PI * 64;
  ring.style.strokeDasharray = c;
  ring.style.strokeDashoffset = c;
  requestAnimationFrame(() => {
    setTimeout(() => {
      ring.style.transition = 'stroke-dashoffset 1.3s cubic-bezier(.16,1,.3,1)';
      ring.style.strokeDashoffset = c - Math.max(0, Math.min(100, pct)) / 100 * c;
    }, 60);
  });
}
// رسم رادار عملکرد از مقادیر ۰..۱
function drawRadar(root, axes, values, color = '#8B5CF6') {
  const svgEl = $('#radarChart', root);
  if (!svgEl) return;
  const cx = 110, cy = 95, r = 62, n = axes.length;
  const pt = (i, scale) => {
    const ang = -Math.PI / 2 + i * (Math.PI * 2 / n);
    return [cx + Math.cos(ang) * r * scale, cy + Math.sin(ang) * r * scale];
  };
  let out = '';
  [0.33, 0.66, 1].forEach(scale => {
    out += `<polygon points="${axes.map((_, i) => pt(i, scale).join(',')).join(' ')}" fill="none" stroke="var(--border)" stroke-width="1"/>`;
  });
  axes.forEach((label, i) => {
    const [x, y] = pt(i, 1.18), [x2, y2] = pt(i, 1);
    out += `<line x1="${cx}" y1="${cy}" x2="${x2}" y2="${y2}" stroke="var(--border)" stroke-width="1"/>`;
    out += `<text x="${x}" y="${y}" font-size="9.5" fill="var(--text-muted)" text-anchor="middle" font-family="Vazirmatn">${esc(label)}</text>`;
  });
  const vp = axes.map((_, i) => pt(i, values[i]).join(',')).join(' ');
  out += `<polygon points="${vp}" fill="${color}33" stroke="${color}" stroke-width="1.6"/>`;
  axes.forEach((_, i) => { const [x, y] = pt(i, values[i]); out += `<circle cx="${x}" cy="${y}" r="2.6" fill="${color}"/>`; });
  svgEl.innerHTML = out;
}
// بوم امبیانت شبکه‌ی سیگنال در کارت خوش‌آمدگویی (هاب اتصال VPN)
function drawHeroNet(canvas) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth || 150, h = canvas.clientHeight || 150;
  canvas.width = w * dpr; canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const colors = ['#22D3EE', '#EC4899', '#8B5CF6'];
  const N = 6;
  const nodes = Array.from({ length: N }, (_, i) => ({
    ang: (i / N) * Math.PI * 2, radius: 0.62 + (i % 2) * 0.16, speed: 0.15 + Math.random() * 0.08,
  }));
  const packets = nodes.map(() => ({ t: Math.random(), speed: 0.006 + Math.random() * 0.006 }));
  let t = 0;
  const cx = w / 2, cy = h / 2;
  function pos(n) { const a = n.ang + t * n.speed * 0.2; return [cx + Math.cos(a) * w * 0.36 * n.radius, cy + Math.sin(a) * h * 0.36 * n.radius]; }
  function frame() {
    if (!canvas.isConnected) return;
    t += 0.016;
    ctx.clearRect(0, 0, w, h);
    nodes.forEach((n, i) => {
      const [x, y] = pos(n);
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y);
      ctx.strokeStyle = 'rgba(139,92,246,0.18)'; ctx.lineWidth = 1; ctx.stroke();
      const p = packets[i]; p.t += p.speed; if (p.t > 1) p.t = 0;
      const px = cx + (x - cx) * p.t, py = cy + (y - cy) * p.t;
      ctx.beginPath(); ctx.arc(px, py, 2.2, 0, Math.PI * 2);
      ctx.fillStyle = colors[i % 3]; ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 8; ctx.fill(); ctx.shadowBlur = 0;
      ctx.beginPath(); ctx.arc(x, y, 3.2, 0, Math.PI * 2); ctx.fillStyle = 'rgba(245,242,255,0.75)'; ctx.fill();
    });
    const pulse = (Math.sin(t * 1.6) + 1) / 2;
    const grad = ctx.createRadialGradient(cx, cy, 2, cx, cy, 26 + pulse * 8);
    grad.addColorStop(0, 'rgba(236,72,153,0.9)'); grad.addColorStop(1, 'rgba(139,92,246,0)');
    ctx.beginPath(); ctx.arc(cx, cy, 14 + pulse * 6, 0, Math.PI * 2); ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath(); ctx.arc(cx, cy, 6, 0, Math.PI * 2); ctx.fillStyle = '#F5F2FF'; ctx.fill();
    requestAnimationFrame(frame);
  }
  frame();
}

/* ============================================================== api === */
async function api(path, opts = {}) {
  const res = await fetch('/api' + path, {
    method: opts.method || 'GET',
    credentials: 'include',
    headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const isAuthEndpoint = path === '/login' || path === '/setup';
  if (res.status === 401 && !isAuthEndpoint) { showLogin(); throw new Error('unauthorized'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { const err = new Error(formatApiError(data.detail)); err.status = res.status; throw err; }
  return data;
}
function formatApiError(detail) {
  let message;
  if (!detail) message = 'Unknown error';
  else if (typeof detail === 'string') message = detail;
  else if (Array.isArray(detail)) message = detail.map(d => (d && (d.msg || d.detail)) || JSON.stringify(d)).join(', ') || 'Unknown error';
  else message = typeof detail === 'object' ? JSON.stringify(detail) : String(detail);
  return window.ShopVPNTranslate ? window.ShopVPNTranslate(message) : message;
}
const apiGet = p => api(p);
const apiPost = (p, body) => api(p, { method: 'POST', body: body || {} });
const apiPut = (p, body) => api(p, { method: 'PUT', body: body || {} });
const apiDelete = p => api(p, { method: 'DELETE' });

async function apiMultipart(path, formData) {
  const res = await fetch('/api' + path, {
    method: 'POST',
    credentials: 'include',
    body: formData,
  });
  const isAuthEndpoint = path === '/login' || path === '/setup';
  if (res.status === 401 && !isAuthEndpoint) { showLogin(); throw new Error('unauthorized'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || (res.status === 413 ? 'حجم فایل از سقف مجاز وب‌سرور (nginx client_max_body_size) بیشتر است.' : `خطای سرور (${res.status})`);
    const err = new Error(formatApiError(detail)); err.status = res.status; throw err;
  }
  return data;
}

/* ============================================================ toast === */
function toast(msg, isError = false) {
  const root = $('#toast-root');
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' error' : '');
  el.textContent = msg;
  root.appendChild(el);
  setTimeout(() => el.remove(), 3800);
}
function handleErr(e) { if (e.message !== 'unauthorized') toast(e.message, true); }

/* ==================================================== receipt viewer === */
function showReceiptModal(kind, id) {
  const paths = { order: `orders/${id}`, topup: `topups/${id}`, 'reseller-request': `reseller-requests/${id}` };
  const url = `/api/${paths[kind] || `orders/${id}`}/receipt`;
  openModal('رسید پرداخت', `
    <div class="receipt-view" style="text-align:center">
      <img src="${url}" alt="رسید پرداخت" style="max-width:100%;max-height:70vh;border-radius:10px" />
      <div style="margin-top:12px">
        <a href="${url}" target="_blank" rel="noopener" class="btn btn-sm">باز کردن در تب جدید</a>
      </div>
    </div>
  `, body => {
    const img = body.querySelector('img');
    img.addEventListener('error', () => {
      body.innerHTML = `
        <div class="empty-state">${svg('empty')}<div>نمایش پیش‌نمایش ممکن نشد (شاید فایل رسید سند/PDF باشد).</div></div>
        <div style="text-align:center;margin-top:12px"><a href="${url}" target="_blank" rel="noopener" class="btn btn-sm">باز کردن رسید</a></div>
      `;
    });
  });
}

/* ============================================================ modal === */
function openModal(title, bodyHtml, onMount, opts = {}) {
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.innerHTML = `<div class="modal${opts.wide ? ' modal-lg' : ''}"><h3>${title}</h3><div class="modal-body">${bodyHtml}</div></div>`;
  backdrop.addEventListener('click', e => { if (e.target === backdrop) backdrop.remove(); });
  document.body.appendChild(backdrop);
  if (onMount) onMount(backdrop.querySelector('.modal-body'), () => backdrop.remove());
  return backdrop;
}

/* ============================================================== nav === */
// ساختار منو: «گروه ← صفحه ← زیرمنو».
// هر زیرمنو مستقیماً به یک تب/بخش داخل همان صفحه می‌رود (وضعیت سفارش، تب تنظیمات،
// بخش‌های تنظیمات فروش و ...). ترتیب گروه‌ها از «روزمره» به «پیکربندی» است.
const _ORDER_SUBS = [['pending', 'در انتظار تایید'], ['approved', 'تایید شده'], ['rejected', 'رد شده']];
const NAV_GROUPS = [
  { id: 'overview', label: 'نمای کلی', items: [
    { key: 'dashboard', label: 'داشبورد', icon: 'dashboard', role: 'any' },
    { key: 'analytics', label: 'آمار پیشرفته', icon: 'revenue', role: 'any' },
    { key: 'reseller-self', label: 'نمایندگی من', icon: 'resellers', role: 'reseller-self' },
  ] },
  { id: 'sales', label: 'فروش و مالی', items: [
    { key: 'orders', label: 'سفارش‌ها', icon: 'orders', role: 'any', subs: _ORDER_SUBS },
    { key: 'topups', label: 'شارژ کیف پول', icon: 'topups', role: 'any', subs: _ORDER_SUBS },
    { key: 'discounts', label: 'کدهای تخفیف', icon: 'discounts', role: 'discounts' },
  ] },
  { id: 'customers', label: 'مشتریان و پشتیبانی', items: [
    { key: 'users', label: 'کاربران', icon: 'users', role: 'any' },
    { key: 'subscriptions', label: 'اشتراک‌های فعال', icon: 'check', role: 'any' },
    { key: 'user-groups', label: 'گروه‌بندی کاربران', icon: 'layers', role: 'any' },
    { key: 'tickets', label: 'تیکت‌ها', icon: 'tickets', role: 'any',
      subs: [['all', 'همه'], ['open', 'باز'], ['answered', 'پاسخ‌داده‌شده'], ['closed', 'بسته']] },
    { key: 'support', label: 'چت زنده', icon: 'support', role: 'any' },
    { key: 'broadcast', label: 'پیام همگانی', icon: 'broadcast', role: 'broadcast' },
  ] },
  { id: 'marketing', label: 'محصولات و بازاریابی', items: [
    { key: 'catalog', label: 'محصولات و بانک کانفیگ', icon: 'catalog', role: 'catalog',
      subs: [['products', 'محصولات'], ['categories', 'دسته‌بندی‌ها']] },
    { key: 'banners', label: 'بنرها', icon: 'banners', role: 'settings' },
  ] },
  { id: 'partners', label: 'نمایندگی‌ها', items: [
    { key: 'resellers', label: 'مدیریت نمایندگی‌ها', icon: 'resellers', role: 'resellers',
      subs: [['bots', 'نماینده‌های بات'], ['credit', 'نمایندگی اعتباری'], ['commission', 'نمایندگی کمیسیونی'], ['requests', 'درخواست‌ها']] },
    { key: 'reseller_tiers', label: 'سطوح نمایندگی', icon: 'layers', role: 'resellers' },
  ] },
  { id: 'infra', label: 'شبکه و زیرساخت', items: [
    { key: 'panels', label: 'پنل‌های VPN', icon: 'panels', role: 'panels' },
    { key: 'ssh', label: 'نودها و سهمیه SSH', icon: 'terminal', role: 'panels' },
  ] },
  { id: 'botcontent', label: 'محتوای ربات', items: [
    { key: 'buttons', label: 'دکمه‌های ربات', icon: 'buttons', role: 'settings' },
    { key: 'bottexts', label: 'متن‌های ربات', icon: 'bottexts', role: 'settings' },
    { key: 'languages', label: 'زبان‌ها', icon: 'globe', role: 'settings' },
  ] },
  { id: 'botconfig', label: 'تنظیمات', items: [
    { key: 'settings', label: 'تنظیمات و برندینگ', icon: 'settings', role: 'settings',
      subs: [['content', 'محتوا و متن‌ها'], ['payment', 'پرداخت و مالی'], ['sales', 'فروش و سرویس‌ها'], ['growth', 'رشد و تعامل'], ['sub', 'اشتراک اختصاصی'], ['ai', 'هوش مصنوعی'], ['system', 'سیستم و پایش'], ['mobile_app', 'اپ موبایل']] },
    { key: 'salessettings', label: 'تنظیمات فروش', icon: 'sliders', role: 'settings',
      subs: [['referral', 'رفرال و جذب'], ['renewal', 'تمدید و نگهداشت'], ['access', 'تست، عضویت و موجودی']] },
    { key: 'subscription-page', label: 'تنظیمات صفحه اشتراک', icon: 'link', role: 'settings' },
  ] },
  { id: 'admin', label: 'مدیریت و امنیت', items: [
    { key: 'database', label: 'مدیریت دیتابیس', icon: 'database', role: 'database' },
    { key: 'webadmins', label: 'کاربران پنل', icon: 'webadmins', role: 'owner' },
    { key: 'tgadmins', label: 'ادمین‌های ربات', icon: 'send', role: 'owner' },
    { key: 'logs', label: 'لاگ فعالیت ادمین‌ها', icon: 'logs', role: 'system' },
    { key: 'system', label: 'سیستم و نگهداری', icon: 'system', role: 'system',
      subs: [['jobs', 'وضعیت اجراها و موجودی'], ['backup', 'بکاپ و بازیابی'], ['danger', 'نگهداری و منطقه خطر']] },
  ] },
  { id: 'account', label: 'حساب کاربری', items: [
    { key: 'account', label: 'حساب من', icon: 'account', role: 'any',
      subs: [['appearance', 'ظاهر پنل'], ['security', 'امنیت حساب']] },
  ] },
];
// لیست تخت (سازگار با کدهای قبلی که NAV.find(...) می‌زنند)
const NAV = NAV_GROUPS.flatMap(g => g.items.map(i => ({ ...i, section: g.label, group: g.id, groupLabel: g.label })));

/* وضعیت زیرمنو هر صفحه: متغیرهای قدیمیِ هر صفحه را می‌خواند/می‌نویسد تا تب‌های
   داخل صفحه و زیرمنوی کناری همیشه یکی باشند. */
const SECTION_STATE = {};
const NAV_SUB_STATE = {
  orders: { get: () => ordersStatus, set: v => { ordersStatus = v; } },
  topups: { get: () => topupsStatus, set: v => { topupsStatus = v; } },
  tickets: { get: () => ticketsStatusFilter || 'all', set: v => { ticketsStatusFilter = v === 'all' ? '' : v; } },
  catalog: { get: () => catalogTab, set: v => { catalogTab = v; } },
  resellers: { get: () => resellersSubTab, set: v => { resellersSubTab = v; } },
  settings: { get: () => settingsActiveTab, set: v => { settingsActiveTab = v; } },
};
function navSubGet(tab) {
  if (NAV_SUB_STATE[tab]) return NAV_SUB_STATE[tab].get();
  const item = NAV.find(n => n.key === tab);
  return SECTION_STATE[tab] || (item?.subs ? item.subs[0][0] : null);
}
function navSubSet(tab, sub) {
  if (NAV_SUB_STATE[tab]) NAV_SUB_STATE[tab].set(sub);
  else SECTION_STATE[tab] = sub;
}

/* بخش‌بندی صفحه‌های «کارت روی کارت» (تنظیمات فروش، سیستم، حساب): کارت‌ها بر اساس
   عنوان‌شان در چند بخش تب‌دار دسته‌بندی می‌شوند و فقط بخش فعال دیده می‌شود. */
const SECTION_PAGES = {
  salessettings: [
    { key: 'referral', label: '🔗 رفرال و جذب', match: ['رفرال', 'گردونه', 'زیرمجموعه‌گیری فیک'] },
    { key: 'renewal', label: '⏳ تمدید و نگهداشت', match: ['یادآوری تمدید', 'پیش‌بینی ریزش', 'یادآوری بر اساس حجم', 'هشدار اتصال', 'تخفیف تمدید'] },
    { key: 'access', label: '🧪 تست، عضویت و موجودی', match: ['کانفیگ تست', 'عضویت اجباری', 'هشدار موجودی'] },
  ],
  system: [
    { key: 'jobs', label: '📊 وضعیت اجراها و موجودی', match: ['یادآوری‌های تمدید', 'وضعیت لحظه‌ای موجودی'] },
    { key: 'backup', label: '💾 بکاپ و بازیابی', match: ['بکاپ دیتابیس'] },
    { key: 'danger', label: '🛠 نگهداری و منطقه خطر', match: ['بازگشت به حالت کارخانه', 'فایل‌های دیتابیس یتیم'] },
  ],
  account: [
    { key: 'appearance', label: '🎨 ظاهر پنل', match: ['تم پنل'] },
    { key: 'security', label: '🔐 امنیت حساب', match: ['تغییر پسورد'] },
  ],
};
function hasPerm(perm) {
  return ME.role === 'owner' || (ME.permissions || []).includes(perm);
}
function canSee(navRole) {
  if (navRole === 'database') return ME?.role === 'owner' && !ME?.tenant;
  const rp = ME?.reseller_profile;
  if (navRole === 'reseller-self') return !!(ME?.tenant && rp);
  if (ME?.tenant && rp) {
    const tier = String(rp.tier_code || '').toLowerCase();
    if (!['gold','vip'].includes(tier)) {
      if (navRole === 'reseller-self') return true;
      if (navRole === 'resellers' || navRole === 'reseller_tiers') return false;
      return navRole === 'any' ? true : hasPerm(navRole);
    }
    if (navRole === 'analytics') return tier === 'vip';
    if (navRole === 'discounts' || navRole === 'banners') return tier === 'vip';
    if (navRole === 'catalog') return true;
    // سطح ۲ فقط ابزارهای عملیاتی خودش را می‌بیند؛ کاتالوگ/پنل/تنظیمات
    // مدیریتی عمداً از منو حذف شده‌اند و backend هم همان‌ها را 403 می‌کند.
    if (navRole === 'any') {
      if (['dashboard', 'account'].includes(CURRENT_TAB)) return true;
      if (['orders', 'users', 'tickets', 'support', 'broadcast'].includes(CURRENT_TAB)) return !!(rp.has_live_bot || rp.inline_link_enabled);
      return true;
    }
    if (['orders', 'users', 'tickets', 'support', 'broadcast'].includes(navRole)) return !!(rp.has_live_bot || rp.inline_link_enabled);
    return false;
  }
  if (navRole === 'resellers' && ME.tenant) return false;
  if (navRole === 'any') return true;
  if (navRole === 'owner') return ME.role === 'owner';
  return hasPerm(navRole);
}
const ROLE_LABEL = { owner: 'مالک', admin: 'مدیر کامل', mid: 'ادمین میانی', support: 'پشتیبان' };

/* ==================================================== live notifications === */
let NOTIF_COUNTS = {};

function applyResellerTierChrome() {
  const p = ME?.reseller_profile;
  const root = document.documentElement;
  root.classList.remove('tenant-reseller', 'tier-gold', 'tier-vip');
  if (!ME?.tenant || !p) return;
  root.classList.add('tenant-reseller', String(p.tier_code || 'gold').toLowerCase() === 'vip' ? 'tier-vip' : 'tier-gold');
  const title = $('#page-title');
  if (title && CURRENT_TAB === 'dashboard') title.textContent = `${p.tier_icon || '🥇'} پنل ${p.tier_title || 'نمایندگی'}`;
  const brand = $('.sidebar-brand .brand-text');
  if (brand) brand.innerHTML = `<strong>${esc(p.tier_title || 'نمایندگی')}</strong><span>پنل اختصاصی ShopVPN</span>`;
}

/* ---- وضعیت منو: گروه‌های جمع‌شده + عبارت جستجو ---- */
let NAV_COLLAPSED = new Set();
try {
  const _savedCollapsed = localStorage.getItem('admin_nav_collapsed');
  NAV_COLLAPSED = _savedCollapsed === null
    ? new Set(NAV_GROUPS.map(g => g.id).filter(id => id !== 'overview'))
    : new Set(JSON.parse(_savedCollapsed || '[]'));
} catch (e) {}
let NAV_QUERY = '';
function saveNavCollapsed() {
  try { localStorage.setItem('admin_nav_collapsed', JSON.stringify([...NAV_COLLAPSED])); } catch (e) {}
}
// یکسان‌سازی نوشتار فارسی/عربی برای جستجو (ی/ي، ک/ك، نیم‌فاصله)
const navNorm = s => String(s || '').toLowerCase().replace(/ي/g, 'ی').replace(/ك/g, 'ک').replace(/‌/g, ' ').trim();

function navGroupOf(tab) { return NAV.find(n => n.key === tab)?.group || null; }

function renderNav() {
  const el = $('#nav-tunnel');
  if (!el) return;
  const CYCLE = ['nav-c1', 'nav-c2', 'nav-c3', 'nav-c4'];
  const q = navNorm(NAV_QUERY);
  const activeGroup = navGroupOf(CURRENT_TAB);
  let html = '';
  let i = 0;
  NAV_GROUPS.forEach(g => {
    let items = g.items.filter(n => canSee(n.role));
    if (!items.length) return;
    // در حالت جستجو: فقط صفحه‌هایی که خودشان یا یکی از زیرمنوهایشان مطابقت دارد
    let subFilter = null;
    if (q) {
      subFilter = {};
      items = items.filter(n => {
        const selfHit = navNorm(n.label).includes(q) || navNorm(g.label).includes(q);
        const subHits = (n.subs || []).filter(([, l]) => navNorm(l).includes(q)).map(s => s[0]);
        subFilter[n.key] = selfHit ? null : subHits;
        return selfHit || subHits.length;
      });
      if (!items.length) return;
    }
    const collapsed = !q && NAV_COLLAPSED.has(g.id) && g.id !== activeGroup;
    const groupCount = items.reduce((s, n) => s + (NOTIF_COUNTS[n.key] || 0), 0);
    html += `<div class="nav-section nav-group-head ${collapsed ? 'is-collapsed' : ''}" data-group="${g.id}" role="button" tabindex="0" aria-expanded="${collapsed ? 'false' : 'true'}">${g.label}${collapsed && groupCount ? `<b class="nav-group-badge">${groupCount > 99 ? '99+' : groupCount}</b>` : ''}</div>`;
    items.forEach(n => {
      const count = NOTIF_COUNTS[n.key] || 0;
      const isActive = n.key === CURRENT_TAB;
      const hasSubs = !!(n.subs && n.subs.length);
      html += `
    <div class="nav-item ${CYCLE[i++ % 4]} ${isActive ? 'active' : ''} ${hasSubs ? 'has-subs' : ''} ${collapsed ? 'nav-hidden' : ''}" data-tab="${n.key}" data-group="${g.id}">
      <span class="nav-icon">${svg(n.icon)}</span><span>${n.label}</span>${count ? `<span class="dot-count">${count > 99 ? '99+' : count}</span>` : ''}
    </div>`;
      // زیرمنو: فقط برای صفحه‌ی فعال (یا نتیجه‌ی جستجو) باز می‌شود
      if (hasSubs && !collapsed && (isActive || (q && subFilter[n.key] && subFilter[n.key].length))) {
        const cur = isActive ? navSubGet(n.key) : null;
        const subs = (q && subFilter[n.key]) ? n.subs.filter(s => subFilter[n.key].includes(s[0])) : n.subs;
        html += `<div class="nav-sublist" data-for="${n.key}">${subs.map(([k, l]) =>
          `<div class="nav-sub ${cur === k ? 'active' : ''}" data-tab="${n.key}" data-sub="${k}"><i></i><span>${l}</span></div>`).join('')}</div>`;
      }
    });
  });
  if (!html) html = `<div class="nav-empty">موردی پیدا نشد</div>`;
  el.innerHTML = html;
  $$('.nav-item', el).forEach(item => item.addEventListener('click', () => { goTo(item.dataset.tab); closeSidebar(); }));
  $$('.nav-sub', el).forEach(item => item.addEventListener('click', e => { e.stopPropagation(); goTo(item.dataset.tab, item.dataset.sub); closeSidebar(); }));
  $$('.nav-group-head', el).forEach(h => {
    const toggle = () => {
      const id = h.dataset.group;
      if (NAV_COLLAPSED.has(id)) NAV_COLLAPSED.delete(id); else NAV_COLLAPSED.add(id);
      saveNavCollapsed();
      renderNav();
    };
    h.addEventListener('click', toggle);
    h.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
  });
}

function updatePageHeading() {
  const n = NAV.find(x => x.key === CURRENT_TAB);
  const title = $('#page-title');
  if (title) title.textContent = n?.label || '';
  const crumb = $('#page-crumb');
  if (!crumb) return;
  if (!n) { crumb.innerHTML = ''; return; }
  let html = `<span>${n.groupLabel}</span>`;
  if (n.subs) {
    const cur = navSubGet(n.key);
    const lbl = n.subs.find(s => s[0] === cur)?.[1];
    if (lbl) html += `<i>›</i><span class="crumb-cur">${lbl}</span>`;
  }
  crumb.innerHTML = html;
}

function goTo(tab, sub) {
  stopSupportPoll();
  const sameTab = tab === CURRENT_TAB;
  CURRENT_TAB = tab;
  try { localStorage.setItem('admin_current_tab', tab); } catch (e) {}
  if (sub) navSubSet(tab, sub);
  // صفحه‌ی مقصد باید گروهش باز باشد
  const g = navGroupOf(tab);
  if (g && NAV_COLLAPSED.delete(g)) saveNavCollapsed();
  renderNav();
  { const act = $('#nav-tunnel .nav-item.active'); const tail = act?.nextElementSibling?.classList.contains('nav-sublist') ? act.nextElementSibling : act; tail?.scrollIntoView({ block: 'nearest' }); }
  updatePageHeading();
  // اگر همین صفحه باز است و تب/بخش داخلی دارد، بدون بارگذاری مجدد جابه‌جا شو
  if (sameTab && sub) {
    if (tab === 'settings' && $('#settings-tabs-nav', content())) { switchSettingsTab(sub, content()); return; }
    if (SECTION_PAGES[tab] && $('.section-nav', content())) { showSection(tab, sub); return; }
  }
  renderPage(tab);
}

/* ---- بخش‌های تب‌دار برای صفحه‌های کارتی ---- */
function enhanceSections() {
  const cfg = SECTION_PAGES[CURRENT_TAB];
  const root = content();
  if (!cfg || !root || root.querySelector(':scope > .section-nav')) return;
  const cards = Array.from(root.children).filter(el => el.matches('.card') || el.querySelector('h3'));
  if (cards.length < 2) return;
  let last = cfg[0].key;
  cards.forEach(el => {
    const h = el.querySelector('h3')?.textContent || '';
    const hit = cfg.find(s => s.match.some(m => h.includes(m)));
    el.dataset.sec = hit ? hit.key : last;
    last = el.dataset.sec;
  });
  const present = cfg.filter(s => cards.some(c => c.dataset.sec === s.key));
  if (present.length < 2) { cards.forEach(c => delete c.dataset.sec); return; }
  const cur = present.find(s => s.key === SECTION_STATE[CURRENT_TAB]) ? SECTION_STATE[CURRENT_TAB] : present[0].key;
  SECTION_STATE[CURRENT_TAB] = cur;
  const nav = document.createElement('div');
  nav.className = 'tabs section-nav';
  nav.setAttribute('role', 'tablist');
  nav.innerHTML = present.map(s => {
    const n = cards.filter(c => c.dataset.sec === s.key).length;
    return `<button type="button" class="tab-btn ${s.key === cur ? 'active' : ''}" data-sec="${s.key}" role="tab">${s.label}<small class="tab-count">${n}</small></button>`;
  }).join('');
  nav.addEventListener('click', e => {
    const b = e.target.closest('[data-sec]');
    if (b) showSection(CURRENT_TAB, b.dataset.sec);
  });
  root.insertBefore(nav, root.firstChild);
  showSection(CURRENT_TAB, cur);
}

function showSection(tab, key) {
  const root = content();
  SECTION_STATE[tab] = key;
  $$(':scope > [data-sec]', root).forEach(el => { el.style.display = el.dataset.sec === key ? '' : 'none'; });
  $$('.section-nav [data-sec]', root).forEach(b => b.classList.toggle('active', b.dataset.sec === key));
  updatePageHeading();
  renderNav();
}

// صفحه‌ها بعد از هر رندر (حتی رندرهای مجدد پس از ذخیره) دوباره بخش‌بندی می‌شوند
new MutationObserver(() => { if (SECTION_PAGES[CURRENT_TAB]) enhanceSections(); })
  .observe(document.getElementById('content'), { childList: true });

// تب‌های داخل صفحه (وضعیت سفارش، تب‌های تنظیمات و ...) را با زیرمنوی کناری هماهنگ نگه می‌دارد
document.getElementById('content').addEventListener('click', e => {
  if (e.target.closest('.tab-btn, .bn-seg-btn, .bru-seg-btn')) setTimeout(() => { renderNav(); updatePageHeading(); }, 80);
});

/* ---- جستجوی منو (کلید / یا Ctrl+K) ---- */
(function initNavSearch() {
  const input = document.getElementById('nav-search-input');
  if (!input) return;
  input.addEventListener('input', () => { NAV_QUERY = input.value; renderNav(); });
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') { input.value = ''; NAV_QUERY = ''; renderNav(); input.blur(); }
    if (e.key === 'Enter') {
      const first = $('#nav-tunnel .nav-sub, #nav-tunnel .nav-item');
      if (first) { goTo(first.dataset.tab, first.dataset.sub); input.value = ''; NAV_QUERY = ''; renderNav(); closeSidebar(); }
    }
  });
  document.addEventListener('keydown', e => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '') || document.activeElement?.isContentEditable;
    if ((e.key === '/' && !typing) || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) {
      if ($('#app')?.hidden) return;
      e.preventDefault(); openSidebar(); input.focus(); input.select();
    }
  });
})();

/* ---- صدای هشدار برای موارد جدید (بدون فایل صوتی، سنتز با Web Audio) ---- */
let NOTIF_AUDIO_CTX = null;
function playNotifSound() {
  try {
    NOTIF_AUDIO_CTX = NOTIF_AUDIO_CTX || new (window.AudioContext || window.webkitAudioContext)();
    const ctx = NOTIF_AUDIO_CTX;
    const now = ctx.currentTime;
    [880, 1180].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0, now + i * 0.14);
      gain.gain.linearRampToValueAtTime(0.18, now + i * 0.14 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, now + i * 0.14 + 0.22);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now + i * 0.14);
      osc.stop(now + i * 0.14 + 0.24);
    });
  } catch (e) { /* مرورگر صدای وب را پشتیبانی نمی‌کند */ }
}

/* ---- بج‌های زنده‌ی منو: هر چند ثانیه شمارش pending را می‌گیرد و اگر رشد
   کرده بود صدا هم پخش می‌کند. این جدا از Push است و فقط وقتی تب باز باشد کار
   می‌کند؛ برای اعلان وقتی مرورگر بسته است به بخش Push پایین‌تر نگاه کن. ---- */
let NOTIF_POLL_STARTED = false;
function startNotificationPolling() {
  if (NOTIF_POLL_STARTED) return;
  NOTIF_POLL_STARTED = true;
  const poll = async () => {
    try {
      const summary = await apiGet('/notifications/summary');
      let grew = false;
      Object.keys(summary).forEach(key => { if (summary[key] > (NOTIF_COUNTS[key] || 0)) grew = true; });
      NOTIF_COUNTS = summary;
      renderNav();
      if (grew) playNotifSound();
    } catch (e) { /* silent */ }
  };
  poll();
  setInterval(poll, 15000);
}

document.addEventListener('click', e => {
  const btn = e.target.closest('[data-history]');
  if (!btn) return;
  const [recordType, recordId] = btn.dataset.history.split(':');
  showRecordHistory(recordType, recordId);
});

/* ============================================================= boot === */
function tenantParam() {
  return new URLSearchParams(location.search).get('b') || '';
}

async function boot() {
  if (location.pathname === '/setup') return boot_setup();
  try {
    ME = await apiGet('/me');
    if (ME.language) localStorage.setItem('sv-lang', ME.language);
    applyResellerTierChrome();
    showApp();
  } catch (e) {
    showLogin();
  }
}

async function boot_setup() {
  const b = tenantParam();
  const t = new URLSearchParams(location.search).get('t') || '';
  $('#login-screen').hidden = true;
  $('#app').hidden = true;
  $('#setup-screen').hidden = false;
  if (!b || !t) {
    $('#setup-subtitle').textContent = 'لینک ناقص است.';
    $('#setup-fields').hidden = true;
    return;
  }
  try {
    const info = await fetch(`/api/setup/info?b=${encodeURIComponent(b)}&t=${encodeURIComponent(t)}`).then(async r => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(formatApiError(data.detail));
      return data;
    });
    $('#setup-subtitle').textContent = info.bot_username
      ? `پنل نمایندگی @${info.bot_username} - یک یوزرنیم و پسورد انتخاب کن`
      : 'یک یوزرنیم و پسورد برای پنل وب خودت انتخاب کن';
  } catch (e) {
    $('#setup-subtitle').textContent = e.message;
    $('#setup-fields').hidden = true;
    return;
  }

  $('#setup-form').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = $('#setup-submit');
    const errBox = $('#setup-error');
    errBox.hidden = true;
    btn.disabled = true; btn.textContent = 'در حال ساخت حساب...';
    try {
      const res = await fetch('/api/setup', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          b, t,
          username: $('#setup-username').value.trim(),
          password: $('#setup-password').value,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(formatApiError(data.detail));
      ME = data;
      history.replaceState(null, '', `/?b=${encodeURIComponent(b)}`);
      $('#setup-screen').hidden = true;
      showApp();
    } catch (e) {
      errBox.textContent = e.message;
      errBox.hidden = false;
    } finally {
      btn.disabled = false; btn.textContent = 'ساخت حساب و ورود';
    }
  });
}

function showLogin() {
  $('#app').hidden = true;
  $('#login-screen').hidden = false;
}

function showApp() {
  $('#login-screen').hidden = true;
  $('#app').hidden = false;
  $('#me-username').textContent = ME.username;
  $('#me-role').textContent = ROLE_LABEL[ME.role] || ME.role;
  $('#me-avatar').textContent = ME.username.slice(0, 2).toUpperCase();
  tickClock();
  setInterval(tickClock, 1000);
  startNotificationPolling();
  const pushBtn = $('#push-toggle-btn');
  if (pushBtn) pushBtn.addEventListener('click', openPushSettingsModal);
  const modeBtn = $('#topbar-mode-toggle');
  if (modeBtn) modeBtn.addEventListener('click', () => {
    const cur = loadTheme();
    applyThemeChoice(cur.theme, cur.mode === 'dark' ? 'light' : 'dark');
  });
  syncTopbarModeToggle();
  initInstallApp();
  let saved = null;
  try { saved = localStorage.getItem('admin_current_tab'); } catch (e) {}
  const savedValid = saved && NAV.find(n => n.key === saved && canSee(n.role));
  // اپ اندروید (وب‌ویو) برای دیپ‌لینک به یک تب مشخص از ?tab=xxx استفاده می‌کند —
  // این همیشه روی مقدار ذخیره‌شده در localStorage اولویت دارد.
  let queryTab = null;
  try { queryTab = new URLSearchParams(location.search).get('tab'); } catch (e) {}
  const queryValid = queryTab && NAV.find(n => n.key === queryTab && canSee(n.role));
  let querySub = null;
  try { querySub = new URLSearchParams(location.search).get('sub'); } catch (e) {}
  const startTab = queryValid ? queryTab : (savedValid ? saved : 'dashboard');
  const startItem = NAV.find(n => n.key === startTab);
  goTo(startTab, queryValid && querySub && startItem?.subs?.some(s => s[0] === querySub) ? querySub : undefined);
}

/* ==================================================== web push (level 2) ===
   اعلان مرورگر واقعی که حتی وقتی مرورگر کاملاً بسته است هم می‌رسد؛ از طریق
   Service Worker + سرویس Push خودِ مرورگر. برخلاف بج‌های بالا، این یکی نیاز
   به یک‌بار «فعال‌سازی» دستی توسط هر ادمین (روی هر دستگاه) دارد چون مرورگرها
   بدون اجازه‌ی صریح کاربر Push را قبول نمی‌کنند. */
const PUSH_SUPPORTED = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  const arr = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) arr[i] = rawData.charCodeAt(i);
  return arr;
}

async function pushStatus() {
  if (!PUSH_SUPPORTED) return 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    const sub = reg ? await reg.pushManager.getSubscription() : null;
    if (!sub) return 'not-subscribed';
    // subscription محلی مرورگر کافی نیست؛ باید مطمئن شویم سرور هم واقعاً آن را ذخیره کرده
    try {
      const { registered } = await apiGet(`/push/status?endpoint=${encodeURIComponent(sub.endpoint)}`);
      return registered ? 'subscribed' : 'not-subscribed';
    } catch (e) {
      return 'not-subscribed';
    }
  } catch (e) {
    return 'not-subscribed';
  }
}

async function enablePushNotifications() {
  if (!PUSH_SUPPORTED) { toast('این مرورگر از اعلان Push پشتیبانی نمی‌کند.', true); return false; }
  try {
    const { publicKey, enabled } = await apiGet('/push/vapid-public-key');
    if (!enabled) { toast('اعلان Push هنوز روی سرور تنظیم نشده (کلید VAPID غایب است).', true); return false; }
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') { toast('اجازه‌ی اعلان داده نشد.', true); return false; }
    const reg = await navigator.serviceWorker.register('/sw.js');
    await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
    }
    const raw = sub.toJSON();
    await apiPost('/push/subscribe', { endpoint: raw.endpoint, keys: raw.keys, user_agent: navigator.userAgent });
    toast('اعلان مرورگر فعال شد — حتی وقتی مرورگر بسته باشد پیام می‌رسد.');
    return true;
  } catch (e) {
    handleErr(e);
    return false;
  }
}

async function disablePushNotifications() {
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    const sub = reg ? await reg.pushManager.getSubscription() : null;
    if (sub) {
      await apiPost('/push/unsubscribe', { endpoint: sub.endpoint });
      await sub.unsubscribe();
    }
    toast('اعلان مرورگر روی این دستگاه غیرفعال شد.');
  } catch (e) { handleErr(e); }
}

function openPushSettingsModal() {
  openModal('اعلان مرورگر (Push)', `<div id="push-modal-body"><p class="card-sub">در حال بررسی وضعیت...</p></div>`, (body) => {
    const paint = async () => {
      const status = await pushStatus();
      const label = {
        unsupported: 'این مرورگر از اعلان Push پشتیبانی نمی‌کند.',
        denied: 'اجازه‌ی اعلان قبلاً رد شده؛ باید از تنظیمات خودِ مرورگر برای این سایت دوباره اجازه بدهی.',
        subscribed: 'اعلان مرورگر روی این دستگاه فعال است — برای سفارش، شارژ کیف پول و تیکت جدید، حتی وقتی مرورگر کاملاً بسته باشد اعلان دریافت می‌کنی.',
        'not-subscribed': 'اعلان مرورگر روی این دستگاه فعال نیست.',
      }[status];
      body.innerHTML = `
        <p class="card-sub" style="margin-bottom:14px;line-height:1.9">${label}</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          ${status === 'not-subscribed' ? '<button class="btn btn-primary btn-sm" id="push-enable-btn">فعال‌سازی</button>' : ''}
          ${status === 'subscribed' ? '<button class="btn btn-sm" id="push-test-btn">ارسال اعلان تست</button><button class="btn btn-danger btn-sm" id="push-disable-btn">غیرفعال‌سازی</button>' : ''}
        </div>
      `;
      const enableBtn = $('#push-enable-btn', body);
      const testBtn = $('#push-test-btn', body);
      const disableBtn = $('#push-disable-btn', body);
      if (enableBtn) enableBtn.addEventListener('click', async () => { enableBtn.disabled = true; await enablePushNotifications(); paint(); });
      if (testBtn) testBtn.addEventListener('click', async () => {
        testBtn.disabled = true;
        try { await apiPost('/push/test'); toast('اعلان تست ارسال شد.'); } catch (e) { handleErr(e); }
        testBtn.disabled = false;
      });
      if (disableBtn) disableBtn.addEventListener('click', async () => { await disablePushNotifications(); paint(); });
    };
    paint();
  });
}

/* ============================================== نصب به عنوان اپ (PWA) === === */
/* اندروید (کروم): با beforeinstallprompt یک دیالوگ نصب بومی نشون میدیم.
   آیفون (سافاری): هیچ API ای برای نصب برنامه‌ای وجود نداره، پس فقط راهنمای
   دستی «Share -> Add to Home Screen» رو نشون می‌دیم. */

// نکته‌ی مهم: قبلاً Service Worker فقط وقتی ثبت می‌شد که ادمین دستی روی
// دکمه‌ی 🔔 (اعلان Push) می‌زد. چون کروم بدون یک Service Worker فعال، سایت
// رو یک PWA قابل‌نصب واقعی نمی‌بینه (و به‌جاش فقط گزینه‌ی عمومی «Install and
// create shortcut» رو تو منو نشون می‌ده، نه دیالوگ واقعی نصب اپ)، اینجا
// همون اول لود صفحه (بدون نیاز به فعال کردن Push) ثبتش می‌کنیم.
if ('serviceWorker' in navigator) {
  const registerSW = () => navigator.serviceWorker.register('/sw.js').catch(() => {});
  if (document.readyState === 'complete') registerSW(); else window.addEventListener('load', registerSW);
}

(function watchAppVersion() {
  const meta = document.querySelector('meta[name="asset-version"]');
  const current = meta && meta.content;
  if (!current || current.startsWith('{{')) return;
  const isTyping = () => {
    const el = document.activeElement;
    if (window.__svLoginPending) return true;
    // Never reload out from under the login screen: a stuck/oscillating
    // version between requests must not turn into a login-blocking loop.
    const loginScreen = document.getElementById('login-screen');
    if (loginScreen && !loginScreen.hidden) return true;
    return !!el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable);
  };
  // Hard cooldown + two-in-a-row confirmation. The old guard only remembered
  // the *last* version it had reloaded for, so if the server ever reported
  // more than two distinct version values in a row (flapping between
  // workers/deploys, or a version source that isn't fully stable), every
  // single check would see "yet another new version" and reload again —
  // in practice a reload loop as fast as the page could re-fire
  // visibilitychange (looks like the page refreshing every second).
  // Fix: (1) never reload more than once per COOLDOWN_MS no matter how many
  // different values show up in between, and (2) only trust a new version
  // once it has been seen twice in a row, so a value that's itself
  // unstable between requests can't trigger a reload at all.
  const COOLDOWN_MS = 5 * 60 * 1000;
  let lastReloadAt = 0;
  try { lastReloadAt = parseInt(sessionStorage.getItem('sv_last_reload_at') || '0', 10) || 0; } catch (e) {}
  let pendingVersion = null;
  const check = async () => {
    try {
      const res = await fetch('/api/app-version', { cache: 'no-store' });
      const data = await res.json();
      if (!data.v || data.v === current || isTyping()) { pendingVersion = null; return; }
      if (Date.now() - lastReloadAt < COOLDOWN_MS) return; // still cooling down from a recent reload
      if (pendingVersion !== data.v) { pendingVersion = data.v; return; } // wait for confirmation
      lastReloadAt = Date.now();
      try { sessionStorage.setItem('sv_last_reload_at', String(lastReloadAt)); } catch (e) {}
      location.reload();
    } catch (e) {}
  };
  document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
  setInterval(() => { if (!document.hidden) check(); }, 60000);
})();

let deferredInstallPrompt = null;

function isStandalonePwa() {
  return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
}
function isIosDevice() {
  return /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1); // آیپد جدید خودش رو مک معرفی می‌کنه
}

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredInstallPrompt = e;
  $('#install-app-btn')?.style && ($('#install-app-btn').style.display = '');
});

window.addEventListener('appinstalled', () => {
  deferredInstallPrompt = null;
  $('#install-app-btn')?.style && ($('#install-app-btn').style.display = 'none');
  toast('پنل به عنوان اپلیکیشن روی این دستگاه نصب شد.');
});

function openIosInstallModal() {
  openModal('نصب پنل روی آیفون', `
    <p class="card-sub" style="margin-bottom:14px;line-height:2">
      سافاری روی آیفون نصب خودکار را پشتیبانی نمی‌کند؛ برای اضافه کردن پنل به هوم‌اسکرین
      (شبیه یک اپ مستقل، با آیکون و بدون نوار آدرس) این مراحل را دنبال کن:
    </p>
    <ol style="padding-inline-start:20px;line-height:2.2;color:var(--text-muted)">
      <li>از نوار پایین سافاری، دکمه‌ی <b>Share</b> (مربع با فلش رو به بالا) را بزن.</li>
      <li>در لیست، گزینه‌ی <b>Add to Home Screen</b> را انتخاب کن.</li>
      <li>روی <b>Add</b> بزن.</li>
      <li>از این به بعد، پنل را فقط از آیکونی که روی هوم‌اسکرین اضافه شد باز کن —
        <b>فقط از همان آیکون</b> اعلان مرورگر (Push) هم قابل فعال‌سازی است، نه از تب معمولی سافاری.</li>
    </ol>
  `);
}

async function initInstallApp() {
  const btn = $('#install-app-btn');
  if (!btn) return;
  if (isStandalonePwa()) { btn.style.display = 'none'; return; }
  if (isIosDevice()) {
    btn.style.display = ''; // روی آیفون همیشه نشون بده (beforeinstallprompt وجود نداره)
    btn.addEventListener('click', openIosInstallModal);
    return;
  }
  // اندروید/دسکتاپ کروم: تا وقتی beforeinstallprompt فایر نشده دکمه مخفی می‌ماند
  btn.addEventListener('click', async () => {
    if (!deferredInstallPrompt) {
      toast('این مرورگر امکان نصب مستقیم را نمی‌دهد؛ از منوی مرورگر «Add to Home screen» را بزن.');
      return;
    }
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    btn.style.display = 'none';
  });
}

/* ===================================================== sidebar (mobile) === */
function closeSidebar() {
  $('.sidebar')?.classList.remove('open');
  $('#sidebar-overlay')?.classList.remove('show');
}
function openSidebar() {
  $('.sidebar')?.classList.add('open');
  $('#sidebar-overlay')?.classList.add('show');
}
$('#hamburger-btn')?.addEventListener('click', () => {
  $('.sidebar')?.classList.contains('open') ? closeSidebar() : openSidebar();
});
$('#sidebar-overlay')?.addEventListener('click', closeSidebar);

function tickClock() {
  $('#topbar-clock').textContent = new Date().toLocaleString('fa-IR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

$('#login-form').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = $('#login-submit');
  const errBox = $('#login-error');
  errBox.hidden = true;
  btn.disabled = true; btn.textContent = 'در حال ورود...';
  window.__svLoginPending = true;
  try {
    await apiPost('/login', {
      username: $('#login-username').value.trim(),
      password: $('#login-password').value,
      b: tenantParam(),
    });
    ME = await apiGet('/me');
    if (ME.language) localStorage.setItem('sv-lang', ME.language);
    applyResellerTierChrome();
    showApp();
  } catch (e) {
    errBox.textContent = e.message;
    errBox.hidden = false;
  } finally {
    btn.disabled = false; btn.textContent = 'ورود';
    window.__svLoginPending = false;
  }
});

$('#logout-btn').addEventListener('click', async () => {
  await apiPost('/logout');
  ME = null;
  showLogin();
});

/* ============================================================== page === */
function content() { return $('#content'); }
function setContent(html) { content().innerHTML = html; }

async function renderPage(tab) {
  setContent('<div class="loading">در حال بارگذاری...</div>');
  try {
    switch (tab) {
      case 'database': return await renderDatabaseManager();
      case 'dashboard': return await renderDashboard();
      case 'analytics': return await renderAnalytics();
      case 'reseller-self': return await renderResellerSelfService();
      case 'orders': return await renderOrders();
      case 'topups': return await renderTopups();
      case 'users': return await renderUsers();
      case 'subscriptions': return await renderSubscriptions();
      case 'user-groups': return await renderUserGroups();
      case 'catalog': return await renderCatalog();
      case 'discounts': return await renderDiscounts();
      case 'tickets': return await renderTickets();
      case 'support': return await renderSupport();
      case 'broadcast': return await renderBroadcast();
      case 'resellers': return await renderResellers();
      case 'reseller_tiers': return await renderResellerTiers();
      case 'panels': return await renderPanels();
      case 'ssh': return await renderSSHManagement();
      case 'system': return await renderSystem();
      case 'settings': return await renderSettings();
      case 'subscription-page': return await renderSubscriptionPageSettings();
      case 'languages': return await renderLanguages();
      case 'buttons': return await renderButtons();
      case 'bottexts': return await renderBotTexts();
      case 'salessettings': return await renderSalesSettings();
      case 'banners': return await renderBanners();
      case 'logs': return await renderLogs();
      case 'webadmins': return await renderWebAdmins();
      case 'tgadmins': return await renderTelegramAdmins();
      case 'account': return await renderAccount();
    }
  } catch (e) { handleErr(e); setContent(`<div class="empty-state">${esc(e.message)}</div>`); }
}


/* ================================================ database manager === */
async function renderDatabaseManager() {
  const api = async (url, opts={}) => {
    const r = await fetch(url, {credentials:'same-origin', headers:{'Content-Type':'application/json'}, ...opts});
    const d = await r.json().catch(()=>({}));
    if (!r.ok) throw new Error(d.detail || 'درخواست ناموفق بود');
    return d;
  };
  setContent(`<section class="hero"><div><h2>🗄️ مدیریت دیتابیس</h2>
    <p>مدیریت امن دیتابیس بات اصلی و نمایندگی‌ها · فقط سوپرادمین</p></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap"><select id="db-tenant" class="field"><option value="">بات اصلی</option></select>
    <button class="btn btn-primary" id="db-backup">⬇️ دانلود بکاپ کامل</button></div></section>
    <div class="db-layout" style="display:grid;grid-template-columns:minmax(210px, .8fr) minmax(0,2.2fr);gap:16px;margin-top:16px">
      <section class="card"><h3>جداول دیتابیس</h3><div id="db-tables" class="db-table-list">در حال بارگذاری...</div>
        <hr><button class="btn btn-ghost btn-block" id="db-audit">📜 لاگ تغییرات</button>
        <button class="btn btn-ghost btn-block" id="db-vacuum">🧹 بهینه‌سازی (VACUUM)</button></section>
      <section class="card"><div id="db-view"><div class="empty-state">برای مشاهده اطلاعات، یک جدول را انتخاب کنید.</div></div></section>
    </div>
    <section class="card" style="margin-top:16px"><h3>کنسول SQL فقط‌خواندنی</h3>
      <p class="muted">فقط SELECT مجاز است؛ حداکثر ۵۰۰ ردیف و ۲ ثانیه زمان اجرا.</p>
      <textarea id="db-sql" rows="4" dir="ltr" style="width:100%;font-family:monospace" placeholder="SELECT name FROM sqlite_master WHERE type='table'"></textarea>
      <button class="btn btn-primary" id="db-run-sql">اجرای کوئری</button><div id="db-sql-result"></div></section>`);
  const tablesEl=$('#db-tables'), view=$('#db-view');
  let selected='', selectedTenant='', currentPage=1, currentSearch='', currentSort='', currentDir='asc', currentData=null;
  const escDb=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function loadTables(){
    const d=await api('/api/database/tables?tenant='+encodeURIComponent(selectedTenant));
    tablesEl.innerHTML=d.tables.map(t=>`<button class="btn btn-ghost btn-block db-table-btn" data-table="${escDb(t.name)}" style="display:flex;justify-content:space-between"><span>${escDb(t.name)}</span><b>${Number(t.rows).toLocaleString()}</b></button>`).join('') || 'جدولی وجود ندارد';
    $$('.db-table-btn',tablesEl).forEach(b=>b.onclick=()=>{selected=b.dataset.table;currentPage=1;loadTable();});
  }
  async function loadTable(){
    if(!selected)return;
    const q=new URLSearchParams({page:currentPage,page_size:50,search:currentSearch,sort:currentSort,direction:currentDir,tenant:selectedTenant});
    const [d, schema]=await Promise.all([api(`/api/database/table/${encodeURIComponent(selected)}?${q}`),api(`/api/database/schema/${encodeURIComponent(selected)}?tenant=${encodeURIComponent(selectedTenant)}`)]);
    currentData=d;
    const pkCols=schema.columns.filter(c=>c.pk).map(c=>c.name);
    const headers=d.columns.map(c=>`<th><button class="btn btn-ghost btn-sm" data-sort="${escDb(c)}">${escDb(c)} ↕</button></th>`).join('');
    const rows=d.rows.map(row=>`<tr>${d.columns.map(c=>`<td>${escDb(typeof row[c]==='object'?JSON.stringify(row[c]):row[c])}</td>`).join('')}
      <td>${pkCols.length && !pkCols.some(k=>/(token|secret|password|passwd|hash|config|credential|private.?key|api.?key)/i.test(k))?`<button class="btn btn-ghost btn-sm" data-edit='${escDb(JSON.stringify(row))}' data-pk='${escDb(JSON.stringify(Object.fromEntries(pkCols.map(k=>[k,row[k]]))))}'>ویرایش</button> <button class="btn btn-danger btn-sm" data-delete='${escDb(JSON.stringify(Object.fromEntries(pkCols.map(k=>[k,row[k]]))))}'>حذف</button>`:'—'}</td></tr>`).join('');
    view.innerHTML=`<div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;justify-content:space-between"><div><h3>${escDb(selected)}</h3><small>${d.total.toLocaleString()} ردیف</small></div>
      <div><button class="btn btn-ghost btn-sm" id="db-schema">ساختار و ایندکس‌ها</button>
      <button class="btn btn-ghost btn-sm" id="db-export-json">JSON</button><button class="btn btn-ghost btn-sm" id="db-export-csv">CSV</button><button class="btn btn-ghost btn-sm" id="db-import-json">ورود JSON</button><input id="db-import-file" type="file" accept=".json,application/json" hidden></div></div>
      <input id="db-search" placeholder="جستجو در ستون‌های غیرحساس..." value="${escDb(currentSearch)}" style="width:100%;margin:12px 0">
      <div style="overflow:auto"><table class="data-table"><thead><tr>${headers}<th>عملیات</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:12px"><button class="btn btn-ghost" id="db-prev" ${currentPage<=1?'disabled':''}>قبلی</button><span>صفحه ${d.page} · ${Math.max(1,Math.ceil(d.total/d.page_size))}</span><button class="btn btn-ghost" id="db-next" ${currentPage*d.page_size>=d.total?'disabled':''}>بعدی</button></div>`;
    $('#db-search').onkeydown=e=>{if(e.key==='Enter'){currentSearch=e.target.value;currentPage=1;loadTable();}};
    $$('[data-sort]',view).forEach(b=>b.onclick=()=>{if(currentSort===b.dataset.sort)currentDir=currentDir==='asc'?'desc':'asc';else{currentSort=b.dataset.sort;currentDir='asc';}loadTable();});
    $('#db-prev').onclick=()=>{currentPage--;loadTable();}; $('#db-next').onclick=()=>{currentPage++;loadTable();};
    $('#db-schema').onclick=()=>openModal('ساختار جدول',`<pre dir="ltr">${escDb(JSON.stringify(schema,null,2))}</pre>`);
    $('#db-export-json').onclick=()=>window.open(`/api/database/export/${encodeURIComponent(selected)}?format=json&tenant=${encodeURIComponent(selectedTenant)}`,'_blank');
    $('#db-export-csv').onclick=()=>window.open(`/api/database/export/${encodeURIComponent(selected)}?format=csv&tenant=${encodeURIComponent(selectedTenant)}`,'_blank');
    $('#db-import-json').onclick=()=>$('#db-import-file').click();
    $('#db-import-file').onchange=async e=>{const file=e.target.files?.[0];if(!file)return;try{const parsed=JSON.parse(await file.text());const rows=Array.isArray(parsed)?parsed:parsed.rows;if(!Array.isArray(rows))throw new Error('ساختار JSON باید آرایه ردیف‌ها یا دارای فیلد rows باشد');if(!confirm(`ورود ${rows.length} ردیف به جدول ${selected}؟ ابتدا بکاپ گرفته می‌شود.`))return;const result=await api(`/api/database/import/${encodeURIComponent(selected)}`,{method:'POST',body:JSON.stringify({rows,tenant:selectedTenant})});toast(`${result.imported} ردیف وارد شد`);await loadTable();await loadTables();}catch(err){toast(err.message||'ورود ناموفق بود');}finally{e.target.value='';}};
    $$('[data-edit]',view).forEach(b=>b.onclick=async()=>{const row=JSON.parse(b.dataset.edit), pk=JSON.parse(b.dataset.pk);const editable=d.columns.filter(c=>!pkCols.includes(c)&&!/(token|secret|password|passwd|hash|config|credential|private.?key|api.?key)/i.test(c));const fields=editable.map(c=>`<label class="field"><span>${escDb(c)}</span><textarea data-col="${escDb(c)}" rows="2">${escDb(row[c]??'')}</textarea></label>`).join('');openModal('ویرایش ردیف',`${fields}<p class="muted">قبل از ذخیره، بکاپ کامل دیتابیس گرفته می‌شود.</p><button class="btn btn-primary" id="db-save-row">ذخیره تغییرات</button>`,body=>{$('#db-save-row',body).onclick=async()=>{const values={};$$('[data-col]',body).forEach(x=>{if(x.value!==String(row[x.dataset.col]??''))values[x.dataset.col]=x.value;});if(!Object.keys(values).length)return toast('تغییری انجام نشده');const result=await api('/api/database/row',{method:'POST',body:JSON.stringify({table:selected,pk,values,tenant:selectedTenant})});toast('تغییرات ذخیره شد؛ بکاپ: '+result.backup);await loadTable();};},{wide:true});});
    $$('[data-delete]',view).forEach(b=>b.onclick=async()=>{if(!confirm('حذف این ردیف؟ قبل از تغییر بکاپ گرفته می‌شود.'))return;await api('/api/database/delete-row',{method:'POST',body:JSON.stringify({table:selected,pk:JSON.parse(b.dataset.delete),tenant:selectedTenant})});toast('ردیف حذف شد؛ بکاپ خودکار ایجاد شد');await loadTable();await loadTables();});
  }
  $('#db-backup').onclick=()=>window.location.href='/api/database/backup?tenant='+encodeURIComponent(selectedTenant);
  $('#db-vacuum').onclick=async()=>{if(!confirm('ابتدا بکاپ کامل گرفته می‌شود. اجرای VACUUM ممکن است چند لحظه طول بکشد. ادامه می‌دهید؟'))return;const d=await api('/api/database/vacuum',{method:'POST',body:JSON.stringify({tenant:selectedTenant})});toast('بهینه‌سازی انجام شد؛ بکاپ: '+d.backup);};
  $('#db-audit').onclick=async()=>{const d=await api('/api/database/audit?tenant='+encodeURIComponent(selectedTenant));openModal('لاگ تغییرات',`<pre>${escDb(JSON.stringify(d.rows,null,2))}</pre>`,null,{wide:true});};
  $('#db-run-sql').onclick=async()=>{const box=$('#db-sql-result');box.textContent='در حال اجرا...';try{const d=await api('/api/database/query',{method:'POST',body:JSON.stringify({sql:$('#db-sql').value,tenant:selectedTenant})});box.innerHTML=`<pre dir="ltr" style="overflow:auto">${escDb(JSON.stringify(d,null,2))}</pre>`;}catch(e){box.textContent=e.message;}};
  $('#db-tenant').onchange=e=>{selectedTenant=e.target.value;selected='';currentPage=1;loadTables();view.innerHTML='<div class="empty-state">یک جدول را انتخاب کنید.</div>';};
  try{const t=await api('/api/database/tenants');$('#db-tenant').innerHTML=t.tenants.map(x=>`<option value="${escDb(x.id)}">${escDb(x.name)} · ${escDb(x.db)}</option>`).join('');await loadTables();}catch(e){tablesEl.textContent=e.message;}
}

/* =============================================== reseller self-service === */
async function renderResellerSelfService() {
  const d = await apiGet('/reseller/self-service');
  const rp = d.profile || {};
  const supply = d.supply || {};
  const fixed = d.inventory || [];
  const services = d.services || [];
  const canCustom = supply.model === 'volume_credit';
  setContent(`
    <div class="hero" style="margin-bottom:16px">
      <div><h2>نمایندگی من</h2><p class="card-sub">این بخش فقط برای مصرف موجودی خودت است؛ هیچ دسترسی مدیریتی به کاتالوگ یا پنل اصلی نداری.</p></div>
    </div>
    <div class="stats-grid" style="margin-bottom:16px">
      <div class="stat-card"><span class="label">مدل تأمین</span><span class="value">${supply.model === 'fixed_product' ? 'محصول آماده' : 'اعتبار حجمی'}</span></div>
      <div class="stat-card"><span class="label">اعتبار حجمی</span><span class="value mono">${fmt(supply.credit_gb || 0)} GB</span></div>
      <div class="stat-card"><span class="label">سرویس‌های من</span><span class="value mono">${fmt(services.length)}</span></div>
    </div>
    <div class="grid-2" style="gap:16px">
      <div class="card">
        <div class="card-head"><h3>📦 محصولات آماده‌ی من</h3><span class="card-sub">فقط محصولاتی که ادمین به موجودی تو داده است.</span></div>
        <div class="admin-list">
          ${fixed.length ? fixed.map(p => `<div class="admin-list-row"><div><b>${esc(p.name)}</b><div class="card-sub">${fmt(p.volume_gb)} گیگ · ${p.duration_days ? fmt(p.duration_days)+' روز' : 'نامحدود'} · موجودی ${fmt(p.qty)}</div></div><button class="btn btn-primary btn-sm" data-self-fixed="${p.id}">دریافت برای خودم</button></div>`).join('') : '<div class="empty-state">موجودی محصول آماده‌ای برای تو ثبت نشده است.</div>'}
        </div>
      </div>
      <div class="card">
        <div class="card-head"><h3>🛠 ساخت کانفیگ دلخواه</h3><span class="card-sub">${canCustom ? `از اعتبار ${fmt(supply.credit_gb || 0)} گیگ مصرف می‌شود.` : 'این قابلیت برای مدل محصول آماده فعال نیست.'}</span></div>
        ${canCustom ? `<div class="form-grid">
          <label class="field"><span>حجم (گیگابایت)</span><input class="input" id="rs-volume" type="number" min="${d.custom_limits.min_gb}" max="${d.custom_limits.max_gb}" value="${Math.min(Math.max(d.custom_limits.min_gb, 10), d.custom_limits.max_gb)}"></label>
          <label class="field"><span>مدت (روز) — ۰ = نامحدود</span><input class="input" id="rs-duration" type="number" min="0" max="3650" value="30"></label>
          <label class="field"><span>نام کاربری (اختیاری)</span><input class="input" id="rs-username" maxlength="64" placeholder="خالی = خودکار"></label>
          <button class="btn btn-primary" id="rs-build">ساخت کانفیگ و کسر از اعتبار</button>
        </div>` : `<div class="empty-state">برای ساخت آزاد، مدل تأمین نمایندگی باید «اعتبار حجمی» باشد.</div>`}
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <div class="card-head"><h3>🔐 سرویس‌های من</h3></div>
      <div class="admin-list">
        ${services.length ? services.map(c => `<div class="admin-list-row"><div><b>${esc(c.display_name || c.username)}</b><div class="card-sub mono">${esc(c.username)} · ${fmt(c.volume_gb)}GB · ${c.duration_days ? fmt(c.duration_days)+' روز' : 'نامحدود'}</div></div><div class="admin-list-row-actions"><button class="btn btn-sm" data-self-toggle="${c.id}">${c.enabled ? 'غیرفعال' : 'فعال'}</button><button class="btn btn-sm" data-self-rename="${c.id}">تغییر نام</button><button class="btn btn-sm" data-self-copy="${c.id}">لینک</button><button class="btn btn-danger btn-sm" data-self-delete="${c.id}">حذف</button></div></div>`).join('') : '<div class="empty-state">هنوز سرویسی برای خودت ساخته نشده است.</div>'}
      </div>
    </div>
  `);
  $$('[data-self-fixed]', content()).forEach(btn => btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      const r = await apiPost('/reseller/self-service/fixed', { product_id: Number(btn.dataset.selfFixed), quantity: 1 });
      toast('کانفیگ ساخته شد.');
      showResellerResult(r);
      await renderResellerSelfService();
    } catch (e) { handleErr(e); btn.disabled = false; }
  }));
  $('#rs-build')?.addEventListener('click', async () => {
    const volume_gb = Number($('#rs-volume').value), duration_days = Number($('#rs-duration').value), username = $('#rs-username').value.trim() || null;
    const btn = $('#rs-build'); btn.disabled = true;
    try { const r = await apiPost('/reseller/self-service/custom', { volume_gb, duration_days, username }); toast('کانفیگ ساخته شد.'); showResellerResult(r); await renderResellerSelfService(); }
    catch (e) { handleErr(e); btn.disabled = false; }
  });
  $$('[data-self-toggle]', content()).forEach(btn => btn.addEventListener('click', async () => { try { await apiPost(`/reseller/self-service/services/${btn.dataset.selfToggle}/toggle`); await renderResellerSelfService(); } catch(e){handleErr(e);} }));
  $$('[data-self-rename]', content()).forEach(btn => btn.addEventListener('click', async () => {
    const name = prompt('نام نمایشی جدید را وارد کن:'); if (!name) return;
    try { await apiPost(`/reseller/self-service/services/${btn.dataset.selfRename}/rename`, { name }); await renderResellerSelfService(); } catch(e){handleErr(e);}
  }));
  $$('[data-self-delete]', content()).forEach(btn => btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      const q = await apiGet(`/reseller/self-service/services/${btn.dataset.selfDelete}/delete-quote`);
      openModal('حذف سرویس', `<div class="form-grid"><div>این سرویس برای همیشه از پنل VPN و از لیست تو حذف می‌شود و غیرقابل بازگشت است.</div><div style="white-space:pre-line">${esc(q.text || 'با حذف این سرویس، اعتباری برگردانده نمی‌شود.')}</div><div class="admin-list-row-actions"><button class="btn btn-sm" id="rs-del-cancel">انصراف</button><button class="btn btn-danger btn-sm" id="rs-del-ok">حذف نهایی</button></div></div>`, (body, close) => {
        $('#rs-del-cancel', body).addEventListener('click', close);
        $('#rs-del-ok', body).addEventListener('click', async ev => {
          ev.target.disabled = true;
          try {
            const r = await apiDelete(`/reseller/self-service/services/${btn.dataset.selfDelete}`);
            close();
            toast(r.refund_text ? `سرویس حذف شد. ${r.refund_text}` : 'سرویس حذف شد.');
            await renderResellerSelfService();
          } catch (e) { handleErr(e); ev.target.disabled = false; }
        });
      });
    } catch (e) { handleErr(e); }
    btn.disabled = false;
  }));
  $$('[data-self-copy]', content()).forEach(btn => btn.addEventListener('click', async () => {
    const service = services.find(x => String(x.id) === String(btn.dataset.selfCopy)); if (!service) return;
    try { await navigator.clipboard.writeText(service.subscription_url || ''); toast('لینک کپی شد.'); } catch(e) { openModal('لینک اشتراک', `<div class="form-grid"><textarea class="input" rows="4" readonly>${esc(service.subscription_url || '')}</textarea></div>`); }
  }));
}

function showResellerResult(r) {
  openModal('✅ کانفیگ آماده است', `<div class="form-grid"><div><b>نام کاربری:</b> <span class="mono">${esc(r.username)}</span></div><div><b>حجم:</b> ${fmt(r.volume_gb)} گیگ · <b>مدت:</b> ${r.duration_days ? fmt(r.duration_days)+' روز' : 'نامحدود'}</div><textarea class="input" rows="5" readonly>${esc(r.subscription_url || '')}</textarea></div>`);
}

/* ========================================================= dashboard === */
function greetingByHour() {
  const h = new Date().getHours();
  if (h < 12) return 'صبح بخیر';
  if (h < 18) return 'ظهر بخیر';
  return 'شب بخیر';
}

function resRingHtml(pct, colorVar, title, sub) {
  const p = Math.max(0, Math.min(100, Math.round(pct)));
  return `
    <div class="card res-card">
      <div class="res-ring" style="--ring-a:${colorVar}" data-pct="${p}"><span>${p}٪</span></div>
      <div class="res-info"><strong>${title}</strong><span>${sub}</span></div>
    </div>`;
}

// بازه‌ی زمانی داشبورد — به انتخاب ادمین، بین صفحات نگه داشته می‌شه
// (localStorage). خالی/null یعنی پیش‌فرض سرور (۱۴ روز اخیر).
const DASH_RANGE_PRESETS = [
  { key: '7', label: '۷ روز', days: 7 },
  { key: '14', label: '۱۴ روز', days: 14 },
  { key: '30', label: '۳۰ روز', days: 30 },
  { key: '90', label: '۹۰ روز', days: 90 },
];
function getDashRange() {
  try { return JSON.parse(localStorage.getItem('sv-dash-range')) || null; } catch (e) { return null; }
}
function setDashRange(range) {
  try {
    if (range) localStorage.setItem('sv-dash-range', JSON.stringify(range));
    else localStorage.removeItem('sv-dash-range');
  } catch (e) {}
}
function isoDaysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
function dashRangeBarHtml(s) {
  const saved = getDashRange();
  const activePreset = saved && saved.preset ? saved.preset : '14';
  const chips = DASH_RANGE_PRESETS.map(p => `
    <button class="btn btn-sm dash-range-chip ${p.key === activePreset ? 'active' : ''}" data-preset="${p.key}">${p.label}</button>
  `).join('');
  const customStart = saved && !saved.preset ? saved.start : '';
  const customEnd = saved && !saved.preset ? saved.end : '';
  return `
    <div class="card dash-range-bar" style="margin-bottom:16px">
      <div class="dash-range-row">
        <div class="dash-range-chips">${chips}
          <button class="btn btn-sm dash-range-chip ${saved && !saved.preset ? 'active' : ''}" id="dash-range-custom-toggle">بازه‌ی دلخواه</button>
        </div>
        <span class="card-sub">${fmtDateOnly(s.start_date)} تا ${fmtDateOnly(s.end_date)}</span>
      </div>
      <div class="dash-range-custom" id="dash-range-custom" ${saved && !saved.preset ? '' : 'hidden'}>
        <input type="date" class="input" id="dash-range-start" value="${customStart}">
        <span>تا</span>
        <input type="date" class="input" id="dash-range-end" value="${customEnd}">
        <button class="btn btn-primary btn-sm" id="dash-range-apply">اعمال</button>
      </div>
    </div>`;
}
function wireDashRangeBar(onChange) {
  const refresh = onChange || renderDashboard;
  const root = content();
  if (!root) return;
  $$('.dash-range-chip[data-preset]', root).forEach(btn => btn.addEventListener('click', () => {
    const days = Number(btn.dataset.preset);
    setDashRange({ preset: btn.dataset.preset, start: isoDaysAgo(days - 1), end: isoDaysAgo(0) });
    refresh();
  }));
  const customToggle = $('#dash-range-custom-toggle', root);
  const customBox = $('#dash-range-custom', root);
  if (customToggle && customBox) {
    customToggle.addEventListener('click', () => { customBox.hidden = !customBox.hidden; });
  }
  const applyBtn = $('#dash-range-apply', root);
  if (applyBtn) applyBtn.addEventListener('click', () => {
    const start = $('#dash-range-start', root).value;
    const end = $('#dash-range-end', root).value;
    if (!start || !end) { toast('هر دو تاریخ رو انتخاب کن.'); return; }
    if (start > end) { toast('تاریخ شروع نباید بعد از تاریخ پایان باشه.'); return; }
    setDashRange({ preset: null, start, end });
    refresh();
  });
}
function resellerTierMeta() {
  const p = ME?.reseller_profile;
  if (!p) return null;
  const vip = String(p.tier_code || '').toLowerCase() === 'vip';
  return {
    code: vip ? 'vip' : 'gold',
    title: p.tier_title || (vip ? 'VIP' : 'طلایی'),
    icon: p.tier_icon || (vip ? '💎' : '🥇'),
    subtitle: vip ? 'مرکز فرماندهی فروش و اعتبار VIP' : 'مرکز عملیات فروش نمایندگی طلایی',
  };
}

function resellerBalanceChartHtml(balance) {
  if (!balance) return '<div class="card-sub">داده‌ای در دسترس نیست.</div>';
  if (balance.model === 'fixed_product') {
    const rows = balance.products || [];
    if (!rows.length) return '<div class="card-sub">محصول فعالی برای این نمایندگی ثبت نشده.</div>';
    const max = Math.max(...rows.map(r => r.qty_remaining), 1);
    return rows.map(r => `
      <div style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px">
          <span>${esc(r.name)}</span><span class="mono">${fmt(r.qty_remaining)}</span>
        </div>
        <div style="height:10px;border-radius:5px;background:var(--border,rgba(128,128,128,.15));overflow:hidden">
          <div style="height:100%;border-radius:5px;background:var(--brand,#8B5CF6);width:${Math.max(2, (r.qty_remaining / max) * 100)}%"></div>
        </div>
      </div>`).join('');
  }
  return `<div class="stat-card"><span class="label">اعتبار حجمی باقیمانده</span><span class="value mono">${fmt(balance.credit_gb || 0)} <small>GB</small></span></div>`;
}

async function renderResellerTierDashboard() {
  const p = ME.reseller_profile || {};
  const meta = resellerTierMeta();
  const vip = meta.code === 'vip';
  const supplyText = p.supply_model === 'fixed_product' ? 'محصول آماده' : 'اعتبار حجمی';
  const heroClass = vip ? 'reseller-tier-hero vip' : 'reseller-tier-hero gold';
  setContent(`
    <div class="${heroClass}">
      <div class="reseller-tier-orb">${meta.icon}</div>
      <div class="reseller-tier-copy">
        <span class="reseller-tier-kicker">SHOPVPN · ${vip ? 'VIP COMMAND' : 'GOLD OPERATIONS'}</span>
        <h2>${meta.icon} پنل نمایندگی ${esc(meta.title)}</h2>
        <p>${meta.subtitle}</p>
      </div>
      <div class="reseller-tier-chip">${supplyText}</div>
    </div>
    <div class="grid grid-4 reseller-kpi-grid">
      <div class="card reseller-kpi"><span>فروش تاییدشده</span><strong>${fmt(p.revenue_toman)} <small>تومان</small></strong><em>از سفارش‌های این پنل</em></div>
      <div class="card reseller-kpi"><span>سفارش موفق</span><strong>${fmt(p.paid_orders)}</strong><em>پرداخت‌های تاییدشده</em></div>
      <div class="card reseller-kpi"><span>سرویس ساخته‌شده</span><strong>${fmt(p.configs_created)}</strong><em>از اعتبار نمایندگی</em></div>
      <div class="card reseller-kpi"><span>${vip ? 'حجم مصرف‌شده' : 'وضعیت تامین'}</span><strong>${vip ? fmt(p.volume_sold_gb) + ' <small>GB</small>' : esc(supplyText)}</strong><em>${vip ? 'حجم سرویس‌های ساخته‌شده' : 'موجودی بر اساس محصول منتخب'}</em></div>
    </div>
    <div class="grid grid-2" style="gap:16px;align-items:start;margin-bottom:16px">
      <div class="card">
        <div class="card-head"><h3>📈 روند فروش (۱۴ روز اخیر)</h3></div>
        <div id="reseller-sales-chart"><div class="card-sub">در حال بارگذاری...</div></div>
      </div>
      <div class="card">
        <div class="card-head"><h3>💼 موجودی نمایندگی</h3></div>
        <div id="reseller-balance-chart"><div class="card-sub">در حال بارگذاری...</div></div>
      </div>
    </div>
    <div class="grid grid-2 reseller-command-grid">
      <div class="card reseller-command-card">
        <div class="card-head"><h3>⚡ عملیات سریع</h3><span class="card-sub">${vip ? 'ابزارهای حرفه‌ای VIP' : 'ابزارهای روزانه نماینده'}</span></div>
        <div class="reseller-action-grid">
          <button class="reseller-action" data-go="reseller-self">🧰 <b>نمایندگی من</b><small>اعتبار، موجودی و سرویس‌ها</small></button>
          <button class="reseller-action" data-go="orders">🧾 <b>سفارش‌ها</b><small>آخرین فروش‌ها و پرداخت‌ها</small></button>
          <button class="reseller-action" data-go="users">👥 <b>مشتری‌ها</b><small>مدیریت مشتریان پنل</small></button>
          <button class="reseller-action" data-go="catalog">📦 <b>محصولات</b><small>کاتالوگ و بانک سرویس</small></button>
        </div>
      </div>
      <div class="card reseller-command-card">
        <div class="card-head"><h3>${vip ? '💎 مزیت‌های VIP' : '🥇 وضعیت Gold'}</h3><span class="card-sub">سطح فعال حساب</span></div>
        <div class="reseller-feature-list">
          ${vip ? `
            <div>📊 <b>گزارش حرفه‌ای</b><span>تحلیل فروش و مصرف اعتبار در یک نگاه</span></div>
            <div>🚀 <b>عملیات سریع</b><span>دسترسی کوتاه به ساخت و مدیریت سرویس</span></div>
            <div>🛡️ <b>کنترل کامل‌تر</b><span>ابزارهای بیشتر بدون نمایش گزینه‌های نامرتبط</span></div>` : `
            <div>📦 <b>فروش محصولی</b><span>تمرکز پنل روی فروش و موجودی محصول آماده</span></div>
            <div>⚡ <b>عملیات سریع</b><span>ساخت و مدیریت سرویس بدون شلوغی پنل</span></div>
            <div>🛡️ <b>محیط اختصاصی</b><span>فقط ابزارهایی که برای Gold لازم است</span></div>`}
        </div>
      </div>
    </div>
  `);
  $$('[data-go]', content()).forEach(b => b.onclick = () => goTo(b.dataset.go));
  try {
    const chart = await apiGet('/reseller/dashboard-chart');
    const salesEl = $('#reseller-sales-chart', content());
    if (salesEl) salesEl.innerHTML = trendChartSvg(chart.sales_trend.points);
    const balEl = $('#reseller-balance-chart', content());
    if (balEl) balEl.innerHTML = resellerBalanceChartHtml(chart.balance);
  } catch (e) { /* اگر چارت با خطا مواجه شد، داشبورد بدون آن قابل استفاده می‌ماند */ }
}

async function renderDashboard() {
  if (ME?.tenant && ['gold','vip'].includes(String(ME?.reseller_profile?.tier_code || '').toLowerCase())) {
    await renderResellerTierDashboard();
    return;
  }
  const range = getDashRange();
  const q = range ? `?start=${range.start}&end=${range.end}` : '';
  const s = await apiGet('/dashboard' + q);
  let sys = null;
  try { sys = await apiGet('/system/stats'); } catch (e) { /* psutil ممکن است نصب نباشد */ }
  const theme = loadTheme().theme;
  if (theme === 'brutalist') await renderDashboardBrutalist(s, sys);
  else if (theme === 'cyberpunk') await renderDashboardCyberpunk(s, sys);
  else if (theme === 'streetops') await renderDashboardStreetOps(s, sys);
  else if (theme === 'android') await renderDashboardAndroid(s, sys);
  else await renderDashboardBento(s, sys);
  const root = content();
  if (root) root.insertAdjacentHTML('afterbegin', dashRangeBarHtml(s));
  wireDashRangeBar();
  appendDashboardCommandCenter(s, sys);
  appendExtraStatsPanel(s);
  await appendCronPanel();
}

/* نوار فرمان داشبورد: میان‌برهای پرتکرار و هشدارهای عملیاتی، مستقل از تم */
function appendDashboardCommandCenter(s, sys) {
  const root = content();
  if (!root || ME?.tenant) return;
  $('#dashboard-command-center', root)?.remove();
  const shortcuts = [
    { key: 'orders', icon: '🧾', title: 'بررسی سفارش‌ها', desc: 'پرداخت‌ها و سفارش‌های جدید' },
    { key: 'users', icon: '👥', title: 'مدیریت کاربران', desc: 'جستجو و مدیریت مشتریان' },
    { key: 'catalog', icon: '📦', title: 'محصولات و کانفیگ‌ها', desc: 'موجودی و بانک سرویس' },
    { key: 'panels', icon: '🖥️', title: 'پنل‌های VPN', desc: 'اتصال و وضعیت پنل‌ها' },
    { key: 'analytics', icon: '📈', title: 'گزارش‌های تحلیلی', desc: 'روند فروش و عملکرد' },
    { key: 'settings', icon: '⚙️', title: 'تنظیمات فروشگاه', desc: 'پیکربندی و برندینگ' },
  ].filter(item => canSee(NAV.find(n => n.key === item.key)?.role || 'any'));
  const lowStock = (s.low_stock_products || []).length;
  const openTickets = Number(s.open_tickets || 0);
  const resourceAlerts = [sys?.cpu?.percent, sys?.ram?.percent, sys?.disk?.percent]
    .map(Number).filter(v => Number.isFinite(v) && v >= 85).length;
  const alerts = [
    { count: lowStock, label: 'محصول کم‌موجودی', target: 'catalog', tone: 'warning', icon: '📦' },
    { count: openTickets, label: 'تیکت نیازمند رسیدگی', target: 'tickets', tone: 'info', icon: '🎧' },
    { count: resourceAlerts, label: 'منبع سرور در آستانه هشدار', target: 'system', tone: 'danger', icon: '🛡️' },
  ].filter(a => a.count > 0 && canSee(NAV.find(n => n.key === a.target)?.role || 'any'));
  const el = document.createElement('section');
  el.id = 'dashboard-command-center';
  el.className = 'dashboard-command-center';
  el.innerHTML = `
    <div class="dcc-heading"><div><span class="dcc-eyebrow">SHOPVPN · CONTROL CENTER</span>
      <h3>${greetingByHour()}، ${esc(ME?.username || 'مدیر')} 👋</h3>
      <p>دسترسی سریع به بخش‌های مهم و مواردی که نیاز به توجه دارند.</p></div>
      <div class="dcc-status"><i></i><span>پنل مدیریت فعال است</span></div></div>
    <div class="dcc-body"><div class="dcc-shortcuts">${shortcuts.map(item => `
      <button type="button" class="dcc-shortcut" data-dash-go="${item.key}"><span class="dcc-shortcut-icon">${item.icon}</span>
      <span class="dcc-shortcut-copy"><b>${item.title}</b><small>${item.desc}</small></span><span class="dcc-arrow">←</span></button>`).join('')}
      </div><aside class="dcc-alerts"><div class="dcc-alert-head"><b>نیازمند توجه</b><span>${alerts.length ? `${alerts.length} مورد` : 'همه‌چیز مرتب است'}</span></div>
      ${alerts.length ? alerts.map(a => `<button type="button" class="dcc-alert ${a.tone}" data-dash-go="${a.target}"><span>${a.icon}</span><span>${a.label}</span><b class="mono">${fmt(a.count)}</b></button>`).join('') :
      '<div class="dcc-all-clear"><span>✓</span><b>مورد فوری وجود ندارد</b><small>موجودی، پشتیبانی و منابع سرور در وضعیت عادی هستند.</small></div>'}</aside></div>`;
  const rangeBar = $('.dash-range-row', root)?.closest('.card');
  if (rangeBar?.parentNode === root) rangeBar.insertAdjacentElement('afterend', el);
  else root.insertBefore(el, root.firstChild);
  $$('[data-dash-go]', el).forEach(btn => btn.addEventListener('click', () => goTo(btn.dataset.dashGo)));
}

/* ------------------------------------------ dashboard: extra stats panel --- */
/* موجودی انبار + تیکت‌ها + نرخ مشتری تکراری. یک پنل مشترک که مستقل از تم زیر
   داشبورد هر تم اضافه می‌شود، تا نیازی به تکرار در ۸ پیاده‌سازی جدا نباشد. */
function appendExtraStatsPanel(s) {
  const root = content();
  if (!root) return;
  const old = $('#extra-stats-panel', root);
  if (old) old.remove();

  const inv = s.inventory || [];
  const low = s.low_stock_products || [];
  const invRows = inv.map(i => `
    <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border,rgba(128,128,128,.15))">
      <span>${esc(i.name)}${i.low_stock ? ' ⚠️' : ''}</span>
      <span class="mono">${fmt(i.unused)} آزاد / ${fmt(i.used)} مصرف‌شده</span>
    </div>`).join('') || '<span class="card-sub">محصول فعالی ثبت نشده</span>';

  const respText = s.avg_ticket_response_minutes != null ? `${s.avg_ticket_response_minutes} دقیقه` : '—';
  const el = document.createElement('div');
  el.className = 'card';
  el.id = 'extra-stats-panel';
  el.style.marginTop = '16px';
  el.innerHTML = `
    <div class="card-head"><h3>موجودی و پشتیبانی</h3><span class="card-sub">${fmtDateOnly(s.start_date)} تا ${fmtDateOnly(s.end_date)}</span></div>
    <div class="grid grid-2" style="gap:16px;align-items:start">
      <div>
        <div class="card-sub" style="margin-bottom:8px">موجودی انبار محصولات فعال</div>
        ${invRows}
      </div>
      <div>
        <div class="card-sub" style="margin-bottom:8px">تیکت‌های پشتیبانی و مشتریان</div>
        <div style="display:flex;justify-content:space-between;padding:6px 0"><span>تیکت ثبت‌شده در بازه</span><span class="mono">${fmt(s.tickets_created)}</span></div>
        <div style="display:flex;justify-content:space-between;padding:6px 0"><span>تیکت باز</span><span class="mono">${fmt(s.tickets_open)}</span></div>
        <div style="display:flex;justify-content:space-between;padding:6px 0"><span>میانگین زمان پاسخ اول</span><span class="mono">${respText}</span></div>
        <div style="display:flex;justify-content:space-between;padding:6px 0"><span>نرخ مشتری تکراری</span><span class="mono">${s.repeat_customer_rate}٪ (${fmt(s.repeat_customers)}/${fmt(s.total_customers)})</span></div>
        <div style="display:flex;justify-content:space-between;padding:6px 0"><span>جمع کل کدهای تخفیف داده‌شده</span><span class="mono">${fmt(s.total_discount_given)} تومان</span></div>
        <div style="display:flex;justify-content:space-between;padding:6px 0"><span>تعداد کل کدهای تخفیف داده‌شده</span><span class="mono">${fmt(s.discount_orders_count)} سفارش</span></div>
      </div>
    </div>
    ${low.length ? `<div class="card-sub" style="margin-top:12px;color:#FB7185">⚠️ ${settingsUiText('\u0645\u0648\u062c\u0648\u062f\u06cc \u06a9\u0645')}: ${low.map(p => esc(p.name)).join(', ')}</div>` : ''}
  `;
  root.appendChild(el);
}

/* ------------------------------------------------- dashboard: cron panel --- */
const CRON_STATUS_META = {
  ok: { label: 'سالم', color: '#22C55E' },
  warn: { label: 'هشدار', color: '#F59E0B' },
  error: { label: 'خطا', color: '#EF4444' },
  skip: { label: 'غیرفعال', color: '#94A3B8' },
};
function cronTime(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || isNaN(d)) return '—';
  return d.toLocaleString('fa-IR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}
function cronPanelBody(st) {
  const results = st.results || {};
  const order = (st.order || Object.keys(results)).filter(k => results[k]);
  const counts = { ok: 0, warn: 0, error: 0, skip: 0 };
  order.forEach(k => { counts[results[k].status] = (counts[results[k].status] || 0) + 1; });
  const badges = ['error', 'warn', 'ok', 'skip'].map(k => `
    <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;background:${CRON_STATUS_META[k].color}22;color:${CRON_STATUS_META[k].color};font-size:12px">
      <span style="width:8px;height:8px;border-radius:50%;background:${CRON_STATUS_META[k].color}"></span>${CRON_STATUS_META[k].label}: ${fmt(counts[k])}
    </span>`).join('');
  if (!order.length) {
    return { badges: '', tiles: '<div class="card-sub" style="padding:12px 0">هنوز هیچ بررسی‌ای اجرا نشده. اجرای خودکار چند دقیقه بعد از بالا آمدن بات انجام می‌شود، یا «اجرای همین الان» را بزنید.</div>' };
  }
  const tiles = order.map(k => {
    const r = results[k];
    const m = CRON_STATUS_META[r.status] || CRON_STATUS_META.skip;
    return `
      <div style="border:1px solid var(--border,rgba(128,128,128,.2));border-inline-start:4px solid ${m.color};border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:6px">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
          <strong>${esc(r.title)}</strong>
          <span style="color:${m.color};font-size:12px;white-space:nowrap">${m.label}</span>
        </div>
        <div style="font-size:13px;line-height:1.7;word-break:break-word">${esc(r.message)}</div>
        <div class="card-sub" style="font-size:11px">${cronTime(r.checked_at)}</div>
      </div>`;
  }).join('');
  return { badges, tiles };
}
function renderCronPanel(el, st) {
  const body = cronPanelBody(st);
  el.innerHTML = `
    <div class="card-head" style="flex-wrap:wrap;gap:10px">
      <h3>کرون‌ها — بررسی ساعتی سیستم‌ها</h3>
      <span class="card-sub">آخرین اجرا: ${cronTime(st.checked_at)}</span>
      <button class="btn btn-sm" id="cron-run-btn" ${st.requested ? 'disabled' : ''}>${st.requested ? 'در حال اجرا...' : 'اجرای همین الان'}</button>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 14px">${body.badges}</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px">${body.tiles}</div>`;
  const btn = $('#cron-run-btn', el);
  if (btn) btn.onclick = () => runCronNow(el, btn);
}
async function runCronNow(el, btn) {
  btn.disabled = true;
  btn.textContent = 'در حال اجرا...';
  const before = (await apiGet('/cron/status').catch(() => ({}))).checked_at || '';
  try { await apiPost('/cron/run'); } catch (e) { handleErr(e); renderCronPanel(el, await apiGet('/cron/status')); return; }
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 3000));
    if (!el.isConnected) return;
    let st;
    try { st = await apiGet('/cron/status'); } catch (e) { continue; }
    if (!st.requested && st.checked_at && st.checked_at !== before) { renderCronPanel(el, st); toast('بررسی‌ها انجام شد.'); return; }
  }
  toast('بات پاسخی نداد؛ مطمئن شوید سرویس بات در حال اجراست.', true);
  try { renderCronPanel(el, await apiGet('/cron/status')); } catch (e) { /* ignore */ }
}
async function appendCronPanel() {
  const root = content();
  if (!root || !ME || ME.tenant || !hasPerm('system')) return;
  let st;
  try { st = await apiGet('/cron/status'); } catch (e) { return; }
  const old = $('#cron-panel', root);
  if (old) old.remove();
  const el = document.createElement('div');
  el.className = 'card';
  el.id = 'cron-panel';
  el.style.marginTop = '16px';
  renderCronPanel(el, st);
  root.appendChild(el);
}

/* ============================================================ analytics === */
// نموداری بزرگ‌تر و با محور/برچسب برای صفحه‌ی «آمار پیشرفته» (برخلاف
// sparklinePath که برای کارت‌های کوچک داشبورد است و برچسب ندارد).
function trendChartSvg(points, w = 720, h = 220, pad = 36) {
  if (!points.length) return '<div class="card-sub">داده‌ای در این بازه نیست.</div>';
  const values = points.map(p => p.revenue);
  const max = Math.max(...values, 1);
  const step = (w - pad * 2) / Math.max(points.length - 1, 1);
  const xy = (v, i) => [pad + i * step, h - pad - (v / max) * (h - pad * 2)];
  const linePts = values.map((v, i) => xy(v, i));
  const line = linePts.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  const area = line + ` L${linePts[linePts.length - 1][0].toFixed(1)},${h - pad} L${linePts[0][0].toFixed(1)},${h - pad} Z`;
  const gridLines = [0, 0.25, 0.5, 0.75, 1].map(f => {
    const y = h - pad - f * (h - pad * 2);
    return `<line x1="${pad}" y1="${y}" x2="${w - pad}" y2="${y}" stroke="var(--border)" stroke-width="1" stroke-dasharray="3,4"/>
            <text x="${pad - 8}" y="${y + 3}" font-size="10" fill="var(--text-muted)" text-anchor="end">${fmt(Math.round(max * f))}</text>`;
  }).join('');
  // برای این‌که محور افقی شلوغ نشود، حداکثر ۸ برچسب پخش‌شده نشان داده می‌شود
  const labelEvery = Math.max(1, Math.ceil(points.length / 8));
  const xLabels = points.map((p, i) => i % labelEvery === 0 || i === points.length - 1
    ? `<text x="${xy(0, i)[0]}" y="${h - 10}" font-size="10" fill="var(--text-muted)" text-anchor="middle">${esc(p.bucket.slice(5))}</text>` : '').join('');
  const dots = linePts.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="3" fill="var(--brand,#8B5CF6)"><title>${esc(points[i].bucket)}: ${fmt(points[i].revenue)} تومان (${fmt(points[i].orders)} سفارش)</title></circle>`).join('');
  return `
    <svg viewBox="0 0 ${w} ${h}" style="width:100%;height:auto">
      ${gridLines}
      <path d="${area}" fill="var(--brand,#8B5CF6)" fill-opacity="0.14" stroke="none"/>
      <path d="${line}" fill="none" stroke="var(--brand,#8B5CF6)" stroke-width="2.2" stroke-linejoin="round"/>
      ${dots}
      ${xLabels}
    </svg>`;
}
function analyticsGatewayHtml(rows) {
  if (!rows.length) return '<div class="card-sub">تراکنشی در این بازه ثبت نشده.</div>';
  const colors = ['#8B5CF6', '#22D3EE', '#EC4899', '#F59E0B', '#34D399', '#60A5FA', '#F87171'];
  const total = rows.reduce((a, r) => a + r.revenue, 0) || 1;
  const donut = donutSegments(70, 70, 54, rows.map(r => ({ value: r.revenue })), colors, 20);
  const legend = rows.map((r, i) => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid var(--border,rgba(128,128,128,.15))">
      <span style="display:flex;align-items:center;gap:8px">
        <span style="width:10px;height:10px;border-radius:50%;background:${colors[i % colors.length]};display:inline-block"></span>
        ${esc(r.gateway)}
      </span>
      <span class="mono" style="text-align:left">
        ${fmt(r.revenue)} تومان · ${((r.revenue / total) * 100).toFixed(1)}٪<br>
        <span style="font-size:11px;color:var(--text-muted)">${fmt(r.success)}/${fmt(r.attempts)} موفق (${r.success_rate}٪)</span>
      </span>
    </div>`).join('');
  return `
    <div class="grid grid-2" style="gap:16px;align-items:center">
      <svg viewBox="0 0 140 140" style="width:150px;height:150px;margin:0 auto;display:block">${donut}</svg>
      <div>${legend}</div>
    </div>`;
}
function analyticsFunnelHtml(f) {
  const stages = [
    { label: 'عضو شدند', v: f.new_users, pct: 100 },
    { label: 'سفارش ثبت کردند', v: f.attempted_purchase, pct: f.start_to_attempt_rate },
    { label: 'خرید موفق', v: f.completed_purchase, pct: f.overall_conversion_rate },
  ];
  return stages.map(s => `
    <div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px">
        <span>${s.label}</span><span class="mono">${fmt(s.v)} (${s.pct}٪)</span>
      </div>
      <div style="height:10px;border-radius:5px;background:var(--border,rgba(128,128,128,.15));overflow:hidden">
        <div class="bar-fill" data-w="${Math.max(2, s.pct)}" style="height:100%;border-radius:5px;background:var(--brand,#8B5CF6);width:0"></div>
      </div>
    </div>`).join('');
}
function analyticsHeatmapHtml(heat) {
  const dayLabels = ['ی', 'د', 'س', 'چ', 'پ', 'ج', 'ش']; // sqlite %w: یکشنبه=۰ .. شنبه=۶
  const max = Math.max(...heat.flat(), 1);
  const rows = heat.map((rowVals, d) => `
    <div style="display:flex;align-items:center;gap:4px">
      <span style="width:16px;font-size:11px;color:var(--text-muted)">${dayLabels[d]}</span>
      <div style="display:flex;gap:2px;flex:1">
        ${rowVals.map((v, h) => `<div title="${dayLabels[d]} ساعت ${h}:00 — ${v} سفارش"
          style="flex:1;aspect-ratio:1;border-radius:2px;background:var(--brand,#8B5CF6);opacity:${v ? (0.12 + (v / max) * 0.88).toFixed(2) : 0.06}"></div>`).join('')}
      </div>
    </div>`).join('');
  return `<div style="display:flex;flex-direction:column;gap:3px">${rows}</div>
    <div class="card-sub" style="margin-top:6px">هر ستون یک ساعت از ۰۰ تا ۲۳ (به وقت تهران) — رنگ پررنگ‌تر یعنی سفارش بیشتر.</div>`;
}
function analyticsTableHtml(rows, cols) {
  if (!rows.length) return '<div class="card-sub">داده‌ای نیست.</div>';
  const head = cols.map(c => `<th>${esc(c.label)}</th>`).join('');
  const body = rows.map(r => `<tr>${cols.map(c => `<td>${c.render ? c.render(r) : esc(r[c.key] ?? '—')}</td>`).join('')}</tr>`).join('');
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}
const ANALYTICS_GRANULARITIES = [{ key: 'day', label: 'روزانه' }, { key: 'week', label: 'هفتگی' }, { key: 'month', label: 'ماهانه' }];
function getAnalyticsGranularity() {
  return localStorage.getItem('sv-analytics-granularity') || 'day';
}
async function renderAnalytics() {
  const range = getDashRange();
  const granularity = getAnalyticsGranularity();
  const q = (range ? `?start=${range.start}&end=${range.end}&` : '?') + `granularity=${granularity}`;
  const s = await apiGet('/dashboard/advanced' + q);
  const gChips = ANALYTICS_GRANULARITIES.map(g => `
    <button class="btn btn-sm dash-range-chip ${g.key === granularity ? 'active' : ''}" data-gran="${g.key}">${g.label}</button>`).join('');
  setContent(`
    <div class="hero" style="margin-bottom:16px">
      <div><h2>📈 آمار پیشرفته</h2><p class="card-sub">روند فروش، درگاه‌های پرداخت، منابع ورودی و نمایندگان، قیف تبدیل و ساعات پرفروش.</p></div>
    </div>
    <div id="analytics-range-slot"></div>

    <div class="card" style="margin-bottom:16px">
      <div class="card-head"><h3>روند درآمد و تعداد سفارش</h3><div class="dash-range-chips">${gChips}</div></div>
      ${trendChartSvg(s.revenue_trend.points)}
    </div>

    <div class="grid grid-2" style="gap:16px;align-items:start;margin-bottom:16px">
      <div class="card">
        <div class="card-head"><h3>تفکیک درگاه‌های پرداخت</h3></div>
        ${analyticsGatewayHtml(s.gateway_breakdown)}
      </div>
      <div class="card">
        <div class="card-head"><h3>قیف تبدیل کاربران تازه‌وارد</h3></div>
        ${analyticsFunnelHtml(s.funnel)}
        <div class="card-sub" style="margin-top:8px">
          🔁 بازگشتی: ${fmt(s.retention.returning_customers)} · 🆕 اولین‌خرید: ${fmt(s.retention.first_time_customers)} ·
          ⚠️ ریزش‌کرده (${s.retention.churn_window_days} روز): ${fmt(s.retention.churned_customers)}
        </div>
      </div>
    </div>

    <div class="grid grid-2" style="gap:16px;align-items:start;margin-bottom:16px">
      <div class="card">
        <div class="card-head"><h3>منابع ورودی کاربر (کمپین‌ها)</h3></div>
        ${analyticsTableHtml(s.campaign_performance, [
          { key: 'source', label: 'منبع' },
          { key: 'new_users', label: 'کاربر جدید', render: r => fmt(r.new_users) },
          { key: 'buyers', label: 'خریدار', render: r => fmt(r.buyers) },
          { key: 'conversion_rate', label: 'تبدیل', render: r => r.conversion_rate + '٪' },
          { key: 'revenue', label: 'درآمد', render: r => fmt(r.revenue) },
        ])}
      </div>
      <div class="card">
        <div class="card-head"><h3>عملکرد نمایندگان داخلی</h3></div>
        ${analyticsTableHtml(s.reseller_performance, [
          { key: 'name', label: 'نماینده' },
          { key: 'customers', label: 'مشتری', render: r => fmt(r.customers) },
          { key: 'orders', label: 'فروش', render: r => fmt(r.orders) },
          { key: 'revenue', label: 'درآمد', render: r => fmt(r.revenue) },
          { key: 'commission_paid', label: 'کمیسیون', render: r => fmt(r.commission_paid) },
        ])}
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h3>شلوغ‌ترین ساعات (نقشه‌ی حرارتی، به وقت تهران)</h3></div>
      ${analyticsHeatmapHtml(s.hourly_heatmap)}
    </div>
  `);
  $('#analytics-range-slot').insertAdjacentHTML('afterbegin', dashRangeBarHtml(s));
  wireDashRangeBar(renderAnalytics);
  $$('.dash-range-chip[data-gran]').forEach(btn => btn.addEventListener('click', () => {
    localStorage.setItem('sv-analytics-granularity', btn.dataset.gran);
    renderAnalytics();
  }));
  activateBarFills(content());
}

/* ----------------------------------------------------- dashboard: glass --- */
function donutSegments(cx, cy, r, data, colors, strokeWidth) {
  const total = data.reduce((a, b) => a + b.value, 0) || 1;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return data.map((d, i) => {
    const frac = d.value / total;
    const seg = `
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${colors[i % colors.length]}" stroke-width="${strokeWidth}"
        stroke-dasharray="${(frac * c).toFixed(2)} ${c.toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}"
        stroke-linecap="round" transform="rotate(-90 ${cx} ${cy})" class="glass-donut-seg"
        style="filter:drop-shadow(0 0 5px ${colors[i % colors.length]}99)"/>`;
    offset += frac * c;
    return seg;
  }).join('');
}

/* --------------------------------------------- dashboard: cyberpunk --- */
function cyberSmoothPath(values, w, h, pad = 6) {
  const max = Math.max(...values, 1), min = Math.min(...values, 0);
  const range = (max - min) || 1;
  const step = (w - pad * 2) / Math.max(values.length - 1, 1);
  const pts = values.map((v, i) => [pad + i * step, h - pad - ((v - min) / range) * (h - pad * 2)]);
  if (pts.length < 2) {
    const p = pts[0] || [pad, h - pad];
    return { line: `M${p[0]},${p[1]}`, area: `M${p[0]},${p[1]} L${p[0]},${h} Z`, last: p };
  }
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)} `;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += `C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)} `;
  }
  const last = pts[pts.length - 1];
  const area = d + `L${last[0].toFixed(1)},${h} L${pts[0][0].toFixed(1)},${h} Z`;
  return { line: d.trim(), area, last };
}
function cyberArc(cx, cy, r, pct, color, width) {
  const c = 2 * Math.PI * r;
  const off = c - Math.max(0, Math.min(100, pct)) / 100 * c;
  return `
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="rgba(0,255,156,.12)" stroke-width="${width}"/>
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="butt"
      stroke-dasharray="${c}" stroke-dashoffset="${c}" data-final="${off}" transform="rotate(-90 ${cx} ${cy})"
      class="cp-gauge-seg" style="filter:drop-shadow(0 0 6px ${color})"/>`;
}

function renderDashboardCyberpunk(s, sys) {
  const trend = cyberSmoothPath(s.daily_series.map(d => d.revenue), 620, 160, 10);
  const deltaUp = (s.revenue_change_pct ?? 0) >= 0;
  const gauges = sys ? [
    { pct: sys.cpu.percent, color: 'var(--cyan)', label: 'CPU', sub: `${sys.cpu.cores} CORES` },
    { pct: sys.ram.percent, color: 'var(--primary)', label: 'RAM', sub: `${sys.ram.used_gb}/${sys.ram.total_gb} GB` },
    { pct: sys.disk.percent, color: 'var(--emerald)', label: 'DISK', sub: `${sys.disk.used_gb}/${sys.disk.total_gb} GB` },
  ] : [];
  const gaugeHtml = gauges.map(g => `
    <div class="cp-gauge">
      <svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="50"/>${cyberArc(60, 60, 50, g.pct, g.color, 8)}</svg>
      <div class="cp-gauge-txt"><b class="mono" style="color:${g.color}">${g.pct}%</b><span>${g.label}</span></div>
      <span class="cp-gauge-sub mono">${g.sub}</span>
    </div>`).join('');

  const maxCatRev = Math.max(...s.category_breakdown.map(c => c.revenue), 1);
  const catRows = s.category_breakdown.map((c, i) => `
    <div class="cp-bar-row">
      <span class="cp-bar-label">${esc(c.name)}</span>
      <span class="cp-bar-track"><span class="cp-bar-fill" data-w="${(c.revenue / maxCatRev) * 100}"></span></span>
      <span class="cp-bar-val mono">${fmt(c.revenue)}</span>
    </div>`).join('') || '<span class="card-sub">// NO_DATA</span>';

  const prodRows = s.top_products.map((p, i) => `
    <div class="cp-list-row">
      <span class="cp-list-idx mono">${String(i + 1).padStart(2, '0')}</span>
      <span class="cp-list-name">${esc(p.name)}</span>
      <span class="cp-list-val mono">${fmt(p.orders)}x</span>
    </div>`).join('') || '<span class="card-sub">// NO_DATA</span>';

  setContent(`
    <div class="cp-hero">
      <div class="cp-hero-line"><span class="cp-prompt">root@shopvpn</span><span class="cp-path">:~$</span> <span class="cp-cmd">whoami</span></div>
      <h2>${greetingByHour().toUpperCase()}, ${esc(ME.username).toUpperCase()}<span class="cp-cursor">_</span></h2>
      <p class="mono">RANGE ${fmtDateOnly(s.start_date)} :: ${fmtDateOnly(s.end_date)}</p>
    </div>

    <div class="cp-stat-grid">
      <div class="cp-stat cp-stat-a">
        <span class="cp-stat-label">TOTAL_REVENUE</span>
        <span class="cp-stat-val mono" data-count="${s.revenue}">0</span>
        <span class="cp-stat-tag ${deltaUp ? 'up' : 'down'}">${deltaUp ? '▲' : '▼'} ${Math.abs(s.revenue_change_pct ?? 0)}%</span>
      </div>
      <div class="cp-stat"><span class="cp-stat-label">ORDERS_OK</span><span class="cp-stat-val mono" data-count="${s.approved}">0</span></div>
      <div class="cp-stat"><span class="cp-stat-label">USERS_TOTAL</span><span class="cp-stat-val mono" data-count="${s.total_users}">0</span></div>
      <div class="cp-stat"><span class="cp-stat-label">CONFIGS_LIVE</span><span class="cp-stat-val mono" data-count="${s.active_configs}">0</span><span class="cp-stat-tag">${fmt(s.open_tickets)} OPEN_TICKETS</span></div>
    </div>

    <div class="cp-panel" style="margin-top:16px">
      <div class="cp-panel-head">// REVENUE_TREND.LOG</div>
      <svg class="cp-trend" viewBox="0 0 620 160" preserveAspectRatio="none">
        <defs><linearGradient id="cpTrendFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--emerald)" stop-opacity=".35"/><stop offset="100%" stop-color="var(--emerald)" stop-opacity="0"/>
        </linearGradient></defs>
        <g class="cp-grid">${[0, 40, 80, 120, 160].map(y => `<line x1="0" y1="${y}" x2="620" y2="${y}"/>`).join('')}</g>
        <path d="${trend.area}" fill="url(#cpTrendFill)"/>
        <path d="${trend.line}" fill="none" stroke="var(--emerald)" stroke-width="2" style="filter:drop-shadow(0 0 6px var(--emerald))"/>
      </svg>
    </div>

    ${gaugeHtml ? `<div class="cp-panel" style="margin-top:16px"><div class="cp-panel-head">// SYS_RESOURCES</div><div class="cp-gauge-row">${gaugeHtml}</div></div>` : ''}

    <div class="cp-cols" style="margin-top:16px">
      <div class="cp-panel"><div class="cp-panel-head">// REVENUE_BY_CATEGORY</div>${catRows}</div>
      <div class="cp-panel"><div class="cp-panel-head">// TOP_PRODUCTS</div>${prodRows}</div>
    </div>

    <div style="margin-top:16px">${serverMapCardHtml()}</div>
  `);

  const root = content();
  $$('.cp-stat-val[data-count]', root).forEach(el => animateCount(el, Number(el.dataset.count)));
  requestAnimationFrame(() => setTimeout(() => {
    $$('.cp-gauge-seg[data-final]', root).forEach(seg => {
      seg.style.transition = 'stroke-dashoffset 1.1s cubic-bezier(.16,1,.3,1)';
      seg.style.strokeDashoffset = seg.dataset.final;
    });
    $$('.cp-bar-fill[data-w]', root).forEach(b => { b.style.width = b.dataset.w + '%'; });
  }, 60));
  mountServerMap();
}

/* ------------------------------------------------ dashboard: streetops --- */
function soSegBar(pct, segments = 12) {
  const p = Math.max(0, Math.min(100, Math.round(pct)));
  const filled = Math.round((p / 100) * segments);
  const color = p >= 60 ? 'var(--emerald)' : p >= 30 ? 'var(--amber)' : 'var(--rose)';
  let html = '';
  for (let i = 0; i < segments; i++) html += `<span class="so-seg${i < filled ? ' on' : ''}" style="${i < filled ? `background:${color};box-shadow:0 0 6px ${color}` : ''}"></span>`;
  return html;
}
function soWantedStars(ratio) {
  const level = Math.max(0, Math.min(5, Math.round(ratio * 5)));
  let html = '';
  for (let i = 0; i < 5; i++) html += `<span class="so-star${i < level ? ' on' : ''}">★</span>`;
  return html;
}
function renderDashboardStreetOps(s, sys) {
  const deltaUp = (s.revenue_change_pct ?? 0) >= 0;
  const wantedRatio = s.active_configs ? Math.min((s.open_tickets / s.active_configs) * 3, 1) : 0;
  const health = sys ? Math.max(0, 100 - (sys.cpu.percent + sys.ram.percent + sys.disk.percent) / 3) : 80;

  const resHtml = sys ? `
    <div class="so-panel">
      <div class="so-panel-head">SERVER VITALS</div>
      <div class="so-vital-row"><span>CPU</span>${soSegBar(sys.cpu.percent)}<b class="mono">${sys.cpu.percent}%</b></div>
      <div class="so-vital-row"><span>RAM</span>${soSegBar(sys.ram.percent)}<b class="mono">${sys.ram.percent}%</b></div>
      <div class="so-vital-row"><span>DISK</span>${soSegBar(sys.disk.percent)}<b class="mono">${sys.disk.percent}%</b></div>
    </div>` : '';

  const maxCatRev = Math.max(...s.category_breakdown.map(c => c.revenue), 1);
  const loadout = s.category_breakdown.map(c => `
    <div class="so-vital-row"><span>${esc(c.name)}</span>${soSegBar((c.revenue / maxCatRev) * 100, 16)}<b class="mono">${fmt(c.revenue)}</b></div>
  `).join('') || '<span class="card-sub">بدون داده</span>';

  const missions = s.top_products.map((p, i) => `
    <div class="so-mission-row"><span class="so-mission-check">✓</span><span class="so-mission-name">${esc(p.name)}</span><span class="so-mission-val mono">${fmt(p.orders)}x</span></div>
  `).join('') || '<span class="card-sub">بدون داده</span>';

  setContent(`
    <div class="so-hero">
      <div class="so-hero-bar top"></div>
      <div class="so-hero-body">
        <span class="so-hero-tag">OBJECTIVE</span>
        <h2>${greetingByHour()}، ${esc(ME.username)}</h2>
        <p class="mono">${fmtDateOnly(s.start_date)} — ${fmtDateOnly(s.end_date)}</p>
      </div>
      <div class="so-hero-bar bottom"></div>
    </div>

    <div class="so-stat-grid">
      <div class="so-stat so-stat-cash">
        <span class="so-stat-label">CASH</span>
        <span class="so-stat-val mono">$<span data-count="${s.revenue}">0</span></span>
        <span class="so-stat-tag ${deltaUp ? 'up' : 'down'}">${deltaUp ? '▲' : '▼'} ${Math.abs(s.revenue_change_pct ?? 0)}%</span>
      </div>
      <div class="so-stat"><span class="so-stat-label">CREW (کاربران)</span><span class="so-stat-val mono" data-count="${s.total_users}">0</span></div>
      <div class="so-stat"><span class="so-stat-label">MISSIONS DONE</span><span class="so-stat-val mono" data-count="${s.approved}">0</span></div>
      <div class="so-stat">
        <span class="so-stat-label">WANTED (تیکت باز)</span>
        <span class="so-stat-stars">${soWantedStars(wantedRatio)}</span>
        <span class="so-stat-tag">${fmt(s.open_tickets)} باز</span>
      </div>
    </div>

    <div class="so-cols" style="margin-top:16px">
      <div class="so-panel">
        <div class="so-panel-head">HEALTH &amp; PERFORMANCE</div>
        <div class="so-vital-row"><span>نرخ تبدیل</span>${soSegBar(s.conversion_rate)}<b class="mono">${fmt(Math.round(s.conversion_rate))}%</b></div>
        <div class="so-vital-row"><span>سلامت سرور</span>${soSegBar(health)}<b class="mono">${fmt(Math.round(health))}%</b></div>
        <div class="so-vital-row"><span>کانفیگ فعال</span>${soSegBar(Math.min(Math.round((s.active_configs / Math.max(s.total_users, 1)) * 100), 100))}<b class="mono">${fmt(s.active_configs)}</b></div>
      </div>
      ${resHtml}
    </div>

    <div class="so-cols" style="margin-top:16px">
      <div class="so-panel"><div class="so-panel-head">LOADOUT — درآمد به تفکیک دسته</div>${loadout}</div>
      <div class="so-panel"><div class="so-panel-head">MISSION LOG — پرفروش‌ترین محصولات</div>${missions}</div>
    </div>

    <div style="margin-top:16px">${serverMapCardHtml()}</div>
  `);

  const root = content();
  $$('.so-stat-val [data-count], .so-stat-val[data-count]', root).forEach(el => animateCount(el, Number(el.dataset.count)));
  mountServerMap();
}

/* ------------------------------------------------ dashboard: brutalist --- */
function renderDashboardBrutalist(s, sys) {
  const maxRev = Math.max(...s.daily_series.map(d => d.revenue), 1);
  const bruColors = ['#FFE600', '#2B6CFF', '#00C853', '#FF3B3B', '#FF3EA5'];
  const resHtml = sys ? `
    <div class="bru-res-grid">
      <div class="bru-res-card">
        <span class="bru-res-label">پردازنده CPU</span>
        <span class="bru-res-val mono">${sys.cpu.percent}٪</span>
        <span class="bru-res-track"><span class="bru-res-fill" data-w="${sys.cpu.percent}" style="background:#2B6CFF"></span></span>
        <span class="bru-res-sub">${sys.cpu.cores} هسته</span>
      </div>
      <div class="bru-res-card">
        <span class="bru-res-label">حافظه RAM</span>
        <span class="bru-res-val mono">${sys.ram.percent}٪</span>
        <span class="bru-res-track"><span class="bru-res-fill" data-w="${sys.ram.percent}" style="background:#FF8A00"></span></span>
        <span class="bru-res-sub">${sys.ram.used_gb} از ${sys.ram.total_gb} گیگ</span>
      </div>
      <div class="bru-res-card">
        <span class="bru-res-label">فضای دیسک</span>
        <span class="bru-res-val mono">${sys.disk.percent}٪</span>
        <span class="bru-res-track"><span class="bru-res-fill" data-w="${sys.disk.percent}" style="background:#00C853"></span></span>
        <span class="bru-res-sub">${sys.disk.used_gb} از ${sys.disk.total_gb} گیگ</span>
      </div>
    </div>` : '';
  const bars = s.daily_series.map((d, i) => `
    <div class="bru-bar-col" title="${d.date}: ${fmt(d.revenue)} تومان">
      <span class="bru-bar-val mono">${fmt(d.revenue)}</span>
      <div class="bru-bar" data-h="${Math.max((d.revenue / maxRev) * 100, 4)}" style="background:${bruColors[i % bruColors.length]}"></div>
    </div>`).join('');

  const deltaUp = (s.revenue_change_pct ?? 0) >= 0;

  const metrics = [
    { label: 'نرخ تبدیل', pct: s.conversion_rate, color: '#2B6CFF' },
    { label: 'سلامت سرور', pct: sys ? Math.max(0, 100 - (sys.cpu.percent + sys.ram.percent + sys.disk.percent) / 3) : 80, color: '#00C853' },
    { label: 'نسبت تیکت باز', pct: s.active_configs ? Math.min(Math.round((s.open_tickets / s.active_configs) * 100), 100) : 0, color: '#FF3B3B' },
    { label: 'ظرفیت کانفیگ', pct: Math.min(Math.round((s.active_configs / Math.max(s.total_users, 1)) * 100), 100), color: '#FF3EA5' },
  ];
  const metricBars = metrics.map(m => `
    <div class="bru-metric-row">
      <span class="bru-metric-label">${m.label}</span>
      <span class="bru-metric-track"><span class="bru-metric-fill" data-w="${m.pct}" style="background:${m.color}"></span></span>
      <span class="bru-metric-val mono">${fmt(Math.round(m.pct))}٪</span>
    </div>`).join('');

  const maxCatRev = Math.max(...s.category_breakdown.map(c => c.revenue), 1);
  const catStack = s.category_breakdown.map((c, i) => `
    <span class="bru-stack-seg" data-w="${(c.revenue / maxCatRev / s.category_breakdown.length) * 100 + (100 / s.category_breakdown.length) * 0}"
      style="background:${bruColors[i % bruColors.length]}; flex:${c.revenue}" title="${esc(c.name)}: ${fmt(c.revenue)}"></span>`).join('');
  const catLegend = s.category_breakdown.map((c, i) => `
    <span class="bru-legend-item"><i style="background:${bruColors[i % bruColors.length]}"></i>${esc(c.name)} — ${fmt(c.revenue)}</span>`).join('') || '<span class="card-sub">داده‌ای نیست</span>';

  const prodList = s.top_products.map((p, i) => `
    <div class="bru-prod-row">
      <span class="bru-prod-num mono">${(i + 1).toString().padStart(2, '۰')}</span>
      <span class="bru-prod-name">${esc(p.name)}</span>
      <span class="bru-prod-val mono">${fmt(p.orders)}</span>
    </div>`).join('') || '<span class="card-sub">داده‌ای نیست</span>';

  setContent(`
    <div class="bru-hero">
      <h2>${greetingByHour()}، ${esc(ME.username).toUpperCase()}</h2>
      <p>${fmtDateOnly(s.start_date)} تا ${fmtDateOnly(s.end_date)}</p>
    </div>

    ${resHtml}
    <div class="bru-grid-4">
      <div class="bru-block bru-yellow">
        <span class="bru-block-label">درآمد ۱۴ روز</span>
        <span class="bru-block-val mono" data-count="${s.revenue}">۰</span>
        <span class="bru-block-tag ${deltaUp ? '' : 'neg'}">${deltaUp ? '▲' : '▼'} ${Math.abs(s.revenue_change_pct ?? 0)}٪</span>
      </div>
      <div class="bru-block bru-white">
        <span class="bru-block-label">سفارش تایید شده</span>
        <span class="bru-block-val mono" data-count="${s.approved}">۰</span>
      </div>
      <div class="bru-block bru-black">
        <span class="bru-block-label">کاربران کل</span>
        <span class="bru-block-val mono" data-count="${s.total_users}">۰</span>
      </div>
      <div class="bru-block bru-white">
        <span class="bru-block-label">کانفیگ فعال / تیکت باز</span>
        <span class="bru-block-val mono" data-count="${s.active_configs}">۰</span>
        <span class="bru-block-tag">${fmt(s.open_tickets)} تیکت باز</span>
      </div>
    </div>

    <div class="bru-panel" style="margin-top:16px">
      <div class="bru-panel-head">روند فروش روزانه</div>
      <div class="bru-bars">${bars}</div>
    </div>

    <div class="bru-cols" style="margin-top:16px">
      <div class="bru-panel">
        <div class="bru-panel-head">شاخص‌های عملکرد</div>
        ${metricBars}
      </div>
      <div class="bru-panel">
        <div class="bru-panel-head">تفکیک درآمد</div>
        <div class="bru-stack">${catStack}</div>
        <div class="bru-legend">${catLegend}</div>
      </div>
    </div>

    <div class="bru-panel" style="margin-top:16px">
      <div class="bru-panel-head">پرفروش‌ترین محصولات</div>
      ${prodList}
    </div>

    <div style="margin-top:16px">${serverMapCardHtml()}</div>
  `);

  const root = content();
  $$('.bru-block-val[data-count]', root).forEach(el => animateCount(el, Number(el.dataset.count)));
  requestAnimationFrame(() => setTimeout(() => {
    $$('.bru-bar[data-h]', root).forEach(b => { b.style.height = b.dataset.h + '%'; });
    $$('.bru-metric-fill[data-w]', root).forEach(b => { b.style.width = b.dataset.w + '%'; });
    $$('.bru-res-fill[data-w]', root).forEach(b => { b.style.width = b.dataset.w + '%'; });
  }, 60));
  mountServerMap();
}

/* ---------------------------------------------------- dashboard: bento --- */
function sparklinePath(values, w, h, pad = 4) {
  const max = Math.max(...values, 1), min = Math.min(...values, 0);
  const range = (max - min) || 1;
  const step = (w - pad * 2) / Math.max(values.length - 1, 1);
  const pts = values.map((v, i) => [pad + i * step, h - pad - ((v - min) / range) * (h - pad * 2)]);
  const line = pts.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  const area = line + ` L${pts[pts.length - 1][0].toFixed(1)},${h} L${pts[0][0].toFixed(1)},${h} Z`;
  return { line, area, last: pts[pts.length - 1] };
}
function ringSegment(cx, cy, r, pct, color, width) {
  const c = 2 * Math.PI * r;
  const off = c - Math.max(0, Math.min(100, pct)) / 100 * c;
  return `
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--border)" stroke-width="${width}"/>
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round"
      stroke-dasharray="${c}" stroke-dashoffset="${c}" data-final="${off}" transform="rotate(-90 ${cx} ${cy})" class="bento-ring-seg"/>`;
}
function renderDashboardBento(s, sys) {
  const trend = sparklinePath(s.daily_series.map(d => d.revenue), 100, 40);
  const deltaUp = (s.revenue_change_pct ?? 0) >= 0;
  const maxCatRev = Math.max(...s.category_breakdown.map(c => c.revenue), 1);
  const widgetColors = ['w-blue', 'w-green', 'w-orange', 'w-pink', 'w-purple'];
  const resWidgets = sys ? `
    <div class="bw w-white span-2">
      <div class="bw-head"><span class="bw-label" style="color:var(--text-muted)">منابع سرور</span></div>
      <div class="bw-res-grid">
        <div class="bw-res-item">
          <div class="bw-res-top"><span>CPU</span><b class="mono">${sys.cpu.percent}٪</b></div>
          <span class="bw-res-track"><span class="bw-res-fill" data-w="${sys.cpu.percent}" style="background:#0A84FF"></span></span>
        </div>
        <div class="bw-res-item">
          <div class="bw-res-top"><span>RAM</span><b class="mono">${sys.ram.percent}٪</b></div>
          <span class="bw-res-track"><span class="bw-res-fill" data-w="${sys.ram.percent}" style="background:#FF9F0A"></span></span>
        </div>
        <div class="bw-res-item">
          <div class="bw-res-top"><span>دیسک</span><b class="mono">${sys.disk.percent}٪</b></div>
          <span class="bw-res-track"><span class="bw-res-fill" data-w="${sys.disk.percent}" style="background:#30D158"></span></span>
        </div>
      </div>
    </div>` : '';
  const catBento = s.category_breakdown.slice(0, 4).map((c, i) => `
    <div class="bw-mini ${widgetColors[i % widgetColors.length]}">
      <span class="bw-mini-name">${esc(c.name)}</span>
      <span class="bw-mini-val mono">${fmt(c.revenue)}</span>
    </div>`).join('') || `<span class="card-sub">داده‌ای نیست</span>`;
  const prodBento = s.top_products.slice(0, 4).map((p, i) => `
    <div class="bw-row">
      <span class="bw-row-dot ${widgetColors[i % widgetColors.length]}"></span>
      <span class="bw-row-name">${esc(p.name)}</span>
      <span class="bw-row-val mono">${fmt(p.orders)}</span>
    </div>`).join('') || `<span class="card-sub">داده‌ای نیست</span>`;

  const ringsData = [
    { pct: s.conversion_rate, color: 'var(--primary)', label: 'تبدیل' },
    { pct: sys ? Math.max(0, 100 - (sys.cpu.percent + sys.ram.percent + sys.disk.percent) / 3) : 80, color: 'var(--emerald)', label: 'سلامت' },
    { pct: s.active_configs ? Math.min(Math.round((s.open_tickets / s.active_configs) * 100), 100) : 0, color: 'var(--rose)', label: 'تیکت' },
  ];

  setContent(`
    <div class="bento-grid">
      <div class="bw w-blue span-2 rows-2">
        <div class="bw-head">
          <span class="bw-label">درآمد ۱۴ روز اخیر</span>
          <span class="bw-badge ${deltaUp ? 'up' : 'down'}">${deltaUp ? '▲' : '▼'} ${Math.abs(s.revenue_change_pct ?? 0)}%</span>
        </div>
        <span class="bw-value mono" data-count="${s.revenue}">۰</span>
        <svg class="bw-trend" viewBox="0 0 100 40" preserveAspectRatio="none">
          <defs><linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#fff" stop-opacity=".55"/><stop offset="100%" stop-color="#fff" stop-opacity="0"/>
          </linearGradient></defs>
          <path d="${trend.area}" fill="url(#trendFill)"/>
          <path d="${trend.line}" fill="none" stroke="#fff" stroke-width="2"/>
        </svg>
      </div>

      <div class="bw w-green">
        <span class="bw-label">کاربران کل</span>
        <span class="bw-value mono" data-count="${s.total_users}">۰</span>
        <span class="bw-sub">${fmt(s.new_users)}+ جدید</span>
      </div>
      <div class="bw w-orange">
        <span class="bw-label">سفارش تایید شده</span>
        <span class="bw-value mono" data-count="${s.approved}">۰</span>
        <span class="bw-sub">${s.conversion_rate}٪ نرخ تبدیل</span>
      </div>

      <div class="bw w-white rows-2 span-2 bento-rings-card">
        <div class="bw-head"><span class="bw-label" style="color:var(--text-muted)">شاخص‌های کلیدی</span></div>
        <div class="bento-rings">
          <svg viewBox="0 0 120 120">
            ${ringSegment(60, 60, 50, ringsData[0].pct, ringsData[0].color, 10)}
            ${ringSegment(60, 60, 36, ringsData[1].pct, ringsData[1].color, 10)}
            ${ringSegment(60, 60, 22, ringsData[2].pct, ringsData[2].color, 10)}
          </svg>
          <div class="bento-rings-legend">
            ${ringsData.map(r => `<span><i style="background:${r.color}"></i>${r.label} · ${fmt(Math.round(r.pct))}٪</span>`).join('')}
          </div>
        </div>
      </div>

      <div class="bw w-pink">
        <span class="bw-label">کانفیگ فعال</span>
        <span class="bw-value mono" data-count="${s.active_configs}">۰</span>
      </div>
      <div class="bw w-purple">
        <span class="bw-label">تیکت باز</span>
        <span class="bw-value mono" data-count="${s.open_tickets}">۰</span>
      </div>

      <div class="bw w-white span-2">
        <div class="bw-head"><span class="bw-label" style="color:var(--text-muted)">تفکیک درآمد</span></div>
        <div class="bw-mini-grid">${catBento}</div>
      </div>
      <div class="bw w-white span-2">
        <div class="bw-head"><span class="bw-label" style="color:var(--text-muted)">پرفروش‌ترین محصولات</span></div>
        ${prodBento}
      </div>
      ${resWidgets}
    </div>

    ${serverMapCardHtml()}
  `);

  const root = content();
  $$('.bw-value[data-count]', root).forEach(el => animateCount(el, Number(el.dataset.count)));
  requestAnimationFrame(() => setTimeout(() => {
    $$('.bento-ring-seg', root).forEach(seg => {
      seg.style.transition = 'stroke-dashoffset 1.1s cubic-bezier(.16,1,.3,1)';
      seg.style.strokeDashoffset = seg.dataset.final;
    });
    $$('.bw-res-fill[data-w]', root).forEach(b => { b.style.width = b.dataset.w + '%'; });
  }, 60));
  mountServerMap();
}

/* --------------------------------------------------- dashboard: android -- */
// متریال دیزاین ۳: کارت هیرو برجسته برای درآمد، گرید کارت‌های آماری با
// آیکون تونال، و دو پنل لیست مانند (تفکیک درآمد / پرفروش‌ترین‌ها) با
// نوار پیشرفت خطی به سبک متریال؛ در پایین وضعیت منابع سرور هم به همین شکل.
function renderDashboardAndroid(s, sys) {
  const trend = sparklinePath(s.daily_series.map(d => d.revenue), 100, 36);
  const deltaUp = (s.revenue_change_pct ?? 0) >= 0;
  const maxCatRev = Math.max(...s.category_breakdown.map(c => c.revenue), 1);
  const maxProdOrders = Math.max(...s.top_products.map(p => p.orders), 1);

  const statCards = [
    { icon: 'users', label: 'کاربران کل', value: s.total_users, sub: `${fmt(s.new_users)}+ جدید`, tone: 1 },
    { icon: 'check', label: 'سفارش تایید شده', value: s.approved, sub: `${s.conversion_rate}٪ نرخ تبدیل`, tone: 2 },
    { icon: 'config', label: 'کانفیگ فعال', value: s.active_configs, sub: null, tone: 3 },
    { icon: 'ticket', label: 'تیکت باز', value: s.open_tickets, sub: null, tone: 4 },
  ];

  const catRows = s.category_breakdown.slice(0, 5).map(c => `
    <div class="and-list-row">
      <span class="and-list-name">${esc(c.name)}</span>
      <span class="and-bar-track"><span class="and-bar-fill" data-w="${Math.max(4, Math.round(c.revenue / maxCatRev * 100))}"></span></span>
      <span class="and-list-val mono">${fmt(c.revenue)}</span>
    </div>`).join('') || `<span class="card-sub">داده‌ای نیست</span>`;

  const prodRows = s.top_products.slice(0, 5).map((p, i) => `
    <div class="and-list-row and-list-row-rank">
      <span class="and-rank">${i + 1}</span>
      <span class="and-list-name">${esc(p.name)}</span>
      <span class="and-bar-track and-bar-track-sm"><span class="and-bar-fill" data-w="${Math.max(4, Math.round(p.orders / maxProdOrders * 100))}"></span></span>
      <span class="and-list-val mono">${fmt(p.orders)}</span>
    </div>`).join('') || `<span class="card-sub">داده‌ای نیست</span>`;

  const resPanel = sys ? `
    <div class="and-panel card">
      <div class="and-panel-head">منابع سرور</div>
      ${[
        { label: 'CPU', pct: sys.cpu.percent },
        { label: 'RAM', pct: sys.ram.percent },
        { label: 'دیسک', pct: sys.disk.percent },
      ].map(r => `
        <div class="and-list-row">
          <span class="and-list-name">${r.label}</span>
          <span class="and-bar-track"><span class="and-bar-fill" data-w="${r.pct}"></span></span>
          <span class="and-list-val mono">${r.pct}٪</span>
        </div>`).join('')}
    </div>` : '';

  setContent(`
    <div class="and-hero card">
      <div class="and-hero-top">
        <span class="and-hero-label">درآمد ۱۴ روز اخیر</span>
        <span class="and-chip ${deltaUp ? 'up' : 'down'}">${deltaUp ? '▲' : '▼'} ${Math.abs(s.revenue_change_pct ?? 0)}٪</span>
      </div>
      <span class="and-hero-value mono" data-count="${s.revenue}">۰</span>
      <svg class="and-hero-spark" viewBox="0 0 100 36" preserveAspectRatio="none">
        <defs><linearGradient id="andTrendFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--primary)" stop-opacity=".35"/><stop offset="100%" stop-color="var(--primary)" stop-opacity="0"/>
        </linearGradient></defs>
        <path d="${trend.area}" fill="url(#andTrendFill)"/>
        <path d="${trend.line}" fill="none" stroke="var(--primary)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>

    <div class="and-grid">
      ${statCards.map(c => `
        <div class="card and-stat">
          <span class="and-stat-icon and-stat-icon-${c.tone}">${svg(c.icon === 'users' ? 'users' : c.icon === 'check' ? 'check' : c.icon === 'config' ? 'catalog' : 'tickets')}</span>
          <span class="and-stat-value mono" data-count="${c.value}">۰</span>
          <span class="and-stat-label">${c.label}</span>
          ${c.sub ? `<span class="and-stat-sub">${c.sub}</span>` : ''}
        </div>`).join('')}
    </div>

    <div class="and-row">
      <div class="and-panel card">
        <div class="and-panel-head">تفکیک درآمد</div>
        ${catRows}
      </div>
      <div class="and-panel card">
        <div class="and-panel-head">پرفروش‌ترین محصولات</div>
        ${prodRows}
      </div>
    </div>

    ${resPanel}
    ${serverMapCardHtml()}
  `);

  const root = content();
  $$('.and-hero-value[data-count], .and-stat-value[data-count]', root).forEach(el => animateCount(el, Number(el.dataset.count)));
  requestAnimationFrame(() => setTimeout(() => {
    $$('.and-bar-fill[data-w]', root).forEach(b => { b.style.width = b.dataset.w + '%'; });
  }, 60));
  mountServerMap();
}

/* ----------------------------------------------------- dashboard: flat --- */


/* ------------------------------------------------------ dashboard: clay --- */

/* ----------------------------------------------------- dashboard: paper --- */

/* -------------------------------------------------- dashboard: obsidian --- */
/* ------------------------------------------------------- dashboard: warp --- */
function warpRingHtml(pct, color, label, value) {
  const p = Math.max(0, Math.min(100, Math.round(pct)));
  return `
    <div class="warp-ring-item">
      <div class="ring warp-ring" style="--ring-a:${color}" data-pct="${p}"><span>${p}٪</span></div>
      <div class="warp-ring-info"><strong>${value}</strong><span>${label}</span></div>
    </div>`;
}


/* ====================================================== world map === */
// ویجت مشترک «نقشه‌ی جهانی سرورها» — در هر ۵ تم از طریق کلاس عمومی .card
// (که هرکدام از تم‌ها استایل خودش را رویش اعمال می‌کند) و متغیرهای CSS
// رنگ تم فعلی (--primary/--emerald/--rose/...) نمایش داده می‌شود؛ یعنی
// یک پیاده‌سازی، هم‌رنگ با هر پنج تم.

// نسخه‌ی واقعی نقشه (خطوط ساحلی) دیگر مستقیماً از CDNهای خارجی گرفته‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
// نمی‌شود — چون اگر مرورگر ادمین به آن دامنه‌ها دسترسی نداشته باشد (فیلتر/
// قطعی)، دانلود ساکت fail می‌شد و فقط گرید خالی می‌ماند. حالا خودِ سرور
// پنل یک‌بار این کار را می‌کند (و روی دیسک cache می‌کند) و ما فقط از
// endpoint خودمان (هم‌مبدأ، بدون نیاز به هیچ CDN) می‌خوانیم. نتیجه هم در
// localStorage کش می‌شود تا در بازدیدهای بعدی اصلاً نیازی به فراخوانی
// مجدد نباشد.
const SV_MAP_CACHE_KEY = 'sv_map_real_v4'; // v4: مسیر ساده‌سازی‌شده (رفع هنگ زوم روی موبایل) — کلید عوض شد تا کش سنگین قبلی مرورگر باطل شود
let SV_REAL = null;
let SV_REAL_PROMISE = null;

async function svEnsureRealMap() {
  if (SV_REAL) return SV_REAL;
  if (SV_REAL_PROMISE) return SV_REAL_PROMISE;
  SV_REAL_PROMISE = (async () => {
    // اول کش محلی را امتحان کن — سریع و بدون نیاز به درخواست جدید
    try {
      const cached = localStorage.getItem(SV_MAP_CACHE_KEY);
      if (cached) {
        SV_REAL = JSON.parse(cached);
        return SV_REAL;
      }
    } catch (e) { /* کش خراب/در دسترس نیست — بی‌اهمیت */ }

    try {
      const data = await apiGet('/dashboard/world-map');
      if (!data || !data.ok || !data.land_path) return null;
      SV_REAL = { landPathD: data.land_path };
      try { localStorage.setItem(SV_MAP_CACHE_KEY, JSON.stringify(SV_REAL)); } catch (e) { /* بی‌اهمیت */ }
      return SV_REAL;
    } catch (e) {
      return null; // اتصال به پنل خودمان هم ناموفق بود — همان گرید ساده باقی می‌ماند
    }
  })();
  return SV_REAL_PROMISE;
}

// معادل خطیِ d3.geoEquirectangular().fitSize([1000, 500], {type:'Sphere'})
// است، پس چه نقشه‌ی دقیق لود شده باشد چه نه، پین‌ها دقیقاً روی همان
// تصویربرداری خطوط ساحلی می‌افتند.
function svProject(lat, lon) {
  const x = (Number(lon) + 180) / 360 * 1000;
  const y = (90 - Number(lat)) / 180 * 500;
  return [x, y];
}

function svMapGraticule() {
  let out = '';
  for (let x = 0; x <= 1000; x += 100) out += `<line x1="${x}" y1="0" x2="${x}" y2="500" class="${x === 500 ? 'sv-map-meridian' : ''}"></line>`;
  for (let y = 0; y <= 500; y += 62.5) out += `<line x1="0" y1="${y.toFixed(1)}" x2="1000" y2="${y.toFixed(1)}" class="${Math.abs(y - 250) < 1 ? 'sv-map-equator' : ''}"></line>`;
  return out;
}

// تا وقتی نقشه‌ی دقیق (از CDN یا کش) لود نشده، بک‌گراند فقط همان گرید
// عرض/طول جغرافیایی (svMapGraticule) است — بدون هیچ چندضلعی تقریبی؛ به
// محض آماده‌شدن svEnsureRealMap، خطوط ساحلی واقعی جای‌گزین می‌شوند.
function svMapLandPaths() {
  return '';
}

function svFlagEmoji(cc) {
  if (!cc || cc.length !== 2) return '🌐';
  try { return String.fromCodePoint(...[...cc.toUpperCase()].map(c => 127397 + c.charCodeAt(0))); }
  catch (e) { return '🌐'; }
}

const SV_STATUS_LABEL = { online: 'آنلاین', offline: 'آفلاین', unknown: 'نامشخص' };

function serverMapCardHtml() {
  return `
  <div class="card sv-map-card">
    <div class="card-head sv-map-head">
      <h3>🗺️ نقشه‌ی جهانی سرورها</h3>
      <div class="sv-map-actions">
        <span class="sv-map-updated" id="sv-map-updated"></span>
        <button class="btn btn-sm" id="sv-map-refresh-btn" hidden>↻ اسکن مجدد</button>
      </div>
    </div>
    <p class="card-sub">لینک ساب مادر را وارد کن تا کانفیگ‌هایش بر اساس IP سرور روی نقشه مشخص شوند.</p>
    <div class="sv-map-linkrow">
      <input type="text" id="sv-map-link-input" class="input" dir="ltr" placeholder="https://example.com/sub/xxxxx">
      <button class="btn btn-primary btn-sm" id="sv-map-scan-btn">بررسی و رسم نقشه</button>
    </div>
    <div class="sv-map-checkrow">
      <label>هر
        <input type="number" id="sv-map-interval-input" class="input input-sm" min="1" max="120" style="width:64px">
        دقیقه چک شود، بعد از
        <input type="number" id="sv-map-streak-input" class="input input-sm" min="1" max="10" style="width:56px">
        دور متوالیِ آفلاین اعلان بده
      </label>
      <button class="btn btn-sm" id="sv-map-check-save-btn">ذخیره</button>
    </div>
    <div class="sv-map-stats" id="sv-map-stats"></div>
    <div class="sv-map-wrap" id="sv-map-wrap">
      <svg id="sv-map-svg" viewBox="0 0 1000 500" preserveAspectRatio="xMidYMid meet">
        <g class="sv-map-grid">${svMapGraticule()}</g>
        <g class="sv-map-land">${svMapLandPaths()}</g>
        <g class="sv-map-markers" id="sv-map-markers"></g>
      </svg>
      <div class="sv-map-tooltip" id="sv-map-tooltip" hidden></div>
      <div class="sv-map-empty" id="sv-map-empty" hidden>هنوز لینک ساب مادری ثبت نشده — یکی وارد کن و «بررسی و رسم نقشه» را بزن.</div>
      <div class="sv-map-loading" id="sv-map-loading" hidden><span class="sv-map-spinner"></span>در حال دریافت و جئولوکیت کانفیگ‌ها…</div>
    </div>
    <div class="sv-map-legend">
      <span><i class="dot online"></i>آنلاین</span>
      <span><i class="dot offline"></i>آفلاین</span>
      <span><i class="dot unknown"></i>نامشخص</span>
    </div>
    <div class="sv-map-list" id="sv-map-list"></div>
  </div>`;
}

function svTooltipHtml(s) {
  const protoBadges = (s.protocols || []).map(p => `<span class="chip">${esc(p.name)}</span>`).join(' ');
  const ipLine = s.ip || 'نامشخص';
  const srcNote = s.source === 'label+geoip'
    ? '🏷️📡 نام کانفیگ + موقعیت دقیق IP (هر دو هم‌راستا)'
    : s.source === 'label'
      ? '🏷️ بر اساس نام کانفیگ (سرور پشت CDN است، مختصات تقریبی مرکز کشور)'
      : '📡 بر اساس موقعیت واقعی IP';
  return `
    <div class="sv-tt-head">${svFlagEmoji(s.country_code)} <b>${esc(s.city || s.country || '—')}</b><span class="sv-tt-country">${esc(s.country || '')}</span></div>
    <div class="sv-tt-name">${esc(s.remark || '—')}</div>
    <div class="sv-tt-ip mono">${esc(ipLine)}</div>
    <div class="sv-tt-row">وضعیت: <b class="sv-tt-status-${s.status}">${SV_STATUS_LABEL[s.status] || 'نامشخص'}</b>
      <span class="sv-tt-check-method">${s.check_method === 'protocol' ? '(بر اساس همین کانفیگ)' : '(فقط باز بودن پورت)'}</span>
    </div>
    <div class="sv-tt-protocols">${protoBadges}</div>
    <div class="sv-tt-source">${srcNote}</div>`;
}

function svShowTooltip(s) {
  const root = content();
  const wrap = $('#sv-map-wrap', root);
  const tip = $('#sv-map-tooltip', root);
  const svgEl = $('#sv-map-svg', root);
  if (!wrap || !tip || !svgEl || s.lat == null || s.lon == null) return;
  const [vx, vy] = svProject(s.lat, s.lon);
  const svgRect = svgEl.getBoundingClientRect();
  const wrapRect = wrap.getBoundingClientRect();
  const px = (svgRect.left - wrapRect.left) + vx * (svgRect.width / 1000);
  const py = (svgRect.top - wrapRect.top) + vy * (svgRect.height / 500);
  tip.innerHTML = svTooltipHtml(s);
  tip.hidden = false;
  tip.style.left = Math.max(4, Math.min(px + 14, wrapRect.width - 236)) + 'px';
  tip.style.top = Math.max(4, Math.min(py + 14, wrapRect.height - 110)) + 'px';
}
function svHideTooltip() {
  const tip = $('#sv-map-tooltip', content());
  if (tip) tip.hidden = true;
}

// چون هر کانفیگ حالا پین جدای خودش را دارد، ممکن است چند کانفیگ دقیقاً
// روی یک سرور (همان lat/lon) باشند — بدون این تابع دقیقاً روی هم می‌افتند
// و فقط بالایی‌شان قابل کلیک می‌ماند. این تابع پین‌های هم‌مکان را به‌صورت
// یک دایره‌ی کوچک دور نقطه‌ی اصلی پخش می‌کند تا همه جدا و کلیک‌پذیر بمانند.
function svSpreadOverlapping(points) {
  const buckets = new Map();
  points.forEach((p, i) => {
    const key = p.x.toFixed(1) + ',' + p.y.toFixed(1);
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(i);
  });
  const out = points.map(p => ({ x: p.x, y: p.y }));
  buckets.forEach(idxs => {
    if (idxs.length < 2) return;
    const spread = Math.min(3 + idxs.length * 0.6, 9);
    idxs.forEach((idx, j) => {
      const angle = (2 * Math.PI * j) / idxs.length;
      out[idx].x += Math.cos(angle) * spread;
      out[idx].y += Math.sin(angle) * spread;
    });
  });
  return out;
}

function svRenderMarkers(servers) {
  const root = content();
  const g = $('#sv-map-markers', root);
  if (!g) return;
  const positions = servers.map(s => (s.lat != null && s.lon != null) ? (([x, y]) => ({ x, y }))(svProject(s.lat, s.lon)) : null);
  const spread = svSpreadOverlapping(positions.map(p => p || { x: -9999, y: -9999 }));
  const r = 6; // چون هر پین حالا دقیقاً یک کانفیگ است، اندازه‌ی ثابت (بدون وزن‌دهی به تعداد) واضح‌تر است
  g.innerHTML = servers.map((s, i) => {
    if (!positions[i]) return '';
    const { x, y } = spread[i];
    const st = SV_STATUS_LABEL[s.status] ? s.status : 'unknown';
    return `<g class="sv-map-pin ${st}" data-idx="${i}" tabindex="0">
      <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(r + 6).toFixed(1)}" class="sv-map-pulse"></circle>
      <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" class="sv-map-dot"></circle>
    </g>`;
  }).join('');
  $$('.sv-map-pin', g).forEach(el => {
    const s = servers[+el.dataset.idx];
    el.addEventListener('mouseenter', () => svShowTooltip(s));
    el.addEventListener('click', () => svShowTooltip(s));
    el.addEventListener('mouseleave', svHideTooltip);
  });
}

function svStatsHtml(data) {
  return `
    <span class="chip">🖥️ ${fmt(data.total_servers)} سرور</span>
    <span class="chip">🌍 ${fmt(data.total_countries)} کشور</span>
    <span class="chip">⚙️ ${fmt(data.total_configs)} کانفیگ</span>`;
}

function svServerListHtml(servers) {
  return servers.map((s, i) => `
    <div class="sv-map-list-row" data-idx="${i}">
      <i class="dot ${SV_STATUS_LABEL[s.status] ? s.status : 'unknown'}"></i>
      <span class="sv-ml-flag">${svFlagEmoji(s.country_code)}</span>
      <span class="sv-ml-name">${esc(s.remark || s.city || s.country || '—')}<small>${esc(s.country || '')}</small></span>
      <span class="sv-ml-ip mono">${esc(s.ip || '—')}</span>
      <span class="sv-ml-count mono">${esc((s.protocols && s.protocols[0] && s.protocols[0].name) || '')}</span>
    </div>`).join('');
}

function svFmtTime(ts) {
  if (!ts) return '';
  try { return 'آخرین اسکن: ' + new Date(ts * 1000).toLocaleString('fa-IR'); } catch (e) { return ''; }
}

async function mountServerMap() {
  const root = content();
  const card = $('.sv-map-card', root);
  if (!card) return;

  const input = $('#sv-map-link-input', root);
  const scanBtn = $('#sv-map-scan-btn', root);
  const refreshBtn = $('#sv-map-refresh-btn', root);
  const loadingEl = $('#sv-map-loading', root);
  const emptyEl = $('#sv-map-empty', root);
  const updatedEl = $('#sv-map-updated', root);
  let currentServers = [];

  // نسخه‌ی دقیق نقشه را در پس‌زمینه بارگیری کن و به‌محض آماده‌شدن جای‌گزین
  // خطوط تقریبی/گرید کن — بدون این‌که منتظرش بمانیم.
  svEnsureRealMap().then(real => {
    if (!real) return;
    const r = content();
    if (!$('.sv-map-card', r)) return; // کاربر جابه‌جا شده
    const landG = $('#sv-map-wrap .sv-map-land', r);
    if (landG) landG.innerHTML = `<path d="${real.landPathD}" class="sv-map-land-poly"></path>`;
    if (currentServers.length) svRenderMarkers(currentServers);
  });

  const paint = (data) => {
    if (!$('.sv-map-card', content())) return; // کاربر به تب دیگری رفته
    if (!data || !data.ok) {
      $('#sv-map-stats', root).innerHTML = '';
      svRenderMarkers([]);
      $('#sv-map-list', root).innerHTML = '';
      if (data && data.error === 'no_link') { if (emptyEl) emptyEl.hidden = false; }
      else if (data && data.error) toast(data.error, true);
      return;
    }
    currentServers = data.servers || [];
    if (emptyEl) emptyEl.hidden = true;
    $('#sv-map-stats', root).innerHTML = svStatsHtml(data);
    svRenderMarkers(currentServers);
    $('#sv-map-list', root).innerHTML = svServerListHtml(currentServers);
    $$('.sv-map-list-row', root).forEach(row => row.addEventListener('click', () => svShowTooltip(currentServers[+row.dataset.idx])));
    if (updatedEl) updatedEl.textContent = svFmtTime(data.generated_at);
    if (refreshBtn) refreshBtn.hidden = false;
  };

  const doScan = async (refresh) => {
    if (loadingEl) loadingEl.hidden = false;
    if (emptyEl) emptyEl.hidden = true;
    try {
      const data = await apiGet(`/dashboard/servers-map${refresh ? '?refresh=1' : ''}`);
      paint(data);
    } catch (e) { handleErr(e); }
    finally { if (loadingEl) loadingEl.hidden = true; }
  };

  try {
    const s = await apiGet('/settings/master-sub');
    if (!$('.sv-map-card', content())) return;
    if (input) input.value = s.link || '';
    if (s.link) { if (refreshBtn) refreshBtn.hidden = false; await doScan(false); }
    else if (emptyEl) emptyEl.hidden = false;
  } catch (e) { /* بی‌اهمیت — کاربر می‌تواند دستی لینک بدهد */ }

  const intervalInput = $('#sv-map-interval-input', root);
  const streakInput = $('#sv-map-streak-input', root);
  const checkSaveBtn = $('#sv-map-check-save-btn', root);

  try {
    const cs = await apiGet('/settings/server-check');
    if (!$('.sv-map-card', content())) return;
    if (intervalInput) {
      intervalInput.value = cs.interval_min;
      intervalInput.min = cs.min_interval_min;
      intervalInput.max = cs.max_interval_min;
    }
    if (streakInput) {
      streakInput.value = cs.offline_streak;
      streakInput.min = cs.min_offline_streak;
      streakInput.max = cs.max_offline_streak;
    }
  } catch (e) { /* بی‌اهمیت — مقادیر پیش‌فرض روی سرور اعمال می‌شود */ }

  if (checkSaveBtn) checkSaveBtn.addEventListener('click', async () => {
    const interval_min = parseInt(intervalInput.value, 10);
    const offline_streak = parseInt(streakInput.value, 10);
    if (!interval_min || !offline_streak) { toast('مقادیر را درست وارد کن', true); return; }
    checkSaveBtn.disabled = true;
    try {
      await apiPost('/settings/server-check', { interval_min, offline_streak });
      const totalMin = interval_min * offline_streak;
      toast(`ذخیره شد — اعلان قطعی بعد از حدود ${totalMin} دقیقه قطعی پیوسته ارسال می‌شود.`);
    } catch (e) { handleErr(e); }
    finally { checkSaveBtn.disabled = false; }
  });

  if (scanBtn) scanBtn.addEventListener('click', async () => {
    const link = (input.value || '').trim();
    if (!link) { toast('لینک ساب را وارد کن', true); return; }
    scanBtn.disabled = true;
    try {
      await apiPost('/settings/master-sub', { link });
      await doScan(true);
      toast('نقشه به‌روزرسانی شد.');
    } catch (e) { handleErr(e); }
    finally { scanBtn.disabled = false; }
  });

  if (refreshBtn) refreshBtn.addEventListener('click', () => doScan(true));

  // وضعیت آنلاین/آفلاین نباید تا زمان رفرش دستی صفحه ثابت بماند.
  // هر ۶۰ ثانیه یک اسکن واقعی انجام می‌دهیم؛ فقط وقتی همین کارت در DOM
  // وجود دارد، تا با جابه‌جایی تب‌ها درخواست اضافه ایجاد نشود.
  const statusTimer = setInterval(() => {
    const activeRoot = content();
    if (!$('.sv-map-card', activeRoot)) {
      clearInterval(statusTimer);
      return;
    }
    doScan(true);
  }, 60 * 1000);
}

/* ============================================================ orders === */
let ordersStatus = 'pending';
let ordersFilters = { q: '', product_id: '', date_from: '', date_to: '' };
let ordersProductsCache = null;
const orderSurveySummaryBtn = () => `<button class="btn btn-sm" data-survey-summary="1">📊 نتایج نظرسنجی</button>`;
function orderSurveyBtn(o, canAct) {
  if (o.survey_rating) return `<span class="badge badge-approved">⭐ ${fmt(o.survey_rating)} / ۵</span>`;
  if (!canAct) return o.survey_sent ? '<span class="mono">ارسال شد</span>' : '<span class="mono">-</span>';
  return `<button class="btn btn-sm" data-survey="${o.id}">${o.survey_sent ? 'ارسال مجدد نظرسنجی' : '🗳 ارسال نظرسنجی'}</button>`;
}
async function openSurveySummaryModal() {
  try {
    const rows = await apiGet('/order-surveys/summary');
    openModal('نتایج نظرسنجی به تفکیک پنل', `
      <div class="table-wrap"><table>
        <thead><tr><th>پنل / لوکیشن</th><th>ارسال‌شده</th><th>پاسخ‌داده‌شده</th><th>میانگین امتیاز</th></tr></thead>
        <tbody>${rows.map(r => `<tr><td>${esc(r.panel_name)}</td><td class="mono">${fmt(r.sent)}</td><td class="mono">${fmt(r.answered)}</td><td class="mono">${r.avg_rating === null ? '—' : '⭐ ' + fmt(r.avg_rating) + ' / ۵'}</td></tr>`).join('') || `<tr><td colspan="4" class="empty-state">هنوز نظرسنجی‌ای ارسال نشده</td></tr>`}</tbody>
      </table></div>`);
  } catch (e) { handleErr(e); }
}
document.addEventListener('click', async e => {
  const send = e.target.closest('[data-survey]');
  if (send) {
    send.disabled = true;
    try { await apiPost(`/orders/${send.dataset.survey}/survey`); toast('نظرسنجی برای کاربر ارسال شد.'); renderOrders(); }
    catch (err) { handleErr(err); send.disabled = false; }
    return;
  }
  if (e.target.closest('[data-survey-summary]')) openSurveySummaryModal();
});
function tierDiscountText(o) {
  return Number(o.tier_discount_amount) > 0 ? `🏷 تخفیف سطح: -${fmt(o.tier_discount_amount)}` : '';
}
function tierDiscountNote(o) {
  const text = tierDiscountText(o);
  return text ? `<div style="font-size:12px;color:var(--muted,#888)">${text}</div>` : '';
}
async function renderOrders() {
  const canAct = hasPerm('orders');
  const params = new URLSearchParams({ status: ordersStatus });
  if (ordersFilters.q.trim()) params.set('q', ordersFilters.q.trim());
  if (ordersFilters.product_id) params.set('product_id', ordersFilters.product_id);
  if (ordersFilters.date_from) params.set('date_from', ordersFilters.date_from);
  if (ordersFilters.date_to) params.set('date_to', ordersFilters.date_to);
  const orders = await apiGet(`/orders?${params.toString()}`);
  if (loadTheme().theme === 'brutalist') return renderOrdersBrutalist(orders, canAct);
  if (loadTheme().theme === 'bento') return renderOrdersBento(orders, canAct);
  if (!ordersProductsCache) { try { ordersProductsCache = await apiGet('/products'); } catch (_) { ordersProductsCache = []; } }
  const filterHtml = `<div class=\"card\" style=\"margin-bottom:12px\"><div style=\"display:flex;gap:8px;flex-wrap:wrap;align-items:end\">
    <label class=\"field\" style=\"min-width:220px;flex:1\"><span>جستجوی کاربر / شماره سفارش</span><input class=\"input\" id=\"orders-q\" value=\"${esc(ordersFilters.q)}\" placeholder=\"نام کاربری، شناسه کاربر یا #سفارش\"></label>
    <label class=\"field\" style=\"min-width:190px\"><span>محصول</span><select class=\"input\" id=\"orders-product\"><option value=\"\">همه محصولات</option>${(ordersProductsCache || []).map(p => `<option value=\"${p.id}\" ${String(ordersFilters.product_id)===String(p.id)?'selected':''}>${esc(p.name)}</option>`).join('')}</select></label>
    <label class=\"field\"><span>از تاریخ</span><input class=\"input\" id=\"orders-from\" type=\"date\" value=\"${esc(ordersFilters.date_from)}\"></label>
    <label class=\"field\"><span>تا تاریخ</span><input class=\"input\" id=\"orders-to\" type=\"date\" value=\"${esc(ordersFilters.date_to)}\"></label>
    <button class=\"btn btn-primary\" id=\"orders-filter-apply\">اعمال فیلتر</button><button class=\"btn\" id=\"orders-filter-clear\">پاک کردن</button>
  </div></div>`;
  setContent(`
    ${filterHtml}
    <div class="tabs">
      ${['pending', 'approved', 'rejected'].map(s => `<button class="tab-btn ${s === ordersStatus ? 'active' : ''}" data-status="${s}">${{ pending: 'در انتظار', approved: 'تایید شده', rejected: 'رد شده' }[s]}</button>`).join('')}
      ${orderSurveySummaryBtn()}
    </div>
    <div class="card">
      <div class="table-wrap"><table>
        <thead><tr><th>#</th><th>کاربر</th><th>محصول</th><th>تعداد</th><th>مبلغ</th><th>تاریخ</th><th>رسید</th>${canAct && ordersStatus === 'pending' ? '<th>عملیات</th>' : ''}${ordersStatus === 'approved' ? '<th>نظرسنجی</th>' : ''}</tr></thead>
        <tbody>
          ${orders.map(o => `<tr>
            <td class="mono">#${o.id} ${historyBtn('order', o.id)}</td>
            <td>${esc(o.username || o.user_id)}</td>
            <td>${esc(o.product_name)}</td>
            <td class="mono">${fmt(o.quantity || 1)}</td>
            <td class="mono">${fmt(o.final_price ?? o.base_price)}${tierDiscountNote(o)}</td>
            <td class="mono">${fmtDate(o.created_at)}</td>
            <td>${o.receipt_file_id ? `<button class="btn btn-sm" data-receipt="order:${o.id}">مشاهده رسید</button>` : '<span class="mono">-</span>'}</td>
            ${ordersStatus === 'approved' ? `<td>${orderSurveyBtn(o, canAct)}</td>` : ''}
            ${canAct && ordersStatus === 'pending' ? `<td>
              <button class="btn btn-primary btn-sm" data-approve="${o.id}">تایید</button>
              <button class="btn btn-danger btn-sm" data-reject="${o.id}">رد</button>
            </td>` : ''}
          </tr>`).join('') || `<tr><td colspan="8" class="empty-state"><div class="icon">${svg('empty')}</div>سفارشی در این وضعیت نیست</td></tr>`}
        </tbody>
      </table></div>
    </div>
  `);
  $$('.tab-btn', content()).forEach(b => b.addEventListener('click', () => { ordersStatus = b.dataset.status; renderOrders(); }));
  const applyFilters = () => { ordersFilters = { q: $('#orders-q', content()).value || '', product_id: $('#orders-product', content()).value || '', date_from: $('#orders-from', content()).value || '', date_to: $('#orders-to', content()).value || '' }; renderOrders(); };
  $('#orders-filter-apply', content())?.addEventListener('click', applyFilters);
  $('#orders-filter-clear', content())?.addEventListener('click', () => { ordersFilters = { q: '', product_id: '', date_from: '', date_to: '' }; renderOrders(); });
  $$('[data-receipt]', content()).forEach(b => b.addEventListener('click', () => {
    const [kind, id] = b.dataset.receipt.split(':');
    showReceiptModal(kind, id);
  }));
  $$('[data-approve]', content()).forEach(b => b.addEventListener('click', async () => {
    b.disabled = true;
    try { await apiPost(`/orders/${b.dataset.approve}/approve`); toast('سفارش تایید شد.'); renderOrders(); }
    catch (e) { handleErr(e); b.disabled = false; }
  }));
  $$('[data-reject]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('سفارش رد شود؟')) return;
    try { await apiPost(`/orders/${b.dataset.reject}/reject`); toast('سفارش رد شد.'); renderOrders(); }
    catch (e) { handleErr(e); }
  }));
}

/* -------------------------------------------------------- orders: bento -- */
function renderOrdersBento(orders, canAct) {
  const total = orders.reduce((sum, o) => sum + Number(o.final_price ?? o.base_price ?? 0), 0);
  setContent(`
    <div class="bn-hero">
      <div><h2>سفارش‌ها</h2><p>${fmt(orders.length)} مورد · جمع ${fmt(total)} تومان</p></div>
      <div class="bn-seg">${['pending', 'approved', 'rejected'].map(s => `<button class="bn-seg-btn ${s === ordersStatus ? 'active' : ''}" data-status="${s}">${ORDERS_STATUS_LABEL[s]}</button>`).join('')}</div>
      ${orderSurveySummaryBtn()}
    </div>
    <div class="bn-list">
      ${orders.map((o, i) => `
        <div class="bn-row-wrap bn-card-anim" style="animation-delay:${Math.min(i * 30, 260)}ms">
          <div class="bn-row">
            ${bnAvatar((o.product_name || '?').trim().charAt(0), i)}
            <div class="bn-row-main">
              <span class="bn-row-title">${esc(o.product_name)}</span>
              <span class="bn-row-sub">${esc(o.username || o.user_id)} · ${fmtDate(o.created_at)}${tierDiscountText(o) ? ' · ' + tierDiscountText(o) : ''}</span>
            </div>
            <div class="bn-row-trail">
              <span class="bn-row-amount mono">${fmt(o.final_price ?? o.base_price)} ت</span>
              ${o.receipt_file_id ? `<button class="bn-btn bn-btn-ghost" data-receipt="order:${o.id}">رسید</button>` : ''}
              ${historyBtn('order', o.id)}
              ${ordersStatus === 'approved' ? orderSurveyBtn(o, canAct) : ''}
            </div>
          </div>
          ${canAct && ordersStatus === 'pending' ? `<div class="bn-row-actions">
            <button class="bn-btn bn-btn-ok" data-approve="${o.id}">تایید</button>
            <button class="bn-btn bn-btn-no" data-reject="${o.id}">رد</button>
          </div>` : ''}
        </div>
      `).join('') || `<div class="empty-state"><div class="icon">${svg('empty')}</div>سفارشی در این وضعیت نیست</div>`}
    </div>
  `);
  $$('.bn-seg-btn', content()).forEach(b => b.addEventListener('click', () => { ordersStatus = b.dataset.status; renderOrders(); }));
  $$('[data-receipt]', content()).forEach(b => b.addEventListener('click', () => {
    const [kind, id] = b.dataset.receipt.split(':');
    showReceiptModal(kind, id);
  }));
  $$('[data-approve]', content()).forEach(b => b.addEventListener('click', async function () {
    this.disabled = true;
    try { await apiPost(`/orders/${b.dataset.approve}/approve`); toast('سفارش تایید شد.'); renderOrders(); }
    catch (e) { handleErr(e); this.disabled = false; }
  }));
  $$('[data-reject]', content()).forEach(b => b.addEventListener('click', async function () {
    if (!confirm('سفارش رد شود؟')) return;
    try { await apiPost(`/orders/${b.dataset.reject}/reject`); toast('سفارش رد شد.'); renderOrders(); }
    catch (e) { handleErr(e); }
  }));
}

/* -------------------------------------------------------- orders: glass -- */

/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

/* -------------------------------------------------- orders: brutalist --- */
// چیدمان «پرونده/تیکت» به‌جای جدول: هر سفارش یه کارت با ته‌برگ شماره‌دار،
// دکمه‌های تایید/رد به‌شکل مهر (استمپ) که با کلیک می‌کوبن (چرخش+بزرگنمایی).
const ORDERS_STATUS_LABEL = { pending: 'در انتظار', approved: 'تایید شده', rejected: 'رد شده' };
function renderOrdersBrutalist(orders, canAct) {
  const total = orders.reduce((sum, o) => sum + Number(o.final_price ?? o.base_price ?? 0), 0);
  setContent(`
    <div class="bru-hero" style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
      <div>
        <h2>پرونده‌های سفارش</h2>
        <p>${fmt(orders.length)} مورد در وضعیت «${ORDERS_STATUS_LABEL[ordersStatus]}» — جمع مبلغ ${fmt(total)} تومان</p>
      </div>
      <div class="bru-seg" role="tablist">
        ${['pending', 'approved', 'rejected'].map(s => `<button class="bru-seg-btn ${s === ordersStatus ? 'active' : ''}" data-status="${s}">${ORDERS_STATUS_LABEL[s]}</button>`).join('')}
      </div>
      ${orderSurveySummaryBtn()}
    </div>

    <div class="bru-ticket-grid">
      ${orders.map((o, i) => `
        <div class="bru-ticket bru-card-anim" style="animation-delay:${Math.min(i * 40, 320)}ms">
          <div class="bru-ticket-stub">
            <span class="bru-ticket-num mono">#${o.id}</span>
            ${historyBtn('order', o.id)}
          </div>
          <div class="bru-ticket-body">
            <div class="bru-ticket-row"><span>کاربر</span><b>${esc(o.username || o.user_id)}</b></div>
            <div class="bru-ticket-row"><span>محصول</span><b>${esc(o.product_name)}</b></div>
            <div class="bru-ticket-row"><span>تعداد</span><b class="mono">${fmt(o.quantity || 1)}</b></div>
            <div class="bru-ticket-row"><span>مبلغ</span><b class="mono bru-amount">${fmt(o.final_price ?? o.base_price)} ت</b></div>
            ${Number(o.tier_discount_amount) > 0 ? `<div class="bru-ticket-row"><span>تخفیف سطح</span><b class="mono">-${fmt(o.tier_discount_amount)} ت</b></div>` : ''}
            <div class="bru-ticket-row"><span>تاریخ</span><b class="mono">${fmtDate(o.created_at)}</b></div>
          </div>
          <div class="bru-ticket-actions">
            ${o.receipt_file_id ? `<button class="btn btn-sm" data-receipt="order:${o.id}">رسید</button>` : ''}
            ${ordersStatus === 'approved' ? orderSurveyBtn(o, canAct) : ''}
            ${canAct && ordersStatus === 'pending' ? `
              <button class="bru-stamp bru-stamp-ok" data-approve="${o.id}" style="--r:-6deg">تایید</button>
              <button class="bru-stamp bru-stamp-no" data-reject="${o.id}" style="--r:4deg">رد</button>
            ` : ''}
          </div>
        </div>
      `).join('') || `<div class="empty-state" style="grid-column:1/-1"><div class="icon">${svg('empty')}</div>سفارشی در این وضعیت نیست</div>`}
    </div>
  `);
  $$('.bru-seg-btn', content()).forEach(b => b.addEventListener('click', () => { ordersStatus = b.dataset.status; renderOrders(); }));
  $$('[data-receipt]', content()).forEach(b => b.addEventListener('click', () => {
    const [kind, id] = b.dataset.receipt.split(':');
    showReceiptModal(kind, id);
  }));
  $$('[data-approve]', content()).forEach(b => b.addEventListener('click', async function () {
    this.classList.add('hit'); this.disabled = true;
    try { await apiPost(`/orders/${b.dataset.approve}/approve`); toast('سفارش تایید شد.'); setTimeout(() => renderOrders(), 260); }
    catch (e) { handleErr(e); this.disabled = false; this.classList.remove('hit'); }
  }));
  $$('[data-reject]', content()).forEach(b => b.addEventListener('click', async function () {
    if (!confirm('سفارش رد شود؟')) return;
    this.classList.add('hit'); this.disabled = true;
    try { await apiPost(`/orders/${b.dataset.reject}/reject`); toast('سفارش رد شد.'); setTimeout(() => renderOrders(), 260); }
    catch (e) { handleErr(e); this.disabled = false; this.classList.remove('hit'); }
  }));
}

/* ============================================================ topups === */
let topupsStatus = 'pending';
async function renderTopups() {
  const canAct = hasPerm('orders');
  const topups = await apiGet(`/topups?status=${topupsStatus}`);
  if (loadTheme().theme === 'brutalist') return renderTopupsBrutalist(topups, canAct);
  if (loadTheme().theme === 'bento') return renderTopupsBento(topups, canAct);
  setContent(`
    <div class="tabs">
      ${['pending', 'approved', 'rejected'].map(s => `<button class="tab-btn ${s === topupsStatus ? 'active' : ''}" data-status="${s}">${{ pending: 'در انتظار', approved: 'تایید شده', rejected: 'رد شده' }[s]}</button>`).join('')}
    </div>
    <div class="card">
      <div class="table-wrap"><table>
        <thead><tr><th>#</th><th>کاربر</th><th>مبلغ</th><th>تاریخ</th><th>رسید</th>${canAct && topupsStatus === 'pending' ? '<th>عملیات</th>' : ''}</tr></thead>
        <tbody>${topups.map(t => `<tr>
          <td class="mono">#${t.id}</td><td>${esc(t.username || t.user_id)}</td>
          <td class="mono">${fmt(t.amount)}</td><td class="mono">${fmtDate(t.created_at)}</td>
          <td>${t.receipt_file_id ? `<button class="btn btn-sm" data-receipt="topup:${t.id}">مشاهده رسید</button>` : '<span class="mono">-</span>'}</td>
          ${canAct && topupsStatus === 'pending' ? `<td>
            <button class="btn btn-primary btn-sm" data-approve="${t.id}">تایید</button>
            <button class="btn btn-danger btn-sm" data-reject="${t.id}">رد</button>
          </td>` : ''}
        </tr>`).join('') || `<tr><td colspan="6" class="empty-state"><div class="icon">${svg('empty')}</div>درخواستی در این وضعیت نیست</td></tr>`}</tbody>
      </table></div>
    </div>
  `);
  $$('.tab-btn', content()).forEach(b => b.addEventListener('click', () => { topupsStatus = b.dataset.status; renderTopups(); }));
  $$('[data-receipt]', content()).forEach(b => b.addEventListener('click', () => {
    const [kind, id] = b.dataset.receipt.split(':');
    showReceiptModal(kind, id);
  }));
  $$('[data-approve]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/topups/${b.dataset.approve}/approve`); toast('شارژ تایید شد.'); renderTopups(); } catch (e) { handleErr(e); }
  }));
  $$('[data-reject]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('این شارژ رد شود؟')) return;
    try { await apiPost(`/topups/${b.dataset.reject}/reject`); toast('رد شد.'); renderTopups(); } catch (e) { handleErr(e); }
  }));
}

/* -------------------------------------------------------- topups: bento -- */
function renderTopupsBento(topups, canAct) {
  const total = topups.reduce((sum, t) => sum + Number(t.amount || 0), 0);
  setContent(`
    <div class="bn-hero">
      <div><h2>شارژ کیف پول</h2><p>${fmt(topups.length)} مورد · جمع ${fmt(total)} تومان</p></div>
      <div class="bn-seg">${['pending', 'approved', 'rejected'].map(s => `<button class="bn-seg-btn ${s === topupsStatus ? 'active' : ''}" data-status="${s}">${ORDERS_STATUS_LABEL[s]}</button>`).join('')}</div>
    </div>
    <div class="bn-list">
      ${topups.map((t, i) => `
        <div class="bn-row-wrap bn-card-anim" style="animation-delay:${Math.min(i * 30, 260)}ms">
          <div class="bn-row">
            ${bnAvatar((t.username || '؟').trim().charAt(0), i)}
            <div class="bn-row-main">
              <span class="bn-row-title">${esc(t.username || t.user_id)}</span>
              <span class="bn-row-sub">${fmtDate(t.created_at)}</span>
            </div>
            <div class="bn-row-trail">
              <span class="bn-row-amount mono">${fmt(t.amount)} ت</span>
              ${t.receipt_file_id ? `<button class="bn-btn bn-btn-ghost" data-receipt="topup:${t.id}">رسید</button>` : ''}
            </div>
          </div>
          ${canAct && topupsStatus === 'pending' ? `<div class="bn-row-actions">
            <button class="bn-btn bn-btn-ok" data-approve="${t.id}">تایید</button>
            <button class="bn-btn bn-btn-no" data-reject="${t.id}">رد</button>
          </div>` : ''}
        </div>
      `).join('') || `<div class="empty-state"><div class="icon">${svg('empty')}</div>درخواستی در این وضعیت نیست</div>`}
    </div>
  `);
  $$('.bn-seg-btn', content()).forEach(b => b.addEventListener('click', () => { topupsStatus = b.dataset.status; renderTopups(); }));
  $$('[data-receipt]', content()).forEach(b => b.addEventListener('click', () => {
    const [kind, id] = b.dataset.receipt.split(':');
    showReceiptModal(kind, id);
  }));
  $$('[data-approve]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/topups/${b.dataset.approve}/approve`); toast('شارژ تایید شد.'); renderTopups(); } catch (e) { handleErr(e); }
  }));
  $$('[data-reject]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('این شارژ رد شود؟')) return;
    try { await apiPost(`/topups/${b.dataset.reject}/reject`); toast('رد شد.'); renderTopups(); } catch (e) { handleErr(e); }
  }));
}


/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

/* -------------------------------------------------- topups: brutalist --- */
function renderTopupsBrutalist(topups, canAct) {
  const total = topups.reduce((sum, t) => sum + Number(t.amount || 0), 0);
  setContent(`
    <div class="bru-hero" style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
      <div>
        <h2>پرونده‌های شارژ کیف پول</h2>
        <p>${fmt(topups.length)} مورد در وضعیت «${ORDERS_STATUS_LABEL[topupsStatus]}» — جمع مبلغ ${fmt(total)} تومان</p>
      </div>
      <div class="bru-seg" role="tablist">
        ${['pending', 'approved', 'rejected'].map(s => `<button class="bru-seg-btn ${s === topupsStatus ? 'active' : ''}" data-status="${s}">${ORDERS_STATUS_LABEL[s]}</button>`).join('')}
      </div>
    </div>

    <div class="bru-ticket-grid">
      ${topups.map((t, i) => `
        <div class="bru-ticket bru-card-anim" style="animation-delay:${Math.min(i * 40, 320)}ms">
          <div class="bru-ticket-stub">
            <span class="bru-ticket-num mono">#${t.id}</span>
            ${t.receipt_file_id ? `<button class="btn btn-sm" data-receipt="topup:${t.id}" style="background:transparent;color:#fff;border-color:#fff;box-shadow:none">رسید</button>` : ''}
          </div>
          <div class="bru-ticket-body">
            <div class="bru-ticket-row"><span>کاربر</span><b>${esc(t.username || t.user_id)}</b></div>
            <div class="bru-ticket-row"><span>مبلغ</span><b class="mono bru-amount">${fmt(t.amount)} ت</b></div>
            <div class="bru-ticket-row"><span>تاریخ</span><b class="mono">${fmtDate(t.created_at)}</b></div>
          </div>
          ${canAct && topupsStatus === 'pending' ? `
          <div class="bru-ticket-actions">
            <button class="bru-stamp bru-stamp-ok" data-approve="${t.id}" style="--r:-6deg">تایید</button>
            <button class="bru-stamp bru-stamp-no" data-reject="${t.id}" style="--r:4deg">رد</button>
          </div>` : ''}
        </div>
      `).join('') || `<div class="empty-state" style="grid-column:1/-1"><div class="icon">${svg('empty')}</div>درخواستی در این وضعیت نیست</div>`}
    </div>
  `);
  $$('.bru-seg-btn', content()).forEach(b => b.addEventListener('click', () => { topupsStatus = b.dataset.status; renderTopups(); }));
  $$('[data-receipt]', content()).forEach(b => b.addEventListener('click', () => {
    const [kind, id] = b.dataset.receipt.split(':');
    showReceiptModal(kind, id);
  }));
  $$('[data-approve]', content()).forEach(b => b.addEventListener('click', async function () {
    this.classList.add('hit'); this.disabled = true;
    try { await apiPost(`/topups/${b.dataset.approve}/approve`); toast('شارژ تایید شد.'); setTimeout(() => renderTopups(), 260); }
    catch (e) { handleErr(e); this.disabled = false; this.classList.remove('hit'); }
  }));
  $$('[data-reject]', content()).forEach(b => b.addEventListener('click', async function () {
    if (!confirm('این شارژ رد شود؟')) return;
    this.classList.add('hit'); this.disabled = true;
    try { await apiPost(`/topups/${b.dataset.reject}/reject`); toast('رد شد.'); setTimeout(() => renderTopups(), 260); }
    catch (e) { handleErr(e); this.disabled = false; this.classList.remove('hit'); }
  }));
}

/* ======================================================= user groups === */
let userGroupsState = { groupId: null, q: '', page: 1, selected: new Set() };
const USER_GROUP_FIELDS = [
  ['joined_at', 'تاریخ عضویت', 'date'],
  ['purchase_date', 'تاریخ خرید تاییدشده (هر خرید)', 'date'],
  ['last_purchase_at', 'تاریخ آخرین خرید تاییدشده', 'date'],
  ['last_service_at', 'تاریخ آخرین ایجاد سرویس', 'date'],
  ['service_expiry_at', 'تاریخ انقضای سرویس', 'date'],
  ['purchase_count', 'تعداد خریدهای تاییدشده', 'number'],
  ['total_purchase', 'مجموع مبلغ خرید (تومان)', 'number'],
  ['wallet_balance', 'موجودی کیف پول (تومان)', 'number'],
  ['topup_total', 'مجموع شارژ تاییدشده (تومان)', 'number'],
  ['active_services', 'تعداد سرویس فعال', 'number'],
  ['referrals_count', 'تعداد زیرمجموعه', 'number'],
  ['telegram_id', 'آیدی عددی تلگرام', 'number'],
  ['username', 'یوزرنیم', 'text'],
  ['first_name', 'نام کاربر', 'text'],
  ['is_blocked', 'وضعیت مسدودی', 'bool'],
  ['phone_verified', 'وضعیت تایید موبایل', 'bool'],
  ['service_type', 'نوع سرویس', 'service_type'],
  ['service_status', 'وضعیت سرویس', 'service_status'],
];
const USER_GROUP_FIELD_META = Object.fromEntries(USER_GROUP_FIELDS.map(x => [x[0], { label: x[1], type: x[2] }]));
const USER_GROUP_OPS = [
  ['eq', 'برابر باشد'], ['ne', 'برابر نباشد'], ['contains', 'شامل باشد'], ['starts', 'شروع شود با'],
  ['gt', 'بزرگ‌تر از'], ['gte', 'بزرگ‌تر یا مساوی'], ['lt', 'کوچک‌تر از'], ['lte', 'کوچک‌تر یا مساوی'],
  ['between', 'بین دو مقدار'], ['empty', 'خالی باشد'], ['not_empty', 'خالی نباشد'],
];
function userGroupRuleValueHtml(field, value) {
  const type = USER_GROUP_FIELD_META[field]?.type || 'text';
  if (type === 'bool') return `<select class="input ug-value"><option value="1" ${String(value) === '1' || value === true ? 'selected' : ''}>بله</option><option value="0" ${String(value) === '0' || value === false ? 'selected' : ''}>خیر</option></select>`;
  if (type === 'service_type') return `<select class="input ug-value"><option value="vpn">VPN (هر نوع)</option><option value="custom" ${value === 'custom' ? 'selected' : ''}>VPN اختصاصی</option><option value="bank" ${value === 'bank' ? 'selected' : ''}>بانک کانفیگ</option><option value="ssh" ${value === 'ssh' ? 'selected' : ''}>SSH</option><option value="none" ${value === 'none' ? 'selected' : ''}>بدون سرویس</option><option value="any" ${value === 'any' ? 'selected' : ''}>دارای هر سرویس</option></select>`;
  if (type === 'service_status') return `<select class="input ug-value"><option value="active" ${value === 'active' ? 'selected' : ''}>دارای سرویس فعال</option><option value="expired" ${value === 'expired' ? 'selected' : ''}>فقط سرویس منقضی/غیرفعال</option><option value="none" ${value === 'none' ? 'selected' : ''}>بدون سرویس</option><option value="any" ${value === 'any' ? 'selected' : ''}>دارای سرویس</option></select>`;
  const inputType = type === 'date' ? 'date' : type === 'number' ? 'number' : 'text';
  return `<input class="input ug-value" type="${inputType}" value="${esc(value ?? '')}" placeholder="${type === 'date' ? 'تاریخ' : type === 'number' ? 'عدد' : 'مقدار'}">`;
}
function userGroupRuleRowHtml(rule = {}, idx = 0) {
  const field = USER_GROUP_FIELD_META[rule.field] ? rule.field : 'joined_at';
  const type = USER_GROUP_FIELD_META[field].type;
  const validOps = {
    text: ['eq','ne','contains','starts','empty','not_empty'],
    number: ['eq','ne','gt','gte','lt','lte','between'],
    date: ['eq','ne','gt','gte','lt','lte','between','empty','not_empty'],
    bool: ['eq','ne'], service_type: ['eq','ne'], service_status: ['eq','ne'],
  };
  const allowedOps = USER_GROUP_OPS.filter(([op]) => (validOps[type] || validOps.text).includes(op));
  return `<div class="ug-rule" data-index="${idx}">
    <select class="input ug-field">${USER_GROUP_FIELDS.map(([v,l]) => `<option value="${v}" ${v === field ? 'selected' : ''}>${l}</option>`).join('')}</select>
    <select class="input ug-op">${allowedOps.map(([v,l]) => `<option value="${v}" ${v === (rule.op || (type === 'date' ? 'gte' : 'eq')) ? 'selected' : ''}>${l}</option>`).join('')}</select>
    <div class="ug-value-wrap">${userGroupRuleValueHtml(field, rule.value)}</div>
    ${rule.op === 'between' ? `<input class="input ug-value2" type="${type === 'date' ? 'date' : 'number'}" value="${esc(rule.value2 ?? '')}" placeholder="تا">` : '<span class="ug-value2-placeholder"></span>'}
    <button class="btn btn-ghost btn-sm ug-remove" type="button" title="حذف شرط">✕</button>
  </div>`;
}
function groupRulesDescription(rules) {
  const conditions = (rules && rules.conditions) || [];
  if (!conditions.length) return 'بدون شرط؛ شامل همه‌ی کاربران';
  const opNames = Object.fromEntries(USER_GROUP_OPS.map(([v,l]) => [v,l]));
  const parts = conditions.map(r => {
    const f = USER_GROUP_FIELD_META[r.field]?.label || r.field;
    const v = r.field === 'service_type' ? ({vpn:'VPN',custom:'VPN اختصاصی',bank:'بانک کانفیگ',ssh:'SSH',none:'بدون سرویس',any:'هر سرویس'}[r.value] || r.value)
      : r.field === 'service_status' ? ({active:'فعال',expired:'منقضی/غیرفعال',none:'بدون سرویس',any:'دارای سرویس'}[r.value] || r.value)
      : r.field === 'is_blocked' || r.field === 'phone_verified' ? (String(r.value) === '1' ? 'بله' : 'خیر') : r.value;
    return `${f} ${opNames[r.op] || ''} ${r.op === 'empty' || r.op === 'not_empty' ? '' : esc(v ?? '')}`;
  });
  return parts.join(rules.match === 'any' ? ' یا ' : ' و ');
}
async function renderUserGroups() {
  if (userGroupsState.groupId) return renderUserGroupMembers();
  const groups = await apiGet('/user-groups');
  setContent(`
    <div class="toolbar ug-toolbar"><div><h2 style="margin:0">گروه‌بندی کاربران</h2><div class="card-sub">ساخت گروه‌های پویا با شرط‌های دلخواه؛ اعضا با اطلاعات به‌روز دیتابیس محاسبه می‌شوند.</div></div>${hasPerm('users') ? '<button class="btn btn-primary" id="ug-create">＋ ساخت گروه جدید</button>' : ''}</div>
    <div class="ug-grid">${groups.map(g => `<div class="card ug-card">
      <div class="ug-card-head"><div><h3>${esc(g.name)}</h3><span class="badge">${fmt(g.member_count)} عضو</span></div><span class="ug-card-icon">👥</span></div>
      <p class="card-sub">${esc(g.description || 'بدون توضیحات')}</p>
      <div class="ug-rules-summary">${groupRulesDescription(g.rules)}</div>
      <div class="ug-card-actions"><button class="btn btn-primary btn-sm" data-ug-open="${g.id}">مشاهده اعضا</button>${hasPerm('users') ? `<button class="btn btn-ghost btn-sm" data-ug-edit="${g.id}">ویرایش</button><button class="btn btn-ghost btn-sm" data-ug-delete="${g.id}">حذف</button>` : ''}</div>
      <div class="ug-card-date">آخرین ویرایش: ${fmtDate(g.updated_at)}</div>
    </div>`).join('') || `<div class="card empty-state">هنوز گروهی ساخته نشده است. برای شروع، «ساخت گروه جدید» را بزن.</div>`}</div>
  `);
  $('#ug-create')?.addEventListener('click', () => openUserGroupEditor());
  $$('[data-ug-open]', content()).forEach(b => b.addEventListener('click', () => { userGroupsState.groupId = Number(b.dataset.ugOpen); userGroupsState.q = ''; userGroupsState.page = 1; userGroupsState.selected = new Set(); renderUserGroups(); }));
  $$('[data-ug-edit]', content()).forEach(b => b.addEventListener('click', async () => { try { openUserGroupEditor(await apiGet(`/user-groups/${Number(b.dataset.ugEdit)}`)); } catch (e) { handleErr(e); } }));
  $$('[data-ug-delete]', content()).forEach(b => b.addEventListener('click', async () => {
    const id = Number(b.dataset.ugDelete); const g = groups.find(x => x.id === id);
    if (!confirm(`گروه «${g?.name || ''}» حذف شود؟ کاربران و سرویس‌های آن تغییری نمی‌کنند.`)) return;
    try { await apiDelete(`/user-groups/${id}`); toast('گروه حذف شد.'); renderUserGroups(); } catch (e) { handleErr(e); }
  }));
}
function openUserGroupEditor(group = null) {
  const isEdit = !!group;
  let conditions = (group?.rules?.conditions || []).map(x => ({...x}));
  if (!conditions.length) conditions = [{field:'joined_at',op:'gte',value:'',value2:''}];
  openModal(isEdit ? 'ویرایش گروه کاربران' : 'ساخت گروه کاربران', `
    <div class="ug-editor">
      <label class="field"><span>نام گروه</span><input class="input" id="ug-name" maxlength="80" value="${esc(group?.name || '')}" placeholder="مثلاً خریداران ماه جاری"></label>
      <label class="field"><span>توضیحات (اختیاری)</span><input class="input" id="ug-description" maxlength="500" value="${esc(group?.description || '')}" placeholder="هدف یا کاربرد این گروه"></label>
      <div class="ug-condition-title"><b>شرط‌های عضویت</b><select class="input" id="ug-match"><option value="all" ${group?.rules?.match !== 'any' ? 'selected' : ''}>همه‌ی شرط‌ها برقرار باشند</option><option value="any" ${group?.rules?.match === 'any' ? 'selected' : ''}>حداقل یکی از شرط‌ها برقرار باشد</option></select></div>
      <div id="ug-condition-list">${conditions.map(userGroupRuleRowHtml).join('')}</div>
      <button class="btn btn-ghost btn-sm" id="ug-add-condition">＋ افزودن شرط</button>
      <p class="card-sub">تاریخ‌ها با قالب روز/ماه/سال انتخاب می‌شوند. برای لینک یا نام سرویس، از جستجوی داخل گروه استفاده کن.</p>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px"><button class="btn btn-primary" id="ug-save">${isEdit ? 'ذخیره تغییرات' : 'ساخت گروه'}</button></div>
    </div>
  `, (body, close) => {
    const list = $('#ug-condition-list', body);
    const redraw = () => {
      list.innerHTML = conditions.map(userGroupRuleRowHtml).join('');
      $$('.ug-field', list).forEach(sel => sel.addEventListener('change', () => {
        const row = sel.closest('.ug-rule'); const idx = Number(row.dataset.index); conditions[idx] = {field:sel.value,op:'eq',value:'',value2:''}; redraw();
      }));
      $$('.ug-value', list).forEach(input => input.addEventListener('change', () => { conditions[Number(input.closest('.ug-rule').dataset.index)].value = input.value; }));
      $$('.ug-value2', list).forEach(input => input.addEventListener('change', () => { conditions[Number(input.closest('.ug-rule').dataset.index)].value2 = input.value; }));
      $$('.ug-op', list).forEach(sel => sel.addEventListener('change', () => {
        const row = sel.closest('.ug-rule'); const idx = Number(row.dataset.index);
        conditions[idx].value = $('.ug-value', row)?.value ?? conditions[idx].value;
        conditions[idx].value2 = $('.ug-value2', row)?.value ?? conditions[idx].value2;
        conditions[idx].op = sel.value; redraw();
      }));
      $$('.ug-remove', list).forEach(btn => btn.addEventListener('click', () => { conditions.splice(Number(btn.closest('.ug-rule').dataset.index),1); redraw(); }));
    };
    redraw();
    $('#ug-add-condition', body).addEventListener('click', () => { if (conditions.length >= 20) return toast('حداکثر ۲۰ شرط مجاز است.', true); conditions.push({field:'joined_at',op:'gte',value:'',value2:''}); redraw(); });
    $('#ug-save', body).addEventListener('click', async () => {
      const name = $('#ug-name', body).value.trim();
      if (!name) return toast('نام گروه را وارد کن.', true);
      const rules = {match:$('#ug-match', body).value,conditions:[]};
      $$('.ug-rule', list).forEach(row => {
        const field = $('.ug-field', row).value, op = $('.ug-op', row).value;
        const value = $('.ug-value', row)?.value ?? '';
        const value2 = $('.ug-value2', row)?.value ?? '';
        if (op === 'empty' || op === 'not_empty' || value !== '') rules.conditions.push({field,op,value,value2});
      });
      const payload = {name,description:$('#ug-description', body).value.trim(),rules};
      try {
        if (isEdit) await apiPut(`/user-groups/${group.id}`, payload); else await apiPost('/user-groups', payload);
        toast(isEdit ? 'گروه به‌روزرسانی شد.' : 'گروه ساخته شد.'); close(); userGroupsState.groupId = null; renderUserGroups();
      } catch (e) { handleErr(e); }
    });
  }, {wide:true});
}
async function renderUserGroupMembers() {
  const id = Number(userGroupsState.groupId);
  const [groups, res] = await Promise.all([apiGet('/user-groups'), apiGet(`/user-groups/${id}/members?q=${encodeURIComponent(userGroupsState.q)}&page=${userGroupsState.page}`)]);
  const group = groups.find(g => Number(g.id) === id);
  if (!group) { userGroupsState.groupId = null; return renderUserGroups(); }
  const pages = Math.max(Math.ceil(res.total / res.limit), 1);
  const selected = userGroupsState.selected;
  setContent(`
    <div class="ug-detail-head"><div><button class="btn btn-ghost btn-sm" id="ug-back">← همه گروه‌ها</button><h2 style="margin:9px 0 4px">${esc(group.name)}</h2><div class="card-sub">${esc(group.description || groupRulesDescription(group.rules))}</div></div><div class="ug-detail-actions"><span class="badge">${fmt(res.total)} عضو</span>${hasPerm('users') ? '<button class="btn btn-ghost btn-sm" id="ug-edit-current">ویرایش گروه</button>' : ''}<button class="btn btn-ghost btn-sm" id="ug-export">خروجی CSV</button></div></div>
    <div class="ug-rules-summary" style="margin:12px 0 16px">شرط‌ها: ${groupRulesDescription(group.rules)}</div>
    <div class="toolbar"><input class="input" id="ug-member-search" value="${esc(userGroupsState.q)}" placeholder="جستجو در گروه: آیدی عددی، یوزرنیم، لینک اشتراک، نام کانفیگ..."/><button class="btn btn-ghost" id="ug-search">جستجو</button><button class="btn btn-ghost" id="ug-refresh">به‌روزرسانی</button></div>
    <div class="card">
      <div class="ug-selected-bar">${hasPerm('users') ? '<label><input type="checkbox" id="ug-select-page"> انتخاب اعضای همین صفحه</label>' : ''}<span>${selected.size} انتخاب شده</span>
        ${hasPerm('users') ? `<button class="btn btn-sm" data-ug-action="message" ${selected.size ? '' : 'disabled'}>ارسال پیام</button>
        <button class="btn btn-sm" data-ug-action="block" ${selected.size ? '' : 'disabled'}>مسدودسازی</button>
        <button class="btn btn-sm" data-ug-action="unblock" ${selected.size ? '' : 'disabled'}>رفع مسدودی</button>
        <button class="btn btn-sm" data-ug-action="wallet" ${selected.size ? '' : 'disabled'}>تغییر کیف پول</button>` : ''}
      </div>
      <div class="table-wrap"><table><thead><tr><th></th><th>آیدی</th><th>کاربر</th><th>وضعیت</th><th>خریدها</th><th>مجموع خرید</th><th>سرویس فعال</th><th>عضویت</th><th>آخرین خرید</th><th>جزئیات</th></tr></thead><tbody>
        ${res.items.map(u => `<tr><td>${hasPerm('users') ? `<input type="checkbox" class="ug-user-check" value="${u.telegram_id}" ${selected.has(Number(u.telegram_id)) ? 'checked' : ''}>` : ''}</td><td class="mono">${u.telegram_id}</td><td>${esc(u.first_name || '—')} ${u.username ? `<span class="card-sub">@${esc(u.username)}</span>` : ''}</td><td>${u.is_blocked ? '<span class="badge badge-rejected">مسدود</span>' : '<span class="badge badge-approved">فعال</span>'}</td><td class="mono">${fmt(u.purchase_count)}</td><td class="mono">${fmt(u.total_purchase)}</td><td class="mono">${fmt(u.active_services)}</td><td class="mono">${fmtDate(u.joined_at)}</td><td class="mono">${fmtDate(u.last_purchase_at)}</td><td><button class="btn btn-ghost btn-sm" data-ug-detail="${u.telegram_id}">مشاهده</button></td></tr>`).join('') || '<tr><td colspan="10" class="empty-state">کاربری با این شرط‌ها یا عبارت جستجو پیدا نشد.</td></tr>'}
      </tbody></table></div>
      <div class="pager">${Array.from({length:pages},(_,i)=>i+1).map(p=>`<button class="btn btn-sm ${p===userGroupsState.page?'btn-primary':''}" data-ug-page="${p}">${p}</button>`).join('')}</div>
    </div>
  `);
  $('#ug-back').addEventListener('click', () => { userGroupsState.groupId = null; userGroupsState.selected = new Set(); renderUserGroups(); });
  $('#ug-edit-current')?.addEventListener('click', () => openUserGroupEditor(group));
  const runSearch = () => { userGroupsState.q = $('#ug-member-search').value.trim(); userGroupsState.page = 1; renderUserGroupMembers(); };
  $('#ug-search').addEventListener('click', runSearch);
  $('#ug-member-search').addEventListener('keydown', e => { if (e.key === 'Enter') runSearch(); });
  $('#ug-refresh').addEventListener('click', () => renderUserGroupMembers());
  $('#ug-select-page').addEventListener('change', e => {
    res.items.forEach(u => e.target.checked ? selected.add(Number(u.telegram_id)) : selected.delete(Number(u.telegram_id)));
    renderUserGroupMembers();
  });
  $$('.ug-user-check', content()).forEach(ch => ch.addEventListener('change', () => { ch.checked ? selected.add(Number(ch.value)) : selected.delete(Number(ch.value)); renderUserGroupMembers(); }));
  $$('[data-ug-page]', content()).forEach(b => b.addEventListener('click', () => { userGroupsState.page = Number(b.dataset.ugPage); renderUserGroupMembers(); }));
  $$('[data-ug-detail]', content()).forEach(b => b.addEventListener('click', () => showUserDetail(Number(b.dataset.ugDetail))));
  $$('[data-ug-action]', content()).forEach(b => b.addEventListener('click', async () => {
    const action = b.dataset.ugAction, ids = [...selected]; if (!ids.length) return;
    let payload = {action,user_ids:ids};
    if (action === 'message') {
      const message = prompt(`متن پیام برای ${ids.length} کاربر:`); if (!message?.trim()) return; payload.message = message.trim();
    } else if (action === 'wallet') {
      const raw = prompt(`مبلغ تغییر برای هر یک از ${ids.length} کاربر (تومان؛ برای کسر مبلغ منفی وارد کن):`); if (raw === null) return; payload.amount = Number(raw);
      if (!Number.isInteger(payload.amount) || payload.amount === 0) return toast('مبلغ نامعتبر است.', true);
    } else if (!confirm(`آیا ${action === 'block' ? 'مسدودسازی' : 'رفع مسدودی'} ${ids.length} کاربر انجام شود؟`)) return;
    try {
      const result = await apiPost(`/user-groups/${id}/actions`, payload);
      toast(`عملیات انجام شد: ${result.succeeded} موفق، ${result.failed} ناموفق`);
      userGroupsState.selected = new Set(); renderUserGroupMembers();
    } catch (e) { handleErr(e); }
  }));
  $('#ug-export').addEventListener('click', async () => {
    try {
      const allRows = [];
      const pageCount = Math.max(1, Math.min(200, Math.ceil(res.total / 25)));
      for (let page = 1; page <= pageCount; page++) {
        const all = await apiGet(`/user-groups/${id}/members?q=${encodeURIComponent(userGroupsState.q)}&page=${page}`);
        allRows.push(...all.items);
      }
      const rows = [['telegram_id','username','first_name','is_blocked','purchase_count','total_purchase','active_services','joined_at','last_purchase_at'], ...allRows.map(u => [u.telegram_id,u.username||'',u.first_name||'',u.is_blocked?1:0,u.purchase_count,u.total_purchase,u.active_services,u.joined_at||'',u.last_purchase_at||''])];
      const csv = '\uFEFF' + rows.map(r => r.map(v => `"${String(v ?? '').replace(/"/g,'""')}"`).join(',')).join('\r\n');
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})); a.download = `user-group-${id}.csv`; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),1500);
      if (res.total > 5000) toast('به‌دلیل محدودیت خروجی، ۵۰۰۰ عضو اول دانلود شدند.');
    } catch (e) { handleErr(e); }
  });
}

/* ============================================================= users === */
let usersState = { q: '', status: 'all', page: 1, sort: 'newest' };
const USERS_STATUS_LABEL = { all: 'همه', active: 'فعال', expired: 'منقضی', blocked: 'مسدود' };
const USERS_SORT_OPTIONS = [['newest', 'جدیدترین'], ['balance', 'بیشترین موجودی'], ['purchase', 'بیشترین میزان خرید'], ['active_services', 'بیشترین سرویس فعال'], ['topup', 'بیشترین میزان شارژ']];
const usersSortSelect = () => `<select class="input" id="user-sort">${USERS_SORT_OPTIONS.map(([v, l]) => `<option value="${v}" ${v === usersState.sort ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
const bindUsersSort = () => {
  const el = $('#user-sort');
  if (el) el.addEventListener('change', e => { usersState.sort = e.target.value; usersState.page = 1; renderUsers(); });
};
async function renderUsers() {
  const res = await apiGet(`/users?q=${encodeURIComponent(usersState.q)}&status=${usersState.status}&page=${usersState.page}&sort=${usersState.sort}`);
  const pages = Math.max(Math.ceil(res.total / res.limit), 1);
  if (loadTheme().theme === 'brutalist') return renderUsersBrutalist(res, pages);
  if (loadTheme().theme === 'bento') return renderUsersBento(res, pages);
  setContent(`
    <div class="toolbar">
      <input class="input" id="user-search" placeholder="جستجو (آیدی، یوزرنیم، نام)..." value="${esc(usersState.q)}">
      <select class="input" id="user-status">
        ${[['all', 'همه'], ['active', 'فعال'], ['expired', 'منقضی'], ['blocked', 'مسدود']].map(([v, l]) => `<option value="${v}" ${v === usersState.status ? 'selected' : ''}>${l}</option>`).join('')}
      </select>
      ${usersSortSelect()}
    </div>
    <div class="card">
      <div class="table-wrap"><table>
        <thead><tr><th>آیدی</th><th>یوزرنیم</th><th>نام</th><th>وضعیت</th><th>کیف پول</th><th>میزان خرید</th><th>سرویس فعال</th><th>میزان شارژ</th><th>عضویت</th><th>عملیات</th></tr></thead>
        <tbody>${res.items.map(u => `<tr>
          <td class="mono">${u.telegram_id}</td><td>${esc(u.username || '—')}</td><td>${esc(u.first_name || '—')}</td>
          <td>${u.is_blocked ? '<span class="badge badge-rejected">مسدود</span>' : '<span class="badge badge-approved">فعال</span>'}</td>
          <td class="mono">${fmt(u.referral_credit)}</td>
          <td class="mono">${fmt(u.total_purchase)}</td>
          <td class="mono">${fmt(u.active_services)}</td>
          <td class="mono">${fmt(u.total_topup)}</td>
          <td class="mono">${fmtDate(u.joined_at)}</td>
          <td>
            <button class="btn btn-ghost btn-sm" data-detail="${u.telegram_id}">جزئیات</button>
            ${hasPerm('users') ? (u.is_blocked
              ? `<button class="btn btn-sm" data-unblock="${u.telegram_id}">رفع مسدودی</button>`
              : `<button class="btn btn-danger btn-sm" data-block="${u.telegram_id}">مسدودسازی</button>`) : ''}
          </td>
        </tr>`).join('') || `<tr><td colspan="10" class="empty-state"><div class="icon">${svg('empty')}</div>کاربری یافت نشد</td></tr>`}</tbody>
      </table></div>
      <div class="pager">${Array.from({ length: pages }, (_, i) => i + 1).map(p => `<button class="btn btn-sm ${p === usersState.page ? 'btn-primary' : ''}" data-page="${p}">${p}</button>`).join('')}</div>
    </div>
  `);
  $('#user-search').addEventListener('keydown', e => { if (e.key === 'Enter') { usersState.q = e.target.value; usersState.page = 1; renderUsers(); } });
  $('#user-status').addEventListener('change', e => { usersState.status = e.target.value; usersState.page = 1; renderUsers(); });
  bindUsersSort();
  $$('[data-page]', content()).forEach(b => b.addEventListener('click', () => { usersState.page = Number(b.dataset.page); renderUsers(); }));
  $$('[data-block]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/users/${b.dataset.block}/block`); toast('کاربر مسدود شد.'); renderUsers(); } catch (e) { handleErr(e); }
  }));
  $$('[data-unblock]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/users/${b.dataset.unblock}/unblock`); toast('رفع مسدودیت شد.'); renderUsers(); } catch (e) { handleErr(e); }
  }));
  $$('[data-detail]', content()).forEach(b => b.addEventListener('click', () => showUserDetail(Number(b.dataset.detail))));
}

/* ============================================== active subscriptions === */
// لیست سراسری همه‌ی اشتراک‌ها (شخصی/پنل مستقیم، تست، بانک کانفیگ و SSH) با جستجو بر اساس
// نام اشتراک، آی‌دی عددی کاربر یا یوزرنیم تلگرام و مدیریت کامل اشتراک و کاربر از یک‌جا.
let subsState = { q: '', kind: 'all', status: 'active', sort: 'newest', page: 1 };
let subsItems = [];
const SUBS_KIND_LABEL = { custom: '🛡 شخصی', test: '🧪 تست', bank: '🏦 بانک کانفیگ', ssh: '🖥 SSH' };
const SUBS_STATE_BADGE = { active: ['badge-approved', 'فعال'], expired: ['badge-pending', 'منقضی'], disabled: ['badge-rejected', 'غیرفعال'] };
const SUBS_SORTS = [['newest', 'جدیدترین'], ['oldest', 'قدیمی‌ترین'], ['expiry_asc', 'نزدیک‌ترین انقضا'], ['expiry_desc', 'دورترین انقضا'], ['name', 'نام اشتراک']];

function subsKindKey(it) { return it.kind === 'custom' && it.is_test ? 'test' : it.kind; }
function subsUserLabel(it) { return it.user_username ? '@' + it.user_username : (it.user_first_name || String(it.user_id)); }
function subsRemaining(iso) {
  if (!iso || !String(iso).trim()) return 'نامحدود';
  const t = Date.parse(String(iso).trim().replace(' ', 'T'));
  if (isNaN(t)) return fmtDate(iso);
  const days = Math.ceil((t - Date.now()) / 86400000);
  return days > 0 ? `${fmt(days)} روز مانده` : (days === 0 ? 'امروز' : `${fmt(-days)} روز پیش منقضی شد`);
}

async function renderSubscriptions() {
  const qs = `q=${encodeURIComponent(subsState.q)}&kind=${subsState.kind}&status=${subsState.status}&sort=${subsState.sort}&page=${subsState.page}`;
  const res = await apiGet(`/subscriptions?${qs}`);
  const pages = Math.max(Math.ceil(res.total / res.limit), 1);
  if (subsState.page > pages) { subsState.page = pages; return renderSubscriptions(); }
  subsItems = res.items;
  const c = res.counts || {};
  const allCount = (c.active || 0) + (c.expired || 0) + (c.disabled || 0);
  const chip = (v, l, n) => `<button class="btn btn-sm ${subsState.status === v ? 'btn-primary' : ''}" data-sub-status="${v}">${l} (${fmt(n)})</button>`;
  setContent(`
    <div class="toolbar">
      <input class="input" id="subs-search" placeholder="جستجو: نام اشتراک، آیدی عددی کاربر، یوزرنیم..." value="${esc(subsState.q)}">
      <button class="btn btn-sm btn-primary" id="subs-search-btn">${svg('search')} جستجو</button>
      <select class="input" id="subs-kind">
        ${[['all', 'همه‌ی انواع'], ['custom', SUBS_KIND_LABEL.custom], ['test', SUBS_KIND_LABEL.test], ['bank', SUBS_KIND_LABEL.bank], ['ssh', SUBS_KIND_LABEL.ssh]].map(([v, l]) => `<option value="${v}" ${v === subsState.kind ? 'selected' : ''}>${l}</option>`).join('')}
      </select>
      <select class="input" id="subs-sort">
        ${SUBS_SORTS.map(([v, l]) => `<option value="${v}" ${v === subsState.sort ? 'selected' : ''}>${l}</option>`).join('')}
      </select>
    </div>
    <div class="toolbar" style="flex-wrap:wrap;gap:6px">
      ${chip('active', 'فعال', c.active || 0)}${chip('expired', 'منقضی', c.expired || 0)}${chip('disabled', 'غیرفعال', c.disabled || 0)}${chip('all', 'همه', allCount)}
    </div>
    <div class="card">
      <div class="table-wrap"><table>
        <thead><tr><th>اشتراک</th><th>کاربر</th><th>حجم / مدت</th><th>انقضا</th><th>وضعیت</th><th>عملیات</th></tr></thead>
        <tbody>${res.items.map((it, i) => {
          const [bc, bl] = SUBS_STATE_BADGE[it.state] || ['badge-muted', it.state];
          const kindKey = subsKindKey(it);
          return `<tr>
            <td><b>${esc(it.name)}</b><div style="opacity:.7;font-size:12px">${SUBS_KIND_LABEL[kindKey] || kindKey}${it.extra ? ' · ' + esc(it.extra) : ''}${it.auto_renew ? ' · 🔁' : ''}</div></td>
            <td><a href="#" data-sub-user="${it.user_id}">${esc(subsUserLabel(it))}</a><div class="mono" style="font-size:12px;opacity:.7">${it.user_id}${it.user_blocked ? ' · 🚫 مسدود' : ''}</div></td>
            <td class="mono">${it.kind === 'custom' ? `${it.volume_gb ? fmt(it.volume_gb) + ' گیگ' : 'نامحدود'} / ${it.duration_days > 0 ? fmt(it.duration_days) + ' روز' : 'نامحدود'}` : '—'}</td>
            <td class="mono">${it.expires_at && String(it.expires_at).trim() ? fmtDate(it.expires_at) : '—'}<div style="opacity:.7;font-size:12px">${esc(subsRemaining(it.expires_at))}</div></td>
            <td><span class="badge ${bc}">${bl}</span></td>
            <td>
              <button class="btn btn-ghost btn-sm" data-sub-manage="${i}">مدیریت</button>
              ${it.link ? `<button class="btn btn-ghost btn-sm" data-sub-copy="${i}">کپی لینک</button>` : ''}
            </td>
          </tr>`;
        }).join('') || `<tr><td colspan="6" class="empty-state"><div class="icon">${svg('empty')}</div>اشتراکی یافت نشد</td></tr>`}</tbody>
      </table></div>
      <div class="pager">
        <button class="btn btn-sm" id="subs-prev" ${subsState.page <= 1 ? 'disabled' : ''}>قبلی</button>
        <span class="mono" style="align-self:center">صفحه ${fmt(subsState.page)} از ${fmt(pages)} · ${fmt(res.total)} اشتراک</span>
        <button class="btn btn-sm" id="subs-next" ${subsState.page >= pages ? 'disabled' : ''}>بعدی</button>
      </div>
    </div>
  `);
  const doSearch = () => { subsState.q = $('#subs-search').value.trim(); subsState.page = 1; renderSubscriptions(); };
  $('#subs-search').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
  $('#subs-search-btn').addEventListener('click', doSearch);
  $('#subs-kind').addEventListener('change', e => { subsState.kind = e.target.value; subsState.page = 1; renderSubscriptions(); });
  $('#subs-sort').addEventListener('change', e => { subsState.sort = e.target.value; subsState.page = 1; renderSubscriptions(); });
  $$('[data-sub-status]', content()).forEach(b => b.addEventListener('click', () => { subsState.status = b.dataset.subStatus; subsState.page = 1; renderSubscriptions(); }));
  $('#subs-prev').addEventListener('click', () => { subsState.page = Math.max(1, subsState.page - 1); renderSubscriptions(); });
  $('#subs-next').addEventListener('click', () => { subsState.page += 1; renderSubscriptions(); });
  $$('[data-sub-user]', content()).forEach(a => a.addEventListener('click', e => { e.preventDefault(); showUserDetail(Number(a.dataset.subUser)); }));
  $$('[data-sub-manage]', content()).forEach(b => b.addEventListener('click', () => openSubscriptionManager(subsItems[Number(b.dataset.subManage)])));
  $$('[data-sub-copy]', content()).forEach(b => b.addEventListener('click', async () => {
    const it = subsItems[Number(b.dataset.subCopy)];
    try { await navigator.clipboard.writeText(it.link); toast('لینک کپی شد.'); } catch (e) { toast('کپی ناموفق بود.', true); }
  }));
}

function openSubscriptionManager(it) {
  if (!it) return;
  const canManage = hasPerm('users');
  const kindKey = subsKindKey(it);
  const [bc, bl] = SUBS_STATE_BADGE[it.state] || ['badge-muted', it.state];
  const act = (a, label, cls = '') => `<button class="btn btn-sm ${cls}" data-sm-act="${a}">${label}</button>`;
  let subBtns = '';
  if (canManage) {
    if (it.kind === 'custom' && !it.is_test) {
      subBtns = act('toggle', it.state === 'disabled' ? '✅ فعال‌سازی' : '⏸ غیرفعال‌سازی')
        + act('rename', '✏️ تغییر نام')
        + (it.duration_days > 0 ? act('autorenew', it.auto_renew ? '🔁 خاموش‌کردن تمدید خودکار' : '🔁 روشن‌کردن تمدید خودکار') : '')
        + act('transfer', '📤 انتقال به کاربر دیگر')
        + act('cut', '✂️ قطع دسترسی و لینک جدید')
        + act('history', '🕘 تاریخچه')
        + act('delete', '🗑 حذف', 'btn-danger');
    } else if (it.kind === 'custom') {
      subBtns = act('history', '🕘 تاریخچه') + act('delete', '🗑 حذف', 'btn-danger');
    } else if (it.kind === 'bank') {
      subBtns = act('toggle', it.state === 'disabled' ? '✅ فعال‌سازی' : '⏸ غیرفعال‌سازی')
        + act('history', '🕘 فعالیت‌ها')
        + act('delete', '🗑 حذف', 'btn-danger');
    } else if (it.kind === 'ssh') {
      subBtns = act('toggle', it.state === 'disabled' ? '✅ فعال‌سازی' : '⏸ غیرفعال‌سازی')
        + act('delete', '🗑 حذف', 'btn-danger');
    }
  }
  const userBtns = act('user-detail', '👤 پروفایل و مدیریت کامل کاربر', 'btn-primary')
    + (canManage ? (it.user_blocked ? act('unblock', '✅ رفع مسدودی کاربر') : act('block', '🚫 مسدودسازی کاربر', 'btn-danger'))
      + act('message', '✉️ ارسال پیام') + act('wallet', '💰 تغییر کیف پول') : '');
  const rows = [
    ['نام اشتراک', esc(it.name)],
    ['نوع', `${SUBS_KIND_LABEL[kindKey] || kindKey}${it.extra ? ' · ' + esc(it.extra) : ''}`],
    ['کاربر', `${esc(subsUserLabel(it))} <span class="mono">(${it.user_id})</span>`],
    ['وضعیت', `<span class="badge ${bc}">${bl}</span>${it.auto_renew ? ' · تمدید خودکار فعال' : ''}`],
    ['حجم / مدت', it.kind === 'custom' ? `${it.volume_gb ? fmt(it.volume_gb) + ' گیگ' : 'نامحدود'} / ${it.duration_days > 0 ? fmt(it.duration_days) + ' روز' : 'نامحدود'}` : '—'],
    ['ساخت', it.created_at ? fmtDate(it.created_at) : '—'],
    ['انقضا', `${it.expires_at && String(it.expires_at).trim() ? fmtDate(it.expires_at) : '—'} (${esc(subsRemaining(it.expires_at))})`],
    ['موجودی کیف پول کاربر', `${fmt(it.user_wallet)} تومان`],
  ];
  openModal(`مدیریت اشتراک: ${esc(it.name)}`, `
    <div class="table-wrap"><table><tbody>${rows.map(([k, v]) => `<tr><th style="width:38%">${k}</th><td>${v}</td></tr>`).join('')}</tbody></table></div>
    ${it.link ? `<label class="field"><span>لینک اشتراک</span><div style="display:flex;gap:6px"><input class="input mono" readonly dir="ltr" value="${esc(it.link)}" id="sm-link"><button class="btn btn-sm" data-sm-act="copy">کپی</button></div></label>` : ''}
    ${subBtns ? `<h4 class="ud-section-title">عملیات اشتراک</h4><div style="display:flex;flex-wrap:wrap;gap:8px">${subBtns}</div>` : ''}
    <h4 class="ud-section-title">عملیات کاربر</h4><div style="display:flex;flex-wrap:wrap;gap:8px">${userBtns}</div>
  `, (body, close) => {
    $$('[data-sm-act]', body).forEach(btn => btn.addEventListener('click', async () => {
      try {
        const done = await runSubscriptionAction(it, btn.dataset.smAct, close);
        if (done) { toast('انجام شد.'); close(); renderSubscriptions(); }
      } catch (e) { handleErr(e); }
    }));
  }, { wide: true });
}

// خروجی true یعنی عملیات تغییر داده و لیست باید تازه شود؛ false یعنی چیزی تغییر نکرده.
async function runSubscriptionAction(it, action, close) {
  const id = it.id, uid = it.user_id;
  if (action === 'copy') { await navigator.clipboard.writeText(it.link); toast('لینک کپی شد.'); return false; }
  if (action === 'user-detail') { close(); showUserDetail(Number(uid)); return false; }
  if (action === 'block') { if (!confirm('این کاربر مسدود شود؟')) return false; await apiPost(`/users/${uid}/block`); return true; }
  if (action === 'unblock') { await apiPost(`/users/${uid}/unblock`); return true; }
  if (action === 'message') {
    const text = (prompt('متن پیام برای کاربر:') || '').trim();
    if (!text) return false;
    await apiPost(`/users/${uid}/message`, { text });
    toast('پیام ارسال شد.');
    return false;
  }
  if (action === 'wallet') {
    const raw = prompt('مبلغ تغییر کیف پول به تومان (عدد منفی = کسر):');
    const delta = Number(String(raw || '').replace(/[,\s]/g, ''));
    if (!raw || !Number.isFinite(delta) || !delta) return false;
    await apiPost(`/users/${uid}/wallet`, { delta });
    return true;
  }
  if (it.kind === 'custom') {
    if (action === 'toggle') { await apiPost(`/custom-configs/${id}/toggle`); return true; }
    if (action === 'rename') {
      const newName = prompt('نام جدید کانفیگ (فقط حروف انگلیسی، عدد و آندرلاین، ۳ تا ۲۰ کاراکتر):');
      if (!newName) return false;
      await apiPost(`/custom-configs/${id}/rename`, { new_name: newName });
      return true;
    }
    if (action === 'autorenew') { await apiPost(`/custom-configs/${id}/auto-renew`, { enabled: !it.auto_renew }); return true; }
    if (action === 'transfer') {
      const targetId = prompt('آی‌دی عددی تلگرام کاربر مقصد:');
      if (!targetId || !/^\d+$/.test(targetId.trim())) { if (targetId) toast('آی‌دی عددی نامعتبر است.', true); return false; }
      if (!confirm('این عملیات غیرقابل بازگشت است. ادامه می‌دهید؟')) return false;
      await apiPost(`/custom-configs/${id}/transfer`, { target_telegram_id: parseInt(targetId.trim(), 10) });
      return true;
    }
    if (action === 'cut') {
      if (!confirm('لینک فعلی از کار می‌افتد و لینک جدیدی با همان حجم/زمان باقی‌مانده صادر می‌شود. ادامه می‌دهید؟')) return false;
      await apiPost(`/custom-configs/${id}/cut-access`);
      return true;
    }
    if (action === 'history') {
      const rows = await apiGet(`/custom-configs/${id}/history`);
      openModal('تاریخچه‌ی سرویس', rows.length
        ? `<div class="table-wrap"><table><thead><tr><th>رویداد</th><th>جزئیات</th><th>تاریخ</th></tr></thead><tbody>${rows.map(r => `<tr><td>${esc(SVC_EVENT_LABEL[r.event_type] || r.event_type)}</td><td>${esc(r.detail || '-')}</td><td class="mono">${fmtDate(r.created_at)}</td></tr>`).join('')}</tbody></table></div>`
        : `<div class="empty-state">${svg('empty')}<div>تاریخچه‌ای ثبت نشده.</div></div>`);
      return false;
    }
    if (action === 'delete') {
      if (!confirm('این سرویس برای همیشه از پنل VPN و از این کاربر حذف می‌شود و غیرقابل بازگشت است. ادامه می‌دهید؟')) return false;
      await apiDelete(`/custom-configs/${id}`);
      return true;
    }
  }
  if (it.kind === 'bank') {
    if (action === 'toggle') { await apiPost(`/user-configs/${id}/disable`, { disabled: it.state !== 'disabled' }); return true; }
    if (action === 'history') {
      const rows = await apiGet(`/user-configs/${id}/activity`);
      openModal('فعالیت‌های کانفیگ', rows.length
        ? `<div class="table-wrap"><table><thead><tr><th>رویداد</th><th>جزئیات</th><th>تاریخ</th></tr></thead><tbody>${rows.map(r => `<tr><td>${esc(r.action)}</td><td>${esc(r.details || '-')}</td><td class="mono">${fmtDate(r.created_at)}</td></tr>`).join('')}</tbody></table></div>`
        : `<div class="empty-state">${svg('empty')}<div>فعالیتی ثبت نشده.</div></div>`);
      return false;
    }
    if (action === 'delete') {
      if (!confirm('این کانفیگ برای همیشه حذف می‌شود و این عملیات غیرقابل بازگشت است. ادامه می‌دهید؟')) return false;
      await apiDelete(`/user-configs/${id}`);
      return true;
    }
  }
  if (it.kind === 'ssh') {
    const sshAct = action === 'toggle' ? (it.state === 'disabled' ? 'enable' : 'disable') : action;
    if (!['enable', 'disable', 'delete'].includes(sshAct)) return false;
    if (sshAct === 'delete' && !confirm('حساب SSH حذف شود؟')) return false;
    try {
      await apiPost(`/subscriptions/ssh/${encodeURIComponent(it.sid)}/action`, { action: sshAct });
    } catch (e) {
      if (sshAct === 'delete' && confirm(`${e.message}\n\nحذف اجباری (فقط از پنل، بدون تماس با نود) انجام شود؟`)) {
        await apiPost(`/subscriptions/ssh/${encodeURIComponent(it.sid)}/action`, { action: 'delete', force: true });
      } else { throw e; }
    }
    return true;
  }
  return false;
}

/* ---------------------------------------------------------- users: bento */
function renderUsersBento(res, pages) {
  setContent(`
    <div class="bn-hero">
      <div><h2>کاربران</h2><p>${fmt(res.total)} کاربر ثبت‌شده</p></div>
      <div class="bn-seg">${['all', 'active', 'expired', 'blocked'].map(s => `<button class="bn-seg-btn ${s === usersState.status ? 'active' : ''}" data-ustatus="${s}">${USERS_STATUS_LABEL[s]}</button>`).join('')}</div>
    </div>
    <input class="bn-search" id="user-search" placeholder="جستجو: آیدی، یوزرنیم، نام..." value="${esc(usersState.q)}" style="margin-bottom:14px">
    ${usersSortSelect()}
    <div class="bn-list">
      ${res.items.map((u, i) => `
        <div class="bn-row bn-card-anim" style="animation-delay:${Math.min(i * 25, 240)}ms">
          ${bnAvatar((u.first_name || u.username || '؟').trim().charAt(0).toUpperCase(), i)}
          <div class="bn-row-main">
            <span class="bn-row-title">${esc(u.username ? '@' + u.username : (u.first_name || '—'))}</span>
            <span class="bn-row-sub">ID: ${u.telegram_id} · عضویت ${fmtDate(u.joined_at)} · کیف پول ${fmt(u.referral_credit)} · خرید ${fmt(u.total_purchase)} · سرویس فعال ${fmt(u.active_services)} · شارژ ${fmt(u.total_topup)}</span>
          </div>
          <div class="bn-row-trail">
            ${bnPill(u.is_blocked ? 'مسدود' : 'فعال', u.is_blocked ? 'no' : 'ok')}
            <button class="bn-btn bn-btn-ghost" data-detail="${u.telegram_id}">جزئیات</button>
            ${hasPerm('users') ? (u.is_blocked
              ? `<button class="bn-btn bn-btn-ok" data-unblock="${u.telegram_id}">رفع مسدودی</button>`
              : `<button class="bn-btn bn-btn-no" data-block="${u.telegram_id}">مسدودسازی</button>`) : ''}
          </div>
        </div>
      `).join('') || `<div class="empty-state"><div class="icon">${svg('empty')}</div>کاربری یافت نشد</div>`}
    </div>
    <div class="pager" style="margin-top:16px">${Array.from({ length: pages }, (_, i) => i + 1).map(p => `<button class="btn btn-sm ${p === usersState.page ? 'btn-primary' : ''}" data-page="${p}">${p}</button>`).join('')}</div>
  `);
  $('#user-search').addEventListener('keydown', e => { if (e.key === 'Enter') { usersState.q = e.target.value; usersState.page = 1; renderUsers(); } });
  $$('.bn-seg-btn[data-ustatus]', content()).forEach(b => b.addEventListener('click', () => { usersState.status = b.dataset.ustatus; usersState.page = 1; renderUsers(); }));
  bindUsersSort();
  $$('[data-page]', content()).forEach(b => b.addEventListener('click', () => { usersState.page = Number(b.dataset.page); renderUsers(); }));
  $$('[data-block]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/users/${b.dataset.block}/block`); toast('کاربر مسدود شد.'); renderUsers(); } catch (e) { handleErr(e); }
  }));
  $$('[data-unblock]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/users/${b.dataset.unblock}/unblock`); toast('رفع مسدودیت شد.'); renderUsers(); } catch (e) { handleErr(e); }
  }));
  $$('[data-detail]', content()).forEach(b => b.addEventListener('click', () => showUserDetail(Number(b.dataset.detail))));
}

/* ---------------------------------------------------------- users: glass */

/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

/* --------------------------------------------------- users: brutalist --- */
// چیدمان «دایرکتوری/تابلوی اعلانات» به‌جای جدول: هر کاربر یه کارت با
// آواتار حرفی درشت و برچسب وضعیت مثل استیکر گوشه‌ی پرونده.
function renderUsersBrutalist(res, pages) {
  const activeCount = res.items.filter(u => !u.is_blocked).length;
  setContent(`
    <div class="bru-hero" style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
      <div>
        <h2>دایرکتوری کاربران</h2>
        <p>${fmt(res.total)} کاربر ثبت‌شده — ${fmt(activeCount)} فعال در این صفحه</p>
      </div>
    </div>

    <div class="bru-toolbar">
      <input class="bru-search-input" id="user-search" placeholder="جستجو: آیدی، یوزرنیم، نام..." value="${esc(usersState.q)}">
      <div class="bru-seg" role="tablist">
        ${['all', 'active', 'expired', 'blocked'].map(s => `<button class="bru-seg-btn ${s === usersState.status ? 'active' : ''}" data-ustatus="${s}">${USERS_STATUS_LABEL[s]}</button>`).join('')}
      </div>
      ${usersSortSelect()}
    </div>

    <div class="bru-user-grid">
      ${res.items.map((u, i) => `
        <div class="bru-user-card bru-card-anim" style="animation-delay:${Math.min(i * 35, 300)}ms">
          <span class="bru-flag ${u.is_blocked ? 'bru-flag-no' : 'bru-flag-ok'}">${u.is_blocked ? 'مسدود' : 'فعال'}</span>
          <div class="bru-user-avatar mono">${esc((u.first_name || u.username || String(u.telegram_id)).trim().charAt(0).toUpperCase())}</div>
          <div class="bru-user-name">${esc(u.username ? '@' + u.username : (u.first_name || '—'))}</div>
          <div class="bru-user-id mono">ID: ${u.telegram_id}</div>
          <div class="bru-user-joined mono">عضویت: ${fmtDate(u.joined_at)}</div>
          <div class="bru-user-joined mono">کیف پول: ${fmt(u.referral_credit)}</div>
          <div class="bru-user-joined mono">میزان خرید: ${fmt(u.total_purchase)}</div>
          <div class="bru-user-joined mono">سرویس فعال: ${fmt(u.active_services)}</div>
          <div class="bru-user-joined mono">میزان شارژ: ${fmt(u.total_topup)}</div>
          <div class="bru-user-actions">
            <button class="btn btn-sm btn-ghost" data-detail="${u.telegram_id}">جزئیات</button>
            ${hasPerm('users') ? (u.is_blocked
              ? `<button class="btn btn-sm" data-unblock="${u.telegram_id}">رفع مسدودی</button>`
              : `<button class="btn btn-sm btn-danger" data-block="${u.telegram_id}">مسدودسازی</button>`) : ''}
          </div>
        </div>
      `).join('') || `<div class="empty-state" style="grid-column:1/-1"><div class="icon">${svg('empty')}</div>کاربری یافت نشد</div>`}
    </div>

    <div class="pager" style="margin-top:16px">${Array.from({ length: pages }, (_, i) => i + 1).map(p => `<button class="btn btn-sm ${p === usersState.page ? 'btn-primary' : ''}" data-page="${p}">${p}</button>`).join('')}</div>
  `);
  $('#user-search').addEventListener('keydown', e => { if (e.key === 'Enter') { usersState.q = e.target.value; usersState.page = 1; renderUsers(); } });
  $$('.bru-seg-btn[data-ustatus]', content()).forEach(b => b.addEventListener('click', () => { usersState.status = b.dataset.ustatus; usersState.page = 1; renderUsers(); }));
  bindUsersSort();
  $$('[data-page]', content()).forEach(b => b.addEventListener('click', () => { usersState.page = Number(b.dataset.page); renderUsers(); }));
  $$('[data-block]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/users/${b.dataset.block}/block`); toast('کاربر مسدود شد.'); renderUsers(); } catch (e) { handleErr(e); }
  }));
  $$('[data-unblock]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/users/${b.dataset.unblock}/unblock`); toast('رفع مسدودیت شد.'); renderUsers(); } catch (e) { handleErr(e); }
  }));
  $$('[data-detail]', content()).forEach(b => b.addEventListener('click', () => showUserDetail(Number(b.dataset.detail))));
}

async function showUserDetail(tgId) {
  const d = await apiGet(`/users/${tgId}`);
  const services = await apiGet(`/users/${tgId}/custom-configs`).catch(() => []);
  const bankConfigs = await apiGet(`/users/${tgId}/configs`).catch(() => []);
  const refs = await apiGet(`/users/${tgId}/referrals`).catch(() => ({ items: [], total: 0, pending_bonus_count: 0, bonus_amount: 0 }));
  const isSenior = hasPerm('users');
  const u = d.user;
  const displayName = u.username ? '@' + u.username : (u.first_name || tgId);
  const initial = (u.first_name || u.username || String(tgId)).trim().charAt(0).toUpperCase();

  const statCards = [
    { label: 'کیف پول', val: `${fmt(u.referral_credit)} تومان` },
    { label: 'زیرمجموعه‌ها', val: fmt(d.referral.count) },
    { label: 'تاریخ عضویت', val: fmtDate(u.joined_at) },
    { label: 'تست دریافتی', val: u.test_used ? 'بله' : 'خیر' },
  ];
  if (d.is_reseller) statCards.push({ label: 'اعتبار نمایندگی', val: `${fmt(d.reseller_credit)} گیگ` });
  const ws = d.wallet_status || {};
  if (ws.limit > 0 || ws.debt > 0) {
    statCards.push({ label: 'سقف اعتبار پس‌پرداخت', val: `${fmt(ws.limit)} تومان` });
    statCards.push({ label: 'بدهی فعلی', val: `${fmt(ws.debt)} تومان` });
  }
  if (u.referred_by) statCards.push({ label: 'دعوت‌شده توسط', val: `#${u.referred_by}` });

  openModal(`کاربر ${esc(displayName)}`, `
    <div class="ud-head">
      <div class="ud-avatar">${esc(initial)}</div>
      <div class="ud-id">
        <strong>${esc(displayName)}</strong>
        <span class="mono">ID: ${tgId}</span>
      </div>
      <span class="badge ${u.is_blocked ? 'badge-rejected' : 'badge-approved'}">${u.is_blocked ? 'مسدود' : 'فعال'}</span>
      ${hasPerm('resellers') && !d.is_reseller && !d.agent_tier ? `<button class="btn btn-sm btn-primary" id="ud-make-reseller">🏪 نماینده کردن</button>` : ''}
      ${hasPerm('resellers') && (d.is_reseller || d.agent_tier) ? `${d.is_reseller ? '<button class="btn btn-sm btn-primary" id="ud-edit-reseller">⚙️ ویرایش نمایندگی</button>' : ''}<button class="btn btn-sm" id="ud-change-reseller-tier">⚖️ تغییر سطح نماینده</button><button class="btn btn-sm btn-danger" id="ud-delete-reseller">🗑 حذف نمایندگی</button>` : ''}
      ${historyBtn('user', tgId)}
    </div>

    <div class="ud-stats">
      ${statCards.map(s => `<div class="ud-stat"><span>${s.label}</span><b class="mono">${s.val}</b></div>`).join('')}
    </div>

    ${isSenior ? `<div class="form-row" style="margin:16px 0">
      <input class="input" id="wallet-delta" type="number" placeholder="مبلغ (مثبت=افزایش، منفی=کاهش)">
      <button class="btn btn-primary" id="wallet-submit">اعمال</button>
    </div>` : ''}

    ${hasPerm('resellers') ? `<div class="form-row" style="margin:16px 0">
      <input class="input" id="credit-limit-amount" type="number" min="0" value="${u.credit_limit || 0}" placeholder="سقف اعتبار پس‌پرداخت (تومان، ۰ = سقف پیش‌فرض سطح)">
      <button class="btn btn-primary" id="credit-limit-submit">ثبت سقف</button>
    </div>` : ''}

    ${isSenior ? `<div class="form-row" style="margin:16px 0">
      <input class="input" id="user-msg-text" type="text" placeholder="متن پیام مستقیم به این کاربر...">
      <button class="btn btn-primary" id="user-msg-submit">ارسال پیام</button>
    </div>` : ''}

    ${services.length ? `
    <h4 class="ud-section-title">سرویس‌های مستقیم-پنل</h4>
    <div id="ud-services">${renderUserServices(services, isSenior)}</div>
    ` : ''}

    ${bankConfigs.length ? `
    <h4 class="ud-section-title">کانفیگ‌های بانک محصول</h4>
    <div id="ud-bank-configs">${renderUserBankConfigs(bankConfigs, isSenior)}</div>
    ` : ''}

    <h4 class="ud-section-title">سفارش‌های اخیر</h4>
    <div class="table-wrap"><table><thead><tr><th>#</th><th>محصول</th><th>مبلغ</th><th>وضعیت</th><th>تاریخ</th></tr></thead>
    <tbody>${d.orders.slice(0, 10).map(o => `<tr><td class="mono">#${o.id}</td><td>${esc(o.product_name || '-')}</td><td class="mono">${fmt(o.final_price)}${tierDiscountNote(o)}</td><td>${esc(o.status)}</td><td class="mono">${fmtDate(o.created_at)}</td></tr>`).join('') || `<tr><td colspan="5" class="empty-state"><div class="icon">${svg('empty')}</div>سفارشی نیست</td></tr>`}</tbody></table></div>

    <h4 class="ud-section-title">زیرمجموعه‌ها (${fmt(refs.total)})</h4>
    ${refs.suspended ? '<div class="hint-text" style="color:var(--danger,#c0392b)">⛔️ پاداش رفرال این کاربر به‌خاطر تشخیص تقلب متوقف شده است.</div>' : ''}
    ${isSenior && refs.pending_bonus_count > 0 && refs.bonus_amount > 0 ? `<div class="form-row" style="margin:8px 0"><span class="hint-text">${fmt(refs.pending_bonus_count)} زیرمجموعه پاداش دعوت دریافت نکرده‌اند (هرکدام ${fmt(refs.bonus_amount)} تومان)</span><button class="btn btn-primary btn-sm" id="ud-pay-pending-refs">💰 پرداخت پاداش‌های پرداخت‌نشده</button></div>` : ''}
    <div class="table-wrap"><table><thead><tr><th>کاربر</th><th>آیدی</th><th>عضویت</th><th>خرید تاییدشده</th><th>پاداش دعوت</th></tr></thead>
    <tbody>${(refs.items || []).map(r => `<tr><td>${esc(r.username ? '@' + r.username : (r.first_name || '-'))}</td><td class="mono">${r.telegram_id}</td><td class="mono">${fmtDate(r.joined_at)}</td><td class="mono">${fmt(r.approved_orders)}</td><td>${r.bonus_given ? '✅ پرداخت شده' : '⏳ پرداخت نشده'}</td></tr>`).join('') || `<tr><td colspan="5" class="empty-state"><div class="icon">${svg('empty')}</div>زیرمجموعه‌ای نیست</td></tr>`}</tbody></table></div>

    <h4 class="ud-section-title">شارژهای کیف پول</h4>
    <div class="table-wrap"><table><thead><tr><th>#</th><th>مبلغ</th><th>وضعیت</th><th>تاریخ</th></tr></thead>
    <tbody>${(d.topups || []).slice(0, 10).map(t => `<tr><td class="mono">#${t.id}</td><td class="mono">${fmt(t.amount)}</td><td>${esc(t.status)}</td><td class="mono">${fmtDate(t.created_at)}</td></tr>`).join('') || `<tr><td colspan="4" class="empty-state"><div class="icon">${svg('empty')}</div>شارژی ثبت نشده</td></tr>`}</tbody></table></div>

    <h4 class="ud-section-title">لاگ تغییرات موجودی کیف پول</h4>
    <div class="table-wrap"><table><thead><tr><th>نوع</th><th>تغییر</th><th>قبل</th><th>بعد</th><th>توضیح</th><th>تاریخ</th></tr></thead>
    <tbody>${(d.wallet_transactions || []).map(t => `<tr><td>${esc(t.label)}</td><td class="mono" dir="ltr">${t.delta > 0 ? '+' : ''}${fmt(t.delta)}</td><td class="mono">${fmt(t.balance_before)}</td><td class="mono">${fmt(t.balance_after)}</td><td>${esc(t.note || '-')}</td><td class="mono">${fmtDate(t.created_at)}</td></tr>`).join('') || `<tr><td colspan="6" class="empty-state"><div class="icon">${svg('empty')}</div>تراکنشی ثبت نشده</td></tr>`}</tbody></table></div>
  `, (body, close) => {
    const submitBtn = $('#wallet-submit', body);
    if (submitBtn) submitBtn.addEventListener('click', async () => {
      const delta = Number($('#wallet-delta', body).value);
      if (!delta) return;
      try { await apiPost(`/users/${tgId}/wallet`, { delta }); toast('کیف پول به‌روزرسانی شد.'); close(); }
      catch (e) { handleErr(e); }
    });
    const payRefsBtn = $('#ud-pay-pending-refs', body);
    if (payRefsBtn) payRefsBtn.addEventListener('click', async () => {
      try { const r = await apiPost(`/users/${tgId}/referrals/pay-pending`); toast(`${fmt(r.total)} تومان پاداش دعوت پرداخت شد.`); close(); await showUserDetail(tgId); }
      catch (e) { handleErr(e); }
    });
    const creditLimitBtn = $('#credit-limit-submit', body);
    if (creditLimitBtn) creditLimitBtn.addEventListener('click', async () => {
      const amount = Number($('#credit-limit-amount', body).value);
      if (!Number.isFinite(amount) || amount < 0) { toast('مبلغ نامعتبر است.', true); return; }
      try { await apiPut(`/users/${tgId}/credit-limit`, { amount }); toast('سقف اعتبار ثبت شد.'); close(); await showUserDetail(tgId); }
      catch (e) { handleErr(e); }
    });
    const msgBtn = $('#user-msg-submit', body);
    if (msgBtn) msgBtn.addEventListener('click', async () => {
      const input = $('#user-msg-text', body);
      const text = input.value.trim();
      if (!text) return;
      try { await apiPost(`/users/${tgId}/message`, { text }); toast('پیام ارسال شد.'); input.value = ''; }
      catch (e) { handleErr(e); }
    });
    if (isSenior) wireUserServiceActions(body, tgId, close);
    if (isSenior) wireUserBankConfigActions(body, tgId, close);
    const makeResellerBtn = $('#ud-make-reseller', body);
    if (makeResellerBtn) makeResellerBtn.addEventListener('click', () => openMakeResellerModal(tgId, close));
    const editResellerBtn = $('#ud-edit-reseller', body);
    if (editResellerBtn) editResellerBtn.addEventListener('click', () => openResellerManageModal(tgId));
    const changeTierBtn = $('#ud-change-reseller-tier', body);
    if (changeTierBtn) changeTierBtn.addEventListener('click', () => openChangeResellerTierModal(tgId, close, d.agent_tier));
    const deleteResellerBtn = $('#ud-delete-reseller', body);
    if (deleteResellerBtn) deleteResellerBtn.addEventListener('click', async () => {
      if (!confirm('حذف کامل نمایندگی این کاربر و موجودی‌های نمایندگی انجام شود؟')) return;
      try {
        await apiDelete(`/resellers/${tgId}`);
        toast('نمایندگی حذف شد.');
        close();
        await showUserDetail(tgId);
      } catch (e) { handleErr(e); }
    });
  }, { wide: true });
}

/* نماینده‌کردن مستقیم یک کاربر بر اساس سطح‌های نمایندگی (برنزی، نقره‌ای، طلایی، VIP) */
function openMakeResellerModal(tgId, closeUserModal) {
  apiGet('/reseller-tiers').then(all => {
    const tiers = all.filter(t => t.is_enabled);
    if (!tiers.length) { toast('هیچ سطح نمایندگی فعالی وجود ندارد.', true); return; }
    openMakeResellerTierModal(tgId, closeUserModal, tiers);
  }).catch(handleErr);
}

/* تغییر سطح نمایندگیِ یک نماینده‌ی موجود (مثلاً برنزی -> طلایی) بدون نیاز به
   حذف کامل و ساخت دوباره‌ی دستی. */
function openChangeResellerTierModal(tgId, closeUserModal, currentTierCode) {
  apiGet('/reseller-tiers').then(all => {
    const tiers = all.filter(t => t.is_enabled && t.code !== currentTierCode);
    if (!tiers.length) { toast('سطح فعال دیگری برای انتقال این نماینده وجود ندارد.', true); return; }
    openMakeResellerTierModal(tgId, closeUserModal, tiers, { isChange: true });
  }).catch(handleErr);
}

function openMakeResellerTierModal(tgId, closeUserModal, tiers, opts = {}) {
  const isChange = !!opts.isChange;
  openModal(isChange ? `تغییر سطح نمایندگی کاربر ${tgId}` : `نماینده کردن کاربر ${tgId}`, `
    <div class="form-grid">
      <div><b>سطح نمایندگی</b></div>
      <select class="input" id="mr-tier">
        ${tiers.map(t => `<option value="${esc(t.code)}">${esc(t.icon)} ${esc(t.title)} (${esc(t.model_label)})</option>`).join('')}
      </select>
      <div class="hint-text" id="mr-tier-info"></div>

      <div id="mr-percent-wrap" style="display:none">
        <div><b>درصد کمیسیون</b></div>
        <div class="hint-text" id="mr-percent-hint"></div>
        <input class="input" id="mr-percent" type="number" min="1" max="100" placeholder="مثلاً 10">
      </div>

      <div id="mr-discount-wrap" style="display:none">
        <div><b>درصد تخفیف نقره‌ای</b></div>
        <div class="hint-text">این درصد به‌صورت اختصاصی برای همین نماینده ثبت می‌شود. تخفیف پلکانی خرید عمده می‌تواند آن را بیشتر کند.</div>
        <input class="input" id="mr-discount" type="number" min="1" max="100" placeholder="مثلاً 15">
      </div>

      <div id="mr-volume-wrap" style="display:none">
        <div><b>حجم اعتبار اولیه (گیگ)</b></div>
        <input class="input" id="mr-volume" type="number" placeholder="مثلاً 500">
      </div>

      <div id="mr-fixed-wrap" style="display:none">
        <div><b>محصولات اولیه نماینده</b></div>
        <div class="hint-text">چند محصول را هم‌زمان انتخاب کن و برای هرکدام تعداد جداگانه بده.</div>
        <div id="mr-fixed-products" style="display:grid;gap:8px;max-height:260px;overflow:auto;padding:4px 0">
          <div class="hint-text">در حال بارگذاری...</div>
        </div>
      </div>

      <div id="mr-panel-wrap" style="display:none">
        <div><b>پنل اعتباری نمایندگی (اختیاری)</b></div>
        <select class="input" id="mr-panel"><option value="">پیش‌فرض خودکار</option></select>
      </div>

      <div id="mr-note-wrap">
        <div><b>یادداشت داخلی (اختیاری)</b></div>
        <textarea class="input" id="mr-note" rows="2" placeholder="${isChange ? 'مثلاً دلیل تغییر سطح این نماینده...' : 'مثلاً دلیل نماینده‌کردن این کاربر...'}"></textarea>
      </div>

      ${isChange ? '<div class="hint-text">با ثبت، وضعیت نمایندگیِ فعلی این کاربر (بات اختصاصی، اعتبار/موجودی، کمیسیون یا تخفیف) کامل پاک و سطح جدید مثل ساخت نمایندگی از نو برایش تنظیم می‌شود. کیف پول و سابقه‌ی مالی او دست‌نخورده می‌ماند.</div>' : ''}
      <button class="btn btn-primary" id="mr-submit">${isChange ? 'ثبت و تغییر سطح' : 'ثبت و نماینده کردن'}</button>
    </div>
  `, (body, close) => {
    const tierSel = $('#mr-tier', body);
    const currentTier = () => tiers.find(t => t.code === tierSel.value);
    const show = (id, on) => { $(id, body).style.display = on ? '' : 'none'; };
    const syncTier = () => {
      const t = currentTier();
      const features = [t.has_dedicated_bot && 'بات مستقل', t.has_web_panel && 'پنل وب', t.has_miniapp && 'مینی‌اپ'].filter(Boolean);
      $('#mr-tier-info', body).textContent = [t.summary, features.length ? `${settingsUiText('\u0627\u0645\u06a9\u0627\u0646\u0627\u062a')}: ${features.join(', ')}` : ''].filter(Boolean).join(' | ');
      show('#mr-percent-wrap', t.model === 'commission');
      show('#mr-discount-wrap', t.model === 'discount' && t.code === 'silver');
      show('#mr-volume-wrap', t.model === 'volume_credit');
      show('#mr-fixed-wrap', t.model === 'fixed_product');
      show('#mr-panel-wrap', t.model === 'volume_credit' || t.model === 'fixed_product');
      if (t.model === 'commission') {
        const low = t.commission_min || 1;
        const high = t.commission_max || 100;
        $('#mr-percent-hint', body).textContent = `درصدی از هر خرید مشتریانی که با لینک اختصاصی او وارد شوند به کیف پولش واریز می‌شود (بازه مجاز: ${low} تا ${high}).`;
      }
    };
    tierSel.addEventListener('change', syncTier);
    syncTier();

    apiGet('/reseller-panels-lite').then(panels => {
      const sel = $('#mr-panel', body);
      if (sel) sel.insertAdjacentHTML('beforeend', panels.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join(''));
    }).catch(() => {});

    apiGet('/reseller-fixed-products').then(products => {
      const wrap = $('#mr-fixed-products', body);
      if (!wrap) return;
      wrap.innerHTML = products.length
        ? products.map(p => `
          <label style="display:grid;grid-template-columns:auto 1fr 95px;align-items:center;gap:8px;padding:9px 10px;border:1px solid var(--border,#333);border-radius:10px">
            <input type="checkbox" class="mr-product-check" data-product-id="${p.id}">
            <span>${esc(p.name)}</span>
            <input class="input mr-product-qty" data-product-id="${p.id}" type="number" min="1" value="1" placeholder="تعداد">
          </label>`).join('')
        : '<div class="hint-text">محصول خودکار فعالی برای تخصیص وجود ندارد.</div>';
    }).catch(() => {});

    $('#mr-submit', body).addEventListener('click', async () => {
      const t = currentTier();
      const payload = {
        tier_code: t.code,
        note: $('#mr-note', body).value.trim() || null,
      };
      if (t.model === 'commission') {
        const percent = Number($('#mr-percent', body).value);
        const low = t.commission_min || 1;
        const high = t.commission_max || 100;
        if (!percent || percent < low || percent > high) { toast(`درصد کمیسیون باید بین ${low} تا ${high} باشد.`, true); return; }
        payload.percent = percent;
      } else if (t.model === 'discount') {
        const discount = Number($('#mr-discount', body).value);
        if (!discount || discount < 1 || discount > 100) { toast('درصد تخفیف نقره‌ای باید بین ۱ تا ۱۰۰ باشد.', true); return; }
        payload.discount_percent = discount;
      } else if (t.model === 'fixed_product') {
        const items = $$('.mr-product-check', body).filter(x => x.checked).map(ch => {
          const qtyEl = $$(`.mr-product-qty[data-product-id="${ch.dataset.productId}"]`, body)[0];
          return { product_id: Number(ch.dataset.productId), quantity: Number(qtyEl?.value || 0) };
        }).filter(x => x.quantity > 0);
        if (!items.length) { toast('حداقل یک محصول را انتخاب کنید.', true); return; }
        payload.supply_items = items;
        payload.supply_product_id = items[0].product_id;
        payload.supply_qty = items[0].quantity;
      } else if (t.model === 'volume_credit') {
        const volume_gb = Number($('#mr-volume', body).value);
        if (!volume_gb || volume_gb <= 0) { toast('حجم اعتبار اولیه نامعتبر است.', true); return; }
        payload.volume_gb = volume_gb;
      }
      if (t.model === 'volume_credit' || t.model === 'fixed_product') {
        payload.panel_server_id = $('#mr-panel', body).value ? Number($('#mr-panel', body).value) : null;
      }
      if (isChange && !confirm('تایید می‌کنی؟ وضعیت نمایندگیِ فعلی این کاربر کامل پاک و سطح جدید از نو تنظیم می‌شود.')) return;
      try {
        await apiPost(`/users/${tgId}/${isChange ? 'change-reseller-tier' : 'make-reseller'}`, payload);
        toast(isChange ? 'سطح نمایندگی با موفقیت تغییر کرد.' : 'کاربر با موفقیت نماینده شد.');
        close();
        if (closeUserModal) closeUserModal();
        showUserDetail(tgId);
      } catch (e) { handleErr(e); }
    });
  });
}

/* سرویس‌های مستقیم-پنل یک کاربر - معادل «سرویس‌های من» در ربات، ولی از
   سمت ادمین: فعال/غیرفعال، تغییر نام، تمدید خودکار، انتقال، قطع دسترسی و
   تاریخچه، دقیقاً روی همان توابع دیتابیس/پروایدر که بات و مینی‌اپ استفاده
   می‌کنند (پس رفتار و اثر هر سه سطح یکسان است). */
function renderUserServices(services, isSenior) {
  return `<div class="table-wrap"><table><thead><tr>
    <th>نام</th><th>حجم/مدت</th><th>وضعیت</th><th>تمدید خودکار</th>${isSenior ? '<th>اکشن‌ها</th>' : ''}
  </tr></thead><tbody>
  ${services.map(c => `
    <tr data-svc-row="${c.id}">
      <td>${esc(c.display_name)}${c.is_test ? ' <span class="badge">تست</span>' : ''}</td>
      <td class="mono">${c.volume_gb} گیگ / ${c.duration_days} روز</td>
      <td><span class="badge ${c.enabled ? 'badge-approved' : 'badge-rejected'}">${c.enabled ? 'فعال' : 'غیرفعال'}</span></td>
      <td>${c.duration_days > 0 ? (c.auto_renew ? 'فعال' : 'غیرفعال') : '—'}</td>
      ${isSenior && !c.is_test ? `<td style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn btn-sm" data-svc-action="toggle" data-svc-id="${c.id}">${c.enabled ? 'غیرفعال کردن' : 'فعال کردن'}</button>
        <button class="btn btn-sm" data-svc-action="rename" data-svc-id="${c.id}">تغییر نام</button>
        ${c.duration_days > 0 ? `<button class="btn btn-sm" data-svc-action="autorenew" data-svc-id="${c.id}" data-svc-state="${c.auto_renew ? 1 : 0}">تمدید خودکار</button>` : ''}
        <button class="btn btn-sm" data-svc-action="transfer" data-svc-id="${c.id}">انتقال</button>
        <button class="btn btn-sm" data-svc-action="cut" data-svc-id="${c.id}">قطع دسترسی</button>
        <button class="btn btn-sm" data-svc-action="history" data-svc-id="${c.id}">تاریخچه</button>
        <button class="btn btn-sm btn-danger" data-svc-action="delete" data-svc-id="${c.id}">حذف</button>
      </td>` : (isSenior ? '<td>—</td>' : '')}
    </tr>
  `).join('')}
  </tbody></table></div>`;
}

/* کانفیگ‌های بانک محصول (لینک‌های ساده‌ی از پیش‌آماده - نه سرویس مستقیم-پنل
   بالا) که به این کاربر اختصاص یافته‌اند: مشاهده، غیرفعال/فعال کردن نمایش
   لینک و حذف کامل. */
function renderUserBankConfigs(configs, isSenior) {
  return `<div class="table-wrap"><table><thead><tr>
    <th>محصول</th><th>سفارش</th><th>لینک</th><th>وضعیت</th>${isSenior ? '<th>اکشن‌ها</th>' : ''}
  </tr></thead><tbody>
  ${configs.map(c => `
    <tr data-cfg-row="${c.id}">
      <td>${esc(c.product_name)}</td>
      <td class="mono">${c.order_id ? '#' + c.order_id : '-'}</td>
      <td class="mono" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.link || '-')}</td>
      <td><span class="badge ${c.is_disabled ? 'badge-rejected' : 'badge-approved'}">${c.is_disabled ? 'غیرفعال' : 'فعال'}</span></td>
      ${isSenior ? `<td style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn btn-sm" data-cfg-action="toggle" data-cfg-id="${c.id}" data-cfg-state="${c.is_disabled ? 1 : 0}">${c.is_disabled ? 'فعال کردن' : 'غیرفعال کردن'}</button>
        <button class="btn btn-sm btn-danger" data-cfg-action="delete" data-cfg-id="${c.id}">حذف</button>
      </td>` : ''}
    </tr>
  `).join('')}
  </tbody></table></div>`;
}

function wireUserBankConfigActions(body, tgId, close) {
  $$('[data-cfg-action]', body).forEach(el => {
    el.addEventListener('click', async () => {
      const action = el.dataset.cfgAction;
      const id = el.dataset.cfgId;
      try {
        if (action === 'toggle') {
          const disabled = el.dataset.cfgState !== '1';
          await apiPost(`/user-configs/${id}/disable`, { disabled });
        } else if (action === 'delete') {
          if (!confirm('این کانفیگ برای همیشه حذف می‌شود و این عملیات غیرقابل بازگشت است. ادامه می‌دهید؟')) return;
          await apiDelete(`/user-configs/${id}`);
        }
        toast('انجام شد.');
        close();
        showUserDetail(tgId);
      } catch (e) { handleErr(e); }
    });
  });
}

const SVC_EVENT_LABEL = {
  purchase: 'خرید', renewal: 'تمدید', toggle: 'فعال/غیرفعال',
  auto_renew_toggle: 'تمدید خودکار', rename: 'تغییر نام', transfer: 'انتقال',
  cut_access: 'قطع دسترسی', auto_renew: 'تمدید خودکار (خودکار انجام‌شده)',
};

function wireUserServiceActions(body, tgId, close) {
  $$('[data-svc-action]', body).forEach(el => {
    el.addEventListener('click', async () => {
      const action = el.dataset.svcAction;
      const id = el.dataset.svcId;
      try {
        if (action === 'toggle') {
          await apiPost(`/custom-configs/${id}/toggle`);
        } else if (action === 'rename') {
          const newName = prompt('نام جدید کانفیگ (فقط حروف انگلیسی، عدد و آندرلاین، ۳ تا ۲۰ کاراکتر):');
          if (!newName) return;
          await apiPost(`/custom-configs/${id}/rename`, { new_name: newName });
        } else if (action === 'autorenew') {
          const enabled = el.dataset.svcState !== '1';
          await apiPost(`/custom-configs/${id}/auto-renew`, { enabled });
        } else if (action === 'transfer') {
          const targetId = prompt('آی‌دی عددی تلگرام کاربر مقصد:');
          if (!targetId || !/^\d+$/.test(targetId.trim())) { toast('آی‌دی عددی نامعتبر است.', true); return; }
          if (!confirm('این عملیات غیرقابل بازگشت است. ادامه می‌دهید؟')) return;
          await apiPost(`/custom-configs/${id}/transfer`, { target_telegram_id: parseInt(targetId.trim(), 10) });
        } else if (action === 'cut') {
          if (!confirm('لینک فعلی از کار می‌افتد و لینک جدیدی با همان حجم/زمان باقی‌مانده صادر می‌شود. ادامه می‌دهید؟')) return;
          await apiPost(`/custom-configs/${id}/cut-access`);
        } else if (action === 'history') {
          const rows = await apiGet(`/custom-configs/${id}/history`);
          openModal('تاریخچه‌ی سرویس', rows.length
            ? `<div class="table-wrap"><table><thead><tr><th>رویداد</th><th>جزئیات</th><th>تاریخ</th></tr></thead><tbody>${rows.map(r => `<tr><td>${esc(SVC_EVENT_LABEL[r.event_type] || r.event_type)}</td><td>${esc(r.detail || '-')}</td><td class="mono">${fmtDate(r.created_at)}</td></tr>`).join('')}</tbody></table></div>`
            : `<div class="empty-state">${svg('empty')}<div>تاریخچه‌ای ثبت نشده.</div></div>`);
          return;
        } else if (action === 'delete') {
          if (!confirm('این سرویس برای همیشه از پنل VPN و از این کاربر حذف می‌شود و غیرقابل بازگشت است. ادامه می‌دهید؟')) return;
          await apiDelete(`/custom-configs/${id}`);
        }
        toast('انجام شد.');
        close();
        showUserDetail(tgId);
      } catch (e) { handleErr(e); }
    });
  });
}

/* ============================================================ catalog === */
let catalogTab = 'products';
/* منبع کانفیگ محصول: بانک کانفیگ (پیش‌فرض) یا اتصال مستقیم به یک پنل مشخص.
   این سه تابع بین هر سه تم کاتالوگ (پیش‌فرض/بنتو/برتالیست) مشترک است. */
// روش‌های پرداخت مجاز برای یک محصول (کیف پول/کارت/آبان‌گیت‌وی/کریپتو/درگاه‌های
// سفارشی) - دقیقاً معادل چیزی که بات از داخل منوی محصول می‌سازد؛ چون هر دو
// روی database.py (product_allows_payment_method) اعمال می‌شوند، همین‌جا هم
// چک‌اوت مینی‌اپ و هم بات با تنظیم یکسان رفتار می‌کنند.
async function openProductPaymentMethodsModal(product) {
  let methods, current;
  try {
    [methods, current] = await Promise.all([
      apiGet('/payment-methods'),
      apiGet(`/products/${product.id}/payment-methods`),
    ]);
  } catch (e) { return handleErr(e); }
  const allowed = current.allowed; // null/[] یعنی «همه مجازند»
  const isAllowed = (key) => !allowed || !allowed.length || allowed.includes(key);
  openModal(`💳 روش‌های پرداخت مجاز: ${esc(product.name)}`, `
    <p class="card-sub">اگر هیچ‌کدام تیک نخورَد یا همه تیک بخورند، یعنی این محصول با همه‌ی
      روش‌های پرداخت فعال قابل خرید است (بدون محدودیت).</p>
    <div class="form-grid">
      ${methods.map(m => `
        <label class="field field-row">
          <span>${esc(m.label)}${!m.enabled ? ' (غیرفعال)' : ''}${m.min_amount ? ` — حداقل ${fmt(m.min_amount)} تومان` : ''}</span>
          <input type="checkbox" data-pm="${esc(m.key)}" ${isAllowed(m.key) ? 'checked' : ''}>
        </label>`).join('') || '<div class="card-sub">هیچ روش پرداختی تعریف نشده.</div>'}
    </div>
    <button class="btn btn-primary" id="pm-save" style="margin-top:12px">ذخیره</button>
  `, (b, close) => {
    $('#pm-save', b).addEventListener('click', async () => {
      const boxes = $$('[data-pm]', b);
      const checked = boxes.filter(i => i.checked).map(i => i.dataset.pm);
      const methodsPayload = (checked.length === 0 || checked.length === boxes.length) ? null : checked;
      try {
        await apiPost(`/products/${product.id}/payment-methods`, { methods: methodsPayload });
        toast('ذخیره شد.'); close();
      } catch (e) { handleErr(e); }
    });
  });
}

// روش‌های پرداخت مجاز برای «شارژ کیف پول» - دقیقاً معادل
// openProductPaymentMethodsModal اما مستقل از محصول (سراسری، فقط برای
// فرایند شارژ کیف پول)؛ چون هر دو روی database.py (wallet_topup_allows_payment_method)
// اعمال می‌شوند، بات و مینی‌اپ هر دو با همین تنظیم رفتار می‌کنند.
async function openWalletPaymentMethodsModal() {
  let methods, current;
  try {
    [methods, current] = await Promise.all([
      apiGet('/payment-methods'),
      apiGet('/wallet/payment-methods'),
    ]);
  } catch (e) { return handleErr(e); }
  const allowed = current.allowed; // null/[] یعنی «همه مجازند»
  const isAllowed = (key) => !allowed || !allowed.length || allowed.includes(key);
  openModal('👛 روش‌های پرداخت مجاز: شارژ کیف پول', `
    <p class="card-sub">اگر هیچ‌کدام تیک نخورَد یا همه تیک بخورند، یعنی شارژ کیف پول با همه‌ی
      روش‌های پرداخت فعال ممکن است (بدون محدودیت). این تنظیم مستقل از محدودیت روش پرداخت هر محصول است.</p>
    <div class="form-grid">
      ${methods.map(m => `
        <label class="field field-row">
          <span>${esc(m.label)}${!m.enabled ? ' (غیرفعال)' : ''}${m.min_amount ? ` — حداقل ${fmt(m.min_amount)} تومان` : ''}</span>
          <input type="checkbox" data-wpm="${esc(m.key)}" ${isAllowed(m.key) ? 'checked' : ''}>
        </label>`).join('') || '<div class="card-sub">هیچ روش پرداختی تعریف نشده.</div>'}
    </div>
    <button class="btn btn-primary" id="wpm-save" style="margin-top:12px">ذخیره</button>
  `, (b, close) => {
    $('#wpm-save', b).addEventListener('click', async () => {
      const boxes = $$('[data-wpm]', b);
      const checked = boxes.filter(i => i.checked).map(i => i.dataset.wpm);
      if (checked.length === 0) { toast('حداقل یک روش پرداخت باید فعال بماند.', true); return; }
      const methodsPayload = (checked.length === boxes.length) ? null : checked;
      try {
        await apiPost('/wallet/payment-methods', { methods: methodsPayload });
        toast('ذخیره شد.'); close();
      } catch (e) { handleErr(e); }
    });
  });
}

async function openCustomConfigPaymentMethodsModal() {
  let methods, current;
  try {
    [methods, current] = await Promise.all([
      apiGet('/payment-methods'),
      apiGet('/custom-config/payment-methods'),
    ]);
  } catch (e) { return handleErr(e); }
  const allowed = current.allowed;
  const isAllowed = (key) => !allowed || !allowed.length || allowed.includes(key);
  openModal('🛠 روش‌های پرداخت مجاز: ساخت کانفیگ شخصی', `
    <p class="card-sub">اگر همه تیک بخورند، یعنی ساخت کانفیگ شخصی با همه‌ی روش‌های پرداخت فعال ممکن است
      (بدون محدودیت). این تنظیم برای مینی‌اپ و بات (وقتی پلن اختصاصی محدودیت خودش را ندارد) اعمال می‌شود.</p>
    <div class="form-grid">
      ${methods.map(m => `
        <label class="field field-row">
          <span>${esc(m.label)}${!m.enabled ? ' (غیرفعال)' : ''}${m.min_amount ? ` — حداقل ${fmt(m.min_amount)} تومان` : ''}</span>
          <input type="checkbox" data-ccpm="${esc(m.key)}" ${isAllowed(m.key) ? 'checked' : ''}>
        </label>`).join('') || '<div class="card-sub">هیچ روش پرداختی تعریف نشده.</div>'}
    </div>
    <button class="btn btn-primary" id="ccpm-save" style="margin-top:12px">ذخیره</button>
  `, (b, close) => {
    $('#ccpm-save', b).addEventListener('click', async () => {
      const boxes = $$('[data-ccpm]', b);
      const checked = boxes.filter(i => i.checked).map(i => i.dataset.ccpm);
      if (checked.length === 0) { toast('حداقل یک روش پرداخت باید فعال بماند.', true); return; }
      const methodsPayload = (checked.length === boxes.length) ? null : checked;
      try {
        await apiPost('/custom-config/payment-methods', { methods: methodsPayload });
        toast('ذخیره شد.'); close();
      } catch (e) { handleErr(e); }
    });
  });
}

let catalogDsubEnabled = false;

// دسته‌بندی تو در تو: ویرایش نام/والد، افزودن زیردسته و جابه‌جایی (بالا/پایین) بین هم‌ردیف‌ها
function catIndentHtml(c) {
  const d = Number(c.depth || 0);
  return d ? `<span style="display:inline-block;width:${d * 18}px"></span>↳ ` : '';
}
function catDescendantIds(categories, id) {
  const out = new Set();
  const walk = pid => categories.forEach(x => { if (Number(x.parent_id) === pid && !out.has(x.id)) { out.add(x.id); walk(x.id); } });
  walk(Number(id));
  return out;
}
function catParentOptionsHtml(categories, selectedId, excludeId) {
  const banned = excludeId ? catDescendantIds(categories, excludeId) : new Set();
  if (excludeId) banned.add(Number(excludeId));
  return `<option value="">📂 دسته‌ی اصلی (بدون والد)</option>` + categories.filter(x => !banned.has(x.id))
    .map(x => `<option value="${x.id}" ${Number(selectedId) === x.id ? 'selected' : ''}>${esc(x.path || x.name)}</option>`).join('');
}
function openCategoryCreateModal(categories, presetParent = null) {
  openModal(presetParent ? 'زیردسته‌ی جدید' : 'دسته‌بندی جدید', `
    <div class="form-grid"><input class="input" id="cat-new-name" placeholder="نام دسته‌بندی">
    <select class="input" id="cat-new-parent">${catParentOptionsHtml(categories, presetParent, null)}</select>
    <button class="btn btn-primary" id="cat-new-save">ثبت</button></div>`, (b, close) => {
    $('#cat-new-save', b).addEventListener('click', async () => {
      const name = $('#cat-new-name', b).value.trim();
      if (!name) return toast('نام دسته‌بندی را وارد کنید.', true);
      const parent = Number($('#cat-new-parent', b).value) || null;
      try { await apiPost('/categories', { name, parent_id: parent }); toast('اضافه شد.'); close(); renderCatalog(); } catch (e) { handleErr(e); }
    });
  });
}
// رنگ دکمه‌ی دسته‌بندی در بات/مینی‌اپ (خالی = پیش‌فرض)
const CAT_COLOR_OPTIONS = [['', '⚪ پیش‌فرض', ''], ['primary', '🔵 آبی', '#2563eb'], ['success', '🟢 سبز', '#16a34a'], ['danger', '🔴 قرمز', '#dc2626']];
function catColorValue(c) { return String((c && c.button_color) || ''); }
function catColorHex(v) { const o = CAT_COLOR_OPTIONS.find(x => x[0] === String(v || '')); return o ? o[2] : ''; }
function catColorSelectHtml(c, attrs = '') {
  const cur = catColorValue(c);
  const hex = catColorHex(cur);
  return `<select class="input" ${attrs} title="رنگ دکمه‌ی این دسته در بات" style="width:auto;min-width:96px;padding:4px 6px;${hex ? `border-inline-start:6px solid ${hex}` : ''}">${CAT_COLOR_OPTIONS.map(([v, l]) => `<option value="${v}" ${v === cur ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
}
function catOrderButtonsHtml(c, categories, cls = 'btn btn-sm') {
  const sibs = categories.filter(x => (x.parent_id || null) === (c.parent_id || null));
  const i = sibs.findIndex(x => x.id === c.id);
  return `<button class="${cls}" data-cat-up="${c.id}" ${i <= 0 ? 'disabled' : ''} title="بالا">▲</button>
    <button class="${cls}" data-cat-down="${c.id}" ${i === sibs.length - 1 ? 'disabled' : ''} title="پایین">▼</button>
    <button class="${cls}" data-add-subcat="${c.id}" title="افزودن زیردسته">＋ زیردسته</button>
    ${catColorSelectHtml(c, `data-cat-color="${c.id}"`)}
    <button class="${cls}" data-edit-cat="${c.id}">✏️ ویرایش</button>`;
}
function wireCategoryActions(body, categories, basePath = '/categories') {
  const reload = () => renderCatalog();
  $$('[data-cat-up],[data-cat-down]', body).forEach(btn => btn.addEventListener('click', async () => {
    const id = btn.dataset.catUp || btn.dataset.catDown;
    const direction = btn.dataset.catUp ? 'up' : 'down';
    try { await apiPost(`${basePath}/${id}/move`, { direction }); reload(); } catch (e) { handleErr(e); }
  }));
  $$('[data-add-subcat]', body).forEach(btn => btn.addEventListener('click', () => openCategoryCreateModal(categories, Number(btn.dataset.addSubcat))));
  $$('[data-cat-color]', body).forEach(sel => sel.addEventListener('change', async () => {
    const cat = categories.find(x => x.id === Number(sel.dataset.catColor));
    if (!cat) return;
    try { await apiPut(`${basePath}/${cat.id}`, { name: cat.name, button_color: sel.value }); toast('رنگ دکمه ذخیره شد.'); reload(); } catch (e) { handleErr(e); }
  }));
  $$('[data-edit-cat]', body).forEach(btn => btn.addEventListener('click', () => {
    const cat = categories.find(x => x.id === Number(btn.dataset.editCat));
    if (!cat) return;
    openModal('ویرایش دسته‌بندی', `
      <div class="form-grid"><input class="input" id="cat-edit-name" placeholder="نام دسته‌بندی" value="${esc(cat.name)}">
      <label class="field"><span>📂 دسته‌ی والد</span><select class="input" id="cat-edit-parent">${catParentOptionsHtml(categories, cat.parent_id, cat.id)}</select></label>
      ${basePath === '/categories' ? `
      <label class="field"><span>😀 ایموجی دکمه‌ی دسته در بات (خالی = پیش‌فرض، - = بدون ایموجی)</span><input class="input" id="cat-edit-emoji" maxlength="16" value="${esc(cat.emoji || '')}"></label>
      <label class="field"><span>🏷 ایموجی محصولات این دسته در بات (خالی = پیش‌فرض، - = بدون ایموجی)</span><input class="input" id="cat-edit-prod-emoji" maxlength="16" value="${esc(cat.product_emoji || '')}"></label>
      <label class="field"><span>🎨 رنگ دکمه‌ی این دسته (در بات و مینی‌اپ)</span>${catColorSelectHtml(cat, 'id="cat-edit-color"')}</label>` : ''}
      <button class="btn btn-primary" id="cat-edit-save">ذخیره</button></div>`, (b, close) => {
      $('#cat-edit-save', b).addEventListener('click', async () => {
        const name = $('#cat-edit-name', b).value.trim();
        if (!name) return toast('نام دسته‌بندی را وارد کنید.', true);
        const parent = Number($('#cat-edit-parent', b).value) || null;
        const payload = { name, parent_id: parent };
        if (basePath === '/categories') {
          payload.emoji = $('#cat-edit-emoji', b).value.trim();
          payload.product_emoji = $('#cat-edit-prod-emoji', b).value.trim();
          payload.button_color = $('#cat-edit-color', b).value;
        }
        try { await apiPut(`${basePath}/${cat.id}`, payload); toast('ویرایش شد.'); close(); reload(); } catch (e) { handleErr(e); }
      });
    });
  }));
}

// رنگ دکمه‌ی محصول در بات تلگرام (اختیاری؛ خالی = رنگ پیش‌فرض/سراسری)
function productBtnStyleHtml(idPrefix, current) {
  const opts = [['', '⚪️ پیش‌فرض'], ['primary', '🔵 آبی'], ['success', '🟢 سبز'], ['danger', '🔴 قرمز']];
  return `<label class="field"><span>🎨 رنگ دکمه‌ی محصول در بات</span>
    <select class="input" id="${idPrefix}-btn-style">${opts.map(([v, l]) => `<option value="${v}" ${String(current || '') === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>`;
}
function readProductBtnStyle(b, idPrefix) {
  const el = $(`#${idPrefix}-btn-style`, b);
  return el ? el.value : '';
}

// جستجوی زنده داخل لیست گروه/Inbound (تعداد زیاد مقصد در پنل‌های بزرگ)
function targetSearchBoxHtml() {
  return '<input type="search" class="input" data-target-search placeholder="🔍 جستجوی گروه / Inbound..." autocomplete="off" style="margin-bottom:7px">';
}
function bindTargetSearch(root) {
  if (!root) return;
  $$('[data-target-search]', root).forEach(inp => {
    if (inp.dataset.bound === '1') return;
    inp.dataset.bound = '1';
    inp.addEventListener('input', () => {
      const q = inp.value.trim().toLowerCase();
      const box = inp.parentElement.querySelector('[data-target-list]');
      if (!box) return;
      let shown = 0;
      box.querySelectorAll('label.field-row').forEach(l => {
        const ok = !q || l.textContent.toLowerCase().includes(q);
        l.style.display = ok ? '' : 'none';
        if (ok) shown++;
      });
      let empty = box.querySelector('[data-target-empty]');
      if (!shown) {
        if (!empty) { empty = document.createElement('div'); empty.dataset.targetEmpty = '1'; empty.className = 'card-sub'; empty.textContent = 'موردی پیدا نشد.'; box.appendChild(empty); }
      } else if (empty) empty.remove();
    });
  });
}

async function loadProductPanelTargetPicker(b, serverId, selectedValues = []) {
  const host = $('#prod-target-picker', b);
  if (!host) return { choices: [] };
  if (!serverId) { host.innerHTML = ''; host.dataset.hasChoices = '0'; return { choices: [] }; }
  host.innerHTML = '<div class="card-sub">در حال دریافت گروه‌ها / Inboundهای پنل...</div>';
  try {
    const info = await apiGet(`/panel-servers/${Number(serverId)}/product-targets`);
    const choices = Array.isArray(info.choices) ? info.choices : [];
    if (!choices.length) {
      host.innerHTML = '<div class="card-sub">این پنل مقصد قابل انتخاب زنده ندارد؛ قالب ذخیره‌شده پنل استفاده می‌شود.</div>';
      host.dataset.hasChoices = '0'; return info;
    }
    const selected = new Set((selectedValues || []).map(String));
    host.innerHTML = `<div class="field" style="margin-top:8px"><span>🎯 گروه / Inbound مخصوص این محصول</span>${targetSearchBoxHtml()}<div data-target-list style="display:grid;gap:7px;max-height:220px;overflow:auto;padding:9px;border:1px solid var(--border);border-radius:10px">${choices.map(c => `<label class="field-row"><span>${esc(String(c.label || c.value))}</span><input type="checkbox" data-product-target-value="${esc(String(c.value))}" ${selected.has(String(c.value)) ? 'checked' : ''}></label>`).join('')}</div><span class="card-sub">این مقصد فقط برای همین محصول ذخیره می‌شود و تنظیمات مشترک پنل تغییر نمی‌کند.</span></div>`;
    host.dataset.hasChoices = '1'; bindTargetSearch(host); return info;
  } catch (e) {
    host.dataset.hasChoices = 'error';
    host.innerHTML = `<div class="form-error">دریافت مقصدهای پنل ناموفق بود: ${esc(e.message || 'خطا')}</div>`;
    throw e;
  }
}
async function loadMultiPanelTargetPickers(b, prefillConfigs = {}) {
  const host = $('#prod-multi-target-pickers', b);
  if (!host) return;
  const ids = $$('.prod-multi-panel:checked', b).map(el => Number(el.value));
  host.innerHTML = '';
  for (const sid of ids) {
    const panel = (window.__productPanelServers || []).find(x => Number(x.id) === sid);
    const section = document.createElement('div');
    section.className = 'card';
    section.dataset.multiPanelId = String(sid);
    section.dataset.hasChoices = 'loading';
    section.innerHTML = `<div class="card-sub">در حال دریافت مقصدهای ${esc(panel?.name || `پنل #${sid}`)}...</div>`;
    host.appendChild(section);
    try {
      const info = await apiGet(`/panel-servers/${sid}/product-targets`);
      const choices = Array.isArray(info.choices) ? info.choices : [];
      const cfg = prefillConfigs[sid] || prefillConfigs[String(sid)] || window.__productPrefillTargetConfig || null;
      const selected = new Set(productTargetValuesFromConfig(cfg, sid));
      if (!choices.length) {
        section.dataset.hasChoices = '0';
        section.innerHTML = `<div class="card-sub">${esc(panel?.name || `پنل #${sid}`)}: مقصد زنده ندارد؛ قالب پنل استفاده می‌شود.</div>`;
      } else {
        section.dataset.hasChoices = '1';
        section.innerHTML = `<div class="field"><span>🎯 مقصد اختصاصی ${esc(panel?.name || `پنل #${sid}`)}</span>${targetSearchBoxHtml()}<div data-target-list style="display:grid;gap:7px;max-height:190px;overflow:auto;padding:9px;border:1px solid var(--border);border-radius:10px">${choices.map(c => `<label class="field-row"><span>${esc(String(c.label || c.value))}</span><input type="checkbox" data-multi-target-value="${esc(String(c.value))}" ${selected.has(String(c.value)) ? 'checked' : ''}></label>`).join('')}</div></div>`;
        bindTargetSearch(section);
      }
    } catch (e) {
      section.dataset.hasChoices = 'error';
      section.innerHTML = `<div class="form-error">دریافت مقصدهای ${esc(panel?.name || sid)} ناموفق بود: ${esc(e.message || 'خطا')}</div>`;
    }
  }
}
function readMultiPanelTargetConfigs(b) {
  const out = {};
  $$('#prod-multi-target-pickers [data-multi-panel-id]', b).forEach(section => {
    const sid = section.dataset.multiPanelId;
    if (section.dataset.hasChoices === '1') {
      out[sid] = $$('[data-multi-target-value]:checked', section).map(el => el.getAttribute('data-multi-target-value'));
    }
  });
  return out;
}
function productTargetValuesFromConfig(raw, serverId = null) {
  let cfg = raw;
  if (typeof cfg === 'string') { try { cfg = JSON.parse(cfg); } catch (_) { cfg = null; } }
  if (!cfg || !cfg.field) return [];
  if (serverId && cfg.panel_server_id != null && Number(cfg.panel_server_id) !== Number(serverId)) return [];
  const value = cfg.value;
  if (cfg.field === 'xui_inbound_ids') return (Array.isArray(value) ? value : [value]).map(String);
  if (value && typeof value === 'object' && !Array.isArray(value)) return Object.entries(value).flatMap(([proto, items]) => (items || []).map(item => `${proto}::${item}`));
  return (Array.isArray(value) ? value : [value]).filter(x => x != null).map(String);
}
function readProductTargetValues(b) {
  const host = $('#prod-target-picker', b);
  if (!host || host.dataset.hasChoices !== '1') return null;
  return $$('[data-product-target-value]:checked', host).map(el => el.getAttribute('data-product-target-value'));
}

function productProvisionFieldsHtml(panelServers, sshNodes = [], prefill = null) {
  window.__productPanelServers = panelServers || [];
  window.__productPrefillExtraTargetConfigs = (prefill && prefill.extra_panel_target_configs) || {};
  panelServers = panelServers || []; sshNodes = sshNodes || [];
  const isDirect = !!(prefill && (prefill.provision_server_id || prefill.provision_ssh_node_id));
  const extraPanels = ((prefill && prefill.extra_panel_ids) || []).map(Number);
  const extraNodes = ((prefill && prefill.extra_ssh_node_ids) || []).map(Number);
  const isMulti = extraPanels.length + extraNodes.length > 0;
  const selPanels = isMulti ? [Number(prefill.provision_server_id || 0), ...extraPanels].filter(Boolean) : [];
  const selNodes = isMulti ? [Number(prefill.provision_ssh_node_id || 0), ...extraNodes].filter(Boolean) : [];
  const selectedProvisionPanel = panelServers.find(s => Number(s.id) === Number(prefill && prefill.provision_server_id));
  const target = isMulti ? 'multi' : (prefill && prefill.provision_ssh_node_id ? (prefill.provision_server_id ? 'both' : 'ssh') : (selectedProvisionPanel && selectedProvisionPanel.panel_type === 'stealth' ? 'vless' : 'vpn'));
  const comboLocked = !catalogDsubEnabled;
  const durUnlimited = !!(prefill && prefill.duration_days === 0);
  const volUnlimited = !!(prefill && prefill.auto_provision_volume_gb === 0);
  return `
    <div class="form-row" style="gap:12px;align-items:center">
      <label style="display:flex;align-items:center;gap:4px"><input type="radio" name="prod-source" value="bank" ${isDirect ? '' : 'checked'}> بانک کانفیگ</label>
      <label style="display:flex;align-items:center;gap:4px"><input type="radio" name="prod-source" value="direct" ${isDirect ? 'checked' : ''}> ساخت خودکار</label>
      ${prefill ? '' : '<label style="display:flex;align-items:center;gap:4px"><input type="radio" name="prod-source" value="panel"> 🔑 فروش پنل (یوزر/پسورد)</label>'}
    </div>
    <div id="prod-direct-fields" class="form-grid" style="display:${isDirect ? '' : 'none'}">
      <label class="field"><span>نوع مقصد</span><select class="input" id="prod-target-type"><option value="vpn" ${target === 'vpn' ? 'selected' : ''}>پنل VPN</option>${panelServers.some(s => s.panel_type === 'stealth') ? `<option value="vless" ${target === 'vless' ? 'selected' : ''}>نود VLESS</option>` : ''}${sshNodes.length || (prefill && prefill.provision_ssh_node_id) ? `<option value="ssh" ${target === 'ssh' ? 'selected' : ''}>نود SSH (Linux Agent)</option><option value="both" ${target === 'both' ? 'selected' : ''} ${comboLocked && target !== 'both' ? 'disabled' : ''}>ترکیبی VPN + SSH (حجم و زمان مشترک)${comboLocked ? ' — نیازمند ساب اختصاصی فعال' : ''}</option>` : ''}<option value="multi" ${target === 'multi' ? 'selected' : ''} ${comboLocked && target !== 'multi' ? 'disabled' : ''}>چند پنل / چند نود (حجم و زمان مشترک)${comboLocked ? ' — نیازمند ساب اختصاصی فعال' : ''}</option></select><span class="card-sub" id="prod-multi-hint" style="display:${comboLocked ? '' : 'none'}">ترکیب و چند مقصدی فقط وقتی ساب اختصاصی فعال باشد کار می‌کند.</span></label>
      <div id="prod-multi-fields" style="display:${target === 'multi' ? '' : 'none'}">
        <div class="card-sub">پنل‌های VPN (هر تعداد)</div>
        ${panelServers.map(s2 => `<label class="field field-row"><span>${esc(s2.name)}</span><input type="checkbox" class="prod-multi-panel" value="${s2.id}" ${selPanels.includes(Number(s2.id)) ? 'checked' : ''}></label>`).join('') || '<div class="card-sub">پنلی نیست</div>'}
        <div id="prod-multi-target-pickers" style="display:grid;gap:8px"></div>
        <div class="card-sub">نودهای SSH (هر تعداد)</div>
        ${sshNodes.map(n2 => `<label class="field field-row"><span>${esc(n2.name)} · ${esc(n2.host || '')}</span><input type="checkbox" class="prod-multi-node" value="${n2.id}" data-protocols="${esc((n2.protocols || ['ssh']).join(','))}" ${selNodes.includes(Number(n2.id)) ? 'checked' : ''}></label>`).join('') || '<div class="card-sub">نودی نیست</div>'}
        <span class="card-sub">حجم و زمان بین همه‌ی مقصدها مشترک است و خروجی همه در یک لینک ساب اختصاصی ادغام می‌شود.</span>
      </div>
      <div id="prod-vpn-fields" style="display:${(target === 'ssh' || target === 'multi') ? 'none' : ''}"><label class="field"><span id="prod-server-label">${target === 'vless' ? 'نود VLESS' : 'پنل VPN'}</span><select class="input" id="prod-server">${panelServers.map(s => `<option value="${s.id}" data-panel-type="${esc(s.panel_type || '')}" ${prefill && Number(prefill.provision_server_id) === Number(s.id) ? 'selected' : ''}>${s.panel_type === 'stealth' ? 'VLESS · ' : ''}${esc(s.name)}</option>`).join('')}</select></label><div id="prod-target-picker"></div></div>
      <div id="prod-ssh-fields" style="display:${(target === 'ssh' || target === 'both' || target === 'multi') ? '' : 'none'}"><label class="field" id="prod-ssh-node-field" style="display:${target === 'multi' ? 'none' : ''}"><span>نود SSH</span><select class="input" id="prod-ssh-node">${sshNodes.map(n => `<option value="${n.id}" data-protocols="${esc((n.protocols || ['ssh']).join(','))}" ${prefill && Number(prefill.provision_ssh_node_id) === Number(n.id) ? 'selected' : ''}>${esc(n.name)} · ${esc(n.host || '')}</option>`).join('')}</select><span class="card-sub">فقط Linux Agent فعال با حسابداری معتبر پشتیبانی می‌شود.</span></label>
      <div id="prod-proto-wrap" style="display:${(target === 'multi' || target === 'both') ? '' : 'none'}">
        <div class="card-sub">پروتکل‌های حساب SSH (هر تعداد)</div>
        <div id="prod-multi-protocols" data-prefill="${esc((prefill && prefill.provision_ssh_protocol) || 'ssh')}" style="display:flex;flex-wrap:wrap;gap:12px"></div>
        <span class="card-sub">روی هر نود فقط پروتکل‌های تیک‌خورده‌ای که همان نود نصب دارد ساخته می‌شود. OpenVPN و WireGuard فقط وقتی انتخاب‌پذیرند که یک پنل VPN هم در محصول باشد و فایل آن‌ها داخل لینک ساب اختصاصی تحویل می‌شود.</span>
      </div>
      <label class="field" id="prod-ssh-proto-field" style="display:none"><span>پروتکل حساب</span><select class="input" id="prod-ssh-protocol" data-prefill="${esc((prefill && prefill.provision_ssh_protocol) || 'ssh')}"><option value="ssh">SSH</option></select><span class="card-sub">OpenVPN و WireGuard فقط در محصول «ترکیبی» ممکن‌اند و فایل آن‌ها داخل لینک ساب اختصاصی تحویل می‌شود (ساب اختصاصی باید فعال باشد).</span></label></div>
      <label class="field field-row"><span>♾ مدت اعتبار نامحدود</span><input type="checkbox" id="prod-duration-unlimited" ${durUnlimited ? 'checked' : ''}></label>
      <label class="field"><span>حجم (GB) — ۰ = نامحدود</span><input class="input" id="prod-volume" type="number" min="0" step="1" placeholder="حجم (گیگابایت)" value="${prefill && prefill.auto_provision_volume_gb != null ? prefill.auto_provision_volume_gb : ''}" ${volUnlimited ? 'disabled' : ''}></label>
      <label class="field field-row"><span>♾ حجم نامحدود</span><input type="checkbox" id="prod-volume-unlimited" ${volUnlimited ? 'checked' : ''}></label>
      <div id="prod-user-limit-fields" style="display:none;grid-column:1/-1">
        <div class="card-sub">👥 محدودیت تعداد کاربر همزمان <span id="prod-user-limit-supported-by"></span></div>
        <div class="form-grid">
          <label class="field"><span>کاربر پایه (۰ = بدون محدودیت)</span><input class="input" id="prod-base-users" type="number" min="0" max="20" step="1" value="${prefill && prefill.base_users != null ? prefill.base_users : 0}"></label>
          <label class="field"><span>قیمت هر کاربر اضافه (تومان)</span><input class="input" id="prod-extra-user-price" type="number" min="0" step="1" value="${prefill && prefill.extra_user_price != null ? prefill.extra_user_price : 0}"></label>
          <label class="field"><span>سقف نهایی کاربر</span><input class="input" id="prod-max-users" type="number" min="0" max="20" step="1" value="${prefill && prefill.max_users != null ? prefill.max_users : 0}"></label>
        </div>
        <span class="card-sub">این گزینه فقط وقتی فعال است که تمام پنل‌های VPN انتخاب‌شده از محدودیت کاربر پشتیبانی کنند.</span>
      </div>
      ${renewRulesHtml(prefill)}
    </div>`;
}

// «قوانین تمدید کامل» هر محصول (renewal_rules.py در بک‌اند). پیش‌فرض‌ها رفتار قبلی را حفظ می‌کنند.
function renewRulesHtml(prefill) {
  const v = (k, d) => (prefill && prefill[k] != null ? Number(prefill[k]) : d);
  const reset = v('renew_reset', 0) === 1;
  const row = (id, label, on, hint, disabled) => `<label class="field field-row"><span>${label}${hint ? `<small class="card-sub" style="display:block">${hint}</small>` : ''}</span><input type="checkbox" id="${id}" ${on ? 'checked' : ''} ${disabled ? 'disabled' : ''}></label>`;
  return `<div id="prod-renew-rules" style="grid-column:1/-1;border-top:1px dashed var(--border, #8884);margin-top:10px;padding-top:10px">
    <div class="card-sub">🔄 قوانین تمدید کامل</div>
    ${row('prod-renew-enabled', 'قابل تمدید کامل باشد', v('renew_full_enabled', 1) === 1, 'اگر خاموش باشد این محصول در لیست تمدید کامل نمایش داده نمی‌شود.')}
    ${row('prod-renew-same-type', 'فقط برای سرویس‌های هم‌نوع', v('renew_same_type_only', 1) === 1, 'نامحدود فقط به سرویس نامحدود و حجمی فقط به سرویس حجمی نمایش داده می‌شود.')}
    ${row('prod-renew-reset', 'ریست کامل بعد از تمدید', reset, 'حجم و زمان باقیمانده حذف و فقط بسته‌ی جدید اعمال می‌شود.')}
    ${row('prod-renew-carry-volume', 'انتقال حجم باقیمانده', !reset && v('renew_carry_volume', 1) === 1, 'حجم باقیمانده به محصول جدید اضافه می‌شود.', reset)}
    ${row('prod-renew-carry-time', 'انتقال زمان باقیمانده', !reset && v('renew_carry_time', 1) === 1, 'روزهای باقیمانده به محصول جدید اضافه می‌شود.', reset)}
  </div>`;
}

function wireRenewRules(b) {
  const reset = $('#prod-renew-reset', b);
  if (!reset) return;
  const cv = $('#prod-renew-carry-volume', b), ct = $('#prod-renew-carry-time', b);
  reset.addEventListener('change', () => {
    if (reset.checked) { cv.checked = false; ct.checked = false; }
    cv.disabled = ct.disabled = reset.checked;
  });
}

function collectRenewRules(b) {
  const en = $('#prod-renew-enabled', b);
  if (!en) return undefined;
  const reset = $('#prod-renew-reset', b).checked;
  return {
    renew_full_enabled: en.checked ? 1 : 0,
    renew_same_type_only: $('#prod-renew-same-type', b).checked ? 1 : 0,
    renew_reset: reset ? 1 : 0,
    renew_carry_volume: !reset && $('#prod-renew-carry-volume', b).checked ? 1 : 0,
    renew_carry_time: !reset && $('#prod-renew-carry-time', b).checked ? 1 : 0,
  };
}

function wireProductProvisionToggle(b) {
  wireRenewRules(b);
  $$('input[name="prod-source"]', b).forEach(r => r.addEventListener('change', () => {
    const df = $('#prod-direct-fields', b);
    const srcVal = $('input[name="prod-source"]:checked', b).value;
    if (df) df.style.display = srcVal === 'direct' ? '' : 'none';
    ['#prod-duration', '#prod-renew-rules'].forEach(sel => { const el = $(sel, b); const box = el ? (el.closest('.field') || el) : null; if (box) box.style.display = srcVal === 'panel' ? 'none' : ''; });
  }));
  const targetType = $('#prod-target-type', b);
  const syncPanelOptions = () => {
    const sel = $('#prod-server', b);
    if (!sel) return;
    const tt = targetType ? targetType.value : 'vpn';
    const allowed = tt === 'vless' ? 'stealth-only' : (tt === 'vpn' ? 'non-stealth' : null);
    const current = sel.value;
    let first = '';
    [...sel.options].forEach(opt => {
      const typ = opt.dataset.panelType || '';
      const show = !allowed || (allowed === 'stealth-only' ? typ === 'stealth' : typ !== 'stealth');
      opt.hidden = !show;
      opt.disabled = !show;
      if (show && !first) first = opt.value;
    });
    if (sel.selectedOptions[0]?.disabled) sel.value = first;
    const label = $('#prod-server-label', b);
    if (label) label.textContent = tt === 'vless' ? 'نود VLESS' : (tt === 'vpn' ? 'پنل VPN' : 'پنل VPN / VLESS');
  };
  const syncUserLimit = () => {
    const wrap = $('#prod-user-limit-fields', b);
    if (!wrap) return;
    const tt = targetType ? targetType.value : 'vpn';
    const serverData = (window.__productPanelServers || []);
    let ids = [];
    if (tt === 'multi') ids = $$('.prod-multi-panel:checked', b).map(c => Number(c.value));
    else if (tt === 'both' || tt === 'vpn' || tt === 'vless') { const v = Number($('#prod-server', b)?.value || 0); if (v) ids=[v]; }
    const rows = ids.map(id => serverData.find(s => Number(s.id) === id)).filter(Boolean);
    const supported = rows.length > 0 && rows.every(s => !!s.supports_user_limit);
    wrap.style.display = supported ? '' : 'none';
    const hint = $('#prod-user-limit-supported-by', b);
    if (hint) hint.textContent = supported ? `(${rows.map(s => s.name).join('، ')})` : '';
    if (!supported) {
      const base=$('#prod-base-users',b), extra=$('#prod-extra-user-price',b), max=$('#prod-max-users',b);
      if(base) base.value='0'; if(extra) extra.value='0'; if(max) max.value='0';
    }
  };
  const syncMultiProtocols = () => {
    const box = $('#prod-multi-protocols', b);
    if (!box) return;
    const tt = targetType ? targetType.value : '';
    const nodeSel0 = $('#prod-ssh-node', b);
    const nodes = tt === 'both'
      ? [(nodeSel0?.selectedOptions[0]?.dataset.protocols || 'ssh').split(',').filter(Boolean)]
      : $$('.prod-multi-node:checked', b).map(c => (c.dataset.protocols || 'ssh').split(',').filter(Boolean));
    // اجتماع پروتکل‌های نودهای انتخابی (هر نود فقط پروتکل‌های خودش را می‌سازد)
    let available = ['ssh', 'openvpn', 'wireguard'].filter(p => nodes.some(n => n.includes(p)));
    if (!nodes.length) available = ['ssh'];
    if (tt !== 'both' && !$$('.prod-multi-panel:checked', b).length) available = available.filter(x => x === 'ssh');
    if (!available.length) available = ['ssh'];
    const current = box.dataset.touched
      ? $$('input[data-multi-proto]:checked', box).map(c => c.dataset.multiProto)
      : (box.dataset.prefill || 'ssh').split(',').map(s => s.trim()).filter(Boolean);
    let checked = available.filter(p => current.includes(p));
    if (!checked.length) checked = [available[0]];
    box.innerHTML = available.map(p => `<label style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-multi-proto="${esc(p)}" ${checked.includes(p) ? 'checked' : ''}> ${esc(SSH_PROTO_LABELS[p] || p)}</label>`).join('');
    $$('input[data-multi-proto]', box).forEach(c => c.addEventListener('change', () => { box.dataset.touched = '1'; }));
  };
  const syncSshProtocol = () => {
    syncMultiProtocols();
    const sel = $('#prod-ssh-protocol', b), nodeSel = $('#prod-ssh-node', b);
    if (!sel || !nodeSel) return;
    let available = (nodeSel.selectedOptions[0]?.dataset.protocols || 'ssh').split(',').filter(Boolean);
    const isMultiType = targetType && targetType.value === 'multi';
    const list = (targetType && targetType.value === 'both') ? available : ['ssh'];
    const keep = sel.value && sel.dataset.touched ? sel.value : (sel.dataset.prefill || 'ssh');
    sel.innerHTML = list.map(p => `<option value="${esc(p)}" ${p === keep ? 'selected' : ''}>${esc(SSH_PROTO_LABELS[p] || p)}</option>`).join('');
  };
  if ($('#prod-ssh-protocol', b)) {
    $('#prod-ssh-protocol', b).addEventListener('change', e => { e.target.dataset.touched = '1'; });
    if ($('#prod-ssh-node', b)) $('#prod-ssh-node', b).addEventListener('change', syncSshProtocol);
    $$('.prod-multi-node, .prod-multi-panel', b).forEach(c => c.addEventListener('change', syncSshProtocol));
    syncSshProtocol();
  }
  if (targetType) targetType.addEventListener('change', () => {
    const t = targetType.value;
    syncPanelOptions();
    if ($('#prod-server', b)) loadProductPanelTargetPicker(b, $('#prod-server', b).value, []).catch(() => {});
    if ($('#prod-vpn-fields', b)) $('#prod-vpn-fields', b).style.display = (t === 'ssh' || t === 'multi') ? 'none' : '';
    if ($('#prod-ssh-fields', b)) $('#prod-ssh-fields', b).style.display = (t === 'ssh' || t === 'both' || t === 'multi') ? '' : 'none';
    if ($('#prod-ssh-node-field', b)) $('#prod-ssh-node-field', b).style.display = t === 'multi' ? 'none' : '';
    if ($('#prod-proto-wrap', b)) $('#prod-proto-wrap', b).style.display = (t === 'multi' || t === 'both') ? '' : 'none';
    if ($('#prod-multi-fields', b)) $('#prod-multi-fields', b).style.display = t === 'multi' ? '' : 'none';
    syncSshProtocol();
    syncUserLimit();
  });
  const durUnlimitedCb = $('#prod-duration-unlimited', b);
  if (durUnlimitedCb) {
    const durInput = $('#prod-duration', b);
    if (durInput) durInput.disabled = durUnlimitedCb.checked;
    durUnlimitedCb.addEventListener('change', () => { if (durInput) durInput.disabled = durUnlimitedCb.checked; });
  }
  $$('.prod-multi-panel', b).forEach(c => c.addEventListener('change', syncUserLimit));
  const multiPanelChecks = $$('.prod-multi-panel', b);
  multiPanelChecks.forEach(c => c.addEventListener('change', () => {
    loadMultiPanelTargetPickers(b, window.__productPrefillExtraTargetConfigs || {}).catch(e => toast(e.message || 'دریافت مقصدهای پنل ناموفق بود.', true));
  }));
  if (targetType && targetType.value === 'multi') {
    loadMultiPanelTargetPickers(b, window.__productPrefillExtraTargetConfigs || {}).catch(() => {});
  }
  const prodServer = $('#prod-server', b);
  if (prodServer) {
    prodServer.addEventListener('change', async () => {
      syncUserLimit();
      try { await loadProductPanelTargetPicker(b, prodServer.value, []); } catch (e) { toast(e.message || 'دریافت مقصد پنل ناموفق بود.', true); }
    });
    loadProductPanelTargetPicker(b, prodServer.value, productTargetValuesFromConfig(window.__productPrefillTargetConfig, prodServer.value)).catch(() => {});
  }
  syncPanelOptions();
  syncUserLimit();
  const volUnlimitedCb = $('#prod-volume-unlimited', b);
  if (volUnlimitedCb) volUnlimitedCb.addEventListener('change', () => {
    const volInput = $('#prod-volume', b); if (volInput) volInput.disabled = volUnlimitedCb.checked;
  });
}

function readProductProvisionFields(b) {
  const sourceEl = $('input[name="prod-source"]:checked', b);
  const source = sourceEl ? sourceEl.value : 'bank';
  const isDirect = source === 'direct';
  const durUnlimitedCb = $('#prod-duration-unlimited', b);
  const durationUnlimited = isDirect && durUnlimitedCb && durUnlimitedCb.checked;
  const durInput = $('#prod-duration', b);
  const duration_days = durationUnlimited ? 0 : (Number(durInput ? durInput.value : 0) || 30);
  const userLimit = () => ({ base_users: Number($('#prod-base-users', b)?.value || 0), extra_user_price: Number($('#prod-extra-user-price', b)?.value || 0), max_users: Number($('#prod-max-users', b)?.value || 0), renew_rules: collectRenewRules(b) });
  if (source === 'panel') return { ok: true, source: 'panel', product_kind: 'panel_account', provision_server_id: null, provision_ssh_node_id: null, extra_panel_ids: [], extra_ssh_node_ids: [], auto_provision_volume_gb: null, duration_days: 0 };
  if (!isDirect) return { ok: true, source: 'bank', provision_server_id: null, provision_ssh_node_id: null, extra_panel_ids: [], extra_ssh_node_ids: [], auto_provision_volume_gb: null, duration_days, ...userLimit() };
  const target = $('#prod-target-type', b)?.value || 'vpn';
  const volUnlimitedCb = $('#prod-volume-unlimited', b);
  const volumeUnlimited = volUnlimitedCb && volUnlimitedCb.checked;
  const auto_provision_volume_gb = volumeUnlimited ? 0 : Number($('#prod-volume', b).value);
  if (auto_provision_volume_gb < 0 || (!volumeUnlimited && !auto_provision_volume_gb)) {
    toast('برای ساخت خودکار، حجم معتبر یا حجم نامحدود را انتخاب کنید.', true); return { ok: false };
  }
  if (target === 'multi') {
    if (!catalogDsubEnabled) { toast('چند پنل/نود فقط وقتی ساب اختصاصی فعال است ممکن است.', true); return { ok: false }; }
    const panels = $$('.prod-multi-panel:checked', b).map(c => Number(c.value));
    const nodes = $$('.prod-multi-node:checked', b).map(c => Number(c.value));
    if (panels.length + nodes.length < 2) { toast('حداقل دو مقصد (پنل یا نود) انتخاب کنید.', true); return { ok: false }; }
    const panelTargetMap = readMultiPanelTargetConfigs(b);
    const primaryTargetValues = panelTargetMap[String(panels[0])] || [];
    for (const sid of panels) {
      const section = $(`#prod-multi-target-pickers [data-multi-panel-id="${sid}"]`, b);
      if (section && section.dataset.hasChoices === '1' && !(panelTargetMap[String(sid)] || []).length) {
        toast(`برای پنل ${sid} حداقل یک مقصد انتخاب کنید.`, true); return { ok: false };
      }
      if (section && section.dataset.hasChoices === 'error') {
        toast(`دریافت مقصدهای پنل ${sid} ناموفق بوده است.`, true); return { ok: false };
      }
    }
    const extraTargetValues = { ...panelTargetMap };
    delete extraTargetValues[String(panels[0])];
    return { ok: true, source: 'direct', provision_server_id: panels[0] || null, provision_target_values: primaryTargetValues,
      extra_panel_target_values: extraTargetValues, provision_ssh_node_id: nodes[0] || null,
      extra_panel_ids: panels.slice(1), extra_ssh_node_ids: nodes.slice(1),
      provision_ssh_protocol: nodes.length ? ($$('#prod-multi-protocols input[data-multi-proto]:checked', b).map(c => c.dataset.multiProto).join(',') || 'ssh') : 'ssh',
      auto_provision_volume_gb, duration_days, ...userLimit() };
  }
  if (target === 'both') {
    const provision_server_id = Number($('#prod-server', b)?.value || 0);
    const provision_ssh_node_id = Number($('#prod-ssh-node', b)?.value || 0);
    if (!provision_server_id) { toast('یک پنل VPN فعال انتخاب کنید.', true); return { ok: false }; }
    if (!provision_ssh_node_id) { toast('یک نود SSH فعال انتخاب کنید.', true); return { ok: false }; }
    const provision_target_values = readProductTargetValues(b);
    if (provision_target_values !== null && !provision_target_values.length) { toast('حداقل یک گروه یا Inbound انتخاب کنید.', true); return { ok: false }; }
    return { ok: true, source: 'direct', provision_server_id, provision_target_values, provision_ssh_node_id, extra_panel_ids: [], extra_ssh_node_ids: [],
      provision_ssh_protocol: $$('#prod-multi-protocols input[data-multi-proto]:checked', b).map(c => c.dataset.multiProto).join(',') || 'ssh', auto_provision_volume_gb, duration_days, ...userLimit() };
  }
  if (target === 'ssh') {
    const provision_ssh_node_id = Number($('#prod-ssh-node', b)?.value || 0);
    if (!provision_ssh_node_id) { toast('یک نود SSH فعال انتخاب کنید.', true); return { ok: false }; }
    return { ok: true, source: 'direct', provision_server_id: null, provision_ssh_node_id, extra_panel_ids: [], extra_ssh_node_ids: [], provision_ssh_protocol: 'ssh', auto_provision_volume_gb, duration_days, ...userLimit() };
  }
  const provision_server_id = Number($('#prod-server', b)?.value || 0);
  if (!provision_server_id) { toast('یک پنل VPN فعال انتخاب کنید.', true); return { ok: false }; }
  const provision_target_values = readProductTargetValues(b);
  if (provision_target_values !== null && !provision_target_values.length) { toast('حداقل یک گروه یا Inbound انتخاب کنید.', true); return { ok: false }; }
  return { ok: true, source: 'direct', provision_server_id, provision_target_values, provision_ssh_node_id: null, extra_panel_ids: [], extra_ssh_node_ids: [], auto_provision_volume_gb, duration_days, ...userLimit() };
}

// روش‌های پرداخت مجاز حین «ساخت» محصول جدید (پیش‌فرض: همه تیک‌خورده = بدون
// محدودیت). خروجی همان قرارداد payment_methods در بدنه‌ی POST /products است.
function productPaymentMethodsFieldsHtml(paymentMethods) {
  if (!paymentMethods || !paymentMethods.length) return '';
  return `
    <div class="field" style="margin-top:4px">
      <span class="card-sub">💳 روش‌های پرداخت مجاز (اگر همه یا هیچ‌کدام تیک نخورَد، یعنی بدون محدودیت)</span>
      <div class="form-grid" style="margin-top:6px">
        ${paymentMethods.map(m => `
          <label class="field field-row">
            <span>${esc(m.label)}${!m.enabled ? ' (غیرفعال)' : ''}</span>
            <input type="checkbox" data-newprod-pm="${esc(m.key)}" checked>
          </label>`).join('')}
      </div>
    </div>`;
}

function readProductPaymentMethodsFields(b) {
  const boxes = $$('[data-newprod-pm]', b);
  if (!boxes.length) return null;
  const checked = boxes.filter(i => i.checked).map(i => i.dataset.newprodPm);
  return (checked.length === 0 || checked.length === boxes.length) ? null : checked;
}

function _discountLimitPrefill(product) {
  // مقدار باقی‌مانده‌ی مدت (روز) و تعداد را برای ذخیره‌ی مجدد فرم پیش‌فرض می‌گذارد تا ویرایش بی‌ربط، شمارش را از نو شروع نکند.
  let days = '';
  if (product && product.discount_expires_at) {
    const ms = new Date(String(product.discount_expires_at).replace(/Z?$/, 'Z')).getTime() - Date.now();
    if (!isNaN(ms)) days = Math.max(Math.ceil(ms / 86400000), 1);
  }
  let uses = '';
  const mx = Number((product && product.discount_max_uses) || 0);
  if (mx > 0) uses = Math.max(mx - Number(product.discount_used_count || 0), 1);
  return { days, uses };
}

function productDiscountFieldsHtml(prefix, product) {
  const active = product && Number(product.compare_price || 0) > Number(product.price || 0);
  const sel = (v) => (active ? 'price' : 'none') === v ? 'selected' : '';
  const pre = _discountLimitPrefill(active ? product : null);
  return `<div class="form-row">
    <select class="input" id="${prefix}-dmode">
      <option value="none" ${sel('none')}>بدون تخفیف</option>
      <option value="price" ${sel('price')}>تخفیف: قیمت جدید</option>
      <option value="pct" ${sel('pct')}>تخفیف: درصدی</option>
    </select>
    <input class="input" id="${prefix}-dval" type="number" placeholder="قیمت جدید (تومان) یا درصد" value="${active ? product.price : ''}">
  </div>
  <div class="form-row">
    <input class="input" id="${prefix}-ddays" type="number" min="0" placeholder="مدت تخفیف (روز) - خالی = نامحدود" value="${pre.days}">
    <input class="input" id="${prefix}-duses" type="number" min="0" placeholder="سقف تعداد خرید - خالی = نامحدود" value="${pre.uses}">
  </div>
  <div class="muted" style="font-size:12px">اگر هر دو پر باشند، هرکدام زودتر برسد تخفیف تمام می‌شود و قیمت به قیمت اصلی برمی‌گردد.</div>`;
}

function readProductDiscount(b, prefix, base) {
  const mode = $('#' + prefix + '-dmode', b).value;
  const v = Number($('#' + prefix + '-dval', b).value) || 0;
  const days = Math.max(Math.floor(Number($('#' + prefix + '-ddays', b).value) || 0), 0);
  const uses = Math.max(Math.floor(Number($('#' + prefix + '-duses', b).value) || 0), 0);
  if (mode === 'none') return { price: base, compare_price: 0, discount_days: 0, discount_max_uses: 0 };
  if (mode === 'price') {
    if (!(v > 0 && v < base)) { toast('قیمت جدید باید از قیمت اصلی کمتر باشد.', true); return null; }
    return { price: v, compare_price: base, discount_days: days, discount_max_uses: uses };
  }
  if (!(v >= 1 && v <= 99)) { toast('درصد تخفیف باید بین 1 تا 99 باشد.', true); return null; }
  return { price: Math.max(Math.round(base * (100 - v) / 100), 1), compare_price: base, discount_days: days, discount_max_uses: uses };
}

// فرم کامل «ویرایش محصول»: نام/قیمت/توضیحات/دسته + امکان تغییر منبع تأمین
// (بانک کانفیگ ⇄ اتصال مستقیم به پنل) و در حالت مستقیم، تغییر خودِ پنل/حجم.
function productEditFormHtml(product, categories, panelServers, sshNodes) {
  return `
    <div class="form-grid">
      <select class="input" id="pe-cat">${categories.map(c => `<option value="${c.id}" ${c.id === product.category_id ? 'selected' : ''}>${esc(c.path || c.name)}</option>`).join('')}</select>
      <input class="input" id="pe-name" placeholder="نام محصول" value="${esc(product.name)}">
      <div class="form-row">
        <input class="input" id="pe-price" type="number" placeholder="قیمت اصلی (تومان)" value="${Number(product.compare_price || 0) > Number(product.price) ? product.compare_price : product.price}">
        <input class="input" id="prod-duration" type="number" placeholder="مدت (روز)" value="${product.duration_days || 30}">
      </div>
      ${productDiscountFieldsHtml('pe', product)}
      <textarea class="input" id="pe-desc" placeholder="توضیحات (اختیاری)" rows="2">${esc(product.description || '')}</textarea>
      ${productBtnStyleHtml('pe', product.btn_style)}
      <textarea class="input" id="pe-ai-desc" placeholder="🤖 توضیح برای هوش مصنوعی (راهنمای خرید؛ به کاربر نمایش داده نمی‌شود)" rows="2">${esc(product.ai_description || '')}</textarea>
      ${productProvisionFieldsHtml(panelServers, sshNodes, product)}
      <button class="btn btn-primary" id="pe-save">ذخیره</button>
    </div>`;
}

function openProductEditModal(product, categories, panelServers, sshNodes) {
  window.__productPrefillTargetConfig = product.provision_target_config || null;
  openModal('ویرایش محصول', productEditFormHtml(product, categories, panelServers, sshNodes), (b, close) => {
    wireProductProvisionToggle(b);
    $('#pe-save', b).addEventListener('click', async () => {
      const name = $('#pe-name', b).value.trim();
      const price = Number($('#pe-price', b).value);
      if (!name || !price) return toast('نام و قیمت الزامی است.', true);
      const disc = readProductDiscount(b, 'pe', price);
      if (!disc) return;
      const prov = readProductProvisionFields(b);
      if (!prov.ok) return;
      const payload = {
        category_id: Number($('#pe-cat', b).value), name, price: disc.price, compare_price: disc.compare_price, discount_days: disc.discount_days, discount_max_uses: disc.discount_max_uses,
        description: $('#pe-desc', b).value, btn_style: readProductBtnStyle(b, 'pe'), ai_description: $('#pe-ai-desc', b)?.value ?? '', duration_days: prov.duration_days, product_kind: prov.product_kind || 'config',
        source: prov.source,
      };
      if (prov.source === 'direct') {
        payload.provision_server_id = prov.provision_server_id;
        payload.provision_target_values = prov.provision_target_values;
        payload.extra_panel_target_values = prov.extra_panel_target_values;
        payload.provision_ssh_node_id = prov.provision_ssh_node_id;
        payload.provision_ssh_protocol = prov.provision_ssh_protocol;
        payload.extra_panel_ids = prov.extra_panel_ids;
        payload.extra_ssh_node_ids = prov.extra_ssh_node_ids;
        payload.auto_provision_volume_gb = prov.auto_provision_volume_gb;
        payload.base_users = prov.base_users; payload.extra_user_price = prov.extra_user_price; payload.max_users = prov.max_users; payload.renew_rules = prov.renew_rules;
      }
      try {
        await apiPut(`/products/${product.id}`, payload);
        toast('محصول ویرایش شد.'); close(); renderCatalog();
      } catch (e) { handleErr(e); }
    });
  });
}

let catalogSearch = '';

function normSearch(v) {
  return String(v == null ? '' : v).toLowerCase().replace(/ي/g, 'ی').replace(/ك/g, 'ک').replace(/[\u200c\u200d]/g, ' ').replace(/\s+/g, ' ').trim();
}

function productSearchAttr(p) {
  return esc(normSearch(`${p.name} ${p.category_name}`));
}

function productSearchInputHtml() {
  return `<input class="input" id="prod-search" type="search" placeholder="جستجو در محصولات (نام یا دسته‌بندی)" value="${esc(catalogSearch)}" style="max-width:300px;min-width:180px">`;
}

function wireProductSearch(body, itemSelector, containerSelector) {
  const input = $('#prod-search', body);
  const items = $$(itemSelector, body);
  if (!input || !items.length) return;
  const container = $(containerSelector, body);
  const empty = document.createElement('div');
  empty.className = 'empty-state';
  empty.style.display = 'none';
  empty.textContent = 'محصولی با این مشخصات پیدا نشد.';
  if (container) container.insertAdjacentElement('afterend', empty);
  const apply = () => {
    catalogSearch = input.value;
    const terms = normSearch(input.value).split(' ').filter(Boolean);
    let shown = 0;
    items.forEach(el => {
      const hay = el.dataset.search || '';
      const ok = terms.every(t => hay.includes(t));
      el.style.display = ok ? '' : 'none';
      if (ok) shown++;
    });
    empty.style.display = shown ? 'none' : '';
  };
  input.addEventListener('input', apply);
  apply();
}

async function renderCatalog() {
  const [categories, products, panelServers, sshNodes, paymentMethods, multiInfo] = await Promise.all([
    apiGet('/categories'), apiGet('/products'), apiGet('/panel-servers-lite'), apiGet('/ssh/nodes-lite').catch(() => []), apiGet('/payment-methods'),
    apiGet('/products/multi-target-info').catch(() => ({ dsub_enabled: false })),
  ]);
  catalogDsubEnabled = !!(multiInfo && multiInfo.dsub_enabled);
  if (loadTheme().theme === 'brutalist') return renderCatalogBrutalist(categories, products, panelServers, sshNodes, paymentMethods);
  if (loadTheme().theme === 'bento') return renderCatalogBento(categories, products, panelServers, sshNodes, paymentMethods);
  setContent(`
    <div class="tabs">
      <button class="tab-btn ${catalogTab === 'products' ? 'active' : ''}" data-t="products">محصولات</button>
      <button class="tab-btn ${catalogTab === 'categories' ? 'active' : ''}" data-t="categories">دسته‌بندی‌ها</button>
    </div>
    <div id="catalog-body"></div>
  `);
  $$('.tab-btn', content()).forEach(b => b.addEventListener('click', () => { catalogTab = b.dataset.t; renderCatalog(); }));

  const body = $('#catalog-body');
  if (catalogTab === 'categories') {
    body.innerHTML = `
      <div class="toolbar"><button class="btn btn-primary btn-sm" id="add-cat">+ دسته‌بندی جدید</button></div>
      <div class="card"><div class="table-wrap"><table><thead><tr><th>نام</th><th>وضعیت</th><th>عملیات</th></tr></thead>
      <tbody>${categories.map(c => `<tr>
        <td>${catIndentHtml(c)}${esc(c.name)}</td>
        <td>${c.is_active ? '<span class="badge badge-approved">فعال</span>' : '<span class="badge badge-rejected">غیرفعال</span>'}</td>
        <td><div class="row-actions">${catOrderButtonsHtml(c, categories)}
        <button class="btn btn-sm" data-toggle-cat="${c.id}">${c.is_active ? 'غیرفعال کن' : 'فعال کن'}</button>
        <button class="btn btn-danger btn-sm" data-del-cat="${c.id}">حذف</button></div></td>
      </tr>`).join('') || '<tr><td colspan="3" class="empty-state">دسته‌بندی‌ای نیست</td></tr>'}</tbody></table></div></div>`;
    $('#add-cat').addEventListener('click', () => openCategoryCreateModal(categories));
    $$('[data-toggle-cat]', body).forEach(b => b.addEventListener('click', async () => {
      try { await apiPost(`/categories/${b.dataset.toggleCat}/toggle`); renderCatalog(); } catch (e) { handleErr(e); }
    }));
    $$('[data-del-cat]', body).forEach(b => b.addEventListener('click', async () => {
      if (!confirm('حذف شود؟ (محصولات این دسته هم حذف می‌شوند)')) return;
      try { await apiDelete(`/categories/${b.dataset.delCat}`); toast('حذف شد.'); renderCatalog(); } catch (e) { handleErr(e); }
    }));
    wireCategoryActions(body, categories);
    return;
  }

  const activeCategories = categories.filter(c => c.is_active);
  body.innerHTML = `
    <div class="toolbar">
      <button class="btn btn-primary btn-sm" id="add-prod" ${activeCategories.length ? '' : 'disabled'}>+ محصول جدید</button>
      ${activeCategories.length ? '' : '<span class="card-sub">برای ساخت محصول، ابتدا حداقل یک دسته‌بندی فعال بسازید.</span>'}
      <button class="btn btn-sm" id="add-cat-inline">+ دسته‌بندی جدید</button>
      ${productSearchInputHtml()}
    </div>
    ${activeCategories.length ? '' : '<div class="card" style="margin-bottom:12px"><div class="empty-state">هنوز دسته‌بندی فعالی برای فروش وجود ندارد. ابتدا دسته‌بندی بسازید و آن را فعال نگه دارید.</div></div>'}
    <div class="card"><div class="table-wrap"><table><thead><tr><th>نام</th><th>دسته</th><th>قیمت</th><th>موجودی</th><th>وضعیت</th><th>عملیات</th></tr></thead>
    <tbody>${products.map((p, i) => {
      const sameCat = products.filter(x => x.category_id === p.category_id);
      const posInCat = sameCat.findIndex(x => x.id === p.id);
      return `<tr data-search="${productSearchAttr(p)}">
      <td>
        <div class="reorder-col">
          <button class="btn btn-xs" data-prod-up="${p.id}" data-cat="${p.category_id}" ${posInCat === 0 ? 'disabled' : ''}>▲</button>
          <button class="btn btn-xs" data-prod-down="${p.id}" data-cat="${p.category_id}" ${posInCat === sameCat.length - 1 ? 'disabled' : ''}>▼</button>
        </div>
        ${esc(p.name)}
      </td><td>${esc(p.category_name)}</td><td class="mono">${fmt(p.price)}</td>
      <td class="mono">${p.is_auto_provision ? `<span class="chip">${((p.extra_panel_ids || []).length + (p.extra_ssh_node_ids || []).length) ? 'چندمقصدی' : (p.provision_ssh_node_id ? 'SSH خودکار' : (p.provision_server_id ? (p.provision_panel_type === 'stealth' ? 'VLESS خودکار' : 'VPN مستقیم') : 'خودکار'))}</span>` : fmt(p.stock)}</td>
      <td>${p.is_active ? '<span class="badge badge-approved">فعال</span>' : '<span class="badge badge-rejected">غیرفعال</span>'}</td>
      <td>
        ${!p.is_auto_provision ? `<button class="btn btn-sm" data-configs="${p.id}">بانک کانفیگ</button>` : ''}
        <button class="btn btn-sm" data-edit-prod="${p.id}">ویرایش</button>
        <button class="btn btn-sm" data-pay-methods="${p.id}">💳 پرداخت</button>
        <button class="btn btn-sm" data-toggle-prod="${p.id}">${p.is_active ? 'غیرفعال' : 'فعال'}</button>
        <button class="btn btn-danger btn-sm" data-del-prod="${p.id}">حذف</button>
      </td>
    </tr>`;
    }).join('') || '<tr><td colspan="6" class="empty-state">محصولی نیست</td></tr>'}</tbody></table></div></div>`;

  $('#add-cat-inline').addEventListener('click', () => openCategoryCreateModal(categories));
  wireProductSearch(body, 'tbody tr[data-search]', '.card');
  if (!activeCategories.length) return;
  $('#add-prod').addEventListener('click', () => { window.__productPrefillTargetConfig = null; openModal('محصول جدید', `
    <div class="form-grid">
      <select class="input" id="prod-cat">${activeCategories.map(c => `<option value="${c.id}">${esc(c.path || c.name)}</option>`).join('')}</select>
      <input class="input" id="prod-name" placeholder="نام محصول">
      <div class="form-row"><input class="input" id="prod-price" type="number" placeholder="قیمت اصلی (تومان)">
      <input class="input" id="prod-duration" type="number" placeholder="مدت (روز)" value="30"></div>
      ${productDiscountFieldsHtml('prod', null)}
      <textarea class="input" id="prod-desc" placeholder="توضیحات (اختیاری)" rows="2"></textarea>
      ${productBtnStyleHtml('prod', '')}
      <textarea class="input" id="prod-ai-desc" placeholder="🤖 توضیح برای هوش مصنوعی (راهنمای خرید؛ به کاربر نمایش داده نمی‌شود)" rows="2"></textarea>
      ${productProvisionFieldsHtml(panelServers, sshNodes)}
      ${productPaymentMethodsFieldsHtml(paymentMethods)}
      <button class="btn btn-primary" id="prod-save">ثبت</button>
    </div>`, (b, close) => {
    wireProductProvisionToggle(b);
    $('#prod-save', b).addEventListener('click', async () => {
      const name = $('#prod-name', b).value.trim();
      const price = Number($('#prod-price', b).value);
      if (!name || !price) return toast('نام و قیمت الزامی است.', true);
      const disc = readProductDiscount(b, 'prod', price);
      if (!disc) return;
      const prov = readProductProvisionFields(b);
      if (!prov.ok) return;
      const payment_methods = readProductPaymentMethodsFields(b);
      try {
        await apiPost('/products', {
          category_id: Number($('#prod-cat', b).value), name, price: disc.price, compare_price: disc.compare_price, discount_days: disc.discount_days, discount_max_uses: disc.discount_max_uses,
          description: $('#prod-desc', b).value, btn_style: readProductBtnStyle(b, 'prod'), ai_description: $('#prod-ai-desc', b)?.value || '', duration_days: prov.duration_days, product_kind: prov.product_kind || 'config',
          provision_server_id: prov.provision_server_id, provision_target_values: prov.provision_target_values, extra_panel_target_values: prov.extra_panel_target_values, provision_ssh_node_id: prov.provision_ssh_node_id, provision_ssh_protocol: prov.provision_ssh_protocol, extra_panel_ids: prov.extra_panel_ids, extra_ssh_node_ids: prov.extra_ssh_node_ids,
          auto_provision_volume_gb: prov.auto_provision_volume_gb, payment_methods, base_users: prov.base_users, extra_user_price: prov.extra_user_price, max_users: prov.max_users, renew_rules: prov.renew_rules,
        });
        toast('محصول اضافه شد.'); close(); renderCatalog();
      } catch (e) { handleErr(e); }
    });
  }); });
  $$('[data-toggle-prod]', body).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/products/${b.dataset.toggleProd}/toggle`); renderCatalog(); } catch (e) { handleErr(e); }
  }));
  $$('[data-del-prod]', body).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('این محصول حذف شود؟')) return;
    try { await apiDelete(`/products/${b.dataset.delProd}`); toast('حذف شد.'); renderCatalog(); } catch (e) { handleErr(e); }
  }));
  $$('[data-configs]', body).forEach(b => b.addEventListener('click', () => showConfigBank(Number(b.dataset.configs))));
  $$('[data-edit-prod]', body).forEach(b => b.addEventListener('click', () => {
    const p = products.find(x => x.id === Number(b.dataset.editProd));
    if (p) openProductEditModal(p, categories, panelServers, sshNodes);
  }));
  $$('[data-pay-methods]', body).forEach(b => b.addEventListener('click', () => {
    const p = products.find(x => x.id === Number(b.dataset.payMethods));
    if (p) openProductPaymentMethodsModal(p);
  }));
  async function moveProduct(productId, categoryId, dir) {
    const ids = products.filter(x => x.category_id === categoryId).map(x => x.id);
    const idx = ids.indexOf(productId);
    const swapWith = idx + dir;
    if (swapWith < 0 || swapWith >= ids.length) return;
    [ids[idx], ids[swapWith]] = [ids[swapWith], ids[idx]];
    try {
      await apiPost('/products/reorder', { category_id: categoryId, product_ids: ids });
      renderCatalog();
    } catch (e) { handleErr(e); }
  }
  $$('[data-prod-up]', body).forEach(b => b.addEventListener('click', () => moveProduct(Number(b.dataset.prodUp), Number(b.dataset.cat), -1)));
  $$('[data-prod-down]', body).forEach(b => b.addEventListener('click', () => moveProduct(Number(b.dataset.prodDown), Number(b.dataset.cat), 1)));
}

/* ---------------------------------------------------------- catalog: bento */
function renderCatalogBento(categories, products, panelServers, sshNodes, paymentMethods) {
  setContent(`
    <div class="bn-hero">
      <div><h2>ویترین محصولات</h2><p>${fmt(products.length)} محصول در ${fmt(categories.length)} دسته‌بندی</p></div>
      <div class="bn-seg">
        <button class="bn-seg-btn ${catalogTab === 'products' ? 'active' : ''}" data-t="products">محصولات</button>
        <button class="bn-seg-btn ${catalogTab === 'categories' ? 'active' : ''}" data-t="categories">دسته‌بندی‌ها</button>
      </div>
    </div>
    <div id="catalog-body"></div>
  `);
  $$('.bn-seg-btn[data-t]', content()).forEach(b => b.addEventListener('click', () => { catalogTab = b.dataset.t; renderCatalog(); }));

  const body = $('#catalog-body');
  if (catalogTab === 'categories') {
    body.innerHTML = `
      <div class="bn-toolbar" style="justify-content:flex-end"><button class="bn-btn bn-btn-ok" id="add-cat">+ دسته‌بندی جدید</button></div>
      <div class="bn-list">
        ${categories.map((c, i) => `
          <div class="bn-row bn-card-anim" style="animation-delay:${Math.min(i * 25, 220)}ms">
            ${bnAvatar(c.name.trim().charAt(0), i)}
            <div class="bn-row-main"><span class="bn-row-title">${catIndentHtml(c)}${esc(c.name)}</span></div>
            <div class="bn-row-trail">
              ${bnPill(c.is_active ? 'فعال' : 'غیرفعال', c.is_active ? 'ok' : 'no')}
              ${catOrderButtonsHtml(c, categories, 'bn-btn bn-btn-ghost')}
              <button class="bn-btn bn-btn-ghost" data-toggle-cat="${c.id}">${c.is_active ? 'غیرفعال کن' : 'فعال کن'}</button>
              <button class="bn-btn bn-btn-no" data-del-cat="${c.id}">حذف</button>
            </div>
          </div>
        `).join('') || `<div class="empty-state"><div class="icon">${svg('empty')}</div>دسته‌بندی‌ای نیست</div>`}
      </div>`;
    $('#add-cat').addEventListener('click', () => openCategoryCreateModal(categories));
    $$('[data-toggle-cat]', body).forEach(b => b.addEventListener('click', async () => {
      try { await apiPost(`/categories/${b.dataset.toggleCat}/toggle`); renderCatalog(); } catch (e) { handleErr(e); }
    }));
    $$('[data-del-cat]', body).forEach(b => b.addEventListener('click', async () => {
      if (!confirm('حذف شود؟ (محصولات این دسته هم حذف می‌شوند)')) return;
      try { await apiDelete(`/categories/${b.dataset.delCat}`); toast('حذف شد.'); renderCatalog(); } catch (e) { handleErr(e); }
    }));
    wireCategoryActions(body, categories);
    return;
  }

  body.innerHTML = `
    <div class="bn-toolbar" style="justify-content:flex-end;gap:8px">${productSearchInputHtml()}<button class="bn-btn bn-btn-ok" id="add-prod">+ محصول جدید</button></div>
    <div class="bn-card-grid">
      ${products.map((p, i) => `
        <div class="bn-card bn-card-anim" data-search="${productSearchAttr(p)}" style="animation-delay:${Math.min(i * 30, 260)}ms">
          <div class="bw ${BN_ACCENTS[i % BN_ACCENTS.length]}" style="border-radius:16px;padding:12px 14px">
            <span class="bw-value mono" style="font-size:18px">${fmt(p.price)} ت</span>
          </div>
          <div class="bn-row-title" style="font-size:14px">${esc(p.name)}</div>
          <div class="bn-row-sub">${esc(p.category_name)} · ${p.provision_ssh_node_id ? 'SSH خودکار' : (p.provision_server_id ? (p.provision_panel_type === 'stealth' ? 'VLESS خودکار' : 'VPN مستقیم') : (p.is_auto_provision ? 'خودکار' : 'موجودی: '+fmt(p.stock)))}</div>
          ${bnPill(p.is_active ? 'فعال' : 'غیرفعال', p.is_active ? 'ok' : 'no')}
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">
            ${!p.is_auto_provision ? `<button class="bn-btn bn-btn-ghost" data-configs="${p.id}">بانک کانفیگ</button>` : ''}
            <button class="bn-btn bn-btn-ghost" data-edit-prod="${p.id}">ویرایش</button>
            <button class="bn-btn bn-btn-ghost" data-pay-methods="${p.id}">💳 پرداخت</button>
            <button class="bn-btn bn-btn-ghost" data-toggle-prod="${p.id}">${p.is_active ? 'غیرفعال' : 'فعال'}</button>
            <button class="bn-btn bn-btn-no" data-del-prod="${p.id}">حذف</button>
          </div>
        </div>
      `).join('') || `<div class="empty-state" style="grid-column:1/-1"><div class="icon">${svg('empty')}</div>محصولی نیست</div>`}
    </div>`;

  wireProductSearch(body, '.bn-card[data-search]', '.bn-card-grid');
  $('#add-prod').addEventListener('click', () => openModal('محصول جدید', `
    <div class="form-grid">
      <select class="input" id="prod-cat">${categories.map(c => `<option value="${c.id}">${esc(c.path || c.name)}</option>`).join('')}</select>
      <input class="input" id="prod-name" placeholder="نام محصول">
      <div class="form-row"><input class="input" id="prod-price" type="number" placeholder="قیمت اصلی (تومان)">
      <input class="input" id="prod-duration" type="number" placeholder="مدت (روز)" value="30"></div>
      ${productDiscountFieldsHtml('prod', null)}
      <textarea class="input" id="prod-desc" placeholder="توضیحات (اختیاری)" rows="2"></textarea>
      ${productBtnStyleHtml('prod', '')}
      <textarea class="input" id="prod-ai-desc" placeholder="🤖 توضیح برای هوش مصنوعی (راهنمای خرید؛ به کاربر نمایش داده نمی‌شود)" rows="2"></textarea>
      ${productProvisionFieldsHtml(panelServers, sshNodes)}
      ${productPaymentMethodsFieldsHtml(paymentMethods)}
      <button class="btn btn-primary" id="prod-save">ثبت</button>
    </div>`, (b, close) => {
    wireProductProvisionToggle(b);
    $('#prod-save', b).addEventListener('click', async () => {
      const name = $('#prod-name', b).value.trim();
      const price = Number($('#prod-price', b).value);
      if (!name || !price) return toast('نام و قیمت الزامی است.', true);
      const disc = readProductDiscount(b, 'prod', price);
      if (!disc) return;
      const prov = readProductProvisionFields(b);
      if (!prov.ok) return;
      const payment_methods = readProductPaymentMethodsFields(b);
      try {
        await apiPost('/products', {
          category_id: Number($('#prod-cat', b).value), name, price: disc.price, compare_price: disc.compare_price, discount_days: disc.discount_days, discount_max_uses: disc.discount_max_uses,
          description: $('#prod-desc', b).value, btn_style: readProductBtnStyle(b, 'prod'), ai_description: $('#prod-ai-desc', b)?.value || '', duration_days: prov.duration_days, product_kind: prov.product_kind || 'config',
          provision_server_id: prov.provision_server_id, provision_target_values: prov.provision_target_values, extra_panel_target_values: prov.extra_panel_target_values, provision_ssh_node_id: prov.provision_ssh_node_id, provision_ssh_protocol: prov.provision_ssh_protocol, extra_panel_ids: prov.extra_panel_ids, extra_ssh_node_ids: prov.extra_ssh_node_ids,
          auto_provision_volume_gb: prov.auto_provision_volume_gb, payment_methods, base_users: prov.base_users, extra_user_price: prov.extra_user_price, max_users: prov.max_users, renew_rules: prov.renew_rules,
        });
        toast('محصول اضافه شد.'); close(); renderCatalog();
      } catch (e) { handleErr(e); }
    });
  }));
  $$('[data-toggle-prod]', body).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/products/${b.dataset.toggleProd}/toggle`); renderCatalog(); } catch (e) { handleErr(e); }
  }));
  $$('[data-del-prod]', body).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('این محصول حذف شود؟')) return;
    try { await apiDelete(`/products/${b.dataset.delProd}`); toast('حذف شد.'); renderCatalog(); } catch (e) { handleErr(e); }
  }));
  $$('[data-configs]', body).forEach(b => b.addEventListener('click', () => showConfigBank(Number(b.dataset.configs))));
  $$('[data-edit-prod]', body).forEach(b => b.addEventListener('click', () => {
    const p = products.find(x => x.id === Number(b.dataset.editProd));
    if (p) openProductEditModal(p, categories, panelServers, sshNodes);
  }));
  $$('[data-pay-methods]', body).forEach(b => b.addEventListener('click', () => {
    const p = products.find(x => x.id === Number(b.dataset.payMethods));
    if (p) openProductPaymentMethodsModal(p);
  }));
}

/* -------------------------------------------------- catalog: brutalist -- */
// محصولات به‌شکل «برچسب قیمت آویزون» (تگ مشکی با سوراخ) و دسته‌بندی‌ها به
// شکل ردیف‌های فهرست ضخیم‌قاب.
function renderCatalogBrutalist(categories, products, panelServers, sshNodes, paymentMethods) {
  setContent(`
    <div class="bru-hero" style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
      <div>
        <h2>ویترین محصولات</h2>
        <p>${fmt(products.length)} محصول در ${fmt(categories.length)} دسته‌بندی</p>
      </div>
      <div class="bru-seg" role="tablist">
        <button class="bru-seg-btn ${catalogTab === 'products' ? 'active' : ''}" data-t="products">محصولات</button>
        <button class="bru-seg-btn ${catalogTab === 'categories' ? 'active' : ''}" data-t="categories">دسته‌بندی‌ها</button>
      </div>
    </div>
    <div id="catalog-body"></div>
  `);
  $$('.bru-seg-btn[data-t]', content()).forEach(b => b.addEventListener('click', () => { catalogTab = b.dataset.t; renderCatalog(); }));

  const body = $('#catalog-body');
  if (catalogTab === 'categories') {
    body.innerHTML = `
      <div class="bru-toolbar" style="justify-content:flex-end">
        <button class="bru-stamp bru-stamp-ok" id="add-cat" style="--r:-3deg">+ دسته‌بندی جدید</button>
      </div>
      <div class="bru-cat-list">
        ${categories.map((c, i) => `
          <div class="bru-cat-row bru-card-anim" style="animation-delay:${Math.min(i * 30, 250)}ms">
            <span class="bru-cat-name">${catIndentHtml(c)}${esc(c.name)}</span>
            <span class="bru-flag ${c.is_active ? 'bru-flag-ok' : 'bru-flag-no'}">${c.is_active ? 'فعال' : 'غیرفعال'}</span>
            <div class="bru-cat-actions">
              ${catOrderButtonsHtml(c, categories)}
        <button class="btn btn-sm" data-toggle-cat="${c.id}">${c.is_active ? 'غیرفعال کن' : 'فعال کن'}</button>
              <button class="btn btn-danger btn-sm" data-del-cat="${c.id}">حذف</button>
            </div>
          </div>
        `).join('') || `<div class="empty-state"><div class="icon">${svg('empty')}</div>دسته‌بندی‌ای نیست</div>`}
      </div>`;
    $('#add-cat').addEventListener('click', () => openCategoryCreateModal(categories));
    $$('[data-toggle-cat]', body).forEach(b => b.addEventListener('click', async () => {
      try { await apiPost(`/categories/${b.dataset.toggleCat}/toggle`); renderCatalog(); } catch (e) { handleErr(e); }
    }));
    $$('[data-del-cat]', body).forEach(b => b.addEventListener('click', async () => {
      if (!confirm('حذف شود؟ (محصولات این دسته هم حذف می‌شوند)')) return;
      try { await apiDelete(`/categories/${b.dataset.delCat}`); toast('حذف شد.'); renderCatalog(); } catch (e) { handleErr(e); }
    }));
    wireCategoryActions(body, categories);
    return;
  }

  body.innerHTML = `
    <div class="bru-toolbar" style="justify-content:flex-end;gap:8px">
      ${productSearchInputHtml()}
      <button class="bru-stamp bru-stamp-ok" id="add-prod" style="--r:-3deg">+ محصول جدید</button>
    </div>
    <div class="bru-product-grid">
      ${products.map((p, i) => `
        <div class="bru-product-card bru-card-anim" data-search="${productSearchAttr(p)}" style="animation-delay:${Math.min(i * 35, 300)}ms">
          <div class="bru-product-tag">
            <span class="bru-product-tag-hole"></span>
            <span class="bru-product-price mono">${fmt(p.price)} ت</span>
          </div>
          <div class="bru-product-body">
            <div class="bru-product-name">${esc(p.name)}</div>
            <div class="bru-product-cat">${esc(p.category_name)}</div>
            <div class="bru-coupon-row"><span>موجودی</span><b class="mono">${p.is_auto_provision ? 'خودکار' : fmt(p.stock)}</b></div>
            <span class="bru-flag ${p.is_active ? 'bru-flag-ok' : 'bru-flag-no'}" style="align-self:flex-start">${p.is_active ? 'فعال' : 'غیرفعال'}</span>
          </div>
          <div class="bru-coupon-actions" style="flex-wrap:wrap">
            ${!p.is_auto_provision ? `<button class="btn btn-sm" data-configs="${p.id}">بانک کانفیگ</button>` : ''}
            <button class="btn btn-sm" data-edit-prod="${p.id}">ویرایش</button>
            <button class="btn btn-sm" data-pay-methods="${p.id}">💳 پرداخت</button>
            <button class="btn btn-sm" data-toggle-prod="${p.id}">${p.is_active ? 'غیرفعال' : 'فعال'}</button>
            <button class="btn btn-danger btn-sm" data-del-prod="${p.id}">حذف</button>
          </div>
        </div>
      `).join('') || `<div class="empty-state" style="grid-column:1/-1"><div class="icon">${svg('empty')}</div>محصولی نیست</div>`}
    </div>`;

  wireProductSearch(body, '.bru-product-card[data-search]', '.bru-product-grid');
  $('#add-prod').addEventListener('click', () => openModal('محصول جدید', `
    <div class="form-grid">
      <select class="input" id="prod-cat">${categories.map(c => `<option value="${c.id}">${esc(c.path || c.name)}</option>`).join('')}</select>
      <input class="input" id="prod-name" placeholder="نام محصول">
      <div class="form-row"><input class="input" id="prod-price" type="number" placeholder="قیمت اصلی (تومان)">
      <input class="input" id="prod-duration" type="number" placeholder="مدت (روز)" value="30"></div>
      ${productDiscountFieldsHtml('prod', null)}
      <textarea class="input" id="prod-desc" placeholder="توضیحات (اختیاری)" rows="2"></textarea>
      ${productBtnStyleHtml('prod', '')}
      <textarea class="input" id="prod-ai-desc" placeholder="🤖 توضیح برای هوش مصنوعی (راهنمای خرید؛ به کاربر نمایش داده نمی‌شود)" rows="2"></textarea>
      ${productProvisionFieldsHtml(panelServers, sshNodes)}
      ${productPaymentMethodsFieldsHtml(paymentMethods)}
      <button class="btn btn-primary" id="prod-save">ثبت</button>
    </div>`, (b, close) => {
    wireProductProvisionToggle(b);
    $('#prod-save', b).addEventListener('click', async () => {
      const name = $('#prod-name', b).value.trim();
      const price = Number($('#prod-price', b).value);
      if (!name || !price) return toast('نام و قیمت الزامی است.', true);
      const disc = readProductDiscount(b, 'prod', price);
      if (!disc) return;
      const prov = readProductProvisionFields(b);
      if (!prov.ok) return;
      const payment_methods = readProductPaymentMethodsFields(b);
      try {
        await apiPost('/products', {
          category_id: Number($('#prod-cat', b).value), name, price: disc.price, compare_price: disc.compare_price, discount_days: disc.discount_days, discount_max_uses: disc.discount_max_uses,
          description: $('#prod-desc', b).value, btn_style: readProductBtnStyle(b, 'prod'), ai_description: $('#prod-ai-desc', b)?.value || '', duration_days: prov.duration_days, product_kind: prov.product_kind || 'config',
          provision_server_id: prov.provision_server_id, provision_target_values: prov.provision_target_values, extra_panel_target_values: prov.extra_panel_target_values, provision_ssh_node_id: prov.provision_ssh_node_id, provision_ssh_protocol: prov.provision_ssh_protocol, extra_panel_ids: prov.extra_panel_ids, extra_ssh_node_ids: prov.extra_ssh_node_ids,
          auto_provision_volume_gb: prov.auto_provision_volume_gb, payment_methods, base_users: prov.base_users, extra_user_price: prov.extra_user_price, max_users: prov.max_users, renew_rules: prov.renew_rules,
        });
        toast('محصول اضافه شد.'); close(); renderCatalog();
      } catch (e) { handleErr(e); }
    });
  }));
  $$('[data-toggle-prod]', body).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/products/${b.dataset.toggleProd}/toggle`); renderCatalog(); } catch (e) { handleErr(e); }
  }));
  $$('[data-del-prod]', body).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('این محصول حذف شود؟')) return;
    try { await apiDelete(`/products/${b.dataset.delProd}`); toast('حذف شد.'); renderCatalog(); } catch (e) { handleErr(e); }
  }));
  $$('[data-configs]', body).forEach(b => b.addEventListener('click', () => showConfigBank(Number(b.dataset.configs))));
  $$('[data-edit-prod]', body).forEach(b => b.addEventListener('click', () => {
    const p = products.find(x => x.id === Number(b.dataset.editProd));
    if (p) openProductEditModal(p, categories, panelServers, sshNodes);
  }));
  $$('[data-pay-methods]', body).forEach(b => b.addEventListener('click', () => {
    const p = products.find(x => x.id === Number(b.dataset.payMethods));
    if (p) openProductPaymentMethodsModal(p);
  }));
}

/* ------------------------------------------------------- catalog: glass -- */

/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

async function showConfigBank(productId) {
  const [res, usedRes] = await Promise.all([
    apiGet(`/products/${productId}/configs`),
    apiGet(`/products/${productId}/configs/used`),
  ]);
  const configs = res.items || [];
  const usedConfigs = usedRes.items || [];
  const usedCount = res.used_count || 0;
  const isPanelKind = res.product_kind === 'panel_account';
  openModal(isPanelKind ? 'موجودی پنل‌ها' : 'بانک کانفیگ', `
    <div class="cfg-stats">
      <div class="cfg-stat"><span>لینک‌های آزاد</span><b class="mono">${fmt(configs.length)}</b></div>
      <div class="cfg-stat"><span>تحویل‌شده</span><b class="mono">${fmt(usedCount)}</b></div>
      <div class="cfg-stat"><span>مجموع</span><b class="mono">${fmt(configs.length + usedCount)}</b></div>
    </div>
    <label class="field" style="margin-top:16px">
      <span>${isPanelKind ? 'افزودن پنل جدید' : 'افزودن لینک جدید'}</span>
      <textarea class="input" id="new-links" rows="6" placeholder="${isPanelKind ? 'هر خط یک پنل: آدرس | یوزر | پسورد | توضیحات' : 'هر خط یک لینک کانفیگ...'}"></textarea>
    </label>
    <button class="btn btn-primary btn-block" id="add-links" style="margin-top:10px">افزودن لینک‌ها</button>
    <h4 class="cfg-list-title">لینک‌های آزاد (${configs.length})</h4>
    <div class="table-wrap cfg-table-wrap">
      <table><tbody>${configs.map(c => `<tr>
        <td class="mono cfg-link-cell">${esc(c.link)}</td>
        <td class="cfg-actions"><button class="btn btn-ghost btn-sm" data-copy-cfg="${esc(c.link)}">کپی</button><button class="btn btn-danger btn-sm" data-del-cfg="${c.id}">حذف</button></td>
      </tr>`).join('') || `<tr><td colspan="2" class="empty-state"><div class="icon">${svg('empty')}</div>خالی است</td></tr>`}</tbody></table>
    </div>
    <h4 class="cfg-list-title">تحویل‌شده / ناموجود (${usedConfigs.length})</h4>
    <div class="table-wrap cfg-table-wrap">
      <table><tbody>${usedConfigs.map(c => `<tr>
        <td class="mono cfg-link-cell">${esc(c.link)}</td>
        <td class="mono">${c.assigned_user_id ? esc(String(c.assigned_user_id)) : '-'}</td>
        <td class="cfg-actions"><button class="btn btn-ghost btn-sm" data-copy-cfg="${esc(c.link)}">کپی</button><button class="btn btn-danger btn-sm" data-del-used-cfg="${c.id}">حذف</button></td>
      </tr>`).join('') || `<tr><td colspan="3" class="empty-state"><div class="icon">${svg('empty')}</div>خالی است</td></tr>`}</tbody></table>
    </div>
  `, (body, close) => {
    $('#add-links', body).addEventListener('click', async () => {
      const links = $('#new-links', body).value;
      if (!links.trim()) return;
      try {
        const r = await apiPost(`/products/${productId}/configs`, { links });
        toast(`${r.added} لینک اضافه شد${r.duplicates ? ` (${r.duplicates} تکراری نادیده گرفته شد)` : ''}.`);
        close(); showConfigBank(productId);
      } catch (e) { handleErr(e); }
    });
    $$('[data-copy-cfg]', body).forEach(b => b.addEventListener('click', () => {
      navigator.clipboard?.writeText(b.dataset.copyCfg).then(() => toast('کپی شد.'));
    }));
    $$('[data-del-cfg]', body).forEach(b => b.addEventListener('click', async () => {
      try { await apiDelete(`/configs/${b.dataset.delCfg}`); close(); showConfigBank(productId); } catch (e) { handleErr(e); }
    }));
    $$('[data-del-used-cfg]', body).forEach(b => b.addEventListener('click', async () => {
      if (!confirm('این کانفیگِ تحویل‌شده برای همیشه از بانک محصول حذف می‌شود و این عملیات غیرقابل بازگشت است. ادامه می‌دهید؟')) return;
      try { await apiDelete(`/products/${productId}/configs/${b.dataset.delUsedCfg}/used`); close(); showConfigBank(productId); } catch (e) { handleErr(e); }
    }));
  }, { wide: true });
}

/* ===================================================== reseller tiers === */
const TIER_NUM_FIELDS = [
  ['commission_min', 'حداقل درصد کمیسیون (خالی=بدون محدودیت)'],
  ['commission_max', 'حداکثر درصد کمیسیون (خالی=بدون محدودیت)'],
  ['permanent_discount_percent', 'تخفیف دائمی٪ (سطح تخفیفی)'],
  ['min_qty', 'حداقل تعداد خرید (خرید عمده محصول)'],
  ['min_volume_gb', 'حداقل حجم خرید به گیگ (اعتبار حجمی)'],
  ['credit_limit_toman', 'سقف اعتبار پس‌پرداخت به تومان (۰=بدون اعتبار)'],
];
const TIER_FLAG_FIELDS = [
  ['has_miniapp', 'مینی‌اپ اختصاصی'], ['has_web_panel', 'پنل وب'],
  ['has_dedicated_bot', 'بات مستقل'], ['auto_approve', 'تایید خودکار درخواست (سطح تخفیفی)'],
];
function tierSummaryLine(t) {
  const parts = [];
  if (t.commission_min !== null || t.commission_max !== null) parts.push(`کمیسیون ${fmt(t.commission_min ?? 0)} تا ${fmt(t.commission_max ?? 100)}٪`);
  if (t.permanent_discount_percent !== null) parts.push(`تخفیف دائمی ${fmt(t.permanent_discount_percent)}٪`);
  if (t.min_qty !== null) parts.push(`حداقل ${fmt(t.min_qty)} عدد`);
  if (t.min_volume_gb !== null) parts.push(`حداقل ${fmt(t.min_volume_gb)} گیگ`);
  if (t.credit_limit_toman) parts.push(`سقف اعتبار ${fmt(t.credit_limit_toman)} تومان`);
  [['has_miniapp', 'مینی‌اپ'], ['has_web_panel', 'پنل وب'], ['has_dedicated_bot', 'بات مستقل']].forEach(([k, l]) => { if (t[k]) parts.push(l); });
  return parts.join(' · ') || '—';
}
function openTierEditor(t, reload) {
  const isDiscount = t.model === 'discount';
  const numFields = isDiscount ? TIER_NUM_FIELDS.filter(([k]) => k === 'permanent_discount_percent' || k === 'credit_limit_toman') : TIER_NUM_FIELDS;
  const flagFields = isDiscount ? TIER_FLAG_FIELDS.filter(([k]) => k === 'auto_approve') : TIER_FLAG_FIELDS;
  const nums = numFields.map(([k, label]) => `<label class="field"><span>${label}</span><input class="input" id="tier-${k}" type="number" min="0" value="${t[k] ?? ''}"></label>`).join('');
  const flags = flagFields.map(([k, label]) => `<label class="field"><span><input type="checkbox" id="tier-${k}" ${t[k] ? 'checked' : ''}> ${label}</span></label>`).join('');
  openModal(`ویرایش سطح ${esc(t.title)}`, `
    <div class="form-grid">
      <div class="form-row">
        <input class="input" id="tier-title" placeholder="عنوان" value="${esc(t.title)}">
        <input class="input" id="tier-icon" placeholder="ایموجی" value="${esc(t.icon)}">
      </div>
      <input class="input" id="tier-summary" placeholder="توضیح کوتاه (داخل لیست سطح‌ها)" value="${esc(t.summary)}">
      <input class="input" id="tier-description" placeholder="توضیح کامل (کارت جزئیات)" value="${esc(t.description)}">
      <label class="field"><span>ترتیب نمایش</span><input class="input" id="tier-sort_order" type="number" value="${t.sort_order}"></label>
      ${nums}${flags}
      <button class="btn btn-primary" id="tier-save">ذخیره</button>
    </div>`, (b, close) => {
    $('#tier-save', b).addEventListener('click', async () => {
      const payload = {
        title: $('#tier-title', b).value.trim(), icon: $('#tier-icon', b).value.trim(),
        summary: $('#tier-summary', b).value.trim(), description: $('#tier-description', b).value.trim(),
        sort_order: Number($('#tier-sort_order', b).value) || 0,
      };
      numFields.forEach(([k]) => { const v = $('#tier-' + k, b).value; payload[k] = v === '' ? null : Number(v); });
      flagFields.forEach(([k]) => { payload[k] = $('#tier-' + k, b).checked; });
      try { await apiPut(`/reseller-tiers/${t.code}`, payload); toast('ذخیره شد.'); close(); reload(); } catch (e) { handleErr(e); }
    });
  });
}
async function renderResellerTiers() {
  const [tiers, requests] = await Promise.all([apiGet('/reseller-tiers'), apiGet('/reseller-requests?status=pending_review')]);
  const members = {};
  await Promise.all(tiers.filter(t => t.model === 'discount').map(async t => { members[t.code] = await apiGet(`/reseller-tiers/${t.code}/members`); }));
  const requestsHtml = requests.length ? `
    <div class="card"><h3 style="margin:12px">درخواست‌های جدید نمایندگی</h3><div class="table-wrap"><table>
      <thead><tr><th>سطح</th><th>کاربر</th><th>آیدی</th><th>عملیات</th></tr></thead>
      <tbody>${requests.map(r => `<tr>
        <td>${esc(r.tier_title || r.tier_code || '—')}</td><td>${esc(r.first_name || '')} ${r.username ? '@' + esc(r.username) : ''}</td>
        <td class="mono">${r.user_id}</td>
        <td><button class="btn btn-primary btn-sm" data-quote-tier="${r.id}">💰 بررسی و قیمت‌گذاری</button>
        <button class="btn btn-danger btn-sm" data-reject-tier="${r.id}">رد</button></td>
      </tr>`).join('')}</tbody></table></div></div>` : '';
  const tierCards = tiers.map(t => `
    <div class="card" style="margin-top:12px">
      <div class="toolbar">
        <strong>${esc(t.icon)} ${esc(t.title)}</strong>
        <span class="badge">${esc(t.model_label)}</span>
        ${t.is_enabled ? '<span class="badge badge-approved">فعال</span>' : '<span class="badge badge-rejected">غیرفعال</span>'}
        <span style="margin-inline-start:auto"></span>
        <button class="btn btn-sm" data-tier-toggle="${t.code}">${t.is_enabled ? 'غیرفعال‌سازی' : 'فعال‌سازی'}</button>
        <button class="btn btn-primary btn-sm" data-tier-edit="${t.code}">ویرایش</button>
      </div>
      <p style="margin:0 12px 12px;font-size:13px">${esc(t.summary)}<br><span style="color:var(--muted,#888)">${tierSummaryLine(t)}</span></p>
      <div class="toolbar" style="margin:0 12px 12px"><button class="btn btn-sm" data-paycfg="${t.code}">💳 درگاه‌های هزینه نمایندگی</button></div>
      ${t.model === 'discount' && !t.permanent_discount_percent && !t.qty_discounts.length ? '<p style="margin:0 12px 12px;font-size:13px;color:var(--danger,#d33)">⚠️ هنوز هیچ تخفیفی (دائمی یا پلکانی) برای این سطح تنظیم نشده؛ تا آن موقع خریدها بدون تخفیف ثبت می‌شوند.</p>' : ''}
      ${t.model === 'discount' ? `
        <div style="margin:0 12px 12px">
          <div class="toolbar"><strong style="font-size:13px">پلکان تخفیف خرید یک‌جا</strong>
            <button class="btn btn-sm" data-qty-add="${t.code}">+ پله</button></div>
          <div class="table-wrap"><table><thead><tr><th>از تعداد</th><th>درصد تخفیف</th><th></th></tr></thead>
          <tbody>${t.qty_discounts.map(q => `<tr><td class="mono">${fmt(q.min_qty)}</td><td class="mono">${fmt(q.discount_percent)}٪</td>
            <td><button class="btn btn-danger btn-sm" data-qty-del="${q.id}">حذف</button></td></tr>`).join('') || '<tr><td colspan="3" class="empty-state">پله‌ای ثبت نشده</td></tr>'}</tbody></table></div>
          <div class="toolbar" style="margin-top:8px"><strong style="font-size:13px">اعضا (${fmt(t.members_count)})</strong>
            <button class="btn btn-sm" data-member-add="${t.code}">+ عضو</button></div>
          <div class="table-wrap"><table><thead><tr><th>نام</th><th>آیدی</th><th>تخفیف</th><th></th></tr></thead>
          <tbody>${(members[t.code] || []).map(m => `<tr><td>${esc(m.first_name || '')} ${m.username ? '@' + esc(m.username) : ''}</td>
            <td class="mono">${m.telegram_id}</td>
            <td class="mono">${m.reseller_discount_percent ? fmt(m.reseller_discount_percent) + '٪' : '—'}</td>
            <td><button class="btn btn-danger btn-sm" data-member-del="${t.code}:${m.telegram_id}">حذف عضویت</button></td></tr>`).join('') || '<tr><td colspan="4" class="empty-state">عضوی ندارد</td></tr>'}</tbody></table></div>
        </div>` : ''}
    </div>`).join('');
  setContent(requestsHtml + tierCards);
  const reload = () => renderResellerTiers();
  $$('[data-tier-edit]', content()).forEach(b => b.addEventListener('click', () => openTierEditor(tiers.find(t => t.code === b.dataset.tierEdit), reload)));
  $$('[data-tier-toggle]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/reseller-tiers/${b.dataset.tierToggle}/toggle`); reload(); } catch (e) { handleErr(e); }
  }));
  $$('[data-quote-tier]', content()).forEach(b => b.addEventListener('click', () => {
    const req = requests.find(x => String(x.id) === String(b.dataset.quoteTier));
    if (req) openResellerRequestModal(req);
  }));
  $$('[data-reject-tier]', content()).forEach(b => b.addEventListener('click', () => openResellerRequestRejectModal(Number(b.dataset.rejectTier), 'rejected', null)));
  $$('[data-paycfg]', content()).forEach(b => b.addEventListener('click', async () => {
    const code = b.dataset.paycfg;
    try {
      const data = await apiGet(`/reseller-tiers/${code}/payment-methods`);
      const checks = data.methods.map(m => `<label class="field"><span><input type="checkbox" data-pm="${esc(m.key)}" ${data.selected.includes(m.key) ? 'checked' : ''}> ${esc(m.label)}</span></label>`).join('');
      openModal('درگاه‌های هزینه نمایندگی', `<div class="form-grid">${checks}<button class="btn btn-primary" id="save-reseller-pm">ذخیره</button></div>`, (body, close) => {
        $('#save-reseller-pm', body).addEventListener('click', async () => {
          const methods = $$('[data-pm]', body).filter(x => x.checked).map(x => x.dataset.pm);
          if (!methods.length) { toast('حداقل یک درگاه را انتخاب کنید.', true); return; }
          try { await apiPut(`/reseller-tiers/${code}/payment-methods`, {methods}); toast('ذخیره شد.'); close(); } catch(e) { handleErr(e); }
        });
      });
    } catch(e) { handleErr(e); }
  }));
  $$('[data-qty-del]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiDelete(`/reseller-tiers/qty-discounts/${b.dataset.qtyDel}`); reload(); } catch (e) { handleErr(e); }
  }));
  $$('[data-member-del]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('عضویت این کاربر حذف شود؟')) return;
    const [code, uid] = b.dataset.memberDel.split(':');
    try { await apiDelete(`/reseller-tiers/${code}/members/${uid}`); toast('حذف شد.'); reload(); } catch (e) { handleErr(e); }
  }));
  $$('[data-member-add]', content()).forEach(b => b.addEventListener('click', () => {
    const code = b.dataset.memberAdd;
    const isSilver = code === 'silver';
    openModal(isSilver ? 'افزودن نماینده نقره‌ای' : 'افزودن عضو به سطح', `
    <div class="form-grid">
      <div style="opacity:.72;font-size:12.5px">آیدی عددی تلگرام کاربر را وارد کنید.</div>
      <input class="input" id="member-tgid" type="number" min="1" placeholder="آیدی عددی تلگرام کاربر">
      ${isSilver ? `<label class="field"><span>درصد تخفیف اختصاصی این نماینده</span><input class="input" id="member-discount" type="number" min="1" max="100" placeholder="مثلاً 15"></label><div style="opacity:.65;font-size:12px">این درصد فقط برای همین نماینده است؛ پلکان خرید عمده می‌تواند تخفیف را بیشتر کند.</div>` : ''}
      <button class="btn btn-primary" id="member-save">${isSilver ? 'ثبت نماینده نقره‌ای' : 'افزودن'}</button>
    </div>`, (m, close) => {
    $('#member-save', m).addEventListener('click', async () => {
      const telegram_id = Number($('#member-tgid', m).value);
      const payload = { telegram_id };
      if (isSilver) payload.discount_percent = Number($('#member-discount', m).value);
      if (!telegram_id || (isSilver && (!payload.discount_percent || payload.discount_percent < 1 || payload.discount_percent > 100))) {
        toast(isSilver ? 'آیدی و درصد تخفیف ۱ تا ۱۰۰ را وارد کنید.' : 'آیدی نامعتبر است.', true); return;
      }
      try {
        await apiPost(`/reseller-tiers/${code}/members`, payload);
        toast(isSilver ? `نماینده نقره‌ای با تخفیف ${payload.discount_percent}٪ ثبت شد.` : 'عضو اضافه شد.'); close(); reload();
      } catch (e) { handleErr(e); }
    });
  });
  }));
  $$('[data-qty-add]', content()).forEach(b => b.addEventListener('click', () => openModal('پله‌ی جدید تخفیف', `
    <div class="form-grid">
      <input class="input" id="qty-min" type="number" min="2" placeholder="حداقل تعداد خرید یک‌جا (مثلا ۱۰)">
      <input class="input" id="qty-pct" type="number" min="1" max="100" placeholder="درصد تخفیف">
      <button class="btn btn-primary" id="qty-save">ثبت</button>
    </div>`, (m, close) => {
    $('#qty-save', m).addEventListener('click', async () => {
      try {
        await apiPost(`/reseller-tiers/${b.dataset.qtyAdd}/qty-discounts`, {
          min_qty: Number($('#qty-min', m).value), discount_percent: Number($('#qty-pct', m).value),
        });
        toast('ثبت شد.'); close(); reload();
      } catch (e) { handleErr(e); }
    });
  })));
}

/* ========================================================== discounts === */
function discountExtraFieldsHtml(categories, products) {
  return `
      <div class="form-row">
        <input class="input" id="code-minpurchase" type="number" placeholder="حداقل مبلغ خرید (تومان)">
        <input class="input" id="code-maxpurchase" type="number" placeholder="حداکثر مبلغ خرید (تومان)">
      </div>
      <label class="field"><span>سقف مبلغ تخفیف (تومان، فقط برای تخفیف درصدی — مثلاً ۲۰٪ تا سقف ۴۰۰۰۰ تومان)</span>
        <input class="input" id="code-maxdiscount" type="number" placeholder="خالی = بدون سقف"></label>
      <select class="input" id="code-scope">
        <option value="">🌐 بدون محدودیت (همه‌ی محصولات)</option>
        ${categories.length ? `<optgroup label="فقط یک دسته‌بندی خاص">${categories.map(c => `<option value="cat:${c.id}">📁 ${esc(c.path || c.name)}</option>`).join('')}</optgroup>` : ''}
        ${products.length ? `<optgroup label="فقط یک محصول خاص">${products.map(p => `<option value="prod:${p.id}">📦 ${esc(p.name)}</option>`).join('')}</optgroup>` : ''}
        ${products.length ? `<option value="mprod">🧩 چند محصول خاص (انتخاب زیر)</option>` : ''}
      </select>
      <div id="code-mprod-wrap" style="display:none">
        <div class="form-row" style="flex-wrap:wrap;gap:6px;max-height:180px;overflow:auto;border:1px solid var(--border,#ddd);border-radius:8px;padding:8px">
          ${products.map(p => `<label style="display:flex;align-items:center;gap:6px;font-size:13px">
            <input type="checkbox" class="code-mprod-item" value="${p.id}"><span>${esc(p.name)}</span></label>`).join('')}
        </div>
      </div>
      <label class="field"><span>تاریخ انقضا (اختیاری)</span><input class="input" id="code-expires" type="date"></label>
      <div class="form-row">
        <input class="input" id="code-peruser" type="number" min="0" placeholder="سقف استفاده‌ی هر کاربر (خالی=نامحدود)">
        <select class="input" id="code-audience">
          <option value="all">👥 همه‌ی کاربران</option>
          <option value="normal">🙂 فقط کاربران عادی</option>
          <option value="reseller">🤝 فقط نمایندگان</option>
        </select>
      </div>
      <label class="field" style="display:flex;align-items:center;gap:8px"><input type="checkbox" id="code-firstonly"><span>فقط برای اولین خرید کاربر</span></label>`;
}
function discountExtraFieldsBindScope(b) {
  const scopeEl = $('#code-scope', b);
  const wrap = $('#code-mprod-wrap', b);
  if (!scopeEl || !wrap) return;
  scopeEl.addEventListener('change', () => { wrap.style.display = scopeEl.value === 'mprod' ? '' : 'none'; });
}
function discountExtraFieldsPayload(b) {
  const scope = $('#code-scope', b).value;
  let product_id = null, category_id = null, product_ids = null;
  if (scope.startsWith('cat:')) category_id = Number(scope.split(':')[1]);
  if (scope.startsWith('prod:')) product_id = Number(scope.split(':')[1]);
  if (scope === 'mprod') {
    product_ids = $$('.code-mprod-item', b).filter(i => i.checked).map(i => Number(i.value));
    if (!product_ids.length) product_ids = null;
  }
  const expiresRaw = $('#code-expires', b).value;
  return {
    min_purchase: Number($('#code-minpurchase', b).value) || null,
    max_purchase: Number($('#code-maxpurchase', b).value) || null,
    max_discount_amount: Number($('#code-maxdiscount', b).value) || null,
    product_id, category_id, product_ids,
    expires_at: expiresRaw ? new Date(expiresRaw + 'T23:59:59').toISOString() : null,
    per_user_limit: Number($('#code-peruser', b).value) || null,
    first_purchase_only: $('#code-firstonly', b).checked,
    audience: $('#code-audience', b).value,
  };
}
function discountConstraintsLine(c, categories, products) {
  const parts = [];
  if (c.min_purchase) parts.push(`حداقل خرید ${fmt(c.min_purchase)}ت`);
  if (c.max_purchase) parts.push(`حداکثر خرید ${fmt(c.max_purchase)}ت`);
  if (c.max_discount_amount) parts.push(`سقف تخفیف ${fmt(c.max_discount_amount)}ت`);
  if (c.product_ids && c.product_ids.length) {
    const names = c.product_ids.map(id => { const p = products.find(x => x.id === id); return p ? esc(p.name) : '#' + id; });
    parts.push(`مخصوص محصولات: ${names.join('، ')}`);
  } else if (c.product_id) { const p = products.find(x => x.id === c.product_id); parts.push(`مخصوص محصول: ${p ? esc(p.name) : '#' + c.product_id}`); }
  else if (c.category_id) { const cat = categories.find(x => x.id === c.category_id); parts.push(`مخصوص دسته: ${cat ? esc(cat.name) : '#' + c.category_id}`); }
  if (c.per_user_limit) parts.push(`هر کاربر ${c.per_user_limit} بار`);
  if (c.first_purchase_only) parts.push('فقط خرید اول');
  if (c.audience === 'normal') parts.push('فقط کاربران عادی');
  else if (c.audience === 'reseller') parts.push('فقط نمایندگان');
  if (c.expires_at) parts.push(`انقضا: ${String(c.expires_at).slice(0, 10)}`);
  return parts.join(' · ');
}
let discountCategoryFilter = 'all';

function discountFilterCodes(codes) {
  if (discountCategoryFilter === 'all') return codes;
  if (discountCategoryFilter === '__none__') {
    return codes.filter(c => !c.category_id);
  }
  const id = Number(discountCategoryFilter);
  return codes.filter(c => Number(c.category_id) === id);
}

function discountManageBar(categories) {
  const opts = [
    `<option value="all">همه دسته‌بندی‌ها</option>`,
    `<option value="__none__">بدون دسته‌بندی</option>`,
    ...categories.map(c => `<option value="${c.id}">${esc(c.name || c.title || `دسته #${c.id}`)}</option>`),
  ].join('');
  return `
    <div class="toolbar" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
      <select class="input" id="discount-filter" style="min-width:190px">${opts}</select>
      <button class="btn btn-danger btn-sm" id="discount-delete-category">حذف کدهای این دسته</button>
      <button class="btn btn-danger btn-sm" id="discount-delete-all">حذف همه کدها</button>
    </div>`;
}

function bindDiscountManageBar(categories) {
  const select = $('#discount-filter', content());
  if (!select) return;
  select.value = discountCategoryFilter;
  select.addEventListener('change', () => {
    discountCategoryFilter = select.value;
    renderDiscounts();
  });

  $('#discount-delete-all', content()).addEventListener('click', async () => {
    if (!confirm('همه کدهای تخفیف حذف شوند؟ این عملیات قابل بازگشت نیست.')) return;
    try {
      const res = await apiPost('/discounts/delete-all');
      toast(`${fmt(res.deleted)} کد حذف شد.`);
      discountCategoryFilter = 'all';
      renderDiscounts();
    } catch (e) { handleErr(e); }
  });

  $('#discount-delete-category', content()).addEventListener('click', async () => {
    if (discountCategoryFilter === 'all') return toast('اول یک دسته‌بندی را انتخاب کن.', true);
    const categoryId = discountCategoryFilter === '__none__' ? null : Number(discountCategoryFilter);
    if (!confirm('کدهای تخفیف این دسته حذف شوند؟ این عملیات قابل بازگشت نیست.')) return;
    try {
      const res = await apiPost('/discounts/delete-category', { category_id: categoryId });
      toast(`${fmt(res.deleted)} کد حذف شد.`);
      renderDiscounts();
    } catch (e) { handleErr(e); }
  });
}

async function renderDiscounts() {
  const [allCodes, categories, products] = await Promise.all([
    apiGet('/discounts'), apiGet('/categories'), apiGet('/products'),
  ]);
  const codes = discountFilterCodes(allCodes);
  if (loadTheme().theme === 'brutalist') return renderDiscountsBrutalist(codes, categories, products);
  if (loadTheme().theme === 'bento') return renderDiscountsBento(codes, categories, products);
  setContent(`
    ${discountManageBar(categories)}
    <div class="toolbar"><button class="btn btn-primary btn-sm" id="add-code">+ کد تخفیف جدید</button></div>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>کد</th><th>تخفیف</th><th>محدودیت‌ها</th><th>سقف استفاده</th><th>مصرف‌شده</th><th>وضعیت</th><th>عملیات</th></tr></thead>
      <tbody>${codes.map(c => `<tr>
        <td class="mono">${esc(c.code)}</td>
        <td>${c.percent ? c.percent + '%' : fmt(c.fixed_amount) + ' تومان'}</td>
        <td style="font-size:12px;color:var(--muted,#888)">${discountConstraintsLine(c, categories, products) || '—'}</td>
        <td class="mono">${c.max_uses ? fmt(c.max_uses) : 'نامحدود'}</td>
        <td class="mono">${fmt(c.used_count)}</td>
        <td>${c.is_active ? '<span class="badge badge-approved">فعال</span>' : '<span class="badge badge-rejected">غیرفعال</span>'}</td>
        <td><button class="btn btn-sm" data-toggle="${c.id}">${c.is_active ? 'غیرفعال' : 'فعال'}</button>
        <button class="btn btn-danger btn-sm" data-del="${c.id}">حذف</button></td>
      </tr>`).join('') || '<tr><td colspan="7" class="empty-state">کدی ثبت نشده</td></tr>'}</tbody>
    </table></div></div>
  `);
  bindDiscountManageBar(categories);
  $('#add-code').addEventListener('click', () => openModal('کد تخفیف جدید', `
    <div class="form-grid">
      <input class="input" id="code-value" placeholder="کد (مثلا SUMMER20)">
      <div class="form-row">
        <input class="input" id="code-percent" type="number" placeholder="درصد تخفیف">
        <input class="input" id="code-fixed" type="number" placeholder="یا مبلغ ثابت">
      </div>
      <input class="input" id="code-maxuses" type="number" placeholder="سقف تعداد استفاده (۰=نامحدود)" value="0">
      ${discountExtraFieldsHtml(categories, products)}
      <button class="btn btn-primary" id="code-save">ثبت</button>
    </div>`, (b, close) => {
    discountExtraFieldsBindScope(b);
    $('#code-save', b).addEventListener('click', async () => {
      const code = $('#code-value', b).value.trim();
      if (!code) return toast('کد را وارد کن.', true);
      try {
        await apiPost('/discounts', {
          code,
          percent: Number($('#code-percent', b).value) || null,
          fixed_amount: Number($('#code-fixed', b).value) || null,
          max_uses: Number($('#code-maxuses', b).value) || 0,
          ...discountExtraFieldsPayload(b),
        });
        toast('کد اضافه شد.'); close(); renderDiscounts();
      } catch (e) { handleErr(e); }
    });
  }));
  $$('[data-toggle]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/discounts/${b.dataset.toggle}/toggle`); renderDiscounts(); } catch (e) { handleErr(e); }
  }));
  $$('[data-del]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('حذف شود؟')) return;
    try { await apiDelete(`/discounts/${b.dataset.del}`); toast('حذف شد.'); renderDiscounts(); } catch (e) { handleErr(e); }
  }));
}

/* ------------------------------------------------------ discounts: bento */
function renderDiscountsBento(codes, categories, products) {
  setContent(`
    <div class="bn-hero">
      <div><h2>کدهای تخفیف</h2><p>${fmt(codes.length)} کد ثبت‌شده</p></div>
      <button class="bn-btn bn-btn-ok" id="add-code">+ کد جدید</button>
    </div>
    ${discountManageBar(categories)}
    <div class="bn-card-grid">
      ${codes.map((c, i) => `
        <div class="bn-card bn-card-anim" style="animation-delay:${Math.min(i * 30, 260)}ms">
          <div class="bw ${BN_ACCENTS[i % BN_ACCENTS.length]}" style="border-radius:16px;padding:12px 14px">
            <span class="bw-value mono" style="font-size:20px">${c.percent ? c.percent + '%' : fmt(c.fixed_amount) + ' ت'}</span>
          </div>
          <div class="bn-row-title mono" style="font-size:14px">${esc(c.code)}</div>
          <div class="bn-row-sub">سقف: ${c.max_uses ? fmt(c.max_uses) : 'نامحدود'} · مصرف: ${fmt(c.used_count)}</div>
          ${discountConstraintsLine(c, categories, products) ? `<div class="bn-row-sub" style="font-size:11px">${discountConstraintsLine(c, categories, products)}</div>` : ''}
          ${bnPill(c.is_active ? 'فعال' : 'غیرفعال', c.is_active ? 'ok' : 'no')}
          <div style="display:flex;gap:8px;margin-top:6px">
            <button class="bn-btn bn-btn-ghost" data-toggle="${c.id}">${c.is_active ? 'غیرفعال' : 'فعال'}</button>
            <button class="bn-btn bn-btn-no" data-del="${c.id}">حذف</button>
          </div>
        </div>
      `).join('') || `<div class="empty-state" style="grid-column:1/-1"><div class="icon">${svg('empty')}</div>کدی ثبت نشده</div>`}
    </div>
  `);
  bindDiscountManageBar(categories);
  $('#add-code').addEventListener('click', () => openModal('کد تخفیف جدید', `
    <div class="form-grid">
      <input class="input" id="code-value" placeholder="کد (مثلا SUMMER20)">
      <div class="form-row">
        <input class="input" id="code-percent" type="number" placeholder="درصد تخفیف">
        <input class="input" id="code-fixed" type="number" placeholder="یا مبلغ ثابت">
      </div>
      <input class="input" id="code-maxuses" type="number" placeholder="سقف تعداد استفاده (۰=نامحدود)" value="0">
      ${discountExtraFieldsHtml(categories, products)}
      <button class="btn btn-primary" id="code-save">ثبت</button>
    </div>`, (b, close) => {
    discountExtraFieldsBindScope(b);
    $('#code-save', b).addEventListener('click', async () => {
      const code = $('#code-value', b).value.trim();
      if (!code) return toast('کد را وارد کن.', true);
      try {
        await apiPost('/discounts', {
          code,
          percent: Number($('#code-percent', b).value) || null,
          fixed_amount: Number($('#code-fixed', b).value) || null,
          max_uses: Number($('#code-maxuses', b).value) || 0,
          ...discountExtraFieldsPayload(b),
        });
        toast('کد اضافه شد.'); close(); renderDiscounts();
      } catch (e) { handleErr(e); }
    });
  }));
  $$('[data-toggle]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/discounts/${b.dataset.toggle}/toggle`); renderDiscounts(); } catch (e) { handleErr(e); }
  }));
  $$('[data-del]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('حذف شود؟')) return;
    try { await apiDelete(`/discounts/${b.dataset.del}`); toast('حذف شد.'); renderDiscounts(); } catch (e) { handleErr(e); }
  }));
}


/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

/* ------------------------------------------------ discounts: brutalist -- */
// کدهای تخفیف به‌شکل «بلیط پانچ‌شده» (کوپن) با خط بریدگی دایره‌ای وسط —
// عدد تخفیف با فونت درشت مثل تگ قیمت.
function renderDiscountsBrutalist(codes, categories, products) {
  setContent(`
    <div class="bru-hero" style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
      <div>
        <h2>کدهای تخفیف</h2>
        <p>${fmt(codes.length)} کد ثبت‌شده</p>
      </div>
      <button class="bru-stamp bru-stamp-ok" id="add-code" style="--r:-3deg">+ کد جدید</button>
    </div>

    ${discountManageBar(categories)}
    <div class="bru-coupon-grid">
      ${codes.map((c, i) => `
        <div class="bru-coupon bru-card-anim ${c.is_active ? '' : 'bru-coupon-off'}" style="animation-delay:${Math.min(i * 40, 320)}ms">
          <div class="bru-coupon-value">${c.percent ? c.percent + '%' : fmt(c.fixed_amount) + ' ت'}</div>
          <div class="bru-coupon-cut"></div>
          <div class="bru-coupon-body">
            <div class="bru-coupon-code mono">${esc(c.code)}</div>
            <div class="bru-coupon-row"><span>سقف مصرف</span><b class="mono">${c.max_uses ? fmt(c.max_uses) : 'نامحدود'}</b></div>
            <div class="bru-coupon-row"><span>مصرف‌شده</span><b class="mono">${fmt(c.used_count)}</b></div>
            ${discountConstraintsLine(c, categories, products) ? `<div class="bru-coupon-row" style="font-size:11px"><span>محدودیت</span><b>${discountConstraintsLine(c, categories, products)}</b></div>` : ''}
            <span class="bru-flag ${c.is_active ? 'bru-flag-ok' : 'bru-flag-no'}" style="align-self:flex-start">${c.is_active ? 'فعال' : 'غیرفعال'}</span>
          </div>
          <div class="bru-coupon-actions">
            <button class="btn btn-sm" data-toggle="${c.id}">${c.is_active ? 'غیرفعال' : 'فعال'}</button>
            <button class="btn btn-danger btn-sm" data-del="${c.id}">حذف</button>
          </div>
        </div>
      `).join('') || `<div class="empty-state" style="grid-column:1/-1"><div class="icon">${svg('empty')}</div>کدی ثبت نشده</div>`}
    </div>
  `);
  bindDiscountManageBar(categories);
  $('#add-code').addEventListener('click', () => openModal('کد تخفیف جدید', `
    <div class="form-grid">
      <input class="input" id="code-value" placeholder="کد (مثلا SUMMER20)">
      <div class="form-row">
        <input class="input" id="code-percent" type="number" placeholder="درصد تخفیف">
        <input class="input" id="code-fixed" type="number" placeholder="یا مبلغ ثابت">
      </div>
      <input class="input" id="code-maxuses" type="number" placeholder="سقف تعداد استفاده (۰=نامحدود)" value="0">
      ${discountExtraFieldsHtml(categories, products)}
      <button class="btn btn-primary" id="code-save">ثبت</button>
    </div>`, (b, close) => {
    discountExtraFieldsBindScope(b);
    $('#code-save', b).addEventListener('click', async () => {
      const code = $('#code-value', b).value.trim();
      if (!code) return toast('کد را وارد کن.', true);
      try {
        await apiPost('/discounts', {
          code,
          percent: Number($('#code-percent', b).value) || null,
          fixed_amount: Number($('#code-fixed', b).value) || null,
          max_uses: Number($('#code-maxuses', b).value) || 0,
          ...discountExtraFieldsPayload(b),
        });
        toast('کد اضافه شد.'); close(); renderDiscounts();
      } catch (e) { handleErr(e); }
    });
  }));
  $$('[data-toggle]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/discounts/${b.dataset.toggle}/toggle`); renderDiscounts(); } catch (e) { handleErr(e); }
  }));
  $$('[data-del]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('حذف شود؟')) return;
    try { await apiDelete(`/discounts/${b.dataset.del}`); toast('حذف شد.'); renderDiscounts(); } catch (e) { handleErr(e); }
  }));
}

/* ============================================================= support === */
async function renderSupport() {
  stopSupportPoll();
  const convs = await apiGet('/support/conversations');
  if (loadTheme().theme === 'brutalist') return renderSupportBrutalist(convs);
  if (loadTheme().theme === 'bento') return renderSupportBento(convs);
  setContent(`
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>کاربر</th><th>آخرین پیام</th><th>زمان</th><th></th></tr></thead>
      <tbody>${convs.map(c => `<tr>
        <td>${esc(c.user_name || c.user_username || ('#' + c.user_id))}${c.unread ? ` <span class="badge badge-pending">${c.unread}</span>` : ''}${c.locked_for_me ? ` <span class="badge badge-rejected" title="${esc(c.locked_by || '')}">🔒</span>` : ''}</td>
        <td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${c.last_sender === 'admin' ? '↩ ' : ''}${esc(c.last_message || '')}</td>
        <td class="mono">${fmtDate(c.last_at)}</td>
        <td><button class="btn btn-sm" data-open="${c.user_id}">مشاهده</button></td>
      </tr>`).join('') || '<tr><td colspan="4" class="empty-state">گفتگویی نیست</td></tr>'}</tbody>
    </table></div></div>
  `);
  $$('[data-open]', content()).forEach(b => b.addEventListener('click', () => showSupportChat(Number(b.dataset.open))));
  SUPPORT_POLL_TIMER = setInterval(async () => {
    if (CURRENT_TAB !== 'support') return stopSupportPoll();
    try { const fresh = await apiGet('/support/conversations'); renderSupportRows(fresh); } catch (e) { /* silent */ }
  }, 5000);
}

function renderSupportRows(convs) {
  const tbody = $('table tbody', content());
  if (!tbody) return;
  tbody.innerHTML = convs.map(c => `<tr>
    <td>${esc(c.user_name || c.user_username || ('#' + c.user_id))}${c.unread ? ` <span class="badge badge-pending">${c.unread}</span>` : ''}${c.locked_for_me ? ` <span class="badge badge-rejected" title="${esc(c.locked_by || '')}">🔒</span>` : ''}</td>
    <td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${c.last_sender === 'admin' ? '↩ ' : ''}${esc(c.last_message || '')}</td>
    <td class="mono">${fmtDate(c.last_at)}</td>
    <td><button class="btn btn-sm" data-open="${c.user_id}">مشاهده</button></td>
  </tr>`).join('') || '<tr><td colspan="4" class="empty-state">گفتگویی نیست</td></tr>';
  $$('[data-open]', tbody).forEach(b => b.addEventListener('click', () => showSupportChat(Number(b.dataset.open))));
}

/* ---------------------------------------------------------- support: bento */
function renderSupportBento(convs) {
  setContent(`
    <div class="bn-hero"><div><h2>صندوق پشتیبانی</h2><p>${fmt(convs.length)} گفتگو</p></div></div>
    <div class="bn-list" id="support-inbox-list">${supportInboxRowsHtmlBento(convs)}</div>
  `);
  $$('[data-open]', content()).forEach(b => b.addEventListener('click', () => showSupportChat(Number(b.dataset.open))));
  SUPPORT_POLL_TIMER = setInterval(async () => {
    if (CURRENT_TAB !== 'support') return stopSupportPoll();
    try { const fresh = await apiGet('/support/conversations'); renderSupportRowsBento(fresh); } catch (e) { /* silent */ }
  }, 5000);
}


/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- ‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍*/

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */
function supportInboxRowsHtmlBento(convs) {
  return convs.map((c, i) => `
    <div class="bn-row bn-card-anim" style="animation-delay:${Math.min(i * 25, 220)}ms">
      ${bnAvatar((c.user_name || c.user_username || '؟').trim().charAt(0), i)}
      <div class="bn-row-main">
        <span class="bn-row-title">${esc(c.user_name || c.user_username || ('#' + c.user_id))}${c.locked_for_me ? ' 🔒' : ''}</span>
        <span class="bn-row-sub">${c.last_sender === 'admin' ? '↩ ' : ''}${esc(c.last_message || '')}</span>
      </div>
      <div class="bn-row-trail">
        ${c.unread ? bnPill(c.unread, 'no') : ''}
        <span class="bn-row-sub mono">${fmtDate(c.last_at)}</span>
        <button class="bn-btn bn-btn-ghost" data-open="${c.user_id}">مشاهده</button>
      </div>
    </div>
  `).join('') || `<div class="empty-state"><div class="icon">${svg('empty')}</div>گفتگویی نیست</div>`;
}


/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */
function renderSupportRowsBento(convs) {
  const list = $('#support-inbox-list', content());
  if (!list) return;
  list.innerHTML = supportInboxRowsHtmlBento(convs);
  $$('[data-open]', list).forEach(b => b.addEventListener('click', () => showSupportChat(Number(b.dataset.open))));
}


/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

/* -------------------------------------------------- support: brutalist -- */
// اینباکس گفتگوها به‌شکل ردیف‌های ضخیم با آواتار حرفی و نشان تعداد
// نخوانده مثل مهر گرد قرمز روی گوشه.
function renderSupportBrutalist(convs) {
  setContent(`
    <div class="bru-hero">
      <h2>صندوق پشتیبانی</h2>
      <p>${fmt(convs.length)} گفتگو</p>
    </div>
    <div class="bru-inbox-list" id="support-inbox-list">${supportInboxRowsHtml(convs)}</div>
  `);
  $$('[data-open]', content()).forEach(b => b.addEventListener('click', () => showSupportChat(Number(b.dataset.open))));
  SUPPORT_POLL_TIMER = setInterval(async () => {
    if (CURRENT_TAB !== 'support') return stopSupportPoll();
    try { const fresh = await apiGet('/support/conversations'); renderSupportRowsBrutalist(fresh); } catch (e) { /* silent */ }
  }, 5000);
}
function supportInboxRowsHtml(convs) {
  return convs.map((c, i) => `
    <div class="bru-inbox-row bru-card-anim" style="animation-delay:${Math.min(i * 30, 240)}ms">
      <div class="bru-inbox-avatar mono">${esc((c.user_name || c.user_username || '#').trim().charAt(0).toUpperCase())}</div>
      <div class="bru-inbox-main">
        <div class="bru-inbox-name">${esc(c.user_name || c.user_username || ('#' + c.user_id))}${c.locked_for_me ? ` <span title="${esc(c.locked_by || '')}">🔒</span>` : ''}</div>
        <div class="bru-inbox-msg">${c.last_sender === 'admin' ? '↩ ' : ''}${esc(c.last_message || '')}</div>
      </div>
      <div class="bru-inbox-meta">
        <span class="mono">${fmtDate(c.last_at)}</span>
        ${c.unread ? `<span class="bru-inbox-badge">${c.unread}</span>` : ''}
      </div>
      <button class="btn btn-sm" data-open="${c.user_id}">مشاهده</button>
    </div>
  `).join('') || `<div class="empty-state"><div class="icon">${svg('empty')}</div>گفتگویی نیست</div>`;
}
function renderSupportRowsBrutalist(convs) {
  const list = $('#support-inbox-list', content());
  if (!list) return;
  list.innerHTML = supportInboxRowsHtml(convs);
  $$('[data-open]', list).forEach(b => b.addEventListener('click', () => showSupportChat(Number(b.dataset.open))));
}

async function showSupportChat(userId) {
  let lastId = 0;
  let d;
  try {
    d = await apiGet(`/support/${userId}/messages`);
  } catch (e) {
    handleErr(e);
    return;
  }
  lastId = d.messages.length ? d.messages[d.messages.length - 1].id : 0;
  const title = d.user.user_name || d.user.user_username || `#${userId}`;
  const locked = d.user.locked_for_me;
  let pollTimer = null;
  const bubble = m => `<div style="align-self:${m.sender === 'admin' ? 'flex-end' : 'flex-start'};max-width:80%;background:${m.sender === 'admin' ? 'var(--signal-dim)' : 'var(--panel-2)'};padding:8px 12px;border-radius:9px;font-size:13px">
        ${esc(m.message)}<div class="card-sub" style="font-size:10px;margin-top:3px">${fmtDate(m.created_at)}</div>
      </div>`;
  const modal = openModal(`چت با ${esc(title)}`, `
    <div id="sc-log" style="display:flex;flex-direction:column;gap:8px;max-height:320px;overflow-y:auto;margin-bottom:12px">
      ${d.messages.map(bubble).join('') || '<span class="card-sub">پیامی نیست</span>'}
    </div>
    ${locked ? `<div class="card-sub" style="color:var(--danger,#ff6b52);margin-bottom:8px">🔒 این گفتگو در حال حاضر توسط ${esc(d.user.locked_by || 'ادمین دیگری')} پاسخ داده می‌شود.</div>` : ''}
    <div style="display:flex;gap:8px">
      <input class="input" id="sc-input" placeholder="پاسخ..." style="flex:1" ${locked ? 'disabled' : ''}>
      <button class="btn btn-primary" id="sc-send" ${locked ? 'disabled' : ''}>ارسال</button>
    </div>
  `, (body, close) => {
    const log = $('#sc-log', body);
    const input = $('#sc-input', body);
    log.scrollTop = log.scrollHeight;
    const send = async () => {
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      try {
        await apiPost(`/support/${userId}/messages`, { message: text });
        log.insertAdjacentHTML('beforeend', bubble({ sender: 'admin', message: text, created_at: new Date().toISOString() }));
        log.scrollTop = log.scrollHeight;
      } catch (e) { handleErr(e); }
    };
    $('#sc-send', body).addEventListener('click', send);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });

    pollTimer = setInterval(async () => {
      try {
        const fresh = await apiGet(`/support/${userId}/messages?since_id=${lastId}`);
        fresh.messages.forEach(m => {
          log.insertAdjacentHTML('beforeend', bubble(m));
          lastId = m.id;
        });
        if (fresh.messages.length) log.scrollTop = log.scrollHeight;
      } catch (e) { /* silent */ }
    }, 4000);
  });
  modal.addEventListener('click', e => { if (e.target === modal) { clearInterval(pollTimer); renderSupport(); } });
}

/* ============================================================= tickets === */
let ticketsStatusFilter = '';
const TICKETS_STATUS_LABEL = { '': 'همه', open: 'باز', answered: 'پاسخ‌داده‌شده', closed: 'بسته' };
async function renderTickets() {
  const tickets = await apiGet(`/tickets${ticketsStatusFilter ? '?status=' + ticketsStatusFilter : ''}`);
  if (loadTheme().theme === 'brutalist') return renderTicketsBrutalist(tickets);
  if (loadTheme().theme === 'bento') return renderTicketsBento(tickets);
  setContent(`
    <div class="tabs">
      ${[['', 'همه'], ['open', 'باز'], ['answered', 'پاسخ‌داده‌شده'], ['closed', 'بسته']].map(([v, l]) => `<button class="tab-btn ${v === ticketsStatusFilter ? 'active' : ''}" data-s="${v}">${l}</button>`).join('')}
    </div>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>#</th><th>کاربر</th><th>موضوع</th><th>وضعیت</th><th>آخرین بروزرسانی</th><th></th></tr></thead>
      <tbody>${tickets.map(t => `<tr>
        <td class="mono">#${t.id}</td><td>${esc(t.username || t.user_id)}</td><td>${esc(t.subject)}</td>
        <td>${{ open: '<span class="badge badge-pending">باز</span>', answered: '<span class="badge badge-approved">پاسخ‌داده‌شده</span>', closed: '<span class="badge badge-rejected">بسته</span>' }[t.status] || t.status}</td>
        <td class="mono">${fmtDate(t.updated_at)}</td>
        <td><button class="btn btn-sm" data-open="${t.id}">مشاهده</button></td>
      </tr>`).join('') || '<tr><td colspan="6" class="empty-state">تیکتی نیست</td></tr>'}</tbody>
    </table></div></div>
  `);
  $$('.tab-btn', content()).forEach(b => b.addEventListener('click', () => { ticketsStatusFilter = b.dataset.s; renderTickets(); }));
  $$('[data-open]', content()).forEach(b => b.addEventListener('click', () => showTicket(Number(b.dataset.open))));
}

/* ---------------------------------------------------------- tickets: bento */
function renderTicketsBento(tickets) {
  setContent(`
    <div class="bn-hero">
      <div><h2>تیکت‌های پشتیبانی</h2><p>${fmt(tickets.length)} تیکت در فیلتر «${TICKETS_STATUS_LABEL[ticketsStatusFilter]}»</p></div>
      <div class="bn-seg">${[['', 'همه'], ['open', 'باز'], ['answered', 'پاسخ‌داده‌شده'], ['closed', 'بسته']].map(([v, l]) => `<button class="bn-seg-btn ${v === ticketsStatusFilter ? 'active' : ''}" data-s="${v}">${l}</button>`).join('')}</div>
    </div>
    <div class="bn-list">
      ${tickets.map((t, i) => `
        <div class="bn-row bn-card-anim" style="animation-delay:${Math.min(i * 25, 220)}ms">
          ${bnAvatar((t.username || '؟').trim().charAt(0), i)}
          <div class="bn-row-main">
            <span class="bn-row-title">${esc(t.subject)}</span>
            <span class="bn-row-sub">${esc(t.username || t.user_id)} · ${fmtDate(t.updated_at)}</span>
          </div>
          <div class="bn-row-trail">
            ${bnPill(TICKETS_STATUS_LABEL[t.status] || t.status, t.status === 'open' ? 'pending' : t.status === 'answered' ? 'ok' : 'no')}
            <button class="bn-btn bn-btn-ghost" data-open="${t.id}">مشاهده</button>
          </div>
        </div>
      `).join('') || `<div class="empty-state"><div class="icon">${svg('empty')}</div>تیکتی نیست</div>`}
    </div>
  `);
  $$('.bn-seg-btn[data-s]', content()).forEach(b => b.addEventListener('click', () => { ticketsStatusFilter = b.dataset.s; renderTickets(); }));
  $$('[data-open]', content()).forEach(b => b.addEventListener('click', () => showTicket(Number(b.dataset.open))));
}


/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

/* -------------------------------------------------- tickets: brutalist -- */
// هر تیکت به‌شکل کارت «پرونده‌ی باز» با برچسب وضعیت مثل استیکر گوشه.
function renderTicketsBrutalist(tickets) {
  setContent(`
    <div class="bru-hero" style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
      <div>
        <h2>تیکت‌های پشتیبانی</h2>
        <p>${fmt(tickets.length)} تیکت در فیلتر «${TICKETS_STATUS_LABEL[ticketsStatusFilter]}»</p>
      </div>
      <div class="bru-seg" role="tablist">
        ${[['', 'همه'], ['open', 'باز'], ['answered', 'پاسخ‌داده‌شده'], ['closed', 'بسته']].map(([v, l]) => `<button class="bru-seg-btn ${v === ticketsStatusFilter ? 'active' : ''}" data-s="${v}">${l}</button>`).join('')}
      </div>
    </div>
    <div class="bru-ticket-grid">
      ${tickets.map((t, i) => `
        <div class="bru-ticket bru-card-anim" style="animation-delay:${Math.min(i * 40, 320)}ms">
          <div class="bru-ticket-stub">
            <span class="bru-ticket-num mono">#${t.id}</span>
            <span class="bru-flag ${t.status === 'open' ? 'bru-flag-pending' : t.status === 'answered' ? 'bru-flag-ok' : 'bru-flag-no'}">${TICKETS_STATUS_LABEL[t.status] || t.status}</span>
          </div>
          <div class="bru-ticket-body">
            <div class="bru-ticket-row"><span>کاربر</span><b>${esc(t.username || t.user_id)}</b></div>
            <div class="bru-ticket-row" style="flex-direction:column;align-items:flex-start;gap:2px"><span>موضوع</span><b style="white-space:normal">${esc(t.subject)}</b></div>
            <div class="bru-ticket-row"><span>بروزرسانی</span><b class="mono">${fmtDate(t.updated_at)}</b></div>
          </div>
          <div class="bru-ticket-actions">
            <button class="btn btn-sm" data-open="${t.id}">مشاهده</button>
          </div>
        </div>
      `).join('') || `<div class="empty-state" style="grid-column:1/-1"><div class="icon">${svg('empty')}</div>تیکتی نیست</div>`}
    </div>
  `);
  $$('.bru-seg-btn[data-s]', content()).forEach(b => b.addEventListener('click', () => { ticketsStatusFilter = b.dataset.s; renderTickets(); }));
  $$('[data-open]', content()).forEach(b => b.addEventListener('click', () => showTicket(Number(b.dataset.open))));
}

async function showTicket(ticketId) {
  const d = await apiGet(`/tickets/${ticketId}/messages`);
  const canAct = hasPerm('tickets');
  openModal(`تیکت: ${esc(d.ticket.subject)}`, `
    <div style="display:flex;flex-direction:column;gap:8px;max-height:280px;overflow-y:auto;margin-bottom:12px">
      ${d.messages.map(m => `<div style="background:${m.sender === 'admin' ? 'var(--signal-dim)' : 'var(--panel-2)'};padding:8px 12px;border-radius:9px;font-size:13px">
        <strong style="font-size:11px;color:var(--text-muted)">${m.sender === 'admin' ? 'ادمین' : 'کاربر'}</strong><br>${esc(m.message)}
      </div>`).join('') || '<span class="card-sub">پیامی نیست</span>'}
    </div>
    ${canAct && d.ticket.status !== 'closed' ? `
      <textarea class="input" id="ticket-reply" rows="2" placeholder="پاسخ..."></textarea>
      <div class="modal-actions">
        <button class="btn btn-primary" id="ticket-send">ارسال پاسخ</button>
        <button class="btn btn-danger" id="ticket-close-btn">بستن تیکت</button>
      </div>` : ''}
  `, (body, close) => {
    const send = $('#ticket-send', body);
    if (send) send.addEventListener('click', async () => {
      const message = $('#ticket-reply', body).value.trim();
      if (!message) return;
      try { await apiPost(`/tickets/${ticketId}/reply`, { message }); toast('پاسخ ارسال شد.'); close(); renderTickets(); } catch (e) { handleErr(e); }
    });
    const closeBtn = $('#ticket-close-btn', body);
    if (closeBtn) closeBtn.addEventListener('click', async () => {
      try { await apiPost(`/tickets/${ticketId}/close`); toast('تیکت بسته شد.'); close(); renderTickets(); } catch (e) { handleErr(e); }
    });
  });
}

/* =========================================================== broadcast === */
/* ------------------------------------------------------ broadcast: bento */
function renderBroadcastBento() {
  setContent(`
    <div class="bn-hero"><div><h2>پیام همگانی</h2><p>ارسال متنی به همه‌ی کاربران غیرمسدود ربات</p></div></div>
    <div class="bn-card" style="max-width:680px">
      <textarea class="bn-search" id="bc-text" rows="7" maxlength="4000" style="width:100%;border-radius:18px;resize:vertical" placeholder="متن پیام را بنویس..."></textarea>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px">
        <select class="input" id="bc-media-type">
          <option value="">فقط متن</option>
          <option value="photo">عکس</option>
          <option value="voice">ویس</option>
        </select>
        <input class="input" id="bc-file" type="file" style="flex:1;min-width:220px" accept="image/*,audio/*">
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px">
        <span class="mono" id="bc-count" style="font-size:12px;color:var(--text-muted)">۰ / ۴۰۰۰</span>
        <button class="bn-btn bn-btn-ok" id="bc-send" style="padding:10px 22px">ارسال به همه</button>
      </div>
      <div id="bc-result" style="margin-top:16px"></div>
    </div>
  `);
  const ta = $('#bc-text', content());
  ta.addEventListener('input', () => { $('#bc-count', content()).textContent = `${ta.value.length} / 4000`; });

  $('#bc-send', content()).addEventListener('click', () => {
    const text = ta.value.trim();
    const mediaType = $('#bc-media-type', content()).value;
    const file = $('#bc-file', content()).files[0];
    if (!text && !file) return toast('متن یا فایل پیام خالی است.', true);
    if (file && !mediaType) return toast('نوع فایل را انتخاب کن.', true);
    if (mediaType === 'photo' && file && !file.type.startsWith('image/')) return toast('فایل انتخاب‌شده عکس نیست.', true);
    if (mediaType === 'voice' && file && !file.type.startsWith('audio/')) return toast('فایل انتخاب‌شده ویس/صوتی نیست.', true);
    openModal('تایید ارسال همگانی', `
      <p style="font-size:13px;line-height:1.9">این پیام برای <strong>همه‌ی کاربران</strong> ربات ارسال می‌شود و قابل بازگشت نیست. مطمئنی؟</p>
      <div style="border-radius:14px;background:var(--surface-2);padding:10px 12px;font-size:13px;white-space:pre-wrap;max-height:160px;overflow-y:auto">${esc(text)}</div>
      <div class="modal-actions">
        <button class="btn btn-primary" id="bc-confirm">بله، ارسال کن</button>
      </div>
    `, (body, close) => {
      $('#bc-confirm', body).addEventListener('click', async () => {
        const btn = $('#bc-confirm', body);
        btn.disabled = true; btn.textContent = 'در حال ارسال...';
        try {
          const form = new FormData();
          form.append('message', text);
          if (file) {
            form.append('media_type', mediaType);
            form.append('file', file);
          }
          const res = await apiMultipart('/broadcast', form);
          close();
          $('#bc-result', content()).innerHTML = `
            <div class="bento-grid" style="grid-auto-rows:minmax(84px,auto)">
              <div class="bw w-blue"><span class="bw-label">کل</span><span class="bw-value mono">${fmt(res.total)}</span></div>
              <div class="bw w-green"><span class="bw-label">موفق</span><span class="bw-value mono">${fmt(res.success)}</span></div>
              <div class="bw w-pink"><span class="bw-label">ناموفق</span><span class="bw-value mono">${fmt(res.failed)}</span></div>
            </div>`;
          ta.value = '';
          $('#bc-media-type', content()).value = '';
          $('#bc-file', content()).value = '';
          $('#bc-count', content()).textContent = '۰ / ۴۰۰۰';
          toast('پیام همگانی ارسال شد.');
        } catch (e) { close(); handleErr(e); }
      });
    });
  });
}


/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

async function renderBroadcast() {
  if (loadTheme().theme === 'brutalist') return renderBroadcastBrutalist();
  if (loadTheme().theme === 'bento') return renderBroadcastBento();
  setContent(`
    <div class="card" style="max-width:640px">
      <h3 style="margin:0 0 4px">ارسال پیام همگانی</h3>
      <p class="card-sub" style="margin:0 0 14px">این پیام برای همه‌ی کاربران ربات (غیرمسدود) به‌صورت متنی ارسال می‌شود.</p>
      <textarea class="input" id="bc-text" rows="6" maxlength="4000" placeholder="متن پیام را بنویس..."></textarea>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px">
        <select class="input" id="bc-media-type">
          <option value="">فقط متن</option>
          <option value="photo">عکس</option>
          <option value="voice">ویس</option>
        </select>
        <input class="input" id="bc-file" type="file" style="flex:1;min-width:220px" accept="image/*,audio/*">
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px">
        <span class="card-sub" id="bc-count">۰ / ۴۰۰۰</span>
        <button class="btn btn-primary" id="bc-send">ارسال به همه</button>
      </div>
      <div id="bc-result" style="margin-top:14px"></div>
    </div>
  `);
  const ta = $('#bc-text', content());
  ta.addEventListener('input', () => { $('#bc-count', content()).textContent = `${ta.value.length} / 4000`; });

  $('#bc-send', content()).addEventListener('click', () => {
    const text = ta.value.trim();
    const mediaType = $('#bc-media-type', content()).value;
    const file = $('#bc-file', content()).files[0];
    if (!text && !file) return toast('متن یا فایل پیام خالی است.', true);
    if (file && !mediaType) return toast('نوع فایل را انتخاب کن.', true);
    if (mediaType === 'photo' && file && !file.type.startsWith('image/')) return toast('فایل انتخاب‌شده عکس نیست.', true);
    if (mediaType === 'voice' && file && !file.type.startsWith('audio/')) return toast('فایل انتخاب‌شده ویس/صوتی نیست.', true);
    openModal('تایید ارسال همگانی', `
      <p style="font-size:13px;line-height:1.9">این پیام برای <strong>همه‌ی کاربران</strong> ربات ارسال می‌شود و قابل بازگشت نیست. مطمئنی؟</p>
      <div style="background:var(--panel-2);padding:10px 12px;border-radius:9px;font-size:13px;white-space:pre-wrap;max-height:160px;overflow-y:auto">${esc(text)}</div>
      <div class="modal-actions">
        <button class="btn btn-primary" id="bc-confirm">بله، ارسال کن</button>
      </div>
    `, (body, close) => {
      $('#bc-confirm', body).addEventListener('click', async () => {
        const btn = $('#bc-confirm', body);
        btn.disabled = true; btn.textContent = 'در حال ارسال...';
        try {
          const form = new FormData();
          form.append('message', text);
          if (file) {
            form.append('media_type', mediaType);
            form.append('file', file);
          }
          const res = await apiMultipart('/broadcast', form);
          close();
          $('#bc-result', content()).innerHTML = `
            <div class="card" style="background:var(--panel-2)">
              📢 ارسال تمام شد — کل: <strong>${res.total}</strong> ·
              موفق: <strong style="color:var(--ok, #3ddc84)">${res.success}</strong> ·
              ناموفق: <strong style="color:var(--danger, #ff6b52)">${res.failed}</strong>
            </div>`;
          ta.value = '';
          $('#bc-media-type', content()).value = '';
          $('#bc-file', content()).value = '';
          $('#bc-count', content()).textContent = '۰ / ۴۰۰۰';
          toast('پیام همگانی ارسال شد.');
        } catch (e) { close(); handleErr(e); }
      });
    });
  });
}

/* ------------------------------------------------ broadcast: brutalist -- */
// چیدمان «کنسول بلندگو»: تکست‌ناحیه‌ی درشت با شمارنده‌ی مونو، دکمه‌ی
// مُهر بزرگ، و نتیجه‌ی ارسال به‌شکل سه بلاک آماری مثل داشبورد.
function renderBroadcastBrutalist() {
  setContent(`
    <div class="bru-hero">
      <h2>کنسول پیام همگانی</h2>
      <p>ارسال متنی به همه‌ی کاربران غیرمسدود ربات</p>
    </div>
    <div class="bru-panel" style="max-width:680px">
      <div class="bru-panel-head">متن پیام</div>
      <textarea class="bru-search-input" id="bc-text" rows="7" maxlength="4000" style="width:100%;resize:vertical" placeholder="متن پیام را بنویس..."></textarea>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px">
        <select class="input" id="bc-media-type">
          <option value="">فقط متن</option>
          <option value="photo">عکس</option>
          <option value="voice">ویس</option>
        </select>
        <input class="input" id="bc-file" type="file" style="flex:1;min-width:220px" accept="image/*,audio/*">
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px">
        <span class="mono" id="bc-count" style="font-weight:800;font-size:12px">۰ / ۴۰۰۰</span>
        <button class="bru-stamp bru-stamp-ok" id="bc-send" style="--r:-3deg">ارسال به همه</button>
      </div>
      <div id="bc-result" style="margin-top:16px"></div>
    </div>
  `);
  const ta = $('#bc-text', content());
  ta.addEventListener('input', () => { $('#bc-count', content()).textContent = `${ta.value.length} / 4000`; });

  $('#bc-send', content()).addEventListener('click', () => {
    const text = ta.value.trim();
    const mediaType = $('#bc-media-type', content()).value;
    const file = $('#bc-file', content()).files[0];
    if (!text && !file) return toast('متن یا فایل پیام خالی است.', true);
    if (file && !mediaType) return toast('نوع فایل را انتخاب کن.', true);
    if (mediaType === 'photo' && file && !file.type.startsWith('image/')) return toast('فایل انتخاب‌شده عکس نیست.', true);
    if (mediaType === 'voice' && file && !file.type.startsWith('audio/')) return toast('فایل انتخاب‌شده ویس/صوتی نیست.', true);
    openModal('تایید ارسال همگانی', `
      <p style="font-size:13px;line-height:1.9">این پیام برای <strong>همه‌ی کاربران</strong> ربات ارسال می‌شود و قابل بازگشت نیست. مطمئنی؟</p>
      <div style="border:2.5px solid #000;background:var(--surface-2);padding:10px 12px;font-size:13px;white-space:pre-wrap;max-height:160px;overflow-y:auto">${esc(text)}</div>
      <div class="modal-actions">
        <button class="btn btn-primary" id="bc-confirm">بله، ارسال کن</button>
      </div>
    `, (body, close) => {
      $('#bc-confirm', body).addEventListener('click', async () => {
        const btn = $('#bc-confirm', body);
        btn.disabled = true; btn.textContent = 'در حال ارسال...';
        try {
          const form = new FormData();
          form.append('message', text);
          if (file) {
            form.append('media_type', mediaType);
            form.append('file', file);
          }
          const res = await apiMultipart('/broadcast', form);
          close();
          $('#bc-result', content()).innerHTML = `
            <div class="bru-grid-4" style="grid-template-columns:repeat(3,1fr)">
              <div class="bru-block bru-white"><span class="bru-block-label">کل</span><span class="bru-block-val mono">${fmt(res.total)}</span></div>
              <div class="bru-block bru-yellow"><span class="bru-block-label">موفق</span><span class="bru-block-val mono">${fmt(res.success)}</span></div>
              <div class="bru-block bru-black"><span class="bru-block-label">ناموفق</span><span class="bru-block-val mono">${fmt(res.failed)}</span></div>
            </div>`;
          ta.value = '';
          $('#bc-media-type', content()).value = '';
          $('#bc-file', content()).value = '';
          $('#bc-count', content()).textContent = '۰ / ۴۰۰۰';
          toast('پیام همگانی ارسال شد.');
        } catch (e) { close(); handleErr(e); }
      });
    });
  });
}

/* =========================================================== resellers === */
let resellersSubTab = 'bots'; // 'bots' | 'credit' | 'requests'
let resellerReqFilter = 'open';

const RESELLERS_SUBTABS = [
  ['bots', 'نماینده‌های بات'],
  ['credit', 'نمایندگی اعتباری'],
  ['commission', 'نمایندگی کمیسیونی'],
  ['requests', 'درخواست‌های نمایندگی'],
];

const RESELLER_REQ_OPEN = new Set(['pending_review', 'awaiting_payment', 'awaiting_payment_review', 'awaiting_bot_info']);
const RESELLER_REQ_STATUS_LABEL = {
  pending_review: 'در انتظار بررسی', awaiting_payment: 'در انتظار پرداخت',
  awaiting_payment_review: 'در انتظار تایید رسید', awaiting_bot_info: 'در انتظار توکن بات',
  completed: 'تکمیل‌شده', rejected: 'ردشده', payment_rejected: 'پرداخت ردشده', cancelled: 'کنسل‌شده',
};
const RESELLER_REQ_STATUS_BADGE = {
  pending_review: 'badge-pending', awaiting_payment: 'badge-pending',
  awaiting_payment_review: 'badge-pending', awaiting_bot_info: 'badge-pending',
  completed: 'badge-approved', rejected: 'badge-rejected', payment_rejected: 'badge-rejected', cancelled: 'badge-rejected',
};

function resellersSubtabsHtml() {
  return `<div class="tabs">${RESELLERS_SUBTABS.map(([v, l]) =>
    `<button class="tab-btn ${v === resellersSubTab ? 'active' : ''}" data-sub="${v}">${l}</button>`).join('')}</div>`;
}
function bindResellersSubtabs(root) {
  $$('.tab-btn[data-sub]', root).forEach(b => b.addEventListener('click', () => {
    resellersSubTab = b.dataset.sub; renderResellers();
  }));
}

/* ================================================= sales settings === */
// تنظیمات فروش که قبلاً فقط از داخل ربات/مینی‌اپ قابل تغییر بود: رفرال،
// گردونه‌شانس، کریپتو، یادآوری تمدید/حجمی، کانفیگ تست، عضویت اجباری، هشدار موجودی.

function _swSpan(key, on) {
  return `<span class="switch" data-swkey="${key}" data-on="${on ? '1' : '0'}"><i></i></span>`;
}
function _bindSwitches(root) {
  $$('.switch[data-swkey]', root).forEach(sw => {
    sw.addEventListener('click', () => { sw.dataset.on = sw.dataset.on === '1' ? '0' : '1'; sw.classList.toggle('on'); });
    if (sw.dataset.on === '1') sw.classList.add('on');
  });
}
function _swOn(root, key) { return $(`.switch[data-swkey="${key}"]`, root)?.dataset.on === '1'; }
function _val(root, key) { return $(`[data-fkey="${key}"]`, root)?.value; }
function _num(root, key) { return Number(_val(root, key)) || 0; }

function _referralFraudFlagsRows(items) {
  if (!items || !items.length) return '<div class="card-sub">هشدار بازی وجود ندارد.</div>';
  return items.map(f => `
    <div class="row-item" data-flag-id="${f.id}" style="border:1px solid var(--border,#333);border-radius:8px;padding:8px;margin-bottom:8px">
      <div><b>${esc(f.username ? '@' + f.username : (f.first_name || ('کاربر ' + f.referrer_id)))}</b> (${f.referrer_id})</div>
      <div class="card-sub">${esc(f.reason)}</div>
      <div class="card-sub">دعوت‌ها: ${fmt(f.invited_total)} | بی‌خرید: ${fmt(f.zero_purchase_count)} | دعوت انبوه: ${fmt(f.burst_count)} | ${fmtDate(f.created_at)}</div>
      <button class="btn btn-sm" data-resolve-flag="${f.id}" style="margin-top:6px">✅ رفع شد (بررسی دستی انجام شد)</button>
    </div>
  `).join('');
}

async function renderSalesSettings() {
  const [referral, wheel, renewal, churn, volumeReminder, connectAlert, earlyRenewal, testConfig, testPlans, panelServers, forceJoin, stockAlert, products, referralFraud, fraudFlags] = await Promise.all([
    apiGet('/settings/referral'), apiGet('/settings/wheel'),
    apiGet('/settings/renewal'), apiGet('/settings/churn'), apiGet('/settings/volume-reminder'), apiGet('/settings/connect-alert'),
    apiGet('/settings/early-renewal-discount'), apiGet('/settings/test-config'),
    apiGet('/test-config/plans'), apiGet('/test-config/panel-servers-lite'),
    apiGet('/settings/force-join'), apiGet('/settings/stock-alert'), apiGet('/products'),
    apiGet('/settings/referral-fraud'), apiGet('/referral-fraud/flags?resolved=false'),
  ]);

  const eligibleProducts = (products || []).filter(p => p.is_auto_provision && p.provision_server_id);
  const productOptions = eligibleProducts.map(p =>
    `<option value="${p.id}" ${referral.free_config_product_id === p.id ? 'selected' : ''}>${esc(p.name)}${p.is_active ? '' : ' (غیرفعال)'}</option>`
  ).join('');

  setContent(`
    <div class="card">
      <h3>🔗 رفرال — سه مدل مستقل زیرمجموعه‌گیری</h3>

      <div class="card-sub" style="margin:8px 0 4px"><b>① پورسانت درصدی از خرید</b></div>
      <label class="field field-row"><span>فعال</span>${_swSpan('ref_enabled', referral.enabled)}</label>
      <label class="field"><span>درصد پورسانت</span><input class="input" data-fkey="ref_percent" type="number" value="${referral.percent}"></label>
      <label class="field"><span>سقف تعداد نفرات پورسانت‌دار (۰ = نامحدود)</span><input class="input" data-fkey="ref_commission_max" type="number" value="${referral.commission_max_count}"></label>

      <div class="card-sub" style="margin:16px 0 4px"><b>② کانفیگ رایگان با تعداد دعوت مشخص</b></div>
      <label class="field field-row"><span>فعال</span>${_swSpan('ref_fc_enabled', referral.free_config_enabled)}</label>
      <label class="field"><span>تعداد دعوت لازم</span><input class="input" data-fkey="ref_fc_threshold" type="number" value="${referral.free_config_threshold}"></label>
      <label class="field"><span>محصول جایزه</span>
        <select class="input" data-fkey="ref_fc_product">
          <option value="">— انتخاب کنید —</option>
          ${productOptions}
        </select>
      </label>
      <div class="card-sub">فقط محصولاتی که «تحویل خودکار» دارند و به یک پنل وصل‌اند نمایش داده می‌شوند؛ می‌توانید محصولی غیرفعال (که در فروشگاه نمایش داده نمی‌شود) مخصوص همین جایزه بسازید.</div>

      <div class="card-sub" style="margin:16px 0 4px"><b>③ شارژ ثابت کیف پول به‌ازای هر دعوت</b></div>
      <label class="field field-row"><span>فعال</span>${_swSpan('ref_ib_enabled', referral.invite_bonus_enabled)}</label>
      <label class="field"><span>مبلغ شارژ (تومان)</span><input class="input" data-fkey="ref_ib_amount" type="number" value="${referral.invite_bonus_amount}"></label>
      <label class="field"><span>سقف تعداد دعوت‌های مشمول (۰ = نامحدود)</span><input class="input" data-fkey="ref_ib_max" type="number" value="${referral.invite_bonus_max_count}"></label>

      <button class="btn btn-primary btn-sm" id="save-referral" style="margin-top:12px">ذخیره همه‌ی تنظیمات رفرال</button>
    </div>

    <div class="card">
      <h3>🎰 گردونه‌ی شانس</h3>
      <label class="field field-row"><span>فعال</span>${_swSpan('wheel_enabled', wheel.enabled)}</label>
      <label class="field"><span>درصد برد</span><input class="input" data-fkey="wheel_win_percent" type="number" value="${wheel.win_percent}"></label>
      <label class="field"><span>جوایز (٪ تخفیف، با کاما جدا کن)</span><input class="input" data-fkey="wheel_prizes" type="text" value="${(wheel.prizes || []).join(', ')}"></label>
      <label class="field"><span>اعتبار کد (ساعت)</span><input class="input" data-fkey="wheel_expiry_hours" type="number" value="${wheel.code_expiry_hours}"></label>
      <label class="field"><span>فاصله‌ی بین دو چرخش (ساعت)</span><input class="input" data-fkey="wheel_cooldown_hours" type="number" value="${wheel.cooldown_hours}"></label>
      <button class="btn btn-primary btn-sm" id="save-wheel">ذخیره</button>
    </div>

    <div class="card">
      <h3>⏳ یادآوری تمدید</h3>
      <label class="field field-row"><span>فعال</span>${_swSpan('renewal_enabled', renewal.enabled)}</label>
      <label class="field"><span>چند روز قبل از انقضا</span><input class="input" data-fkey="renewal_days_before" type="number" value="${renewal.days_before}"></label>
      <label class="field"><span>درصد تخفیف کد پیشنهادی</span><input class="input" data-fkey="renewal_discount_percent" type="number" value="${renewal.discount_percent}"></label>
      <label class="field"><span>اعتبار کد (ساعت)</span><input class="input" data-fkey="renewal_discount_expiry_hours" type="number" value="${renewal.discount_expiry_hours}"></label>
      <button class="btn btn-primary btn-sm" id="save-renewal">ذخیره</button>
    </div>

    <div class="card">
      <h3>🔮 پیش‌بینی ریزش و پیشنهاد تمدید شخصی</h3>
      <div class="card-sub" style="margin-bottom:8px">کاربرانی که از فاصله‌ی معمول خریدشان عقب افتاده‌اند و سرویس فعال ندارند شناسایی می‌شوند. با AI فعال، AI بر اساس سابقه‌ی خرید و مصرف، خطر ریزش را می‌سنجد و تصمیم می‌گیرد تخفیف لازم است یا نه و متن شخصی می‌نویسد. بدون AI، قواعد ثابت و تخفیف بالا استفاده می‌شود.</div>
      <label class="field field-row"><span>فعال</span>${_swSpan('churn_enabled', churn.enabled)}</label>
      <label class="field field-row"><span>تصمیم و متن پیشنهاد با AI</span>${_swSpan('churn_ai_enabled', churn.ai_enabled)}</label>
      <label class="field"><span>سقف تخفیف قابل پیشنهاد توسط AI (٪)</span><input class="input" data-fkey="churn_max_discount_percent" type="number" value="${churn.max_discount_percent}"></label>
      <label class="field"><span>حداقل خطر ریزش برای ارسال (۱ تا ۱۰۰)</span><input class="input" data-fkey="churn_min_score" type="number" value="${churn.min_score}"></label>
      <label class="field"><span>درصد تخفیف پیش‌فرض (بدون AI)</span><input class="input" data-fkey="churn_discount_percent" type="number" value="${churn.discount_percent}"></label>
      <label class="field"><span>اعتبار کد (ساعت)</span><input class="input" data-fkey="churn_discount_expiry_hours" type="number" value="${churn.discount_expiry_hours}"></label>
      <label class="field"><span>حداقل فاصله بین دو پیشنهاد به یک کاربر (روز)</span><input class="input" data-fkey="churn_cooldown_days" type="number" value="${churn.cooldown_days}"></label>
      <label class="field"><span>حداکثر پیشنهاد در هر دور بررسی</span><input class="input" data-fkey="churn_max_per_run" type="number" value="${churn.max_per_run}"></label>
      <button class="btn btn-primary btn-sm" id="save-churn">ذخیره</button>
    </div>

    <div class="card">
      <h3>📶 یادآوری بر اساس حجم مصرفی</h3>
      <label class="field field-row"><span>فعال</span>${_swSpan('volume_enabled', volumeReminder.enabled)}</label>
      <label class="field"><span>مبنای آستانه</span>
        <select class="input" data-fkey="volume_mode">
          <option value="percent" ${volumeReminder.mode === 'percent' ? 'selected' : ''}>درصد باقی‌مانده</option>
          <option value="gb" ${volumeReminder.mode === 'gb' ? 'selected' : ''}>گیگابایت باقی‌مانده</option>
        </select>
      </label>
      <label class="field"><span>درصد آستانه (وقتی مبنا درصد است)</span><input class="input" data-fkey="volume_percent" type="number" value="${volumeReminder.percent}"></label>
      <label class="field"><span>گیگ باقی‌مانده (وقتی مبنا گیگ است)</span><input class="input" data-fkey="volume_gb_left" type="number" value="${volumeReminder.gb_left}"></label>
      <label class="field"><span>درصد تخفیف کد پیشنهادی</span><input class="input" data-fkey="volume_discount_percent" type="number" value="${volumeReminder.discount_percent}"></label>
      <label class="field"><span>اعتبار کد (ساعت)</span><input class="input" data-fkey="volume_discount_expiry_hours" type="number" value="${volumeReminder.discount_expiry_hours}"></label>
      <button class="btn btn-primary btn-sm" id="save-volume">ذخیره</button>
    </div>

    <div class="card">
      <h3>🔌 هشدار اتصال / عدم‌اتصال به کانفیگ</h3>
      <div class="card-sub" style="margin:8px 0 4px"><b>✅ هشدار اتصال</b></div>
      <label class="field field-row"><span>فعال</span>${_swSpan('connect_enabled', connectAlert.connect_enabled)}</label>
      <label class="field"><span>آستانه‌ی مصرف (مگابایت) — از این مقدار به بعد «متصل» در نظر گرفته می‌شود</span>
        <input class="input" data-fkey="connect_threshold_mb" type="number" step="0.1" value="${connectAlert.connect_threshold_mb}"></label>
      <label class="field"><span>متن پیام (از {used_gb} می‌توانید استفاده کنید)</span>
        <textarea class="input" data-fkey="connect_text" rows="3">${esc(connectAlert.connect_text || '')}</textarea></label>

      <div class="card-sub" style="margin:16px 0 4px"><b>⚠️ هشدار عدم‌اتصال</b></div>
      <label class="field field-row"><span>فعال</span>${_swSpan('no_connect_enabled', connectAlert.no_connect_enabled)}</label>
      <label class="field"><span>مهلت بعد از فعال‌سازی سرویس (ساعت)</span>
        <input class="input" data-fkey="no_connect_hours" type="number" value="${connectAlert.no_connect_hours}"></label>
      <label class="field"><span>آستانه‌ی مصرف (مگابایت) — زیر این مقدار یعنی هنوز متصل نشده</span>
        <input class="input" data-fkey="no_connect_threshold_mb" type="number" step="0.1" value="${connectAlert.no_connect_threshold_mb}"></label>
      <label class="field"><span>متن پیام (از {used_gb} می‌توانید استفاده کنید)</span>
        <textarea class="input" data-fkey="no_connect_text" rows="3">${esc(connectAlert.no_connect_text || '')}</textarea></label>
      <button class="btn btn-primary btn-sm" id="save-connect-alert" style="margin-top:8px">ذخیره</button>
    </div>

    <div class="card">
      <h3>🎁 تخفیف تمدید کامل زودهنگام</h3>
      <div class="card-sub" style="margin-bottom:8px">اگر کاربر از «حساب من» تمدید کامل سرویس بزند و تا انقضای واقعی سرویسش حداکثر N روز مانده باشد، این تخفیف به‌صورت خودکار (بدون نیاز به کد) روی قیمت پلن اعمال می‌شود.</div>
      <label class="field field-row"><span>فعال</span>${_swSpan('early_renewal_enabled', earlyRenewal.enabled)}</label>
      <label class="field"><span>حداکثر روز مانده به انقضا</span><input class="input" data-fkey="early_renewal_days" type="number" value="${earlyRenewal.days_before}"></label>
      <label class="field"><span>درصد تخفیف</span><input class="input" data-fkey="early_renewal_percent" type="number" value="${earlyRenewal.percent}"></label>
      <button class="btn btn-primary btn-sm" id="save-early-renewal">ذخیره</button>
    </div>

    <div class="card">
      <h3>🧪 کانفیگ تست</h3>
      <div class="card-sub" style="margin-bottom:8px">
        موجودی بانک لینک دستی (قدیمی): <b>${fmt(testConfig.bank_stock)}</b>
      </div>
      <label class="field field-row"><span>فعال</span>${_swSpan('test_enabled', testConfig.enabled)}</label>
      <div style="display:flex;gap:8px;margin:8px 0 16px">
        <button class="btn btn-primary btn-sm" id="save-test">ذخیره</button>
        <button class="btn btn-sm btn-danger" id="reset-test-all">بازنشانی کانفیگ تست برای همه‌ی کاربران</button>
      </div>
      <div class="card-sub" style="margin-bottom:6px">
        هر کاربر مستقل از تعداد پلن‌های زیر، در کل فقط یک بار مجاز به دریافت کانفیگ تست است
        (مگر با «بازنشانی برای همه» بالا). هر پلن پنل/حجم/مدت/پیشوند نام کاربری خودش را دارد؛
        اگر بیش از یک پلن فعال باشد، کاربر هنگام درخواست کانفیگ تست از بین آن‌ها انتخاب می‌کند.
      </div>
      <div id="test-plans-list"></div>
      <button class="btn btn-sm" id="add-test-plan" style="margin-top:8px">➕ افزودن پلن کانفیگ تست</button>
    </div>

    <div class="card">
      <h3>📢 عضویت اجباری در کانال</h3>
      <label class="field field-row"><span>فعال</span>${_swSpan('fj_enabled', forceJoin.enabled)}</label>
      <label class="field"><span>آیدی کانال‌ها (مثل ‎@my_channel) — هر کانال در یک خط، بدون محدودیت تعداد</span><textarea class="input" data-fkey="fj_channel" rows="4" style="direction:ltr;text-align:left">${esc((forceJoin.channels || (forceJoin.channel ? [forceJoin.channel] : [])).join('\n'))}</textarea></label>
      <div class="card-sub">این تنظیم روی ربات اصلی، مینی‌اپ، و تمام بات‌های نمایندگی به‌طور یکسان اعمال می‌شود.</div>
      <button class="btn btn-primary btn-sm" id="save-forcejoin">ذخیره</button>
    </div>

    <div class="card">
      <h3>📉 هشدار موجودی کم محصول</h3>
      <label class="field"><span>آستانه (وقتی موجودی یک محصول به این عدد برسد، به ادمین‌ها اطلاع داده می‌شود)</span>
        <input class="input" data-fkey="stock_threshold" type="number" value="${stockAlert.threshold}"></label>
      <button class="btn btn-primary btn-sm" id="save-stock">ذخیره</button>
    </div>

    <div class="card">
      <h3>🚨 هشدار زیرمجموعه‌گیری فیک</h3>
      <div class="card-sub" style="margin-bottom:8px">چون تلگرام IP/دستگاه نمی‌دهد، تشخیص فقط بر اساس رفتار حساب‌هاست: دعوت انبوه در بازه‌ی کوتاه، یا نرخ بالای زیرمجموعه‌های بی‌خرید. با تشخیص مشکوک، به ادمین‌ها هشدار داده می‌شود.</div>
      <label class="field field-row"><span>فعال</span>${_swSpan('rf_enabled', referralFraud.detection_enabled)}</label>
      <label class="field"><span>تعداد دعوت که یعنی «انبوه»</span><input class="input" data-fkey="rf_burst_count" type="number" value="${referralFraud.burst_count}"></label>
      <label class="field"><span>بازه‌ی زمانی دعوت انبوه (دقیقه)</span><input class="input" data-fkey="rf_burst_minutes" type="number" value="${referralFraud.burst_minutes}"></label>
      <label class="field"><span>حداقل تعداد دعوت لازم برای بررسی نرخ بی‌خریدی</span><input class="input" data-fkey="rf_min_invites" type="number" value="${referralFraud.min_invites}"></label>
      <label class="field"><span>درصد بی‌خریدی که یعنی مشکوک</span><input class="input" data-fkey="rf_zero_ratio" type="number" value="${referralFraud.zero_purchase_ratio}"></label>
      <label class="field field-row"><span>توقف خودکار پاداش رفرال کاربر مشکوک تا بررسی دستی</span>${_swSpan('rf_auto_suspend', referralFraud.auto_suspend)}</label>
      <button class="btn btn-primary btn-sm" id="save-referral-fraud" style="margin-top:12px">ذخیره</button>

      <div class="card-sub" style="margin:16px 0 8px"><b>هشدارهای باز (${fraudFlags.items.length})</b></div>
      <div id="referral-fraud-flags-list">${_referralFraudFlagsRows(fraudFlags.items)}</div>
    </div>
  `);

  const root = content();
  _bindSwitches(root);

  $('#save-referral').addEventListener('click', async () => {
    try {
      await apiPost('/settings/referral', {
        enabled: _swOn(root, 'ref_enabled'),
        percent: _num(root, 'ref_percent'),
        commission_max_count: _num(root, 'ref_commission_max'),
        free_config_enabled: _swOn(root, 'ref_fc_enabled'),
        free_config_threshold: _num(root, 'ref_fc_threshold'),
        free_config_product_id: _val(root, 'ref_fc_product') ? Number(_val(root, 'ref_fc_product')) : null,
        invite_bonus_enabled: _swOn(root, 'ref_ib_enabled'),
        invite_bonus_amount: _num(root, 'ref_ib_amount'),
        invite_bonus_max_count: _num(root, 'ref_ib_max'),
      });
      toast('تنظیمات رفرال ذخیره شد.');
    } catch (e) { handleErr(e); }
  });

  $('#save-wheel').addEventListener('click', async () => {
    const prizes = (_val(root, 'wheel_prizes') || '').split(',').map(s => Number(s.trim())).filter(n => n > 0);
    try {
      await apiPost('/settings/wheel', {
        enabled: _swOn(root, 'wheel_enabled'), win_percent: _num(root, 'wheel_win_percent'),
        prizes, expiry_hours: _num(root, 'wheel_expiry_hours'), cooldown_hours: _num(root, 'wheel_cooldown_hours'),
      });
      toast('تنظیمات گردونه ذخیره شد.');
    } catch (e) { handleErr(e); }
  });

  $('#save-renewal').addEventListener('click', async () => {
    try {
      await apiPost('/settings/renewal', {
        enabled: _swOn(root, 'renewal_enabled'), days_before: _num(root, 'renewal_days_before'),
        discount_percent: _num(root, 'renewal_discount_percent'), discount_expiry_hours: _num(root, 'renewal_discount_expiry_hours'),
      });
      toast('تنظیمات یادآوری تمدید ذخیره شد.');
    } catch (e) { handleErr(e); }
  });

  $('#save-churn').addEventListener('click', async () => {
    try {
      await apiPost('/settings/churn', {
        enabled: _swOn(root, 'churn_enabled'), ai_enabled: _swOn(root, 'churn_ai_enabled'),
        max_discount_percent: _num(root, 'churn_max_discount_percent'), min_score: _num(root, 'churn_min_score'),
        discount_percent: _num(root, 'churn_discount_percent'), discount_expiry_hours: _num(root, 'churn_discount_expiry_hours'),
        cooldown_days: _num(root, 'churn_cooldown_days'), max_per_run: _num(root, 'churn_max_per_run'),
      });
      toast('تنظیمات پیش‌بینی ریزش ذخیره شد.');
    } catch (e) { handleErr(e); }
  });

  $('#save-volume').addEventListener('click', async () => {
    try {
      await apiPost('/settings/volume-reminder', {
        enabled: _swOn(root, 'volume_enabled'), mode: _val(root, 'volume_mode'),
        percent: _num(root, 'volume_percent'), gb_left: _num(root, 'volume_gb_left'),
        discount_percent: _num(root, 'volume_discount_percent'), discount_expiry_hours: _num(root, 'volume_discount_expiry_hours'),
      });
      toast('تنظیمات یادآوری حجمی ذخیره شد.');
    } catch (e) { handleErr(e); }
  });

  $('#save-connect-alert').addEventListener('click', async () => {
    try {
      await apiPost('/settings/connect-alert', {
        connect_enabled: _swOn(root, 'connect_enabled'),
        connect_threshold_mb: _num(root, 'connect_threshold_mb'),
        connect_text: _val(root, 'connect_text'),
        no_connect_enabled: _swOn(root, 'no_connect_enabled'),
        no_connect_hours: _num(root, 'no_connect_hours'),
        no_connect_threshold_mb: _num(root, 'no_connect_threshold_mb'),
        no_connect_text: _val(root, 'no_connect_text'),
      });
      toast('تنظیمات هشدار اتصال/عدم‌اتصال ذخیره شد.');
    } catch (e) { handleErr(e); }
  });

  $('#save-early-renewal').addEventListener('click', async () => {
    try {
      await apiPost('/settings/early-renewal-discount', {
        enabled: _swOn(root, 'early_renewal_enabled'),
        days_before: _num(root, 'early_renewal_days'),
        percent: _num(root, 'early_renewal_percent'),
      });
      toast('تنظیمات تخفیف تمدید زودهنگام ذخیره شد.');
    } catch (e) { handleErr(e); }
  });

  $('#save-test').addEventListener('click', async () => {
    try {
      await apiPost('/settings/test-config', { enabled: _swOn(root, 'test_enabled') });
      toast('وضعیت کانفیگ تست ذخیره شد.');
    } catch (e) { handleErr(e); }
  });
  $('#reset-test-all').addEventListener('click', async () => {
    if (!confirm('همه‌ی کاربران دوباره امکان دریافت کانفیگ تست پیدا می‌کنند. ادامه بدم؟')) return;
    try {
      const res = await apiPost('/settings/test-config/reset-all');
      toast(`برای ${res.count} کاربر بازنشانی شد.`);
    } catch (e) { handleErr(e); }
  });

  function _tpVol(mb) { return mb >= 1024 ? `${(mb / 1024).toFixed(2).replace(/\.?0+$/, '')} گیگ` : `${mb} مگابایت`; }
  function _tpDur(h) { return (h >= 24 && h % 24 === 0) ? `${h / 24} روز` : `${h} ساعت`; }
  function _tpTargets(p) {
    const parts = [];
    if (p.panel_server_name) parts.push(`پنل: ${esc(p.panel_server_name)}`);
    if (p.provision_ssh_node_name) parts.push(`SSH: ${esc(p.provision_ssh_node_name)}`);
    const extra = (p.extra_panel_ids || []).length + (p.extra_ssh_node_ids || []).length;
    if (extra) parts.push(`+${extra} مقصد`);
    return parts.join(' · ') || 'پنل: —';
  }

  function renderTestPlansList(plans) {
    const box = $('#test-plans-list', root);
    if (!plans.length) {
      box.innerHTML = `<div class="card-sub">هنوز هیچ پلنی تعریف نشده.</div>`;
      return;
    }
    box.innerHTML = plans.map(p => `
      <div class="row-item" data-plan-id="${p.id}" style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border,#333)">
        <div>
          <b>${p.is_active ? '🟢' : '🔴'} ${esc(p.name)}</b>
          <div class="card-sub">پیشوند: ${esc(p.name_prefix)} · ${_tpTargets(p)} · ${_tpVol(p.volume_mb)} / ${_tpDur(p.duration_hours)}${p.base_users ? ` · ${p.base_users} کاربر` : ''}</div>
        </div>
        <div style="display:flex;gap:6px">
          <button class="btn btn-sm" data-tp-edit="${p.id}">ویرایش</button>
          <button class="btn btn-sm" data-tp-toggle="${p.id}">${p.is_active ? 'غیرفعال کن' : 'فعال کن'}</button>
          <button class="btn btn-sm btn-danger" data-tp-del="${p.id}">حذف</button>
        </div>
      </div>
    `).join('');

    $$('[data-tp-toggle]', box).forEach(b => b.addEventListener('click', async () => {
      try { await apiPost(`/test-config/plans/${b.dataset.tpToggle}/toggle`); await reloadTestPlans(); } catch (e) { handleErr(e); }
    }));
    $$('[data-tp-del]', box).forEach(b => b.addEventListener('click', async () => {
      if (!confirm('این پلن حذف شود؟ کانفیگ‌های تست ساخته‌شده قبلی دست‌نخورده می‌مانند.')) return;
      try { await apiDelete(`/test-config/plans/${b.dataset.tpDel}`); await reloadTestPlans(); } catch (e) { handleErr(e); }
    }));
    $$('[data-tp-edit]', box).forEach(b => b.addEventListener('click', () => {
      const plan = plans.find(p => p.id === Number(b.dataset.tpEdit));
      openTestPlanForm(plan);
    }));
  }

  async function reloadTestPlans() {
    const plans = await apiGet('/test-config/plans');
    renderTestPlansList(plans);
  }

  async function openTestPlanForm(plan) {
    if (!panelServers.length) { toast('اول باید حداقل یک سرور پنل فعال ثبت کنی.'); return; }
    const isEdit = !!plan;
    const [sshNodes, multiInfo] = await Promise.all([
      apiGet('/ssh/nodes-lite').catch(() => []),
      apiGet('/products/multi-target-info').catch(() => ({ dsub_enabled: false })),
    ]);
    catalogDsubEnabled = !!(multiInfo && multiInfo.dsub_enabled);
    const prefill = plan
      ? { ...plan, provision_server_id: plan.panel_server_id }
      : { provision_server_id: panelServers[0].id, provision_ssh_protocol: 'ssh', extra_panel_ids: [], extra_ssh_node_ids: [] };
    window.__productPrefillTargetConfig = (plan && plan.provision_target_config) || null;
    openModal(isEdit ? 'ویرایش پلن کانفیگ تست' : 'افزودن پلن کانفیگ تست', `
      <div class="form-grid">
        <label class="field"><span>نام پلن</span><input class="input" id="tpf-name" value="${plan ? esc(plan.name) : ''}"></label>
        <label class="field"><span>پیشوند نام کاربری (فقط حروف/عدد انگلیسی)</span><input class="input" id="tpf-prefix" style="direction:ltr;text-align:left" value="${plan ? esc(plan.name_prefix) : 'test'}"></label>
        <label class="field"><span>حجم (مگابایت - برای ۱ گیگ عدد 1024 بزن)</span><input class="input" id="tpf-volume" type="number" value="${plan ? plan.volume_mb : 1024}"></label>
        <label class="field"><span>مدت (ساعت - برای ۱ روز عدد 24 بزن)</span><input class="input" id="tpf-duration" type="number" value="${plan ? plan.duration_hours : 24}"></label>
        ${productProvisionFieldsHtml(panelServers, sshNodes, prefill)}
        <button class="btn btn-primary btn-sm" id="tpf-save">ذخیره</button>
      </div>
    `, (body, close) => {
      wireProductProvisionToggle(body);
      const directRadio = body.querySelector('input[name="prod-source"][value="direct"]');
      directRadio.checked = true;
      const radioRow = directRadio.closest('.form-row');
      if (radioRow) radioRow.style.display = 'none';
      ['#prod-duration-unlimited', '#prod-volume', '#prod-volume-unlimited'].forEach(sel => {
        const el = body.querySelector(sel);
        if (el) (el.closest('label') || el).style.display = 'none';
      });
      body.querySelector('#prod-volume').value = 1;
      const renewBox = body.querySelector('#prod-renew-rules');
      if (renewBox) renewBox.style.display = 'none';
      body.querySelector('#prod-direct-fields').style.display = '';
      body.querySelector('#tpf-save').addEventListener('click', async () => {
        const prov = readProductProvisionFields(body);
        if (!prov.ok) return;
        const body_ = {
          name: body.querySelector('#tpf-name').value.trim(),
          name_prefix: body.querySelector('#tpf-prefix').value.trim(),
          volume_mb: Number(body.querySelector('#tpf-volume').value) || 0,
          duration_hours: Number(body.querySelector('#tpf-duration').value) || 0,
          panel_server_id: prov.provision_server_id,
          provision_target_values: prov.provision_target_values,
          extra_panel_target_values: prov.extra_panel_target_values,
          provision_ssh_node_id: prov.provision_ssh_node_id,
          provision_ssh_protocol: prov.provision_ssh_protocol,
          extra_panel_ids: prov.extra_panel_ids,
          extra_ssh_node_ids: prov.extra_ssh_node_ids,
          base_users: prov.base_users,
          extra_user_price: prov.extra_user_price,
          max_users: prov.max_users,
        };
        try {
          if (isEdit) await apiPut(`/test-config/plans/${plan.id}`, body_);
          else await apiPost('/test-config/plans', body_);
          close();
          toast('پلن ذخیره شد.');
          await reloadTestPlans();
        } catch (e) { handleErr(e); }
      });
    });
  }

  renderTestPlansList(testPlans);
  $('#add-test-plan').addEventListener('click', () => openTestPlanForm(null));

  $('#save-forcejoin').addEventListener('click', async () => {
    try {
      await apiPost('/settings/force-join', { enabled: _swOn(root, 'fj_enabled'), channel: _val(root, 'fj_channel') });
      toast('تنظیمات عضویت اجباری ذخیره شد.');
    } catch (e) { handleErr(e); }
  });

  $('#save-stock').addEventListener('click', async () => {
    try {
      await apiPost('/settings/stock-alert', { threshold: _num(root, 'stock_threshold') });
      toast('آستانه‌ی هشدار موجودی ذخیره شد.');
    } catch (e) { handleErr(e); }
  });

  $('#save-referral-fraud').addEventListener('click', async () => {
    try {
      await apiPost('/settings/referral-fraud', {
        detection_enabled: _swOn(root, 'rf_enabled'),
        burst_count: _num(root, 'rf_burst_count'),
        burst_minutes: _num(root, 'rf_burst_minutes'),
        min_invites: _num(root, 'rf_min_invites'),
        zero_purchase_ratio: _num(root, 'rf_zero_ratio'),
        auto_suspend: _swOn(root, 'rf_auto_suspend'),
      });
      toast('تنظیمات هشدار زیرمجموعه‌گیری فیک ذخیره شد.');
    } catch (e) { handleErr(e); }
  });

  $('#referral-fraud-flags-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-resolve-flag]');
    if (!btn) return;
    const flagId = btn.dataset.resolveFlag;
    try {
      await apiPost(`/referral-fraud/flags/${flagId}/resolve`);
      btn.closest('[data-flag-id]').remove();
      toast('هشدار رفع شد.');
    } catch (e2) { handleErr(e2); }
  });
}

/* ======================================================== banners === */

const BANNER_NAV_OPTIONS = [
  ['store', '🛒 فروشگاه (خرید سرویس)'], ['services', '🛡 سرویس‌های من'], ['wallet', '💳 کیف پول'],
  ['profile', '👤 حساب کاربری'], ['support', '💬 پشتیبانی'], ['referral', '🤝 دعوت دوستان'],
  ['test', '🧪 کانفیگ تست رایگان'], ['wheel', '🎡 چرخ شانس'], ['home', '🏠 صفحه‌ی خانه'],
];
const BANNER_BG_PRESETS = [
  'linear-gradient(120deg, #0d1a12, #123a20 55%, #17532c)',
  'linear-gradient(120deg, #2b1608, #4d2510 55%, #7a3a14)',
  'linear-gradient(120deg, #0d1420, #142845 55%, #1c3f6e)',
  'linear-gradient(120deg, #150c22, #2a1440 55%, #431f66)',
  'linear-gradient(120deg, #2a0d16, #4d1027 55%, #7a1b45)',
  'linear-gradient(120deg, #1a1405, #3d2f0a 55%, #5e480f)',
];

async function renderBanners() {
  let list = await apiGet('/banners');

  const rowHtml = (b, i) => `
    <div class="card" data-banner-row="${i}" style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <strong>بنر ${i + 1}${b.kind === 'expiry' ? ' ⏰ (خودکار: انقضای سرویس — {n} = تعداد سرویس‌ها)' : b.kind === 'referral' ? ' 🤝 (خودکار: دعوت دوستان)' : ''}${b.enabled === false ? ' (غیرفعال)' : ''}</strong>
        <div style="display:flex;gap:6px">
          <button type="button" class="btn btn-sm" data-b-up ${i === 0 ? 'disabled' : ''}>▲</button>
          <button type="button" class="btn btn-sm" data-b-down ${i === list.length - 1 ? 'disabled' : ''}>▼</button>
          <button type="button" class="btn btn-sm btn-danger" data-b-remove ${b.kind ? 'disabled title="بنر خودکار است؛ غیرفعالش کن"' : ''}>🗑</button>
        </div>
      </div>
      <div data-b-preview style="border-radius:12px;padding:12px 14px;margin-bottom:10px;color:#fff;min-height:48px;${b.image ? `background:url('${b.image}') center/cover no-repeat` : `background:${esc(b.bg || BANNER_BG_PRESETS[0])}`}">
        ${b.image && b.image_only ? '' : `<span style="font-size:20px">${esc(b.icon || '')}</span> <b>${esc(b.title || 'بنر جدید')}</b>`}
      </div>
      <label class="field"><span>آیکون (اموجی)</span><input class="input" data-b-icon maxlength="4" value="${esc(b.icon || '')}"></label>
      <label class="field"><span>عنوان بنر</span><input class="input" data-b-title maxlength="40" value="${esc(b.title || '')}"></label>
      <label class="field"><span>توضیح کوتاه</span><input class="input" data-b-sub maxlength="120" value="${esc(b.sub || '')}"></label>
      <label class="field"><span>متن دکمه</span><input class="input" data-b-cta maxlength="30" value="${esc(b.cta || '')}"></label>
      <label class="field"><span>با ضربه‌زدن، کاربر منتقل شود به</span>
        <select class="input" data-b-nav>${BANNER_NAV_OPTIONS.map(([v, l]) => `<option value="${v}" ${v === b.nav ? 'selected' : ''}>${l}</option>`).join('')}</select>
      </label>
      <label class="field"><span>پس‌زمینه (گرادیان/رنگ CSS)</span>
        <input class="input" data-b-bg value="${esc(b.bg || '')}" style="direction:ltr;text-align:left">
      </label>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">
        ${BANNER_BG_PRESETS.map((bg) => `<button type="button" data-b-preset="${esc(bg)}" style="width:28px;height:28px;border-radius:8px;border:1px solid var(--border,#444);background:${bg};cursor:pointer"></button>`).join('')}
      </div>
      <label class="field"><span>عکس آماده (اختیاری، زیر ۲ مگابایت، پیشنهاد ۱۲۰۰×۴۰۰)</span>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <input type="file" accept="image/*" data-b-upload hidden>
          <button type="button" class="btn btn-sm" data-b-pick>📤 آپلود عکس</button>
          ${b.image ? '<button type="button" class="btn btn-sm btn-danger" data-b-clear-image>🗑 حذف عکس</button>' : ''}
        </div>
      </label>
      ${b.image ? `<label class="field field-row"><span>فقط عکس نمایش داده شود</span>${_swSpan('b_imageonly_' + i, !!b.image_only)}</label>` : ''}
      <label class="field field-row"><span>فعال</span>${_swSpan('b_enabled_' + i, b.enabled !== false)}</label>
    </div>`;

  const collect = (root) => $$('#banners-list [data-banner-row]', root).map((row, i) => {
    const prev = list[Number(row.dataset.bannerRow)] || {};
    return {
      id: prev.id || null,
      kind: prev.kind || null,
      icon: $('[data-b-icon]', row).value,
      title: $('[data-b-title]', row).value.trim(),
      sub: $('[data-b-sub]', row).value.trim(),
      cta: $('[data-b-cta]', row).value.trim(),
      nav: $('[data-b-nav]', row).value,
      bg: $('[data-b-bg]', row).value.trim(),
      image: prev.image || '',
      image_only: prev.image ? _swOn(root, 'b_imageonly_' + row.dataset.bannerRow) : false,
      enabled: _swOn(root, 'b_enabled_' + row.dataset.bannerRow),
    };
  });

  const draw = () => {
    setContent(`
      <div class="card">
        <h3>🖼 بنرهای فروشگاه (مینی‌اپ)</h3>
        <div class="card-sub">این بنرها در صفحه‌ی اصلی مینی‌اپ به‌صورت چرخشی نمایش داده می‌شوند (حداکثر ۵۰ بنر). تغییرات اینجا و در مینی‌اپ یکسان است.</div>
      </div>
      <div id="banners-list">${list.length ? list.map(rowHtml).join('') : '<div class="card">هنوز بنری اضافه نشده.</div>'}</div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-sm" id="banner-add">➕ افزودن بنر</button>
        <button class="btn btn-primary btn-sm" id="banner-save">ذخیره‌ی همه</button>
      </div>
    `);
    const root = content();
    _bindSwitches(root);
    const sync = () => { list = collect(root); };

    $$('#banners-list [data-banner-row]', root).forEach((row) => {
      const idx = Number(row.dataset.bannerRow);
      const fileInput = $('[data-b-upload]', row);
      $('[data-b-pick]', row).addEventListener('click', () => fileInput.click());
      fileInput.addEventListener('change', async () => {
        const file = fileInput.files[0];
        if (!file) return;
        const fd = new FormData();
        fd.append('photo', file);
        try {
          const res = await fetch('/api/banners/upload-image', { method: 'POST', credentials: 'include', body: fd });
          const data = await res.json();
          if (!res.ok) throw new Error(formatApiError(data.detail));
          sync();
          list[idx].image = data.image;
          list[idx].image_only = true;
          draw();
        } catch (e) { toast(e.message, true); }
      });
      const clr = $('[data-b-clear-image]', row);
      if (clr) clr.addEventListener('click', () => { sync(); list[idx].image = ''; list[idx].image_only = false; draw(); });
      $$('[data-b-preset]', row).forEach((btn) => btn.addEventListener('click', () => {
        $('[data-b-bg]', row).value = btn.dataset.bPreset;
        if (!list[idx].image) $('[data-b-preview]', row).style.background = btn.dataset.bPreset;
      }));
      $('[data-b-remove]', row).addEventListener('click', () => { sync(); if (list[idx] && list[idx].kind) return; list.splice(idx, 1); draw(); });
      $('[data-b-up]', row).addEventListener('click', () => { sync(); if (idx > 0) { [list[idx - 1], list[idx]] = [list[idx], list[idx - 1]]; draw(); } });
      $('[data-b-down]', row).addEventListener('click', () => { sync(); if (idx < list.length - 1) { [list[idx + 1], list[idx]] = [list[idx], list[idx + 1]]; draw(); } });
    });

    $('#banner-add').addEventListener('click', () => {
      sync();
      list.push({ id: null, icon: '✨', title: 'بنر جدید', sub: '', cta: 'مشاهده', nav: 'store', bg: BANNER_BG_PRESETS[0], image: '', image_only: false, enabled: true });
      draw();
    });
    $('#banner-save').addEventListener('click', async () => {
      sync();
      try {
        const res = await apiPost('/banners', { banners: list });
        toast('بنرها ذخیره شدند.');
        list = res.banners;
        draw();
      } catch (e) { handleErr(e); }
    });
  };
  draw();
}

async function renderResellers() {
  try {
    if (resellersSubTab === 'bots') await renderResellersBotsTab();
    else if (resellersSubTab === 'requests') await renderResellersRequestsTab();
    else if (resellersSubTab === 'commission') await renderResellersCommissionTab();
    else await renderResellersCreditTab();
  } catch (e) { handleErr(e); }
}

/* --------------------------------------------- سطح ۱: نماینده‌های کامل (بات) -- */
async function renderResellersBotsTab() {
  const bots = await apiGet('/reseller-bots');
  const totalRevenue = bots.reduce((a, b) => a + (b.revenue_toman || 0), 0);
  const totalOrders = bots.reduce((a, b) => a + (b.paid_orders || 0), 0);
  setContent(`
    ${resellersSubtabsHtml()}
    <div class="grid grid-4">
      <div class="card stat-card">
        <div class="stat-top"><span class="stat-icon stat-icon-1">${svg('resellers')}</span></div>
        <span class="value mono">${fmt(bots.length)}</span>
        <span class="label">تعداد نماینده‌های صاحب بات</span>
      </div>
      <div class="card stat-card">
        <div class="stat-top"><span class="stat-icon stat-icon-2">${svg('check')}</span></div>
        <span class="value mono">${fmt(bots.filter(b => b.is_active).length)}</span>
        <span class="label">فعال</span>
      </div>
      <div class="card stat-card">
        <div class="stat-top"><span class="stat-icon stat-icon-3">${svg('users')}</span></div>
        <span class="value mono">${fmt(totalOrders)}</span>
        <span class="label">سفارش تاییدشده (مجموع همه)</span>
      </div>
      <div class="card stat-card">
        <div class="stat-top"><span class="stat-icon stat-icon-4">${svg('tickets')}</span></div>
        <span class="value mono">${fmt(totalRevenue)} <span style="font-size:12px;font-weight:600">تومان</span></span>
        <span class="label">مجموع فروش همه‌ی نماینده‌ها</span>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h3>نماینده‌های صاحب بات مستقل</h3>
        <span class="card-sub">مبلغ فروش از سفارش‌های تاییدشده‌ی همان دیتابیس مستقل نماینده محاسبه شده است.</span>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>#</th><th>مالک</th><th>بات</th><th>فروش</th><th>وضعیت</th><th>پنل وب</th><th>تاریخ ثبت</th><th>عملیات</th></tr></thead>
        <tbody>${bots.map(b => `<tr>
          <td class="mono">#${b.id}</td>
          <td>${esc(b.owner_name || '—')}<div class="mono" style="opacity:.65;font-size:12px">${b.owner_telegram_id}</div></td>
          <td>${b.bot_username ? '@' + esc(b.bot_username) : '<span style="opacity:.5">—</span>'}</td>
          <td><span class="mono">${fmt(b.revenue_toman)} تومان</span><div style="opacity:.6;font-size:11.5px">${fmt(b.paid_orders)} سفارش</div></td>
          <td>${b.is_active ? '<span class="badge badge-approved">فعال</span>' : '<span class="badge badge-rejected">غیرفعال</span>'}</td>
          <td>${b.web_panel_enabled ? '<span class="badge badge-approved">فعال</span>' : '<span class="badge badge-rejected">غیرفعال</span>'}</td>
          <td class="mono">${fmtDate(b.created_at)}</td>
          <td><button class="btn btn-sm" data-manage="${b.id}">مدیریت</button></td>
        </tr>`).join('') || `<tr><td colspan="8" class="empty-state">${svg('empty')}<div>هیچ بات نمایندگی‌ای ثبت نشده</div></td></tr>`}</tbody>
      </table></div>
    </div>
  `);
  bindResellersSubtabs(content());
  $$('[data-manage]', content()).forEach(btn =>
    btn.addEventListener('click', () => openResellerBotManageModal(bots.find(b => b.id === Number(btn.dataset.manage)))));
  mountResellerRevenueReport(bots);
}

const resellerRevenueState = { start: '', end: '', botId: '' };

function mountResellerRevenueReport(bots) {
  const host = document.createElement('div');
  host.className = 'card';
  host.id = 'rrev-card';
  content().appendChild(host);
  const st = resellerRevenueState;
  const addDays = (s, n) => new Date(new Date(s + 'T00:00:00Z').getTime() + n * 86400000).toISOString().slice(0, 10);
  const jDay = s => parseInt(new Intl.DateTimeFormat('en-u-ca-persian', { day: 'numeric', timeZone: 'UTC' }).format(new Date(s + 'T00:00:00Z')), 10);
  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Tehran' });
  const monthStart = addDays(today, -(jDay(today) - 1));
  const prevEnd = addDays(monthStart, -1);
  const presets = [
    ['امروز', today, today],
    ['۷ روز اخیر', addDays(today, -6), today],
    ['۳۰ روز اخیر', addDays(today, -29), today],
    ['این ماه', monthStart, today],
    ['ماه قبل', addDays(prevEnd, -(jDay(prevEnd) - 1)), prevEnd],
  ];
  if (!st.start || !st.end) { st.start = presets[1][1]; st.end = today; }
  const load = async () => {
    host.innerHTML = '<div class="empty-state">در حال بارگذاری...</div>';
    try {
      const q = `start=${st.start}&end=${st.end}` + (st.botId ? `&bot_id=${st.botId}` : '');
      drawResellerRevenue(host, await apiGet(`/reseller-bots/revenue?${q}`), bots, presets, load);
    } catch (e) { host.innerHTML = ''; handleErr(e); }
  };
  load();
}

function drawResellerRevenue(host, data, bots, presets, reload) {
  const st = resellerRevenueState;
  const unit = '<span style="font-size:12px;font-weight:600">تومان</span>';
  const botName = b => esc(b.owner_name || ('#' + b.id)) + (b.bot_username ? ` <span style="opacity:.6">@${esc(b.bot_username)}</span>` : '');
  const bar = (v, max) => `<div style="height:8px;border-radius:8px;background:rgba(127,127,127,.18);overflow:hidden"><div style="height:100%;border-radius:8px;background:var(--brand,#8B5CF6);width:${v ? Math.max(3, Math.round(v / max * 100)) : 0}%"></div></div>`;
  const byDay = !!st.botId && data.days;
  const list = byDay ? data.days : data.bots;
  const maxRev = Math.max(1, ...list.map(x => x.revenue));
  host.innerHTML = `
    <div class="card-head"><h3>فروش نماینده‌ها</h3>
      <span class="card-sub">سفارش‌های تاییدشده، به تومان، به وقت تهران.</span></div>
    <div class="form-row" style="gap:8px;flex-wrap:wrap;margin-bottom:8px">
      <label class="field" style="margin:0"><span>از تاریخ <b class="mono">${fmtDateOnly(st.start)}</b></span><input type="date" class="input" id="rrev-start" value="${st.start}"></label>
      <label class="field" style="margin:0"><span>تا تاریخ <b class="mono">${fmtDateOnly(st.end)}</b></span><input type="date" class="input" id="rrev-end" value="${st.end}"></label>
    </div>
    <div class="tabs" style="margin-bottom:8px;flex-wrap:wrap">${presets.map(([l, s, e], i) =>
      `<button class="tab-btn ${s === st.start && e === st.end ? 'active' : ''}" data-rrev-preset="${i}">${l}</button>`).join('')}</div>
    <select class="input" id="rrev-bot" style="max-width:260px;margin-bottom:12px">
      <option value="">همه‌ی نماینده‌ها (تفکیک نماینده)</option>
      ${bots.map(b => `<option value="${b.id}" ${String(b.id) === String(st.botId) ? 'selected' : ''}>${esc(b.owner_name || ('#' + b.id))}${b.bot_username ? ' (@' + esc(b.bot_username) + ')' : ''} (تفکیک روز)</option>`).join('')}
    </select>
    <div class="card stat-card" style="margin-bottom:12px"><span class="value mono">${fmt(data.total.revenue)} ${unit}</span><span class="label">جمع فروش، ${fmt(data.total.orders)} سفارش</span></div>
    <div class="table-wrap"><table>
      <thead><tr><th>${byDay ? 'روز' : 'نماینده'}</th><th>فروش</th><th>سفارش</th>${byDay ? '' : '<th>سهم</th>'}<th style="min-width:90px"></th></tr></thead>
      <tbody>${list.map(x => `<tr ${byDay ? '' : `data-rrev-pick="${x.id}" style="cursor:pointer"`}>
        <td>${byDay ? fmtDateOnly(x.date) : botName(x)}</td>
        <td class="mono"><b>${fmt(x.revenue)}</b></td>
        <td class="mono">${fmt(x.orders)}</td>
        ${byDay ? '' : `<td class="mono">${fmt(data.total.revenue ? Math.round(x.revenue / data.total.revenue * 100) : 0)}٪</td>`}
        <td>${bar(x.revenue, maxRev)}</td>
      </tr>`).join('') || `<tr><td colspan="5" class="empty-state">موردی نیست</td></tr>`}</tbody>
    </table></div>`;
  const setRange = (s, e) => { st.start = s; st.end = e; reload(); };
  $$('[data-rrev-preset]', host).forEach(b => b.addEventListener('click', () => {
    const [, s, e] = presets[Number(b.dataset.rrevPreset)]; setRange(s, e);
  }));
  const onDate = () => {
    const s = $('#rrev-start', host).value, e = $('#rrev-end', host).value;
    if (s && e && s <= e) setRange(s, e); else toast('بازه نامعتبر است.');
  };
  $('#rrev-start', host).addEventListener('change', onDate);
  $('#rrev-end', host).addEventListener('change', onDate);
  $('#rrev-bot', host).addEventListener('change', e => { st.botId = e.target.value; reload(); });
  $$('[data-rrev-pick]', host).forEach(el => el.addEventListener('click', () => { st.botId = el.dataset.rrevPick; reload(); }));
}

function openResellerBotManageModal(bot) {
  openModal(`مدیریت نماینده #${bot.id}`, `
    <div class="form-grid">
      <div><b>بات:</b> ${bot.bot_username ? '@' + esc(bot.bot_username) : '—'}</div>
      <div><b>وضعیت فعلی:</b> ${bot.is_active ? 'فعال' : 'غیرفعال'}
        <span style="opacity:.6;font-size:12px">(اعمال واقعی تغییر وضعیت روی پروسه‌ی بات تا حدود ۱۰ ثانیه طول می‌کشد)</span>
      </div>
      <button class="btn btn-sm" id="rb-toggle">${bot.is_active ? '⏸ غیرفعال کردن' : '▶️ فعال کردن'}</button>
      <hr>
      <div><b>نام مالک</b></div>
      <input class="input" id="rb-owner-name" value="${esc(bot.owner_name || '')}" placeholder="نام مالک">
      <div><b>آیدی عددی مالک (تلگرام)</b></div>
      <input class="input" id="rb-owner-id" type="number" value="${bot.owner_telegram_id}" placeholder="آیدی تلگرام مالک">
      <button class="btn btn-sm" id="rb-save-owner">ذخیره مشخصات مالک</button>
      <hr>
      <div><b>پنل وب اختصاصی</b></div>
      ${bot.web_panel_enabled ? `
        <button class="btn btn-sm" id="rb-wp-link">🔗 نمایش لینک ورود ثابت</button>
        <button class="btn btn-sm" id="rb-wp-regen">🔁 ساخت لینک راه‌اندازی جدید (ارسال به نماینده)</button>
        <button class="btn btn-sm btn-danger" id="rb-wp-off">⛔️ غیرفعال کردن پنل وب</button>
      ` : `
        <button class="btn btn-sm btn-primary" id="rb-wp-on">🌐 فعال‌سازی پنل وب (ارسال لینک به نماینده)</button>
      `}
      <hr>
      <button class="btn btn-sm btn-danger" id="rb-delete">🗑 حذف این نماینده</button>
    </div>
  `, (body, close) => {
    $('#rb-toggle', body).addEventListener('click', async () => {
      try { await apiPost(`/reseller-bots/${bot.id}/toggle`); toast('وضعیت تغییر کرد.'); close(); renderResellers(); }
      catch (e) { handleErr(e); }
    });
    $('#rb-save-owner', body).addEventListener('click', async () => {
      try {
        await apiPut(`/reseller-bots/${bot.id}`, {
          owner_name: $('#rb-owner-name', body).value || null,
          owner_telegram_id: Number($('#rb-owner-id', body).value) || null,
        });
        toast('ذخیره شد.'); close(); renderResellers();
      } catch (e) { handleErr(e); }
    });
    const linkBtn = $('#rb-wp-link', body);
    if (linkBtn) linkBtn.addEventListener('click', async () => {
      try {
        const r = await apiGet(`/reseller-bots/${bot.id}/web-panel/login-link`);
        openModal('لینک ورود ثابت پنل وب', `
          <div class="form-grid"><input class="input" readonly value="${esc(r.login_link)}" onclick="this.select()"></div>
        `);
      } catch (e) { handleErr(e); }
    });
    const regenBtn = $('#rb-wp-regen', body);
    if (regenBtn) regenBtn.addEventListener('click', async () => {
      try {
        const r = await apiPost(`/reseller-bots/${bot.id}/web-panel/regenerate`);
        toast(r.sent_to_owner ? 'لینک جدید ساخته و برای نماینده ارسال شد.' : 'لینک ساخته شد ولی ارسال به نماینده ناموفق بود.');
      } catch (e) { handleErr(e); }
    });
    const offBtn = $('#rb-wp-off', body);
    if (offBtn) offBtn.addEventListener('click', async () => {
      try { await apiPost(`/reseller-bots/${bot.id}/web-panel/disable`); toast('پنل وب غیرفعال شد.'); close(); renderResellers(); }
      catch (e) { handleErr(e); }
    });
    const onBtn = $('#rb-wp-on', body);
    if (onBtn) onBtn.addEventListener('click', async () => {
      try {
        const r = await apiPost(`/reseller-bots/${bot.id}/web-panel/enable`);
        toast(r.sent_to_owner ? 'پنل وب فعال شد و لینک راه‌اندازی برای نماینده ارسال شد.' : 'پنل وب فعال شد ولی ارسال لینک ناموفق بود.');
        close(); renderResellers();
      } catch (e) { handleErr(e); }
    });

    $('#rb-delete', body).addEventListener('click', () => {
      openModal('حذف نماینده', `
        <div class="form-grid">
          <div>⚠️ آیا از حذف نماینده #${bot.id} مطمئنی؟ این کار برگشت‌پذیر نیست.</div>
          <label style="display:flex;gap:6px;align-items:center;cursor:pointer">
            <input type="checkbox" id="rb-del-purge"> دیتابیس این نماینده هم کامل پاک شود
          </label>
          <button class="btn btn-danger" id="rb-del-confirm">حذف قطعی</button>
        </div>
      `, (b2, close2) => {
        $('#rb-del-confirm', b2).addEventListener('click', async () => {
          try {
            const purge = $('#rb-del-purge', b2).checked;
            await apiDelete(`/reseller-bots/${bot.id}?purge_db=${purge}`);
            toast('نماینده حذف شد.'); close2(); close(); renderResellers();
          } catch (e) { handleErr(e); }
        });
      });
    });
  }, { wide: true });
}

/* --------------------------------------- سطح ۲: نمایندگی اعتباری (استخر حجم) -- */
async function renderResellersCreditTab() {
  const [resellers, cohort, orphans] = await Promise.all([
    apiGet('/resellers'),
    apiGet('/resellers/analytics/cohort').catch(() => null),
    apiGet('/resellers/orphans').catch(() => []),
  ]);

  for (const r of resellers) {
    r.reseller_supply_model = r.reseller_supply_model || 'volume_credit';
    if (r.reseller_supply_model === 'fixed_product') {
      try {
        const m = await apiGet(`/resellers/${r.telegram_id}/manage`);
        const primary = (m.inventory || []).find(x => Number(x.product_id) === Number(m.supply.product_id));
        r.fixed_product_qty = primary ? primary.qty_remaining : 0;
        r.fixed_product_name = primary ? primary.name : 'محصول مشخص نشده';
      } catch (_) {}
    }
  }
  const hasResellers = resellers.length > 0;
  const totalSoldGb = resellers.reduce((a, r) => a + (r.sold_volume_gb || 0), 0);
  const totalSoldConfigs = resellers.reduce((a, r) => a + (r.sold_configs || 0), 0);
  const introHtml = `
    <div class="card" style="padding:18px 20px">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap">
        <div style="min-width:240px">
          <h3 style="margin:0 0 6px">نمایندگی اعتباری</h3>
          <span class="card-sub">کاربرانی که بدون داشتن بات یا پنل مستقل، از یک «اعتبار حجمی» (گیگ) که خودت بهشون تخصیص می‌دی، داخل همین بات برای مشتری‌های خودشون کانفیگ می‌سازن. هر کانفیگ به‌اندازه‌ی حجمش از اعتبارشون کم می‌شه — پول این فروش‌ها بین خودشون و مشتری‌هاشونه و توی این بات ثبت نمی‌شه، فقط حجم فروخته‌شده قابل ردیابیه.</span>
        </div>
        <button class="btn btn-primary btn-sm" id="cres-add" style="white-space:nowrap">🔍 جستجو / فعال‌سازی نماینده با آیدی</button>
      </div>
      ${hasResellers ? `
      <div style="display:flex;gap:22px;margin-top:16px;padding-top:14px;border-top:1px solid var(--border);flex-wrap:wrap">
        <div><span class="value mono" style="font-size:18px">${fmt(totalSoldGb)}</span> <span class="label">گیگ فروخته‌شده (مجموع)</span></div>
        <div><span class="value mono" style="font-size:18px">${fmt(totalSoldConfigs)}</span> <span class="label">کانفیگ ساخته‌شده (مجموع)</span></div>
      </div>` : ''}
    </div>
  `;

  const cohortHtml = hasResellers && cohort ? renderResellerCohortBlock(cohort) : (hasResellers ? '' : `
    <div class="card empty-state" style="padding:40px 20px">
      ${svg('resellers')}
      <div style="font-weight:700;margin-top:10px">هنوز هیچ نمایندگی اعتباری‌ای فعال نیست</div>
      <div style="opacity:.7;font-size:13px;margin-top:4px;max-width:420px;margin-inline:auto">
        از دکمه‌ی «جستجو / فعال‌سازی نماینده با آیدی» بالا، آیدی عددی یک کاربر (که قبلاً بات را استارت کرده) را وارد کن تا برایش نمایندگی فعال و اعتبار تخصیص بدی.
      </div>
    </div>
  `);

  const orphansHtml = orphans.length ? `
    <div class="card">
      <div class="card-head"><h3>کاربران با رد پای نمایندگی بدون بات (Orphan)</h3>
        <span class="card-sub">پرچم/اعتبار/پنل نمایندگی روی رکورد این کاربران باقی مانده ولی هیچ بات نمایندگی‌ای برایشان ثبت نیست؛ معمولاً بعد از حذف دستی یک نماینده در سطح دیتابیس رخ می‌دهد.</span>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>آیدی</th><th>نام/یوزرنیم</th><th>وضعیت</th><th>اعتبار</th><th>عملیات</th></tr></thead>
        <tbody>${orphans.map(o => `<tr>
          <td class="mono">${o.telegram_id}</td>
          <td>${esc(o.first_name || o.username || '—')}</td>
          <td>${o.is_reseller ? '<span class="badge badge-pending">پرچم نماینده روشن</span>' : '<span style="opacity:.5">—</span>'}</td>
          <td class="mono">${fmt(o.reseller_credit_gb)} گیگ</td>
          <td><button class="btn btn-sm" data-purge="${o.telegram_id}">پاکسازی</button></td>
        </tr>`).join('')}</tbody>
      </table></div>
    </div>` : '';

  const listHtml = `
    <div class="card">
      <div class="card-head"><h3>لیست نمایندگان (${fmt(resellers.length)} نفر)</h3>
        <span class="card-sub">برای تغییر اعتبار، پنل اختصاصی یا وضعیت هرکدام، از دکمه‌های همان ردیف استفاده کن.</span>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>کاربر</th><th>مدل تامین</th><th>موجودی</th><th>فروش</th><th>پنل</th><th>وضعیت</th><th>عملیات</th></tr></thead>
        <tbody>${resellers.map(r => `<tr>
          <td>${r.username ? `<div>@${esc(r.username)}</div>` : ''}<div class="mono" style="${r.username ? 'opacity:.6;font-size:12px' : ''}">${r.telegram_id}</div></td>
          <td>${r.reseller_supply_model === 'fixed_product' ? '<span class="badge badge-pending">محصول آماده</span>' : '<span class="badge">اعتبار حجمی</span>'}</td>
          <td>${r.reseller_supply_model === 'fixed_product' ? `<span class="mono">${fmt(r.fixed_product_qty || 0)} عدد</span><div style="opacity:.6;font-size:11px">${esc(r.fixed_product_name || 'محصول مشخص نشده')}</div>` : `<span class="mono">${fmt(r.reseller_credit_gb)} گیگ</span>`}</td>
          <td class="mono">${fmt(r.sold_volume_gb)} گیگ<div style="opacity:.6;font-size:11.5px">${fmt(r.sold_configs)} کانفیگ</div></td>
          <td>${r.reseller_panel_id ? `<span class="mono">#${r.reseller_panel_id}</span>` : '<span style="opacity:.5">پیش‌فرض</span>'}</td>
          <td>${r.is_reseller ? '<span class="badge badge-approved">فعال</span>' : '<span class="badge badge-rejected">غیرفعال</span>'}</td>
          <td><div style="display:flex;gap:6px;flex-wrap:wrap">
            <button class="btn btn-sm btn-primary" data-manage-l2="${r.telegram_id}">⚙️ مدیریت</button>
            <button class="btn btn-sm" data-credit="${r.telegram_id}">💳 اعتبار</button>
            <button class="btn btn-sm" data-toggle-status="${r.telegram_id}" data-cur="${r.is_reseller ? 1 : 0}">${r.is_reseller ? '⛔️ غیرفعال' : '✅ فعال'}</button>
            <button class="btn btn-sm" data-log="${r.telegram_id}">📜 تاریخچه</button>
          </div></td>
        </tr>`).join('') || `<tr><td colspan="8" class="empty-state">${svg('empty')}<div>نماینده ثبت نشده</div></td></tr>`}</tbody>
      </table></div>
    </div>
  `;

  setContent(`
    ${resellersSubtabsHtml()}
    ${introHtml}
    ${cohortHtml}
    ${orphansHtml}
    ${listHtml}
  `);
  bindResellersSubtabs(content());

  $('#cres-add', content()).addEventListener('click', openResellerFindModal);

  $$('[data-manage-l2]', content()).forEach(b => b.addEventListener('click', () => openResellerManageModal(Number(b.dataset.manageL2))));

  $$('[data-credit]', content()).forEach(b =>
    b.addEventListener('click', () => openResellerCreditModal(b.dataset.credit)));

  $$('[data-toggle-status]', content()).forEach(b => b.addEventListener('click', async () => {
    try {
      await apiPost(`/resellers/${b.dataset.toggleStatus}/status`, { enabled: b.dataset.cur !== '1' });
      toast('وضعیت تغییر کرد.'); renderResellers();
    } catch (e) { handleErr(e); }
  }));

  $$('[data-log]', content()).forEach(b => b.addEventListener('click', async () => {
    try {
      const log = await apiGet(`/resellers/${b.dataset.log}/log`);
      openModal(`تاریخچه اعتبار #${b.dataset.log}`, `
        <div class="table-wrap"><table>
          <thead><tr><th>تاریخ</th><th>تغییر</th><th>دلیل</th></tr></thead>
          <tbody>${log.map(l => `<tr>
            <td class="mono">${fmtDate(l.created_at)}</td>
            <td class="mono">${l.delta_gb > 0 ? '+' : ''}${fmt(l.delta_gb)}</td>
            <td>${esc(l.reason || '—')}</td>
          </tr>`).join('') || '<tr><td colspan="3" class="empty-state">رکوردی نیست</td></tr>'}</tbody>
        </table></div>
      `, null, { wide: true });
    } catch (e) { handleErr(e); }
  }));

  $$('[data-panel]', content()).forEach(b => b.addEventListener('click', async () => {
    try {
      const panels = await apiGet('/reseller-panels-lite');
      const cur = b.dataset.panelCur;
      openModal('پنل اختصاصی این نماینده', `
        <div class="form-grid">
          <select class="input" id="rp-panel">
            <option value="">پیش‌فرض خودکار (اولین پنل نمایندگی فعال)</option>
            ${panels.map(p => `<option value="${p.id}" ${String(p.id) === cur ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}
          </select>
          <button class="btn btn-primary" id="rp-save">ذخیره</button>
        </div>
      `, (body, close) => {
        $('#rp-save', body).addEventListener('click', async () => {
          const val = $('#rp-panel', body).value;
          try {
            await apiPost(`/resellers/${b.dataset.panel}/panel`, { panel_server_id: val ? Number(val) : null });
            toast('ذخیره شد.'); close(); renderResellers();
          } catch (e) { handleErr(e); }
        });
      });
    } catch (e) { handleErr(e); }
  }));

  $$('[data-purge]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/resellers/${b.dataset.purge}/purge`); toast('پاکسازی شد.'); renderResellers(); }
    catch (e) { handleErr(e); }
  }));

  if (hasResellers && cohort) {
    activateRings(content());
    $$('[data-toggle-churn]', content()).forEach(el => el.addEventListener('click', () => {
      const box = $('#churn-list-box', content());
      box.style.display = box.style.display === 'none' ? '' : 'none';
    }));
  }
}

/* --------------------------------- نمایندگی کمیسیونی (لینک اختصاصی داخل بات) -- */
// بدون حجم و بدون محصول آماده؛ فقط درصد کمیسیون دائمی روی خریدهای مشتریان
// زیرمجموعه، تا وقتی ادمین خودش نمایندگی را غیرفعال کند. مستقل کامل از
// نمایندگی حجمی/سطح ۲ بالا و از درخواست‌های آن (تب renderResellersCreditTab).
async function renderResellersCommissionTab() {
  const [activeRes, pending] = await Promise.all([
    apiGet('/resellers/inline-commissions'),
    apiGet('/resellers/commission-requests?status=pending'),
  ]);
  const active = activeRes.items || [];
  const pendingList = pending.items || [];

  const introHtml = `
    <div class="card" style="padding:18px 20px">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap">
        <div style="min-width:240px">
          <h3 style="margin:0 0 6px">نمایندگی کمیسیونی (لینک اختصاصی داخل بات اصلی)</h3>
          <span class="card-sub">بدون حجم و بدون محصول آماده؛ نماینده فقط یک لینک اختصاصی می‌گیرد و روی هر خرید مشتریانی که با آن لینک وارد شوند، درصدی کمیسیون دائمی به کیف پولش اضافه می‌شود — تا وقتی خودت غیرفعالش کنی. یا خودت مستقیم درصد را تعیین می‌کنی، یا کاربر با یک درصد پیشنهادی درخواست می‌دهد و تو تایید/رد می‌کنی.</span>
        </div>
        <button class="btn btn-primary btn-sm" id="comres-add" style="white-space:nowrap">➕ ساخت مستقیم نماینده جدید</button>
      </div>
    </div>
  `;

  const pendingHtml = `
    <div class="card">
      <div class="card-head"><h3>درخواست‌های در انتظار (${fmt(pendingList.length)})</h3>
        <span class="card-sub">درصد پیشنهادی خودِ کاربر است؛ تایید یعنی همین درصد فعال می‌شود.</span>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>کاربر</th><th>درصد پیشنهادی</th><th>تاریخ</th><th>عملیات</th></tr></thead>
        <tbody>${pendingList.map(r => `<tr>
          <td>${r.username ? `<div>@${esc(r.username)}</div>` : ''}<div class="mono" style="${r.username ? 'opacity:.6;font-size:12px' : ''}">${r.user_id}</div></td>
          <td class="mono">${fmt(r.proposed_percent)}٪</td>
          <td class="mono">${fmtDate ? fmtDate(r.created_at) : esc(r.created_at || '—')}</td>
          <td><div style="display:flex;gap:6px;flex-wrap:wrap">
            <button class="btn btn-sm btn-primary" data-comres-approve="${r.id}">✅ تایید</button>
            <button class="btn btn-sm btn-danger" data-comres-reject="${r.id}">❌ رد</button>
          </div></td>
        </tr>`).join('') || `<tr><td colspan="4" class="empty-state">${svg('empty')}<div>درخواست در انتظاری نیست</div></td></tr>`}</tbody>
      </table></div>
    </div>
  `;

  const activeHtml = `
    <div class="card">
      <div class="card-head"><h3>نماینده‌های کمیسیونی فعال (${fmt(active.length)} نفر)</h3></div>
      <div class="table-wrap"><table>
        <thead><tr><th>کاربر</th><th>درصد کمیسیون</th><th>مشتریان</th><th>خریدهای تسویه‌شده</th><th>مجموع کارمزد</th><th>عملیات</th></tr></thead>
        <tbody>${active.map(r => `<tr>
          <td>${r.username ? `<div>@${esc(r.username)}</div>` : ''}<div class="mono" style="${r.username ? 'opacity:.6;font-size:12px' : ''}">${r.telegram_id}</div></td>
          <td class="mono">${fmt(r.percent)}٪</td>
          <td class="mono">${fmt(r.customers)}</td>
          <td class="mono">${fmt(r.paid_orders)}</td>
          <td class="mono">${fmt(r.total_commission)} تومان</td>
          <td><div style="display:flex;gap:6px;flex-wrap:wrap">
            <button class="btn btn-sm" data-comres-edit="${r.telegram_id}" data-cur-percent="${r.percent}">✏️ درصد</button>
            <button class="btn btn-sm btn-danger" data-comres-disable="${r.telegram_id}">⛔️ غیرفعال</button>
          </div></td>
        </tr>`).join('') || `<tr><td colspan="6" class="empty-state">${svg('empty')}<div>نماینده‌ی کمیسیونیِ فعالی نیست</div></td></tr>`}</tbody>
      </table></div>
    </div>
  `;

  setContent(`
    ${resellersSubtabsHtml()}
    ${introHtml}
    ${pendingHtml}
    ${activeHtml}
  `);
  bindResellersSubtabs(content());

  $('#comres-add', content()).addEventListener('click', openCommissionResellerDirectModal);

  $$('[data-comres-approve]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('این درخواست با همان درصد پیشنهادی تایید شود؟')) return;
    try {
      await apiPost(`/resellers/commission-requests/${b.dataset.comresApprove}/approve`);
      toast('تایید شد.'); renderResellers();
    } catch (e) { handleErr(e); }
  }));

  $$('[data-comres-reject]', content()).forEach(b => b.addEventListener('click', () => {
    openModal('رد درخواست نمایندگی کمیسیونی', `
      <div class="form-grid">
        <input class="input" id="comres-reject-reason" placeholder="دلیل رد (برای کاربر ارسال می‌شود)">
        <button class="btn btn-danger" id="comres-reject-go">رد درخواست</button>
      </div>
    `, (body, close) => {
      $('#comres-reject-go', body).addEventListener('click', async () => {
        const reason = $('#comres-reject-reason', body).value.trim();
        if (!reason) { toast('دلیل رد را وارد کن.', true); return; }
        try {
          await apiPost(`/resellers/commission-requests/${b.dataset.comresReject}/reject`, { reason });
          toast('رد شد و به کاربر اطلاع داده شد.'); close(); renderResellers();
        } catch (e) { handleErr(e); }
      });
    });
  }));

  $$('[data-comres-edit]', content()).forEach(b => b.addEventListener('click', () => {
    openModal(`ویرایش درصد کمیسیون #${b.dataset.comresEdit}`, `
      <div class="form-grid">
        <input class="input" id="comres-edit-percent" type="number" min="1" max="100" value="${b.dataset.curPercent}">
        <button class="btn btn-primary" id="comres-edit-go">ذخیره</button>
      </div>
    `, (body, close) => {
      $('#comres-edit-go', body).addEventListener('click', async () => {
        const percent = Number($('#comres-edit-percent', body).value);
        if (!percent || percent < 1 || percent > 100) { toast('درصد باید بین ۱ تا ۱۰۰ باشد.', true); return; }
        try {
          await apiPut(`/resellers/inline-commissions/${b.dataset.comresEdit}`, { percent });
          toast('درصد به‌روزرسانی شد.'); close(); renderResellers();
        } catch (e) { handleErr(e); }
      });
    });
  }));

  $$('[data-comres-disable]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('نمایندگی کمیسیونی این کاربر غیرفعال شود؟')) return;
    try {
      await apiDelete(`/resellers/inline-commissions/${b.dataset.comresDisable}`);
      toast('غیرفعال شد.'); renderResellers();
    } catch (e) { handleErr(e); }
  }));
}

function openCommissionResellerDirectModal() {
  openModal('ساخت مستقیم نماینده‌ی کمیسیونی', `
    <div class="form-grid">
      <div style="opacity:.7;font-size:12.5px">آیدی عددی تلگرام کاربر را وارد کن؛ کاربر باید قبلاً حداقل یک‌بار بات را استارت کرده باشد. این نمایندگی بدون حجم و بدون محصول آماده است — فقط یک درصد کمیسیون دائمی.</div>
      <input class="input" id="comres-direct-id" type="number" placeholder="آیدی عددی تلگرام">
      <input class="input" id="comres-direct-percent" type="number" min="1" max="100" placeholder="درصد کمیسیون (مثلاً 10)">
      <button class="btn btn-primary" id="comres-direct-go">ساخت نمایندگی</button>
    </div>
  `, (body, close) => {
    $('#comres-direct-go', body).addEventListener('click', async () => {
      const owner_telegram_id = Number($('#comres-direct-id', body).value);
      const percent = Number($('#comres-direct-percent', body).value);
      if (!owner_telegram_id) { toast('آیدی عددی نامعتبر است.', true); return; }
      if (!percent || percent < 1 || percent > 100) { toast('درصد باید بین ۱ تا ۱۰۰ باشد.', true); return; }
      try {
        await apiPost('/resellers/inline-commissions', { owner_telegram_id, percent });
        toast('نمایندگی کمیسیونی ساخته شد.'); close(); renderResellers();
      } catch (e) { handleErr(e); }
    });
  });
}

async function openResellerManageModal(tgId) {
  try {
    const m = await apiGet(`/resellers/${tgId}/manage`);
    const u=m.user, supply=m.supply, inventory=m.inventory||[];
    const products=await apiGet('/reseller-fixed-products');
    openModal(`مدیریت کامل نماینده #${tgId}`, `
      <div class="form-grid">
        <div><b>کاربر:</b> ${esc(u.username ? '@'+u.username : (u.first_name || '—'))} <span class="mono">${tgId}</span></div>
        <input class="input" id="l2-owner-name" value="${esc(u.first_name || '')}" placeholder="نام نماینده">
        <label>مدل تامین</label>
        <select class="input" id="l2-model"><option value="volume_credit" ${supply.model==='volume_credit'?'selected':''}>اعتبار حجمی</option><option value="fixed_product" ${supply.model==='fixed_product'?'selected':''}>محصول آماده</option></select>
        <div id="l2-fixed-wrap"><label>محصولات اختصاص‌یافته</label><div class="form-grid" id="l2-products">${products.map(p=>{ const inv=inventory.find(x=>Number(x.product_id)===Number(p.id)); const checked=!!inv && Number(inv.qty_remaining||0)>0; const qty=checked?Number(inv.qty_remaining):1; return `<label class="admin-list-row" style="cursor:pointer"><span style="display:flex;gap:8px;align-items:center"><input type="checkbox" class="l2-product-check" data-product-id="${p.id}" ${checked?'checked':''}><b>${esc(p.name)}</b></span><input class="input l2-product-qty" data-product-id="${p.id}" type="number" min="0" value="${qty}" style="max-width:110px" onclick="event.stopPropagation()"></label>`; }).join('') || '<div class="hint-text">محصولی موجود نیست.</div>'}</div></div>
        <div><label>پنل نمایندگی</label><select class="input" id="l2-panel"><option value="">پیش‌فرض خودکار</option></select></div>
        <label style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="l2-enabled" ${u.is_reseller?'checked':''}> نمایندگی فعال باشد</label>
        <button class="btn btn-primary" id="l2-save">💾 ذخیره تغییرات</button>
        <hr>
        <div><b>موجودی محصولات</b></div>
        <div id="l2-inventory">${inventory.length ? inventory.map(x=>`<div class="admin-list-row"><div><b>${esc(x.name)}</b><div style="opacity:.65;font-size:12px">${x.qty_remaining} عدد</div></div><div class="admin-list-row-actions"><button class="btn btn-sm" data-l2-inv="${x.product_id}" data-delta="1">+1</button><button class="btn btn-sm" data-l2-inv="${x.product_id}" data-delta="-1">−1</button></div></div>`).join('') : '<div class="hint-text">موجودی محصولی ثبت نشده است.</div>'}</div>
        <div style="display:flex;gap:6px;align-items:center"><select class="input" id="l2-add-product">${products.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select><input class="input" id="l2-add-qty" type="number" value="1" min="1" placeholder="تعداد"><button class="btn" id="l2-add">➕ شارژ</button></div>
        <hr><button class="btn btn-danger" id="l2-delete">🗑 حذف کامل نمایندگی</button>
      </div>`, async (body, close) => {
      const panels=await apiGet('/reseller-panels-lite').catch(()=>[]);
      $('#l2-panel',body).insertAdjacentHTML('beforeend',panels.map(x=>`<option value="${x.id}" ${Number(x.id)===Number(u.reseller_panel_id)?'selected':''}>${esc(x.name)}</option>`).join(''));
      const sync=()=>$('#l2-fixed-wrap',body).style.display=$('#l2-model',body).value==='fixed_product'?'':'none'; sync(); $('#l2-model',body).onchange=sync;
      $('#l2-save',body).onclick=async()=>{ try { const model=$('#l2-model',body).value; const selected=$$('.l2-product-check',body).filter(x=>x.checked).map(ch=>({product_id:Number(ch.dataset.productId),qty:Number($$(`.l2-product-qty[data-product-id="${ch.dataset.productId}"]`,body)[0]?.value||0)})).filter(x=>x.qty>0); if(model==='fixed_product'&&!selected.length){toast('حداقل یک محصول را انتخاب کنید.',true);return;} await api(`/resellers/${tgId}`,{method:"PATCH",body:{owner_name:$('#l2-owner-name',body).value.trim()||null,enabled:$('#l2-enabled',body).checked,supply_model:model,supply_products:model==='fixed_product'?selected:null,panel_server_id:$('#l2-panel',body).value?Number($('#l2-panel',body).value):null}}); toast('ذخیره شد.'); close(); renderResellers(); } catch(e){handleErr(e);} };
      $$('[data-l2-inv]',body).forEach(btn=>btn.onclick=async()=>{try{await apiPost(`/resellers/${tgId}/products/${btn.dataset.l2Inv}/inventory`,{delta:Number(btn.dataset.delta),reason:'تنظیم از پنل مدیریت'}); toast('موجودی به‌روزرسانی شد.'); close(); openResellerManageModal(tgId);}catch(e){handleErr(e);}});
      $('#l2-add',body).onclick=async()=>{try{const q=Number($('#l2-add-qty',body).value); if(!q||q<1)throw Error('تعداد نامعتبر است.'); await apiPost(`/resellers/${tgId}/products/${$('#l2-add-product',body).value}/inventory`,{delta:q,reason:'شارژ محصول از پنل مدیریت'}); toast('موجودی شارژ شد.'); close(); openResellerManageModal(tgId);}catch(e){handleErr(e);}};
      $('#l2-delete',body).onclick=async()=>{if(!confirm('حذف کامل این نماینده و موجودی‌هایش انجام شود؟'))return; try{await apiDelete(`/resellers/${tgId}`);toast('نمایندگی حذف شد.');close();renderResellers();}catch(e){handleErr(e);}};
    }, {wide:true});
  } catch(e){handleErr(e);}
}

function openResellerCreditModal(tgId, parentClose) {
  openModal(`تنظیم اعتبار حجمی #${tgId}`, `
    <div class="form-grid">
      <input class="input" id="credit-delta" type="number" placeholder="مقدار (گیگ، منفی برای کسر)">
      <input class="input" id="credit-reason" placeholder="دلیل (اختیاری)">
      <button class="btn btn-primary" id="credit-save">ثبت</button>
    </div>`, (body, close) => {
    $('#credit-save', body).addEventListener('click', async () => {
      const delta_gb = Number($('#credit-delta', body).value);
      if (!delta_gb) { toast('مقدار نامعتبر است.', true); return; }
      try {
        await apiPost(`/resellers/${tgId}/credit`, { delta_gb, reason: $('#credit-reason', body).value });
        toast('اعتبار به‌روزرسانی شد.'); close(); if (parentClose) parentClose(); renderResellers();
      } catch (e) { handleErr(e); }
    });
  });
}

function openResellerFindModal() {
  openModal('جستجوی کاربر برای نمایندگی', `
    <div class="form-grid">
      <div style="opacity:.7;font-size:12.5px">آیدی عددی تلگرام کاربر را وارد کن؛ کاربر باید قبلاً حداقل یک‌بار بات را استارت کرده باشد.</div>
      <input class="input" id="cres-find-id" type="number" placeholder="آیدی عددی تلگرام">
      <button class="btn btn-primary" id="cres-find-go">جستجو</button>
      <div id="cres-find-result"></div>
    </div>
  `, (body, close) => {
    const doSearch = async () => {
      const id = Number($('#cres-find-id', body).value);
      const box = $('#cres-find-result', body);
      if (!id) { toast('آیدی نامعتبر است.', true); return; }
      box.innerHTML = `<div style="opacity:.6;font-size:13px">در حال جستجو...</div>`;
      try {
        const data = await apiGet(`/users/${id}`);
        const name = data.user.first_name || data.user.username || `#${id}`;
        box.innerHTML = `
          <div class="card" style="padding:14px;margin-top:6px">
            <div style="font-weight:700">${esc(name)} ${data.user.username ? `<span style="opacity:.6;font-weight:400">@${esc(data.user.username)}</span>` : ''}</div>
            <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              <span class="badge ${data.is_reseller ? 'badge-approved' : 'badge-rejected'}">${data.is_reseller ? 'نماینده‌ی فعال' : 'نماینده نیست'}</span>
              <span class="mono" style="font-size:12.5px;opacity:.8">اعتبار فعلی: ${fmt(data.reseller_credit)} گیگ</span>
            </div>
            <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
              <button class="btn btn-sm ${data.is_reseller ? 'btn-danger' : 'btn-primary'}" id="cres-find-toggle">
                ${data.is_reseller ? '⛔️ غیرفعال کردن نمایندگی' : '✅ فعال‌سازی نمایندگی'}
              </button>
              <button class="btn btn-sm" id="cres-find-credit">💳 تنظیم اعتبار</button>
            </div>
          </div>
        `;
        $('#cres-find-toggle', box).addEventListener('click', async () => {
          try {
            await apiPost(`/resellers/${id}/status`, { enabled: !data.is_reseller });
            toast('وضعیت تغییر کرد.'); close(); renderResellers();
          } catch (e) { handleErr(e); }
        });
        $('#cres-find-credit', box).addEventListener('click', () => openResellerCreditModal(id, close));
      } catch (e) {
        box.innerHTML = `
          <div class="empty-state" style="padding:20px 0">
            ${svg('empty')}<div>کاربری با این آیدی پیدا نشد؛ باید حداقل یک‌بار بات را استارت کرده باشد.</div>
          </div>`;
      }
    };
    $('#cres-find-go', body).addEventListener('click', doSearch);
    $('#cres-find-id', body).addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
  });
}

/* ------------------------------------------------------ درخواست‌های نمایندگی -- */
async function renderResellersRequestsTab() {
  const all = await apiGet('/reseller-requests');
  const filtered = resellerReqFilter === 'open' ? all.filter(r => RESELLER_REQ_OPEN.has(r.status))
    : resellerReqFilter === 'all' ? all
    : all.filter(r => r.status === resellerReqFilter);

  setContent(`
    ${resellersSubtabsHtml()}
    <div class="tabs">
      ${[['open', 'باز'], ['all', 'همه'], ['completed', 'تکمیل‌شده'], ['rejected', 'ردشده'], ['cancelled', 'کنسل‌شده']].map(([v, l]) =>
        `<button class="tab-btn ${v === resellerReqFilter ? 'active' : ''}" data-rf="${v}">${l}</button>`).join('')}
    </div>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>#</th><th>سطح</th><th>کاربر</th><th>حجم</th><th>هزینه</th><th>وضعیت</th><th>تاریخ</th><th>عملیات</th></tr></thead>
      <tbody>${filtered.map(r => `<tr>
        <td class="mono">#${r.id}</td>
        <td>${esc(r.tier_title || r.tier_code || '—')}</td>
        <td>${esc(r.username ? '@' + r.username : ('#' + r.user_id))}</td>
        <td class="mono">${fmt(r.volume_gb)} گیگ</td>
        <td class="mono">${r.price_toman ? fmt(r.price_toman) + ' تومان' : '—'}</td>
        <td><span class="badge ${RESELLER_REQ_STATUS_BADGE[r.status] || ''}">${RESELLER_REQ_STATUS_LABEL[r.status] || r.status}</span></td>
        <td class="mono">${fmtDate(r.created_at)}</td>
        <td><button class="btn btn-sm" data-req="${r.id}">مدیریت</button></td>
      </tr>`).join('') || `<tr><td colspan="8" class="empty-state">${svg('empty')}<div>درخواستی در این وضعیت نیست</div></td></tr>`}</tbody>
    </table></div></div>
  `);
  bindResellersSubtabs(content());
  $$('[data-rf]', content()).forEach(b => b.addEventListener('click', () => {
    resellerReqFilter = b.dataset.rf; renderResellersRequestsTab();
  }));
  $$('[data-req]', content()).forEach(b => b.addEventListener('click', () =>
    openResellerRequestModal(all.find(r => r.id === Number(b.dataset.req)))));
}

function openResellerRequestModal(req) {
  const isOpen = RESELLER_REQ_OPEN.has(req.status);
  let actionsHtml = '';
  if (req.status === 'pending_review') {
    actionsHtml = `
      <div><b>هزینه‌ی نمایندگی (تومان)</b></div>
      <input class="input" id="rq-price" type="number" placeholder="مبلغ به تومان">
      ${req.tier_code === 'bronze' ? `<div><b>درصد کمیسیون برنزی</b></div><input class="input" id="rq-percent" type="number" min="1" max="100" placeholder="درصد کمیسیون" value="${req.proposed_percent ?? ''}">` : ''}
      ${req.tier_code === 'silver' ? `<div><b>درصد تخفیف نقره‌ای</b></div><input class="input" id="rq-discount" type="number" min="1" max="100" placeholder="مثلاً 15٪" value="${req.proposed_percent ?? ''}"><div style="opacity:.65;font-size:12px">این درصد برای همین نماینده ثبت می‌شود؛ پلکان خرید عمده می‌تواند تخفیف را بیشتر کند.</div>` : ''}
      <div><b>روش‌های پرداخت مجاز</b></div>
      <div id="rq-methods" style="display:flex;flex-direction:column;gap:6px"></div>
      <div><b>پنل اختصاصی (اختیاری)</b></div>
      <select class="input" id="rq-panel"><option value="">پیش‌فرض خودکار</option></select>
      <button class="btn btn-primary" id="rq-quote">✅ تایید و ارسال هزینه به کاربر</button>
      <button class="btn btn-danger" id="rq-reject">❌ رد درخواست</button>
    `;
  } else if (req.status === 'awaiting_payment_review') {
    actionsHtml = `
      <button class="btn btn-sm" id="rq-receipt">🧾 نمایش رسید پرداخت</button>
      <button class="btn btn-primary" id="rq-payok">✅ تایید پرداخت</button>
      <button class="btn btn-danger" id="rq-payreject">❌ رد پرداخت</button>
    `;
  }
  const cancelHtml = isOpen ? `<hr><button class="btn btn-sm" id="rq-cancel">لغو دستی این درخواست</button>` : '';

  openModal(`درخواست نمایندگی #${req.id}`, `
    <div class="form-grid">
      <div><b>کاربر:</b> ${esc(req.username ? '@' + req.username : '—')} (<span class="mono">${req.user_id}</span>)</div>
      <div><b>حجم درخواستی:</b> ${fmt(req.volume_gb)} گیگ</div>
      ${req.proposed_percent != null ? `<div><b>پیشنهاد کاربر:</b> ${fmt(req.proposed_percent)}٪</div>` : ''}
      ${req.request_text ? `<div><b>توضیحات کاربر:</b> ${esc(req.request_text)}</div>` : ''}
      <div><b>وضعیت:</b> ${RESELLER_REQ_STATUS_LABEL[req.status] || req.status}</div>
      ${req.price_toman ? `<div><b>هزینه‌ی ثبت‌شده:</b> ${fmt(req.price_toman)} تومان</div>` : ''}
      ${req.reject_reason ? `<div><b>دلیل رد:</b> ${esc(req.reject_reason)}</div>` : ''}
      <hr>
      ${actionsHtml || '<div style="opacity:.6">در وضعیت فعلی، عملیاتی جز لغو دستی روی این درخواست ممکن نیست.</div>'}
      ${cancelHtml}
    </div>
  `, (body, close) => {
    if (req.status === 'pending_review') {
      apiGet('/reseller-panels-lite').then(panels => {
        const sel = $('#rq-panel', body);
        if (sel) sel.insertAdjacentHTML('beforeend', panels.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join(''));
      }).catch(() => {});
      if (req.tier_code) apiGet(`/reseller-tiers/${encodeURIComponent(req.tier_code)}/payment-methods`).then(r => {
        const box = $('#rq-methods', body);
        if (!box) return;
        box.innerHTML = r.methods.filter(m => m.enabled).map(m => `<label style="display:flex;gap:8px;align-items:center"><input type="checkbox" class="rq-method" value="${esc(m.key)}" ${r.selected.includes(m.key) ? 'checked' : ''}><span>${esc(m.label)}</span></label>`).join('');
      }).catch(() => {});
      $('#rq-quote', body).addEventListener('click', async () => {
        const price_toman = Number($('#rq-price', body).value);
        const panelVal = $('#rq-panel', body).value;
        if (!price_toman || price_toman <= 0) { toast('مبلغ نامعتبر است.', true); return; }
        try {
          const commission_percent = $('#rq-percent', body) ? Number($('#rq-percent', body).value) || null : null;
          const discount_percent = $('#rq-discount', body) ? Number($('#rq-discount', body).value) || null : null;
          if (req.tier_code === 'silver' && (!discount_percent || discount_percent < 1 || discount_percent > 100)) { toast('درصد تخفیف نقره‌ای را بین ۱ تا ۱۰۰ وارد کنید.', true); return; }
          const payment_methods = $$('.rq-method:checked', body).map(i => i.value);
          const hasMethodBoxes = $$('.rq-method', body).length > 0;
          if (hasMethodBoxes && !payment_methods.length) { toast('حداقل یک روش پرداخت انتخاب کنید.', true); return; }
          await apiPost(`/reseller-requests/${req.id}/quote`, { price_toman, panel_server_id: panelVal ? Number(panelVal) : null, commission_percent, discount_percent, payment_methods: hasMethodBoxes ? payment_methods : null });
          toast('هزینه برای کاربر ارسال شد.'); close(); renderResellers();
        } catch (e) { handleErr(e); }
      });
      $('#rq-reject', body).addEventListener('click', () => openResellerRequestRejectModal(req.id, 'rejected', close));
    } else if (req.status === 'awaiting_payment_review') {
      $('#rq-receipt', body).addEventListener('click', () => showReceiptModal('reseller-request', req.id));
      $('#rq-payok', body).addEventListener('click', async () => {
        try { await apiPost(`/reseller-requests/${req.id}/approve-payment`); toast('پرداخت تایید شد.'); close(); renderResellers(); }
        catch (e) { handleErr(e); }
      });
      $('#rq-payreject', body).addEventListener('click', () => openResellerRequestRejectModal(req.id, 'payment_rejected', close));
    }
    if (isOpen) {
      $('#rq-cancel', body).addEventListener('click', async () => {
        try { await apiPost(`/reseller-requests/${req.id}/cancel`); toast('درخواست کنسل شد.'); close(); renderResellers(); }
        catch (e) { handleErr(e); }
      });
    }
  }, { wide: true });
}

function openResellerRequestRejectModal(requestId, kind, parentClose) {
  openModal('دلیل رد', `
    <div class="form-grid">
      <textarea class="input" id="rq-reject-reason" rows="3" placeholder="دلیل رد (برای کاربر ارسال می‌شود)"></textarea>
      <button class="btn btn-danger" id="rq-reject-confirm">ثبت رد</button>
    </div>
  `, (body, close) => {
    $('#rq-reject-confirm', body).addEventListener('click', async () => {
      const reason = $('#rq-reject-reason', body).value.trim();
      if (!reason) { toast('دلیل رد الزامی است.', true); return; }
      try {
        await apiPost(`/reseller-requests/${requestId}/reject`, { reason, kind });
        toast('ثبت شد.'); close(); parentClose(); renderResellers();
      } catch (e) { handleErr(e); }
    });
  });
}

/* -------------------------------------------------- کوهورت نگهداشت (مشترک) -- */
function renderResellerCohortBlock(data) {
  const c = data.churn;
  const months = data.cohorts.filter(m => m.size > 0);
  const allMonths = months.length ? months[months.length - 1].retention.map(r => r.month) : [];

  const heatRows = months.map(co => {
    const cells = co.retention.map(r => {
      const pct = r.pct;
      const alpha = Math.max(0.08, Math.min(1, pct / 100));
      return `<td class="mono" style="text-align:center;background:rgba(139,92,246,${alpha.toFixed(2)});border-radius:6px">
        ${pct}٪<div style="font-size:10px;opacity:.75">${fmt(r.active)} نفر</div>
      </td>`;
    }).join('');
    const pad = allMonths.length - co.retention.length;
    return `<tr><td class="mono">${co.cohort_month}</td><td class="mono">${fmt(co.size)}</td>${cells}${'<td></td>'.repeat(Math.max(0, pad))}</tr>`;
  }).join('');

  const churnRows = c.list.slice(0, 30).map(u => `
    <tr>
      <td class="mono">${u.telegram_id}</td><td>${esc(u.username || '—')}</td>
      <td class="mono">${fmt(u.credit_gb)}</td>
      <td class="mono">${u.last_activity ? fmtDate(u.last_activity) : 'هیچ‌وقت'}</td>
      <td class="mono">${fmt(u.days_inactive)} روز</td>
    </tr>`).join('') || '<tr><td colspan="5" class="empty-state">نماینده‌ی ریزش‌کرده‌ای نیست 🎉</td></tr>';

  return `
    <div class="grid grid-4">
      <div class="card stat-card">
        <div class="stat-top"><span class="stat-icon stat-icon-1">${svg('resellers')}</span></div>
        <span class="value mono">${fmt(c.total)}</span>
        <span class="label">کل نمایندگان فعلی</span>
      </div>
      <div class="card stat-card">
        <div class="stat-top"><span class="stat-icon stat-icon-2">${svg('check')}</span></div>
        <span class="value mono">${fmt(c.active)}</span>
        <span class="label">فعال (${fmt(c.inactivity_days)} روز اخیر فعالیت داشته‌اند)</span>
      </div>
      <div class="card stat-card" data-toggle-churn style="cursor:pointer">
        <div class="stat-top">
          <span class="stat-icon stat-icon-4">${svg('tickets')}</span>
          <div class="ring" style="--ring-a:var(--rose)" data-pct="${c.churn_rate}"><span>${c.churn_rate}٪</span></div>
        </div>
        <span class="value mono">${fmt(c.churned)}</span>
        <span class="label">ریزش‌کرده (بی‌فعالیت) — کلیک کن تا لیستش را ببینی</span>
      </div>
      <div class="card stat-card">
        <div class="stat-top"><span class="stat-icon stat-icon-3">${svg('users')}</span></div>
        <span class="value mono">${fmt(months.reduce((a, m) => a + m.size, 0))}</span>
        <span class="label">نماینده‌ی جدید در ${fmt(data.cohorts.length)} ماه اخیر</span>
      </div>
    </div>

    ${months.length ? `
    <div class="card">
      <div class="card-head"><h3>کوهورت نگهداشت ماهانه نمایندگان</h3>
        <span class="card-sub">هر ردیف، نماینده‌هایی هستند که در همان ماه فعال شدند. ستون‌های M0, M1, ... یعنی چند درصد از همان گروه در ماه‌های بعدی هم فعالیت (شارژ/مصرف اعتبار) داشته‌اند — رنگ پررنگ‌تر یعنی نگهداشت بهتر.</span>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>ماه فعال‌سازی</th><th>تعداد</th>${allMonths.map((m, i) => `<th class="mono">M${i}</th>`).join('')}</tr></thead>
        <tbody>${heatRows}</tbody>
      </table></div>
    </div>` : ''}

    <div class="card" id="churn-list-box" style="display:none">
      <div class="card-head"><h3>نماینده‌های در آستانه‌ی ریزش / ریزش‌کرده</h3></div>
      <div class="table-wrap"><table>
        <thead><tr><th>آیدی</th><th>یوزرنیم</th><th>اعتبار (گیگ)</th><th>آخرین فعالیت</th><th>مدت بی‌فعالیتی</th></tr></thead>
        <tbody>${churnRows}</tbody>
      </table></div>
    </div>
  `;
}


/* ============================================================== panels === */
const PANEL_TYPE_OPTIONS_HTML = [
  ['pasarguard', 'PasarGuard'], ['3xui', '3X-UI'], ['marzban', 'Marzban'],
  ['marzneshin', 'Marzneshin'], ['hiddify', 'Hiddify'], ['alireza', 'Alireza X-UI'],
  ['rebecca', 'Rebecca'], ['sui', 'S-UI'], ['wgdashboard', 'WGDashboard'], ['mikrotik', 'MikroTik'], ['ibsng', 'IBSng'], ['wui', 'W-UI'], ['stealth', 'Stealth VLESS'],
].map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
const PANEL_INBOUND_SELECT_TYPES = ['3xui', 'alireza'];
const PANEL_SUB_BASE_URL_TYPES = ['3xui', 'hiddify', 'alireza'];
const PANEL_TEMPLATE_BASED_TYPES = ['pasarguard', 'marzban', 'marzneshin', 'rebecca', 'sui', 'wgdashboard', 'mikrotik', 'ibsng', 'wui'];
const PANEL_TOKEN_ONLY_TYPES = ['3xui', 'rebecca', 'sui', 'wgdashboard', 'wui', 'stealth'];
const PANEL_SECRET_PLACEHOLDERS = {
  rebecca: 'توکن ادمین (Bearer token)',
  sui: 'API Token (Admin ← API Token در پنل)',
  wgdashboard: 'API Key (Settings ← API Keys در پنل)',
  wui: 'API Token (Settings ← Authentication ← API Token در پنل)',
  stealth: 'توکن API نود (نصاب در پایان نصب چاپ می‌کند)',
};
const PANEL_TEMPLATE_PLACEHOLDERS = {
  sui: 'نام یک کاربر (client) موجود روی پنل',
  rebecca: 'نام یک کاربر موجود روی پنل',
  wgdashboard: 'نام configuration (مثلا wg0)',
  wui: 'نام یک مشتری (customer) موجود روی پنل',
  mikrotik: 'نام profile در User Manager',
  ibsng: 'نام گروه (Group) در IBSng',
};
const PANEL_TEMPLATE_HINTS = {
  sui: 'inbound های کاربر نمونه برای کاربرهای جدید استفاده می‌شود. فقط API Token لازم است.',
  rebecca: 'سرویس (service) کاربر نمونه برای کاربرهای جدید استفاده می‌شود. فقط توکن لازم است.',
  wgdashboard: 'فقط API Key لازم است. کاربرها به‌صورت peer داخل configuration ساخته می‌شوند و حجم/انقضا با Schedule Job اعمال می‌شود.',
  wui: 'interface های مشتری نمونه برای کاربرهای جدید استفاده می‌شود. فقط API Token لازم است. آدرس API باید شامل Web Base Path پنل باشد.',
  mikrotik: 'حجم و مدت را profile تعیین می‌کند و مقدار حجم/مدت محصول اعمال نمی‌شود. یوزر/پس ادمین روتر (REST API) لازم است.',
  ibsng: 'حجم و مدت را گروه تعیین می‌کند و مقدار حجم/مدت محصول اعمال نمی‌شود. یوزر/پس ادمین IBSng لازم است.',
};

// ---- نصب خودکار نود Stealth VLESS (مشترک بین «پنل‌ها» و «نودها و سهمیه SSH») ----
function stealthAutoBoxHtml(withName) {
  return `
    ${withName ? '<input class="input" id="sa-name" placeholder="نام نود (مثلاً Stealth-1)" maxlength="80">' : ''}
    <div class="form-grid">
      <input class="input" id="sa-host" placeholder="آی‌پی سرور" dir="ltr">
      <input class="input" id="sa-port" type="number" min="1" max="65535" value="22" placeholder="پورت SSH">
      <input class="input" id="sa-pass" type="password" autocomplete="off" placeholder="رمز root" dir="ltr">
      <input class="input" id="sa-domain" placeholder="دامنه نود (cdn.example.com)" dir="ltr">
      <select class="input" id="sa-decoy"><option value="movie">سایت جعلی: تماشای فیلم (ساختگی)</option><option value="proxy">سایت جعلی: آینه‌ی یک سایت واقعی</option></select>
      <input class="input" id="sa-proxy" placeholder="آدرس سایت واقعی (https://...)" dir="ltr" style="display:none">
      <select class="input" id="sa-cert"><option value="letsencrypt">گواهی Let's Encrypt (دامنه باید به سرور اشاره کند)</option><option value="self">گواهی خودامضا (کلادفلر باید روی Full باشد)</option></select>
      <input class="input" id="sa-email" type="email" placeholder="ایمیل (برای Let's Encrypt)" dir="ltr">
      <input class="input" id="sa-pubport" type="number" value="443" placeholder="پورت عمومی (443)">
      <div style="display:flex;gap:12px;flex-wrap:wrap;font-size:13px">
        <label><input type="checkbox" class="sa-tr" value="ws" checked> WebSocket</label>
        <label><input type="checkbox" class="sa-tr" value="httpupgrade" checked> HTTPUpgrade</label>
        <label><input type="checkbox" class="sa-tr" value="grpc" checked> gRPC</label>
        <label><input type="checkbox" class="sa-tr" value="xhttp"> xhttp (stream-one)</label>
      </div>
      <button class="btn btn-primary" id="sa-install" type="button">نصب و راه‌اندازی خودکار</button>
    </div>
    <pre id="sa-log" class="mono" style="display:none;white-space:pre-wrap;margin-top:8px"></pre>
    <p class="card-sub">سرور باید Ubuntu/Debian تازه باشد. xray (فقط VLESS)، nginx، سایت جعلی، گواهی TLS و ثبت در پنل خودکار انجام می‌شود. رمز root فقط برای همین نصب استفاده می‌شود و ذخیره نمی‌شود. بعد از نصب، نود در همین بخش «نودها و سهمیه SSH» و همچنین «پنل‌های VPN» با نوع Stealth VLESS قابل مدیریت و انتخاب برای ساخت محصول است.</p>`;
}

function wireStealthAutoBox(root, getName, onDone) {
  const saDecoy = $('#sa-decoy', root);
  saDecoy.addEventListener('change', () => { $('#sa-proxy', root).style.display = saDecoy.value === 'proxy' ? '' : 'none'; });
  $('#sa-install', root).addEventListener('click', e => {
    const btn = e.currentTarget, logEl = $('#sa-log', root);
    const v = id => $(id, root).value.trim();
    const name = getName();
    const transports = [...root.querySelectorAll('.sa-tr:checked')].map(i => i.value);
    if (!name || !v('#sa-host') || !$('#sa-pass', root).value || !v('#sa-domain')) return toast('نام، آی‌پی، رمز root و دامنه را وارد کنید.', true);
    if (!transports.length) return toast('حداقل یک ترنسپورت را تیک بزنید.', true);
    sshRunInstallJob(root, btn, logEl, () => apiPost('/stealth/nodes/auto-install', {
      name, host: v('#sa-host'), ssh_port: Number(v('#sa-port')) || 22, password: $('#sa-pass', root).value,
      domain: v('#sa-domain'), decoy: saDecoy.value, proxy_url: v('#sa-proxy') || null, cert: v('#sa-cert'),
      email: v('#sa-email'), transports, port: Number(v('#sa-pubport')) || 443,
    }), onDone, '/stealth/nodes/install-jobs');
  });
}

function panelAddFormHtml() {
  return `
    <div class="form-grid">
      <input class="input" id="p-name" placeholder="نام (مثلا سرور آلمان)">
      <select class="input" id="p-type">${PANEL_TYPE_OPTIONS_HTML}</select>
      <input class="input" id="p-url" placeholder="آدرس پنل (https://...)">
      <div class="form-row"><input class="input" id="p-user" placeholder="یوزرنیم"><input class="input" id="p-pass" type="password" placeholder="پسورد"></div>
      <input class="input" id="p-template" placeholder="نام کاربری نمونه (برای دریافت قالب)" style="display:none">
      <p id="p-hint" style="display:none;font-size:12px;color:var(--muted,#8892a6);margin:0"></p>
      <select class="input" id="p-cat"><option value="">🗂 بدون دسته‌بندی</option>${(window.__panelCats || []).map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select>
      <button class="btn btn-primary" id="p-save">ثبت</button>
    </div>
    <div id="p-stealth-auto" class="card" style="display:none;padding:12px;margin-top:6px">
      <b>⚡ نصب خودکار نود Stealth روی سرور جدید</b>
      <p class="card-sub">نام را در فیلد بالای فرم بنویسید؛ فیلدهای آدرس/توکن بالا برای نصب خودکار لازم نیست.</p>
      ${stealthAutoBoxHtml(false)}
    </div>`;
}

function wirePanelAddForm(body, close) {
  const typeSel = $('#p-type', body), userInp = $('#p-user', body), passInp = $('#p-pass', body), hint = $('#p-hint', body), templateInp = $('#p-template', body);
  function syncTypeUI() {
    const t = typeSel.value;
    templateInp.style.display = 'none';
    const autoBox = $('#p-stealth-auto', body);
    if (autoBox) autoBox.style.display = t === 'stealth' ? '' : 'none';
    if (t === 'stealth') {
      userInp.style.display = 'none'; userInp.value = '';
      passInp.placeholder = PANEL_SECRET_PLACEHOLDERS.stealth;
      hint.style.display = 'block';
      hint.textContent = 'اگر نود را قبلاً با نصاب نصب کرده‌اید، آدرس API و توکن را وارد و «ثبت» بزنید؛ در غیر این صورت از بخش «نصب خودکار» پایین استفاده کنید.';
    } else if (t === '3xui') {
      userInp.style.display = 'none'; userInp.value = '';
      passInp.placeholder = 'API Token (Settings ← Security در پنل)';
      hint.style.display = 'block';
      hint.textContent = '3X-UI جدید فقط با API Token کار می‌کند؛ یوزرنیم لازم نیست. بعد از ثبت باید inbound و لینک Subscription را هم تنظیم کنی.';
    } else if (t === 'hiddify') {
      userInp.style.display = ''; userInp.placeholder = 'هر مقداری (استفاده نمی‌شود)';
      passInp.placeholder = 'Hiddify API Key (UUID ادمین)';
      hint.style.display = 'block';
      hint.textContent = 'Hiddify یوزر/پس ندارد؛ فقط API Key لازم است. بعد از ثبت لینک Subscription را هم می‌پرسیم.';
    } else if (t === 'alireza') {
      userInp.style.display = ''; userInp.placeholder = 'یوزرنیم';
      passInp.placeholder = 'پسورد';
      hint.style.display = 'block';
      hint.textContent = 'فقط یک inbound قابل انتخاب است. بعد از ثبت باید inbound و لینک Subscription را هم تنظیم کنی.';
    } else {
      const tokenOnly = PANEL_TOKEN_ONLY_TYPES.includes(t);
      userInp.style.display = tokenOnly ? 'none' : ''; userInp.placeholder = 'یوزرنیم';
      if (tokenOnly) userInp.value = '';
      passInp.placeholder = PANEL_SECRET_PLACEHOLDERS[t] || 'پسورد';
      hint.style.display = 'block';
      templateInp.style.display = '';
      templateInp.placeholder = PANEL_TEMPLATE_PLACEHOLDERS[t] || 'نام کاربری نمونه (برای دریافت قالب)';
      hint.textContent = PANEL_TEMPLATE_HINTS[t] || 'یک نام کاربری که از قبل روی این پنل ساخته شده را وارد کن؛ تنظیمات (گروه/پروکسی) او به‌عنوان قالب برای کاربرهای جدید استفاده می‌شود.';
    }
  }
  typeSel.addEventListener('change', syncTypeUI);
  syncTypeUI();
  if ($('#sa-install', body)) wireStealthAutoBox(body, () => $('#p-name', body).value.trim(), () => { close(); renderPanels(); });

  $('#p-save', body).addEventListener('click', async () => {
    const name = $('#p-name', body).value.trim(), api_url = $('#p-url', body).value.trim();
    const panel_type = typeSel.value;
    if (!name || !api_url) return toast('نام و آدرس الزامی است.', true);
    if (!passInp.value.trim()) return toast(PANEL_TOKEN_ONLY_TYPES.includes(panel_type) ? 'API Token الزامی است.' : 'رمز/کلید الزامی است.', true);
    if (PANEL_TEMPLATE_BASED_TYPES.includes(panel_type) && !templateInp.value.trim()) {
      return toast(PANEL_TEMPLATE_PLACEHOLDERS[panel_type] ? 'مقدار قالب الزامی است.' : 'نام کاربری نمونه الزامی است.', true);
    }
    let serverId, warning = '';
    try {
      const r = await apiPost('/panel-servers', {
        name, panel_type, api_url,
        api_username: userInp.value, api_password: passInp.value,
        panel_category_id: Number($('#p-cat', body)?.value) || undefined,
        template_username: PANEL_TEMPLATE_BASED_TYPES.includes(panel_type) ? templateInp.value.trim() : undefined,
      });
      serverId = r.id; warning = r.warning || '';
    } catch (e) { return handleErr(e); }

    if (PANEL_INBOUND_SELECT_TYPES.includes(panel_type)) return finishXuiInboundSetup(serverId, close);
    if (PANEL_SUB_BASE_URL_TYPES.includes(panel_type)) return askPanelSubBaseUrl(serverId, close);
    toast(warning ? ('پنل اضافه شد.\n' + warning) : 'پنل اضافه شد.'); close(); renderPanels();
  });
}

async function finishXuiInboundSetup(serverId, closeParent) {
  let inbounds;
  try {
    inbounds = await apiGet(`/panel-servers/${serverId}/inbounds`);
  } catch (e) {
    toast('پنل ذخیره شد ولی دریافت لیست inbound ناموفق بود: ' + e.message, true);
    closeParent(); renderPanels();
    return;
  }
  if (!inbounds.length) {
    toast('این پنل هیچ inbound ای ندارد؛ اول از داخل پنل یک inbound بساز، بعد دوباره تلاش کن.', true);
    try { await apiDelete(`/panel-servers/${serverId}?force=true`); } catch (e) { /* ignore */ }
    closeParent(); renderPanels();
    return;
  }
  closeParent();
  openXuiInboundModal(serverId, inbounds, [], '');
}

function openXuiInboundModal(serverId, inbounds, selectedIds, subBaseUrl) {
  const selected = new Set(selectedIds || []);
  openModal('انتخاب Inbound', `
    <div class="form-grid">
      <p style="margin:0">کدام inbound(ها) برای ساخت کاربرهای جدید استفاده شود؟ (می‌توانی چند مورد را تیک بزنی)</p>
      <div id="p-inbound-list" style="display:flex;flex-direction:column;gap:6px;max-height:220px;overflow:auto">
        ${inbounds.map(ib => `
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" class="p-inbound-cb" value="${ib.id}" ${selected.has(ib.id) ? 'checked' : ''}>
            <span>#${ib.id} ${esc(ib.remark || '')} (${esc(ib.protocol)}:${ib.port})</span>
          </label>`).join('')}
      </div>
      <input class="input" id="p-suburl" placeholder="لینک پایه‌ی Subscription (https://...)" value="${esc(subBaseUrl || '')}">
      <button class="btn btn-primary" id="p-inbound-save">ثبت</button>
    </div>`, (body2, close2) => {
    $('#p-inbound-save', body2).addEventListener('click', async () => {
      const suburl = $('#p-suburl', body2).value.trim();
      const inbound_ids = $$('.p-inbound-cb', body2).filter(cb => cb.checked).map(cb => parseInt(cb.value, 10));
      if (!suburl) return toast('لینک Subscription الزامی است.', true);
      if (!inbound_ids.length) return toast('حداقل یک inbound را تیک بزن.', true);
      try {
        await apiPut(`/panel-servers/${serverId}`, { xui_inbound_ids: inbound_ids, xui_sub_base_url: suburl });
        toast('پنل تنظیم شد.'); close2(); renderPanels();
      } catch (e) { handleErr(e); }
    });
  });
}

function askPanelSubBaseUrl(serverId, closeParent) {
  closeParent();
  openModal('لینک Subscription', `
    <div class="form-grid">
      <p style="margin:0">لینک پایه‌ی Subscription این پنل را وارد کن:</p>
      <input class="input" id="p-suburl" placeholder="https://...">
      <button class="btn btn-primary" id="p-suburl-save">ثبت</button>
    </div>`, (body2, close2) => {
    $('#p-suburl-save', body2).addEventListener('click', async () => {
      const suburl = $('#p-suburl', body2).value.trim();
      if (!suburl) return toast('لینک Subscription الزامی است.', true);
      try {
        await apiPut(`/panel-servers/${serverId}`, { xui_sub_base_url: suburl });
        toast('پنل تنظیم شد.'); close2(); renderPanels();
      } catch (e) { handleErr(e); }
    });
  });
}

function wirePanelDeleteButtons() {
  $$('[data-del]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('حذف شود؟')) return;
    try {
      await apiDelete(`/panel-servers/${b.dataset.del}`); toast('حذف شد.'); renderPanels();
    } catch (e) {
      if (e.status === 409) {
        if (confirm(e.message + '\n\nحذف کامل (همراه با کانفیگ‌های مرتبط) انجام شود؟')) {
          try { await apiDelete(`/panel-servers/${b.dataset.del}?force=true`); toast('حذف شد.'); renderPanels(); } catch (e2) { handleErr(e2); }
        }
      } else handleErr(e);
    }
  }));
}

function panelHealthHtml(s) {
  if (!s.is_active || !s.health_status) return '';
  const down = s.health_status === 'down';
  const when = s.health_last_check
    ? new Date(s.health_last_check).toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit' }) : '';
  const tip = down && s.health_error ? ` title="${esc(s.health_error)}"` : '';
  return `<div${tip} style="font-size:11px;margin-top:4px;color:${down ? '#FB7185' : '#34D399'}">${down ? '🔴 قطع' : '🟢 آنلاین'}${when ? ' · آخرین بررسی ' + when : ''}</div>`;
}

function wirePanelReorder(servers) {
  $$(`[data-move-up], [data-move-down]`, content()).forEach(b => b.addEventListener('click', async () => {
    const id = Number(b.dataset.moveUp || b.dataset.moveDown);
    const idx = servers.findIndex(s => s.id === id);
    if (idx < 0) return;
    const target = b.dataset.moveUp ? idx - 1 : idx + 1;
    if (target < 0 || target >= servers.length) return;
    const ids = servers.map(s => s.id);
    [ids[idx], ids[target]] = [ids[target], ids[idx]];
    b.disabled = true;
    try { await apiPost('/panel-servers/reorder', { server_ids: ids }); toast('ترتیب سرورها ذخیره شد.'); renderPanels(); }
    catch (e) { handleErr(e); }
    finally { b.disabled = false; }
  }));
}

let sshTab = 'nodes';
const SSH_PROTO_LABELS = { ssh: 'SSH', openvpn: 'OpenVPN', wireguard: 'WireGuard' };
function sshProtoFieldsHtml(installed = []) {
  const box = (key, checked) => `<label style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-ssh-proto="${key}" ${installed.includes(key) ? 'checked disabled' : (checked ? 'checked' : '')}> ${SSH_PROTO_LABELS[key]}${installed.includes(key) ? ' <span class="card-sub">(نصب شده)</span>' : ''}</label>`;
  return `<div class="field"><span>پروتکل‌ها (تیک بزنید)</span>${box('ssh', !installed.length)}${box('openvpn', false)}${box('wireguard', false)}</div>
    <div data-ssh-ovpn-opts style="display:none" class="form-grid">
      <label class="field"><span>پورت OpenVPN</span><input class="input" data-ssh-ovpn-port type="number" min="1" max="65535" value="1194" dir="ltr"></label>
      <label class="field"><span>انتقال OpenVPN</span><select class="input" data-ssh-ovpn-proto><option value="udp">UDP (سریع‌تر)</option><option value="tcp">TCP (عبور بهتر از فیلتر)</option></select></label>
    </div>
    <div data-ssh-wg-opts style="display:none" class="form-grid">
      <label class="field"><span>پورت WireGuard (UDP)</span><input class="input" data-ssh-wg-port type="number" min="1" max="65535" value="51820" dir="ltr"></label>
    </div>`;
}
function sshBindProtoFields(el) {
  const sync = () => {
    const on = el.querySelector('[data-ssh-proto="openvpn"]:not(:disabled)')?.checked; const o = el.querySelector('[data-ssh-ovpn-opts]'); if (o) o.style.display = on ? '' : 'none';
    const wgOn = el.querySelector('[data-ssh-proto="wireguard"]:not(:disabled)')?.checked; const w = el.querySelector('[data-ssh-wg-opts]'); if (w) w.style.display = wgOn ? '' : 'none';
  };
  el.querySelectorAll('[data-ssh-proto]').forEach(c => c.addEventListener('change', sync));
  sync();
}
function sshReadProtoFields(el) {
  const protocols = [...el.querySelectorAll('[data-ssh-proto]:not(:disabled)')].filter(c => c.checked).map(c => c.dataset.sshProto);
  return { protocols, ovpn_port: Number(el.querySelector('[data-ssh-ovpn-port]')?.value) || 1194, ovpn_proto: el.querySelector('[data-ssh-ovpn-proto]')?.value || 'udp', wg_port: Number(el.querySelector('[data-ssh-wg-port]')?.value) || 51820 };
}
async function sshRunInstallJob(el, btn, logEl, startRequest, onDone, jobBase = '/ssh/nodes/install-jobs') {
  btn.disabled = true; logEl.style.display = ''; logEl.textContent = 'شروع نصب...';
  try {
    const r = await startRequest();
    el.querySelectorAll('input[type=password]').forEach(i => { i.value = ''; });
    for (let i = 0; i < 400; i++) {
      await new Promise(res => setTimeout(res, 2000));
      const j = await apiGet(`${jobBase}/${r.job_id}`);
      logEl.textContent = (j.log || []).join('\n');
      if (j.status === 'done') { toast(j.warning ? ('نصب شد؛ ' + j.warning) : 'نصب با موفقیت انجام شد.', !!j.warning); onDone(); return; }
      if (j.status === 'error') { logEl.textContent += '\n❌ ' + (j.error || 'خطا'); toast(j.error || 'نصب ناموفق بود.', true); btn.disabled = false; return; }
    }
    toast('نصب طولانی شد؛ بعداً وضعیت نودها را بررسی کنید.', true); btn.disabled = false;
  } catch (err) { handleErr(err); btn.disabled = false; }
}
function sshHostsModal(node, reload) {
  const protos = node.protocols || ['ssh'];
  const hosts = (node.hosts || []).map(h => ({ ...h }));
  const hasSsh = protos.includes('ssh');
  const protoSelect = (val) => `<select class="input" data-h="protocol">${protos.map(p => `<option value="${p}"${p === val ? ' selected' : ''}>${esc(SSH_PROTO_LABELS[p] || p)}</option>`).join('')}</select>`;
  const hostRow = (h, i) => `<div class="card" style="padding:10px;margin-bottom:8px" data-host-row="${i}">
    <div class="form-grid">
      <label class="field"><span>پروتکل</span>${protoSelect(h.protocol)}</label>
      <label class="field"><span>عنوان (اختیاری؛ به نام کانفیگ اضافه می‌شود)</span><input class="input" data-h="remark" maxlength="60" value="${esc(h.remark || '')}"></label>
      <label class="field"><span>آدرس (دامنه یا IP؛ مثلاً سرور تانل)</span><input class="input" data-h="address" dir="ltr" value="${esc(h.address || '')}" placeholder="tunnel.example.com"></label>
      <label class="field"><span>پورت (خالی = پورت خود نود)</span><input class="input" data-h="port" type="number" min="1" max="65535" dir="ltr" value="${h.port ? Number(h.port) : ''}" ${h.protocol === 'ssh' ? 'disabled placeholder="هر حساب پورت اختصاصی دارد"' : ''}></label>
      <label class="field" style="flex-direction:row;gap:8px;align-items:center"><input type="checkbox" data-h="enabled" ${h.enabled !== false ? 'checked' : ''}><span>فعال</span></label>
      <button class="btn btn-danger btn-sm" data-host-del="${i}">حذف هاست</button>
    </div></div>`;
  const body = `
    <p class="card-sub">آدرس واقعی نود (<span class="mono" dir="ltr">${esc(node.host)}</span>) تغییر نمی‌کند؛ هاست‌ها فقط آدرسِ نمایش‌داده‌شده در لینک/فایل کاربر را عوض می‌کنند و روی حساب‌های قدیمی هم اعمال می‌شوند. اگر برای یک پروتکل چند هاست فعال بگذارید، برای هر کدام یک لینک/فایل ساخته می‌شود. بدون هاست فعال، همان آدرس نود استفاده می‌شود.</p>
    <div id="ssh-hosts-list"></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
      <button class="btn btn-sm" id="ssh-host-add">+ هاست جدید</button>
      <button class="btn btn-primary btn-sm" id="ssh-hosts-save">ذخیره هاست‌ها</button>
    </div>
    ${hasSsh ? `<div class="card" style="padding:10px">
      <b>بازه‌ی پورت حساب‌های SSH</b>
      <p class="card-sub">هر حساب SSH یک پورت اختصاصی روی نود می‌گیرد (حسابداری حجم بر اساس پورت است). از این بازه برای حساب‌های جدید انتخاب می‌شود. برای پورت ثابت، شروع و پایان را یکی بگذارید (فقط یک حساب جا می‌شود). حساب‌های قبلی تغییر نمی‌کنند. Agent نود باید نسخه‌ی جدید باشد.</p>
      <div class="form-grid">
        <label class="field"><span>از پورت</span><input class="input" id="ssh-range-min" type="number" min="1024" max="65535" dir="ltr" value="${Number(node.ssh_port_min)}"></label>
        <label class="field"><span>تا پورت</span><input class="input" id="ssh-range-max" type="number" min="1024" max="65535" dir="ltr" value="${Number(node.ssh_port_max)}"></label>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-primary btn-sm" id="ssh-range-save">ذخیره بازه</button>
        <button class="btn btn-sm" id="ssh-range-reset">بازگشت به پیش‌فرض (20000-39999)</button>
      </div>
      <p class="card-sub" id="ssh-range-note">اگر ufw روی نود فعال باشد، Agent بازه‌ی جدید را خودش باز می‌کند؛ در غیر این صورت فایروال/Security Group را دستی باز کنید.</p>
    </div>` : ''}`;
  openModal(`هاست‌های نود «${esc(node.name)}»`, body, (el, close) => {
    const listEl = el.querySelector('#ssh-hosts-list');
    const readRows = () => $$('[data-host-row]', el).map((row, i) => {
      const g = k => row.querySelector(`[data-h="${k}"]`);
      const protocol = g('protocol').value;
      const portRaw = g('port').value.trim();
      return { id: hosts[i]?.id || null, protocol, remark: g('remark').value.trim(), address: g('address').value.trim(),
               port: protocol === 'ssh' || !portRaw ? null : Number(portRaw), enabled: g('enabled').checked };
    });
    const draw = () => {
      listEl.innerHTML = hosts.length ? hosts.map(hostRow).join('') : '<div class="empty-state">هاستی تعریف نشده؛ آدرس خود نود استفاده می‌شود.</div>';
      $$('[data-host-del]', listEl).forEach(b => b.addEventListener('click', () => { sync(); hosts.splice(Number(b.dataset.hostDel), 1); draw(); }));
      $$('[data-h="protocol"]', listEl).forEach(sel => sel.addEventListener('change', () => { sync(); draw(); }));
    };
    const sync = () => { readRows().forEach((r, i) => { hosts[i] = r; }); };
    draw();
    el.querySelector('#ssh-host-add').addEventListener('click', () => {
      sync();
      hosts.push({ id: null, protocol: protos[0], remark: '', address: '', port: null, enabled: true });
      draw();
    });
    el.querySelector('#ssh-hosts-save').addEventListener('click', async e => {
      const btn = e.currentTarget; const payload = readRows();
      btn.disabled = true;
      try { await apiPut(`/ssh/nodes/${Number(node.id)}/hosts`, { hosts: payload }); toast('هاست‌ها ذخیره شد.'); close(); await reload(); }
      catch (err) { handleErr(err); btn.disabled = false; }
    });
    const saveRange = async (min, max, btn) => {
      btn.disabled = true;
      try {
        const r = await apiPut(`/ssh/nodes/${Number(node.id)}/ssh-port-range`, { port_min: min, port_max: max });
        toast(`بازه‌ی پورت SSH ذخیره شد (${r.ssh_port_min}-${r.ssh_port_max}، ظرفیت ${r.capacity} حساب).`);
        close(); await reload();
      } catch (err) { handleErr(err); btn.disabled = false; }
    };
    el.querySelector('#ssh-range-save')?.addEventListener('click', e => saveRange(Number(el.querySelector('#ssh-range-min').value), Number(el.querySelector('#ssh-range-max').value), e.currentTarget));
    el.querySelector('#ssh-range-reset')?.addEventListener('click', e => saveRange(null, null, e.currentTarget));
  }, { wide: true });
}
async function stealthNodeSettingsModal(node, reload) {
  let settings;
  try { settings = await apiGet(`/panel-servers/${Number(node.id)}/stealth-settings`); }
  catch (err) { handleErr(err); return; }
  openModal(`تنظیمات نود VLESS «${esc(node.name)}»`, `
    <div class="form-grid">
      <div class="card-sub" style="grid-column:1/-1">مشخصات نصب‌شده: <b dir="ltr">${esc(settings.domain || '—')}:${Number(settings.port || 443)}</b> · ترنسپورت‌ها: ${(settings.transports || []).map(esc).join('، ') || '—'}</div>
      <label class="field"><span>نام نود در پنل</span><input class="input" id="vless-set-name" maxlength="80" value="${esc(node.name || '')}"></label>
      <label class="field"><span>آدرس API</span><input class="input" id="vless-set-url" dir="ltr" value="${esc(node.api_url || '')}"></label>
      <label class="field"><span>نام کاربری API</span><input class="input" id="vless-set-user" dir="ltr" value="stealth"></label>
      <label class="field"><span>توکن API جدید (اختیاری)</span><input class="input" id="vless-set-token" type="password" autocomplete="new-password" placeholder="برای حفظ توکن فعلی خالی بگذارید" dir="ltr"></label>
      <button class="btn" id="vless-set-connection">ذخیره اتصال پنل</button>
      <div class="divider" style="grid-column:1/-1"></div>
      <label class="field"><span>عنوان نمایشی لینک‌ها</span><input class="input" id="vless-set-title" maxlength="40" value="${esc(settings.title || 'Stealth')}"></label>
      <label class="field"><span>Fingerprint</span><select class="input" id="vless-set-fp">${['chrome','firefox','safari','random','randomized'].map(x=>`<option value="${x}" ${settings.fingerprint===x?'selected':''}>${x}</option>`).join('')}</select></label>
      <label class="field"><span>SNI</span><input class="input" id="vless-set-sni" dir="ltr" value="${esc(settings.sni || settings.domain || '')}"></label>
      <label class="field"><span>Host / Authority</span><input class="input" id="vless-set-host" dir="ltr" value="${esc(settings.host || settings.domain || '')}"></label>
      <p class="card-sub" style="grid-column:1/-1">تغییر عنوان، Fingerprint، SNI و Host روی لینک‌های جدید اشتراک اعمال می‌شود. دامنه، پورت، گواهی TLS و ترنسپورت‌ها در حال حاضر از طریق نصب/بازپیکربندی سرور تغییر می‌کنند.</p>
      <button class="btn btn-primary" id="vless-set-save">ذخیره تنظیمات نود</button>
    </div>`, (el, close) => {
      el.querySelector('#vless-set-connection').addEventListener('click', async e => {
        const btn=e.currentTarget; btn.disabled=true;
        const body={name:el.querySelector('#vless-set-name').value.trim(),api_url:el.querySelector('#vless-set-url').value.trim(),api_username:el.querySelector('#vless-set-user').value.trim()||'stealth'};
        const token=el.querySelector('#vless-set-token').value;
        if(token) body.api_password=token;
        if(!body.name||!/^https?:\/\//i.test(body.api_url)){toast('نام و آدرس معتبر API را وارد کنید.',true);btn.disabled=false;return;}
        try { await apiPut(`/panel-servers/${Number(node.id)}`,body); toast('اتصال پنل ذخیره شد.'); await reload(); }
        catch(err){handleErr(err);btn.disabled=false;}
      });
      el.querySelector('#vless-set-save').addEventListener('click', async e => {
        const btn=e.currentTarget; btn.disabled=true;
        const body={title:el.querySelector('#vless-set-title').value.trim(),fingerprint:el.querySelector('#vless-set-fp').value,sni:el.querySelector('#vless-set-sni').value.trim(),host:el.querySelector('#vless-set-host').value.trim()};
        try { await apiPut(`/panel-servers/${Number(node.id)}/stealth-settings`,body); toast('تنظیمات نود VLESS ذخیره شد.'); close(); await reload(); }
        catch(err){handleErr(err);btn.disabled=false;}
      });
    }, { wide: true });
}
async function renderSSHManagement() {
  const [d, panelServers] = await Promise.all([apiGet('/ssh/overview'), apiGet('/panel-servers').catch(() => [])]);
  const nodes = d.nodes || [], pools = d.pools || [], accounts = d.accounts || [];
  const vlessNodes = (panelServers || []).filter(s => s.panel_type === 'stealth');
  const fmtBytes = n => {
    n = Number(n || 0);
    if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
    return `${(n / 1024 ** 3).toFixed(2)} GB`;
  };
  const statusFa = s => ({active:'فعال',pending:'در انتظار',error:'خطا',degraded:'ناپایدار',disabled:'غیرفعال',stale:'داده قدیمی',exceeded:'سهمیه تمام‌شده',quota_exceeded:'سهمیه تمام‌شده',expired:'منقضی',deleted:'حذف‌شده'}[s] || s || 'نامشخص');
  const tabs = [['nodes','نودها',nodes.length],['accounts','حساب‌ها',accounts.length],['pools','استخرها',pools.length]];
  const tabBar = `<div class="toolbar" style="gap:8px;flex-wrap:wrap">${tabs.map(([k,l,c])=>`<button class="btn btn-sm ${sshTab===k?'btn-primary':''}" data-ssh-tab="${k}">${l} (${c})</button>`).join('')}<span style="flex:1"></span>${
    sshTab==='nodes' ? '<button class="btn btn-primary btn-sm" id="ssh-add-node">+ افزودن نود</button> <button class="btn btn-sm" id="ssh-add-stealth">+ نود Stealth VLESS</button>' :
    sshTab==='accounts' ? '<button class="btn btn-primary btn-sm" id="ssh-add-account">+ ساخت حساب</button>' :
    '<button class="btn btn-sm" id="ssh-reconcile">پایش و اعمال سهمیه</button><button class="btn btn-sm" id="ssh-attach-open">اتصال VPN به استخر</button><button class="btn btn-primary btn-sm" id="ssh-add-pool">+ ساخت استخر</button>'}</div>`;

  const nodesHtml = `<div class="card"><div class="table-wrap"><table>
    <thead><tr><th>نام</th><th>آدرس</th><th>پروتکل‌ها</th><th>وضعیت</th><th>عملیات</th></tr></thead>
    <tbody>${nodes.map(n=>`<tr>
      <td>${esc(n.name)}</td>
      <td class="mono" style="direction:ltr;text-align:right">${esc(n.host)}:${Number(n.port)}${(n.hosts||[]).filter(h=>h.enabled!==false).map(h=>`<div style="font-size:11px;opacity:.8">↪ ${esc(SSH_PROTO_LABELS[h.protocol]||h.protocol)}: ${esc(h.address)}${h.port?':'+Number(h.port):''}</div>`).join('')}</td>
      <td>${(n.protocols||['ssh']).map(p=>`<span class="chip">${esc(SSH_PROTO_LABELS[p]||p)}${p==='openvpn'&&n.ovpn_port?` · ${Number(n.ovpn_port)}/${esc(n.ovpn_proto||'udp')}`:''}${p==='wireguard'&&n.wg_port?` · ${Number(n.wg_port)}/udp`:''}${p==='ssh'&&n.ssh_port_custom?` · ${Number(n.ssh_port_min)}-${Number(n.ssh_port_max)}`:''}</span>`).join(' ')}</td>
      <td>${esc(statusFa(n.status))}${n.last_error ? `<div style="font-size:11px;color:#FB7185;margin-top:4px">${esc(n.last_error)}</div>` : ''}</td>
      <td><button class="btn btn-sm" data-ssh-test-node="${Number(n.id)}">تست اتصال</button> ${(n.protocols||['ssh']).length<3&&n.node_type==='linux'?`<button class="btn btn-sm" data-ssh-add-proto="${Number(n.id)}">+ پروتکل</button> `:''}<button class="btn btn-sm" data-ssh-hosts-node="${Number(n.id)}">هاست‌ها</button> <button class="btn btn-sm" data-ssh-rename-node="${Number(n.id)}" data-ssh-node-name="${esc(n.name)}">تغییر نام</button> <button class="btn btn-danger btn-sm" data-ssh-del-node="${Number(n.id)}">حذف</button></td>
    </tr>`).join('') || '<tr><td colspan="5" class="empty-state">هنوز نودی ثبت نشده است.</td></tr>'}</tbody></table></div></div>`;

  const vlessNodesHtml = `<div class="card" style="margin-top:12px"><div style="padding:12px 14px 0"><b>نودهای VLESS</b><p class="card-sub">نصب، اتصال، تنظیمات API و وضعیت استفاده از نودهای VLESS از همین بخش مدیریت می‌شود.</p></div><div class="table-wrap"><table>
    <thead><tr><th>نام</th><th>آدرس API</th><th>وضعیت</th><th>مصرف</th><th>عملیات</th></tr></thead>
    <tbody>${vlessNodes.map(n=>`<tr>
      <td><b>${esc(n.name)}</b><div class="card-sub">Stealth VLESS · #${Number(n.id)}</div></td>
      <td class="mono" dir="ltr">${esc(n.api_url || '')}</td>
      <td>${n.is_active ? (n.health_status === 'error' ? 'خطا' : 'فعال') : 'غیرفعال'}${n.health_error ? `<div class="card-sub" style="color:#FB7185">${esc(n.health_error)}</div>` : ''}</td>
      <td><span class="chip">${n.used_for_custom_config ? 'کانفیگ شخصی' : 'بدون کانفیگ شخصی'}</span> <span class="chip">${n.used_for_test_config ? 'کانفیگ تست' : 'بدون تست'}</span></td>
      <td>
        <button class="btn btn-sm" data-vless-test="${Number(n.id)}">تست اتصال</button>
        <button class="btn btn-sm" data-vless-edit="${Number(n.id)}">تنظیمات</button>
        <button class="btn btn-sm" data-vless-toggle="${Number(n.id)}">${n.is_active ? 'غیرفعال‌سازی' : 'فعال‌سازی'}</button>
        <button class="btn btn-sm" data-vless-usage="custom" data-vless-id="${Number(n.id)}">${n.used_for_custom_config ? 'قطع کانفیگ شخصی' : 'کانفیگ شخصی'}</button>
        <button class="btn btn-sm" data-vless-usage="test" data-vless-id="${Number(n.id)}">${n.used_for_test_config ? 'قطع تست' : 'کانفیگ تست'}</button>
        <button class="btn btn-danger btn-sm" data-vless-delete="${Number(n.id)}">حذف</button>
      </td>
    </tr>`).join('') || '<tr><td colspan="5" class="empty-state">هنوز نود VLESS ثبت نشده است.</td></tr>'}</tbody></table></div></div>`;

  const accountsHtml = `<div class="card"><div class="table-wrap"><table>
    <thead><tr><th>نام کاربری</th><th>پروتکل</th><th>سرور</th><th>کاربر</th><th>استخر</th><th>وضعیت</th><th>عملیات</th></tr></thead>
    <tbody>${accounts.map(a=>`<tr>
      <td><b>${esc(a.username)}</b></td>
      <td>${esc(SSH_PROTO_LABELS[a.protocol]||a.protocol||'SSH')}</td>
      <td class="mono" style="direction:ltr;text-align:right">${esc(a.host)}:${Number(a.port)}${(a.endpoints||[]).filter(e=>e.host_id).map(e=>`<div style="font-size:11px;opacity:.8">↪ ${esc(e.address)}:${Number(e.port)}${e.remark?' · '+esc(e.remark):''}</div>`).join('')}</td>
      <td>${Number(a.user_id)}</td>
      <td>${a.quota_pool_id ? '#'+Number(a.quota_pool_id) : '—'}</td>
      <td>${esc(statusFa(a.status))}</td>
      <td><button class="btn btn-sm" data-ssh-account-action="enable" data-ssh-account-id="${esc(a.account_id)}">فعال</button> <button class="btn btn-sm" data-ssh-account-action="disable" data-ssh-account-id="${esc(a.account_id)}">غیرفعال</button> <button class="btn btn-danger btn-sm" data-ssh-account-action="delete" data-ssh-account-id="${esc(a.account_id)}">حذف</button></td>
    </tr>`).join('') || '<tr><td colspan="7" class="empty-state">هنوز حسابی ثبت نشده است.</td></tr>'}</tbody></table></div></div>`;

  const poolsHtml = `<div class="card"><div class="table-wrap"><table>
    <thead><tr><th>شناسه</th><th>عنوان</th><th>کاربر</th><th>مصرف</th><th>وضعیت</th><th>اعضا</th></tr></thead>
    <tbody>${pools.map(p=>{const u=p.usage||{};return `<tr>
      <td>#${Number(p.id)}</td><td>${esc(p.label||'')}</td><td>${Number(p.user_id)}</td>
      <td>${fmtBytes(u.used_bytes)} از ${Number(p.limit_bytes||0) ? fmtBytes(p.limit_bytes) : 'نامحدود'}</td>
      <td>${esc(statusFa(p.status))}</td><td>${(p.members||[]).length}</td>
    </tr>`}).join('') || '<tr><td colspan="6" class="empty-state">استخر سهمیه‌ای وجود ندارد.</td></tr>'}</tbody></table></div></div>`;

  setContent(tabBar + (sshTab==='nodes' ? nodesHtml + vlessNodesHtml : sshTab==='accounts' ? accountsHtml : poolsHtml));

  $$('[data-ssh-tab]',content()).forEach(b=>b.addEventListener('click',()=>{sshTab=b.dataset.sshTab;renderSSHManagement();}));

  // ---- افزودن نود (نصب خودکار) ----
  $('#ssh-add-stealth')?.addEventListener('click',()=>openModal('افزودن نود Stealth VLESS',stealthAutoBoxHtml(true),(el,close)=>{
    wireStealthAutoBox(el,()=>el.querySelector('#sa-name').value.trim(),()=>{close();renderSSHManagement();});
  }));
  $('#ssh-add-node')?.addEventListener('click',()=>openModal('افزودن نود',`
    <div class="form-grid">
      <label class="field"><span>نام نود</span><input class="input" id="ssh-auto-name" placeholder="Germany-1" maxlength="80"></label>
      <label class="field"><span>آی‌پی سرور</span><input class="input" id="ssh-auto-host" placeholder="203.0.113.10" dir="ltr"></label>
      <label class="field"><span>پورت SSH</span><input class="input" id="ssh-auto-port" type="number" min="1" max="65535" value="22"></label>
      <label class="field"><span>رمز root</span><input class="input" id="ssh-auto-pass" type="password" autocomplete="off" dir="ltr"></label>
      ${sshProtoFieldsHtml([])}
      <button class="btn btn-primary" id="ssh-auto-install">نصب و راه‌اندازی خودکار</button>
    </div>
    <pre id="ssh-auto-log" class="mono" style="display:none;white-space:pre-wrap;margin-top:8px"></pre>
    <p class="card-sub">سرور باید Ubuntu/Debian تازه باشد. می‌توانید هر ترکیبی از SSH، OpenVPN و WireGuard را نصب کنید. نصب Agent، گواهی TLS، توکن، فایروال و تست حسابداری حجم خودکار انجام می‌شود. رمز root فقط برای همین نصب استفاده می‌شود و ذخیره نمی‌شود.</p>`,(el,close)=>{
    sshBindProtoFields(el);
    el.querySelector('#ssh-auto-install').addEventListener('click', e => {
      const btn=e.currentTarget, logEl=el.querySelector('#ssh-auto-log');
      const name=el.querySelector('#ssh-auto-name').value.trim(), host=el.querySelector('#ssh-auto-host').value.trim(), password=el.querySelector('#ssh-auto-pass').value;
      const pf=sshReadProtoFields(el);
      if(!name||!host||!password){toast('نام، آی‌پی و رمز root را وارد کنید.',true);return;}
      if(!pf.protocols.length){toast('حداقل یک پروتکل را تیک بزنید.',true);return;}
      sshRunInstallJob(el,btn,logEl,()=>apiPost('/ssh/nodes/auto-install',{name,host,ssh_port:Number(el.querySelector('#ssh-auto-port').value)||22,username:'root',password,...pf}),async()=>{close();await renderSSHManagement();});
    });
  }));

  // ---- افزودن پروتکل به نود موجود ----
  $$('[data-ssh-add-proto]',content()).forEach(btn=>btn.addEventListener('click',()=>{
    const node=nodes.find(n=>Number(n.id)===Number(btn.dataset.sshAddProto)); if(!node) return;
    openModal(`افزودن پروتکل به «${esc(node.name)}»`,`
      <div class="form-grid">
        <label class="field"><span>رمز root سرور ${esc(node.host)}</span><input class="input" id="ssh-up-pass" type="password" autocomplete="off" dir="ltr"></label>
        ${sshProtoFieldsHtml(node.protocols||['ssh'])}
        <button class="btn btn-primary" id="ssh-up-install">نصب روی این نود</button>
      </div>
      <pre id="ssh-up-log" class="mono" style="display:none;white-space:pre-wrap;margin-top:8px"></pre>
      <p class="card-sub">حساب‌ها و تنظیمات فعلی نود دست نمی‌خورند؛ فقط پروتکل تیک‌خورده نصب می‌شود. رمز root ذخیره نمی‌شود.</p>`,(el,close)=>{
      sshBindProtoFields(el);
      el.querySelector('#ssh-up-install').addEventListener('click', e => {
        const b=e.currentTarget, logEl=el.querySelector('#ssh-up-log'), password=el.querySelector('#ssh-up-pass').value;
        const pf=sshReadProtoFields(el);
        if(!password){toast('رمز root را وارد کنید.',true);return;}
        if(!pf.protocols.length){toast('پروتکلی برای نصب تیک نخورده است.',true);return;}
        sshRunInstallJob(el,b,logEl,()=>apiPost(`/ssh/nodes/${Number(node.id)}/add-protocols`,{password,...pf}),async()=>{close();await renderSSHManagement();});
      });
    });
  }));

  // ---- ساخت استخر ----
  $('#ssh-add-pool')?.addEventListener('click',()=>openModal('ساخت استخر سهمیه مشترک',`
    <div class="form-grid">
      <label class="field"><span>شناسه کاربر تلگرام</span><input class="input" id="ssh-pool-user" type="number" min="1" placeholder="123456789"></label>
      <label class="field"><span>سقف کل (GB) — صفر یعنی نامحدود</span><input class="input" id="ssh-pool-limit" type="number" min="0" step="0.1" value="50"></label>
      <label class="field"><span>انقضا (ISO اختیاری)</span><input class="input" id="ssh-pool-expiry" placeholder="2026-12-31T23:59:59+00:00"></label>
      <label class="field"><span>عنوان</span><input class="input" id="ssh-pool-label" value="سهمیه مشترک VPN + SSH" maxlength="100"></label>
      <button class="btn btn-primary" id="ssh-pool-create">ساخت استخر</button>
    </div>`,(el,close)=>{
    el.querySelector('#ssh-pool-create').addEventListener('click', async e => {
      const btn=e.currentTarget; btn.disabled=true;
      try { const r=await apiPost('/ssh/pools',{user_id:Number(el.querySelector('#ssh-pool-user').value),limit_gb:Number(el.querySelector('#ssh-pool-limit').value),expires_at:el.querySelector('#ssh-pool-expiry').value.trim()||null,label:el.querySelector('#ssh-pool-label').value.trim()}); toast(`استخر #${r.pool_id} ساخته شد.`); close(); await renderSSHManagement(); }
      catch(err){handleErr(err);btn.disabled=false;}
    });
  }));

  // ---- اتصال VPN به استخر ----
  $('#ssh-attach-open')?.addEventListener('click',()=>openModal('اتصال کانفیگ VPN به استخر',`
    <div class="form-grid">
      <label class="field"><span>استخر</span><select class="input" id="ssh-attach-pool"><option value="">انتخاب استخر</option>${pools.filter(p=>p.status==='active').map(p=>`<option value="${Number(p.id)}">#${Number(p.id)} · کاربر ${Number(p.user_id)} · ${esc(p.label||'')}</option>`).join('')}</select></label>
      <label class="field"><span>شناسه کانفیگ VPN</span><input class="input" id="ssh-attach-config" type="number" min="1"></label>
      <button class="btn btn-primary" id="ssh-attach-vpn">اتصال VPN به استخر</button>
    </div>`,(el,close)=>{
    el.querySelector('#ssh-attach-vpn').addEventListener('click', async e => {
      const btn=e.currentTarget; btn.disabled=true;
      try { await apiPost(`/ssh/pools/${Number(el.querySelector('#ssh-attach-pool').value)}/attach-vpn`,{custom_config_id:Number(el.querySelector('#ssh-attach-config').value)}); toast('کانفیگ VPN به استخر متصل شد.'); close(); await renderSSHManagement(); }
      catch(err){handleErr(err);btn.disabled=false;}
    });
  }));

  // ---- ساخت حساب ----
  $('#ssh-add-account')?.addEventListener('click',()=>openModal('ساخت حساب SSH',`
    <div class="form-grid">
      <label class="field"><span>نود فعال</span><select class="input" id="ssh-account-node"><option value="">انتخاب نود</option>${nodes.map(n=>`<option value="${Number(n.id)}" data-protocols="${esc((n.protocols||['ssh']).join(','))}">${esc(n.name)} · #${Number(n.id)}</option>`).join('')}</select></label>
      <label class="field"><span>پروتکل حساب</span><select class="input" id="ssh-account-protocol"><option value="ssh">SSH</option></select></label>
      <label class="field"><span>شناسه کاربر</span><input class="input" id="ssh-account-user" type="number" min="1"></label>
      <label class="field"><span>نام کاربری</span><input class="input" id="ssh-account-username" maxlength="32" placeholder="user123"></label>
      <label class="field"><span>سقف مستقل (GB) — بدون استخر</span><input class="input" id="ssh-account-limit" type="number" min="0" step="0.1" value="0"></label>
      <label class="field"><span>مدت (روز)</span><input class="input" id="ssh-account-days" type="number" min="0" value="30"></label>
      <label class="field"><span>استخر مشترک (اختیاری)</span><select class="input" id="ssh-account-pool"><option value="">بدون استخر</option>${pools.filter(p=>p.status==='active').map(p=>`<option value="${Number(p.id)}">#${Number(p.id)} · کاربر ${Number(p.user_id)} · ${esc(p.label||'')}</option>`).join('')}</select></label>
      <button class="btn btn-primary" id="ssh-account-create">ساخت حساب</button>
    </div>`,(el,close)=>{
    const nodeSel=el.querySelector('#ssh-account-node'), protoSel=el.querySelector('#ssh-account-protocol');
    nodeSel.addEventListener('change',()=>{
      const list=(nodeSel.selectedOptions[0]?.dataset.protocols||'ssh').split(',').filter(Boolean);
      protoSel.innerHTML=list.map(p=>`<option value="${esc(p)}">${esc(SSH_PROTO_LABELS[p]||p)}</option>`).join('');
    });
    el.querySelector('#ssh-account-create').addEventListener('click', async e => {
      const btn=e.currentTarget; btn.disabled=true;
      try { const poolVal=el.querySelector('#ssh-account-pool').value; const r=await apiPost('/ssh/accounts',{node_id:Number(el.querySelector('#ssh-account-node').value),user_id:Number(el.querySelector('#ssh-account-user').value),username:el.querySelector('#ssh-account-username').value.trim(),limit_gb:Number(el.querySelector('#ssh-account-limit').value),days:Number(el.querySelector('#ssh-account-days').value),quota_pool_id:poolVal?Number(poolVal):null,protocol:protoSel.value});
        close();
        if(r.protocol==='wireguard'){
          openModal('حساب WireGuard ساخته شد',`<p>نام کاربری: <b>${esc(r.username)}</b></p><p>سرور: <code>${esc(r.host)}:${Number(r.port)}</code></p><p class="card-sub">فایل .conf فقط همین بار نمایش داده می‌شود؛ آن را دانلود و به کاربر تحویل بده.</p><button class="btn btn-primary" id="ssh-download-wg">دانلود فایل .conf</button>`,(el2)=>{el2.querySelector('#ssh-download-wg')?.addEventListener('click',()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([r.profile||''],{type:'application/x-wireguard-profile'}));a.download=`${r.username}.conf`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000);});});
          await renderSSHManagement(); return;
        }
        if(r.protocol==='openvpn'){
          openModal('حساب OpenVPN ساخته شد',`<p>نام کاربری: <b>${esc(r.username)}</b></p><p>سرور: <code>${esc(r.host)}:${Number(r.port)}</code></p><p class="card-sub">پروفایل .ovpn فقط همین بار نمایش داده می‌شود؛ آن را دانلود و به کاربر تحویل بده.</p><button class="btn btn-primary" id="ssh-download-ovpn">دانلود فایل .ovpn</button>`,(el2)=>{el2.querySelector('#ssh-download-ovpn')?.addEventListener('click',()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([r.profile||''],{type:'application/x-openvpn-profile'}));a.download=`${r.username}.ovpn`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000);});});
          await renderSSHManagement(); return;
        }
        openModal('حساب SSH ساخته شد',`<p>نام کاربری: <b>${esc(r.username)}</b></p><p>سرور: <code>${esc(r.host)}:${Number(r.port)}</code></p><p>رمز عبور (فقط همین بار نمایش داده می‌شود):</p><input class="input" id="ssh-created-password" readonly value="${esc(r.password||'')}"><p class="card-sub">${esc(r.warning||'رمز را امن به کاربر تحویل بده؛ در دیتابیس ذخیره نشده است.')}</p><button class="btn btn-primary" id="ssh-copy-created-password">کپی رمز</button>`,(el2)=>{el2.querySelector('#ssh-copy-created-password')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(r.password||'');toast('رمز کپی شد.');}catch(_){el2.querySelector('#ssh-created-password')?.select();toast('رمز را دستی کپی کن.');}});});
        await renderSSHManagement();
      } catch(err){handleErr(err);btn.disabled=false;}
    });
  }));

  // ---- عملیات روی نود/حساب/پایش ----
  $$('[data-ssh-rename-node]',content()).forEach(btn=>btn.addEventListener('click',async()=>{const name=(prompt('نام جدید نود (همین نام روی کانفیگ SSH کاربر دیده می‌شود):',btn.dataset.sshNodeName||'')||'').trim();if(!name||name===btn.dataset.sshNodeName)return;btn.disabled=true;try{await apiPost(`/ssh/nodes/${Number(btn.dataset.sshRenameNode)}/rename`,{name});toast('نام نود تغییر کرد.');await renderSSHManagement();}catch(err){handleErr(err);btn.disabled=false;}}));
  $$('[data-ssh-hosts-node]',content()).forEach(btn=>btn.addEventListener('click',()=>{const node=nodes.find(n=>Number(n.id)===Number(btn.dataset.sshHostsNode));if(node)sshHostsModal(node,renderSSHManagement);}));
  $$('[data-ssh-del-node]',content()).forEach(btn=>btn.addEventListener('click',async()=>{if(!confirm('این نود حذف شود؟'))return;btn.disabled=true;const nid=Number(btn.dataset.sshDelNode);try{await apiDelete(`/ssh/nodes/${nid}`);toast('نود حذف شد.');await renderSSHManagement();}catch(err){if(/حساب SSH فعال/.test(err.message||'')&&confirm(err.message+'\n\nاگر سرور این نود حذف شده یا از دسترس خارج است، نود و همه‌ی حساب‌هایش فقط از پنل پاک می‌شوند (روی سرور تغییری داده نمی‌شود). ادامه می‌دهید؟')){try{await apiDelete(`/ssh/nodes/${nid}?force=true`);toast('نود و حساب‌هایش از پنل حذف شد.');await renderSSHManagement();return;}catch(err2){handleErr(err2);}}else{handleErr(err);}btn.disabled=false;}}));
  $$('[data-ssh-test-node]',content()).forEach(btn=>btn.addEventListener('click',async()=>{btn.disabled=true;try{const r=await apiPost(`/ssh/nodes/${Number(btn.dataset.sshTestNode)}/test`,{});toast(r.ok?'اتصال Agent موفق بود.':'پاسخ Agent معتبر نیست.');await renderSSHManagement();}catch(err){handleErr(err);btn.disabled=false;}}));
  $$('[data-vless-test]',content()).forEach(btn=>btn.addEventListener('click',async()=>{btn.disabled=true;try{const r=await apiPost(`/panel-servers/${Number(btn.dataset.vlessTest)}/test`,{});toast(r.ok?'اتصال نود VLESS موفق بود.':'اتصال نود VLESS ناموفق بود.');await renderSSHManagement();}catch(err){handleErr(err);btn.disabled=false;}}));
  $$('[data-vless-edit]',content()).forEach(btn=>btn.addEventListener('click',()=>{const node=vlessNodes.find(n=>Number(n.id)===Number(btn.dataset.vlessEdit));if(node)stealthNodeSettingsModal(node,renderSSHManagement);}));
  $$('[data-vless-toggle]',content()).forEach(btn=>btn.addEventListener('click',async()=>{btn.disabled=true;try{await apiPost(`/panel-servers/${Number(btn.dataset.vlessToggle)}/toggle`,{});toast('وضعیت نود تغییر کرد.');await renderSSHManagement();}catch(err){handleErr(err);btn.disabled=false;}}));
  $$('[data-vless-usage]',content()).forEach(btn=>btn.addEventListener('click',async()=>{btn.disabled=true;try{await apiPost(`/panel-servers/${Number(btn.dataset.vlessId)}/usage/${btn.dataset.vlessUsage}`,{});toast('تنظیم مصرف نود ذخیره شد.');await renderSSHManagement();}catch(err){handleErr(err);btn.disabled=false;}}));
  $$('[data-vless-delete]',content()).forEach(btn=>btn.addEventListener('click',async()=>{if(!confirm('نود VLESS حذف شود؟ سرویس‌ها و محصولات متصل را بررسی کنید.'))return;btn.disabled=true;try{await apiDelete(`/panel-servers/${Number(btn.dataset.vlessDelete)}`);toast('نود VLESS حذف شد.');await renderSSHManagement();}catch(err){handleErr(err);btn.disabled=false;}}));
  $$('[data-ssh-account-action]',content()).forEach(btn=>btn.addEventListener('click',async()=>{const action=btn.dataset.sshAccountAction;if(action==='delete'&&!confirm('حساب SSH حذف شود؟'))return;btn.disabled=true;const url=`/ssh/accounts/${encodeURIComponent(btn.dataset.sshAccountId)}/action`;try{await apiPost(url,{action});toast('عملیات انجام شد.');await renderSSHManagement();}catch(err){if(action==='delete'&&err.status===502&&confirm(err.message+'\n\nحذف اجباری فقط از پنل انجام شود؟ (روی سرور نود تغییری داده نمی‌شود)')){try{await apiPost(url,{action,force:true});toast('حساب فقط از پنل حذف شد.');await renderSSHManagement();return;}catch(err2){handleErr(err2);}}else{handleErr(err);}btn.disabled=false;}}));
  $('#ssh-reconcile')?.addEventListener('click',async e=>{const btn=e.currentTarget;btn.disabled=true;try{const r=await apiPost('/ssh/reconcile-once',{});const results=r.results||[];const failed=results.filter(x=>!x.enforcement_complete).length;const stale=results.filter(x=>x.state==='stale').length;toast(failed?`پایش انجام شد؛ ${failed} استخر نیازمند بررسی است.`:(stale?`${stale} استخر به‌علت گزارش مصرف قدیمی در حالت امن باقی ماند.`:'پایش سهمیه انجام شد.'));await renderSSHManagement();}catch(err){handleErr(err);btn.disabled=false;}});
}

let panelCatFilter = 'all';

async function renderPanels() {
  const servers = await apiGet('/panel-servers');
  const pcats = await apiGet('/panel-categories').catch(() => []);
  window.__panelCats = pcats;
  if (loadTheme().theme === 'brutalist') { renderPanelsBrutalist(servers); enhancePanelCategories(servers, pcats); return; }
  if (loadTheme().theme === 'bento') { renderPanelsBento(servers); enhancePanelCategories(servers, pcats); return; }
  setContent(`
    <div class="toolbar"><button class="btn btn-primary btn-sm" id="add-panel">+ پنل جدید</button></div>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>نام</th><th>نوع</th><th>آدرس</th><th>وضعیت</th><th>مصرف</th><th>عملیات</th></tr></thead>
      <tbody>${servers.map(s => `<tr>
        <td>${esc(s.name)}</td><td>${esc(s.type_label)}</td><td class="mono" style="direction:ltr;text-align:right">${esc(s.api_url)}</td>
        <td>
          <button class="btn btn-sm ${s.is_active ? '' : 'btn-danger'}" data-toggle-active="${s.id}">${s.is_active ? '✅ فعال' : '⛔️ غیرفعال'}</button>
          ${s.is_configured ? '' : '<div style="font-size:11px;color:#FB7185;margin-top:4px">⚠️ تکمیل‌نشده</div>'}
          ${panelHealthHtml(s)}
        </td>
        <td>
          <label style="display:flex;gap:4px;align-items:center;font-size:12px;white-space:nowrap"><input type="checkbox" data-usage="custom" data-usage-id="${s.id}" ${s.used_for_custom_config ? 'checked' : ''}> کانفیگ شخصی</label>
          <label style="display:flex;gap:4px;align-items:center;font-size:12px;white-space:nowrap"><input type="checkbox" data-usage="test" data-usage-id="${s.id}" ${s.used_for_test_config ? 'checked' : ''}> کانفیگ تست</label>
        </td>
        <td>
          <button class="btn btn-sm" data-move-up="${s.id}" title="یک پله بالا">↑</button>
          <button class="btn btn-sm" data-move-down="${s.id}" title="یک پله پایین">↓</button>
          <button class="btn btn-sm" data-test="${s.id}">تست اتصال</button>
          <button class="btn btn-sm" data-edit="${s.id}">ویرایش</button>
          ${PANEL_INBOUND_SELECT_TYPES.includes(s.panel_type) ? `<button class="btn btn-sm" data-edit-inbounds="${s.id}">Inbound ها</button>` : ''}
          ${PANEL_TEMPLATE_BASED_TYPES.includes(s.panel_type) ? `<button class="btn btn-sm" data-retemplate="${s.id}">قالب جدید</button>` : ''}
          <button class="btn btn-danger btn-sm" data-del="${s.id}">حذف</button>
        </td>
      </tr>`).join('') || '<tr><td colspan="6" class="empty-state">پنلی ثبت نشده</td></tr>'}</tbody>
    </table></div></div>
  `);
  $('#add-panel').addEventListener('click', () => openModal('پنل جدید', panelAddFormHtml(), wirePanelAddForm));
  $$('[data-edit-inbounds]', content()).forEach(b => b.addEventListener('click', async () => {
    const server = servers.find(s => s.id === Number(b.dataset.editInbounds));
    b.textContent = '⏳...'; b.disabled = true;
    try {
      const inbounds = await apiGet(`/panel-servers/${server.id}/inbounds`);
      openXuiInboundModal(server.id, inbounds, server.xui_inbound_ids || [], server.xui_sub_base_url || '');
    } catch (e) { handleErr(e); }
    finally { b.textContent = 'Inbound ها'; b.disabled = false; }
  }));
  $$('[data-test]', content()).forEach(b => b.addEventListener('click', async () => {
    b.textContent = 'در حال تست...'; b.disabled = true;
    try {
      const r = await apiPost(`/panel-servers/${b.dataset.test}/test`);
      toast(r.ok ? 'اتصال موفق بود.' : (r.error || 'اتصال ناموفق بود.'), !r.ok);
    } catch (e) { handleErr(e); }
    finally { b.textContent = 'تست اتصال'; b.disabled = false; }
  }));
  $$('[data-toggle-active]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/panel-servers/${b.dataset.toggleActive}/toggle`); renderPanels(); } catch (e) { handleErr(e); }
  }));
  $$('[data-usage]', content()).forEach(cb => cb.addEventListener('change', async () => {
    try { await apiPost(`/panel-servers/${cb.dataset.usageId}/usage/${cb.dataset.usage}`); toast('ذخیره شد.'); }
    catch (e) { handleErr(e); cb.checked = !cb.checked; }
  }));
  $$('[data-edit]', content()).forEach(b => b.addEventListener('click', () => openPanelEditModal(servers.find(s => s.id === Number(b.dataset.edit)))));
  $$('[data-retemplate]', content()).forEach(b => b.addEventListener('click', () => openPanelRetemplateModal(Number(b.dataset.retemplate))));
  wirePanelReorder(servers);
  wirePanelDeleteButtons();
  enhancePanelCategories(servers, pcats);
}


// ---------------------------------------------------------------- دسته‌بندی پنل‌ها --
// مستقل از تم: فیلتر دسته، انتخاب دسته‌ی هر پنل و مدیریت دسته‌ها روی DOM همان صفحه اضافه می‌شود.
function enhancePanelCategories(servers, pcats) {
  const root = content();
  const rowOf = id => { const b = root.querySelector(`[data-edit="${id}"]`); return b ? b.closest('tr, .bn-card, .bru-server-card') : null; };
  const countOf = cid => servers.filter(s => (cid === 'none' ? !s.panel_category_id : Number(s.panel_category_id) === Number(cid))).length;
  if (panelCatFilter !== 'all' && panelCatFilter !== 'none' && !pcats.some(c => String(c.id) === String(panelCatFilter))) panelCatFilter = 'all';

  const chips = [['all', `همه (${servers.length})`], ...pcats.map(c => [String(c.id), `${c.name} (${countOf(c.id)})`])];
  if (pcats.length) chips.push(['none', `بدون دسته (${countOf('none')})`]);
  const bar = document.createElement('div');
  bar.className = 'toolbar';
  bar.style.cssText = 'flex-wrap:wrap;gap:6px;margin:0 0 12px';
  bar.innerHTML = `${chips.map(([v, l]) => `<button class="btn btn-sm ${String(panelCatFilter) === v ? 'btn-primary' : ''}" data-pcat-filter="${esc(v)}">${esc(l)}</button>`).join('')}
    <button class="btn btn-sm" id="pcat-manage">🗂 مدیریت دسته‌بندی‌ها</button>`;
  root.insertBefore(bar, root.firstChild);

  servers.forEach(s => {
    const row = rowOf(s.id);
    if (!row) return;
    row.dataset.pcat = s.panel_category_id ? String(s.panel_category_id) : 'none';
    const host = root.querySelector(`[data-edit="${s.id}"]`).parentElement;
    const sel = document.createElement('select');
    sel.className = 'input';
    sel.dataset.panelCat = s.id;
    sel.title = 'دسته‌بندی پنل';
    sel.style.cssText = 'width:auto;min-width:110px;padding:4px 8px;font-size:12px;margin-inline-start:4px';
    sel.innerHTML = `<option value="">🗂 بدون دسته</option>${pcats.map(c => `<option value="${c.id}" ${Number(s.panel_category_id) === c.id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}`;
    sel.addEventListener('change', async () => {
      try { await apiPost(`/panel-servers/${s.id}/category`, { category_id: sel.value ? Number(sel.value) : null }); toast('دسته‌بندی پنل ذخیره شد.'); renderPanels(); }
      catch (e) { handleErr(e); }
    });
    host.appendChild(sel);
  });

  const applyFilter = () => {
    servers.forEach(s => {
      const row = rowOf(s.id);
      if (row) row.style.display = (panelCatFilter === 'all' || row.dataset.pcat === String(panelCatFilter)) ? '' : 'none';
    });
  };
  applyFilter();
  $$('[data-pcat-filter]', bar).forEach(b => b.addEventListener('click', () => { panelCatFilter = b.dataset.pcatFilter; renderPanels(); }));
  $('#pcat-manage', bar).addEventListener('click', () => openPanelCategoriesModal(pcats));
}

function openPanelCategoriesModal(pcats) {
  const rowsHtml = pcats.map((c, i) => `
    <div class="field-row" style="gap:6px;align-items:center">
      <span style="flex:1">${esc(c.name)}</span>
      <button class="btn btn-xs" data-pc-up="${c.id}" ${i === 0 ? 'disabled' : ''}>▲</button>
      <button class="btn btn-xs" data-pc-down="${c.id}" ${i === pcats.length - 1 ? 'disabled' : ''}>▼</button>
      <button class="btn btn-xs" data-pc-edit="${c.id}">✏️</button>
      <button class="btn btn-xs btn-danger" data-pc-del="${c.id}">🗑</button>
    </div>`).join('') || '<div class="card-sub">هنوز دسته‌بندی‌ای ساخته نشده.</div>';
  openModal('دسته‌بندی پنل‌ها', `
    <div class="form-grid">
      <div style="display:grid;gap:8px">${rowsHtml}</div>
      <div class="form-row"><input class="input" id="pc-new" placeholder="نام دسته‌بندی جدید (مثلاً آلمان)"><button class="btn btn-primary" id="pc-add">+ افزودن</button></div>
    </div>`, (b, close) => {
    const done = () => { close(); renderPanels(); };
    $('#pc-add', b).addEventListener('click', async () => {
      const name = $('#pc-new', b).value.trim(); if (!name) return;
      try { await apiPost('/panel-categories', { name }); toast('اضافه شد.'); done(); } catch (e) { handleErr(e); }
    });
    $$('[data-pc-up],[data-pc-down]', b).forEach(btn => btn.addEventListener('click', async () => {
      const id = btn.dataset.pcUp || btn.dataset.pcDown;
      try { await apiPost(`/panel-categories/${id}/move`, { direction: btn.dataset.pcUp ? 'up' : 'down' }); done(); } catch (e) { handleErr(e); }
    }));
    $$('[data-pc-edit]', b).forEach(btn => btn.addEventListener('click', async () => {
      const cat = pcats.find(c => c.id === Number(btn.dataset.pcEdit));
      const name = (prompt('نام جدید دسته‌بندی:', cat ? cat.name : '') || '').trim();
      if (!name) return;
      try { await apiPut(`/panel-categories/${cat.id}`, { name }); toast('ویرایش شد.'); done(); } catch (e) { handleErr(e); }
    }));
    $$('[data-pc-del]', b).forEach(btn => btn.addEventListener('click', async () => {
      if (!confirm('حذف شود؟ (پنل‌های این دسته حذف نمی‌شوند؛ فقط «بدون دسته» می‌شوند)')) return;
      try { await apiDelete(`/panel-categories/${btn.dataset.pcDel}`); toast('حذف شد.'); done(); } catch (e) { handleErr(e); }
    }));
  });
}

function openPanelEditModal(server) {
  openModal('ویرایش پنل', `
    <div class="form-grid">
      <input class="input" id="pe-name" placeholder="نام" value="${esc(server.name)}">
      <input class="input" id="pe-url" placeholder="آدرس پنل" value="${esc(server.api_url)}" style="direction:ltr;text-align:left">
      <div class="form-row">
        <input class="input" id="pe-user" placeholder="یوزرنیم (خالی = بدون تغییر)">
        <input class="input" id="pe-pass" type="password" placeholder="پسورد/توکن (خالی = بدون تغییر)">
      </div>
      ${PANEL_SUB_BASE_URL_TYPES.includes(server.panel_type) ? `
        <input class="input" id="pe-suburl" placeholder="لینک Subscription" value="${esc(server.xui_sub_base_url || '')}" style="direction:ltr;text-align:left">
      ` : ''}
      <button class="btn btn-primary" id="pe-save">ذخیره</button>
    </div>`, (body, close) => {
    $('#pe-save', body).addEventListener('click', async () => {
      const payload = { name: $('#pe-name', body).value.trim(), api_url: $('#pe-url', body).value.trim() };
      const user = $('#pe-user', body).value.trim(), pass = $('#pe-pass', body).value.trim();
      if (user) payload.api_username = user;
      if (pass) payload.api_password = pass;
      const suburlInp = $('#pe-suburl', body);
      if (suburlInp && suburlInp.value.trim()) payload.xui_sub_base_url = suburlInp.value.trim();
      try {
        await apiPut(`/panel-servers/${server.id}`, payload);
        toast('پنل ویرایش شد.'); close(); renderPanels();
      } catch (e) { handleErr(e); }
    });
  });
}

function openPanelRetemplateModal(serverId) {
  openModal('دریافت قالب جدید', `
    <div class="form-grid">
      <p style="margin:0">نام کاربری نمونه‌ی جدید روی این پنل را وارد کن:</p>
      <input class="input" id="pt-username" placeholder="نام کاربری نمونه">
      <button class="btn btn-primary" id="pt-save">دریافت قالب</button>
    </div>`, (body, close) => {
    $('#pt-save', body).addEventListener('click', async () => {
      const username = $('#pt-username', body).value.trim();
      if (!username) return toast('نام کاربری الزامی است.', true);
      try {
        await apiPost(`/panel-servers/${serverId}/template`, { template_username: username });
        toast('قالب به‌روزرسانی شد.'); close(); renderPanels();
      } catch (e) { handleErr(e); }
    });
  });
}

/* ------------------------------------------------------------ panels: bento */
function renderPanelsBento(servers) {
  setContent(`
    <div class="bn-hero">
      <div><h2>سرورهای پنل VPN</h2><p>${fmt(servers.length)} سرور متصل</p></div>
      <button class="bn-btn bn-btn-ok" id="add-panel">+ پنل جدید</button>
    </div>
    <div class="bn-card-grid">
      ${servers.map((s, i) => `
        <div class="bn-card bn-card-anim" style="animation-delay:${Math.min(i * 30, 260)}ms">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="width:10px;height:10px;border-radius:50%;background:${s.is_active ? 'var(--emerald)' : 'var(--rose)'};flex-shrink:0"></span>
            <span class="bn-row-title">${esc(s.name)}</span>
          </div>
          <div class="bn-row-sub">${esc(s.type_label)}</div>
          <div class="bn-row-sub mono" style="direction:ltr;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.api_url)}</div>
          ${panelHealthHtml(s)}
          <div style="display:flex;gap:8px;margin-top:6px;flex-wrap:wrap">
            <button class="bn-btn bn-btn-ghost" data-move-up="${s.id}">↑</button>
            <button class="bn-btn bn-btn-ghost" data-move-down="${s.id}">↓</button>
            <button class="bn-btn bn-btn-ghost" data-test="${s.id}">تست اتصال</button>
            <button class="bn-btn bn-btn-ghost" data-edit="${s.id}">ویرایش</button>
            ${PANEL_INBOUND_SELECT_TYPES.includes(s.panel_type) ? `<button class="bn-btn bn-btn-ghost" data-edit-inbounds="${s.id}">Inbound ها</button>` : ''}
            ${PANEL_TEMPLATE_BASED_TYPES.includes(s.panel_type) ? `<button class="bn-btn bn-btn-ghost" data-retemplate="${s.id}">قالب جدید</button>` : ''}
            <button class="bn-btn bn-btn-no" data-del="${s.id}">حذف</button>
          </div>
        </div>
      `).join('') || `<div class="empty-state" style="grid-column:1/-1"><div class="icon">${svg('empty')}</div>پنلی ثبت نشده</div>`}
    </div>
  `);
  $('#add-panel').addEventListener('click', () => openModal('پنل جدید', panelAddFormHtml(), wirePanelAddForm));
  $$('[data-test]', content()).forEach(b => b.addEventListener('click', async () => {
    b.textContent = 'در حال تست...'; b.disabled = true;
    try {
      const r = await apiPost(`/panel-servers/${b.dataset.test}/test`);
      toast(r.ok ? 'اتصال موفق بود.' : (r.error || 'اتصال ناموفق بود.'), !r.ok);
    } catch (e) { handleErr(e); }
    finally { b.textContent = 'تست اتصال'; b.disabled = false; }
  }));
  $$('[data-edit]', content()).forEach(b => b.addEventListener('click', () => openPanelEditModal(servers.find(s => s.id === Number(b.dataset.edit)))));
  $$('[data-edit-inbounds]', content()).forEach(b => b.addEventListener('click', async () => {
    const server = servers.find(s => s.id === Number(b.dataset.editInbounds));
    b.textContent = '⏳...'; b.disabled = true;
    try {
      const inbounds = await apiGet(`/panel-servers/${server.id}/inbounds`);
      openXuiInboundModal(server.id, inbounds, server.xui_inbound_ids || [], server.xui_sub_base_url || '');
    } catch (e) { handleErr(e); }
    finally { b.textContent = 'Inbound ها'; b.disabled = false; }
  }));
  $$('[data-retemplate]', content()).forEach(b => b.addEventListener('click', () => openPanelRetemplateModal(Number(b.dataset.retemplate))));
  wirePanelReorder(servers);
  wirePanelDeleteButtons();
}


/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

/* --------------------------------------------------- panels: brutalist -- */
// هر سرور پنل به‌شکل کارت «سرور رَک» با چراغ وضعیت گرد و دکمه‌ی تست اتصال
// که در حین تست چشمک می‌زند.
function renderPanelsBrutalist(servers) {
  setContent(`
    <div class="bru-hero" style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
      <div>
        <h2>سرورهای پنل VPN</h2>
        <p>${fmt(servers.length)} سرور متصل</p>
      </div>
      <button class="bru-stamp bru-stamp-ok" id="add-panel" style="--r:-3deg">+ پنل جدید</button>
    </div>
    <div class="bru-panel-grid">
      ${servers.map((s, i) => `
        <div class="bru-server-card bru-card-anim" style="animation-delay:${Math.min(i * 35, 300)}ms">
          <div class="bru-server-top">
            <span class="bru-server-dot ${s.is_active ? 'on' : 'off'}"></span>
            <span class="bru-server-name">${esc(s.name)}</span>
          </div>
          <div class="bru-coupon-row"><span>نوع</span><b>${esc(s.type_label)}</b></div>
          <div class="bru-server-url mono">${esc(s.api_url)}</div>
          ${panelHealthHtml(s)}
          <div class="bru-coupon-actions" style="padding:0;border:none;margin-top:8px;flex-wrap:wrap">
            <button class="btn btn-sm" data-test="${s.id}">تست اتصال</button>
            <button class="btn btn-sm" data-edit="${s.id}">ویرایش</button>
            ${PANEL_INBOUND_SELECT_TYPES.includes(s.panel_type) ? `<button class="btn btn-sm" data-edit-inbounds="${s.id}">Inbound ها</button>` : ''}
            ${PANEL_TEMPLATE_BASED_TYPES.includes(s.panel_type) ? `<button class="btn btn-sm" data-retemplate="${s.id}">قالب جدید</button>` : ''}
            <button class="btn btn-danger btn-sm" data-del="${s.id}">حذف</button>
          </div>
        </div>
      `).join('') || `<div class="empty-state" style="grid-column:1/-1"><div class="icon">${svg('empty')}</div>پنلی ثبت نشده</div>`}
    </div>
  `);
  $('#add-panel').addEventListener('click', () => openModal('پنل جدید', panelAddFormHtml(), wirePanelAddForm));
  $$('[data-test]', content()).forEach(b => b.addEventListener('click', async () => {
    b.classList.add('bru-testing'); b.textContent = 'در حال تست...'; b.disabled = true;
    try {
      const r = await apiPost(`/panel-servers/${b.dataset.test}/test`);
      toast(r.ok ? 'اتصال موفق بود.' : (r.error || 'اتصال ناموفق بود.'), !r.ok);
    } catch (e) { handleErr(e); }
    finally { b.classList.remove('bru-testing'); b.textContent = 'تست اتصال'; b.disabled = false; }
  }));
  $$('[data-edit]', content()).forEach(b => b.addEventListener('click', () => openPanelEditModal(servers.find(s => s.id === Number(b.dataset.edit)))));
  $$('[data-edit-inbounds]', content()).forEach(b => b.addEventListener('click', async () => {
    const server = servers.find(s => s.id === Number(b.dataset.editInbounds));
    b.textContent = '⏳...'; b.disabled = true;
    try {
      const inbounds = await apiGet(`/panel-servers/${server.id}/inbounds`);
      openXuiInboundModal(server.id, inbounds, server.xui_inbound_ids || [], server.xui_sub_base_url || '');
    } catch (e) { handleErr(e); }
    finally { b.textContent = 'Inbound ها'; b.disabled = false; }
  }));
  $$('[data-retemplate]', content()).forEach(b => b.addEventListener('click', () => openPanelRetemplateModal(Number(b.dataset.retemplate))));
  wirePanelReorder(servers);
  wirePanelDeleteButtons();
}

/* ============================================================ settings === */
const RATE_SOURCE_LABEL = { tgju: 'tgju.org', nobitex: 'نوبیتکس', wallex: 'والکس', coingecko: 'CoinGecko (جهانی)', manual: 'دستی (تنظیم‌شده در پنل)' };

function rateCardHtml(r) {
  const rateTxt = r.rate ? `${fmt(r.rate)} تومان` : '—';
  const sourceTxt = r.source ? (RATE_SOURCE_LABEL[r.source] || r.source) : '—';
  const errTxt = !r.ok
    ? `<span class="card-sub" style="color:var(--rose)">دریافت زنده ناموفق بود؛ ${r.rate ? 'مقدار کش قدیمی نمایش داده شده.' : 'مقداری در کش نیست.'} (${esc(r.error || '')})</span>`
    : (r.source === 'manual'
        ? `<span class="card-sub" style="color:var(--amber, #f5a623)">⚠️ همه‌ی منابع زنده شکست خوردند؛ نرخ دستی تنظیم‌شده در پایین همین صفحه موقتاً استفاده شد.</span>`
        : '');
  return `
    <div class="card" style="margin-bottom:18px" id="rate-card">
      <div class="card-head">
        <h3>نرخ ارز (دلار به تومان)</h3>
        <button class="btn btn-sm" id="rate-refresh">🔄 رفرش کش</button>
      </div>
      <div class="chip-row">
        <span class="chip mono">نرخ فعلی: ${rateTxt}</span>
        <span class="chip">منبع: ${sourceTxt}</span>
        <span class="chip mono">آخرین بروزرسانی: ${fmtDate(r.updated_at)}</span>
      </div>
      ${errTxt}
    </div>`;
}

const SETTINGS_TABS = [
  { key: 'content', label: '📝 محتوا و متن‌ها' },
  { key: 'payment', label: '💳 پرداخت و مالی' },
  { key: 'sales', label: '🛒 فروش و سرویس‌ها' },
  { key: 'growth', label: '🎁 رشد و تعامل' },
  { key: 'sub', label: '🔗 اشتراک اختصاصی' },
  { key: 'ai', label: '🤖 هوش مصنوعی' },
  { key: 'system', label: '🛠 سیستم و پایش' },
  { key: 'mobile_app', label: '📱 اپ موبایل' },
];
const EXTRA_GROUP_TABS = {
  content: ['terms', 'welcome', 'support_texts', 'translation_keys', 'post_tools'],
  payment: ['currency', 'card_to_card_ui', 'crypto_payment_toggle_mini', 'wallet'],
  sales: ['main_menu', 'delivery', 'smart_sub', 'location', 'provisioning', 'free_test', 'cleanup', 'alerts', 'acct_svc_buttons_mini', 'acct_svc_buttons_web', 'service_buttons_extra'],
  growth: ['signup_gift', 'referral_adv', 'referral_fraud', 'lottery', 'engagement', 'season', 'daily_quiz', 'gift_cards', 'renewal_adv', 'churn', 'reminder_discount_codes', 'force_join'],
  sub: ['dsub_enable_web', 'dsub_basic', 'dsub_apps'],
  ai: ['ai_general', 'ai_providers', 'ai_buy_guide', 'ai_extra_agents', 'receipt_ai'],
  system: ['system', 'report_and_server_monitoring', 'backup', 'spam_limits', 'misc_admin', 'parity_extra'],
};
const EXTRA_GROUP_TAB_INDEX = (() => {
  const m = {};
  Object.keys(EXTRA_GROUP_TABS).forEach(tab => EXTRA_GROUP_TABS[tab].forEach((id, i) => { m[id] = { tab, order: i }; }));
  return m;
})();
// نکته: تنظیمات رفرال، گردونه‌شانس، کریپتو، یادآوری تمدید/حجم، کانفیگ تست خودکار،
// عضویت اجباری و هشدار موجودی همگی به‌طور کامل‌تر در صفحه‌ی «تنظیمات فروش» هستند؛
// اینجا تکرار نمی‌شوند تا تنظیمات فروش فقط یک مرجع داشته باشد.

const SETTINGS_GROUPS = [
  // ---------------------------------------------------------- محتوا و متن‌ها
  { tab: 'content', title: 'متن‌های پایه', fields: [
    { key: 'store_name', label: 'نام فروشگاه', type: 'text' },
    { key: 'welcome_text', label: 'متن خوش‌آمدگویی (شروع ربات)', type: 'textarea' },
    { key: 'contact_text', label: 'متن ابتدای بخش ارتباط با پشتیبانی', type: 'textarea' },
    { key: 'after_buy_text', label: 'متن راهنمای پرداخت (بعد از انتخاب محصول)', type: 'textarea' },
  ]},
  // نکته: متن/رنگ/ترتیب/فعال‌سازی دکمه‌های منوی اصلی ربات، و همچنین رنگ
  // دکمه‌های مسیر خرید (انتخاب دسته/محصول/ادامه/کد تخفیف/بازگشت) دیگر اینجا
  // نیست؛ برای یکپارچه‌سازی، همه‌شان به تب «دکمه‌های ربات» منتقل شدند.
  { tab: 'content', title: '🛍 دکمه مینی‌اپ فروشگاه', fields: [
    { key: 'miniapp_button_text', label: 'نام دکمه فروشگاه در منوی اصلی ربات', type: 'text' },
    { key: 'miniapp_button_style', label: 'رنگ دکمه فروشگاه', type: 'select', options: [['', 'پیش‌فرض'], ['primary', 'آبی'], ['success', 'سبز'], ['danger', 'قرمز']] },
    { key: 'miniapp_menu_button_text', label: 'نام دکمه فروشگاه کنار کادر پیام تلگرام', type: 'text' },
  ]},
  { tab: 'content', title: '📨 قالب پیام تحویل کانفیگ بر اساس نوع پنل', fields: [
    { key: 'delivery_message_template_default', label: 'قالب تحویل — عمومی', type: 'textarea' },
    { key: 'delivery_message_template_pasarguard', label: 'قالب تحویل — PasarGuard', type: 'textarea' },
    { key: 'delivery_message_template_3xui', label: 'قالب تحویل — 3X-UI', type: 'textarea' },
    { key: 'delivery_message_template_marzban', label: 'قالب تحویل — Marzban', type: 'textarea' },
    { key: 'delivery_message_template_marzneshin', label: 'قالب تحویل — Marzneshin', type: 'textarea' },
    { key: 'delivery_message_template_hiddify', label: 'قالب تحویل — Hiddify', type: 'textarea' },
    { key: 'delivery_message_template_alireza', label: 'قالب تحویل — Alireza', type: 'textarea' },
    { key: 'delivery_message_template_rebecca', label: 'قالب تحویل — Rebecca', type: 'textarea' },
    { key: 'delivery_message_template_sui', label: 'قالب تحویل — SUI', type: 'textarea' },
    { key: 'delivery_message_template_wgdashboard', label: 'قالب تحویل — WGDashboard', type: 'textarea' },
    { key: 'delivery_message_template_mikrotik', label: 'قالب تحویل — MikroTik', type: 'textarea' },
    { key: 'delivery_message_template_ibsng', label: 'قالب تحویل — IBSng', type: 'textarea' },
    { key: 'delivery_message_template_wui', label: 'قالب تحویل — WUI', type: 'textarea' },
    { key: 'delivery_message_template_stealth', label: 'قالب تحویل — Stealth', type: 'textarea' },
  ]},
  { tab: 'content', title: '🗺 نقشه زنده شبکه — مکان سرورها (دستی)', fields: [
    { key: 'netmap_locations', label: 'مکان سرورها', type: 'netmap_simple' },
  ]},


  // ------------------------------------------------------------ پرداخت و مالی
  { tab: 'payment', title: 'کارت بانکی', fields: [
    { key: 'card_number', label: 'شماره کارت', type: 'text' },
    { key: 'card_holder', label: 'نام صاحب کارت', type: 'text' },
  ]},
  { tab: 'payment', title: '🏦 استعلام بانکی رسید (کارت↔شبا، نام صاحب کارت)', fields: [
    { key: 'bank_inquiry_enabled', label: 'فعال بودن استعلام بانکی (پیش‌فرض خاموش؛ چک محلی کد بانک شبا همیشه فعال است)', type: 'bool' },
    { key: 'bank_inquiry_url', label: 'آدرس API سرویس استعلام (می‌تواند {card} داشته باشد)', type: 'text' },
    { key: 'bank_inquiry_method', label: 'متد: GET یا POST', type: 'text' },
    { key: 'bank_inquiry_headers_json', label: 'هدرها (JSON، مثلاً {"Authorization":"Bearer ..."})', type: 'password' },
    { key: 'bank_inquiry_body_json', label: 'بدنه‌ی JSON برای POST (مثلاً {"card":"{card}"})', type: 'textarea' },
    { key: 'bank_inquiry_iban_path', label: 'مسیر شبا در پاسخ (مثلاً data.iban)', type: 'text' },
    { key: 'bank_inquiry_owner_path', label: 'مسیر نام صاحب کارت؛ چند مسیر با ویرگول (مثلاً data.first_name,data.last_name)', type: 'text' },
    { key: 'bank_inquiry_timeout', label: 'مهلت پاسخ (ثانیه)', type: 'number' },
    { key: 'bank_inquiry_cache_hours', label: 'مدت کش نتیجه (ساعت)', type: 'number' },
    { key: 'bank_inquiry_auto_reject', label: 'رد خودکار رسید وقتی مقصد طبق استعلام قطعاً اشتباه است (پیش‌فرض خاموش = فقط هشدار)', type: 'bool' },
  ]},
  { tab: 'payment', title: 'نرخ ارز پشتیبان (عمومی فروشگاه)', fields: [
    { key: 'manual_usd_rate_toman', label: 'نرخ دلار دستی — فقط وقتی همه‌ی منابع زنده شکست بخورند استفاده می‌شود', type: 'number' },
  ]},
  { tab: 'payment', title: '🪙 پرداخت کریپتو (Plisio)', fields: [
    { key: 'crypto_payment_enabled', label: 'فعال بودن پرداخت کریپتو', type: 'bool' },
    { key: 'plisio_api_key', label: 'کلید API درگاه Plisio', type: 'password' },
  ]},
  { tab: 'payment', title: '💳 آبان گیت‌وی (کارت به کارت خودکار)', fields: [
    { key: 'abangateway_payment_enabled', label: 'فعال بودن درگاه آبان گیت‌وی', type: 'bool' },
    { key: 'abangateway_api_key', label: 'کلید API آبان گیت‌وی', type: 'password' },
  ]},
  { tab: 'payment', title: '💳 بلوپال (کارت به کارت خودکار)', fields: [
    { key: 'blupal_payment_enabled', label: 'فعال بودن درگاه بلوپال', type: 'bool' },
    { key: 'blupal_api_key', label: 'کلید API بلوپال', type: 'password' },
  ]},
  { tab: 'payment', title: '⭐ NoapayBot - استارز تلگرام (تایید آنی)', fields: [
    { key: 'noapay_payment_enabled', label: 'فعال بودن درگاه NoapayBot', type: 'bool' },
    { key: 'noapay_api_key', label: 'کلید API NoapayBot', type: 'password' },
    { key: 'noapay_webhook_secret', label: 'رمز HMAC وب‌هوک (X-Starbot-Signature)', type: 'password' },
    { key: 'noapay_rate_toman_per_star', label: 'نرخ تومان به‌ازای هر استارز', type: 'number' },
  ]},
  { tab: 'payment', title: '🟡 زرین‌پال (تایید آنی)', fields: [
    { key: 'zarinpal_payment_enabled', label: 'فعال بودن درگاه زرین‌پال', type: 'bool' },
    { key: 'zarinpal_merchant_id', label: 'مرچنت کد', type: 'password' },
  ]},
  { tab: 'payment', title: '🔵 آقای پرداخت (تایید آنی)', fields: [
    { key: 'aqayepardakht_payment_enabled', label: 'فعال بودن درگاه آقای پرداخت', type: 'bool' },
    { key: 'aqayepardakht_pin', label: 'پین درگاه', type: 'password' },
  ]},
  { tab: 'payment', title: '💸 تترا۹۸ (تایید آنی)', fields: [
    { key: 'tetra98_payment_enabled', label: 'فعال بودن درگاه تترا۹۸', type: 'bool' },
    { key: 'tetra98_api_key', label: 'کلید API', type: 'password' },
  ]},
  { tab: 'payment', title: '💳 کیوب‌پی (تایید آنی)', fields: [
    { key: 'cubepay_payment_enabled', label: 'فعال بودن درگاه کیوب‌پی', type: 'bool' },
    { key: 'cubepay_token', label: 'توکن API', type: 'password' },
    { key: 'cubepay_fee', label: 'کارمزد اضافه به مبلغ کاربر (درصد تا ۱۰۰، بالاتر یعنی مبلغ ثابت تومان)', type: 'number' },
  ]},
  { tab: 'payment', title: '💰 NowPayments (تایید آنی)', fields: [
    { key: 'nowpayments_payment_enabled', label: 'فعال بودن درگاه NowPayments', type: 'bool' },
    { key: 'nowpayments_api_key', label: 'کلید API', type: 'password' },
    { key: 'nowpayments_ipn_secret', label: 'IPN Secret (پیشنهادی)', type: 'password' },
  ]},
  { tab: 'payment', title: '⭐ استارز داخلی تلگرام (تایید آنی)', fields: [
    { key: 'tgstars_payment_enabled', label: 'فعال بودن درگاه استارز داخلی تلگرام', type: 'bool' },
    { key: 'tgstars_rate_toman_per_star', label: 'نرخ دستی هر استارز (تومان) - ۰ یعنی خودکار', type: 'number' },
    { key: 'tgstars_usd_per_star', label: 'ارزش هر استارز به دلار (نرخ خودکار)', type: 'number' },
    { key: 'tgstars_margin_percent', label: 'درصد حاشیه سود روی نرخ خودکار', type: 'number' },
  ]},
  { tab: 'payment', title: '📡 کارت‌به‌کارت با تایید خودکار (پیامک بانک)', fields: [
    { key: 'card_to_card_auto_enabled', label: 'فعال بودن (نیازمند حداقل یک کارت فعال - پایین همین صفحه)', type: 'bool' },
    { key: 'card_to_card_auto_timeout_minutes', label: 'مهلت هر مبلغ (دقیقه) - بعدش می‌رود صف بررسی دستی', type: 'number' },
    { key: 'card_to_card_auto_amount_digits', label: 'تعداد رقم آخر برای یکتاسازی مبلغ (پیشنهاد: ۳)', type: 'number' },
    { key: 'card_to_card_sms_amount_unit', label: 'واحد مبلغ داخل پیامک بانک', type: 'select', options: [['rial', 'ریال (اکثر بانک‌ها)'], ['toman', 'تومان']] },
  ]},

  // ------------------------------------------------------ سرویس‌های ویژه
  { tab: 'sales', title: '📱 تایید شماره موبایل برای خرید', fields: [
    { key: 'phone_verify_enabled', label: 'خرید فقط با شماره‌ی تاییدشده (اشتراک‌گذاری با دکمه‌ی تلگرام) — بات و مینی‌اپ', type: 'bool' },
    { key: 'phone_verify_countries', label: 'کشورهای مجاز', type: 'phone_countries' },
  ]},
  { tab: 'sales', title: '🛒 سقف تعداد خرید در هر سفارش', fields: [
    { key: 'auto_provision_max_qty', label: 'حداکثر تعداد محصولات خودکار در هر سفارش (۰=نامحدود)', type: 'number' },
  ] },
  { tab: 'sales', title: '🧹 پاکسازی سرویس‌ها', fields: [
    { key: 'inactive_config_delete_time', label: 'ساعت حذف خودکار کانفیگ‌های غیرفعال (HH:MM به وقت تهران؛ خالی = خاموش)', type: 'text' },
  ]},
  { tab: 'system', title: '📊 گزارش روزانه‌ی فروش', fields: [
    { key: 'daily_report_enabled', label: 'ارسال گزارش روزانه‌ی فروش به مدیران', type: 'bool' },
    { key: 'daily_report_time', label: 'ساعت ارسال به وقت تهران (مثل 23:45)', type: 'text' },
  ] },
  { tab: 'system', title: '🩺 پایش سلامت پنل‌های VPN', fields: [
    { key: 'panel_health_enabled', label: 'هشدار قطعی و بازیابی پنل‌ها به مدیران (بررسی هر ۵ دقیقه)', type: 'bool' },
  ] },
  { tab: 'system', title: '🛡 ضداسپم کاربران', fields: [
    { key: 'spam_guard_enabled', label: 'فعال بودن ضداسپم (هشدار و سپس مسدودسازی خودکار)', type: 'bool' },
    { key: 'spam_limit', label: 'حداکثر تعداد درخواست در بازه‌ی زمانی', type: 'number' },
    { key: 'spam_window', label: 'بازه‌ی زمانی (ثانیه)', type: 'number' },
  ] },
  { tab: 'sales', title: 'کانفیگ شخصی/سفارشی', fields: [
    { key: 'custom_config_enabled', label: 'فعال بودن ساخت کانفیگ شخصی', type: 'bool' },
    { key: 'custom_config_min_gb', label: 'حداقل حجم مجاز (گیگ)', type: 'number' },
    { key: 'custom_config_max_gb', label: 'حداکثر حجم مجاز (گیگ)', type: 'number' },
    { key: 'custom_config_duration_days', label: 'مدت اعتبار (روز)', type: 'number' },
    { key: 'btn_custom_config', label: 'متن دکمه ساخت کانفیگ شخصی', type: 'text' },
  ]},
  { tab: 'sales', title: '🧾 نمایش دکمه‌های حساب کاربری', fields: [
    { key: 'acct_show_orders', label: 'نمایش «سرویس‌ها و سفارش‌های من»', type: 'bool' },
    { key: 'acct_show_referral', label: 'نمایش «زیرمجموعه‌گیری من»', type: 'bool' },
    { key: 'acct_show_wallet', label: 'نمایش «کیف پول من»', type: 'bool' },
    { key: 'acct_show_add_service', label: 'نمایش «افزودن حساب (اتصال کانفیگ قبلی)»', type: 'bool' },
    { key: 'acct_show_merge', label: 'نمایش «ادغام با حساب ایمیلی»', type: 'bool' },
    { key: 'acct_show_smartsub', label: 'نمایش «اشتراک هوشمند (ادغام کانفیگ‌ها)»', type: 'bool' },
    { key: 'acct_add_service_by_username', label: 'افزودن حساب با نام کاربری کانفیگ (علاوه بر لینک ساب)', type: 'bool' },
  ]},
  { tab: 'sales', title: '🛠 نمایش دکمه‌های سرویس', fields: [
    { key: 'svc_show_renew_full', label: 'دکمه «تمدید کامل سرویس»', type: 'bool' },
    { key: 'svc_show_renew_volume', label: 'دکمه «تمدید حجم سرویس»', type: 'bool' },
    { key: 'svc_show_renew_time', label: 'دکمه «تمدید زمان سرویس»', type: 'bool' },
    { key: 'svc_show_cut_access', label: 'دکمه «قطع دسترسی و لینک جدید»', type: 'bool' },
    { key: 'svc_show_update_config', label: 'دکمه «بروزرسانی کانفیگ»', type: 'bool' },
    { key: 'svc_show_qr', label: 'دکمه «کیوآر کانفیگ»', type: 'bool' },
    { key: 'svc_show_delete', label: 'دکمه «حذف کامل سرویس»', type: 'bool' },
    { key: 'svc_refund_window_hours', label: 'مهلت بازگشت وجه هنگام حذف سرویس (ساعت پس از خرید؛ ۰ = غیرفعال)', type: 'number' },
    { key: 'svc_show_toggle', label: 'دکمه «فعال/غیرفعال کردن کانفیگ»', type: 'bool' },
    { key: 'svc_show_rename', label: 'دکمه «تغییر نام کانفیگ»', type: 'bool' },
    { key: 'svc_show_auto_renew', label: 'دکمه «تمدید خودکار»', type: 'bool' },
    { key: 'svc_show_transfer', label: 'دکمه «انتقال کانفیگ»', type: 'bool' },
    { key: 'svc_show_history', label: 'دکمه «تاریخچه سرویس»', type: 'bool' },
  ]},

  // -------------------------------------------------------------- اپ موبایل
  // این ۴ مقدار از پروژه‌ی فایربیس خودت می‌آید (کنسول فایربیس > تنظیمات پروژه
  // > اپ اندروید با پکیج com.shopvpn.admin > google-services.json). این مقادیر
  // محرمانه نیستند (داخل هر APK قابل مشاهده‌اند)، فقط برای تشخیص پروژه‌اند؛
  // اپ اندروید این‌ها را در زمان اجرا برای فعال‌شدن پوش لحظه‌ای (FCM) می‌خواند.
  { tab: 'mobile_app', title: '🔔 پوش نوتیف اندروید (Firebase)', fields: [
    { key: '_push_guide_button', label: 'راهنمای کامل فعال‌سازی پوش (قدم به قدم)', type: 'push_guide_button' },
    { key: '_firebase_json_extract', label: 'استخراج خودکار از google-services.json (پیشنهادی)', type: 'firebase_json_extract' },
    { key: 'firebase_api_key', label: 'Firebase API Key', type: 'text' },
    { key: 'firebase_app_id', label: 'Firebase App ID', type: 'text' },
    { key: 'firebase_project_id', label: 'Firebase Project ID', type: 'text' },
    { key: 'firebase_sender_id', label: 'Firebase Sender ID (Project number)', type: 'text' },
  ]},
  // این یکی جدا از ۴ فیلد بالاست: آن ۴ تا فقط برای مقداردهی فایربیس داخل خودِ
  // اپ اندروید هستند (تا اپ بتواند توکن FCM بگیرد)، ولی این JSON برای سمت
  // سرور است تا خودِ سرور بتواند واقعاً پوش بفرستد (Firebase Console > Project
  // Settings > Service Accounts > Generate new private key، کل فایل دانلودی
  // را همین‌جا پیست کن). بدون این فیلد، حتی اگر توکن دستگاه درست ثبت شده
  // باشد، هیچ پوشی فرستاده نمی‌شود.
  { tab: 'mobile_app', title: '🔐 سرویس‌اکانت فایربیس (سمت سرور - برای واقعاً فرستادن پوش)', fields: [
    { key: 'firebase_service_account_json', label: 'Firebase Service Account JSON (کل فایل دانلودی را اینجا پیست کن)', type: 'textarea' },
  ]},
  // دکمه‌ای که یک پوش واقعی به آخرین دستگاه ثبت‌شده‌ی همین ادمین می‌فرستد و
  // خطای واقعی گوگل را نشان می‌دهد - به‌جای اینکه برای تست، منتظر یک سفارش
  // واقعی بمانی و از سکوت حدس بزنی مشکل کجاست.
  { tab: 'mobile_app', title: '🧪 تست ارسال پوش', fields: [
    { key: '_push_test_button', label: 'ارسال یک پوش آزمایشی به آخرین دستگاه ثبت‌شده‌ی این ادمین', type: 'push_test_button' },
  ]},
];

function settingsUiText(value) {
  // Settings are generated dynamically, so translate the source label before
  // inserting it into the DOM instead of relying only on the mutation observer.
  // This keeps the settings screen bilingual even when a section is rendered
  // or re-rendered before the observer runs.
  return (typeof window.ShopVPNTranslate === 'function')
    ? window.ShopVPNTranslate(String(value ?? ''))
    : String(value ?? '');
}

/* ---------------------------------------------- ویرایشگر ساده‌ی مکان سرورها - */
const NETMAP_CITIES = [
  ['de','Frankfurt','فرانکفورت (آلمان)',50.11,8.68],['nl','Amsterdam','آمستردام (هلند)',52.37,4.90],
  ['gb','London','لندن (انگلیس)',51.51,-0.13],['fr','Paris','پاریس (فرانسه)',48.86,2.35],
  ['fi','Helsinki','هلسینکی (فنلاند)',60.17,24.94],['se','Stockholm','استکهلم (سوئد)',59.33,18.07],
  ['no','Oslo','اسلو (نروژ)',59.91,10.75],['dk','Copenhagen','کپنهاگ (دانمارک)',55.68,12.57],
  ['ch','Zurich','زوریخ (سوئیس)',47.38,8.54],['at','Vienna','وین (اتریش)',48.21,16.37],
  ['it','Milan','میلان (ایتالیا)',45.46,9.19],['es','Madrid','مادرید (اسپانیا)',40.42,-3.70],
  ['pt','Lisbon','لیسبون (پرتغال)',38.72,-9.14],['ie','Dublin','دوبلین (ایرلند)',53.35,-6.26],
  ['pl','Warsaw','ورشو (لهستان)',52.23,21.01],['cz','Prague','پراگ (چک)',50.08,14.44],
  ['ro','Bucharest','بخارست (رومانی)',44.43,26.10],['bg','Sofia','صوفیه (بلغارستان)',42.70,23.32],
  ['lt','Vilnius','ویلنیوس (لیتوانی)',54.69,25.28],['lv','Riga','ریگا (لتونی)',56.95,24.11],
  ['ee','Tallinn','تالین (استونی)',59.44,24.75],['ua','Kyiv','کیف (اوکراین)',50.45,30.52],
  ['ru','Moscow','مسکو (روسیه)',55.76,37.62],['tr','Istanbul','استانبول (ترکیه)',41.01,28.98],
  ['am','Yerevan','ایروان (ارمنستان)',40.18,44.51],['kz','Almaty','آلماتی (قزاقستان)',43.24,76.89],
  ['ae','Dubai','دبی (امارات)',25.20,55.27],['ir','Tehran','تهران (ایران)',35.69,51.39],
  ['in','Mumbai','بمبئی (هند)',19.08,72.88],['sg','Singapore','سنگاپور',1.35,103.82],
  ['hk','Hong Kong','هنگ‌کنگ',22.32,114.17],['jp','Tokyo','توکیو (ژاپن)',35.68,139.69],
  ['kr','Seoul','سئول (کره جنوبی)',37.57,126.98],['au','Sydney','سیدنی (استرالیا)',-33.87,151.21],
  ['us','New York','نیویورک (آمریکا)',40.71,-74.01],['us','Los Angeles','لس‌آنجلس (آمریکا)',34.05,-118.24],
  ['us','Dallas','دالاس (آمریکا)',32.78,-96.80],['us','Miami','میامی (آمریکا)',25.76,-80.19],
  ['us','Chicago','شیکاگو (آمریکا)',41.88,-87.63],['ca','Toronto','تورنتو (کانادا)',43.65,-79.38],
  ['br','Sao Paulo','سائوپائولو (برزیل)',-23.55,-46.63],
];
let nmProductsCache = null;
async function nmLoadProducts() {
  if (nmProductsCache) return nmProductsCache;
  try { nmProductsCache = (await apiGet('/products')) || []; } catch (_) { nmProductsCache = []; }
  return nmProductsCache;
}
function nmCityIndex(o) {
  const lat = Number(o.lat), lon = Number(o.lon);
  return NETMAP_CITIES.findIndex(c => c[0] === String(o.cc || '').toLowerCase() && Math.abs(c[3] - lat) < 0.05 && Math.abs(c[4] - lon) < 0.05);
}
function nmParse(raw) {
  const rows = [], legacy = [];
  let data = [];
  try { data = raw && raw.trim() ? JSON.parse(raw) : []; } catch (_) { data = []; }
  (Array.isArray(data) ? data : []).forEach(o => {
    const ids = (o.product_ids || []).map(Number).filter(Boolean);
    const ci = nmCityIndex(o);
    if (ids.length >= 1 && !o.match && ci >= 0) ids.forEach(id => rows.push({ pid: id, ci }));
    else legacy.push(o);
  });
  return { rows, legacy };
}
function nmRender(ed) {
  const prods = nmProductsCache || [];
  const box = ed.querySelector('.nm-rows');
  box.innerHTML = ed.__rows.map((r, i) => `
    <div class="nm-row" data-i="${i}" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <select class="input nm-prod" style="flex:1;min-width:150px">
        <option value="">— محصول —</option>
        ${prods.map(p => `<option value="${p.id}" ${Number(p.id) === Number(r.pid) ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}
        ${r.pid && !prods.some(p => Number(p.id) === Number(r.pid)) ? `<option value="${r.pid}" selected>محصول شماره ${r.pid}</option>` : ''}
      </select>
      <select class="input nm-city" style="flex:1;min-width:150px">
        <option value="">— شهر —</option>
        ${NETMAP_CITIES.map((c, ci) => `<option value="${ci}" ${ci === r.ci ? 'selected' : ''}>${esc(c[2])}</option>`).join('')}
      </select>
      <button type="button" class="btn btn-sm nm-del" title="حذف">🗑</button>
    </div>`).join('') + (ed.__legacy.length ? `<div class="card-sub">${ed.__legacy.length} مورد از تنظیمات قدیمی هم نگه داشته شده است.</div>` : '');
}
function nmSync(ed) {
  const out = ed.__legacy.slice();
  const byCity = {};
  ed.__rows.forEach(r => {
    if (!r.pid || r.ci === '' || r.ci == null || !NETMAP_CITIES[r.ci]) return;
    (byCity[r.ci] = byCity[r.ci] || []).push(Number(r.pid));
  });
  Object.keys(byCity).forEach(ci => {
    const c = NETMAP_CITIES[ci];
    out.push({ product_ids: byCity[ci], cc: c[0], city: c[1], city_fa: c[2].replace(/\s*\(.*\)$/, ''), lat: c[3], lon: c[4] });
  });
  ed.querySelector('input[type=hidden]').value = out.length ? JSON.stringify(out) : '';
}
async function nmInit(ed) {
  if (ed.dataset.ready) return;
  ed.dataset.ready = '1';
  const { rows, legacy } = nmParse(ed.dataset.nmRaw || '');
  ed.__rows = rows; ed.__legacy = legacy;
  nmRender(ed);
  await nmLoadProducts();
  nmRender(ed);
}
document.addEventListener('click', e => {
  const ed = e.target.closest && e.target.closest('.netmap-ed'); if (!ed) return;
  if (e.target.closest('.nm-add')) { ed.__rows.push({ pid: '', ci: '' }); nmRender(ed); }
  const del = e.target.closest('.nm-del');
  if (del) { ed.__rows.splice(Number(del.closest('.nm-row').dataset.i), 1); nmRender(ed); nmSync(ed); }
});
document.addEventListener('change', e => {
  const ed = e.target.closest && e.target.closest('.netmap-ed'); if (!ed) return;
  const row = e.target.closest('.nm-row'); if (!row) return;
  const r = ed.__rows[Number(row.dataset.i)];
  if (e.target.classList.contains('nm-prod')) r.pid = e.target.value;
  if (e.target.classList.contains('nm-city')) r.ci = e.target.value === '' ? '' : Number(e.target.value);
  nmSync(ed);
});
new MutationObserver(() => document.querySelectorAll('.netmap-ed:not([data-ready])').forEach(nmInit))
  .observe(document.body, { childList: true, subtree: true });


const PHONE_COUNTRY_DEFAULTS = [
  ['98', '🇮🇷 ایران', true], ['93', '🇦🇫 افغانستان', false], ['964', '🇮🇶 عراق', false], ['90', '🇹🇷 ترکیه', false],
  ['971', '🇦🇪 امارات', false], ['966', '🇸🇦 عربستان', false], ['965', '🇰🇼 کویت', false], ['974', '🇶🇦 قطر', false],
  ['973', '🇧🇭 بحرین', false], ['968', '🇴🇲 عمان', false], ['92', '🇵🇰 پاکستان', false], ['91', '🇮🇳 هند', false],
  ['994', '🇦🇿 آذربایجان', false], ['374', '🇦🇲 ارمنستان', false], ['993', '🇹🇲 ترکمنستان', false], ['992', '🇹🇯 تاجیکستان', false],
  ['998', '🇺🇿 ازبکستان', false], ['7', '🇷🇺 روسیه / قزاقستان', false], ['49', '🇩🇪 آلمان', false], ['44', '🇬🇧 انگلیس', false],
  ['1', '🇺🇸 آمریکا / کانادا', false], ['33', '🇫🇷 فرانسه', false], ['31', '🇳🇱 هلند', false], ['46', '🇸🇪 سوئد', false],
];
function pcParse(raw) {
  let data = [];
  try { data = raw && raw.trim() ? JSON.parse(raw) : []; } catch (_) { data = []; }
  if (!Array.isArray(data) || !data.length) return PHONE_COUNTRY_DEFAULTS.map(([p, n, a]) => ({ p, n, a }));
  return data.map(o => ({ p: String(o.p || ''), n: String(o.n || ''), a: !!o.a }));
}
function pcRender(ed) {
  ed.querySelector('.pc-rows').innerHTML = ed.__rows.map((r, i) => `
    <div class="pc-row" data-i="${i}" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <input type="checkbox" class="pc-allow" ${r.a ? 'checked' : ''} title="مجاز">
      <span dir="ltr">+</span>
      <input class="input pc-prefix" dir="ltr" inputmode="numeric" placeholder="98" style="width:84px" value="${esc(r.p)}">
      <input class="input pc-name" placeholder="نام کشور" style="flex:1;min-width:130px" value="${esc(r.n)}">
      <button type="button" class="btn btn-sm pc-del" title="حذف">🗑</button>
    </div>`).join('');
}
function pcSync(ed) {
  const out = ed.__rows
    .map(r => ({ p: String(r.p || '').replace(/\D/g, ''), n: String(r.n || '').trim(), a: !!r.a }))
    .filter(r => r.p && r.n);
  ed.querySelector('input[type=hidden]').value = JSON.stringify(out);
}
function pcInit(ed) {
  if (ed.dataset.ready) return;
  ed.dataset.ready = '1';
  ed.__rows = pcParse(ed.dataset.pcRaw || '');
  pcRender(ed);
}
document.addEventListener('click', e => {
  const ed = e.target.closest && e.target.closest('.phone-ed'); if (!ed) return;
  if (e.target.closest('.pc-add')) { ed.__rows.push({ p: '', n: '', a: true }); pcRender(ed); return; }
  const del = e.target.closest('.pc-del');
  if (del) { ed.__rows.splice(Number(del.closest('.pc-row').dataset.i), 1); pcRender(ed); pcSync(ed); }
});
document.addEventListener('input', e => {
  const ed = e.target.closest && e.target.closest('.phone-ed'); if (!ed) return;
  const row = e.target.closest('.pc-row'); if (!row) return;
  const r = ed.__rows[Number(row.dataset.i)];
  if (e.target.classList.contains('pc-prefix')) r.p = e.target.value;
  if (e.target.classList.contains('pc-name')) r.n = e.target.value;
  pcSync(ed);
});
document.addEventListener('change', e => {
  const ed = e.target.closest && e.target.closest('.phone-ed'); if (!ed) return;
  const row = e.target.closest('.pc-row'); if (!row) return;
  if (e.target.classList.contains('pc-allow')) { ed.__rows[Number(row.dataset.i)].a = e.target.checked; pcSync(ed); }
});
new MutationObserver(() => document.querySelectorAll('.phone-ed:not([data-ready])').forEach(pcInit))
  .observe(document.body, { childList: true, subtree: true });

function settingsFieldHtml(f, settings) {
  const val = settings[f.key] ?? '';
  if (f.type === 'bool') {
    const on = val === '1' || val === 1 || val === true;
    return `
      <label class="field field-row">
        <span>${esc(settingsUiText(f.label))}</span>
        <span class="switch" data-key="${f.key}" data-type="bool" data-on="${on ? '1' : '0'}"><i></i></span>
      </label>`;
  }
  if (f.type === 'push_test_button') {
    return `<label class="field">
      <span>${esc(settingsUiText(f.label))}</span>
      <button type="button" class="btn btn-sm push-test-btn">ارسال پوش تست</button>
    </label>`;
  }
  if (f.type === 'sub_template_tools') {
    return `<label class="field">
      <span>${esc(settingsUiText(f.label))}</span>
      <span class="card-sub">قالب اختصاصی فقط وقتی اعمال می‌شود که کلید بالا روشن و کد معتبر باشد؛ در غیر این‌صورت (یا اگر خطایی پیش بیاید) خودکار قالب پیش‌فرض نمایش داده می‌شود.</span>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
        <button type="button" class="btn btn-sm sub-tpl-default-btn">⬇️ پر کردن با قالب پیش‌فرض (برای ویرایش)</button>
        <button type="button" class="btn btn-sm sub-tpl-upload-btn">📤 آپلود فایل .html</button>
        <input type="file" class="sub-tpl-upload-input" accept=".html,.htm,text/html" hidden>
        <button type="button" class="btn btn-sm sub-tpl-guide-btn">📖 راهنمای متغیرها</button>
      </div>
    </label>`;
  }
  if (f.type === 'code') {
    return `<label class="field"><span>${esc(settingsUiText(f.label))}</span>
      <textarea class="input" rows="14" dir="ltr" spellcheck="false" style="font-family:monospace;font-size:12px;white-space:pre" data-key="${f.key}" data-type="text">${esc(val)}</textarea></label>`;
  }
  if (f.type === 'push_guide_button') {
    return `<label class="field">
      <span>${esc(settingsUiText(f.label))}</span>
      <button type="button" class="btn btn-sm push-guide-btn">📖 مشاهده راهنما</button>
    </label>`;
  }
  if (f.type === 'firebase_json_extract') {
    return `<label class="field">
      <span>${esc(settingsUiText(f.label))}</span>
      <span class="card-sub">کل فایل google-services.json (کنسول فایربیس &gt; تنظیمات پروژه &gt; اپ اندروید com.shopvpn.admin) را دانلود کن و محتواش را اینجا پیست کن؛ ۴ فیلد پایین خودکار پر می‌شوند - نیازی به کپی دستی تک‌تک مقادیر نیست.</span>
      <div class="firebase-json-extract">
        <textarea class="input" rows="4" placeholder='{"project_info": {...}, "client": [...]}'></textarea>
        <button type="button" class="btn btn-sm firebase-json-extract-btn" style="margin-top:8px">استخراج و پرکردن خودکار</button>
      </div>
    </label>`;
  }
  if (f.type === 'phone_countries') {
    return `<div class="field phone-ed" data-pc-raw="${esc(val)}">
      <span class="card-sub">فقط شماره‌هایی که پیش‌شماره‌ی تیک‌خورده دارند می‌توانند خرید کنند. شماره فقط با دکمه‌ی اشتراک‌گذاری تلگرام (و فقط شماره‌ی خود کاربر) پذیرفته می‌شود. پیش‌شماره را بدون + و صفر وارد کن.</span>
      <div class="pc-rows" style="display:flex;flex-direction:column;gap:8px;margin-top:10px"></div>
      <button type="button" class="btn btn-sm pc-add" style="margin-top:10px">➕ افزودن کشور</button>
      <input type="hidden" data-key="${f.key}" data-type="text" value="${esc(val)}">
    </div>`;
  }
  if (f.type === 'netmap_simple') {
    return `<div class="field netmap-ed" data-nm-raw="${esc(val)}">
      <span class="card-sub">اگر مکان یک سرور روی «نقشه زنده شبکه» اشتباه است، این‌جا محصول را انتخاب کن و شهر درستش را بزن. اگر خالی بماند، مکان‌ها خودکار تشخیص داده می‌شوند.</span>
      <div class="nm-rows" style="display:flex;flex-direction:column;gap:8px;margin-top:10px"></div>
      <button type="button" class="btn btn-sm nm-add" style="margin-top:10px">➕ افزودن مکان</button>
      <input type="hidden" data-key="${f.key}" data-type="text" value="${esc(val)}">
    </div>`;
  }
  if (f.type === 'textarea') {
    return `<label class="field"><span>${esc(settingsUiText(f.label))}</span>
      <textarea class="input" rows="3" data-key="${f.key}" data-type="text">${esc(val)}</textarea></label>`;
  }
  if (f.type === 'select') {
    return `<label class="field"><span>${esc(settingsUiText(f.label))}</span>
      <select class="input" data-key="${f.key}" data-type="text">
        ${f.options.map(([v, l]) => `<option value="${v}" ${val === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}
      </select></label>`;
  }
  if (f.type === 'color') {
    const cur = ['primary', 'success', 'danger'].includes(val) ? val : '';
    const swatches = [['', 'swatch-default', 'پیش‌فرض (خاکستری)'], ['primary', 'swatch-primary', 'آبی'], ['success', 'swatch-success', 'سبز'], ['danger', 'swatch-danger', 'قرمز']];
    return `<label class="field"><span>${esc(settingsUiText(f.label))}</span>
      <div class="color-pick" data-key="${f.key}" data-color="${cur}">
        ${swatches.map(([v, cls, title]) => `<button type="button" class="color-swatch ${cls} ${cur === v ? 'active' : ''}" data-value="${v}" title="${esc(settingsUiText(title))}"></button>`).join('')}
      </div></label>`;
  }
  if (f.type === 'image') {
    return `
      <label class="field">
        <span>${esc(settingsUiText(f.label))}</span>
        <div class="image-field" data-key="${f.key}">
          ${val ? `<img src="${val}" class="image-field-preview">` : '<span class="card-sub">تصویری تنظیم نشده</span>'}
          <div class="image-field-actions">
            <input type="file" accept="image/*" class="image-field-input" hidden>
            <button type="button" class="btn btn-sm image-field-pick">انتخاب تصویر</button>
            ${val ? '<button type="button" class="btn btn-sm btn-danger image-field-clear">حذف</button>' : ''}
          </div>
          <input type="hidden" data-key="${f.key}" data-type="text" value="${esc(val)}">
        </div>
      </label>`;
  }
  return `<label class="field"><span>${esc(settingsUiText(f.label))}</span>
    <input class="input" type="${f.type === 'password' ? 'password' : f.type === 'number' ? 'number' : 'text'}"${f.type === 'number' ? ' step="any"' : ''} data-key="${f.key}" data-type="text" value="${esc(val)}"></label>`;
}

let settingsActiveTab = 'content';

function renderSettingsGroups(settings) {
  const seen = new Set();
  return `<div class="settings-accordion" id="settings-accordion">
    ${SETTINGS_GROUPS.map(g => {
      const isFirstInTab = !seen.has(g.tab);
      seen.add(g.tab);
      return `
      <div class="settings-group ${isFirstInTab ? 'open' : ''}" data-settings-tab="${g.tab}" style="${g.tab === settingsActiveTab ? '' : 'display:none'}">
        <button type="button" class="settings-group-head">
          <span>${esc(settingsUiText(g.title))}</span>
          <span class="settings-group-arrow">˅</span>
        </button>
        <div class="settings-group-body"><div class="form-grid">
          ${g.fields.map(f => settingsFieldHtml(f, settings)).join('')}
        </div></div>
      </div>`;
    }).join('')}
  </div>
  <div class="settings-live-preview" data-settings-tab="content" style="${settingsActiveTab === 'content' ? '' : 'display:none'}">
    <div class="settings-live-preview-head">
      <div><strong>🔗 پیش‌نمایش زنده صفحه لینک ساب</strong><div class="card-sub">برندینگ و بخش‌های صفحه ساب را قبل از ذخیره به‌صورت زنده ببین.</div></div>
      <button type="button" class="btn btn-sm" id="sub-page-preview-open">باز کردن در تب جدید</button>
    </div>
    <iframe id="sub-page-preview-frame" title="پیش‌نمایش صفحه لینک ساب" src="/api/settings/sub-page-preview?preview=1" loading="lazy"></iframe>
  </div>`;
}

function settingsTabsHtml() {
  return `<div class="tabs" id="settings-tabs-nav">
    ${SETTINGS_TABS.map(t => `<button type="button" class="tab-btn ${t.key === settingsActiveTab ? 'active' : ''}" data-tab="${t.key}">${settingsUiText(t.label)}</button>`).join('')}
  </div>`;
}

function switchSettingsTab(tab, root) {
  settingsActiveTab = tab;
  $$('#settings-tabs-nav .tab-btn, #settings-tabs-nav .bru-seg-btn, #settings-tabs-nav .bn-seg-btn', root).forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $$('[data-settings-tab]', root).forEach(el => { el.style.display = el.dataset.settingsTab === tab ? '' : 'none'; });
  syncExtraSettingsTab(root);
}

/* ---------------------------------------------- تب «تنظیمات تکمیلی» -- */
// اسکیمای این تب از سرور می‌آید (GET /api/settings/extra) و هر گروه جداگانه
// با POST /api/settings/extra ذخیره می‌شود. عمداً از data-xkey (نه data-key)
// استفاده می‌شود تا دکمه‌ی عمومیِ «ذخیره تغییرات» این فیلدها را (مخصوصاً
// رمزهای ماسک‌شده را) از مسیر /settings ننویسد.‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
const EXTRA_SECRET_MASK = '••••••••';

function extraSettingsTabHtml() {
  return `<div id="extra-settings-root"></div>`;
}

function extraFieldHtml(f, values) {
  const T = settingsUiText;
  const ff = { ...f, key: '__XK__' + f.key, label: f.label };
  let html = settingsFieldHtml(ff, { ['__XK__' + f.key]: values[f.key] ?? f.default ?? '' });
  html = html.split('data-key="__XK__').join('data-xkey="');
  if (f.type === 'password') {
    html = html.replace('type="password"', `type="password" autocomplete="new-password" placeholder="${esc(T('خالی = بدون تغییر'))}"`);
  } else if (f.type === 'number') {
    if (f.min !== undefined) html = html.replace('type="number"', `type="number" min="${esc(f.min)}"`);
    if (f.max !== undefined) html = html.replace('type="number"', `type="number" max="${esc(f.max)}"`);
  }
  const hint = f.hint ? `<div class="card-sub extra-hint">${esc(T(f.hint))}</div>` : '';
  const search = esc(`${f.label} ${f.hint || ''} ${f.key}`.toLowerCase());
  return `<div class="extra-field" data-extra-search="${search}">${html}${hint}</div>`;
}

// تصویر پس‌زمینه‌ی QR (فایل مشترک qr_background.png که بات هم استفاده می‌کند)
function extraQrBackgroundHtml() {
  const T = settingsUiText;
  return `<div class="extra-field extra-qrbg" data-extra-search="${esc('تصویر پس‌زمینه qr background')}" style="margin-top:12px">
    <label class="label">${esc(T('🖼 تصویر پس‌زمینه‌ی QR'))}</label>
    <div class="card-sub" data-qrbg-status>${esc(T('در حال بررسی...'))}</div>
    <img data-qrbg-preview alt="" style="display:none;max-width:160px;border-radius:12px;margin:8px 0">
    <input type="file" accept="image/*" data-qrbg-file class="input" style="margin-top:6px">
    <div class="card-sub extra-hint">${esc(T('حداقل ۳۰۰×۳۰۰ و حداکثر ۸ مگابایت؛ ۵۰۰×۵۰۰ یا بزرگ‌تر پیشنهاد می‌شود.'))}</div>
    <div style="display:flex;gap:8px;margin-top:8px">
      <button type="button" class="btn" data-qrbg-upload>${esc(T('آپلود'))}</button>
      <button type="button" class="btn" data-qrbg-remove style="display:none">${esc(T('حذف'))}</button>
    </div>
  </div>`;
}

async function wireExtraQrBackground(box) {
  const wrap = $('.extra-qrbg', box);
  if (!wrap) return;
  const T = settingsUiText;
  const statusEl = $('[data-qrbg-status]', wrap), img = $('[data-qrbg-preview]', wrap);
  const rm = $('[data-qrbg-remove]', wrap), up = $('[data-qrbg-upload]', wrap), fileEl = $('[data-qrbg-file]', wrap);
  const refresh = async () => {
    try {
      const st = await apiGet('/settings/qr-background');
      statusEl.textContent = st.has
        ? T(st.enabled ? '✅ تصویر آپلود شده و فعال است.' : '⏸ تصویر آپلود شده ولی غیرفعال است.')
        : T('تصویری آپلود نشده؛ QR ساده‌ی سیاه/سفید ارسال می‌شود.');
      rm.style.display = st.has ? '' : 'none';
      if (st.has) {
        const pv = await apiGet('/settings/qr-background/preview');
        img.src = pv.image; img.style.display = '';
      } else {
        img.style.display = 'none';
      }
    } catch (e) { statusEl.textContent = ''; handleErr(e); }
  };
  up.addEventListener('click', async () => {
    const file = fileEl.files[0];
    if (!file) { toast(T('ابتدا یک تصویر انتخاب کن.'), true); return; }
    const fd = new FormData();
    fd.append('photo', file);
    up.disabled = true;
    try {
      const res = await fetch('/api/settings/qr-background', { method: 'POST', credentials: 'include', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(formatApiError(data.detail));
      fileEl.value = '';
      toast(T('تصویر پس‌زمینه ذخیره و فعال شد.'));
      await refresh();
    } catch (e) { toast(e.message, true); }
    finally { up.disabled = false; }
  });
  rm.addEventListener('click', async () => {
    try { await apiDelete('/settings/qr-background'); toast(T('تصویر پس‌زمینه حذف شد.')); await refresh(); }
    catch (e) { handleErr(e); }
  });
  box._refreshQrBg = refresh;
  refresh();
}

function extraSettingsHtml(data) {
  const T = settingsUiText;
  const values = data.values || {};
  // کلیدهایی که فرم عمومی همین صفحه از قبل دارد دوباره نمایش داده نمی‌شوند تا
  // دو فرم روی یک کلید همدیگر را بازنویسی نکنند.
  const existing = new Set();
  SETTINGS_GROUPS.forEach(g => g.fields.forEach(f => existing.add(f.key)));
  const placeOf = g => EXTRA_GROUP_TAB_INDEX[g.id] || { tab: 'system', order: 999 };
  const tabOrder = SETTINGS_TABS.map(t => t.key);
  const groups = (data.groups || []).map(g => ({ ...g, fields: (g.fields || []).filter(f => !existing.has(f.key)) }))
    .filter(g => g.fields.length)
    .sort((a, b) => (tabOrder.indexOf(placeOf(a).tab) - tabOrder.indexOf(placeOf(b).tab)) || (placeOf(a).order - placeOf(b).order));
  const seenTab = new Set();
  const legacyTabs = new Set(SETTINGS_GROUPS.map(g => g.tab));
  return `
    <div class="extra-search"><input class="input" type="search" id="extra-search-input" placeholder="${esc(T('جستجو در تنظیمات...'))}" autocomplete="off"></div>
    <div class="settings-accordion" id="extra-accordion">
      ${groups.map(g => {
        const tab = placeOf(g).tab;
        const firstInTab = !legacyTabs.has(tab) && !seenTab.has(tab);
        seenTab.add(tab);
        return `
        <div class="settings-group extra-group ${firstInTab ? 'open' : ''}" data-settings-tab="${tab}" style="${tab === settingsActiveTab ? '' : 'display:none'}" data-extra-group="${esc(g.id)}" data-extra-title="${esc(String(g.title || '').toLowerCase())}">
          <button type="button" class="settings-group-head">
            <span>${esc(T(g.title))}</span>
            <span class="settings-group-arrow">˅</span>
          </button>
          <div class="settings-group-body">
            <div class="form-grid">${g.fields.map(f => extraFieldHtml(f, values)).join('')}</div>
            ${g.id === 'post_tools' ? extraQrBackgroundHtml() : ''}
            <button type="button" class="btn btn-primary extra-save-btn" data-group="${esc(g.id)}" style="margin-top:12px">${esc(T('ذخیره'))}</button>
          </div>
        </div>`;
      }).join('')}
    </div>
    <div class="card-sub extra-empty" style="display:none">${esc(T('موردی پیدا نشد.'))}</div>`;
}

function filterExtraSettings(box, q) {
  q = (q || '').trim().toLowerCase();
  let anyGroup = false;
  $$('.extra-group', box).forEach(g => {
    if (g.dataset.settingsTab !== settingsActiveTab) return;
    const titleHit = !!q && (g.dataset.extraTitle || '').includes(q);
    let shown = 0;
    $$('.extra-field', g).forEach(fl => {
      const hit = !q || titleHit || (fl.dataset.extraSearch || '').includes(q);
      fl.style.display = hit ? '' : 'none';
      if (hit) shown++;
    });
    g.style.display = shown ? '' : 'none';
    if (shown) anyGroup = true;
    if (q && shown) g.classList.add('open');
  });
  const empty = $('.extra-empty', box);
  if (empty) empty.style.display = anyGroup ? 'none' : '';
}

async function saveExtraGroup(groupEl, btn) {
  const values = {};
  $$('[data-xkey]:not(.switch)', groupEl).forEach(el => { values[el.dataset.xkey] = el.value; });
  $$('.switch[data-xkey]', groupEl).forEach(sw => { values[sw.dataset.xkey] = sw.dataset.on === '1' ? '1' : '0'; });
  btn.disabled = true;
  try {
    const saved = await apiPost('/settings/extra', { values });
    // رمز تازه‌ذخیره‌شده دیگر در صفحه نمی‌ماند؛ به ماسک برمی‌گردد.
    $$('input[type=password][data-xkey]', groupEl).forEach(inp => { if (inp.value.trim()) inp.value = EXTRA_SECRET_MASK; });
    toast(settingsUiText('ذخیره شد.'));
    if (saved && saved.profile) {
      const errs = Object.values(saved.profile.errors || {}).join('؛ ');
      toast(saved.profile.ok ? settingsUiText('روی تلگرام اعمال شد.')
        : settingsUiText('ذخیره شد ولی اعمال روی تلگرام ناموفق بود: ') + errs);
    }
    const qbox = groupEl.closest('#extra-settings-root');
    if (qbox && qbox._refreshQrBg && groupEl.dataset.extraGroup === 'post_tools') qbox._refreshQrBg();
  } catch (e) {
    handleErr(e);
  } finally {
    btn.disabled = false;
  }
}

async function ensureExtraSettings(root) {
  const box = $('#extra-settings-root', root);
  if (!box || box.dataset.loaded === '1' || box.dataset.loading === '1') return;
  box.dataset.loading = '1';
  box.innerHTML = `<div class="card-sub">${esc(settingsUiText('در حال بارگذاری...'))}</div>`;
  try {
    const data = await apiGet('/settings/extra');
    box.innerHTML = extraSettingsHtml(data);
    box.dataset.loaded = '1';
    $$('.settings-group-head', box).forEach(h => h.addEventListener('click', () => h.parentElement.classList.toggle('open')));
    $$('.switch[data-xkey]', box).forEach(sw => sw.addEventListener('click', () => { sw.dataset.on = sw.dataset.on === '1' ? '0' : '1'; }));
    $$('.extra-save-btn', box).forEach(b => b.addEventListener('click', () => saveExtraGroup(b.closest('.extra-group'), b)));
    wireExtraQrBackground(box);
    const si = $('#extra-search-input', box);
    if (si) si.addEventListener('input', () => filterExtraSettings(box, si.value));
    if (typeof window.ShopVPNApplyI18n === 'function') { try { window.ShopVPNApplyI18n(); } catch (_) {} }
  } catch (e) {
    box.innerHTML = '';
    handleErr(e);
  } finally {
    box.dataset.loading = '0';
  }
}

function syncExtraSettingsTab(root) {
  const hasLegacy = SETTINGS_GROUPS.some(g => g.tab === settingsActiveTab);
  $$('.settings-save-bar', root).forEach(el => { el.style.display = hasLegacy ? '' : 'none'; });
  ensureExtraSettings(root);
  const box = $('#extra-settings-root', root);
  const si = box && $('#extra-search-input', box);
  const bar = box && $('.extra-search', box);
  if (bar) bar.style.display = $$('.extra-group', box).some(g => g.dataset.settingsTab === settingsActiveTab) ? '' : 'none';
  if (si) {
    $$('.extra-group', box).forEach(g => { g.style.display = g.dataset.settingsTab === settingsActiveTab ? '' : 'none'; $$('.extra-field', g).forEach(fl => { fl.style.display = ''; }); });
    si.value = '';
    const empty = $('.extra-empty', box); if (empty) empty.style.display = 'none';
  }
}

/* --------------------------------------------- تنظیمات: اپ موبایل مدیریت -- */
// توکن‌های دسترسی طولانی‌مدت (PAT) برای اپ اندروید مدیریت؛ خود اپ هم از
// داخل «تنظیمات» می‌تواند توکن جدید بسازد، این بخش فقط برای اولین اتصال
// و مدیریت/باطل‌کردن توکن‌ها از روی مرورگر است.
function mobileTokenRowsHtml(tokens) {
  return (tokens || []).map(t => `
    <div class="list-row" data-token-row="${t.id}">
      <div>
        <div>${esc(t.name)}${t.revoked_at ? ' <span class="badge badge-muted">باطل‌شده</span>' : ''}</div>
        <div class="mono" style="font-size:12px;color:var(--muted,#888)">${esc(t.token_prefix)} · ساخته‌شده ${fmtDate(t.created_at)}${t.last_used_at ? ' · آخرین استفاده ' + fmtDate(t.last_used_at) : ''}</div>
      </div>
      ${!t.revoked_at
        ? `<button class="btn btn-danger btn-sm" data-revoke-token="${t.id}">باطل کردن</button>`
        : `<button class="btn btn-danger btn-sm" data-delete-token="${t.id}">حذف</button>`}
    </div>`).join('') || `<div class="empty-state">هنوز توکنی نساخته‌ای.</div>`;
}

function mobileAppCardHtml(tokens) {
  return `
  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
      <h3 style="margin:0">اپ موبایل مدیریت</h3>
      <button type="button" class="btn btn-sm" id="admin-app-guide">📖 راهنمای کامل و دانلود</button>
    </div>
    <p style="color:var(--muted,#888);font-size:13px">
      از اینجا یک توکن دسترسی برای اپ اندروید ShopVPN Admin بساز. آدرس همین پنل و
      این توکن را داخل اپ وارد کن تا وصل شود. هر گوشی/دستگاه بهتر است توکن جدا داشته باشد.
      برای توضیح کامل، نصب، و رفع اخطار امنیتی نصب، روی «راهنمای کامل و دانلود» بزن.
    </p>
    <div class="form-inline" style="display:flex;gap:8px;margin:12px 0">
      <input type="text" id="new-mobile-token-name" placeholder="نام دستگاه (مثلاً گوشی من)" style="flex:1" />
      <button class="btn btn-primary" id="create-mobile-token-btn">ساخت توکن</button>
    </div>
    <div id="new-mobile-token-box"></div>
    <div class="list" id="mobile-token-list" style="margin-top:8px">${mobileTokenRowsHtml(tokens)}</div>
  </div>`;
}

function copyTokenText(text, btn) {
  const done = () => { toast('کپی شد.'); };
  const fallback = () => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
      document.execCommand('copy');
      done();
    } catch (e) {
      toast('کپی خودکار کار نکرد؛ متن را دستی انتخاب و کپی کن.');
    }
    document.body.removeChild(ta);
  };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(fallback);
  } else {
    fallback();
  }
}

async function reloadMobileTokenList(root) {
  const list = $('#mobile-token-list', root);
  if (!list) return;
  try {
    const tokens = await apiGet('/app/tokens');
    list.innerHTML = mobileTokenRowsHtml(tokens);
    bindMobileTokenListEvents(root);
  } catch (e) {
    handleErr(e);
  }
}

function bindMobileTokenListEvents(root) {
  $$('[data-revoke-token]', root).forEach(btn => btn.addEventListener('click', async () => {
    if (!confirm('این توکن باطل شود؟ دستگاهی که با آن وصل شده دیگر دسترسی نخواهد داشت.')) return;
    try {
      await apiDelete(`/app/tokens/${btn.dataset.revokeToken}`);
      toast('توکن باطل شد.');
      reloadMobileTokenList(root);
    } catch (e) {
      handleErr(e);
    }
  }));

  $$('[data-delete-token]', root).forEach(btn => btn.addEventListener('click', async () => {
    if (!confirm('این توکن برای همیشه حذف شود؟')) return;
    try {
      await apiDelete(`/app/tokens/${btn.dataset.deleteToken}`);
      toast('توکن حذف شد.');
      reloadMobileTokenList(root);
    } catch (e) {
      handleErr(e);
    }
  }));
}

function bindMobileAppEvents(root, refresh) {
  $('#admin-app-guide', root)?.addEventListener('click', () => openModal('📖 راهنمای کامل اپ مدیریت', _adminAppGuideHtml(), null, { wide: true }));
  const createBtn = $('#create-mobile-token-btn', root);
  if (createBtn) createBtn.addEventListener('click', async () => {
    const nameInput = $('#new-mobile-token-name', root);
    const name = (nameInput?.value || 'دستگاه من').trim();
    createBtn.disabled = true;
    try {
      const res = await apiPost('/app/tokens', { name });
      const box = $('#new-mobile-token-box', root);
      if (box) {
        box.innerHTML = `
          <div class="card" style="background:var(--surface-2,#1a1a1a);margin-bottom:10px">
            <p style="font-size:13px">این توکن فقط همین یک‌بار نمایش داده می‌شود — همین الان کپی کن. با ساخت یا بستن توکن بعدی، این جعبه پاک می‌شود.</p>
            <div style="display:flex;gap:8px;align-items:center">
              <code class="mono" id="new-mobile-token-code" style="flex:1;word-break:break-all;user-select:all;cursor:text">${esc(res.token)}</code>
              <button class="btn btn-ghost btn-sm" id="new-mobile-token-copy-btn">کپی</button>
            </div>
            <p class="mono" style="font-size:12px;margin-top:6px">آدرس سرور: ${esc(res.server_url || location.origin)}</p>
            <button class="btn btn-ghost btn-sm" id="new-mobile-token-dismiss-btn" style="margin-top:6px">بستن</button>
          </div>`;
        $('#new-mobile-token-copy-btn', box).addEventListener('click', (ev) => copyTokenText(res.token, ev.currentTarget));
        $('#new-mobile-token-dismiss-btn', box).addEventListener('click', () => { box.innerHTML = ''; });
      }
      if (nameInput) nameInput.value = '';
      toast('توکن ساخته شد.');
      reloadMobileTokenList(root);
    } catch (e) {
      handleErr(e);
    } finally {
      createBtn.disabled = false;
    }
  });

  bindMobileTokenListEvents(root);
}


// از کل محتوای google-services.json دقیقاً همان ۴ مقداری را که پنل نیاز
// دارد بیرون می‌کشد. چون این مقادیر عیناً از فایل خوانده می‌شوند (نه با
// کپی دستی هر بخش)، دیگر امکان جابه‌جا پیست‌کردن ترتیب Firebase App ID
// (باگی که یک‌بار باعث قطع کامل نوتیف شد) وجود ندارد.
function extractGoogleServicesJson(text) {
  const data = JSON.parse(text);
  const projectNumber = data?.project_info?.project_number;
  const projectId = data?.project_info?.project_id;
  const client = (data?.client || [])[0];
  const appId = client?.client_info?.mobilesdk_app_id;
  const apiKey = (client?.api_key || [])[0]?.current_key;
  if (!projectNumber || !projectId || !appId || !apiKey) {
    throw new Error('missing fields');
  }
  return {
    firebase_sender_id: String(projectNumber),
    firebase_project_id: String(projectId),
    firebase_app_id: String(appId),
    firebase_api_key: String(apiKey),
  };
}

function _subTemplateGuideHtml() {
  const row = (k, d) => `<tr><td dir="ltr"><code>${esc(k)}</code></td><td>${esc(d)}</td></tr>`;
  return `<div class="card-sub" style="line-height:2">
    <p>قالب یک فایل HTML کامل است. سرور این چهار نشانه را جایگزین می‌کند:</p>
    <table class="tbl"><tbody>
      ${row('__DATA__', 'آبجکت JSON اطلاعات اشتراک؛ داخل script مثل const D=__DATA__; بگذار (فقط یک‌بار)')}
      ${row('__TITLE__', 'عنوان صفحه (برای تگ title)')}
      ${row('__THEME__', 'auto / light / dark')}
      ${row('__NONCE__', 'اختیاری؛ به تگ‌های script بدون nonce خودکار اضافه می‌شود')}
    </tbody></table>
    <p style="margin-top:12px">فیلدهای داخل <code dir="ltr">D</code>:</p>
    <table class="tbl"><tbody>
      ${row('user, brand, logo', 'نام سرویس، نام برند، آدرس لوگو (https)')}
      ${row('state', 'active / limited / expired / disabled ...')}
      ${row('used, total', 'مصرف و حجم کل به گیگابایت (total=null یعنی نامحدود)')}
      ${row('expire, daysLeft, planDays, created, now', 'زمان‌ها (ثانیه‌ی یونیکس) و روز باقی‌مانده')}
      ${row('notice, support, footer, theme', 'اعلان، لینک پشتیبانی، متن پایین، تم')}
      ${row('sub', 'لینک ساب کاربر')}
      ${row('show.{configs,chart,qr,apps,faq}', 'کلیدهای نمایش بخش‌ها از تنظیمات')}
      ${row('configs[] = {n,f,p,u}', 'نام، پرچم، پروتکل و لینک هر کانفیگ')}
      ${row('apps[]', 'برنامه‌ها به تفکیک سیستم‌عامل')}
      ${row('faq[]', 'جفت‌های [سوال، جواب]')}
      ${row('series', 'نمودار مصرف {labels, values}')}
      ${row('live', 'آیا اطلاعات زنده از پنل گرفته شد')}
    </tbody></table>
    <p style="margin-top:12px">محدودیت‌های امنیتی (CSP): فقط اسکریپت inline مجاز است؛ اسکریپت/CDN خارجی و درخواست شبکه (fetch) مسدود است. فونت از Google Fonts و تصویر از https یا data: مجاز است. QR کل لینک: <code dir="ltr">/s/&lt;token&gt;/qr.png</code> و QR کانفیگ شماره‌ی N: <code dir="ltr">?i=N</code>.</p>
    <p>ساده‌ترین راه: «پر کردن با قالب پیش‌فرض» را بزن، ظاهرش را ویرایش کن، ذخیره کن و پیش‌نمایش زنده را ببین. می‌توانی فایل آماده را هم با «آپلود فایل .html» بگذاری؛ فایل باید تک‌فایل باشد (CSS/JS/عکس داخل خودش؛ عکس‌ها به‌صورت data:).</p>
  </div>`;
}

function bindSettingsGroupEvents(root) {
  $$('.sub-tpl-guide-btn', root).forEach((btn) => {
    btn.addEventListener('click', () => openModal('📖 راهنمای قالب اختصاصی صفحه ساب', _subTemplateGuideHtml(), null, { wide: true }));
  });
  $$('.sub-tpl-upload-btn', root).forEach((btn) => {
    const input = btn.parentElement.querySelector('.sub-tpl-upload-input');
    if (!input) return;
    btn.addEventListener('click', () => input.click());
    input.addEventListener('change', async () => {
      const file = input.files && input.files[0];
      input.value = '';
      if (!file) return;
      const ta = $('textarea[data-key="dsub_custom_template"]', root);
      if (!ta) return;
      if (file.size > 400000) { toast('حجم فایل بیش از ۴۰۰ کیلوبایت است.'); return; }
      try {
        const text = await file.text();
        if (!text.includes('__DATA__')) { toast('این فایل شامل __DATA__ نیست؛ قالب معتبر نیست (راهنمای متغیرها را ببین).'); return; }
        if (ta.value.trim() && !confirm('متن فعلی قالب با محتوای فایل جایگزین شود؟')) return;
        ta.value = text;
        ta.dispatchEvent(new Event('input', { bubbles: true }));
        toast('فایل در کادر قرار گرفت؛ برای ثبت «ذخیره تغییرات» را بزن.');
      } catch (e) {
        handleErr(e);
      }
    });
  });
  $$('.sub-tpl-default-btn', root).forEach((btn) => {
    btn.addEventListener('click', async () => {
      const ta = $('textarea[data-key="dsub_custom_template"]', root);
      if (!ta) return;
      if (ta.value.trim() && !confirm('متن فعلی قالب با قالب پیش‌فرض جایگزین شود؟')) return;
      btn.disabled = true;
      try {
        const res = await fetch('/api/settings/sub-page-template/default', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        ta.value = await res.text();
        toast('قالب پیش‌فرض در کادر قرار گرفت؛ ویرایش کن و «ذخیره تغییرات» را بزن.');
      } catch (e) {
        handleErr(e);
      } finally {
        btn.disabled = false;
      }
    });
  });
  $$('.push-guide-btn', root).forEach((btn) => {
    btn.addEventListener('click', () => openModal('📖 راهنمای کامل فعال‌سازی پوش نوتیف', _pushNotifGuideHtml(), null, { wide: true }));
  });
  $$('.push-test-btn', root).forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      const prevTxt = btn.textContent;
      btn.textContent = 'در حال ارسال...';
      try {
        await apiPost('/app/push-test');
        toast('پوش تست با موفقیت به گوگل تحویل داده شد. اگه تا چند ثانیه روی گوشی چیزی نیومد، مشکل دیگه سمت سرور نیست - مجوز نوتیف یا بهینه‌سازی باتری رو روی گوشی چک کن.');
      } catch (e) {
        handleErr(e);
      } finally {
        btn.disabled = false;
        btn.textContent = prevTxt;
      }
    });
  });
  $$('.firebase-json-extract', root).forEach((box) => {
    const textarea = $('textarea', box);
    const btn = $('.firebase-json-extract-btn', box);
    btn.addEventListener('click', () => {
      let values;
      try {
        values = extractGoogleServicesJson(textarea.value);
      } catch (e) {
        toast('این متن، فایل معتبر google-services.json به‌نظر نمی‌رسه. مطمئن شو کل فایل رو (بدون تغییر) پیست کردی.');
        return;
      }
      Object.entries(values).forEach(([key, value]) => {
        const input = $(`[data-key="${key}"]`, root);
        if (input) input.value = value;
      });
      textarea.value = '';
      toast('۴ فیلد پایین با موفقیت پر شدند؛ حالا روی «ذخیره تغییرات» بزن.');
    });
  });
  $$('.settings-group-head', root).forEach(btn => btn.addEventListener('click', () => {
    btn.parentElement.classList.toggle('open');
  }));
  $$('.switch[data-key]', root).forEach(sw => sw.addEventListener('click', () => {
    const on = sw.dataset.on !== '1';
    sw.dataset.on = on ? '1' : '0';
  }));
  $$('.color-pick', root).forEach(box => {
    $$('.color-swatch', box).forEach(btn => btn.addEventListener('click', () => {
      box.dataset.color = btn.dataset.value;
      $$('.color-swatch', box).forEach(b => b.classList.toggle('active', b === btn));
    }));
  });
  $$('.image-field', root).forEach(box => {
    const fileInput = $('.image-field-input', box);
    const hidden = $('input[type=hidden]', box);
    $('.image-field-pick', box).addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      const file = fileInput.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => { hidden.value = reader.result; toast('تصویر انتخاب شد؛ برای ثبت روی «ذخیره تغییرات» بزن.'); };
      reader.readAsDataURL(file);
    });
    const clearBtn = $('.image-field-clear', box);
    if (clearBtn) clearBtn.addEventListener('click', () => { hidden.value = ''; box.querySelector('.image-field-preview')?.remove(); toast('تصویر حذف شد؛ برای ثبت روی «ذخیره تغییرات» بزن.'); });
  });
}

async function collectAndSaveSettings(root, btn) {
  const items = [];
  $$('[data-key][data-type]:not(.switch)', root).forEach(el => items.push({ key: el.dataset.key, value: el.value }));
  $$('.switch[data-key]', root).forEach(sw => items.push({ key: sw.dataset.key, value: sw.dataset.on === '1' ? '1' : '0' }));
  $$('.color-pick[data-key]', root).forEach(box => items.push({ key: box.dataset.key, value: box.dataset.color || '' }));

  // اعتبارسنجی فرمت Firebase App ID: باید دقیقاً «شماره‌پروژه:شماره‌اپ:android:هش»
  // باشد (عیناً همان‌طور که داخل google-services.json آمده). اگر ترتیبش
  // جابه‌جا پیست شود، اپ اندروید هیچ‌وقت نمی‌تواند توکن FCM بگیرد و هیچ
  // نوتیفی نمی‌رسد - بدون هیچ خطای قابل‌مشاهده‌ای در پنل یا اپ. این چک همان
  // لحظه‌ی ذخیره جلوی این اشتباه رو می‌گیره.
  const appIdItem = items.find((i) => i.key === 'firebase_app_id');
  if (appIdItem && appIdItem.value.trim() && !/^\d+:\d+:android:[0-9a-fA-F]+$/.test(appIdItem.value.trim())) {
    toast('Firebase App ID نامعتبره. فرمت درست باید مثل 1:691452629264:android:b0b15107cc5a72ea8dd595 باشه - دقیقاً از google-services.json کپی کن.');
    return;
  }

  for (const it of items) {
    if (it.key === 'dsub_accent_color' || it.key === 'dsub_secondary_color') {
      const h = normalizeHex(it.value);
      if (!h) { toast('رنگ نامعتبر است؛ کد HEX باید شش رقمی مثل #6366F1 باشد.'); return; }
      it.value = h;
    }
  }

  btn.disabled = true;
  const prevTxt = btn.textContent; btn.textContent = 'در حال ذخیره...';
  try {
    for (const item of items) {
      await apiPost('/settings', item);
    }
    toast('تنظیمات ذخیره شد.');
    const prevFrame = $('#sub-page-preview-frame', root);
    if (prevFrame) { try { prevFrame.contentWindow.location.reload(); } catch (e) { prevFrame.src = prevFrame.src; } }
  } catch (e) {
    handleErr(e);
  } finally {
    btn.disabled = false; btn.textContent = prevTxt;
  }
}

/* ------------------------------------------------------- menu order card - */
// نکته: ویرایشگر ترتیب/فعال‌سازی/متن/رنگ دکمه‌های منوی اصلی از اینجا به تب
// «دکمه‌های ربات» منتقل شد (پایین‌تر: buildMainMenuGroup). این بخش فقط نوع
// نمایش منو (Reply/Inline) و تعداد ستون را نگه می‌دارد که مکمل آن است.

function mainMenuDisplayCardHtml(mm) {
  return `
    <div class="card" style="margin-bottom:18px">
      <div class="card-head">
        <h3>نمایش منوی اصلی</h3>
        <button class="btn btn-primary btn-sm" id="mm-display-save">ذخیره</button>
      </div>
      <span class="card-sub">نوع نمایش منو (پایین/شیشه‌ای) و چیدمان دکمه‌ها - جدا از ترتیب آیتم‌های منو در پایین. حداقل یکی از دو منو باید فعال بماند.</span>
      <div class="form-grid" style="margin-top:12px">
        <label class="field"><span>منوی پایین (Reply Keyboard)</span>
          <select class="input" id="mm-reply">
            <option value="1" ${mm.reply_enabled ? 'selected' : ''}>فعال</option>
            <option value="0" ${!mm.reply_enabled ? 'selected' : ''}>غیرفعال</option>
          </select>
        </label>
        <label class="field"><span>منوی شیشه‌ای بالا (Inline)</span>
          <select class="input" id="mm-inline">
            <option value="1" ${mm.inline_enabled ? 'selected' : ''}>فعال</option>
            <option value="0" ${!mm.inline_enabled ? 'selected' : ''}>غیرفعال</option>
          </select>
        </label>
        <label class="field"><span>چیدمان دکمه‌ها</span>
          <select class="input" id="mm-columns">
            <option value="1" ${mm.columns === 1 ? 'selected' : ''}>۱ دکمه در هر ردیف</option>
            <option value="2" ${mm.columns === 2 ? 'selected' : ''}>۲ دکمه در هر ردیف</option>
          </select>
        </label>
      </div>
    </div>`;
}

async function saveMainMenuDisplay() {
  const root = content();
  const btn = $('#mm-display-save', root);
  const reply_enabled = $('#mm-reply', root).value === '1';
  const inline_enabled = $('#mm-inline', root).value === '1';
  if (!reply_enabled && !inline_enabled) { toast('حداقل یکی از منوی پایین یا شیشه‌ای باید فعال باشد.'); return; }
  const columns = Number($('#mm-columns', root).value) || 1;
  btn.disabled = true;
  const prevTxt = btn.textContent; btn.textContent = 'در حال ذخیره...';
  try {
    await apiPost('/settings/main-menu-display', { reply_enabled, inline_enabled, columns });
    toast('ذخیره شد.');
  } catch (e) {
    handleErr(e);
  } finally {
    btn.disabled = false; btn.textContent = prevTxt;
  }
}

/* ================================================== bot buttons studio === */
// استودیوی گرافیکی «دکمه‌های ربات»: یک گوشی تلگرام‌مانند که دقیقاً همان کیبوردی را
// نشان می‌دهد که کاربر/ادمین در ربات می‌بیند. دکمه‌ها با نگه‌داشتن و کشیدن (موس و
// لمس) بین ردیف‌ها جابه‌جا و کنار هم/زیر هم چیده می‌شوند؛ دکمه‌های پنل مدیریت را
// می‌شود روی یکی از دسته‌ها رها کرد تا به آن دسته منتقل شوند.
const BS_MAX_ROW = 4;
const BS = {
  groups: {}, order: [], cur: 'main_menu', sel: null,
  dirty: new Set(), edited: new Set(),
  mm: { reply: true, inline: false, columns: 1, mode: 'reply', dirty: false },
  styleOptions: [], adminCats: [], drag: null, suppressClick: false,
};
const BS_SHORT = {
  main_menu: '🏠 منوی اصلی', account_hub: '🧾 حساب کاربری من', payment_methods: '💳 روش‌های پرداخت',
  svc_detail: '📦 صفحه‌ی سرویس', wallet_menu: '👛 کیف پول', contact_menu: '📞 ارتباط با پشتیبانی',
  buyflow: '🛒 مسیر خرید: متن/رنگ', buyflow_confirm: '🛒 مسیر خرید: ترتیب', admin_categories: '🔧 دسته‌های پنل مدیریت',
};
const BS_STYLE_LABEL = { '': 'پیش‌فرض', primary: 'آبی', success: 'سبز', danger: 'قرمز' };

function bsLabel(g) { return BS_SHORT[g.key] || g.category_label || g.label; }
function bsIsAdminItems(g) { return g.key.startsWith('admin_items__'); }
function bsFlatOrder(g) { return g.rows.flat(); }
function bsBreaks(g) { return g.rows.slice(1).map(r => r[0]); }
function bsItem(g, key) { return g.items.find(i => i.key === key); }
function bsId(g, key) { return g.key + '::' + key; }

function bsFixed(g) {
  if (g.key === 'main_menu') return { bubble: '🏠 به ربات خوش آمدید', top: [], bottom: [] };
  if (g.key === 'admin_categories') return { bubble: '🔧 پنل مدیریت:', top: [], bottom: [['⬅️ بازگشت']] };
  if (bsIsAdminItems(g)) return { bubble: `${g.category_label}:`, top: [], bottom: [['⬅️ بازگشت به پنل مدیریت']] };
  if (g.key === 'account_hub') return { bubble: '🧾 حساب کاربری من', top: [], bottom: [['🌐 زبان / Language'], ['⬅️ بازگشت به منوی اصلی']] };
  if (g.key === 'svc_detail') return { bubble: '📦 جزئیات سرویس', top: [], bottom: [['⬅️ بازگشت به لیست']] };
  if (g.key === 'wallet_menu') return { bubble: '👛 کیف پول', top: [], bottom: [] };
  if (g.key === 'contact_menu') return { bubble: '📞 ارتباط با پشتیبانی', top: [], bottom: [['❌ انصراف']] };
  if (g.key === 'payment_methods') return { bubble: '💳 روش پرداخت را انتخاب کنید:', top: [], bottom: [['❌ انصراف']] };
  if (g.key === 'buyflow_confirm') return { bubble: '🛒 تأیید خرید', top: [['➖', '🔢 تعداد: 1', '➕']], bottom: [['⬅️ بازگشت']] };
  return { bubble: '🛒 مسیر خرید', top: [], bottom: [] };
}

function bsMainGroup(items) {
  const g = {
    key: 'main_menu', label: 'منوی اصلی ربات', reorderable: true, supports_row_break: true, items,
    note: 'ترتیب، چیدمان ردیف‌ها، فعال/غیرفعال بودن، متن و رنگ دکمه‌های منوی اصلی.',
  };
  const custom = items.some(i => i.break_before !== null && i.break_before !== undefined);
  const rows = [];
  items.forEach((it, idx) => {
    if (!rows.length) { rows.push([it.key]); return; }
    const newRow = custom ? it.break_before !== false : (rows[rows.length - 1].length >= BS.mm.columns);
    if (newRow) rows.push([it.key]); else rows[rows.length - 1].push(it.key);
  });
  g.rows = rows;
  return g;
}

function bsNormalize(g) {
  const keys = g.items.map(i => i.key);
  if (!g.rows) g.rows = keys.map(k => [k]);
  g.rows = g.rows.map(r => r.filter(k => keys.includes(k))).filter(r => r.length);
  keys.forEach(k => { if (!g.rows.some(r => r.includes(k))) g.rows.push([k]); });
  g.rowsEditable = !!g.supports_row_break && g.reorderable;
  g.items.forEach(it => { if (it.enabled === undefined && it.togglable) it.enabled = true; });
}

async function bsLoad() {
  const [registry, menu, mm] = await Promise.all([apiGet('/buttons'), apiGet('/settings/menu-order'), apiGet('/settings/main-menu-display')]);
  BS.styleOptions = registry.style_options || [];
  BS.adminCats = registry.admin_categories || [];
  BS.mm = { reply: !!mm.reply_enabled, inline: !!mm.inline_enabled, columns: mm.columns || 1, mode: mm.reply_enabled || !mm.inline_enabled ? 'reply' : 'inline', dirty: false };
  const list = [bsMainGroup(menu), ...registry.groups];
  BS.groups = {}; BS.order = [];
  list.forEach(g => { bsNormalize(g); BS.groups[g.key] = g; BS.order.push(g.key); });
  BS.dirty.clear(); BS.edited.clear();
  if (!BS.groups[BS.cur]) BS.cur = 'main_menu';
  BS.sel = null;
}

function bsChangeCount() {
  const editedGroups = new Set([...BS.edited].map(x => x.split('::')[0]));
  const groups = new Set([...BS.dirty, ...editedGroups]);
  return groups.size + (BS.mm.dirty ? 1 : 0);
}

/* ---------------------------------------------------------------- render -- */
function bsTopHtml() {
  const n = bsChangeCount();
  return `
    <div class="bs-top">
      <div>
        <h3>استودیوی چیدمان دکمه‌های ربات</h3>
        <span class="card-sub">دکمه رو لمس کن تا ویرایشش کنی؛ نگه دار و بکش تا جابه‌جا شه.</span>
      </div>
      <div class="bs-top-actions">
        <span class="chip bs-unsaved" ${n ? '' : 'hidden'}>${n} صفحه تغییر ذخیره‌نشده</span>
        <button class="btn btn-ghost btn-sm" id="bs-reload" ${n ? '' : 'disabled'}>بازگردانی</button>
        <button class="btn btn-primary btn-sm" id="bs-save" ${n ? '' : 'disabled'}>ذخیره همه</button>
      </div>
    </div>`;
}

function bsScreensHtml() {
  const sectionBtn = (k) => {
    const g = BS.groups[k]; if (!g) return '';
    const dirty = BS.dirty.has(k) || [...BS.edited].some(x => x.startsWith(k + '::'));
    return `<button type="button" class="bs-screen${k === BS.cur ? ' active' : ''}" data-bs-screen="${esc(k)}">
      <span>${esc(bsLabel(g))}</span><small>${g.items.length}</small>${dirty ? '<i class="bs-dot"></i>' : ''}</button>`;
  };
  const user = ['main_menu', 'account_hub', 'svc_detail', 'wallet_menu', 'contact_menu', 'payment_methods', 'buyflow', 'buyflow_confirm'];
  const adm = ['admin_categories', ...BS.order.filter(k => k.startsWith('admin_items__'))];
  return `
    <div class="bs-screens-title">منوی کاربران</div>
    <div class="bs-screens-list">${user.map(sectionBtn).join('')}</div>
    <div class="bs-screens-title">پنل مدیریت (ادمین)</div>
    <div class="bs-screens-list">${adm.map(sectionBtn).join('')}</div>`;
}

function bsBtnHtml(g, it) {
  const text = it.has_text ? (it.text || it.label) : it.label;
  const off = it.togglable && it.enabled === false;
  return `<button type="button" class="tg-btn st-${esc(it.style || '')}${BS.sel === it.key ? ' sel' : ''}${off ? ' off' : ''}${g.reorderable ? ' can-drag' : ''}" data-key="${esc(it.key)}">
    <span dir="auto">${esc(text)}</span>${off ? '<i class="tg-badge">خاموش</i>' : ''}${it.admin_only ? '<i class="tg-badge adm">ادمین</i>' : ''}</button>`;
}

function bsFixedRowHtml(r) {
  return `<div class="tg-row tg-fixed">${r.map(t => `<span class="tg-btn tg-static"><span dir="auto">${esc(t)}</span></span>`).join('')}</div>`;
}

function bsPhoneHtml(g) {
  const fx = bsFixed(g);
  const isMain = g.key === 'main_menu';
  const mode = isMain ? (BS.mm.mode === 'inline' ? 'inline' : 'reply') : 'inline';
  const rowsHtml = g.rows.map((row, i) =>
    `<div class="tg-row" data-row="${i}">${row.map(k => bsBtnHtml(g, bsItem(g, k))).join('')}</div><div class="tg-gap" data-gap="${i + 1}"></div>`
  ).join('');
  const kb = `
    <div class="tg-kb tg-kb-${mode}" id="tg-kb">
      ${(fx.top || []).map(bsFixedRowHtml).join('')}
      <div class="tg-gap${g.rows.length ? '' : ' big'}" data-gap="0"></div>
      ${g.rows.length ? rowsHtml : '<div class="tg-empty">دکمه‌ای اینجا نیست؛ یکی رو بکش و رها کن</div>'}
      ${(fx.bottom || []).map(bsFixedRowHtml).join('')}
    </div>`;
  const bubble = `<div class="tg-bubble" dir="auto">${esc(fx.bubble)}</div>`;
  return `
    <div class="tg-phone">
      <div class="tg-head"><span class="tg-avatar">🤖</span><div><b>ربات شما</b><small>bot</small></div></div>
      <div class="tg-chat">
        ${bubble}
        ${mode === 'inline' ? kb : ''}
      </div>
      ${mode === 'reply' ? `<div class="tg-reply-wrap">${kb}</div>` : '<div class="tg-input">پیام بنویس…</div>'}
    </div>`;
}

function bsModeBarHtml(g) {
  if (g.key === 'main_menu') {
    return `
      <div class="bs-modebar">
        <div class="bs-seg">
          <button type="button" data-bs-mode="reply" class="${BS.mm.mode === 'reply' ? 'active' : ''}">کیبورد پایین</button>
          <button type="button" data-bs-mode="inline" class="${BS.mm.mode === 'inline' ? 'active' : ''}">شیشه‌ای زیر پیام</button>
        </div>
        <label class="bs-switch-row"><span class="switch" data-bs-mm="reply" data-on="${BS.mm.reply ? '1' : '0'}"><i></i></span><span>منوی پایین فعال</span></label>
        <label class="bs-switch-row"><span class="switch" data-bs-mm="inline" data-on="${BS.mm.inline ? '1' : '0'}"><i></i></span><span>منوی شیشه‌ای فعال</span></label>
      </div>`;
  }
  if (bsIsAdminItems(g)) {
    const chips = BS.adminCats.filter(c => c.key !== g.category).map(c =>
      `<button type="button" class="bs-cat" data-drop-cat="${esc(c.key)}"><span dir="auto">${esc(c.label)}</span></button>`).join('');
    return `
      <div class="bs-catdrop">
        <div class="bs-catdrop-title">برای انتقال به دسته‌ی دیگر، دکمه رو بکش روی یکی از این‌ها:</div>
        <div class="bs-catdrop-list">${chips}</div>
      </div>`;
  }
  if (g.note) return `<div class="bs-note card-sub">${esc(g.note)}</div>`;
  return '';
}

function bsInspectorHtml(g) {
  const it = BS.sel && bsItem(g, BS.sel);
  if (!it) {
    return `
      <div class="bs-insp-empty">
        <div class="bs-insp-ico">👆</div>
        <b>یک دکمه رو انتخاب کن</b>
        <p class="card-sub">لمس کن تا متن، رنگ و وضعیتش رو ویرایش کنی. برای جابه‌جایی، دکمه رو نگه دار و بکش:</p>
        <ul class="bs-legend">
          <li><i class="lg lg-v"></i> وسط یک ردیف رها کنی ← کنار بقیه‌ی دکمه‌ها می‌شینه</li>
          <li><i class="lg lg-h"></i> بین دو ردیف رها کنی ← ردیف جدید می‌سازه</li>
          ${bsIsAdminItems(g) ? '<li><i class="lg lg-c"></i> روی یک دسته رها کنی ← به آن دسته منتقل می‌شه</li>' : ''}
        </ul>
        ${g.reorderable ? '' : '<p class="card-sub">جای دکمه‌های این صفحه ثابته؛ فقط متن و رنگشون قابل تغییره.</p>'}
      </div>`;
  }
  const ri = g.rows.findIndex(r => r.includes(it.key));
  const row = g.rows[ri];
  const ci = row.indexOf(it.key);
  const swatches = it.has_style ? `
    <div class="bs-field"><span>رنگ دکمه</span>
      <div class="bs-swatches">${BS.styleOptions.map(o => `<button type="button" class="bs-sw st-${esc(o.value)}${(it.style || '') === o.value ? ' on' : ''}" data-bs-style="${esc(o.value)}" title="${esc(BS_STYLE_LABEL[o.value] || o.label)}"></button>`).join('')}</div>
    </div>` : '';
  const text = it.has_text ? `
    <label class="bs-field"><span>متن دکمه</span>
      <input class="input" id="bs-text" type="text" value="${esc(it.text || '')}" placeholder="متن دکمه"></label>` : '';
  const toggle = it.togglable ? `
    <div class="bs-field bs-inline"><span>نمایش در ربات</span>
      <span class="switch" data-bs-act="toggle" data-on="${it.enabled ? '1' : '0'}"><i></i></span></div>` : '';
  const arrows = g.reorderable ? `
    <div class="bs-field"><span>جای دکمه</span>
      <div class="bs-arrows">
        <button type="button" class="btn btn-sm" data-bs-act="up" title="بالاتر">⬆</button>
        <button type="button" class="btn btn-sm" data-bs-act="down" title="پایین‌تر">⬇</button>
        ${g.rowsEditable ? `
        <button type="button" class="btn btn-sm" data-bs-act="left" ${ci === 0 ? 'disabled' : ''} title="چپ">⬅</button>
        <button type="button" class="btn btn-sm" data-bs-act="right" ${ci === row.length - 1 ? 'disabled' : ''} title="راست">➡</button>
        <button type="button" class="btn btn-sm" data-bs-act="join" ${ri === 0 || g.rows[ri - 1].length >= BS_MAX_ROW ? 'disabled' : ''}>↩ بچسبان به ردیف بالا</button>` : ''}
      </div>
    </div>` : '';
  const catSel = bsIsAdminItems(g) ? `
    <label class="bs-field"><span>انتقال به دسته</span>
      <select class="input" id="bs-cat"><option value="">— انتخاب کن —</option>
        ${BS.adminCats.filter(c => c.key !== g.category).map(c => `<option value="${esc(c.key)}">${esc(c.label)}</option>`).join('')}
      </select></label>` : '';
  return `
    <div class="bs-insp-head"><b dir="auto">${esc(it.label)}</b><code>${esc(it.key)}</code>
      <button type="button" class="btn btn-ghost btn-sm bs-close" data-bs-act="close" title="بستن">✕</button></div>
    ${text}${swatches}${toggle}${arrows}${catSel}
    ${!it.has_text && !it.has_style && !it.togglable ? '<p class="card-sub">این دکمه متن/رنگ قابل ویرایش ندارد.</p>' : ''}
    <button type="button" class="btn btn-primary bs-insp-save" data-bs-act="save" ${bsChangeCount() ? '' : 'disabled'}>ذخیره تغییرات</button>`;
}

function bsRenderPhone() {
  const g = BS.groups[BS.cur];
  $('#bs-stage-body').innerHTML = bsModeBarHtml(g) + bsPhoneHtml(g);
}
function bsRenderInspector() {
  const el = $('#bs-inspector');
  el.innerHTML = bsInspectorHtml(BS.groups[BS.cur]);
  el.classList.toggle('sheet', !!BS.sel);
  $('#bs-root').classList.toggle('has-sel', !!BS.sel);
}
function bsRenderTop() {
  $('#bs-top').innerHTML = bsTopHtml();
  const n = bsChangeCount();
  $('#bs-bottom').innerHTML = n
    ? `<div class="card bs-savecard"><span>${n} صفحه تغییر ذخیره‌نشده</span><button class="btn btn-primary btn-sm" id="bs-save2">ذخیره همه</button></div>`
    : '';
}
function bsRenderScreens() { $('#bs-screens').innerHTML = bsScreensHtml(); }
function bsRefresh() { bsRenderTop(); bsRenderScreens(); bsRenderPhone(); bsRenderInspector(); }

/* ------------------------------------------------------------- mutations -- */
function bsMarkDirty(gk) { BS.dirty.add(gk); }
function bsMarkEdited(g, key) { BS.edited.add(bsId(g, key)); }

function bsMoveToCat(key, cat) {
  const from = BS.groups[BS.cur];
  const to = BS.groups['admin_items__' + cat];
  if (!to || to === from) return;
  const idx = from.items.findIndex(i => i.key === key);
  if (idx < 0) return;
  const [it] = from.items.splice(idx, 1);
  from.rows = from.rows.map(r => r.filter(k => k !== key)).filter(r => r.length);
  to.items.push(it);
  to.rows.push([key]);
  const oldId = bsId(from, key);
  if (BS.edited.has(oldId)) { BS.edited.delete(oldId); BS.edited.add(bsId(to, key)); }
  bsMarkDirty(from.key); bsMarkDirty(to.key);
  BS.sel = null;
  toast(`«${it.text || it.label}» به «${to.category_label}» منتقل شد؛ آخر لیستش قرار گرفت.`);
}

function bsApplyDrop(key, t) {
  const g = BS.groups[BS.cur];
  if (!t) return;
  if (t.type === 'cat') { bsMoveToCat(key, t.cat); bsRefresh(); return; }
  if (t.type === 'row' && g.rows[t.row].filter(k => k !== key).length >= BS_MAX_ROW) {
    toast(`هر ردیف حداکثر ${BS_MAX_ROW} دکمه می‌تونه داشته باشه.`); return;
  }
  const before = JSON.stringify(g.rows);
  const rows = g.rows.map(r => r.slice());
  const oldRow = rows.find(r => r.includes(key));
  if (t.type === 'newrow') {
    rows.splice(t.index, 0, [key]);
    oldRow.splice(oldRow.indexOf(key), 1);
  } else {
    oldRow.splice(oldRow.indexOf(key), 1);
    rows[t.row].splice(t.index, 0, key);
  }
  g.rows = rows.filter(r => r.length);
  if (JSON.stringify(g.rows) !== before) bsMarkDirty(g.key);
  bsRefresh();
}

function bsAction(act) {
  if (act === 'close') { BS.sel = null; bsRefresh(); return; }
  const g = BS.groups[BS.cur];
  const key = BS.sel; if (!key) return;
  const it = bsItem(g, key);
  const ri = g.rows.findIndex(r => r.includes(key));
  const row = g.rows[ri];
  const ci = row.indexOf(key);
  const before = JSON.stringify(g.rows);
  if (act === 'toggle') {
    it.enabled = !it.enabled; bsMarkEdited(g, key);
  } else if (act === 'left' && ci > 0) {
    [row[ci - 1], row[ci]] = [row[ci], row[ci - 1]];
  } else if (act === 'right' && ci < row.length - 1) {
    [row[ci + 1], row[ci]] = [row[ci], row[ci + 1]];
  } else if (act === 'up') {
    if (row.length > 1 && g.rowsEditable) { row.splice(ci, 1); g.rows.splice(ri, 0, [key]); }
    else if (ri > 0) { [g.rows[ri - 1], g.rows[ri]] = [g.rows[ri], g.rows[ri - 1]]; }
  } else if (act === 'down') {
    if (row.length > 1 && g.rowsEditable) { row.splice(ci, 1); g.rows.splice(ri + 1, 0, [key]); }
    else if (ri < g.rows.length - 1) { [g.rows[ri + 1], g.rows[ri]] = [g.rows[ri], g.rows[ri + 1]]; }
  } else if (act === 'join' && ri > 0 && g.rows[ri - 1].length < BS_MAX_ROW) {
    row.splice(ci, 1);
    g.rows[ri - 1].push(key);
    g.rows = g.rows.filter(r => r.length);
  }
  if (JSON.stringify(g.rows) !== before) bsMarkDirty(g.key);
  bsRefresh();
}

/* ------------------------------------------------------------------ drag -- */
function bsBlockTouch(e) { if (BS.drag && BS.drag.active) e.preventDefault(); }

function bsHit(x, y) {
  const g = BS.groups[BS.cur];
  const el = document.elementFromPoint(x, y);
  const catEl = el && el.closest('[data-drop-cat]');
  if (catEl && bsIsAdminItems(g)) return { type: 'cat', cat: catEl.dataset.dropCat, el: catEl };
  const kb = $('#tg-kb'); const phone = $('.tg-phone');
  if (!kb || !phone) return null;
  const pr = phone.getBoundingClientRect();
  if (x < pr.left - 30 || x > pr.right + 30 || y < pr.top - 30 || y > pr.bottom + 30) return null;
  const rowEls = $$('.tg-row[data-row]', kb);
  if (!rowEls.length) return { type: 'newrow', index: 0 };
  const rects = rowEls.map(r => r.getBoundingClientRect());
  for (let i = 0; i < rects.length; i++) {
    const r = rects[i];
    if (y >= r.top && y <= r.bottom) {
      if (!g.rowsEditable) return { type: 'newrow', index: y < (r.top + r.bottom) / 2 ? i : i + 1 };
      if (y < r.top + r.height * 0.22) return { type: 'newrow', index: i };
      if (y > r.bottom - r.height * 0.22) return { type: 'newrow', index: i + 1 };
      const btns = $$('.tg-btn', rowEls[i]).filter(b => b.dataset.key !== BS.drag.key);
      let idx = 0;
      btns.forEach(b => { const br = b.getBoundingClientRect(); if (x > br.left + br.width / 2) idx++; });
      return { type: 'row', row: i, index: idx };
    }
  }
  if (y < rects[0].top) return { type: 'newrow', index: 0 };
  if (y > rects[rects.length - 1].bottom) return { type: 'newrow', index: rects.length };
  for (let i = 0; i < rects.length - 1; i++) {
    if (y > rects[i].bottom && y < rects[i + 1].top) return { type: 'newrow', index: i + 1 };
  }
  return null;
}

function bsShowIndicator(t) {
  const kb = $('#tg-kb'); if (!kb) return;
  let ind = $('#bs-ind');
  if (!ind) { ind = document.createElement('div'); ind.id = 'bs-ind'; kb.appendChild(ind); }
  $$('[data-drop-cat]').forEach(c => c.classList.remove('hot'));
  if (!t) { ind.style.display = 'none'; return; }
  if (t.type === 'cat') { t.el.classList.add('hot'); ind.style.display = 'none'; return; }
  const g = BS.groups[BS.cur];
  const kr = kb.getBoundingClientRect();
  const rowEls = $$('.tg-row[data-row]', kb);
  const full = t.type === 'row' && g.rows[t.row].filter(k => k !== BS.drag.key).length >= BS_MAX_ROW;
  ind.className = (full ? 'bad ' : '') + (t.type === 'newrow' ? 'h' : 'v');
  if (t.type === 'newrow') {
    let y;
    if (!rowEls.length) y = 24;
    else if (t.index === 0) y = rowEls[0].getBoundingClientRect().top - kr.top - 4;
    else if (t.index >= rowEls.length) y = rowEls[rowEls.length - 1].getBoundingClientRect().bottom - kr.top + 4;
    else y = (rowEls[t.index - 1].getBoundingClientRect().bottom + rowEls[t.index].getBoundingClientRect().top) / 2 - kr.top;
    ind.style.cssText = `display:block;left:6px;right:6px;top:${y - 2}px;height:4px`;
  } else {
    const rowEl = rowEls[t.row]; const rr = rowEl.getBoundingClientRect();
    const btns = $$('.tg-btn', rowEl).filter(b => b.dataset.key !== BS.drag.key);
    let x;
    if (!btns.length) x = rr.left + rr.width / 2;
    else if (t.index === 0) x = btns[0].getBoundingClientRect().left - 3;
    else if (t.index >= btns.length) x = btns[btns.length - 1].getBoundingClientRect().right + 3;
    else x = (btns[t.index - 1].getBoundingClientRect().right + btns[t.index].getBoundingClientRect().left) / 2;
    ind.style.cssText = `display:block;left:${x - kr.left - 2}px;top:${rr.top - kr.top}px;width:4px;height:${rr.height}px`;
  }
}

function bsGhostMove(x, y) {
  const gh = BS.drag && BS.drag.ghost; if (!gh) return;
  gh.style.left = (x - gh.offsetWidth / 2) + 'px';
  gh.style.top = (y - gh.offsetHeight / 2) + 'px';
}

function bsDragStart() {
  const st = BS.drag; if (!st || st.active) return;
  st.active = true;
  clearTimeout(st.timer);
  const gh = st.btn.cloneNode(true);
  gh.classList.add('tg-ghost');
  gh.style.width = st.btn.offsetWidth + 'px';
  document.body.appendChild(gh);
  st.ghost = gh;
  st.btn.classList.add('drag-src');
  document.body.classList.add('bs-dragging');
  document.addEventListener('touchmove', bsBlockTouch, { passive: false });
  bsGhostMove(st.lx ?? st.x, st.ly ?? st.y);
  if (navigator.vibrate) { try { navigator.vibrate(12); } catch (_) {} }
}

function bsDragCleanup() {
  const st = BS.drag;
  if (st) { clearTimeout(st.timer); if (st.ghost) st.ghost.remove(); }
  document.removeEventListener('pointermove', bsOnMove);
  document.removeEventListener('pointerup', bsOnUp);
  document.removeEventListener('pointercancel', bsOnCancel);
  document.removeEventListener('touchmove', bsBlockTouch);
  document.body.classList.remove('bs-dragging');
  $('#bs-ind')?.remove();
  $$('[data-drop-cat]').forEach(c => c.classList.remove('hot'));
  $$('.drag-src').forEach(b => b.classList.remove('drag-src'));
  BS.drag = null;
}

function bsSelect(key) {
  BS.sel = key; bsRenderPhone(); bsRenderInspector();
  requestAnimationFrame(() => {
    const s = $('.tg-btn.sel');
    if (!s || window.innerWidth >= 1000) return;
    const over = s.getBoundingClientRect().bottom - window.innerHeight * 0.45;
    if (over <= 0) return;
    let sc = s.parentElement;
    while (sc && sc.scrollHeight <= sc.clientHeight + 1) sc = sc.parentElement;
    (sc || document.scrollingElement).scrollBy({ top: over, behavior: 'smooth' });
  });
}

function bsOnPointerDown(e) {
  const btn = e.target.closest('.tg-btn[data-key]');
  if (!btn || (e.pointerType === 'mouse' && e.button !== 0)) return;
  if (BS.drag) bsDragCleanup();
  const g = BS.groups[BS.cur];
  const st = { key: btn.dataset.key, btn, x: e.clientX, y: e.clientY, lx: e.clientX, ly: e.clientY, type: e.pointerType, active: false, timer: null, ghost: null, target: null };
  BS.drag = st;
  if (g.reorderable && st.type !== 'mouse') st.timer = setTimeout(bsDragStart, 380);
  document.addEventListener('pointermove', bsOnMove, { passive: false });
  document.addEventListener('pointerup', bsOnUp);
  document.addEventListener('pointercancel', bsOnCancel);
}

function bsOnMove(e) {
  const st = BS.drag; if (!st) return;
  st.lx = e.clientX; st.ly = e.clientY;
  if (!st.active) {
    const dist = Math.hypot(e.clientX - st.x, e.clientY - st.y);
    if (st.type === 'mouse') { if (dist > 5 && BS.groups[BS.cur].reorderable) bsDragStart(); }
    else if (dist > 10) bsDragCleanup();
    return;
  }
  e.preventDefault();
  bsGhostMove(e.clientX, e.clientY);
  st.target = bsHit(e.clientX, e.clientY);
  bsShowIndicator(st.target);
}

function bsOnUp(e) {
  const st = BS.drag; if (!st) return;
  const key = st.key;
  const moved = Math.hypot(e.clientX - st.x, e.clientY - st.y);
  if (!st.active || moved < 10) {
    const wasTouch = st.type !== 'mouse';
    bsDragCleanup();
    if (wasTouch) {
      BS.suppressClick = true;
      setTimeout(() => { BS.suppressClick = false; }, 350);
      bsSelect(key);
    }
    return;
  }
  const target = bsHit(e.clientX, e.clientY);
  bsDragCleanup();
  BS.suppressClick = true;
  setTimeout(() => { BS.suppressClick = false; }, 350);
  bsApplyDrop(key, target);
}

function bsOnCancel() { bsDragCleanup(); }

/* ------------------------------------------------------------------ save -- */
async function bsSaveAll() {
  const btns = $$('#bs-save, #bs-save2');
  const btn = btns[0];
  for (const gk of BS.order) {
    const g = BS.groups[gk];
    const bad = g.items.find(i => BS.edited.has(bsId(g, i.key)) && i.has_text && !(i.text || '').trim());
    if (bad) { toast(`متن دکمه‌ی «${bad.label}» نمی‌تونه خالی باشه.`, true); return; }
  }
  if (BS.mm.dirty && !BS.mm.reply && !BS.mm.inline) { toast('حداقل یکی از منوی پایین یا شیشه‌ای باید فعال باشه.', true); return; }
  btns.forEach(b => { b.disabled = true; });
  const prev = btn.textContent; btn.textContent = 'در حال ذخیره...';
  try {
    if (BS.mm.dirty) {
      await apiPost('/settings/main-menu-display', { reply_enabled: BS.mm.reply, inline_enabled: BS.mm.inline, columns: BS.mm.columns });
    }
    const adminKeys = BS.order.filter(k => k.startsWith('admin_items__'));
    if (adminKeys.some(k => BS.dirty.has(k))) {
      const overrides = {};
      adminKeys.forEach(k => {
        const g = BS.groups[k];
        g.items.forEach(it => { if (it.default_category && it.default_category !== g.category) overrides[it.key] = g.category; });
      });
      await apiPost('/buttons/admin-item-categories', { overrides });
    }
    for (const gk of BS.order) {
      const g = BS.groups[gk];
      const edited = g.items.filter(it => BS.edited.has(bsId(g, it.key)));
      if (!BS.dirty.has(gk) && !edited.length) continue;
      if (gk === 'main_menu') {
        const buttons = edited.map(i => ({
          key: i.key,
          enabled: i.togglable ? !!i.enabled : undefined,
          text: i.has_text ? i.text : undefined,
          style: i.has_style ? i.style : undefined,
        }));
        if (BS.dirty.has(gk)) await apiPost('/settings/menu-layout', { order: bsFlatOrder(g), breaks: bsBreaks(g), buttons });
        else await apiPost('/settings/menu-order', { order: bsFlatOrder(g), buttons });
        continue;
      }
      if (BS.dirty.has(gk) && g.reorderable) {
        await apiPost('/buttons/layout', { group: gk, order: bsFlatOrder(g), breaks: g.rowsEditable ? bsBreaks(g) : [] });
      }
      for (const it of edited) {
        if (!it.has_text && !it.has_style && !it.togglable) continue;
        await apiPost('/buttons/item', { group: gk, key: it.key, text: it.has_text ? it.text : undefined, style: it.has_style ? it.style : undefined, enabled: it.togglable ? !!it.enabled : undefined });
      }
    }
    toast('ذخیره شد.');
    await bsLoad();
    bsRefresh();
  } catch (e) {
    handleErr(e);
    btns.forEach(b => { b.disabled = false; });
    btn.textContent = prev;
  }
}

/* ------------------------------------------------------------------ boot -- */
function bsWire() {
  const root = $('#bs-root');
  root.addEventListener('pointerdown', (e) => { if (e.target.closest('#bs-stage')) bsOnPointerDown(e); });
  root.addEventListener('contextmenu', (e) => { if (e.target.closest('.tg-btn')) e.preventDefault(); });
  root.addEventListener('click', async (e) => {
    const q = (sel) => { const el = e.target.closest(sel); return el && root.contains(el) ? el : null; };
    const screen = q('[data-bs-screen]');
    if (screen) { BS.cur = screen.dataset.bsScreen; BS.sel = null; bsRefresh(); return; }
    if (q('#bs-save, #bs-save2')) return bsSaveAll();
    if (q('#bs-reload')) { await bsLoad(); bsRefresh(); toast('تغییرات ذخیره‌نشده برگردانده شد.'); return; }
    const mode = q('[data-bs-mode]');
    if (mode) { BS.mm.mode = mode.dataset.bsMode; bsRenderPhone(); return; }
    const mmSw = q('[data-bs-mm]');
    if (mmSw) {
      const k = mmSw.dataset.bsMm; BS.mm[k] = !BS.mm[k]; BS.mm.dirty = true;
      if (!BS.mm.reply && !BS.mm.inline) { BS.mm[k] = true; toast('حداقل یکی از دو منو باید فعال بمونه.', true); }
      if (BS.mm.mode === 'reply' && !BS.mm.reply && BS.mm.inline) BS.mm.mode = 'inline';
      if (BS.mm.mode === 'inline' && !BS.mm.inline && BS.mm.reply) BS.mm.mode = 'reply';
      bsRefresh(); return;
    }
    const cat = q('.bs-cat');
    if (cat && BS.sel) { bsMoveToCat(BS.sel, cat.dataset.dropCat); bsRefresh(); return; }
    const sw = q('.bs-sw');
    if (sw && BS.sel) {
      const g = BS.groups[BS.cur]; bsItem(g, BS.sel).style = sw.dataset.bsStyle; bsMarkEdited(g, BS.sel);
      bsRenderTop(); bsRenderScreens(); bsRenderPhone(); bsRenderInspector(); return;
    }
    const act = q('[data-bs-act]');
    if (act) { if (act.dataset.bsAct === 'save') return bsSaveAll(); bsAction(act.dataset.bsAct); return; }
    const tgBtn = q('#bs-stage .tg-btn[data-key]');
    if (tgBtn) {
      if (BS.suppressClick) return;
      bsSelect(tgBtn.dataset.key); return;
    }
    if (q('#bs-stage') && !q('.bs-modebar, .bs-catdrop') && BS.sel) {
      BS.sel = null; bsRenderPhone(); bsRenderInspector();
    }
  });
  root.addEventListener('input', (e) => {
    if (e.target.id === 'bs-text' && BS.sel) {
      const g = BS.groups[BS.cur];
      bsItem(g, BS.sel).text = e.target.value; bsMarkEdited(g, BS.sel);
      bsRenderTop(); bsRenderScreens(); bsRenderPhone();
      const sv = $('.bs-insp-save'); if (sv) sv.disabled = false;
    }
  });
  root.addEventListener('change', (e) => {
    if (e.target.id === 'bs-cat' && e.target.value && BS.sel) { bsMoveToCat(BS.sel, e.target.value); bsRefresh(); }
  });
}

async function renderButtons() {
  if (BS.drag) bsDragCleanup();
  await bsLoad();
  setContent(`
    <div id="bs-root" class="bs-root">
      <div class="card bs-topcard" id="bs-top"></div>
      <div class="bs-grid">
        <aside class="bs-screens" id="bs-screens"></aside>
        <section class="bs-stage" id="bs-stage"><div id="bs-stage-body"></div></section>
        <aside class="bs-inspector card" id="bs-inspector"></aside>
      </div>
      <div class="settings-save-bar" id="bs-bottom"></div>
    </div>`);
  bsWire();
  bsRefresh();
}

/* ========================================================= bot texts === */
// قابلیت ۵۰: تب مستقل «متن‌های ربات». برخلاف تب «دکمه‌ها»، لیست این تب
// خودکار از سرور می‌آید (GET /api/texts) و با اضافه‌شدن db.get_text(...)ی
// جدید به کد بات، همان لحظه‌ی بالا آمدن بعدیِ بات، ردیف تازه‌ای این‌جا ظاهر
// می‌شود - بدون نیاز به تغییر این فایل.
let BOT_TEXTS_ALL = [];

function botTextItemHtml(it) {
  return `
    <div class="card" style="margin-bottom:12px" data-bt-key="${esc(it.key)}">
      <div class="card-head">
        <h3 style="font-size:13px;font-weight:500">${esc(it.category)} <span style="color:var(--muted,#9ca3af)">/ ${esc(it.key)}</span></h3>
        ${it.overridden ? '<span class="badge">ویرایش‌شده</span>' : ''}
      </div>
      <textarea class="input bt-textarea" rows="3" style="width:100%;resize:vertical">${esc(it.current_text)}</textarea>
      <div style="display:flex;gap:8px;margin-top:10px">
        <button class="btn btn-primary btn-sm bt-save">ذخیره</button>
        ${it.overridden ? '<button class="btn btn-sm bt-reset">بازگردانی به پیش‌فرض</button>' : ''}
      </div>
    </div>`;
}

function renderBotTextList(items) {
  const root = content();
  $('#bt-list', root).innerHTML = items.length
    ? items.map(botTextItemHtml).join('')
    : '<div class="empty-state">چیزی پیدا نشد.</div>';
  $$('.bt-save', root).forEach(b => b.addEventListener('click', e => saveBotText(e.target.closest('[data-bt-key]'))));
  $$('.bt-reset', root).forEach(b => b.addEventListener('click', e => resetBotText(e.target.closest('[data-bt-key]'))));
}

async function saveBotText(card) {
  const key = card.dataset.btKey;
  const value = $('.bt-textarea', card).value;
  const btn = $('.bt-save', card);
  btn.disabled = true;
  const prevTxt = btn.textContent; btn.textContent = 'در حال ذخیره...';
  try {
    await apiPost('/texts', { key, value });
    const item = BOT_TEXTS_ALL.find(i => i.key === key);
    if (item) { item.current_text = value; item.overridden = true; }
    renderBotTextList(BOT_TEXTS_ALL);
    toast('ذخیره شد.');
  } catch (e) { handleErr(e); } finally { btn.disabled = false; btn.textContent = prevTxt; }
}

async function resetBotText(card) {
  const key = card.dataset.btKey;
  try {
    await apiPost('/texts/reset', { key });
    const item = BOT_TEXTS_ALL.find(i => i.key === key);
    if (item) { item.current_text = item.default_text; item.overridden = false; }
    renderBotTextList(BOT_TEXTS_ALL);
    toast('به پیش‌فرض بازگشت.');
  } catch (e) { handleErr(e); }
}

async function renderBotTexts() {
  const res = await apiGet('/texts');
  BOT_TEXTS_ALL = res.items || [];
  const html = `
    <div class="card" style="margin-bottom:18px">
      <span class="card-sub">همه‌ی متن‌های ربات (پیام‌های کاربر و پیام‌های ادمین داخل ربات) این‌جا لیست شده‌اند. با اضافه‌شدن قابلیت‌های جدید به ربات، متن‌های تازه خودکار به همین لیست اضافه می‌شوند.</span>
      <input class="input" id="bt-search" placeholder="جستجو در کلید/دسته/متن..." style="margin-top:10px">
    </div>
    <div id="bt-list"></div>`;
  setContent(html);
  renderBotTextList(BOT_TEXTS_ALL);
  $('#bt-search', content()).addEventListener('input', e => {
    const q = e.target.value.trim().toLowerCase();
    const filtered = !q ? BOT_TEXTS_ALL : BOT_TEXTS_ALL.filter(it =>
      it.key.toLowerCase().includes(q) || it.category.toLowerCase().includes(q) || it.current_text.toLowerCase().includes(q));
    renderBotTextList(filtered);
  });
}

/* ============================================================ gateways === */
function _gwHeadersToText(h) { return Object.entries(h || {}).map(([k, v]) => `${k}: ${v}`).join('\n'); }
function _gwTextToHeaders(t) {
  const out = {};
  (t || '').split('\n').forEach(line => {
    const idx = line.indexOf(':');
    if (idx > 0) out[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  });
  return out;
}

function _gwFormHtml(gw) {
  const c = (gw && gw.config) || {};
  const credFields = c.credential_fields || [];
  const creds = c.credentials || {};
  const cr = c.create_request || {};
  const crResp = c.create_response || {};
  const vr = c.verify_request || {};
  const vResp = c.verify_response || {};
  const wa = c.webhook_auth || {};
  const wm = c.webhook_mapping || {};
  return `
    <input type="hidden" id="gw-id" value="${gw ? gw.id : ''}">
    <div class="form-grid">
      <input class="input" id="gw-name" placeholder="نام نمایشی (مثلاً زرین‌پال)" value="${gw ? esc(gw.name) : ''}">
      <input class="input" id="gw-key" placeholder="کلید یکتا انگلیسی (مثلاً zarinpal)" value="${gw ? esc(gw.key) : ''}" ${gw ? 'disabled' : ''} style="direction:ltr;text-align:left">
      <label class="field field-row"><span>فعال</span>${_swSpan('gw-enabled', gw ? gw.enabled : false)}</label>
      <label class="field"><span>حداقل مبلغ مجاز با این درگاه (تومان - ۰ یعنی بدون محدودیت)</span>
        <input class="input" id="gw-min-amount" type="number" min="0" value="${gw ? (gw.min_amount || 0) : 0}"></label>
      <label class="field"><span>تحمل اختلاف مبلغ پرداختی (٪) — اگر پایین‌تر «مسیر مبلغ» را در بخش استعلام/وب‌هوک پر کنی</span>
        <input class="input" id="gw-amount-tolerance" type="number" min="0" step="0.1" value="${c.amount_tolerance_percent != null ? c.amount_tolerance_percent : 1}"></label>
    </div>

    <div class="card-sub" style="margin:16px 0 6px"><b>💰 مبلغ ارسالی به درگاه</b></div>
    <div class="form-grid">
      <label class="field"><span>واحد/ارز مبلغ ارسالی به <code>{amount}</code></span>
        <select class="input" id="gw-amount-currency">
          <option value="toman" ${(c.amount_currency || 'toman') === 'toman' ? 'selected' : ''}>تومان</option>
          <option value="rial" ${c.amount_currency === 'rial' ? 'selected' : ''}>ریال</option>
          <option value="usd" ${c.amount_currency === 'usd' ? 'selected' : ''}>دلار (درگاه ارزی — بر اساس نرخ دلار تنظیمات)</option>
        </select></label>
      <label class="field"><span>ضریب مبلغ (روی مبلغ نهایی همین درگاه ضرب می‌شود — پیش‌فرض ۱)</span>
        <input class="input" id="gw-amount-multiplier" type="number" min="0" step="0.0001" value="${c.amount_multiplier != null ? c.amount_multiplier : 1}"></label>
    </div>
    <div class="card-sub" style="margin:6px 0 0;color:var(--muted,#9ca3af);font-size:12px">اگه «دلار» رو انتخاب کنی، مبلغ تومانیِ سفارش با نرخ دلار (تنظیمات → کریپتو → نرخ دلار به تومان، یا نرخ خودکار) به دلار تبدیل می‌شه و همون (بعد از اعمال ضریب) به <code>{amount}</code> پاس داده می‌شه؛ برای تومان/ریال هم ضریب روی همون مبلغ (بعد از تبدیل ریال) اعمال می‌شه. مبلغ تومانیِ واقعیِ سفارش هميشه بدون تغییر و جدا از این تنظیمات هم در <code>{amount_toman}</code> در دسترسه.</div>

    <div class="card-sub" style="margin:16px 0 6px"><b>🔑 اعتبارنامه (API Key و مشابه)</b></div>
    <div id="gw-cred-rows"></div>
    <button type="button" class="btn btn-sm" id="gw-add-cred">+ فیلد جدید</button>

    <div class="card-sub" style="margin:16px 0 6px"><b>📨 ساخت فاکتور (Create Invoice)</b></div>
    <div class="form-grid">
      <select class="input" id="gw-cr-method"><option ${cr.method !== 'GET' ? 'selected' : ''}>POST</option><option ${cr.method === 'GET' ? 'selected' : ''}>GET</option></select>
      <select class="input" id="gw-cr-bodytype"><option value="json" ${(cr.body_type || 'json') === 'json' ? 'selected' : ''}>JSON</option><option value="form" ${cr.body_type === 'form' ? 'selected' : ''}>Form</option></select>
    </div>
    <input class="input" id="gw-cr-url" placeholder="URL — https://gateway.example.com/api/invoice" style="direction:ltr;text-align:left;margin-top:8px" value="${esc(cr.url || '')}">
    <label class="field"><span>Headers (هر خط: Key: Value)</span><textarea class="input" id="gw-cr-headers" rows="2" style="direction:ltr;text-align:left" placeholder="Authorization: Bearer {api_key}">${esc(_gwHeadersToText(cr.headers))}</textarea></label>
    <label class="field"><span>Body (JSON)</span><textarea class="input" id="gw-cr-body" rows="3" style="direction:ltr;text-align:left" placeholder='{"amount":"{amount}","callback":"{callback_url}","order_id":"{order_id}"}'>${esc(JSON.stringify(cr.body || {}, null, 2))}</textarea></label>
    <div class="form-grid">
      <input class="input" id="gw-cr-resp-url" placeholder="مسیر لینک پرداخت در پاسخ (data.link)" style="direction:ltr;text-align:left" value="${esc(crResp.invoice_url_path || '')}">
      <input class="input" id="gw-cr-resp-txn" placeholder="مسیر شناسه‌ی تراکنش در پاسخ (data.id)" style="direction:ltr;text-align:left" value="${esc(crResp.txn_id_path || '')}">
    </div>
    <label class="field field-row"><span>این درگاه به شماره موبایل مشتری نیاز دارد</span>${_swSpan('gw-req-phone', !!c.require_customer_phone)}</label>
    <div class="card-sub" style="margin:6px 0 0;color:var(--muted,#9ca3af);font-size:12px">اگه فعال کنی، قبل از ساخت فاکتور از مشتری خواسته می‌شه با دکمه‌ی تلگرامی «اشتراک‌گذاری شماره موبایل» شماره‌اش رو بفرسته. دو پلیس‌هولدر همیشه در دسترس‌اند: <code>{customer_user_id}</code> (آیدی عددی تلگرام مشتری، خودکار و بدون نیاز به این گزینه) و <code>{customer_phone}</code> (فقط با فعال بودن این گزینه پر می‌شه، وگرنه خالیه).</div>

    <div class="card-sub" style="margin:16px 0 6px"><b>✅ استعلام پرداخت (Verify) — برای درگاه‌هایی که کاربر را برمی‌گردانند</b></div>
    <label class="field field-row"><span>فعال باشد</span>${_swSpan('gw-v-enabled', !!c.verify_enabled)}</label>
    <div class="form-grid">
      <select class="input" id="gw-v-method"><option ${vr.method !== 'GET' ? 'selected' : ''}>POST</option><option ${vr.method === 'GET' ? 'selected' : ''}>GET</option></select>
      <select class="input" id="gw-v-bodytype"><option value="json" ${(vr.body_type || 'json') === 'json' ? 'selected' : ''}>JSON</option><option value="form" ${vr.body_type === 'form' ? 'selected' : ''}>Form</option></select>
    </div>
    <input class="input" id="gw-v-url" placeholder="URL استعلام" style="direction:ltr;text-align:left;margin-top:8px" value="${esc(vr.url || '')}">
    <label class="field"><span>Headers</span><textarea class="input" id="gw-v-headers" rows="2" style="direction:ltr;text-align:left">${esc(_gwHeadersToText(vr.headers))}</textarea></label>
    <label class="field"><span>Body (JSON) — از {query.X} برای پارامترهای بازگشتی درگاه استفاده کن</span><textarea class="input" id="gw-v-body" rows="3" style="direction:ltr;text-align:left" placeholder='{"authority":"{query.Authority}","amount":"{amount}"}'>${esc(JSON.stringify(vr.body || {}, null, 2))}</textarea></label>
    <div class="form-grid">
      <input class="input" id="gw-v-resp-status" placeholder="مسیر وضعیت در پاسخ (data.code)" style="direction:ltr;text-align:left" value="${esc(vResp.status_path || '')}">
      <input class="input" id="gw-v-resp-success" placeholder="مقادیر موفق (با کاما، مثل 100,101)" style="direction:ltr;text-align:left" value="${esc((vResp.success_values || []).join(','))}">
      <input class="input" id="gw-v-resp-amount" placeholder="مسیر مبلغ پرداختی در پاسخ (اختیاری، مثلاً data.amount)" style="direction:ltr;text-align:left" value="${esc(vResp.amount_path || '')}">
    </div>
    <div class="card-sub" style="margin:6px 0 0;color:var(--muted,#9ca3af);font-size:12px">اگر پر شود، مبلغِ برگشتی از درگاه با مبلغ واقعیِ فاکتور مقایسه می‌شود تا از تایید سفارش با پرداخت کمتر جلوگیری شود.</div>

    <div class="card-sub" style="margin:16px 0 6px"><b>📡 وب‌هوک (Webhook) — برای درگاه‌هایی که سرور به سرور خبر می‌دهند</b></div>
    <label class="field field-row"><span>فعال باشد</span>${_swSpan('gw-w-enabled', !!c.webhook_enabled)}</label>
    <select class="input" id="gw-w-mode">
      <option value="none" ${(wa.mode || 'none') === 'none' ? 'selected' : ''}>بدون احراز (فقط اتکا به شناسه‌ی تراکنش)</option>
      <option value="header_secret" ${wa.mode === 'header_secret' ? 'selected' : ''}>رمز ثابت در هدر</option>
      <option value="query_secret" ${wa.mode === 'query_secret' ? 'selected' : ''}>رمز ثابت در query string</option>
      <option value="hmac_sha256" ${wa.mode === 'hmac_sha256' ? 'selected' : ''}>امضای HMAC-SHA256</option>
    </select>
    <div class="form-grid" style="margin-top:8px">
      <input class="input" id="gw-w-header" placeholder="نام هدر (رمز/امضا)" style="direction:ltr;text-align:left" value="${esc(wa.header_name || '')}">
      <input class="input" id="gw-w-query" placeholder="نام پارامتر query (رمز)" style="direction:ltr;text-align:left" value="${esc(wa.query_param || '')}">
      <input class="input" id="gw-w-secretfield" placeholder="کدام فیلد اعتبارنامه = رمز" style="direction:ltr;text-align:left" value="${esc(wa.secret_field || '')}">
    </div>
    <div class="form-grid" style="margin-top:8px">
      <input class="input" id="gw-w-map-txn" placeholder="مسیر شناسه‌ی تراکنش در بدنه" style="direction:ltr;text-align:left" value="${esc(wm.txn_id_path || '')}">
      <input class="input" id="gw-w-map-status" placeholder="مسیر وضعیت در بدنه" style="direction:ltr;text-align:left" value="${esc(wm.status_path || '')}">
      <input class="input" id="gw-w-map-success" placeholder="مقادیر موفق (با کاما)" style="direction:ltr;text-align:left" value="${esc((wm.success_values || []).join(','))}">
      <input class="input" id="gw-w-map-amount" placeholder="مسیر مبلغ در بدنه (اختیاری)" style="direction:ltr;text-align:left" value="${esc(wm.amount_path || '')}">
    </div>
    ${(wa.mode || 'none') === 'none' ? '<div class="card-sub" style="margin:6px 0 0;color:var(--danger,#ef4444);font-size:12px">⚠️ بدون احراز هویت وب‌هوک، پیشنهاد می‌شود حتماً «مسیر مبلغ در بدنه» را پر کنی؛ در غیر این صورت هر کسی که txn را حدس بزند می‌تواند سفارش خودش را جعلاً پرداخت‌شده اعلام کند.</div>' : ''}

    <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap">
      <button class="btn btn-primary" id="gw-save">💾 ذخیره</button>
      ${gw ? '<button class="btn" id="gw-test">🧪 تست اتصال (فاکتور واقعی ۱۰۰۰ تومانی)</button>' : ''}
      ${gw ? '<button class="btn btn-danger" id="gw-del">🗑 حذف</button>' : ''}
    </div>
    <div class="card-sub" id="gw-form-err" style="color:var(--danger,#ef4444)"></div>
  `;
}

function _gwAddCredRow(container, name, label, secret, value) {
  const row = document.createElement('div');
  row.className = 'form-grid';
  row.style.marginBottom = '6px';
  row.innerHTML = `
    <input class="input" placeholder="نام فیلد (مثل api_key)" value="${esc(name || '')}" data-cred-name style="direction:ltr;text-align:left">
    <input class="input" placeholder="برچسب نمایشی" value="${esc(label || '')}" data-cred-label>
    <input class="input" placeholder="مقدار" value="${esc(value || '')}" data-cred-value style="direction:ltr;text-align:left">
    <label class="field field-row" style="flex:0 0 auto"><span>محرمانه</span><input type="checkbox" data-cred-secret ${secret !== false ? 'checked' : ''}></label>
    <button type="button" class="btn btn-danger btn-sm" data-cred-del>×</button>
  `;
  row.querySelector('[data-cred-del]').addEventListener('click', () => row.remove());
  container.appendChild(row);
}

function _gwCollectConfig(body) {
  const creds = {}, credFields = [];
  $$('#gw-cred-rows > div', body).forEach(row => {
    const name = row.querySelector('[data-cred-name]').value.trim();
    if (!name) return;
    creds[name] = row.querySelector('[data-cred-value]').value;
    credFields.push({ name, label: row.querySelector('[data-cred-label]').value.trim() || name, secret: row.querySelector('[data-cred-secret]').checked });
  });
  let crBody = {}, vBody = {};
  try { crBody = JSON.parse($('#gw-cr-body', body).value || '{}'); } catch (e) { throw new Error('بدنه‌ی درخواست «ساخت فاکتور» JSON معتبر نیست.'); }
  try { vBody = JSON.parse($('#gw-v-body', body).value || '{}'); } catch (e) { throw new Error('بدنه‌ی درخواست «استعلام» JSON معتبر نیست.'); }
  return {
    credential_fields: credFields,
    credentials: creds,
    create_request: {
      method: $('#gw-cr-method', body).value, url: $('#gw-cr-url', body).value.trim(),
      headers: _gwTextToHeaders($('#gw-cr-headers', body).value), body_type: $('#gw-cr-bodytype', body).value, body: crBody,
    },
    create_response: { invoice_url_path: $('#gw-cr-resp-url', body).value.trim(), txn_id_path: $('#gw-cr-resp-txn', body).value.trim() },
    require_customer_phone: _swOn(body, 'gw-req-phone'),
    verify_enabled: _swOn(body, 'gw-v-enabled'),
    verify_request: {
      method: $('#gw-v-method', body).value, url: $('#gw-v-url', body).value.trim(),
      headers: _gwTextToHeaders($('#gw-v-headers', body).value), body_type: $('#gw-v-bodytype', body).value, body: vBody,
    },
    verify_response: {
      status_path: $('#gw-v-resp-status', body).value.trim(),
      success_values: $('#gw-v-resp-success', body).value.split(',').map(s => s.trim()).filter(Boolean),
      amount_path: $('#gw-v-resp-amount', body).value.trim(),
    },
    webhook_enabled: _swOn(body, 'gw-w-enabled'),
    webhook_auth: {
      mode: $('#gw-w-mode', body).value, header_name: $('#gw-w-header', body).value.trim(),
      query_param: $('#gw-w-query', body).value.trim(), secret_field: $('#gw-w-secretfield', body).value.trim(), hmac_algo: 'sha256',
    },
    webhook_mapping: {
      txn_id_path: $('#gw-w-map-txn', body).value.trim(), status_path: $('#gw-w-map-status', body).value.trim(),
      success_values: $('#gw-w-map-success', body).value.split(',').map(s => s.trim()).filter(Boolean),
      amount_path: $('#gw-w-map-amount', body).value.trim(),
    },
    amount_tolerance_percent: parseFloat($('#gw-amount-tolerance', body).value) || 0,
    amount_currency: $('#gw-amount-currency', body).value,
    amount_multiplier: parseFloat($('#gw-amount-multiplier', body).value) || 1,
  };
}

function _gwOpenForm(gw) {
  openModal(gw ? `✏️ ویرایش: ${esc(gw.name)}` : '➕ افزودن درگاه جدید', _gwFormHtml(gw), (body, close) => {
    _bindSwitches(body);
    const credWrap = $('#gw-cred-rows', body);
    (((gw && gw.config) || {}).credential_fields || []).forEach(f => _gwAddCredRow(credWrap, f.name, f.label, f.secret, ((gw.config.credentials) || {})[f.name] || ''));
    if (!gw) _gwAddCredRow(credWrap);
    $('#gw-add-cred', body).addEventListener('click', () => _gwAddCredRow(credWrap));
    const wModeSel = $('#gw-w-mode', body);
    if (wModeSel) {
      wModeSel.addEventListener('change', () => {
        let warn = $('#gw-w-none-warn', body);
        if (wModeSel.value === 'none') {
          if (!warn) {
            warn = document.createElement('div');
            warn.id = 'gw-w-none-warn';
            warn.className = 'card-sub';
            warn.style.cssText = 'margin:6px 0 0;color:var(--danger,#ef4444);font-size:12px';
            warn.textContent = '⚠️ بدون احراز هویت وب‌هوک، پیشنهاد می‌شود حتماً «مسیر مبلغ در بدنه» را پر کنی؛ در غیر این صورت هر کسی که txn را حدس بزند می‌تواند سفارش خودش را جعلاً پرداخت‌شده اعلام کند.';
            wModeSel.parentElement.appendChild(warn);
          }
        } else if (warn) {
          warn.remove();
        }
      });
    }

    $('#gw-save', body).addEventListener('click', async () => {
      const errBox = $('#gw-form-err', body);
      errBox.textContent = '';
      try {
        const config = _gwCollectConfig(body);
        const payload = {
          key: $('#gw-key', body).value.trim(), name: $('#gw-name', body).value.trim(),
          enabled: _swOn(body, 'gw-enabled'), config,
          min_amount: Math.max(0, Number($('#gw-min-amount', body).value) || 0),
        };
        if (!payload.name || !payload.key) { errBox.textContent = 'نام و کلید درگاه الزامی است.'; return; }
        if (gw) await apiPut(`/gateways/${gw.id}`, payload);
        else await apiPost('/gateways', payload);
        toast('ذخیره شد.'); close(); renderSettings();
      } catch (e) { errBox.textContent = e.message; }
    });

    if (gw) {
      $('#gw-test', body).addEventListener('click', async () => {
        const errBox = $('#gw-form-err', body);
        errBox.textContent = 'در حال ساخت فاکتور آزمایشی...';
        try {
          const r = await apiPost(`/gateways/${gw.id}/test`, { amount_toman: 1000 });
          errBox.style.color = r.success ? 'var(--ok,#22c55e)' : 'var(--danger,#ef4444)';
          errBox.textContent = r.success ? `✅ فاکتور ساخته شد (مبلغ ارسالی: ${r.sent_amount} ${r.sent_currency}) — لینک: ${r.invoice_url || '(بدون لینک)'} — txn: ${r.txn_id}` : `❌ ${r.error}`;
        } catch (e) { errBox.textContent = e.message; }
      });
      $('#gw-del', body).addEventListener('click', async () => {
        if (!confirm('این درگاه حذف شود؟')) return;
        try { await apiDelete(`/gateways/${gw.id}`); toast('حذف شد.'); close(); renderSettings(); } catch (e) { handleErr(e); }
      });
    }
  }, { wide: true });
}

function _gwGuideHtml() {
  return `
    <p class="card-sub">این متن رو همراه با عکس/متن مستندات API درگاه پرداخت موردنظر به یه چت‌بات
    (مثل Claude یا ChatGPT) بده و بگو: «طبق این راهنما فرم رو برام پر کن». پلیس‌هولدرهای
    قابل استفاده تو URL / هدر / بدنه‌ی درخواست:</p>
    <ul style="margin:6px 0;padding-inline-start:18px;line-height:2">
      <li><code>{amount}</code> — مبلغ نهایی ارسالی (بر اساس واحد/ضریب تنظیم‌شده در بخش «مبلغ ارسالی به درگاه» — تومان/ریال/دلار)</li>
      <li><code>{amount_toman}</code> — همیشه مبلغ خامِ واقعی سفارش به تومان، بدون ضریب/تبدیل</li>
      <li><code>{currency}</code> — کد ارز مبلغ ارسالی (IRT/IRR/USD)</li>
      <li><code>{order_id}</code> — شناسه‌ی داخلی سفارش</li>
      <li><code>{description}</code> — توضیح سفارش</li>
      <li><code>{callback_url}</code> — آدرس بازگشت مرورگر کاربر بعد از پرداخت</li>
      <li><code>{webhook_url}</code> — آدرسی که خودِ سرور درگاه باید بهش وب‌هوک بزنه</li>
      <li><code>{تنظیم اعتبارنامه}</code> مثل <code>{api_key}</code> — هر فیلدی که تو بخش اعتبارنامه تعریف کردی</li>
      <li><code>{query.X}</code> — فقط تو Verify: پارامتر X از query صفحه‌ی بازگشت</li>
      <li><code>{gateway_ref}</code> — فقط تو Verify: شناسه‌ای که خودِ درگاه موقع ساخت فاکتور برگردونده</li>
      <li><code>{customer_user_id}</code> — آیدی عددی تلگرام مشتری، همیشه و خودکار پر می‌شه</li>
      <li><code>{customer_phone}</code> — شماره موبایل مشتری؛ فقط اگه تیک «این درگاه به شماره موبایل مشتری نیاز دارد» رو فعال کنی از مشتری گرفته و پر می‌شه</li>
    </ul>
    <p class="card-sub"><b>ساخت فاکتور</b> (اجباری): URL و بدنه‌ی درخواستی که فاکتور می‌سازه، به‌علاوه
    این‌که تو پاسخ JSON درگاه، «لینک پرداخت» و «شناسه‌ی تراکنش» تو کدوم مسیر هستن (مثلاً
    <code>data.link</code> یا <code>data.id</code>).</p>
    <p class="card-sub"><b>استعلام (Verify)</b> (اختیاری): برای درگاه‌هایی که فقط کاربر رو برمی‌گردونن
    و باید جدا وضعیت پرداخت رو بپرسیم. از <code>{gateway_ref}</code> یا <code>{query.X}</code> استفاده کن.</p>
    <p class="card-sub"><b>وب‌هوک</b>: مهم‌ترین بخش برای تکمیل خودکار سفارش — آدرسش رو (که خودمون به‌صورت
    <code>{webhook_url}</code> به درگاه می‌دیم) توی بدنه‌ی درخواست ساخت فاکتور به درگاه پاس بده،
    و بگو تو JSON که درگاه بهش می‌فرسته، «شناسه‌ی تراکنش» و «وضعیت» کجاست.</p>
    <p class="card-sub">بعد از پر کردن فرم: «ذخیره» بزن، بعد از دکمه‌ی «تست اتصال» استفاده کن. اگه
    خطا داد، متن خطا (که معمولاً پیام خودِ درگاهه) رو کپی کن و به همون چت‌بات بده.</p>
  `;
}

// چرا نصب APKهای این پروژه (فوروارد پیامک / اپ مدیریت) هشدار امنیتی اندروید
// را نشان می‌دهد — این توضیح مشترک، هم در راهنمای فوروارد پیامک و هم در
// راهنمای اپ مدیریت استفاده می‌شود تا یک‌جا نگه‌داری شود.
function _installWarningHtml(repoUrl) {
  return `
    <p class="card-sub"><b>⚠️ چرا موقع نصب اخطار امنیتی نشون می‌ده؟</b> چون این اپ از گوگل‌پلی نصب
    نمی‌شه (اونجا منتشر نشده)، خودِ اندروید (Play Protect) هر APK ای که خارج از پلی‌استور نصب بشه رو
    به‌صورت خودکار «ناشناس» علامت می‌زنه و هشدار عمومی «این برنامه ممکن است مضر باشد» رو نشون می‌ده -
    این هشدار برای <b>همه‌ی</b> اپ‌های خارج از پلی‌استوره (حتی اپ‌های کاملاً معتبر)، نه فقط این یکی، و
    هیچ ربطی به خطرناک‌بودن واقعی کد نداره.</p>
    <p class="card-sub">چون سورس‌کد کامل این اپ به‌صورت عمومی و اوپن‌سورس روی گیت‌هاب منتشر شده،
    هرکسی (خودت یا هر برنامه‌نویسی) می‌تونه کل کد رو بخونه و ببینه دقیقاً چیکار می‌کنه - هیچ داده‌ای به
    سرور شخص سومی فرستاده نمی‌شه، فقط با همون سروری که خودت مالکشی حرف می‌زنه:</p>
    <p class="card-sub" style="direction:ltr;text-align:left">
      <a href="${repoUrl}" target="_blank" rel="noopener">${repoUrl}</a>
    </p>
    <p class="card-sub">برای رد کردن هشدار موقع نصب: روی «نصب بدون بررسی» / «Install anyway» بزن (متن
    دقیق بسته به گوشی فرق داره). اگه گوشیت اصلاً اجازه‌ی نصب از «منابع ناشناس» رو نمی‌ده، اول باید از
    تنظیمات گوشی (Settings ← Apps ← نصب اپ‌های ناشناس / Install unknown apps) این اجازه رو برای
    مرورگر یا فایل‌منیجری که APK رو باهاش باز می‌کنی فعال کنی.</p>
  `;
}

function _smsForwarderGuideHtml() {
  const repo = 'https://github.com/mehdirafatpanah/sms-forwarder';
  const zip = 'https://github.com/mehdirafatpanah/sms-forwarder/archive/refs/heads/main.zip';
  return `
    <p class="card-sub"><b>این اپ چیکار می‌کنه؟</b> یک اپ اندروید سبک (BankSmsForwarder) که روی همون
    گوشی/سیم‌کارتی نصب می‌شه که پیامک‌های واریزی بانک بهش می‌رسه. هر پیامک بانکی که دریافت می‌شه رو
    می‌خونه و به آدرس «وب‌هوک» بالا (همراه با توکن امنیتی) می‌فرسته؛ چون مبلغ هر فاکتور یکتاست (مبلغ
    اصلی + چند رقم آخر تصادفی)، ربات خودش تشخیص می‌ده این پیامک برای کدوم فاکتور بوده و اون سفارش/شارژ
    رو <b>بدون هیچ دخالت دستی ادمین</b> تایید می‌کنه.</p>

    <p class="card-sub"><b>📥 نصب و اتصال — قدم به قدم</b></p>
    <ol style="margin:6px 0;padding-inline-start:18px;line-height:2">
      <li>APK رو از دکمه‌ی «دانلود اپ فوروارد پیامک» پایین همین راهنما دانلود کن.</li>
      <li>فایل دانلودشده رو نصب کن (اگه هشدار امنیتی دید، بخش پایین همین راهنما رو بخون).</li>
      <li>اپ رو باز کن و دسترسی «خواندن پیامک‌ها (SMS)» رو که می‌خواد، تایید کن - بدون این دسترسی اپ
      اصلاً نمی‌تونه پیامک بانک رو ببینه.</li>
      <li>«آدرس وب‌هوک» و «توکن» بالای همین صفحه (دکمه‌های «کپی آدرس» و «ساخت/بازتولید توکن») رو کپی
      کن و داخل تنظیمات اپ (Webhook URL / Token) پیست کن.</li>
      <li><b>مهم:</b> از تنظیمات گوشی، این اپ رو از «بهینه‌سازی باتری» (Battery optimization) مستثنی
      کن. بدون این کار، اندروید ممکنه اپ رو در پس‌زمینه ببنده و پیامک‌های جدید رو از دست بدی.</li>
    </ol>
    <p class="card-sub">هر بار «بازتولید توکن» بزنی، توکن قبلی از کار می‌افته و باید همون توکن جدید رو
    داخل اپ هم آپدیت کنی، وگرنه پیامک‌ها دیگه تایید نمی‌شن.</p>

    ${_installWarningHtml(repo)}

    <div class="actions" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
      <a href="${zip}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">⬇️ دانلود اپ فوروارد پیامک (APK/سورس)</a>
      <a href="${repo}" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">مشاهده سورس‌کد در گیت‌هاب</a>
    </div>
  `;
}

function _adminAppGuideHtml() {
  const repo = 'https://github.com/mehdirafatpanah/app-shopvpn';
  const zip = 'https://github.com/mehdirafatpanah/app-shopvpn/archive/refs/heads/main.zip';
  return `
    <p class="card-sub"><b>این اپ چیکار می‌کنه؟</b> نسخه‌ی موبایل همین پنل ادمین (ShopVpnAdmin) -
    سفارش‌ها، کاربران، محصولات، نمایندگی‌ها، درگاه‌های پرداخت و تنظیمات فروشگاه رو مستقیم از روی گوشی
    مدیریت کن، به‌علاوه‌ی امکان دریافت پوش نوتیف لحظه‌ای برای سفارش‌های جدید (اگه راهنمای پوش نوتیف رو
    هم انجام بدی).</p>

    <p class="card-sub"><b>📥 نصب و اتصال — قدم به قدم</b></p>
    <ol style="margin:6px 0;padding-inline-start:18px;line-height:2">
      <li>APK رو از دکمه‌ی «دانلود اپ مدیریت» پایین همین راهنما دانلود و نصب کن.</li>
      <li>بالای همین کارت («اپ موبایل مدیریت»)، یک نام برای دستگاهت بزن و روی «ساخت توکن» بزن.</li>
      <li>توکن نمایش‌داده‌شده رو کپی کن - این توکن فقط همون یک‌بار کامل نشون داده می‌شه.</li>
      <li>داخل اپ اندروید، آدرس همین پنل (دامنه‌ای که همین الان داخل مرورگرت بازه) و همون توکن رو وارد
      کن تا وصل بشه. برای هر گوشی/دستگاه بهتره یک توکن جدا بسازی تا در صورت نیاز فقط همون یکی رو باطل
      کنی.</li>
    </ol>

    ${_installWarningHtml(repo)}

    <div class="actions" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
      <a href="${zip}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">⬇️ دانلود اپ مدیریت (APK/سورس)</a>
      <a href="${repo}" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">مشاهده سورس‌کد در گیت‌هاب</a>
    </div>
  `;
}

function _pushNotifGuideHtml() {
  const repo = 'https://github.com/mehdirafatpanah/app-shopvpn';
  return `
    <p class="card-sub">پوش نوتیف اپ مدیریت روی <b>پروژه‌ی فایربیس (Firebase) خودت</b> کار می‌کنه - هر
    نصب مستقل ShopVPN، پروژه‌ی فایربیس مجزای خودش رو می‌سازه (رایگانه)، و اپ اندروید (بدون نیاز به
    بیلد جدید) این تنظیمات رو در لحظه‌ی ورود از همین پنل می‌خونه.</p>

    <p class="card-sub"><b>🔔 قدم‌های فعال‌سازی</b></p>
    <ol style="margin:6px 0;padding-inline-start:18px;line-height:2">
      <li>وارد <a href="https://console.firebase.google.com" target="_blank" rel="noopener">console.firebase.google.com</a>
      شو و یک پروژه‌ی جدید بساز (Add project) - رایگانه، نیازی به کارت بانکی نیست.</li>
      <li>داخل پروژه، «Add app» رو بزن و نوع اپ رو Android انتخاب کن. در «Android package name»
      دقیقاً همین رو وارد کن (بزرگی/کوچکی حروف مهمه): <code>com.shopvpn.admin</code></li>
      <li>فایل <code>google-services.json</code> که گوگل بهت می‌ده رو دانلود کن (نیازی به قدم‌های بعدی
      SDK پیشنهادی گوگل نیست، فقط همین فایل کافیه).</li>
      <li>به تب «🔔 پوش نوتیف اندروید (Firebase)» همین صفحه برگرد، کل محتوای فایل رو داخل کادر
      «استخراج خودکار از google-services.json» پیست کن و دکمه‌ی «استخراج و پرکردن خودکار» رو بزن؛
      ۴ فیلد پایینش خودکار پر می‌شن. بعد «ذخیره تغییرات» رو بزن.</li>
      <li>برای اینکه سرور واقعاً بتونه پوش بفرسته (نه فقط اپ توکن بگیره): توی همون کنسول فایربیس برو
      Project Settings ← Service Accounts ← «Generate new private key»، و کل فایل JSON دانلودشده رو
      داخل فیلد «Firebase Service Account JSON» (کمی پایین‌تر همین تب) پیست کن و دوباره ذخیره کن.</li>
      <li>اپ اندروید مدیریت رو <b>کامل ببند</b> (نه فقط برو پس‌زمینه، از لیست اپ‌های اخیر هم حذفش کن) و
      دوباره باز کن تا با تنظیمات جدید فایربیس مقداردهی بشه.</li>
      <li>برای تست: از همین تب دکمه‌ی «ارسال پوش تست» رو بزن - اگه گوشیت پوش رو گرفت، تمام شد؛ اگه
      نگرفت، دسترسی نوتیف و بهینه‌سازی باتری اپ رو روی گوشی چک کن.</li>
    </ol>

    <p class="card-sub">این ۴ مقدار محرمانه نیستن (داخل خود APK هم قابل مشاهده‌ان)، فقط برای شناسایی
    پروژه‌ی فایربیس هستن؛ چیزی که واقعاً باید محرمانه بمونه همون «Service Account JSON» بالاست.</p>

    <p class="card-sub">اپ اندروید مدیریت هم مثل اپ فوروارد پیامک کاملاً اوپن‌سورسه، پس هیچ نگرانی
    امنیتی‌ای از بابت نصبش (یا هشداری که اندروید موقع نصب نشون می‌ده) وجود نداره - سورس کامل:</p>
    <p class="card-sub" style="direction:ltr;text-align:left">
      <a href="${repo}" target="_blank" rel="noopener">${repo}</a>
    </p>
  `;
}

// همه‌ی روش‌های پرداخت (حداقل مبلغ هر روش، درگاه‌های سفارشی، کارت‌به‌کارت خودکار)
// در همین یک تب («تنظیمات» ← «پرداخت») کنار کارت/کریپتو/آبان‌گیت‌وی نمایش داده می‌شود
// تا مدیریت پرداخت یک‌جا باشد، نه پخش‌شده در چند صفحه‌ی جدا.
function paymentExtrasHtml({ methods, gateways, c2cCards, c2cWebhook, c2cInvoices }) {
  const builtin = (methods || []).filter(m => !m.is_custom && m.key !== 'wallet');
  return `
    <div class="card">
      <div class="card-sub" style="margin-bottom:10px"><b>👛 روش‌های پرداخت مجاز برای شارژ کیف پول</b> — مستقل از
        محدودیت روش پرداخت هر محصول: با این تنظیم می‌توانی مشخص کنی کاربر هنگام شارژ کیف پول کدام روش‌ها را ببیند.</div>
      <button class="btn btn-sm" id="wallet-pm-edit">✏️ مدیریت روش‌های پرداخت شارژ کیف پول</button>
    </div>

    <div class="card">
      <div class="card-sub" style="margin-bottom:10px"><b>🛠 روش‌های پرداخت مجاز برای ساخت کانفیگ شخصی</b> — مشخص کن
        کاربر هنگام ساخت کانفیگ شخصی کدام روش‌ها (کیف پول، کارت‌به‌کارت، درگاه‌ها) را ببیند.</div>
      <button class="btn btn-sm" id="cc-pm-edit">✏️ مدیریت روش‌های پرداخت کانفیگ شخصی</button>
    </div>

    <div class="card">
      <div class="card-sub" style="margin-bottom:10px"><b>💵 حداقل مبلغ مجاز هر روش پرداخت</b> — اگر مبلغ سفارش
        از این عدد کمتر باشد، آن روش برای کاربر نمایش داده نمی‌شود (۰ یعنی بدون محدودیت).
        در بات و مینی‌اپ هر دو یکسان اعمال می‌شود.</div>
      <div class="table-wrap"><table>
        <thead><tr><th>روش پرداخت</th><th>حداقل مبلغ (تومان)</th><th></th><th>پوش نوتیف ادمین</th><th>پوش «معطل‌مانده» بعد از (دقیقه)</th></tr></thead>
        <tbody>${builtin.map(m => `<tr>
          <td>${esc(m.label)}</td>
          <td><input class="input" data-min-amount="${esc(m.key)}" type="number" min="0" value="${m.min_amount || 0}" style="max-width:160px"></td>
          <td><button class="btn btn-sm" data-save-min="${esc(m.key)}">ذخیره</button></td>
          <td><span class="switch" data-push-key="${esc(m.key)}" data-on="${m.push_enabled ? '1' : '0'}" title="پوش نوتیف ادمین برای این روش پرداخت"><i></i></span></td>
          <td>${m.is_instant ? `<div class="form-grid" style="grid-template-columns:120px auto;gap:6px">
            <input class="input" data-notify-timeout="${esc(m.key)}" type="number" min="0" value="${m.notify_timeout_minutes || 0}" style="max-width:100px" title="۰ یعنی خاموش">
            <button class="btn btn-sm" data-save-timeout="${esc(m.key)}">ذخیره</button>
          </div>` : '—'}</td>
        </tr>`).join('')}</tbody>
      </table></div>
      <div class="card-sub" style="margin-top:8px">ستون آخر فقط برای درگاه‌های «تایید آنی» است: اگر فاکتور یک سفارش/شارژ
        بیش از این مدت هنوز new/pending بماند (نه تایید شده، نه گیرافتاده)، یک پوش جدای «معطل‌مانده» برای ادمین می‌رود
        تا خودت پیگیری کنی. صفر یعنی این قابلیت خاموش است.</div>
    </div>

    <div class="toolbar">
      <button class="btn btn-primary btn-sm" id="gw-add">+ درگاه سفارشی جدید</button>
      <button class="btn btn-sm" id="gw-guide">📖 راهنمای افزودن API</button>
    </div>
    <div class="card">
      <div class="card-sub" style="margin-bottom:10px"><b>🔌 درگاه‌های پرداخت سفارشی</b> — هر درگاهی که یک HTTP API
        داشته باشد رو بدون نوشتن کد وصل کن. از پلیس‌هولدرهایی مثل
        <code>{amount}</code>, <code>{order_id}</code>, <code>{callback_url}</code>, <code>{webhook_url}</code> و
        هر فیلد اعتبارنامه (مثلاً <code>{api_key}</code>) استفاده کن.</div>
      ${(gateways || []).length ? `<div class="table-wrap"><table>
        <thead><tr><th>نام</th><th>کلید</th><th>حداقل مبلغ</th><th>وضعیت</th><th>پوش نوتیف ادمین</th><th>پوش «معطل‌مانده» (دقیقه)</th><th>عملیات</th></tr></thead>
        <tbody>${gateways.map(gw => `<tr>
          <td>${esc(gw.name)}</td>
          <td class="mono">${esc(gw.key)}</td>
          <td>${gw.min_amount ? fmt(gw.min_amount) + ' ت' : '—'}</td>
          <td>${gw.enabled ? '<span class="badge badge-approved">فعال</span>' : '<span class="badge badge-rejected">غیرفعال</span>'}</td>
          <td><span class="switch" data-push-key="custom:${esc(gw.key)}" data-on="${(methods || []).find(m => m.key === `custom:${gw.key}`)?.push_enabled ? '1' : '0'}" title="پوش نوتیف ادمین برای این درگاه"><i></i></span></td>
          <td><div class="form-grid" style="grid-template-columns:90px auto;gap:6px">
            <input class="input" data-notify-timeout="custom:${esc(gw.key)}" type="number" min="0" value="${(methods || []).find(m => m.key === `custom:${gw.key}`)?.notify_timeout_minutes || 0}" style="max-width:90px" title="۰ یعنی خاموش">
            <button class="btn btn-sm" data-save-timeout="custom:${esc(gw.key)}">ذخیره</button>
          </div></td>
          <td><button class="btn btn-sm" data-edit="${gw.id}">ویرایش</button></td>
        </tr>`).join('')}</tbody>
      </table></div>` : '<div class="card-sub">هنوز درگاهی اضافه نشده.</div>'}
    </div>

    <div class="toolbar">
      <button class="btn btn-primary btn-sm" id="c2c-add-card">+ کارت کارت‌به‌کارت خودکار جدید</button>
    </div>
    <div class="card">
      <div class="card-sub" style="margin-bottom:10px"><b>📶 کارت‌به‌کارت با تایید خودکار (پیامک بانک)</b> — فعال‌بودن/
        مهلت/تعداد رقم یکتاساز/واحد مبلغ بالای همین صفحه (کنار کریپتو و آبان‌گیت‌وی) تنظیم می‌شود؛ اینجا فقط
        کارت‌ها و اتصال اپ <b>BankSmsForwarder</b> است. واریزی‌ها بین کارت‌های فعال چرخشی پخش می‌شوند.</div>
      ${(c2cCards || []).length ? `<div class="table-wrap"><table>
        <thead><tr><th>شماره کارت</th><th>به نام</th><th>بانک</th><th>وضعیت</th><th>عملیات</th></tr></thead>
        <tbody>${c2cCards.map(c => `<tr>
          <td class="mono">${esc(c.card_number)}</td>
          <td>${esc(c.holder_name || '—')}</td>
          <td>${esc(c.bank_name || '—')}</td>
          <td>${c.is_active ? '<span class="badge badge-approved">فعال</span>' : '<span class="badge badge-rejected">غیرفعال</span>'}</td>
          <td><button class="btn btn-sm" data-edit-card="${c.id}">ویرایش</button></td>
        </tr>`).join('')}</tbody>
      </table></div>` : '<div class="card-sub">هنوز کارتی اضافه نشده — بدون حداقل یک کارت فعال، این روش پرداخت به کاربر نمایش داده نمی‌شود.</div>'}

      <div class="card-sub" style="margin:16px 0 6px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
        <b>📡 اتصال اپ BankSmsForwarder</b>
        <button type="button" class="btn btn-sm" id="sms-forwarder-guide">📖 راهنمای کامل و دانلود</button>
      </div>
      ${(c2cWebhook || {}).webhook_url ? `<div class="form-grid">
        <input class="input" readonly value="${esc(c2cWebhook.webhook_url)}" style="direction:ltr;text-align:left">
        <button class="btn btn-sm" id="c2c-copy-url">📋 کپی آدرس</button>
      </div>` : '<div class="card-sub" style="color:var(--danger,#ef4444)">آدرس مینی‌اپ (MINIAPP_URL/API_BASE_URL) روی سرور تنظیم نشده.</div>'}
      <div class="form-grid" style="margin-top:8px">
        <input class="input" readonly value="${(c2cWebhook || {}).webhook_token_set ? '•••••••••••••••••••••• (تنظیم شده)' : 'هنوز توکنی ساخته نشده'}" style="direction:ltr;text-align:left">
        <button class="btn btn-sm" id="c2c-regen-token">🔁 ساخت/بازتولید توکن</button>
      </div>
      <div class="card-sub" style="margin-top:6px;color:var(--muted,#9ca3af);font-size:12px">
        آدرس بالا و توکن رو داخل تنظیمات اپ اندروید BankSmsForwarder (بخش Webhook URL / Token) وارد کن.
        هر بار «بازتولید توکن» بزنی، توکن قبلی از کار می‌افته و باید توی اپ هم آپدیتش کنی. برای توضیح
        کامل، نصب، و رفع اخطار امنیتی نصب، روی «راهنمای کامل و دانلود» بالا بزن.
      </div>
    </div>

    ${(c2cInvoices || []).length ? `<div class="card">
      <div class="card-sub" style="margin-bottom:10px"><b>⏳ فاکتورهای کارت‌به‌کارت در انتظار پیامک</b></div>
      <div class="table-wrap"><table>
        <thead><tr><th>#</th><th>نوع</th><th>مبلغ یکتا</th><th>ساخته‌شده</th><th>مهلت تا</th><th>وضعیت</th></tr></thead>
        <tbody>${c2cInvoices.map(i => `<tr>
          <td>${i.id}</td>
          <td>${i.kind === 'wallet_topup' ? 'شارژ کیف پول' : 'سفارش'} #${i.ref_id}</td>
          <td class="mono">${fmt(i.amount_toman)} ت</td>
          <td>${fmtDate(i.created_at)}</td>
          <td>${fmtDate(i.expires_at)}</td>
          <td>${C2C_STATUS_LABEL[i.status] || esc(i.status)}</td>
        </tr>`).join('')}</tbody>
      </table>
    </div>` : ''}
  `;
}

function bindPaymentExtrasEvents(root, { gateways, c2cCards, c2cWebhook }) {
  $('#sms-forwarder-guide', root)?.addEventListener('click', () => openModal('📖 راهنمای کامل فوروارد پیامک', _smsForwarderGuideHtml(), null, { wide: true }));
  $('#wallet-pm-edit', root)?.addEventListener('click', () => openWalletPaymentMethodsModal());
  $('#cc-pm-edit', root)?.addEventListener('click', () => openCustomConfigPaymentMethodsModal());
  $$('[data-save-min]', root).forEach(b => b.addEventListener('click', async () => {
    const key = b.dataset.saveMin;
    const value = Math.max(0, Number($(`[data-min-amount="${key}"]`, root).value) || 0);
    try {
      await apiPost(`/payment-methods/${encodeURIComponent(key)}/min-amount`, { min_amount: value });
      toast('ذخیره شد.');
    } catch (e) { handleErr(e); }
  }));

  $$('[data-save-timeout]', root).forEach(b => b.addEventListener('click', async () => {
    const key = b.dataset.saveTimeout;
    const minutes = Math.max(0, Number($(`[data-notify-timeout="${key}"]`, root).value) || 0);
    try {
      await apiPost(`/payment-methods/${encodeURIComponent(key)}/notify-timeout`, { minutes });
      toast(minutes > 0 ? `اگر بیش از ${minutes} دقیقه تایید نشود، پوش «معطل‌مانده» می‌رود.` : 'پوش «معطل‌مانده» برای این روش خاموش شد.');
    } catch (e) { handleErr(e); }
  }));

  $$('[data-push-key]', root).forEach(sw => sw.addEventListener('click', async () => {
    if (sw.dataset.busy === '1') return; // جلوگیری از دابل‌تپ/دابل‌کلیک که حالت رو خراب می‌کرد
    sw.dataset.busy = '1';
    const key = sw.dataset.pushKey;
    const nextOn = sw.dataset.on !== '1';
    sw.dataset.on = nextOn ? '1' : '0'; // خوش‌بینانه: فوری تغییر بده، اگر خطا خورد برگردون
    try {
      await apiPost(`/payment-methods/${encodeURIComponent(key)}/push`, { enabled: nextOn });
      toast(nextOn ? 'پوش این روش فعال شد.' : 'پوش این روش خاموش شد.');
    } catch (e) {
      sw.dataset.on = nextOn ? '0' : '1';
      handleErr(e);
    } finally {
      sw.dataset.busy = '0';
    }
  }));

  $('#gw-add', root).addEventListener('click', () => _gwOpenForm(null));
  $('#gw-guide', root).addEventListener('click', () => openModal('📖 راهنمای افزودن درگاه جدید', _gwGuideHtml(), null, { wide: true }));
  $$('[data-edit]', root).forEach(b => b.addEventListener('click', async () => {
    try { _gwOpenForm(await apiGet(`/gateways/${b.dataset.edit}`)); } catch (e) { handleErr(e); }
  }));

  $('#c2c-add-card', root).addEventListener('click', () => _c2cOpenCardForm(null));
  $$('[data-edit-card]', root).forEach(b => b.addEventListener('click', () => {
    const card = (c2cCards || []).find(c => String(c.id) === b.dataset.editCard);
    if (card) _c2cOpenCardForm(card);
  }));

  const copyBtn = $('#c2c-copy-url', root);
  if (copyBtn) copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText((c2cWebhook || {}).webhook_url || '').then(() => toast('آدرس کپی شد.'));
  });

  const regenBtn = $('#c2c-regen-token', root);
  if (regenBtn) regenBtn.addEventListener('click', async () => {
    if ((c2cWebhook || {}).webhook_token_set && !confirm('توکن قبلی از کار می‌افتد و باید توی اپ هم آپدیتش کنی. ادامه بدم؟')) return;
    try {
      const r = await apiPost('/settings/card-to-card/regenerate-token');
      openModal('توکن جدید وب‌هوک', `
        <div class="card-sub">این توکن رو کپی کن و توی تنظیمات اپ BankSmsForwarder وارد کن (فقط همین یک‌بار کامل نشون داده می‌شه):</div>
        <input class="input" readonly value="${esc(r.webhook_token)}" style="direction:ltr;text-align:left;margin-top:8px">
      `, null);
      renderSettings();
    } catch (e) { handleErr(e); }
  });
}

/* ==================================================== card-to-card auto === */
function _c2cCardFormHtml(card) {
  return `
    <input type="hidden" id="c2c-id" value="${card ? card.id : ''}">
    <label class="field"><span>شماره کارت (۱۶ رقم)</span>
      <input class="input" id="c2c-number" maxlength="19" style="direction:ltr;text-align:left"
        placeholder="6037-9917-xxxx-xxxx" value="${card ? esc(card.card_number) : ''}"></label>
    <div class="form-grid">
      <input class="input" id="c2c-holder" placeholder="به نام (صاحب حساب)" value="${card ? esc(card.holder_name || '') : ''}">
      <input class="input" id="c2c-bank" placeholder="نام بانک (اختیاری)" value="${card ? esc(card.bank_name || '') : ''}">
    </div>
    <label class="field"><span>اولویت نمایش (عدد کوچیک‌تر زودتر)</span>
      <input class="input" id="c2c-sort" type="number" value="${card ? (card.sort_order || 0) : 0}"></label>
    <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap">
      <button class="btn btn-primary" id="c2c-save">💾 ذخیره</button>
      ${card ? `<button class="btn" id="c2c-toggle">${card.is_active ? '🔴 غیرفعال کردن' : '🟢 فعال کردن'}</button>` : ''}
      ${card ? '<button class="btn btn-danger" id="c2c-del">🗑 حذف</button>' : ''}
    </div>
    <div class="card-sub" id="c2c-form-err" style="color:var(--danger,#ef4444)"></div>
  `;
}

function _c2cOpenCardForm(card) {
  openModal(card ? 'ویرایش کارت' : 'کارت جدید', _c2cCardFormHtml(card), (body, close) => {
    const errBox = $('#c2c-form-err', body);
    $('#c2c-save', body).addEventListener('click', async () => {
      errBox.textContent = '';
      const payload = {
        card_number: $('#c2c-number', body).value.trim(),
        holder_name: $('#c2c-holder', body).value.trim(),
        bank_name: $('#c2c-bank', body).value.trim(),
        sort_order: Number($('#c2c-sort', body).value) || 0,
      };
      try {
        if (card) await apiPut(`/card-to-card/cards/${card.id}`, payload);
        else await apiPost('/card-to-card/cards', payload);
        toast('ذخیره شد.'); close(); renderSettings();
      } catch (e) { errBox.textContent = e.message; }
    });
    if (card) {
      $('#c2c-toggle', body).addEventListener('click', async () => {
        try { await apiPost(`/card-to-card/cards/${card.id}/toggle`); toast('انجام شد.'); close(); renderSettings(); }
        catch (e) { handleErr(e); }
      });
      $('#c2c-del', body).addEventListener('click', async () => {
        if (!confirm('این کارت حذف شود؟')) return;
        try { await apiDelete(`/card-to-card/cards/${card.id}`); toast('حذف شد.'); close(); renderSettings(); }
        catch (e) { handleErr(e); }
      });
    }
  });
}

const C2C_STATUS_LABEL = {
  pending: '<span class="badge">در انتظار پیامک</span>',
  completed: '<span class="badge badge-approved">تایید شد</span>',
  manual_review: '<span class="badge badge-rejected">منقضی - بررسی دستی</span>',
};


function translationHealthBadge(h) {
  const T = s => settingsUiText(s);
  if (h.language === 'fa' || h.language === 'en') return `<span class="badge badge-approved">${T("\u067e\u06cc\u0634\u200c\u0641\u0631\u0636")}</span>`;
  if (h.auto_quarantined) return `<span class="badge" style="border-color:var(--rose);color:var(--rose)">${T("\u0642\u0631\u0646\u0637\u06cc\u0646\u0647 \u062e\u0648\u062f\u06a9\u0627\u0631")}</span>`;
  if (h.healthy) return `<span class="badge badge-approved">${T("\u0633\u0627\u0644\u0645")}</span>`;
  return `<span class="badge" style="border-color:var(--amber,#f5a623);color:var(--amber,#f5a623)">${T("\u0646\u06cc\u0627\u0632\u0645\u0646\u062f \u0628\u0631\u0631\u0633\u06cc")}</span>`;
}

function translationMetricCard(label, value, hint='') {
  return `<div class="card" style="margin:0"><div class="card-sub">${settingsUiText(label)}</div><div style="font-size:28px;font-weight:800;margin-top:6px">${esc(String(value))}</div>${hint ? `<div class="card-sub" style="margin-top:5px">${esc(hint)}</div>` : ''}</div>`;
}

async function renderLanguages() {
  const [rows, dashboard] = await Promise.all([
    apiGet('/languages'),
    apiGet('/i18n/dashboard').catch(() => null),
  ]);
  const T = s => settingsUiText(s);
  const healthByCode = Object.fromEntries((dashboard?.languages || []).map(x => [x.language, x]));
  const summary = dashboard?.summary || {};
  const providers = dashboard?.providers || [];
  setContent(`<div class="page-head"><div><h1>${T("\u0632\u0628\u0627\u0646\u200c\u0647\u0627")}</h1><p>${T("\u0645\u062f\u06cc\u0631\u06cc\u062a \u062e\u0648\u062f\u06a9\u0627\u0631 \u062a\u0631\u062c\u0645\u0647 \u0648 \u06a9\u0627\u062a\u0627\u0644\u0648\u06af")}</p></div></div>
    ${dashboard ? `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:18px">
      ${translationMetricCard("\u0632\u0628\u0627\u0646\u200c\u0647\u0627\u06cc \u0641\u0639\u0627\u0644", summary.enabled_languages ?? '—')}
      ${translationMetricCard("\u0632\u0628\u0627\u0646\u200c\u0647\u0627\u06cc \u0622\u0645\u0627\u062f\u0647", summary.warm_languages ?? '—')}
      ${translationMetricCard("\u0632\u0628\u0627\u0646\u200c\u0647\u0627\u06cc \u0646\u06cc\u0627\u0632\u0645\u0646\u062f \u0628\u0631\u0631\u0633\u06cc", summary.pending_languages ?? '—')}
      ${translationMetricCard("\u0632\u0628\u0627\u0646\u200c\u0647\u0627\u06cc \u062f\u0631 \u0642\u0631\u0646\u0637\u06cc\u0646\u0647", summary.quarantined_languages ?? '—')}
      ${translationMetricCard("\u06a9\u0644\u06cc\u062f\u0647\u0627\u06cc \u0645\u0646\u0628\u0639", dashboard.source_count ?? '—', dashboard.catalog_version ? `v${dashboard.catalog_version}` : '')}
    </div>
    <div class="card" style="margin-bottom:18px"><div class="card-head"><h3>${T("\u0627\u0631\u0627\u0626\u0647\u200c\u062f\u0647\u0646\u062f\u06af\u0627\u0646")}</h3><span class="chip mono">${providers.filter(x => x.configured).length}/${providers.length} ${T("\u0622\u0645\u0627\u062f\u0647")}</span></div><div class="chip-row">${providers.length ? providers.map(x => `<span class="chip">${esc(x.name)} · ${x.configured ? T("\u0622\u0645\u0627\u062f\u0647") : T("\u0641\u0639\u0627\u0644 \u0646\u06cc\u0633\u062a")}</span>`).join('') : `<span class="card-sub">${T("\u0647\u06cc\u0686 \u0633\u0631\u0648\u06cc\u0633 \u062a\u0631\u062c\u0645\u0647\u200c\u0627\u06cc \u062a\u0646\u0638\u06cc\u0645 \u0646\u0634\u062f\u0647 \u0627\u0633\u062a.")}</span>`}</div></div>` : ''}
    <div class="card"><div class="table-wrap"><table><thead><tr><th>${T("\u0632\u0628\u0627\u0646")}</th><th>${T("\u06a9\u062f")}</th><th>${T("\u062c\u0647\u062a")}</th><th>${T("\u0648\u0636\u0639\u06cc\u062a")}</th><th>${T("\u0633\u0644\u0627\u0645\u062a \u062a\u0631\u062c\u0645\u0647")}</th><th>${T("\u0639\u0645\u0644\u06cc\u0627\u062a")}</th></tr></thead><tbody>
      ${rows.map(x => {
        const h = healthByCode[x.code] || {};
        const status = x.enabled ? `<span class="badge badge-approved">${T("\u0641\u0639\u0627\u0644")}</span>` : `<span class="badge">${T("\u063a\u06cc\u0631\u0641\u0639\u0627\u0644")}</span>`;
        const isBuiltin = (x.code === 'fa' || x.code === 'en');
        const action = isBuiltin ? `<span class="muted">${T("\u067e\u06cc\u0634\u200c\u0641\u0631\u0636")}</span>` : (x.enabled ? `<button class="btn btn-sm" data-lang-disable="${esc(x.code)}">${T("\u063a\u06cc\u0631\u0641\u0639\u0627\u0644\u200c\u0633\u0627\u0632\u06cc")}</button>` : `<button class="btn btn-sm btn-primary" data-lang-enable="${esc(x.code)}">${T("\u0641\u0639\u0627\u0644\u200c\u0633\u0627\u0632\u06cc \u062e\u0648\u062f\u06a9\u0627\u0631")}</button>`);
        const logBtn = isBuiltin ? '' : ` <button class="btn btn-sm" data-lang-log="${esc(x.code)}" title="${T('\u0644\u0627\u06af \u0632\u0646\u062f\u0647 \u062a\u0631\u062c\u0645\u0647')}">${T('\u0644\u0627\u06af \u0632\u0646\u062f\u0647')}</button>`;
        return `<tr><td>${esc(`${x.flag || ''} ${x.native_name || x.name}`)}</td><td class="mono">${esc(x.code)}</td><td>${x.rtl ? 'RTL' : 'LTR'}</td><td>${status}</td><td>${translationHealthBadge(h)}</td><td>${action}${logBtn}</td></tr>`;
      }).join('')}
    </tbody></table></div></div>`);
}

// لاگ زنده‌ی ترجمه: هر بار با فاصله‌ی کوتاه از سرور می‌پرسد چه خط‌های جدیدی
// اضافه شده (since=آخرین seq)، تا وقتی running=false برگردد و چند بار دیگر
// برای اطمینان از دریافت آخرین خط‌ها.
function openTranslationLogModal(code, label) {
  let since = 0, timer = null, stopped = false, idleTicks = 0;
  const body = openModal(`${settingsUiText('\u0644\u0627\u06af \u0632\u0646\u062f\u0647 \u062a\u0631\u062c\u0645\u0647')} — ${esc(label || code)}`, `
    <div id="tlog-bar" style="height:8px;border-radius:20px;background:var(--border-soft);overflow:hidden;margin-bottom:10px">
      <div id="tlog-bar-fill" style="height:100%;width:0%;background:var(--green,#22c55e);transition:width .3s"></div>
    </div>
    <div id="tlog-summary" class="card-sub" style="margin-bottom:10px">${settingsUiText('\u062f\u0631 \u062d\u0627\u0644 \u0627\u062a\u0635\u0627\u0644...')}</div>
    <div id="tlog-lines" class="mono" style="max-height:340px;overflow:auto;background:var(--bg,#0b0f14);color:#c8f0d0;border-radius:10px;padding:10px 12px;font-size:12.5px;line-height:1.9;direction:ltr;text-align:left"></div>
  `, (bodyEl, close) => {
    bodyEl.closest('.modal-backdrop').addEventListener('click', e => {
      if (e.target.classList.contains('modal-backdrop')) { stopped = true; clearInterval(timer); }
    });
    const linesEl = bodyEl.querySelector('#tlog-lines');
    const fillEl = bodyEl.querySelector('#tlog-bar-fill');
    const sumEl = bodyEl.querySelector('#tlog-summary');
    const levelColor = { error: '#ff6b6b', warn: '#f5c26b', done: '#7fd8a0', info: '#c8f0d0' };
    const tick = async () => {
      if (stopped) return;
      let data;
      try { data = await apiGet(`/i18n/logs/${encodeURIComponent(code)}?since=${since}`); }
      catch (e) { return; }
      if (data.entries && data.entries.length) {
        const atBottom = linesEl.scrollTop + linesEl.clientHeight >= linesEl.scrollHeight - 8;
        for (const e of data.entries) {
          since = Math.max(since, e.seq);
          const div = document.createElement('div');
          div.style.color = levelColor[e.level] || levelColor.info;
          const t = new Date(e.ts * 1000).toLocaleTimeString('fa-IR');
          div.textContent = `[${t}] ${e.message}`;
          linesEl.appendChild(div);
        }
        if (atBottom) linesEl.scrollTop = linesEl.scrollHeight;
      }
      const total = data.total || 0;
      const pct = total ? Math.min(100, Math.round((data.done / total) * 100)) : (data.running ? 0 : 100);
      fillEl.style.width = pct + '%';
      sumEl.textContent = total
        ? `${data.done} / ${total} — ${data.running ? settingsUiText('\u062f\u0631 \u062d\u0627\u0644 \u0627\u0646\u062c\u0627\u0645') : settingsUiText('\u067e\u0627\u06cc\u0627\u0646 \u06cc\u0627\u0641\u062a')}`
        : (data.running ? settingsUiText('\u062f\u0631 \u062d\u0627\u0644 \u0634\u0631\u0648\u0639...') : settingsUiText('\u0647\u06cc\u0686 \u0639\u0645\u0644\u06cc\u0627\u062a\u06cc \u062f\u0631 \u062c\u0631\u06cc\u0627\u0646 \u0646\u06cc\u0633\u062a.'));
      if (!data.running) {
        idleTicks++;
        if (idleTicks > 2) { clearInterval(timer); }
      } else {
        idleTicks = 0;
      }
    };
    tick();
    timer = setInterval(tick, 900);
  });
  return body;
}

document.addEventListener('click', async e => {
  const en = e.target.closest('[data-lang-enable]');
  const dis = e.target.closest('[data-lang-disable]');
  const logBtn = e.target.closest('[data-lang-log]');
  if (logBtn) { openTranslationLogModal(logBtn.dataset.langLog); return; }
  if (!en && !dis) return;
  const code = (en || dis).dataset.langEnable || (en || dis).dataset.langDisable;
  (en || dis).disabled = true;
  if (en) openTranslationLogModal(code); // درخواست فعال‌سازی تا پایان ترجمه صبر می‌کند؛ لاگ زنده همزمان با آن باز می‌شود
  try {
    const result = await apiPost(`/languages/${encodeURIComponent(code)}/${en ? 'enable' : 'disable'}`);
    toast(en ? `${settingsUiText('\u0632\u0628\u0627\u0646 \u0641\u0639\u0627\u0644 \u0634\u062f')} — ${result.translated || 0} ${settingsUiText('\u062a\u0631\u062c\u0645\u0647 \u062e\u0648\u062f\u06a9\u0627\u0631 \u0633\u0627\u062e\u062a\u0647 \u0634\u062f')}.` : `${settingsUiText('\u0632\u0628\u0627\u0646 \u063a\u06cc\u0631\u0641\u0639\u0627\u0644 \u0634\u062f')}.`);
    await renderLanguages();
  } catch (err) { handleErr(err); (en || dis).disabled = false; }
});



async function renderSubscriptionPageSettings() {
  const s = await apiGet('/settings');
  const val = k => s[k] ?? '';
  const field = (key, label, type='text', hint='') => `
    <label class="field"><span>${label}</span>
      <input class="input" data-key="${key}" data-type="${type}" type="${type === 'number' ? 'number' : 'text'}" value="${esc(val(key))}">
      ${hint ? `<small class="card-sub">${hint}</small>` : ''}
    </label>`;
  const area = (key, label, rows=3) => `<label class="field"><span>${label}</span><textarea class="input" data-key="${key}" data-type="textarea" rows="${rows}">${esc(val(key))}</textarea></label>`;
  const select = (key,label,options) => `<label class="field"><span>${label}</span><select class="input" data-key="${key}" data-type="select">${options.map(([v,l])=>`<option value="${v}" ${String(val(key))===v?'selected':''}>${l}</option>`).join('')}</select></label>`;
  const toggle = (key,label) => `<label class="field field-row"><span>${label}</span><button type="button" class="switch" data-key="${key}" data-on="${val(key)==='1'?'1':'0'}"><i></i></button></label>`;
  const colorField = (key,label,def) => {
    const v = normalizeHex(val(key)) || def;
    return `<div class="field color-field"><span>${label} (HEX)</span>
      <div class="color-row">
        <input type="color" class="color-native" data-color-for="${key}" value="${v.toLowerCase()}" aria-label="${label}">
        <input class="input" data-key="${key}" data-type="text" data-default="${def}" dir="ltr" maxlength="7" inputmode="text" autocomplete="off" spellcheck="false" value="${esc(val(key) || def)}">
      </div></div>`;
  };
  const paletteHtml = `<div class="palette-wrap"><span class="card-sub">پالت‌های آماده (با یک کلیک رنگ اصلی و مکمل ست می‌شوند)</span>
    <div class="palette-grid">${SUB_PAGE_PALETTES.map(([n,a,b]) => `<button type="button" class="palette-chip" data-a="${a}" data-b="${b}" title="${esc(n)}"><i style="background:linear-gradient(135deg,${a},${b})"></i><span>${esc(n)}</span></button>`).join('')}</div></div>`;
  setContent(`
    <div class="hero"><div><h2>تنظیمات صفحه اشتراک</h2><p class="card-sub">مدیریت کامل ظاهر، محتوا و رفتار لینک ساب اختصاصی</p></div></div>
    <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>🔌 وضعیت و آدرس سرویس</h3></div><div class="form-grid">
      ${select('dsub_enabled','فعال بودن لینک ساب اختصاصی',[['0','غیرفعال'],['1','فعال']])}
      ${select('dsub_web_page','نمایش صفحه وب در مرورگر',[['0','غیرفعال'],['1','فعال']])}
      ${field('dsub_base_url','آدرس پایه سرور ساب','text','خالی = استفاده از مقدار تنظیم‌شده در فایل .env')}
    </div></div>
    <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>🎨 ظاهر و قالب صفحه</h3></div>
      <div class="form-grid">
        ${select('dsub_style','سبک نمایش',[['minimal','مینیمال'],['modern','مدرن'],['glass','شیشه‌ای'],['cyberpunk','سایبرپانک'],['classic','کلاسیک']])}
        ${select('dsub_theme','حالت رنگ',[['auto','خودکار'],['light','روشن'],['dark','تیره']])}
        ${colorField('dsub_accent_color','رنگ اصلی','#6366F1')}
        ${colorField('dsub_secondary_color','رنگ مکمل','#06B6D4')}
        ${select('dsub_card_style','استایل کارت‌ها',[['rounded','گرد'],['soft','ملایم'],['sharp','گوشه‌دار']])}
        ${select('dsub_density','تراکم محتوا',[['comfortable','راحت'],['compact','فشرده']])}
      </div>
      ${paletteHtml}
      <div class="card-sub">پیش‌نمایش زنده (با هر تغییر، بدون ذخیره به‌روز می‌شود)</div>
      <iframe id="sub-page-preview-frame" src="/api/settings/sub-page-preview?preview=1" title="پیش‌نمایش صفحه اشتراک" style="width:100%;height:560px;border:1px solid var(--border);border-radius:14px;background:#fff"></iframe>
      <button class="btn btn-ghost btn-sm" id="sub-page-preview-open" type="button">باز کردن پیش‌نمایش در تب جدید</button>
    </div>
    <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>🏷️ برندینگ و اطلاعات</h3></div><div class="form-grid">
      ${field('dsub_brand','نام برند صفحه')}${field('dsub_logo_url','آدرس لوگو (HTTPS)')}
      ${area('dsub_notice','اعلان بالای صفحه')}${field('dsub_support_url','لینک پشتیبانی')}
      ${field('dsub_footer_text','متن پایین صفحه')}
    </div></div>
    <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>🧩 بخش‌های قابل نمایش</h3></div><div class="form-grid">
      ${toggle('dsub_show_configs','نمایش کانفیگ‌ها')}${toggle('dsub_show_chart','نمایش نمودار مصرف')}
      ${toggle('dsub_show_qr','نمایش QR')}${toggle('dsub_show_apps','نمایش برنامه‌ها')}
      ${toggle('dsub_show_faq','نمایش راهنمای عیب‌یابی')}
    </div></div>
    <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>⚙️ تنظیمات پیشرفته</h3></div><div class="form-grid">
      ${field('dsub_profile_title','عنوان پروفایل داخل اپ')}
      ${field('dsub_update_interval','فاصله بروزرسانی (ساعت)','number')}
      ${select('dsub_info_line','خط اول ساب',[['0','خاموش'],['1','روشن']])}
      ${field('dsub_info_line_text','متن خط اول ساب')}
      ${toggle('dsub_expired_placeholder','نمایش کانفیگ نمایشی برای سرویس پایان‌یافته')}
      ${area('dsub_expired_text','متن سرویس منقضی')}${area('dsub_limited_text','متن اتمام حجم')}
      ${field('dsub_cache_ttl','مدت کش (ثانیه)','number')}
      ${toggle('dsub_usage_sampling','ثبت نمونه مصرف')}${toggle('dsub_log_enabled','ثبت لاگ دسترسی')}
    </div></div>
    <div class="card" style="margin-bottom:16px"><div class="card-head"><h3>📱 برنامه‌ها، سوالات و قالب HTML</h3></div>
      <div class="form-grid">
        ${area('dsub_faq','سوالات متداول (هر خط: سوال | جواب)',5)}
        ${area('dsub_custom_apps','برنامه‌های سفارشی (هر خط: platform|name|description|add_prefix|download_url)',5)}
        ${field('dsub_apps_hidden','برنامه‌های مخفی (مثلاً ios:Streisand,android:Hiddify)')}
        ${field('dsub_apps_rec','برنامه پیشنهادی هر سیستم‌عامل (مثلاً ios:Hiddify,android:v2rayNG)')}
        ${toggle('dsub_custom_template_enabled','استفاده از قالب HTML اختصاصی')}
        ${area('dsub_custom_template','کد HTML قالب اختصاصی',12)}
      </div>
      <div class="form-grid" style="margin-top:10px">
        <button class="btn btn-ghost sub-tpl-guide-btn" type="button">راهنمای قالب</button>
        <button class="btn btn-ghost sub-tpl-default-btn" type="button">پر کردن قالب پیش‌فرض</button>
        <label class="btn btn-ghost" style="cursor:pointer">آپلود فایل HTML<input class="sub-tpl-upload-input" type="file" accept=".html,text/html" hidden></label>
      </div>
    </div>
    <div class="settings-save-bar"><button class="btn btn-primary btn-block" id="subscription-page-save">ذخیره تنظیمات صفحه اشتراک</button></div>
  `);
  const root = content();
  bindSettingsGroupEvents(root);
  bindSubPageColorPickers(root);
  bindSubscriptionLivePreview(root);
  $('#subscription-page-save',root).addEventListener('click',()=>collectAndSaveSettings(root,$('#subscription-page-save',root)));
  $$('.sub-tpl-guide-btn',root).forEach(btn=>btn.addEventListener('click',()=>openModal('راهنمای قالب اختصاصی',_subTemplateGuideHtml(),null,{wide:true})));
  $$('.sub-tpl-default-btn',root).forEach(btn=>btn.addEventListener('click',async()=>{
    try { const r=await fetch('/api/settings/sub-page-template/default',{credentials:'same-origin'}); if(!r.ok) throw new Error('HTTP '+r.status); $('textarea[data-key="dsub_custom_template"]',root).value=await r.text(); toast('قالب پیش‌فرض بارگذاری شد؛ ذخیره را بزن.'); } catch(e){handleErr(e);}
  }));
  $$('.sub-tpl-upload-input',root).forEach(input=>input.addEventListener('change',async()=>{
    const file=input.files&&input.files[0]; input.value=''; if(!file)return;
    if(file.size>400000){toast('حجم فایل بیش از ۴۰۰ کیلوبایت است.');return;}
    try{const t=await file.text();if(!t.includes('__DATA__')){toast('قالب باید شامل __DATA__ باشد.');return;} $('textarea[data-key="dsub_custom_template"]',root).value=t;toast('قالب بارگذاری شد؛ ذخیره را بزن.');}catch(e){handleErr(e);}
  }));
}

async function renderSettings() {
  if (!SETTINGS_TABS.some(t => t.key === settingsActiveTab)) settingsActiveTab = 'content';
  const [settings, rate, mainMenuDisplay, gateways, methods, c2cCards, c2cWebhook, c2cInvoices, mobileTokens] = await Promise.all([
    apiGet('/settings'),
    apiGet('/exchange-rate').catch(e => ({ ok: false, rate: null, source: null, updated_at: null, error: e.message })),
    apiGet('/settings/main-menu-display').catch(() => ({ reply_enabled: true, inline_enabled: false, columns: 1 })),
    apiGet('/gateways').catch(() => []),
    apiGet('/payment-methods').catch(() => []),
    apiGet('/card-to-card/cards').catch(() => []),
    apiGet('/settings/card-to-card').catch(() => ({})),
    apiGet('/card-to-card/invoices?status=pending').catch(() => []),
    apiGet('/app/tokens').catch(() => []),
  ]);
  const pay = { gateways, methods, c2cCards, c2cWebhook, c2cInvoices };
  if (loadTheme().theme === 'brutalist') { renderSettingsBrutalist(settings, rate, mainMenuDisplay, pay, mobileTokens); return; }
  if (loadTheme().theme === 'bento') { renderSettingsBento(settings, rate, mainMenuDisplay, pay, mobileTokens); return; }
  setContent(`
    ${settingsTabsHtml()}

    <div data-settings-tab="content" style="${settingsActiveTab === 'content' ? '' : 'display:none'}">
      ${mainMenuDisplayCardHtml(mainMenuDisplay)}
    </div>

    <div data-settings-tab="payment" style="${settingsActiveTab === 'payment' ? '' : 'display:none'}">
      ${rateCardHtml(rate)}
      ${paymentExtrasHtml(pay)}
    </div>

    <div data-settings-tab="mobile_app" style="${settingsActiveTab === 'mobile_app' ? '' : 'display:none'}">
      ${mobileAppCardHtml(mobileTokens)}
    </div>

    ${extraSettingsTabHtml()}

    ${renderSettingsGroups(settings)}

    <div class="settings-save-bar">
      <button class="btn btn-primary btn-block" id="settings-save">${settingsUiText('ذخیره تغییرات')}</button>
    </div>
  `);
  $$('#settings-tabs-nav .tab-btn', content()).forEach(btn => btn.addEventListener('click', () => switchSettingsTab(btn.dataset.tab, content())));
  bindSettingsGroupEvents(content());
  bindSubscriptionLivePreview(content());
  syncExtraSettingsTab(content());
  bindPaymentExtrasEvents(content(), pay);
  bindMobileAppEvents(content(), renderSettings);
  $('#mm-display-save').addEventListener('click', saveMainMenuDisplay);
  $('#settings-save').addEventListener('click', () => collectAndSaveSettings(content(), $('#settings-save')));
  $('#rate-refresh').addEventListener('click', async () => {
    const btn = $('#rate-refresh');
    btn.disabled = true; btn.textContent = 'در حال دریافت...';
    try {
      await apiPost('/exchange-rate/refresh');
      toast('نرخ بروزرسانی شد.');
    } catch (e) {
      handleErr(e);
    } finally {
      renderSettings();
    }
  });
}

/* ----------------------------------------------------- settings: bento -- */
// تب افقی به سگمنت کپسولی اپلی تبدیل می‌شه؛ بدنه‌ی فرم همون منطق قبلیه،
// فقط با آکاردئون/سوییچ/سواچ گردتر (از طریق CSS اسکوپ‌شده به تم bento).

const SUB_PAGE_PALETTES = [
  ['ایندیگو و فیروزه‌ای', '#6366F1', '#06B6D4'], ['اقیانوس', '#0EA5E9', '#2563EB'], ['زمرد', '#10B981', '#059669'],
  ['غروب', '#F97316', '#EC4899'], ['گل‌رز', '#F43F5E', '#FB7185'], ['بنفش سلطنتی', '#8B5CF6', '#D946EF'],
  ['نئون سایبر', '#22D3EE', '#A3E635'], ['طلایی', '#F59E0B', '#EF4444'], ['جنگل', '#16A34A', '#65A30D'],
  ['آسمان شب', '#3B82F6', '#8B5CF6'], ['خاکستری مدرن', '#475569', '#94A3B8'], ['تلگرام', '#229ED9', '#2AABEE'],
];

function normalizeHex(v) {
  let h = String(v || '').trim().replace(/^#/, '');
  if (/^[0-9a-fA-F]{3}$/.test(h)) h = h.split('').map(c => c + c).join('');
  return /^[0-9a-fA-F]{6}$/.test(h) ? '#' + h.toUpperCase() : '';
}

function bindSubPageColorPickers(root) {
  const fire = el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); };
  const setPair = (key, hex) => {
    const txt = $(`input[data-key="${key}"]`, root), nat = $(`input[data-color-for="${key}"]`, root);
    if (!txt) return;
    txt.value = hex; txt.classList.remove('invalid');
    if (nat) nat.value = hex.toLowerCase();
    fire(txt);
  };
  $$('input[data-color-for]', root).forEach(nat => {
    const key = nat.dataset.colorFor, txt = $(`input[data-key="${key}"]`, root);
    nat.addEventListener('input', () => setPair(key, nat.value.toUpperCase()));
    txt.addEventListener('input', () => {
      const h = normalizeHex(txt.value);
      txt.classList.toggle('invalid', !!txt.value.trim() && !h);
      if (h) nat.value = h.toLowerCase();
    });
    txt.addEventListener('blur', () => { const h = normalizeHex(txt.value); if (h) { txt.value = h; } else if (!txt.value.trim()) { txt.value = txt.dataset.default || ''; } });
  });
  $$('.palette-chip', root).forEach(chip => chip.addEventListener('click', () => {
    setPair('dsub_accent_color', chip.dataset.a); setPair('dsub_secondary_color', chip.dataset.b);
    $$('.palette-chip', root).forEach(c => c.classList.toggle('active', c === chip));
  }));
}

function bindSubscriptionLivePreview(root) {
  const frame = $('#sub-page-preview-frame', root);
  if (!frame) return;
  const get = key => {
    const el = $(`[data-key="${key}"]`, root);
    if (!el) return '';
    if (el.classList.contains('switch')) return el.dataset.on === '1' ? '1' : '0';
    if (el.type === 'checkbox') return el.checked ? '1' : '0';
    if (key === 'dsub_accent_color' || key === 'dsub_secondary_color') return normalizeHex(el.value);
    return el.value ?? '';
  };
  const payload = () => ({
    brand: get('dsub_brand') || get('store_name') || 'ShopVPN',
    logo: get('dsub_logo_url') || '',
    notice: get('dsub_notice'),
    support: get('dsub_support_url') || '',
    footer: get('dsub_footer_text'),
    theme: get('dsub_theme') || 'auto', style: get('dsub_style') || 'minimal', accent: get('dsub_accent_color') || '#6366F1', secondary: get('dsub_secondary_color') || '#06B6D4', cardStyle: get('dsub_card_style') || 'rounded', density: get('dsub_density') || 'comfortable',
    show: {
      configs: get('dsub_show_configs') !== '0', chart: get('dsub_show_chart') !== '0',
      qr: get('dsub_show_qr') !== '0', apps: get('dsub_show_apps') !== '0', faq: get('dsub_show_faq') !== '0'
    }
  });
  let timer = null;
  const sendNow = () => { try { frame.contentWindow.postMessage({ type: 'shopvpn-sub-page-preview', payload: payload() }, '*'); } catch (e) {} };
  const send = () => { clearTimeout(timer); timer = setTimeout(sendNow, 40); };
  frame.addEventListener('load', sendNow);
  const openBtn = $('#sub-page-preview-open', root);
  if (openBtn) openBtn.onclick = () => window.open('/api/settings/sub-page-preview?preview=1', '_blank', 'noopener');
  $$('[data-key]', root).forEach(el => {
    const key = el.dataset.key || '';
    if (key.startsWith('dsub_') || key === 'store_name') {
      el.addEventListener('input', send); el.addEventListener('change', send);
      // سوییچ‌ها رویداد input/change نمی‌دهند؛ تغییرشان را با کلیک می‌گیریم (بعد از جابه‌جایی data-on)
      if (el.classList.contains('switch')) el.addEventListener('click', () => setTimeout(send, 0));
    }
  });
  sendNow();
}

function renderSettingsBento(settings, rate, mainMenuDisplay, pay, mobileTokens) {
  setContent(`
    <div class="bn-hero"><div><h2>${settingsUiText('تنظیمات')}</h2><p>${settingsUiText('پیکربندی محتوا، پرداخت، کمپین و سرویس‌های ربات')}</p></div></div>
    <div class="bn-seg" id="settings-tabs-nav" style="margin-bottom:16px">
      ${SETTINGS_TABS.map(t => `<button type="button" class="bn-seg-btn ${t.key === settingsActiveTab ? 'active' : ''}" data-tab="${t.key}">${settingsUiText(t.label)}</button>`).join('')}
    </div>
    <div data-settings-tab="content" style="${settingsActiveTab === 'content' ? '' : 'display:none'}">
      ${mainMenuDisplayCardHtml(mainMenuDisplay)}
    </div>
    <div data-settings-tab="payment" style="${settingsActiveTab === 'payment' ? '' : 'display:none'}">
      ${rateCardHtml(rate)}
      ${paymentExtrasHtml(pay)}
    </div>
    <div data-settings-tab="mobile_app" style="${settingsActiveTab === 'mobile_app' ? '' : 'display:none'}">
      ${mobileAppCardHtml(mobileTokens)}
    </div>
    ${extraSettingsTabHtml()}
    ${renderSettingsGroups(settings)}
    <div class="settings-save-bar">
      <button class="bn-btn bn-btn-ok btn-block" id="settings-save" style="width:100%;padding:12px">${settingsUiText('ذخیره تغییرات')}</button>
    </div>
  `);
  $$('#settings-tabs-nav .bn-seg-btn', content()).forEach(btn => btn.addEventListener('click', () => switchSettingsTab(btn.dataset.tab, content())));
  bindSettingsGroupEvents(content());
  bindSubscriptionLivePreview(content());
  syncExtraSettingsTab(content());
  bindPaymentExtrasEvents(content(), pay);
  bindMobileAppEvents(content(), renderSettings);
  $('#mm-display-save').addEventListener('click', saveMainMenuDisplay);
  $('#settings-save').addEventListener('click', () => collectAndSaveSettings(content(), $('#settings-save')));
  $('#rate-refresh').addEventListener('click', async () => {
    const btn = $('#rate-refresh');
    btn.disabled = true; btn.textContent = 'در حال دریافت...';
    try {
      await apiPost('/exchange-rate/refresh');
      toast('نرخ بروزرسانی شد.');
    } catch (e) {
      handleErr(e);
    } finally {
      renderSettings();
    }
  });
}


/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

/* ------------------------------------------------- settings: brutalist -- */
// ناوبری از تب افقی به سایدبار عمودی تبدیل می‌شه (مثل داشبورد ادمین‌های
// واقعی) — بدنه‌ی فرم‌ها با همون منطق قبلی، فقط قاب/سوییچ/سواچ برutalist.
function renderSettingsBrutalist(settings, rate, mainMenuDisplay, pay, mobileTokens) {
  setContent(`
    <div class="bru-hero"><h2>${settingsUiText('تنظیمات')}</h2><p>${settingsUiText('پیکربندی محتوا، پرداخت، کمپین و سرویس‌های ربات')}</p></div>
    <div class="bru-settings-layout">
      <nav class="bru-settings-nav" id="settings-tabs-nav">
        ${SETTINGS_TABS.map(t => `<button type="button" class="bru-seg-btn ${t.key === settingsActiveTab ? 'active' : ''}" data-tab="${t.key}">${t.label}</button>`).join('')}
      </nav>
      <div class="bru-settings-content">
        <div data-settings-tab="content" style="${settingsActiveTab === 'content' ? '' : 'display:none'}">
          ${mainMenuDisplayCardHtml(mainMenuDisplay)}
        </div>
        <div data-settings-tab="payment" style="${settingsActiveTab === 'payment' ? '' : 'display:none'}">
          ${rateCardHtml(rate)}
          ${paymentExtrasHtml(pay)}
        </div>
        <div data-settings-tab="mobile_app" style="${settingsActiveTab === 'mobile_app' ? '' : 'display:none'}">
          ${mobileAppCardHtml(mobileTokens)}
        </div>
        ${extraSettingsTabHtml()}
        ${renderSettingsGroups(settings)}
        <div class="settings-save-bar">
          <button class="bru-stamp bru-stamp-ok btn-block" id="settings-save" style="--r:-2deg;width:100%">ذخیره تغییرات</button>
        </div>
      </div>
    </div>
  `);
  $$('#settings-tabs-nav .bru-seg-btn', content()).forEach(btn => btn.addEventListener('click', () => switchSettingsTab(btn.dataset.tab, content())));
  bindSettingsGroupEvents(content());
  bindSubscriptionLivePreview(content());
  syncExtraSettingsTab(content());
  bindPaymentExtrasEvents(content(), pay);
  bindMobileAppEvents(content(), renderSettings);
  $('#mm-display-save').addEventListener('click', saveMainMenuDisplay);
  $('#settings-save').addEventListener('click', () => collectAndSaveSettings(content(), $('#settings-save')));
  $('#rate-refresh').addEventListener('click', async () => {
    const btn = $('#rate-refresh');
    btn.disabled = true; btn.textContent = 'در حال دریافت...';
    try {
      await apiPost('/exchange-rate/refresh');
      toast('نرخ بروزرسانی شد.');
    } catch (e) {
      handleErr(e);
    } finally {
      renderSettings();
    }
  });
}

/* ================================================================ logs === */
let logsPage = 1;
let logsFilter = { action: '', record_type: '', record_id: '' };
const RECORD_TYPE_LABEL = {
  order: 'سفارش', topup: 'شارژ کیف پول', user: 'کاربر', category: 'دسته‌بندی', product: 'محصول',
  config: 'کانفیگ', discount: 'کد تخفیف', ticket: 'تیکت', reseller: 'نماینده', panel: 'پنل VPN',
  setting: 'تنظیم', webadmin: 'ادمین پنل',
};
const ACTION_LABEL = {
  admin_add: 'افزودن ادمین', admin_remove: 'حذف ادمین', admin_role_change: 'تغییر نقش ادمین',
  backup_create: 'ساخت بکاپ', backup_restore: 'بازیابی بکاپ', factory_reset: 'بازگشت به حالت کارخانه', broadcast: 'پیام همگانی',
  card_change: 'تغییر شماره کارت', category_add: 'افزودن دسته‌بندی', category_delete: 'حذف دسته‌بندی',
  category_edit: 'ویرایش دسته‌بندی', category_toggle: 'فعال/غیرفعال کردن دسته‌بندی',
  config_delete: 'حذف کانفیگ', configs_add: 'افزودن کانفیگ', custom_config_approve: 'تایید کانفیگ سفارشی',
  custom_config_toggle: 'فعال/غیرفعال کردن کانفیگ سفارشی', discount_add: 'افزودن کد تخفیف',
  discount_delete: 'حذف کد تخفیف', discount_toggle: 'فعال/غیرفعال کردن کد تخفیف',
  exchange_rate_refresh: 'بروزرسانی نرخ ارز', menu_order_change: 'تغییر ترتیب منو',
  main_menu_display_change: 'تغییر نمایش منوی اصلی',
  order_approve: 'تایید سفارش', order_reject: 'رد سفارش', order_fake_receipt: 'فیش فیک + بلاک کاربر', orphan_db_file_delete: 'حذف فایل بلااستفاده',
  panel_add: 'افزودن پنل VPN', panel_delete: 'حذف پنل VPN', panel_server_add: 'افزودن سرور پنل',
  panel_server_delete: 'حذف سرور پنل', panel_server_template_update: 'ویرایش قالب سرور پنل',
  panel_server_usage_toggle: 'فعال/غیرفعال کردن مصرف سرور', plisio_key_change: 'تغییر کلید Plisio',
  abangateway_key_change: 'تغییر کلید آبان گیت‌وی',
  blupal_key_change: 'تغییر کلید بلوپال',
  extra_gateway_setting: 'تغییر تنظیمات درگاه پرداخت',
  extra_gateway_toggle: 'تغییر وضعیت درگاه پرداخت',
  pricing_tier_add: 'افزودن رده قیمتی', pricing_tier_delete: 'حذف رده قیمتی', product_add: 'افزودن محصول',
  product_delete: 'حذف محصول', product_edit: 'ویرایش محصول', product_price_edit: 'ویرایش قیمت محصول',
  product_server_edit: 'تغییر پنل/اینباند محصول', product_volume_edit: 'تغییر حجم محصول',
  product_toggle: 'فعال/غیرفعال کردن محصول', reseller_credit_adjust: 'تغییر اعتبار نماینده', reseller_credit_limit: 'تغییر سقف اعتبار پس‌پرداخت', order_survey_send: 'ارسال نظرسنجی سفارش',
  reseller_credit_toggle: 'فعال/غیرفعال کردن اعتبار نماینده', reseller_orphan_purge: 'پاکسازی نمایندگان بلااستفاده',
  reseller_panel_set: 'تنظیم پنل نماینده', reseller_request_admin_cancel: 'لغو درخواست نمایندگی',
  reseller_request_payment_approve: 'تایید پرداخت نمایندگی', reseller_request_quote: 'ثبت مبلغ درخواست نمایندگی',
  reseller_request_reject: 'رد درخواست نمایندگی', reseller_status_toggle: 'فعال/غیرفعال کردن نماینده',
  reset_test_configs: 'ریست کانفیگ‌های تست', setting_change: 'تغییر تنظیمات', support_reply: 'پاسخ پشتیبانی',
  ticket_close: 'بستن تیکت', ticket_reply: 'پاسخ تیکت', topup_approve: 'تایید شارژ کیف پول',
  topup_reject: 'رد شارژ کیف پول', user_block: 'مسدودسازی کاربر', user_unblock: 'رفع مسدودی کاربر',
  user_message: 'پیام مستقیم به کاربر',
  wallet_adjust: 'تغییر موجودی کیف پول', web_admin_active: 'فعال/غیرفعال کردن ادمین پنل',
  web_admin_add: 'افزودن ادمین پنل', web_admin_delete: 'حذف ادمین پنل', web_admin_permissions: 'تغییر دسترسی‌های ادمین پنل',
};
function actionLabel(a) { return ACTION_LABEL[a] || esc(a); }
function goToLogsFor(recordType, recordId) {
  logsFilter = { action: '', record_type: recordType, record_id: String(recordId) };
  logsPage = 1;
  goTo('logs');
}
/* ---------------------------------------------------- bento helpers ---- */
// اجزای مشترک تم Bento (اپل): پیل رنگی برای وضعیت، آواتار دایره‌ای گرادیانی —
// دقیقاً همون زبان بصری ویجت‌های داشبورد (.bw / .w-*) که برای بقیه‌ی صفحات
// هم استفاده می‌شه تا کل پنل یکدست بمونه.
const BN_ACCENTS = ['w-blue', 'w-green', 'w-orange', 'w-pink', 'w-purple'];
function bnPill(label, kind) { return `<span class="bn-pill bn-pill-${kind}">${label}</span>`; }
function bnAvatar(ch, i) { return `<div class="bn-avatar ${BN_ACCENTS[i % BN_ACCENTS.length]}">${esc(ch)}</div>`; }

const GLASS_COLORS = ['#8B5CF6', '#22D3EE', '#34D399', '#FBBF24', '#FB7185', '#EC4899'];
function glPill(label, kind) { return `<span class="gl-pill gl-pill-${kind}">${label}</span>`; }
function glAvatar(ch, i) { return `<div class="gl-avatar" style="--c:${GLASS_COLORS[i % GLASS_COLORS.length]}">${esc(ch)}</div>`; }

const CYB_COLORS = ['#00FF9C', '#00E5FF', '#FF2E9A', '#C6FF00', '#FF2E5B'];
function cybPill(label, kind) { return `<span class="cyb-pill cyb-pill-${kind}">${label}</span>`; }
function cybAvatar(ch, i) { return `<div class="cyb-avatar" style="--c:${CYB_COLORS[i % CYB_COLORS.length]}">${esc(ch)}</div>`; }

const CLY_COLORS = ['#F97316', '#FB923C', '#FBBF24', '#10B981', '#EC4899', '#06B6D4'];
function clyPill(label, kind) { return `<span class="cly-pill cly-pill-${kind}">${label}</span>`; }
function clyAvatar(ch, i) { return `<div class="cly-avatar" style="--c:${CLY_COLORS[i % CLY_COLORS.length]}">${esc(ch)}</div>`; }

const PPR_COLORS = ['#111827', '#374151', '#065F46', '#92400E', '#991B1B', '#1F2937'];
function pprPill(label, kind) { return `<span class="ppr-pill ppr-pill-${kind}">${label}</span>`; }
function pprAvatar(ch, i) { return `<div class="ppr-avatar" style="--c:${PPR_COLORS[i % PPR_COLORS.length]}">${esc(ch)}</div>`; }

const OBK_COLORS = ['#0AFF6B', '#EDEDED', '#FFB800', '#FF3344'];
function obkPill(label, kind) { return `<span class="obk-pill obk-pill-${kind}">${label}</span>`; }
function obkAvatar(ch, i) { return `<div class="obk-avatar" style="--c:${OBK_COLORS[i % OBK_COLORS.length]}">${esc(ch)}</div>`; }

const WRP_COLORS = ['#7C5CFF', '#3FE0C0', '#FF6F91', '#9A93C9', '#5A3CFF'];
function wrpPill(label, kind) { return `<span class="wrp-pill wrp-pill-${kind}">${label}</span>`; }
function wrpAvatar(ch, i) { return `<div class="wrp-avatar" style="--c:${WRP_COLORS[i % WRP_COLORS.length]}">${esc(ch)}</div>`; }

function historyBtn(recordType, recordId) {
  return hasPerm('system')
    ? `<button class="btn btn-ghost btn-sm" data-history="${recordType}:${recordId}" title="تاریخچه">تاریخچه</button>` : '';
}
async function showRecordHistory(recordType, recordId) {
  const qs = new URLSearchParams({ page: 1, record_type: recordType, record_id: String(recordId) });
  const res = await apiGet(`/admin-logs?${qs.toString()}`);
  openModal(`تاریخچه ${RECORD_TYPE_LABEL[recordType] || esc(recordType)} #${esc(recordId)}`, `
    <div class="table-wrap" style="max-height:60vh;overflow-y:auto">
      <table><thead><tr><th>ادمین</th><th>عملیات</th><th>جزئیات</th><th>تاریخ</th></tr></thead>
      <tbody>${res.items.map(l => `<tr>
        <td class="mono">${l.admin_id}</td><td>${actionLabel(l.action)}</td>
        <td>${esc(l.details)}</td><td class="mono">${fmtDate(l.created_at)}</td>
      </tr>`).join('') || `<tr><td colspan="4" class="empty-state"><div class="icon">${svg('empty')}</div>لاگی ثبت نشده</td></tr>`}</tbody></table>
    </div>
    <button class="btn btn-block" id="rh-full-log" style="margin-top:14px">مشاهده کامل در لاگ سیستم</button>
  `, (body, close) => {
    $('#rh-full-log', body).addEventListener('click', () => { close(); goToLogsFor(recordType, recordId); });
  }, { wide: true });
}
async function renderLogs() {
  const actionsRes = await apiGet('/admin-logs/actions');
  const qs = new URLSearchParams({ page: logsPage });
  if (logsFilter.action) qs.set('action', logsFilter.action);
  if (logsFilter.record_type) qs.set('record_type', logsFilter.record_type);
  if (logsFilter.record_id) qs.set('record_id', logsFilter.record_id);
  const res = await apiGet(`/admin-logs?${qs.toString()}`);
  const pages = Math.max(Math.ceil(res.total / res.limit), 1);
  if (loadTheme().theme === 'brutalist') return renderLogsBrutalist(actionsRes, res, pages);
  if (loadTheme().theme === 'bento') return renderLogsBento(actionsRes, res, pages);
  setContent(`
    <div class="card" style="margin-bottom:14px">
      <div class="form-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
        <select class="input" id="lf-action">
          <option value="">همه‌ی عملیات</option>
          ${actionsRes.actions.map(a => `<option value="${a}" ${a === logsFilter.action ? 'selected' : ''}>${actionLabel(a)}</option>`).join('')}
        </select>
        <select class="input" id="lf-type">
          <option value="">همه‌ی رکوردها</option>
          ${Object.keys(RECORD_TYPE_LABEL).map(t => `<option value="${t}" ${t === logsFilter.record_type ? 'selected' : ''}>${RECORD_TYPE_LABEL[t]}</option>`).join('')}
        </select>
        <input class="input" id="lf-id" placeholder="شناسه رکورد (مثلاً آیدی سفارش)" value="${esc(logsFilter.record_id)}">
        <button class="btn btn-primary btn-sm" id="lf-apply">اعمال فیلتر</button>
        <button class="btn btn-sm" id="lf-clear">پاک‌کردن</button>
      </div>
    </div>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>ادمین</th><th>عملیات</th><th>رکورد</th><th>جزئیات</th><th>تاریخ</th></tr></thead>
      <tbody>${res.items.map(l => `<tr>
        <td class="mono">${l.admin_id}</td><td>${actionLabel(l.action)}</td>
        <td>${l.record_type ? `<span class="chip">${RECORD_TYPE_LABEL[l.record_type] || esc(l.record_type)} #${esc(l.record_id)}</span>` : '—'}</td>
        <td>${esc(l.details)}</td><td class="mono">${fmtDate(l.created_at)}</td>
      </tr>`).join('') || '<tr><td colspan="5" class="empty-state">لاگی ثبت نشده</td></tr>'}</tbody>
    </table></div>
    <div class="pager">${Array.from({ length: pages }, (_, i) => i + 1).map(p => `<button class="btn btn-sm ${p === logsPage ? 'btn-primary' : ''}" data-page="${p}">${p}</button>`).join('')}</div>
    </div>
  `);
  $$('[data-page]', content()).forEach(b => b.addEventListener('click', () => { logsPage = Number(b.dataset.page); renderLogs(); }));
  $('#lf-apply').addEventListener('click', () => {
    logsFilter = { action: $('#lf-action').value, record_type: $('#lf-type').value, record_id: $('#lf-id').value.trim() };
    logsPage = 1; renderLogs();
  });
  $('#lf-clear').addEventListener('click', () => { logsFilter = { action: '', record_type: '', record_id: '' }; logsPage = 1; renderLogs(); });
}

/* ------------------------------------------------------------- logs: bento */
function renderLogsBento(actionsRes, res, pages) {
  setContent(`
    <div class="bn-hero"><div><h2>لاگ سیستم</h2><p>${fmt(res.total)} رکورد ثبت‌شده</p></div></div>
    <div class="bn-card" style="margin-bottom:14px">
      <div class="form-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
        <select class="input" id="lf-action">
          <option value="">همه‌ی عملیات</option>
          ${actionsRes.actions.map(a => `<option value="${a}" ${a === logsFilter.action ? 'selected' : ''}>${actionLabel(a)}</option>`).join('')}
        </select>
        <select class="input" id="lf-type">
          <option value="">همه‌ی رکوردها</option>
          ${Object.keys(RECORD_TYPE_LABEL).map(t => `<option value="${t}" ${t === logsFilter.record_type ? 'selected' : ''}>${RECORD_TYPE_LABEL[t]}</option>`).join('')}
        </select>
        <input class="input" id="lf-id" placeholder="شناسه رکورد" value="${esc(logsFilter.record_id)}">
        <button class="bn-btn bn-btn-ok" id="lf-apply">اعمال فیلتر</button>
        <button class="bn-btn bn-btn-ghost" id="lf-clear">پاک‌کردن</button>
      </div>
    </div>
    <div class="bn-list">
      ${res.items.map((l, i) => `
        <div class="bn-row bn-card-anim" style="animation-delay:${Math.min(i * 20, 200)}ms">
          ${bnAvatar('#', i)}
          <div class="bn-row-main">
            <span class="bn-row-title">${actionLabel(l.action)}</span>
            <span class="bn-row-sub">ادمین #${l.admin_id}${l.record_type ? ` · ${RECORD_TYPE_LABEL[l.record_type] || esc(l.record_type)} #${esc(l.record_id)}` : ''}${l.details ? ' · ' + esc(l.details) : ''}</span>
          </div>
          <span class="bn-row-sub mono">${fmtDate(l.created_at)}</span>
        </div>
      `).join('') || `<div class="empty-state"><div class="icon">${svg('empty')}</div>لاگی ثبت نشده</div>`}
    </div>
    <div class="pager" style="margin-top:16px">${Array.from({ length: pages }, (_, i) => i + 1).map(p => `<button class="btn btn-sm ${p === logsPage ? 'btn-primary' : ''}" data-page="${p}">${p}</button>`).join('')}</div>
  `);
  $$('[data-page]', content()).forEach(b => b.addEventListener('click', () => { logsPage = Number(b.dataset.page); renderLogs(); }));
  $('#lf-apply').addEventListener('click', () => {
    logsFilter = { action: $('#lf-action').value, record_type: $('#lf-type').value, record_id: $('#lf-id').value.trim() };
    logsPage = 1; renderLogs();
  });
  $('#lf-clear').addEventListener('click', () => { logsFilter = { action: '', record_type: '', record_id: '' }; logsPage = 1; renderLogs(); });
}


/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

/* ---------------------------------------------------- logs: brutalist --- */
// لاگ‌ها به‌شکل نوار زمانی (تایم‌لاین) با خط ضخیم سمت راست، به‌جای جدول.
function renderLogsBrutalist(actionsRes, res, pages) {
  setContent(`
    <div class="bru-hero"><h2>لاگ سیستم</h2><p>${fmt(res.total)} رکورد ثبت‌شده</p></div>
    <div class="bru-panel" style="margin-bottom:16px">
      <div class="form-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
        <select class="input" id="lf-action">
          <option value="">همه‌ی عملیات</option>
          ${actionsRes.actions.map(a => `<option value="${a}" ${a === logsFilter.action ? 'selected' : ''}>${actionLabel(a)}</option>`).join('')}
        </select>
        <select class="input" id="lf-type">
          <option value="">همه‌ی رکوردها</option>
          ${Object.keys(RECORD_TYPE_LABEL).map(t => `<option value="${t}" ${t === logsFilter.record_type ? 'selected' : ''}>${RECORD_TYPE_LABEL[t]}</option>`).join('')}
        </select>
        <input class="input" id="lf-id" placeholder="شناسه رکورد (مثلاً آیدی سفارش)" value="${esc(logsFilter.record_id)}">
        <button class="bru-stamp bru-stamp-ok" id="lf-apply" style="--r:-2deg">اعمال فیلتر</button>
        <button class="btn btn-sm" id="lf-clear">پاک‌کردن</button>
      </div>
    </div>
    <div class="bru-log-list">
      ${res.items.map((l, i) => `
        <div class="bru-log-row bru-card-anim" style="animation-delay:${Math.min(i * 25, 220)}ms">
          <span class="bru-log-time mono">${fmtDate(l.created_at)}</span>
          <div class="bru-log-main">
            <span class="bru-log-action">${actionLabel(l.action)}</span>
            <span class="bru-log-admin mono">ادمین #${l.admin_id}</span>
            ${l.record_type ? `<span class="chip">${RECORD_TYPE_LABEL[l.record_type] || esc(l.record_type)} #${esc(l.record_id)}</span>` : ''}
          </div>
          ${l.details ? `<div class="bru-log-details">${esc(l.details)}</div>` : ''}
        </div>
      `).join('') || `<div class="empty-state"><div class="icon">${svg('empty')}</div>لاگی ثبت نشده</div>`}
    </div>
    <div class="pager" style="margin-top:16px">${Array.from({ length: pages }, (_, i) => i + 1).map(p => `<button class="btn btn-sm ${p === logsPage ? 'btn-primary' : ''}" data-page="${p}">${p}</button>`).join('')}</div>
  `);
  $$('[data-page]', content()).forEach(b => b.addEventListener('click', () => { logsPage = Number(b.dataset.page); renderLogs(); }));
  $('#lf-apply').addEventListener('click', () => {
    logsFilter = { action: $('#lf-action').value, record_type: $('#lf-type').value, record_id: $('#lf-id').value.trim() };
    logsPage = 1; renderLogs();
  });
  $('#lf-clear').addEventListener('click', () => { logsFilter = { action: '', record_type: '', record_id: '' }; logsPage = 1; renderLogs(); });
}

/* ========================================================== webadmins === */
const PERM_LABEL = {
  orders: 'سفارش‌ها و شارژ کیف پول', users: 'کاربران (بلاک/کیف پول)', catalog: 'محصولات و بانک کانفیگ',
  discounts: 'کدهای تخفیف', tickets: 'تیکت‌ها و چت زنده', broadcast: 'پیام همگانی',
  resellers: 'نمایندگی‌ها', panels: 'پنل‌های VPN و نرخ ارز', system: 'سیستم، بکاپ (وضعیت) و لاگ‌ها',
  settings: 'تنظیمات و برندینگ', backup: 'ساخت بکاپ فوری',
};

function permChecklistHtml(idPrefix, selected) {
  return `<div class="chip-row" style="flex-wrap:wrap;gap:6px">${PERM_KEYS.map(p => `
    <label style="display:flex;align-items:center;gap:4px;font-size:12px;background:var(--panel-2);padding:4px 8px;border-radius:7px">
      <input type="checkbox" id="${idPrefix}-${p}" data-perm="${p}" ${selected.includes(p) ? 'checked' : ''}>${PERM_LABEL[p] || p}
    </label>`).join('')}</div>`;
}
function readPermChecklist(root, idPrefix) {
  return PERM_KEYS.filter(p => $(`#${idPrefix}-${p}`, root)?.checked);
}

let PERM_KEYS = [];
async function renderWebAdmins() {
  if (!PERM_KEYS.length) PERM_KEYS = (await apiGet('/web-admins/permissions')).permissions;
  const admins = await apiGet('/web-admins');
  if (loadTheme().theme === 'brutalist') return renderWebAdminsBrutalist(admins);
  if (loadTheme().theme === 'bento') return renderWebAdminsBento(admins);
  setContent(`
    <div class="toolbar"><button class="btn btn-primary btn-sm" id="add-admin">+ کاربر پنل جدید</button></div>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>یوزرنیم</th><th>نقش</th><th>مجوزها</th><th>وضعیت</th><th>آخرین ورود</th><th>عملیات</th></tr></thead>
      <tbody>${admins.map(a => `<tr>
        <td>${esc(a.username)}</td>
        <td><span class="badge badge-${a.role}">${ROLE_LABEL[a.role]}</span></td>
        <td>${a.role === 'owner' ? `<span class="card-sub">${settingsUiText('\u0647\u0645\u0647')}</span>` : `<span class="card-sub">${a.permissions.length ? a.permissions.map(p => PERM_LABEL[p] || p).join(', ') : settingsUiText('\u0628\u062f\u0648\u0646 \u0645\u062c\u0648\u0632 (\u0641\u0642\u0637 \u0645\u0634\u0627\u0647\u062f\u0647)')}</span>`}</td>
        <td>${a.is_active ? '<span class="badge badge-approved">فعال</span>' : '<span class="badge badge-rejected">غیرفعال</span>'}</td>
        <td class="mono">${fmtDate(a.last_login)}</td>
        <td>${a.role === 'owner' ? '<span class="card-sub">مالک</span>' : `
          <button class="btn btn-sm" data-edit-perms="${a.id}">ویرایش مجوزها</button>
          <button class="btn btn-sm" data-toggle-active="${a.id}" data-active="${a.is_active}">${a.is_active ? 'غیرفعال' : 'فعال'}</button>
          <button class="btn btn-danger btn-sm" data-del="${a.id}">حذف</button>`}</td>
      </tr>`).join('')}</tbody>
    </table></div></div>
  `);
  $('#add-admin').addEventListener('click', () => openModal('کاربر پنل جدید', `
    <div class="form-grid">
      <input class="input" id="na-user" placeholder="یوزرنیم">
      <input class="input" id="na-pass" type="password" placeholder="پسورد (حداقل ۸ کاراکتر)">
      <div class="card-sub" style="margin-top:4px">مجوزها:</div>
      ${permChecklistHtml('na', [])}
      <button class="btn btn-primary" id="na-save">ثبت</button>
    </div>`, (body, close) => {
    $('#na-save', body).addEventListener('click', async () => {
      try {
        await apiPost('/web-admins', {
          username: $('#na-user', body).value.trim(), password: $('#na-pass', body).value,
          role: 'admin', permissions: readPermChecklist(body, 'na'),
        });
        toast('کاربر ساخته شد.'); close(); renderWebAdmins();
      } catch (e) { handleErr(e); }
    });
  }));
  $$('[data-edit-perms]', content()).forEach(b => b.addEventListener('click', () => {
    const a = admins.find(x => x.id === Number(b.dataset.editPerms));
    openModal(`مجوزهای ${esc(a.username)}`, `
      ${permChecklistHtml('ep', a.permissions)}
      <button class="btn btn-primary" id="ep-save" style="margin-top:14px">ذخیره</button>
    `, (body, close) => {
      $('#ep-save', body).addEventListener('click', async () => {
        try {
          await apiPost(`/web-admins/${a.id}/permissions`, { permissions: readPermChecklist(body, 'ep') });
          toast('مجوزها به‌روزرسانی شد.'); close(); renderWebAdmins();
        } catch (e) { handleErr(e); }
      });
    });
  }));
  $$('[data-toggle-active]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/web-admins/${b.dataset.toggleActive}/active`, { active: b.dataset.active !== 'true' }); renderWebAdmins(); } catch (e) { handleErr(e); }
  }));
  $$('[data-del]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('این حساب حذف شود؟')) return;
    try { await apiDelete(`/web-admins/${b.dataset.del}`); toast('حذف شد.'); renderWebAdmins(); } catch (e) { handleErr(e); }
  }));
}

/* ========================================================= tg admins === */
// ادمین‌های تلگرامی ربات (جدول admins، بر اساس آیدی عددی) - جدا از «کاربران
// پنل» بالا که برای لاگین با یوزرنیم/پسورد به همین پنل وب هستند. این‌ها
// دسترسی ادمین داخل خود بات تلگرام را کنترل می‌کنند.
const TG_ADMIN_ROLE_LABEL = { admin: 'مدیر کامل', mid: 'ادمین میانی', support: 'پشتیبان' };

async function renderTelegramAdmins() {
  const admins = await apiGet('/telegram-admins');
  setContent(`
    <div class="toolbar"><button class="btn btn-primary btn-sm" id="add-tgadmin">+ افزودن ادمین</button></div>
    <p class="card-sub" style="margin-bottom:14px">این‌ها ادمین‌های خودِ ربات تلگرام‌اند (بر اساس آیدی عددی)، جدا از «کاربران پنل» که برای ورود به همین پنل وب استفاده می‌شوند.</p>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>آیدی عددی تلگرام</th><th>نقش</th><th>عملیات</th></tr></thead>
      <tbody>${admins.map(a => `<tr>
        <td class="mono">${a.telegram_id}</td>
        <td>${a.role === 'owner' ? '<span class="badge">مالک اصلی</span>' : `<span class="badge badge-${a.role}">${TG_ADMIN_ROLE_LABEL[a.role] || a.role}</span>`}</td>
        <td>${a.role === 'owner' ? '<span class="card-sub">مالک</span>' : `
          <button class="btn btn-sm" data-change-role="${a.telegram_id}" data-role="${a.role}">تغییر نقش</button>
          <button class="btn btn-danger btn-sm" data-del-tgadmin="${a.telegram_id}">حذف</button>`}</td>
      </tr>`).join('') || `<tr><td colspan="3" class="empty-state"><div class="icon">${svg('empty')}</div>ادمینی ثبت نشده است</td></tr>`}</tbody>
    </table></div></div>
  `);

  function roleOptionsHtml(selected) {
    return Object.entries(TG_ADMIN_ROLE_LABEL).map(([v, l]) => `<option value="${v}" ${v === selected ? 'selected' : ''}>${l}</option>`).join('');
  }

  $('#add-tgadmin').addEventListener('click', () => openModal('افزودن ادمین ربات', `
    <div class="form-grid">
      <input class="input" id="na-tgid" type="number" placeholder="آیدی عددی تلگرام">
      <label class="field"><span>نقش</span><select class="input" id="na-role">${roleOptionsHtml('admin')}</select></label>
      <button class="btn btn-primary" id="na-tg-save">ثبت</button>
    </div>`, (body, close) => {
    $('#na-tg-save', body).addEventListener('click', async () => {
      const tgId = Number($('#na-tgid', body).value);
      if (!tgId) { toast('آیدی عددی معتبر وارد کنید.'); return; }
      try {
        await apiPost('/telegram-admins', { telegram_id: tgId, role: $('#na-role', body).value });
        toast('ادمین اضافه شد.'); close(); renderTelegramAdmins();
      } catch (e) { handleErr(e); }
    });
  }));

  $$('[data-change-role]', content()).forEach(b => b.addEventListener('click', () => {
    const tgId = b.dataset.changeRole;
    openModal(`تغییر نقش ${tgId}`, `
      <div class="form-grid">
        <select class="input" id="cr-role">${roleOptionsHtml(b.dataset.role)}</select>
        <button class="btn btn-primary" id="cr-save">ذخیره</button>
      </div>`, (body, close) => {
      $('#cr-save', body).addEventListener('click', async () => {
        try {
          await apiPost(`/telegram-admins/${tgId}/role`, { role: $('#cr-role', body).value });
          toast('نقش تغییر کرد.'); close(); renderTelegramAdmins();
        } catch (e) { handleErr(e); }
      });
    });
  }));

  $$('[data-del-tgadmin]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('این ادمین از ربات حذف شود؟')) return;
    try { await apiDelete(`/telegram-admins/${b.dataset.delTgadmin}`); toast('حذف شد.'); renderTelegramAdmins(); } catch (e) { handleErr(e); }
  }));
}

/* ------------------------------------------------------- webadmins: bento */
function renderWebAdminsBento(admins) {
  setContent(`
    <div class="bn-hero">
      <div><h2>ادمین‌های پنل</h2><p>${fmt(admins.length)} حساب ثبت‌شده</p></div>
      <button class="bn-btn bn-btn-ok" id="add-admin">+ کاربر پنل جدید</button>
    </div>
    <div class="bn-list">
      ${admins.map((a, i) => `
        <div class="bn-row bn-card-anim" style="animation-delay:${Math.min(i * 25, 220)}ms">
          ${bnAvatar(a.username.trim().charAt(0).toUpperCase(), i)}
          <div class="bn-row-main">
            <span class="bn-row-title">${esc(a.username)}</span>
            <span class="bn-row-sub">${ROLE_LABEL[a.role]} · ورود: ${fmtDate(a.last_login)}</span>
          </div>
          <div class="bn-row-trail">
            ${bnPill(a.is_active ? 'فعال' : 'غیرفعال', a.is_active ? 'ok' : 'no')}
            ${a.role !== 'owner' ? `
            <button class="bn-btn bn-btn-ghost" data-edit-perms="${a.id}">مجوزها</button>
            <button class="bn-btn bn-btn-ghost" data-toggle-active="${a.id}" data-active="${a.is_active}">${a.is_active ? 'غیرفعال' : 'فعال'}</button>
            <button class="bn-btn bn-btn-no" data-del="${a.id}">حذف</button>` : ''}
          </div>
        </div>
      `).join('')}
    </div>
  `);
  $('#add-admin').addEventListener('click', () => openModal('کاربر پنل جدید', `
    <div class="form-grid">
      <input class="input" id="na-user" placeholder="یوزرنیم">
      <input class="input" id="na-pass" type="password" placeholder="پسورد (حداقل ۸ کاراکتر)">
      <div class="card-sub" style="margin-top:4px">مجوزها:</div>
      ${permChecklistHtml('na', [])}
      <button class="btn btn-primary" id="na-save">ثبت</button>
    </div>`, (body, close) => {
    $('#na-save', body).addEventListener('click', async () => {
      try {
        await apiPost('/web-admins', {
          username: $('#na-user', body).value.trim(), password: $('#na-pass', body).value,
          role: 'admin', permissions: readPermChecklist(body, 'na'),
        });
        toast('کاربر ساخته شد.'); close(); renderWebAdmins();
      } catch (e) { handleErr(e); }
    });
  }));
  $$('[data-edit-perms]', content()).forEach(b => b.addEventListener('click', () => {
    const a = admins.find(x => x.id === Number(b.dataset.editPerms));
    openModal(`مجوزهای ${esc(a.username)}`, `
      ${permChecklistHtml('ep', a.permissions)}
      <button class="btn btn-primary" id="ep-save" style="margin-top:14px">ذخیره</button>
    `, (body, close) => {
      $('#ep-save', body).addEventListener('click', async () => {
        try {
          await apiPost(`/web-admins/${a.id}/permissions`, { permissions: readPermChecklist(body, 'ep') });
          toast('مجوزها به‌روزرسانی شد.'); close(); renderWebAdmins();
        } catch (e) { handleErr(e); }
      });
    });
  }));
  $$('[data-toggle-active]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/web-admins/${b.dataset.toggleActive}/active`, { active: b.dataset.active !== 'true' }); renderWebAdmins(); } catch (e) { handleErr(e); }
  }));
  $$('[data-del]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('این حساب حذف شود؟')) return;
    try { await apiDelete(`/web-admins/${b.dataset.del}`); toast('حذف شد.'); renderWebAdmins(); } catch (e) { handleErr(e); }
  }));
}


/* -------------------------------------------------- cyberpunk --- */

/* -------------------------------------------------- clay --- */

/* -------------------------------------------------- paper --- */

/* -------------------------------------------------- obsidian --- */

/* -------------------------------------------------- warp --- */

/* ------------------------------------------------- webadmins: brutalist - */
// کارت شناسنامه‌ای برای هر ادمین پنل، با برچسب نقش مثل مهر روی پرونده.
function renderWebAdminsBrutalist(admins) {
  setContent(`
    <div class="bru-hero" style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
      <div>
        <h2>ادمین‌های پنل</h2>
        <p>${fmt(admins.length)} حساب ثبت‌شده</p>
      </div>
      <button class="bru-stamp bru-stamp-ok" id="add-admin" style="--r:-3deg">+ کاربر پنل جدید</button>
    </div>
    <div class="bru-user-grid">
      ${admins.map((a, i) => `
        <div class="bru-user-card bru-card-anim" style="animation-delay:${Math.min(i * 35, 300)}ms;text-align:center">
          <span class="bru-flag ${a.is_active ? 'bru-flag-ok' : 'bru-flag-no'}">${a.is_active ? 'فعال' : 'غیرفعال'}</span>
          <div class="bru-user-avatar mono">${esc(a.username.trim().charAt(0).toUpperCase())}</div>
          <div class="bru-user-name">${esc(a.username)}</div>
          <div class="bru-flag" style="background:var(--primary);margin-top:4px">${ROLE_LABEL[a.role]}</div>
          <div class="bru-user-id mono" style="margin-top:6px">ورود: ${fmtDate(a.last_login)}</div>
          <div class="bru-user-joined" style="max-width:190px">${a.role === 'owner' ? settingsUiText('\u062f\u0633\u062a\u0631\u0633\u06cc \u06a9\u0627\u0645\u0644') : (a.permissions.length ? a.permissions.map(p => PERM_LABEL[p] || p).join(', ') : settingsUiText('\u0628\u062f\u0648\u0646 \u0645\u062c\u0648\u0632'))}</div>
          ${a.role !== 'owner' ? `
          <div class="bru-user-actions">
            <button class="btn btn-sm" data-edit-perms="${a.id}">مجوزها</button>
            <button class="btn btn-sm" data-toggle-active="${a.id}" data-active="${a.is_active}">${a.is_active ? 'غیرفعال' : 'فعال'}</button>
            <button class="btn btn-danger btn-sm" data-del="${a.id}">حذف</button>
          </div>` : ''}
        </div>
      `).join('')}
    </div>
  `);
  $('#add-admin').addEventListener('click', () => openModal('کاربر پنل جدید', `
    <div class="form-grid">
      <input class="input" id="na-user" placeholder="یوزرنیم">
      <input class="input" id="na-pass" type="password" placeholder="پسورد (حداقل ۸ کاراکتر)">
      <div class="card-sub" style="margin-top:4px">مجوزها:</div>
      ${permChecklistHtml('na', [])}
      <button class="btn btn-primary" id="na-save">ثبت</button>
    </div>`, (body, close) => {
    $('#na-save', body).addEventListener('click', async () => {
      try {
        await apiPost('/web-admins', {
          username: $('#na-user', body).value.trim(), password: $('#na-pass', body).value,
          role: 'admin', permissions: readPermChecklist(body, 'na'),
        });
        toast('کاربر ساخته شد.'); close(); renderWebAdmins();
      } catch (e) { handleErr(e); }
    });
  }));
  $$('[data-edit-perms]', content()).forEach(b => b.addEventListener('click', () => {
    const a = admins.find(x => x.id === Number(b.dataset.editPerms));
    openModal(`مجوزهای ${esc(a.username)}`, `
      ${permChecklistHtml('ep', a.permissions)}
      <button class="btn btn-primary" id="ep-save" style="margin-top:14px">ذخیره</button>
    `, (body, close) => {
      $('#ep-save', body).addEventListener('click', async () => {
        try {
          await apiPost(`/web-admins/${a.id}/permissions`, { permissions: readPermChecklist(body, 'ep') });
          toast('مجوزها به‌روزرسانی شد.'); close(); renderWebAdmins();
        } catch (e) { handleErr(e); }
      });
    });
  }));
  $$('[data-toggle-active]', content()).forEach(b => b.addEventListener('click', async () => {
    try { await apiPost(`/web-admins/${b.dataset.toggleActive}/active`, { active: b.dataset.active !== 'true' }); renderWebAdmins(); } catch (e) { handleErr(e); }
  }));
  $$('[data-del]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('این حساب حذف شود؟')) return;
    try { await apiDelete(`/web-admins/${b.dataset.del}`); toast('حذف شد.'); renderWebAdmins(); } catch (e) { handleErr(e); }
  }));
}

/* ============================================================= system === */
async function renderSystem() {
  const jobs = await apiGet('/system/jobs');
  const r = jobs.renewal;
  const stockRows = jobs.stock;
  const lowCount = stockRows.filter(p => p.low).length;
  const backupStatus = await apiGet('/system/backup/status');
  const orphanFiles = await apiGet('/orphan-db-files').catch(() => []);
  const isOwner = ME.role === 'owner';

  setContent(`
    <div class="card" style="margin-bottom:18px">
      <div class="card-head"><h3>یادآوری‌های تمدید/حجم</h3></div>
      <p class="card-sub" style="margin-bottom:10px">این بخش فقط وضعیت آخرین اجرا را نشان می‌دهد؛ زمان‌بندی اجرا (هر ۱ ساعت) از کد بات کنترل می‌شود و از اینجا قابل تغییر نیست.</p>
      <div class="chip-row">
        <span class="chip">آخرین اجرا: ${r.last_run ? fmtDate(r.last_run) : 'هنوز اجرا نشده'}</span>
        <span class="chip">یادآوری تاریخ ارسال‌شده: ${fmt(r.last_date_sent)}</span>
        <span class="chip">یادآوری حجم ارسال‌شده: ${fmt(r.last_volume_sent)}</span>
      </div>
    </div>

    <div class="card" style="margin-bottom:18px">
      <div class="card-head">
        <h3>وضعیت لحظه‌ای موجودی محصولات</h3>
        <span class="card-sub">${lowCount ? `${lowCount} محصول زیر آستانه هشدار` : 'همه محصولات موجودی کافی دارند'}</span>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>محصول</th><th>موجودی</th><th>آستانه هشدار</th><th>وضعیت</th></tr></thead>
        <tbody>${stockRows.map(p => `<tr>
          <td>${esc(p.name)}</td>
          <td class="mono">${fmt(p.stock)}</td>
          <td class="mono">${fmt(p.threshold)}</td>
          <td>${p.low
            ? `<span class="badge badge-rejected">کم${p.alerted ? ' · هشدار ارسال شد' : ''}</span>`
            : '<span class="badge badge-approved">کافی</span>'}</td>
        </tr>`).join('') || `<tr><td colspan="4" class="empty-state"><div class="icon">${svg('empty')}</div>محصولی برای نمایش نیست</td></tr>`}</tbody>
      </table></div>
    </div>

    <div class="card" style="margin-bottom:18px">
      <div class="card-head"><h3>بکاپ دیتابیس</h3></div>
      <div class="chip-row" style="margin-bottom:14px">
        <span class="chip">آخرین بکاپ: ${backupStatus.last_backup_at ? fmtDate(backupStatus.last_backup_at) : 'ثبت نشده'}</span>
        <span class="chip">حجم آخرین بکاپ: ${backupStatus.last_backup_size_mb ?? '—'} مگابایت</span>
        <span class="chip">تعداد نسخه‌های نگه‌داشته‌شده: ${fmt(backupStatus.count)}</span>
      </div>
      ${isOwner ? `
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px">
        <button class="btn btn-primary" id="backup-create-btn">📥 گرفتن بکاپ فوری و ارسال به تلگرام</button>
      </div>
      <div id="backup-create-status"></div>

      <div class="card-head" style="margin-top:10px"><h3>بازیابی از فایل بکاپ</h3></div>
      <p class="card-sub" style="margin-bottom:10px">⚠️ با تایید، کل دیتابیس فعلی با فایل آپلودی جایگزین می‌شود. این کار قابل بازگشت نیست مگر با بکاپ دیگر. قبل از جایگزینی، یک نسخه از وضعیت فعلی خودکار ذخیره می‌شود.</p>
      <input type="file" class="input" id="restore-file" accept=".db,.sqlite,.sqlite3" style="margin-bottom:10px">
      <div id="restore-area"></div>
      ` : `<p class="card-sub">گرفتن بکاپ فوری و بازیابی فقط برای مالک در دسترس است.</p>`}
    </div>

    ${isOwner ? `
    <div class="card" style="margin-bottom:18px;border-color:var(--rose)">
      <div class="card-head"><h3>🏭 بازگشت به حالت کارخانه</h3></div>
      <p class="card-sub" style="margin-bottom:10px">همه‌ی داده‌ی این بات (کاربرها، سفارش‌ها، محصولات، کیف پول، تیکت‌ها، تنظیمات و ...) پاک می‌شود؛ دقیقاً مثل روز اول نصب، چه در مینی‌اپ چه در همین پنل وب. فقط حساب خودت به‌عنوان مالک باقی می‌ماند. این کار فقط روی همین بات اثر می‌گذارد و به نماینده‌های زیرمجموعه (در صورت وجود) کاری ندارد. قبل از پاک‌سازی یک بکاپ ایمنی خودکار گرفته می‌شود.</p>
      <button class="btn btn-danger btn-sm" id="factory-reset-open-btn">بازگشت به حالت کارخانه...</button>
      <div id="factory-reset-area" style="margin-top:12px"></div>
    </div>
    ` : ''}

    <div class="card" style="margin-bottom:18px">
      <div class="card-head">
        <h3>فایل‌های دیتابیس یتیم</h3>
        <span class="card-sub">${orphanFiles.length ? `${orphanFiles.length} فایل یتیم پیدا شد` : 'فایل یتیمی پیدا نشد'}</span>
      </div>
      <p class="card-sub" style="margin-bottom:10px">فایل‌های <span class="mono">.db</span> داخل پوشه‌ی reseller_dbs که هیچ رکورد نماینده‌ای (حتی حذف‌شده) در جدول نماینده‌ها به آن‌ها اشاره نمی‌کند؛ معمولاً باقیمانده‌ی نماینده‌های حذف‌شده با گزینه‌ی «فقط حذف، دیتابیس نگه داشته شود» هستند. حذف این فایل‌ها غیرقابل بازگشت است.</p>
      <div class="table-wrap"><table>
        <thead><tr><th>نام فایل</th><th>حجم</th><th>عملیات</th></tr></thead>
        <tbody>${orphanFiles.map(o => `<tr>
          <td class="mono">${esc(o.filename)}</td>
          <td class="mono">${(o.size / 1024).toFixed(1)} کیلوبایت</td>
          <td><button class="btn btn-danger btn-sm" data-del-orphan="${esc(o.filename)}">حذف</button></td>
        </tr>`).join('') || `<tr><td colspan="3" class="empty-state"><div class="icon">${svg('empty')}</div>فایل یتیمی روی دیسک نیست</td></tr>`}</tbody>
      </table></div>
    </div>
  `);

  $$('[data-del-orphan]', content()).forEach(b => b.addEventListener('click', async () => {
    if (!confirm(`فایل «${b.dataset.delOrphan}» برای همیشه حذف شود؟`)) return;
    try {
      await apiDelete(`/orphan-db-files/${encodeURIComponent(b.dataset.delOrphan)}`);
      toast('حذف شد.'); renderSystem();
    } catch (e) { handleErr(e); }
  }));

  if (!isOwner) return;

  $('#backup-create-btn').addEventListener('click', async () => {
    const btn = $('#backup-create-btn');
    const status = $('#backup-create-status', content());
    btn.disabled = true;
    status.innerHTML = '<span class="card-sub">⏳ در حال ساخت و ارسال بکاپ...</span>';
    try {
      const res = await apiPost('/system/backup/create');
      status.innerHTML = `<span class="card-sub">✅ بکاپ (${esc(res.filename)}, ${res.size_mb} مگابایت) ساخته شد و به ${res.sent} ادمین ارسال شد${res.failed ? ` (${res.failed} ناموفق)` : ''}.</span>`;
      toast('بکاپ گرفته شد.');
    } catch (e) {
      status.innerHTML = '';
      handleErr(e);
    } finally {
      btn.disabled = false;
    }
  });

  let restorePendingFile = null;

  function renderRestoreArea() {
    const area = $('#restore-area', content());
    if (!restorePendingFile) {
      area.innerHTML = '';
      return;
    }
    const sizeMb = (restorePendingFile.size / (1024 * 1024)).toFixed(1);
    area.innerHTML = `
      <div class="card" style="margin-top:0;border-color:var(--rose)">
        <p class="card-sub" style="margin:0 0 8px">📦 فایل انتخاب‌شده: ${esc(restorePendingFile.name)} (${sizeMb} مگابایت)</p>
        <p class="card-sub" style="margin:0 0 10px">⚠️ مرحله ۱: این عمل کل دیتابیس فعلی رو با این فایل جایگزین می‌کنه. مطمئنی؟</p>
        <div style="display:flex;gap:8px">
          <button class="btn btn-danger btn-sm" id="restore-step1-btn">بله، ادامه بده</button>
          <button class="btn btn-ghost btn-sm" id="restore-cancel-btn">انصراف</button>
        </div>
      </div>
    `;
    $('#restore-step1-btn', area).addEventListener('click', () => renderRestoreConfirmStep());
    $('#restore-cancel-btn', area).addEventListener('click', cancelRestore);
  }

  function renderRestoreConfirmStep() {
    const area = $('#restore-area', content());
    area.innerHTML = `
      <div class="card" style="margin-top:0;border-color:var(--rose)">
        <p class="card-sub" style="margin:0 0 10px">⚠️ مرحله ۲ (نهایی): برای تایید نهایی، عبارت <strong class="mono">RESTORE</strong> رو دقیقاً تایپ کن.</p>
        <input class="input" id="restore-confirm-input" placeholder="RESTORE" style="margin-bottom:10px">
        <div style="display:flex;gap:8px">
          <button class="btn btn-danger btn-sm" id="restore-final-btn">✅ تایید نهایی و جایگزینی</button>
          <button class="btn btn-ghost btn-sm" id="restore-cancel-btn2">انصراف</button>
        </div>
        <div id="restore-final-status" style="margin-top:10px"></div>
      </div>
    `;
    $('#restore-cancel-btn2', area).addEventListener('click', cancelRestore);
    $('#restore-final-btn', area).addEventListener('click', async () => {
      const phrase = $('#restore-confirm-input', area).value.trim();
      if (phrase.toUpperCase() !== 'RESTORE') {
        $('#restore-final-status', area).innerHTML = '<span class="card-sub" style="color:var(--rose)">عبارت را دقیقاً RESTORE وارد کن.</span>';
        return;
      }
      const statusEl = $('#restore-final-status', area);
      statusEl.innerHTML = '<span class="card-sub">⏳ در حال بازیابی...</span>';
      try {
        const formData = new FormData();
        formData.append('file', restorePendingFile);
        formData.append('confirm_phrase', phrase);
        const res = await fetch('/api/system/backup/restore', { method: 'POST', credentials: 'include', body: formData });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { const d = data.detail || (res.status === 413 ? 'حجم فایل از سقف مجاز وب‌سرور (nginx client_max_body_size) بیشتر است.' : `خطای سرور (${res.status})`); throw new Error(window.ShopVPNTranslate ? window.ShopVPNTranslate(d) : d); }
        statusEl.innerHTML = `<span class="card-sub">✅ دیتابیس بازیابی شد. نسخه‌ی قبلی به‌عنوان «${esc(data.pre_restore_backup)}» ذخیره شد. صفحه را رفرش کن.</span>`;
        restorePendingFile = null;
        $('#restore-file').value = '';
      } catch (e) {
        statusEl.innerHTML = `<span class="card-sub" style="color:var(--rose)">${esc(e.message)}</span>`;
      }
    });
  }

  function cancelRestore() {
    restorePendingFile = null;
    $('#restore-file').value = '';
    renderRestoreArea();
  }

  $('#restore-file').addEventListener('change', e => {
    const file = e.target.files[0];
    if (!file) { restorePendingFile = null; renderRestoreArea(); return; }
    if (!/\.(db|sqlite|sqlite3)$/i.test(file.name)) {
      toast('فایل باید پسوند .db یا .sqlite داشته باشد.', true);
      e.target.value = '';
      return;
    }
    restorePendingFile = file;
    renderRestoreArea();
  });

  let factoryResetStep = 0;

  function renderFactoryResetArea() {
    const area = $('#factory-reset-area', content());
    if (factoryResetStep === 0) { area.innerHTML = ''; return; }
    if (factoryResetStep === 1) {
      area.innerHTML = `
        <div class="card" style="margin-top:0;border-color:var(--rose)">
          <p class="card-sub" style="margin:0 0 10px">⚠️ مرحله ۱: این کار همه‌ی داده‌ی این بات را برای همیشه پاک می‌کند. مطمئنی؟</p>
          <div style="display:flex;gap:8px">
            <button class="btn btn-danger btn-sm" id="factory-reset-step1-btn">بله، ادامه بده</button>
            <button class="btn btn-ghost btn-sm" id="factory-reset-cancel-btn">انصراف</button>
          </div>
        </div>`;
      $('#factory-reset-step1-btn', area).addEventListener('click', () => { factoryResetStep = 2; renderFactoryResetArea(); });
      $('#factory-reset-cancel-btn', area).addEventListener('click', cancelFactoryReset);
      return;
    }
    area.innerHTML = `
      <div class="card" style="margin-top:0;border-color:var(--rose)">
        <p class="card-sub" style="margin:0 0 10px">⚠️ مرحله ۲ (نهایی): برای تایید، عبارت <strong class="mono">RESET</strong> رو دقیقاً تایپ کن.</p>
        <input class="input" id="factory-reset-confirm-input" placeholder="RESET" style="margin-bottom:10px">
        <div style="display:flex;gap:8px">
          <button class="btn btn-danger btn-sm" id="factory-reset-final-btn">✅ تایید نهایی و پاک‌سازی</button>
          <button class="btn btn-ghost btn-sm" id="factory-reset-cancel-btn2">انصراف</button>
        </div>
        <div id="factory-reset-final-status" style="margin-top:10px"></div>
      </div>`;
    $('#factory-reset-cancel-btn2', area).addEventListener('click', cancelFactoryReset);
    $('#factory-reset-final-btn', area).addEventListener('click', async () => {
      const phrase = $('#factory-reset-confirm-input', area).value.trim();
      const statusEl = $('#factory-reset-final-status', area);
      if (phrase.toUpperCase() !== 'RESET') {
        statusEl.innerHTML = '<span class="card-sub" style="color:var(--rose)">عبارت را دقیقاً RESET وارد کن.</span>';
        return;
      }
      statusEl.innerHTML = '<span class="card-sub">⏳ در حال پاک‌سازی...</span>';
      try {
        const formData = new FormData();
        formData.append('confirm_phrase', phrase);
        const res = await fetch('/api/system/factory-reset', { method: 'POST', credentials: 'include', body: formData });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(window.ShopVPNTranslate ? window.ShopVPNTranslate(data.detail || 'Unknown error') : (data.detail || 'Unknown error'));
        statusEl.innerHTML = `<span class="card-sub">✅ بات به حالت کارخانه بازگشت.${data.safety_backup ? ` بکاپ قبل از پاک‌سازی: «${esc(data.safety_backup)}».` : ''} صفحه را رفرش کن.</span>`;
        factoryResetStep = 0;
      } catch (e) {
        statusEl.innerHTML = `<span class="card-sub" style="color:var(--rose)">${esc(e.message)}</span>`;
      }
    });
  }

  function cancelFactoryReset() {
    factoryResetStep = 0;
    renderFactoryResetArea();
  }

  $('#factory-reset-open-btn', content()).addEventListener('click', () => {
    factoryResetStep = 1;
    renderFactoryResetArea();
  });
}

/* ============================================================= account === */
function renderThemeCard(t, cur) {
  const active = t.id === cur.theme;
  const swatchHtml = t.swatch.map(c => `<span style="background:${c}"></span>`).join('');
  return `
    <div class="theme-card ${active ? 'active' : ''} ${t.ready ? '' : 'locked'}" data-theme-id="${t.id}">
      <div class="theme-card-swatch">${swatchHtml}</div>
      <div class="theme-card-body">
        <strong>${esc(t.name)}</strong>
        <span>${esc(t.desc)}</span>
      </div>
      ${active ? '<span class="theme-card-badge">فعال</span>' : (t.ready ? '' : '<span class="theme-card-badge locked">به‌زودی</span>')}
    </div>`;
}

async function renderAccount() {
  const cur = loadTheme();
  const activeMeta = THEMES.find(t => t.id === cur.theme) || THEMES[0];
  setContent(`
    <div class="card" style="margin-bottom:18px">
      <div class="card-head"><h3>تم پنل</h3></div>
      <div class="theme-grid" id="theme-grid">
        ${THEMES.map(t => renderThemeCard(t, cur)).join('')}
      </div>
      <span class="card-sub">این یک ترجیح شخصیه و فقط برای همین مرورگر ذخیره می‌شود؛ روی نمایش پنل برای بقیه‌ی ادمین‌ها اثری ندارد.${activeMeta.supportsMode ? ' سوییچ روشن/تیره از نوار بالا در دسترسه.' : ''}</span>
    </div>

    <div class="card" style="max-width:420px;margin-bottom:18px">
      <div class="card-head"><h3>تغییر یوزرنیم</h3></div>
      <div class="form-grid">
        <span class="card-sub">یوزرنیم فعلی: <b class="mono">${esc(ME.username)}</b></span>
        <input class="input" id="acc-new-username" type="text" autocomplete="off" placeholder="یوزرنیم جدید (حداقل ۳ کاراکتر)">
        <input class="input" id="acc-username-pass" type="password" placeholder="پسورد فعلی">
        <button class="btn btn-primary" id="acc-username-save">تغییر یوزرنیم</button>
      </div>
    </div>

    <div class="card" style="max-width:420px">
      <div class="card-head"><h3>تغییر پسورد</h3></div>
      <div class="form-grid">
        <input class="input" id="acc-cur" type="password" placeholder="پسورد فعلی">
        <input class="input" id="acc-new" type="password" placeholder="پسورد جدید (حداقل ۸ کاراکتر)">
        <button class="btn btn-primary" id="acc-save">تغییر پسورد</button>
      </div>
    </div>
  `);
  $$('.theme-card', content()).forEach(card => card.addEventListener('click', () => {
    const id = card.dataset.themeId;
    const meta = THEMES.find(t => t.id === id);
    if (!meta.ready) { toast('این تم هنوز آماده نیست — به‌زودی اضافه می‌شود.'); return; }
    applyThemeChoice(id);
    renderAccount();
  }));
  $('#acc-username-save').addEventListener('click', async () => {
    try {
      const res = await apiPost('/me/username', { current_password: $('#acc-username-pass').value, new_username: $('#acc-new-username').value });
      ME.username = res.username;
      $('#me-username').textContent = ME.username;
      $('#me-avatar').textContent = ME.username.slice(0, 2).toUpperCase();
      toast('یوزرنیم تغییر کرد.');
      renderAccount();
    } catch (e) { handleErr(e); }
  });
  $('#acc-save').addEventListener('click', async () => {
    try {
      await apiPost('/me/password', { current_password: $('#acc-cur').value, new_password: $('#acc-new').value });
      toast('پسورد تغییر کرد.');
      $('#acc-cur').value = ''; $('#acc-new').value = '';
    } catch (e) { handleErr(e); }
  });
}

boot();
/*‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍*/
// 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
