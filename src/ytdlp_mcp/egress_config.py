from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import ENV_OVERRIDES, load_configured_policy
from .errors import PolicyError
from .policy import Policy


def activate_profile_in_config(
    *,
    config_source: dict[str, Any],
    policy: Policy,
    profile_name: str,
    allow_external_vpn_without_proxy: bool = False,
) -> dict[str, Any]:
    config_path = _config_path_from_source(config_source)
    _reject_conflicting_env_override(config_source, "active_egress_profile")
    _reject_conflicting_env_override(config_source, "proxy")
    _reject_conflicting_env_override(config_source, "require_proxy")

    profile = policy.egress_profile(profile_name)
    if profile is None:
        raise PolicyError(f"Egress profile does not exist: {profile_name}")
    if profile.type == "proxy" and not profile.proxy:
        raise PolicyError(f"Proxy egress profile has no proxy configured: {profile.name}")
    if (
        profile.type == "external_vpn"
        and policy.require_proxy
        and not allow_external_vpn_without_proxy
    ):
        raise PolicyError(
            "External VPN profiles cannot satisfy require_proxy. Pass "
            "allow_external_vpn_without_proxy=true only after the process-level VPN "
            "route has been verified."
        )

    payload = _load_config_payload(config_path)
    profile_payload = _profile_payload(payload, profile_name)
    profile_payload["enabled"] = True
    payload["active_egress_profile"] = profile_name
    if profile.type == "external_vpn" and policy.require_proxy:
        payload["require_proxy"] = False

    backup_path = _backup_config(config_path)
    _write_config_payload(config_path, payload)

    try:
        reloaded = load_configured_policy(config_path)
    except Exception:
        config_path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
        raise

    return {
        "config_path": str(config_path),
        "backup_path": str(backup_path),
        "active_egress_profile": profile_name,
        "policy": reloaded.policy.as_dict(),
    }


def _config_path_from_source(config_source: dict[str, Any]) -> Path:
    path = config_source.get("config_path")
    if not path or not config_source.get("config_loaded"):
        raise PolicyError("A writable JSON config file is required to activate profiles.")
    config_path = Path(str(path)).expanduser().resolve()
    if not config_path.exists() or not config_path.is_file():
        raise PolicyError(f"Config file does not exist: {config_path}")
    return config_path


def _reject_conflicting_env_override(config_source: dict[str, Any], key: str) -> None:
    env_name = ENV_OVERRIDES[key]
    if env_name in set(config_source.get("env_overrides", [])):
        raise PolicyError(
            f"Cannot update {key} in config because {env_name} overrides it at runtime."
        )


def _load_config_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PolicyError(f"Config file is not valid JSON: {path}", detail=str(exc)) from exc
    if not isinstance(payload, dict):
        raise PolicyError("Config file must contain a JSON object.")
    return payload


def _profile_payload(payload: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = payload.get("egress_profiles")
    if isinstance(profiles, dict):
        profile = profiles.get(profile_name)
        if not isinstance(profile, dict):
            raise PolicyError(f"Egress profile is not present in config: {profile_name}")
        return profile
    if isinstance(profiles, list):
        for profile in profiles:
            if isinstance(profile, dict) and profile.get("name") == profile_name:
                return profile
        raise PolicyError(f"Egress profile is not present in config: {profile_name}")
    raise PolicyError("egress_profiles must be an object or list in the config file.")


def _backup_config(path: Path) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-activate-egress-{timestamp}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


def _write_config_payload(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
