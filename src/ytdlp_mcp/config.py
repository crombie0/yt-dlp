from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import PolicyError
from .policy import (
    DEFAULT_EGRESS_COOLDOWN_SECONDS,
    DEFAULT_MAX_CONCURRENT_JOBS,
    DEFAULT_MAX_LOG_LINES,
    DEFAULT_MAX_PLAYLIST_ITEMS,
    DEFAULT_OUTPUT_ROOT,
    Policy,
)

CONFIG_PATH_ENV = "YTDLP_MCP_CONFIG"
POLICY_KEYS = {
    "output_root",
    "job_db_path",
    "egress_state_path",
    "download_archive_path",
    "proxy",
    "require_proxy",
    "active_egress_profile",
    "egress_profiles",
    "egress_cooldown_seconds",
    "allow_local_urls",
    "allowed_domains",
    "blocked_domains",
    "max_playlist_items",
    "max_concurrent_jobs",
    "max_log_lines",
}
ENV_OVERRIDES = {
    "output_root": "YTDLP_MCP_OUTPUT_ROOT",
    "job_db_path": "YTDLP_MCP_JOB_DB_PATH",
    "egress_state_path": "YTDLP_MCP_EGRESS_STATE_PATH",
    "download_archive_path": "YTDLP_MCP_DOWNLOAD_ARCHIVE_PATH",
    "proxy": "YTDLP_MCP_PROXY",
    "require_proxy": "YTDLP_MCP_REQUIRE_PROXY",
    "active_egress_profile": "YTDLP_MCP_ACTIVE_EGRESS_PROFILE",
    "egress_cooldown_seconds": "YTDLP_MCP_EGRESS_COOLDOWN_SECONDS",
    "allow_local_urls": "YTDLP_MCP_ALLOW_LOCAL_URLS",
    "allowed_domains": "YTDLP_MCP_ALLOWED_DOMAINS",
    "blocked_domains": "YTDLP_MCP_BLOCKED_DOMAINS",
    "max_playlist_items": "YTDLP_MCP_MAX_PLAYLIST_ITEMS",
    "max_concurrent_jobs": "YTDLP_MCP_MAX_CONCURRENT_JOBS",
    "max_log_lines": "YTDLP_MCP_MAX_LOG_LINES",
}


@dataclass(frozen=True, slots=True)
class ConfigLoadResult:
    policy: Policy
    source: dict[str, Any]


def load_configured_policy(
    config_path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> ConfigLoadResult:
    effective_env = os.environ if env is None else env
    selected_config_path = config_path or effective_env.get(CONFIG_PATH_ENV)
    file_values: dict[str, Any] = {}
    source: dict[str, Any] = {
        "config_path": None,
        "config_loaded": False,
        "config_keys": [],
        "env_overrides": [],
    }

    if selected_config_path:
        path = Path(selected_config_path).expanduser()
        source["config_path"] = str(path)
        file_values = _load_json_config(path)
        source["config_path"] = str(path.resolve())
        source["config_loaded"] = True
        source["config_keys"] = sorted(file_values)

    values: dict[str, Any] = {
        "output_root": DEFAULT_OUTPUT_ROOT,
        "job_db_path": None,
        "egress_state_path": None,
        "download_archive_path": None,
        "proxy": None,
        "require_proxy": False,
        "active_egress_profile": None,
        "egress_profiles": [],
        "egress_cooldown_seconds": DEFAULT_EGRESS_COOLDOWN_SECONDS,
        "allow_local_urls": False,
        "allowed_domains": [],
        "blocked_domains": [],
        "max_playlist_items": DEFAULT_MAX_PLAYLIST_ITEMS,
        "max_concurrent_jobs": DEFAULT_MAX_CONCURRENT_JOBS,
        "max_log_lines": DEFAULT_MAX_LOG_LINES,
    }
    values.update(file_values)

    env_overrides: list[str] = []
    for key, env_name in ENV_OVERRIDES.items():
        raw_value = effective_env.get(env_name)
        if raw_value is None or raw_value == "":
            continue
        values[key] = raw_value
        env_overrides.append(env_name)
    source["env_overrides"] = env_overrides

    policy = Policy(
        output_root=Path(_string_value(values["output_root"], "output_root")),
        job_db_path=_optional_path_value(values["job_db_path"], "job_db_path"),
        egress_state_path=_optional_path_value(values["egress_state_path"], "egress_state_path"),
        download_archive_path=_optional_path_value(
            values["download_archive_path"],
            "download_archive_path",
        ),
        proxy=_optional_string_value(values["proxy"], "proxy"),
        require_proxy=_bool_value(values["require_proxy"], "require_proxy"),
        active_egress_profile=_optional_string_value(
            values["active_egress_profile"],
            "active_egress_profile",
        ),
        egress_profiles=_egress_profiles_value(values["egress_profiles"]),
        egress_cooldown_seconds=_int_value(
            values["egress_cooldown_seconds"],
            "egress_cooldown_seconds",
        ),
        allow_local_urls=_bool_value(values["allow_local_urls"], "allow_local_urls"),
        allowed_domains=_list_value(values["allowed_domains"], "allowed_domains"),
        blocked_domains=_list_value(values["blocked_domains"], "blocked_domains"),
        max_playlist_items=_int_value(values["max_playlist_items"], "max_playlist_items"),
        max_concurrent_jobs=_int_value(values["max_concurrent_jobs"], "max_concurrent_jobs"),
        max_log_lines=_int_value(values["max_log_lines"], "max_log_lines"),
    )
    _validate_positive_policy(policy)
    source["effective_policy"] = policy.as_dict()
    return ConfigLoadResult(policy=policy, source=source)


def _load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PolicyError(f"Config file does not exist: {path}")
    if not path.is_file():
        raise PolicyError(f"Config path is not a file: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PolicyError(f"Config file is not valid JSON: {path}", detail=str(exc)) from exc

    if not isinstance(payload, dict):
        raise PolicyError("Config file must contain a JSON object.")

    unknown = sorted(set(payload) - POLICY_KEYS)
    if unknown:
        raise PolicyError(f"Unknown config keys: {', '.join(unknown)}")

    return dict(payload)


def _string_value(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyError(f"{key} must be a non-empty string.")
    return value


def _optional_path_value(value: Any, key: str) -> Path | None:
    if value is None:
        return None
    return Path(_string_value(value, key))


def _optional_string_value(value: Any, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PolicyError(f"{key} must be a string.")
    stripped = value.strip()
    return stripped or None


def _bool_value(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise PolicyError(f"{key} must be a boolean.")


def _int_value(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise PolicyError(f"{key} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{key} must be an integer.") from exc


def _list_value(value: Any, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if not isinstance(value, list):
        raise PolicyError(f"{key} must be a list of strings.")
    if not all(isinstance(item, str) for item in value):
        raise PolicyError(f"{key} must be a list of strings.")
    return tuple(value)


def _egress_profiles_value(value: Any) -> Any:
    if value is None:
        return ()
    if isinstance(value, (dict, list)):
        return value
    raise PolicyError("egress_profiles must be a list or object.")


def _validate_positive_policy(policy: Policy) -> None:
    if policy.max_playlist_items < 1:
        raise PolicyError("max_playlist_items must be at least 1.")
    if policy.max_concurrent_jobs < 1:
        raise PolicyError("max_concurrent_jobs must be at least 1.")
    if policy.max_log_lines < 1:
        raise PolicyError("max_log_lines must be at least 1.")
    if policy.egress_cooldown_seconds < 1:
        raise PolicyError("egress_cooldown_seconds must be at least 1.")
