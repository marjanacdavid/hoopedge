"""Korisnici, sesije, planovi i placanja (SQLite, bez dodatnih paketa).

- Lozinke: scrypt (stdlib) s nasumicnim saltom; u bazi nikad otvoreni tekst.
- Sesije: nasumicni token u HttpOnly cookieju; u bazi samo SHA-256 tog tokena.
- Planovi: free / pro / pro_plus (+ admin). Placeni plan vrijedi do `plan_expires_at`, poslije se
  automatski racuna kao free (nema cron posla).
- Placanja: jedna funkcija `activate_plan` koju poziva bilo koji pruzalac (Stripe webhook, rucna dodjela...).
"""
import base64
import calendar
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

ALL_MARKETS = ("PTS", "AST", "REB", "3PM", "PA")

PLANS = {
    "free":     {"label": "Free", "price_cents": 0,    "markets": ("PTS",),    "limit": 5,    "ai": False},
    "pro":      {"label": "Pro",  "price_cents": 999,  "markets": ("PTS",),    "limit": None, "ai": False},
    "pro_plus": {"label": "Pro+", "price_cents": 3999, "markets": ALL_MARKETS, "limit": None, "ai": True},
}
GUEST = {"label": "Guest", "price_cents": 0, "markets": ("PTS",), "limit": 0, "ai": False}
ADMIN = {"label": "Admin", "price_cents": 0, "markets": ALL_MARKETS, "limit": None, "ai": True}
PREVIEW_KEYS = ("admin", "guest", "free", "pro", "pro_plus")   # sta admin moze "glumiti" radi testiranja
PAID_PLANS = ("pro", "pro_plus")

SESSION_DAYS = 30
VERIFY_HOURS = 24
RESET_HOURS = 1

_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")
_COMMON_PW = {"password", "password1", "12345678", "123456789", "qwertyui", "11111111", "iloveyou", "basketball", "hoopedge1"}


