"""
tts.py - Hidden Logic production TTS path.
Gemini TTS with the fixed Orus voice. The narration transcript is the only text sent to
Gemini; the editorial delivery direction is kept as review metadata and never sent.
Every take is transcribed and measured before acceptance. A single alternate take is
allowed only after a measurable delivery-quality failure; failures never fall back to
Edge or a different voice.
"""
import json
import os
import re
import subprocess



# Production pilot voice identity is fixed. Delivery variation lives in speech metadata,
# never in a randomly substituted speaker.
DEFAULT_VOICE = "Orus"

DELIVERY_DIRECTIONS = {
    "curious_observation": "Curious observation: conversational and alert, as if noticing a small real-world detail with the listener. Natural pauses; no theatrical suspense.",
    "understated_dry_amusement": "Understated dry amusement: lightly wry, restrained, and human; never sarcastic or performative. Keep the explanation clear.",
    "confident_practical_explanation": "Confident practical explanation: calm, direct, and helpful, like a person explaining a useful mechanism to a friend. No announcer cadence.",
}
DIRECTION_ORDER = tuple(DELIVERY_DIRECTIONS)
GEMINI_TTS_MODEL_DEFAULT = "gemini-3.8-flash-tts"
WHISPER_MODEL_NAME = "small.en"
_WHISPER_MODEL = None


def pick_voice():
    return "Orus"


def _transcribe_audio(mp3_path: str):
    """Return (recognized transcript, word timings) from the rendered take.

    The cached model avoids reloading weights for every pilot. Missing ASR is a hard
    failure for the production/pilot gate; estimated timings are not evidence of an
    accurate transcript.
    """
    global _WHISPER_MODEL
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is required to verify a narration take") from exc
    try:
        if _WHISPER_MODEL is None:
            _WHISPER_MODEL = WhisperModel(WHISPER_MODEL_NAME, device="cpu", compute_type="int8")
        segments, _ = _WHISPER_MODEL.transcribe(mp3_path, word_timestamps=True, language="en")
        segments = list(segments)
        transcript_parts = []
        words = []
        for seg in segments:
            if seg.text:
                transcript_parts.append(seg.text.strip())
            for word in (seg.words or []):
                words.append({"word": word.word.strip(), "start": round(float(word.start), 3),
                              "end": round(float(word.end), 3)})
        transcript = " ".join(part for part in transcript_parts if part).strip()
        if len(words) < 5 or not transcript:
            raise RuntimeError("speech recognition returned too few words to verify the take")
        return transcript, words
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"faster-whisper transcript/timing verification failed: {exc}") from exc


def _audio_duration(mp3_path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", mp3_path],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip())


GEMINI_TTS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"


def _extract_interaction_audio(payload: dict) -> tuple[bytes, str]:
    """Accept the Interactions convenience response and its raw REST step form."""
    audio = payload.get("output_audio") or {}
    if isinstance(audio, dict) and audio.get("data"):
        import base64
        return base64.b64decode(audio["data"]), str(audio.get("mime_type") or "audio/wav")
    for step in payload.get("steps", []) or []:
        for part in step.get("content", []) or []:
            if part.get("type") == "audio" and part.get("data"):
                import base64
                return base64.b64decode(part["data"]), str(part.get("mime_type") or "audio/wav")
    raise RuntimeError("Gemini TTS response contained no audio payload")


def _gemini_tts_request_body(transcript: str, voice: str, direction: str, model: str) -> dict:
    """Build a Gemini TTS request whose only text input is the exact narration.

    The editorial delivery direction is validated and kept for metadata/review only. It is
    never sent to Gemini: no style prompt, annotation, or instruction text is included.
    """
    if voice != "Orus":
        raise RuntimeError(f"Production voice is locked to Orus, not {voice!r}")
    if direction not in DELIVERY_DIRECTIONS:
        raise ValueError(f"Unknown delivery direction: {direction}")
    transcript = str(transcript or "").strip()
    if not transcript:
        raise ValueError("Cannot synthesize an empty script")
    from editorial_quality import contains_spoken_instruction
    if contains_spoken_instruction(transcript):
        raise ValueError("Narration contains an internal TTS/production instruction; refusing to speak it")
    return {
        "model": model,
        "input": [{
            "type": "user_input",
            "content": [{
                "type": "text",
                "text": transcript,
            }],
        }],
        "response_format": {"type": "audio", "mime_type": "audio/wav", "sample_rate": 24000},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }


def _write_gemini_audio(text: str, mp3_path: str, api_key: str, voice: str,
                        direction: str, model: str) -> None:
    """Synthesize the transcript verbatim. `direction` is not sent to Gemini."""
    import requests
    body = _gemini_tts_request_body(text, voice, direction, model)
    response = requests.post(
        GEMINI_TTS_URL,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=body,
        timeout=180,
    )
    response.raise_for_status()
    audio_bytes, mime_type = _extract_interaction_audio(response.json())
    if len(audio_bytes) < 2048:
        raise RuntimeError("Gemini TTS returned an empty or truncated audio payload")

    raw_path = mp3_path + (".wav" if b"RIFF" in audio_bytes[:16] else ".pcm")
    with open(raw_path, "wb") as fh:
        fh.write(audio_bytes)
    try:
        if raw_path.endswith(".pcm"):
            # The Interactions API raw L16 output is mono, signed 16-bit PCM at 24 kHz.
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", "24000",
                "-ac", "1", "-i", raw_path, "-codec:a", "libmp3lame", "-q:a", "2", mp3_path,
            ], check=True, timeout=120)
        else:
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-i", raw_path,
                "-codec:a", "libmp3lame", "-q:a", "2", mp3_path,
            ], check=True, timeout=120)
    finally:
        try:
            os.remove(raw_path)
        except OSError:
            pass
    # Deliberately no atempo, pitch shifting, silenceremove, or speed normalization.
    if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) < 1024:
        raise RuntimeError("Gemini audio conversion did not produce a valid MP3")


