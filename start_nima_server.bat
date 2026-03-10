@echo off
setlocal

REM NIMA server startup script
REM - Assumes Python + dependencies are already installed
REM - app.py loads .env automatically via python-dotenv

set PROJECT_DIR=C:\ai-manim
cd /d "%PROJECT_DIR%" || (echo [ERR] Cannot cd to %PROJECT_DIR% & exit /b 1)

echo [NIMA] Starting Flask server from %CD%
echo [NIMA] If this is the first run, install deps:  pip install -r requirements.txt

REM Prefer the Python launcher if available
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 app.py
) else (
  python app.py
)
