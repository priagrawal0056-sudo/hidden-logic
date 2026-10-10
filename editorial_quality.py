"""Deterministic editorial gates shared by script, voice, captions, and pilot runs.

The LLM proposes material; this module applies small, testable checks before an
episode can enter the reserve. A failed check is a skip, never a reason to fill a
slot with weaker copy or footage.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Iterable


MIN_SCRIPT_WORDS = 45
MAX_SCRIPT_WORDS = 75
EXPECTED_SENTENCES = 5
EXPECTED_BEATS = 5
MAX_FIRST_ANSWER_SECONDS = 6.0
MIN_TRANSCRIPT_ACCURACY = 0.90
TARGET_VOICE_DURATION = (18.0, 35.0)
MAX_LONG_PAUSE_SECONDS = 1.8
MIN_PITCH_SPAN_SEMITONES = 2.0
MIN_WORD_DURATION_CV = 0.12

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by", "for",
    "from", "had", "has", "have", "how", "in", "into", "is", "it", "its", "of",
    "on", "or", "that", "the", "their", "then", "there", "this", "to", "up",
    "was", "were", "what", "when", "where", "which", "while", "who", "why", "with",
    "you", "your", "they", "them", "we", "our", "he", "she", "his", "her", "do",
    "does", "did", "can", "could", "would", "should", "will", "just", "always",
}

GENERIC_VISUAL_QUERIES = {
    "cinematic", "cinematic footage", "documentary shot", "slow motion", "abstract",
    "abstract logic", "mysterious lighting", "person looking at phone", "walking down street",
}

PROMPT_LEAK_PATTERNS = (
    r"\bread this in a\b",
    r"\bread\s+(?:this|the following|the script)\s+(?:in|with)\s+(?:a\s+)?"
    r"(?:warm|friendly|natural|curious|conversational|confident|understated|calm)\b",
    r"\bread\s+(?:in|with)\s+(?:a\s+)?(?:warm|friendly|natural|curious|"
    r"conversational|confident|understated|calm)\b",
    r"\b(?:use|keep|maintain)\s+(?:a\s+)?(?:warm|friendly|natural|curious|"
    r"conversational|confident|understated|calm)\b.{0,60}\b(?:tone|voice|cadence|delivery)\b",
    r"\b(?:voice|delivery|speech|tts)\s+(?:direction|instruction|prompt)\b",
    r"\bthe following (?:text|script)\b",
    r"\bwarm,? friendly,? natural voice\b",
    r"\bvoice direction\b",
    r"\bcurious observation\b",
    r"\bunderstated dry amusement\b",
    r"\bconfident practical explanation\b",
    r"\bdo not read (?:the )?instructions\b",
    r"\bspeech metadata\b",
    r"\b(?:speak|say|narrate|deliver|sound|read)\s+(?:this|it|these lines|the (?:script|narration|line|following))?\s*"
    r"(?:in an? |with an? |warmly|curiously|calmly|playfully|dryly|wryly|naturally)\b",
    r"\b(?:curious|conversational|understated|wry|dry|confident|warm|friendly|calm|natural|playful)\s+"
    r"(?:tone|delivery|cadence|speaking style)\b",
    r"\bstyle (?:prompt|direction|instruction|note)s?\b",
    r"\bsounds? (?:playful|curious|understated|conversational|confident|wry)\b",
)


def contains_spoken_instruction(text: str) -> bool:
    """True when text contains an internal production/TTS direction, not narration."""
    return any(re.search(pattern, str(text or ""), flags=re.I | re.S)
               for pattern in PROMPT_LEAK_PATTERNS)

FORCED_SUSPENSE_PATTERNS = (
    r"you've been tricked",
    r"you won't believe",
    r"but that's not even the (?:clever|strange|crazy) part",
    r"wait until the end",
    r"the real reason comes later",
    r"nobody wants you to know",
    r"this changes everything",
)

GENERIC_AI_PATTERNS = (
    r"in today's (?:fast-paced|ever-changing|modern) world",
    r"let's dive into",
    r"delve into",
    r"unlock the (?:secret|power|potential)",
    r"game changer",
    r"seamlessly",
    r"it's important to note",
    r"in conclusion",
)

UNIVERSAL_CLAIM_PATTERNS = (
    r"\beveryone\b",
    r"\bnobody\b",
    r"\balways\b",
    r"\bnever\b",
    r"\ball (?:people|users|customers|shoppers|travelers|travellers)\b",
)


class EditorialGateError(ValueError):
    """Raised when a proposed episode fails a deterministic editorial gate."""


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:['’][a-z0-9]+)?", str(text or "").lower())


def split_sentences(script: str) -> list[str]:
    """Small, dependency-free sentence splitter for the short scripts we generate."""
    text = re.sub(r"\s+", " ", str(script or "")).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Word error rate in [0, 1+]; insertion errors are included."""
    ref, hyp = tokens(reference), tokens(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    row = list(range(len(hyp) + 1))
    for i, expected in enumerate(ref, 1):
        next_row = [i]
        for j, actual in enumerate(hyp, 1):
            next_row.append(min(
                next_row[-1] + 1,
                row[j] + 1,
                row[j - 1] + (expected != actual),
            ))
        row = next_row
    return row[-1] / len(ref)


def transcript_accuracy(reference: str, hypothesis: str) -> float:
    return max(0.0, 1.0 - word_error_rate(reference, hypothesis))


def _normalized_phrase(text: str) -> list[str]:
    return tokens(text)


def find_phrase_span(word_timings: list[dict], phrase: str) -> tuple[float, float] | None:
    """Return the first start/end pair for an exact normalized phrase in word timings."""
    wanted = _normalized_phrase(phrase)
    got = [tokens(w.get("word", "")) for w in word_timings]
    flat = [part for word_parts in got for part in word_parts]
    if not wanted or not flat:
        return None
    for i in range(len(flat) - len(wanted) + 1):
        if flat[i:i + len(wanted)] != wanted:
            continue
        # Timings are normally one token per item. This mapping also tolerates a token split
        # across two Whisper records by locating each flattened token's owning record.
        owners = []
        for idx, parts in enumerate(got):
            owners.extend([idx] * len(parts))
        first_i, last_i = owners[i], owners[i + len(wanted) - 1]
        return float(word_timings[first_i]["start"]), float(word_timings[last_i]["end"])
    return None


def _first_answer_quote(script: str, supplied_quote: str = "") -> str:
    if supplied_quote and tokens(supplied_quote):
        return supplied_quote.strip()
    # Conservative local fallback: identify a plain causal/explanatory clause.
    cue = re.search(
        r"\b(?:because|since|that means|which means|this happens when|the reason is|"
        r"works by|comes from|is caused by|is due to|lets? .*? to|makes? .*? easier|"
        r"keeps? .*? from|uses? .*? to)\b",
        script,
        flags=re.I,
    )
    if not cue:
        return ""
    before = tokens(script[:cue.start()])
    tail = re.split(r"(?<=[.!?])\s+", script[cue.start():], maxsplit=1)[0]
    return " ".join(tokens(tail)[:8]) if before else " ".join(tokens(tail)[:8])


def estimated_phrase_time(script: str, phrase: str, words_per_second: float = 2.5) -> float | None:
    """Estimate phrase onset for pre-TTS script validation at a conservative read pace."""
    text_tokens = tokens(script)
    phrase_tokens = tokens(phrase)
    if not phrase_tokens:
        return None
    for i in range(len(text_tokens) - len(phrase_tokens) + 1):
        if text_tokens[i:i + len(phrase_tokens)] == phrase_tokens:
            return i / max(0.1, words_per_second)
    return None


def sentence_timing_spans(script: str, word_timings: list[dict]) -> list[dict]:
    """Map each spoken sentence to its actual word-timing boundaries in order."""
    sentences = split_sentences(script)
    timing_tokens = [tokens(item.get("word", "")) for item in word_timings or []]
    flat, owners = [], []
    for owner, parts in enumerate(timing_tokens):
        for part in parts:
            flat.append(part)
            owners.append(owner)
    spans = []
    cursor = 0
    for sentence in sentences:
        wanted = tokens(sentence)
        found = None
        for offset in range(cursor, len(flat) - len(wanted) + 1):
            if flat[offset:offset + len(wanted)] == wanted:
                found = offset
                break
        if found is None or not wanted:
            raise ValueError("sentence does not match verified word timings")
        first_owner = owners[found]
        last_owner = owners[found + len(wanted) - 1]
        spans.append({
            "sentence": sentence,
            "start": float(word_timings[first_owner]["start"]),
            "end": float(word_timings[last_owner]["end"]),
            "first_word_index": first_owner,
            "last_word_index": last_owner,
        })
        cursor = found + len(wanted)
    if len(spans) != EXPECTED_SENTENCES:
        raise ValueError(f"expected {EXPECTED_SENTENCES} sentence timings, got {len(spans)}")
    return spans


def five_beat_segment_durations(script: str, word_timings: list[dict],
                                audio_duration: float | None = None) -> list[float]:
    """Allocate five visual beats around actual sentence boundaries and pauses."""
    spans = sentence_timing_spans(script, word_timings)
    if not spans:
        raise ValueError("no sentence spans available")
    end_time = float(audio_duration if audio_duration is not None else word_timings[-1]["end"] + 0.8)
    boundaries = [0.0]
    for current, following in zip(spans, spans[1:]):
        gap_start, gap_end = current["end"], following["start"]
        if gap_end < gap_start - 0.05:
            raise ValueError("sentence word timings overlap")
        boundaries.append((gap_start + max(gap_start, gap_end)) / 2.0)
    boundaries.append(end_time)
    durations = [round(boundaries[i + 1] - boundaries[i], 3) for i in range(len(boundaries) - 1)]
    if len(durations) != EXPECTED_BEATS or any(value <= 0 for value in durations):
        raise ValueError("five narration-aligned beat durations are invalid")
    return durations


def first_answer_time(script: str, word_timings: list[dict] | None = None,
                      quote: str = "") -> float | None:
    quote = _first_answer_quote(script, quote)
    if not quote:
        return None
    if word_timings is not None:
        # Once measured timings are supplied, an unlocated answer phrase is a rejection;
        # never conceal the mismatch with a script-position estimate.
        span = find_phrase_span(word_timings, quote)
        return span[0] if span else None
    return estimated_phrase_time(script, quote)


def _content_words(text: str) -> set[str]:
    return {w for w in tokens(text) if w not in STOPWORDS and len(w) > 2}


def title_matches_script(title: str, script: str, topic: str = "") -> bool:
    title_words = _content_words(title)
    script_words = _content_words(script)
    topic_words = _content_words(topic)
    if not title_words or not script_words:
        return False
    overlap = title_words & script_words
    if len(title_words) >= 4 and len(overlap) < 2:
        return False
    if len(title_words) < 4 and not overlap:
        return False
    # If the topic has distinctive words, at least one must be present in both packaging and copy.
    distinctive = topic_words - STOPWORDS
    if distinctive and not (distinctive & title_words & script_words):
        return False
    return True


def validate_script(script: str, title: str, topic: str = "", broll_keywords: Iterable[str] | None = None,
                    first_answer_quote: str = "", evidence_record: dict | None = None,
                    require_five_beats: bool = True) -> list[str]:
    """Return editorial defects without attempting to rewrite or weaken the proposal."""
    issues: list[str] = []
    clean = re.sub(r"\s+", " ", str(script or "")).strip()
    script_words = tokens(clean)
    sentences = split_sentences(clean)

    if not clean:
        issues.append("empty_script")
        return issues
    if len(script_words) < MIN_SCRIPT_WORDS:
        issues.append("script_too_short")
    if len(script_words) > MAX_SCRIPT_WORDS:
        issues.append("script_too_long")
    if len(sentences) != EXPECTED_SENTENCES:
        issues.append("story_must_have_exactly_five_complete_sentences")
    if not re.search(r"[.!?][\"'”’)]*$", clean):
        issues.append("unfinished_ending")
    if any(re.search(pattern, clean, re.I) for pattern in FORCED_SUSPENSE_PATTERNS):
        issues.append("forced_suspense")
    if any(re.search(pattern, clean, re.I) for pattern in GENERIC_AI_PATTERNS):
        issues.append("generic_ai_phrase")
    if any(re.search(pattern, clean, re.I) for pattern in UNIVERSAL_CLAIM_PATTERNS):
        issues.append("unsupported_universal_claim_wording")
    if contains_spoken_instruction(clean):
        issues.append("tts_instruction_leak_in_script")

    quote = _first_answer_quote(clean, first_answer_quote)
    answer_at = estimated_phrase_time(clean, quote) if quote else None
    if answer_at is None or answer_at > MAX_FIRST_ANSWER_SECONDS:
        issues.append("first_useful_answer_late_or_unmarked")

    if not title_matches_script(title, clean, topic):
        issues.append("title_script_mismatch")

    queries = [str(q).strip() for q in (broll_keywords or []) if str(q).strip()]
    if require_five_beats and len(queries) != EXPECTED_BEATS:
        issues.append("shot_plan_must_have_five_beats")
    normalized = [re.sub(r"[^a-z0-9]+", " ", q.lower()).strip() for q in queries]
    if len(set(normalized)) != len(normalized):
        issues.append("duplicate_shot_queries")
    if any(q in GENERIC_VISUAL_QUERIES or len(q.split()) < 3 for q in normalized):
        issues.append("generic_or_underdescribed_shot_query")

    record = evidence_record or {}
    if not isinstance(record, dict) or not str(record.get("mechanism", "")).strip():
        issues.append("missing_supported_mechanism_evidence")
    else:
        claims = record.get("supported_claims")
        if not isinstance(claims, list) or not any(str(claim).strip() for claim in claims):
            issues.append("missing_supported_claims")
        sources = record.get("sources")
        valid_sources = [
            source for source in sources or []
            if isinstance(source, dict)
            and str(source.get("title", "")).strip()
            and str(source.get("url", "")).lower().startswith(("https://", "http://"))
        ] if isinstance(sources, list) else []
        if not valid_sources:
            issues.append("missing_evidence_source")
    return issues


def coefficient_of_variation(values: Iterable[float]) -> float:
    vals = [float(v) for v in values if math.isfinite(float(v)) and float(v) >= 0]
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    if mean <= 0:
        return 0.0
    variance = sum((x - mean) ** 2 for x in vals) / len(vals)
    return math.sqrt(variance) / mean


def voice_delivery_issues(*, transcript_accuracy_value: float, duration_seconds: float,
                          word_timings: list[dict], pitch_span_semitones: float | None,
                          word_duration_cv: float, max_pause_seconds: float,
                          clipping_detected: bool = False,
                          min_duration: float = TARGET_VOICE_DURATION[0],
                          max_duration: float = TARGET_VOICE_DURATION[1]) -> list[str]:
    issues: list[str] = []
    if not math.isfinite(float(transcript_accuracy_value)) or transcript_accuracy_value < MIN_TRANSCRIPT_ACCURACY:
        issues.append("transcript_mismatch")
    if (not math.isfinite(float(duration_seconds)) or duration_seconds < min_duration
            or duration_seconds > max_duration):
        issues.append("voice_duration_out_of_band")
    if not word_timings:
        issues.append("missing_word_timing")
    elif float(word_timings[0].get("start", 0.0)) > 0.6:
        issues.append("excessive_leading_silence")
    if not math.isfinite(float(max_pause_seconds)) or max_pause_seconds > MAX_LONG_PAUSE_SECONDS:
        issues.append("excessive_pause")
    if (pitch_span_semitones is None or not math.isfinite(float(pitch_span_semitones))
            or pitch_span_semitones < MIN_PITCH_SPAN_SEMITONES):
        issues.append("flat_pitch_movement")
    if not math.isfinite(float(word_duration_cv)) or word_duration_cv < MIN_WORD_DURATION_CV:
        issues.append("overly_even_word_timing")
    if clipping_detected:
        issues.append("audio_clipping")
    return issues


def validate_word_timings(words: list[dict], duration_seconds: float | None = None,
                          *, max_overlap_seconds: float = 0.05) -> list[str]:
    issues: list[str] = []
    prev_start = -1.0
    prev_end = -1.0
    for i, item in enumerate(words or []):
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            issues.append("invalid_word_timing")
            continue
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            issues.append("invalid_word_timing")
        if i and start < prev_start:
            issues.append("unordered_word_timing")
        if i and start < prev_end - max_overlap_seconds:
            issues.append("overlapping_word_timing")
        if duration_seconds is not None and end > duration_seconds + 0.25:
            issues.append("word_timing_beyond_audio")
        prev_start, prev_end = start, max(prev_end, end)
    return sorted(set(issues))


def validate_render(path: str | Path, expected_duration: float | None = None,
                    width: int = 1080, height: int = 1920) -> tuple[list[str], dict]:
    """Check the rendered MP4 has valid streams, dimensions, duration, and audible non-clipped audio."""
    import subprocess

    target = Path(path)
    issues: list[str] = []
    metrics: dict = {}
    if not target.is_file() or target.stat().st_size < 10_000:
        return ["render_missing_or_truncated"], metrics
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        payload = json.loads(probe.stdout)
    except Exception as exc:
        return ["render_probe_failed:" + type(exc).__name__], metrics
    streams = payload.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video:
        issues.append("render_video_stream_missing")
    else:
        if int(video.get("width", 0)) != width or int(video.get("height", 0)) != height:
            issues.append("render_resolution_invalid")
        if video.get("codec_name") != "h264":
            issues.append("render_video_codec_invalid")
        metrics["video_codec"] = video.get("codec_name")
        metrics["width"] = video.get("width")
        metrics["height"] = video.get("height")
    if not audio:
        issues.append("render_audio_stream_missing")
    else:
        if audio.get("codec_name") != "aac":
            issues.append("render_audio_codec_invalid")
        metrics["audio_codec"] = audio.get("codec_name")
    try:
        duration = float(payload.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    metrics["duration_seconds"] = round(duration, 3)
    if not math.isfinite(duration) or duration <= 0:
        issues.append("render_duration_invalid")
    elif expected_duration is not None and abs(duration - float(expected_duration)) > 0.75:
        issues.append("render_duration_mismatch")

    if audio:
        try:
            analysis = subprocess.run(
                ["ffmpeg", "-hide_banner", "-i", str(target), "-map", "0:a:0",
                 "-af", "volumedetect", "-f", "null", "-"],
                capture_output=True, text=True, check=True, timeout=90,
            )
            text = analysis.stderr
            mean_match = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", text)
            peak_match = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", text)
            if mean_match:
                metrics["mean_volume_db"] = float(mean_match.group(1))
                if metrics["mean_volume_db"] < -48.0:
                    issues.append("render_audio_too_quiet")
            else:
                issues.append("render_audio_level_unavailable")
            if peak_match:
                metrics["peak_volume_db"] = float(peak_match.group(1))
                if metrics["peak_volume_db"] >= -0.05:
                    issues.append("render_audio_clipping")
            else:
                issues.append("render_audio_peak_unavailable")
        except Exception:
            issues.append("render_audio_analysis_failed")
    return sorted(set(issues)), metrics


def validate_episode_meta(metadata: dict, workdir: str | Path | None = None,
                          *, min_visual_score: float = 8.0) -> list[str]:
    """Validate all machine-checkable gates before an episode enters/passes the reserve.

    Human review remains a separate gate. This function verifies the evidence, exact
    narration/timings, five distinct reviewed clips/crops, captions, and final MP4 without
    making network calls.
    """
    import hashlib
    import subprocess

    issues: list[str] = []

    def finite_number(value):
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except (TypeError, ValueError):
            return None

    if not isinstance(metadata, dict):
        return ["metadata_missing_or_invalid"]
    script = str(metadata.get("script", ""))
    title = str(metadata.get("title", ""))
    topic = str(metadata.get("topic", ""))
    issues.extend(validate_script(
        script, title, topic, metadata.get("broll_keywords", []),
        metadata.get("first_answer_quote", ""), metadata.get("evidence_record", {}),
        require_five_beats=True,
    ))
    if not title.strip() or len(title.strip()) > 95:
        issues.append("title_missing_or_too_long")
    title_score = finite_number(metadata.get("title_score", 0))
    title_clarity = finite_number(metadata.get("title_frustration", 0))
    if title_score is None or title_clarity is None:
        issues.append("title_score_invalid")
    else:
        if title_score < 24:
            issues.append("title_score_below_threshold")
        if title_clarity < 7:
            issues.append("title_clarity_below_threshold")
    if metadata.get("user_rejected") is True or str(metadata.get("human_review_status", "")).lower() in {
        "rejected", "reject", "declined", "needs_changes", "needs-changes",
    }:
        issues.append("user_rejected_episode")

    root = Path(workdir) if workdir is not None else None
    timing_path = root / "timings.json" if root else None
    words = []
    if timing_path and timing_path.is_file():
        try:
            words = json.loads(timing_path.read_text(encoding="utf-8"))
        except Exception:
            issues.append("word_timings_unreadable")
    if not isinstance(words, list) or not words:
        issues.append("verified_word_timings_missing")
        words = []
    else:
        timing_issues = validate_word_timings(words)
        issues.extend(timing_issues)
        quote = str(metadata.get("first_answer_quote", ""))
        try:
            answer_at = first_answer_time(script, words, quote)
        except (AttributeError, KeyError, TypeError, ValueError):
            answer_at = None
        if (answer_at is None or not math.isfinite(float(answer_at))
                or answer_at > MAX_FIRST_ANSWER_SECONDS):
            issues.append("first_useful_answer_after_six_seconds")

    voice = metadata.get("tts_quality")
    if not isinstance(voice, dict):
        issues.append("voice_quality_metadata_missing")
        voice = {}
    if metadata.get("voice_identity") != "Orus" or metadata.get("voice") != "Orus":
        issues.append("voice_identity_not_orus")
    if metadata.get("transcript_verified") is not True:
        issues.append("transcript_not_verified")
    if metadata.get("timing_source") != "faster-whisper-word-timestamps":
        issues.append("timing_source_not_verified_asr")
    accuracy = transcript_accuracy(script, str(metadata.get("transcript_actual", "")))
    if accuracy < MIN_TRANSCRIPT_ACCURACY:
        issues.append("transcript_mismatch")
    recorded_accuracy = finite_number(voice.get("transcript_accuracy", accuracy))
    if recorded_accuracy is None:
        issues.append("voice_quality_metric_invalid")
    elif recorded_accuracy < MIN_TRANSCRIPT_ACCURACY:
        issues.append("transcript_accuracy_below_threshold")
    voice_duration = finite_number(voice.get("duration_seconds"))
    if voice_duration is None or not TARGET_VOICE_DURATION[0] <= voice_duration <= TARGET_VOICE_DURATION[1]:
        issues.append("voice_duration_out_of_band")
    max_pause = finite_number(voice.get("max_pause_seconds"))
    if max_pause is None or max_pause > MAX_LONG_PAUSE_SECONDS:
        issues.append("voice_pause_out_of_band")
    word_cv = finite_number(voice.get("word_duration_cv"))
    if word_cv is None or word_cv < MIN_WORD_DURATION_CV:
        issues.append("voice_timing_too_even")
    pitch_span = finite_number(voice.get("pitch_span_semitones"))
    if pitch_span is None or pitch_span < MIN_PITCH_SPAN_SEMITONES:
        issues.append("voice_pitch_variation_too_low")
    if voice.get("clipping_detected") is not False:
        issues.append("voice_clipping_or_unknown")
    answer_time = finite_number(voice.get("first_answer_seconds"))
    if answer_time is None or answer_time > MAX_FIRST_ANSWER_SECONDS:
        issues.append("voice_first_answer_too_late")
    if metadata.get("tts_engine") != "gemini" or not metadata.get("tts_model"):
        issues.append("tts_engine_or_model_missing")

    beats = metadata.get("story_beats")
    shots = metadata.get("footage_shots")
    if not isinstance(beats, list) or len(beats) != EXPECTED_BEATS:
        issues.append("five_story_beats_missing")
        beats = []
    elif any(not isinstance(item, dict) for item in beats):
        issues.append("story_beat_metadata_invalid")
        beats = []
    if not isinstance(shots, list) or len(shots) != EXPECTED_BEATS:
        issues.append("five_reviewed_footage_shots_missing")
        shots = []
    elif any(not isinstance(item, dict) for item in shots):
        issues.append("footage_shot_metadata_invalid")
        shots = []
    if len(beats) == EXPECTED_BEATS and len(shots) == EXPECTED_BEATS:
        ids = [str(item.get("clip_id", "")) for item in shots]
        hashes = [str(item.get("sha256", "")) for item in shots]
        if any(not value for value in ids) or len(set(ids)) != EXPECTED_BEATS:
            issues.append("footage_clip_ids_missing_or_reused")
        if any(not value for value in hashes) or len(set(hashes)) != EXPECTED_BEATS:
            issues.append("footage_hashes_missing_or_reused")
        expected_labels = ("observation", "action_start", "detail", "change_comparison", "payoff")
        beat_labels = [str(item.get("beat", "")) for item in beats]
        if beat_labels != list(expected_labels):
            issues.append("story_beat_order_invalid")
        expected_sentences = split_sentences(script)
        if len(expected_sentences) == EXPECTED_SENTENCES and [
            str(item.get("sentence", "")).strip() for item in beats
        ] != expected_sentences:
            issues.append("story_sentence_mapping_invalid")
        actions = []
        for index, (beat, shot) in enumerate(zip(beats, shots)):
            review = shot.get("review") if isinstance(shot, dict) else None
            crop = shot.get("crop_position") if isinstance(shot, dict) else None
            if not isinstance(review, dict) or review.get("status") != "accepted":
                issues.append(f"beat_{index+1}_frame_review_missing")
            else:
                score = finite_number(review.get("score", 0))
                if score is None:
                    issues.append(f"beat_{index+1}_visual_score_invalid")
                elif score < min_visual_score:
                    issues.append(f"beat_{index+1}_visual_score_low")
                if review.get("relevant") is not True or review.get("category_match") is not True:
                    issues.append(f"beat_{index+1}_visual_category_mismatch")
                visible_action = str(review.get("visible_action", "")).strip()
                if review.get("action_visible") is not True or not visible_action:
                    issues.append(f"beat_{index+1}_action_not_reviewed")
                actions.append(" ".join(tokens(visible_action)))
                reviewed_start = finite_number(review.get("reviewed_source_start"))
                source_start_recorded = finite_number(shot.get("source_start"))
                if reviewed_start is None or source_start_recorded is None:
                    issues.append(f"beat_{index+1}_reviewed_start_invalid")
                elif abs(reviewed_start - source_start_recorded) > 0.01:
                    issues.append(f"beat_{index+1}_reviewed_start_mismatch")
            if not isinstance(crop, dict) or crop.get("x") not in {"left", "center", "right"} \
                    or crop.get("y") not in {"top", "center", "bottom"}:
                issues.append(f"beat_{index+1}_crop_position_invalid")
            if str(beat.get("beat", "")) != str(shot.get("beat", "")):
                issues.append(f"beat_{index+1}_shot_plan_order_mismatch")
            query = str(shot.get("query", "")).strip()
            queries = metadata.get("broll_keywords")
            expected_query = str(queries[index]).strip() if isinstance(queries, list) and index < len(queries) else ""
            if not query or query != expected_query:
                issues.append(f"beat_{index+1}_shot_query_mismatch")
            for key in ("provider", "provider_id", "source_url", "license", "creator", "creator_url"):
                value = shot.get(key)
                if not str(value or "").strip():
                    issues.append(f"beat_{index+1}_source_metadata_missing_{key}")
            if not str(shot.get("source_url", "")).lower().startswith(("https://", "http://")):
                issues.append(f"beat_{index+1}_source_url_invalid")
            source_start = finite_number(shot.get("source_start"))
            clip_duration = finite_number(shot.get("duration_seconds"))
            segment_duration = finite_number(beat.get("duration_seconds"))
            shot_segment_duration = finite_number(
                shot.get("segment_duration_seconds", segment_duration)
            )
            if shot_segment_duration is None or segment_duration is None \
                    or abs(shot_segment_duration - segment_duration) > 0.02:
                issues.append(f"beat_{index+1}_segment_duration_mismatch")
            if (source_start is None or clip_duration is None or segment_duration is None
                    or source_start < 0 or clip_duration <= 0 or segment_duration <= 0
                    or source_start + segment_duration > clip_duration + 0.05):
                issues.append(f"beat_{index+1}_reviewed_window_invalid")
            if root is not None:
                raw_path = Path(str(shot.get("local_path", "")))
                if raw_path.is_absolute() or raw_path.is_file():
                    clip_path = raw_path
                else:
                    clip_path = root / raw_path
                if not clip_path.is_file() or clip_path.stat().st_size == 0:
                    issues.append(f"beat_{index+1}_clip_missing_or_empty")
                else:
                    try:
                        probe = subprocess.run(
                            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", str(clip_path)],
                            capture_output=True, text=True, check=True, timeout=30,
                        )
                        actual_clip_duration = float(probe.stdout.strip())
                        if abs(actual_clip_duration - clip_duration) > 0.25 \
                                or source_start + segment_duration > actual_clip_duration + 0.05:
                            issues.append(f"beat_{index+1}_clip_duration_mismatch")
                    except Exception:
                        issues.append(f"beat_{index+1}_clip_probe_failed")
                    try:
                        digest_obj = hashlib.sha256()
                        with clip_path.open("rb") as clip_file:
                            for block in iter(lambda: clip_file.read(1024 * 1024), b""):
                                digest_obj.update(block)
                        if digest_obj.hexdigest() != str(shot.get("sha256", "")):
                            issues.append(f"beat_{index+1}_clip_hash_mismatch")
                    except OSError:
                        issues.append(f"beat_{index+1}_clip_hash_unreadable")
                samples = shot.get("sampled_frames")
                if not isinstance(samples, list) or not samples:
                    issues.append(f"beat_{index+1}_sampled_frames_missing")
                    samples = []
                for sample in samples:
                    if not isinstance(sample, dict):
                        issues.append(f"beat_{index+1}_sampled_frame_invalid")
                        continue
                    frame = Path(str(sample.get("path", "")))
                    if not frame.is_absolute():
                        frame = root / frame
                    if not frame.is_file() or frame.stat().st_size < 1000:
                        issues.append(f"beat_{index+1}_sampled_frame_invalid")
        if len(actions) == EXPECTED_BEATS and len(set(actions)) != EXPECTED_BEATS:
            issues.append("visible_actions_reused_across_beats")

    caption_quality = metadata.get("caption_quality")
    if not isinstance(caption_quality, dict) or caption_quality.get("timing_source") != "verified_word_boundaries" \
            or caption_quality.get("fade") is not False:
        issues.append("caption_quality_metadata_invalid")
    if root is not None:
        caption_path = root / "captions.ass"
        if not caption_path.is_file():
            issues.append("caption_file_missing")
        elif words:
            try:
                from captions import validate_ass
                issues.extend(validate_ass(str(caption_path), word_timings=words))
            except Exception:
                issues.append("caption_file_validation_failed")
        video_path = root / "short.mp4"
        if not video_path.is_file():
            issues.append("render_file_missing")
        else:
            expected_duration = finite_number(metadata.get("render_expected_duration_seconds"))
            if expected_duration is None or expected_duration <= 0:
                issues.append("render_expected_duration_invalid")
            render_issues, render_metrics = validate_render(
                video_path, expected_duration=expected_duration
            )
            issues.extend(render_issues)
            recorded = metadata.get("render_quality")
            if not isinstance(recorded, dict):
                issues.append("render_quality_metadata_mismatch")
            else:
                for key in ("video_codec", "audio_codec", "width", "height"):
                    if recorded.get(key) != render_metrics.get(key):
                        issues.append("render_quality_metadata_mismatch")
                        break
                for key, tolerance in (("duration_seconds", 0.75),
                                       ("mean_volume_db", 1.0), ("peak_volume_db", 1.0)):
                    old_value = finite_number(recorded.get(key))
                    current_value = finite_number(render_metrics.get(key))
                    if old_value is None or current_value is None or abs(old_value - current_value) > tolerance:
                        issues.append("render_quality_metadata_mismatch")
                        break
    render = metadata.get("render_quality")
    if not isinstance(render, dict):
        issues.append("render_quality_metadata_invalid")
    else:
        width_value = finite_number(render.get("width"))
        height_value = finite_number(render.get("height"))
        if (render.get("video_codec") != "h264" or render.get("audio_codec") != "aac"
                or width_value != 1080 or height_value != 1920):
            issues.append("render_quality_metadata_invalid")
        mean_volume = finite_number(render.get("mean_volume_db"))
        peak_volume = finite_number(render.get("peak_volume_db"))
        if mean_volume is None or peak_volume is None:
            issues.append("render_audio_level_invalid")
        elif mean_volume < -48 or peak_volume >= -0.05:
            issues.append("render_audio_level_out_of_bounds")
    return sorted(set(issues))


def record_skip_reason(path: str | Path, *, episode_id: str, topic: str, reason: str,
                       phase: str = "generation") -> None:
    """Append one machine-readable skip record; never overwrites a previous reserve."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "episode_id": episode_id,
        "topic": topic,
        "phase": phase,
        "reason": str(reason)[:600],
    }
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
