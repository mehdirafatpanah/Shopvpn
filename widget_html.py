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


_COMMON_CSS = (
    ".c{display:flex;align-items:center;gap:8px;padding:8px;margin-bottom:6px;border-radius:10px;"
    "background:var(--tg-theme-secondary-bg-color)}"
    ".x{flex:1;min-width:0}.x b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
    ".s{font-size:12px;color:var(--tg-theme-hint-color)}"
    ".bn{border:0;border-radius:8px;padding:5px 10px;font-size:12px;"
    "background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color)}"
    ".bn.g{background:var(--tg-theme-bg-color);color:var(--tg-theme-text-color)}"
    ".bn.on{background:var(--tg-theme-button-color);color:var(--tg-theme-button-text-color)}"
    ".w{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px}"
    ".w .bn{flex:1}"
)

_COMMON_JS = (
    "const W=window.TelegramWidget,$=i=>document.getElementById(i),fa=n=>(+n||0).toLocaleString('fa-IR');"
    "let D={},busy=0;try{D=JSON.parse(W.chatData)||{}}catch(e){}"
    "const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e};"
    "const bt=(x,f,c)=>{const b=el('button',c||'bn',x);b.onclick=()=>f(b);return b};"
    "const arm=(x,f,c)=>bt(x,b=>{if(b.dataset.a){f();return}b.dataset.a=1;const o=b.textContent;"
    "b.textContent='مطمئنید؟';setTimeout(()=>{delete b.dataset.a;b.textContent=o},4000)},c);"
    "const row=(...n)=>{const d=el('div','c');n.forEach(x=>d.append(x));return d};"
    "const box=(a,b)=>{const d=el('div','x');d.append(el('b',0,a),el('span','s',b));return d};"
    "function ask(q){if(busy)return;busy=1;$('m').textContent='...';W.request(q).then(a=>{"
    "try{const v=JSON.parse(a.result);if(v&&typeof v=='object'){D=v;$('m').textContent='';dr();return}}catch(e){}"
    "$('m').textContent=a.result||''},e=>{$('m').textContent=e.code}).then(()=>{busy=0})}"
)

_LIST_BODY = "<div dir=rtl lang=fa><div class=hd>{title}</div><div id=L></div><div class=m id=m></div></div>"

_SERVICES_CSS = (
    "svg.rg{width:44px;height:44px;flex:none}"
    ".rk{stroke:var(--tg-theme-bg-color)}.rf{stroke:var(--tg-theme-button-color)}.rf.lw{stroke:#ff3b30}"
    ".off{opacity:.55}"
)

_SERVICES_JS = (
    "function ring(p,lw){const c=100.5,n='http://www.w3.org/2000/svg',s=document.createElementNS(n,'svg');"
    "s.setAttribute('viewBox','0 0 40 40');s.setAttribute('class','rg');"
    "s.innerHTML='<circle cx=20 cy=20 r=16 fill=none stroke-width=4 class=rk /><circle cx=20 cy=20 r=16 fill=none "
    "stroke-width=4 class=\"rf'+(lw?' lw':'')+'\" stroke-dasharray=\"'+(c*p)+' '+c+'\" transform=\"rotate(-90 20 20)\" />';return s}"
    "function dr(){const L=$('L');L.replaceChildren();const S=D.s||[];"
    "if(!S.length){L.append(el('div','s','سرویس فعالی ندارید.'));return}"
    "S.forEach(v=>{const p=v[3]>0?Math.min(1,v[2]/v[3]):0,d=v[4],"
    "r=row(ring(p,p>.9||(d>=0&&d<=3)),box(v[1],fa(v[2])+' از '+fa(v[3])+' گیگ | '+(d<0?'بدون انقضا':fa(d)+' روز مانده')));"
    "if(!v[5])r.classList.add('off');"
    "const a=el('div');a.append(bt('تمدید',()=>ask('v:n:'+v[0])),bt('لینک',()=>ask('v:l:'+v[0]),'bn g'));"
    "a.style.cssText='display:flex;flex-direction:column;gap:4px';r.append(a);L.append(r)})}"
    "dr();W.request('v:r').then(a=>{try{D=JSON.parse(a.result);dr()}catch(e){}},()=>{});"
)

_WALLET_JS = (
    "function dr(){const L=$('L');L.replaceChildren();"
    "const h=el('div','c');h.append(box(fa(D.b)+' تومان','موجودی کیف پول'));L.append(h);"
    "const w=el('div','w');(D.p||[]).forEach(a=>w.append(bt('+'+fa(a),()=>ask('w:t:'+a))));L.append(w);"
    "(D.t||[]).forEach(t=>{const r=row(box(t[1],''));const b=el('b',0,(t[0]>0?'+':'')+fa(t[0]));"
    "b.style.color=t[0]>0?'#34c759':'#ff3b30';r.append(b);L.append(r)});"
    "L.append(row(box('دعوت‌ها: '+fa(D.c),'اعتبار: '+fa(D.r)+' تومان'),bt('لینک دعوت',()=>ask('w:i'))))}"
    "dr();W.request('w:r').then(a=>{try{D=JSON.parse(a.result);dr()}catch(e){}},()=>{});"
)

