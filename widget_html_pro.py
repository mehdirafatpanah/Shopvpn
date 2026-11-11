"""HTML for the extra admin widgets (pulse, alerts, leaderboards, analysis). Reuses widget_html helpers."""
import widget_html as _wh

_PRO_CSS = (
    ".g2{display:flex;gap:6px;margin:8px 0}"
    ".g2 div{flex:1;padding:6px 2px;border-radius:8px;background:var(--tg-theme-secondary-bg-color);text-align:center}"
    ".g2 b{display:block}"
    ".off{opacity:.5}"
    ".bar{display:block;height:4px;border-radius:2px;margin-top:5px;background:var(--tg-theme-button-color)}"
    ".hm{display:grid;grid-template-columns:repeat(10,1fr);gap:4px;margin:8px 0}"
    ".hm i{display:block;aspect-ratio:1;border-radius:4px;background:var(--tg-theme-secondary-bg-color)}"
    ".hm i.sel{outline:2px solid var(--tg-theme-accent-text-color)}"
    "svg.bars{width:100%;height:64px;display:block;margin-top:6px}"
    "svg.bars .b{fill:var(--tg-theme-button-color)}svg.bars .z{fill:var(--tg-theme-accent-text-color)}"
    ".ban{padding:10px;border-radius:10px;margin-bottom:8px;font-weight:600;text-align:center;"
    "background:var(--tg-theme-secondary-bg-color)}"
)

_BARS_JS = r"""
function bars(v,hi){const mx=Math.max(1,...v);let h='';
v.forEach((x,i)=>{const t=Math.max(2,x/mx*58);
h+='<rect class="'+(i==hi?'z':'b')+'" x="'+(i*10+1)+'" y="'+(62-t)+'" width="8" height="'+t+'" rx="2"/>'});
const s=document.createElementNS('http://www.w3.org/2000/svg','svg');
s.setAttribute('viewBox','0 0 240 64');s.setAttribute('class','bars');s.innerHTML=h;return s}
"""

_PULSE_JS = _BARS_JS + r"""
function dr(){const L=$('L');L.replaceChildren();
const w=el('div','w');[['0','امروز'],['1','دیروز']].forEach(x=>w.append(bt(x[1],()=>ask('p:'+x[0]),String(D.b||0)==x[0]?'bn on':'bn g')));L.append(w);
const r=D.r||0,p=D.p||0,dl=p>0?Math.round((r-p)/p*100):(r>0?100:0);
const h=el('div','c'),bd=el('b',0,(dl>0?'▲ ':dl<0?'▼ ':'')+fa(Math.abs(dl))+'٪');
bd.style.color=dl>=0?'#34c759':'#ff3b30';h.append(box(fa(r)+' تومان','درآمد '+(D.b?'دیروز':'امروز')+' نسبت به روز قبل'),bd);L.append(h);
const g=el('div','g2');[[D.o,'سفارش'],[D.u,'کاربر جدید'],[D.q,'در صف'],[D.t,'تیکت باز']].forEach(x=>{
const d=el('div');d.append(el('b',0,fa(x[0])),el('span','s',x[1]));g.append(d)});L.append(g);
const H=D.h||[];if(H.length){const mx=Math.max(...H);L.append(el('div','s','درآمد ساعتی (به هزار تومان)'));
L.append(bars(H,mx>0?H.indexOf(mx):-1));const f=el('div','s','۰۰ ← ۲۳ (وقت تهران)');f.style.textAlign='center';L.append(f)}
if(D.d>0){const a=row(box('⚠️ '+fa(D.d)+' پنل قطع است','برای جزئیات «سلامت پنل‌ها» را باز کنید'));a.style.color='#ff3b30';L.append(a)}}
dr();W.request('p:r').then(a=>{try{D=JSON.parse(a.result);dr()}catch(e){}},()=>{});
"""

_ALERTS_JS = r"""
const R=[['🧾','سفارش در انتظار تایید',1],['👛','شارژ در انتظار تایید',1],['🎫','تیکت باز',1],['🔴','پنل قطع‌شده',1],
['⏳','سرویس با انقضا تا ۲۴ ساعت دیگر',0],['📅','سرویس با انقضا تا ۳ روز دیگر',0]];
function dr(){const L=$('L');L.replaceChildren();const A=D.a||[0,0,0,0,0,0];
const hot=A[0]+A[1]+A[2]+A[3];
L.append(el('div','ban',hot?'⚠️ '+fa(hot)+' مورد نیاز به توجه دارد':'✅ همه‌چیز مرتب است'));
R.forEach((x,i)=>{const n=A[i]||0,r=row(box(x[0]+' '+x[1],n?fa(n)+' مورد':'موردی نیست'));
if(!n)r.classList.add('off');
if(x[2]&&n)r.append(bt('باز کردن',()=>ask('a:go:'+i)));L.append(r)});
const w=el('div','w');w.append(bt('بروزرسانی',()=>ask('a:r'),'bn g'));L.append(w)}
dr();W.request('a:r').then(a=>{try{D=JSON.parse(a.result);dr()}catch(e){}},()=>{});
"""

