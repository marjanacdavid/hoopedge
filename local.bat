@echo off
rem ============================================================================
rem  LOKALNO TESTIRANJE (samo na tvom racunaru). NE kopiraj ovaj fajl na server.
rem  run_windows.bat ga ucitava automatski ako postoji.
rem  Prijava: korisnik AdminHoopEd8 + tvoja lozinka. U fajlu je samo HASH lozinke, ne lozinka.
rem ============================================================================
set "HOOPEDGE_ADMIN_USER=AdminHoopEd8"
set "HOOPEDGE_ADMIN_PASSWORD_HASH=scrypt:16384:8:1:ZDuxHAZgMHC2pRMrgJeBcA:6JGyaIXky36llh697Wh9qkdWqLfuOL1bJS_2RoOwLio"
set "HOOPEDGE_BASE_URL=http://127.0.0.1:8000"
rem DEV rezim: kad nema SMTP-a, linkovi za potvrdu emaila i reset lozinke se prikazuju NA EKRANU
rem (umjesto da se salju emailom), pa mozes testirati registraciju i "Forgot password" bez email servera.
set "HOOPEDGE_DEV_SHOW_LINKS=1"
