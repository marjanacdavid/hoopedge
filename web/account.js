/* Stranica naloga: plan, placanja, nadogradnja i admin alati. Prava dolaze sa servera (/api/me). */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const root = $('#acct');
  const eur = c => '€' + (c / 100).toFixed(2);
  const dt = iso => iso ? new Date(iso).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
  const day = iso => iso ? new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—';
  const kv = (k, v, small) => `<div class="acct-kv"><span>${esc(k)}</span><b>${v}</b>${small ? `<small>${small}</small>` : ''}</div>`;
  let notice = '';

  const FEATURES = {
    guest: 'Nothing unlocked — sign in to see the first 5 projections.',
    free: 'First 5 projections of the day · points market only · no AI assistant.',
    pro: 'All player points projections · no other markets · no AI assistant.',
    pro_plus: 'All markets (PTS, AST, REB, 3PM, P+A) · Smart Prediction · HOOPEDGE AI assistant.',
    admin: 'Everything, no payment needed. Use "Preview as" below to see exactly what each plan shows.',
  };

  function statusHtml(p) {
    if (p.key === 'admin') return '<span class="acct-status active">● Administrator</span>';
    if (p.is_paid && p.active) return '<span class="acct-status active">● Active</span>';
    if (p.expired) return '<span class="acct-status expired">● Expired — back on Free</span>';
    return '<span class="acct-status none">● Free plan (no payment)</span>';
  }

  function planCard(me) {
    const p = me.plan;
    const paid = p.is_paid && !me.preview;
    const left = p.days_left != null ? `${p.days_left} day${p.days_left === 1 ? '' : 's'} left` : '';
    return `<div class="acct-card"><h2>Your plan</h2>
      <div class="acct-plan-top"><span class="acct-badge ${esc(p.key)}">${esc(p.label.toUpperCase())}</span>${statusHtml(p)}${me.preview ? '<span class="he-chip-plan admin">preview</span>' : ''}</div>
      <div class="acct-grid">
        ${kv('Plan', esc(p.label))}
        ${kv('Last payment', paid || p.expired ? esc(dt(p.paid_at)) : '—', paid || p.expired ? '' : 'No payment yet')}
        ${kv('Valid until', paid || p.expired ? esc(dt(p.expires_at)) : (p.key === 'admin' ? 'No expiry' : '—'), paid ? left : (p.expired ? 'Expired' : ''))}
      </div>
      <p class="acct-note">${esc(FEATURES[p.key] || '')}</p></div>`;
  }

  function upgradeCard(me) {
    const cur = me.plan.key, canPay = me.billing_enabled;
    const btn = (id, label, price) => `<button class="he-btn ${id === 'pro_plus' ? 'purple' : ''}" ${canPay ? '' : 'disabled'} onclick="HE.buy('${id}')">${cur === id ? 'Extend 1 month' : 'Choose ' + label} · ${eur(price)}</button>`;
    return `<div class="acct-card"><h2>Upgrade or extend</h2>
      <div class="he-plans" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">
        <div class="he-plan ${cur === 'pro' ? 'current' : ''}"><h3>PRO</h3><div class="he-price">€9.99<small> / month</small></div>
          <ul><li>All player points projections</li><li>Points market only</li><li>No HOOPEDGE AI</li></ul>${btn('pro', 'Pro', 999)}</div>
        <div class="he-plan best ${cur === 'pro_plus' ? 'current' : ''}"><h3>PRO+</h3><div class="he-price">€39.99<small> / month</small></div>
          <ul><li>All markets: PTS, AST, REB, 3PM, P+A</li><li>Smart Prediction, all markets</li><li>HOOPEDGE AI assistant</li></ul>${btn('pro_plus', 'Pro+', 3999)}</div>
      </div>
      <p class="acct-note">Each purchase is a one-time payment for 1 month (no automatic renewal). Buying the same plan again adds a month after your current end date. Switching to a different plan starts it immediately and replaces the remaining time of the old plan.${canPay ? '' : ' <b>Online payment is not enabled yet</b> — contact the administrator to activate a plan.'}</p></div>`;
  }

  function historyCard(me) {
    const rows = me.payments.map(p => `<tr><td>${esc(day(p.paid_at))}</td><td>${esc(p.label)}</td><td>${p.amount_cents ? esc(eur(p.amount_cents)) : 'Free (granted)'}</td><td>${esc(day(p.period_start))} → ${esc(day(p.period_end))}</td><td>${esc(p.provider)}</td></tr>`).join('');
    return `<div class="acct-card"><h2>Payment history</h2>${rows
      ? `<div class="acct-scroll"><table class="acct-table"><thead><tr><th>Paid</th><th>Plan</th><th>Amount</th><th>Period</th><th>Via</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : '<div class="acct-empty">No payments yet.</div>'}</div>`;
  }

  function profileCard(me) {
    const u = me.user;
    return `<div class="acct-card"><h2>Account</h2><div class="acct-grid">
      ${kv('Email', u.email ? esc(u.email) : '—')}
      ${u.username ? kv('Username', esc(u.username)) : ''}
      ${kv('Email status', u.email_verified ? '✅ Confirmed' : '⚠ Not confirmed')}
      ${kv('Member since', esc(day(u.created_at)))}</div>
      <div class="he-row" style="margin-top:16px"><a class="he-btn ghost" href="/" style="text-decoration:none;display:inline-block">← Dashboard</a><button class="he-btn danger" onclick="HE.logout()">Sign out</button></div></div>`;
  }

  function adminCard(me) {
    const cur = me.preview || 'admin';
    const seg = [['admin', 'Admin (everything)'], ['guest', 'Guest'], ['free', 'Free'], ['pro', 'Pro'], ['pro_plus', 'Pro+']]
      .map(([k, l]) => `<button class="${cur === k ? 'on' : ''}" onclick="ACCT.preview('${k}')">${l}</button>`).join('');
    return `<div class="acct-card acct-admin"><h2>Admin tools</h2>
      <p class="acct-note" style="margin:0 0 10px">Preview as: the whole app (dashboard, Smart Prediction, AI) behaves exactly like for that plan until you switch back.</p>
      <div class="acct-seg">${seg}</div>
      <div id="admMsg"></div>
      <h2 style="margin-top:20px">Grant / manage a user</h2>
      <div class="acct-inline">
        <div class="he-field"><label>Email or username</label><input id="admId" placeholder="user@example.com"></div>
        <div class="he-field" style="max-width:130px"><label>Plan</label><select id="admPlan"><option value="pro">Pro</option><option value="pro_plus">Pro+</option></select></div>
        <div class="he-field" style="max-width:90px"><label>Months</label><input id="admMonths" type="number" min="1" max="12" value="1"></div>
        <button class="he-btn" onclick="ACCT.grant()">Grant</button>
        <button class="he-btn ghost" onclick="ACCT.verifyUser()">Confirm email</button>
        <button class="he-btn ghost" onclick="ACCT.revoke()">Revoke</button>
      </div>
      <div id="admUsers" style="margin-top:18px"><button class="he-btn small ghost" onclick="ACCT.users()">Show users</button></div></div>`;
  }

  function securityCard(me) {
    if (me.user.is_admin) return `<div class="acct-card"><h2>Security</h2><p class="acct-note" style="margin:0 0 12px">The administrator password is set on the server (<code>HOOPEDGE_ADMIN_PASSWORD_HASH</code>), so it cannot be changed here.</p><button class="he-btn ghost" onclick="ACCT.logoutAll()">Sign out of all devices</button></div>`;
    return `<div class="acct-card"><h2>Security</h2><div id="secMsg"></div>
      <div class="acct-inline">
        <div class="he-field"><label for="pwCur">Current password</label><input id="pwCur" type="password" autocomplete="current-password" maxlength="128"></div>
        <div class="he-field"><label for="pwNew">New password</label><input id="pwNew" type="password" autocomplete="new-password" maxlength="128"></div>
        <div class="he-field"><label for="pwNew2">Repeat new password</label><input id="pwNew2" type="password" autocomplete="new-password" maxlength="128"></div>
        <button class="he-btn" onclick="ACCT.changePw()">Change password</button></div>
      <p class="acct-note">Changing your password signs out your other devices.</p>
      <div class="he-row" style="margin-top:12px"><button class="he-btn ghost" onclick="ACCT.logoutAll()">Sign out of all devices</button></div></div>`;
  }

  function dangerCard(me) {
    if (me.user.is_admin) return '';
    return `<div class="acct-card" style="border-color:rgba(255,122,122,.45)"><h2 style="color:#ff9d9d">Delete account</h2>
      <p class="acct-note" style="margin-top:0">Permanently deletes your account and signs you out everywhere. Any remaining paid time ends immediately. Payment records are kept without personal data, as needed for bookkeeping.</p>
      <div id="delMsg"></div>
      <div class="acct-inline"><div class="he-field"><label for="delPw">Your password</label><input id="delPw" type="password" autocomplete="current-password" maxlength="128"></div>
      <button class="he-btn danger" onclick="ACCT.deleteAcct()">Delete my account</button></div></div>`;
  }

  let lastSnap = '';
  function render() {
    const me = HE.me;
    lastSnap = JSON.stringify(me);
    if (!me || !me.authenticated) {
      root.innerHTML = `<div class="acct-card he-center"><div class="he-big-ico">🔐</div><h2 style="font-size:20px;color:#fff;text-transform:none;letter-spacing:0">Sign in to see your account</h2>
        <p class="he-sub">Your plan, payments and expiry date are shown here.</p><button class="he-btn" onclick="HE.openAuth('login')">Sign in</button> <button class="he-btn ghost" onclick="HE.openAuth('register')">Create account</button></div>`;
      window.__heAfterLogin = () => { render(); };
      return;
    }
    root.innerHTML = `<h1>My account</h1><div class="he-sub" style="margin:0">Plan, validity and payments.</div>
      ${notice ? `<div class="he-msg info" style="margin-top:14px">${esc(notice)}</div>` : ''}
      ${planCard(me)}${me.plan.key === 'admin' && !me.preview ? '' : upgradeCard(me)}${historyCard(me)}${profileCard(me)}${securityCard(me)}${me.user.is_admin ? adminCard(me) : ''}${dangerCard(me)}`;
  }

  const admMsg = (kind, t) => { const el = $('#admMsg'); if (el) el.innerHTML = `<div class="he-msg ${kind}">${esc(t)}</div>`; };
  const val = id => ($(id) ? $(id).value.trim() : '');
  const post = (p, b) => HE.api(p, { method: 'POST', body: JSON.stringify(b || {}) });

  const secMsg = (kind, t) => { const el = $('#secMsg'); if (el) el.innerHTML = `<div class="he-msg ${kind}">${esc(t)}</div>`; };

  window.ACCT = {
    async changePw() {
      const cur = val('#pwCur'), n1 = $('#pwNew').value, n2 = $('#pwNew2').value;
      if (!cur || !n1) return secMsg('err', 'Fill in your current and new password.');
      if (n1.length < 8) return secMsg('err', 'New password must be at least 8 characters.');
      if (n1 !== n2) return secMsg('err', 'New passwords do not match.');
      try { const r = await post('/api/account/password', { current: $('#pwCur').value, password: n1 }); ['#pwCur', '#pwNew', '#pwNew2'].forEach(s => $(s).value = ''); secMsg('ok', r.message); }
      catch (e) { secMsg('err', e.message); }
    },
    async logoutAll() {
      try { await post('/api/auth/logout-all'); } catch (e) { /* svejedno */ }
      location.href = '/';
    },
    async deleteAcct() {
      const pw = $('#delPw').value;
      const el = $('#delMsg');
      if (!pw) { el.innerHTML = '<div class="he-msg err">Enter your password to confirm.</div>'; return; }
      if (!confirm('Delete your account permanently? This cannot be undone.')) return;
      try { await post('/api/account/delete', { password: pw }); location.href = '/'; }
      catch (e) { el.innerHTML = `<div class="he-msg err">${esc(e.message)}</div>`; }
    },
    async preview(k) {
      try { HE.me = await post('/api/admin/preview', { plan: k }); render(); admMsg('ok', k === 'admin' ? 'Back to full admin access.' : `Now previewing as ${HE.me.plan.label}. Open the dashboard to see it.`); }
      catch (e) { admMsg('err', e.message); }
    },
    async grant() {
      try { const r = await post('/api/admin/grant', { identifier: val('#admId'), plan: val('#admPlan'), months: +val('#admMonths') || 1 }); admMsg('ok', `Granted ${r.plan}. Valid until ${dt(r.valid_until)}.`); }
      catch (e) { admMsg('err', e.message); }
    },
    async verifyUser() { try { await post('/api/admin/verify', { identifier: val('#admId') }); admMsg('ok', 'Email marked as confirmed.'); } catch (e) { admMsg('err', e.message); } },
    async revoke() { try { await post('/api/admin/revoke', { identifier: val('#admId') }); admMsg('ok', 'Plan revoked (user is on Free).'); } catch (e) { admMsg('err', e.message); } },
    async users() {
      try {
        const list = await HE.api('/api/admin/users');
        $('#admUsers').innerHTML = `<div class="acct-scroll"><table class="acct-table"><thead><tr><th>User</th><th>Plan</th><th>Valid until</th><th>Email</th><th>Last login</th></tr></thead><tbody>${list.map(u => `<tr><td>${esc(u.email || u.username)}${u.is_admin ? ' 👑' : ''}</td><td>${esc(u.plan)}</td><td>${esc(u.valid_until ? day(u.valid_until) : '—')}</td><td>${u.verified ? '✅' : '⚠'}</td><td>${esc(u.last_login ? day(u.last_login) : '—')}</td></tr>`).join('')}</tbody></table></div>`;
      } catch (e) { admMsg('err', e.message); }
    },
  };

  async function pollAfterCheckout(before) {
    for (let i = 0; i < 15; i++) {
      await new Promise(r => setTimeout(r, 2000));
      await HE.refresh();
      if (HE.me && HE.me.payments.length > before) { notice = '✅ Payment received. Your plan is active.'; render(); return; }
    }
    notice = 'Payment is being processed. It can take a minute — refresh this page shortly.'; render();
  }

  HE.ready = HE.ready || Promise.resolve();
  (async function init() {
    await (HE.ready || HE.refresh());
    if (!HE.me) await HE.refresh();
    const q = new URLSearchParams(location.search), co = q.get('checkout');
    if (co) history.replaceState(null, '', '/account');
    if (co === 'cancel') notice = 'Payment cancelled. You were not charged.';
    render();
    if (co === 'success' && HE.me && HE.me.authenticated) { notice = 'Payment received. Activating your plan…'; const n = HE.me.payments.length; render(); pollAfterCheckout(n); }
  })();
  const _refresh = HE.refresh;
  // ponovo iscrtaj SAMO ako su se podaci promijenili (inace bi kasno osvjezavanje obrisalo ono sto korisnik kuca)
  HE.refresh = async function () { const r = await _refresh(); if (root.dataset.ready && JSON.stringify(HE.me) !== lastSnap) render(); return r; };
  root.dataset.ready = '1';
})();
