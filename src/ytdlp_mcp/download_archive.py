from __future__ import annotations

from pathlib import Path
from typing import Any

from .policy import Policy


def archive_summary(policy: Policy, *, limit: int = 50) -> dict[str, Any]:
    path = policy.resolved_download_archive_path
    if path is None:
        return {
            "enabled": False,
            "path": None,
            "exists": False,
            "entry_count": 0,
            "recent_entries": [],
        }

    entries = _read_entries(path) if path.exists() else []
    bounded_limit = max(0, min(int(limit), 500))
    return {
        "enabled": True,
        "path": str(path),
        "exists": path.exists(),
        "entry_count": len(entries),
        "recent_entries": entries[-bounded_limit:] if bounded_limit else [],
    }


def _read_entries(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if line.strip()]
