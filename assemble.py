"""
assemble.py - v2
Builds the final 1080x1920 Short with real production polish:
  - cuts between multiple background clips every ~4s (pattern interrupts)
  - subtle alternating pan motion on every clip (nothing static)
  - burned-in animated captions
  - voiceover + ducked music, with an audio fade-out
"""
import json
import os
import subprocess

SEG = 3.3          # seconds per background clip; overridden by config 'cut_seconds'
W, H = 1080, 1920
PAN_SCALE_W, PAN_SCALE_H = 1188, 2112   # 110% oversize so we can pan inside it

_FONT_CACHE = "__unset__"


def _find_brand_font(here):
    """Find the channel brand font (Anton) - a single ultra-bold condensed file dropped in the
    project folder. Anton is purpose-built for high-impact, instantly-readable Shorts captions.
    Returns a path or None."""
    import glob
    # direct file in the project root (the usual case)
    for name in ("Anton-Regular.ttf", "Anton.ttf", "anton-regular.ttf"):
        p = os.path.join(here, name)
        if os.path.exists(p):
            return p
    # also look one level down (e.g. an Anton/ folder) just in case
    hits = glob.glob(os.path.join(here, "**", "Anton*.ttf"), recursive=True)
    hits = [h for h in hits if "italic" not in os.path.basename(h).lower()]
    return hits[0] if hits else None


def _find_font():
    """Find a real .ttf/.otf font file for drawtext overlays. drawtext needs an explicit
    font path on systems where fontconfig isn't configured (notably many Windows ffmpeg
    builds). Checks for the channel brand font (Anton) first, then common system locations.
    Returns a path or None (caller then skips the overlay)."""
    global _FONT_CACHE
    if _FONT_CACHE != "__unset__":
        return _FONT_CACHE
    here = os.path.dirname(os.path.abspath(__file__))
    # 1) the channel brand font (Anton) takes priority - gives every video a consistent identity
    brand_font = _find_brand_font(here)
    if brand_font:
        _FONT_CACHE = brand_font
        return brand_font
    candidates = [
        os.path.join(here, "assets", "brand.ttf"),      # optional user-supplied brand font
        os.path.join(here, "brand.ttf"),
        # Windows
        r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\seguisb.ttf",
        r"C:\Windows\Fonts\Verdana.ttf", r"C:\Windows\Fonts\tahoma.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            _FONT_CACHE = p
            return p
    # last resort: scan the Windows font dir for any ttf
    win = r"C:\Windows\Fonts"
    if os.path.isdir(win):
        for f in os.listdir(win):
            if f.lower().endswith((".ttf", ".otf")):
                _FONT_CACHE = os.path.join(win, f)
                return _FONT_CACHE
    _FONT_CACHE = None
    return None


def _audio_duration(timings_path: str) -> float:
    with open(timings_path) as f:
        words = json.load(f)
    return words[-1]["end"] + 0.8



def _make_sfx(workdir: str):
    """Synthesize subtle sound-design assets with ffmpeg (no downloads, $0).
    Returns (whoosh_path, impact_path) or (None, None) on failure (non-fatal)."""
    import subprocess as _sp
    try:
        whoosh = os.path.join(workdir, "_whoosh.wav")
        # filtered noise swept down = a soft 'whoosh' for transitions
        _sp.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", "anoisesrc=d=0.35:c=pink:a=0.18",
                 "-af", "highpass=f=300,lowpass=f=4000,afade=t=in:d=0.05,"
                        "afade=t=out:st=0.12:d=0.23,volume=0.5",
                 whoosh], check=True, timeout=30)
        impact = os.path.join(workdir, "_impact.wav")
        # low sine thump + click = a clean 'impact' hit for the twist/reveal
        _sp.run(["ffmpeg", "-y", "-v", "error",
                 "-f", "lavfi", "-i", "sine=f=70:d=0.4",
                 "-af", "afade=t=out:st=0.06:d=0.34,volume=0.6",
                 impact], check=True, timeout=30)
        return whoosh, impact
    except Exception:
        return None, None


