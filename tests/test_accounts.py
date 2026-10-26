"""Testovi za naloge, planove i zakljucavanje. Pokretanje: python -m pytest tests/test_accounts.py -q"""
import hashlib, hmac, json, os, re, sys, tempfile, time
_tmp = tempfile.mkdtemp()
os.environ.update(HOOPEDGE_USERS_DB=os.path.join(_tmp, "users.db"), HOOPEDGE_DB=os.path.join(_tmp, "track.db"),
                  HOOPEDGE_TRUST_PROXY="1", HOOPEDGE_BASE_URL="https://example.test",
                  STRIPE_WEBHOOK_SECRET="whsec_test")
os.environ.pop("SMTP_HOST", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from app import auth, mailer, billing
ADMIN_PW = "test-admin-Pass#42"
os.environ["HOOPEDGE_ADMIN_USER"] = "AdminHoopEd8"
os.environ["HOOPEDGE_ADMIN_PASSWORD_HASH"] = auth.hash_password(ADMIN_PW)

from app import main, accounts
from app.engine import project
from app.models import PlayerInput
from app.smart import MARKETS, build_smart

SENT = []
mailer.send_mail = lambda to, subject, text, html="": SENT.append((to, subject, text)) or True


def _players():
    out, pid = [], 1
    for g, (t1, t2) in enumerate([("AAA", "BBB"), ("CCC", "DDD"), ("EEE", "FFF")]):
        for team, opp, home in ((t1, t2, True), (t2, t1, False)):
            for k in range(4):
                base = 14 + pid % 7 * 2
                out.append(PlayerInput(id=pid, name=f"Real Name {pid}", team=team, opponent=opp, home=home,
                                       last5=base + k, last10=base, last20=base, season=base, minutes=30 + k, usage=22,
                                       ast_last5=4, ast_last10=4, ast_last20=4, ast_season=4,
                                       reb_last5=5, reb_last10=5, reb_last20=5, reb_season=5,
                                       tpm_last5=2, tpm_last10=2, tpm_last20=2, tpm_season=2,
                                       pa_last5=base + 4, pa_last10=base + 4, pa_last20=base + 4, pa_season=base + 4,
                                       game_date=f"2026-11-0{g + 1}", game_time=f"2026-11-0{g + 1}T0{g}:00Z",
                                       headshot=f"https://img.test/{pid}.png"))
                pid += 1
    return out


PLAYERS = _players()
main.STATE["data"] = {m: [project(p, market=m) for p in PLAYERS] for m in MARKETS}
main.STATE["smart"] = build_smart(PLAYERS, main.STATE["data"])
main.STATE["ready"] = True
NAMES = {p.name for p in PLAYERS}

_n = [0]


def client(ip=None):
    _n[0] += 1
    return TestClient(main.app, headers={"X-Forwarded-For": ip or f"10.0.0.{_n[0]}"})


def register_and_verify(c, email, pw="Sup3r-secret!"):
    SENT.clear()
    r = c.post("/api/auth/register", json={"accept_terms": True, "email": email, "password": pw})
    assert r.status_code == 200, r.text
    link = re.search(r"https://example\.test(/api/auth/verify\?token=[\w-]+)", SENT[-1][2]).group(1)
    return link


def login(c, ident, pw="Sup3r-secret!"):
    return c.post("/api/auth/login", json={"identifier": ident, "password": pw})


def user_with_plan(plan=None, months=1, email=None):
    c = client()
    email = email or f"u{_n[0]}@example.com"
    link = register_and_verify(c, email)
    assert c.get(link, follow_redirects=False).headers["location"] == "/?verified=1"
    assert login(c, email).status_code == 200
    if plan:
        u = accounts.store.find(email)
        accounts.store.activate_plan(u["id"], plan, "test", ref=f"t{_n[0]}", months=months)
    return c, email


# ------------------------------------------------------------ registracija i potvrda emaila
def test_register_validation():
    c = client()
    assert c.post("/api/auth/register", json={"accept_terms": True, "email": "nope", "password": "Sup3r-secret!"}).status_code == 400
    assert c.post("/api/auth/register", json={"accept_terms": True, "email": "a@b.com", "password": "short"}).status_code == 400
    assert c.post("/api/auth/register", json={"accept_terms": True, "email": "a@b.com", "password": "password"}).status_code == 400


def test_email_confirmation_flow():
    c = client()
    link = register_and_verify(c, "flow@example.com")
    assert SENT[-1][0] == "flow@example.com" and "Confirm" in SENT[-1][1]
    r = login(c, "flow@example.com")                           # prije potvrde: blokirano
    assert r.status_code == 403 and r.json()["detail"]["code"] == "email_not_verified"
    assert c.get("/api/me").json()["authenticated"] is False
    assert c.get(link, follow_redirects=False).headers["location"] == "/?verified=1"
    assert c.get(link, follow_redirects=False).headers["location"] == "/?verify=invalid"   # jednokratan
    r = login(c, "FLOW@example.com")                           # email nije osjetljiv na velika slova
    assert r.status_code == 200 and "he_session" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    me = c.get("/api/me").json()
    assert me["authenticated"] and me["plan"]["key"] == "free" and me["user"]["email_verified"]


def test_bad_token_and_expired_token():
    c = client()
    assert c.get("/api/auth/verify?token=garbage", follow_redirects=False).headers["location"] == "/?verify=invalid"
    link = register_and_verify(c, "exp@example.com")
    u = accounts.store.find("exp@example.com")
    accounts.store.db.execute("UPDATE users SET verify_expires=? WHERE id=?", (time.time() - 5, u["id"]))
    accounts.store.db.commit()
    assert c.get(link, follow_redirects=False).headers["location"] == "/?verify=invalid"


def test_register_existing_verified_email_reveals_nothing():
    c, email = user_with_plan()
    SENT.clear()
    r1 = c.post("/api/auth/register", json={"accept_terms": True, "email": email, "password": "Other-pass-123"})
    r2 = client().post("/api/auth/register", json={"accept_terms": True, "email": "brandnew@example.com", "password": "Other-pass-123"})
    assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
    assert [m[0] for m in SENT] == ["brandnew@example.com"]    # postojecem se ne salje ni mail
    assert login(client(), email, "Sup3r-secret!").status_code == 200   # lozinka se nije promijenila


def test_reregister_unverified_replaces_password_and_token():
    c = client()
    old = register_and_verify(c, "pend@example.com", "Attacker-pass-1")
    new = register_and_verify(c, "pend@example.com", "Owner-pass-2345")
    assert c.get(old, follow_redirects=False).headers["location"] == "/?verify=invalid"
    assert c.get(new, follow_redirects=False).headers["location"] == "/?verified=1"
    assert login(c, "pend@example.com", "Attacker-pass-1").status_code == 401
    assert login(c, "pend@example.com", "Owner-pass-2345").status_code == 200


def test_login_generic_errors_and_rate_limit():
    c = client("9.9.9.9")
    a = login(c, "ghost@example.com", "whatever-123")
    c2, email = user_with_plan()
    b = login(client(), email, "wrong-password")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    codes = [login(client("8.8.8.8"), "rl@example.com", "x" * 10).status_code for _ in range(10)]
    assert codes[-1] == 429


def test_cross_origin_post_blocked():
    c = client()
    r = c.post("/api/auth/register", json={"accept_terms": True, "email": "x@example.com", "password": "Sup3r-secret!"},
               headers={"Origin": "https://evil.example", "Host": "example.test"})
    assert r.status_code == 403


def test_logout_invalidates_session():
    c, _ = user_with_plan()
    assert c.get("/api/me").json()["authenticated"]
    c.post("/api/auth/logout")
    assert c.get("/api/me").json()["authenticated"] is False


# ------------------------------------------------------------ zakljucavanje podataka
def _locked(items):
    return [x for x in items if x.get("locked")]


def test_guest_sees_everything_locked_and_leaks_nothing():
    r = client().get("/api/projections?market=PTS")
    items = r.json()
    assert r.status_code == 200 and len(items) == len(PLAYERS) and len(_locked(items)) == len(items)
    assert not any(n in r.text for n in NAMES) and "img.test" not in r.text and "Real Name" not in r.text
    assert all(x["player_id"] < 0 for x in items)


def test_free_sees_exactly_first_five_in_dashboard_order():
    c, _ = user_with_plan()
    items = c.get("/api/projections?market=PTS").json()
    real = [x for x in items if not x.get("locked")]
    assert len(real) == 5 and len(_locked(items)) == len(PLAYERS) - 5
    # prvih 5 = prva utakmica, igraci po model score opadajuce
    first_game = [x for x in main.STATE["data"]["PTS"] if x.game_date == "2026-11-01"]
    want = [p.player_id for p in sorted(first_game, key=lambda x: -x.model_score)[:5]]
    assert {x["player_id"] for x in real} == set(want)
    text = json.dumps(items)
    leaked = [n for n in NAMES if n in text and n not in {x["name"] for x in real}]
    assert not leaked, leaked
    assert text.count("img.test") == 5


def test_free_selection_is_stable_across_refreshes():
    c, _ = user_with_plan()
    a = {x["player_id"] for x in c.get("/api/projections?market=PTS").json() if not x.get("locked")}
    for p in main.STATE["data"]["PTS"]:           # model "osvjezen": scoreovi se promijene
        p.model_score = 100 - p.model_score
    b = {x["player_id"] for x in c.get("/api/projections?market=PTS").json() if not x.get("locked")}
    for p in main.STATE["data"]["PTS"]:
        p.model_score = 100 - p.model_score
    assert a == b


@pytest.mark.parametrize("plan,markets_ok", [(None, ["PTS"]), ("pro", ["PTS"]), ("pro_plus", ["PTS", "AST", "REB", "3PM", "PA"])])
def test_market_access(plan, markets_ok):
    c, _ = user_with_plan(plan)
    for m in ("PTS", "AST", "REB", "3PM", "PA"):
        r = c.get(f"/api/projections?market={m}")
        if m in markets_ok:
            assert r.status_code == 200, (plan, m)
        else:
            assert r.status_code == 403 and r.json()["detail"]["upgrade_required"], (plan, m)
            assert r.json()["detail"]["required_plan"] == "pro_plus"


def test_pro_sees_all_points_real_and_pro_plus_all_markets():
    c, _ = user_with_plan("pro")
    items = c.get("/api/projections?market=PTS").json()
    assert len(items) == len(PLAYERS) and not _locked(items) and {x["name"] for x in items} == NAMES
    c2, _ = user_with_plan("pro_plus")
    for m in ("AST", "REB", "3PM", "PA"):
        assert not _locked(c2.get(f"/api/projections?market={m}").json())


def test_player_detail_gating():
    c, _ = user_with_plan()
    free_ids = {x["player_id"] for x in c.get("/api/projections?market=PTS").json() if not x.get("locked")}
    other = next(p.id for p in PLAYERS if p.id not in free_ids)
    assert c.get(f"/api/players/{next(iter(free_ids))}?market=PTS").status_code == 200
    r = c.get(f"/api/players/{other}?market=PTS")
    assert r.status_code == 403 and r.json()["detail"]["upgrade_required"]
    assert client().get(f"/api/players/{other}?market=PTS").status_code == 401   # gost
    assert c.get(f"/api/players/{next(iter(free_ids))}?market=AST").status_code == 403


def test_smart_picks_gating():
    g = client().get("/api/smart-picks?limit=500")
    assert len(g.json()) > 0 and all(x.get("locked") for x in g.json()) and not any(n in g.text for n in NAMES)
    c, _ = user_with_plan()
    rows = c.get("/api/smart-picks?limit=500").json()
    assert {x["smart_market"] for x in rows} == {"PTS"}
    assert len([x for x in rows if not x.get("locked")]) == 5
    c2, _ = user_with_plan("pro")
    rows = c2.get("/api/smart-picks?limit=500").json()
    assert {x["smart_market"] for x in rows} == {"PTS"} and not _locked(rows)
    c3, _ = user_with_plan("pro_plus")
    rows = c3.get("/api/smart-picks?limit=500").json()
    assert {x["smart_market"] for x in rows} == set(MARKETS) and not _locked(rows)


def test_value_and_top_props_are_gated():
    g = client()
    for url in ("/api/top-props?limit=50", "/api/value-props?min_edge=-100&limit=50"):
        r = g.get(url)
        assert r.status_code == 200 and not any(n in r.text for n in NAMES), url
    assert client().get("/api/top-props?market=AST").status_code == 403


def test_ai_chat_requires_pro_plus():
    assert client().post("/api/chat", json={"question": "hi"}).status_code == 401
    for plan in (None, "pro"):
        c, _ = user_with_plan(plan)
        r = c.post("/api/chat", json={"question": "hi"})
        assert r.status_code == 403 and r.json()["detail"]["required_plan"] == "pro_plus"
    c, _ = user_with_plan("pro_plus")
    r = c.post("/api/chat", json={"question": "hi"})
    assert r.status_code != 403 and r.status_code != 401      # prosao guard (AI kljuc nije podesen u testu)


def test_tracking_and_debug_are_admin_only():
    c, _ = user_with_plan("pro_plus")
    for u in ("/api/tracking/summary", "/api/tracking/picks", "/api/tracking/export.csv", "/api/debug/player/1"):
        assert client().get(u).status_code == 403 and c.get(u).status_code == 403, u


# ------------------------------------------------------------ planovi, istek, placanja
def test_plan_expiry_and_extension():
    c, email = user_with_plan()
    u = accounts.store.find(email)
    t0 = time.time()
    p1 = accounts.store.activate_plan(u["id"], "pro", "test", ref="a1", now=t0 - 40 * 86400)   # istekao prije ~10 dana
    me = c.get("/api/me").json()
    assert me["plan"]["key"] == "free" and me["plan"]["expired"] is True and me["plan"]["expires_at"]
    assert len(c.get("/api/projections?market=PTS").json()) == len(PLAYERS) and _locked(c.get("/api/projections?market=PTS").json())
    p2 = accounts.store.activate_plan(u["id"], "pro", "test", ref="a2", now=t0)       # istekao -> pocinje odmah
    assert abs(p2["period_start"] - t0) < 2
    p3 = accounts.store.activate_plan(u["id"], "pro", "test", ref="a3", now=t0)       # jos vazi -> nastavlja se na kraj
    assert p3["period_start"] == p2["period_end"] and p3["period_end"] > p2["period_end"]
    me = c.get("/api/me").json()
    assert me["plan"]["key"] == "pro" and me["plan"]["active"] and me["plan"]["days_left"] > 55
    p4 = accounts.store.activate_plan(u["id"], "pro_plus", "test", ref="a4", now=t0)  # drugi plan -> odmah
    assert abs(p4["period_start"] - t0) < 2
    assert len(me["payments"]) == 3 and c.get("/api/me").json()["plan"]["key"] == "pro_plus"


def test_payment_idempotent_and_amounts():
    c, email = user_with_plan()
    u = accounts.store.find(email)
    assert accounts.store.activate_plan(u["id"], "pro", "stripe", ref="cs_1")["amount_cents"] == 999
    assert accounts.store.activate_plan(u["id"], "pro", "stripe", ref="cs_1") is None
    assert accounts.store.activate_plan(u["id"], "pro_plus", "stripe", ref="cs_2")["amount_cents"] == 3999


def test_add_months_clamps_to_month_end():
    from datetime import datetime, timezone
    t = datetime(2026, 1, 31, 12, tzinfo=timezone.utc).timestamp()
    assert datetime.fromtimestamp(auth.add_months(t), timezone.utc).strftime("%Y-%m-%d") == "2026-02-28"
    t = datetime(2026, 12, 15, tzinfo=timezone.utc).timestamp()
    assert datetime.fromtimestamp(auth.add_months(t), timezone.utc).strftime("%Y-%m-%d") == "2027-01-15"


def _stripe_event(uid, plan, amount, status="paid", sid="cs_test_1", typ="checkout.session.completed"):
    return {"type": typ, "data": {"object": {"id": sid, "payment_status": status, "currency": "eur", "amount_total": amount,
                                              "client_reference_id": str(uid), "metadata": {"plan": plan, "user_id": str(uid)}}}}


def _post_webhook(c, event, secret="whsec_test", ts=None, sig=None):
    body = json.dumps(event).encode()
    ts = ts or int(time.time())
    sig = sig or hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return c.post("/api/billing/webhook", content=body, headers={"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"})


def test_stripe_webhook_activates_once():
    c, email = user_with_plan()
    u = accounts.store.find(email)
    r = _post_webhook(client(), _stripe_event(u["id"], "pro_plus", 3999, sid="cs_w1"))
    assert r.status_code == 200 and r.json()["outcome"] == "activated"
    assert c.get("/api/me").json()["plan"]["key"] == "pro_plus"
    assert _post_webhook(client(), _stripe_event(u["id"], "pro_plus", 3999, sid="cs_w1")).json()["outcome"] == "duplicate"
    assert len(c.get("/api/me").json()["payments"]) == 1


def test_stripe_webhook_rejects_bad_input():
    c, email = user_with_plan()
    u = accounts.store.find(email)
    ev = _stripe_event(u["id"], "pro", 999, sid="cs_bad")
    assert _post_webhook(client(), ev, secret="wrong").status_code == 400
    assert _post_webhook(client(), ev, ts=int(time.time()) - 4000).status_code == 400           # prestar
    assert _post_webhook(client(), ev, sig="0" * 64).status_code == 400
    assert _post_webhook(client(), _stripe_event(u["id"], "pro", 1, sid="cs_x")).json()["outcome"] == "amount/plan mismatch"
    assert _post_webhook(client(), _stripe_event(u["id"], "pro", 999, status="unpaid", sid="cs_y")).json()["outcome"] == "not paid"
    assert _post_webhook(client(), {"type": "customer.created", "data": {"object": {}}}).json()["outcome"] == "ignored"
    assert c.get("/api/me").json()["plan"]["key"] == "free"


def test_checkout_requires_login_and_config(monkeypatch):
    assert client().post("/api/billing/checkout", json={"plan": "pro"}).status_code == 401
    c, _ = user_with_plan()
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert c.post("/api/billing/checkout", json={"plan": "pro"}).status_code == 503
    assert c.get("/api/me").json()["billing_enabled"] is False
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    seen = {}

    class R:
        status_code = 200
        def json(self): return {"url": "https://checkout.stripe.test/s/1"}
    monkeypatch.setattr(billing.requests, "post", lambda url, data=None, auth=None, timeout=None: seen.update(data=data) or R())
    assert c.post("/api/billing/checkout", json={"plan": "pro_plus"}).json()["url"].startswith("https://checkout.stripe.test")
    assert seen["data"]["line_items[0][price_data][unit_amount]"] == "3999" and seen["data"]["metadata[plan]"] == "pro_plus"
    assert c.post("/api/billing/checkout", json={"plan": "free"}).status_code == 400


# ------------------------------------------------------------ admin
def admin_client():
    c = client()
    r = login(c, "AdminHoopEd8", ADMIN_PW)
    assert r.status_code == 200, r.text
    return c


def test_admin_login_sees_everything():
    c = admin_client()
    me = c.get("/api/me").json()
    assert me["plan"]["key"] == "admin" and me["user"]["is_admin"] and me["plan"]["expires_at"] is None
    for m in MARKETS:
        items = c.get(f"/api/projections?market={m}").json()
        assert len(items) == len(PLAYERS) and not _locked(items)
    assert c.get("/api/tracking/summary").status_code == 200
    r = c.post("/api/chat", json={"question": "hi"})
    assert r.status_code not in (401, 403)
    assert login(client(), "adminhoopedge8", ADMIN_PW).status_code == 401       # drugo ime = pogresno
    assert login(client(), "AdminHoopEd8", "wrong").status_code == 401


def test_admin_preview_simulates_plans():
    c = admin_client()
    assert c.post("/api/admin/preview", json={"plan": "free"}).json()["plan"]["key"] == "free"
    items = c.get("/api/projections?market=PTS").json()
    assert len([x for x in items if not x.get("locked")]) == 5
    assert c.get("/api/projections?market=AST").status_code == 403
    assert c.post("/api/chat", json={"question": "hi"}).status_code == 403
    assert c.post("/api/admin/preview", json={"plan": "pro"}).status_code == 200      # admin alati rade i u previewu
    assert not _locked(c.get("/api/projections?market=PTS").json())
    assert c.post("/api/admin/preview", json={"plan": "guest"}).json()["plan"]["key"] == "guest"
    assert len(_locked(c.get("/api/projections?market=PTS").json())) == len(PLAYERS)
    me = c.post("/api/admin/preview", json={"plan": "admin"}).json()
    assert me["plan"]["key"] == "admin" and me["preview"] is None
    assert c.post("/api/admin/preview", json={"plan": "bogus"}).status_code == 400


def test_non_admin_cannot_use_admin_endpoints():
    c, _ = user_with_plan("pro_plus")
    for path, body in (("/api/admin/preview", {"plan": "free"}), ("/api/admin/grant", {"identifier": "x", "plan": "pro"}),
                       ("/api/admin/verify", {"identifier": "x"}), ("/api/admin/revoke", {"identifier": "x"})):
        assert c.post(path, json=body).status_code == 403 and client().post(path, json=body).status_code == 403
    assert c.get("/api/admin/users").status_code == 403


def test_admin_grant_verify_revoke():
    a = admin_client()
    c = client()
    SENT.clear()
    c.post("/api/auth/register", json={"accept_terms": True, "email": "manual@example.com", "password": "Sup3r-secret!"})
    assert login(c, "manual@example.com").status_code == 403
    assert a.post("/api/admin/verify", json={"identifier": "manual@example.com"}).status_code == 200
    assert login(c, "manual@example.com").status_code == 200
    r = a.post("/api/admin/grant", json={"identifier": "manual@example.com", "plan": "pro_plus", "months": 2}).json()
    assert r["ok"] and c.get("/api/me").json()["plan"]["key"] == "pro_plus"
    assert any(u["email"] == "manual@example.com" and u["plan"] == "pro_plus" for u in a.get("/api/admin/users").json())
    a.post("/api/admin/revoke", json={"identifier": "manual@example.com"})
    assert c.get("/api/me").json()["plan"]["key"] == "free"


def test_password_hashing():
    h = auth.hash_password("correct horse")
    assert h.startswith("scrypt:") and "$" not in h and "%" not in h and " " not in h
    assert auth.verify_password("correct horse", h) and not auth.verify_password("wrong", h)
    assert not auth.verify_password("x", "garbage") and h != auth.hash_password("correct horse")


def test_plans_endpoint_and_account_page():
    plans = client().get("/api/plans").json()
    assert [p["id"] for p in plans] == ["free", "pro", "pro_plus"] and [p["price"] for p in plans] == [0, 9.99, 39.99]


# ------------------------------------------------------------ saglasnost, zaboravljena lozinka, upravljanje nalogom
def test_register_requires_terms_consent():
    c = client()
    r = c.post("/api/auth/register", json={"email": "noterms@example.com", "password": "Sup3r-secret!"})
    assert r.status_code == 400 and "Terms" in r.json()["detail"]["message"]
    r = c.post("/api/auth/register", json={"email": "noterms@example.com", "password": "Sup3r-secret!", "accept_terms": False})
    assert r.status_code == 400
    assert accounts.store.find("noterms@example.com") is None
    assert c.post("/api/auth/register", json={"email": "terms@example.com", "password": "Sup3r-secret!", "accept_terms": True}).status_code == 200
    assert accounts.store.find("terms@example.com")["terms_accepted_at"] > 0


def _reset_link(email):
    SENT.clear()
    r = client().post("/api/auth/forgot", json={"email": email})
    assert r.status_code == 200, r.text
    return r, (re.search(r"https://example\.test/\?reset=([\w-]+)", SENT[-1][2]).group(1) if SENT else None)


def test_forgot_password_is_generic_and_sends_only_to_existing():
    _, email = user_with_plan()
    r1, tok = _reset_link(email)
    assert tok and SENT[-1][0] == email and "Reset your" in SENT[-1][1]
    r2, none = _reset_link("ghost-user@example.com")
    assert none is None and not SENT
    assert r1.json() == r2.json() and "dev_link" not in r1.json()
    assert client().post("/api/auth/forgot", json={"email": "nonsense"}).status_code == 400


def test_reset_password_full_flow_and_single_use():
    c, email = user_with_plan()
    other = client(); assert login(other, email).status_code == 200            # druga sesija (drugi uredjaj)
    _, tok = _reset_link(email)
    n = client()
    assert n.post("/api/auth/reset", json={"token": tok, "password": "short"}).status_code == 400    # slaba lozinka ne trosi token
    r = n.post("/api/auth/reset", json={"token": tok, "password": "Brand-New-Pass-9"})
    assert r.status_code == 200
    assert n.post("/api/auth/reset", json={"token": tok, "password": "Another-Pass-10"}).status_code == 400   # jednokratan
    assert login(client(), email, "Sup3r-secret!").status_code == 401
    assert login(client(), email, "Brand-New-Pass-9").status_code == 200
    assert c.get("/api/me").json()["authenticated"] is False and other.get("/api/me").json()["authenticated"] is False  # svi uredjaji odjavljeni


def test_reset_token_expiry_and_garbage():
    _, email = user_with_plan()
    _, tok = _reset_link(email)
    u = accounts.store.find(email)
    accounts.store.db.execute("UPDATE users SET reset_expires=? WHERE id=?", (time.time() - 5, u["id"])); accounts.store.db.commit()
    r = client().post("/api/auth/reset", json={"token": tok, "password": "Brand-New-Pass-9"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_reset_token"
    assert client().post("/api/auth/reset", json={"token": "garbage", "password": "Brand-New-Pass-9"}).status_code == 400
    assert login(client(), email).status_code == 200                           # stara lozinka i dalje vazi


def test_reset_confirms_unverified_email_and_replaces_squatter_password():
    c = client()
    register_and_verify(c, "squat@example.com", "Attacker-pass-1")             # neverifikovan nalog s tudjom lozinkom
    assert login(c, "squat@example.com", "Attacker-pass-1").status_code == 403
    _, tok = _reset_link("squat@example.com")
    assert client().post("/api/auth/reset", json={"token": tok, "password": "Owner-pass-2345"}).status_code == 200
    assert login(c, "squat@example.com", "Attacker-pass-1").status_code == 401
    assert login(c, "squat@example.com", "Owner-pass-2345").status_code == 200  # vlasnik emaila je potvrdio posjedovanje


def test_admin_cannot_get_reset_link():
    assert accounts.store.new_reset_token(accounts.store.find("AdminHoopEd8")["id"]) is not None   # ne puca...
    u = accounts.store.find("AdminHoopEd8")
    assert u["reset_hash"] is None                                              # ...ali token se za admina ne pohranjuje
    assert client().post("/api/auth/reset", json={"token": "x" * 40, "password": "Brand-New-Pass-9"}).status_code == 400


def test_forgot_rate_limit():
    ip = "7.7.7.7"
    codes = [client(ip).post("/api/auth/forgot", json={"email": f"rl{i}@example.com"}).status_code for i in range(8)]
    assert codes[:6] == [200] * 6 and codes[-1] == 429


def test_change_password():
    c, email = user_with_plan()
    other = client(); login(other, email)
    assert c.post("/api/account/password", json={"current": "wrong-one-123", "password": "Brand-New-Pass-9"}).status_code == 400
    assert c.post("/api/account/password", json={"current": "Sup3r-secret!", "password": "short"}).status_code == 400
    assert c.post("/api/account/password", json={"current": "Sup3r-secret!", "password": "Sup3r-secret!"}).status_code == 400
    assert c.post("/api/account/password", json={"current": "Sup3r-secret!", "password": "Brand-New-Pass-9"}).status_code == 200
    assert c.get("/api/me").json()["authenticated"] is True                     # trenutna sesija ostaje
    assert other.get("/api/me").json()["authenticated"] is False                # ostali uredjaji odjavljeni
    assert login(client(), email, "Sup3r-secret!").status_code == 401 and login(client(), email, "Brand-New-Pass-9").status_code == 200
    assert client().post("/api/account/password", json={"current": "a", "password": "b"}).status_code == 401


def test_admin_cannot_change_or_delete_via_ui():
    a = admin_client()
    assert a.post("/api/account/password", json={"current": ADMIN_PW, "password": "Brand-New-Pass-9"}).status_code == 400
    assert a.post("/api/account/delete", json={"password": ADMIN_PW}).status_code == 400
    assert a.get("/api/me").json()["plan"]["key"] == "admin"


def test_logout_all_devices():
    c, email = user_with_plan()
    other = client(); login(other, email)
    assert c.post("/api/auth/logout-all").status_code == 200
    assert c.get("/api/me").json()["authenticated"] is False and other.get("/api/me").json()["authenticated"] is False
    assert client().post("/api/auth/logout-all").status_code == 401


def test_delete_account_keeps_payment_records_without_personal_data():
    c, email = user_with_plan("pro")
    u = accounts.store.find(email)
    assert c.post("/api/account/delete", json={"password": "wrong-pass-123"}).status_code == 400
    assert accounts.store.find(email) is not None
    assert c.post("/api/account/delete", json={"password": "Sup3r-secret!"}).status_code == 200
    assert accounts.store.find(email) is None and login(client(), email).status_code == 401
    assert c.get("/api/me").json()["authenticated"] is False
    rows = accounts.store.db.execute("SELECT * FROM payments WHERE user_id=?", (u["id"],)).fetchall()
    assert len(rows) == 1 and "email" not in rows[0].keys()                      # zapis o placanju ostaje, bez emaila
    c2 = client(); register_and_verify(c2, email); c2.get  # isti email se moze ponovo registrovati


def test_dev_links_only_when_enabled_no_smtp_and_loopback(monkeypatch):
    local = TestClient(main.app, client=("127.0.0.1", 50000))                  # isti racunar, bez proxy zaglavlja
    body = lambda e: {"email": e, "password": "Sup3r-secret!", "accept_terms": True}
    assert "dev_link" not in local.post("/api/auth/register", json=body("dev0@example.com")).json()      # zadano: iskljuceno
    monkeypatch.setenv("HOOPEDGE_DEV_SHOW_LINKS", "1")
    r = local.post("/api/auth/register", json=body("dev1@example.com")).json()
    assert "dev_link" in r
    path = r["dev_link"].replace("https://example.test", "")
    assert local.get(path, follow_redirects=False).headers["location"] == "/?verified=1"                 # link zaista radi
    assert "dev_link" in local.post("/api/auth/forgot", json={"email": "dev1@example.com"}).json()
    # isto podesavanje na serveru: udaljeni klijent, klijent iza proxyja ili pravi SMTP -> NIKAD link u odgovoru
    remote = TestClient(main.app, client=("203.0.113.9", 50000))
    assert "dev_link" not in remote.post("/api/auth/forgot", json={"email": "dev1@example.com"}).json()
    assert "dev_link" not in remote.post("/api/auth/register", json=body("dev3@example.com")).json()
    proxied = TestClient(main.app, client=("127.0.0.1", 50000), headers={"X-Forwarded-For": "198.51.100.7"})
    assert "dev_link" not in proxied.post("/api/auth/forgot", json={"email": "dev1@example.com"}).json()
    assert "dev_link" not in proxied.post("/api/auth/register", json=body("dev4@example.com")).json()
    monkeypatch.setattr(mailer, "configured", lambda: True)
    assert "dev_link" not in local.post("/api/auth/register", json=body("dev2@example.com")).json()
    assert "dev_link" not in local.post("/api/auth/forgot", json={"email": "dev1@example.com"}).json()


def test_terms_and_privacy_pages_and_old_db_migration(tmp_path):
    c = client()
    for p in ("/terms", "/privacy"):
        r = c.get(p)
        assert r.status_code == 200 and "DRAFT" in r.text
    import sqlite3
    old = tmp_path / "old.db"
    db = sqlite3.connect(old)
    db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE COLLATE NOCASE, username TEXT UNIQUE COLLATE NOCASE,"
                     "password_hash TEXT NOT NULL, email_verified INTEGER NOT NULL DEFAULT 0, verify_hash TEXT, verify_expires REAL,"
                     "plan TEXT NOT NULL DEFAULT 'free', plan_paid_at REAL, plan_expires_at REAL, is_admin INTEGER NOT NULL DEFAULT 0,"
                     "created_at REAL NOT NULL, last_login REAL); INSERT INTO users(email,password_hash,created_at) VALUES('x@y.com','h',1);")
    db.commit(); db.close()
    st = auth.Store(str(old))                                                  # ne smije puknuti, stari podaci ostaju
    assert st.find("x@y.com") is not None
    assert {"reset_hash", "reset_expires", "terms_accepted_at"} <= {r["name"] for r in st.db.execute("PRAGMA table_info(users)")}
