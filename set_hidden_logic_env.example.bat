@echo off
REM ============================================================================
REM  Hidden Logic - secrets as ENVIRONMENT VARIABLES (more secure than config.json)
REM
REM  HOW TO USE:
REM   1. Copy this file to "set_hidden_logic_env.bat" and paste your REAL keys below.
REM   2. Keep that .bat private (it is git-ignored).
REM   3. Run it ONCE to set the variables permanently for your user account:
REM         set_hidden_logic_env.bat
REM   4. Then you can REMOVE these same keys from config.json - the pipeline reads
REM      the HL_* variables automatically (config_loader.py), and env vars win over
REM      the file. (Leave the NON-secret settings in config.json.)
REM
REM  config_loader.py recognizes exactly these names:
REM    HL_GEMINI_API_KEY, HL_PEXELS_API_KEY, HL_PIXABAY_API_KEY,
REM    HL_ALERT_WEBHOOK_URL, HL_ELEVENLABS_API_KEY (single),
REM    HL_ELEVENLABS_API_KEYS (comma-separated pool, read by tts.py)
REM
REM  'setx' writes them permanently to your user account. Open a NEW terminal /
REM  restart Task Scheduler afterwards so it picks them up.
REM ============================================================================

setx HL_GEMINI_API_KEY      "PASTE_GEMINI_KEY_HERE"
setx HL_PEXELS_API_KEY      "PASTE_PEXELS_KEY_HERE"
setx HL_PIXABAY_API_KEY     "PASTE_PIXABAY_KEY_HERE"
setx HL_ALERT_WEBHOOK_URL   "PASTE_DISCORD_WEBHOOK_URL_HERE"

REM Optional - ElevenLabs premium voice (pool of keys, comma-separated, no spaces):
setx HL_ELEVENLABS_API_KEYS "PASTE_EL_KEY_1,PASTE_EL_KEY_2"

echo.
echo Done. Open a NEW terminal (and restart Task Scheduler) so the variables take effect.
echo Then remove the same keys from config.json.
