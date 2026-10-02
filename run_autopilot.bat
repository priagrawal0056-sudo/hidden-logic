@echo off
setlocal EnableExtensions
REM Hidden Logic local scheduler entrypoint.
REM This file is location-independent: it runs from the repository folder and never
REM assumes a particular Windows username or Conda installation.

set "PROJECT=%~dp0"
pushd "%PROJECT%" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Cannot open project folder "%PROJECT%".
  exit /b 1
)

if not exist "logs" mkdir "logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "STAMP=%%I"
if not defined STAMP set "STAMP=run_%RANDOM%"
set "LOG=logs\autopilot_%STAMP%.log"

echo ===== autopilot start %date% %time% ===== > "%LOG%"
echo Project: %PROJECT% >> "%LOG%"

REM Use a project-local virtualenv when available. HL_PYTHON can select a different
REM python.exe for users who keep their environment elsewhere (including Conda).
set "PYTHON=python"
if exist "%PROJECT%.venv\Scripts\python.exe" set "PYTHON=%PROJECT%.venv\Scripts\python.exe"
if defined HL_PYTHON set "PYTHON=%HL_PYTHON%"
echo Python command: "%PYTHON%" >> "%LOG%"
where python >> "%LOG%" 2>&1
"%PYTHON%" -c "import sys; print('Python executable:', sys.executable); print('Python version:', sys.version)" >> "%LOG%" 2>&1
if errorlevel 1 goto python_failed

REM Fail before the long run if required packages, ffmpeg, or generation keys are missing.
"%PYTHON%" -c "import requests, edge_tts, google.auth.transport.requests, google_auth_oauthlib.flow, googleapiclient.discovery; print('Python dependencies OK')" >> "%LOG%" 2>&1
if errorlevel 1 goto dependencies_failed
where ffmpeg >> "%LOG%" 2>&1
if errorlevel 1 goto ffmpeg_failed
where ffprobe >> "%LOG%" 2>&1
if errorlevel 1 goto ffmpeg_failed
"%PYTHON%" -c "import config_loader,sys; c=config_loader.load_config(); ok=lambda x: bool(x) and not str(x).strip().startswith('PASTE_'); missing=[]; missing += [] if (str(c.get('llm_provider','gemini')).strip().lower() == 'claude_code' or ok(c.get('gemini_api_key'))) else ['HL_GEMINI_API_KEY / gemini_api_key']; missing += [] if (ok(c.get('pexels_api_key')) or ok(c.get('pixabay_api_key'))) else ['HL_PEXELS_API_KEY or HL_PIXABAY_API_KEY']; print('Generation API credentials OK' if not missing else 'Missing generation credentials: ' + ', '.join(missing)); sys.exit(bool(missing))" >> "%LOG%" 2>&1
if errorlevel 1 goto credentials_failed

if /I "%~1"=="--dry-run" goto dry_run

echo Starting full autopilot... >> "%LOG%"
"%PYTHON%" -u autopilot.py >> "%LOG%" 2>&1
set "RUN_EXIT=%ERRORLEVEL%"
goto run_finished

:dry_run
echo Building one test video without uploading... >> "%LOG%"
"%PYTHON%" -u run_daily.py --hero --dry-run --count 1 >> "%LOG%" 2>&1
set "RUN_EXIT=%ERRORLEVEL%"

:run_finished
echo ===== autopilot end %date% %time% (exit %RUN_EXIT%) ===== >> "%LOG%"
echo Autopilot finished with exit code %RUN_EXIT%. Log: %PROJECT%%LOG%
popd
exit /b %RUN_EXIT%

:python_failed
echo ERROR: Python could not start. Set HL_PYTHON to the full path of python.exe, or create .venv in this folder. >> "%LOG%"
echo Python could not start. See "%PROJECT%%LOG%".
set "RUN_EXIT=1"
goto failed

:dependencies_failed
echo ERROR: Required Python packages are missing from the selected interpreter. >> "%LOG%"
echo Install requirements with: "%PYTHON%" -m pip install -r requirements.txt >> "%LOG%"
echo Dependencies are missing. Install requirements; see "%PROJECT%%LOG%".
set "RUN_EXIT=1"
goto failed

:ffmpeg_failed
echo ERROR: ffmpeg or ffprobe was not found on PATH. Install a full ffmpeg build and reopen Task Scheduler. >> "%LOG%"
echo ffmpeg/ffprobe was not found on PATH. See "%PROJECT%%LOG%".
set "RUN_EXIT=1"
goto failed

:credentials_failed
echo ERROR: Gemini and either Pexels or Pixabay credentials are required to generate videos. >> "%LOG%"
echo Configure API keys in config.json or the HL_* environment variables. >> "%LOG%"
echo Required generation keys are missing. See "%PROJECT%%LOG%".
set "RUN_EXIT=1"
goto failed

:failed
echo ===== autopilot stopped during preflight (exit %RUN_EXIT%) ===== >> "%LOG%"
popd
exit /b %RUN_EXIT%
