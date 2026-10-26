/* HOOPEDGE: prijava, registracija, planovi. Ucitava se na dashboardu i na /account.
   Svi podaci o pravima dolaze sa servera (/api/me); ovdje se samo prikazuju. Pravo zakljucavanje je na serveru. */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const eur = c => '€' + (c / 100).toFixed(2);
  const FALLBACK_PLANS = [
    { id: 'free', name: 'FREE', price: 0, features: ['First 5 projections of the day', 'Points (PTS) market only', 'Everything else is blurred'] },
    { id: 'pro', name: 'PRO', price: 9.99, features: ['All player points projections', 'Points (PTS) market only', 'No HOOPEDGE AI assistant', '1 month access'] },
    { id: 'pro_plus', name: 'PRO+', price: 39.99, features: ['Everything: PTS, AST, REB, 3PM and P+A', 'Smart Prediction across all markets', 'HOOPEDGE AI assistant', '1 month access'] },
  ];

  const HE = window.HE = { me: null, plans: null };

  async function api(path, opts = {}) {
    const r = await fetch(path, {
      credentials: 'same-origin', ...opts,
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    });
    let j = {};
    try { j = await r.json(); } catch (e) { /* prazan odgovor */ }
    if (!r.ok) {
      const d = j.detail && typeof j.detail === 'object' ? j.detail : { message: typeof j.detail === 'string' ? j.detail : 'Request failed' };
      const err = new Error(d.message || 'Request failed');
      err.status = r.status; err.detail = d;
      throw err;
    }
    return j;
  }
  HE.api = api;
  const post = (p, body) => api(p, { method: 'POST', body: JSON.stringify(body || {}) });

  // ------------------------------------------------------------------ stanje
  const signedIn = () => !!(HE.me && HE.me.authenticated);
  HE.signedIn = signedIn;
  HE.planKey = () => (HE.me ? HE.me.plan.key : 'guest');
  HE.marketLocked = m => !!HE.me && !HE.me.entitlements.markets.includes(String(m).toUpperCase());
  HE.canAI = () => !HE.me || HE.me.entitlements.ai;

  HE.refresh = async function () {
    try { HE.me = await api('/api/me'); } catch (e) { console.warn('HOOPEDGE /api/me failed', e); }
    paintAll();
    return HE.me;
  };

  function paintHeader() {
    [$('#heAuthBtn'), $('#heAuthBtnM')].filter(Boolean).forEach(b => {
      if (signedIn()) { b.innerHTML = `<span class="he-chip-plan ${esc(HE.me.plan.key)}">${esc(HE.me.plan.label)}</span> Account`; b.classList.add('he-signed'); }
      else { b.textContent = 'Sign in'; b.classList.remove('he-signed'); }
    });
  }

  function paintMarkets() {
    document.querySelectorAll('.market-btn').forEach(b => {
      const lock = HE.marketLocked(b.dataset.market);
      b.classList.toggle('is-locked', lock);
      b.title = lock ? 'Included in Pro+' : '';
    });
  }

  function paintChat() {
    const f = document.getElementById('heFab');
    if (f) f.textContent = (HE.canAI() ? '' : '🔒 ') + 'Ask HOOPEDGE AI';
  }

  function planCtaLabel(id) {
    const cur = HE.planKey(), isAdmin = cur === 'admin';
    if (!signedIn()) return id === 'free' ? 'Create free account' : 'Sign in to buy';
    if (isAdmin) return id === 'free' ? 'Admin account' : 'Buy (test)';
    if (id === 'free') return cur === 'free' ? 'Current plan' : 'Included';
    if (cur === id) return 'Extend 1 month';
    return id === 'pro' ? 'Choose Pro' : 'Choose Pro+';
  }
  HE.planCta = id => `<button class="plan-cta" data-plan="${esc(id)}" onclick="HE.choosePlan('${esc(id)}')">${esc(planCtaLabel(id))}</button>`;

  function paintPlanButtons() {
    document.querySelectorAll('#plans .plan-cta').forEach(b => {
      const id = b.dataset.plan;
      b.textContent = planCtaLabel(id);
      b.disabled = signedIn() && id === 'free';
    });
  }

  function paintBanner() {
    const cards = $('#cards');
    if (!cards) return;
    let el = $('#planBanner');
    const m = HE.me;
    const list = (typeof allPlayers !== 'undefined' && Array.isArray(allPlayers)) ? allPlayers : [];
    const open = list.filter(p => !p.locked).length, total = list.length;
    let html = '', cls = '';
    if (!m) html = '';
    else if (m.preview) {
      cls = 'preview';
      html = `<div><b>ADMIN PREVIEW</b> · you are seeing the app exactly as a <b>${esc(m.plan.label)}</b> user would.</div><div class="he-bn-actions"><button class="he-btn small" onclick="HE.exitPreview()">Exit preview</button></div>`;
    } else if (!m.authenticated) {
      html = `<div>🔒 <b>Sign in or create a free account</b> to unlock the first 5 projections of the day.</div><div class="he-bn-actions"><button class="he-btn small" onclick="HE.openAuth('login')">Sign in</button><button class="he-btn small ghost" onclick="HE.openAuth('register')">Create account</button></div>`;
    } else if (m.plan.key === 'free') {
      html = `<div><b>Free plan</b> · ${open} of ${total || '—'} projections visible, points market only.</div><div class="he-bn-actions"><button class="he-btn small purple" onclick="HE.openUpgrade()">See plans</button></div>`;
    } else if (m.plan.key === 'pro') {
      html = `<div><b>Pro plan</b> · all points projections. Upgrade to <b>Pro+</b> for assists, rebounds, 3PM, P+A and HOOPEDGE AI.</div><div class="he-bn-actions"><button class="he-btn small purple" onclick="HE.openUpgrade('market')">Upgrade to Pro+</button></div>`;
    }
    if (!html) { if (el) el.remove(); return; }
    if (!el) { el = document.createElement('div'); el.id = 'planBanner'; cards.parentNode.insertBefore(el, cards); }
    el.className = cls; el.innerHTML = html;
  }

  function paintAll() { paintHeader(); paintMarkets(); paintChat(); paintPlanButtons(); paintBanner(); }
  HE.afterRender = function () { paintMarkets(); paintBanner(); paintPlanButtons(); };

  HE.headerClick = () => { if (signedIn()) location.href = '/account'; else HE.openAuth('login'); };

  // ucitaj podatke dashboarda ponovo (nakon prijave/odjave)
  HE.reload = function () {
    try {
      if (typeof marketCache !== 'undefined') marketCache = {};
      if (typeof allPlayers !== 'undefined') allPlayers = [];
      if (typeof selectedGame !== 'undefined') selectedGame = null;
      if (typeof load === 'function') load();
    } catch (e) { console.error(e); }
  };

  // ------------------------------------------------------------------ toast i modal
  function toast(msg, err) {
    let t = $('#heToast');
    if (!t) { t = document.createElement('div'); t.id = 'heToast'; document.body.appendChild(t); }
    t.textContent = msg; t.className = (err ? 'err ' : '') + 'show';
    clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('show'), 3600);
  }
  HE.toast = toast;

  function modal() {
    let m = $('#heModal');
    if (!m) {
      m = document.createElement('div'); m.id = 'heModal';
      m.addEventListener('mousedown', e => { if (e.target === m) closeModal(); });
      document.body.appendChild(m);
    }
    return m;
  }
  function openModal(html, wide) {
    const m = modal();
    m.innerHTML = `<div class="he-box${wide ? ' wide' : ''}" role="dialog" aria-modal="true"><button class="he-x" aria-label="Close" onclick="HE.closeModal()">×</button>${html}</div>`;
    m.classList.add('open');
    return m.firstChild;
  }
  function closeModal() { const m = $('#heModal'); if (m) m.classList.remove('open'); }
  HE.closeModal = closeModal;
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

  const msg = (kind, text) => text ? `<div class="he-msg ${kind}">${esc(text)}</div>` : '';

  // ------------------------------------------------------------------ prijava / registracija
  HE.openAuth = function (tab = 'login', opts = {}) {
    const isLogin = tab === 'login';
    const box = openModal(`
      <h2>${isLogin ? 'Welcome back' : 'Create your account'}</h2>
      <p class="he-sub">${isLogin ? 'Sign in to see your projections.' : 'Free account: first 5 projections of the day. You must confirm your email.'}</p>
      <div class="he-tabs"><button class="${isLogin ? 'on' : ''}" onclick="HE.openAuth('login')">Sign in</button><button class="${isLogin ? '' : 'on'}" onclick="HE.openAuth('register')">Create account</button></div>
      <div id="heAuthMsg">${msg(opts.kind || 'info', opts.notice)}</div>
      <form id="heAuthForm" novalidate>
        <div class="he-field"><label for="heId">${isLogin ? 'Email or username' : 'Email'}</label><input id="heId" type="${isLogin ? 'text' : 'email'}" autocomplete="${isLogin ? 'username' : 'email'}" maxlength="254" required></div>
        <div class="he-field"><label for="hePw">Password</label><input id="hePw" type="password" autocomplete="${isLogin ? 'current-password' : 'new-password'}" maxlength="128" required>${isLogin ? '<div class="he-hint" style="text-align:right"><button class="he-link" type="button" id="heForgot">Forgot password?</button></div>' : '<div class="he-hint">At least 8 characters.</div>'}</div>
        ${isLogin ? '' : '<div class="he-field"><label for="hePw2">Repeat password</label><input id="hePw2" type="password" autocomplete="new-password" maxlength="128" required></div><label class="he-check"><input type="checkbox" id="heTerms"><span>I am 18 or older and agree to the <a href="/terms" target="_blank" rel="noopener">Terms of Use</a> and <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>.</span></label>'}
        <button class="he-btn he-full" id="heSubmit" type="submit">${isLogin ? 'Sign in' : 'Create account'}</button>
      </form>`);
    const id = $('#heId', box);
    if (opts.identifier) id.value = opts.identifier;
    setTimeout(() => (opts.identifier ? $('#hePw', box) : id).focus(), 30);
    $('#heAuthForm', box).addEventListener('submit', ev => { ev.preventDefault(); (isLogin ? doLogin : doRegister)(box); });
    const fg = $('#heForgot', box);
    if (fg) fg.onclick = () => { const v = id.value.trim(); HE.openForgot(v.includes('@') ? v : ''); };
  };

  function setMsg(box, kind, text, extra = '') { $('#heAuthMsg', box).innerHTML = msg(kind, text) + extra; }
  function busy(box, on) { const b = $('#heSubmit', box); b.disabled = on; if (on) b.dataset.t = b.textContent, b.textContent = 'Please wait…'; else if (b.dataset.t) b.textContent = b.dataset.t; }

  async function doLogin(box) {
    const identifier = $('#heId', box).value.trim(), password = $('#hePw', box).value;
    if (!identifier || !password) return setMsg(box, 'err', 'Enter your email/username and password.');
    busy(box, true);
    try {
      HE.me = await post('/api/auth/login', { identifier, password });
      closeModal(); paintAll(); HE.reload(); toast('Signed in');
      if (typeof window.__heAfterLogin === 'function') window.__heAfterLogin();
    } catch (e) {
      busy(box, false);
      if (e.detail && e.detail.code === 'email_not_verified' && identifier.includes('@')) {
        setMsg(box, 'err', e.message, `<p class="he-hint">Didn't get it? <button class="he-link" type="button" id="heResend">Resend confirmation email</button></p>`);
        $('#heResend', box).onclick = () => resend(box, identifier);
      } else setMsg(box, 'err', e.message);
    }
  }

  async function resend(box, email) {
    try { const r = await post('/api/auth/resend', { email }); setMsg(box, 'ok', r.message, devBox(r.dev_link)); }
    catch (e) { setMsg(box, 'err', e.message); }
  }

  async function doRegister(box) {
    const email = $('#heId', box).value.trim(), pw = $('#hePw', box).value, pw2 = $('#hePw2', box).value;
    if (!email) return setMsg(box, 'err', 'Enter your email address.');
    if (pw.length < 8) return setMsg(box, 'err', 'Password must be at least 8 characters.');
    if (pw !== pw2) return setMsg(box, 'err', 'Passwords do not match.');
    if (!$('#heTerms', box).checked) return setMsg(box, 'err', 'Please accept the Terms of Use and Privacy Policy.');
    busy(box, true);
    try {
      const r = await post('/api/auth/register', { email, password: pw, accept_terms: true });
      box.innerHTML = `<button class="he-x" aria-label="Close" onclick="HE.closeModal()">×</button>
        <div class="he-center"><div class="he-big-ico">✉️</div><h2>Check your email</h2>
        <p class="he-sub">${esc(r.message)}</p>
        <p class="he-hint">Sent to <b>${esc(email)}</b>. Don't see it? Check spam.</p>${devBox(r.dev_link)}
        <div class="he-row" style="justify-content:center;margin-top:16px"><button class="he-btn ghost" id="heResend2">Resend email</button><button class="he-btn" id="heGoLogin">I confirmed, sign in</button></div><div id="heAuthMsg" style="margin-top:12px"></div></div>`;
      $('#heResend2', box).onclick = () => resend(box, email);
      $('#heGoLogin', box).onclick = () => HE.openAuth('login', { identifier: email });
    } catch (e) { busy(box, false); setMsg(box, 'err', e.message); }
  }

  function devBox(link) {
    return link ? `<div class="he-msg dev"><b>DEV MODE</b>: no email is sent when running locally. <a href="${esc(link)}">Open the link</a> (this is what the email would contain).</div>` : '';
  }

  HE.openForgot = function (email) {
    const box = openModal(`<h2>Reset your password</h2>
      <p class="he-sub">Enter your account email and we'll send you a link to choose a new password.</p>
      <div id="heAuthMsg"></div>
      <form id="heForgotForm" novalidate>
        <div class="he-field"><label for="heFe">Email</label><input id="heFe" type="email" autocomplete="email" maxlength="254" required></div>
        <button class="he-btn he-full" id="heSubmit" type="submit">Send reset link</button>
      </form>
      <p class="he-hint he-center" style="margin-top:14px"><button class="he-link" type="button" id="heBackLogin">Back to sign in</button></p>`);
    const inp = $('#heFe', box); inp.value = email || ''; setTimeout(() => inp.focus(), 30);
    $('#heBackLogin', box).onclick = () => HE.openAuth('login');
    $('#heForgotForm', box).addEventListener('submit', async ev => {
      ev.preventDefault();
      const v = inp.value.trim();
      if (!v) return setMsg(box, 'err', 'Enter your email address.');
      busy(box, true);
      try { const r = await post('/api/auth/forgot', { email: v }); busy(box, false); setMsg(box, 'ok', r.message, devBox(r.dev_link)); }
      catch (e) { busy(box, false); setMsg(box, 'err', e.message); }
    });
  };

  HE.openReset = function (token) {
    const box = openModal(`<h2>Choose a new password</h2>
      <p class="he-sub">Pick a strong password you don't use anywhere else.</p>
      <div id="heAuthMsg"></div>
      <form id="heResetForm" novalidate>
        <div class="he-field"><label for="heNp">New password</label><input id="heNp" type="password" autocomplete="new-password" maxlength="128" required><div class="he-hint">At least 8 characters.</div></div>
        <div class="he-field"><label for="heNp2">Repeat new password</label><input id="heNp2" type="password" autocomplete="new-password" maxlength="128" required></div>
        <button class="he-btn he-full" id="heSubmit" type="submit">Change password</button>
      </form>`);
    setTimeout(() => $('#heNp', box).focus(), 30);
    $('#heResetForm', box).addEventListener('submit', async ev => {
      ev.preventDefault();
      const p1 = $('#heNp', box).value, p2 = $('#heNp2', box).value;
      if (p1.length < 8) return setMsg(box, 'err', 'Password must be at least 8 characters.');
      if (p1 !== p2) return setMsg(box, 'err', 'Passwords do not match.');
      busy(box, true);
      try {
        await post('/api/auth/reset', { token, password: p1 });
        box.innerHTML = `<button class="he-x" aria-label="Close" onclick="HE.closeModal()">×</button><div class="he-center"><div class="he-big-ico">✅</div><h2>Password changed</h2><p class="he-sub">You were signed out on all devices. Sign in with your new password.</p><button class="he-btn" onclick="HE.openAuth('login')">Sign in</button></div>`;
      } catch (e) {
        busy(box, false);
        setMsg(box, 'err', e.message, e.detail && e.detail.code === 'bad_reset_token' ? '<p class="he-hint"><button class="he-link" type="button" id="heNewLink">Request a new link</button></p>' : '');
        const b = $('#heNewLink', box); if (b) b.onclick = () => HE.openForgot();
      }
    });
  };

  HE.logout = async function () {
    try { await post('/api/auth/logout'); } catch (e) { /* svejedno */ }
    HE.me = null; await HE.refresh();
    if (location.pathname === '/account') location.href = '/'; else { HE.reload(); toast('Signed out'); }
  };

  // ------------------------------------------------------------------ planovi i placanje
  async function loadPlans() {
    if (HE.plans) return HE.plans;
    try { HE.plans = await api('/api/plans'); } catch (e) { HE.plans = FALLBACK_PLANS; }
    return HE.plans;
  }

  HE.openUpgrade = async function (reason) {
    const plans = await loadPlans();
    const title = reason === 'ai' ? 'HOOPEDGE AI is a Pro+ feature'
      : reason === 'market' ? 'More markets with Pro+' : 'Unlock all projections';
    const sub = reason === 'ai' ? 'Ask HOOPEDGE AI about any player, matchup or projection with Pro+.'
      : reason === 'market' ? 'Assists, rebounds, 3-pointers and Points + Assists are included in Pro+.'
      : 'Pick the plan that fits you. Each plan is a one-time payment for 1 month.';
    const cur = HE.planKey();
    const cards = plans.map(p => {
      const current = signedIn() && cur === p.id;
      const btn = !signedIn()
        ? (p.id === 'free' ? `<button class="he-btn ghost" onclick="HE.openAuth('register')">Create free account</button>` : `<button class="he-btn ${p.id === 'pro_plus' ? 'purple' : ''}" onclick="HE.openAuth('login',{notice:'Sign in to buy a plan.'})">Sign in to buy</button>`)
        : p.id === 'free' ? `<button class="he-btn ghost" disabled>${cur === 'free' ? 'Current plan' : 'Included'}</button>`
        : `<button class="he-btn ${p.id === 'pro_plus' ? 'purple' : ''}" onclick="HE.buy('${esc(p.id)}')">${current ? 'Extend 1 month' : 'Choose ' + esc(p.name)} · €${p.price}</button>`;
      return `<div class="he-plan ${current ? 'current' : ''} ${p.id === 'pro_plus' ? 'best' : ''}"><h3>${esc(p.name)}</h3>
        <div class="he-price">€${p.price}${p.price ? '<small> / month</small>' : ''}</div>
        <ul>${p.features.map(f => `<li>${esc(f)}</li>`).join('')}</ul>${btn}</div>`;
    }).join('');
    openModal(`<h2>${esc(title)}</h2><p class="he-sub">${esc(sub)}</p><div id="heAuthMsg"></div><div class="he-plans">${cards}</div>
      ${HE.me && HE.me.billing_enabled === false && signedIn() ? '<p class="he-hint" style="margin-top:12px">Online payment is not enabled yet. Contact the administrator to activate a plan.</p>' : ''}`, true);
  };

  HE.choosePlan = function (id) {
    if (!signedIn()) return id === 'free' ? HE.openAuth('register') : HE.openAuth('login', { notice: 'Sign in to buy a plan.' });
    if (id === 'free') return toast(HE.planKey() === 'free' ? 'You are on the Free plan.' : 'Free features are included in your plan.');
    HE.buy(id);
  };

  HE.buy = async function (plan) {
    if (!signedIn()) return HE.openAuth('login', { notice: 'Sign in to buy a plan.' });
    try {
      toast('Opening secure checkout…');
      const r = await post('/api/billing/checkout', { plan });
      location.href = r.url;
    } catch (e) {
      if (e.status === 401) return HE.openAuth('login');
      toast(e.message, true);
    }
  };

  HE.exitPreview = async function () {
    try { HE.me = await post('/api/admin/preview', { plan: 'admin' }); paintAll(); HE.reload(); toast('Preview off'); }
    catch (e) { toast(e.message, true); }
  };

  // 401/403 odgovor servera -> odgovarajuci prozor
  HE.handleForbidden = function (detail) {
    const d = detail || {};
    if (d.login_required) return HE.openAuth('login');
    if (d.upgrade_required) return HE.openUpgrade(d.required_plan === 'pro_plus' ? (/AI/.test(d.message || '') ? 'ai' : 'market') : '');
    if (d.message) toast(d.message, true);
  };

  // ------------------------------------------------------------------ start
  function start() {
    const q = new URLSearchParams(location.search);
    const clean = () => history.replaceState(null, '', location.pathname + location.hash);
    if (q.get('reset')) { const t = q.get('reset'); clean(); HE.openReset(t); }
    HE.ready = HE.refresh().then(() => {
      if (q.get('verified')) { clean(); HE.openAuth('login', { notice: '✅ Email confirmed. Sign in to continue.', kind: 'ok' }); }
      else if (q.get('verify')) { clean(); HE.openAuth('login', { notice: 'That confirmation link is invalid or already used. If your account is still unconfirmed, sign in to resend it.', kind: 'err' }); }
      else if (q.get('login') && !signedIn()) { clean(); HE.openAuth('login'); }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
