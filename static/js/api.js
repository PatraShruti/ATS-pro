async function cApi(url, opts={}) {
    const token = localStorage.getItem('ats_company_token') || '';
    const res = await fetch(url, { ...opts, headers: { 'Authorization': `Bearer ${token}`, ...(opts.headers||{}) } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
}
async function cPost(url, body) { return cApi(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) }); }
async function cPostForm(url, fd) { return cApi(url, { method:'POST', body:fd }); }
async function cPatch(url, body) { return cApi(url, { method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) }); }
async function cDelete(url) { return cApi(url, { method:'DELETE' }); }

function toast(msg, type='success') {
    const t = document.createElement('div');
    const c = type==='success'?'var(--emerald)':type==='error'?'#ef4444':'var(--gold)';
    t.style.cssText=`position:fixed;bottom:28px;right:28px;z-index:9999;background:var(--glass-bg);backdrop-filter:blur(20px);border:1px solid ${c};border-radius:14px;padding:14px 20px;font-size:14px;color:var(--text-primary);display:flex;align-items:center;gap:10px;box-shadow:0 8px 32px rgba(0,0,0,.4);animation:sti .3s ease;max-width:360px;`;
    t.innerHTML=`<span>${type==='success'?'✅':type==='error'?'❌':'ℹ️'}</span><span>${msg}</span>`;
    document.body.appendChild(t);
    setTimeout(()=>{t.style.opacity='0';t.style.transition='opacity .4s';setTimeout(()=>t.remove(),400);},3500);
}
function scoreClass(s) { return s>=80?'score-high':s>=50?'score-mid':'score-low'; }
function fmtDate(iso) { return new Date(iso).toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'2-digit'}); }
function hireColor(h) { return {'Strong Hire':'#22c55e','Hire':'#22c55e','Maybe':'#eab308','Reject':'#f87171','Pending':'#60a5fa'}[h]||'#60a5fa'; }
function hireBg(h) { return {'Strong Hire':'rgba(34,197,94,.15)','Hire':'rgba(34,197,94,.12)','Maybe':'rgba(234,179,8,.12)','Reject':'rgba(239,68,68,.12)','Pending':'rgba(96,165,250,.12)'}[h]||'rgba(96,165,250,.12)'; }

const _sty=document.createElement('style');
_sty.textContent=`.score-pill{padding:4px 12px;border-radius:20px;font-size:13px;font-weight:600;font-family:'Space Mono',monospace;}.score-high{background:rgba(34,197,94,.15);color:#22c55e;}.score-mid{background:rgba(234,179,8,.15);color:#eab308;}.score-low{background:rgba(239,68,68,.15);color:#f87171;}.skill-tag{display:inline-block;padding:4px 10px;border-radius:12px;font-size:12px;margin:2px;}.st-good{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);color:#22c55e;}.st-bad{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:#f87171;}.st-warn{background:rgba(234,179,8,.1);border:1px solid rgba(234,179,8,.3);color:#eab308;}.ldots{display:inline-flex;gap:6px;}.ldots span{width:8px;height:8px;background:currentColor;border-radius:50%;animation:ld 1.2s ease-in-out infinite;}.ldots span:nth-child(2){animation-delay:.2s}.ldots span:nth-child(3){animation-delay:.4s}@keyframes ld{0%,80%,100%{transform:scale(.5)}40%{transform:scale(1)}}@keyframes sti{from{transform:translateY(16px);opacity:0}to{transform:translateY(0);opacity:1}}.hire-badge{display:inline-block;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600;}.form-sel{width:100%;padding:12px 16px;background:var(--glass-bg);border:1px solid var(--glass-border);border-radius:11px;color:var(--text-primary);font-family:inherit;font-size:14px;cursor:pointer;appearance:none;}.form-sel:focus{outline:none;border-color:var(--emerald-light);}.form-sel option{background:#0a0f0d;}.act-btn{padding:5px 12px;border-radius:7px;font-size:11px;cursor:pointer;border:1px solid;transition:all .2s;font-family:inherit;}`;
document.head.appendChild(_sty);
