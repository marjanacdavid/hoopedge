let selectedGame=null,minConfidence='ALL',allPlayers=[],selectedMarket='PTS';
let mobileTab='TRENDS',mobileMenuOpen=false,marketCache={};
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const initials=n=>String(n||'').split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0]).join('').toUpperCase();
function photo(p){return p.headshot?`<span class="photo-wrap"><img class="headshot" src="${esc(p.headshot)}" alt="${esc(p.name)}" loading="lazy"></span>`:`<div class="avatar">${initials(p.name)}</div>`}
function scoreClass(v){return v>=82?'elite':v>=72?'strong':v>=62?'good':v>=52?'lean':'pass'}
function marketMeta(){return selectedMarket==='AST'?{label:'AST',name:'Assists'}:selectedMarket==='REB'?{label:'REB',name:'Rebounds'}:{label:'PTS',name:'Points'}}
function filtered(list=allPlayers){return list.filter(p=>minConfidence==='ALL'||scoreClass(+p.model_score)===minConfidence.toLowerCase())}
function groups(list=allPlayers){const m=new Map();for(const p of filtered(list)){const t=[p.team,p.opponent].sort(),k=`${p.game_date}|${p.game_time}|${t.join('-')}`;if(!m.has(k))m.set(k,{key:k,date:p.game_date,time:p.game_time,teams:t,players:[]});m.get(k).players.push(p)}return [...m.values()].map(g=>(g.players.sort((a,b)=>+b.model_score-+a.model_score),g)).sort((a,b)=>(a.date+a.time).localeCompare(b.date+b.time))}
function timeLabel(t){try{return t?new Date(t).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):''}catch{return t||''}}
function val(v,d=1){const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—'}
function stat(label,value,cls=''){return `<div class="pstat ${cls}"><span>${label}</span><b>${value}</b></div>`}
function gameLabel(g){return `${g.teams[0]} <span>vs</span> ${g.teams[1]}`}
function mobileGameStrip(gs){
  if(!gs.length)return '<div class="mobile-game-toolbar"><div class="mobile-game-empty">No games available</div></div>';
  if(!selectedGame||!gs.some(g=>g.key===selectedGame))selectedGame=gs[0].key;
  return `<div class="mobile-game-toolbar"><div class="mobile-game-toolbar-head"><span class="mobile-toolbar-label">TODAY'S GAMES</span><span class="mobile-toolbar-hint">Swipe →</span></div><div class="mobile-game-scroller">${gs.map(g=>`<button class="mobile-game-chip ${selectedGame===g.key?'active':''}" onclick="setMobileGame('${encodeURIComponent(g.key)}')"><b>${esc(g.teams[0])}</b><span>vs</span><b>${esc(g.teams[1])}</b><small>${esc(timeLabel(g.time))}</small></button>`).join('')}</div></div>`
}
function mobileControls(){
 return `<div class="mobile-analysis-stack">
   <div class="mobile-toolbar-row period-row"><span class="mobile-toolbar-caption">FORM</span><div class="mobile-pills"><button class="mobile-pill active">L10</button><button class="mobile-pill">L5</button><button class="mobile-pill">H2H</button><button class="mobile-pill">SZN</button></div></div>
   <div class="mobile-toolbar-row market-row"><span class="mobile-toolbar-caption">MARKET</span><div class="mobile-pills"><button class="mobile-pill ${mobileTab==='TRENDS'?'active':''}" onclick="setMobileTab('TRENDS')">Trends</button><button class="mobile-pill ${mobileTab==='PTS'?'active':''}" onclick="setMobileTab('PTS')">Points</button><button class="mobile-pill ${mobileTab==='AST'?'active':''}" onclick="setMobileTab('AST')">Assists</button><button class="mobile-pill ${mobileTab==='REB'?'active':''}" onclick="setMobileTab('REB')">REB</button></div></div>
 </div>`
}
function playerRow(p){
 const score=+p.model_score, conf=+p.confidence_score, m=marketMeta();
 return `<div class="game-player ${scoreClass(score)}" onclick="event.stopPropagation();detail(${p.player_id})">
   <div class="player-main"><div class="identity">${photo(p)}<div><div class="player">${esc(p.name)}</div><div class="match">${esc(p.team)} • ${esc(p.opponent)} • ${val(p.expected_minutes)} min expected</div></div></div><div class="player-primary"><div class="projection"><span>PROJECTION</span><b>${val(p.projection)} <small>${m.label}</small></b></div><div class="score-badge ${scoreClass(score)}"><b>${score.toFixed(0)}</b><small>MODEL SCORE</small></div></div></div>
   <div class="player-stats">${stat('Season',val(p.stat_season))}${stat('Last 5',val(p.stat_last5))}${stat('Last 10',val(p.stat_last10))}${stat('Last 20',val(p.stat_last20))}${stat('Trend',`${+p.trend>=0?'+':''}${val(p.trend)}`,+p.trend>=0?'positive':'negative')}${stat('Minutes',val(p.expected_minutes))}${stat('Usage',`${val(p.usage)}%`)}${stat('Pace',`${val(p.pace,0)}%`)}${stat('Opp Def',`${val(p.opponent_defense,1)}`)}${stat('MC',Number(p.monte_carlo||10000).toLocaleString())}</div>
   <div class="confidence-bottom"><div class="confidence-label"><span>CONFIDENCE</span><b>${conf.toFixed(0)}%</b><em>${esc(p.confidence||'')}</em></div><div class="confidence-bar"><i style="width:${Math.max(0,Math.min(100,conf))}%"></i></div></div>
 </div>`
}
function trendScore(p){
 const season=Number(p.stat_season),last=Number(p.stat_last10),delta=Number(p.trend);
 if(Number.isFinite(last)&&Number.isFinite(season)&&season!==0)return ((last-season)/Math.abs(season))*100;
 return Number.isFinite(delta)?delta:0;
}
function trendLabel(v){return v>=0?'▲ Uptrend':'▼ Downtrend'}
function trendCard(p,cat){
 const season=Number(p.stat_season),last=Number(p.stat_last10),delta=trendScore(p),m=cat==='PTS'?'Points':cat==='AST'?'Assists':'Rebounds';
 const width=Math.max(12,Math.min(100,50+delta*1.6));
 return `<div class="mobile-player-card trend-card" onclick="detail(${p.player_id})"><div class="mobile-player-top"><div class="identity">${photo(p)}<div><div class="mobile-player-name">${esc(p.name)} <small>${esc(p.team)}</small></div><div class="match">vs ${esc(p.opponent)}</div></div></div><div class="trend-badge ${delta>=0?'up':'down'}">${trendLabel(delta)}</div></div><div class="trend-insight"><div><span>BEST RECENT MARKET</span><b>${m}</b></div><div class="trend-numbers"><span>L10</span><strong>${val(last)}</strong><em>Season ${val(season)}</em></div></div><div class="trend-bar"><i style="width:${width}%"></i></div><div class="trend-foot"><span>Last 10 average</span><b>${delta>=0?'+':''}${val(delta)}% vs season</b></div></div>`
}
async function ensureTrendMarkets(){
 if(marketCache.AST&&marketCache.REB)return;
 const jobs=['AST','REB'].filter(x=>!marketCache[x]).map(async m=>{try{const r=await fetch('/api/projections?market='+m);if(!r.ok)throw new Error('Market '+m+' unavailable');marketCache[m]=await r.json()}catch(e){marketCache[m]=[]}});
 await Promise.all(jobs);
}
function bestMarketFor(id){
 const sources={PTS:allPlayers,AST:marketCache.AST||[],REB:marketCache.REB||[]};
 let best=null;
 for(const [market,list] of Object.entries(sources)){const p=list.find(x=>+x.player_id===+id);if(!p)continue;const score=trendScore(p);if(!best||score>best.score)best={market,player:p,score}}
 return best||{market:selectedMarket,player:allPlayers.find(x=>+x.player_id===+id),score:0};
}
async function renderMobilePlayers(g){
 const container=document.querySelector('#cards');
 if(!g){container.innerHTML='<div class="empty">Select a game above.</div>';return}
 let players=[...g.players];
 if(mobileTab==='TRENDS'){
   container.innerHTML='<div class="mobile-trend-loading">Analyzing recent form across Points, Assists and Rebounds…</div>';
   await ensureTrendMarkets();
   players=players.map(p=>({base:p,best:bestMarketFor(p.player_id)})).sort((a,b)=>b.best.score-a.best.score);
   container.innerHTML=`<div class="mobile-section-title"><div><div class="eyebrow">RECENT FORM</div><h3>Trending players</h3></div><span>Last 10 vs season</span></div>`+players.map(x=>trendCard(x.best.player||x.base,x.best.market)).join('');
 }else{
   const cat=mobileTab==='PTS'?'PTS':mobileTab==='AST'?'AST':'REB';
   if(cat!==selectedMarket){await setMarket(cat,true)}
   players=(groups(allPlayers).find(x=>x.key===g.key)||g).players;
   container.innerHTML=`<div class="mobile-section-title"><div><div class="eyebrow">${cat==='PTS'?'POINTS':cat==='AST'?'ASSISTS':'REBOUNDS'}</div><h3>${esc(g.teams[0])} vs ${esc(g.teams[1])}</h3></div><span>${players.length} players</span></div>`+players.map(playerRow).join('');
 }
 document.querySelectorAll('.headshot').forEach(i=>i.addEventListener('error',()=>i.style.display='none'));
}
function render(){
 const gs=groups();
 document.querySelector('#showing').textContent=`${gs.length} utakmica • klikni utakmicu za igrače`;
 const mobile=document.querySelector('#mobileGameBar');
 if(mobile)mobile.innerHTML=mobileGameStrip(gs);
 const controls=document.querySelector('#mobileControls');
 if(controls)controls.innerHTML=mobileControls();
 if(window.matchMedia('(max-width:800px)').matches){
   const g=gs.find(x=>x.key===selectedGame)||gs[0];
   if(g)selectedGame=g.key;
   renderMobilePlayers(g);
 }else{
   document.querySelector('#cards').innerHTML=gs.map(g=>{const o=selectedGame===g.key;return `<article class="game-card ${o?'open':''}" onclick="toggleGame('${encodeURIComponent(g.key)}')"><div class="game-head"><div><div class="eyebrow">NBA GAME</div><h3>${esc(g.teams[0])} <span>vs</span> ${esc(g.teams[1])}</h3><div class="game-meta">${esc(g.date)} ${timeLabel(g.time)} • ${g.players.length} igrača</div></div><div class="game-arrow">${o?'−':'+'}</div></div>${o?`<div class="game-players"><div class="players-sort"><span>Igrači</span><small>sortirano po Model Score • najveći → najmanji</small></div>${g.players.map(playerRow).join('')}</div>`:''}</article>`}).join('')||'<div class="empty">Nema utakmica za izabrani filter.</div>';
   document.querySelectorAll('.headshot').forEach(i=>i.addEventListener('error',()=>i.style.display='none'));
 }
}
window.toggleGame=k=>{k=decodeURIComponent(k);selectedGame=selectedGame===k?null:k;render()};
window.setMobileGame=k=>{selectedGame=decodeURIComponent(k);render()};
window.setConfidence=v=>{minConfidence=v;selectedGame=null;render()};
window.setMobileTab=async v=>{mobileTab=v; if(v!=='TRENDS'&&v!==selectedMarket){await setMarket(v,true)} render()};
window.toggleMobileMenu=()=>{mobileMenuOpen=!mobileMenuOpen;document.querySelector('#mobileMenu').classList.toggle('open',mobileMenuOpen);document.querySelector('#mobileMenuToggle').setAttribute('aria-expanded',mobileMenuOpen?'true':'false')};
window.closeMobileMenu=()=>{mobileMenuOpen=false;document.querySelector('#mobileMenu').classList.remove('open');document.querySelector('#mobileMenuToggle').setAttribute('aria-expanded','false')};
window.setMarket=async(v,silent=false)=>{selectedMarket=(v||'PTS').toUpperCase();marketCache[selectedMarket]=allPlayers;selectedGame=null;document.querySelectorAll('.market-btn').forEach(b=>b.classList.toggle('active',b.dataset.market===selectedMarket));if(!silent)await load();else render()};
async function load(){const st=document.querySelector('#apiStatus');st.textContent='LOADING MODEL DATA…';try{const c=new AbortController(),tm=setTimeout(()=>c.abort(),60000),r=await fetch('/api/projections?market='+encodeURIComponent(selectedMarket),{signal:c.signal});clearTimeout(tm);const body=await r.text();let ps;try{ps=JSON.parse(body)}catch{throw Error('Backend returned invalid JSON: '+body.slice(0,300))}if(!r.ok)throw Error(JSON.stringify(ps.detail||ps));allPlayers=ps;marketCache[selectedMarket]=ps;const h=await fetch('/api/health').then(x=>x.json()).catch(()=>({stats:{},errors:[]}));document.querySelector('#players').textContent=ps.length;document.querySelector('#apiStatus').textContent='LIVE • ESPN FREE • MODEL ACTIVE';document.querySelector('#high').textContent=ps.filter(x=>x.is_leader).length;document.querySelector('#games').textContent=Number(h.stats?.games)||groups().length;render();document.querySelector('#diagText').textContent=(h.errors||[]).join('\n')||'Model: advanced modeling • form • minutes • usage • pace • opponent defense • home/away';const plans=await fetch('/api/plans').then(r=>r.json());document.querySelector('#plans').innerHTML=plans.map((p,i)=>`<div class="plan ${i===1?'featured':''}"><div class="eyebrow">${p.name}</div><div class="price">€${p.price}${p.price?'<small>/mo</small>':''}</div><ul>${p.features.map(f=>`<li>${f}</li>`).join('')}</ul></div>`).join('')}catch(e){st.textContent='API ERROR';document.querySelector('#cards').innerHTML='<div class="empty error"><b>NBA model could not be loaded.</b><br><small>'+esc(e.message||e)+'</small><br><button onclick="location.reload()">Retry</button></div>'}}
async function loadPlayerMarkets(id){const out={};for(const m of ['PTS','AST','REB']){try{if(m==='PTS'&&allPlayers.length){out.PTS=allPlayers.find(x=>+x.player_id===+id)||null}else{if(!marketCache[m]){const r=await fetch('/api/players/'+id+'?market='+m);if(r.ok)marketCache[m]=await r.json();}out[m]=Array.isArray(marketCache[m])?marketCache[m].find(x=>+x.player_id===+id):marketCache[m]}}catch{out[m]=null}}return out}
function detailProfile(mk){return Object.entries(mk).map(([k,p])=>p?`<div class="profile-stat"><span>${k}</span><b>${val(p.stat_last10)}</b><small>L10</small><em>${val(p.stat_season)} season</em></div>`:'').join('')}
async function detail(id){
 const p=allPlayers.find(x=>+x.player_id===+id); if(!p)return;
 const d=document.querySelector('#detail'),m=marketMeta();d.classList.remove('hidden');d.innerHTML=`<div class="detail-mobile-head"><button class="detail-back" onclick="document.querySelector('#detail').classList.add('hidden')">←</button><span>PLAYER PROFILE</span></div><div class="player-detail-hero"><div class="identity">${photo(p)}<div><div class="eyebrow">PLAYER MODEL</div><h2>${esc(p.name)}</h2><div class="match">${esc(p.team)} vs ${esc(p.opponent)} • ${esc(p.game_date)}</div></div></div><div class="detail-score"><b>${(+p.model_score).toFixed(0)}</b><span>MODEL SCORE</span></div></div><section class="detail-section"><div class="detail-section-title"><span>01</span><h3>Matchup profile</h3></div><div class="detail-metrics"><div><span>Projection</span><b>${val(p.projection)} ${m.label}</b></div><div><span>Confidence</span><b>${(+p.confidence_score).toFixed(0)}/100</b></div><div><span>Minutes</span><b>${val(p.expected_minutes)}</b></div><div><span>Usage</span><b>${val(p.usage)}%</b></div><div><span>Pace</span><b>${val(p.pace,0)}%</b></div><div><span>Opp Defense</span><b>${val(p.opponent_defense,1)}×</b></div></div></section><section class="detail-section"><div class="detail-section-title"><span>02</span><h3>Offensive profile</h3></div><div id="profileMarkets" class="profile-markets"><div class="profile-loading">Loading Points / Assists / Rebounds…</div></div></section><section class="detail-section"><div class="detail-section-title"><span>03</span><h3>Recent trends</h3></div><div class="trend-summary"><div class="trend-main"><span>${m.name.toUpperCase()} • LAST 10</span><b>${val(p.stat_last10)}</b><small>Season ${val(p.stat_season)} • Trend ${+p.trend>=0?'+':''}${val(p.trend)}</small></div><div class="trend-progress"><i style="width:${Math.max(10,Math.min(100,50+trendScore(p)))}%"></i></div></div></section><section class="detail-section"><div class="detail-section-title"><span>04</span><h3>Model probabilities</h3></div><div class="thresholds">${Object.entries(p.thresholds||{}).map(([k,v])=>`<div><b>${k}</b><br><span>${v}%</span></div>`).join('')}</div><div class="factor-list">${(p.reasons||[]).map((x,i)=>`<div><span>${i+1}</span>${esc(x)}</div>`).join('')}</div></section><p class="model-note">HOOPEDGE uses the real fields exposed by the current NBA model. Detailed shot-location and per-game log charts can be added when those raw feeds are exposed by the backend.</p>`;
 d.scrollIntoView({behavior:'smooth'});
 const mk=await loadPlayerMarkets(id);const el=document.querySelector('#profileMarkets');if(el)el.innerHTML=detailProfile(mk);
}
window.addEventListener('resize',()=>{clearTimeout(window.__hoopedgeResize);window.__hoopedgeResize=setTimeout(()=>render(),180)});
load();
