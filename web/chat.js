(function(){
const css=`
#heFab{position:fixed;right:18px;bottom:56px;z-index:60;background:#edf2ff;color:#02140c;border:0;border-radius:999px;padding:13px 18px;font-weight:800;cursor:pointer;box-shadow:0 8px 28px rgba(0,0,0,.35)}
#hePanel{position:fixed;right:18px;bottom:104px;z-index:60;width:min(380px,calc(100vw - 36px));height:min(520px,70vh);display:none;flex-direction:column;background:var(--panel,#0b1030);border:1px solid var(--line,#334);border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.45);color:var(--text,#fff);overflow:hidden;backdrop-filter:blur(10px)}
#hePanel.open{display:flex}
#heHead{padding:14px 16px;border-bottom:1px solid var(--line,#334);font-weight:800;display:flex;justify-content:space-between}
#heHead span{color:var(--green,#11d889)}
#heMsgs{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:10px;font-size:14px;line-height:1.5}
.heM{max-width:88%;padding:10px 12px;border-radius:12px;white-space:pre-wrap}
.heM.u{align-self:flex-end;background:var(--green,#11d889);color:#02140c}
.heM.a{align-self:flex-start;background:var(--soft,rgba(255,255,255,.08))}
#heForm{display:flex;gap:8px;padding:10px;border-top:1px solid var(--line,#334)}
#heIn{flex:1;background:transparent;border:1px solid var(--line,#334);border-radius:10px;padding:10px;color:inherit;font:inherit}
#heSend{background:var(--green,#11d889);color:#02140c;border:0;border-radius:10px;padding:0 14px;font-weight:800;cursor:pointer}
#heNote{font-size:10px;color:var(--muted,#99a);padding:0 14px 8px}
`;
const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
const root=document.createElement('div');
root.innerHTML=`<button id="heFab">Ask HOOPEDGE AI</button>
<div id="hePanel"><div id="heHead"><div>HOOPEDGE <span>AI</span></div><div id="heClose" style="cursor:pointer">✕</div></div>
<div id="heMsgs"></div><div id="heNote">Statistical estimates, not guarantees or betting advice.</div>
<div id="heForm"><input id="heIn" maxlength="500" placeholder="e.g. Explain Jokić points projection"><button id="heSend">Send</button></div></div>`;
document.body.appendChild(root);
const $=s=>root.querySelector(s),msgs=$('#heMsgs'),inp=$('#heIn');
let history=[];
function add(role,text){const d=document.createElement('div');d.className='heM '+(role==='user'?'u':'a');d.textContent=text;msgs.appendChild(d);msgs.scrollTop=msgs.scrollHeight;return d}
add('assistant','Hi! Ask me about any player in today\'s or tomorrow\'s games, e.g. "Who are the top PTS projections?"');
function toggle(){if(window.HE&&!HE.canAI()&&!$('#hePanel').classList.contains('open')){HE.openUpgrade('ai');return}$('#hePanel').classList.toggle('open');if($('#hePanel').classList.contains('open'))inp.focus()}
$('#heFab').onclick=toggle;$('#heClose').onclick=toggle;
async function send(text){
  if(!text.trim())return;add('user',text);inp.value='';
  const wait=add('assistant','…');
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:text,history:history.slice(-6)})});
    const j=await r.json();
    if(!r.ok){if((r.status===401||r.status===403)&&window.HE)HE.handleForbidden(j.detail);throw new Error((j.detail&&j.detail.message)||'Error')}
    wait.textContent=j.answer;
    history.push({role:'user',content:text},{role:'assistant',content:j.answer});
  }catch(e){wait.textContent='⚠ '+e.message}
}
$('#heSend').onclick=()=>send(inp.value);
inp.addEventListener('keydown',e=>{if(e.key==='Enter')send(inp.value)});
window.hoopedgeAsk=q=>{if(!$('#hePanel').classList.contains('open'))toggle();send(q)};
})();