def _emphasis_beats(timings_path: str, emphasis_words=None, max_beats: int = 6):
    """Return timestamps (seconds) of the strongest words to zoom-punch on:
    emphasis words and numbers. Spread out so punches don't bunch up."""
    import re as _re
    try:
        words = json.load(open(timings_path))
    except Exception:
        return []
    emph = set()
    for w in (emphasis_words or []):
        emph.add(_re.sub(r"[^a-z0-9]", "", w.lower()))
    beats = []
    for w in words:
        tok = _re.sub(r"[^a-z0-9]", "", w.get("word", "").lower())
        is_num = bool(_re.search(r"\d", w.get("word", "")))
        if tok and (tok in emph or is_num):
            beats.append(w["start"])
    # thin out: keep beats at least 1.2s apart, cap the count
    out, last = [], -9
    for b in sorted(beats):
        if b - last >= 1.2:
            out.append(b); last = b
        if len(out) >= max_beats:
            break
    return out


def assemble(bg_paths: list[str], voice_path: str, timings_path: str,
             ass_path: str, out_path: str, music_path: str | None = None,
             music_volume: float = 0.10, seg_seconds: float | None = None,
             emphasis_words=None, sfx_dir: str | None = None,
             brand_label: str | None = None, fast_pacing: bool = True,
             opening_hook_text: str | None = None, show_subscribe_cue: bool = False,
             show_follow_cue: bool = False):
    duration = _audio_duration(timings_path)
    punch_beats = _emphasis_beats(timings_path, emphasis_words)
    
    if isinstance(seg_seconds, list):
        # We are using sentence-aware durations
        n_segs = min(len(seg_seconds), len(bg_paths)) if bg_paths else len(seg_seconds)
        bg_paths = list(bg_paths)[:n_segs]
        durs_array = seg_seconds[:n_segs]
        # if the total duration of clips doesn't quite match audio, scale them
        total_durs = sum(durs_array)
        durs_array = [d * (duration / total_durs) for d in durs_array] if total_durs > 0 else [duration/n_segs]*n_segs
    else:
        # Fallback to legacy fixed pacing
        if seg_seconds:
            SEG = float(seg_seconds)
        elif fast_pacing:
            SEG = 2.2
        want = max(1, int(duration // SEG) + 1)
        n_segs = min(want, len(bg_paths)) if bg_paths else want
        bg_paths = list(bg_paths)
        durs_array = [duration / n_segs] * n_segs
    
    ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")

    cmd = ["ffmpeg", "-y"]
    # inputs: loop each bg so short clips still fill their segment
    for p in bg_paths:
        cmd += ["-stream_loop", "-1", "-i", p]
    vi_voice = len(bg_paths)
    cmd += ["-i", voice_path]
    has_music = bool(music_path and os.path.exists(music_path))
    if has_music:
        cmd += ["-stream_loop", "-1", "-i", music_path]
    # sound design: synth whoosh + impact, add as inputs
    whoosh_p, impact_p = _make_sfx(os.path.dirname(out_path) or ".")
    has_sfx = bool(whoosh_p and impact_p)
    vi_whoosh = vi_impact = None
    if has_sfx:
        base_inputs = len(bg_paths) + 1 + (1 if has_music else 0)
        cmd += ["-i", whoosh_p, "-i", impact_p]
        vi_whoosh = base_inputs
        vi_impact = base_inputs + 1

    # video graph: each segment = trim + oversize scale + panning crop
    fc = []
    seg_labels = []
    # Probe each b-roll clip's real duration once, so reuse offsets (below) can never trim
    # past the end of a short clip. A failed probe stores None -> that clip simply never
    # gets an offset (safe fallback to old behavior).
    def _probe_dur(p):
        try:
            r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                                "-of", "csv=p=0", p], capture_output=True, text=True, timeout=15)
            return float(r.stdout.strip())
        except Exception:
            return None
    _bg_durs = [_probe_dur(p) for p in bg_paths]
    _src_use_count = {}

    for s in range(n_segs):
        seg_len = durs_array[s]
        frames = int(seg_len * 30)
        # one distinct clip per segment, in order (no repeats within the video). EXCEPTION:
        # the LAST segment reuses the FIRST clip so the closing visual matches the opening -
        # a "perfect loop" (research: the strongest retention signal, pushes >100% replays).
        if n_segs >= 3 and s == n_segs - 1:
            src = 0
        else:
            src = s % len(bg_paths)
        # REUSE OFFSET: when clip supply < segment count, the same clip serves multiple segments.
        # Previously every segment trimmed from t=0, so a reused clip replayed its EXACT same
        # opening seconds - visibly "the same clip again". Now each reuse advances its start
        # offset (~3.5s stride, clamped to the clip's real length), so reuse #2 shows a later
        # window of the footage - it reads as a different shot of the same scene, which is
        # exactly what scene consistency wants. The loop-back final segment stays at t=0 ON
        # PURPOSE: it must mirror the opening frame for the seamless loop. Probe failures
        # fall back to offset 0 (today's behavior, no worse).
        if n_segs >= 3 and s == n_segs - 1:
            start_off = 0.0
        else:
            prior_uses = _src_use_count.get(src, 0)
            clip_dur = _bg_durs[src]
            start_off = 0.0
            if prior_uses > 0 and clip_dur and clip_dur > (seg_len + 0.1):
                start_off = min(prior_uses * 3.5, max(0.0, clip_dur - seg_len - 0.05))
            _src_use_count[src] = prior_uses + 1
        base = (f"[{src}:v]trim=start={start_off:.2f}:duration={seg_len},"
                f"setpts=PTS-STARTPTS,"
                f"scale={PAN_SCALE_W}:{PAN_SCALE_H}:force_original_aspect_ratio=increase,"
                f"crop={PAN_SCALE_W}:{PAN_SCALE_H},setsar=1,fps=30,")
        kind = s % 3
        if kind == 2:
            # slow push-in (zoom) for every third segment
            motion = (f"zoompan=z='1+0.10*on/{frames}':"
                      f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s={W}x{H}:fps=30,")
        else:
            x_expr = f"(in_w-{W})*(t/{seg_len:.3f})" if kind == 0 else f"(in_w-{W})*(1-t/{seg_len:.3f})"
            motion = f"crop={W}:{H}:x='{x_expr}':y='(in_h-{H})/2',"
        fc.append(base + motion + f"format=yuv420p[v{s}]")
        seg_labels.append(f"[v{s}]")
    fc.append("".join(seg_labels) + f"concat=n={n_segs}:v=1:a=0[vcat]")
    fc.append(
        # Cinematic grade: a gentle S-curve for contrast depth, a slight cool-shadow / warm-
        # highlight push (the subtle "teal-orange" look that makes stock footage read as graded),
        # richer saturation, light sharpening, and a soft vignette. This is the difference between
        # "raw Pexels clip" and "looks colour-graded by an editor" - all free, all in one pass.
        "[vcat]curves=preset=medium_contrast,"
        "eq=contrast=1.08:brightness=0.012:saturation=1.20:gamma=0.98,"
        "colorbalance=rs=-0.04:gs=-0.01:bs=0.04:rh=0.04:gh=0.01:bh=-0.03,"
        "unsharp=5:5:0.45:5:5:0.0,vignette=angle=PI/4.6"
        # (removed the burned-in gold progress bar: it sat in the bottom 10px, exactly where
        #  YouTube's own Shorts progress bar + title overlay it, so it was redundant/covered.)
        "[vgrade]"
    )
    # ZOOM-PUNCH on emphasis beats: brief scale pulse synced to key words (a real
    # editor's punch-in on emphasis). Build a piecewise zoom expression over 't'.
    if punch_beats:
        PW = 0.34          # full pulse width (seconds)
        AMP = 0.08         # 8% zoom punch
        h = PW / 2.0
        # zoompan exposes 'on' (output frame index); time = on/30. Build a sum of
        # triangular pulses using between() (supported) instead of abs() (not).
        tt = "(on/30)"
        terms = []
        for b in punch_beats:
            # rise covers [b-h, b], fall covers (b, b+h]; the tiny gap at b prevents
            # both firing at the center (which would double the punch to 16%).
            rise = rf"between({tt}\,{b-h:.3f}\,{b:.3f})*(({tt}-{b-h:.3f})/{h:.3f})"
            fall = rf"between({tt}\,{b+0.001:.3f}\,{b+h:.3f})*((({b+h:.3f})-{tt})/{h:.3f})"
            terms.append(f"({rise}+{fall})")
        zexpr = f"1+{AMP}*(" + "+".join(terms) + ")"
        OS_W, OS_H = int(W*1.18), int(H*1.18)
        fc.append(
            f"[vgrade]scale={OS_W}:{OS_H},setsar=1,"
            f"zoompan=z='{zexpr}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:"
            f"s={W}x{H}:fps=30[vpunch]")
        punch_label = "[vpunch]"
    else:
        punch_label = "[vgrade]"
    # LOOP AID: a very short fade at the tail so the loop point is seamless, not a hard
    # cut (pairs with the audio fade). Keeps retention-boosting loops smooth.
    loop_fade = 0.25
    lf_start = max(0.0, duration - loop_fade)
    # VISUAL SIGNATURE (channel branding, on every video so it's recognizable in-feed and
    # in screenshots/reshares): a persistent "Hidden Logic" wordmark top-left, plus an optional
    # franchise badge top-right naming the series ("HOT TAKE", "CALLED IT", etc). Both sit
    # in the top band, clear of the centre caption column and the bottom YouTube UI.
    # IMPORTANT: drawtext resolves fonts via fontconfig, which is often MISSING on Windows
    # ffmpeg builds (libass/subtitles use DirectWrite instead, so captions work but drawtext
    # would crash with "Cannot load default config file"). So we find a real font file and
    # pass it explicitly. If none is found, we skip the branding overlay rather than fail the
    # whole video - the channel survives without a wordmark; it must not lose the upload.
    def _esc(t):
        return t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019").replace("%", "\\%")

    def _wrap_hook(text, width):
        # wrap the opening-hook text to at most ~2 lines so it never runs off-screen.
        words = text.strip().split()
        lines, cur = [], ""
        for w in words:
            if len(cur) + len(w) + 1 <= width:
                cur = (cur + " " + w).strip()
            else:
                lines.append(cur)
                cur = w
            if len(lines) == 2:        # cap at 2 lines; drop anything that would overflow
                break
        if cur and len(lines) < 2:
            lines.append(cur)
        return "\n".join(lines[:2])

    def _ff(path):  # escape a font path for an ffmpeg filter (Windows backslashes + colon)
        return path.replace("\\", "/").replace(":", "\\:")

    font = _find_font()
    if font:
        ff = f":fontfile='{_ff(font)}'"
        brand = ("drawtext=text='Hidden Logic':x=40:y=186:fontsize=46:fontcolor=white:"
                 "box=1:boxcolor=0x000000@0.55:boxborderw=16:"
                 "shadowcolor=0x000000@0.7:shadowx=2:shadowy=2" + ff)
        badge = ""
        if brand_label:
            bl = _esc(brand_label.upper())
            badge = (f",drawtext=text='{bl}':x=w-tw-40:y=46:fontsize=40:"
                     "fontcolor=0x101010:box=1:boxcolor=0xFFC800@0.92:boxborderw=14" + ff)
        # SUBSCRIBE CUE: a bold on-screen prompt in the final ~3s. OFF by default now that the
        # channel uses ABRUPT endings (an end CTA is exactly the wind-down that abrupt endings
        # avoid to protect retention). Set show_subscribe_cue=True in config to bring it back.
        sub = ""
        if show_subscribe_cue:
            sub_start = max(0.0, duration - 3.0)
            sub = (f",drawtext=text='SUBSCRIBE':x=(w-tw)/2:y=h*0.70:fontsize=72:"
                   "fontcolor=white:box=1:boxcolor=0xCC0000@0.92:boxborderw=22:"
                   "shadowcolor=0x000000@0.7:shadowx=3:shadowy=3:"
                   f"enable='gte(t,{sub_start:.2f})'" + ff)
        # PERSISTENT FOLLOW CUE: a SMALL, subtle "follow for more" tucked under the wordmark,
        # shown for the WHOLE video. Unlike the big end-card SUBSCRIBE above, this is NOT a
        # wind-down - it never interrupts the abrupt ending or the seamless loop, so it doesn't
        # cost retention. But because ~80% watch muted and never read the description, a constant
        # tiny visual nudge is the one place a "follow" ask can lift sub-conversion without a
        # trade-off. Sits just below the top-left "Hidden Logic" wordmark, out of the caption zone.
        # Toggle via show_follow_cue in config (default off; test it for ~1 week and watch subs).
        follow = ""
        if show_follow_cue:
            follow = (",drawtext=text='\u25B6 follow for more':x=44:y=244:fontsize=30:"
                      "fontcolor=0xFFFFFF@0.92:box=1:boxcolor=0x000000@0.30:boxborderw=10:"
                      "shadowcolor=0x000000@0.6:shadowx=2:shadowy=2" + ff)
        # OPENING TEXT HOOK: a big bold claim on-screen for the first ~2.8s. Research: on-
        # screen text during the hook lifts watch time ~18% on faceless Shorts, because most
        # viewers watch the first second with sound off and the text is what stops the swipe.
        # Sits in the upper-middle, above the spoken-caption zone. Toggle: pass
        # opening_hook_text=None (or "fast_pacing"/hook off in config) to skip.
        # TEXTUAL HOOK (the third hook): a SHORT punchy line that AMPLIFIES the curiosity gap,
        # shown big at the top for the first ~2.3s - distinct from the centre captions (which
        # carry the spoken words). Top Shorts use a triple hook (visual + spoken + on-screen
        # text); subtitles alone are not a hook. ~80% watch the first second muted, so this line
        # plus the first frame sell the click. opening_hook_text now carries the script's
        # distinct 'text_hook' (e.g. "ON PURPOSE", "YOU'VE BEEN TRICKED"), NOT the narration.
        hook_overlay = ""
        if opening_hook_text and opening_hook_text.strip():
            _ht = _esc(opening_hook_text.strip().upper()[:34])
            hook_overlay = (
                f",drawtext=text='{_ht}':x=(w-tw)/2:y=h*0.13:fontsize=58:fontcolor=0xFFC800:"
                "box=1:boxcolor=0x000000@0.55:boxborderw=18:"
                "shadowcolor=0x000000@0.7:shadowx=2:shadowy=2:"
                "enable='lte(t,2.3)'" + ff)
        brand_chain = f"{brand}{badge}{sub}{follow}{hook_overlay},"
    else:
        print("[assemble] no usable font found for branding overlay - skipping wordmark "
              "(video still builds normally)")
        brand_chain = ""
    # Tell libass where to find the brand font (Anton) so captions render in it. Without a
    # fontsdir, libass falls back to a system font even if the ASS asks for Anton by name.
    # Anton sits in the project root, so point fontsdir there.
    here_dir = os.path.dirname(os.path.abspath(__file__))
    fontsdir_opt = ":fontsdir='" + here_dir.replace("\\", "/").replace(":", "\\:") + "'"
    fc.append(f"{punch_label}subtitles='{ass_escaped}'{fontsdir_opt},{brand_chain}"
              f"fade=t=out:st={lf_start:.2f}:d={loop_fade}:color=black[vout]")

    # audio graph
    fade_start = max(0.0, duration - 0.6)
    voice_fx = ("highpass=f=85,acompressor=threshold=-18dB:ratio=3:attack=8:release=120,"
                "equalizer=f=3200:t=q:w=1.2:g=2")
    # base voice (+music) bus first
    if has_music:
        fc.append(f"[{vi_voice}:a]{voice_fx}[vx]")
        fc.append(f"[{vi_voice+1}:a]volume={music_volume:.2f}[m]")
        # normalize=0 so adding the music bed does NOT halve the voice (amix otherwise divides
        # by the input count); loudnorm downstream sets the final integrated loudness.
        fc.append(f"[vx][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[abed]")
    else:
        fc.append(f"[{vi_voice}:a]{voice_fx}[abed]")

    if has_sfx:
        # whoosh at each internal cut boundary; impact once at the twist (~65%)
        sfx_labels = []
        k = 0
        # Whoosh at each REAL internal cut boundary = the cumulative sum of segment durations.
        # The old code used `s * seg_len`, where seg_len was the LAST segment's length leaked
        # from the video loop, so whooshes landed on an arbitrary uniform grid and never on the
        # actual (variable-length) cuts they are meant to punctuate.
        cut_acc = 0.0
        for s in range(0, n_segs - 1):                  # boundary AFTER segment s
            cut_acc += durs_array[s]
            if cut_acc > duration - 0.3:
                break
            delay_ms = int(cut_acc * 1000)
            fc.append(f"[{vi_whoosh}:a]adelay={delay_ms}|{delay_ms},volume=0.45[wh{k}]")
            sfx_labels.append(f"[wh{k}]"); k += 1
        impact_t = max(0.0, duration * 0.50)  # 50% mark: research's 2nd-biggest drop point
        idelay = int(impact_t * 1000)
        fc.append(f"[{vi_impact}:a]adelay={idelay}|{idelay},volume=0.6[imp]")
        sfx_labels.append("[imp]")
        # mix bed + all sfx, then master
        fc.append(f"[abed]{''.join(sfx_labels)}amix=inputs={1+len(sfx_labels)}:"
                  f"duration=first:dropout_transition=0:normalize=0,"
                  f"loudnorm=I=-14:TP=-1.5:LRA=9,"
                  f"afade=t=out:st={fade_start:.2f}:d=0.6[aout]")
    else:
        fc.append(f"[abed]loudnorm=I=-14:TP=-1.5:LRA=9,"
                  f"afade=t=out:st={fade_start:.2f}:d=0.6[aout]")

    cmd += ["-filter_complex", ";".join(fc),
            "-map", "[vout]", "-map", "[aout]",
            "-t", f"{duration:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            out_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # clean up synthesized SFX temp files (don't litter the workdir)
    for _p in (whoosh_p, impact_p):
        try:
            if _p and os.path.exists(_p):
                os.remove(_p)
        except Exception:
            pass
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + proc.stderr[-2000:])
    # Two-pass loudnorm post-process so output hits -14 LUFS precisely (single-pass lands ~1 LU
    # quiet, so Shorts sound softer than competitors in-feed). Best-effort, keeps original on fail.
    _normalize_loudness(out_path)
    return out_path


def _normalize_loudness(path: str, target_i: float = -14.0, target_tp: float = -1.5, target_lra: float = 9.0):
    """Optional 2-pass loudnorm: measure the rendered file, then re-apply loudnorm with the
    measured values so the output hits the target LUFS precisely. Audio-only re-encode (video is
    copied, so it's fast and lossless). Best-effort - on ANY error the original file is untouched."""
    try:
        import re as _re, json as _json
        measure = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
             f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json",
             "-f", "null", "-"],
            capture_output=True, text=True)
        m = _re.search(r"\{[^{}]*\"input_i\"[\s\S]*?\}", measure.stderr or "")
        if not m:
            return
        st = _json.loads(m.group(0))
        af = (f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:"
              f"measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
              f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}:"
              f"offset={st.get('target_offset', '0.0')}:linear=true")
        tmp = path + ".norm.mp4"
        r2 = subprocess.run(
            ["ffmpeg", "-hide_banner", "-y", "-i", path, "-af", af,
             "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", tmp],
            capture_output=True, text=True)
        if r2.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 1000:
            os.replace(tmp, path)
        elif os.path.exists(tmp):
            os.remove(tmp)
    except Exception:
        pass