def _decode_pcm16(mp3_path: str, sample_rate: int = 16000):
    """Decode audio for pitch and peak checks. Returns a normalized numpy vector."""
    import numpy as np
    decoded = subprocess.run([
        "ffmpeg", "-v", "error", "-i", mp3_path, "-f", "s16le", "-ac", "1",
        "-ar", str(sample_rate), "pipe:1",
    ], capture_output=True, check=True, timeout=120)
    if len(decoded.stdout) < sample_rate * 2:
        raise RuntimeError("audio is too short to measure")
    samples = np.frombuffer(decoded.stdout, dtype="<i2").astype(np.float32) / 32768.0
    return samples


def _pitch_span_and_peak(mp3_path: str) -> tuple[float | None, bool]:
    """Estimate voiced F0 movement in semitones and detect digital clipping."""
    try:
        import numpy as np
        samples = _decode_pcm16(mp3_path, 16000)
    except Exception as exc:
        print(f"[tts] pitch/clipping analysis unavailable: {exc}")
        return None, False
    clipped = bool(np.max(np.abs(samples)) >= 0.999)
    frame_size, hop, sample_rate = 640, 160, 16000
    min_lag, max_lag = sample_rate // 360, sample_rate // 70
    voiced = []
    fft_size = 1 << (2 * frame_size - 1).bit_length()
    for offset in range(0, max(0, len(samples) - frame_size), hop):
        frame = samples[offset:offset + frame_size].astype(np.float64)
        frame -= frame.mean()
        rms = float(np.sqrt(np.mean(frame * frame)))
        if rms < 0.008:
            continue
        spectrum = np.fft.rfft(frame, n=fft_size)
        corr = np.fft.irfft(spectrum * np.conjugate(spectrum), n=fft_size)[:frame_size]
        if corr[0] <= 0:
            continue
        region = corr[min_lag:max_lag + 1]
        if not len(region):
            continue
        lag = int(np.argmax(region)) + min_lag
        strength = float(corr[lag] / corr[0])
        frequency = sample_rate / lag
        if strength >= 0.30 and 70 <= frequency <= 360:
            voiced.append(frequency)
    if len(voiced) < 12:
        return None, clipped
    semitones = 12.0 * np.log2(np.asarray(voiced, dtype=np.float64))
    span = float(np.percentile(semitones, 90) - np.percentile(semitones, 10))
    return span, clipped


def _take_metrics(script: str, mp3_path: str) -> tuple[list[dict], dict, list[str]]:
    from editorial_quality import (
        coefficient_of_variation,
        contains_spoken_instruction,
        transcript_accuracy,
        validate_word_timings,
        voice_delivery_issues,
    )
    transcript, words = _transcribe_audio(mp3_path)
    duration = _audio_duration(mp3_path)
    accuracy = transcript_accuracy(script, transcript)
    if contains_spoken_instruction(transcript):
        issues = ["tts_direction_spoken_in_audio"]
    else:
        issues = []
    durations = [max(0.0, float(w["end"]) - float(w["start"])) for w in words]
    gaps = [max(0.0, float(b["start"]) - float(a["end"]))
            for a, b in zip(words, words[1:])]
    pitch_span, clipping = _pitch_span_and_peak(mp3_path)
    issues.extend(validate_word_timings(words, duration_seconds=duration))
    delivery_issues = voice_delivery_issues(
        transcript_accuracy_value=accuracy,
        duration_seconds=duration,
        word_timings=words,
        pitch_span_semitones=pitch_span,
        word_duration_cv=coefficient_of_variation(durations),
        max_pause_seconds=max(gaps, default=0.0),
        clipping_detected=clipping,
    )
    metrics = {
        "transcript": transcript,
        "transcript_accuracy": round(accuracy, 4),
        "duration_seconds": round(duration, 3),
        "max_pause_seconds": round(max(gaps, default=0.0), 3),
        "word_duration_cv": round(coefficient_of_variation(durations), 4),
        "pitch_span_semitones": round(pitch_span, 3) if pitch_span is not None else None,
        "clipping_detected": clipping,
        "timing_source": "faster-whisper-word-timestamps",
    }
    return words, metrics, sorted(set(issues + delivery_issues))


