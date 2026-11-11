import html as _html

_BASE = (
    "body{margin:0;padding:10px 22px 14px}"
    ".hd{font-weight:700;margin-bottom:8px}"
    ".m{font-size:12px;color:var(--tg-theme-hint-color);min-height:15px;margin-top:6px}"
    "button{font:inherit}"
)

_SLIDER_CSS = (
    ".l{margin-top:8px;font-size:14px}"
    ".t{position:relative;height:30px;touch-action:pan-y}"
    ".t i{display:block;position:absolute}"
    ".k{top:13px;left:0;right:0;height:4px;border-radius:2px;background:var(--tg-theme-secondary-bg-color)}"
    ".f{top:13px;right:0;height:4px;border-radius:2px;background:var(--tg-theme-button-color)}"
    ".h{top:4px;width:22px;height:22px;margin-right:-11px;border-radius:11px;"
    "background:var(--tg-theme-bg-color);border:2px solid var(--tg-theme-button-color)}"
    ".p{display:flex;justify-content:space-between;align-items:center;margin-top:8px;padding-top:10px;"
    "border-top:1px solid var(--tg-theme-section-separator-color);font-weight:600}"
    "#go{width:100%;margin-top:10px}"
)

_TRACK = "<i class=k></i><i class=f></i><i class=h></i>"

_CUSTOM_BODY = (
    "<div dir=rtl lang=fa><div class=hd>🛠 سرویس سفارشی</div>"
    "<div class=l id=gl></div><div class=t id=gt>" + _TRACK + "</div>"
    "<div id=dr><div class=l id=dl></div><div class=t id=dt>" + _TRACK + "</div></div>"
    "<div class=p><span>قیمت:</span><b id=pc></b></div>"
    "<button id=go>ادامه</button><div class=m id=m></div></div>"
)

_CUSTOM_JS = (
    "const W=window.TelegramWidget,$=i=>document.getElementById(i),fa=n=>n.toLocaleString('fa-IR');"
    "let P={};try{P=JSON.parse(W.publicData)}catch(e){}"
    "const T=P.t||[[0,0,0]];let g=P.a,d=P.c;"
    "function pr(v){for(const x of T){if(v<x[0])break;if(!x[1]||v<=x[1])return v*x[2]}"
    "return v*(v<T[0][0]?T[0][2]:T[T.length-1][2])}"
    "function ui(){$('gl').textContent='حجم ترافیک: '+fa(g)+' گیگابایت';"
    "$('dl').textContent='مدت زمان: '+fa(d)+' روز';"
    "$('pc').textContent=fa(pr(g))+' '+(P.u||'')}"
    "function sl(id,lo,hi,get,set){const t=$(id),h=t.children[2],f=t.children[1];let on=0;"
    "function dw(){const q=hi>lo?(get()-lo)/(hi-lo)*100:0;h.style.right=q+'%';f.style.width=q+'%'}"
    "function mv(e){const r=t.getBoundingClientRect();let q=(r.right-e.clientX)/r.width;"
    "q=Math.min(1,Math.max(0,q));set(Math.round(lo+q*(hi-lo)));dw();ui()}"
    "t.addEventListener('pointerdown',e=>{on=1;t.setPointerCapture(e.pointerId);mv(e)});"
    "t.addEventListener('pointermove',e=>{if(on)mv(e)});"
    "t.addEventListener('pointerup',()=>{on=0});t.addEventListener('pointercancel',()=>{on=0});dw()}"
    "sl('gt',P.a,P.b,()=>g,v=>{g=v});"
    "if(P.c==P.d)$('dr').hidden=true;else sl('dt',P.c,P.d,()=>d,v=>{d=v});"
    "ui();"
    "$('go').onclick=()=>{const b=$('go');b.disabled=true;$('m').textContent='...';"
    "W.request('c:'+g+':'+d).then(a=>{$('m').textContent=a.result||''},"
    "e=>{$('m').textContent=e.code}).then(()=>{b.disabled=false})};"
)

_STATS_CSS = (
    ".tb{display:flex;gap:4px;margin-bottom:8px}"
    ".tb button{flex:1;padding:4px 0;border:0;border-radius:8px;font-size:12px;"
    "background:var(--tg-theme-secondary-bg-color);color:var(--tg-theme-text-color)}"
    ".tb .on{background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color)}"
    "#rv{font-size:22px;font-weight:700}"
    ".s{font-size:12px;color:var(--tg-theme-hint-color)}"
    ".g{display:flex;gap:6px;margin:8px 0}"
    ".g div{flex:1;padding:6px;border-radius:8px;background:var(--tg-theme-secondary-bg-color);text-align:center}"
    ".g b{display:block}"
    "svg{width:100%;height:64px;display:block}"
    ".b{fill:var(--tg-theme-button-color)}.z{fill:var(--tg-theme-accent-text-color)}"
)

_STATS_BODY = (
    "<div dir=rtl lang=fa><div class=hd>📊 آمار ربات</div><div class=tb id=tb></div>"
    "<div id=rv></div><div class=s>تومان فروش</div>"
    "<div class=g><div><b id=o></b><span class=s>سفارش</span></div>"
    "<div><b id=u></b><span class=s>کاربر جدید</span></div>"
    "<div><b id=a></b><span class=s>میانگین</span></div></div>"
    "<svg id=ch viewBox='0 0 280 64'></svg><div class=m id=m></div></div>"
)

_STATS_JS = (
    "const W=window.TelegramWidget,$=i=>document.getElementById(i),fa=n=>(+n||0).toLocaleString('fa-IR');"
    "const TB=[['1','امروز'],['7','۷ روز'],['30','۳۰ روز'],['0','کل']];let D={},busy=0;"
    "try{D=JSON.parse(W.chatData)||{}}catch(e){}"
    "function dr(){$('tb').replaceChildren(...TB.map(x=>{const b=document.createElement('button');"
    "b.textContent=x[1];if(x[0]==D.k)b.className='on';b.onclick=()=>ask(x[0]);return b}));"
    "$('rv').textContent=fa(D.r);$('o').textContent=fa(D.o);$('u').textContent=fa(D.u);$('a').textContent=fa(D.a);"
    "const s=D.s||[],mx=Math.max(1,...s);let h='';"
    "s.forEach((v,i)=>{const t=Math.max(3,v/mx*60);"
    "h+='<rect class='+(i==s.length-1?'z':'b')+' x='+(i*20+2)+' y='+(64-t)+' width=16 height='+t+' rx=2 />'});"
    "$('ch').innerHTML=h}"
    "function ask(k){if(busy)return;busy=1;$('m').textContent='...';"
    "W.request('s:'+k).then(a=>{try{D=JSON.parse(a.result);$('m').textContent='';dr()}"
    "catch(e){$('m').textContent=a.result||''}},e=>{$('m').textContent=e.code}).then(()=>{busy=0})}"
    "dr();W.request('s:'+(D.k||'30')).then(a=>{try{D=JSON.parse(a.result);dr()}catch(e){}},()=>{});"
)

_FEATURES_CSS = (
    ".r{display:flex;justify-content:space-between;align-items:center;padding:7px 0;"
    "border-top:1px solid var(--tg-theme-section-separator-color)}"
    ".sw{width:46px;height:26px;min-height:0;padding:0;border:0;border-radius:13px;position:relative;"
    "background:var(--tg-theme-secondary-bg-color)}"
    ".sw:after{content:'';position:absolute;top:3px;right:3px;width:20px;height:20px;border-radius:10px;"
    "background:var(--tg-theme-hint-color)}"
    ".sw.on{background:var(--tg-theme-button-color)}"
    ".sw.on:after{right:23px;background:#fff}"
)

_FEATURES_JS = (
    "const W=window.TelegramWidget,B=document.querySelectorAll('.sw'),M=document.getElementById('m');"
    "let s=[];try{s=JSON.parse(W.chatData)||[]}catch(e){}"
    "function dr(){B.forEach((b,i)=>b.classList.toggle('on',!!s[i]))}"
    "function ap(a){try{const v=JSON.parse(a.result);if(Array.isArray(v)){s=v;dr();M.textContent='';return}}catch(e){}"
    "M.textContent=a.result||''}"
    "B.forEach((b,i)=>{b.onclick=()=>{b.disabled=true;M.textContent='...';"
    "W.request('f:'+i).then(ap,e=>{M.textContent=e.code}).then(()=>{b.disabled=false})}});"
    "dr();W.request('f:r').then(ap,()=>{});"
)


def custom_plan_html() -> str:
    return f"<style>{_BASE}{_SLIDER_CSS}</style>{_CUSTOM_BODY}<script>{_CUSTOM_JS}</script>"


def stats_html() -> str:
    return f"<style>{_BASE}{_STATS_CSS}</style>{_STATS_BODY}<script>{_STATS_JS}</script>"


def features_html(labels) -> str:
    rows = "".join(
        f"<div class=r><span>{_html.escape(label)}</span><button class=sw></button></div>"
        for label in labels
    )
    body = f"<div dir=rtl lang=fa><div class=hd>⚙️ مدیریت قابلیت‌ها</div>{rows}<div class=m id=m></div></div>"
    return f"<style>{_BASE}{_FEATURES_CSS}</style>{body}<script>{_FEATURES_JS}</script>"
