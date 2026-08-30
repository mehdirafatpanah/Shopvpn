const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();
try { tg.setHeaderColor("#0a0e17"); tg.setBackgroundColor("#0a0e17"); } catch (e) {}

const initData = tg.initData; // برای هدر X-Init-Data به بک‌اند فرستاده می‌شود
const content = document.getElementById("content");

// شناسه‌ی نماینده (اگر مینی‌اپ از یک بات نمایندگی باز شده باشد) - از URL خوانده می‌شود
// و به تمام درخواست‌های API اضافه می‌شود تا سرور دیتابیس/توکن درست را انتخاب کند.
const TENANT_ID = new URLSearchParams(window.location.search).get("b") || "";

function withTenant(path) {
  if (!TENANT_ID) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}b=${encodeURIComponent(TENANT_ID)}`;
}

// ---------------------------------------------------------------------------
// تبدیل میلادی به شمسی (فقط برای نمایش؛ منطق داخلی همچنان میلادی/ISO است)
// ---------------------------------------------------------------------------
function gregorianToJalali(gy, gm, gd) {
  const g_d_m = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const j_d_m = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29];
  const div = (a, b) => Math.floor(a / b);

  const gy2 = gy - 1600, gm2 = gm - 1, gd2 = gd - 1;
  let g_day_no = 365 * gy2 + div(gy2 + 3, 4) - div(gy2 + 99, 100) + div(gy2 + 399, 400);
  for (let i = 0; i < gm2; i++) g_day_no += g_d_m[i];
  if (gm2 > 1 && ((gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0)) g_day_no += 1;
  g_day_no += gd2;

  let j_day_no = g_day_no - 79;
  const j_np = div(j_day_no, 12053);
  j_day_no %= 12053;

  let jy = 979 + 33 * j_np + 4 * div(j_day_no, 1461);
  j_day_no %= 1461;

  if (j_day_no >= 366) {
    jy += div(j_day_no - 1, 365);
    j_day_no = (j_day_no - 1) % 365;
  }

  let jm = 12, jd = j_day_no + 1;
  for (let i = 0; i < 11; i++) {
    if (j_day_no < j_d_m[i]) { jm = i + 1; jd = j_day_no + 1; break; }
    j_day_no -= j_d_m[i];
  }
  return [jy, jm, jd];
}

function toJalaliStr(value, withTime = false) {
  if (!value) return "-";
  const d = value instanceof Date ? value : new Date(value);
  if (isNaN(d.getTime())) return String(value);
  const [jy, jm, jd] = gregorianToJalali(d.getFullYear(), d.getMonth() + 1, d.getDate());
  const pad = (n) => String(n).padStart(2, "0");
  let out = `${jy}/${pad(jm)}/${pad(jd)}`;
  if (withTime) out += ` - ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return out;
}

function toJalaliMonthDay(value) {
  if (!value) return "-";
  const d = value instanceof Date ? value : new Date(value);
  if (isNaN(d.getTime())) return String(value);
  const [, jm, jd] = gregorianToJalali(d.getFullYear(), d.getMonth() + 1, d.getDate());
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(jm)}/${pad(jd)}`;
}

function jalaliToGregorian(jy, jm, jd) {
  const j_d_m = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29];
  const g_d_m = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const div = (a, b) => Math.floor(a / b);

  const jy2 = jy - 979, jm2 = jm - 1, jd2 = jd - 1;
  let j_day_no = 365 * jy2 + div(jy2, 33) * 8 + div((jy2 % 33) + 3, 4);
  for (let i = 0; i < jm2; i++) j_day_no += j_d_m[i];
  j_day_no += jd2;

  let g_day_no = j_day_no + 79;

  let gy = 1600 + 400 * div(g_day_no, 146097);
  g_day_no %= 146097;

  if (g_day_no >= 36525) {
    g_day_no -= 1;
    gy += 100 * div(g_day_no, 36524);
    g_day_no %= 36524;
    if (g_day_no >= 365) g_day_no += 1;
  }

  gy += 4 * div(g_day_no, 1461);
  g_day_no %= 1461;

  if (g_day_no >= 366) {
    g_day_no -= 1;
    gy += div(g_day_no, 365);
    g_day_no %= 365;
  }

  let gm = 1, gd = g_day_no + 1;
  let days = g_day_no;
  for (let i = 0; i < 12; i++) {
    const dim = g_d_m[i] + (i === 1 && ((gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0) ? 1 : 0);
    if (days < dim) { gm = i + 1; gd = days + 1; break; }
    days -= dim;
  }
  return [gy, gm, gd];
}

function jalaliToISO(jy, jm, jd) {
  const [gy, gm, gd] = jalaliToGregorian(jy, jm, jd);
  const pad = (n) => String(n).padStart(2, "0");
  return `${gy}-${pad(gm)}-${pad(gd)}`;
}

function isoToJalaliYMD(iso) {
  const d = new Date(iso);
  return gregorianToJalali(d.getFullYear(), d.getMonth() + 1, d.getDate());
}

function jalaliDateSelectHtml(idPrefix, jy, jm, jd) {
  const dayOptions = Array.from({ length: 31 }, (_, i) => i + 1)
    .map((d) => `<option value="${d}" ${d === jd ? "selected" : ""}>${d}</option>`).join("");
  const monthOptions = JALALI_MONTH_NAMES
    .map((name, i) => `<option value="${i + 1}" ${i + 1 === jm ? "selected" : ""}>${name}</option>`).join("");
  const yearOptions = Array.from({ length: 6 }, (_, i) => jy - 4 + i)
    .map((y) => `<option value="${y}" ${y === jy ? "selected" : ""}>${y}</option>`).join("");
  return `
    <select class="input" id="${idPrefix}-d" style="flex:0 0 25%;padding:8px 4px">${dayOptions}</select>
    <select class="input" id="${idPrefix}-m" style="flex:0 0 38%;padding:8px 4px">${monthOptions}</select>
    <select class="input" id="${idPrefix}-y" style="flex:0 0 30%;padding:8px 4px">${yearOptions}</select>
  `;
}

const JALALI_MONTH_NAMES = [
  "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
  "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
];

function notify(message) {
  if (tg.showAlert) tg.showAlert(message);
  else alert(message);
}

async function api(path, options = {}) {
  const res = await fetch(withTenant(path), {
    ...options,
    headers: { "Content-Type": "application/json", "X-Init-Data": initData, ...(options.headers || {}) },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "خطا" }));
    if (res.status === 403 && err.detail && err.detail.code === "force_join") {
      showForceJoinGate(err.detail);
      throw new Error(err.detail.message || "برای ادامه باید در کانال عضو شوید.");
    }
    const msg = typeof err.detail === "string" ? err.detail : (err.detail && err.detail.message) || "خطای ناشناخته";
    throw new Error(msg);
  }
  return res.json();
}

// بنر/صفحه‌ی عضویت اجباری در کانال - هم‌تراز با force_join.py در ربات اصلی
// که قبل از هر اکشنی (خرید/تاپ‌آپ/تست/گردونه) عضویت را چک می‌کند.
function showForceJoinGate(info) {
  const overlay = document.createElement("div");
  overlay.className = "force-join-overlay";
  overlay.innerHTML = `
    <div class="card" style="max-width:320px;text-align:center">
      <h3><span class="ic">📢</span>عضویت در کانال الزامی است</h3>
      <p style="margin:10px 0">برای استفاده از این بخش، ابتدا باید در کانال زیر عضو شوید:</p>
      <a class="btn" href="${info.join_link}" target="_blank" style="text-decoration:none;display:block;margin-bottom:8px">📢 عضویت در کانال</a>
      <button class="btn outline" id="force-join-recheck-btn">✅ بررسی مجدد عضویت</button>
      <button class="btn outline small" id="force-join-close-btn" style="margin-top:8px">بستن</button>
    </div>
  `;
  document.body.appendChild(overlay);
  document.getElementById("force-join-close-btn").onclick = () => overlay.remove();
  document.getElementById("force-join-recheck-btn").onclick = async () => {
    try {
      const status = await api("/api/force-join-status");
      if (!status.required || status.member) {
        notify("✅ عضویت شما تایید شد.");
        overlay.remove();
      } else {
        notify("هنوز عضو کانال نشده‌اید.");
      }
    } catch (e) { /* از خود force-join-status هیچ‌وقت force_join throw نمی‌کند */ }
  };
}

// آپلود فایل (مولتی‌پارت) - بدون Content-Type دستی تا مرورگر boundary را ست کند
async function apiUpload(path, formData) {
  const res = await fetch(withTenant(path), {
    method: "POST",
    headers: { "X-Init-Data": initData },
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "خطا" }));
    throw new Error(err.detail || "خطای ناشناخته");
  }
  return res.json();
}

function fmt(n) {
  return Number(n).toLocaleString("fa-IR");
}

function formatCardNumber(raw) {
  const digits = String(raw || "").replace(/\D/g, "");
  if (digits.length < 8) return raw || "----";
  return digits.replace(/(.{4})/g, "$1 ").trim();
}

function skeleton(rows = 3) {
  return `<div class="skeleton-block">${'<div class="skel"></div>'.repeat(rows)}</div>`;
}

function errorState(message) {
  return `<div class="state-msg error"><span class="ic">⚠</span>${message}</div>`;
}

// ---------------------------------------------------------------------------
// تب کانفیگ تست
// ---------------------------------------------------------------------------

async function renderTestConfig() {
  content.innerHTML = skeleton(1);
  try {
    const status = await api("/api/test-config");
    content.innerHTML = `
      <div class="eyebrow">کانفیگ تست</div>
      <div class="card" id="test-config-card">
        <h3><span class="ic">🧪</span>کانفیگ تست رایگان</h3>
        <p class="hint-text">یک کانفیگ محدود و رایگان برای امتحان کیفیت سرویس، فقط یک‌بار برای هر کاربر.</p>
        ${testConfigBody(status)}
      </div>
    `;
    const btn = document.getElementById("test-config-btn");
    if (btn) btn.onclick = () => claimTestConfig(btn);
  } catch (e) {
    content.innerHTML = errorState(e.message);
  }
}

function testConfigBody(status) {
  if (!status.enabled) return `<div class="state-msg"><span class="ic">◌</span>در حال حاضر کانفیگ تست غیرفعال است.</div>`;
  if (status.used) {
    if (!status.link) return `<div class="state-msg"><span class="ic">✅</span>شما کانفیگ تست خود را قبلاً دریافت کرده‌اید.</div>`;
    return `
      <div class="state-msg" style="padding:0 0 10px"><span class="ic">✅</span>کانفیگ تست شما</div>
      <div class="link-box">${status.link}</div>
      <div class="qr-row">
        <img src="https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(status.link)}" width="96" height="96" alt="QR" />
        <button class="btn small outline" onclick="navigator.clipboard.writeText('${status.link}');tg.HapticFeedback.notificationOccurred('success')">📋 کپی لینک</button>
      </div>
    `;
  }
  if (status.available <= 0) return `<div class="state-msg"><span class="ic">◌</span>موجودی کانفیگ تست تمام شده است.</div>`;
  return `<button class="btn" id="test-config-btn">دریافت کانفیگ تست رایگان</button>`;
}

async function claimTestConfig(btn) {
  btn.disabled = true;
  btn.textContent = "در حال دریافت...";
  try {
    const r = await api("/api/test-config/claim", { method: "POST" });
    const card = document.getElementById("test-config-card");
    card.innerHTML = `
      <h3><span class="ic">🧪</span>کانفیگ تست رایگان</h3>
      <div class="link-box">${r.link}</div>
      <div class="qr-row">
        <img src="https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(r.link)}" width="96" height="96" alt="QR" />
        <button class="btn small outline" onclick="navigator.clipboard.writeText('${r.link}');tg.HapticFeedback.notificationOccurred('success')">📋 کپی لینک</button>
      </div>
    `;
    tg.HapticFeedback.notificationOccurred("success");
  } catch (e) {
    notify("خطا: " + e.message);
    btn.disabled = false;
    btn.textContent = "دریافت کانفیگ تست رایگان";
  }
}

// ---------------------------------------------------------------------------
// تب زیرمجموعه‌گیری
// ---------------------------------------------------------------------------

async function renderReferral() {
  content.innerHTML = skeleton(1);
  try {
    const r = await api("/api/referral");
    if (!r.enabled) {
      content.innerHTML = `<div class="state-msg"><span class="ic">◌</span>زیرمجموعه‌گیری در حال حاضر غیرفعال است.</div>`;
      return;
    }
    content.innerHTML = `
      ${referralCard(r)}
    `;
    const copyBtn = document.getElementById("copy-referral-btn");
    if (copyBtn) copyBtn.onclick = () => {
      navigator.clipboard.writeText(r.link);
      tg.HapticFeedback.notificationOccurred("success");
      notify("لینک دعوت کپی شد.");
    };
  } catch (e) {
    content.innerHTML = errorState(e.message);
  }
}

// ---------------------------------------------------------------------------
// تب پشتیبانی (چت)
// ---------------------------------------------------------------------------

let supportPollTimer = null;
let supportLastId = 0;
let supportSection = "chat"; // chat | tickets
let ticketView = { level: "list" }; // list | thread

function renderSupport() {
  content.innerHTML = `
    <div class="segmented" id="support-section-tabs">
      <button class="seg-btn ${supportSection === "chat" ? "active" : ""}" data-section="chat">گفتگوی زنده</button>
      <button class="seg-btn ${supportSection === "tickets" ? "active" : ""}" data-section="tickets">تیکت‌ها</button>
    </div>
    <div id="support-section-body"></div>
  `;
  document.querySelectorAll("#support-section-tabs .seg-btn").forEach((b) => {
    b.onclick = () => {
      clearInterval(supportPollTimer);
      supportSection = b.dataset.section;
      if (supportSection === "tickets") ticketView = { level: "list" };
      renderSupport();
    };
  });
  if (supportSection === "chat") renderSupportChat();
  else renderTicketsSection();
}

function renderSupportChat() {
  const body = document.getElementById("support-section-body");
  body.innerHTML = `
    <div class="chat-wrap">
      <div class="chat-messages" id="chat-messages">${skeleton(2)}</div>
      <form class="chat-input-row" id="chat-form">
        <input type="text" id="chat-input" placeholder="پیام خود را بنویسید..." autocomplete="off" />
        <button type="submit" class="chat-send-btn" aria-label="ارسال">
          <svg viewBox="0 0 24 24" fill="none"><path d="M4 12 20 4l-6 16-3-7-7-1Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>
        </button>
      </form>
    </div>
  `;

  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  form.onsubmit = async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    appendChatMessage({ sender: "user", message: text, created_at: new Date().toISOString() }, true);
    try {
      await api("/api/support/messages", { method: "POST", body: JSON.stringify({ message: text }) });
    } catch (e2) {
      notify("خطا: " + e2.message);
    }
  };

  supportLastId = 0;
  document.getElementById("chat-messages").innerHTML = "";
  loadSupportMessages(true);
  clearInterval(supportPollTimer);
  supportPollTimer = setInterval(() => loadSupportMessages(false), 4000);
}

async function loadSupportMessages(initial) {
  try {
    const msgs = await api(`/api/support/messages?since_id=${supportLastId}`);
    if (initial && msgs.length === 0) {
      document.getElementById("chat-messages").innerHTML =
        `<div class="state-msg"><span class="ic">💬</span>سوالی دارید؟ همینجا بنویسید تا پشتیبانی پاسخ دهد.</div>`;
    }
    msgs.forEach((m) => appendChatMessage(m, false));
  } catch (e) {
    // در پس‌زمینه صامت (ارور نمایش داده نمی‌شود تا مزاحم تایپ کاربر نشود)
  }
}

function appendChatMessage(m, isOptimistic) {
  const box = document.getElementById("chat-messages");
  if (!box) return;
  if (box.querySelector(".state-msg")) box.innerHTML = "";
  if (m.id) supportLastId = Math.max(supportLastId, m.id);
  const time = new Date(m.created_at).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${m.sender === "user" ? "mine" : "admin"}`;
  bubble.innerHTML = `<div class="chat-text"></div><div class="chat-time">${time}</div>`;
  bubble.querySelector(".chat-text").textContent = m.message;
  box.appendChild(bubble);
  box.scrollTop = box.scrollHeight;
}

// ---------------------------------------------------------------------------
// تیکت‌ها (بخش دوم تب پشتیبانی)
// ---------------------------------------------------------------------------

const TICKET_STATUS_LABEL = { open: "🟡 در انتظار پاسخ", answered: "🟢 پاسخ داده‌شده", closed: "⚪️ بسته‌شده" };