class TTSQualityError(RuntimeError):
    """Both permitted Orus takes failed measurable delivery checks."""


def _set_voice_metadata(metadata: dict | None, *, voice: str, direction: str, model: str,
                        take: int, metrics: dict) -> None:
    if metadata is None:
        return
    metadata["voice"] = voice
    metadata["voice_identity"] = "Orus"
    metadata["voice_direction"] = direction
    metadata["tts_style_prompt"] = "none"
    metadata["tts_style_prompt_sent"] = False
    metadata["tts_engine"] = "gemini"
    metadata["tts_model"] = model
    metadata["tts_take"] = take
    metadata["timing_source"] = metrics.get("timing_source", "faster-whisper-word-timestamps")
    metadata["tts_quality"] = {k: v for k, v in metrics.items() if k != "transcript"}
    metadata["transcript_verified"] = True
    metadata["transcript_accuracy"] = metrics.get("transcript_accuracy")
    metadata["transcript_actual"] = metrics.get("transcript", "")


def synthesize(text: str, mp3_path: str, timings_path: str, voice: str = DEFAULT_VOICE,
               api_key: str = "", engine: str = "gemini", cfg: dict | None = None,
               metadata: dict | None = None, direction: str | None = None):
    """Generate exact-transcript Orus audio and verified word timings.

    `auto` is retained as a backwards-compatible spelling for the production Gemini path.
    It intentionally does NOT fall through to ElevenLabs, Kokoro, Edge, or another voice.
    A second Gemini take is synthesized only if the primary audio fails measurable checks.
    """
    selected_voice = str(voice or DEFAULT_VOICE).strip()
    if selected_voice.lower() == "auto":
        selected_voice = "Orus"
    if selected_voice != "Orus":
        raise RuntimeError("The editorial pilot is locked to the Orus voice identity")
    if not api_key:
        raise RuntimeError("Gemini API key is required for the Orus TTS pilot")
    if engine not in {"auto", "gemini", "gemini_tts"}:
        raise RuntimeError(
            f"Unsupported production TTS engine {engine!r}; no alternate-voice fallback is allowed"
        )

    model = str((cfg or {}).get("gemini_tts_model") or GEMINI_TTS_MODEL_DEFAULT).strip()
    direction = direction or (metadata or {}).get("voice_direction") or (cfg or {}).get(
        "tts_direction", "curious_observation"
    )
    if direction not in DELIVERY_DIRECTIONS:
        raise ValueError(f"Unknown delivery direction: {direction}")

    import editorial_quality
    if editorial_quality.contains_spoken_instruction(text):
        raise TTSQualityError(
            "Narration contains an internal TTS/production instruction; refusing to synthesize it"
        )
    last_issues: list[str] = []
    for take in (1, 2):
        temp_mp3 = f"{mp3_path}.take{take}.tmp.mp3"
        try:
            # API/network/codec errors are not delivery failures; stop immediately instead of
            # spending another take or falling back to another engine.
            _write_gemini_audio(text, temp_mp3, api_key, selected_voice, direction, model)
            words, metrics, issues = _take_metrics(text, temp_mp3)
            issues.extend(editorial_quality.validate_word_timings(
                words, duration_seconds=metrics.get("duration_seconds")
            ))
            quote = (metadata or {}).get("first_answer_quote", "")
            answer_at = editorial_quality.first_answer_time(text, words, quote)
            metrics["first_answer_seconds"] = round(answer_at, 3) if answer_at is not None else None
            if answer_at is None or answer_at > editorial_quality.MAX_FIRST_ANSWER_SECONDS:
                issues.append("first_useful_answer_after_six_seconds")
            issues = sorted(set(issues))
            if issues:
                last_issues = issues
                print(f"[tts] Orus take {take} rejected: {', '.join(issues)}")
                if take == 1:
                    continue
                raise TTSQualityError(
                    "Both Orus takes failed delivery checks: " + ", ".join(last_issues)
                )

            os.replace(temp_mp3, mp3_path)
            with open(timings_path, "w", encoding="utf-8") as fh:
                json.dump(words, fh, indent=2)
            _set_voice_metadata(metadata, voice=selected_voice, direction=direction,
                                model=model, take=take, metrics=metrics)
            print(
                f"[tts] Accepted Orus take {take} ({direction}, {model}, "
                f"accuracy={metrics['transcript_accuracy']:.3f}, "
                f"duration={metrics['duration_seconds']:.1f}s)"
            )
            return words
        except TTSQualityError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Gemini Orus TTS take {take} failed; refusing alternate-engine fallback: {exc}"
            ) from exc
        finally:
            try:
                if os.path.exists(temp_mp3):
                    os.remove(temp_mp3)
            except OSError:
                pass
    raise TTSQualityError("No Orus narration take passed delivery checks")


if __name__ == "__main__":
    raise SystemExit(
        "tts.py is a library entry point; use python pilot_batch.py --generate to create "
        "unpublished, quality-gated pilots."
    )
