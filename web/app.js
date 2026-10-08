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

 if(mobileTab==='TRENDS'){
   container.innerHTML='<div class="mobile-trend-loading">Analyzing recent form across Points, Assists and Rebounds…</div>';
   await ensureTrendMarkets();
   const players=[...g.players]
     .map(p=>({base:p,best:bestMarketFor(p.player_id)}))
     .sort((a,b)=>b.best.score-a.best.score);

   container.innerHTML=`<div class="mobile-section-title"><div><div class="eyebrow">RECENT FORM</div><h3>Trending players</h3></div><span>Last 10 vs season</span></div>`+
     players.map(x=>trendCard(x.best.player||x.base,x.best.market)).join('');
 }else{
   const cat=mobileTab==='PTS'?'PTS':mobileTab==='AST'?'AST':'REB';
   const data=await ensureMarketData(cat);
   selectedMarket=cat;
   const players=playersForMobileMarket(data,g);

   container.innerHTML=`<div class="mobile-section-title"><div><div class="eyebrow">${cat==='PTS'?'POINTS':cat==='AST'?'ASSISTS':'REBOUNDS'}</div><h3>${esc(g.teams[0])} vs ${esc(g.teams[1])}</h3></div><span>${players.length} players</span></div>`+
     (players.length
       ? players.map(p=>trendCard(p,cat)).join('')
       : '<div class="empty">No player data available for this market.</div>');
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
async function ensureMarketData(m){
 const key=(m||'PTS').toUpperCase();
 if(Array.isArray(marketCache[key])&&marketCache[key].length)return marketCache[key];
 try{
   const r=await fetch('/api/projections?market='+encodeURIComponent(key));
   if(!r.ok)throw new Error('Market '+key+' unavailable');
   const data=await r.json();
   marketCache[key]=Array.isArray(data)?data:[];
   return marketCache[key];
 }catch(e){
   marketCache[key]=[];
   return [];
 }
}
window.setMobileTab=async v=>{
 mobileTab=(v||'TRENDS').toUpperCase();
 if(mobileTab!=='TRENDS'){
   const data=await ensureMarketData(mobileTab);
   selectedMarket=mobileTab;
   marketCache[mobileTab]=data;
 }
 render();
};
window.toggleMobileMenu=()=>{mobileMenuOpen=!mobileMenuOpen;document.querySelector('#mobileMenu').classList.toggle('open',mobileMenuOpen);document.querySelector('#mobileMenuToggle').setAttribute('aria-expanded',mobileMenuOpen?'true':'false')};
window.closeMobileMenu=()=>{mobileMenuOpen=false;document.querySelector('#mobileMenu').classList.remove('open');document.querySelector('#mobileMenuToggle').setAttribute('aria-expanded','false')};
window.setMarket=async(v,silent=false)=>{
 selectedMarket=(v||'PTS').toUpperCase();
 selectedGame=null;
 document.querySelectorAll('.market-btn').forEach(b=>b.classList.toggle('active',b.dataset.market===selectedMarket));
 if(!silent)await load();else render();
};
async function load(){const st=document.querySelector('#apiStatus');st.textContent='LOADING MODEL DATA…';try{const c=new AbortController(),tm=setTimeout(()=>c.abort(),60000),r=await fetch('/api/projections?market='+encodeURIComponent(selectedMarket),{signal:c.signal});clearTimeout(tm);const body=await r.text();let ps;try{ps=JSON.parse(body)}catch{throw Error('Backend returned invalid JSON: '+body.slice(0,300))}if(!r.ok)throw Error(JSON.stringify(ps.detail||ps));allPlayers=ps;marketCache[selectedMarket]=ps;const h=await fetch('/api/health').then(x=>x.json()).catch(()=>({stats:{},errors:[]}));document.querySelector('#players').textContent=ps.length;document.querySelector('#apiStatus').textContent='LIVE • ESPN FREE • MODEL ACTIVE';document.querySelector('#high').textContent=ps.filter(x=>x.is_leader).length;document.querySelector('#games').textContent=Number(h.stats?.games)||groups().length;render();document.querySelector('#diagText').textContent=(h.errors||[]).join('\n')||'Model: advanced modeling • form • minutes • usage • pace • opponent defense • home/away';const plans=await fetch('/api/plans').then(r=>r.json());document.querySelector('#plans').innerHTML=plans.map((p,i)=>`<div class="plan ${i===1?'featured':''}"><div class="eyebrow">${p.name}</div><div class="price">€${p.price}${p.price?'<small>/mo</small>':''}</div><ul>${p.features.map(f=>`<li>${f}</li>`).join('')}</ul></div>`).join('')}catch(e){st.textContent='API ERROR';document.querySelector('#cards').innerHTML='<div class="empty error"><b>NBA model could not be loaded.</b><br><small>'+esc(e.message||e)+'</small><br><button onclick="location.reload()">Retry</button></div>'}}
async function loadPlayerMarkets(id){const out={};for(const m of ['PTS','AST','REB']){try{if(m==='PTS'&&allPlayers.length){out.PTS=allPlayers.find(x=>+x.player_id===+id)||null}else{if(!marketCache[m]){const r=await fetch('/api/players/'+id+'?market='+m);if(r.ok)marketCache[m]=await r.json();}out[m]=Array.isArray(marketCache[m])?marketCache[m].find(x=>+x.player_id===+id):marketCache[m]}}catch{out[m]=null}}return out}
function detailProfile(mk){return Object.entries(mk).map(([k,p])=>p?`<div class="profile-stat"><span>${k}</span><b>${val(p.stat_last10)}</b><small>L10</small><em>${val(p.stat_season)} season</em></div>`:'').join('')}
function hoopedgeRecentValues(p, market){
 const keys={PTS:['last10_values','last10_points','recent_points','game_log_points'],AST:['last10_assists','recent_assists','game_log_assists'],REB:['last10_rebounds','recent_rebounds','game_log_rebounds']}[market]||[];
 for(const k of keys){if(Array.isArray(p?.[k])&&p[k].length)return p[k].map(Number).filter(Number.isFinite).slice(-10)}
 if(Array.isArray(p?.game_logs)){
   const vals=p.game_logs.slice(-10).map(g=>Number(g?.[market.toLowerCase()]??g?.value)).filter(Number.isFinite); if(vals.length)return vals;
 }
 return [];
}
window.hoopedgeRecentValues=hoopedgeRecentValues;
function profileBarChart(p){
 const vals=hoopedgeRecentValues(p,selectedMarket);
 if(vals.length){
   const max=Math.max(...vals,1), min=Math.min(...vals,0);
   return `<div class="profile-bars">${vals.map((v,i)=>{const h=Math.max(12,Math.round((v/max)*100));return `<div class="profile-bar-col"><b>${val(v)}</b><i style="height:${h}%"></i><small>${i===vals.length-1?'L':'#'+(i+1)}</small></div>`}).join('')}</div><div class="profile-chart-note">Last ${vals.length} games • ${marketMeta().name}</div>`;
 }
 return `<div class="profile-bars aggregate-bars"><div class="profile-bar-col"><b>${val(p.stat_season)}</b><i style="height:58%"></i><small>SZN</small></div><div class="profile-bar-col"><b>${val(p.stat_last5)}</b><i style="height:76%"></i><small>L5</small></div><div class="profile-bar-col"><b>${val(p.stat_last10)}</b><i style="height:88%"></i><small>L10</small></div><div class="profile-bar-col"><b>${+p.trend>=0?'+':''}${val(p.trend)}</b><i style="height:${Math.max(18,Math.min(100,50+Number(p.trend||0)*3))}%"></i><small>Δ</small></div></div><div class="profile-chart-note">The current feed exposes L5/L10 aggregates; individual game values are not available.</div>`;
}
function detailProfile(mk){return Object.entries(mk).map(([k,p])=>p?`<div class="profile-stat"><span>${k}</span><b>${val(p.stat_last10)}</b><small>L10</small><em>${val(p.stat_season)} season</em></div>`:'').join('')}
function bestDetailMarket(mk){let best=null;for(const [k,p] of Object.entries(mk)){if(!p)continue;const s=trendScore(p);if(!best||s>best.score)best={k,p,score:s}}return best}
function profileMetric(p,label,value,sub=''){return `<div class="profile-kpi"><span>${esc(label)}</span><b>${value}</b>${sub?`<small>${esc(sub)}</small>`:''}</div>`}
function profileLineValue(p){return Number(p?.line ?? p?.prop_line ?? p?.market_line ?? p?.projection)}
function profileChart(p){
 const vals=hoopedgeRecentValues(p,selectedMarket); const line=profileLineValue(p); const name=marketMeta().name;
 if(!vals.length)return `<div class="pe-chart-empty">Recent game values are not exposed by the current feed.</div>`;
 const finite=vals.filter(Number.isFinite); const max=Math.max(...finite, Number.isFinite(line)?line:0, 1); const min=Math.min(0,...finite,Number.isFinite(line)?line:0); const range=Math.max(1,max-min);
 return `<div class="pe-chart-wrap"><div class="pe-ylabels"><span>${val(max,1)}</span><span>${val((max+min)/2,1)}</span><span>${val(min,1)}</span></div><div class="pe-bars">${vals.map((v,i)=>{const h=Math.max(10,Math.round(((v-min)/range)*88));const hit=Number.isFinite(line)?v>=line:true;return `<div class="pe-bar-col"><div class="pe-bar-value">${val(v)}</div><i class="${hit?'hit':'miss'}" style="height:${h}%"></i><small>${i<vals.length?('#'+(i+1)):''}</small></div>`}).join('')}<div class="pe-line" style="bottom:${Math.max(8,Math.min(92,((line-min)/range)*100))}%"><span>${Number.isFinite(line)?val(line):'—'}</span></div></div></div><div class="pe-chart-label">Last ${vals.length} games • ${esc(name)}</div>`;
}
function shotChartMarkup(p){
 const raw=p?.shot_profile||p?.shot_chart||p?.shot_zones||null;
 const zones=raw&&typeof raw==='object'?raw:null;
 const zone=(...keys)=>{if(!zones)return null;for(const k of keys){if(Number.isFinite(Number(zones[k])))return Number(zones[k]);}return null};
 const three=zone('three','3pt','3PTM','three_pct'),mid=zone('mid','mid_range','midrange'),paint=zone('paint','restricted','rim'),left=zone('left_corner','corner_left','left_corner_3'),right=zone('right_corner','corner_right','right_corner_3'),net=zone('net','rim_pct');
 const has=[three,mid,paint,left,right,net].some(v=>v!==null);
 const f=v=>v===null?'—':(v<=1? v.toFixed(3):v.toFixed(1));
 return `<div class="shot-head"><div><div class="shot-player">${photo(p)}<div><b>${esc(p.name)}</b><small>${val(p.stat_season)} ${marketMeta().name} • ${esc(p.team)}</small></div></div></div><div class="shot-vs">VS</div><div class="shot-opponent"><div class="shot-opponent-logo">${initials(p.opponent||'OPP')}</div><b>${esc(p.opponent||'Opponent')}</b><small>Opponent defense</small></div></div><div class="shot-tabs"><span class="active">${esc(p.name)}</span><span>Edge</span><span>${esc(p.opponent||'Defense')}</span></div><div class="shot-periods"><span class="active">SZN</span><span>L5</span><span>L10</span><span>L20</span><span>H2H</span></div><div class="shot-legend"><span><i class="tri up"></i>ADV Player</span><span><i class="dot"></i>Neutral</span><span><i class="tri down"></i>ADV Def</span></div><div class="court"><div class="court-arc"></div><div class="court-key three"><b>THREE</b><strong>${f(three)}</strong></div><div class="court-key mid"><b>MID-RANGE</b><strong>${f(mid)}</strong></div><div class="court-key paint"><b>PAINT</b><strong>${f(paint)}</strong></div><div class="court-key left"><b>CORNER</b><strong>${f(left)}</strong></div><div class="court-key right"><b>CORNER</b><strong>${f(right)}</strong></div><div class="court-key net"><b>NET</b><strong>${f(net)}</strong></div><div class="court-key-note">${has?'Shot-zone data from the player feed':'Shot-zone data not exposed by the current NBA feed'}</div></div>`;
}
function offensiveProfileMarkup(p){
 const raw=p?.offensive_profile||p?.play_type_profile||p?.play_types||null; let rows=[];
 if(raw&&typeof raw==='object'&&!Array.isArray(raw)) rows=Object.entries(raw).map(([k,v])=>({name:k,pts:Number(v?.pts??v?.points??v),pct:Number(v?.pct??v?.percent),rank:v?.rank??v?.def_rank})).filter(x=>Number.isFinite(x.pts)||Number.isFinite(x.pct));
 const fallback=[['PR Ball Handler',29],['Free Throws',16],['Spot Up',14],['Isolation',13],['Other',28]];
 if(!rows.length)rows=fallback.map(([name,pct])=>({name,pct,pts:null,rank:null,derived:true}));
 const total=rows.reduce((s,x)=>s+(Number.isFinite(x.pct)?x.pct:0),0)||100; rows=rows.slice(0,5).map(x=>({...x,pct:Number.isFinite(x.pct)?x.pct/total*100:0}));
 const colors=['green','blue','purple','yellow','orange']; let acc=0; const stops=rows.map((x,i)=>{const a=acc;acc+=x.pct;return `${colors[i]} ${a}% ${acc}%`}).join(',');
 return `<div class="offense-top"><div class="offense-copy"><div class="shot-player">${photo(p)}<div><b>${esc(p.name)}</b><small>vs ${esc(p.opponent||'Opponent')}</small><small>${esc(p.game_date||'Today')}</small></div></div></div><div class="offense-donut" style="background:conic-gradient(${stops})"><div><b>${val(p.stat_season)}</b><span>${marketMeta().name}</span></div></div></div><div class="offense-table"><div class="offense-row header"><span>PLAY TYPE</span><span>PTS</span><span>% PTS</span><span>D v PLAY</span></div>${rows.map((x,i)=>`<div class="offense-row"><span><i class="dot ${colors[i]}"></i>${esc(x.name)}</span><span>${Number.isFinite(x.pts)?val(x.pts):'—'}</span><span>${x.pct.toFixed(0)}%</span><span>${x.rank??'—'}</span></div>`).join('')}</div>${!raw?'<div class="profile-data-note">Play-type percentages are shown as a visual fallback until the backend exposes player play-type data.</div>':''}`;
}
function recentTrendsMarkup(p){const vals=hoopedgeRecentValues(p,selectedMarket);const last=Number(p.stat_last10);const season=Number(p.stat_season);return `<div class="recent-top"><div class="shot-player">${photo(p)}<div><b>${esc(p.name)}</b><small>${esc(p.team)} • ${esc(p.opponent||'Opponent')}</small></div></div><div class="recent-badge">${trendLabel(trendScore(p))}</div></div><div class="recent-insight"><span>INSIGHT</span><p>${Number.isFinite(last)&&Number.isFinite(season)?`${esc(p.name)} is averaging ${val(last)} ${marketMeta().name.toLowerCase()} over the last 10 games, compared with ${val(season)} for the season.`:'Recent-form insight will appear when L10 data is available.'}</p></div>${profileChart(p)}`}
async function detail(id){
 const p=allPlayers.find(x=>+x.player_id===+id); if(!p)return; const d=document.querySelector('#detail'); d.classList.remove('hidden'); document.body.classList.add('player-detail-open');
 const m=marketMeta(); const line=profileLineValue(p); const hit=Number.isFinite(line)&&Number.isFinite(Number(p.stat_last10))?Math.round(Math.min(100,Math.max(0,(Number(p.stat_last10)/line)*100))):Number(p.confidence_score)||0;
 d.innerHTML=`<div class="detail-mobile-head"><button class="detail-back" onclick="closeDetail()">←</button><span>PLAYER PROFILE</span></div><div class="player-profile-hero"><div class="profile-hero-copy"><div class="eyebrow">PLAYER MODEL</div><h2>${esc(p.name)}</h2><div class="profile-team">${esc(p.team)} vs ${esc(p.opponent||'Opponent')} • ${esc(p.game_date||'Today')}</div></div><div class="profile-hero-photo">${photo(p)}</div><div class="detail-score"><b>${(+p.model_score||0).toFixed(0)}</b><span>MODEL SCORE</span></div></div><div class="profile-market-tabs"><button class="${selectedMarket==='PTS'?'active':''}" onclick="setProfileMarket('PTS',${p.player_id})">Points</button><button class="${selectedMarket==='AST'?'active':''}" onclick="setProfileMarket('AST',${p.player_id})">Assists</button><button class="${selectedMarket==='REB'?'active':''}" onclick="setProfileMarket('REB',${p.player_id})">REB</button><button>3PTM</button><button>P+A</button></div><section class="profile-block"><div class="profile-kicker">01</div><h3>Player overview</h3><div class="profile-overview-grid">${profileMetric(p,'L10 AVG',val(p.stat_last10),m.name)}${profileMetric(p,'LINE',Number.isFinite(line)?val(line):'—','market line')}${profileMetric(p,'HIT RATE',`${hit.toFixed(0)}%`,'last 10')}${profileMetric(p,'POS RANK',p.position_rank??'—','current rank')}${profileMetric(p,'OPPONENT',`vs ${esc(p.opponent||'—')}`,'matchup')}${profileMetric(p,'MINUTES',val(p.expected_minutes),'expected')}</div></section><section class="profile-block"><div class="profile-kicker">02</div><h3>Last 10 games</h3>${profileChart(p)}</section><section class="profile-block"><div class="profile-kicker">03</div><h3>Shot Chart</h3><div class="shot-card">${shotChartMarkup(p)}</div></section><section class="profile-block"><div class="profile-kicker">04</div><h3>Offensive Profile</h3><div class="offense-card">${offensiveProfileMarkup(p)}</div></section><section class="profile-block"><div class="profile-kicker">05</div><h3>Recent Trends</h3><div class="recent-card">${recentTrendsMarkup(p)}</div></section><section class="profile-block"><div class="profile-kicker">06</div><h3>Model probabilities</h3><div class="thresholds">${Object.entries(p.thresholds||{}).map(([k,v])=>`<div><b>${esc(k)}</b><span>${esc(v)}%</span></div>`).join('')||`<div><b>Confidence</b><span>${val(p.confidence_score,0)}%</span></div>`}</div><div class="factor-list">${(p.reasons||[]).map((x,i)=>`<div><span>${i+1}</span>${esc(x)}</div>`).join('')}</div></section>`;
 d.scrollIntoView({behavior:'smooth',block:'start'}); document.querySelectorAll('#detail .headshot').forEach(i=>i.addEventListener('error',()=>i.style.display='none'));
}
window.closeDetail=()=>{document.body.classList.remove('player-detail-open');const d=document.querySelector('#detail');d.classList.add('hidden');d.innerHTML='';window.scrollTo({top:0,behavior:'smooth'})};
window.setProfileMarket=async(v,id)=>{try{if(!marketCache[v]){const r=await fetch('/api/projections?market='+encodeURIComponent(v));if(!r.ok)throw new Error('Market unavailable');marketCache[v]=await r.json()}allPlayers=marketCache[v]||allPlayers;selectedMarket=v;detail(id)}catch(e){detail(id)}};

window.addEventListener('resize',()=>{clearTimeout(window.__hoopedgeResize);window.__hoopedgeResize=setTimeout(()=>render(),180)});
load();
