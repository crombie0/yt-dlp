from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .policy import Policy

OK = "ok"
WARNING = "warning"
ERROR = "error"


def build_environment_diagnostics(policy: Policy, versions: dict[str, Any]) -> dict[str, Any]:
    checks = [
        _version_check("python", versions.get("python"), required=True),
        _version_check(
            "mcp",
            versions.get("mcp") or _installed_package_location("mcp"),
            required=True,
        ),
        _version_check("yt_dlp", versions.get("yt_dlp"), required=True),
        _version_check("ffmpeg", versions.get("ffmpeg"), required=False),
        _output_root_check(policy.resolved_output_root),
        _job_db_check(policy.resolved_job_db_path),
        _policy_check(policy),
    ]
    return {
        "status": _overall_status(checks),
        "checks": checks,
        "versions": versions,
        "policy": policy.as_dict(),
    }


def _version_check(name: str, value: object, *, required: bool) -> dict[str, Any]:
    if value:
        return {
            "name": name,
            "status": OK,
            "required": required,
            "detail": str(value),
        }

    status = ERROR if required else WARNING
    message = "required dependency is missing" if required else "optional dependency is missing"
    return {
        "name": name,
        "status": status,
        "required": required,
        "detail": message,
    }


def _installed_package_location(package: str) -> str | None:
    spec = find_spec(package)
    if spec is None:
        return None
    return spec.origin or "installed"


def _output_root_check(output_root: Path) -> dict[str, Any]:
    root_exists = output_root.exists()
    parent = output_root if root_exists else output_root.parent
    parent_exists = parent.exists()
    is_directory = output_root.is_dir() if root_exists else None
    writable = (
        os.access(output_root if root_exists else parent, os.W_OK)
        if parent_exists
        else False
    )

    status = OK
    detail = "output root exists and appears writable"
    if root_exists and not is_directory:
        status = ERROR
        detail = "output root exists but is not a directory"
    elif not parent_exists:
        status = ERROR
        detail = "output root parent directory does not exist"
    elif not writable:
        status = WARNING
        detail = "output root or parent is not writable by this process"
    elif not root_exists:
        status = WARNING
        detail = "output root does not exist yet but parent appears writable"

    return {
        "name": "output_root",
        "status": status,
        "required": True,
        "path": str(output_root),
        "exists": root_exists,
        "is_directory": is_directory,
        "parent": str(parent),
        "parent_exists": parent_exists,
        "writable": writable,
        "detail": detail,
    }


def _job_db_check(job_db_path: Path | None) -> dict[str, Any]:
    if job_db_path is None:
        return {
            "name": "job_db",
            "status": OK,
            "required": False,
            "path": None,
            "detail": "job persistence is disabled",
        }

    parent = job_db_path.parent
    parent_exists = parent.exists()
    writable = os.access(parent, os.W_OK) if parent_exists else False
    status = OK
    detail = "job persistence database path appears writable"
    if not parent_exists:
        status = WARNING
        detail = "job persistence database parent directory does not exist yet"
    elif not writable:
        status = WARNING
        detail = "job persistence database parent directory is not writable"

    return {
        "name": "job_db",
        "status": status,
        "required": False,
        "path": str(job_db_path),
        "parent": str(parent),
        "parent_exists": parent_exists,
        "writable": writable,
        "detail": detail,
    }


def _policy_check(policy: Policy) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    active_egress = policy.active_egress()
    if policy.active_egress_profile and active_egress is None:
        errors.append(f"active egress profile does not exist: {policy.active_egress_profile}")
    if active_egress and not active_egress.enabled:
        errors.append(f"active egress profile is disabled: {active_egress.name}")
    if active_egress and active_egress.type == "proxy" and not active_egress.proxy:
        errors.append(f"active proxy egress profile has no proxy configured: {active_egress.name}")
    if policy.require_proxy and not policy.proxy:
        errors.append("outbound proxy is required but not configured")
    if policy.allow_local_urls:
        warnings.append("local/private URLs are allowed")
    if not policy.allowed_domains:
        warnings.append("no allowed domain list is configured")
    if policy.allowed_domains and policy.blocked_domains:
        overlap = sorted(set(policy.allowed_domains) & set(policy.blocked_domains))
        if overlap:
            warnings.append(f"domains appear in both allow and block lists: {', '.join(overlap)}")
    if policy.max_playlist_items > 100:
        warnings.append("playlist item limit is high")
    if policy.max_concurrent_jobs > (os.cpu_count() or 1) * 2:
        warnings.append("concurrent job limit is high for this host")

    detail_parts = errors + warnings
    status = ERROR if errors else WARNING if warnings else OK
    return {
        "name": "policy",
        "status": status,
        "required": True,
        "detail": (
            "; ".join(detail_parts) if detail_parts else "policy is within conservative defaults"
        ),
    }


def _overall_status(checks: list[dict[str, Any]]) -> str:
    statuses = {check["status"] for check in checks}
    if ERROR in statuses:
        return ERROR
    if WARNING in statuses:
        return WARNING
    return OK
