"""Create six unpublished, human-review pilots through the existing pipeline.

This command is intentionally inert unless --generate is supplied. It never publishes,
uploads, or enables rollout; each draft uses Orus with a controlled delivery direction.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path


PILOT_SPECS = (
    {
        "pilot_id": "technology-01",
        "category": "technology",
        "topic": "A phone charger cable that only works when it bends beside the plug",
        "voice_direction": "curious_observation",
    },
    {
        "pilot_id": "technology-02",
        "category": "technology",
        "topic": "A contactless payment terminal that asks a shopper to try the card again",
        "voice_direction": "understated_dry_amusement",
    },
    {
        "pilot_id": "queues-travel-01",
        "category": "queues_travel",
        "topic": "An airport security tray that slows the line when it stops at the scanner exit",
        "voice_direction": "confident_practical_explanation",
    },
    {
        "pilot_id": "queues-travel-02",
        "category": "queues_travel",
        "topic": "A passenger pausing at a train station turnstile while people queue behind",
        "voice_direction": "curious_observation",
    },
    {
        "pilot_id": "shopping-pricing-01",
        "category": "shopping_pricing",
        "topic": "A shopper comparing two cereal boxes by reading their unit-price labels",
        "voice_direction": "understated_dry_amusement",
    },
    {
        "pilot_id": "shopping-pricing-02",
        "category": "shopping_pricing",
        "topic": "A grocery shopper comparing a sale label with the unit price on a different package size",
        "voice_direction": "confident_practical_explanation",
    },
)


def _usable_key(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text and not text.startswith("PASTE_") and "_HERE" not in text)


def _save_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true",
                        help="explicitly generate the six unpublished drafts (uses configured APIs)")
    parser.add_argument("--output-dir", default=None,
                        help="draft root (default: pilots/unpublished/YYYYMMDD)")
    parser.add_argument("--config", default="config.json", help="configuration path")
    args = parser.parse_args()

    print("Six unpublished Hidden Logic pilots — no uploads or publication are performed.")
    for spec in PILOT_SPECS:
        print(f"- {spec['pilot_id']} [{spec['category']}] | {spec['voice_direction']} | {spec['topic']}")
    if not args.generate:
        print("Plan only. Add --generate to create drafts; human review remains required.")
        return 0

    import config_loader
    import editorial_quality
    import run_daily

    cfg = config_loader.load_config(args.config)
    cfg["rollout_enabled"] = False
    cfg["pilot_review_complete"] = False
    for key in ("gemini_api_key", "pexels_api_key", "pixabay_api_key"):
        if not _usable_key(cfg.get(key)):
            cfg[key] = ""
    if not cfg.get("gemini_api_key"):
        parser.error("Gemini credentials are required for script, frame review, and Orus TTS")
    if not cfg.get("pexels_api_key") and not cfg.get("pixabay_api_key"):
        parser.error("Pexels or Pixabay credentials are required for stock-only footage")

    root = Path(args.output_dir or Path("pilots") / "unpublished" / dt.date.today().strftime("%Y%m%d"))
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / "pilot_batch_report.json"
    report = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rollout_enabled": False,
        "pilot_review_complete": False,
        "publication_performed": False,
        "human_review_required": True,
        "pilots": [],
    }
    _save_report(report_path, report)

    for spec in PILOT_SPECS:
        workdir = root / spec["pilot_id"]
        entry = {
            **spec,
            "status": "pending",
            "human_review_status": "pending",
            "workdir": str(workdir),
        }
        if workdir.is_dir() and any(workdir.iterdir()):
            meta_path = workdir / "meta.json"
            video_path = workdir / "short.mp4"
            if meta_path.is_file() and video_path.is_file():
                try:
                    existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    issues = editorial_quality.validate_episode_meta(existing_meta, workdir)
                    if not issues:
                        entry.update(
                            status="ready_for_human_review",
                            human_review_status=existing_meta.get("human_review_status", "pending"),
                            skip_reason="existing_draft_preserved",
                            title=existing_meta.get("title", ""),
                            voice=existing_meta.get("voice_identity", ""),
                            voice_direction=existing_meta.get("voice_direction", ""),
                            tts_model=existing_meta.get("tts_model", ""),
                        )
                    else:
                        entry.update(status="skipped", skip_reason="existing_draft_quality_failed: "
                                     + "; ".join(issues))
                except Exception as exc:
                    entry.update(status="skipped", skip_reason=f"existing_draft_unreadable: {exc}")
            else:
                entry.update(status="skipped", skip_reason="partial_draft_preserved")
            report["pilots"].append(entry)
            _save_report(report_path, report)
            continue
        try:
            result = run_daily.make_one(
                cfg, str(workdir), dry_run=True, topic=spec["topic"],
                strict_topic_lock=True, generate_only=True,
                voice_direction=spec["voice_direction"], pilot_id=spec["pilot_id"],
            )
            if not isinstance(result, dict) or not (workdir / "short.mp4").is_file():
                raise RuntimeError("pipeline returned without a complete rendered draft")
            meta = result.get("meta") or {}
            issues = editorial_quality.validate_episode_meta(meta, workdir)
            if issues:
                raise RuntimeError("reserve gate rejected pilot: " + "; ".join(issues))
            entry.update(
                status="ready_for_human_review",
                title=meta.get("title", ""),
                voice=meta.get("voice_identity", ""),
                voice_direction=meta.get("voice_direction", ""),
                tts_model=meta.get("tts_model", ""),
                quality_issues=[],
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            entry.update(status="skipped", skip_reason=reason)
            editorial_quality.record_skip_reason(
                root / "skip_reasons.jsonl", episode_id=spec["pilot_id"],
                topic=spec["topic"], reason=reason, phase="pilot_generation",
            )
        report["pilots"].append(entry)
        _save_report(report_path, report)
        print(f"{entry['pilot_id']}: {entry['status']}"
              + (f" — {entry['skip_reason']}" if entry.get("skip_reason") else ""))

    try:
        import review_package
        review_path = review_package.write_review_page(
            root, report["pilots"], title="Hidden Logic six-pilot review",
        )
        report["review_page"] = review_path.name
    except Exception as exc:
        # Keep review rendering helpful but non-blocking; the JSON report and videos remain authoritative.
        print(f"Static review page unavailable (non-fatal): {type(exc).__name__}: {exc}")
    _save_report(report_path, report)

    ready = sum(item["status"] == "ready_for_human_review" for item in report["pilots"])
    print(f"\nSaved {ready}/{len(PILOT_SPECS)} review-ready pilots under {root}.")
    print(f"Report: {report_path}")
    if report.get("review_page"):
        print(f"Review page: {root / report['review_page']}")
    print("No video was uploaded or published; rollout_enabled remains false.")
    return 0 if ready == len(PILOT_SPECS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
