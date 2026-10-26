"""API za naloge: registracija s potvrdom emaila, prijava, /api/me, naplata i admin alati."""
import json
import logging
import os
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import auth, billing, mailer
from .auth import PLANS, PREVIEW_KEYS, RateLimiter, Store, iso, plan_status, resolve

log = logging.getLogger("hoopedge.accounts")

COOKIE = "he_session"
store = Store()
limiter = RateLimiter()
router = APIRouter()


# ---------------------------------------------------------------- kontekst zahtjeva
class Ctx:
    def __init__(self, user, preview, token):
        self.user, self.preview, self.token = user, preview, token
        self.plan_key, self.ent = resolve(user, preview)

    @property
    def is_admin(self):
        return bool(self.user and self.user.get("is_admin"))


def get_ctx(request: Request) -> Ctx:
    token = request.cookies.get(COOKIE, "")
    user, preview = store.session_user(token)
    return Ctx(user, preview, token if user else "")


def client_ip(request: Request) -> str:
    if os.getenv("HOOPEDGE_TRUST_PROXY") == "1":   # samo iza nginx-a koji postavlja X-Forwarded-For
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _host(h: str) -> str:
    return (h or "").split(":")[0].lower()


def check_origin(request: Request):
    """Odbij cross-site POST (uz SameSite=Lax cookie): Origin mora biti isti host."""
    origin = request.headers.get("origin")
    if origin:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        if _host(urlparse(origin).netloc) != _host(host):
            raise HTTPException(403, detail={"message": "Cross-origin request blocked."})


def link_base(request: Request):
    """Osnova linka u emailu. Host header se NE smije slijepo vjerovati kad se salju pravi mailovi."""
    env = os.getenv("HOOPEDGE_BASE_URL", "").rstrip("/")
    if env:
        return env
    if mailer.configured():
        log.error("HOOPEDGE_BASE_URL nije postavljen; verifikacioni email nije poslan (sigurnosna zastita).")
        return None
    return str(request.base_url).rstrip("/")


