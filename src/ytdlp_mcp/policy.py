from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .errors import PolicyError

DEFAULT_OUTPUT_ROOT = "downloads"
DEFAULT_MAX_PLAYLIST_ITEMS = 20
DEFAULT_MAX_CONCURRENT_JOBS = 2
DEFAULT_MAX_LOG_LINES = 200


@dataclass(frozen=True, slots=True)
class Policy:
    output_root: Path = field(default_factory=lambda: Path(DEFAULT_OUTPUT_ROOT))
    job_db_path: Path | None = None
    allow_local_urls: bool = False
    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()
    max_playlist_items: int = DEFAULT_MAX_PLAYLIST_ITEMS
    max_concurrent_jobs: int = DEFAULT_MAX_CONCURRENT_JOBS
    max_log_lines: int = DEFAULT_MAX_LOG_LINES

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_root", Path(self.output_root))
        if self.job_db_path is not None:
            object.__setattr__(self, "job_db_path", Path(self.job_db_path))
        object.__setattr__(self, "allowed_domains", normalize_domain_list(self.allowed_domains))
        object.__setattr__(self, "blocked_domains", normalize_domain_list(self.blocked_domains))

    @classmethod
    def from_env(cls) -> Policy:
        output_root = Path(os.environ.get("YTDLP_MCP_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT))
        return cls(
            output_root=output_root,
            job_db_path=_env_path("YTDLP_MCP_JOB_DB_PATH"),
            allow_local_urls=_env_bool("YTDLP_MCP_ALLOW_LOCAL_URLS", default=False),
            allowed_domains=_env_list("YTDLP_MCP_ALLOWED_DOMAINS"),
            blocked_domains=_env_list("YTDLP_MCP_BLOCKED_DOMAINS"),
            max_playlist_items=_env_int(
                "YTDLP_MCP_MAX_PLAYLIST_ITEMS",
                default=DEFAULT_MAX_PLAYLIST_ITEMS,
                minimum=1,
            ),
            max_concurrent_jobs=_env_int(
                "YTDLP_MCP_MAX_CONCURRENT_JOBS",
                default=DEFAULT_MAX_CONCURRENT_JOBS,
                minimum=1,
            ),
            max_log_lines=_env_int(
                "YTDLP_MCP_MAX_LOG_LINES",
                default=DEFAULT_MAX_LOG_LINES,
                minimum=1,
            ),
        )

    @property
    def resolved_output_root(self) -> Path:
        return self.output_root.expanduser().resolve()

    def as_dict(self) -> dict[str, object]:
        job_db_path = self.resolved_job_db_path
        return {
            "output_root": str(self.resolved_output_root),
            "job_db_path": str(job_db_path) if job_db_path else None,
            "allow_local_urls": self.allow_local_urls,
            "allowed_domains": list(self.allowed_domains),
            "blocked_domains": list(self.blocked_domains),
            "max_playlist_items": self.max_playlist_items,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "max_log_lines": self.max_log_lines,
        }

    @property
    def resolved_job_db_path(self) -> Path | None:
        if self.job_db_path is None:
            return None
        return self.job_db_path.expanduser().resolve()


def validate_url(url: str, policy: Policy) -> str:
    url = (url or "").strip()
    if not url:
        raise PolicyError("URL is required.")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise PolicyError("Only http and https URLs are allowed.")
    if not parsed.hostname:
        raise PolicyError("URL must include a hostname.")

    hostname = parsed.hostname.strip().lower().rstrip(".")
    if not policy.allow_local_urls and _is_local_hostname(hostname):
        raise PolicyError("Local or private network URLs are blocked by default.")
    if _domain_matches(hostname, policy.blocked_domains):
        raise PolicyError("URL hostname is blocked by server policy.")
    if policy.allowed_domains and not _domain_matches(hostname, policy.allowed_domains):
        raise PolicyError("URL hostname is not in the allowed domain list.")

    return url


def normalize_domain_list(domains: object) -> tuple[str, ...]:
    if domains is None:
        return ()
    if isinstance(domains, str):
        candidates = [item.strip() for item in domains.split(",")]
    else:
        try:
            candidates = list(domains)  # type: ignore[arg-type]
        except TypeError as exc:
            raise PolicyError("domain lists must be a list of strings.") from exc

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        domain = _normalize_domain(candidate)
        if domain and domain not in seen:
            normalized.append(domain)
            seen.add(domain)
    return tuple(normalized)


def validate_playlist_items(playlist_items: str | None, policy: Policy) -> str | None:
    if playlist_items is None or playlist_items == "":
        return f"1-{policy.max_playlist_items}"

    value = playlist_items.strip()
    if not value:
        return f"1-{policy.max_playlist_items}"

    # yt-dlp supports ranges such as "1-5" and comma lists. The MVP keeps this
    # intentionally narrower so the server can enforce an upper bound reliably.
    if value.isdigit():
        number = int(value)
        if number < 1 or number > policy.max_playlist_items:
            raise PolicyError(
                f"playlist_items must be between 1 and {policy.max_playlist_items}."
            )
        return str(number)

    if "-" in value:
        start_text, end_text = value.split("-", 1)
        if not start_text.isdigit() or not end_text.isdigit():
            raise PolicyError("playlist_items ranges must look like '1-5'.")
        start = int(start_text)
        end = int(end_text)
        if start < 1 or end < start or end > policy.max_playlist_items:
            raise PolicyError(
                f"playlist_items range must stay within 1-{policy.max_playlist_items}."
            )
        return f"{start}-{end}"

    raise PolicyError("playlist_items must be a number or a simple range such as '1-5'.")


def validate_output_template(output_template: str | None) -> str:
    template = (output_template or "%(title).200B [%(id)s].%(ext)s").strip()
    if not template:
        raise PolicyError("output_template cannot be empty.")

    path = Path(template)
    if path.is_absolute():
        raise PolicyError("output_template must be relative to the output root.")
    if any(part == ".." for part in path.parts):
        raise PolicyError("output_template cannot contain '..' path traversal.")
    if "\x00" in template:
        raise PolicyError("output_template cannot contain NUL bytes.")

    return template


def safe_child_path(policy: Policy, *parts: str) -> Path:
    root = policy.resolved_output_root
    candidate = root.joinpath(*parts).expanduser().resolve()
    if candidate != root and root not in candidate.parents:
        raise PolicyError("Resolved path escapes the configured output root.")
    return candidate


def _is_local_hostname(hostname: str) -> bool:
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        return True

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False

    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _domain_matches(hostname: str, domains: tuple[str, ...]) -> bool:
    normalized_hostname = hostname.lower().rstrip(".")
    return any(
        normalized_hostname == domain or normalized_hostname.endswith(f".{domain}")
        for domain in domains
    )


def _normalize_domain(domain: object) -> str:
    if not isinstance(domain, str):
        raise PolicyError("domain list entries must be strings.")

    value = domain.strip().lower().removeprefix(".").rstrip(".")
    if not value:
        return ""
    if "://" in value or "/" in value or "@" in value or ":" in value:
        raise PolicyError(f"Invalid domain entry: {domain}")

    labels = value.split(".")
    for label in labels:
        if not label:
            raise PolicyError(f"Invalid domain entry: {domain}")
        if len(label) > 63:
            raise PolicyError(f"Invalid domain entry: {domain}")
        if label.startswith("-") or label.endswith("-"):
            raise PolicyError(f"Invalid domain entry: {domain}")
        if not all(ch.isascii() and (ch.isalnum() or ch == "-") for ch in label):
            raise PolicyError(f"Invalid domain entry: {domain}")
    return value


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int, minimum: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise PolicyError(f"{name} must be an integer.") from exc
    if parsed < minimum:
        raise PolicyError(f"{name} must be at least {minimum}.")
    return parsed


def _env_list(name: str) -> tuple[str, ...]:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return ()
    return normalize_domain_list(value)


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return Path(value)