# ---------------------------------------------------------------- lozinke
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    """Format: scrypt:n:r:p:salt:hash (samo znakovi [A-Za-z0-9_:-], pa je siguran u env fajlu i systemd-u)."""
    n, r, p = 2 ** 14, 8, 1
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt:{n}:{r}:{p}:{_b64(salt)}:{_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, want = stored.split(":")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(dk, _unb64(want))
    except Exception:
        return False


_DUMMY = None


def dummy_hash() -> str:
    """Za izjednacavanje vremena kad korisnik ne postoji (da se ne vidi koji emailovi postoje)."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(secrets.token_hex(8))
    return _DUMMY


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---------------------------------------------------------------- validacija
def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(email) and len(email) <= 254 and bool(_EMAIL_RE.match(email))


def password_problem(password: str, email: str = "") -> str:
    """Vraca tekst problema ili prazan string ako je lozinka ok."""
    pw = str(password or "")
    if len(pw) < 8:
        return "Password must be at least 8 characters."
    if len(pw) > 128:
        return "Password is too long (max 128 characters)."
    if pw.lower() in _COMMON_PW or len(set(pw)) < 4:
        return "That password is too easy to guess."
    local = email.split("@")[0] if email else ""
    if local and len(local) >= 4 and pw.lower() == local.lower():
        return "Password must not be the same as your email."
    return ""


# ---------------------------------------------------------------- datumi
def add_months(ts: float, months: int = 1) -> float:
    """Kalendarski mjesec (23.10. -> 23.11.), s ogranicenjem na zadnji dan mjeseca."""
    d = datetime.fromtimestamp(ts, timezone.utc)
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return d.replace(year=y, month=m, day=day).timestamp()


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


# ---------------------------------------------------------------- rate limit
class RateLimiter:
    """Klizni prozor u memoriji: dovoljno za jedan proces."""

    def __init__(self):
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self.hits) > 20000:   # povremeno cisti stare kljuceve
                for k in [k for k, v in self.hits.items() if not v or now - v[-1] > 86400]:
                    self.hits.pop(k, None)
            return True


# ---------------------------------------------------------------- baza
class Store:
    def __init__(self, path=None):
        self.path = path or os.getenv("HOOPEDGE_USERS_DB", "data/users.db")
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT UNIQUE COLLATE NOCASE,
              username TEXT UNIQUE COLLATE NOCASE,
              password_hash TEXT NOT NULL,
              email_verified INTEGER NOT NULL DEFAULT 0,
              verify_hash TEXT, verify_expires REAL,
              plan TEXT NOT NULL DEFAULT 'free',
              plan_paid_at REAL, plan_expires_at REAL,
              is_admin INTEGER NOT NULL DEFAULT 0,
              created_at REAL NOT NULL, last_login REAL);
            CREATE TABLE IF NOT EXISTS sessions(
              token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
              created_at REAL NOT NULL, expires_at REAL NOT NULL, preview_plan TEXT);
            CREATE TABLE IF NOT EXISTS payments(
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
              plan TEXT NOT NULL, amount_cents INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'eur',
              provider TEXT NOT NULL, provider_ref TEXT,
              paid_at REAL NOT NULL, period_start REAL NOT NULL, period_end REAL NOT NULL,
              UNIQUE(provider, provider_ref));
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
            """)
            # migracija: starije baze dobiju nove kolone (reset lozinke, saglasnost s uslovima)
            have = {r["name"] for r in self.db.execute("PRAGMA table_info(users)")}
            for col, typ in (("reset_hash", "TEXT"), ("reset_expires", "REAL"), ("terms_accepted_at", "REAL")):
                if col not in have:
                    self.db.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
            self.db.commit()

    # ---- korisnici
    def _one(self, sql, args=()):
        with self.lock:
            r = self.db.execute(sql, args).fetchone()
            return dict(r) if r else None

    def get_user(self, user_id):
        return self._one("SELECT * FROM users WHERE id=?", (user_id,))

    def find(self, identifier: str):
        """Email ili korisnicko ime (bez obzira na velika/mala slova)."""
        ident = str(identifier or "").strip()
        if not ident:
            return None
        return self._one("SELECT * FROM users WHERE email=? OR username=?", (normalize_email(ident), ident))

    def create_user(self, email: str, password: str):
        """-> (user_id, verify_token). Email mora biti vec normalizovan."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO users(email,password_hash,verify_hash,verify_expires,created_at,terms_accepted_at) VALUES(?,?,?,?,?,?)",
                (email, hash_password(password), _sha(token), now + VERIFY_HOURS * 3600, now, now))
            self.db.commit()
            return cur.lastrowid, token

    def reset_unverified(self, user_id: int, password: str):
        """Ponovna registracija neverifikovanog emaila: nova lozinka (zadnji pobjeđuje) + novi token."""
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute(
                "UPDATE users SET password_hash=?, verify_hash=?, verify_expires=? WHERE id=? AND email_verified=0",
                (hash_password(password), _sha(token), time.time() + VERIFY_HOURS * 3600, user_id))
            self.db.commit()
        return token

    def new_verify_token(self, user_id: int):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute("UPDATE users SET verify_hash=?, verify_expires=? WHERE id=? AND email_verified=0",
                            (_sha(token), time.time() + VERIFY_HOURS * 3600, user_id))
            self.db.commit()
        return token

    def verify_email(self, token: str):
        """Jednokratni token. -> user_id ili None."""
        if not token or len(token) > 200:
            return None
        with self.lock:
            r = self.db.execute("SELECT id, verify_expires FROM users WHERE verify_hash=? AND email_verified=0",
                                (_sha(token),)).fetchone()
            if not r or (r["verify_expires"] or 0) < time.time():
                return None
            self.db.execute("UPDATE users SET email_verified=1, verify_hash=NULL, verify_expires=NULL WHERE id=?", (r["id"],))
            self.db.commit()
            return r["id"]

    def mark_verified(self, user_id: int):
        with self.lock:
            self.db.execute("UPDATE users SET email_verified=1, verify_hash=NULL, verify_expires=NULL WHERE id=?", (user_id,))
            self.db.commit()

    def touch_login(self, user_id: int):
        with self.lock:
            self.db.execute("UPDATE users SET last_login=? WHERE id=?", (time.time(), user_id))
            self.db.commit()

    def ensure_admin(self, username: str, password_hash: str):
        """Napravi/azuriraj admin nalog (bez emaila, uvijek verifikovan). Promjena hasha u env-u mijenja lozinku."""
        with self.lock:
            r = self.db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            if r:
                self.db.execute("UPDATE users SET password_hash=?, is_admin=1, email_verified=1 WHERE id=?", (password_hash, r["id"]))
            else:
                self.db.execute("INSERT INTO users(username,password_hash,email_verified,is_admin,plan,created_at) VALUES(?,?,1,1,'pro_plus',?)",
                                (username, password_hash, time.time()))
            self.db.commit()

    def list_users(self, limit=200):
        with self.lock:
            rows = self.db.execute("SELECT id,email,username,email_verified,plan,plan_paid_at,plan_expires_at,is_admin,created_at,last_login "
                                   "FROM users ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    # ---- sesije
    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock:
            self.db.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
            self.db.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                            (_sha(token), user_id, now, now + SESSION_DAYS * 86400))
            self.db.commit()
        return token

    def session_user(self, token: str):
        """-> (user dict, preview_plan) ili (None, None)."""
        if not token or len(token) > 200:
            return None, None
        with self.lock:
            r = self.db.execute("SELECT user_id, preview_plan, expires_at FROM sessions WHERE token_hash=?", (_sha(token),)).fetchone()
            if not r or r["expires_at"] < time.time():
                return None, None
            u = self.db.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone()
            return (dict(u), r["preview_plan"]) if u else (None, None)

    def delete_session(self, token: str):
        if token:
            with self.lock:
                self.db.execute("DELETE FROM sessions WHERE token_hash=?", (_sha(token),))
                self.db.commit()

    def set_preview(self, token: str, plan):
        with self.lock:
            self.db.execute("UPDATE sessions SET preview_plan=? WHERE token_hash=?", (plan, _sha(token)))
            self.db.commit()

    def delete_sessions(self, user_id: int, keep_token=None):
        """Odjavi korisnika sa svih uredjaja (osim, opciono, trenutne sesije)."""
        with self.lock:
            if keep_token:
                self.db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user_id, _sha(keep_token)))
            else:
                self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self.db.commit()

    # ---- zaboravljena / promjena lozinke
    def new_reset_token(self, user_id: int):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute("UPDATE users SET reset_hash=?, reset_expires=? WHERE id=? AND is_admin=0",
                            (_sha(token), time.time() + RESET_HOURS * 3600, user_id))
            self.db.commit()
        return token

    def consume_reset(self, token: str, password: str):
        """Jednokratni token: postavi novu lozinku, potvrdi email (primio je link), odjavi sve uredjaje. -> user_id | None."""
        if not token or len(token) > 200:
            return None
        with self.lock:
            r = self.db.execute("SELECT id, reset_expires FROM users WHERE reset_hash=? AND is_admin=0", (_sha(token),)).fetchone()
            if not r or (r["reset_expires"] or 0) < time.time():
                return None
            self.db.execute("UPDATE users SET password_hash=?, reset_hash=NULL, reset_expires=NULL, email_verified=1, "
                            "verify_hash=NULL, verify_expires=NULL WHERE id=?", (hash_password(password), r["id"]))
            self.db.execute("DELETE FROM sessions WHERE user_id=?", (r["id"],))
            self.db.commit()
            return r["id"]

    def set_password(self, user_id: int, password: str, keep_token=None):
        with self.lock:
            self.db.execute("UPDATE users SET password_hash=?, reset_hash=NULL, reset_expires=NULL WHERE id=?",
                            (hash_password(password), user_id))
            self.db.commit()
        self.delete_sessions(user_id, keep_token)

    def delete_user(self, user_id: int):
        """Brise nalog i sesije. Zapisi o placanjima ostaju (bez licnih podataka) zbog knjigovodstva."""
        with self.lock:
            self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self.db.execute("DELETE FROM users WHERE id=? AND is_admin=0", (user_id,))
            self.db.commit()

    # ---- planovi i placanja
    def activate_plan(self, user_id: int, plan: str, provider: str, ref=None, amount_cents=None,
                      currency="eur", months=1, now=None):
        """Aktivira/produzava placeni plan. Idempotentno po (provider, ref).

        - isti plan jos vazi  -> novi mjesec se dodaje NA KRAJ postojeceg perioda
        - drugi plan / istekao -> pocinje odmah (ostatak starog plana se ne prenosi)
        Vraca dict placanja ili None ako je to placanje vec obradjeno.
        """
        if plan not in PAID_PLANS:
            raise ValueError("unknown plan")
        now = now or time.time()
        amount = PLANS[plan]["price_cents"] * months if amount_cents is None else int(amount_cents)
        with self.lock:
            if ref is not None and self.db.execute("SELECT 1 FROM payments WHERE provider=? AND provider_ref=?", (provider, str(ref))).fetchone():
                return None
            u = self.db.execute("SELECT plan, plan_expires_at FROM users WHERE id=?", (user_id,)).fetchone()
            if not u:
                raise ValueError("unknown user")
            start = now
            if u["plan"] == plan and (u["plan_expires_at"] or 0) > now:
                start = u["plan_expires_at"]
            end = add_months(start, months)
            self.db.execute("UPDATE users SET plan=?, plan_paid_at=?, plan_expires_at=? WHERE id=?", (plan, now, end, user_id))
            self.db.execute("INSERT INTO payments(user_id,plan,amount_cents,currency,provider,provider_ref,paid_at,period_start,period_end) "
                            "VALUES(?,?,?,?,?,?,?,?,?)",
                            (user_id, plan, amount, currency, provider, None if ref is None else str(ref), now, start, end))
            self.db.commit()
            return {"plan": plan, "paid_at": now, "period_start": start, "period_end": end, "amount_cents": amount}

    def revoke_plan(self, user_id: int):
        with self.lock:
            self.db.execute("UPDATE users SET plan='free', plan_expires_at=NULL WHERE id=?", (user_id,))
            self.db.commit()

    def payments(self, user_id: int, limit=20):
        with self.lock:
            rows = self.db.execute("SELECT plan,amount_cents,currency,provider,paid_at,period_start,period_end FROM payments "
                                   "WHERE user_id=? ORDER BY paid_at DESC, id DESC LIMIT ?", (user_id, limit)).fetchall()
            return [dict(r) for r in rows]


# ---------------------------------------------------------------- efektivni plan
def plan_status(user, now=None):
    """Efektivni plan korisnika: istekao placeni plan se racuna kao free."""
    now = now or time.time()
    plan = user.get("plan") or "free"
    exp = user.get("plan_expires_at")
    if plan in PAID_PLANS and exp and exp > now:
        return {"key": plan, "active": True, "expired": False, "paid_at": user.get("plan_paid_at"), "expires_at": exp,
                "days_left": max(0, int((exp - now) // 86400) + (1 if (exp - now) % 86400 else 0))}
    expired = plan in PAID_PLANS
    return {"key": "free", "active": False, "expired": expired, "paid_at": user.get("plan_paid_at") if expired else None,
            "expires_at": exp if expired else None, "days_left": 0}


def resolve(user, preview=None, now=None):
    """-> (kljuc plana, entitlements). Admin moze 'glumiti' drugi plan (preview) radi testiranja."""
    if user is None:
        return "guest", GUEST
    if user.get("is_admin"):
        if preview in ("guest", "free", "pro", "pro_plus"):
            return preview, (GUEST if preview == "guest" else PLANS[preview])
        return "admin", ADMIN
    key = plan_status(user, now)["key"]
    return key, PLANS[key]


def required_plan_for_market(market: str) -> str:
    return "pro_plus" if market not in PLANS["pro"]["markets"] else "pro"


def _main():
    """python -m app.auth hash   -> ispise hash lozinke za HOOPEDGE_ADMIN_PASSWORD_HASH."""
    import getpass
    if len(sys.argv) > 1 and sys.argv[1] == "hash":
        pw = getpass.getpass("Admin password: ")
        if getpass.getpass("Repeat: ") != pw:
            sys.exit("Passwords do not match.")
        print("HOOPEDGE_ADMIN_PASSWORD_HASH=" + hash_password(pw))
    else:
        print("usage: python -m app.auth hash")


if __name__ == "__main__":
    _main()
