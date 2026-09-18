"""
tts.py - v3 (robust)
Free text-to-speech via Microsoft Edge voices (edge-tts).
Generates an MP3 voiceover plus word-level timings for the animated captions.

Robustness:
  - retries, then falls back to a different voice
  - if the service returns audio but no WordBoundary events (happens with some
    edge-tts versions/voices), word timings are ESTIMATED from the real audio
    duration, weighted by word length, so captions still sync well
"""
import asyncio
import json
import os
import random
import re
import subprocess

import edge_tts
from assemble import _ffmpeg


def _pause_removals(words, silences, threshold=.65, keep=.32):
    """Trim only detected silence inside a long measured inter-word gap."""
    cuts = []
    for left, right in zip(words, words[1:]):
        low, high = float(left['end']) + .06, float(right['start']) - .06
        for start, end in silences:
            a, b = max(low, start), min(high, end)
            if b - a > threshold:
                cuts.append((a + keep/2, b - keep/2))
    return cuts


def tighten_long_pauses(voice_path, timings_path):
    """Keep ordinary breaths. Re-map captions after trimming isolated long silence."""
    with open(timings_path, encoding='utf-8') as source:
        words = json.load(source)
    detection = subprocess.run([_ffmpeg(), '-hide_banner', '-i', voice_path, '-af',
                                'silencedetect=noise=-45dB:d=0.65', '-f', 'null', '-'],
                               capture_output=True, text=True, check=True)
    silences, start = [], None
    for event, value in re.findall(r'silence_(start|end): ([\d.]+)', detection.stderr):
        if event == 'start':
            start = float(value)
        elif start is not None:
            silences.append((start, float(value)))
            start = None
    cuts = _pause_removals(words, silences)
    if cuts:
        segments, previous = [], 0.0
        for i, (a, b) in enumerate(cuts):
            segments.append(f'[0:a]atrim=start={previous}:end={a},asetpts=PTS-STARTPTS[p{i}]')
            previous = b
        segments.append(f'[0:a]atrim=start={previous},asetpts=PTS-STARTPTS[p{len(cuts)}]')
        segments.append(''.join(f'[p{i}]' for i in range(len(cuts)+1)) + f'concat=n={len(cuts)+1}:v=0:a=1[out]')
        temporary = voice_path + '.tightened.mp3'
        subprocess.run([_ffmpeg(), '-v', 'error', '-y', '-i', voice_path, '-filter_complex',
                        ';'.join(segments), '-map', '[out]', '-c:a', 'libmp3lame', '-b:a', '192k', temporary], check=True)
        for word in words:
            for key in ('start', 'end'):
                old = word[key]
                word[key] = round(old - sum(b-a for a,b in cuts if b <= old), 6)
        os.replace(temporary, voice_path)
        with open(timings_path, 'w', encoding='utf-8') as output:
            json.dump(words, output, indent=2)
    with open(voice_path + '.pause-edits.json', 'w', encoding='utf-8') as output:
        json.dump({'removed_intervals':cuts, 'removed_seconds':sum(b-a for a,b in cuts)}, output, indent=2)
    return words


# ---------------------------------------------------------------- prosody
_REVEAL_CUES = ("but ", "until ", "then ", "except ", "yet ", "still ",
                "here's ", "turns out", "nobody ", "somehow ")


def _add_prosody(text: str) -> str:
    """Keep the writer's punctuation; do not manufacture suspense pauses."""
    return re.sub(r"\s+", " ", text).strip()

# Microsoft's newer "Multilingual" neural voices are dramatically more natural
# than the classic ones (breathing, intonation, less robotic cadence).
DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
VOICE_POOL = [
    "en-US-AndrewMultilingualNeural",  # warm, very human - the standout (weighted)
    "en-US-AndrewMultilingualNeural",
    "en-US-BrianMultilingualNeural",   # friendly, easygoing
    "en-GB-RyanNeural",                # British, warm, suits football
]
FALLBACK_VOICE = "en-US-AndrewNeural"


