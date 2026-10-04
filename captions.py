"""
captions.py - quiet phrase-level captions for the Hidden Logic editorial pilot.
Uses the verified word timings, conservative safe-area geometry, and only one or two
meaningful highlights. No repeated pop animation or caption-led visual treatment.
"""
import json
import re

CAPTION_FONT_SIZE = 62
CAPTION_MARGIN_L = 145
CAPTION_MARGIN_R = 145
CAPTION_MARGIN_V = 390
MAX_LINE_CHARS = 24

ASS_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,Lora,{CAPTION_FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00101010,&H64000000,0,0,0,0,100,100,0,0,1,4,1,2,{CAPTION_MARGIN_L},{CAPTION_MARGIN_R},{CAPTION_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
# Bottom-center alignment is positioned above the Shorts title/progress overlay. The type
# is intentionally smaller and calmer; action remains the visual priority.

GOLD = r"{\c&H00C8FF&}"   # gold/amber in BGR (default emphasis color)
WHITE = r"{\c&HFFFFFF&}"
# Accent palette (BGR hex for ASS). Rotating the emphasis color per video is one of the
# cheap "surface signal" variations that reduce the mass-production fingerprint while
# staying on-brand (all are bright, high-contrast, readable on football footage).
ACCENT_PALETTE = {
    "gold":   r"{\c&H00C8FF&}",   # amber
    "cyan":   r"{\c&HFFE000&}",   # bright cyan
    "green":  r"{\c&H66FF66&}",   # lime
    "orange": r"{\c&H1488FF&}",   # vivid orange
}
CAPTION_FADE = ""


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _norm(w: str) -> str:
    return re.sub(r"[^\w]", "", w).lower()


def _ends_sentence(w: str) -> bool:
    """True if the word ends a complete sentence."""
    return bool(re.search(r"[.!?][\"'\)\]]*\s*$", str(w)))


def _ends_phrase(w: str) -> bool:
    return bool(re.search(r"[,;:][\"'\)\]]*\s*$", str(w)))


def _visible_len(token: str) -> int:
    """Length of a token ignoring ASS override tags like {\\c&H..&} so wrapping math is
    based on the actual visible characters, not the color codes."""
    return len(re.sub(r"\{[^}]*\}", "", token))


def _wrap_ass(parts: list[str], max_chars_per_line: int = MAX_LINE_CHARS) -> str:
    """Join phrase tokens into balanced ASS lines with a hard break before overflow."""
    lines, cur, cur_len = [], [], 0
    for tok in parts:
        vlen = _visible_len(tok)
        # +1 for the space if the line already has content
        if cur and cur_len + 1 + vlen > max_chars_per_line:
            lines.append(" ".join(cur))
            cur, cur_len = [tok], vlen
        else:
            cur.append(tok)
            cur_len += (1 + vlen) if cur_len else vlen
    if cur:
        lines.append(" ".join(cur))
    return r"\N".join(lines)


def build_ass(timings_path: str, ass_path: str, emphasis_words: list[str] | None = None,
              group_size: int = 5, accent: str | None = None, opening_group: int = 5):
    # Build emphasis lookups: single words AND multi-word phrases ("on purpose",
    # "empty space"). The old code matched single tokens only, so any multi-word emphasis
    # the script author flagged (e.g. "ONE THING") never received the gold pop.
    raw_emphasis = emphasis_words or []
    emph_single: set[str] = set()
    emph_phrases: list[list[str]] = []
    # Highlight at most two meaningful words/phrases per episode; do not auto-highlight
    # every number or every phrase boundary.
    for e in raw_emphasis[:2]:
        toks = [_norm(t) for t in str(e).split() if _norm(t)]
        if len(toks) == 1:
            emph_single.add(toks[0])
        elif len(toks) > 1:
            emph_phrases.append(toks)
    # per-video accent color (anti-sameness). Defaults to gold; accepts a palette key.
    accent_color = ACCENT_PALETTE.get(accent or "gold", GOLD)
    with open(timings_path, encoding="utf-8") as f:
        words = json.load(f)
    n = len(words)
    norm_words = [_norm(w["word"]) for w in words]
    # Precompute emphasis only for the one or two selected words/phrases.
    emph_flags = [False] * n
    for idx in range(n):
        if norm_words[idx] in emph_single:
            emph_flags[idx] = True
    for phrase in emph_phrases:
        L = len(phrase)
        for idx in range(n - L + 1):
            if norm_words[idx:idx + L] == phrase:
                for k in range(idx, idx + L):
                    emph_flags[k] = True

    lines = [ASS_HEADER]
    # Captions follow actual word boundaries in small phrase groups. Sentence boundaries always
    # end a card, and a short final hold gives the takeaway time to register without an end card.
    if not words:
        raise ValueError("Caption timing input contains no word boundaries")
    i = 0
    HOLD = 0.10
    while i < n:
        size = group_size
        # Group words into phrase-sized cards. A sentence boundary always ends a card;
        # commas and semicolons may end one after at least three words.
        chunk_idx = []
        j = i
        while j < n and len(chunk_idx) < size:
            chunk_idx.append(j)
            if _ends_sentence(words[j]["word"]):
                j += 1
                break
            if len(chunk_idx) >= 3 and _ends_phrase(words[j]["word"]):
                j += 1
                break
            j += 1
        if not chunk_idx:
            break
        nxt = j
        chunk = [words[k] for k in chunk_idx]
        natural_end = chunk[-1]["end"]
        start = float(chunk[0]["start"])
        # End each caption at its OWN last spoken word (+ a small hold), NOT at the next
        # group's start. The old code stretched every caption to fill the gap until the next
        # one, so on every sentence pause a word was shown 0.5-1.5s BEFORE it was spoken.
        end = natural_end + HOLD
        if nxt < n:
            end = min(end, words[nxt]["start"])   # never overlap / pre-empt the next caption
        else:
            end = natural_end + 0.9               # hold the final takeaway long enough to read
        if end <= start:
            end = max(natural_end, start + 0.3)
        parts = []
        for k in chunk_idx:
            token = words[k]["word"]
            if emph_flags[k]:
                parts.append(f"{accent_color}{token}{WHITE}")
            else:
                parts.append(token)
        text = _wrap_ass(parts, max_chars_per_line=MAX_LINE_CHARS)
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Word,,0,0,0,,{CAPTION_FADE}{text}")
        i = nxt
    from editorial_quality import validate_word_timings
    timing_issues = validate_word_timings(words)
    if timing_issues:
        raise ValueError("Caption timing validation failed: " + ", ".join(timing_issues))
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    caption_issues = validate_ass(ass_path, word_timings=words)
    if caption_issues:
        raise ValueError("Caption layout validation failed: " + ", ".join(caption_issues))


def validate_ass(ass_path: str, word_timings: list[dict] | None = None) -> list[str]:
    """Validate caption geometry, event timing, safe area, and transcript alignment."""
    issues = []
    with open(ass_path, encoding="utf-8") as fh:
        content = fh.read()
    if "Style: Word,Lora" not in content:
        issues.append("caption_style_missing")
    if f"Style: Word,Lora,{CAPTION_FONT_SIZE}" not in content:
        issues.append("caption_font_or_size_invalid")
    if f",2,{CAPTION_MARGIN_L},{CAPTION_MARGIN_R},{CAPTION_MARGIN_V},1" not in content:
        issues.append("caption_outside_safe_area")
    if "PlayResX: 1080" not in content or "PlayResY: 1920" not in content:
        issues.append("caption_resolution_mismatch")

    def parse_ts(value: str) -> float:
        h, m, s = value.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    events = []
    for line in content.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", 9)
        if len(fields) < 10:
            issues.append("malformed_caption_event")
            continue
        try:
            start, end = parse_ts(fields[1]), parse_ts(fields[2])
        except (ValueError, IndexError):
            issues.append("malformed_caption_timing")
            continue
        if start < 0 or end <= start:
            issues.append("invalid_caption_timing")
        events.append((start, end, fields[9]))

    if not events:
        issues.append("no_caption_events")
    events.sort(key=lambda event: event[0])
    for previous, current in zip(events, events[1:]):
        if current[0] < previous[1] - 0.02:
            issues.append("caption_events_overlap")
    for _, _, text in events:
        clean = re.sub(r"\{[^}]*\}", "", text).replace(r"\N", "\n")
        if any(len(line) > MAX_LINE_CHARS for line in clean.splitlines()):
            issues.append("caption_width_overflow")

    if word_timings is not None:
        expected = [_norm(item.get("word", "")) for item in word_timings]
        expected = [word for word in expected if word]
        spoken_index = 0
        for event_start, event_end, text in events:
            clean = re.sub(r"\{[^}]*\}", "", text).replace(r"\N", " ")
            visible = [_norm(token) for token in clean.split()]
            visible = [word for word in visible if word]
            if not visible or expected[spoken_index:spoken_index + len(visible)] != visible:
                issues.append("caption_transcript_mismatch")
                continue
            first_word = word_timings[spoken_index]
            last_word = word_timings[spoken_index + len(visible) - 1]
            if abs(event_start - float(first_word["start"])) > 0.05:
                issues.append("caption_not_aligned_to_word_boundary")
            if event_end < float(last_word["end"]) - 0.02:
                issues.append("caption_cuts_off_before_word_end")
            if event_end - float(last_word["end"]) > 1.25:
                issues.append("caption_hold_too_long")
            spoken_index += len(visible)
        if spoken_index != len(expected):
            issues.append("caption_missing_or_extra_words")
        if events and events[-1][1] - float(word_timings[-1]["end"]) < 0.6:
            issues.append("final_takeaway_hold_too_short")
    return sorted(set(issues))
