from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import PolicyError
from .policy import Policy

MAX_EVENTS = 500
COOLDOWN_CATEGORIES = {
    "RATE_LIMITED",
    "FORBIDDEN",
    "CAPTCHA_REQUIRED",
    "BOT_DETECTION",
}


@dataclass(frozen=True, slots=True)
class EgressFailureClassification:
    category: str
    reason: str
    cooldown: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "reason": self.reason,
            "cooldown": self.cooldown,
        }


class EgressHealthStore:
    def __init__(self, path: Path):
        self._path = path.expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if not self._path.exists():
            self._save({"version": 1, "events": [], "cooldowns": []})

    def status(self, policy: Policy, *, now: float | None = None) -> dict[str, Any]:
        current_time = time.time() if now is None else now
        state = self._load()
        cooldowns = [
            item
            for item in state.get("cooldowns", [])
            if _float_value(item.get("until")) > current_time
        ]
        return {
            "state_path": str(self._path),
            "cooldowns": cooldowns,
            "recent_events": list(state.get("events", []))[-25:],
            "active_block": self.active_block(policy, now=current_time),
        }

    def active_block(
        self,
        policy: Policy,
        *,
        url: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        current_time = time.time() if now is None else now
        profile = _profile_key(policy)
        domain = _domain_from_url(url) if url else None
        for item in self._load().get("cooldowns", []):
            if item.get("profile") != profile:
                continue
            if _float_value(item.get("until")) <= current_time:
                continue
            if domain and item.get("domain") not in {domain, "*"}:
                continue
            return dict(item)
        return None

    def enforce_available(self, policy: Policy, url: str) -> None:
        block = self.active_block(policy, url=url)
        if not block:
            return
        until = int(_float_value(block.get("until")))
        raise PolicyError(
            "Active egress profile is cooling down for "
            f"{block.get('domain')} until {until} after {block.get('category')}."
        )

    def record_failure(
        self,
        policy: Policy,
        url: str,
        classification: EgressFailureClassification,
        *,
        message: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        current_time = time.time() if now is None else now
        event = {
            "time": current_time,
            "profile": _profile_key(policy),
            "domain": _domain_from_url(url),
            "category": classification.category,
            "reason": classification.reason,
            "message": _compact_message(message),
        }

        with self._lock:
            state = self._load()
            events = list(state.get("events", []))
            events.append(event)
            state["events"] = events[-MAX_EVENTS:]

            if classification.cooldown:
                cooldown = {
                    "profile": event["profile"],
                    "domain": event["domain"],
                    "category": classification.category,
                    "reason": classification.reason,
                    "since": current_time,
                    "until": current_time + policy.egress_cooldown_seconds,
                }
                state["cooldowns"] = _upsert_cooldown(
                    state.get("cooldowns", []),
                    cooldown,
                )
                event["cooldown_until"] = cooldown["until"]

            self._save(state)
        return event

    def clear_cooldowns(
        self,
        *,
        profile_name: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._load()
            before = list(state.get("cooldowns", []))
            after = [
                item
                for item in before
                if not _matches_cooldown(item, profile_name=profile_name, domain=domain)
            ]
            state["cooldowns"] = after
            self._save(state)
        return {"removed": len(before) - len(after), "remaining": len(after)}

    def _load(self) -> dict[str, Any]:
        with self._lock:
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"version": 1, "events": [], "cooldowns": []}
            if not isinstance(payload, dict):
                return {"version": 1, "events": [], "cooldowns": []}
            payload.setdefault("version", 1)
            payload.setdefault("events", [])
            payload.setdefault("cooldowns", [])
            return payload

    def _save(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(f"{self._path.suffix}.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
            tmp.replace(self._path)


def classify_failure(message: object) -> EgressFailureClassification | None:
    text = str(message or "")
    normalized = " ".join(text.lower().split())
    if not normalized:
        return None
    if "429" in normalized or "too many requests" in normalized or "rate limit" in normalized:
        return EgressFailureClassification("RATE_LIMITED", "rate limit signal", True)
    if "captcha" in normalized or "verify you are human" in normalized:
        return EgressFailureClassification("CAPTCHA_REQUIRED", "captcha challenge", True)
    if "unusual traffic" in normalized or "bot detection" in normalized:
        return EgressFailureClassification("BOT_DETECTION", "bot detection signal", True)
    if "403" in normalized or "forbidden" in normalized or "access denied" in normalized:
        return EgressFailureClassification("FORBIDDEN", "forbidden response", True)
    if "sign in" in normalized or "login required" in normalized:
        return EgressFailureClassification("AUTH_REQUIRED", "authentication required", False)
    return None


def _profile_key(policy: Policy) -> str:
    if policy.active_egress_profile:
        return policy.active_egress_profile
    if policy.proxy:
        return "proxy"
    return "direct"


def _domain_from_url(url: str | None) -> str:
    hostname = urlparse(url or "").hostname
    return hostname.lower().rstrip(".") if hostname else "*"


def _compact_message(message: str) -> str:
    return " ".join(str(message).split())[:500]


def _upsert_cooldown(cooldowns: object, cooldown: dict[str, Any]) -> list[dict[str, Any]]:
    source = cooldowns if isinstance(cooldowns, list) else []
    items = [dict(item) for item in source if isinstance(item, dict)]
    key = (cooldown["profile"], cooldown["domain"])
    replaced = False
    for index, item in enumerate(items):
        if (item.get("profile"), item.get("domain")) == key:
            items[index] = cooldown
            replaced = True
            break
    if not replaced:
        items.append(cooldown)
    return items


def _matches_cooldown(
    item: dict[str, Any],
    *,
    profile_name: str | None,
    domain: str | None,
) -> bool:
    if profile_name and item.get("profile") != profile_name:
        return False
    return not (domain and item.get("domain") != domain)


def _float_value(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
