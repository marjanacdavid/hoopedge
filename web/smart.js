/* Smart Prediction: rang lista pickova po vjerovatnoci kroz sve kategorije. */
(function () {
  const LABEL = { PTS: 'PTS', AST: 'AST', REB: 'REB', '3PM': '3PM', PA: 'P+A' };
  const NAME = { PTS: 'Points', AST: 'Assists', REB: 'Rebounds', '3PM': '3-Pointers', PA: 'Points + Assists' };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (v, d = 1) => (v === null || v === undefined || !Number.isFinite(+v)) ? '—' : (+v).toFixed(d);
  const state = { rows: [], view: 'players', market: 'ALL', source: 'all', minWin: 0, loading: false, error: '' };

  const css = `
#smartView{position:fixed;inset:0;z-index:70;background:var(--bg,#070b1d);color:var(--text,#fff);overflow:auto;display:none;-webkit-overflow-scrolling:touch}
#smartView.open{display:block}
.sm-wrap{max-width:760px;margin:0 auto;padding:16px 14px 80px}
.sm-top{display:flex;align-items:center;gap:12px;margin-bottom:6px}
.sm-back{background:transparent;border:1px solid var(--line,rgba(255,255,255,.18));color:inherit;border-radius:10px;padding:8px 12px;font-weight:700;cursor:pointer}
.sm-title{font-size:22px;font-weight:900;letter-spacing:.2px}.sm-title span{color:var(--green,#11d889)}
.sm-sub{color:var(--muted,#8f9ab8);font-size:13px;margin:2px 0 14px}
.sm-bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.sm-chip{background:rgba(255,255,255,.05);border:1px solid var(--line,rgba(255,255,255,.14));color:inherit;border-radius:999px;padding:7px 12px;font-size:12.5px;font-weight:700;cursor:pointer}
.sm-chip.on{background:var(--green,#11d889);border-color:var(--green,#11d889);color:#02140c}
.sm-sel{background:rgba(255,255,255,.05);border:1px solid var(--line,rgba(255,255,255,.14));color:inherit;border-radius:999px;padding:7px 10px;font-size:12.5px;font-weight:700}
.sm-card{display:grid;grid-template-columns:34px 52px 1fr auto;gap:10px;align-items:center;padding:12px;margin-bottom:10px;border-radius:16px;background:rgba(255,255,255,.04);border:1px solid var(--line,rgba(255,255,255,.1));cursor:pointer}
.sm-card:active{transform:scale(.995)}
.sm-rank{font-weight:900;font-size:15px;color:var(--muted,#8f9ab8);text-align:center}
.sm-card:nth-child(-n+3) .sm-rank{color:var(--green,#11d889)}
.sm-photo{width:52px;height:52px;border-radius:50%;background:rgba(255,255,255,.08);object-fit:cover;object-position:top;display:flex;align-items:center;justify-content:center;font-weight:800;overflow:hidden}
.sm-name{font-weight:800;font-size:15px;line-height:1.2}.sm-name small{color:var(--muted,#8f9ab8);font-weight:600;margin-left:4px}
.sm-pick{margin-top:3px;font-weight:900;font-size:14px}.sm-pick.over{color:var(--green,#11d889)}.sm-pick.under{color:#ff7a7a}
.sm-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;font-size:11px;color:var(--muted,#8f9ab8)}
.sm-chips span{background:rgba(255,255,255,.06);border-radius:999px;padding:2px 8px;font-weight:700}
.sm-chips .book{background:rgba(17,216,137,.15);color:var(--green,#11d889)}.sm-chips .warn{background:rgba(255,122,122,.15);color:#ff7a7a}
.sm-alt{margin-top:5px;font-size:11.5px;color:var(--muted,#8f9ab8)}
.sm-win{text-align:right}.sm-win b{display:block;font-size:24px;font-weight:900;color:var(--green,#11d889);line-height:1}
.sm-win small{font-size:10.5px;color:var(--muted,#8f9ab8);font-weight:700}
.sm-empty,.sm-note{color:var(--muted,#8f9ab8);font-size:12.5px;line-height:1.5}
.sm-empty{padding:30px 6px;text-align:center}.sm-note{margin-top:16px;padding:12px;border-radius:12px;background:rgba(255,255,255,.04)}
@media(max-width:420px){.sm-card{grid-template-columns:26px 44px 1fr auto;gap:8px;padding:10px}.sm-photo{width:44px;height:44px}.sm-win b{font-size:21px}}
`;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
  const root = document.createElement('div'); root.id = 'smartView'; document.body.appendChild(root);

  function initials(n) { return String(n || '?').split(/\s+/).map(x => x[0]).slice(0, 2).join('').toUpperCase(); }

  function visibleRows() {
    let rows = state.rows.filter(r =>
      (state.market === 'ALL' || r.smart_market === state.market) &&
      (state.source === 'all' || r.smart_source === state.source) &&
      (r.win_chance || 0) >= state.minWin);
    if (state.view !== 'players') return rows.map(r => ({ best: r, alt: null }));
    const seen = new Map();
    for (const r of rows) {
      if (!seen.has(r.player_id)) seen.set(r.player_id, { best: r, alt: null });
      else if (!seen.get(r.player_id).alt) seen.get(r.player_id).alt = r;
    }
    return [...seen.values()];
  }

  function pickText(r) { return `${esc(r.pick_side)} ${num(r.line)} ${LABEL[r.smart_market] || esc(r.smart_market)}`; }

  function card(item, i) {
    const r = item.best, book = r.smart_source === 'book';
    const photo = r.headshot ? `<img class="sm-photo" src="${esc(r.headshot)}" alt="" loading="lazy">` : `<div class="sm-photo">${esc(initials(r.name))}</div>`;
    const chips = [
      book ? `<span class="book">BOOK LINE${r.books ? ' · ' + r.books + ' books' : ''}</span>` : `<span>vs season avg</span>`,
      book && r.dtm != null ? `<span class="book">DTM ${r.dtm > 0 ? '+' : ''}${num(r.dtm, 1)}</span>` : '',
      `<span>Proj ${num(r.projection)} ${LABEL[r.smart_market] || ''}</span>`,
      r.b2b ? `<span class="warn">B2B</span>` : (r.rest_days != null ? `<span>Rest ${r.rest_days}d</span>` : ''),
      r.injury_status ? `<span class="warn">${esc(r.injury_status)}</span>` : '',
    ].filter(Boolean).join('');
    const alt = item.alt ? `<div class="sm-alt">Also: ${pickText(item.alt)} · ${num(item.alt.win_chance, 0)}%</div>` : '';
    return `<div class="sm-card${r.locked ? ' locked' : ''}" onclick="${r.locked ? 'HE.openUpgrade()' : `smartOpen(${+r.player_id},'${esc(r.smart_market)}')`}">${r.locked ? '<span class="lock-pill">🔒 Locked</span>' : ''}
      <div class="sm-rank">${i + 1}</div>${photo}
      <div><div class="sm-name">${esc(r.name)}<small>${esc(r.team)} vs ${esc(r.opponent)}</small></div>
        <div class="sm-pick ${String(r.pick_side).toLowerCase()}">${pickText(r)}</div>
        <div class="sm-chips">${chips}</div>${alt}</div>
      <div class="sm-win"><b>${num(r.win_chance, 0)}%</b><small>WIN CHANCE</small></div></div>`;
  }

  const chipBtn = (label, on, js) => `<button class="sm-chip ${on ? 'on' : ''}" onclick="${js}">${label}</button>`;

  function render() {
    const mkts = ['ALL', 'PTS', 'AST', 'REB', '3PM', 'PA'];
    let body;
    if (state.loading) body = `<div class="sm-empty">Loading smart predictions…</div>`;
    else if (state.error) body = `<div class="sm-empty">${esc(state.error)}</div>`;
    else {
      const items = visibleRows();
      body = items.length ? items.slice(0, 80).map(card).join('') : `<div class="sm-empty">No picks match these filters yet.</div>`;
    }
    root.innerHTML = `<div class="sm-wrap">
      <div class="sm-top"><button class="sm-back" onclick="closeSmart()">← Back</button><div class="sm-title">Smart <span>Prediction</span></div></div>
      <div class="sm-sub">Highest-probability picks across points, assists, rebounds, 3-pointers and P+A.</div>
      <div class="sm-bar">
        ${chipBtn('One per player', state.view === 'players', "smartSet('view','players')")}
        ${chipBtn('All picks', state.view === 'all', "smartSet('view','all')")}
        <select class="sm-sel" onchange="smartSet('source',this.value)">
          <option value="all" ${state.source === 'all' ? 'selected' : ''}>All sources</option>
          <option value="book" ${state.source === 'book' ? 'selected' : ''}>Book lines only</option>
          <option value="model" ${state.source === 'model' ? 'selected' : ''}>vs season avg only</option></select>
        <select class="sm-sel" onchange="smartSet('minWin',+this.value)">
          ${[0, 55, 60, 65, 70].map(v => `<option value="${v}" ${state.minWin === v ? 'selected' : ''}>${v ? 'Win ≥ ' + v + '%' : 'Any win chance'}</option>`).join('')}</select>
      </div>
      <div class="sm-bar">${mkts.map(m => chipBtn(m === 'ALL' ? 'All' : (LABEL[m]), state.market === m, `smartSet('market','${m}')`)).join('')}</div>
      ${body}
      <div class="sm-note"><b>How it works.</b> Each pick is the more likely side (over/under) of a line. <b>BOOK LINE</b> picks use a real sportsbook line; DTM is the gap between the model and the market after removing the sportsbook margin. <b>vs season avg</b> picks use the player's season average as the line because no book line exists, so they show consistency, not value against the market. Ranking is by Win Chance, with small penalties for low minutes and for picks without a book line. Win Chance is a model estimate pulled toward 50%, not a guarantee.</div>
    </div>`;
  }

  async function load() {
    state.loading = true; state.error = ''; render();
    try {
      const r = await fetch('/api/smart-picks?limit=500');
      const body = await r.json();
      if (!r.ok) throw new Error((body.detail && body.detail.message) || 'Could not load predictions');
      state.rows = Array.isArray(body) ? body : [];
    } catch (e) { state.error = e.message || 'Could not load predictions'; }
    state.loading = false; render();
  }

  window.smartSet = (k, v) => { if (k === 'market' && v !== 'ALL' && window.HE && HE.marketLocked(v)) { HE.openUpgrade('market'); return; } state[k] = v; render(); };
  window.openSmart = () => {
    root.classList.add('open'); document.body.style.overflow = 'hidden'; root.scrollTop = 0;
    if (typeof window.closeMobileMenu === 'function') window.closeMobileMenu();
    load();
  };
  window.closeSmart = () => { root.classList.remove('open'); document.body.style.overflow = ''; };
  window.smartOpen = async (pid, market) => {
    window.closeSmart();
    try { if (typeof ensureMarketData === 'function') { const d = await ensureMarketData(market); marketCache[market] = d; } } catch (e) { /* detail falls back */ }
    if (typeof detail === 'function') detail(pid, market);
  };
  document.addEventListener('keydown', e => { if (e.key === 'Escape') window.closeSmart(); });
})();
