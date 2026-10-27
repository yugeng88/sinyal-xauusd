"""Halaman dasbor (otomatis dari index.html). Disematkan agar ikut ter-bundle di hosting serverless."""
HTML = r'''<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b0e1a">
<title>Sinyal XAUUSD & NASDAQ</title>
<style>
:root{
  --bg:#0b0e1a; --panel:#12162a; --line:#232a47; --text:#eef0f8; --mute:#8b93b3;
  --buy:#4ade80; --sell:#f87171; --wait:#fbbf24; --accent:#e8845f;
  --font:"Inter","Segoe UI",system-ui,-apple-system,Roboto,sans-serif;
}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--text);font-family:var(--font);
  padding:max(16px,env(safe-area-inset-top)) 16px max(24px,env(safe-area-inset-bottom));
  display:flex;justify-content:center;
  background-image:radial-gradient(900px 400px at 85% -10%,#2a1a2e55,transparent),
                   radial-gradient(700px 400px at 0% 100%,#16225255,transparent)}
main{width:100%;max-width:460px;display:grid;gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
h1{font-size:22px;font-weight:700;letter-spacing:.2px}
.sub{color:var(--mute);font-size:13px;margin-top:4px}
.badge{font-weight:700;font-size:14px;padding:6px 14px;border-radius:8px;border:1.5px solid currentColor}
.BUY{color:var(--buy)} .SELL{color:var(--sell)} .WAIT{color:var(--wait)}
.price{font-size:30px;font-weight:700;margin-top:10px;font-variant-numeric:tabular-nums}
.chart{margin-top:10px}
svg{width:100%;height:auto;display:block}
.legend{display:flex;gap:14px;font-size:12px;color:var(--mute);justify-content:center;margin-top:6px;flex-wrap:wrap}
.legend i{display:inline-block;width:14px;height:2px;vertical-align:middle;margin-right:5px}
.grid{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.cell{padding:12px 14px;border-bottom:1px solid var(--line)}
.cell:nth-child(odd){border-right:1px solid var(--line)}
.cell:nth-last-child(-n+2){border-bottom:0}
.cell small{display:block;color:var(--mute);font-size:12px;margin-bottom:4px}
.cell b{font-size:18px;font-variant-numeric:tabular-nums}
.tp{color:var(--buy)} .sl{color:var(--sell)}
.bar{height:6px;background:var(--line);border-radius:4px;overflow:hidden;margin:8px 0 6px}
.bar>div{height:100%;background:var(--accent);border-radius:4px;transition:width .6s}
.row{display:flex;justify-content:space-between;font-size:13px}
.note{color:var(--mute);font-size:12px;line-height:1.5}
h2{font-size:15px;margin-bottom:8px}
.summary{font-size:14px;line-height:1.65;color:#d6daee}
.warn{margin-top:8px;font-size:13px;color:var(--wait)}
.ind{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.ind div{font-size:12px;color:var(--mute)} .ind b{display:block;color:var(--text);font-size:15px;margin-top:2px}
.status{font-size:12px;color:var(--mute);display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--buy);margin-right:6px}
.dot.stale{background:var(--wait)} .dot.err{background:var(--sell)}
.error{border-color:#6b2a2a;background:#2a1417;color:#fecaca;font-size:13px;line-height:1.5}
.hist{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}
.hist td,.hist th{padding:6px 4px;border-bottom:1px solid var(--line);text-align:left}
.hist th{color:var(--mute);font-weight:500}
.tabs{display:flex;gap:8px}
.tab{flex:1;background:var(--panel);color:var(--mute);border:1px solid var(--line);border-radius:10px;padding:11px 8px;font:600 14px var(--font);cursor:pointer}
.tab[aria-selected="true"]{color:var(--text);border-color:var(--accent);background:#1a1d33}
.note-box{margin-top:10px;font-size:12.5px;line-height:1.5;color:var(--wait);border:1px solid #5b4a1a;background:#2a2412;border-radius:8px;padding:8px 10px}
.CLOSED{color:var(--mute)}
.brow{display:flex;gap:8px;margin:8px 0}
.brow input{flex:1;min-width:0;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:11px 12px;font:600 16px var(--font)}
.brow button{background:var(--panel);color:var(--mute);border:1px solid var(--line);border-radius:8px;padding:0 14px;font:600 14px var(--font);cursor:pointer}
.bgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
.bgrid div{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:9px 11px}
.bgrid small{display:block;color:var(--mute);font-size:11.5px;margin-bottom:3px}
.bgrid b{font-size:16px;font-variant-numeric:tabular-nums}
.bgrid i{display:block;font-style:normal;color:var(--mute);font-size:11.5px;margin-top:2px}
.status-box{margin-top:10px;font-size:13px;line-height:1.55;border:1px solid #2c3a66;background:#141a33;border-radius:8px;padding:9px 11px}
.status-box .mute{color:var(--mute)} .status-box .warnline{color:var(--wait)}
.tfs{display:flex;gap:6px}
.tf{flex:1;background:transparent;color:var(--mute);border:1px solid var(--line);border-radius:8px;padding:8px 0;font:600 13px var(--font);cursor:pointer}
.tf[aria-selected="true"]{color:var(--text);border-color:#4a5688;background:#171c35}
.confirm{margin-top:8px;font-size:13px;line-height:1.5;border-radius:8px;padding:9px 11px;border:1px solid var(--line)}
.confirm.ok{border-color:#1f6b3d;background:#10241a}.confirm.wait{border-color:#6b5a1f;background:#241f10}.confirm.na{background:#171a2c}
.confirm ul{list-style:none;padding:0;margin:6px 0 0}.confirm li{display:flex;gap:6px;justify-content:space-between;font-size:12.5px;padding:2px 0}
.confirm .y{color:var(--buy)}.confirm .n{color:var(--sell)}.confirm small{color:var(--mute)}
.statline{font-size:12.5px;line-height:1.55;color:var(--mute);margin:0 0 10px}
.empty{color:var(--mute);font-size:14px;text-align:center;padding:18px 0}
.disc{text-align:center;color:var(--mute);font-size:12px}
a:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (prefers-reduced-motion:reduce){.bar>div{transition:none}}
</style>
</head>
<body>
<main>
  <div class="tabs" role="tablist" aria-label="Pilih instrumen">
    <button class="tab" role="tab" id="tab-XAUUSD" data-sym="XAUUSD">XAUUSD</button>
    <button class="tab" role="tab" id="tab-NASDAQ" data-sym="NASDAQ">NASDAQ</button>
  </div>
  <div class="tfs" role="tablist" aria-label="Pilih timeframe">
    <button class="tf" role="tab" data-tf="M5">M5</button>
    <button class="tf" role="tab" data-tf="M15">M15</button>
    <button class="tf" role="tab" data-tf="M30">M30</button>
    <button class="tf" role="tab" data-tf="H1">H1</button>
  </div>
  <div id="err" class="card error" hidden></div>
  <section class="card" id="main">
    <div class="empty" id="loading">Mengambil data pasar…</div>
  </section>
  <section class="card" id="brokercard" hidden>
    <h2>Pakai harga broker Anda</h2>
    <p class="note">Harga di broker bisa berbeda dari data aplikasi. Ketik harga saat ini di broker Anda, lalu level Entry, SL, dan TP dihitung ulang dari jarak poin sinyal.</p>
    <div class="brow"><input id="bp" inputmode="decimal" autocomplete="off" placeholder="mis. 29011.91" aria-label="Harga di broker Anda"><button id="bclear" type="button">Hapus</button></div>
    <div class="brow"><input id="sp" inputmode="decimal" autocomplete="off" placeholder="Spread broker (poin), mis. 0.36" aria-label="Spread broker dalam poin"></div>
    <div id="bout"></div>
  </section>
  <section class="card" id="sumcard" hidden>
    <h2>Ringkasan teknikal</h2>
    <p class="summary" id="summary"></p>
    <p class="warn" id="warn" hidden></p>
  </section>
  <section class="card" id="indcard" hidden>
    <h2>Indikator</h2>
    <div class="ind" id="ind"></div>
  </section>
  <section class="card" id="histcard" hidden>
    <h2>Riwayat sinyal (dihitung ulang dari data candle)</h2>
    <p class="statline" id="stats"></p>
    <table class="hist"><thead><tr><th>Terbit (UTC)</th><th>Arah</th><th>Entry</th><th>Hasil</th></tr></thead>
    <tbody id="hist"></tbody></table>
  </section>
  <div class="status"><span><i class="dot" id="dot"></i><span id="stat">menghubungkan…</span></span><span id="src"></span></div>
  <p class="disc">Bukan saran investasi. Trading berisiko. Level dihitung dari ATR dan indikator, bukan prediksi harga.<br>Versi 5 · M5/M15/M30/H1 + konfirmasi M1</p>
</main>

<script>
const $ = id => document.getElementById(id);
const fmt = (n, d=2) => n == null ? "–" : Number(n).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let last = null;
const SYMS = ["XAUUSD","NASDAQ"];
const TFS = ["M5","M15","M30","H1"];
const [h1_, h2_] = location.hash.replace("#","").toUpperCase().split("-");
let cur = SYMS.includes(h1_) ? h1_ : "XAUUSD";
let curTF = TFS.includes(h2_) ? h2_ : "H1";
let seq = 0, lastConfirm = null;

function activeOf(sig){ return sig && sig.tracking ? sig.tracking.active : null; }
function levelsOf(sig){ const A = activeOf(sig); return sig && sig.tracking ? (A ? A.levels : null) : (sig && sig.levels); }
const OUT = {SL:"Kena SL", TP3:"TP3 tercapai", EXPIRED:"Kedaluwarsa", REVERSED:"Berbalik arah", OPEN:"Pasar tutup", ACTIVE:"Aktif"};
function outText(o, tp){ let t = OUT[o] || o; if(tp>0 && (o==="SL"||o==="EXPIRED"||o==="REVERSED"||o==="ACTIVE"||o==="OPEN")) t += " · TP"+tp+" tercapai"; return t; }
function ageText(h){ return h<1 ? Math.max(1,Math.round(h*60))+" menit" : (Math.round(h*10)/10)+" jam"; }
function leftText(h){ return h<1 ? Math.max(0,Math.round(h*60))+" menit" : Math.round(h*10)/10+" jam"; }

function chartSVG(sig){
  const pts = sig.chart, L = levelsOf(sig);
  const W=420,H=190,pl=6,pr=52,pt=8,pb=8;
  let vals = pts.map(p=>p.c);
  if(L){ vals = vals.concat([L.entry, L.stop_loss, ...L.tp]); }
  let lo=Math.min(...vals), hi=Math.max(...vals), pad=(hi-lo)*.06||1; lo-=pad; hi+=pad;
  const x=i=>pl+i*(W-pl-pr)/(pts.length-1), y=v=>pt+(hi-v)*(H-pt-pb)/(hi-lo);
  const path = pts.map((p,i)=>(i?"L":"M")+x(i).toFixed(1)+" "+y(p.c).toFixed(1)).join("");
  let g = `<path d="${path}" fill="none" stroke="#c9cfee" stroke-width="1.6" stroke-linejoin="round"/>`;
  const line=(v,c,l,dash)=>`<line x1="${pl}" x2="${W-pr}" y1="${y(v)}" y2="${y(v)}" stroke="${c}" stroke-width="1" ${dash?'stroke-dasharray="4 3"':''}/>
    <text x="${W-pr+4}" y="${y(v)+3.5}" fill="${c}" font-size="10">${l}</text>`;
  if(L){
    g += line(L.entry,"#8b93b3","Entry",true) + line(L.stop_loss,"#f87171","SL",true);
    L.tp.forEach((v,i)=>{ g += line(v,"#4ade80","TP"+(i+1),true); });
  }
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Grafik harga penutupan H1, 48 candle terakhir">${g}</svg>`;
}

function render(s){
  const sig = s.signal;
  $("err").hidden = !s.error;
  if(s.error) $("err").textContent = "Data belum bisa diambil: " + s.error + (sig ? " (menampilkan sinyal terakhir yang berhasil)" : "");
  if(!sig){ $("loading").textContent = s.error ? "Belum ada data. Aplikasi mencoba lagi otomatis." : "Server baru bangun, mengambil data pasar (sekitar 1 menit)…"; return; }
  const A = activeOf(sig), L = levelsOf(sig), closed = !!sig.market_closed;
  const d = A ? A.direction : sig.direction;
  const badgeCls = closed ? "CLOSED" : d, badgeTxt = closed ? "TUTUP" : (A ? d : (d==="WAIT" ? "TUNGGU" : d));
  const conf = A ? A.confidence : sig.confidence;
  const live = sig.live_price ?? sig.price;
  let status = "";
  if(A){
    const mv = A.move_points, R = A.levels.risk_points;
    const tpTxt = A.tp_hit>0 ? "TP"+A.tp_hit+" sudah tercapai" : "belum ada TP tercapai";
    status = `<div class="status-box"><b>Sinyal ${A.direction} aktif</b>, terbit ${ageText(A.age_hours)} lalu. Level dikunci saat terbit.<br>
      Harga sekarang ${fmt(live)} (${mv>0?"+":""}${fmt(mv)} poin dari entry) · ${tpTxt}.<br>
      Berlaku sampai SL, TP3, atau sekitar ${leftText(Math.max(0,A.expires_in_hours))} lagi.
      ${sig.direction!==A.direction && !closed ? `<br><span class="mute">Indikator saat ini: ${sig.direction==="WAIT"?"TUNGGU":sig.direction} (skor ${sig.score>0?"+":""}${sig.score}). Sinyal tetap berlaku sampai berakhir.</span>`:""}
      ${mv>R ? `<br><span class="warnline">Harga sudah bergerak lebih dari 1R dari entry. Masuk sekarang berarti RR lebih kecil dari yang tertera.</span>`:""}</div>
      <div id="confbox"></div>`;
  }
  const cells = L ? `
    <div class="cell"><small>Entry</small><b>${fmt(L.entry)}</b></div>
    <div class="cell"><small>Stop loss</small><b class="sl">${fmt(L.stop_loss)}</b></div>
    <div class="cell"><small>Take profit 1 · RR 1:${L.rr[0]}</small><b class="tp">${fmt(L.tp[0])}</b></div>
    <div class="cell"><small>Take profit 2 · RR 1:${L.rr[1]}</small><b class="tp">${fmt(L.tp[1])}</b></div>
    <div class="cell"><small>Take profit 3 · RR 1:${L.rr[2]}</small><b class="tp">${fmt(L.tp[2])}</b></div>
    <div class="cell"><small>Jarak risiko</small><b>${fmt(L.risk_points)}</b></div>` : "";
  $("main").innerHTML = `
    <div class="top"><div><h1>${esc(sig.label || sig.symbol)}</h1><div class="sub">${esc(sig.timeframe)} · candle tertutup ${esc(sig.candle_time.slice(0,16).replace("T"," "))} UTC</div></div>
    <span class="badge ${badgeCls}">${badgeTxt}</span></div>
    <div class="price">${fmt(live)}</div>
    ${status}
    ${sig.note?`<div class="note-box">${esc(sig.note)}</div>`:""}
    <div class="chart">${chartSVG(sig)}</div>
    ${L?`<div class="legend"><span><i style="background:#8b93b3"></i>Entry</span><span><i style="background:#f87171"></i>Stop loss</span><span><i style="background:#4ade80"></i>Take profit</span></div>`:""}
    ${L?`<div class="grid" style="margin-top:12px">${cells}</div>`:`<p class="empty">${closed?"Pasar tampaknya tutup.":"Belum ada setup yang cukup selaras."} Tidak ada level entry saat ini.</p>`}
    <div style="margin-top:14px"><div class="row"><span>Tingkat keyakinan${A?" (saat terbit)":""}</span><b>${conf}%</b></div>
    <div class="bar" role="progressbar" aria-valuenow="${conf}" aria-valuemin="0" aria-valuemax="100"><div style="width:${conf}%"></div></div>
    <p class="note">Keselarasan indikator${A?"":" (skor "+(sig.score>0?"+":"")+sig.score+" dari ±"+sig.max_score+")"}, bukan peluang profit.</p></div>`;
  $("sumcard").hidden = false; $("summary").textContent = s.summary || "";
  $("warn").hidden = !sig.warnings.length; $("warn").textContent = sig.warnings.join(" · ");
  const i = sig.indicators;
  $("ind").innerHTML = [["EMA 20",fmt(i.ema20)],["EMA 50",fmt(i.ema50)],["EMA 100",fmt(i.ema100)],
    ["RSI 14",fmt(i.rsi14,1)],["ATR 14",fmt(i.atr14)],["24 jam",i.change_24h_pct==null?"–":(i.change_24h_pct>0?"+":"")+fmt(i.change_24h_pct)+"%"]]
    .map(([a,b])=>`<div>${a}<b>${b}</b></div>`).join("");
  $("indcard").hidden = false;
  $("src").textContent = "Sumber: " + sig.source;
  renderConfirm();
  updateBroker();
}

function renderConfirm(){
  const box = $("confbox"); if(!box) return;
  const A = activeOf(last && last.signal);
  if(!A){ box.innerHTML = ""; return; }
  const j = lastConfirm, c = j && j.signal_time === A.time ? j.confirm : null;
  if(!c){ box.innerHTML = '<div class="confirm na">Konfirmasi M1: memuat…</div>'; return; }
  if(!c.checks){ box.innerHTML = `<div class="confirm na"><b>Konfirmasi M1 belum tersedia.</b><br>${esc(c.message||"")}</div>`; return; }
  const ok = c.state === "CONFIRMED";
  const items = c.checks.map(x=>`<li><span>${x.ok?'<span class="y">✔</span>':'<span class="n">✖</span>'} ${esc(x.name)}</span><small>${esc(x.detail)}</small></li>`).join("");
  const first = c.first_time ? `<br><small>${ok?"Pertama terkonfirmasi":"Sempat terkonfirmasi"} pukul ${esc(c.first_time.slice(11,16))} UTC di sekitar ${fmt(c.first_price)}${ok?"":" (kini belum)"}.</small>` : "";
  box.innerHTML = `<div class="confirm ${ok?"ok":"wait"}"><b>Konfirmasi M1: ${ok?"TERKONFIRMASI":"BELUM"}</b>${ok?` · harga M1 ${fmt(c.price)}`:""}<ul>${items}</ul>${first}
    <br><small>Aturan heuristik, bukan jaminan. Sumber M1: ${esc(c.source||"–")}.</small>${c.warning?`<br><small>${esc(c.warning)}</small>`:""}</div>`;
}
async function loadConfirm(my){
  const A = activeOf(last && last.signal);
  if(!A){ lastConfirm = null; renderConfirm(); return; }
  try{
    const r = await fetch(`/api/confirm?symbol=${cur}&tf=${curTF}`,{cache:"no-store"}); const j = await r.json();
    if(my!==seq) return; lastConfirm = j;
  }catch(e){ if(my!==seq) return; lastConfirm = {signal_time:A.time, confirm:{state:"ERROR", message:"Tidak bisa menghubungi server."}}; }
  renderConfirm();
}

function ls(k,v){ try{ if(v===undefined) return localStorage.getItem(k)||""; if(v) localStorage.setItem(k,v); else localStorage.removeItem(k); }catch(e){ return ""; } }
function parsePrice(raw, ref){
  const t = String(raw).replace(/\s/g,"");
  if(!t) return null;
  const c = [
    parseFloat(t.replace(/,/g,"")),                          // 29,011.91 atau 29011.91
    parseFloat(t.replace(/\./g,"").replace(",",".")),         // 29.011,91
    parseFloat(t.replace(/[.,](?=.*[.,])/g,"").replace(",","."))  // 29.011.91 (pemisah campur)
  ].filter(x=>isFinite(x)&&x>0);
  if(!c.length) return null;
  return c.sort((a,b)=>Math.abs(Math.log(a/ref))-Math.abs(Math.log(b/ref)))[0];   // ambil yang paling dekat harga acuan
}
function updateBroker(){
  const card=$("brokercard"), out=$("bout");
  const sig = last && last.signal, L = levelsOf(sig);
  if(!sig){ card.hidden = true; return; }
  const ref = sig.live_price ?? sig.price;
  card.hidden = false;
  if(!L){
    out.innerHTML = '<p class="note">Belum ada level untuk dihitung ulang ('+(sig.market_closed?"pasar tampaknya tutup":"belum ada sinyal BUY atau SELL")+'). Kartu ini menghitung otomatis begitu sinyal BUY atau SELL muncul.</p>';
    return;
  }
  const spRaw = parseFloat(String($("sp").value).replace(",","."));
  const spHtml = (isFinite(spRaw) && spRaw>0) ? (()=>{ const pct = spRaw/L.risk_points*100;
    return `<p class="${pct>20?"warn":"note"}" style="margin-top:10px">Spread ${fmt(spRaw)} poin = ${pct.toFixed(0)}% dari jarak SL (${fmt(L.risk_points)} poin).${pct>20?" Spread sebesar ini sangat mengurangi RR di timeframe kecil. Pertimbangkan tidak masuk.":""}</p>`; })() : "";
  const raw = $("bp").value, p = parsePrice(raw, ref);
  if(!raw.trim()){ out.innerHTML = spHtml; return; }
  if(p==null){ out.innerHTML='<p class="note" style="color:var(--sell)">Angka belum terbaca. Contoh: 29011.91</p>'; return; }
  const sl = L.stop_loss - L.entry, tp = L.tp.map(x=>x-L.entry);
  const sg = v => (v>0?"+":"")+fmt(v);
  const gap = Math.abs(p/ref-1)*100;
  out.innerHTML = `
    <div class="bgrid">
      <div><small>Entry (harga broker)</small><b>${fmt(p)}</b></div>
      <div><small>Stop loss</small><b class="sl">${fmt(p+sl)}</b><i>${sg(sl)} poin</i></div>
      <div><small>Take profit 1</small><b class="tp">${fmt(p+tp[0])}</b><i>${sg(tp[0])} poin</i></div>
      <div><small>Take profit 2</small><b class="tp">${fmt(p+tp[1])}</b><i>${sg(tp[1])} poin</i></div>
      <div><small>Take profit 3</small><b class="tp">${fmt(p+tp[2])}</b><i>${sg(tp[2])} poin</i></div>
      <div><small>Selisih ke harga aplikasi</small><b>${fmt(p-ref)}</b><i>${gap.toFixed(2)}%</i></div>
    </div>
    ${gap>0.5?'<p class="warn">Harga broker berbeda cukup jauh dari harga acuan sinyal ('+gap.toFixed(2)+'%). Sinyal mungkin sudah tidak relevan, atau angkanya salah ketik.</p>':""}${spHtml}`;
}
$("bp").addEventListener("input",()=>{ ls("bp_"+cur,$("bp").value.trim()); updateBroker(); });
$("sp").addEventListener("input",()=>{ ls("sp_"+cur,$("sp").value.trim()); updateBroker(); });
$("bclear").addEventListener("click",()=>{ $("bp").value=""; $("sp").value=""; ls("bp_"+cur,""); ls("sp_"+cur,""); updateBroker(); });

function switchView(sym, tf){
  cur = sym; curTF = tf; seq++; last = null; lastConfirm = null;
  $("bp").value = ls("bp_"+sym); $("sp").value = ls("sp_"+sym); $("brokercard").hidden = true;
  history.replaceState(null,"","#"+sym.toLowerCase()+"-"+tf.toLowerCase());
  document.querySelectorAll(".tab").forEach(b=>b.setAttribute("aria-selected", b.dataset.sym===sym));
  document.querySelectorAll(".tf").forEach(b=>b.setAttribute("aria-selected", b.dataset.tf===tf));
  $("main").innerHTML = '<div class="empty" id="loading">Mengambil data pasar…</div>';
  ["sumcard","indcard","histcard"].forEach(i=>$(i).hidden=true);
  $("err").hidden = true; $("src").textContent = ""; $("stat").textContent = "menghubungkan…";
  load();
}
document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>switchView(b.dataset.sym, curTF)));
document.querySelectorAll(".tf").forEach(b=>b.addEventListener("click",()=>switchView(cur, b.dataset.tf)));

function tick(){
  if(!last) return;
  const dot=$("dot"), age = last.updated_at ? Math.round((new Date(last.now) - new Date(last.updated_at))/60000 + (Date.now()-lastFetch)/60000) : null;
  const every = Math.max(1, Math.round((last.update_seconds||900)/60)), stale = age!=null && age > every*3 + 2;
  dot.className = "dot" + (last.error ? " err" : stale ? " stale" : "");
  $("stat").textContent = age==null ? "menunggu data pertama" :
    `diperbarui ${age<1?"baru saja":age+" menit lalu"} · otomatis tiap ${every} menit` + (stale?" · data mungkin basi":"");
}

let lastFetch = Date.now();
function renderHistory(sig){
  const tr = sig && sig.tracking, A = activeOf(sig);
  const rows = [];
  if(A) rows.push({time:A.time, direction:A.direction, entry:A.levels.entry, outcome:"ACTIVE", tp_hit:A.tp_hit});
  if(tr) rows.push(...tr.recent);
  const st = tr && tr.stats;
  $("histcard").hidden = !rows.length && !(st && st.total);
  $("stats").textContent = !st ? "" : st.total === 0 ? "Belum ada sinyal yang selesai pada data ini." :
    `Dalam data ±${st.days} hari (${st.total} sinyal selesai): ${st.sl_first} kena SL sebelum TP1 (${Math.round(st.sl_first/st.total*100)}%), ${st.tp1plus} mencapai TP1 atau lebih (${st.tp3} sampai TP3), ${st.no_result} tanpa hasil (kedaluwarsa atau berbalik). Setelah SL, sinyal arah sama diblokir ${st.cooldown_bars} candle. Ini hasil data lalu, bukan jaminan ke depan.`;
  $("hist").innerHTML = rows.slice(0,10).map(x=>`<tr><td>${esc(x.time.slice(5,16).replace("T"," "))}</td><td class="${x.direction}">${x.direction}</td><td>${fmt(x.entry)}</td><td>${esc(outText(x.outcome,x.tp_hit))}</td></tr>`).join("");
}
async function load(){
  const my = seq, sym = cur, tf = curTF;
  try{
    const r = await fetch(`/api/signal?symbol=${sym}&tf=${tf}`,{cache:"no-store"}); const j = await r.json();
    if(my!==seq) return;               // pengguna sudah pindah tab
    last = j; lastFetch = Date.now(); render(last);
    renderHistory(j.signal);
    loadConfirm(my);
  }catch(e){ $("err").hidden=false; $("err").textContent="Tidak bisa menghubungi server aplikasi."; }
  tick();
}
async function cycle(){ await load(); setTimeout(cycle, (last && last.signal) ? 30000 : 5000); }
document.querySelectorAll(".tab").forEach(b=>b.setAttribute("aria-selected", b.dataset.sym===cur));
document.querySelectorAll(".tf").forEach(b=>b.setAttribute("aria-selected", b.dataset.tf===curTF));
$("bp").value = ls("bp_"+cur); $("sp").value = ls("sp_"+cur);
cycle(); setInterval(tick, 15000);
</script>
</body>
</html>
'''
