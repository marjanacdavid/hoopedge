@echo off
cd /d %~dp0
if not exist app\main.py goto badfolder
if not exist requirements.txt goto badfolder
rem Kljucevi (Gemini / Odds) se citaju iz keys.bat (kopiraj keys.example.bat u keys.bat i upisi svoje)
if exist keys.bat call keys.bat
rem Lokalno testiranje naloga (admin + dev linkovi): local.bat
if exist local.bat call local.bat
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
python -m pip install -r requirements.txt
if errorlevel 1 goto piperr
start "" http://127.0.0.1:8000
python -m uvicorn app.main:app --reload --port 8000
pause
exit /b 0

:badfolder
echo.
echo GRESKA: ovo nije kompletan folder aplikacije - nedostaje app\main.py ili requirements.txt.
echo Raspakuj CIJELI hoopedge-ai-complete.zip u prazan folder i pokreni run_windows.bat iz njega.
echo.
pause
exit /b 1

:piperr
echo.
echo GRESKA: instalacija paketa nije uspjela. Provjeri internet i da imas Python 3.9 ili noviji sa python.org.
echo.
pause
exit /b 1
