@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
python bootstrap.py
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