async function renderTicketsSection() {
  const body = document.getElementById("support-section-body");
  body.innerHTML = skeleton(2);
  try {
    if (ticketView.level === "list") await renderTicketsList(body);
    else await renderTicketThread(body);
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

async function renderTicketsList(body) {
  const tickets = await api("/api/tickets");
  body.innerHTML = `
    <div class="card">
      ${tickets.length === 0 ? `<div class="hint-text" style="margin:0">هنوز تیکتی ثبت نکرده‌ای.</div>` : tickets.map((t) => `
        <div class="admin-list-row" data-open-ticket="${t.id}" style="cursor:pointer">
          <div class="admin-list-row-main">
            <span>${t.subject}</span>
            <span class="hint-text" style="margin:0">${TICKET_STATUS_LABEL[t.status] || t.status}</span>
          </div>
        </div>
      `).join("")}
    </div>
    <button class="btn" id="new-ticket-btn">🎫 ثبت تیکت جدید</button>
    <div class="card" id="new-ticket-form" style="display:none;margin-top:12px">
      <input class="input" id="new-ticket-subject" type="text" placeholder="موضوع تیکت" style="direction:rtl;text-align:right;font-family:var(--font-body);margin-bottom:8px" />
      <textarea class="input" id="new-ticket-message" rows="4" placeholder="توضیح مشکل یا سوال خود را بنویس..." style="direction:rtl;text-align:right;font-family:var(--font-body)"></textarea>
      <button class="btn" id="new-ticket-submit" style="margin-top:8px">ارسال تیکت</button>
    </div>
  `;
  body.querySelectorAll("[data-open-ticket]").forEach((el) => {
    el.onclick = () => {
      ticketView = { level: "thread", ticketId: Number(el.dataset.openTicket) };
      renderTicketsSection();
    };
  });
  document.getElementById("new-ticket-btn").onclick = () => {
    document.getElementById("new-ticket-form").style.display = "";
  };
  document.getElementById("new-ticket-submit").onclick = async () => {
    const subject = document.getElementById("new-ticket-subject").value.trim();
    const message = document.getElementById("new-ticket-message").value.trim();
    if (!subject || !message) { notify("موضوع و متن پیام الزامی است."); return; }
    try {
      const t = await api("/api/tickets", { method: "POST", body: JSON.stringify({ subject, message }) });
      tg.HapticFeedback.notificationOccurred("success");
      ticketView = { level: "thread", ticketId: t.id };
      renderTicketsSection();
    } catch (e) { notify(e.message); }
  };
}

let ticketThreadLastId = 0;

async function renderTicketThread(body) {
  const { ticketId } = ticketView;
  const data = await api(`/api/tickets/${ticketId}/messages`);
  const { ticket, messages } = data;
  ticketThreadLastId = messages.length ? messages[messages.length - 1].id : 0;
  const closed = ticket.status === "closed";
  body.innerHTML = `
    <button class="btn outline small" id="back-to-tickets" style="width:auto;margin-bottom:12px">→ بازگشت به لیست تیکت‌ها</button>
    <div class="eyebrow" style="margin-top:0">${ticket.subject} <span class="hint-text" style="margin-right:6px">${TICKET_STATUS_LABEL[ticket.status] || ""}</span></div>
    <div class="chat-wrap">
      <div class="chat-messages" id="ticket-messages"></div>
      ${closed
        ? `<p class="hint-text" style="text-align:center">این تیکت بسته شده است.</p>`
        : `<form class="chat-input-row" id="ticket-form">
            <input type="text" id="ticket-input" placeholder="پاسخ خود را بنویسید..." autocomplete="off" />
            <button type="submit" class="chat-send-btn" aria-label="ارسال">
              <svg viewBox="0 0 24 24" fill="none"><path d="M4 12 20 4l-6 16-3-7-7-1Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>
            </button>
          </form>
          <button class="btn outline small" id="close-ticket-btn" style="width:auto;margin-top:8px">بستن این تیکت</button>`}
    </div>
  `;
  document.getElementById("back-to-tickets").onclick = () => {
    ticketView = { level: "list" };
    renderTicketsSection();
  };
  const box = document.getElementById("ticket-messages");
  if (messages.length === 0) {
    box.innerHTML = `<div class="state-msg"><span class="ic">🎫</span>پیامی هنوز ثبت نشده.</div>`;
  }
  messages.forEach((m) => {
    if (box.querySelector(".state-msg")) box.innerHTML = "";
    const time = new Date(m.created_at).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${m.sender === "user" ? "mine" : "admin"}`;
    bubble.innerHTML = `<div class="chat-text"></div><div class="chat-time">${time}</div>`;
    bubble.querySelector(".chat-text").textContent = m.message;
    box.appendChild(bubble);
  });
  box.scrollTop = box.scrollHeight;

  if (!closed) {
    const form = document.getElementById("ticket-form");
    const input = document.getElementById("ticket-input");
    form.onsubmit = async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      const time = new Date().toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
      const bubble = document.createElement("div");
      bubble.className = "chat-bubble mine";
      bubble.innerHTML = `<div class="chat-text"></div><div class="chat-time">${time}</div>`;
      bubble.querySelector(".chat-text").textContent = text;
      box.appendChild(bubble);
      box.scrollTop = box.scrollHeight;
      try {
        await api(`/api/tickets/${ticketId}/messages`, { method: "POST", body: JSON.stringify({ message: text }) });
      } catch (e2) {
        notify("خطا: " + e2.message);
      }
    };
    document.getElementById("close-ticket-btn").onclick = async () => {
      if (!confirm("این تیکت بسته شود؟")) return;
      try {
        await api(`/api/tickets/${ticketId}/close`, { method: "POST" });
        renderTicketsSection();
      } catch (e) { notify(e.message); }
    };
  }
}

// ---------------------------------------------------------------------------
// تب خانه
// ---------------------------------------------------------------------------
// آیکون‌های خطی (outline) برای گرید دسترسی سریع — هم‌راستا با آیکون‌های نوار پایین
const ICON_STORE = `<svg viewBox="0 0 24 24" fill="none"><path d="M4 8h16l-1.2 10.2a2 2 0 0 1-2 1.8H7.2a2 2 0 0 1-2-1.8L4 8Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M8 8V6a4 4 0 0 1 8 0v2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;
const ICON_SHIELD = `<svg viewBox="0 0 24 24" fill="none"><path d="M12 2 4 6v6c0 5 3.4 8.7 8 10 4.6-1.3 8-5 8-10V6l-8-4Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M9.5 12.2 11.3 14l3.2-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICON_WALLET = `<svg viewBox="0 0 24 24" fill="none"><rect x="3.5" y="6" width="17" height="12.5" rx="2.2" stroke="currentColor" stroke-width="1.8"/><path d="M3.5 10h17" stroke="currentColor" stroke-width="1.8"/><circle cx="16.5" cy="14.2" r="1.3" fill="currentColor"/></svg>`;
const ICON_PROFILE = `<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="8" r="3.4" stroke="currentColor" stroke-width="1.8"/><path d="M5 19.5c0-3.6 3.1-6.2 7-6.2s7 2.6 7 6.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;
const ICON_SUPPORT = `<svg viewBox="0 0 24 24" fill="none"><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7A2.5 2.5 0 0 1 17.5 16H10l-4 3.5V16H6.5A2.5 2.5 0 0 1 4 13.5v-7Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>`;
const ICON_REFERRAL = `<svg viewBox="0 0 24 24" fill="none"><circle cx="9" cy="8.5" r="2.7" stroke="currentColor" stroke-width="1.8"/><path d="M4 19c0-3 2.3-5 5-5s5 2 5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="17" cy="7.5" r="2.1" stroke="currentColor" stroke-width="1.8"/><path d="M15.5 13c2.2.3 3.8 2 3.8 4.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;
const ICON_TEST = `<svg viewBox="0 0 24 24" fill="none"><path d="M9 3h6M10 3v6.5L5.5 18a2 2 0 0 0 1.8 3h9.4a2 2 0 0 0 1.8-3L14 9.5V3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M8 15h8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;

function setHeaderWallet(amount) {
  const el = document.getElementById("header-wallet-amount");
  if (el) el.textContent = `${fmt(amount)} تومان`;
}

function promoSlides({ me, expiring, referralLink, customBanners }) {
  // بنرهای اول کاروسل، از پنل ادمین > ظاهر > بنرها قابل مدیریت هستند (متن،
  // آیکون، رنگ و مقصد هر بنر). دو بنرِ زیر که به‌صورت خودکار و پویا اضافه
  // می‌شوند (انقضای سرویس / دعوت دوستان) شخصی‌سازی‌شده‌اند و از تنظیمات
  // بنرها مستقل‌اند.
  const slides = [];
  if (expiring && expiring.length > 0) {
    slides.push({
      bg: "linear-gradient(120deg, #2b1608, #4d2510 55%, #7a3a14)",
      icon: "⏰",
      title: "سرویس شما رو به اتمام است",
      sub: `${expiring.length} سرویس نزدیک به تاریخ انقضا. برای تمدید ضربه بزن.`,
      cta: "تمدید سرویس",
      nav: "services",
    });
  }
  (customBanners || []).forEach((b) => slides.push(b));
  if (referralLink) {
    slides.push({
      bg: "linear-gradient(120deg, #0d1420, #142845 55%, #1c3f6e)",
      icon: "🤝",
      title: "دوستاتو دعوت کن",
      sub: "با دعوت از دوستان، اعتبار رایگان به کیف پولت اضافه کن.",
      cta: "مشاهده لینک دعوت",
      nav: "referral",
    });
  }
  if (slides.length === 0) {
    slides.push({
      bg: "linear-gradient(120deg, #0d1a12, #123a20 55%, #17532c)",
      icon: "🛒",
      title: "خرید سرویس جدید!",
      sub: "سرویس مورد نظرتو انتخاب کن و در چند ثانیه فعالش کن!",
      cta: "شروع خرید",
      nav: "store",
    });
  }
  return slides;
}

function renderPromoCarousel(slides) {
  return `
    <div class="promo-carousel">
      <div class="promo-track" id="promo-track">
        ${slides.map((s) => {
          const bgStyle = s.image ? `url('${s.image}') center/cover no-repeat` : s.bg;
          return `
          <div class="promo-slide ${s.image && s.image_only ? "promo-slide-image-only" : ""}" data-nav="${s.nav}" style="--promo-bg:${bgStyle}">
            ${s.image && s.image_only ? "" : `
            <div class="promo-slide-body">
              <div class="promo-slide-title">${s.title}</div>
              <div class="promo-slide-sub">${s.sub}</div>
              <div class="promo-slide-cta">‹ ${s.cta}</div>
            </div>
            <div class="promo-slide-icon">${s.icon}</div>
            `}
          </div>
        `;
        }).join("")}
      </div>
      ${slides.length > 1 ? `<div class="promo-dots">${slides.map((_, i) => `<span class="${i === 0 ? "active" : ""}"></span>`).join("")}</div>` : ""}
    </div>
  `;
}

function wirePromoCarousel(root) {
  const track = root.querySelector("#promo-track");
  if (!track) return;
  track.querySelectorAll(".promo-slide[data-nav]").forEach((el) => {
    el.onclick = () => switchTab(el.dataset.nav);
  });
  const dots = root.querySelectorAll(".promo-dots span");
  if (!dots.length) return;
  track.addEventListener("scroll", () => {
    const idx = Math.round(track.scrollLeft / track.clientWidth);
    dots.forEach((d, i) => d.classList.toggle("active", i === idx));
  }, { passive: true });
}

async function renderHome() {
  content.innerHTML = skeleton(3);
  try {
    const [me, orders, customConfigs, expiring, referral, customBanners] = await Promise.all([
      api("/api/me"),
      api("/api/orders"),
      api("/api/custom-configs").catch(() => []),
      api("/api/expiring").catch(() => []),
      api("/api/referral").catch(() => null),
      api("/api/banners").catch(() => []),
    ]);
    setHeaderWallet(me.wallet_credit);
    const active = orders.filter((o) => o.status === "approved" && !o.is_custom_config);
    const customCards = customConfigs.map((c) => ({
      id: `cc-${c.id}`,
      product_name: `🛠 کانفیگ شخصی «${c.username}» (${c.volume_gb} گیگ / ${c.duration_days} روز)`,
      quantity: 1,
      status: "approved",
      link: c.subscription_url,
      links: c.subscription_url ? [c.subscription_url] : [],
      expires_at: c.expires_at || null,
    }));
    const allActive = [...active, ...customCards];

    const adminTabBtn = document.getElementById("admin-tab-btn");
    if (adminTabBtn) adminTabBtn.style.display = me.is_admin ? "" : "none";

    const slides = promoSlides({ me, expiring, referralLink: referral && referral.link, customBanners });

    content.innerHTML = `
      <div class="home-greet">
        <h1>👋 سلام ${me.first_name}</h1>
        <p>خوش آمدی</p>
      </div>

      ${renderPromoCarousel(slides)}

      <div class="eyebrow">دسترسی سریع</div>
      <div class="quick-grid">
        <div class="quick-item" data-nav="store"><span class="q-label">خرید سرویس جدید</span><span class="q-ic">${ICON_STORE}</span></div>
        <div class="quick-item" data-nav="services"><span class="q-label">سرویس‌های من</span><span class="q-ic">${ICON_SHIELD}</span></div>
        <div class="quick-item" data-nav="wallet"><span class="q-label">کیف پول</span><span class="q-ic">${ICON_WALLET}</span></div>
        <div class="quick-item" data-nav="profile"><span class="q-label">حساب کاربری</span><span class="q-ic">${ICON_PROFILE}</span></div>
        <div class="quick-item full" data-nav="support"><span class="q-label">پشتیبانی</span><span class="q-ic">${ICON_SUPPORT}</span></div>
      </div>

      <div class="eyebrow">سرویس‌های من</div>
      <div class="card">
        ${allActive.length === 0
          ? `<div class="state-msg"><span class="ic">◌</span>هنوز سرویسی ندارید.<br><span style="font-size:11.5px">از فروشگاه یک سرویس بخرید تا اینجا نمایش داده شود.</span></div>`
          : allActive.map(orderCard).join("")}
      </div>
    `;
    content.querySelectorAll(".quick-item[data-nav]").forEach((el) => {
      el.onclick = () => switchTab(el.dataset.nav);
    });
    wirePromoCarousel(content);
    allActive.filter((o) => o.link).forEach((o) => {
      const links = (o.links && o.links.length) ? o.links : [o.link];
      links.forEach((link, idx) => loadSubInfo(`${o.id}-${idx}`, link));
    });
    wireAddToAppButtons(content);
  } catch (e) {
    content.innerHTML = errorState(e.message);
  }
}

// ---------------------------------------------------------------------------
// تب پروفایل
// ---------------------------------------------------------------------------
async function renderProfile() {
  content.innerHTML = skeleton(3);
  try {
    const [me, orders, customConfigs, referral] = await Promise.all([
      api("/api/me"),
      api("/api/orders"),
      api("/api/custom-configs").catch(() => []),
      api("/api/referral").catch(() => ({ enabled: true })),
    ]);
    setHeaderWallet(me.wallet_credit);
    const active = orders.filter((o) => o.status === "approved" && !o.is_custom_config);
    const activeCustom = customConfigs.filter((c) => !c.expires_at || new Date(c.expires_at) > new Date());
    const activeCount = active.length + activeCustom.length;

    const tgUser = (tg.initDataUnsafe && tg.initDataUnsafe.user) || {};
    const username = me.username || tgUser.username || "";
    const photoUrl = tgUser.photo_url || "";
    const initial = (me.first_name || "؟").trim().charAt(0).toUpperCase();

    content.innerHTML = `
      <div class="card profile-hero">
        <div class="profile-avatar-wrap">
          <div class="profile-avatar">${photoUrl ? `<img src="${photoUrl}" alt="" />` : initial}</div>
        </div>
        <div class="profile-name">${me.first_name || ""}</div>
        ${username ? `<div class="profile-meta-row" id="copy-username"><span>📋</span>@${username}</div>` : ""}
        <div class="profile-meta-row" id="copy-userid"><span>📋</span>شناسه: ${me.telegram_id}</div>

        <div class="profile-info-grid">
          <div class="stat-card"><div class="stat-num">${fmt(activeCount)}</div><div class="stat-label">سرویس فعال</div></div>
          <div class="stat-card"><div class="stat-num">${fmt(me.wallet_credit)}</div><div class="stat-label">موجودی کیف پول</div></div>
          <div class="profile-info-row"><span>تاریخ عضویت</span><b>${me.joined_at ? toJalaliStr(me.joined_at) : "-"}</b></div>
        </div>
      </div>

      <div class="card">
        <div class="list-row" data-nav="wallet">
          <div class="list-row-main">
            <div class="list-row-ic line">${ICON_WALLET}</div>
            <div class="list-row-text"><div class="list-row-title">کیف پول و افزایش موجودی</div></div>
          </div>
          <span class="list-row-chev">‹</span>
        </div>
        <div class="list-row" data-nav="services">
          <div class="list-row-main">
            <div class="list-row-ic line">${ICON_SHIELD}</div>
            <div class="list-row-text"><div class="list-row-title">سرویس‌های من</div></div>
          </div>
          <span class="list-row-chev">‹</span>
        </div>
        ${referral.enabled ? `
        <div class="list-row" data-nav="referral">
          <div class="list-row-main">
            <div class="list-row-ic line">${ICON_REFERRAL}</div>
            <div class="list-row-text"><div class="list-row-title">زیرمجموعه‌گیری</div></div>
          </div>
          <span class="list-row-chev">‹</span>
        </div>` : ""}
        <div class="list-row" data-nav="test">
          <div class="list-row-main">
            <div class="list-row-ic line">${ICON_TEST}</div>
            <div class="list-row-text"><div class="list-row-title">دریافت کانفیگ تست</div></div>
          </div>
          <span class="list-row-chev">‹</span>
        </div>
        <div class="list-row" data-nav="support">
          <div class="list-row-main">
            <div class="list-row-ic line">${ICON_SUPPORT}</div>
            <div class="list-row-text"><div class="list-row-title">پشتیبانی</div></div>
          </div>
          <span class="list-row-chev">‹</span>
        </div>
      </div>
    `;
    content.querySelectorAll(".list-row[data-nav]").forEach((el) => {
      el.onclick = () => switchTab(el.dataset.nav);
    });
    const cu = document.getElementById("copy-username");
    if (cu) cu.onclick = (e) => { e.stopPropagation(); navigator.clipboard.writeText("@" + username); tg.HapticFeedback.notificationOccurred("success"); notify("کپی شد."); };
    const ci = document.getElementById("copy-userid");
    if (ci) ci.onclick = (e) => { e.stopPropagation(); navigator.clipboard.writeText(String(me.telegram_id)); tg.HapticFeedback.notificationOccurred("success"); notify("کپی شد."); };
  } catch (e) {
    content.innerHTML = errorState(e.message);
  }
}

function expiringBanner(items) {
  const rows = items.map((it) => {
    const d = new Date(it.expires_at);
    const days = Math.max(0, Math.ceil((d - new Date()) / 86400000));
    return `<div class="expiring-row">
      <span>📦 ${it.product_name}</span>
      <b>${days === 0 ? "امروز منقضی می‌شود" : `${days} روز مانده`}</b>
    </div>`;
  }).join("");
  return `
    <div class="banner banner-warn">
      <div class="banner-title"><span class="ic">⏰</span>سرویس‌های نزدیک به انقضا</div>
      ${rows}
      <div class="banner-hint">برای تمدید به بخش «فروشگاه» بروید.</div>
    </div>
  `;
}

function testConfigCard(status) {
  if (!status.enabled) return "";
  let body;
  if (status.used) {
    body = `<div class="state-msg"><span class="ic">✅</span>شما کانفیگ تست خود را دریافت کرده‌اید.</div>`;
  } else if (status.available <= 0) {
    body = `<div class="state-msg"><span class="ic">◌</span>موجودی کانفیگ تست تمام شده است.</div>`;
  } else {
    body = `<button class="btn" id="test-config-btn">دریافت کانفیگ تست رایگان</button>`;
  }
  return `
    <div class="eyebrow">کانفیگ تست</div>
    <div class="card" id="test-config-card">
      <h3><span class="ic">🧪</span>کانفیگ تست رایگان</h3>
      ${body}
    </div>
  `;
}

async function claimTestConfig(btn) {
  btn.disabled = true;
  btn.textContent = "در حال دریافت...";
  try {
    const r = await api("/api/test-config/claim", { method: "POST" });
    const card = document.getElementById("test-config-card");
    card.innerHTML = `
      <h3><span class="ic">🧪</span>کانفیگ تست رایگان</h3>
      <div class="link-box">${r.link}</div>
      <div class="qr-row">
        <img src="https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(r.link)}" width="96" height="96" alt="QR" />
        <button class="btn small outline" onclick="navigator.clipboard.writeText('${r.link}');tg.HapticFeedback.notificationOccurred('success')">📋 کپی لینک</button>
      </div>
    `;
    tg.HapticFeedback.notificationOccurred("success");
  } catch (e) {
    notify("خطا: " + e.message);
    btn.disabled = false;
    btn.textContent = "دریافت کانفیگ تست رایگان";
  }
}

function referralCard(r) {
  const rows = [];
  if (r.commission_enabled) {
    const cap = r.commission_max_count > 0 ? ` (تا ${fmt(r.commission_max_count)} نفر)` : "";
    rows.push(`<div class="stat-row"><span>پورسانت خرید</span><b>${r.percent}٪ از اولین خرید${cap}</b></div>`);
  }
  if (r.free_config_enabled) {
    rows.push(`<div class="stat-row"><span>کانفیگ رایگان</span><b>با دعوت ${fmt(r.free_config_threshold)} نفر</b></div>`);
  }
  if (r.invite_bonus_enabled) {
    const cap = r.invite_bonus_max_count > 0 ? ` (تا ${fmt(r.invite_bonus_max_count)} دعوت)` : "";
    rows.push(`<div class="stat-row"><span>شارژ به‌ازای دعوت</span><b>${fmt(r.invite_bonus_amount)} تومان${cap}</b></div>`);
  }
  return `
    <div class="eyebrow">زیرمجموعه‌گیری</div>
    <div class="card">
      <h3><span class="ic">🤝</span>دعوت از دوستان</h3>
      ${rows.join("")}
      <div class="stat-row"><span>تعداد زیرمجموعه‌ها</span><b>${fmt(r.count)}</b></div>
      <div class="stat-row"><span>اعتبار کسب‌شده</span><b>${fmt(r.credit)} تومان</b></div>
      ${r.link ? `
      <div class="link-box" style="margin-top:8px">${r.link}</div>
      <button class="btn small outline" id="copy-referral-btn" data-link="${r.link}" style="width:100%;margin-top:8px">📋 کپی لینک دعوت</button>
      ` : ""}
    </div>
  `;
}

// ---------------------------------------------------------------------------
// تب سرویس‌ها (لیست کامل با جست‌وجو و فیلتر وضعیت)
// ---------------------------------------------------------------------------

let servicesFilter = "all"; // all | active | expired | inactive
let servicesQuery = "";

function enterServicesTab() {
  servicesFilter = "all";
  servicesQuery = "";
  renderServices();
}

function serviceStatusKey(o) {
  if (o.status !== "approved") return "inactive";
  if (o.expires_at) {
    if (new Date(o.expires_at) < new Date()) return "expired";
  }
  return "active";
}

async function renderServices() {
  content.innerHTML = skeleton(3);
  try {
    const [orders, customConfigs] = await Promise.all([
      api("/api/orders"),
      api("/api/custom-configs").catch(() => []),
    ]);
    const customCards = customConfigs.map((c) => ({
      id: `cc-${c.id}`,
      custom_config_id: c.id,
      product_name: `🛠 کانفیگ شخصی «${c.username}» (${c.volume_gb} گیگ / ${c.duration_days} روز)`,
      quantity: 1,
      status: "approved",
      is_custom_config: true,
      link: c.subscription_url,
      links: c.subscription_url ? [c.subscription_url] : [],
      expires_at: c.expires_at || null,
    }));
    const all = [...orders, ...customCards];

    const FILTERS = [
      { key: "all", label: "همه" },
      { key: "active", label: "فعال" },
      { key: "expired", label: "منقضی" },
      { key: "inactive", label: "غیرفعال" },
    ];
    const filtered = all.filter((o) => {
      if (servicesFilter !== "all" && serviceStatusKey(o) !== servicesFilter) return false;
      if (servicesQuery && !o.product_name.toLowerCase().includes(servicesQuery.toLowerCase())) return false;
      return true;
    });

    content.innerHTML = `
      <input class="input" id="services-search" type="text" placeholder="جست‌وجوی سرویس..."
        style="direction:rtl;text-align:right;margin-bottom:10px" value="${escHtml(servicesQuery)}" />
      <div class="chip-row">
        ${FILTERS.map((f) => `<button class="chip ${servicesFilter === f.key ? "active" : ""}" data-filter="${f.key}">${f.label}</button>`).join("")}
      </div>
      <div id="services-list">
        ${filtered.length === 0
          ? `<div class="state-msg"><span class="ic">◌</span>سرویسی یافت نشد.</div>`
          : `<div class="card">${filtered.map((o) => serviceStatusKey(o) === "active" ? orderCard(o, { deletable: true }) : serviceInactiveRow(o)).join("")}</div>`}
      </div>
    `;

    document.getElementById("services-search").oninput = (e) => {
      servicesQuery = e.target.value;
      renderServices();
    };
    content.querySelectorAll(".chip[data-filter]").forEach((el) => {
      el.onclick = () => { servicesFilter = el.dataset.filter; renderServices(); };
    });

    filtered.filter((o) => serviceStatusKey(o) === "active" && o.link).forEach((o) => {
      const links = (o.links && o.links.length) ? o.links : [o.link];
      links.forEach((link, idx) => loadSubInfo(`${o.id}-${idx}`, link));
    });
    wireAddToAppButtons(content);
    wireDeleteConfigButtons(content, renderServices);
  } catch (e) {
    content.innerHTML = errorState(e.message);
  }
}

// حذف کامل و برگشت‌ناپذیر یک کانفیگ (محصول یا شخصی) توسط خود کاربر؛ همان
// عملیاتی که در بات اصلی هم از طریق منوی «سفارش‌های من» در دسترس است - هر دو
// از یک دیتابیس حذف می‌کنند، پس نتیجه همه‌جا یکسان و همزمان اعمال می‌شود.
function wireDeleteConfigButtons(root, onDeleted) {
  root.querySelectorAll("[data-del-kind]").forEach((el) => {
    el.onclick = async () => {
      if (!confirm("⚠️ این عملیات غیرقابل بازگشت است.\nاطلاعات و لینک این کانفیگ برای همیشه از سیستم پاک می‌شود. ادامه می‌دهید؟")) return;
      const kind = el.dataset.delKind;
      const id = el.dataset.delId;
      const path = kind === "custom" ? `/api/custom-configs/${id}` : `/api/orders/configs/${id}`;
      el.disabled = true;
      try {
        await api(path, { method: "DELETE" });
        if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
        if (onDeleted) onDeleted();
      } catch (e2) {
        el.disabled = false;
        notify(e2.message);
      }
    };
  });
}

function serviceInactiveRow(o) {
  const key = serviceStatusKey(o);
  const badgeClass = key === "expired" ? "pending" : "rejected";
  const label = key === "expired" ? "منقضی‌شده" : (o.status === "pending" ? "در انتظار تایید" : "رد‌شده");
  const exp = o.expires_at ? toJalaliStr(o.expires_at) : "";
  return `
    <div class="order-block">
      <div class="stat-row">
        <span>${o.product_name}${o.quantity > 1 ? ` × ${o.quantity}` : ""}</span>
        <span class="badge ${badgeClass}">${label}${exp ? ` · ${exp}` : ""}</span>
      </div>
    </div>
  `;
}

function orderCard(o, opts = {}) {
  const deletable = !!opts.deletable;
  const exp = o.expires_at ? toJalaliStr(o.expires_at) : "نامحدود";
  const links = (o.links && o.links.length) ? o.links : (o.link ? [o.link] : []);
  return `
    <div class="order-block">
      <div class="stat-row"><span>${o.product_name}${o.quantity > 1 ? ` × ${o.quantity}` : ""}</span><span class="badge approved">فعال تا ${exp}</span></div>
      ${links.map((link, idx) => {
        const delKind = o.is_custom_config ? "custom" : "order";
        const delId = o.is_custom_config ? o.custom_config_id : (o.config_ids && o.config_ids[idx]);
        return `
      ${links.length > 1 ? `<div class="hint-text" style="margin:8px 0 4px">🔢 کانفیگ ${idx + 1} از ${links.length}</div>` : ""}
      <div class="sub-info" id="sub-info-${o.id}-${idx}"><div class="sub-info-loading">در حال دریافت اطلاعات مصرف...</div></div>
      <div class="link-box">${link}</div>
      <div class="qr-row">
        <img src="https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(link)}" width="96" height="96" alt="QR" />
        <button class="btn small outline" onclick="navigator.clipboard.writeText('${link}');tg.HapticFeedback.notificationOccurred('success')">📋 کپی لینک</button>
        ${deletable && delId ? `<button class="btn small outline danger" data-del-kind="${delKind}" data-del-id="${delId}">🗑 حذف کامل</button>` : ""}
      </div>
      ${renderAddToAppBlock(`${o.id}-${idx}`, link, o.product_name)}
      `;
      }).join("")}
    </div>
  `;
}

// ---------------------------------------------------------------------------
// افزودن خودکار اشتراک به اپلیکیشن‌های وی‌پی‌ان (iOS / اندروید)
// ---------------------------------------------------------------------------

const VPN_APPS = {
  ios: [
    {
      key: "shadowrocket", name: "Shadowrocket", icon: "🚀",
      store: "https://apps.apple.com/app/id932747118",
      deepLink: (sub, remark) => `shadowrocket://add/sub/${btoa(unescape(encodeURIComponent(sub)))}?remark=${encodeURIComponent(remark)}`,
    },
    {
      key: "streisand", name: "Streisand", icon: "🎗",
      store: "https://apps.apple.com/app/id6450534064",
      deepLink: (sub) => `streisand://import/${encodeURIComponent(sub)}`,
    },
    {
      key: "v2box", name: "V2Box", icon: "📦",
      store: "https://apps.apple.com/app/id6446814690",
      deepLink: (sub, remark) => `v2box://install-sub?url=${encodeURIComponent(sub)}&name=${encodeURIComponent(remark)}`,
    },
  ],
  android: [
    {
      key: "hiddify", name: "Hiddify Next", icon: "🛡",
      store: "https://play.google.com/store/apps/details?id=app.hiddify.com",
      androidPackage: "app.hiddify.com",
      deepLink: (sub, remark) => `hiddify://import/${encodeURIComponent(sub)}#${encodeURIComponent(remark)}`,
    },
    {
      key: "v2raytun", name: "v2RayTun", icon: "⚡",
      store: "https://play.google.com/store/apps/details?id=com.v2raytun.android",
      androidPackage: "com.v2raytun.android",
      deepLink: (sub) => `v2raytun://import/${encodeURIComponent(sub)}`,
    },
    {
      key: "v2box", name: "V2Box", icon: "📦",
      store: "https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box",
      androidPackage: "dev.hexasoftware.v2box",
      deepLink: (sub, remark) => `v2box://install-sub?url=${encodeURIComponent(sub)}&name=${encodeURIComponent(remark)}`,
    },
    {
      key: "v2rayng", name: "v2rayNG", icon: "🔷",
      store: "https://github.com/2dust/v2rayNG/releases/latest",
      androidPackage: "com.v2ray.ang",
      deepLink: (sub, remark) => `v2rayng://install-sub?url=${encodeURIComponent(sub)}&name=${encodeURIComponent(remark)}`,
    },
  ],
};

function renderAddToAppBlock(orderId, link, productName) {
  return `
    <div class="add-to-app-wrap" style="margin-top:10px">
      <button class="btn small outline add-to-app-toggle" data-order-id="${orderId}" style="width:100%">📲 افزودن به برنامه</button>
      <div class="add-to-app-panel" id="add-to-app-panel-${orderId}" data-link="${escHtml(link)}" data-name="${escHtml(productName || "ShopVPN")}" style="display:none;margin-top:8px"></div>
    </div>
  `;
}

function addToAppPlatformPickerHtml(orderId) {
  return `
    <div style="display:flex;gap:8px">
      <button class="btn small add-to-app-platform" data-order-id="${orderId}" data-platform="ios" style="width:50%">📱 آیفون (iOS)</button>
      <button class="btn small add-to-app-platform" data-order-id="${orderId}" data-platform="android" style="width:50%">🤖 اندروید</button>
    </div>
  `;
}

function addToAppListHtml(orderId, platform) {
  const apps = VPN_APPS[platform] || [];
  return `
    <p class="hint-text" style="margin:0 0 8px">برنامه‌ات رو انتخاب کن: «دانلود» صفحه‌ی برنامه رو تو مارکت باز می‌کنه، «افزودن» اگه نصب باشه اشتراک رو مستقیم بهش می‌فرسته.</p>
    <div style="display:flex;flex-direction:column;gap:6px">
      ${apps.map((a) => `
        <div class="add-to-app-row" style="display:flex;align-items:center;gap:6px">
          <span style="flex:1;text-align:right;font-size:12.5px;color:var(--text-dim,#c9c4e0);padding:0 4px">${a.icon} ${a.name}</span>
          <button class="btn small outline add-to-app-download" data-platform="${platform}" data-app="${a.key}" style="flex:0 0 auto">⬇️ دانلود</button>
          <button class="btn small add-to-app-pick" data-order-id="${orderId}" data-platform="${platform}" data-app="${a.key}" style="flex:0 0 auto">📲 افزودن</button>
        </div>
      `).join("")}
    </div>
    <button class="btn small outline add-to-app-back" data-order-id="${orderId}" style="width:100%;margin-top:8px">⬅️ بازگشت</button>
  `;
}

function tryOpenAppOrStore(deepLink, storeUrl, androidPackage = "") {
  // Telegram Mini Apps cannot use tg.openLink() for arbitrary custom schemes:
  // Telegram documents that openLink is restricted to allowed URL schemes.
  // Also, assigning window.location to hiddify:// / v2rayng:// navigates the
  // Telegram WebView and produces ERR_UNKNOWN_URL_SCHEME.
  //
  // So we first ask the OS URL handler through a real anchor click. On
  // Android, if that is intercepted by the WebView, we make a second attempt
  // with an Android intent:// URL bound to the app package.
  let backgrounded = false;
  let settled = false;
  let intentTried = false;

  const markBackgrounded = () => { backgrounded = true; };
  const cleanup = () => {
    document.removeEventListener("visibilitychange", markBackgrounded);
    window.removeEventListener("blur", markBackgrounded);
  };
  const isAndroid = /Android/i.test(navigator.userAgent || "");

  document.addEventListener("visibilitychange", markBackgrounded);
  window.addEventListener("blur", markBackgrounded);

  const launch = (url) => {
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.style.display = "none";
    document.body.appendChild(a);
    try { a.click(); } catch (e) {}
    setTimeout(() => { try { a.remove(); } catch (e) {} }, 1000);
  };

  // First attempt: direct custom-scheme URL.
  launch(deepLink);

  // Android fallback: intent:// lets Android resolve the package without
  // navigating the Telegram WebView to the custom scheme itself.
  const tryIntent = () => {
    if (settled || backgrounded || !isAndroid || !androidPackage || intentTried) return;
    intentTried = true;
    try {
      const u = new URL(deepLink);
      let body = `${u.host}${u.pathname}${u.search}`;
      // The fragment is optional for these import links and conflicts with
      // Android's #Intent separator, so omit it in the package fallback.
      const intentUrl = `intent://${body}#Intent;scheme=${u.protocol.slice(0, -1)};package=${androidPackage};end`;
      launch(intentUrl);
    } catch (e) {}
  };

  setTimeout(tryIntent, 350);

  const fallback = () => {
    if (settled) return;
    settled = true;
    cleanup();
    if (!backgrounded) {
      if (tg && typeof tg.openLink === "function") {
        tg.openLink(storeUrl);
      } else {
        window.open(storeUrl, "_blank", "noopener,noreferrer");
      }
    }
  };

  // Allow enough time for the OS to switch to the installed app.
  setTimeout(fallback, 2200);
}

function wireAddToAppButtons(root) {
  root.querySelectorAll(".add-to-app-toggle").forEach((btn) => {
    btn.onclick = () => {
      const orderId = btn.dataset.orderId;
      const panel = document.getElementById(`add-to-app-panel-${orderId}`);
      if (!panel) return;
      const isOpen = panel.style.display !== "none";
      if (isOpen) {
        panel.style.display = "none";
        return;
      }
      panel.innerHTML = addToAppPlatformPickerHtml(orderId);
      panel.style.display = "";
      wireAddToAppButtons(panel);
    };
  });
  root.querySelectorAll(".add-to-app-platform").forEach((btn) => {
    btn.onclick = () => {
      const orderId = btn.dataset.orderId;
      const platform = btn.dataset.platform;
      const panel = document.getElementById(`add-to-app-panel-${orderId}`);
      if (!panel) return;
      panel.innerHTML = addToAppListHtml(orderId, platform);
      wireAddToAppButtons(panel);
    };
  });
  root.querySelectorAll(".add-to-app-back").forEach((btn) => {
    btn.onclick = () => {
      const orderId = btn.dataset.orderId;
      const panel = document.getElementById(`add-to-app-panel-${orderId}`);
      if (!panel) return;
      panel.innerHTML = addToAppPlatformPickerHtml(orderId);
      wireAddToAppButtons(panel);
    };
  });
  root.querySelectorAll(".add-to-app-download").forEach((btn) => {
    btn.onclick = () => {
      const platform = btn.dataset.platform;
      const appKey = btn.dataset.app;
      const app = (VPN_APPS[platform] || []).find((a) => a.key === appKey);
      if (!app) return;
      tg.HapticFeedback.notificationOccurred("success");
      if (tg && typeof tg.openLink === "function") {
        tg.openLink(app.store);
      } else {
        window.open(app.store, "_blank", "noopener,noreferrer");
      }
    };
  });
  root.querySelectorAll(".add-to-app-pick").forEach((btn) => {
    btn.onclick = () => {
      const orderId = btn.dataset.orderId;
      const platform = btn.dataset.platform;
      const appKey = btn.dataset.app;
      const panel = document.getElementById(`add-to-app-panel-${orderId}`);
      if (!panel) return;
      const link = panel.dataset.link;
      const name = panel.dataset.name;
      const app = (VPN_APPS[platform] || []).find((a) => a.key === appKey);
      if (!app) return;
      tg.HapticFeedback.notificationOccurred("success");
      tryOpenAppOrStore(app.deepLink(link, name), app.store, app.androidPackage);
    };
  });
}

function fmtGB(bytes) {
  return (bytes / (1024 ** 3)).toFixed(2);
}

async function loadSubInfo(orderId, link) {
  const box = document.getElementById(`sub-info-${orderId}`);
  if (!box) return;
  try {
    const info = await api(`/api/sub-info?link=${encodeURIComponent(link)}`);
    if (!box.isConnected) return;
    if (!info.ok) {
      box.innerHTML = `<div class="sub-info-error">⚠️ اطلاعات مصرف در دسترس نیست</div>`;
      return;
    }
    const used = info.upload + info.download;
    const total = info.total;
    let usageHtml;
    if (total > 0) {
      const percent = Math.min(100, Math.round((used / total) * 100));
      const remaining = Math.max(0, total - used);
      usageHtml = `
        <div class="sub-info-row"><span>مصرف</span><b>${fmtGB(used)} از ${fmtGB(total)} گیگابایت</b></div>
        <div class="progress-track"><div class="progress-fill" style="width:${percent}%"></div></div>
        <div class="sub-info-row"><span>باقی‌مانده</span><b>${fmtGB(remaining)} گیگابایت</b></div>
      `;
    } else {
      usageHtml = `<div class="sub-info-row"><span>مصرف</span><b>${fmtGB(used)} گیگابایت (نامحدود)</b></div>`;
    }
    let expiryHtml = `<div class="sub-info-row"><span>انقضا</span><b>نامحدود</b></div>`;
    if (info.expire) {
      const expDate = new Date(info.expire * 1000);
      const daysLeft = Math.max(0, Math.ceil((expDate - new Date()) / 86400000));
      expiryHtml = `<div class="sub-info-row"><span>انقضا</span><b>${toJalaliStr(expDate)} (${daysLeft} روز مانده)</b></div>`;
    }
    box.innerHTML = usageHtml + expiryHtml;
  } catch (e) {
    if (box.isConnected) box.innerHTML = `<div class="sub-info-error">⚠️ اطلاعات مصرف در دسترس نیست</div>`;
  }
}

// ---------------------------------------------------------------------------
// کارت بانکی + آپلود رسید (مشترک بین «شارژ کیف پول» و «پرداخت سفارش»)
// ---------------------------------------------------------------------------
// کش ساده برای لیست درگاه‌های سفارشی فعال (در طول یک نشست کافی است یک‌بار بگیریم)
let _customGatewaysCache = null;
async function fetchCustomGateways() {
  if (_customGatewaysCache) return _customGatewaysCache;
  try {
    _customGatewaysCache = await api("/api/gateways");
  } catch (e) {
    _customGatewaysCache = [];
  }
  return _customGatewaysCache;
}

function renderReceiptCard(box, { amount, cardNumber, cardHolder, sendReceipt, successText, cryptoEnabled, createCryptoInvoice, customGateways, createCustomGatewayInvoice, cardToCardEnabled }) {
  customGateways = customGateways || [];
  // اگر ادمین کارت‌به‌کارت دستی را غیرفعال کرده باشد (card_to_card_enabled=0)، این بخش
  // باید مثل بات اصلی مخفی شود؛ پیش‌فرض (undefined، برای سازگاری با پاسخ‌های قدیمی) فعال است.
  const cardEnabled = cardToCardEnabled !== false && !!cardNumber;
  const noPaymentMethod = !cardEnabled && !cryptoEnabled && !customGateways.length;
  const customGatewaysHtml = customGateways.length ? `
    <div style="display:flex;align-items:center;gap:8px;margin:16px 0">
      <div style="flex:1;height:1px;background:var(--border,rgba(255,255,255,.1))"></div>
      <span class="hint-text" style="margin:0">یا</span>
      <div style="flex:1;height:1px;background:var(--border,rgba(255,255,255,.1))"></div>
    </div>
    ${customGateways.map(gw => `
      <button class="btn outline custom-gw-btn" data-key="${gw.key}" style="width:100%;margin-bottom:8px">🔌 پرداخت با ${escHtml(gw.name)}</button>
    `).join("")}
    <div id="custom-gw-error" class="field-error"></div>
  ` : "";

  if (noPaymentMethod) {
    box.innerHTML = `<div class="state-msg"><span class="ic">⚠️</span>در حال حاضر روش پرداخت فعالی موجود نیست. لطفاً با پشتیبانی تماس بگیرید.</div>`;
    return;
  }

  box.innerHTML = `
    ${cardEnabled ? `
    <h3><span class="ic">💳</span>واریز و ارسال رسید</h3>
    <div class="bank-card">
      <div class="bank-card-top">
        <div class="bank-card-chip"></div>
        <div class="bank-card-brand">SHOP PAY</div>
      </div>
      <div class="bank-card-number">${formatCardNumber(cardNumber)}</div>
      <div class="bank-card-bottom">
        <div>
          <div class="bank-card-holder-label">به نام</div>
          <div class="bank-card-holder">${cardHolder || "---"}</div>
        </div>
        <div class="bank-card-amount">${fmt(amount)} تومان</div>
      </div>
    </div>
    <button class="copy-chip" id="copy-card-btn" style="width:100%;margin-bottom:12px">📋 کپی شماره کارت</button>

    <label class="receipt-upload" id="receipt-drop">
      <span class="ic">🧾</span>
      <span id="receipt-label">مبلغ را واریز کن و عکس رسید را همینجا انتخاب کن</span>
      <input type="file" id="receipt-file" accept="image/*" />
    </label>
    <img id="receipt-preview" class="receipt-preview" style="display:none" />
    <button class="btn" id="send-receipt-btn" disabled>ارسال رسید برای تایید</button>
    ` : ""}

    ${cryptoEnabled ? `
      <div style="display:flex;align-items:center;gap:8px;margin:16px 0">
        <div style="flex:1;height:1px;background:var(--border,rgba(255,255,255,.1))"></div>
        <span class="hint-text" style="margin:0">یا</span>
        <div style="flex:1;height:1px;background:var(--border,rgba(255,255,255,.1))"></div>
      </div>
      <button class="btn outline" id="pay-crypto-btn" style="width:100%">🪙 پرداخت با ارز دیجیتال (تایید آنی)</button>
      <div id="crypto-pay-error" class="field-error"></div>
    ` : ""}

    ${customGatewaysHtml}
  `;

  if (cardEnabled) {
    box.querySelector("#copy-card-btn").onclick = () => {
      navigator.clipboard.writeText(String(cardNumber).replace(/\s/g, ""));
      tg.HapticFeedback.notificationOccurred("success");
    };

    const fileInput = box.querySelector("#receipt-file");
    const preview = box.querySelector("#receipt-preview");
    const drop = box.querySelector("#receipt-drop");
    const sendBtn = box.querySelector("#send-receipt-btn");

    fileInput.onchange = () => {
      const file = fileInput.files[0];
      if (!file) return;
      drop.classList.add("has-file");
      box.querySelector("#receipt-label").textContent = "✅ عکس رسید انتخاب شد";
      preview.src = URL.createObjectURL(file);
      preview.style.display = "block";
      sendBtn.disabled = false;
    };

    sendBtn.onclick = async () => {
      const file = fileInput.files[0];
      if (!file) return;
      sendBtn.disabled = true;
      sendBtn.textContent = "در حال ارسال...";
      try {
        await sendReceipt(file);
        tg.HapticFeedback.notificationOccurred("success");
        box.innerHTML = `<div class="state-msg"><span class="ic">✅</span>${successText}</div>`;
      } catch (e) {
        notify("خطا: " + e.message);
        sendBtn.disabled = false;
        sendBtn.textContent = "ارسال رسید برای تایید";
      }
    };
  }

  if (cryptoEnabled) {
    const cryptoBtn = box.querySelector("#pay-crypto-btn");
    const cryptoErr = box.querySelector("#crypto-pay-error");
    cryptoBtn.onclick = async () => {
      cryptoErr.textContent = "";
      cryptoBtn.disabled = true;
      cryptoBtn.textContent = "در حال ساخت فاکتور...";
      try {
        const res = await createCryptoInvoice();
        tg.HapticFeedback.notificationOccurred("success");
        box.innerHTML = `
          <div class="state-msg">
            <span class="ic">🪙</span>
            فاکتور پرداخت ساخته شد. روی دکمه‌ی زیر بزن، ارز و مبلغ رو انتخاب کن و پرداخت رو تکمیل کن.
            <br/>به‌محض تایید تراکنش روی بلاک‌چین، به‌صورت خودکار سفارش/کیف‌پول شما تسویه می‌شود.
          </div>
          <button class="btn" id="open-invoice-btn" style="width:100%;margin-top:12px">🔗 رفتن به صفحه‌ی پرداخت</button>
        `;
        box.querySelector("#open-invoice-btn").onclick = () => tg.openLink(res.invoice_url);
        tg.openLink(res.invoice_url);
      } catch (e) {
        cryptoErr.textContent = e.message;
        cryptoBtn.disabled = false;
        cryptoBtn.textContent = "🪙 پرداخت با ارز دیجیتال (تایید آنی)";
      }
    };
  }

  if (customGateways.length && createCustomGatewayInvoice) {
    const cgErr = box.querySelector("#custom-gw-error");
    box.querySelectorAll(".custom-gw-btn").forEach((btn) => {
      const gwName = btn.textContent;
      btn.onclick = async () => {
        cgErr.textContent = "";
        box.querySelectorAll(".custom-gw-btn").forEach((b) => (b.disabled = true));
        btn.textContent = "در حال ساخت فاکتور...";
        try {
          const res = await createCustomGatewayInvoice(btn.dataset.key);
          tg.HapticFeedback.notificationOccurred("success");
          box.innerHTML = `
            <div class="state-msg">
              <span class="ic">🔌</span>
              فاکتور پرداخت ساخته شد. روی دکمه‌ی زیر بزن و پرداخت رو تکمیل کن.
              <br/>پس از تایید پرداخت، به‌صورت خودکار سفارش/کیف‌پول شما تسویه می‌شود.
            </div>
            <button class="btn" id="open-invoice-btn" style="width:100%;margin-top:12px">🔗 رفتن به صفحه‌ی پرداخت</button>
          `;
          if (res.invoice_url) {
            box.querySelector("#open-invoice-btn").onclick = () => tg.openLink(res.invoice_url);
            tg.openLink(res.invoice_url);
          } else {
            box.querySelector("#open-invoice-btn").style.display = "none";
          }
        } catch (e) {
          cgErr.textContent = e.message;
          box.querySelectorAll(".custom-gw-btn").forEach((b) => (b.disabled = false));
          btn.textContent = gwName;
        }
      };
    });
  }
}

// ---------------------------------------------------------------------------
// تب فروشگاه
// ---------------------------------------------------------------------------
let storeCategoryView = null; // null = لیست دسته‌بندی‌ها، وگرنه شناسه دسته‌بندی انتخاب‌شده

async function renderStore() {
  content.innerHTML = skeleton(4);
  try {
    const categories = await api("/api/catalog");
    if (categories.length === 0) {
      content.innerHTML = `<div class="state-msg"><span class="ic">◌</span>در حال حاضر محصولی موجود نیست.</div>`;
      return;
    }
    window._storeProducts = {};
    categories.forEach((c) => c.products.forEach((p) => { window._storeProducts[p.id] = p; }));
    window._storeCategories = categories;

    if (storeCategoryView == null) {
      let customConfigRow = "";
      try {
        const cfgInfo = await api("/api/custom-config/info");
        if (cfgInfo.enabled || cfgInfo.reseller_available) {
          customConfigRow = `
            <div class="list-row" id="custom-config-entry-row">
              <div class="list-row-main">
                <div class="list-row-ic">🛠</div>
                <div class="list-row-text">
                  <span class="list-row-title">ساخت کانفیگ شخصی</span>
                  <span class="list-row-sub">${cfgInfo.reseller_available ? "با اعتبار نمایندگی یا خرید مستقیم" : "حجم و مدت دلخواه خودت را انتخاب کن"}</span>
                </div>
              </div>
              <span class="list-row-chev">‹</span>
            </div>`;
        }
      } catch (e) { /* اگه این بخش غیرفعال/خطا بود، بی‌صدا رد شو */ }
      content.innerHTML = `
        <div class="eyebrow">یک دسته را انتخاب کنید</div>
        ${customConfigRow}
        ${categories.map((c) => `
          <div class="list-row" data-cat="${c.id}">
            <div class="list-row-main">
              <div class="list-row-ic">🏬</div>
              <div class="list-row-text">
                <span class="list-row-title">${c.name}</span>
                <span class="list-row-sub">${c.products.length} محصول</span>
              </div>
            </div>
            <span class="list-row-chev">‹</span>
          </div>
        `).join("")}
      `;
      const ccRow = document.getElementById("custom-config-entry-row");
      if (ccRow) ccRow.onclick = renderCustomConfigBuilder;
      content.querySelectorAll(".list-row[data-cat]").forEach((el) => {
        el.onclick = () => { storeCategoryView = parseInt(el.dataset.cat, 10); renderStore(); };
      });
      return;
    }

    const cat = categories.find((c) => c.id === storeCategoryView);
    if (!cat) { storeCategoryView = null; return renderStore(); }
    content.innerHTML = `
      <div class="list-row" id="store-back-row">
        <div class="list-row-main">
          <span class="list-row-ic">‹</span>
          <div class="list-row-text"><span class="list-row-title">بازگشت به دسته‌بندی‌ها</span></div>
        </div>
      </div>
      <div class="eyebrow">${cat.name}</div>
      <div class="card">
        <h3><span class="ic">▣</span>${cat.name}</h3>
        ${cat.products.map((p) => `
          <div class="product">
            <div>
              <div class="product-name">${p.name}</div>
              <div class="price">${fmt(p.price)} تومان</div>
            </div>
            <button class="btn small" ${p.stock <= 0 ? "disabled" : ""}
              onclick="openProductPurchase(${p.id})">
              ${p.stock <= 0 ? "ناموجود" : "خرید"}
            </button>
          </div>
        `).join("")}
      </div>
    `;
    document.getElementById("store-back-row").onclick = () => { storeCategoryView = null; renderStore(); };
  } catch (e) {
    content.innerHTML = errorState(e.message);
  }
}

function enterStoreTab() {
  storeCategoryView = null;
  renderStore();
}

function openProductPurchase(productId) {
  const p = (window._storeProducts || {})[productId];
  if (!p) return;
  renderPurchasePanel(productId, p, 1, null);
}

function renderPurchasePanel(productId, p, quantity, discountCode) {
  quantity = Math.max(1, Math.min(quantity, p.stock));
  const total = p.price * quantity;
  content.innerHTML = `
    <button class="btn outline small" id="back-to-store-btn" style="width:auto;margin-bottom:12px">→ بازگشت به فروشگاه</button>
    <div class="eyebrow">خرید محصول</div>
    <div class="card">
      <h3><span class="ic">📦</span>${p.name}</h3>
      <div class="stat-row"><span>قیمت واحد</span><b>${fmt(p.price)} تومان</b></div>
      ${p.is_auto_provision
        ? `<div class="stat-row"><span>تأمین</span><b>⚡️ خودکار و لحظه‌ای</b></div>`
        : `<div class="stat-row"><span>موجودی</span><b>${p.stock} عدد</b></div>`}
      <div class="qty-stepper">
        <button class="btn small outline" id="qty-dec-btn" ${quantity <= 1 ? "disabled" : ""}>➖</button>
        <span class="qty-value">${quantity}</span>
        <button class="btn small outline" id="qty-inc-btn" ${quantity >= p.stock ? "disabled" : ""}>➕</button>
      </div>
      <input class="input" id="purchase-discount-code" type="text" placeholder="کد تخفیف (اختیاری)"
        value="${discountCode ? escHtml(discountCode) : ""}" style="direction:ltr;text-align:left;margin-top:10px" />
      <div class="stat-row" style="margin-top:10px"><span>جمع کل</span><b>${fmt(total)} تومان</b></div>
      <button class="btn" id="confirm-purchase-btn" style="margin-top:10px">✅ تایید و ادامه</button>
    </div>
  `;
  document.getElementById("back-to-store-btn").onclick = renderStore;
  document.getElementById("qty-dec-btn").onclick = () => {
    const code = document.getElementById("purchase-discount-code").value.trim();
    renderPurchasePanel(productId, p, quantity - 1, code);
  };
  document.getElementById("qty-inc-btn").onclick = () => {
    const code = document.getElementById("purchase-discount-code").value.trim();
    renderPurchasePanel(productId, p, quantity + 1, code);
  };
  document.getElementById("confirm-purchase-btn").onclick = () => {
    const code = document.getElementById("purchase-discount-code").value.trim();
    buyProduct(productId, quantity, code || null);
  };
}

async function buyProduct(productId, quantity, code) {
  try {
    const result = await api("/api/orders", {
      method: "POST",
      body: JSON.stringify({ product_id: productId, quantity: quantity || 1, discount_code: code || null }),
    });
    if (result.status === "approved") {
      tg.HapticFeedback.notificationOccurred("success");
      notify("✅ خرید تایید شد! از تب خانه لینک را ببینید.");
      switchTab("home");
    } else {
      content.innerHTML = `
        <button class="btn outline small" id="back-to-store-btn" style="width:auto;margin-bottom:12px">→ بازگشت به فروشگاه</button>
        <div class="eyebrow">پرداخت سفارش</div>
        <div class="card" id="order-payment-card"></div>
      `;
      document.getElementById("back-to-store-btn").onclick = renderStore;
      const customGateways = await fetchCustomGateways();
      renderReceiptCard(document.getElementById("order-payment-card"), {
        amount: result.final_price,
        cardNumber: result.card_number,
        cardHolder: result.card_holder,
        cardToCardEnabled: result.card_to_card_enabled,
        successText: "رسید ارسال شد. پس از تایید ادمین، کانفیگ از تب خانه در دسترس شما خواهد بود.",
        sendReceipt: async (file) => {
          const fd = new FormData();
          fd.append("photo", file);
          await apiUpload(`/api/orders/${result.order_id}/receipt`, fd);
        },
        cryptoEnabled: result.crypto_enabled,
        createCryptoInvoice: async () => api(`/api/orders/${result.order_id}/crypto-invoice`, { method: "POST" }),
        customGateways,
        createCustomGatewayInvoice: async (key) => api(`/api/orders/${result.order_id}/custom-invoice/${key}`, { method: "POST" }),
      });
    }
  } catch (e) {
    notify("خطا: " + e.message);
  }
}

// ---------------------------------------------------------------------------
// ساخت کانفیگ شخصی (اتصال مستقیم به پنل VPN) - معادل CustomConfigFlow ربات؛
// از داخل تب فروشگاه در دسترس است.
// ---------------------------------------------------------------------------

function _randomCustomUsername() {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let s = "u";
  for (let i = 0; i < 8; i++) s += chars[Math.floor(Math.random() * chars.length)];
  return s;
}

function _priceForVolume(tiers, gb) {
  for (const t of tiers) {
    if (gb >= t.from_gb && (t.to_gb == null || gb <= t.to_gb)) return gb * t.price_per_gb;
  }
  return 0;
}

async function renderCustomConfigBuilder() {
  content.innerHTML = skeleton(3);
  try {
    const info = await api("/api/custom-config/info");
    if (!info.enabled && !info.reseller_available) {
      content.innerHTML = `<div class="state-msg"><span class="ic">◌</span>این بخش در حال حاضر غیرفعال است.</div>`;
      return;
    }
    let useCredit = info.reseller_available; // اگه اعتبار نمایندگی داره، پیش‌فرض روی رایگان باشه
    let username = _randomCustomUsername();
    let volume = info.reseller_available ? Math.min(info.reseller_credit_gb, 10) || 1 : info.min_gb;

    const draw = () => {
      const price = useCredit ? 0 : _priceForVolume(info.tiers, volume);
      content.innerHTML = `
        <button class="btn outline small" id="back-to-store-btn" style="width:auto;margin-bottom:12px">→ بازگشت به فروشگاه</button>
        <div class="eyebrow">🛠 ساخت کانفیگ شخصی</div>
        <div class="card">
          ${info.reseller_available ? `
            <div class="stat-row">
              <span>روش ساخت</span>
              <div>
                <button class="btn small ${useCredit ? "" : "outline"}" id="cc-mode-credit">اعتبار نمایندگی (${fmt(info.reseller_credit_gb)} گیگ)</button>
                <button class="btn small ${useCredit ? "outline" : ""}" id="cc-mode-pay">خرید</button>
              </div>
            </div>` : ""}
          <label class="field-label">نام کاربری</label>
          <div style="display:flex;gap:8px">
            <input class="input" id="cc-username" type="text" value="${escHtml(username)}" style="direction:ltr;text-align:left" />
            <button class="btn outline small" id="cc-random-btn">🎲 تصادفی</button>
          </div>
          <label class="field-label" style="margin-top:10px">حجم (گیگابایت)</label>
          <input class="input" id="cc-volume" type="number" value="${volume}"
            min="${useCredit ? 1 : info.min_gb}" max="${useCredit ? info.reseller_credit_gb : info.max_gb}" style="direction:ltr;text-align:left" />
          <div class="stat-row" style="margin-top:8px"><span>مدت اعتبار</span><b>${info.duration_days} روز</b></div>
          ${!useCredit ? `
            <div class="pricing-table" style="margin-top:10px;font-size:13px">
              ${info.tiers.map((t) => `<div class="stat-row"><span>${t.from_gb} تا ${t.to_gb == null ? "به‌بالا" : t.to_gb} گیگ</span><b>${fmt(t.price_per_gb)} تومان/گیگ</b></div>`).join("")}
            </div>
            <div class="stat-row" style="margin-top:10px"><span>موجودی کیف پول</span><b>${fmt(info.wallet_credit)} تومان</b></div>
          ` : ""}
          <div class="stat-row" style="margin-top:10px"><span>${useCredit ? "هزینه" : "جمع کل"}</span><b>${useCredit ? "رایگان (از اعتبار)" : fmt(price) + " تومان"}</b></div>
          <button class="btn" id="cc-submit-btn" style="margin-top:10px">✅ ساخت کانفیگ</button>
        </div>
      `;
      document.getElementById("back-to-store-btn").onclick = renderStore;
      if (info.reseller_available) {
        document.getElementById("cc-mode-credit").onclick = () => { useCredit = true; volume = Math.min(volume, info.reseller_credit_gb) || 1; draw(); };
        document.getElementById("cc-mode-pay").onclick = () => { useCredit = false; volume = Math.max(volume, info.min_gb); draw(); };
      }
      document.getElementById("cc-random-btn").onclick = () => { username = _randomCustomUsername(); draw(); };
      document.getElementById("cc-username").oninput = (e) => { username = e.target.value; };
      document.getElementById("cc-volume").oninput = (e) => { volume = parseInt(e.target.value, 10) || 0; };
      document.getElementById("cc-submit-btn").onclick = () => submitCustomConfig(username, volume, useCredit, info);
    };
    draw();
  } catch (e) {
    content.innerHTML = errorState(e.message);
  }
}

async function submitCustomConfig(username, volumeGb, useCredit, info) {
  username = (username || "").trim();
  if (!/^[A-Za-z0-9_]{3,20}$/.test(username)) {
    notify("نام کاربری نامعتبر است. فقط حروف انگلیسی، عدد و آندرلاین، بین ۳ تا ۲۰ کاراکتر.");
    return;
  }
  if (!volumeGb || volumeGb <= 0) { notify("حجم را درست وارد کنید."); return; }
  try {
    const result = await api("/api/custom-configs", {
      method: "POST",
      body: JSON.stringify({ username, volume_gb: volumeGb, use_credit: !!useCredit }),
    });
    if (result.status === "approved") {
      tg.HapticFeedback.notificationOccurred("success");
      content.innerHTML = `
        <div class="eyebrow">🛠 کانفیگ شخصی شما آماده شد</div>
        <div class="card">
          <div class="stat-row"><span>لینک اشتراک</span></div>
          <div class="code" style="word-break:break-all;direction:ltr;text-align:left;margin-top:6px">${escHtml(result.link)}</div>
          <button class="btn outline small" id="cc-copy-btn" style="margin-top:10px">📋 کپی لینک</button>
        </div>
      `;
      document.getElementById("cc-copy-btn").onclick = () => {
        navigator.clipboard.writeText(result.link).then(() => notify("لینک کپی شد."));
      };
    } else {
      content.innerHTML = `
        <button class="btn outline small" id="back-to-store-btn" style="width:auto;margin-bottom:12px">→ بازگشت به فروشگاه</button>
        <div class="eyebrow">پرداخت کانفیگ شخصی</div>
        <div class="card" id="cc-payment-card"></div>
      `;
      document.getElementById("back-to-store-btn").onclick = renderStore;
      const customGateways2 = await fetchCustomGateways();
      renderReceiptCard(document.getElementById("cc-payment-card"), {
        amount: result.final_price,
        cardNumber: result.card_number,
        cardHolder: result.card_holder,
        cardToCardEnabled: result.card_to_card_enabled,
        successText: "رسید ارسال شد. پس از تایید ادمین، کانفیگ از تب خانه در دسترس شما خواهد بود.",
        sendReceipt: async (file) => {
          const fd = new FormData();
          fd.append("photo", file);
          await apiUpload(`/api/orders/${result.order_id}/receipt`, fd);
        },
        cryptoEnabled: result.crypto_enabled,
        createCryptoInvoice: async () => api(`/api/orders/${result.order_id}/crypto-invoice`, { method: "POST" }),
        customGateways: customGateways2,
        createCustomGatewayInvoice: async (key) => api(`/api/orders/${result.order_id}/custom-invoice/${key}`, { method: "POST" }),
      });
    }
  } catch (e) {
    notify("خطا: " + e.message);
  }
}

// ---------------------------------------------------------------------------
// تب گردونه شانس -> دستگاه جکپات با ۳ رول
// ---------------------------------------------------------------------------
const SLOT_SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "💎", "7️⃣"];
const JACKPOT_SYMBOL = "💎";

async function renderWheel() {
  content.innerHTML = skeleton(1);
  try {
    const status = await api("/api/wheel");
    if (!status.enabled) {
      content.innerHTML = `<div class="state-msg"><span class="ic">◌</span>گردونه شانس غیرفعال است.</div>`;
      return;
    }
    content.innerHTML = `
      <div class="jackpot">
        <div class="jackpot-title"><span class="bulb"></span>جکپات شانس<span class="bulb"></span></div>
        <div class="marquee">${'<span class="lamp"></span>'.repeat(10)}</div>
        <div class="reels">
          <div class="reel" id="reel-0"><span class="reel-symbol">🍒</span></div>
          <div class="reel" id="reel-1"><span class="reel-symbol">⭐</span></div>
          <div class="reel" id="reel-2"><span class="reel-symbol">🔔</span></div>
        </div>
        <button class="spin-cta" id="spin-btn" ${status.can_spin ? "" : "disabled"}>
          ${status.can_spin ? "بکش! 🎰" : `⏳ ${status.remaining_hours} ساعت`}
        </button>
        <div id="jackpot-result"></div>
      </div>
    `;
    if (status.can_spin) {
      document.getElementById("spin-btn").onclick = spinWheel;
    }
  } catch (e) {
    content.innerHTML = errorState(e.message);
  }
}

function randomSymbol() {
  return SLOT_SYMBOLS[Math.floor(Math.random() * SLOT_SYMBOLS.length)];
}

async function spinWheel() {
  const btn = document.getElementById("spin-btn");
  const reels = [0, 1, 2].map((i) => document.getElementById(`reel-${i}`));
  const resultBox = document.getElementById("jackpot-result");
  btn.disabled = true;
  resultBox.innerHTML = "";
  reels.forEach((r) => {
    r.classList.add("spinning");
    r.classList.remove("win");
  });

  const spinIntervals = reels.map((r) =>
    setInterval(() => { r.querySelector(".reel-symbol").textContent = randomSymbol(); }, 70)
  );

  let apiResult, apiError;
  try {
    apiResult = await api("/api/wheel/spin", { method: "POST" });
  } catch (e) {
    apiError = e;
  }

  // رول‌ها یکی‌یکی با فاصله می‌ایستند، شبیه دستگاه واقعی
  const stopDelays = [1400, 1900, 2400];
  reels.forEach((r, i) => {
    setTimeout(() => {
      clearInterval(spinIntervals[i]);
      r.classList.remove("spinning");
      const finalSymbol = apiResult && apiResult.won ? JACKPOT_SYMBOL : randomSymbol();
      r.querySelector(".reel-symbol").textContent = finalSymbol;
      if (i === 2) {
        if (apiError) {
          resultBox.innerHTML = `<div class="jackpot-result lose">خطا: ${apiError.message}</div>`;
          btn.disabled = false;
          return;
        }
        tg.HapticFeedback.notificationOccurred(apiResult.won ? "success" : "error");
        if (apiResult.won) {
          reels.forEach((rr) => rr.classList.add("win"));
          resultBox.innerHTML = `
            <div class="jackpot-result win">
              🎉 جکپات بردی! کد تخفیف ${apiResult.percent}٪
              <div class="code">${apiResult.code}</div>
            </div>`;
        } else {
          resultBox.innerHTML = `<div class="jackpot-result lose">😔 امروز شانس نبود، فردا دوباره امتحان کن!</div>`;
        }
        renderWheel_refreshButtonOnly();
      }
    }, stopDelays[i]);
  });
}

// بعد از نتیجه، فقط وضعیت دکمه را بدون پاک‌کردن نتیجه به‌روزرسانی می‌کند
async function renderWheel_refreshButtonOnly() {
  try {
    const status = await api("/api/wheel");
    const btn = document.getElementById("spin-btn");
    if (!btn) return;
    btn.disabled = !status.can_spin;
    btn.textContent = status.can_spin ? "بکش! 🎰" : `⏳ ${status.remaining_hours} ساعت`;
    if (status.can_spin) btn.onclick = spinWheel;
  } catch (e) {}
}

// ---------------------------------------------------------------------------
// تب کیف پول
// ---------------------------------------------------------------------------
async function renderWallet() {
  content.innerHTML = skeleton(2);
  try {
    const me = await api("/api/me");
    setHeaderWallet(me.wallet_credit);
    content.innerHTML = `
      <div class="eyebrow">کیف پول</div>
      <div class="card">
        <h3><span class="ic">👛</span>موجودی فعلی</h3>
        <div class="stat-row"><span>قابل استفاده برای خرید</span><b>${fmt(me.wallet_credit)} تومان</b></div>
      </div>
      <div class="eyebrow">شارژ کیف پول</div>
      <div class="card" id="topup-card">
        <input id="topup-amount" class="input" type="number" placeholder="مبلغ به تومان" />
        <button class="btn" id="topup-btn">ثبت درخواست شارژ</button>
      </div>
    `;
    document.getElementById("topup-btn").onclick = async () => {
      const amount = parseInt(document.getElementById("topup-amount").value, 10);
      if (!amount || amount < 1000) return notify("حداقل مبلغ ۱۰۰۰ تومان است.");
      const btn = document.getElementById("topup-btn");
      btn.disabled = true;
      try {
        const r = await api("/api/wallet/topup-request", { method: "POST", body: JSON.stringify({ amount }) });
        renderTopupPaymentStep(r.topup_id, amount, r.card_number, r.card_holder, r.crypto_enabled, r.card_to_card_enabled);
      } catch (e) {
        notify("خطا: " + e.message);
        btn.disabled = false;
      }
    };
  } catch (e) {
    content.innerHTML = errorState(e.message);
  }
}

async function renderTopupPaymentStep(topupId, amount, cardNumber, cardHolder, cryptoEnabled, cardToCardEnabled) {
  const box = document.getElementById("topup-card");
  const customGateways = await fetchCustomGateways();
  renderReceiptCard(box, {
    amount, cardNumber, cardHolder, cardToCardEnabled,
    successText: "رسید ارسال شد. پس از تایید ادمین، کیف پول شما شارژ می‌شود.",
    sendReceipt: async (file) => {
      const fd = new FormData();
      fd.append("topup_id", topupId);
      fd.append("photo", file);
      await apiUpload("/api/wallet/topup-receipt", fd);
    },
    cryptoEnabled,
    createCryptoInvoice: async () => api("/api/wallet/crypto-invoice", { method: "POST", body: JSON.stringify({ topup_id: topupId }) }),
    customGateways,
    createCustomGatewayInvoice: async (key) => api(`/api/wallet/custom-invoice/${key}`, { method: "POST", body: JSON.stringify({ topup_id: topupId }) }),
  });
}

// ---------------------------------------------------------------------------
// تب مدیریت (فقط ادمین) - چیدمان دکمه‌های منوی اصلی
// ---------------------------------------------------------------------------

let adminMenuItems = [];
let adminMenuCustomLayout = false; // یعنی همین الان چیدمان ردیف‌ها (نه فقط ترتیب) دستی تغییر کرده

const STYLE_OPTIONS = [
  { value: "", label: "⚪️ پیش‌فرض" },
  { value: "primary", label: "🔵 آبی" },
  { value: "success", label: "🟢 سبز" },
  { value: "danger", label: "🔴 قرمز" },
];

let adminSection = "stats"; // stats | menu | branding | catalog | tickets | livechat | sales | users | resellers
let adminGroup = null; // گروه فعلاً باز در پنل مدیریت (سطح اول ناوبری)
let adminCatalogView = { level: "categories" }; // categories | products | configs
let adminPanelsView = { level: "servers" }; // servers | pricing
let adminTicketView = { level: "list" }; // list | thread
let adminLiveChatView = { level: "list" }; // list | thread
let adminPresenceTimer = null;
let adminLiveChatPollTimer = null;

const ADMIN_TABS = [
  { key: "stats", label: "📊 آمار", fullOnly: true, seniorOnly: true },
  { key: "sales", label: "💰 فروش", fullOnly: true, seniorOnly: true },
  { key: "finance", label: "💳 مالی و پرداخت", fullOnly: true, seniorOnly: true },
  { key: "catalog", label: "📦 محصولات", fullOnly: true, seniorOnly: true },
  { key: "panels", label: "🖥 پنل‌های VPN", fullOnly: true, seniorOnly: true },
  { key: "users", label: "👤 کاربران", fullOnly: true },
  { key: "resellers", label: "🏪 نمایندگی‌ها", fullOnly: true, seniorOnly: true, mainBotOnly: true },
  { key: "livechat", label: "💬 پشتیبانی زنده", fullOnly: false },
  { key: "tickets", label: "🎫 تیکت‌ها", fullOnly: false },
  { key: "menu", label: "🧩 چیدمان منو", fullOnly: true, seniorOnly: true },
  { key: "branding", label: "🎨 برندینگ", fullOnly: true, seniorOnly: true },
  { key: "banners", label: "🖼 بنرها", fullOnly: true, seniorOnly: true },
  { key: "adminlog", label: "📜 لاگ ادمین", fullOnly: true, seniorOnly: true },
  { key: "backup", label: "🗄 بکاپ", fullOnly: true, ownerOnly: true },
];

// دسته‌بندی سطح اول پنل مدیریت مینی‌اپ: به‌جای یک ردیف طولانیِ ۱۲ تایی از
// تب‌های قابل اسکرول، ادمین اول یک گروه را انتخاب می‌کند و سپس زیرتب‌های
// همان گروه (در صورت وجود بیش از یک مورد) نمایش داده می‌شود.
const ADMIN_TAB_GROUPS = [
  { key: "overview", label: "📊 آمار و فروش", tabs: ["stats", "sales"] },
  { key: "finance_group", label: "💳 مالی و پرداخت", tabs: ["finance"] },
  { key: "catalog_panels", label: "📦 محصولات و پنل‌ها", tabs: ["catalog", "panels"] },
  { key: "people", label: "👥 کاربران و نمایندگی", tabs: ["users", "resellers"] },
  { key: "support", label: "💬 پشتیبانی", tabs: ["livechat", "tickets"] },
  { key: "appearance", label: "🎨 منو و برندینگ", tabs: ["menu", "branding", "banners"] },
  { key: "system", label: "🗂 سیستم", tabs: ["adminlog", "backup"] },
];

async function renderAdmin() {
  const isMainBot = !TENANT_ID;

  let adminRole = "admin";
  try {
    const check = await api("/api/admin/check");
    adminRole = check.admin_role || "admin";
  } catch (e) {
    // در صورت خطا محتاطانه فرض می‌کنیم دسترسی کامل نیست
  }
  const isSupport = adminRole === "support";
  const isMid = adminRole === "mid";
  const isOwner = adminRole === "owner";
  const isSenior = adminRole === "owner" || adminRole === "admin";
  const visibleTabs = ADMIN_TABS.filter(
    (t) =>
      (!isSupport || !t.fullOnly) &&
      (!t.seniorOnly || isSenior) &&
      (!t.ownerOnly || isOwner) &&
      (!t.mainBotOnly || isMainBot)
  );
  const visibleKeys = new Set(visibleTabs.map((t) => t.key));

  // گروه‌هایی که حداقل یک تب قابل‌مشاهده دارند
  const visibleGroups = ADMIN_TAB_GROUPS
    .map((g) => ({ ...g, tabs: g.tabs.filter((k) => visibleKeys.has(k)) }))
    .filter((g) => g.tabs.length > 0);

  // اگر تب فعلی در هیچ گروه قابل‌مشاهده‌ای نیست (مثلاً به‌خاطر تغییر نقش)، ریست کن
  if (!visibleKeys.has(adminSection)) {
    adminSection = visibleGroups.length ? visibleGroups[0].tabs[0] : "";
  }
  // گروه فعلی را از روی تب فعال پیدا کن (اگر قبلاً تعیین نشده یا دیگر معتبر نیست)
  let currentGroup = visibleGroups.find((g) => g.key === adminGroup);
  if (!currentGroup || !currentGroup.tabs.includes(adminSection)) {
    currentGroup = visibleGroups.find((g) => g.tabs.includes(adminSection)) || visibleGroups[0];
  }
  adminGroup = currentGroup ? currentGroup.key : null;

  const tabLabel = (key) => (ADMIN_TABS.find((t) => t.key === key) || {}).label || key;

  const prevTabsEl = document.getElementById("admin-section-tabs");
  const prevScrollLeft = prevTabsEl ? prevTabsEl.scrollLeft : 0;
  content.innerHTML = `
    ${isSupport ? `<div class="banner" style="margin-bottom:10px"><div class="banner-title"><span class="ic">🎧</span>نقش شما: پشتیبان (دسترسی محدود)</div></div>` : ""}
    ${isMid ? `<div class="banner" style="margin-bottom:10px"><div class="banner-title"><span class="ic">🥈</span>نقش شما: ادمین میانی (بدون آمار/فروش/نمایندگی/برندینگ/محصولات)</div></div>` : ""}
    <div class="segmented-group" id="admin-group-tabs">
      ${visibleGroups.map((g) => `<button class="seg-btn-group ${adminGroup === g.key ? "active" : ""}" data-group="${g.key}">${g.label}</button>`).join("")}
    </div>
    ${currentGroup && currentGroup.tabs.length > 1 ? `
    <div class="segmented" id="admin-section-tabs">
      ${currentGroup.tabs.map((k) => `<button class="seg-btn ${adminSection === k ? "active" : ""}" data-section="${k}">${tabLabel(k)}</button>`).join("")}
    </div>` : ""}
    <div id="admin-section-body">${skeleton(4)}</div>
  `;
  const newTabsEl = document.getElementById("admin-section-tabs");
  if (newTabsEl) {
    newTabsEl.scrollLeft = prevScrollLeft;
    const activeBtn = newTabsEl.querySelector(".seg-btn.active");
    if (activeBtn) activeBtn.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  document.querySelectorAll("#admin-group-tabs .seg-btn-group").forEach((b) => {
    b.onclick = () => {
      const g = visibleGroups.find((x) => x.key === b.dataset.group);
      if (!g) return;
      if (adminSection !== "livechat") clearInterval(adminLiveChatPollTimer);
      adminGroup = g.key;
      adminSection = g.tabs[0];
      if (adminSection === "catalog") adminCatalogView = { level: "categories" };
      if (adminSection === "panels") adminPanelsView = { level: "servers" };
      if (adminSection === "tickets") adminTicketView = { level: "list" };
      if (adminSection === "livechat") adminLiveChatView = { level: "list" };
      if (adminSection === "users") adminUserView = { level: "list", filter: "all", query: "" };
      renderAdmin();
    };
  });
  document.querySelectorAll("#admin-section-tabs .seg-btn").forEach((b) => {
    b.onclick = () => {
      if (adminSection !== "livechat") clearInterval(adminLiveChatPollTimer);
      adminSection = b.dataset.section;
      if (adminSection === "catalog") adminCatalogView = { level: "categories" };
      if (adminSection === "panels") adminPanelsView = { level: "servers" };
      if (adminSection === "tickets") adminTicketView = { level: "list" };
      if (adminSection === "livechat") adminLiveChatView = { level: "list" };
      if (adminSection === "users") adminUserView = { level: "list", filter: "all", query: "" };
      renderAdmin();
    };
  });
  if (adminSection !== "livechat") clearInterval(adminLiveChatPollTimer);
  // با هر بار باز بودن پنل ادمین، حضور آنلاین ادمین به‌صورت دوره‌ای ثبت می‌شود
  // تا پیام‌های پشتیبانی زنده‌ی جدید به او مسیریابی شوند.
  clearInterval(adminPresenceTimer);
  adminPresenceTimer = setInterval(() => { api("/api/admin/check").catch(() => {}); }, 20000);
  if (adminSection === "stats") await renderAdminStatsSection();
  else if (adminSection === "menu") await renderAdminMenuSection();
  else if (adminSection === "branding") await renderAdminBrandingSection();
  else if (adminSection === "banners") await renderAdminBannersSection();
  else if (adminSection === "catalog") await renderAdminCatalogSection();
  else if (adminSection === "panels") await renderAdminPanelsSection();
  else if (adminSection === "users") await renderAdminUsersSection();
  else if (adminSection === "sales") await renderAdminSalesSection();
  else if (adminSection === "finance") await renderAdminFinanceSection();
  else if (adminSection === "livechat") await renderAdminLiveChatSection();
  else if (adminSection === "tickets") await renderAdminTicketsSection();
  else if (adminSection === "adminlog") await renderAdminLogSection();
  else if (adminSection === "resellers" && isMainBot && isSenior) await renderAdminResellersSection();
  else if (adminSection === "backup") await renderAdminBackupSection();
}

// ---------------------------------------------------------------------------
// تب مدیریت > آمار (داشبورد)
// ---------------------------------------------------------------------------

let adminStatsRange = { preset: 14, startDate: "", endDate: "" };

function _statsRangeDates() {
  if (adminStatsRange.startDate && adminStatsRange.endDate) {
    return { start: adminStatsRange.startDate, end: adminStatsRange.endDate };
  }
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - (adminStatsRange.preset - 1));
  const toISO = (d) => d.toISOString().slice(0, 10);
  return { start: toISO(start), end: toISO(end) };
}

function _changeBadge(pct) {
  if (pct === null || pct === undefined) return `<span class="hint-text" style="margin:0">—</span>`;
  const up = pct >= 0;
  const color = up ? "var(--cyan)" : "var(--danger)";
  const arrow = up ? "▲" : "▼";
  return `<span style="color:${color};font-weight:700;font-size:12px">${arrow} ${Math.abs(pct)}٪</span>`;
}

async function renderAdminStatsSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(4);
  try {
    const { start, end } = _statsRangeDates();
    const s = await api(`/api/admin/dashboard?start_date=${start}&end_date=${end}`);
    const maxRevenue = Math.max(...s.daily_series.map((d) => d.revenue), 1);
    const presets = [7, 14, 30, 90];
    const [sJy, sJm, sJd] = isoToJalaliYMD(start);
    const [eJy, eJm, eJd] = isoToJalaliYMD(end);

    body.innerHTML = `
      <div class="card">
        <div class="segmented" style="margin-bottom:10px">
          ${presets.map((p) => `<button class="seg-btn ${!adminStatsRange.startDate && adminStatsRange.preset === p ? "active" : ""}" data-stats-preset="${p}">${p} روز اخیر</button>`).join("")}
        </div>
        <p class="hint-text" style="margin:0 0 4px">از تاریخ</p>
        <div style="display:flex;gap:4px;margin-bottom:10px">
          ${jalaliDateSelectHtml("stats-start", sJy, sJm, sJd)}
        </div>
        <p class="hint-text" style="margin:0 0 4px">تا تاریخ</p>
        <div style="display:flex;gap:4px">
          ${jalaliDateSelectHtml("stats-end", eJy, eJm, eJd)}
        </div>
        <button class="btn small outline" id="stats-apply-range" style="width:auto;margin-top:10px">اعمال بازه‌ی دلخواه</button>
        <p class="hint-text">بازه‌ی نمایش‌داده‌شده: ${toJalaliStr(s.start_date)} تا ${toJalaliStr(s.end_date)}</p>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">💰 درآمد این بازه</div>
        <div class="stat-row"><span>مبلغ</span><b>${fmt(s.revenue)} تومان</b></div>
        <div class="stat-row"><span>نسبت به بازه‌ی قبل</span>${_changeBadge(s.revenue_change_pct)}</div>
      </div>

      <div class="stat-grid">
        <div class="stat-card"><span class="stat-num">${fmt(s.total_users)}</span><span class="stat-label">کل کاربران</span></div>
        <div class="stat-card"><span class="stat-num">+${fmt(s.new_users)}</span><span class="stat-label">کاربر جدید این بازه</span></div>
        <div class="stat-card"><span class="stat-num">${fmt(s.approved)}</span><span class="stat-label">سفارش تاییدشده</span></div>
        <div class="stat-card"><span class="stat-num">${fmt(s.pending)}</span><span class="stat-label">سفارش در انتظار</span></div>
        <div class="stat-card"><span class="stat-num">${fmt(s.rejected)}</span><span class="stat-label">سفارش ردشده</span></div>
        <div class="stat-card"><span class="stat-num">${s.conversion_rate}٪</span><span class="stat-label">نرخ تبدیل</span></div>
        <div class="stat-card"><span class="stat-num">${fmt(s.aov)}</span><span class="stat-label">میانگین سبد خرید (تومان)</span></div>
        <div class="stat-card"><span class="stat-num">${fmt(s.active_configs)}</span><span class="stat-label">کانفیگ فعال</span></div>
        <div class="stat-card"><span class="stat-num">${fmt(s.open_tickets)}</span><span class="stat-label">تیکت باز</span></div>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">📈 روند درآمد در بازه</div>
        <div class="bar-chart">
          ${s.daily_series.map((d) => `
            <div class="bar-chart-col">
              <div class="bar-chart-bar" style="height:${Math.max((d.revenue / maxRevenue) * 100, 3)}%" title="${fmt(d.revenue)} تومان"></div>
              <span class="bar-chart-label">${toJalaliMonthDay(d.date)}</span>
            </div>
          `).join("")}
        </div>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">🗂 تفکیک درآمد بر اساس دسته‌بندی</div>
        ${s.category_breakdown.length === 0 ? `<div class="hint-text" style="margin:0">فروشی در این بازه ثبت نشده.</div>` : s.category_breakdown.map((c) => `
          <div class="admin-list-row">
            <div class="admin-list-row-main">
              <span>${escHtml(c.name)}</span>
              <span class="hint-text" style="margin:0">${c.orders} سفارش</span>
            </div>
            <div class="admin-list-row-actions"><b>${fmt(c.revenue)} تومان</b></div>
          </div>
        `).join("")}
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">🤝 رفرال در مقابل خرید مستقیم</div>
        <div class="stat-row"><span>از طریق رفرال</span><b>${fmt(s.referral_revenue)} تومان</b></div>
        <div class="stat-row"><span>خرید مستقیم</span><b>${fmt(s.direct_revenue)} تومان</b></div>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">🏆 پرفروش‌ترین محصولات این بازه</div>
        ${s.top_products.length === 0 ? `<div class="hint-text" style="margin:0">هنوز فروشی ثبت نشده.</div>` : s.top_products.map((p, i) => `
          <div class="admin-list-row">
            <div class="admin-list-row-main">
              <span>${i + 1}. ${escHtml(p.name)}</span>
              <span class="hint-text" style="margin:0">${p.orders} فروش · ${fmt(p.revenue)} تومان</span>
            </div>
          </div>
        `).join("")}
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">🎫 پشتیبانی و مشتریان تکراری</div>
        <div class="stat-row"><span>تیکت ثبت‌شده در بازه</span><b>${fmt(s.tickets_created)}</b></div>
        <div class="stat-row"><span>تیکت باز</span><b>${fmt(s.tickets_open)}</b></div>
        <div class="stat-row"><span>میانگین زمان پاسخ اول</span><b>${s.avg_ticket_response_minutes != null ? s.avg_ticket_response_minutes + " دقیقه" : "—"}</b></div>
        <div class="stat-row"><span>نرخ مشتری تکراری</span><b>${s.repeat_customer_rate}٪ (${fmt(s.repeat_customers)}/${fmt(s.total_customers)})</b></div>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">📦 موجودی انبار محصولات فعال</div>
        ${(!s.inventory || s.inventory.length === 0) ? `<div class="hint-text" style="margin:0">محصول فعالی ثبت نشده.</div>` : s.inventory.map((p) => `
          <div class="admin-list-row">
            <div class="admin-list-row-main">
              <span>${p.low_stock ? "⚠️ " : ""}${escHtml(p.name)}</span>
              <span class="hint-text" style="margin:0">${p.used} مصرف‌شده</span>
            </div>
            <div class="admin-list-row-actions"><b>${p.unused} آزاد</b></div>
          </div>
        `).join("")}
      </div>

      <a class="btn outline small" style="width:auto;display:inline-block;text-decoration:none;text-align:center" href="${withTenant(`/api/admin/orders/export?start_date=${s.start_date}&end_date=${s.end_date}`)}" target="_blank">📤 خروجی اکسل سفارش‌های این بازه (CSV)</a>
    `;

    body.querySelectorAll("[data-stats-preset]").forEach((el) => {
      el.onclick = () => {
        adminStatsRange = { preset: Number(el.dataset.statsPreset), startDate: "", endDate: "" };
        renderAdminStatsSection();
      };
    });
    document.getElementById("stats-apply-range").onclick = () => {
      const sJyv = Number(document.getElementById("stats-start-y").value);
      const sJmv = Number(document.getElementById("stats-start-m").value);
      const sJdv = Number(document.getElementById("stats-start-d").value);
      const eJyv = Number(document.getElementById("stats-end-y").value);
      const eJmv = Number(document.getElementById("stats-end-m").value);
      const eJdv = Number(document.getElementById("stats-end-d").value);
      const sd = jalaliToISO(sJyv, sJmv, sJdv);
      const ed = jalaliToISO(eJyv, eJmv, eJdv);
      if (sd > ed) { notify("تاریخ شروع باید قبل از تاریخ پایان باشد."); return; }
      adminStatsRange = { preset: 0, startDate: sd, endDate: ed };
      renderAdminStatsSection();
    };
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

// ---------------------------------------------------------------------------
// تب مدیریت > چیدمان منو
// ---------------------------------------------------------------------------

async function renderAdminMenuSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(3);
  try {
    const menu = await api("/api/admin/menu");
    adminMenuItems = menu;
    adminMenuCustomLayout = false;
    body.innerHTML = `
      <p class="hint-text">ترتیب، متن، رنگ و فعال/غیرفعال بودن دکمه‌های منوی اصلی بات را از اینجا مدیریت کن. با فلش‌ها جای دکمه‌ها را جابه‌جا کن؛ با دکمه‌ی «کنار قبلی / ردیف جدید» مشخص کن کدام دکمه‌ها کنار هم و کدام‌ها در ردیف جدا نمایش داده شوند.</p>
      <div class="card" id="admin-menu-list"></div>
      <button class="btn" id="admin-menu-save">💾 ذخیره تغییرات</button>
    `;
    renderAdminMenuList();
    document.getElementById("admin-menu-save").onclick = saveAdminMenu;
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

// ---------------------------------------------------------------------------
// تب مدیریت > برندینگ (نام فروشگاه / بنر / عکس هدر / تم مینی‌اپ)
// ---------------------------------------------------------------------------

async function renderAdminBrandingSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(3);
  try {
    const branding = await api("/api/admin/settings/branding");
    body.innerHTML = `
      <div class="card">
        <div class="eyebrow" style="margin-top:0">🎨 برندینگ مینی‌اپ</div>
        <p class="hint-text">نام و متن بالای صفحه‌ی مینی‌اپ (بنر) همینجا قابل تغییره.</p>
        <label class="field-label">نام فروشگاه (بالای صفحه، کنار آیکون ⚡)</label>
        <input class="input" id="brand-store-name" type="text" placeholder="مثال: SHOP VPN" value="${branding.store_name.replace(/"/g, "&quot;")}" style="direction:rtl;text-align:right;font-family:var(--font-body);margin-bottom:10px" />
        <label class="field-label">متن بنر (زیر نام کاربر، مثلاً یک شعار کوتاه)</label>
        <input class="input" id="brand-banner-text" type="text" placeholder="مثال: اتصال امن و پایدار برقرار است" value="${branding.banner_text.replace(/"/g, "&quot;")}" style="direction:rtl;text-align:right;font-family:var(--font-body);margin-bottom:4px" />
        <div class="field-error" id="brand-error"></div>
        <button class="btn" id="brand-save" style="margin-top:8px">💾 ذخیره برندینگ</button>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">🖼 عکس بالای صفحه (به‌جای خورشید)</div>
        <p class="hint-text">می‌تونی به‌جای انیمیشن خورشید بالای مینی‌اپ، یک عکس/لوگوی دلخواه بذاری.</p>
        <div id="header-logo-preview" style="margin-bottom:10px">
          ${branding.header_image ? `<img src="${branding.header_image}" style="width:88px;height:88px;border-radius:50%;object-fit:cover;border:2px solid var(--glass-brd)" />` : `<span class="hint-text" style="margin:0">فعلاً عکسی تنظیم نشده؛ همون خورشید انیمیشنی نمایش داده می‌شه.</span>`}
        </div>
        <input type="file" accept="image/*" id="header-logo-file" style="margin-bottom:10px" />
        <div class="field-error" id="header-logo-error"></div>
        <div style="display:flex;gap:8px;margin-top:4px">
          <button class="btn" id="header-logo-save">💾 آپلود عکس</button>
          ${branding.header_image ? `<button class="btn outline danger" id="header-logo-reset">🗑 بازگشت به خورشید</button>` : ""}
        </div>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">🎨 تم مینی‌اپ</div>
        <p class="hint-text">یکی از تم‌های آماده رو برای رنگ‌بندی کل مینی‌اپ انتخاب کن.</p>
        <select class="input" id="theme-select" style="margin-bottom:10px">
          ${branding.themes.map((t) => `<option value="${t.id}" ${t.id === branding.theme ? "selected" : ""}>${t.label}</option>`).join("")}
        </select>
        <div class="field-error" id="theme-error"></div>
        <button class="btn" id="theme-save">💾 اعمال تم</button>
      </div>
    `;

    document.getElementById("brand-save").onclick = async () => {
      const errBox = document.getElementById("brand-error");
      errBox.textContent = "";
      const storeName = document.getElementById("brand-store-name").value.trim();
      const bannerText = document.getElementById("brand-banner-text").value.trim();
      if (!storeName || !bannerText) { errBox.textContent = "هر دو کادر باید پر باشند."; return; }
      try {
        await api("/api/admin/settings/branding", {
          method: "POST",
          body: JSON.stringify({ store_name: storeName, banner_text: bannerText }),
        });
        tg.HapticFeedback.notificationOccurred("success");
        notify("برندینگ ذخیره شد. برای دیدن تغییر، صفحه را دوباره باز کن.");
      } catch (e) { errBox.textContent = e.message; }
    };

    document.getElementById("header-logo-save").onclick = async () => {
      const errBox = document.getElementById("header-logo-error");
      errBox.textContent = "";
      const fileInput = document.getElementById("header-logo-file");
      const file = fileInput.files && fileInput.files[0];
      if (!file) { errBox.textContent = "ابتدا یک عکس انتخاب کن."; return; }
      const fd = new FormData();
      fd.append("photo", file);
      try {
        await apiUpload("/api/admin/settings/header-image", fd);
        tg.HapticFeedback.notificationOccurred("success");
        notify("عکس بالای صفحه ذخیره شد. برای دیدن تغییر، صفحه را دوباره باز کن.");
        renderAdminBrandingSection();
      } catch (e) { errBox.textContent = e.message; }
    };

    const resetBtn = document.getElementById("header-logo-reset");
    if (resetBtn) {
      resetBtn.onclick = async () => {
        if (!confirm("عکس سفارشی حذف و به خورشید انیمیشنی پیش‌فرض برگردد؟")) return;
        try {
          await api("/api/admin/settings/header-image", { method: "DELETE" });
          tg.HapticFeedback.notificationOccurred("success");
          renderAdminBrandingSection();
        } catch (e) { notify(e.message); }
      };
    }

    document.getElementById("theme-save").onclick = async () => {
      const errBox = document.getElementById("theme-error");
      errBox.textContent = "";
      const theme = document.getElementById("theme-select").value;
      try {
        await api("/api/admin/settings/theme", { method: "POST", body: JSON.stringify({ theme }) });
        tg.HapticFeedback.notificationOccurred("success");
        notify("تم ذخیره شد. برای دیدن تغییر، صفحه را دوباره باز کن.");
      } catch (e) { errBox.textContent = e.message; }
    };
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

// ---------------------------------------------------------------------------
// تب مدیریت > بنرها (کاروسل بالای صفحه‌ی خانه)
// ---------------------------------------------------------------------------

let adminBannerItems = [];

// مقصدهایی که با ضربه‌زدن روی یک بنر ممکن است باز شوند؛ value باید دقیقاً با
// کلیدهای شیء `tabs` در پایین همین فایل یکی باشد.
const BANNER_NAV_OPTIONS = [
  { value: "store", label: "🛒 فروشگاه (خرید سرویس)" },
  { value: "services", label: "🛡 سرویس‌های من" },
  { value: "wallet", label: "💳 کیف پول" },
  { value: "profile", label: "👤 حساب کاربری" },
  { value: "support", label: "💬 پشتیبانی" },
  { value: "referral", label: "🤝 دعوت دوستان" },
  { value: "test", label: "🧪 کانفیگ تست رایگان" },
  { value: "wheel", label: "🎡 چرخ شانس" },
  { value: "home", label: "🏠 صفحه‌ی خانه" },
];

// چند گرادیانِ آماده برای انتخاب سریعِ رنگ پس‌زمینه‌ی بنر؛ روی هرکدام بزنی
// در کادر متنی زیرش پر می‌شود و می‌شود آن را هم دستی ویرایش کرد.
const BANNER_BG_PRESETS = [
  "linear-gradient(120deg, #0d1a12, #123a20 55%, #17532c)",
  "linear-gradient(120deg, #2b1608, #4d2510 55%, #7a3a14)",
  "linear-gradient(120deg, #0d1420, #142845 55%, #1c3f6e)",
  "linear-gradient(120deg, #150c22, #2a1440 55%, #431f66)",
  "linear-gradient(120deg, #2a0d16, #4d1027 55%, #7a1b45)",
  "linear-gradient(120deg, #1a1405, #3d2f0a 55%, #5e480f)",
];

const BANNER_ANGLE_OPTIONS = [
  { value: "90", label: "↓ عمودی" },
  { value: "120", label: "↘ مورب (پیش‌فرض)" },
  { value: "180", label: "← افقی (راست به چپ)" },
  { value: "0", label: "→ افقی (چپ به راست)" },
  { value: "45", label: "↗ مورب معکوس" },
];

// از یک رشته‌ی گرادیان CSS، اولین یا دومین کد رنگ هگز را استخراج می‌کند (برای
// مقداردهی اولیه‌ی انتخاب‌گرهای رنگی)؛ اگر چیزی پیدا نشود یک پیش‌فرض برمی‌گرداند.
function bannerGradientColorAt(bgStr, index) {
  const matches = String(bgStr || "").match(/#[0-9a-fA-F]{3,8}/g) || [];
  if (matches[index]) {
    let hex = matches[index];
    if (hex.length === 4) hex = "#" + [...hex.slice(1)].map((c) => c + c).join(""); // #abc -> #aabbcc
    return hex.slice(0, 7);
  }
  return index === 0 ? "#150c22" : "#431f66";
}

function bannerGradientAngle(bgStr) {
  const m = String(bgStr || "").match(/linear-gradient\(\s*(\d+)deg/);
  return m ? m[1] : "120";
}

function updateBannerGradientFromControls(idx) {
  const c1 = document.querySelector(`.banner-color-swatch-btn[data-idx="${idx}"][data-which="1"]`).dataset.color;
  const c2 = document.querySelector(`.banner-color-swatch-btn[data-idx="${idx}"][data-which="2"]`).dataset.color;
  const angle = document.querySelector(`.banner-angle-input[data-idx="${idx}"]`).value;
  const gradient = `linear-gradient(${angle}deg, ${c1}, ${c2})`;
  const bgInput = document.querySelector(`.banner-bg-input[data-idx="${idx}"]`);
  if (bgInput) bgInput.value = gradient;
  if (!adminBannerItems[Number(idx)].image) {
    const preview = document.querySelector(`.banner-preview[data-idx="${idx}"]`);
    if (preview) preview.style.background = gradient;
  }
}

// ---------------------------------------------------------------------------
// انتخاب‌گر کامل رنگ (طیف کامل + تیرگی/روشنی + هیو) — چون input[type=color]
// داخل مرورگر درون‌برنامه‌ای تلگرام روی همه‌ی گوشی‌ها درست کار نمی‌کند، یک
// پیکر رنگ اختصاصی با HTML/CSS/Pointer Events ساخته شده که در همه‌جا یکسان کار می‌کند.
// ---------------------------------------------------------------------------

function hsvToRgb(h, s, v) {
  s /= 100; v /= 100;
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  let r, g, b;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
}

function rgbToHex(r, g, b) {
  return "#" + [r, g, b].map((n) => n.toString(16).padStart(2, "0")).join("");
}

function hsvToHex(h, s, v) {
  return rgbToHex(...hsvToRgb(h, s, v));
}

function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(String(hex || "").trim());
  if (!m) return [21, 12, 34];
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
}

function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const d = max - min;
  let h = 0;
  if (d !== 0) {
    if (max === r) h = (((g - b) / d) % 6) * 60;
    else if (max === g) h = ((b - r) / d + 2) * 60;
    else h = ((r - g) / d + 4) * 60;
    if (h < 0) h += 360;
  }
  return [h, max === 0 ? 0 : (d / max) * 100, max * 100];
}

function hexToHsv(hex) {
  return rgbToHsv(...hexToRgb(hex));
}

function openColorPickerModal(initialHex, onConfirm) {
  const [h0, s0, v0] = hexToHsv(initialHex);
  const state = { h: h0, s: s0, v: v0 };

  const overlay = document.createElement("div");
  overlay.className = "color-picker-overlay";
  overlay.innerHTML = `
    <div class="color-picker-modal">
      <div class="color-picker-picker-row">
        <div class="color-picker-sv" id="cp-sv"><div class="color-picker-sv-thumb" id="cp-sv-thumb"></div></div>
        <div class="color-picker-hue" id="cp-hue"><div class="color-picker-hue-thumb" id="cp-hue-thumb"></div></div>
      </div>
      <div class="color-picker-bottom">
        <div class="color-picker-preview" id="cp-preview"></div>
        <input class="input color-picker-hex" id="cp-hex" type="text" maxlength="7" />
      </div>
      <div class="color-picker-actions">
        <button type="button" class="btn outline" id="cp-cancel">انصراف</button>
        <button type="button" class="btn" id="cp-ok">✓ تایید انتخاب</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const svEl = overlay.querySelector("#cp-sv");
  const svThumb = overlay.querySelector("#cp-sv-thumb");
  const hueEl = overlay.querySelector("#cp-hue");
  const hueThumb = overlay.querySelector("#cp-hue-thumb");
  const preview = overlay.querySelector("#cp-preview");
  const hexInput = overlay.querySelector("#cp-hex");

  function render() {
    svEl.style.background = `linear-gradient(to top, #000, transparent), linear-gradient(to right, #fff, transparent), hsl(${state.h}, 100%, 50%)`;
    svThumb.style.left = `${state.s}%`;
    svThumb.style.top = `${100 - state.v}%`;
    hueThumb.style.top = `${(state.h / 360) * 100}%`;
    const hex = hsvToHex(state.h, state.s, state.v);
    preview.style.background = hex;
    hexInput.value = hex;
  }
  render();

  function setSvFromPoint(clientX, clientY) {
    const rect = svEl.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    state.s = x * 100;
    state.v = (1 - y) * 100;
    render();
  }
  function setHueFromPoint(clientY) {
    const rect = hueEl.getBoundingClientRect();
    const y = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    state.h = y * 360;
    render();
  }

  let draggingSv = false, draggingHue = false;
  svEl.addEventListener("pointerdown", (e) => {
    draggingSv = true;
    svEl.setPointerCapture(e.pointerId);
    setSvFromPoint(e.clientX, e.clientY);
  });
  svEl.addEventListener("pointermove", (e) => { if (draggingSv) setSvFromPoint(e.clientX, e.clientY); });
  svEl.addEventListener("pointerup", () => { draggingSv = false; });
  svEl.addEventListener("pointercancel", () => { draggingSv = false; });

  hueEl.addEventListener("pointerdown", (e) => {
    draggingHue = true;
    hueEl.setPointerCapture(e.pointerId);
    setHueFromPoint(e.clientY);
  });
  hueEl.addEventListener("pointermove", (e) => { if (draggingHue) setHueFromPoint(e.clientY); });
  hueEl.addEventListener("pointerup", () => { draggingHue = false; });
  hueEl.addEventListener("pointercancel", () => { draggingHue = false; });

  hexInput.addEventListener("change", () => {
    let v = hexInput.value.trim();
    if (!v.startsWith("#")) v = "#" + v;
    if (/^#[0-9a-fA-F]{6}$/.test(v)) {
      const [h, s, val] = hexToHsv(v);
      state.h = h; state.s = s; state.v = val;
      render();
    }
  });

  function close() { overlay.remove(); }
  overlay.querySelector("#cp-cancel").onclick = close;
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  overlay.querySelector("#cp-ok").onclick = () => {
    const hex = hexInput.value;
    close();
    onConfirm(hex);
  };
}

async function renderAdminBannersSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(3);
  try {
    const banners = await api("/api/admin/banners");
    adminBannerItems = banners;
    body.innerHTML = `
      <p class="hint-text">بنرهای کاروسل بالای صفحه‌ی خانه را همین‌جا اضافه، ویرایش، حذف یا مرتب کن. مشخص کن با ضربه‌زدن روی هر بنر، کاربر به کدام بخش مینی‌اپ منتقل شود.</p>
      <div class="card" id="admin-banner-list"></div>
      <button class="btn outline" id="admin-banner-add" style="margin-bottom:10px">➕ افزودن بنر جدید</button>
      <button class="btn" id="admin-banner-save">💾 ذخیره بنرها</button>
    `;
    renderAdminBannerList();
    document.getElementById("admin-banner-add").onclick = () => {
      collectBannerEdits();
      adminBannerItems.push({
        id: "",
        icon: "✨",
        title: "بنر جدید",
        sub: "",
        cta: "مشاهده",
        nav: "store",
        bg: BANNER_BG_PRESETS[0],
        image: "",
        image_only: false,
        enabled: true,
      });
      renderAdminBannerList();
    };
    document.getElementById("admin-banner-save").onclick = saveAdminBanners;
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

function renderAdminBannerList() {
  const list = document.getElementById("admin-banner-list");
  if (adminBannerItems.length === 0) {
    list.innerHTML = `<div class="state-msg"><span class="ic">🖼</span>هنوز بنری اضافه نشده.</div>`;
    return;
  }
  list.innerHTML = adminBannerItems.map((item, idx) => adminBannerRow(item, idx)).join("");
  adminBannerItems.forEach((item, idx) => {
    const upBtn = document.getElementById(`banner-up-${idx}`);
    const downBtn = document.getElementById(`banner-down-${idx}`);
    const delBtn = document.getElementById(`banner-del-${idx}`);
    if (upBtn) upBtn.onclick = () => moveBannerItem(idx, -1);
    if (downBtn) downBtn.onclick = () => moveBannerItem(idx, 1);
    if (delBtn) delBtn.onclick = () => removeBannerItem(idx);
  });
  list.querySelectorAll(".banner-bg-swatch").forEach((sw) => {
    sw.onclick = () => {
      const idx = Number(sw.dataset.idx);
      const bg = sw.dataset.bg;
      const input = document.querySelector(`.banner-bg-input[data-idx="${idx}"]`);
      if (input) input.value = bg;
      if (!adminBannerItems[idx].image) {
        const preview = document.querySelector(`.banner-preview[data-idx="${idx}"]`);
        if (preview) preview.style.background = bg;
      }
    };
  });
  list.querySelectorAll(".banner-bg-input").forEach((input) => {
    input.oninput = () => {
      if (adminBannerItems[Number(input.dataset.idx)].image) return;
      const preview = document.querySelector(`.banner-preview[data-idx="${input.dataset.idx}"]`);
      if (preview) preview.style.background = input.value;
    };
  });
  list.querySelectorAll(".banner-color-swatch-btn, .banner-angle-input").forEach((el) => {
    if (el.classList.contains("banner-angle-input")) {
      el.onchange = () => updateBannerGradientFromControls(el.dataset.idx);
      return;
    }
    el.onclick = () => {
      openColorPickerModal(el.dataset.color, (hex) => {
        el.dataset.color = hex;
        el.style.background = hex;
        updateBannerGradientFromControls(el.dataset.idx);
      });
    };
  });
  list.querySelectorAll(".banner-image-upload").forEach((btn) => {
    btn.onclick = async () => {
      const idx = Number(btn.dataset.idx);
      const errBox = document.getElementById(`banner-image-error-${idx}`);
      errBox.textContent = "";
      const fileInput = document.querySelector(`.banner-image-file[data-idx="${idx}"]`);
      const file = fileInput.files && fileInput.files[0];
      if (!file) { errBox.textContent = "ابتدا یک عکس انتخاب کن."; return; }
      const fd = new FormData();
      fd.append("photo", file);
      btn.disabled = true;
      btn.textContent = "در حال آپلود...";
      try {
        collectBannerEdits();
        const res = await apiUpload("/api/admin/banners/upload-image", fd);
        adminBannerItems[idx].image = res.image;
        adminBannerItems[idx].image_only = true;
        tg.HapticFeedback.notificationOccurred("success");
        renderAdminBannerList();
      } catch (e) {
        errBox.textContent = e.message;
        btn.disabled = false;
        btn.textContent = "📤 آپلود این عکس";
      }
    };
  });
  list.querySelectorAll(".banner-image-clear").forEach((btn) => {
    btn.onclick = () => {
      collectBannerEdits();
      const idx = Number(btn.dataset.idx);
      adminBannerItems[idx].image = "";
      adminBannerItems[idx].image_only = false;
      renderAdminBannerList();
    };
  });
}

function adminBannerRow(item, idx) {
  const previewBg = item.image ? `url('${item.image}') center/cover no-repeat` : (item.bg || BANNER_BG_PRESETS[0]);
  return `
    <div class="menu-row" data-idx="${idx}">
      <div class="menu-row-top">
        <span class="menu-row-label">بنر ${idx + 1}${item.enabled === false ? " (غیرفعال)" : ""}</span>
        <div class="menu-row-arrows">
          <button type="button" class="btn small outline" id="banner-up-${idx}" ${idx === 0 ? "disabled" : ""}>▲</button>
          <button type="button" class="btn small outline" id="banner-down-${idx}" ${idx === adminBannerItems.length - 1 ? "disabled" : ""}>▼</button>
          <button type="button" class="btn small outline danger" id="banner-del-${idx}">🗑</button>
        </div>
      </div>
      <div class="menu-row-body">
        <div class="banner-preview" data-idx="${idx}" style="background:${previewBg}">
          ${item.image && item.image_only ? "" : `
          <span class="banner-preview-icon banner-icon-input-wrap"><input class="banner-icon-input" data-idx="${idx}" type="text" value="${escHtml(item.icon || "")}" maxlength="4" /></span>
          <span class="banner-preview-title">${escHtml(item.title || "بنر جدید")}</span>
          `}
        </div>

        <p class="hint-text" style="margin-top:0">🖼 می‌تونی به‌جای رنگ گرادیانی، یک عکسِ از قبل طراحی‌شده برای این بنر آپلود کنی. اندازه‌ی پیشنهادی: عرض ۱۲۰۰ پیکسل، ارتفاع ۴۰۰ پیکسل (نسبت تقریبی ۳:۱ — همون شکل کشیده‌ی بنرهای بالای صفحه)، فرمت JPG / PNG / WebP، حجم زیر ۲ مگابایت. عکسی با نسبت دیگه هم کار می‌کنه ولی ممکنه بالا/پایینش برش بخوره چون کل کادر رو پر می‌کنه (cover).</p>
        <div id="banner-image-preview-${idx}">
          ${item.image ? `<img src="${item.image}" style="width:100%;max-width:260px;border-radius:10px;border:1px solid var(--glass-brd);margin-bottom:8px;display:block" />` : ""}
        </div>
        <input type="file" accept="image/*" class="banner-image-file" data-idx="${idx}" style="margin-bottom:8px" />
        <div class="field-error" id="banner-image-error-${idx}"></div>
        <div style="display:flex;gap:8px;margin-bottom:8px">
          <button type="button" class="btn small outline banner-image-upload" data-idx="${idx}">📤 آپلود این عکس</button>
          ${item.image ? `<button type="button" class="btn small outline danger banner-image-clear" data-idx="${idx}">🗑 حذف عکس</button>` : ""}
        </div>
        ${item.image ? `
        <label class="menu-toggle" style="margin-bottom:10px">
          <input type="checkbox" class="banner-imageonly-input" data-idx="${idx}" ${item.image_only ? "checked" : ""} />
          <span>فقط عکس نمایش داده شود (بدون آیکون/عنوان روی آن — برای بنرهای آماده مناسب‌تره)</span>
        </label>
        ` : ""}

        <label class="field-label">عنوان بنر</label>
        <input class="input banner-title-input" data-idx="${idx}" type="text" value="${escHtml(item.title || "")}" placeholder="مثال: خرید سرویس جدید!" style="direction:rtl;text-align:right;font-family:var(--font-body)" />
        <label class="field-label">توضیح کوتاه</label>
        <input class="input banner-sub-input" data-idx="${idx}" type="text" value="${escHtml(item.sub || "")}" placeholder="یک جمله‌ی کوتاه توضیحی" style="direction:rtl;text-align:right;font-family:var(--font-body)" />
        <label class="field-label">متن دکمه</label>
        <input class="input banner-cta-input" data-idx="${idx}" type="text" value="${escHtml(item.cta || "")}" placeholder="مثال: شروع خرید" style="direction:rtl;text-align:right;font-family:var(--font-body)" />
        <label class="field-label">با ضربه‌زدن، کاربر منتقل شود به:</label>
        <select class="input banner-nav-input" data-idx="${idx}">
          ${BANNER_NAV_OPTIONS.map((o) => `<option value="${o.value}" ${o.value === item.nav ? "selected" : ""}>${o.label}</option>`).join("")}
        </select>
        <label class="field-label">رنگ پس‌زمینه (وقتی عکس آپلود نشده باشد)</label>
        <p class="hint-text" style="margin-top:0">با دو دکمه‌ی رنگی زیر، صفحه‌ی کامل انتخاب رنگ باز می‌شه (طیف کامل + تیرگی/روشنی، دقیقاً مثل فتوشاپ) و ازشون یک گرادیان دورنگ می‌سازه. اگه دلت یک رنگ ساده (بدون گرادیان) بخواد، هر دو رنگ رو یکی انتخاب کن.</p>
        <div class="banner-color-picker-row">
          <div class="banner-color-picker">
            <button type="button" class="banner-color-swatch-btn" data-idx="${idx}" data-which="1" data-color="${bannerGradientColorAt(item.bg, 0)}" style="background:${bannerGradientColorAt(item.bg, 0)}"></button>
            <span>رنگ شروع</span>
          </div>
          <div class="banner-color-picker">
            <button type="button" class="banner-color-swatch-btn" data-idx="${idx}" data-which="2" data-color="${bannerGradientColorAt(item.bg, 1)}" style="background:${bannerGradientColorAt(item.bg, 1)}"></button>
            <span>رنگ پایان</span>
          </div>
          <select class="input banner-angle-input" data-idx="${idx}" style="width:auto;flex:1">
            ${BANNER_ANGLE_OPTIONS.map((a) => `<option value="${a.value}" ${a.value === bannerGradientAngle(item.bg) ? "selected" : ""}>${a.label}</option>`).join("")}
          </select>
        </div>
        <p class="hint-text" style="margin:6px 0 4px">یا از پیش‌فرض‌های آماده انتخاب کن:</p>
        <div class="banner-bg-swatches">
          ${BANNER_BG_PRESETS.map((bg) => `<button type="button" class="banner-bg-swatch" data-idx="${idx}" data-bg="${bg}" style="background:${bg}"></button>`).join("")}
        </div>
        <label class="field-label">کد CSS نهایی (می‌تونی دستی هم ویرایش کنی)</label>
        <input class="input banner-bg-input" data-idx="${idx}" type="text" value="${escHtml(item.bg || "")}" placeholder="کد گرادیان/رنگ CSS دلخواه" style="direction:ltr;text-align:left;font-family:var(--font-mono);font-size:11px" />
        <label class="menu-toggle">
          <input type="checkbox" class="banner-enabled-input" data-idx="${idx}" ${item.enabled !== false ? "checked" : ""} />
          <span>فعال (در کاروسل خانه نمایش داده شود)</span>
        </label>
      </div>
    </div>
  `;
}

function collectBannerEdits() {
  document.querySelectorAll(".banner-icon-input").forEach((el) => {
    adminBannerItems[Number(el.dataset.idx)].icon = el.value;
  });
  document.querySelectorAll(".banner-title-input").forEach((el) => {
    adminBannerItems[Number(el.dataset.idx)].title = el.value;
  });
  document.querySelectorAll(".banner-sub-input").forEach((el) => {
    adminBannerItems[Number(el.dataset.idx)].sub = el.value;
  });
  document.querySelectorAll(".banner-cta-input").forEach((el) => {
    adminBannerItems[Number(el.dataset.idx)].cta = el.value;
  });
  document.querySelectorAll(".banner-nav-input").forEach((el) => {
    adminBannerItems[Number(el.dataset.idx)].nav = el.value;
  });
  document.querySelectorAll(".banner-bg-input").forEach((el) => {
    adminBannerItems[Number(el.dataset.idx)].bg = el.value;
  });
  document.querySelectorAll(".banner-imageonly-input").forEach((el) => {
    adminBannerItems[Number(el.dataset.idx)].image_only = el.checked;
  });
  document.querySelectorAll(".banner-enabled-input").forEach((el) => {
    adminBannerItems[Number(el.dataset.idx)].enabled = el.checked;
  });
}

function moveBannerItem(idx, dir) {
  collectBannerEdits();
  const newIdx = idx + dir;
  if (newIdx < 0 || newIdx >= adminBannerItems.length) return;
  const tmp = adminBannerItems[idx];
  adminBannerItems[idx] = adminBannerItems[newIdx];
  adminBannerItems[newIdx] = tmp;
  renderAdminBannerList();
}

function removeBannerItem(idx) {
  collectBannerEdits();
  adminBannerItems.splice(idx, 1);
  renderAdminBannerList();
}

async function saveAdminBanners() {
  collectBannerEdits();
  const saveBtn = document.getElementById("admin-banner-save");
  saveBtn.disabled = true;
  saveBtn.textContent = "در حال ذخیره...";
  try {
    const res = await api("/api/admin/banners", {
      method: "POST",
      body: JSON.stringify({ banners: adminBannerItems }),
    });
    adminBannerItems = res.banners;
    tg.HapticFeedback.notificationOccurred("success");
    notify("بنرها ذخیره شد. برای دیدن تغییرات، صفحه‌ی خانه را دوباره باز کن.");
    renderAdminBannerList();
  } catch (e) {
    notify(e.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "💾 ذخیره بنرها";
  }
}

function computeAdminMenuRowNumbers() {
  let row = 0;
  return adminMenuItems.map((it, idx) => {
    if (idx === 0 || it.break_before !== false) row++;
    return row;
  });
}

function renderAdminMenuList() {
  const list = document.getElementById("admin-menu-list");
  const rowNumbers = computeAdminMenuRowNumbers();
  list.innerHTML = adminMenuItems.map((item, idx) => adminMenuRow(item, idx, rowNumbers)).join("");
  adminMenuItems.forEach((item, idx) => {
    const upBtn = document.getElementById(`menu-up-${idx}`);
    const downBtn = document.getElementById(`menu-down-${idx}`);
    const breakBtn = document.getElementById(`menu-break-${idx}`);
    if (upBtn) upBtn.onclick = () => moveMenuItem(idx, -1);
    if (downBtn) downBtn.onclick = () => moveMenuItem(idx, 1);
    if (breakBtn) breakBtn.onclick = () => toggleMenuBreak(idx);
  });
}

function toggleMenuBreak(idx) {
  collectMenuEdits();
  const item = adminMenuItems[idx];
  if (!item || idx === 0) return;
  item.break_before = item.break_before === false ? true : false;
  adminMenuCustomLayout = true;
  renderAdminMenuList();
}

function adminMenuRow(item, idx, rowNumbers) {
  const styleSelect = item.has_style
    ? `<select class="input menu-style-input" data-idx="${idx}">
        ${STYLE_OPTIONS.map((o) => `<option value="${o.value}" ${o.value === (item.style || "") ? "selected" : ""}>${o.label}</option>`).join("")}
      </select>`
    : "";
  const textInput = item.has_text
    ? `<input class="input menu-text-input" data-idx="${idx}" type="text" value="${(item.text || "").replace(/"/g, "&quot;")}" placeholder="متن دکمه" />`
    : `<div class="hint-text" style="margin:0">${item.label} (بدون متن قابل‌ویرایش)</div>`;
  const toggle = item.togglable
    ? `<label class="menu-toggle">
        <input type="checkbox" class="menu-enabled-input" data-idx="${idx}" ${item.enabled ? "checked" : ""} />
        <span>فعال</span>
      </label>`
    : "";
  const joined = idx > 0 && item.break_before === false;
  const breakBtn = idx > 0
    ? `<button type="button" class="btn small ${joined ? "" : "outline"}" id="menu-break-${idx}" title="کنار دکمه‌ی قبلی یا در ردیف جدید">${joined ? "↔ کنار قبلی" : "⤵ ردیف جدید"}</button>`
    : "";
  return `
    <div class="menu-row" data-idx="${idx}">
      <div class="menu-row-top">
        <span class="menu-row-label">ردیف ${rowNumbers[idx]} · ${item.label}${item.admin_only ? " (فقط ادمین)" : ""}</span>
        <div class="menu-row-arrows">
          ${breakBtn}
          <button type="button" class="btn small outline" id="menu-up-${idx}" ${idx === 0 ? "disabled" : ""}>▲</button>
          <button type="button" class="btn small outline" id="menu-down-${idx}" ${idx === adminMenuItems.length - 1 ? "disabled" : ""}>▼</button>
        </div>
      </div>
      <div class="menu-row-body">
        ${textInput}
        ${styleSelect}
        ${toggle}
      </div>
    </div>
  `;
}

function collectMenuEdits() {
  document.querySelectorAll(".menu-text-input").forEach((el) => {
    adminMenuItems[Number(el.dataset.idx)].text = el.value;
  });
  document.querySelectorAll(".menu-style-input").forEach((el) => {
    adminMenuItems[Number(el.dataset.idx)].style = el.value;
  });
  document.querySelectorAll(".menu-enabled-input").forEach((el) => {
    adminMenuItems[Number(el.dataset.idx)].enabled = el.checked;
  });
}

function moveMenuItem(idx, dir) {
  collectMenuEdits();
  const newIdx = idx + dir;
  if (newIdx < 0 || newIdx >= adminMenuItems.length) return;
  const tmp = adminMenuItems[idx];
  adminMenuItems[idx] = adminMenuItems[newIdx];
  adminMenuItems[newIdx] = tmp;
  renderAdminMenuList();
}

async function saveAdminMenu() {
  collectMenuEdits();
  const saveBtn = document.getElementById("admin-menu-save");
  saveBtn.disabled = true;
  saveBtn.textContent = "در حال ذخیره...";
  try {
    const payload = {
      order: adminMenuItems.map((i) => i.key),
      buttons: adminMenuItems.map((i) => ({ key: i.key, text: i.text, style: i.style, enabled: i.enabled })),
    };
    if (adminMenuCustomLayout) {
      // اگه کاربر همین الان حداقل یک‌بار چیدمان ردیف‌ها رو دستی عوض کرده، بقیه‌ی
      // آیتم‌هایی که هنوز break_before نامشخص (null) دارن، به‌صورت پیش‌فرض
      // «ردیف جدا» در نظر گرفته می‌شن تا رفتار قابل‌پیش‌بینی بمونه.
      payload.row_breaks = adminMenuItems.filter((i, idx) => idx > 0 && i.break_before !== false).map((i) => i.key);
    }
    await api("/api/admin/menu", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    tg.HapticFeedback.notificationOccurred("success");
    notify("چیدمان منو با موفقیت ذخیره شد. برای دیدن تغییرات، بات را دوباره در تلگرام باز کن.");
  } catch (e) {
    notify(e.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "💾 ذخیره تغییرات";
  }
}

// ---------------------------------------------------------------------------
// تب مدیریت > پنل‌های VPN (ساخت کانفیگ شخصی)
// ---------------------------------------------------------------------------

async function renderAdminPanelsSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(3);
  try {
    if (adminPanelsView.level === "add-server") {
      body.innerHTML = `
        <div class="card">
          <div class="eyebrow" style="margin-top:0">➕ افزودن سرور پنل</div>
          <label class="field-label">نام دلخواه سرور</label>
          <input class="input" id="ps-name" type="text" placeholder="مثلاً: سرور آلمان" style="direction:rtl;text-align:right;font-family:var(--font-body);margin-bottom:10px" />
          <label class="field-label">نوع پنل</label>
          <select class="input" id="ps-type" style="margin-bottom:10px">
            <option value="pasarguard">PasarGuard</option>
            <option value="3xui">3X-UI</option>
            <option value="marzban">Marzban</option>
            <option value="marzneshin">Marzneshin</option>
            <option value="hiddify">Hiddify</option>
          </select>
          <label class="field-label">آدرس API (مثلاً https://panel.example.com)</label>
          <input class="input" id="ps-url" type="text" placeholder="https://..." style="direction:ltr;text-align:left;margin-bottom:10px" />
          <label class="field-label">نام کاربری ادمین پنل</label>
          <input class="input" id="ps-username" type="text" style="direction:ltr;text-align:left;margin-bottom:10px" />
          <label class="field-label">رمز عبور ادمین پنل</label>
          <input class="input" id="ps-password" type="password" style="direction:ltr;text-align:left;margin-bottom:10px" />
          <div id="ps-template-wrap">
            <label class="field-label">نام کاربری نمونه (که از قبل روی پنل موجود است)</label>
            <p class="hint-text" style="margin-top:0">تنظیمات پروتکل/گروه همین کاربر به‌عنوان قالب پیش‌فرض برای همه‌ی کانفیگ‌های جدید استفاده می‌شود.</p>
            <input class="input" id="ps-template" type="text" style="direction:ltr;text-align:left;margin-bottom:4px" />
          </div>
          <p class="hint-text" id="ps-xui-hint" style="display:none;margin-top:0">بعد از اتصال، لیست inbound های پنل خوانده می‌شود و در مرحله‌ی بعد یکی را انتخاب می‌کنی.</p>
          <p class="hint-text" id="ps-hiddify-hint" style="display:none;margin-top:0">هیدیفای یوزر/پس ندارد: در «نام کاربری» هر چیزی بنویس، و در «رمز عبور» همان Hiddify-API-Key (UUID ادمین) را بگذار. بعد از اتصال، آدرس عمومی Subscription را می‌پرسیم.</p>
          <div class="field-error" id="ps-error"></div>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button class="btn" id="ps-save">💾 افزودن سرور</button>
            <button class="btn outline" id="ps-cancel">انصراف</button>
          </div>
        </div>
      `;
      const psType = document.getElementById("ps-type");
      const NO_TEMPLATE_TYPES = ["3xui", "hiddify"];
      const syncPsType = () => {
        const needsTemplate = !NO_TEMPLATE_TYPES.includes(psType.value);
        document.getElementById("ps-template-wrap").style.display = needsTemplate ? "block" : "none";
        document.getElementById("ps-xui-hint").style.display = psType.value === "3xui" ? "block" : "none";
        document.getElementById("ps-hiddify-hint").style.display = psType.value === "hiddify" ? "block" : "none";
      };
      psType.onchange = syncPsType;
      syncPsType();
      document.getElementById("ps-cancel").onclick = () => { adminPanelsView = { level: "servers" }; renderAdminPanelsSection(); };
      document.getElementById("ps-save").onclick = async () => {
        const errBox = document.getElementById("ps-error");
        errBox.textContent = "";
        const panelType = psType.value;
        const payload = {
          name: document.getElementById("ps-name").value.trim(),
          panel_type: panelType,
          api_url: document.getElementById("ps-url").value.trim(),
          api_username: document.getElementById("ps-username").value.trim(),
          api_password: document.getElementById("ps-password").value,
          template_username: document.getElementById("ps-template").value.trim(),
        };
        if (!payload.name || !payload.api_url || !payload.api_username || !payload.api_password) {
          errBox.textContent = "نام، آدرس، یوزرنیم و پسورد الزامی هستند."; return;
        }
        if (panelType !== "3xui" && panelType !== "hiddify" && !payload.template_username) {
          errBox.textContent = "نام کاربری نمونه الزامی است."; return;
        }
        try {
          document.getElementById("ps-save").textContent = "⏳ در حال اتصال...";
          document.getElementById("ps-save").disabled = true;
          const res = await api("/api/admin/panel-servers", { method: "POST", body: JSON.stringify(payload) });
          tg.HapticFeedback.notificationOccurred("success");
          if (panelType === "3xui") {
            adminPanelsView = { level: "xui-config", serverId: res.id, inbounds: res.inbounds, name: payload.name };
          } else if (panelType === "hiddify") {
            adminPanelsView = { level: "suburl-config", serverId: res.id, name: payload.name };
          } else {
            notify("سرور با موفقیت اضافه شد.");
            adminPanelsView = { level: "servers" };
          }
          renderAdminPanelsSection();
        } catch (e) {
          errBox.textContent = e.message;
          document.getElementById("ps-save").textContent = "💾 افزودن سرور";
          document.getElementById("ps-save").disabled = false;
        }
      };
      return;
    }

    if (adminPanelsView.level === "xui-config") {
      const inbounds = adminPanelsView.inbounds || [];
      const preselected = new Set(adminPanelsView.selectedIds || []);
      body.innerHTML = `
        <div class="card">
          <div class="eyebrow" style="margin-top:0">⚙️ تنظیم Inbound برای «${adminPanelsView.name || ""}»</div>
          <label class="field-label">کدام inbound(ها) برای ساخت کاربرهای جدید استفاده شود؟ (می‌توانی چند مورد را تیک بزنی)</label>
          <div id="ps-xui-inbound-list" style="display:flex;flex-direction:column;gap:6px;margin-bottom:10px">
            ${inbounds.map((ib) => `
              <label style="display:flex;align-items:center;gap:8px;background:var(--glass-bg);border:1px solid var(--glass-brd);border-radius:8px;padding:8px 10px;cursor:pointer">
                <input type="checkbox" class="ps-xui-inbound-cb" value="${ib.id}" ${preselected.has(ib.id) ? "checked" : ""} />
                <span>#${ib.id} - ${ib.remark || "بدون‌نام"} (${ib.protocol}:${ib.port})</span>
              </label>
            `).join("")}
          </div>
          <label class="field-label">آدرس پایه‌ی Subscription پنل</label>
          <p class="hint-text" style="margin-top:0">همان چیزی که پنل موقع ساخت کاربر دستی نشانت می‌دهد، مثلاً https://domain:2096/sub یا https://domain/sub - بدون / انتهایی.</p>
          <input class="input" id="ps-xui-suburl" type="text" placeholder="https://..." style="direction:ltr;text-align:left;margin-bottom:4px" value="${adminPanelsView.subBaseUrl || ""}" />
          <div class="field-error" id="ps-xui-error"></div>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button class="btn" id="ps-xui-save">💾 ذخیره</button>
            <button class="btn outline" id="ps-xui-cancel">بعداً</button>
          </div>
        </div>
      `;
      if (inbounds.length === 0) {
        document.getElementById("ps-xui-error").textContent = "این پنل هیچ inbound ای ندارد.";
      }
      document.getElementById("ps-xui-cancel").onclick = () => { adminPanelsView = { level: "servers" }; renderAdminPanelsSection(); };
      document.getElementById("ps-xui-save").onclick = async () => {
        const errBox = document.getElementById("ps-xui-error");
        errBox.textContent = "";
        const inbound_ids = Array.from(document.querySelectorAll(".ps-xui-inbound-cb:checked")).map((cb) => parseInt(cb.value, 10));
        const sub_base_url = document.getElementById("ps-xui-suburl").value.trim();
        if (!inbound_ids.length || !sub_base_url) {
          errBox.textContent = "حداقل یک inbound و آدرس Subscription الزامی هستند."; return;
        }
        try {
          document.getElementById("ps-xui-save").disabled = true;
          await api(`/api/admin/panel-servers/${adminPanelsView.serverId}/xui-config`, {
            method: "POST", body: JSON.stringify({ inbound_ids, sub_base_url }),
          });
          tg.HapticFeedback.notificationOccurred("success");
          notify("سرور 3X-UI با موفقیت تنظیم شد.");
          adminPanelsView = { level: "servers" };
          renderAdminPanelsSection();
        } catch (e) {
          errBox.textContent = e.message;
          document.getElementById("ps-xui-save").disabled = false;
        }
      };
      return;
    }

    if (adminPanelsView.level === "suburl-config") {
      body.innerHTML = `
        <div class="card">
          <div class="eyebrow" style="margin-top:0">⚙️ تنظیم آدرس Subscription برای «${adminPanelsView.name || ""}»</div>
          <label class="field-label">آدرس عمومی Subscription پنل</label>
          <p class="hint-text" style="margin-top:0">چون معمولاً با آدرس API ادمین فرق دارد؛ همان دامنه/مسیری که پنل برای لینک اشتراک کاربر نشان می‌دهد - بدون / انتهایی.</p>
          <input class="input" id="ps-suburl" type="text" placeholder="https://..." style="direction:ltr;text-align:left;margin-bottom:4px" />
          <div class="field-error" id="ps-suburl-error"></div>
          <div style="display:flex;gap:8px;margin-top:8px">
            <button class="btn" id="ps-suburl-save">💾 ذخیره</button>
            <button class="btn outline" id="ps-suburl-cancel">بعداً</button>
          </div>
        </div>
      `;
      document.getElementById("ps-suburl-cancel").onclick = () => { adminPanelsView = { level: "servers" }; renderAdminPanelsSection(); };
      document.getElementById("ps-suburl-save").onclick = async () => {
        const errBox = document.getElementById("ps-suburl-error");
        errBox.textContent = "";
        const sub_base_url = document.getElementById("ps-suburl").value.trim();
        if (!sub_base_url) {
          errBox.textContent = "این فیلد الزامی است."; return;
        }
        try {
          document.getElementById("ps-suburl-save").disabled = true;
          await api(`/api/admin/panel-servers/${adminPanelsView.serverId}/xui-config`, {
            method: "POST", body: JSON.stringify({ sub_base_url }),
          });
          tg.HapticFeedback.notificationOccurred("success");
          notify("سرور با موفقیت تنظیم شد.");
          adminPanelsView = { level: "servers" };
          renderAdminPanelsSection();
        } catch (e) {
          errBox.textContent = e.message;
          document.getElementById("ps-suburl-save").disabled = false;
        }
      };
      return;
    }


    if (adminPanelsView.level === "pricing") {
      const tiers = await api("/api/admin/custom-config/pricing-tiers");
      body.innerHTML = `
        <div class="card">
          <div class="eyebrow" style="margin-top:0">💰 قیمت‌گذاری بر اساس بازه‌ی حجم</div>
          <p class="hint-text">قیمت نهایی = کل حجم انتخابی کاربر × نرخ همان بازه‌ای که حجم داخلش قرار می‌گیرد (یک نرخ ثابت برای کل حجم، نه پلکانی). اگر حجم کاربر از آخرین بازه هم بیشتر شود، با نرخ آخرین بازه حساب می‌شود.</p>
          ${tiers.length === 0 ? `<p class="hint-text">هنوز بازه‌ای تعریف نشده.</p>` : ""}
          <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:12px">
            ${tiers.map((t) => `
              <div style="display:flex;justify-content:space-between;align-items:center;background:var(--glass-bg);border:1px solid var(--glass-brd);border-radius:10px;padding:8px 12px">
                <span>${t.from_gb} تا ${t.to_gb ?? "∞"} گیگ ← ${Number(t.price_per_gb).toLocaleString()} تومان/گیگ</span>
                <button class="btn outline danger" data-tier="${t.id}" style="padding:4px 10px;font-size:12px">🗑</button>
              </div>
            `).join("")}
          </div>
          <button class="btn outline" id="pt-add-toggle">➕ افزودن بازه‌ی جدید</button>
          <div id="pt-add-form" style="display:none;margin-top:12px">
            <label class="field-label">از (گیگ)</label>
            <input class="input" id="pt-from" type="number" min="1" style="margin-bottom:10px" />
            <label class="field-label">تا (گیگ) - برای بی‌نهایت خالی بگذار</label>
            <input class="input" id="pt-to" type="number" min="1" style="margin-bottom:10px" />
            <label class="field-label">قیمت هر گیگ (تومان)</label>
            <input class="input" id="pt-price" type="number" min="1" style="margin-bottom:4px" />
            <div class="field-error" id="pt-error"></div>
            <button class="btn" id="pt-save" style="margin-top:8px">💾 افزودن</button>
          </div>
          <div style="margin-top:14px">
            <button class="btn outline" id="pt-back">⬅️ بازگشت</button>
          </div>
        </div>
      `;
      document.getElementById("pt-back").onclick = () => { adminPanelsView = { level: "servers" }; renderAdminPanelsSection(); };
      document.getElementById("pt-add-toggle").onclick = () => {
        document.getElementById("pt-add-form").style.display = "block";
      };
      document.querySelectorAll("[data-tier]").forEach((btn) => {
        btn.onclick = async () => {
          if (!confirm("این بازه حذف شود؟")) return;
          await api(`/api/admin/custom-config/pricing-tiers/${btn.dataset.tier}`, { method: "DELETE" });
          renderAdminPanelsSection();
        };
      });
      document.getElementById("pt-save").onclick = async () => {
        const errBox = document.getElementById("pt-error");
        errBox.textContent = "";
        const from_gb = parseInt(document.getElementById("pt-from").value, 10);
        const toRaw = document.getElementById("pt-to").value.trim();
        const to_gb = toRaw === "" ? null : parseInt(toRaw, 10);
        const price_per_gb = parseInt(document.getElementById("pt-price").value, 10);
        if (!from_gb || !price_per_gb || from_gb <= 0 || price_per_gb <= 0) {
          errBox.textContent = "مقادیر باید عدد صحیح مثبت باشند."; return;
        }
        try {
          await api("/api/admin/custom-config/pricing-tiers", {
            method: "POST", body: JSON.stringify({ from_gb, to_gb, price_per_gb }),
          });
          tg.HapticFeedback.notificationOccurred("success");
          renderAdminPanelsSection();
        } catch (e) { errBox.textContent = e.message; }
      };
      return;
    }

    // level === "servers" (پیش‌فرض)
    const [servers, settings] = await Promise.all([
      api("/api/admin/panel-servers"),
      api("/api/admin/custom-config/settings"),
    ]);

    body.innerHTML = `
      <div class="card">
        <div class="eyebrow" style="margin-top:0">🛠 ساخت کانفیگ شخصی</div>
        <p class="hint-text">کاربران می‌توانند با تعیین نام، حجم و پرداخت متناسب، کاربر خودشان را مستقیماً روی یکی از سرورهای زیر بسازند.</p>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
          <span>وضعیت این بخش: <b>${settings.enabled ? "🟢 فعال" : "🔴 غیرفعال"}</b></span>
          <button class="btn ${settings.enabled ? "outline danger" : ""}" id="cc-toggle" style="padding:6px 14px;font-size:13px">${settings.enabled ? "غیرفعال کن" : "فعال کن"}</button>
        </div>
        <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap">
          <div>
            <label class="field-label">حداقل حجم (گیگ)</label>
            <input class="input" id="cc-min" type="number" min="1" value="${settings.min_gb}" style="width:110px" />
          </div>
          <div>
            <label class="field-label">حداکثر حجم (گیگ)</label>
            <input class="input" id="cc-max" type="number" min="1" value="${settings.max_gb}" style="width:110px" />
          </div>
          <button class="btn outline" id="cc-save-range" style="padding:8px 14px">💾 ذخیره بازه</button>
        </div>
        <div class="field-error" id="cc-error"></div>
        <p class="hint-text" style="margin-top:8px">⏳ مدت اعتبار خرید شخصی فعلاً ثابت روی ${settings.duration_days} روز است.</p>
        <hr style="border-color:var(--glass-brd);margin:14px 0" />
        <div class="eyebrow" style="margin-top:0">🧪 کانفیگ تست (در صورت اتصال به پنل)</div>
        <p class="hint-text" style="margin-top:0">اگر یکی از سرورها برای «کانفیگ تست» فعال باشد، به‌جای انبار ثابت، یک کاربر واقعی با این حجم/مدت روی همان سرور ساخته می‌شود.</p>
        <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap">
          <div>
            <label class="field-label">حجم تست (گیگ)</label>
            <input class="input" id="cc-test-vol" type="number" min="1" value="${settings.test_volume_gb}" style="width:110px" />
          </div>
          <div>
            <label class="field-label">مدت تست (روز)</label>
            <input class="input" id="cc-test-dur" type="number" min="1" value="${settings.test_duration_days}" style="width:110px" />
          </div>
          <button class="btn outline" id="cc-save-test" style="padding:8px 14px">💾 ذخیره</button>
        </div>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">🖥 سرورهای پنل متصل</div>
        ${servers.length === 0 ? `<p class="hint-text">هنوز سروری اضافه نشده.</p>` : ""}
        <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:12px">
          ${servers.map((s) => `
            <div style="background:var(--glass-bg);border:1px solid var(--glass-brd);border-radius:10px;padding:10px 12px">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span>${s.is_active ? "🟢" : "🔴"} <b>${s.name}</b> <span class="hint-text" style="margin:0">(${s.panel_type})</span></span>
              </div>
              <div class="hint-text" style="margin:4px 0 4px;direction:ltr;text-align:left">${s.api_url}</div>
              <div class="hint-text" style="margin:0 0 4px">${s.panel_type === "3xui"
                ? (s.is_configured ? `⚙️ ${s.xui_inbound_ids.length} Inbound تنظیم شده (${s.xui_inbound_ids.map((i) => "#" + i).join("، ")})` : "⚠️ Inbound تنظیم نشده")
                : s.panel_type === "hiddify"
                ? (s.is_configured ? "✅ آدرس Subscription تنظیم شده" : "⚠️ آدرس Subscription تنظیم نشده")
                : (s.has_template ? `🧩 قالب از کاربر «${s.template_username}»` : "⚠️ قالب تنظیم نشده")}</div>
              <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">
                <span class="tag" style="opacity:${s.used_for_custom_config ? 1 : 0.4}">${s.used_for_custom_config ? "✅" : "◻️"} خرید شخصی</span>
                <span class="tag" style="opacity:${s.used_for_test_config ? 1 : 0.4}">${s.used_for_test_config ? "✅" : "◻️"} کانفیگ تست</span>
              </div>
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                <button class="btn outline" data-test="${s.id}" style="padding:4px 10px;font-size:12px">🔌 تست اتصال</button>
                ${s.panel_type === "3xui"
                  ? `<button class="btn outline" data-xui-inbound="${s.id}" data-xui-name="${s.name}" style="padding:4px 10px;font-size:12px">⚙️ تنظیم Inbound</button>`
                  : s.panel_type === "hiddify"
                  ? `<button class="btn outline" data-suburl="${s.id}" data-suburl-name="${s.name}" style="padding:4px 10px;font-size:12px">⚙️ تنظیم آدرس Sub</button>`
                  : `<button class="btn outline" data-template="${s.id}" style="padding:4px 10px;font-size:12px">🧩 تغییر قالب</button>`}
                <button class="btn outline" data-usage-custom="${s.id}" style="padding:4px 10px;font-size:12px">${s.used_for_custom_config ? "غیرفعال (خرید)" : "فعال (خرید)"}</button>
                <button class="btn outline" data-usage-test="${s.id}" style="padding:4px 10px;font-size:12px">${s.used_for_test_config ? "غیرفعال (تست)" : "فعال (تست)"}</button>
                <button class="btn outline" data-toggle="${s.id}" style="padding:4px 10px;font-size:12px">${s.is_active ? "غیرفعال کن" : "فعال کن"}</button>
                <button class="btn outline danger" data-delete="${s.id}" style="padding:4px 10px;font-size:12px">🗑 حذف</button>
              </div>
            </div>
          `).join("")}
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn" id="ps-add-btn">➕ افزودن سرور جدید</button>
          <button class="btn outline" id="pt-goto-btn">💰 قیمت‌گذاری بر اساس بازه</button>
        </div>
      </div>
    `;

    document.getElementById("cc-toggle").onclick = async () => {
      await api("/api/admin/custom-config/settings", {
        method: "POST", body: JSON.stringify({ enabled: !settings.enabled }),
      });
      renderAdminPanelsSection();
    };
    document.getElementById("cc-save-range").onclick = async () => {
      const errBox = document.getElementById("cc-error");
      errBox.textContent = "";
      const min_gb = parseInt(document.getElementById("cc-min").value, 10);
      const max_gb = parseInt(document.getElementById("cc-max").value, 10);
      if (!min_gb || !max_gb || min_gb <= 0 || max_gb <= min_gb) {
        errBox.textContent = "حداکثر باید بزرگ‌تر از حداقل باشد."; return;
      }
      try {
        await api("/api/admin/custom-config/settings", {
          method: "POST", body: JSON.stringify({ min_gb, max_gb }),
        });
        tg.HapticFeedback.notificationOccurred("success");
        notify("بازه‌ی حجم ذخیره شد.");
      } catch (e) { errBox.textContent = e.message; }
    };
    document.getElementById("ps-add-btn").onclick = () => { adminPanelsView = { level: "add-server" }; renderAdminPanelsSection(); };
    document.getElementById("pt-goto-btn").onclick = () => { adminPanelsView = { level: "pricing" }; renderAdminPanelsSection(); };
    document.getElementById("cc-save-test").onclick = async () => {
      const errBox = document.getElementById("cc-error");
      errBox.textContent = "";
      const test_volume_gb = parseInt(document.getElementById("cc-test-vol").value, 10);
      const test_duration_days = parseInt(document.getElementById("cc-test-dur").value, 10);
      if (!test_volume_gb || !test_duration_days || test_volume_gb <= 0 || test_duration_days <= 0) {
        errBox.textContent = "مقادیر باید عدد صحیح مثبت باشند."; return;
      }
      try {
        await api("/api/admin/custom-config/settings", {
          method: "POST", body: JSON.stringify({ test_volume_gb, test_duration_days }),
        });
        tg.HapticFeedback.notificationOccurred("success");
        notify("تنظیمات کانفیگ تست ذخیره شد.");
      } catch (e) { errBox.textContent = e.message; }
    };
    document.querySelectorAll("[data-test]").forEach((btn) => {
      btn.onclick = async () => {
        btn.textContent = "در حال تست...";
        try {
          const res = await api(`/api/admin/panel-servers/${btn.dataset.test}/test`, { method: "POST" });
          notify(res.ok ? "✅ اتصال موفق بود." : `❌ اتصال ناموفق بود.${res.error ? " " + res.error : ""}`);
        } catch (e) { notify(e.message); }
        btn.textContent = "🔌 تست اتصال";
      };
    });
    document.querySelectorAll("[data-template]").forEach((btn) => {
      btn.onclick = async () => {
        const username = prompt("نام کاربری نمونه‌ی جدید (که روی پنل موجود است) را وارد کن:");
        if (!username || !username.trim()) return;
        btn.textContent = "⏳...";
        try {
          await api(`/api/admin/panel-servers/${btn.dataset.template}/template`, {
            method: "POST", body: JSON.stringify({ template_username: username.trim() }),
          });
          tg.HapticFeedback.notificationOccurred("success");
          renderAdminPanelsSection();
        } catch (e) { notify(e.message); btn.textContent = "🧩 تغییر قالب"; }
      };
    });
    document.querySelectorAll("[data-xui-inbound]").forEach((btn) => {
      btn.onclick = async () => {
        const serverId = btn.dataset.xuiInbound;
        const server = servers.find((s) => String(s.id) === String(serverId));
        btn.textContent = "⏳...";
        try {
          const inbounds = await api(`/api/admin/panel-servers/${serverId}/xui-inbounds`);
          adminPanelsView = {
            level: "xui-config", serverId, inbounds, name: btn.dataset.xuiName,
            selectedIds: (server && server.xui_inbound_ids) || [],
            subBaseUrl: (server && server.xui_sub_base_url) || "",
          };
          renderAdminPanelsSection();
        } catch (e) { notify(e.message); btn.textContent = "⚙️ تنظیم Inbound"; }
      };
    });
    document.querySelectorAll("[data-suburl]").forEach((btn) => {
      btn.onclick = () => {
        adminPanelsView = { level: "suburl-config", serverId: btn.dataset.suburl, name: btn.dataset.suburlName };
        renderAdminPanelsSection();
      };
    });
    document.querySelectorAll("[data-usage-custom]").forEach((btn) => {
      btn.onclick = async () => {
        await api(`/api/admin/panel-servers/${btn.dataset.usageCustom}/usage/custom`, { method: "POST" });
        renderAdminPanelsSection();
      };
    });
    document.querySelectorAll("[data-usage-test]").forEach((btn) => {
      btn.onclick = async () => {
        await api(`/api/admin/panel-servers/${btn.dataset.usageTest}/usage/test`, { method: "POST" });
        renderAdminPanelsSection();
      };
    });
    document.querySelectorAll("[data-toggle]").forEach((btn) => {
      btn.onclick = async () => {
        await api(`/api/admin/panel-servers/${btn.dataset.toggle}/toggle`, { method: "POST" });
        renderAdminPanelsSection();
      };
    });
    document.querySelectorAll("[data-delete]").forEach((btn) => {
      btn.onclick = async () => {
        if (!confirm("این سرور حذف شود؟")) return;
        await api(`/api/admin/panel-servers/${btn.dataset.delete}`, { method: "DELETE" });
        renderAdminPanelsSection();
      };
    });
  } catch (e) {
    body.innerHTML = `<div class="card"><p class="hint-text">خطا در بارگذاری: ${e.message}</p></div>`;
  }
}

// ---------------------------------------------------------------------------
// تب مدیریت > محصولات (دسته‌بندی‌ها / محصولات / بانک کانفیگ)
// ---------------------------------------------------------------------------

async function renderAdminCatalogSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(3);
  try {
    if (adminCatalogView.level === "categories") {
      await renderAdminCategories(body);
    } else if (adminCatalogView.level === "products") {
      await renderAdminProducts(body);
    } else if (adminCatalogView.level === "edit-product") {
      await renderAdminEditProduct(body);
    } else if (adminCatalogView.level === "configs") {
      await renderAdminConfigs(body);
    }
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

async function renderAdminCategories(body) {
  const cats = await api("/api/admin/categories");
  body.innerHTML = `
    <div class="card">
      ${cats.length === 0 ? `<div class="hint-text" style="margin:0">هنوز دسته‌بندی‌ای ثبت نشده.</div>` : cats.map((c) => `
        <div class="admin-list-row">
          <div class="admin-list-row-main" data-open-cat="${c.id}" data-cat-name="${(c.name || "").replace(/"/g, "&quot;")}">
            <span>${c.name}</span>
            <span class="hint-text" style="margin:0">${c.product_count} محصول ${c.is_active ? "" : "· غیرفعال"}</span>
          </div>
          <div class="admin-list-row-actions">
            <button class="btn small outline" data-edit-cat="${c.id}">✏️</button>
            <button class="btn small outline" data-toggle-cat="${c.id}">${c.is_active ? "⛔️" : "✅"}</button>
            <button class="btn small outline danger" data-del-cat="${c.id}">🗑️</button>
          </div>
        </div>
      `).join("")}
    </div>
    <div class="card">
      <div class="eyebrow" style="margin-top:0">افزودن دسته‌بندی جدید</div>
      <input class="input" id="new-cat-name" type="text" placeholder="نام دسته‌بندی" style="direction:rtl;text-align:right;font-family:var(--font-body)" />
      <button class="btn" id="new-cat-save" style="margin-top:8px">➕ افزودن</button>
    </div>
  `;
  body.querySelectorAll("[data-open-cat]").forEach((el) => {
    el.onclick = () => {
      adminCatalogView = { level: "products", categoryId: Number(el.dataset.openCat), categoryName: el.dataset.catName };
      renderAdmin();
    };
  });
  body.querySelectorAll("[data-edit-cat]").forEach((el) => {
    el.onclick = async () => {
      const cat = cats.find((c) => c.id === Number(el.dataset.editCat));
      const name = prompt("نام جدید دسته‌بندی:", cat.name);
      if (!name || !name.trim()) return;
      try {
        await api(`/api/admin/categories/${cat.id}`, { method: "PATCH", body: JSON.stringify({ name: name.trim() }) });
        renderAdmin();
      } catch (e) { notify(e.message); }
    };
  });
  body.querySelectorAll("[data-toggle-cat]").forEach((el) => {
    el.onclick = async () => {
      try {
        await api(`/api/admin/categories/${el.dataset.toggleCat}/toggle`, { method: "POST" });
        renderAdmin();
      } catch (e) { notify(e.message); }
    };
  });
  body.querySelectorAll("[data-del-cat]").forEach((el) => {
    el.onclick = async () => {
      if (!confirm("حذف این دسته‌بندی و همه‌ی محصولاتش؟ این کار برگشت‌ناپذیر است.")) return;
      try {
        await api(`/api/admin/categories/${el.dataset.delCat}`, { method: "DELETE" });
        renderAdmin();
      } catch (e) { notify(e.message); }
    };
  });
  document.getElementById("new-cat-save").onclick = async () => {
    const input = document.getElementById("new-cat-name");
    if (!input.value.trim()) return;
    try {
      await api("/api/admin/categories", { method: "POST", body: JSON.stringify({ name: input.value.trim() }) });
      renderAdmin();
    } catch (e) { notify(e.message); }
  };
}

function productProvisionFieldsHtml(panelServers) {
  if (!panelServers || !panelServers.length) return "";
  return `
    <label class="field-label">منبع کانفیگ</label>
    <div style="display:flex;gap:14px;align-items:center;margin-bottom:10px">
      <label style="display:flex;align-items:center;gap:4px"><input type="radio" name="new-prod-source" value="bank" checked /> 📦 بانک کانفیگ</label>
      <label style="display:flex;align-items:center;gap:4px"><input type="radio" name="new-prod-source" value="direct" /> 🔌 اتصال مستقیم به پنل</label>
    </div>
    <div id="new-prod-direct-fields" style="display:none;margin-bottom:8px">
      <select class="input" id="new-prod-server" style="margin-bottom:8px">${panelServers.map((s) => `<option value="${s.id}">${s.name}</option>`).join("")}</select>
      <input class="input" id="new-prod-volume" type="number" placeholder="حجم (گیگابایت)" />
    </div>
  `;
}

async function renderAdminProducts(body) {
  const { categoryId, categoryName } = adminCatalogView;
  const products = await api(`/api/admin/categories/${categoryId}/products`);
  const panelServers = await api("/api/admin/panel-servers-lite").catch(() => []);
  body.innerHTML = `
    <button class="btn outline small" id="back-to-cats" style="width:auto;margin-bottom:12px">→ بازگشت به دسته‌بندی‌ها</button>
    <div class="eyebrow" style="margin-top:0">محصولات «${categoryName}»</div>
    <div class="card">
      ${products.length === 0 ? `<div class="hint-text" style="margin:0">هنوز محصولی در این دسته ثبت نشده.</div>` : products.map((p) => `
        <div class="admin-list-row">
          <div class="admin-list-row-main" ${p.is_auto_provision ? "" : `data-open-prod="${p.id}" data-prod-name="${(p.name || "").replace(/"/g, "&quot;")}"`}>
            <span>${p.name}</span>
            <span class="hint-text" style="margin:0">${fmt(p.price)} تومان · موجودی: ${p.is_auto_provision ? "🔌 خودکار" : p.stock} ${p.is_active ? "" : "· غیرفعال"}</span>
          </div>
          <div class="admin-list-row-actions">
            <button class="btn small outline" data-edit-prod="${p.id}">✏️</button>
            <button class="btn small outline" data-toggle-prod="${p.id}">${p.is_active ? "⛔️" : "✅"}</button>
            <button class="btn small outline danger" data-del-prod="${p.id}">🗑️</button>
          </div>
        </div>
      `).join("")}
    </div>
    <div class="card">
      <div class="eyebrow" style="margin-top:0">افزودن محصول جدید</div>
      <input class="input" id="new-prod-name" type="text" placeholder="نام محصول" style="direction:rtl;text-align:right;font-family:var(--font-body);margin-bottom:8px" />
      <input class="input" id="new-prod-price" type="number" placeholder="قیمت (تومان)" style="margin-bottom:8px" />
      <input class="input" id="new-prod-duration" type="number" placeholder="مدت اعتبار (روز)" value="30" style="margin-bottom:8px" />
      <input class="input" id="new-prod-desc" type="text" placeholder="توضیحات (اختیاری)" style="direction:rtl;text-align:right;font-family:var(--font-body);margin-bottom:8px" />
      ${productProvisionFieldsHtml(panelServers)}
      <div class="field-error" id="new-prod-error"></div>
      <button class="btn" id="new-prod-save">➕ افزودن محصول</button>
    </div>
  `;
  document.getElementById("back-to-cats").onclick = () => {
    adminCatalogView = { level: "categories" };
    renderAdmin();
  };
  body.querySelectorAll("[data-open-prod]").forEach((el) => {
    el.onclick = () => {
      adminCatalogView = {
        level: "configs", productId: Number(el.dataset.openProd), productName: el.dataset.prodName,
        categoryId, categoryName,
      };
      renderAdmin();
    };
  });
  body.querySelectorAll("[data-edit-prod]").forEach((el) => {
    el.onclick = () => {
      const p = products.find((x) => x.id === Number(el.dataset.editProd));
      adminCatalogView = { level: "edit-product", product: p, categoryId, categoryName };
      renderAdmin();
    };
  });
  body.querySelectorAll("[data-toggle-prod]").forEach((el) => {
    el.onclick = async () => {
      try {
        await api(`/api/admin/products/${el.dataset.toggleProd}/toggle`, { method: "POST" });
        renderAdmin();
      } catch (e) { notify(e.message); }
    };
  });
  body.querySelectorAll("[data-del-prod]").forEach((el) => {
    el.onclick = async () => {
      if (!confirm("حذف این محصول و بانک کانفیگ‌هایش؟ این کار برگشت‌ناپذیر است.")) return;
      try {
        await api(`/api/admin/products/${el.dataset.delProd}`, { method: "DELETE" });
        renderAdmin();
      } catch (e) { notify(e.message); }
    };
  });
  const sourceRadios = body.querySelectorAll('input[name="new-prod-source"]');
  sourceRadios.forEach((r) => r.addEventListener("change", () => {
    document.getElementById("new-prod-direct-fields").style.display =
      body.querySelector('input[name="new-prod-source"]:checked').value === "direct" ? "block" : "none";
  }));
  document.getElementById("new-prod-save").onclick = async () => {
    const errBox = document.getElementById("new-prod-error");
    errBox.textContent = "";
    const name = document.getElementById("new-prod-name").value.trim();
    const price = Number(document.getElementById("new-prod-price").value);
    const duration = Number(document.getElementById("new-prod-duration").value) || 30;
    const desc = document.getElementById("new-prod-desc").value.trim();
    if (!name || !price) { errBox.textContent = "نام و قیمت الزامی است."; return; }
    const payload = { category_id: categoryId, name, price, duration_days: duration, description: desc };
    const sourceEl = body.querySelector('input[name="new-prod-source"]:checked');
    if (sourceEl && sourceEl.value === "direct") {
      const provision_server_id = Number(document.getElementById("new-prod-server").value);
      const auto_provision_volume_gb = Number(document.getElementById("new-prod-volume").value);
      if (!provision_server_id || !auto_provision_volume_gb) {
        errBox.textContent = "برای اتصال مستقیم به پنل، پنل و حجم (گیگابایت) را مشخص کنید.";
        return;
      }
      payload.provision_server_id = provision_server_id;
      payload.auto_provision_volume_gb = auto_provision_volume_gb;
    }
    try {
      await api("/api/admin/products", { method: "POST", body: JSON.stringify(payload) });
      renderAdmin();
    } catch (e) { errBox.textContent = e.message; }
  };
}

async function renderAdminEditProduct(body) {
  const { product: p, categoryId, categoryName } = adminCatalogView;
  body.innerHTML = `
    <button class="btn outline small" id="edit-prod-back" style="width:auto;margin-bottom:12px">→ بازگشت به محصولات «${categoryName}»</button>
    <div class="card">
      <div class="eyebrow" style="margin-top:0">✏️ ویرایش محصول</div>
      <label class="field-label">نام محصول</label>
      <input class="input" id="edit-prod-name" type="text" value="${(p.name || "").replace(/"/g, "&quot;")}" style="direction:rtl;text-align:right;font-family:var(--font-body);margin-bottom:10px" />
      <label class="field-label">قیمت (تومان)</label>
      <input class="input" id="edit-prod-price" type="number" value="${p.price}" style="margin-bottom:10px" />
      <label class="field-label">مدت اعتبار (روز)</label>
      <input class="input" id="edit-prod-duration" type="number" value="${p.duration_days}" style="margin-bottom:10px" />
      <label class="field-label">توضیحات (اختیاری)</label>
      <input class="input" id="edit-prod-desc" type="text" value="${(p.description || "").replace(/"/g, "&quot;")}" style="direction:rtl;text-align:right;font-family:var(--font-body);margin-bottom:10px" />
      ${p.is_auto_provision ? `<p class="hint-text">🔌 این محصول به‌صورت خودکار (${p.auto_provision_volume_gb || "?"} گیگ) ساخته می‌شود؛ منبع کانفیگ بعد از ساخت محصول قابل تغییر نیست.</p>` : ""}
      <div class="field-error" id="edit-prod-error"></div>
      <div style="display:flex;gap:8px;margin-top:8px">
        <button class="btn" id="edit-prod-save">💾 ذخیره تغییرات</button>
        <button class="btn outline" id="edit-prod-cancel">انصراف</button>
      </div>
    </div>
  `;
  const back = () => {
    adminCatalogView = { level: "products", categoryId, categoryName };
    renderAdmin();
  };
  document.getElementById("edit-prod-back").onclick = back;
  document.getElementById("edit-prod-cancel").onclick = back;
  document.getElementById("edit-prod-save").onclick = async () => {
    const errBox = document.getElementById("edit-prod-error");
    errBox.textContent = "";
    const name = document.getElementById("edit-prod-name").value.trim();
    const price = Number(document.getElementById("edit-prod-price").value);
    const duration = Number(document.getElementById("edit-prod-duration").value);
    const description = document.getElementById("edit-prod-desc").value.trim();
    if (!name || !price || !duration) { errBox.textContent = "نام، قیمت و مدت اعتبار الزامی هستند."; return; }
    try {
      await api(`/api/admin/products/${p.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name, price, duration_days: duration, description }),
      });
      tg.HapticFeedback.notificationOccurred("success");
      back();
    } catch (e) { errBox.textContent = e.message; }
  };
}

async function renderAdminConfigs(body) {
  const { productId, productName, categoryId, categoryName } = adminCatalogView;
  const configs = await api(`/api/admin/products/${productId}/configs`);
  const PAGE_SIZE = 10;
  let page = 0;
  let query = "";
  const normalizeSearchText = (s) => s.normalize("NFKC").replace(/[\s\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]/g, "").toLowerCase();
  const filteredConfigs = () => {
    const q = normalizeSearchText(query);
    return q ? configs.filter((c) => normalizeSearchText(c.link).includes(q)) : configs;
  };
  const totalPages = () => Math.max(1, Math.ceil(filteredConfigs().length / PAGE_SIZE));

  body.innerHTML = `
    <button class="btn outline small" id="back-to-prods" style="width:auto;margin-bottom:12px">→ بازگشت به محصولات «${categoryName}»</button>
    <div class="eyebrow" style="margin-top:0">بانک کانفیگ «${productName}»</div>
    <div class="card">
      <div class="eyebrow" style="margin-top:0">🎲 دریافت کانفیگ رندوم</div>
      <p class="hint-text">یکی از کانفیگ‌های آزاد این محصول به‌صورت تصادفی برداشته و به تو اختصاص داده می‌شود (از انبار کم می‌شود).</p>
      <button class="btn outline" id="take-random-cfg-btn">🎲 دریافت یک کانفیگ رندوم</button>
      <div id="random-cfg-result"></div>
    </div>
    <div class="card">
      <p class="hint-text" id="cfg-stock-count" style="margin:0 0 10px">موجودی فعلی: ${configs.length} کانفیگ استفاده‌نشده</p>
      <input class="input" id="cfg-search" type="text" dir="ltr" placeholder="🔍 جستجو در لینک کانفیگ‌ها..." style="direction:ltr;text-align:left;margin-bottom:10px" />
      <div id="cfg-list-box"></div>
      <div id="cfg-pagination" style="display:flex;align-items:center;justify-content:space-between;margin-top:10px"></div>
    </div>
    <div class="card">
      <div class="eyebrow" style="margin-top:0">افزودن دسته‌ای کانفیگ</div>
      <p class="hint-text">هر خط یک لینک کانفیگ (vmess/vless/...) وارد کن.</p>
      <textarea class="input" id="new-configs-bulk" rows="5" style="direction:ltr;text-align:left;resize:vertical"></textarea>
      <button class="btn" id="new-configs-save" style="margin-top:8px">➕ افزودن به انبار</button>
    </div>
  `;

  function renderCfgList() {
    const listBox = document.getElementById("cfg-list-box");
    const pagBox = document.getElementById("cfg-pagination");
    const items = filteredConfigs();
    if (page >= totalPages()) page = totalPages() - 1;
    if (page < 0) page = 0;
    const start = page * PAGE_SIZE;
    const pageItems = items.slice(start, start + PAGE_SIZE);

    listBox.innerHTML = items.length === 0
      ? `<div class="hint-text" style="margin:0">${query ? "کانفیگی با این جستجو پیدا نشد." : "کانفیگی در انبار نیست."}</div>`
      : pageItems.map((c) => `
          <div class="admin-list-row">
            <div class="admin-list-row-main" style="direction:ltr;text-align:left;font-family:var(--font-mono);font-size:12px;word-break:break-all;white-space:normal;user-select:all">${c.link}</div>
            <div class="admin-list-row-actions">
              <button class="btn small outline danger" data-del-cfg="${c.id}">🗑️</button>
            </div>
          </div>
        `).join("");

    listBox.querySelectorAll("[data-del-cfg]").forEach((el) => {
      el.onclick = async () => {
        if (!confirm("این کانفیگ حذف شود؟")) return;
        try {
          await api(`/api/admin/configs/${el.dataset.delCfg}`, { method: "DELETE" });
          const idx = configs.findIndex((c) => String(c.id) === el.dataset.delCfg);
          if (idx !== -1) configs.splice(idx, 1);
          document.getElementById("cfg-stock-count").textContent = `موجودی فعلی: ${configs.length} کانفیگ استفاده‌نشده`;
          renderCfgList();
        } catch (e2) { notify(e2.message); }
      };
    });

    pagBox.innerHTML = items.length === 0 ? "" : `
      <button class="btn small outline" id="cfg-prev-page" ${page === 0 ? "disabled" : ""}>◀ قبلی</button>
      <span class="hint-text" style="margin:0">صفحه ${page + 1} از ${totalPages()}${query ? ` (${items.length} نتیجه)` : ""}</span>
      <button class="btn small outline" id="cfg-next-page" ${page >= totalPages() - 1 ? "disabled" : ""}>بعدی ▶</button>
    `;
    const prevBtn = document.getElementById("cfg-prev-page");
    const nextBtn = document.getElementById("cfg-next-page");
    if (prevBtn) prevBtn.onclick = () => { page--; renderCfgList(); };
    if (nextBtn) nextBtn.onclick = () => { page++; renderCfgList(); };
  }

  renderCfgList();

  const searchInput = document.getElementById("cfg-search");
  const applySearch = () => {
    query = searchInput.value;
    page = 0;
    renderCfgList();
  };
  searchInput.addEventListener("input", applySearch);
  searchInput.addEventListener("keyup", applySearch);
  searchInput.addEventListener("change", applySearch);

  document.getElementById("back-to-prods").onclick = () => {
    adminCatalogView = { level: "products", categoryId, categoryName };
    renderAdmin();
  };
  document.getElementById("take-random-cfg-btn").onclick = async () => {
    const resultBox = document.getElementById("random-cfg-result");
    try {
      const res = await api(`/api/admin/products/${productId}/take-random-config`, { method: "POST" });
      tg.HapticFeedback.notificationOccurred("success");
      resultBox.innerHTML = `
        <div class="hint-text" style="margin:10px 0 4px">کانفیگ دریافت‌شده (این مورد از انبار کم شد):</div>
        <div class="input" style="direction:ltr;text-align:left;word-break:break-all;user-select:all">${res.link}</div>
      `;
      // به‌جای رفرش کامل صفحه (که نتیجه‌ی بالا را پاک می‌کند)، فقط لیست و شمارنده را به‌روزرسانی می‌کنیم
      const idx = configs.findIndex((c) => c.id === res.id);
      if (idx !== -1) configs.splice(idx, 1);
      document.getElementById("cfg-stock-count").textContent = `موجودی فعلی: ${configs.length} کانفیگ استفاده‌نشده`;
      renderCfgList();
    } catch (e) {
      resultBox.innerHTML = `<div class="field-error" style="margin-top:10px">${e.message}</div>`;
    }
  };
  body.querySelectorAll("[data-del-cfg]").forEach((el) => {
    el.onclick = async () => {
      if (!confirm("این کانفیگ حذف شود؟")) return;
      try {
        await api(`/api/admin/configs/${el.dataset.delCfg}`, { method: "DELETE" });
        renderAdmin();
      } catch (e) { notify(e.message); }
    };
  });
  document.getElementById("new-configs-save").onclick = async () => {
    const raw = document.getElementById("new-configs-bulk").value;
    const links = raw.split("\n").map((l) => l.trim()).filter(Boolean);
    if (links.length === 0) { notify("هیچ لینکی وارد نشده."); return; }
    try {
      const res = await api(`/api/admin/products/${productId}/configs`, { method: "POST", body: JSON.stringify({ links }) });
      tg.HapticFeedback.notificationOccurred("success");
      notify(`${res.added} کانفیگ اضافه شد.`);
      renderAdmin();
    } catch (e) { notify(e.message); }
  };
}

// ---------------------------------------------------------------------------
// تب مدیریت > مدیریت کاربران (کیف‌پول و در آینده امکانات بیشتر)
// ---------------------------------------------------------------------------

let adminUserView = { level: "list", filter: "all", query: "" };
const USER_STATUS_LABEL = { active: "فعال", expired: "منقضی‌شده", blocked: "بلاک‌شده", none: "بدون سرویس" };
const USER_STATUS_BADGE_CLASS = { active: "approved", expired: "pending", blocked: "rejected", none: "" };

function escHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function renderAdminUsersSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(3);
  try {
    if (adminUserView.level === "list") await renderAdminUsersList(body);
    else await renderAdminUserDetail(body);
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

async function renderAdminUsersList(body) {
  const filter = adminUserView.filter || "all";
  const query = adminUserView.query || "";
  const data = await api(`/api/admin/users?query=${encodeURIComponent(query)}&status=${filter}&limit=50&offset=0`);

  const filters = [
    { k: "all", label: "همه" },
    { k: "active", label: "فعال" },
    { k: "expired", label: "منقضی‌شده" },
    { k: "blocked", label: "بلاک‌شده" },
  ];

  body.innerHTML = `
    <div class="card">
      <div class="eyebrow" style="margin-top:0">📢 پیام گروهی به کاربران منقضی‌شده</div>
      <textarea class="input" id="broadcast-expired-text" rows="2" placeholder="متن پیام تشویق به تمدید..." style="margin-bottom:8px;resize:vertical"></textarea>
      <button class="btn outline small" id="broadcast-expired-btn" style="width:auto">ارسال به همه‌ی کاربران منقضی‌شده</button>
    </div>

    <div class="card">
      <input class="input" id="user-search-input" type="text" placeholder="جستجو با آیدی عددی، یوزرنیم یا نام..." value="${escHtml(query)}" style="margin-bottom:10px" />
      <div class="segmented" style="margin-bottom:0">
        ${filters.map((f) => `<button class="seg-btn ${filter === f.k ? "active" : ""}" data-user-filter="${f.k}">${f.label}</button>`).join("")}
      </div>
    </div>

    <div class="card">
      ${data.users.length === 0
        ? `<div class="state-msg"><span class="ic">👤</span>کاربری پیدا نشد.</div>`
        : data.users.map((u) => `
        <div class="admin-list-row" data-open-user="${u.telegram_id}" style="cursor:pointer">
          <div class="admin-list-row-main">
            <span>${escHtml(u.first_name || "بدون نام")}${u.username ? " (@" + escHtml(u.username) + ")" : ""}</span>
            <span class="hint-text" style="margin:0">🆔 ${u.telegram_id} · 👛 ${fmt(u.wallet_credit)} تومان</span>
          </div>
          <div class="admin-list-row-actions">
            <span class="badge ${USER_STATUS_BADGE_CLASS[u.status]}">${USER_STATUS_LABEL[u.status]}</span>
          </div>
        </div>
      `).join("")}
    </div>
    ${data.total > data.users.length ? `<p class="hint-text" style="text-align:center">${data.users.length} از ${data.total} کاربر نمایش داده شد؛ برای محدودکردن نتایج جستجو کنید.</p>` : ""}
  `;

  document.getElementById("user-search-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      adminUserView = { ...adminUserView, query: e.target.value.trim() };
      renderAdminUsersSection();
    }
  });
  body.querySelectorAll("[data-user-filter]").forEach((el) => {
    el.onclick = () => {
      adminUserView = { ...adminUserView, filter: el.dataset.userFilter };
      renderAdminUsersSection();
    };
  });
  body.querySelectorAll("[data-open-user]").forEach((el) => {
    el.onclick = () => {
      adminUserView = { level: "detail", telegramId: Number(el.dataset.openUser), returnTo: adminUserView };
      renderAdminUsersSection();
    };
  });
  document.getElementById("broadcast-expired-btn").onclick = async () => {
    const text = document.getElementById("broadcast-expired-text").value.trim();
    if (!text) { notify("متن پیام را وارد کن."); return; }
    if (!confirm("این پیام برای همه‌ی کاربران منقضی‌شده ارسال می‌شود. ادامه؟")) return;
    try {
      const res = await api("/api/admin/users/broadcast-expired", { method: "POST", body: JSON.stringify({ text }) });
      tg.HapticFeedback.notificationOccurred("success");
      notify(`ارسال شد. موفق: ${res.success} از ${res.total}`);
      document.getElementById("broadcast-expired-text").value = "";
    } catch (e) { notify("⚠️ " + e.message); }
  };
}

async function renderAdminUserDetail(body) {
  const { telegramId } = adminUserView;
  const u = await api(`/api/admin/users/${telegramId}`);

  const statusLine = `<span class="badge ${USER_STATUS_BADGE_CLASS[u.status]}">${USER_STATUS_LABEL[u.status]}</span>`;

  const ordersHtml = u.orders.length === 0
    ? `<div class="hint-text" style="margin:0">هیچ سفارشی ثبت نکرده.</div>`
    : u.orders.map((o) => `
      <div class="admin-list-row">
        <div class="admin-list-row-main">
          <span>${escHtml(o.product_name || "نامشخص")} — ${fmt(o.final_price ?? o.base_price ?? 0)} تومان</span>
          <span class="hint-text" style="margin:0">#${o.id} · ${o.created_at ? toJalaliStr(o.created_at, true) : ""}${o.config_link ? " · دارای کانفیگ" : ""}</span>
        </div>
        <div class="admin-list-row-actions">
          <span class="badge ${o.status === "approved" ? "approved" : o.status === "pending" ? "pending" : "rejected"}">${o.status === "approved" ? "تاییدشده" : o.status === "pending" ? "در انتظار" : "ردشده"}</span>
        </div>
      </div>
    `).join("");

  const topupsHtml = u.topups.length === 0
    ? `<div class="hint-text" style="margin:0">هیچ شارژ کیف‌پولی ثبت نکرده.</div>`
    : u.topups.map((t) => `
      <div class="admin-list-row">
        <div class="admin-list-row-main">
          <span>${fmt(t.amount)} تومان</span>
          <span class="hint-text" style="margin:0">${t.created_at ? toJalaliStr(t.created_at, true) : ""}</span>
        </div>
        <div class="admin-list-row-actions">
          <span class="badge ${t.status === "approved" ? "approved" : t.status === "pending" ? "pending" : "rejected"}">${t.status === "approved" ? "تاییدشده" : t.status === "pending" ? "در انتظار" : "ردشده"}</span>
        </div>
      </div>
    `).join("");

  body.innerHTML = `
    <button class="btn outline small" id="back-to-user-list" style="width:auto;margin-bottom:12px">→ بازگشت به لیست کاربران</button>

    <div class="card">
      <div class="eyebrow" style="margin-top:0">${escHtml(u.first_name || "بدون نام")}${u.username ? " (@" + escHtml(u.username) + ")" : ""}</div>
      <div class="stat-row"><span>🆔 آیدی عددی</span><span>${u.telegram_id}</span></div>
      <div class="stat-row"><span>📅 تاریخ عضویت</span><span>${u.joined_at ? toJalaliStr(u.joined_at) : "---"}</span></div>
      <div class="stat-row"><span>👛 موجودی کیف‌پول</span><span>${fmt(u.wallet_credit)} تومان</span></div>
      <div class="stat-row"><span>وضعیت سرویس</span>${statusLine}</div>
      <button class="btn ${u.is_blocked ? "" : "outline"} small" id="toggle-block-btn" style="width:auto;margin-top:10px">
        ${u.is_blocked ? "✅ رفع بلاک کاربر" : "⛔️ بلاک‌کردن کاربر"}
      </button>
    </div>

    <div class="card">
      <div class="eyebrow" style="margin-top:0">✏️ تغییر موجودی کیف‌پول</div>
      <input class="input" id="detail-wallet-amount" type="number" placeholder="مثال: 50000 یا -20000" style="margin-bottom:8px" />
      <button class="btn small" id="detail-wallet-save" style="width:auto">💾 اعمال تغییر</button>
    </div>

    <div class="card">
      <div class="eyebrow" style="margin-top:0">✉️ ارسال پیام مستقیم</div>
      <textarea class="input" id="detail-message-text" rows="2" placeholder="متن پیام..." style="margin-bottom:8px;resize:vertical"></textarea>
      <button class="btn small" id="detail-message-send" style="width:auto">ارسال پیام</button>
    </div>

    <div class="eyebrow">🧾 تاریخچه سفارش‌ها</div>
    <div class="card">${ordersHtml}</div>

    <div class="eyebrow">💳 تاریخچه شارژ کیف‌پول</div>
    <div class="card">${topupsHtml}</div>
  `;

  document.getElementById("back-to-user-list").onclick = () => {
    adminUserView = adminUserView.returnTo || { level: "list", filter: "all", query: "" };
    renderAdminUsersSection();
  };

  document.getElementById("toggle-block-btn").onclick = async () => {
    const willBlock = !u.is_blocked;
    if (willBlock && !confirm("این کاربر بلاک شود؟ دیگر نمی‌تواند از بات یا فروشگاه استفاده کند.")) return;
    try {
      await api(`/api/admin/users/${telegramId}/block`, { method: "POST", body: JSON.stringify({ blocked: willBlock }) });
      tg.HapticFeedback.notificationOccurred("success");
      notify(willBlock ? "کاربر بلاک شد." : "بلاک کاربر برداشته شد.");
      renderAdminUsersSection();
    } catch (e) { notify("⚠️ " + e.message); }
  };

  document.getElementById("detail-wallet-save").onclick = async () => {
    const amountRaw = document.getElementById("detail-wallet-amount").value.trim();
    const amount = Number(amountRaw);
    if (!amountRaw || isNaN(amount) || amount === 0) { notify("مبلغ باید عددی غیرصفر باشد."); return; }
    try {
      const res = await api("/api/admin/wallet/adjust", {
        method: "POST",
        body: JSON.stringify({ telegram_id: telegramId, amount }),
      });
      tg.HapticFeedback.notificationOccurred("success");
      notify(`موجودی به ${fmt(res.new_balance)} تومان تغییر کرد.`);
      renderAdminUsersSection();
    } catch (e) { notify("⚠️ " + e.message); }
  };

  document.getElementById("detail-message-send").onclick = async () => {
    const text = document.getElementById("detail-message-text").value.trim();
    if (!text) { notify("متن پیام را وارد کن."); return; }
    try {
      await api(`/api/admin/users/${telegramId}/message`, { method: "POST", body: JSON.stringify({ text }) });
      tg.HapticFeedback.notificationOccurred("success");
      notify("پیام ارسال شد.");
      document.getElementById("detail-message-text").value = "";
    } catch (e) { notify("⚠️ " + e.message); }
  };
}

// ---------------------------------------------------------------------------
// تب مدیریت > لاگ فعالیت ادمین
// ---------------------------------------------------------------------------

const ADMIN_ACTION_LABELS = {
  wallet_adjust: "✏️ تغییر موجودی کیف‌پول",
  product_price_edit: "💲 ویرایش قیمت محصول",
  order_approve: "✅ تایید سفارش",
  order_reject: "❌ رد سفارش",
  topup_approve: "✅ تایید شارژ کیف‌پول",
  topup_reject: "❌ رد شارژ کیف‌پول",
  admin_add: "➕ افزودن ادمین",
  admin_remove: "➖ حذف ادمین",
  admin_role_change: "🔄 تغییر نقش ادمین",
  card_change: "💳 تغییر شماره کارت",
  plisio_key_change: "🪙 تغییر کلید کریپتو (Plisio)",
  abangateway_key_change: "💳 تغییر کلید آبان گیت‌وی",
  backup_create: "🗄 دریافت بکاپ",
  backup_restore: "♻️ بازیابی بکاپ",
  category_add: "📂 افزودن دسته‌بندی",
  category_toggle: "📂 تغییر وضعیت دسته‌بندی",
  category_delete: "🗑 حذف دسته‌بندی",
  product_add: "📦 افزودن محصول",
  product_toggle: "📦 تغییر وضعیت محصول",
  product_delete: "🗑 حذف محصول",
  discount_add: "🎟 افزودن کد تخفیف",
  discount_toggle: "🎟 تغییر وضعیت کد تخفیف",
  discount_delete: "🗑 حذف کد تخفیف",
  broadcast: "📢 ارسال پیام همگانی",
};

let adminLogSelectedId = "";

function _renderAdminLogRows(logs) {
  if (logs.length === 0) return `<div class="hint-text" style="margin:0">هنوز رخدادی برای این ادمین ثبت نشده.</div>`;
  return logs.map((l) => `
    <div class="admin-list-row">
      <div class="admin-list-row-main">
        <span>${ADMIN_ACTION_LABELS[l.action] || l.action}</span>
        <span class="hint-text" style="margin:0">${escHtml(l.details)}</span>
        <span class="hint-text" style="margin:0">👤 ${escHtml(l.admin_name)} (${l.admin_id}) · ${toJalaliStr(l.created_at, true)}</span>
      </div>
    </div>
  `).join("");
}

async function searchAdminLogById() {
  const input = document.getElementById("adminlog-id-input");
  const resultsBox = document.getElementById("adminlog-results");
  const id = (input.value || "").trim();
  if (!id || !/^\d+$/.test(id)) {
    resultsBox.innerHTML = `<div class="hint-text" style="margin:0">لطفاً آیدی عددی ادمین را وارد کن.</div>`;
    return;
  }
  adminLogSelectedId = id;
  resultsBox.innerHTML = skeleton(3);
  try {
    const data = await api(`/api/admin/logs?limit=100&offset=0&admin_id=${id}`);
    resultsBox.innerHTML = `
      <div class="card" style="margin-top:10px">
        ${_renderAdminLogRows(data.logs)}
      </div>
      ${data.total > data.logs.length ? `<p class="hint-text" style="text-align:center">${data.logs.length} از ${data.total} رخداد نمایش داده شد.</p>` : ""}
    `;
  } catch (e) {
    resultsBox.innerHTML = errorState(e.message);
  }
}

async function renderAdminLogSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(4);
  try {
    const adminsData = await api("/api/admin/logs/admins");
    const admins = adminsData.admins || [];
    body.innerHTML = `
      <div class="card">
        <div class="eyebrow" style="margin-top:0">📜 لاگ فعالیت ادمین</div>
        <p class="hint-text">تایید/رد سفارش و شارژ کیف‌پول، تغییر موجودی، مدیریت ادمین‌ها، محصولات، بکاپ و سایر اقدامات هر ادمین اینجا با آیدی عددی همان ادمین ثبت و نمایش داده می‌شود.</p>
        <div style="display:flex;gap:6px;margin-top:8px">
          <input type="text" inputmode="numeric" id="adminlog-id-input" placeholder="آیدی عددی ادمین را وارد کن" value="${escHtml(adminLogSelectedId)}" style="flex:1" />
          <button class="btn small" id="adminlog-search-btn" style="width:auto">جستجو</button>
        </div>
        ${admins.length ? `
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px">
            ${admins.map((a) => `<button class="btn small outline adminlog-chip" data-admin-id="${a.telegram_id}" style="width:auto">${escHtml(a.name) || a.telegram_id} (${a.telegram_id})</button>`).join("")}
          </div>
        ` : ""}
      </div>
      <div id="adminlog-results">
        ${adminLogSelectedId ? "" : `<div class="card"><div class="hint-text" style="margin:0">برای مشاهده‌ی لاگ، آیدی عددی یک ادمین را وارد کن یا از لیست بالا انتخاب کن.</div></div>`}
      </div>
    `;
    document.getElementById("adminlog-search-btn").addEventListener("click", searchAdminLogById);
    document.getElementById("adminlog-id-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") searchAdminLogById();
    });
    document.querySelectorAll(".adminlog-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.getElementById("adminlog-id-input").value = btn.dataset.adminId;
        searchAdminLogById();
      });
    });
    if (adminLogSelectedId) await searchAdminLogById();
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

// ---------------------------------------------------------------------------
// تب مدیریت > بکاپ و بازیابی (فقط مالک اصلی)
// ---------------------------------------------------------------------------

async function downloadAdminBackup() {
  const btn = document.getElementById("admin-backup-create-btn");
  const status = document.getElementById("admin-backup-status");
  if (btn) btn.disabled = true;
  status.innerHTML = `<span class="hint-text">⏳ در حال آماده‌سازی و ارسال بکاپ به چت بات...</span>`;
  try {
    const result = await api("/api/admin/backup/create", { method: "POST" });
    status.innerHTML = `<span class="hint-text">✅ بکاپ (${escHtml(result.filename)}) به چت بات ارسال شد. برای دریافت فایل، چت بات خودت را در تلگرام باز کن.</span>`;
  } catch (e) {
    status.innerHTML = errorState(e.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

let adminRestorePendingFile = null;

function renderAdminRestoreUploadUI() {
  const status = document.getElementById("admin-restore-status");
  const fileInput = document.getElementById("admin-restore-file");
  if (!adminRestorePendingFile) {
    status.innerHTML = "";
    if (fileInput) fileInput.style.display = "";
    return;
  }
  if (fileInput) fileInput.style.display = "none";
  const sizeMb = (adminRestorePendingFile.size / (1024 * 1024)).toFixed(1);
  status.innerHTML = `
    <div class="card" style="margin-top:0">
      <p class="hint-text" style="margin:0 0 8px">📦 فایل انتخاب‌شده: ${escHtml(adminRestorePendingFile.name)} (${sizeMb} مگابایت)</p>
      <p class="hint-text" style="margin:0 0 10px">⚠️ با تایید، دیتابیس فعلی جایگزین می‌شود (یک نسخه از وضعیت فعلی هم قبلش ذخیره می‌شود).</p>
      <div style="display:flex;gap:8px">
        <button class="btn small" id="admin-restore-confirm-btn" style="width:auto">✅ تایید و جایگزینی</button>
        <button class="btn small outline" id="admin-restore-cancel-btn" style="width:auto">❌ انصراف</button>
      </div>
    </div>
  `;
  document.getElementById("admin-restore-confirm-btn").onclick = confirmAdminRestore;
  document.getElementById("admin-restore-cancel-btn").onclick = cancelAdminRestore;
}

function cancelAdminRestore() {
  adminRestorePendingFile = null;
  const fileInput = document.getElementById("admin-restore-file");
  if (fileInput) fileInput.value = "";
  renderAdminRestoreUploadUI();
}

async function confirmAdminRestore() {
  const file = adminRestorePendingFile;
  const status = document.getElementById("admin-restore-status");
  if (!file) return;
  status.innerHTML = `<span class="hint-text">⏳ در حال بازیابی...</span>`;
  try {
    const formData = new FormData();
    formData.append("file", file);
    const result = await apiUpload("/api/admin/backup/restore", formData);
    adminRestorePendingFile = null;
    status.innerHTML = `<span class="hint-text">✅ دیتابیس با موفقیت بازیابی شد. نسخه‌ی قبلی هم به‌عنوان «${escHtml(result.pre_restore_backup)}» کنار دیتابیس ذخیره شد. صفحه را رفرش کن.</span>`;
    const fileInput = document.getElementById("admin-restore-file");
    if (fileInput) { fileInput.value = ""; fileInput.style.display = ""; }
  } catch (e) {
    status.innerHTML = errorState(e.message);
  }
}

function selectAdminRestoreFile(file) {
  if (!file) return;
  if (!/\.(db|sqlite|sqlite3)$/i.test(file.name)) {
    document.getElementById("admin-restore-status").innerHTML = errorState("فایل باید پسوند .db یا .sqlite داشته باشد.");
    return;
  }
  adminRestorePendingFile = file;
  renderAdminRestoreUploadUI();
}

async function renderAdminBackupSection() {
  adminRestorePendingFile = null;
  const body = document.getElementById("admin-section-body");
  body.innerHTML = `
    <div class="card">
      <div class="eyebrow" style="margin-top:0">📥 دریافت بکاپ فوری</div>
      <p class="hint-text">یک نسخه‌ی کامل از دیتابیس فعلی همین الان ساخته و به چت بات ارسال می‌شود.</p>
      <button class="btn" id="admin-backup-create-btn">📥 دریافت بکاپ فوری</button>
      <div id="admin-backup-status" style="margin-top:10px"></div>
    </div>
    <div class="card">
      <div class="eyebrow" style="margin-top:0">♻️ بازیابی از فایل بکاپ</div>
      <p class="hint-text">⚠️ با آپلود یک فایل بکاپ (.db)، دیتابیس فعلی کامل با آن جایگزین می‌شود. این کار قابل بازگشت نیست مگر با بکاپ دیگری. قبل از جایگزینی، یک نسخه‌ی ایمن از وضعیت فعلی هم خودکار ذخیره می‌شود.</p>
      <input type="file" id="admin-restore-file" accept=".db,.sqlite,.sqlite3" style="margin-bottom:10px" />
      <div id="admin-restore-status"></div>
    </div>
  `;
  document.getElementById("admin-backup-create-btn").onclick = downloadAdminBackup;
  document.getElementById("admin-restore-file").onchange = (e) => {
    const file = e.target.files[0];
    selectAdminRestoreFile(file);
  };
}

// ---------------------------------------------------------------------------
// تب مدیریت > فروش (رفرال / گردونه شانس / یادآوری تمدید / کدهای تخفیف)
// ---------------------------------------------------------------------------

async function renderAdminSalesSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(4);
  try {
    const [referral, wheel, renewal, volumeRem, discounts, allProducts] = await Promise.all([
      api("/api/admin/settings/referral"),
      api("/api/admin/settings/wheel"),
      api("/api/admin/settings/renewal"),
      api("/api/admin/settings/volume-reminder"),
      api("/api/admin/discounts"),
      api("/api/admin/products/all").catch(() => []),
    ]);

    const eligibleProducts = (allProducts || []).filter((p) => p.is_auto_provision && p.provision_server_id);
    const fcProductOptions = eligibleProducts
      .map((p) => `<option value="${p.id}" ${referral.free_config_product_id === p.id ? "selected" : ""}>${p.name} (${p.category_name})${p.is_active ? "" : " - غیرفعال"}</option>`)
      .join("");

    body.innerHTML = `
      <div class="card">
        <div class="eyebrow" style="margin-top:0">🤝 زیرمجموعه‌گیری (رفرال) — سه مدل مستقل</div>
        <p class="hint-text">هر کدام از این سه مدل جدا فعال/غیرفعال می‌شود و هم‌زمان می‌توانند فعال باشند.</p>

        <div class="eyebrow" style="margin-top:14px">① پورسانت درصدی از خرید</div>
        <p class="hint-text">وقتی کاربری با لینک دعوت یکی دیگه وارد بشه و اولین خریدش تایید بشه، درصدی از خریدش به‌عنوان اعتبار کیف‌پول به دعوت‌کننده تعلق می‌گیره.</p>
        <div class="field-switch-row">
          <span>فعال باشد</span>
          <label class="switch"><input type="checkbox" id="ref-enabled" ${referral.enabled ? "checked" : ""} /><span class="switch-slider"></span></label>
        </div>
        <label class="field-label">درصد پاداش دعوت‌کننده از هر خرید زیرمجموعه (۰ تا ۱۰۰)</label>
        <input class="input" id="ref-percent" type="number" placeholder="مثال: 10" value="${referral.percent}" style="margin-bottom:10px" />
        <label class="field-label">سقف تعداد نفراتی که پورسانت خریدشان تعلق می‌گیرد (۰ = نامحدود)</label>
        <input class="input" id="ref-commission-max" type="number" placeholder="مثال: 5" value="${referral.commission_max_count}" style="margin-bottom:4px" />

        <div class="eyebrow" style="margin-top:18px">② کانفیگ رایگان با تعداد دعوت مشخص</div>
        <p class="hint-text">با رسیدن تعداد کل دعوت‌شده‌ها (بدون نیاز به خرید آن‌ها) به یک آستانه، محصول انتخابی به‌صورت خودکار روی پنل ساخته و برای دعوت‌کننده ارسال می‌شود.</p>
        <div class="field-switch-row">
          <span>فعال باشد</span>
          <label class="switch"><input type="checkbox" id="ref-fc-enabled" ${referral.free_config_enabled ? "checked" : ""} /><span class="switch-slider"></span></label>
        </div>
        <label class="field-label">تعداد دعوت لازم</label>
        <input class="input" id="ref-fc-threshold" type="number" placeholder="مثال: 10" value="${referral.free_config_threshold}" style="margin-bottom:10px" />
        <label class="field-label">محصول جایزه (فقط محصولات با تحویل خودکار و متصل به پنل)</label>
        <select class="input" id="ref-fc-product" style="margin-bottom:4px">
          <option value="">— انتخاب کنید —</option>
          ${fcProductOptions}
        </select>

        <div class="eyebrow" style="margin-top:18px">③ شارژ ثابت کیف پول به‌ازای هر دعوت</div>
        <p class="hint-text">با ورود هر نفر از طریق لینک دعوت (بدون نیاز به خرید)، مبلغ ثابتی بلافاصله به کیف پول دعوت‌کننده اضافه می‌شود.</p>
        <div class="field-switch-row">
          <span>فعال باشد</span>
          <label class="switch"><input type="checkbox" id="ref-ib-enabled" ${referral.invite_bonus_enabled ? "checked" : ""} /><span class="switch-slider"></span></label>
        </div>
        <label class="field-label">مبلغ شارژ به‌ازای هر دعوت (تومان)</label>
        <input class="input" id="ref-ib-amount" type="number" placeholder="مثال: 5000" value="${referral.invite_bonus_amount}" style="margin-bottom:10px" />
        <label class="field-label">سقف تعداد دعوت‌های مشمول (۰ = نامحدود)</label>
        <input class="input" id="ref-ib-max" type="number" placeholder="مثال: 10" value="${referral.invite_bonus_max_count}" style="margin-bottom:4px" />

        <div class="field-error" id="ref-error"></div>
        <button class="btn" id="ref-save" style="margin-top:8px">💾 ذخیره همه‌ی تنظیمات رفرال</button>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">🎡 گردونه شانس</div>
        <p class="hint-text">کاربرها با گردوندن این چرخ، شانس بردن کد تخفیف دارن.</p>
        <div class="field-switch-row">
          <span>گردونه شانس فعال باشد</span>
          <label class="switch"><input type="checkbox" id="wheel-enabled" ${wheel.enabled ? "checked" : ""} /><span class="switch-slider"></span></label>
        </div>
        <label class="field-label">احتمال برد در هر چرخش (درصد از ۰ تا ۱۰۰)</label>
        <input class="input" id="wheel-win-percent" type="number" placeholder="مثال: 30" value="${wheel.win_percent}" style="margin-bottom:10px" />
        <label class="field-label">لیست درصد جوایز، با کاما جدا شود</label>
        <input class="input" id="wheel-prizes" type="text" placeholder="مثال: 10,20,30,50" value="${wheel.prizes.join(",")}" style="margin-bottom:10px" />
        <label class="field-label">مدت اعتبار کد جایزه پس از برد (ساعت)</label>
        <input class="input" id="wheel-expiry" type="number" placeholder="مثال: 24" value="${wheel.expiry_hours}" style="margin-bottom:10px" />
        <label class="field-label">حداقل فاصله‌ی زمانی بین دو چرخش هر کاربر (ساعت)</label>
        <input class="input" id="wheel-cooldown" type="number" placeholder="مثال: 24" value="${wheel.cooldown_hours}" style="margin-bottom:4px" />
        <div class="field-error" id="wheel-error"></div>
        <button class="btn" id="wheel-save" style="margin-top:8px">💾 ذخیره</button>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">⏰ یادآوری تمدید سرویس</div>
        <p class="hint-text">چند روز مانده به اتمام سرویس، به کاربر پیام یادآوری همراه با کد تخفیف تشویقی برای تمدید فرستاده می‌شود.</p>
        <div class="field-switch-row">
          <span>یادآوری تمدید فعال باشد</span>
          <label class="switch"><input type="checkbox" id="ren-enabled" ${renewal.enabled ? "checked" : ""} /><span class="switch-slider"></span></label>
        </div>
        <label class="field-label">چند روز مانده به پایان سرویس، یادآوری ارسال شود</label>
        <input class="input" id="ren-days" type="number" placeholder="مثال: 5" value="${renewal.days_before}" style="margin-bottom:10px" />
        <label class="field-label">درصد تخفیف کد تشویقی تمدید (۰ تا ۱۰۰)</label>
        <input class="input" id="ren-percent" type="number" placeholder="مثال: 20" value="${renewal.discount_percent}" style="margin-bottom:10px" />
        <label class="field-label">مدت اعتبار کد تشویقی (ساعت)</label>
        <input class="input" id="ren-expiry" type="number" placeholder="مثال: 24" value="${renewal.discount_expiry_hours}" style="margin-bottom:4px" />
        <div class="field-error" id="ren-error"></div>
        <button class="btn" id="ren-save" style="margin-top:8px">💾 ذخیره</button>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">📉 یادآوری اتمام حجم</div>
        <p class="hint-text">وقتی حجم مصرفی کاربر به آستانه‌ی تعیین‌شده برسد، پیام یادآوری همراه با کد تخفیف تشویقی برای تمدید فرستاده می‌شود. این یادآوری مستقل از یادآوری تاریخ انقضاست و برای کانفیگ‌های با حجم نامحدود اعمال نمی‌شود.</p>
        <div class="field-switch-row">
          <span>یادآوری اتمام حجم فعال باشد</span>
          <label class="switch"><input type="checkbox" id="vol-enabled" ${volumeRem.enabled ? "checked" : ""} /><span class="switch-slider"></span></label>
        </div>
        <label class="field-label">مبنای آستانه</label>
        <select class="input" id="vol-mode" style="margin-bottom:10px">
          <option value="percent" ${volumeRem.mode === "percent" ? "selected" : ""}>درصد مصرف</option>
          <option value="gb" ${volumeRem.mode === "gb" ? "selected" : ""}>حجم باقی‌مانده (گیگابایت)</option>
        </select>
        <label class="field-label">وقتی چند درصد از حجم مصرف شد (حالت «درصد مصرف»)</label>
        <input class="input" id="vol-percent" type="number" placeholder="مثال: 80" value="${volumeRem.percent}" style="margin-bottom:10px" />
        <label class="field-label">وقتی چند گیگابایت باقی ماند (حالت «حجم باقی‌مانده»)</label>
        <input class="input" id="vol-gb" type="number" step="0.1" placeholder="مثال: 2" value="${volumeRem.gb_left}" style="margin-bottom:10px" />
        <label class="field-label">درصد تخفیف کد تشویقی (۰ تا ۱۰۰)</label>
        <input class="input" id="vol-discount-percent" type="number" placeholder="مثال: 20" value="${volumeRem.discount_percent}" style="margin-bottom:10px" />
        <label class="field-label">مدت اعتبار کد تشویقی (ساعت)</label>
        <input class="input" id="vol-discount-expiry" type="number" placeholder="مثال: 24" value="${volumeRem.discount_expiry_hours}" style="margin-bottom:4px" />
        <div class="field-error" id="vol-error"></div>
        <button class="btn" id="vol-save" style="margin-top:8px">💾 ذخیره</button>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">🏷️ کدهای تخفیف</div>
        <div id="discounts-list">
          ${discounts.length === 0 ? `<div class="hint-text" style="margin:0">هنوز کد تخفیفی ثبت نشده.</div>` : discounts.map((d) => `
            <div class="admin-list-row">
              <div class="admin-list-row-main">
                <span style="direction:ltr">${d.code}</span>
                <span class="hint-text" style="margin:0">
                  ${d.percent ? `${d.percent}٪` : `${fmt(d.fixed_amount)} تومان`} ·
                  استفاده: ${d.used_count}${d.max_uses ? "/" + d.max_uses : " (نامحدود)"}
                  ${d.is_active ? "" : "· غیرفعال"}
                </span>
              </div>
              <div class="admin-list-row-actions">
                <button class="btn small outline" data-toggle-disc="${d.id}">${d.is_active ? "⛔️" : "✅"}</button>
                <button class="btn small outline danger" data-del-disc="${d.id}">🗑️</button>
              </div>
            </div>
          `).join("")}
        </div>
        <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--glass-brd)">
          <div class="eyebrow">افزودن کد تخفیف جدید</div>
          <label class="field-label">کد تخفیف (حروف/عدد انگلیسی، مثال: SUMMER25)</label>
          <input class="input" id="new-disc-code" type="text" placeholder="SUMMER25" style="margin-bottom:10px;direction:ltr;text-align:left" />
          <label class="field-label">درصد تخفیف (اگر می‌خوای درصدی باشه)</label>
          <input class="input" id="new-disc-percent" type="number" placeholder="مثال: 25" style="margin-bottom:10px" />
          <label class="field-label">یا مبلغ ثابت تخفیف به تومان (فقط یکی از این دو را پر کن)</label>
          <input class="input" id="new-disc-fixed" type="number" placeholder="مثال: 50000" style="margin-bottom:10px" />
          <label class="field-label">حداکثر تعداد دفعات استفاده (۰ یعنی نامحدود)</label>
          <input class="input" id="new-disc-maxuses" type="number" placeholder="0" value="0" style="margin-bottom:4px" />
          <div class="field-error" id="new-disc-error"></div>
          <button class="btn" id="new-disc-save" style="margin-top:8px">➕ افزودن کد تخفیف</button>
        </div>
      </div>
    `;

    document.getElementById("ref-save").onclick = async () => {
      const errBox = document.getElementById("ref-error");
      errBox.textContent = "";
      const percentRaw = document.getElementById("ref-percent").value.trim();
      if (percentRaw === "") { errBox.textContent = "درصد پاداش را وارد کن."; return; }
      const percent = Number(percentRaw);
      if (isNaN(percent) || percent < 0 || percent > 100) { errBox.textContent = "درصد باید عددی بین ۰ تا ۱۰۰ باشد."; return; }

      const commissionMax = Number(document.getElementById("ref-commission-max").value.trim() || "0");
      if (isNaN(commissionMax) || commissionMax < 0) { errBox.textContent = "سقف تعداد نفرات نمی‌تواند منفی باشد."; return; }

      const fcEnabled = document.getElementById("ref-fc-enabled").checked;
      const fcThreshold = Number(document.getElementById("ref-fc-threshold").value.trim() || "0");
      const fcProductRaw = document.getElementById("ref-fc-product").value;
      const fcProductId = fcProductRaw ? Number(fcProductRaw) : null;
      if (fcEnabled && (!fcProductId || fcThreshold < 1)) { errBox.textContent = "برای فعال‌سازی کانفیگ رایگان، محصول جایزه و تعداد دعوت معتبر لازم است."; return; }

      const ibEnabled = document.getElementById("ref-ib-enabled").checked;
      const ibAmount = Number(document.getElementById("ref-ib-amount").value.trim() || "0");
      const ibMax = Number(document.getElementById("ref-ib-max").value.trim() || "0");
      if (ibEnabled && ibAmount <= 0) { errBox.textContent = "برای فعال‌سازی شارژ به‌ازای دعوت، مبلغ باید بزرگ‌تر از صفر باشد."; return; }
      if (isNaN(ibAmount) || ibAmount < 0 || isNaN(ibMax) || ibMax < 0) { errBox.textContent = "مقادیر عددی نمی‌توانند منفی باشند."; return; }

      try {
        await api("/api/admin/settings/referral", {
          method: "POST",
          body: JSON.stringify({
            enabled: document.getElementById("ref-enabled").checked,
            percent,
            commission_max_count: commissionMax,
            free_config_enabled: fcEnabled,
            free_config_threshold: fcThreshold,
            free_config_product_id: fcProductId,
            invite_bonus_enabled: ibEnabled,
            invite_bonus_amount: ibAmount,
            invite_bonus_max_count: ibMax,
          }),
        });
        tg.HapticFeedback.notificationOccurred("success");
        notify("تنظیمات رفرال ذخیره شد.");
      } catch (e) { errBox.textContent = e.message; }
    };

    document.getElementById("wheel-save").onclick = async () => {
      const errBox = document.getElementById("wheel-error");
      errBox.textContent = "";
      const winRaw = document.getElementById("wheel-win-percent").value.trim();
      const prizesRaw = document.getElementById("wheel-prizes").value.trim();
      const expiryRaw = document.getElementById("wheel-expiry").value.trim();
      const cooldownRaw = document.getElementById("wheel-cooldown").value.trim();
      if (!winRaw || !prizesRaw || !expiryRaw || !cooldownRaw) { errBox.textContent = "همه‌ی کادرها باید پر شوند."; return; }
      const winPercent = Number(winRaw);
      const prizes = prizesRaw.split(",").map((p) => Number(p.trim())).filter((p) => p > 0);
      const expiry = Number(expiryRaw);
      const cooldown = Number(cooldownRaw);
      if (isNaN(winPercent) || winPercent < 0 || winPercent > 100) { errBox.textContent = "احتمال برد باید عددی بین ۰ تا ۱۰۰ باشد."; return; }
      if (prizes.length === 0) { errBox.textContent = "حداقل یک جایزه‌ی معتبر وارد کن."; return; }
      if (isNaN(expiry) || expiry <= 0) { errBox.textContent = "اعتبار کد جایزه باید عددی بزرگ‌تر از صفر باشد."; return; }
      if (isNaN(cooldown) || cooldown <= 0) { errBox.textContent = "فاصله‌ی بین چرخش‌ها باید عددی بزرگ‌تر از صفر باشد."; return; }
      try {
        await api("/api/admin/settings/wheel", {
          method: "POST",
          body: JSON.stringify({
            enabled: document.getElementById("wheel-enabled").checked,
            win_percent: winPercent, prizes, expiry_hours: expiry, cooldown_hours: cooldown,
          }),
        });
        tg.HapticFeedback.notificationOccurred("success");
        notify("تنظیمات گردونه شانس ذخیره شد.");
      } catch (e) { errBox.textContent = e.message; }
    };

    document.getElementById("ren-save").onclick = async () => {
      const errBox = document.getElementById("ren-error");
      errBox.textContent = "";
      const daysRaw = document.getElementById("ren-days").value.trim();
      const percentRaw = document.getElementById("ren-percent").value.trim();
      const expiryRaw = document.getElementById("ren-expiry").value.trim();
      if (!daysRaw || !percentRaw || !expiryRaw) { errBox.textContent = "همه‌ی کادرها باید پر شوند."; return; }
      const days = Number(daysRaw), percent = Number(percentRaw), expiry = Number(expiryRaw);
      if (isNaN(days) || days <= 0) { errBox.textContent = "تعداد روز باید عددی بزرگ‌تر از صفر باشد."; return; }
      if (isNaN(percent) || percent < 0 || percent > 100) { errBox.textContent = "درصد تخفیف باید عددی بین ۰ تا ۱۰۰ باشد."; return; }
      if (isNaN(expiry) || expiry <= 0) { errBox.textContent = "اعتبار کد باید عددی بزرگ‌تر از صفر باشد."; return; }
      try {
        await api("/api/admin/settings/renewal", {
          method: "POST",
          body: JSON.stringify({
            enabled: document.getElementById("ren-enabled").checked,
            days_before: days, discount_percent: percent, discount_expiry_hours: expiry,
          }),
        });
        tg.HapticFeedback.notificationOccurred("success");
        notify("تنظیمات یادآوری تمدید ذخیره شد.");
      } catch (e) { errBox.textContent = e.message; }
    };

    document.getElementById("vol-save").onclick = async () => {
      const errBox = document.getElementById("vol-error");
      errBox.textContent = "";
      const mode = document.getElementById("vol-mode").value;
      const percentRaw = document.getElementById("vol-percent").value.trim();
      const gbRaw = document.getElementById("vol-gb").value.trim();
      const discPercentRaw = document.getElementById("vol-discount-percent").value.trim();
      const discExpiryRaw = document.getElementById("vol-discount-expiry").value.trim();
      if (!percentRaw || !gbRaw || !discPercentRaw || !discExpiryRaw) { errBox.textContent = "همه‌ی کادرها باید پر شوند."; return; }
      const percent = Number(percentRaw), gb = Number(gbRaw);
      const discPercent = Number(discPercentRaw), discExpiry = Number(discExpiryRaw);
      if (isNaN(percent) || percent <= 0 || percent >= 100) { errBox.textContent = "درصد آستانه باید عددی بین ۱ تا ۹۹ باشد."; return; }
      if (isNaN(gb) || gb <= 0) { errBox.textContent = "آستانه‌ی گیگابایت باید عددی بزرگ‌تر از صفر باشد."; return; }
      if (isNaN(discPercent) || discPercent < 0 || discPercent > 100) { errBox.textContent = "درصد تخفیف باید عددی بین ۰ تا ۱۰۰ باشد."; return; }
      if (isNaN(discExpiry) || discExpiry <= 0) { errBox.textContent = "اعتبار کد باید عددی بزرگ‌تر از صفر باشد."; return; }
      try {
        await api("/api/admin/settings/volume-reminder", {
          method: "POST",
          body: JSON.stringify({
            enabled: document.getElementById("vol-enabled").checked,
            mode, percent, gb_left: gb,
            discount_percent: discPercent, discount_expiry_hours: discExpiry,
          }),
        });
        tg.HapticFeedback.notificationOccurred("success");
        notify("تنظیمات یادآوری اتمام حجم ذخیره شد.");
      } catch (e) { errBox.textContent = e.message; }
    };

    body.querySelectorAll("[data-toggle-disc]").forEach((el) => {
      el.onclick = async () => {
        try {
          await api(`/api/admin/discounts/${el.dataset.toggleDisc}/toggle`, { method: "POST" });
          renderAdminSalesSection();
        } catch (e) { notify(e.message); }
      };
    });
    body.querySelectorAll("[data-del-disc]").forEach((el) => {
      el.onclick = async () => {
        if (!confirm("این کد تخفیف حذف شود؟")) return;
        try {
          await api(`/api/admin/discounts/${el.dataset.delDisc}`, { method: "DELETE" });
          renderAdminSalesSection();
        } catch (e) { notify(e.message); }
      };
    });
    document.getElementById("new-disc-save").onclick = async () => {
      const errBox = document.getElementById("new-disc-error");
      errBox.textContent = "";
      const code = document.getElementById("new-disc-code").value.trim();
      const percentVal = document.getElementById("new-disc-percent").value.trim();
      const fixedVal = document.getElementById("new-disc-fixed").value.trim();
      const maxUses = Number(document.getElementById("new-disc-maxuses").value) || 0;
      if (!code) { errBox.textContent = "کد تخفیف را وارد کن."; return; }
      if (!percentVal && !fixedVal) { errBox.textContent = "باید یکی از دو کادر درصد یا مبلغ ثابت را پر کنی."; return; }
      if (percentVal && fixedVal) { errBox.textContent = "فقط یکی از دو کادر درصد یا مبلغ ثابت را پر کن، نه هردو."; return; }
      try {
        await api("/api/admin/discounts", {
          method: "POST",
          body: JSON.stringify({
            code, percent: percentVal ? Number(percentVal) : null,
            fixed_amount: fixedVal ? Number(fixedVal) : null, max_uses: maxUses,
          }),
        });
        tg.HapticFeedback.notificationOccurred("success");
        renderAdminSalesSection();
      } catch (e) { errBox.textContent = e.message; }
    };
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

// ---------------------------------------------------------------------------
// تب مدیریت > مالی و پرداخت (شماره کارت / کریپتو / آبان گیت‌وی)
// ---------------------------------------------------------------------------

async function renderAdminFinanceSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(3);
  try {
    const [card, crypto, aban] = await Promise.all([
      api("/api/admin/settings/card"),
      api("/api/admin/settings/crypto"),
      api("/api/admin/settings/abangateway"),
    ]);

    body.innerHTML = `
      <div class="card">
        <div class="eyebrow" style="margin-top:0">🏦 شماره کارت (پرداخت دستی با رسید)</div>
        <p class="hint-text">این شماره کارت به کاربر برای واریز دستی و ارسال رسید نمایش داده می‌شه.</p>
        <label class="field-label">شماره کارت</label>
        <input class="input" id="fin-card-number" type="text" placeholder="6037-XXXX-XXXX-XXXX" value="${(card.card_number || "").replace(/"/g, "&quot;")}" style="direction:ltr;text-align:left;margin-bottom:10px" />
        <label class="field-label">نام صاحب کارت</label>
        <input class="input" id="fin-card-holder" type="text" placeholder="نام و نام خانوادگی" value="${(card.card_holder || "").replace(/"/g, "&quot;")}" style="margin-bottom:4px" />
        <div class="field-error" id="fin-card-error"></div>
        <button class="btn" id="fin-card-save" style="margin-top:8px">💾 ذخیره شماره کارت</button>
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">🪙 پرداخت کریپتو (Plisio)</div>
        <p class="hint-text">با فعال شدن، کاربر هم موقع خرید مستقیم و هم موقع شارژ کیف پول می‌تونه با ارز دیجیتال (BTC/ETH/USDT/...) پرداخت کنه و بلافاصله بعد از تایید تراکنش، سفارش/کیف‌پول به‌صورت خودکار تسویه می‌شه.</p>
        <label class="field-label">API Key (از plisio.net → API Settings)</label>
        <input class="input" id="fin-crypto-key" type="password" placeholder="${crypto.has_own_key ? crypto.masked_key || "•••• تنظیم شده" : "کلید را وارد کن"}" style="direction:ltr;text-align:left;margin-bottom:4px" />
        <p class="hint-text" style="margin-bottom:10px">برای تغییر کلید، کلید جدید را وارد و ذخیره کن. کادر را خالی بگذاری، کلید فعلی دست‌نخورده می‌ماند.</p>
        <div class="field-switch-row">
          <span>پرداخت کریپتو فعال باشد</span>
          <label class="switch"><input type="checkbox" id="fin-crypto-enabled" ${crypto.enabled ? "checked" : ""} /><span class="switch-slider"></span></label>
        </div>
        <label class="field-label">نرخ تبدیل هر ۱ دلار به تومان (خالی یا ۰ = خودکار از tgju/نوبیتکس/والکس/ارزدیجیتال)</label>
        <input class="input" id="fin-crypto-rate" type="number" placeholder="خودکار" value="${crypto.usd_to_toman_rate || ""}" style="margin-bottom:4px" />
        <div class="field-error" id="fin-crypto-error"></div>
        <button class="btn" id="fin-crypto-save" style="margin-top:8px">💾 ذخیره</button>
        ${crypto.has_own_key ? `<button class="btn outline danger" id="fin-crypto-clear" style="margin-top:8px">🗑 حذف کلید و غیرفعال‌سازی</button>` : ""}
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">💳 آبان گیت‌وی (کارت به کارت خودکار)</div>
        <p class="hint-text">با فعال شدن، پرداخت کارت به کارت به‌صورت خودکار از طریق آبان گیت‌وی تایید می‌شه، بدون نیاز به بررسی دستی رسید.</p>
        <label class="field-label">API Key (از abangateway.ir → تنظیمات API)</label>
        <input class="input" id="fin-aban-key" type="password" placeholder="${aban.has_own_key ? aban.masked_key || "•••• تنظیم شده" : "کلید را وارد کن"}" style="direction:ltr;text-align:left;margin-bottom:4px" />
        <p class="hint-text" style="margin-bottom:10px">برای تغییر کلید، کلید جدید را وارد و ذخیره کن. کادر را خالی بگذاری، کلید فعلی دست‌نخورده می‌ماند.</p>
        <div class="field-switch-row">
          <span>آبان گیت‌وی فعال باشد</span>
          <label class="switch"><input type="checkbox" id="fin-aban-enabled" ${aban.enabled ? "checked" : ""} /><span class="switch-slider"></span></label>
        </div>
        <div class="field-error" id="fin-aban-error"></div>
        <button class="btn" id="fin-aban-save" style="margin-top:8px">💾 ذخیره</button>
        ${aban.has_own_key ? `<button class="btn outline danger" id="fin-aban-clear" style="margin-top:8px">🗑 حذف کلید و غیرفعال‌سازی</button>` : ""}
      </div>

      <div class="card">
        <div class="eyebrow" style="margin-top:0">🔌 درگاه‌های پرداخت سفارشی</div>
        <p class="hint-text">هر درگاه دیگری غیر از موارد بالا (داخلی، خارجی، هرچی) رو با وصل‌کردن API خودش، بدون نوشتن کد اضافه کن.</p>
        <button class="btn" id="fin-open-custom-gateways">🧩 مدیریت درگاه‌های سفارشی</button>
      </div>
    `;

    document.getElementById("fin-open-custom-gateways").onclick = () => {
      window.location.href = withTenant("gateways.html");
    };

    document.getElementById("fin-card-save").onclick = async () => {
      const errBox = document.getElementById("fin-card-error");
      errBox.textContent = "";
      const cardNumber = document.getElementById("fin-card-number").value.trim();
      const cardHolder = document.getElementById("fin-card-holder").value.trim();
      if (!cardNumber || !cardHolder) { errBox.textContent = "هر دو کادر باید پر باشند."; return; }
      try {
        await api("/api/admin/settings/card", {
          method: "POST",
          body: JSON.stringify({ card_number: cardNumber, card_holder: cardHolder }),
        });
        tg.HapticFeedback.notificationOccurred("success");
        notify("شماره کارت ذخیره شد.");
      } catch (e) { errBox.textContent = e.message; }
    };

    document.getElementById("fin-crypto-save").onclick = async () => {
      const errBox = document.getElementById("fin-crypto-error");
      errBox.textContent = "";
      const rateRaw = document.getElementById("fin-crypto-rate").value.trim();
      const rate = rateRaw ? Number(rateRaw) : 0;
      if (isNaN(rate) || rate < 0) { errBox.textContent = "نرخ تبدیل باید عددی معتبر باشد (یا خالی بذار برای حالت خودکار)."; return; }
      const keyInput = document.getElementById("fin-crypto-key").value;
      try {
        await api("/api/admin/settings/crypto", {
          method: "POST",
          body: JSON.stringify({
            enabled: document.getElementById("fin-crypto-enabled").checked,
            usd_to_toman_rate: rate,
            api_key: keyInput === "" ? null : keyInput,
          }),
        });
        tg.HapticFeedback.notificationOccurred("success");
        notify("تنظیمات پرداخت کریپتو ذخیره شد.");
        renderAdminFinanceSection();
      } catch (e) { errBox.textContent = e.message; }
    };

    const cryptoClearBtn = document.getElementById("fin-crypto-clear");
    if (cryptoClearBtn) {
      cryptoClearBtn.onclick = async () => {
        if (!confirm("کلید API کریپتو حذف و درگاه غیرفعال شود؟")) return;
        try {
          await api("/api/admin/settings/crypto", {
            method: "POST",
            body: JSON.stringify({ enabled: false, usd_to_toman_rate: Number(document.getElementById("fin-crypto-rate").value.trim() || 0), api_key: "" }),
          });
          tg.HapticFeedback.notificationOccurred("success");
          notify("کلید کریپتو حذف شد.");
          renderAdminFinanceSection();
        } catch (e) { notify(e.message); }
      };
    }

    document.getElementById("fin-aban-save").onclick = async () => {
      const errBox = document.getElementById("fin-aban-error");
      errBox.textContent = "";
      const keyInput = document.getElementById("fin-aban-key").value;
      try {
        await api("/api/admin/settings/abangateway", {
          method: "POST",
          body: JSON.stringify({
            enabled: document.getElementById("fin-aban-enabled").checked,
            api_key: keyInput === "" ? null : keyInput,
          }),
        });
        tg.HapticFeedback.notificationOccurred("success");
        notify("تنظیمات آبان گیت‌وی ذخیره شد.");
        renderAdminFinanceSection();
      } catch (e) { errBox.textContent = e.message; }
    };

    const abanClearBtn = document.getElementById("fin-aban-clear");
    if (abanClearBtn) {
      abanClearBtn.onclick = async () => {
        if (!confirm("کلید API آبان گیت‌وی حذف و درگاه غیرفعال شود؟")) return;
        try {
          await api("/api/admin/settings/abangateway", {
            method: "POST",
            body: JSON.stringify({ enabled: false, api_key: "" }),
          });
          tg.HapticFeedback.notificationOccurred("success");
          notify("کلید آبان گیت‌وی حذف شد.");
          renderAdminFinanceSection();
        } catch (e) { notify(e.message); }
      };
    }
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

// ---------------------------------------------------------------------------
// تب مدیریت > پشتیبانی زنده
// ---------------------------------------------------------------------------

async function renderAdminLiveChatSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(3);
  clearInterval(adminLiveChatPollTimer);
  try {
    if (adminLiveChatView.level === "list") {
      await renderAdminLiveChatList(body);
      adminLiveChatPollTimer = setInterval(() => {
        if (adminLiveChatView.level === "list") renderAdminLiveChatList(body).catch(() => {});
      }, 6000);
    } else {
      await renderAdminLiveChatThread(body);
    }
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

async function renderAdminLiveChatList(body) {
  const convs = await api("/api/admin/support/conversations");
  body.innerHTML = `
    <div class="card">
      ${convs.length === 0 ? `<div class="hint-text" style="margin:0">هنوز گفتگویی ثبت نشده.</div>` : convs.map((c) => `
        <div class="admin-list-row" data-open-chat="${c.user_id}" style="cursor:pointer">
          <div class="admin-list-row-main">
            <span>${c.user_name || "کاربر"} (@${c.user_username || "---"})${c.unread ? ` <span class="badge">${c.unread}</span>` : ""}</span>
            <span class="hint-text" style="margin:0">${c.last_sender === "admin" ? "شما: " : ""}${(c.last_message || "").slice(0, 40)}${c.locked_for_me ? " · 🔒 پاسخ توسط ادمین دیگر" : ""}</span>
          </div>
        </div>
      `).join("")}
    </div>
  `;
  body.querySelectorAll("[data-open-chat]").forEach((el) => {
    el.onclick = () => {
      clearInterval(adminLiveChatPollTimer);
      adminLiveChatView = { level: "thread", userId: Number(el.dataset.openChat) };
      renderAdminLiveChatSection();
    };
  });
}

let adminChatThreadLastId = 0;

async function renderAdminLiveChatThread(body) {
  const { userId } = adminLiveChatView;
  const data = await api(`/api/admin/support/${userId}/messages`);
  const { user, messages } = data;
  adminChatThreadLastId = messages.length ? messages[messages.length - 1].id : 0;
  body.innerHTML = `
    <button class="btn outline small" id="back-to-admin-chats" style="width:auto;margin-bottom:12px">→ بازگشت به لیست گفتگوها</button>
    <div class="eyebrow" style="margin-top:0">${user.user_name || "کاربر"} (@${user.user_username || "---"}) · شناسه: ${user.user_id}</div>
    ${user.locked_for_me ? `<p class="hint-text">🔒 این گفتگو در حال حاضر توسط ادمین دیگری پاسخ داده می‌شود.</p>` : ""}
    <div class="chat-wrap">
      <div class="chat-messages" id="admin-chat-messages"></div>
      ${user.locked_for_me
        ? ""
        : `<form class="chat-input-row" id="admin-chat-form">
            <input type="text" id="admin-chat-input" placeholder="پاسخ خود را بنویسید..." autocomplete="off" />
            <button type="submit" class="chat-send-btn" aria-label="ارسال">
              <svg viewBox="0 0 24 24" fill="none"><path d="M4 12 20 4l-6 16-3-7-7-1Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>
            </button>
          </form>`}
    </div>
  `;
  document.getElementById("back-to-admin-chats").onclick = () => {
    clearInterval(adminLiveChatPollTimer);
    adminLiveChatView = { level: "list" };
    renderAdminLiveChatSection();
  };
  const box = document.getElementById("admin-chat-messages");
  if (messages.length === 0) {
    box.innerHTML = `<div class="state-msg"><span class="ic">💬</span>پیامی هنوز ثبت نشده.</div>`;
  }
  messages.forEach((m) => appendAdminChatMessage(box, m));
  box.scrollTop = box.scrollHeight;

  if (!user.locked_for_me) {
    const form = document.getElementById("admin-chat-form");
    const input = document.getElementById("admin-chat-input");
    form.onsubmit = async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      appendAdminChatMessage(box, { sender: "admin", message: text, created_at: new Date().toISOString() });
      box.scrollTop = box.scrollHeight;
      try {
        await api(`/api/admin/support/${userId}/messages`, { method: "POST", body: JSON.stringify({ message: text }) });
      } catch (e2) {
        notify("خطا: " + e2.message);
      }
    };
  }

  clearInterval(adminLiveChatPollTimer);
  adminLiveChatPollTimer = setInterval(async () => {
    if (adminLiveChatView.level !== "thread" || adminLiveChatView.userId !== userId) return;
    try {
      const fresh = await api(`/api/admin/support/${userId}/messages?since_id=${adminChatThreadLastId}`);
      fresh.messages.forEach((m) => appendAdminChatMessage(box, m));
      if (fresh.messages.length) box.scrollTop = box.scrollHeight;
    } catch (e) {
      // در پس‌زمینه صامت
    }
  }, 4000);
}

function appendAdminChatMessage(box, m) {
  if (!box) return;
  if (box.querySelector(".state-msg")) box.innerHTML = "";
  if (m.id) adminChatThreadLastId = Math.max(adminChatThreadLastId, m.id);
  const time = new Date(m.created_at).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${m.sender === "admin" ? "mine" : "admin"}`;
  bubble.innerHTML = `<div class="chat-text"></div><div class="chat-time">${time}</div>`;
  bubble.querySelector(".chat-text").textContent = m.message;
  box.appendChild(bubble);
}

// ---------------------------------------------------------------------------
// تب مدیریت > تیکت‌ها
// ---------------------------------------------------------------------------

async function renderAdminTicketsSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(3);
  try {
    if (adminTicketView.level === "list") await renderAdminTicketsList(body);
    else await renderAdminTicketThread(body);
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}

async function renderAdminTicketsList(body) {
  const tickets = await api("/api/admin/tickets");
  body.innerHTML = `
    <div class="card">
      ${tickets.length === 0 ? `<div class="hint-text" style="margin:0">هیچ تیکتی ثبت نشده.</div>` : tickets.map((t) => `
        <div class="admin-list-row" data-open-admin-ticket="${t.id}" style="cursor:pointer">
          <div class="admin-list-row-main">
            <span>${t.subject}</span>
            <span class="hint-text" style="margin:0">${t.user_name || "کاربر"} (@${t.user_username || "---"}) · ${TICKET_STATUS_LABEL[t.status] || t.status}${t.locked_for_me ? " · 🔒 پاسخ توسط ادمین دیگر" : ""}</span>
          </div>
        </div>
      `).join("")}
    </div>
  `;
  body.querySelectorAll("[data-open-admin-ticket]").forEach((el) => {
    el.onclick = () => {
      adminTicketView = { level: "thread", ticketId: Number(el.dataset.openAdminTicket) };
      renderAdminTicketsSection();
    };
  });
}

async function renderAdminTicketThread(body) {
  const { ticketId } = adminTicketView;
  const data = await api(`/api/admin/tickets/${ticketId}/messages`);
  const { ticket, messages } = data;
  const closed = ticket.status === "closed";
  const locked = ticket.locked_for_me;
  body.innerHTML = `
    <button class="btn outline small" id="back-to-admin-tickets" style="width:auto;margin-bottom:12px">→ بازگشت به لیست تیکت‌ها</button>
    <div class="eyebrow" style="margin-top:0">${ticket.subject}</div>
    <p class="hint-text">${ticket.user_name || "کاربر"} (@${ticket.user_username || "---"}) · شناسه: ${ticket.user_id} · ${TICKET_STATUS_LABEL[ticket.status] || ""}</p>
    ${locked ? `<p class="hint-text">🔒 این تیکت توسط ادمین دیگری claim شده و فقط برای او (و مالک) فعال است.</p>` : ""}
    <div class="chat-wrap">
      <div class="chat-messages" id="admin-ticket-messages"></div>
      ${closed
        ? `<p class="hint-text" style="text-align:center">این تیکت بسته شده است.</p>`
        : locked
        ? ""
        : `<form class="chat-input-row" id="admin-ticket-form">
            <input type="text" id="admin-ticket-input" placeholder="پاسخ خود را بنویسید..." autocomplete="off" />
            <button type="submit" class="chat-send-btn" aria-label="ارسال">
              <svg viewBox="0 0 24 24" fill="none"><path d="M4 12 20 4l-6 16-3-7-7-1Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>
            </button>
          </form>
          <button class="btn outline small" id="admin-close-ticket-btn" style="width:auto;margin-top:8px">بستن این تیکت</button>`}
    </div>
  `;
  document.getElementById("back-to-admin-tickets").onclick = () => {
    adminTicketView = { level: "list" };
    renderAdminTicketsSection();
  };
  const box = document.getElementById("admin-ticket-messages");
  if (messages.length === 0) {
    box.innerHTML = `<div class="state-msg"><span class="ic">🎫</span>پیامی هنوز ثبت نشده.</div>`;
  }
  messages.forEach((m) => {
    if (box.querySelector(".state-msg")) box.innerHTML = "";
    const time = new Date(m.created_at).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${m.sender === "admin" ? "mine" : "admin"}`;
    bubble.innerHTML = `<div class="chat-text"></div><div class="chat-time">${time}</div>`;
    bubble.querySelector(".chat-text").textContent = m.message;
    box.appendChild(bubble);
  });
  box.scrollTop = box.scrollHeight;

  if (!closed && !locked) {
    const form = document.getElementById("admin-ticket-form");
    const input = document.getElementById("admin-ticket-input");
    form.onsubmit = async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      const time = new Date().toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
      const bubble = document.createElement("div");
      bubble.className = "chat-bubble mine";
      bubble.innerHTML = `<div class="chat-text"></div><div class="chat-time">${time}</div>`;
      bubble.querySelector(".chat-text").textContent = text;
      box.appendChild(bubble);
      box.scrollTop = box.scrollHeight;
      try {
        await api(`/api/admin/tickets/${ticketId}/messages`, { method: "POST", body: JSON.stringify({ message: text }) });
      } catch (e2) {
        notify("خطا: " + e2.message);
      }
    };
    document.getElementById("admin-close-ticket-btn").onclick = async () => {
      if (!confirm("این تیکت بسته شود؟")) return;
      try {
        await api(`/api/admin/tickets/${ticketId}/close`, { method: "POST" });
        renderAdminTicketsSection();
      } catch (e) { notify(e.message); }
    };
  }
}

// ---------------------------------------------------------------------------
// تب مدیریت > نمایندگی‌ها (فقط بات اصلی)
// ---------------------------------------------------------------------------

async function renderAdminResellersSection() {
  const body = document.getElementById("admin-section-body");
  body.innerHTML = skeleton(3);
  try {
    const resellers = await api("/api/admin/resellers");
    body.innerHTML = `
      <p class="hint-text">تغییرات فعال/غیرفعال‌کردن یا حذف، حداکثر تا ۱۰ ثانیه دیگر روی بات واقعی اعمال می‌شود.</p>
      <div class="card">
        ${resellers.length === 0 ? `<div class="hint-text" style="margin:0">هنوز نماینده‌ای ثبت نشده.</div>` : resellers.map((r) => `
          <div class="reseller-row" style="${resellers.indexOf(r) > 0 ? "border-top:1px solid var(--border,rgba(255,255,255,.08));padding-top:12px;margin-top:12px" : ""}">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
              <div style="display:flex;align-items:center;gap:6px;direction:ltr">
                <span style="font-weight:600">@${r.bot_username}</span>
                ${r.is_active ? `<span class="badge" style="background:rgba(60,220,140,.15);color:#3cdc8c">فعال</span>` : `<span class="badge" style="background:rgba(255,90,122,.15);color:var(--danger,#ff5a7a)">غیرفعال</span>`}
              </div>
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                ${r.miniapp_link ? `<button class="btn small outline" data-copy-res-link="${r.id}">🔗 کپی لینک</button>` : ""}
                <button class="btn small outline" data-regen-res-link="${r.id}">🔁 تغییر لینک مینی‌اپ</button>
                <button class="btn small outline" data-edit-res="${r.id}">✏️ ویرایش</button>
                <button class="btn small outline" data-change-res-token="${r.id}">🔄 تغییر بات</button>
                <button class="btn small outline" data-toggle-res="${r.id}">${r.is_active ? "⛔️ غیرفعال" : "✅ فعال"}</button>
                <button class="btn small outline danger" data-del-res="${r.id}">🗑️ حذف</button>
              </div>
            </div>
            <div class="hint-text" style="margin:8px 0 0">👤 ${r.owner_name || "بدون نام"} &nbsp;·&nbsp; شناسه: ${r.owner_telegram_id}</div>
            ${r.miniapp_link ? `
              <div class="hint-text" style="margin:4px 0 0;direction:ltr;text-align:left;word-break:break-all;opacity:.85">${r.miniapp_link}</div>
            ` : `<div class="hint-text" style="margin:4px 0 0;color:var(--danger,#ff5a7a)">⚠️ آدرس MINIAPP_URL روی سرور تنظیم نشده - لینک ساخته نمی‌شود.</div>`}
          </div>
        `).join("")}
      </div>
      <div class="card">
        <div class="eyebrow" style="margin-top:0">افزودن نماینده‌ی جدید</div>
        <input class="input" id="new-res-token" type="text" placeholder="توکن بات (از BotFather)" style="margin-bottom:8px" />
        <button class="btn outline" id="new-res-validate">🔎 بررسی توکن</button>
        <div id="new-res-step2" style="display:none;margin-top:10px">
          <p class="hint-text" id="new-res-username-line"></p>
          <input class="input" id="new-res-owner-id" type="number" placeholder="آیدی عددی نماینده" style="margin-bottom:8px" />
          <input class="input" id="new-res-owner-name" type="text" placeholder="نام نماینده (برای نمایش)" style="direction:rtl;text-align:right;font-family:var(--font-body);margin-bottom:8px" />
          <button class="btn" id="new-res-save">➕ افزودن نماینده</button>
        </div>
      </div>
    `;
    body.querySelectorAll("[data-copy-res-link]").forEach((el) => {
      el.onclick = async () => {
        const r = resellers.find((x) => x.id === Number(el.dataset.copyResLink));
        if (!r || !r.miniapp_link) return;
        try {
          await navigator.clipboard.writeText(r.miniapp_link);
          notify("لینک مینی‌اپ کپی شد ✅");
        } catch (e) {
          prompt("کپی خودکار ممکن نشد؛ لینک را دستی کپی کن:", r.miniapp_link);
        }
      };
    });
    body.querySelectorAll("[data-edit-res]").forEach((el) => {
      el.onclick = async () => {
        const r = resellers.find((x) => x.id === Number(el.dataset.editRes));
        const ownerId = prompt("آیدی عددی نماینده:", r.owner_telegram_id);
        if (ownerId === null || !ownerId.trim()) return;
        const ownerName = prompt("نام نماینده:", r.owner_name || "");
        if (ownerName === null) return;
        try {
          await api(`/api/admin/resellers/${r.id}`, {
            method: "PATCH",
            body: JSON.stringify({ owner_telegram_id: Number(ownerId), owner_name: ownerName.trim() }),
          });
          renderAdmin();
        } catch (e) { notify(e.message); }
      };
    });
    body.querySelectorAll("[data-regen-res-link]").forEach((el) => {
      el.onclick = async () => {
        const ok = confirm("لینک فعلی مینی‌اپ این نماینده از کار می‌افتد و یک لینک تازه ساخته می‌شود.\nادامه می‌دی؟");
        if (!ok) return;
        try {
          const res = await api(`/api/admin/resellers/${el.dataset.regenResLink}/regenerate-link`, { method: "POST" });
          tg.HapticFeedback.notificationOccurred("success");
          try {
            await navigator.clipboard.writeText(res.miniapp_link);
            notify("✅ لینک جدید ساخته و کپی شد.");
          } catch (e) {
            prompt("لینک جدید مینی‌اپ (کپی کن):", res.miniapp_link);
          }
          renderAdmin();
        } catch (e) { notify(e.message); }
      };
    });
    body.querySelectorAll("[data-change-res-token]").forEach((el) => {
      el.onclick = async () => {
        const r = resellers.find((x) => x.id === Number(el.dataset.changeResToken));
        const newToken = prompt(`توکن جدید بات را وارد کن (از BotFather).\nبات فعلی: @${r.bot_username}\n\n⚠️ با این کار بات نمایندگی از توکن فعلی جدا و به بات جدید وصل می‌شود.`, "");
        if (newToken === null || !newToken.trim()) return;
        try {
          const res = await api(`/api/admin/resellers/${r.id}/token`, {
            method: "PATCH",
            body: JSON.stringify({ token: newToken.trim() }),
          });
          tg.HapticFeedback.notificationOccurred("success");
          notify(`✅ لینک نماینده به @${res.username} تغییر کرد. ${res.note || ""}`);
          renderAdmin();
        } catch (e) { notify(e.message); }
      };
    });
    body.querySelectorAll("[data-toggle-res]").forEach((el) => {
      el.onclick = async () => {
        try {
          const res = await api(`/api/admin/resellers/${el.dataset.toggleRes}/toggle`, { method: "POST" });
          notify(res.note || "وضعیت تغییر کرد.");
          renderAdmin();
        } catch (e) { notify(e.message); }
      };
    });
    body.querySelectorAll("[data-del-res]").forEach((el) => {
      el.onclick = async () => {
        const purge = confirm("همراه با حذف نماینده، فایل دیتابیسش هم برای همیشه پاک شود؟\n(تایید = بله پاک شود / لغو = فقط حذف از لیست، فایل نگه داشته شود)");
        try {
          const res = await api(`/api/admin/resellers/${el.dataset.delRes}?purge_db=${purge}`, { method: "DELETE" });
          notify((res.db_purged ? "نماینده حذف و دیتابیسش پاک شد. " : "نماینده حذف شد (دیتابیس نگه داشته شد). ") + (res.note || ""));
          renderAdmin();
        } catch (e) { notify(e.message); }
      };
    });
    document.getElementById("new-res-validate").onclick = async () => {
      const token = document.getElementById("new-res-token").value.trim();
      if (!token) { notify("توکن را وارد کن."); return; }
      try {
        const res = await api("/api/admin/resellers/validate", { method: "POST", body: JSON.stringify({ token }) });
        document.getElementById("new-res-step2").style.display = "";
        document.getElementById("new-res-username-line").textContent = `✅ توکن معتبر است: @${res.username}`;
        document.getElementById("new-res-save").onclick = async () => {
          const ownerId = Number(document.getElementById("new-res-owner-id").value);
          const ownerName = document.getElementById("new-res-owner-name").value.trim();
          if (!ownerId) { notify("آیدی عددی نماینده الزامی است."); return; }
          try {
            const createRes = await api("/api/admin/resellers", {
              method: "POST",
              body: JSON.stringify({ token, username: res.username, owner_telegram_id: ownerId, owner_name: ownerName }),
            });
            tg.HapticFeedback.notificationOccurred("success");
            notify(createRes.note || "نماینده اضافه شد.");
            renderAdmin();
          } catch (e) { notify(e.message); }
        };
      } catch (e) { notify(e.message); }
    };
  } catch (e) {
    body.innerHTML = errorState(e.message);
  }
}


const tabs = {
  home: renderHome,
  store: enterStoreTab,
  services: enterServicesTab,
  profile: renderProfile,
  test: renderTestConfig,
  wheel: renderWheel,
  referral: renderReferral,
  support: renderSupport,
  wallet: renderWallet,
  admin: renderAdmin,
};

function switchTab(name) {
  document.querySelectorAll("#tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  if (name !== "support") clearInterval(supportPollTimer);
  if (name !== "admin") {
    clearInterval(adminPresenceTimer);
    clearInterval(adminLiveChatPollTimer);
  }
  content.classList.remove("fade-in");
  void content.offsetWidth; // ری‌استارت انیمیشن
  tabs[name]();
  content.classList.add("fade-in");
}

document.querySelectorAll("#tabbar button").forEach((b) => b.onclick = () => switchTab(b.dataset.tab));

const headerWalletBtn = document.getElementById("header-wallet-btn");
if (headerWalletBtn) headerWalletBtn.onclick = () => switchTab("wallet");

switchTab("home");
