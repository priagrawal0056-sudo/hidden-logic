"""Write a static, local-first review page for existing Hidden Logic renders.

This adapts the useful review-before-upload idea from the referenced studio without
adding a web server, approval endpoint, uploader, or alternate video pipeline.
"""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
from urllib.parse import quote, urlparse


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _safe_url(root: Path, target: Path) -> str:
    """Return a relative URL only when target is contained in the review package."""
    try:
        relative = target.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return ""
    return quote(relative.as_posix(), safe="/._-()")


def _resolve_workdir(root: Path, entry: dict) -> Path | None:
    raw = entry.get("workdir")
    if raw:
        path = Path(str(raw))
        candidates = [path.resolve()] if path.is_absolute() else [
            (Path.cwd() / path).resolve(),
            (root / path).resolve(),
        ]
    else:
        pilot_id = str(entry.get("pilot_id") or "")
        candidates = [(root / pilot_id).resolve()] if pilot_id else [root.resolve()]

    for candidate in candidates:
        try:
            candidate.relative_to(root.resolve())
            return candidate
        except (OSError, ValueError):
            continue
    return None


def _load_meta(entry: dict, workdir: Path | None) -> dict:
    supplied = entry.get("meta")
    if isinstance(supplied, dict):
        return supplied
    if workdir is None:
        return {}
    try:
        value = json.loads((workdir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _external_source_link(raw_url: object) -> str:
    url = str(raw_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.username or parsed.password:
        return ""
    # Source-page links do not need query strings; omit them to avoid carrying signed
    # or credential-like URL parameters into a downloadable review artifact.
    return parsed._replace(query="", fragment="").geturl()


def _finite_seconds(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 and number < float("inf") else None


def _format_time(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:04.1f}"


def _definition_rows(rows: list[tuple[str, object]]) -> str:
    return "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(_text(value))}</dd>"
        for label, value in rows if value not in (None, "")
    )


def _story_block(meta: dict) -> str:
    beats = meta.get("story_beats")
    if not isinstance(beats, list) or not beats:
        return ""
    rows = []
    cursor = 0.0
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            continue
        label = html.escape(_text(beat.get("beat") or f"Beat {index + 1}"))
        sentence = html.escape(_text(beat.get("sentence")))
        duration = _finite_seconds(beat.get("duration_seconds"))
        if duration is not None and duration > 0:
            start_label = _format_time(cursor)
            end_label = _format_time(cursor + duration)
            control = (
                f'<button type="button" class="beat-jump" data-seek="{cursor:.3f}">'
                f'{label} · {start_label}–{end_label}</button>'
            )
            cursor += duration
        else:
            control = f'<span class="beat-label">{label}</span>'
        rows.append(f'<li>{control}<p>{sentence}</p></li>')
    quote = html.escape(_text(meta.get("first_answer_quote")))
    answer_time = _finite_seconds((meta.get("tts_quality") or {}).get("first_answer_seconds")
                                  if isinstance(meta.get("tts_quality"), dict) else None)
    answer_note = ""
    if quote:
        timing = f" at {_format_time(answer_time)}" if answer_time is not None else ""
        answer_note = f'<p class="answer-note"><strong>Early answer{timing}:</strong> {quote}</p>'
    if not rows and not answer_note:
        return ""
    return (
        '<details class="story"><summary>Five-beat story and narration timing</summary>'
        f'{answer_note}<ol class="beat-list">{"".join(rows)}</ol></details>'
    )


def _evidence_block(meta: dict) -> str:
    record = meta.get("evidence_record")
    if not isinstance(record, dict) or not record:
        return ""
    mechanism = html.escape(_text(record.get("mechanism")))
    claims = record.get("supported_claims")
    claim_list = "".join(
        f"<li>{html.escape(_text(claim))}</li>"
        for claim in claims if _text(claim).strip()
    ) if isinstance(claims, list) else ""
    sources = []
    source_records = record.get("sources")
    if isinstance(source_records, list):
        for source in source_records:
            if not isinstance(source, dict):
                continue
            title = html.escape(_text(source.get("title") or source.get("url") or "Evidence source"))
            url = _external_source_link(source.get("url"))
            if url:
                sources.append(
                    f'<li><a href="{html.escape(url, quote=True)}" '
                    f'target="_blank" rel="noopener noreferrer">{title}</a></li>'
                )
            else:
                sources.append(f"<li>{title}</li>")
    sections = []
    if mechanism:
        sections.append(f'<p><strong>Mechanism:</strong> {mechanism}</p>')
    if claim_list:
        sections.append(f'<h4>Supported claims</h4><ul>{claim_list}</ul>')
    if sources:
        sections.append(f'<h4>Grounded sources</h4><ul>{"".join(sources)}</ul>')
    if not sections:
        return ""
    return '<details class="evidence"><summary>Evidence and claim support</summary>' + "".join(sections) + "</details>"


def _voice_checks(meta: dict) -> str:
    quality = meta.get("tts_quality") if isinstance(meta.get("tts_quality"), dict) else {}
    accuracy = _finite_seconds(quality.get("transcript_accuracy"))
    accuracy_display = f"{accuracy:.1%}" if accuracy is not None and accuracy <= 1 else None
    first_answer = _finite_seconds(quality.get("first_answer_seconds"))
    rows = [
        ("Identity", meta.get("voice_identity") or meta.get("voice")),
        ("Editorial direction (review only)", meta.get("voice_direction")),
        ("Style prompt sent to TTS", "no" if meta.get("tts_style_prompt_sent") is False else meta.get("tts_style_prompt_sent")),
        ("Style prompt", meta.get("tts_style_prompt")),
        ("Engine / model", f"{meta.get('tts_engine', '')} / {meta.get('tts_model', '')}".strip(" /")),
        ("Take", meta.get("tts_take")),
        ("Transcript match", accuracy_display),
        ("First answer", f"{first_answer:.2f}s" if first_answer is not None else None),
        ("Spoken duration", quality.get("duration_seconds")),
        ("Longest pause", quality.get("max_pause_seconds")),
        ("Pitch range (semitones)", quality.get("pitch_span_semitones")),
        ("Word-timing variation", quality.get("word_duration_cv")),
        ("Clipping detected", quality.get("clipping_detected")),
        ("Timing source", meta.get("timing_source")),
    ]
    body = _definition_rows(rows)
    transcript = html.escape(_text(meta.get("transcript_actual")))
    transcript_block = (
        f'<details class="heard"><summary>Listen-check transcript</summary><p>{transcript}</p></details>'
        if transcript else ""
    )
    if not body and not transcript:
        return ""
    return '<details class="voice-check"><summary>Voice and transcript checks</summary><dl>' + body + '</dl>' + transcript_block + '</details>'


def _technical_checks(meta: dict) -> str:
    caption = meta.get("caption_quality") if isinstance(meta.get("caption_quality"), dict) else {}
    render = meta.get("render_quality") if isinstance(meta.get("render_quality"), dict) else {}
    rows = [
        ("Caption timing", caption.get("timing_source")),
        ("Caption fade", caption.get("fade")),
        ("Phrase-level captions", caption.get("phrase_level")),
        ("Video format", f"{render.get('width', '')} × {render.get('height', '')}".strip(" ×")),
        ("Video / audio codec", f"{render.get('video_codec', '')} / {render.get('audio_codec', '')}".strip(" /")),
        ("Render duration (seconds)", render.get("duration_seconds")),
        ("Mean / peak audio (dB)", f"{render.get('mean_volume_db', '')} / {render.get('peak_volume_db', '')}".strip(" /")),
    ]
    body = _definition_rows(rows)
    if not body:
        return ""
    return '<details class="technical"><summary>Caption and render checks</summary><dl>' + body + '</dl></details>'


def _shot_card(root: Path, workdir: Path | None, shot: dict, index: int) -> str:
    beat = html.escape(_text(shot.get("beat") or f"Beat {index + 1}"))
    review = shot.get("review") if isinstance(shot.get("review"), dict) else {}
    crop = shot.get("crop_position") if isinstance(shot.get("crop_position"), dict) else {}
    visible_action = html.escape(_text(review.get("visible_action")))
    details = [
        ("Search query", shot.get("query")),
        ("Provider", shot.get("provider")),
        ("Creator", shot.get("creator")),
        ("License", shot.get("license")),
        ("Reviewed source start", shot.get("source_start")),
        ("Crop", f"x={crop.get('x', '')}, y={crop.get('y', '')}" if crop else ""),
        ("Visible action", review.get("visible_action")),
        ("Frame-review status", review.get("status")),
        ("Frame-review score", review.get("score")),
        ("Frame-review note", review.get("reason")),
    ]
    rows = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(_text(value))}</dd>"
        for label, value in details if value not in (None, "")
    )
    source_url = _external_source_link(shot.get("source_url"))
    source = (
        f'<p><a href="{html.escape(source_url, quote=True)}" '
        'target="_blank" rel="noopener noreferrer">Open stock source</a></p>'
        if source_url else ""
    )
    frame_links = []
    if workdir is not None:
        for sample in shot.get("sampled_frames", []) if isinstance(shot.get("sampled_frames"), list) else []:
            if not isinstance(sample, dict) or not sample.get("path"):
                continue
            sample_path = Path(str(sample["path"]))
            if not sample_path.is_absolute():
                sample_path = workdir / sample_path
            href = _safe_url(root, sample_path)
            if href and sample_path.is_file():
                timestamp = html.escape(_text(sample.get("time_seconds")))
                frame_links.append(
                    f'<a href="{html.escape(href, quote=True)}">{timestamp}s</a>'
                )
    samples = (
        "<p class=\"samples\"><strong>Reviewed frames:</strong> "
        + " · ".join(frame_links) + "</p>"
        if frame_links else ""
    )
    return (
        '<article class="shot">'
        f"<h4>{beat}</h4>"
        f"<p class=\"action\">{visible_action or 'Visible action not recorded.'}</p>"
        f"<dl>{rows}</dl>{source}{samples}"
        "</article>"
    )


def _episode_card(root: Path, entry: dict, index: int) -> str:
    workdir = _resolve_workdir(root, entry)
    meta = _load_meta(entry, workdir)
    title = _text(meta.get("title") or entry.get("title") or entry.get("pilot_id") or f"Draft {index + 1}")
    topic = _text(meta.get("topic") or entry.get("topic"))
    status = _text(entry.get("status") or "preview_ready")
    skip_reason = _text(entry.get("skip_reason"))
    video_url = _safe_url(root, workdir / "short.mp4") if workdir is not None else ""
    video_exists = bool(video_url and (workdir / "short.mp4").is_file())
    video = (
        '<video controls playsinline preload="metadata">'
        f'<source src="{html.escape(video_url, quote=True)}" type="video/mp4">'
        "Your browser does not support local video playback.</video>"
        if video_exists else '<div class="no-video">No rendered MP4 in this slot.</div>'
    )
    script = html.escape(_text(meta.get("script") or meta.get("narration")))
    script_block = (
        f'<details class="script"><summary>Read the narration</summary><pre>{script}</pre></details>'
        if script else ""
    )
    # Pilot/report summaries may omit fields that live in meta.json; fill the identity
    # fields from the batch entry without replacing richer per-take measurements.
    meta = dict(meta)
    for key, fallback in (("voice_identity", entry.get("voice")),
                          ("voice_direction", entry.get("voice_direction")),
                          ("tts_model", entry.get("tts_model"))):
        if not meta.get(key) and fallback:
            meta[key] = fallback
    voice_block = _voice_checks(meta)
    story_block = _story_block(meta)
    evidence_block = _evidence_block(meta)
    technical_block = _technical_checks(meta)
    shot_records = meta.get("footage_shots")
    shots_html = "".join(
        _shot_card(root, workdir, shot, shot_index)
        for shot_index, shot in enumerate(shot_records)
        if isinstance(shot, dict)
    ) if isinstance(shot_records, list) else ""
    shots_block = (
        f'<details class="sources"><summary>Footage, action, crop, and source records ({len(shot_records)})</summary>'
        f'<div class="shots">{shots_html}</div></details>'
        if shots_html else ""
    )
    reason_block = (
        f'<p class="reason"><strong>Skip reason:</strong> {html.escape(skip_reason)}</p>'
        if skip_reason else ""
    )
    human_status = _text(entry.get("human_review_status") or meta.get("human_review_status") or "pending")
    safe_status = html.escape(status.replace("_", " ").title())
    return (
        f'<section class="episode" id="episode-{index + 1}">'
        '<div class="episode-head">'
        f'<div><p class="eyebrow">{html.escape(_text(entry.get("pilot_id") or f"Draft {index + 1}"))}</p>'
        f'<h2>{html.escape(title)}</h2>'
        f'<p class="topic">{html.escape(topic)}</p></div>'
        f'<span class="status">{safe_status}</span></div>'
        f'<div class="media">{video}</div>'
        f'{voice_block}{story_block}{evidence_block}{technical_block}'
        f'{reason_block}{script_block}{shots_block}'
        f'<p class="human"><strong>Human review:</strong> {html.escape(human_status)}. '
        'This page cannot approve or publish a video.</p>'
        '</section>'
    )


def write_review_page(output_dir: str | Path, entries: list[dict], *,
                      title: str = "Hidden Logic video review") -> Path:
    """Write an offline-friendly HTML review index next to the existing render(s).

    Video paths and sampled-frame links are restricted to the output directory. Metadata
    is HTML-escaped, external assets/scripts are not loaded, and no decision/upload endpoint
    is added. The calling pipeline remains responsible for human approval and publication.
    """
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cards = "\n".join(_episode_card(root, entry, index)
                       for index, entry in enumerate(entries))
    page_title = html.escape(title)
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<style>
:root {{ color-scheme: dark; --bg:#101419; --panel:#1a222b; --line:#303c48; --ink:#e9eef4; --muted:#a7b4c0; --accent:#8fc7d9; --warn:#e8c47a; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:24px; background:var(--bg); color:var(--ink); font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1180px; margin:auto; }}
header {{ margin:0 0 24px; padding:20px 24px; border:1px solid var(--line); border-radius:14px; background:var(--panel); }}
h1 {{ margin:0 0 6px; font-size:clamp(1.55rem,3vw,2.1rem); }}
header p {{ margin:0; color:var(--muted); }}
.episode {{ margin:18px 0; padding:22px; border:1px solid var(--line); border-radius:14px; background:var(--panel); }}
.episode-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }}
h2 {{ margin:0; font-size:1.35rem; }}
.eyebrow {{ margin:0 0 4px; color:var(--accent); font-size:.78rem; font-weight:700; letter-spacing:.07em; text-transform:uppercase; }}
.topic,.voice {{ color:var(--muted); }}
.status {{ flex:0 0 auto; padding:4px 10px; border:1px solid var(--line); border-radius:99px; color:var(--accent); font-size:.8rem; }}
.media {{ width:min(100%,420px); margin:18px 0; overflow:hidden; border-radius:10px; background:#050608; }}
video {{ display:block; width:100%; aspect-ratio:9/16; object-fit:contain; }}
.no-video {{ padding:30px 16px; color:var(--warn); text-align:center; }}
.script,.sources,.story,.evidence,.voice-check,.technical {{ margin:14px 0; padding:12px 14px; border:1px solid var(--line); border-radius:9px; }}
summary {{ cursor:pointer; font-weight:650; }}
pre {{ overflow-wrap:anywhere; white-space:pre-wrap; color:#d8e1e9; font:inherit; }}
.beat-list {{ display:grid; gap:10px; padding-left:22px; }}
.beat-list li {{ padding:8px 0; }}
.beat-list p {{ margin:5px 0; color:var(--muted); }}
.beat-jump {{ max-width:100%; padding:5px 9px; border:1px solid var(--line); border-radius:7px; background:#202b35; color:var(--accent); font:inherit; text-align:left; cursor:pointer; }}
.beat-jump:hover {{ background:#2b3a47; }}
.beat-label {{ font-weight:650; }}
.answer-note {{ padding:9px 11px; border-left:3px solid var(--accent); background:#19252b; }}
.heard {{ margin:12px 0 0; padding:8px 10px; border:1px solid var(--line); border-radius:7px; }}
.heard p {{ overflow-wrap:anywhere; }}
.shots {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px; margin-top:12px; }}
.shot {{ padding:12px; border:1px solid var(--line); border-radius:8px; }}
.shot h4 {{ margin:0 0 5px; }}
.shot p {{ margin:5px 0; }}
dl {{ display:grid; grid-template-columns:max-content 1fr; gap:2px 10px; margin:10px 0; font-size:.88rem; }}
dt {{ color:var(--muted); }} dd {{ margin:0; overflow-wrap:anywhere; }}
a {{ color:var(--accent); }}
.samples {{ font-size:.86rem; }}
.reason {{ padding:10px 12px; border-left:3px solid var(--warn); background:#28251c; overflow-wrap:anywhere; }}
.human {{ margin:16px 0 0; padding-top:12px; border-top:1px solid var(--line); color:var(--muted); font-size:.9rem; }}
@media(max-width:640px) {{ body {{ padding:12px; }} .episode {{ padding:16px; }} .episode-head {{ flex-direction:column; }} .status {{ order:-1; }} }}
</style>
</head>
<body><main>
<header><h1>{page_title}</h1><p>Review the full render, narration, reviewed stock sources, selected crop and visible action. This offline page does not record an approval or publish a video.</p></header>
{cards or '<p>No drafts are available to review yet.</p>'}
</main>
<script>
for (const episode of document.querySelectorAll(".episode")) {{
  const player = episode.querySelector("video");
  if (!player) continue;
  for (const button of episode.querySelectorAll("[data-seek]")) {{
    button.addEventListener("click", () => {{
      const start = Number(button.dataset.seek);
      if (Number.isFinite(start) && start >= 0) {{
        player.pause();
        player.currentTime = start;
      }}
    }});
  }}
}}
</script>
</body>
</html>
"""
    target = root / "index.html"
    temp = target.with_suffix(".html.tmp")
    temp.write_text(document, encoding="utf-8")
    os.replace(temp, target)
    return target