_TOP_JS = r"""
const TB=[['p','محصولات'],['b','خریداران'],['r','دعوت‌کنندگان']],PR=[['7','۷ روز'],['30','۳۰ روز'],['0','کل']],MD=['🥇','🥈','🥉','4️⃣','5️⃣'];
function dr(){const L=$('L');L.replaceChildren();const t=D.t||'p',e=D.e||'30';
const w1=el('div','w');TB.forEach(x=>w1.append(bt(x[1],()=>ask('t:'+x[0]+':'+e),x[0]==t?'bn on':'bn g')));L.append(w1);
const w2=el('div','w');PR.forEach(x=>w2.append(bt(x[1],()=>ask('t:'+t+':'+x[0]),x[0]==e?'bn on':'bn g')));L.append(w2);
const Z=D.r||[];if(!Z.length){L.append(el('div','s','داده‌ای برای این بازه نیست.'));return}
const mx=Math.max(1,...Z.map(v=>v[1]));
Z.forEach((v,i)=>{const b=box(MD[i]+' '+v[0],t=='r'?fa(v[1])+' دعوت':fa(v[1])+' خرید | '+fa(v[2])+' تومان');
const bar=el('i','bar');bar.style.width=Math.max(4,v[1]/mx*100)+'%';b.append(bar);L.append(row(b))})}
dr();W.request('t:r').then(a=>{try{D=JSON.parse(a.result);dr()}catch(e){}},()=>{});
"""

_ANALYSIS_JS = _BARS_JS + r"""
const TB=[['h','نقشه حرارتی ۳۰ روز'],['c','دسته‌ها'],['x','ساعت‌های فروش']];let sel=-1;
const dt=i=>new Date(Date.now()-(29-i)*864e5).toLocaleDateString('fa-IR',{month:'long',day:'numeric',timeZone:'Asia/Tehran'});
function dr(){const L=$('L');L.replaceChildren();const t=D.t||'h';
const w=el('div','w');TB.forEach(x=>w.append(bt(x[1],()=>{sel=-1;ask('k:'+x[0])},x[0]==t?'bn on':'bn g')));L.append(w);
if(t=='h'){const V=D.v||[],mx=Math.max(1,...V),g=el('div','hm'),info=el('div','m');
V.forEach((v,i)=>{const c=el('i');if(v>0)c.style.background='var(--tg-theme-button-color)',c.style.opacity=(.18+.82*v/mx).toFixed(2);
if(i==sel)c.classList.add('sel');
c.onclick=()=>{sel=i;dr()};g.append(c)});L.append(g);
const tot=V.reduce((a,b)=>a+b,0),best=V.indexOf(Math.max(...V,0));
if(sel>=0)L.append(row(box(dt(sel),fa(V[sel]*1000)+' تومان')));
L.append(row(box('جمع ۳۰ روز: '+fa(tot*1000)+' تومان','میانگین روزانه: '+fa(Math.round(tot/30)*1000)+' تومان'+(tot?' | بهترین روز: '+dt(best):''))));
L.append(el('div','s','روی هر خانه بزنید؛ تیره‌تر یعنی فروش بیشتر'))}
else if(t=='c'){const Z=D.r||[];if(!Z.length)L.append(el('div','s','فروشی در ۳۰ روز اخیر ثبت نشده است.'));
Z.forEach(v=>{const b=box(v[0],fa(v[2])+'٪ درآمد | '+fa(v[1])+' سفارش'),bar=el('i','bar');bar.style.width=Math.max(4,v[2])+'%';b.append(bar);L.append(row(b))});
if(Z.length)L.append(row(box('سهم زیرمجموعه‌ها',fa(D.f||0)+'٪ از فروش از مسیر رفرال و '+fa(100-(D.f||0))+'٪ مستقیم')))}
else{const H=D.v||[],mx=Math.max(...H,0),i=H.indexOf(mx);L.append(el('div','s','تعداد سفارش‌های ۳۰ روز اخیر به تفکیک ساعت (وقت تهران)'));
L.append(bars(H,mx>0?i:-1));const f=el('div','s','۰۰ ← ۲۳');f.style.textAlign='center';L.append(f);
if(mx>0)L.append(row(box('اوج فروش: ساعت '+fa(i)+' تا '+fa((i+1)%24),fa(mx)+' سفارش')))}}
dr();W.request('k:r').then(a=>{try{D=JSON.parse(a.result);dr()}catch(e){}},()=>{});
"""


def _html(title: str, js: str) -> str:
    return _wh._list_html(title, _PRO_CSS, js)


def pulse_html() -> str:
    return _html("🔴 نبض زنده فروشگاه", _PULSE_JS)


def alerts_html() -> str:
    return _html("🚨 مرکز هشدار", _ALERTS_JS)


def top_html() -> str:
    return _html("🏆 برترین‌ها", _TOP_JS)


def analysis_html() -> str:
    return _html("📊 تحلیل فروش", _ANALYSIS_JS)
