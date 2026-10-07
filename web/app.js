let selectedGame=null,minConfidence='ALL',allPlayers=[],selectedMarket='PTS';
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const initials=n=>String(n||'').split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0]).join('').toUpperCase();
function photo(p){return p.headshot?`<span class="photo-wrap"><img class="headshot" src="${esc(p.headshot)}" alt="${esc(p.name)}" loading="lazy"></span>`:`<div class="avatar">${initials(p.name)}</div>`}
function scoreClass(v){return v>=82?'elite':v>=72?'strong':v>=62?'good':v>=52?'lean':'pass'}
function marketMeta(){return selectedMarket==='AST'?{label:'AST',name:'Assists'}:selectedMarket==='REB'?{label:'REB',name:'Rebounds'}:{label:'PTS',name:'Points'}}
function filtered(){return allPlayers.filter(p=>minConfidence==='ALL'||scoreClass(+p.model_score)===minConfidence.toLowerCase())}
function groups(){const m=new Map();for(const p of filtered()){const t=[p.team,p.opponent].sort(),k=`${p.game_date}|${p.game_time}|${t.join('-')}`;if(!m.has(k))m.set(k,{key:k,date:p.game_date,time:p.game_time,teams:t,players:[]});m.get(k).players.push(p)}return [...m.values()].map(g=>(g.players.sort((a,b)=>+b.model_score-+a.model_score),g)).sort((a,b)=>(a.date+a.time).localeCompare(b.date+b.time))}
function timeLabel(t){try{return t?new Date(t).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):''}catch{return t||''}}
function val(v,d=1){const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—'}
function stat(label,value,cls=''){return `<div class="pstat ${cls}"><span>${label}</span><b>${value}</b></div>`}
function playerRow(p){
  const score=+p.model_score, conf=+p.confidence_score, m=marketMeta();
  return `<div class="game-player ${scoreClass(score)}" onclick="event.stopPropagation();detail(${p.player_id})">
    <div class="player-main">
      <div class="identity">${photo(p)}<div><div class="player">${esc(p.name)}</div><div class="match">${esc(p.team)} • ${esc(p.opponent)} • ${val(p.expected_minutes)} min expected</div></div></div>
      <div class="player-primary">
        <div class="projection"><span>PROJECTION</span><b>${val(p.projection)} <small>${m.label}</small></b></div>
        <div class="score-badge ${scoreClass(score)}"><b>${score.toFixed(0)}</b><small>MODEL SCORE</small></div>
      </div>
    </div>
    <div class="player-stats">
      ${stat('Season',val(p.stat_season))}${stat('Last 5',val(p.stat_last5))}${stat('Last 10',val(p.stat_last10))}${stat('Last 20',val(p.stat_last20))}${stat('Trend',`${+p.trend>=0?'+':''}${val(p.trend)}`,+p.trend>=0?'positive':'negative')}${stat('Minutes',val(p.expected_minutes))}${stat('Usage',`${val(p.usage)}%`)}${stat('Pace',`${val(p.pace,0)}%`)}${stat('Opp Def',`${val(p.opponent_defense,1)}`)}${stat('MC',Number(p.monte_carlo||10000).toLocaleString())}
    </div>
    <div class="confidence-bottom">
      <div class="confidence-label"><span>CONFIDENCE</span><b>${conf.toFixed(0)}%</b><em>${esc(p.confidence||'')}</em></div>
      <div class="confidence-bar"><i style="width:${Math.max(0,Math.min(100,conf))}%"></i></div>
    </div>
  </div>`
}
function render(){
 const gs=groups();
 document.querySelector('#showing').textContent=`${gs.length} utakmica • klikni utakmicu za igrače`;
 document.querySelector('#cards').innerHTML=gs.map(g=>{const o=selectedGame===g.key;return `<article class="game-card ${o?'open':''}" onclick="toggleGame('${encodeURIComponent(g.key)}')">
   <div class="game-head"><div><div class="eyebrow">NBA GAME</div><h3>${esc(g.teams[0])} <span>vs</span> ${esc(g.teams[1])}</h3><div class="game-meta">${esc(g.date)} ${timeLabel(g.time)} • ${g.players.length} igrača</div></div><div class="game-arrow">${o?'−':'+'}</div></div>
   ${o?`<div class="game-players"><div class="players-sort"><span>Igrači</span><small>sortirano po Model Score • najveći → najmanji</small></div>${g.players.map(playerRow).join('')}</div>`:''}
 </article>`}).join('')||'<div class="empty">Nema utakmica za izabrani filter.</div>';
 document.querySelectorAll('.headshot').forEach(i=>i.addEventListener('error',()=>i.style.display='none'))
}
window.toggleGame=k=>{k=decodeURIComponent(k);selectedGame=selectedGame===k?null:k;render()};
window.setConfidence=v=>{minConfidence=v;selectedGame=null;render()};
window.setMarket=v=>{selectedMarket=(v||'PTS').toUpperCase();selectedGame=null;document.querySelectorAll('.market-btn').forEach(b=>b.classList.toggle('active',b.dataset.market===selectedMarket));load()};
async function load(){const st=document.querySelector('#apiStatus');st.textContent='LOADING MODEL DATA…';try{const c=new AbortController(),tm=setTimeout(()=>c.abort(),60000),r=await fetch('/api/projections?market='+encodeURIComponent(selectedMarket),{signal:c.signal});clearTimeout(tm);const body=await r.text();let ps;try{ps=JSON.parse(body)}catch{throw Error('Backend returned invalid JSON: '+body.slice(0,300))}if(!r.ok)throw Error(JSON.stringify(ps.detail||ps));allPlayers=ps;const h=await fetch('/api/health').then(x=>x.json()).catch(()=>({stats:{},errors:[]}));document.querySelector('#players').textContent=ps.length;document.querySelector('#apiStatus').textContent='LIVE • ESPN FREE • MODEL ACTIVE';document.querySelector('#high').textContent=ps.filter(x=>x.is_leader).length;document.querySelector('#games').textContent=Number(h.stats?.games)||groups().length;render();document.querySelector('#diagText').textContent=(h.errors||[]).join('\n')||'Model: 10,000 Monte Carlo • form • minutes • usage • pace • opponent defense • home/away';const plans=await fetch('/api/plans').then(r=>r.json());document.querySelector('#plans').innerHTML=plans.map((p,i)=>`<div class="plan ${i===1?'featured':''}"><div class="eyebrow">${p.name}</div><div class="price">€${p.price}${p.price?'<small>/mo</small>':''}</div><ul>${p.features.map(f=>`<li>${f}</li>`).join('')}</ul></div>`).join('')}catch(e){st.textContent='API ERROR';document.querySelector('#cards').innerHTML='<div class="empty error"><b>NBA model could not be loaded.</b><br><small>'+esc(e.message||e)+'</small><br><button onclick="location.reload()">Retry</button></div>'}}
async function detail(id){const p=await fetch('/api/players/'+id+'?market='+encodeURIComponent(selectedMarket)).then(r=>r.json()),d=document.querySelector('#detail'),m=marketMeta();d.classList.remove('hidden');d.innerHTML=`<div class="top"><div class="identity">${photo(p)}<div><div class="eyebrow">PLAYER MODEL</div><h2>${esc(p.name)}</h2><div class="match">${esc(p.team)} vs ${esc(p.opponent)} • ${esc(p.game_date)}</div></div></div><div class="detail-score"><b>${(+p.model_score).toFixed(0)}</b><span>MODEL SCORE</span></div></div><div class="metric-grid"><div><span>Projection</span><b>${(+p.projection).toFixed(1)} ${m.label}</b></div><div><span>Confidence</span><b>${(+p.confidence_score).toFixed(0)}/100</b></div><div><span>Expected minutes</span><b>${(+p.expected_minutes).toFixed(1)}</b></div><div><span>Usage</span><b>${(+p.usage).toFixed(1)}%</b></div><div><span>Pace</span><b>${(+p.pace).toFixed(0)}%</b></div><div><span>Opp defense</span><b>${(+p.opponent_defense).toFixed(2)}×</b></div><div><span>Form trend</span><b>${+p.trend>=0?'+':''}${(+p.trend).toFixed(1)}</b></div><div><span>Monte Carlo</span><b>${(+p.monte_carlo).toLocaleString()}</b></div></div><h3>Recent ${m.name.toLowerCase()} form</h3><div class="metric-grid compact"><div><span>Season</span><b>${val(p.stat_season)}</b></div><div><span>Last 5</span><b>${val(p.stat_last5)}</b></div><div><span>Last 10</span><b>${val(p.stat_last10)}</b></div><div><span>Last 20</span><b>${val(p.stat_last20)}</b></div></div><h3>Monte Carlo ${m.name.toLowerCase()} probabilities</h3><div class="thresholds">${Object.entries(p.thresholds).map(([k,v])=>`<div><b>${k}</b><br><span>${v}%</span></div>`).join('')}</div><h3>Key model factors</h3><div class="factor-list">${p.reasons.map((x,i)=>`<div><span>${i+1}</span>${esc(x)}</div>`).join('')}</div><p class="model-note">Usage is an estimated scoring-volume proxy. Pace and opponent defense are model factors from recent ESPN scoreboard results.</p>`;d.scrollIntoView({behavior:'smooth'})}
load();
