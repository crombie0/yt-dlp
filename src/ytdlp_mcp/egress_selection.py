from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from .egress_health import EgressHealthStore
from .errors import PolicyError
from .policy import (
    EgressProfile,
    Policy,
    normalize_country_code,
    normalize_country_name,
)


def select_request_egress(
    policy: Policy,
    *,
    profile_name: str | None = None,
    country_code: str | None = None,
    country: str | None = None,
    egress_health: EgressHealthStore | None = None,
    url: str | None = None,
    require_verified: bool = False,
    max_verification_age_seconds: int = 86400,
) -> tuple[Policy, dict[str, Any]]:
    """Return a per-request policy using the requested egress profile or country."""

    normalized_country_code = normalize_country_code(
        country_code,
        key="country_code",
    )
    normalized_country = normalize_country_name(country, key="country")
    requested = {
        "profile_name": profile_name,
        "country_code": normalized_country_code,
        "country": normalized_country,
    }

    if profile_name:
        profile = policy.egress_profile(profile_name)
        if profile is None:
            raise PolicyError(f"Egress profile does not exist: {profile_name}")
        _require_profile_matches_request(
            profile,
            country_code=normalized_country_code,
            country=normalized_country,
        )
    elif normalized_country_code or normalized_country:
        profile = _profile_for_country(
            policy,
            country_code=normalized_country_code,
            country=normalized_country,
            egress_health=egress_health,
            url=url,
            require_verified=require_verified,
            max_verification_age_seconds=max_verification_age_seconds,
        )
    else:
        active = policy.active_egress()
        return policy, {
            "requested": requested,
            "selected": active.as_dict() if active else None,
            "policy_override": False,
        }

    _validate_profile_usable(policy, profile)
    selected_policy = replace(policy, active_egress_profile=profile.name, proxy=None)
    return selected_policy, {
        "requested": requested,
        "selected": profile.as_dict(),
        "policy_override": profile.name != policy.active_egress_profile,
    }


def _profile_for_country(
    policy: Policy,
    *,
    country_code: str | None,
    country: str | None,
    egress_health: EgressHealthStore | None,
    url: str | None,
    require_verified: bool,
    max_verification_age_seconds: int,
) -> EgressProfile:
    matches = [
        profile
        for profile in policy.egress_profiles
        if _profile_matches_country(profile, country_code=country_code, country=country)
    ]
    if not matches:
        label = country_code or country or "requested country"
        raise PolicyError(f"No egress profile is configured for country: {label}")

    candidates = sorted(
        (
            (
                _candidate_rank(
                    policy,
                    profile,
                    egress_health=egress_health,
                    url=url,
                    require_verified=require_verified,
                    max_verification_age_seconds=max_verification_age_seconds,
                ),
                profile,
            )
            for profile in matches
        ),
        key=lambda item: item[0],
    )
    best_rank, best_profile = candidates[0]
    if best_rank[0] != 0:
        blockers = "; ".join(best_rank[4])
        raise PolicyError(
            f"No usable egress profile is available for country: {country_code or country}.",
            detail=blockers,
        )
    return best_profile


def _candidate_rank(
    policy: Policy,
    profile: EgressProfile,
    *,
    egress_health: EgressHealthStore | None,
    url: str | None,
    require_verified: bool,
    max_verification_age_seconds: int,
) -> tuple[int, int, int, int, tuple[str, ...], str]:
    blockers = _profile_blockers(
        policy,
        profile,
        egress_health=egress_health,
        url=url,
        require_verified=require_verified,
        max_verification_age_seconds=max_verification_age_seconds,
    )
    return (
        0 if not blockers else 1,
        0 if profile.enabled else 1,
        0 if profile.name == policy.active_egress_profile else 1,
        0 if profile.type == "proxy" else 1,
        tuple(blockers),
        profile.name,
    )


def _profile_blockers(
    policy: Policy,
    profile: EgressProfile,
    *,
    egress_health: EgressHealthStore | None,
    url: str | None,
    require_verified: bool,
    max_verification_age_seconds: int,
) -> list[str]:
    blockers: list[str] = []
    try:
        _validate_profile_usable(policy, profile)
    except PolicyError as exc:
        blockers.append(str(exc))

    if egress_health is not None:
        block = egress_health.block_for_profile(profile.name, url=url)
        if block:
            blockers.append(
                "profile is cooling down for "
                f"{block.get('domain')} until {int(float(block.get('until', 0)))}"
            )
        if require_verified:
            latest = egress_health.latest_verification(profile.name)
            if latest is None:
                blockers.append("profile has not been verified")
            elif not latest.get("verified"):
                blockers.append("latest verification did not pass")
            elif latest.get("time") is not None:
                age = time.time() - float(latest.get("time", 0))
                if age > max(1, int(max_verification_age_seconds)):
                    blockers.append("latest verification is stale")
    elif require_verified:
        blockers.append("egress verification persistence is not configured")
    return blockers


def _validate_profile_usable(policy: Policy, profile: EgressProfile) -> None:
    if not profile.enabled:
        raise PolicyError(f"Egress profile is disabled: {profile.name}")
    if profile.type == "proxy" and not profile.proxy:
        raise PolicyError(f"Proxy egress profile has no proxy configured: {profile.name}")
    if profile.type == "external_vpn" and policy.require_proxy:
        raise PolicyError(
            "External VPN egress profiles cannot satisfy require_proxy; "
            "use a proxy-backed profile for per-request egress selection."
        )


def _require_profile_matches_request(
    profile: EgressProfile,
    *,
    country_code: str | None,
    country: str | None,
) -> None:
    if country_code and profile.country_code != country_code:
        raise PolicyError(
            f"Egress profile {profile.name} is not configured for country_code={country_code}."
        )
    if country and (profile.country or "").casefold() != country.casefold():
        raise PolicyError(f"Egress profile {profile.name} is not configured for country={country}.")


def _profile_matches_country(
    profile: EgressProfile,
    *,
    country_code: str | None,
    country: str | None,
) -> bool:
    if country_code and profile.country_code != country_code:
        return False
    if country and (profile.country or "").casefold() != country.casefold():
        return False
    return bool(country_code or country)