def dev_links_on(request: Request = None) -> bool:
    """Lokalno testiranje: umjesto emaila pokazi link na ekranu.

    Dvije zastite da se ovo ne pretvori u preuzimanje tudjih naloga ako se lokalna podesavanja
    slucajno kopiraju na server: (1) radi samo uz HOOPEDGE_DEV_SHOW_LINKS=1 i BEZ podesenog SMTP-a;
    (2) link se vraca samo zahtjevima sa ISTOG racunara (loopback, bez proxy zaglavlja)."""
    if os.getenv("HOOPEDGE_DEV_SHOW_LINKS") != "1" or mailer.configured():
        return False
    if request is None:
        return True
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        return False
    return not any(h in request.headers for h in ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded"))


def fail(status, message, **extra):
    return HTTPException(status, detail={"message": message, **extra})


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


# ---------------------------------------------------------------- modeli
class RegisterIn(BaseModel):
    email: str
    password: str
    accept_terms: bool = False


class LoginIn(BaseModel):
    identifier: str
    password: str


class EmailIn(BaseModel):
    email: str


class PlanIn(BaseModel):
    plan: str


class GrantIn(BaseModel):
    identifier: str
    plan: str
    months: int = 1


class IdentIn(BaseModel):
    identifier: str


class ForgotIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    password: str


class ChangePwIn(BaseModel):
    current: str
    password: str


class DeleteIn(BaseModel):
    password: str


# ---------------------------------------------------------------- /api/me
def me_payload(ctx: Ctx) -> dict:
    base = {"billing_enabled": billing.enabled(),
            "plans": [{"id": k, "label": v["label"], "price_cents": v["price_cents"]} for k, v in PLANS.items()]}
    if not ctx.user:
        return {**base, "authenticated": False, "user": None,
                "plan": {"key": "guest", "label": "Guest", "active": False, "expired": False, "paid_at": None,
                         "expires_at": None, "days_left": 0, "is_paid": False},
                "entitlements": {"markets": list(ctx.ent["markets"]), "limit": ctx.ent["limit"], "ai": ctx.ent["ai"]},
                "preview": None, "payments": []}
    u = ctx.user
    st = plan_status(u)
    if ctx.plan_key == "admin":
        plan = {"key": "admin", "label": "Admin", "active": True, "expired": False, "paid_at": None,
                "expires_at": None, "days_left": None, "is_paid": False}
    else:
        key = ctx.plan_key
        if u.get("is_admin"):   # admin u preview modu: prikazi simulirani plan
            plan = {"key": key, "label": ctx.ent["label"], "active": key in ("pro", "pro_plus"), "expired": False,
                    "paid_at": None, "expires_at": None, "days_left": None, "is_paid": key in ("pro", "pro_plus")}
        else:
            plan = {"key": key, "label": PLANS[key]["label"], "active": st["active"], "expired": st["expired"],
                    "paid_at": iso(st["paid_at"]), "expires_at": iso(st["expires_at"]), "days_left": st["days_left"],
                    "is_paid": key in ("pro", "pro_plus")}
    return {**base, "authenticated": True,
            "user": {"id": u["id"], "email": u["email"], "username": u["username"], "is_admin": bool(u["is_admin"]),
                     "email_verified": bool(u["email_verified"]), "created_at": iso(u["created_at"])},
            "plan": plan,
            "entitlements": {"markets": list(ctx.ent["markets"]), "limit": ctx.ent["limit"], "ai": ctx.ent["ai"]},
            "preview": ctx.preview if ctx.is_admin and ctx.preview in PREVIEW_KEYS else None,
            "payments": [{"plan": p["plan"], "label": PLANS[p["plan"]]["label"], "amount_cents": p["amount_cents"],
                          "currency": p["currency"], "provider": p["provider"], "paid_at": iso(p["paid_at"]),
                          "period_start": iso(p["period_start"]), "period_end": iso(p["period_end"])}
                         for p in store.payments(u["id"])]}


@router.get("/api/me")
def me(request: Request):
    return me_payload(get_ctx(request))


# ---------------------------------------------------------------- registracija / potvrda
def _send_verification(email: str, token: str, base: str):
    link = f"{base}/api/auth/verify?token={token}"
    subject, text, html = mailer.verification_email(link)
    mailer.send_mail(email, subject, text, html)


GENERIC_REGISTER = ("If this email can be registered, we sent a confirmation link to it. "
                    "Open it within 24 hours to activate your account. Already registered? Just sign in.")


@router.post("/api/auth/register")
def register(body: RegisterIn, request: Request, bg: BackgroundTasks):
    check_origin(request)
    ip = client_ip(request)
    email = auth.normalize_email(body.email)
    if not auth.valid_email(email):
        raise fail(400, "Please enter a valid email address.")
    problem = auth.password_problem(body.password, email)
    if problem:
        raise fail(400, problem)
    if not body.accept_terms:
        raise fail(400, "Please accept the Terms of Use and Privacy Policy to create an account.")
    if not limiter.allow(f"reg-ip:{ip}", 8, 3600) or not limiter.allow(f"reg-mail:{email}", 3, 3600):
        raise fail(429, "Too many attempts. Please try again later.")
    existing = store.find(email)
    token = None
    if existing is None:
        _, token = store.create_user(email, body.password)
    elif not existing["email_verified"]:
        token = store.reset_unverified(existing["id"], body.password)
    # vec registrovan i verifikovan: ne radimo nista (isti odgovor, da se ne otkriva ko ima nalog)
    out = {"ok": True, "message": GENERIC_REGISTER}
    if token:
        base = link_base(request)
        if base:
            bg.add_task(_send_verification, email, token, base)
            if dev_links_on(request):
                out["dev_link"] = f"{base}/api/auth/verify?token={token}"
    return out


@router.post("/api/auth/resend")
def resend(body: EmailIn, request: Request, bg: BackgroundTasks):
    check_origin(request)
    email = auth.normalize_email(body.email)
    if not auth.valid_email(email):
        raise fail(400, "Please enter a valid email address.")
    if not limiter.allow(f"resend-ip:{client_ip(request)}", 6, 3600) or not limiter.allow(f"resend-mail:{email}", 3, 3600):
        raise fail(429, "Too many attempts. Please try again later.")
    u = store.find(email)
    out = {"ok": True, "message": "If that account is waiting for confirmation, we sent a new link."}
    if u and u["email"] and not u["email_verified"]:
        base = link_base(request)
        if base:
            token = store.new_verify_token(u["id"])
            bg.add_task(_send_verification, email, token, base)
            if dev_links_on(request):
                out["dev_link"] = f"{base}/api/auth/verify?token={token}"
    return out


@router.get("/api/auth/verify")
def verify(token: str, request: Request):
    if not limiter.allow(f"verify-ip:{client_ip(request)}", 30, 3600):
        return RedirectResponse("/?verify=invalid", status_code=303)
    uid = store.verify_email(token)
    return RedirectResponse("/?verified=1" if uid else "/?verify=invalid", status_code=303)


# ---------------------------------------------------------------- prijava
@router.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    check_origin(request)
    ip = client_ip(request)
    ident = (body.identifier or "").strip()[:254]
    if not limiter.allow(f"login-ip:{ip}", 20, 900) or not limiter.allow(f"login-id:{ident.lower()}", 8, 900):
        raise fail(429, "Too many sign-in attempts. Please wait a few minutes.")
    u = store.find(ident)
    ok = auth.verify_password(body.password or "", u["password_hash"] if u else auth.dummy_hash()) and u is not None
    if not ok:
        raise fail(401, "Wrong email/username or password.")
    if not u["email_verified"]:
        raise fail(403, "Please confirm your email first. Check your inbox for the link.", code="email_not_verified")
    store.touch_login(u["id"])
    token = store.create_session(u["id"])
    response.set_cookie(COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=_secure(request), path="/")
    return me_payload(Ctx(store.get_user(u["id"]), None, token))


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    check_origin(request)
    store.delete_session(request.cookies.get(COOKIE, ""))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


# ---------------------------------------------------------------- zaboravljena lozinka
def _send_reset(email: str, link: str):
    subject, text, html = mailer.reset_email(link)
    mailer.send_mail(email, subject, text, html)


@router.post("/api/auth/forgot")
def forgot(body: ForgotIn, request: Request, bg: BackgroundTasks):
    """Uvijek isti odgovor (ne otkriva ko ima nalog). Link vazi 1 sat i jednokratan je."""
    check_origin(request)
    email = auth.normalize_email(body.email)
    if not auth.valid_email(email):
        raise fail(400, "Please enter a valid email address.")
    if not limiter.allow(f"forgot-ip:{client_ip(request)}", 6, 3600) or not limiter.allow(f"forgot-mail:{email}", 3, 3600):
        raise fail(429, "Too many attempts. Please try again later.")
    out = {"ok": True, "message": "If an account exists for that email, we sent a password reset link. It is valid for 1 hour."}
    u = store.find(email)
    if u and u["email"] and not u["is_admin"]:
        base = link_base(request)
        if base:
            link = f"{base}/?reset={store.new_reset_token(u['id'])}"
            bg.add_task(_send_reset, email, link)
            if dev_links_on(request):
                out["dev_link"] = link
    return out


@router.post("/api/auth/reset")
def reset_password(body: ResetIn, request: Request):
    check_origin(request)
    if not limiter.allow(f"reset-ip:{client_ip(request)}", 20, 3600):
        raise fail(429, "Too many attempts. Please try again later.")
    problem = auth.password_problem(body.password)   # prije trosenja tokena, da slaba lozinka ne "spali" link
    if problem:
        raise fail(400, problem)
    if store.consume_reset(body.token, body.password) is None:
        raise fail(400, "This reset link is invalid or has expired. Please request a new one.", code="bad_reset_token")
    return {"ok": True, "message": "Password changed. Sign in with your new password."}


# ---------------------------------------------------------------- upravljanje nalogom
def _require_user(request: Request) -> Ctx:
    ctx = get_ctx(request)
    if not ctx.user:
        raise fail(401, "Sign in to continue.", login_required=True)
    return ctx


def _no_admin(ctx: Ctx, what: str):
    if ctx.user.get("is_admin"):
        raise fail(400, f"The admin account cannot {what} here. The admin password is set on the server (HOOPEDGE_ADMIN_PASSWORD_HASH).")


@router.post("/api/account/password")
def change_password(body: ChangePwIn, request: Request):
    check_origin(request)
    ctx = _require_user(request)
    _no_admin(ctx, "change its password")
    if not limiter.allow(f"chpw:{ctx.user['id']}", 8, 900):
        raise fail(429, "Too many attempts. Please wait a few minutes.")
    if not auth.verify_password(body.current or "", ctx.user["password_hash"]):
        raise fail(400, "Your current password is wrong.")
    problem = auth.password_problem(body.password, ctx.user.get("email") or "")
    if problem:
        raise fail(400, problem)
    if body.password == body.current:
        raise fail(400, "The new password must be different from the current one.")
    store.set_password(ctx.user["id"], body.password, keep_token=ctx.token)
    return {"ok": True, "message": "Password changed. Your other devices were signed out."}


@router.post("/api/auth/logout-all")
def logout_all(request: Request, response: Response):
    check_origin(request)
    ctx = _require_user(request)
    store.delete_sessions(ctx.user["id"])
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/api/account/delete")
def delete_account(body: DeleteIn, request: Request, response: Response):
    check_origin(request)
    ctx = _require_user(request)
    _no_admin(ctx, "be deleted")
    if not limiter.allow(f"delacct:{ctx.user['id']}", 5, 900):
        raise fail(429, "Too many attempts. Please wait a few minutes.")
    if not auth.verify_password(body.password or "", ctx.user["password_hash"]):
        raise fail(400, "Wrong password.")
    store.delete_user(ctx.user["id"])
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


# ---------------------------------------------------------------- naplata
@router.post("/api/billing/checkout")
def checkout(body: PlanIn, request: Request):
    check_origin(request)
    ctx = get_ctx(request)
    if not ctx.user:
        raise fail(401, "Sign in to upgrade.", login_required=True)
    if body.plan not in auth.PAID_PLANS:
        raise fail(400, "Unknown plan.")
    if not billing.enabled():
        raise fail(503, "Online payments are not enabled yet. Contact support to activate a plan.")
    try:
        url = billing.create_checkout(ctx.user, body.plan, link_base(request) or str(request.base_url).rstrip("/"))
    except RuntimeError as e:
        raise fail(502, str(e))
    return {"url": url}


@router.post("/api/billing/webhook")
async def webhook(request: Request):
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise fail(503, "Webhook not configured.")
    payload = await request.body()
    if not billing.verify_signature(payload, request.headers.get("stripe-signature", ""), secret):
        raise fail(400, "Invalid signature.")
    try:
        event = json.loads(payload)
    except Exception:
        raise fail(400, "Invalid payload.")
    outcome = await run_in_threadpool(billing.handle_event, store, event)
    log.info("Stripe event %s -> %s", event.get("type"), outcome)
    return {"received": True, "outcome": outcome}


# ---------------------------------------------------------------- admin alati
def require_admin(request: Request) -> Ctx:
    ctx = get_ctx(request)
    if not ctx.is_admin:
        raise fail(403, "Admin only.")
    return ctx


@router.post("/api/admin/preview")
def admin_preview(body: PlanIn, request: Request):
    """Admin 'glumi' plan (guest/free/pro/pro_plus) da vidi tacno sta korisnik vidi. 'admin' = nazad na sve."""
    check_origin(request)
    ctx = require_admin(request)
    if body.plan not in PREVIEW_KEYS:
        raise fail(400, "Unknown preview plan.")
    store.set_preview(ctx.token, None if body.plan == "admin" else body.plan)
    return me_payload(get_ctx(request))


@router.post("/api/admin/grant")
def admin_grant(body: GrantIn, request: Request):
    check_origin(request)
    require_admin(request)
    u = store.find(body.identifier)
    if not u:
        raise fail(404, "User not found.")
    if body.plan not in auth.PAID_PLANS:
        raise fail(400, "Plan must be pro or pro_plus.")
    if not 1 <= body.months <= 12:
        raise fail(400, "Months must be 1-12.")
    res = store.activate_plan(u["id"], body.plan, provider="manual", ref=None, amount_cents=0, months=body.months)
    return {"ok": True, "plan": body.plan, "valid_until": iso(res["period_end"])}


@router.post("/api/admin/revoke")
def admin_revoke(body: IdentIn, request: Request):
    check_origin(request)
    require_admin(request)
    u = store.find(body.identifier)
    if not u:
        raise fail(404, "User not found.")
    store.revoke_plan(u["id"])
    return {"ok": True}


@router.post("/api/admin/verify")
def admin_verify(body: IdentIn, request: Request):
    """Rucna potvrda emaila (kad SMTP jos nije podesen)."""
    check_origin(request)
    require_admin(request)
    u = store.find(body.identifier)
    if not u:
        raise fail(404, "User not found.")
    store.mark_verified(u["id"])
    return {"ok": True}


@router.get("/api/admin/users")
def admin_users(request: Request):
    require_admin(request)
    return [{"id": u["id"], "email": u["email"], "username": u["username"], "verified": bool(u["email_verified"]),
             "plan": plan_status(u)["key"], "valid_until": iso(u["plan_expires_at"]), "is_admin": bool(u["is_admin"]),
             "created_at": iso(u["created_at"]), "last_login": iso(u["last_login"])} for u in store.list_users()]


# ---------------------------------------------------------------- admin nalog iz env-a
def seed_admin() -> bool:
    user = os.getenv("HOOPEDGE_ADMIN_USER", "AdminHoopEd8").strip()
    h = os.getenv("HOOPEDGE_ADMIN_PASSWORD_HASH", "").strip()
    pw = os.getenv("HOOPEDGE_ADMIN_PASSWORD", "")
    if not h and pw:
        h = auth.hash_password(pw)
    if not h:
        log.warning("Admin nalog nije podesen (postavi HOOPEDGE_ADMIN_PASSWORD_HASH).")
        return False
    if not h.startswith("scrypt:"):
        log.error("HOOPEDGE_ADMIN_PASSWORD_HASH nije ispravan (generisi ga sa: python -m app.auth hash).")
        return False
    store.ensure_admin(user, h)
    log.info("Admin nalog '%s' je spreman.", user)
    return True
