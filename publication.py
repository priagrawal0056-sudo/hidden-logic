"""Fail-closed publication gate shared by every upload path.

Generated pilots and drafts stay unpublished unless rollout is explicitly enabled.
Even after rollout is enabled, a pilot cannot be uploaded until a human marks it
approved, and every episode must still pass the deterministic evidence/media gates.
"""
from __future__ import annotations

from pathlib import Path


class PublicationBlocked(RuntimeError):
    """Raised before any external publishing API is invoked."""


def episode_issues(metadata: dict, workdir: str | Path | None = None) -> list[str]:
    import editorial_quality
    return editorial_quality.validate_episode_meta(metadata, workdir)


def assert_publication_allowed(cfg: dict, metadata: dict | None = None,
                               workdir: str | Path | None = None,
                               *, source: str = "video") -> None:
    """Reject publication unless rollout and episode-specific quality/review gates pass."""
    if not isinstance(cfg, dict) or cfg.get("rollout_enabled") is not True:
        raise PublicationBlocked(
            f"{source} publication is disabled: rollout_enabled must remain false until the "
            "six unpublished pilots pass human review"
        )
    if cfg.get("pilot_review_complete") is not True:
        raise PublicationBlocked(
            f"{source} publication is blocked: pilot_review_complete must be explicitly set "
            "after all six pilots pass human review"
        )
    if metadata is None:
        return

    if metadata.get("pilot_mode") is True and str(
        metadata.get("human_review_status", "")
    ).strip().lower() != "approved":
        raise PublicationBlocked(
            f"pilot {metadata.get('pilot_id', '<unknown>')} is not human-approved"
        )

    issues = episode_issues(metadata, workdir)
    if issues:
        raise PublicationBlocked(
            f"{source} failed editorial publication gates: " + ", ".join(issues)
        )