def pick_voice():
    return DEFAULT_VOICE


async def _synth(text: str, mp3_path: str, voice: str):
    """Stream TTS to file. Returns (n_audio_bytes, word_boundaries)."""
    text = _add_prosody(text)
    rate = _TTS_CFG.get("edge_voice_rate", "+0%")
    communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words = []
    n_bytes = 0
    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
                n_bytes += len(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "word": chunk["text"],
                    "start": chunk["offset"] / 10_000_000.0,
                    "end": (chunk["offset"] + chunk["duration"]) / 10_000_000.0,
                })
    return n_bytes, words


def _coalesce_measured_words(words):
    """Keep a zero-width ASR token with its adjacent measured phrase, never guess a cut."""
    result, pending = [], []
    for word in words:
        if pending:
            if abs(word['start'] - pending[-1]['end']) > .001 or len(pending) > 3:
                raise ValueError('Unresolved zero-width word timing')
        if word['end'] == word['start']:
            if re.search(r'[.!?]$', word['word']):
                raise ValueError('Unresolved sentence-ending timing')
            pending.append(word)
            continue
        if pending:
            word = {**word, 'word': ' '.join(w['word'] for w in pending + [word]),
                    'start': pending[0]['start'], 'timing_granularity': 'measured_phrase'}
            pending = []
        result.append(word)
    if pending:
        raise ValueError('Unresolved trailing word timing')
    return result