_QUEUE_JS = (
    "function dr(){const L=$('L');L.replaceChildren();const Q=D.q||[];"
    "if(!Q.length){L.append(el('div','s','صف خالی است.'));return}"
    "Q.forEach(v=>{const t=v[0]=='t'?'t':'',a=el('div');"
    "a.style.cssText='display:flex;flex-direction:column;gap:4px';"
    "a.append(arm('تایید',()=>ask('q:'+t+'a:'+v[1])),arm('رد',()=>ask('q:'+t+'x:'+v[1]),'bn g'));"
    "L.append(row(box('#'+v[1]+' '+v[2],v[3]+' | '+fa(v[4])+' تومان'),a))});"
    "if(D.n>Q.length)L.append(el('div','s','و '+fa(D.n-Q.length)+' مورد دیگر'))}"
    "dr();W.request('q:r').then(a=>{try{D=JSON.parse(a.result);dr()}catch(e){}},()=>{});"
)

_HEALTH_JS = (
    "const C=['#ff3b30','#34c759','#ffcc00'];"
    "function dr(){const L=$('L');L.replaceChildren();const P=D.p||[];"
    "if(!P.length)L.append(el('div','s','پنل فعالی ثبت نشده است.'));"
    "P.forEach(v=>{const d=el('i');d.style.cssText='width:12px;height:12px;border-radius:6px;flex:none;background:'+C[v[1]];"
    "const cap=v[3]?fa(v[2])+' از '+fa(v[3]):fa(v[2])+' سرویس';"
    "L.append(row(d,box(v[1]==0?v[0]+' (قطع)':v[0],cap+(v[4]?' | '+fa(v[4])+' ms':''))))});"
    "const w=el('div','w');w.append(bt('بررسی زنده',()=>ask('h:p')),bt('بروزرسانی',()=>ask('h:r'),'bn g'));L.append(w)}"
    "dr();"
)

_MEMBERS_JS = (
    "let sel=0;const TB=[['n','جدیدترین'],['b','مسدود'],['w','موجودی']];"
    "function dr(){const L=$('L');L.replaceChildren();const w=el('div','w');"
    "TB.forEach(x=>w.append(bt(x[1],()=>{sel=0;ask('m:r:'+x[0]+':0')},x[0]==D.t?'bn on':'bn g')));L.append(w);"
    "const U=D.u||[];if(!U.length)L.append(el('div','s','کاربری یافت نشد.'));"
    "U.forEach(v=>{const r=row(box((v[3]?'🚫 ':'')+v[1]+' ('+v[0]+')',fa(v[2])+' تومان'));"
    "r.onclick=()=>{sel=sel==v[0]?0:v[0];dr()};L.append(r);"
    "if(sel==v[0]){const a=el('div','w'),k=D.t+':'+D.o+':'+v[0];"
    "[1e4,5e4,1e5].forEach(s=>a.append(arm('+'+fa(s),()=>ask('m:c:'+k+':'+s))));"
    "a.append(arm(v[3]?'آزاد':'مسدود',()=>ask('m:b:'+k),'bn g'));L.append(a)}});"
    "const p=el('div','w');if(D.o>0)p.append(bt('قبلی',()=>ask('m:r:'+D.t+':'+Math.max(0,D.o-5)),'bn g'));"
    "if(D.o+5<D.n)p.append(bt('بعدی',()=>ask('m:r:'+D.t+':'+(D.o+5)),'bn g'));L.append(p)}"
    "dr();W.request('m:r:'+(D.t||'n')+':'+(D.o||0)).then(a=>{try{D=JSON.parse(a.result);dr()}catch(e){}},()=>{});"
)


def _list_html(title: str, css: str, js: str) -> str:
    body = _LIST_BODY.format(title=title)
    return f"<style>{_BASE}{_COMMON_CSS}{css}</style>{body}<script>{_COMMON_JS}{js}</script>"


def services_html() -> str:
    return _list_html("📶 سرویس‌های من", _SERVICES_CSS, _SERVICES_JS)


def wallet_html() -> str:
    return _list_html("💰 کیف پول و دعوت", "", _WALLET_JS)


def queue_html() -> str:
    return _list_html("🧾 صف تایید", "", _QUEUE_JS)


def health_html() -> str:
    return _list_html("🩺 سلامت پنل‌ها", "", _HEALTH_JS)


def members_html() -> str:
    return _list_html("👥 مدیریت سریع کاربران", "", _MEMBERS_JS)
