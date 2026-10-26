# HOOPEDGE: nalozi, planovi, naplata

## 0. Lokalno testiranje na svom računaru (prvo ovo)

1. Raspakuj ZIP preko svog foldera aplikacije (prepiše se samo ono što je u ZIP-u; `keys.bat` ostaje).
2. Dvoklik na **run_windows.bat** (Linux/Mac: `./run_local.sh`). Automatski učitava `keys.bat` (Gemini/Odds ključevi)
   i novi `local.bat` (admin nalog + dev režim). Otvori http://127.0.0.1:8000
3. Klikni **Sign in** i upiši:
   - korisnik: `AdminHoopEd8`
   - lozinka: ona koju si mi dao
4. Admin vidi sve. Na stranici **Account** (/account) → *Admin tools* → **Preview as** (Guest / Free / Pro / Pro+) vidiš
   tačno šta vidi korisnik tog plana; na dashboardu stoji žuti baner ADMIN PREVIEW s dugmetom Exit preview.

**Registracija i "Forgot password" bez email servera:** u `local.bat` je uključen DEV režim. Umjesto slanja emaila,
link za potvrdu / reset lozinke pojavi se **na ekranu** (žuti okvir "DEV MODE"). Klikni ga i nastavi. Dev linkovi se prikazuju
samo zahtjevima sa istog računara i nikad ako je podešen SMTP, pa ne mogu procuriti na server.

Baza naloga je `data/users.db` (samo na tvom računaru). **Ne kopiraj** `data/users.db`, `local.bat` ni `run_local.sh` na server.
Brisanje `data/users.db` vraća sve na početak (admin se ponovo napravi pri startu).

## 1. Admin nalog na serveru (kad dođe vrijeme)
Dodaj u `/etc/hoopedge.env` pa `sudo systemctl restart hoopedge`:
```
HOOPEDGE_ADMIN_USER=AdminHoopEd8
HOOPEDGE_ADMIN_PASSWORD_HASH=scrypt:16384:8:1:ZDuxHAZgMHC2pRMrgJeBcA:6JGyaIXky36llh697Wh9qkdWqLfuOL1bJS_2RoOwLio
```
To je hash lozinke, ne lozinka. Nova lozinka: `python -m app.auth hash` (sa aktivnim venv-om), pa promijeni hash i restartuj.
Admin lozinka se ne mijenja kroz sajt, nego samo ovim putem.

## 2. Email (potvrda registracije i reset lozinke)
```
HOOPEDGE_BASE_URL=https://tvoj-domen.com      # tačna adresa sajta, bez / na kraju
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tvoj.email@gmail.com
SMTP_PASSWORD=app-lozinka-od-16-znakova
SMTP_FROM=tvoj.email@gmail.com
```
- Bez SMTP-a emailovi se ne šalju; linkovi se upišu u log (`journalctl -u hoopedge -n 50`), a admin može ručno potvrditi
  nalog (Account → Admin tools → *Confirm email*).
- Iza nginx-a dodaj `HOOPEDGE_TRUST_PROXY=1` (ograničenja pokušaja gledaju pravu IP adresu korisnika).

## 3. Naplata (opciono)
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```
Webhook: `https://tvoj-domen.com/api/billing/webhook`, događaj `checkout.session.completed`. Bez ključeva su dugmad za
kupovinu isključena, a planove dodjeljuješ ručno (Account → Admin tools → *Grant*).
Drugi pružalac naplate: njegov webhook samo poziva `store.activate_plan(user_id, plan, provider, ref)`.

## Planovi (app/auth.py → PLANS)
| Plan | Cijena | Tržišta | Igrači | AI |
|---|---|---|---|---|
| Guest (bez naloga) | - | - | sve zamagljeno | ne |
| Free | 0 | PTS | prvih 5 | ne |
| Pro | 9.99 EUR / mj | PTS | svi | ne |
| Pro+ | 39.99 EUR / mj | PTS, AST, REB, 3PM, P+A | svi | da |
| Admin | - | sve | svi | da |

## Šta korisnik može sam (stranica /account)
- vidi plan, status, kada je plaćeno i do kada važi, historiju plaćanja
- mijenja lozinku (ostali uređaji se odjave), odjavljuje se sa svih uređaja
- briše nalog (potvrda lozinkom; zapisi o plaćanjima ostaju bez ličnih podataka)
- "Forgot password?" na prijavi šalje link koji važi 1 sat i radi jednom; nakon promjene svi uređaji se odjave

## Uslovi i privatnost
`/terms` i `/privacy` su **NACRTI** sa poljima u uglastim zagradama `[ZAMIJENI]` (naziv/adresa, politika povrata, PDV,
pružaoci usluga...). Prije naplate ih popuni i daj da pregleda pravnik. Registracija traži saglasnost (18+, uslovi, privatnost).

## Testovi
`python -m pytest tests -q`
