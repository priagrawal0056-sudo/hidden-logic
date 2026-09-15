"""
captions.py - v2
Word timings -> .ass subtitles with the modern Shorts look:
pop-in scale animation per caption, gold highlight on emphasis words
(numbers, names, superlatives picked by the script generator).
"""
import json
import re

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,Anton,88,&H00FFFFFF,&H00FFFFFF,&H00101010,&HC8000000,0,0,0,0,100,100,1,0,1,5,2,8,110,210,1240,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
# Alignment 8 = top-center anchor; MarginV 540 drops the caption block to ~28% from the
# top, parking it in the SAFE central band. This keeps text clear of YouTube's Shorts UI:
# the bottom ~15% (progress bar, title, channel) and the right ~12% (like/comment/share/
# remix buttons). Left/right margins of 140px add extra horizontal safety. Research: text
# under the UI overlays gets covered and drives instant swipes.

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
POP = r"{\q2}"  # Stable phrase captions, without a size pulse.
POP_FIRST = r"{\q2}"  # Stable phrase captions, without a size pulse.
# OPENING HOOK style: holds a full hook PHRASE (several words) on the first frame, which is
# what the Shorts feed grabs as the de-facto thumbnail. Pops in but stays at 100% (not 115%)
# so a longer phrase doesn't overflow, and \q2 keeps natural word-wrapping to 2-3 lines.
POP_HOOK = r"{\q2}"  # Stable phrase captions, without a size pulse.


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _norm(w: str) -> str:
    return re.sub(r"[^\w]", "", w).lower()


def _ends_sentence(w: str) -> bool:
    """True if the word visually ends a sentence/clause, so a caption group should not
    pair it with the first word of the next sentence (e.g. avoid 'TRICK. THE' cards)."""
    return bool(re.search(r"[.!?,;][\"'\)\]]*\s*$", str(w)))


def _visible_len(token: str) -> int:
    """Length of a token ignoring ASS override tags like {\\c&H..&} so wrapping math is
    based on the actual visible characters, not the color codes."""
    return len(re.sub(r"\{[^}]*\}", "", token))


def _wrap_ass(parts: list[str], max_chars_per_line: int = 22) -> str:
    """Join colored tokens into ASS text with hard line breaks (\\N) so a long opening hook
    phrase wraps to 2-3 balanced lines instead of overflowing one line off-screen."""
    if not parts:
        return ''
    if len(parts) == 1 or _visible_len(' '.join(parts)) <= max_chars_per_line:
        return ' '.join(parts)
    split = min(range(1,len(parts)), key=lambda i: max(_visible_len(' '.join(parts[:i])), _visible_len(' '.join(parts[i:]))))
    return ' '.join(parts[:split]) + r'\N' + ' '.join(parts[split:])


def build_ass(timings_path: str, ass_path: str, emphasis_words: list[str] | None = None,
              group_size: int = 5, accent: str | None = None, opening_group: int = 5):
    # Build emphasis lookups: single words AND multi-word phrases ("on purpose",
    # "empty space"). The old code matched single tokens only, so any multi-word emphasis
    # the script author flagged (e.g. "ONE THING") never received the gold pop.
    raw_emphasis = emphasis_words or []
    emph_single: set[str] = set()
    emph_phrases: list[list[str]] = []
    for e in raw_emphasis:
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
    # Precompute which word indices get the accent color (singles, any token with a digit,
    # and every token inside a matched multi-word emphasis phrase).
    emph_flags = [False] * n
    for idx in range(n):
        if norm_words[idx] in emph_single or re.search(r"\d", words[idx]["word"]):
            emph_flags[idx] = True
    for phrase in emph_phrases:
        L = len(phrase)
        for idx in range(n - L + 1):
            if norm_words[idx:idx + L] == phrase:
                for k in range(idx, idx + L):
                    emph_flags[k] = True

    lines = [ASS_HEADER]
    # THE OPENING FRAME doubles as the feed's de-facto thumbnail (Shorts shows an auto-grabbed
    # first frame, not a custom thumbnail). So the FIRST caption shows a coherent hook phrase
    # (a complete claim stops the scroll far better than a 2-word fragment). After that, fall
    # back to fast 2-word pops. Grouping is SENTENCE-AWARE: a group never pairs the last word
    # of one sentence with the first word of the next ("TRICK. THE").
    i = 0
    first = True
    HOLD = 0.12          # small hold so a caption doesn't vanish the instant the word ends
    OPENING_HOLD = 0.6   # the hook claim lingers a touch longer (it is the de-facto thumbnail)
    while i < n:
        size = opening_group if first else group_size
        # Keep short clauses together and avoid leaving a tiny verb phrase alone.
        remaining = 0
        for word in words[i:i+10]:
            remaining += 1
            if _ends_sentence(word['word']):
                break
        if not first and 6 <= remaining <= 7:
            size = remaining
        elif not first and 8 <= remaining <= 9:
            size = remaining - 5
        # Accumulate up to `size` words, but stop early at a sentence boundary so the
        # sentence-ending word is the LAST word in its card.
        chunk_idx = []
        j = i
        while j < n and len(chunk_idx) < size:
            chunk_idx.append(j)
            if _ends_sentence(words[j]["word"]):
                j += 1
                break
            j += 1
        if not chunk_idx:
            break
        nxt = j
        chunk = [words[k] for k in chunk_idx]
        natural_end = chunk[-1]["end"]
        start = 0.0 if first else chunk[0]["start"]   # hook text on screen from frame 0
        # End each caption at its OWN last spoken word (+ a small hold), NOT at the next
        # group's start. The old code stretched every caption to fill the gap until the next
        # one, so on every sentence pause a word was shown 0.5-1.5s BEFORE it was spoken.
        end = natural_end + (OPENING_HOLD if first else HOLD)
        if nxt < n:
            end = min(end, words[nxt]["start"])   # never overlap / pre-empt the next caption
        else:
            end = natural_end + 0.5               # hold the final card a little longer
        if end <= start:
            end = max(natural_end, start + 0.3)
        parts = []
        for k in chunk_idx:
            token = words[k]["word"].upper()
            if emph_flags[k]:
                parts.append(f"{accent_color}{token}{WHITE}")
            else:
                parts.append(token)
        text = _wrap_ass(parts, max_chars_per_line=22)
        from PIL import ImageFont
        from assemble import _find_font
        font_path = _find_font()
        if not font_path:
            raise RuntimeError('Caption font unavailable for safe-zone measurement')
        visible = re.sub(r'\{[^}]*\}', '', text).split(r'\N')
        size = 88
        while size >= 32:
            font = ImageFont.truetype(font_path, size)
            if max(font.getlength(line) + len(line) for line in visible) <= 740 and len(visible)*(size*1.25) <= 350:
                break
            size -= 2
        if size < 32:
            raise ValueError('Caption cannot fit the safe zone')
        text = rf'{{\fs{size}}}' + text
        style = POP_HOOK if first else POP
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Word,,0,0,0,,{style}{text}")
        i = nxt
        first = False
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
