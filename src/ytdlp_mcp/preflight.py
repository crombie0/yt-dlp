from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .download_archive import archive_summary
from .egress import get_egress_status
from .egress_health import EgressHealthStore
from .errors import PolicyError
from .options import validate_download_parameters
from .policy import Policy, validate_url


def build_download_preflight(
    policy: Policy,
    *,
    url: str,
    egress_health: EgressHealthStore | None = None,
    kind: str = "video",
    format_selector: str | None = None,
    audio_format: str = "m4a",
    subtitle_languages: list[str] | None = None,
    subtitle_format: str = "best",
    output_template: str | None = None,
    playlist_items: str | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []
    validated_url: str | None = None
    download_plan: dict[str, Any] | None = None

    try:
        validated_url = validate_url(url, policy)
        _add_check(checks, "url_policy", "pass", "URL is allowed by policy.")
    except PolicyError as exc:
        blockers.append(str(exc))
        _add_check(checks, "url_policy", "fail", str(exc))

    try:
        download_plan = validate_download_parameters(
            policy,
            kind=kind,
            format_selector=format_selector,
            audio_format=audio_format,
            subtitle_languages=subtitle_languages,
            subtitle_format=subtitle_format,
            output_template=output_template,
            playlist_items=playlist_items,
        )
        _add_check(checks, "download_options", "pass", "Download parameters are valid.")
    except PolicyError as exc:
        blockers.append(str(exc))
        _add_check(checks, "download_options", "fail", str(exc))

    output = _output_status(policy.resolved_output_root)
    if output["status"] == "fail":
        blockers.append(str(output["detail"]))
    elif output["status"] == "warn":
        warnings.append(str(output["detail"]))
    _add_check(checks, "output_root", str(output["status"]), str(output["detail"]))

    archive = archive_summary(policy, limit=10)
    if archive["enabled"]:
        detail = "Download archive is enabled."
        if not archive["exists"]:
            detail = "Download archive is enabled but the archive file does not exist yet."
            warnings.append(detail)
        _add_check(checks, "download_archive", "pass", detail)
    else:
        detail = "Download archive is disabled; duplicate media may be requested again."
        warnings.append(detail)
        _add_check(checks, "download_archive", "warn", detail)

    egress = get_egress_status(policy)
    for issue in egress["issues"]:
        blockers.append(str(issue))
    _add_check(
        checks,
        "egress_policy",
        "pass" if egress["ok"] else "fail",
        "Active egress policy is usable." if egress["ok"] else "; ".join(egress["issues"]),
    )

    egress_health_payload = _egress_health_status(
        policy,
        egress_health=egress_health,
        url=validated_url,
    )
    if egress_health_payload["status"] == "fail":
        blockers.append(str(egress_health_payload["detail"]))
    elif egress_health_payload["status"] == "warn":
        warnings.append(str(egress_health_payload["detail"]))
    _add_check(
        checks,
        "egress_health",
        str(egress_health_payload["status"]),
        str(egress_health_payload["detail"]),
    )

    ready = not blockers
    return {
        "ok": True,
        "ready": ready,
        "recommended_next_tool": "start_download" if ready else None,
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
        "checks": checks,
        "url": {
            "input": url,
            "validated": validated_url,
            "domain": _domain_from_url(validated_url),
        },
        "download": download_plan,
        "output": output,
        "archive": archive,
        "egress": egress,
        "egress_health": egress_health_payload["health"],
    }


def _egress_health_status(
    policy: Policy,
    *,
    egress_health: EgressHealthStore | None,
    url: str | None,
) -> dict[str, Any]:
    if egress_health is None:
        return {
            "status": "warn",
            "detail": "egress_state_path is not configured; cooldown checks are disabled.",
            "health": {
                "enabled": False,
                "detail": "egress_state_path is not configured",
            },
        }

    health = egress_health.status(policy)
    url_block = egress_health.active_block(policy, url=url) if url else None
    health["url_block"] = url_block
    if url_block:
        detail = (
            "Active egress profile is cooling down for "
            f"{url_block.get('domain')} until {int(float(url_block.get('until', 0)))}."
        )
        return {"status": "fail", "detail": detail, "health": health}
    return {
        "status": "pass",
        "detail": "No active egress cooldown blocks this URL.",
        "health": health,
    }


def _output_status(root: Path) -> dict[str, Any]:
    resolved = root.expanduser().resolve()
    payload: dict[str, Any] = {
        "root": str(resolved),
        "exists": resolved.exists(),
        "is_dir": resolved.is_dir() if resolved.exists() else None,
        "writable": None,
        "status": "pass",
        "detail": "Output root is writable.",
    }

    if resolved.exists() and not resolved.is_dir():
        payload["status"] = "fail"
        payload["detail"] = "Output root exists but is not a directory."
        return payload

    if resolved.exists():
        payload["writable"] = os.access(resolved, os.W_OK | os.X_OK)
        if not payload["writable"]:
            payload["status"] = "fail"
            payload["detail"] = "Output root is not writable."
        return payload

    parent = _nearest_existing_parent(resolved)
    payload["nearest_existing_parent"] = str(parent)
    payload["parent_writable"] = os.access(parent, os.W_OK | os.X_OK)
    if payload["parent_writable"]:
        payload["status"] = "warn"
        payload["detail"] = "Output root does not exist yet; it will be created on download."
    else:
        payload["status"] = "fail"
        payload["detail"] = "Output root does not exist and nearest parent is not writable."
    return payload


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def _add_check(
    checks: list[dict[str, Any]],
    name: str,
    status: str,
    detail: str,
) -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def _domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    hostname = urlparse(url).hostname
    return hostname.lower().rstrip(".") if hostname else None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped
