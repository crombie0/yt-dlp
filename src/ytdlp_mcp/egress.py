from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from .errors import DependencyError, DownloadError, PolicyError
from .policy import Policy, redact_proxy_url, validate_url

DEFAULT_EGRESS_CHECK_URL = "https://api.ipify.org?format=json"
DEFAULT_EGRESS_GEO_URL = "https://ipinfo.io/json"


def list_egress_profiles(policy: Policy) -> dict[str, Any]:
    return {
        "active_egress_profile": policy.active_egress_profile,
        "require_proxy": policy.require_proxy,
        "fallback_proxy": redact_proxy_url(policy.proxy),
        "profiles": [profile.as_dict() for profile in policy.egress_profiles],
    }


def get_egress_status(policy: Policy) -> dict[str, Any]:
    active = policy.active_egress()
    issues: list[str] = []
    if policy.active_egress_profile and active is None:
        issues.append(f"active egress profile does not exist: {policy.active_egress_profile}")
    if active and not active.enabled:
        issues.append(f"active egress profile is disabled: {active.name}")
    if active and active.type == "proxy" and not active.proxy:
        issues.append(f"active proxy egress profile has no proxy configured: {active.name}")
    if policy.require_proxy and not policy.proxy:
        issues.append("outbound proxy is required but no proxy is configured")

    return {
        "ok": not issues,
        "active_egress_profile": active.as_dict() if active else None,
        "require_proxy": policy.require_proxy,
        "effective_proxy": redact_proxy_url(policy.proxy),
        "issues": issues,
    }


def test_egress_ip(
    policy: Policy,
    *,
    profile_name: str | None = None,
    url: str = DEFAULT_EGRESS_CHECK_URL,
    timeout: int = 10,
    allow_disabled: bool = False,
    include_geo: bool = False,
    geo_url: str = DEFAULT_EGRESS_GEO_URL,
) -> dict[str, Any]:
    validated_url = validate_url(url, policy)
    profile = policy.egress_profile(profile_name) if profile_name else policy.active_egress()
    proxy = _proxy_for_test(policy, profile_name=profile_name, allow_disabled=allow_disabled)
    body = _curl_text(validated_url, proxy=proxy, timeout=timeout)

    geo = None
    if include_geo:
        validated_geo_url = validate_url(geo_url, policy)
        geo_body = body if validated_geo_url == validated_url else _curl_text(
            validated_geo_url,
            proxy=proxy,
            timeout=timeout,
        )
        geo = _extract_geo(geo_body)

    return {
        "profile": profile.as_dict() if profile else None,
        "proxy": redact_proxy_url(proxy),
        "url": validated_url,
        "ip": _extract_ip(body),
        "raw": body[:1000],
        "geo": geo,
    }


def _curl_text(url: str, *, proxy: str | None, timeout: int) -> str:
    command = _curl_command(url, proxy=proxy, timeout=timeout)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(timeout + 2, 3),
        )
    except subprocess.TimeoutExpired as exc:
        raise DownloadError("Egress IP check timed out.", detail=str(exc)) from exc
    except OSError as exc:
        raise DownloadError("Egress IP check could not run.", detail=str(exc)) from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise DownloadError("Egress IP check failed.", detail=detail)

    return result.stdout.strip()


def _proxy_for_test(
    policy: Policy,
    *,
    profile_name: str | None,
    allow_disabled: bool = False,
) -> str | None:
    profile = policy.egress_profile(profile_name) if profile_name else policy.active_egress()
    if profile_name and profile is None:
        raise PolicyError(f"Egress profile does not exist: {profile_name}")
    if profile and not profile.enabled and not allow_disabled:
        raise PolicyError(f"Egress profile is disabled: {profile.name}")
    if profile and profile.type == "proxy":
        if not profile.proxy:
            raise PolicyError(f"Proxy egress profile has no proxy configured: {profile.name}")
        return profile.proxy
    if profile and profile.type == "external_vpn":
        if policy.require_proxy:
            raise PolicyError(
                "External VPN egress profiles cannot satisfy require_proxy; "
                "disable require_proxy only after the process-level VPN is verified."
            )
        return None
    if policy.require_proxy and not policy.proxy:
        raise PolicyError("Outbound proxy is required by policy but no proxy is configured.")
    return policy.proxy


def _curl_command(url: str, *, proxy: str | None, timeout: int) -> list[str]:
    curl = shutil.which("curl")
    if not curl:
        raise DependencyError("curl is required for egress IP checks.")
    command = [
        curl,
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--max-time",
        str(max(1, timeout)),
    ]
    if proxy:
        command.extend(["--proxy", proxy])
    command.append(url)
    return command


def _extract_ip(body: str) -> str | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip() or None
    if isinstance(payload, dict) and isinstance(payload.get("ip"), str):
        return payload["ip"]
    return None


def _extract_geo(body: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    country = payload.get("country")
    return {
        "ip": payload.get("ip") if isinstance(payload.get("ip"), str) else None,
        "country_code": country.upper() if isinstance(country, str) and country else None,
        "country": (
            payload.get("country_name") if isinstance(payload.get("country_name"), str) else None
        ),
        "region": payload.get("region") if isinstance(payload.get("region"), str) else None,
        "city": payload.get("city") if isinstance(payload.get("city"), str) else None,
        "org": payload.get("org") if isinstance(payload.get("org"), str) else None,
        "timezone": payload.get("timezone") if isinstance(payload.get("timezone"), str) else None,
    }
