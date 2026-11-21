@echo off
setlocal
echo === Helpdesk Agent ===
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from python.org
    pause & exit /b 1
)

REM Check Docker
docker info >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker not running. Open Docker Desktop and wait for it to start.
    pause & exit /b 1
)

REM Check Ollama
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo ERROR: Ollama not running. Open a new terminal and run: ollama serve
    pause & exit /b 1
)

REM Create venv if needed
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 ( echo ERROR: venv creation failed & pause & exit /b 1 )
)

REM Install deps
echo Installing dependencies...
.venv\Scripts\pip install -e ".[dev]" -q
if errorlevel 1 ( echo ERROR: pip install failed & pause & exit /b 1 )

REM Create .env if missing
if not exist .env (
    echo Creating .env from .env.example...
    copy .env.example .env >nul
)

REM Start Postgres
echo Starting Postgres...
docker compose up -d --wait
if errorlevel 1 ( echo ERROR: Docker failed & pause & exit /b 1 )

REM Seed database
echo Seeding database...
.venv\Scripts\python -m helpdesk.db.seed
if errorlevel 1 ( echo ERROR: Seeding failed & pause & exit /b 1 )

REM Ingest policy docs
echo Ingesting policy documents...
.venv\Scripts\python -m helpdesk.rag.ingest
if errorlevel 1 ( echo ERROR: Ingestion failed & pause & exit /b 1 )

REM Start chat
set AS=%1
if "%AS%"=="" set AS=E003
echo.
echo === Starting chat (signed in as %AS%) ===
echo Type /quit to exit.
echo.
.venv\Scripts\python -m helpdesk.cli --as %AS%
pause
