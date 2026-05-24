from __future__ import annotations

import time
from typing import Any

from .egress_health import EgressHealthStore
from .policy import Policy, validate_url


def recommend_egress_profile(
    policy: Policy,
    *,
    egress_health: EgressHealthStore | None,
    url: str | None = None,
    require_verified: bool = True,
    max_verification_age_seconds: int = 86400,
    exclude_active: bool = False,
) -> dict[str, Any]:
    validated_url = validate_url(url, policy) if url else None
    current_time = time.time()
    candidates = [
        _candidate_payload(
            policy,
            profile,
            egress_health=egress_health,
            url=validated_url,
            require_verified=require_verified,
            max_verification_age_seconds=max_verification_age_seconds,
            now=current_time,
            exclude_active=exclude_active,
        )
        for profile in policy.egress_profiles
    ]
    ranked = sorted(candidates, key=_rank_candidate)
    recommended = next((item for item in ranked if item["ready_for_activation"]), None)
    return {
        "ok": True,
        "recommended_profile": recommended["name"] if recommended else None,
        "recommended": recommended,
        "candidates": ranked,
        "url": validated_url,
        "require_verified": require_verified,
        "max_verification_age_seconds": max_verification_age_seconds,
    }


def _candidate_payload(
    policy: Policy,
    profile: Any,
    *,
    egress_health: EgressHealthStore | None,
    url: str | None,
    require_verified: bool,
    max_verification_age_seconds: int,
    now: float,
    exclude_active: bool,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []

    if exclude_active and profile.name == policy.active_egress_profile:
        blockers.append("profile is already active")
    if profile.type == "proxy" and not profile.proxy:
        blockers.append("proxy profile has no proxy configured")
    if profile.type == "external_vpn" and policy.require_proxy:
        blockers.append("external_vpn cannot satisfy require_proxy")

    latest_verification = None
    if egress_health is None:
        if require_verified:
            blockers.append("egress verification persistence is not configured")
        else:
            warnings.append("egress verification persistence is not configured")
    else:
        latest_verification = egress_health.latest_verification(profile.name)
        if latest_verification is None:
            if require_verified:
                blockers.append("profile has not been verified")
        elif not latest_verification.get("verified"):
            blockers.append("latest verification did not pass")
        else:
            age = now - float(latest_verification.get("time", 0))
            if age > max_verification_age_seconds:
                blockers.append("latest verification is stale")

        block = egress_health.block_for_profile(profile.name, url=url)
        if block:
            blockers.append(
                "profile is cooling down for "
                f"{block.get('domain')} until {int(float(block.get('until', 0)))}"
            )

    if not profile.enabled:
        warnings.append("profile is disabled; activation is required before use")

    return {
        "name": profile.name,
        "type": profile.type,
        "enabled": profile.enabled,
        "is_active": profile.name == policy.active_egress_profile,
        "ready_for_activation": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "latest_verification": latest_verification,
    }


def _rank_candidate(candidate: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        0 if candidate["ready_for_activation"] else 1,
        0 if candidate["enabled"] else 1,
        0 if candidate["is_active"] else 1,
        candidate["name"],
    )
