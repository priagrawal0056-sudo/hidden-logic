@echo off
REM ===== Hidden Logic - daily autopilot launcher for Task Scheduler =====
REM This runs the full pipeline once. Point Windows Task Scheduler at THIS file.
REM It activates conda (so the right Python/libraries are used), moves into the project
REM folder, runs autopilot, and writes a dated log you can check later.

REM --- adjust ONLY if your paths differ ---
set "PROJECT=C:\Users\USER\Downloads\MIND GLITCH\MIND GLITCH"
set "CONDA=C:\Users\USER\anaconda3\Scripts\activate.bat"

cd /d "%PROJECT%"

REM make a logs folder and a timestamped log FIRST so startup diagnostics are captured
if not exist "logs" mkdir "logs"
set "STAMP=%date:~-4%-%date:~4,2%-%date:~7,2%_%time:~0,2%-%time:~3,2%"
set "STAMP=%STAMP: =0%"
set "LOG=logs\autopilot_%STAMP%.log"

echo ===== autopilot start %date% %time% ===== >> "%LOG%"

REM activate conda base env if it exists (so 'python' has all your packages)
if exist "%CONDA%" (
  call "%CONDA%" base
) else (
  echo WARNING: conda not found at "%CONDA%" - using 'python' from PATH instead >> "%LOG%"
)

REM Record which interpreter is actually running. A scheduler using a DIFFERENT python than
REM the one where your packages are installed is the #1 cause of the silent
REM "ModuleNotFoundError: No module named 'google'" failure (zero videos, no alert).
echo --- python in use --- >> "%LOG%"
where python >> "%LOG%" 2>&1
python -c "import sys; print('executable:', sys.executable)" >> "%LOG%" 2>&1
python -c "import google, googleapiclient, requests, edge_tts; print('deps OK')" >> "%LOG%" 2>&1
if errorlevel 1 echo DEPENDENCY CHECK FAILED: required packages missing in this env - run "pip install -r requirements.txt" here. (autopilot still runs and will Discord-alert on import failure.) >> "%LOG%"

python -u autopilot.py >> "%LOG%" 2>&1
echo ===== autopilot end %date% %time% ===== >> "%LOG%"