def _align_with_whisper(text: str, mp3_path: str):
    """If faster-whisper is installed, get TRUE word timestamps from the audio.
    This makes captions frame-accurate. Optional: pip install faster-whisper"""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    from assemble import sentence_segments
    report = {'expected': text, 'attempts': [], 'passed': False}
    primary = _TTS_CFG.get('alignment_model', 'base.en')
    fallback = _TTS_CFG.get('alignment_fallback_model', 'small.en')
    names = list(dict.fromkeys(n for n in (primary, fallback) if n))
    for name in names:
        try:
            model = WhisperModel(name, device="cpu", compute_type="int8")
            for beam in ((1, 5) if name == primary else (5,)):
                segments, _ = model.transcribe(mp3_path, word_timestamps=True, language="en",
                                               vad_filter=True, condition_on_previous_text=False,
                                               beam_size=beam, hallucination_silence_threshold=0.5)
                words = [{"word": w.word.strip(), "start": round(w.start, 3),
                          "end": round(w.end, 3)}
                         for seg in segments for w in (seg.words or [])]
                attempt = {'model': name, 'beam': beam, 'words': words}
                report['attempts'].append(attempt)
                try:
                    words = _coalesce_measured_words(words)
                    sentence_segments(words, text)
                except ValueError as exc:
                    attempt['reason'] = str(exc)
                    print(f"[tts] alignment rejected ({name}, beam={beam}): {exc}")
                    continue
                report['passed'] = True
                with open(mp3_path + '.alignment.json', 'w', encoding='utf-8') as output:
                    json.dump(report, output, indent=2)
                print(f"[tts] measured alignment used ({len(words)} words; transcript checked)")
                return words
        except Exception as exc:
            report['attempts'].append({'model': name, 'error_type': type(exc).__name__})
            print(f"[tts] measured alignment unavailable ({name}: {type(exc).__name__})")
    with open(mp3_path + '.alignment.json', 'w', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    return None


def _speech_end(mp3_path: str, total: float) -> float:
    """Detect where speech actually ends (trailing silence caused caption drift)."""
    out = subprocess.run(
        ["ffmpeg", "-i", mp3_path, "-af", "silencedetect=noise=-35dB:d=0.25",
         "-f", "null", "-"], capture_output=True, text=True)
    starts = re.findall(r"silence_start: ([\d.]+)", out.stderr)
    ends = re.findall(r"silence_end: ([\d.]+)", out.stderr)
    if starts:
        last_start = float(starts[-1])
        # speech ends at last_start if that final silence runs to (or near) EOF
        if not ends or float(ends[-1]) < last_start or total - float(ends[-1]) < 0.3:
            return last_start
    return total


SPEECH_SPEED = 1.0  # post-processing tempo (1.0 = off); gentle, not rushed
VOICE_PITCH = 1.0    # neutral - do NOT deepen. Deepening was part of the "menacing" feel.


def _apply_speed(mp3_path: str, factor: float):
    """Speed up AND trim leading silence: the first word must hit instantly.
    Dead air at 0:00 is the #1 cause of swipe-aways."""
    sped = mp3_path + ".sped.mp3"
    af = "silenceremove=start_periods=1:start_threshold=-40dB:start_silence=0.03:detection=peak"
    tempo = factor
    if abs(VOICE_PITCH - 1.0) >= 0.01:
        # pitch down without changing speed: resample trick + tempo compensation
        af += f",aresample=48000,asetrate={int(48000*VOICE_PITCH)},aresample=48000"
        tempo = factor / VOICE_PITCH
    if abs(tempo - 1.0) >= 0.01:
        af += f",atempo={tempo:.4f}"
    # normalize loudness so no video comes out quiet/scary - consistent broadcast level
    af += ",loudnorm=I=-15:TP=-1.5:LRA=11"
    subprocess.run([_ffmpeg(), "-y", "-v", "error", "-i", mp3_path,
                    "-filter:a", af, sped], check=True)
    
    import time
    for _ in range(10):
        try:
            os.replace(sped, mp3_path)
            break
        except PermissionError:
            time.sleep(0.2)
    else:
        # If it still fails, try removing first then renaming
        try:
            os.remove(mp3_path)
            os.rename(sped, mp3_path)
        except Exception:
            # Fallback if both fail
            pass

def _audio_duration(mp3_path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", mp3_path],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def _syllables(word: str) -> float:
    """Rough syllable count - speech duration tracks syllables far better than raw characters,
    so caption timing estimated this way drifts much less when whisper isn't available."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 1.0
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and n > 1:  # silent trailing e
        n -= 1
    return float(max(1, n))


def _estimate_timings(text: str, duration: float) -> list[dict]:
    """No word-level timestamps available: spread words across the real audio duration,
    weighted by SYLLABLE COUNT (a much better proxy for spoken length than characters) plus
    pause weight after punctuation. Whisper alignment is strongly preferred; this only runs
    when whisper is unavailable, and keeps drift small enough that captions still track."""
    tokens = [t for t in text.split() if t.strip()]
    if not tokens:
        return []
    LEAD, TAIL = 0.15, 0.30  # small silences at start/end of TTS audio
    speakable = max(0.5, duration - LEAD - TAIL)
    weights = []
    for t in tokens:
        w = _syllables(t) + 0.5   # base: syllables (+0.5 floor so 1-syllable words aren't too fast)
        if re.search(r"[.!?]$", t):
            w += 2.5   # sentence-end pause
        elif re.search(r"[,;:]$", t):
            w += 1.2
        weights.append(w)
    total = sum(weights)
    words, t_cursor = [], LEAD
    for tok, w in zip(tokens, weights):
        d = speakable * (w / total)
        clean = re.sub(r"[^\w'-]", "", tok)
        words.append({
            "word": clean or tok,
            "estimated": True,
            "start": round(t_cursor, 3),
            "end": round(t_cursor + d * 0.9, 3),  # word ends just before its pause
        })
        t_cursor += d
    return words


GEMINI_TTS_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
GEMINI_TTS_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]
GEMINI_VOICES = ["Puck", "Aoede", "Kore"]  # warm, upbeat, friendly (not deep/gravelly)
TTS_LIST_URL = "https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=200"
_tts_models = None
_EL_WARNED = False   # one-time flag so the "no ElevenLabs keys" note prints once per run

# ----- ElevenLabs (premium, most natural voice - the biggest retention lever) -----
# Key comes from env HL_ELEVENLABS_API_KEY or ELEVENLABS_API_KEY, or config "elevenlabs_api_key".
# Never hardcode the key. Voice + model are configurable; defaults are a deep narrator voice.
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVENLABS_DEFAULT_VOICE = "NOpBlnGInO9m6vDvFkFC"
ELEVENLABS_DEFAULT_MODEL = "eleven_v3"


def _elevenlabs_keys_doc():
    """ElevenLabs keys are read as a POOL by _elevenlabs_keys(): env HL_ELEVENLABS_API_KEYS
    (comma-separated) and/or config 'elevenlabs_api_keys' (list), plus single-key fallbacks
    HL_ELEVENLABS_API_KEY / ELEVENLABS_API_KEY / config 'elevenlabs_api_key'."""
    pass


# config injected by synthesize() so this module stays import-light
_TTS_CFG: dict = {}

# Keys that have failed (401 bad-key or 429 out-of-credits) THIS run - skipped on retry so we
# don't keep hammering a dead key. Cleared each process start.
_EL_DEAD_KEYS: set = set()
# Where the per-video rotation cursor is persisted, so each video uses a DIFFERENT key across
# runs (not just within one process). Small JSON next to the script.
_EL_ROTATION_FILE = "el_key_rotation.json"


def _elevenlabs_keys() -> list:
    """Return the pool of ElevenLabs keys, in order. Sources (merged, de-duped, order kept):
      - env HL_ELEVENLABS_API_KEYS or ELEVENLABS_API_KEYS  (comma/space separated)
      - config "elevenlabs_api_keys"  (a JSON list)
      - the single-key fallbacks (env HL_ELEVENLABS_API_KEY / ELEVENLABS_API_KEY / config)
    Never hardcode keys; these all come from env or config.json."""
    keys: list = []
    for env_name in ("HL_ELEVENLABS_API_KEYS", "ELEVENLABS_API_KEYS"):
        raw = os.getenv(env_name, "")
        if raw:
            for part in raw.replace(",", " ").split():
                part = part.strip()
                if part:
                    keys.append(part)
    cfg_list = _TTS_CFG.get("elevenlabs_api_keys")
    if isinstance(cfg_list, list):
        keys.extend([str(k).strip() for k in cfg_list if str(k).strip()])
    # single-key backward compatibility
    single = (os.getenv("HL_ELEVENLABS_API_KEY")
              or os.getenv("ELEVENLABS_API_KEY")
              or _TTS_CFG.get("elevenlabs_api_key", "") or "")
    if single:
        keys.append(single.strip())
    # de-dupe preserving order
    seen = set()
    pool = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            pool.append(k)
    return pool


def _el_next_start_index(pool_size: int) -> int:
    """Advance and persist the rotation cursor so EACH video starts on a different key."""
    if pool_size <= 0:
        return 0
    idx = 0
    try:
        if os.path.exists(_EL_ROTATION_FILE):
            with open(_EL_ROTATION_FILE, encoding="utf-8") as f:
                idx = int(json.load(f).get("next", 0))
    except Exception:
        idx = 0
    start = idx % pool_size
    try:
        with open(_EL_ROTATION_FILE, "w", encoding="utf-8") as f:
            json.dump({"next": (start + 1) % pool_size}, f)
    except Exception:
        pass
    return start


def _try_elevenlabs(text: str, mp3_path: str, timings_path: str):
    """ElevenLabs TTS: by far the most natural voice available, which is the single biggest
    lever on Shorts retention (synthetic-sounding narration is a top swipe-away cause).
    Returns whisper-aligned word timings, or None to fall through to the free engines
    (Gemini -> Kokoro -> Edge) if no key is set or the API fails / is out of credits."""
    pool = _elevenlabs_keys()
    if not pool:
        return None
    import requests
    voice_id = _TTS_CFG.get("elevenlabs_voice_id", ELEVENLABS_DEFAULT_VOICE)
    model_id = _TTS_CFG.get("elevenlabs_model_id", ELEVENLABS_DEFAULT_MODEL)

    # Each video starts on a DIFFERENT key (persisted rotation cursor). On failure we fail over
    # to the next key in the pool. Only when ALL keys are dead/failed do we return None so the
    # caller falls back to Gemini.
    n = len(pool)
    start = _el_next_start_index(n)
    order = [pool[(start + off) % n] for off in range(n)]

    audio = None
    used_key = None
    for ki, key in enumerate(order):
        # skip keys already known-dead this run (bad key or out of credits)
        key_tag = key[-6:] if len(key) >= 6 else key
        if key in _EL_DEAD_KEYS:
            continue
        try:
            r = requests.post(
                ELEVENLABS_TTS_URL.format(voice_id=voice_id),
                headers={"xi-api-key": key, "Content-Type": "application/json",
                         "Accept": "audio/mpeg"},
                json={
                    "text": text,
                    "model_id": model_id,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0,
                                       "use_speaker_boost": True},
                },
                timeout=120,
            )
            if r.status_code == 401:
                print(f"[tts] ElevenLabs key …{key_tag} rejected (401 bad key) - trying next key.")
                _EL_DEAD_KEYS.add(key)
                continue
            if r.status_code == 429:
                print(f"[tts] ElevenLabs key …{key_tag} out of credits (429) - trying next key.")
                _EL_DEAD_KEYS.add(key)
                continue
            r.raise_for_status()
            data = r.content
            if len(data) < 1000:
                print(f"[tts] ElevenLabs key …{key_tag} returned almost no audio - trying next key.")
                continue
            audio = data
            used_key = key_tag
            break
        except Exception as e:
            print(f"[tts] ElevenLabs key …{key_tag} request failed ({str(e)[:60]}) - trying next key.")
            continue

    if audio is None:
        live = sum(1 for k in pool if k not in _EL_DEAD_KEYS)
        print(f"[tts] All {n} ElevenLabs key(s) failed/exhausted - falling back to Gemini "
              f"({live} keys still untried may recover next run).")
        return None

    # ElevenLabs returns MP3 directly. Write it, normalize speed, align timings.
    with open(mp3_path, "wb") as f:
        f.write(audio)
    try:
        _apply_speed(mp3_path, SPEECH_SPEED)
    except Exception:
        pass
    words = _align_with_whisper(text, mp3_path)
    if not words:
        total = _audio_duration(mp3_path)
        words = _estimate_timings(text, min(total, _speech_end(mp3_path, total)))
    with open(timings_path, "w", encoding="utf-8") as f:
        json.dump(words, f, indent=2)
    print(f"[tts] ElevenLabs voice used (key …{used_key}, voice={voice_id[:8]}…, "
          f"model={model_id}, {len(words)} words)")
    return words


def _discover_tts_models(api_key: str) -> list:
    """Find the newest TTS-capable Gemini models this key can use."""
    global _tts_models
    if _tts_models:
        return _tts_models
    try:
        import requests
        r = requests.get(TTS_LIST_URL.format(key=api_key), timeout=30)
        r.raise_for_status()
        names = [m["name"].removeprefix("models/") for m in r.json().get("models", [])
                 if "tts" in m["name"]]
        names.sort(key=lambda n: ("pro" in n, n), reverse=True)  # flash first (free quota)
        if names:
            _tts_models = names[:3]
            return _tts_models
    except Exception:
        pass
    _tts_models = GEMINI_TTS_MODELS
    return _tts_models


def _try_gemini_tts(text: str, mp3_path: str, timings_path: str, api_key: str):
    """Gemini native TTS: the most natural free voice available. Returns word
    timings (whisper-aligned or estimated) or None to fall through to Edge."""
    if not api_key:
        return None
    import base64
    import requests
    style = _TTS_CFG.get("narration_direction", (
        "Read only the SCRIPT below. Speak as an interested, matter-of-fact person explaining "
        "something they have noticed to one listener. Let the opening observation sound curious, "
        "then become clear and assured as you explain the answer. Emphasize the actual contrast "
        "in the sentences, not every noun. Vary sentence melody and the length of natural pauses. "
        "Let short lines land; connect the explanatory phrases smoothly. Finish with a relaxed, "
        "conclusive falling tone. Avoid a uniform announcer cadence, exaggerated cheerfulness, "
        "whispering, theatrical suspense and added laughs or filler words. Do not speak these directions."
    ))
    style += (" Keep connected phrases flowing within each sentence; don't pause after every "
              "few words or reset into an announcer voice at each line. Speak to one friend, "
              "with understated curiosity and emphasis on the meaningful contrast. Let the "
              "final invitation sound like part of the conversation, without a sales pitch. "
              "Read exactly the script, without added words or performed laughter.")
    body = {
        "contents": [{"parts": [{"text": style + "\n\nSCRIPT:\n" + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {
                "voiceName": _TTS_CFG.get("gemini_voice", "Orus")}}},
        },
    }
    model = _TTS_CFG.get("gemini_tts_model", "gemini-3.1-flash-tts-preview")
    for narration_attempt in range(2):
        try:
            r = requests.post(GEMINI_TTS_URL.format(model=model, key=api_key),
                              json=body, timeout=120)
            if r.status_code in (401, 403, 429):
                print(f"[tts] Gemini narration unavailable (HTTP {r.status_code}); stopping without changing voices.")
                return None
            if r.status_code == 404:
                return None
            r.raise_for_status()
            part = r.json()["candidates"][0]["content"]["parts"][0]
            pcm = base64.b64decode(part["inlineData"]["data"])
        except Exception:
            continue
        raw = mp3_path + ".pcm"
        with open(raw, "wb") as f:
            f.write(pcm)
        # Gemini TTS returns 24kHz mono 16-bit PCM
        subprocess.run([_ffmpeg(), "-y", "-v", "error", "-f", "s16le", "-ar", "24000",
                        "-ac", "1", "-i", raw, mp3_path], check=True)
        os.remove(raw)
        _apply_speed(mp3_path, SPEECH_SPEED)
        words = _align_with_whisper(text, mp3_path)
        if not words:
            import shutil
            shutil.copyfile(mp3_path, mp3_path + f'.rejected-{narration_attempt+1}.mp3')
            diagnostic = mp3_path + '.alignment.json'
            if os.path.exists(diagnostic):
                shutil.copyfile(diagnostic, diagnostic + f'.rejected-{narration_attempt+1}.json')
            if narration_attempt == 0:
                print('[tts] Unverified narration saved for review; retrying the same script once.')
                continue
            raise RuntimeError("Gemini narration needs verified word timings; estimated cuts are disabled")
        with open(timings_path, "w", encoding="utf-8") as f:
            json.dump(words, f, indent=2)
        print(f"[tts] Gemini TTS used ({model}, {len(words)} words)")
        return words
    return None


def _try_kokoro(text: str, mp3_path: str, timings_path: str):
    """Kokoro: open-source local TTS, the most human-sounding free option.
    Used automatically if installed (pip install kokoro soundfile torch)."""
    try:
        from kokoro import KPipeline
        import soundfile as sf
        import numpy as np
    except ImportError:
        return None
    pipe = KPipeline(lang_code="a")  # American English
    chunks = [a for (_, _, a) in pipe(text, voice="am_michael")]
    audio = np.concatenate(chunks)
    wav = mp3_path.replace(".mp3", ".wav")
    sf.write(wav, audio, 24000)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav, mp3_path], check=True)
    os.remove(wav)
    _apply_speed(mp3_path, SPEECH_SPEED)
    words = _align_with_whisper(text, mp3_path) or _estimate_timings(text, _audio_duration(mp3_path))
    with open(timings_path, "w", encoding="utf-8") as f:
        json.dump(words, f, indent=2)
    print(f"[tts] Kokoro local engine used ({len(words)} words)")
    return words


def synthesize(text: str, mp3_path: str, timings_path: str, voice: str = DEFAULT_VOICE,
               api_key: str = "", engine: str = "auto", cfg: dict | None = None):
    """Generate voiceover MP3 + word timings JSON. Returns list of word timings.
    Engine chain (engine="auto"): ElevenLabs (premium, most natural) -> Gemini TTS ->
    Kokoro (if installed) -> Edge. ElevenLabs is tried first because voice naturalness is
    the single biggest lever on Shorts retention; it falls through automatically if no key
    is configured or it errors / runs out of credits."""
    global _TTS_CFG
    _TTS_CFG = dict(cfg or {})
    allow_fallback = bool(_TTS_CFG.get("allow_voice_fallback", False))
    if engine == "auto" and not allow_fallback:
        engine = _TTS_CFG.get("preferred_tts_engine", "gemini")
    if engine not in ("auto", "gemini", "elevenlabs", "kokoro", "edge"):
        raise ValueError("Unsupported narration engine")
    # ElevenLabs first (best quality). Falls through to free engines if unavailable.
    if engine in ("auto", "elevenlabs"):
        global _EL_WARNED
        if engine == "auto" and not _elevenlabs_keys() and not _EL_WARNED:
            _EL_WARNED = True
            print("[tts] No ElevenLabs keys set - using the FREE Gemini TTS voice (natural, "
                  "human-sounding). ElevenLabs is optional and only marginally better; the "
                  "free Gemini voice is the default and works well.")
        el = _try_elevenlabs(text, mp3_path, timings_path)
        if el:
            return el
        if engine == "elevenlabs" and not allow_fallback:
            raise RuntimeError("Selected ElevenLabs narration unavailable; voice substitution disabled")
        if engine == "elevenlabs":
            print("[tts] ElevenLabs unavailable, falling back to free voices")
    if engine in ("auto", "gemini"):
        g = _try_gemini_tts(text, mp3_path, timings_path, api_key)
        if g:
            return g
        if engine == "gemini" and not allow_fallback:
            raise RuntimeError("Selected Gemini narration unavailable; voice substitution disabled. Check connection/quota.")
        if engine == "gemini":
            print("[tts] Gemini TTS unavailable, falling back to Edge")
    if engine in ("auto", "kokoro"):
        kokoro = _try_kokoro(text, mp3_path, timings_path)
        if kokoro:
            return kokoro
        if engine == "kokoro" and not allow_fallback:
            raise RuntimeError("Selected local narration unavailable; voice substitution disabled")
    attempts = [voice, voice] + ([FALLBACK_VOICE] if allow_fallback else [])  # retry same voice once, then fallback
    last_err = None
    for v in attempts:
        try:
            n_bytes, words = asyncio.run(_synth(text, mp3_path, v))
        except Exception as e:
            last_err = e
            continue
        if n_bytes < 1000:  # essentially no audio: treat as failure, retry
            last_err = RuntimeError(f"TTS returned almost no audio with voice {v}")
            continue
        if not words:
            _apply_speed(mp3_path, 1.0)  # trim leading silence (edge path)
            # audio fine, timing metadata missing: try true alignment, else estimate
            words = _align_with_whisper(text, mp3_path)
            if not words:
                total = _audio_duration(mp3_path)
                duration = min(total, _speech_end(mp3_path, total))
                words = _estimate_timings(text, duration)
                print(f"[tts] estimated {len(words)} word timings "
                      f"(speech ends {duration:.1f}s of {total:.1f}s audio)")
        with open(timings_path, "w", encoding="utf-8") as f:
            json.dump(words, f, indent=2)
        return words
    raise RuntimeError(
        f"TTS failed after retries and fallback voice. Last error: {last_err}. "
        "Check your internet connection, then try: pip install --upgrade edge-tts"
    )


if __name__ == "__main__":
    w = synthesize(
        "You walk in for milk. It's hidden at the very back, on purpose.",
        "test_voice.mp3", "test_timings.json",
    )
    print(f"Generated {len(w)} word timings, audio ends at {w[-1]['end']:.2f}s")
    os.remove("test_voice.mp3"); os.remove("test_timings.json")
