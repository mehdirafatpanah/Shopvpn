# -*- coding: utf-8 -*-
"""صفحه‌ی تمام‌صفحه‌ی «در حال ساخت‌وساز» برای حالت تعمیرات فروشگاه وب (بدون فایل خارجی)."""
import html

from gear_svg import gear_path

_TEXT = {
    "fa": {"dir": "rtl", "title": "در حال بروزرسانی", "h": "در حال ساخت‌وساز هستیم",
           "sub": "فروشگاه موقتاً در دست بروزرسانی است. به‌زودی با امکانات بهتر برمی‌گردیم.",
           "tag": "کارگران در حال کارند", "back": "کمی بعد دوباره سر بزنید"},
    "en": {"dir": "ltr", "title": "Under maintenance", "h": "We're under construction",
           "sub": "The store is being updated. We'll be back soon with improvements.",
           "tag": "Crew at work", "back": "Please check back shortly"},
}

_SCENE = f"""<svg class="scene" viewBox="0 0 420 260" aria-hidden="true">
<defs>
  <linearGradient id="gd" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fbbf24"/><stop offset="1" stop-color="#f59e0b"/></linearGradient>
  <pattern id="hz" width="22" height="22" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
    <rect width="11" height="22" fill="#fbbf24"/><rect x="11" width="11" height="22" fill="#1f2937"/></pattern>
</defs>
<!-- ساختمان نیمه‌کاره -->
<g class="bld" fill="none" stroke="currentColor" stroke-width="2" opacity=".55">
  <rect x="268" y="118" width="96" height="112"/><path d="M268 150h96M268 182h96M300 118v112M332 118v112"/>
  <path d="M268 118l16-16h64l16 16" stroke-dasharray="4 5"/>
</g>
<!-- جرثقیل -->
<g stroke="#f59e0b" stroke-width="4" stroke-linejoin="round" stroke-linecap="round" fill="none">
  <path d="M96 232V52"/><path d="M122 232V52"/>
  <path d="M96 232l26-26M122 232L96 206M96 206l26-26M122 206L96 180M96 180l26-26M122 180L96 154M96 154l26-26M122 154L96 128M96 128l26-26M122 128L96 102M96 102l26-26M122 102L96 76M96 76l26-26" stroke-width="2.5"/>
  <path d="M60 52h260" /><path d="M60 52l49-34 49 34" stroke-width="3"/>
  <path d="M60 52v14M320 52v-6" stroke-width="3"/>
</g>
<rect x="54" y="58" width="22" height="22" rx="3" fill="#6b7280"/>
<g class="swing" style="transform-origin:262px 52px">
  <path d="M262 52v92" stroke="currentColor" stroke-width="2.5"/>
  <g class="blk"><rect x="238" y="144" width="48" height="26" rx="3" fill="url(#gd)"/><path d="M238 157h48M262 144v26" stroke="#b45309" stroke-width="2"/></g>
  <path d="M256 144l6-8 6 8" fill="none" stroke="currentColor" stroke-width="2.5"/>
</g>
<!-- چرخدنده‌ها -->
<path class="gear g1" fill="url(#gd)" fill-rule="evenodd" d="{gear_path(214, 212, 24, 19, 10, 7)}"/>
<path class="gear g2" fill="#fbbf24" fill-rule="evenodd" opacity=".8" d="{gear_path(168, 218, 16, 12, 8, 5)}"/>
<!-- زمین و نوار هشدار -->
<rect x="20" y="232" width="380" height="8" rx="4" fill="url(#hz)"/>
<path d="M20 244h380" stroke="currentColor" stroke-width="2" opacity=".35"/>
</svg>"""

_CSS = """
:root{--bg:#f6f4ee;--fg:#1f2937;--mut:#6b7280;--card:#ffffffd9;--line:#e7e2d4;--a:#f59e0b}
@media (prefers-color-scheme:dark){:root{--bg:#12100a;--fg:#f3efe2;--mut:#a39b86;--card:#1d1a10d9;--line:#332e1c;--a:#fbbf24}}
*{box-sizing:border-box;margin:0}html,body{height:100%}
body{font-family:Vazirmatn,Tahoma,"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--fg);display:grid;place-items:center;padding:20px}
.bg{position:fixed;inset:0;overflow:hidden;pointer-events:none}
.bg::before{content:"";position:absolute;inset:auto -10vmax -22vmax -10vmax;height:46vmax;border-radius:50%;background:#f59e0b26;filter:blur(90px)}
.bg i{position:absolute;inset:0;opacity:.45;background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);background-size:44px 44px;
-webkit-mask-image:radial-gradient(circle at 50% 40%,#000 0,transparent 70%);mask-image:radial-gradient(circle at 50% 40%,#000 0,transparent 70%)}
main{position:relative;width:min(520px,100%);text-align:center;background:var(--card);border:1px solid var(--line);border-radius:28px;padding:26px 26px 30px;
backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);box-shadow:0 30px 80px -34px #f59e0b66;animation:in .6s cubic-bezier(.2,.8,.2,1) both}
@keyframes in{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.scene{width:100%;height:auto;color:var(--fg)}
.gear{transform-box:fill-box;transform-origin:center}.g1{animation:cw 8s linear infinite}.g2{animation:ccw 6s linear infinite}
@keyframes cw{to{transform:rotate(360deg)}}@keyframes ccw{to{transform:rotate(-360deg)}}
.swing{animation:sw 4.5s ease-in-out infinite}@keyframes sw{0%,100%{transform:rotate(5deg)}50%{transform:rotate(-5deg)}}
h1{font-size:24px;font-weight:800;margin:10px 0 8px}
p{color:var(--mut);font-size:14.5px;line-height:1.9;white-space:pre-line}
.bar{height:8px;border-radius:99px;margin:22px auto 0;width:min(260px,80%);background:var(--line);overflow:hidden}
.bar b{display:block;height:100%;width:55%;border-radius:99px;background:repeating-linear-gradient(45deg,#fbbf24 0 10px,#1f2937 10px 20px);background-size:28px 28px;animation:mv 1s linear infinite}
@keyframes mv{to{background-position:28px 0}}
.tag{margin-top:12px;font-size:12.5px;color:var(--mut)}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""


def render(lang: str = "fa", custom_text: str = "") -> str:
    t = _TEXT.get(lang) or _TEXT["fa"]
    sub = html.escape(custom_text.strip()) if custom_text and custom_text != "__default__" else t["sub"]
    return f"""<!DOCTYPE html>
<html lang="{lang if lang in _TEXT else 'fa'}" dir="{t['dir']}">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{t['title']}</title><style>{_CSS}</style></head>
<body><div class="bg"><i></i></div>
<main role="main">{_SCENE}<h1>{t['h']}</h1><p>{sub}</p>
<div class="bar" role="progressbar" aria-label="{t['tag']}"><b></b></div><div class="tag">{t['tag']} · {t['back']}</div></main>
</body></html>"""
