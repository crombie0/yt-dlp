from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from .errors import PolicyError, YtdlpMcpError
from .policy import Policy

DEFAULT_PREVIEW_BYTES = 16_384
MAX_PREVIEW_BYTES = 262_144
TEXT_EXTENSIONS = {
    ".ass",
    ".csv",
    ".description",
    ".info.json",
    ".json",
    ".lrc",
    ".md",
    ".srt",
    ".txt",
    ".vtt",
    ".xml",
}
TEXT_MIME_PREFIXES = ("application/json", "application/xml", "text/")


class ArtifactNotFoundError(YtdlpMcpError):
    code = "ARTIFACT_NOT_FOUND"
    public_message = "No artifact exists for the supplied job_id and index."


def build_artifact_manifest(policy: Policy, job_id: str, files: list[str]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for index, file_path in enumerate(files):
        path = _resolve_artifact_path(policy, file_path)
        mime_type = _guess_mime_type(path)
        exists = path.exists() and path.is_file()
        stat = path.stat() if exists else None
        artifacts.append(
            {
                "index": index,
                "name": path.name,
                "path": str(path),
                "exists": exists,
                "size": stat.st_size if stat else None,
                "modified_at": stat.st_mtime if stat else None,
                "mime_type": mime_type,
                "is_text": _is_text_artifact(path, mime_type),
                "resource": f"ytdlp://jobs/{job_id}/artifacts/{index}/preview",
            }
        )
    return artifacts


def preview_artifact(
    policy: Policy,
    job_id: str,
    files: list[str],
    index: int,
    *,
    max_bytes: int = DEFAULT_PREVIEW_BYTES,
) -> dict[str, Any]:
    if index < 0 or index >= len(files):
        raise ArtifactNotFoundError(f"No artifact exists at index={index} for job_id={job_id}.")

    path = _resolve_artifact_path(policy, files[index])
    if not path.exists() or not path.is_file():
        raise ArtifactNotFoundError(f"Artifact file no longer exists for job_id={job_id}.")

    byte_limit = _normalize_preview_bytes(max_bytes)
    raw = path.read_bytes()[:byte_limit]
    stat = path.stat()
    mime_type = _guess_mime_type(path)
    is_text = _is_text_artifact(path, mime_type)
    payload: dict[str, Any] = {
        "job_id": job_id,
        "index": index,
        "name": path.name,
        "path": str(path),
        "size": stat.st_size,
        "mime_type": mime_type,
        "is_text": is_text,
        "truncated": stat.st_size > len(raw),
        "bytes_read": len(raw),
    }

    if is_text:
        payload["encoding"] = "utf-8"
        payload["text"] = raw.decode("utf-8", errors="replace")
    else:
        payload["encoding"] = "base64"
        payload["base64"] = base64.b64encode(raw).decode("ascii")

    return payload


def _resolve_artifact_path(policy: Policy, file_path: str) -> Path:
    path = Path(file_path).expanduser().resolve()
    root = policy.resolved_output_root
    if path != root and root not in path.parents:
        raise PolicyError("Artifact path escapes the configured output root.")
    return path


def _guess_mime_type(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    return mime_type or "application/octet-stream"


def _is_text_artifact(path: Path, mime_type: str) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    return any(mime_type.startswith(prefix) for prefix in TEXT_MIME_PREFIXES)


def _normalize_preview_bytes(max_bytes: int) -> int:
    try:
        parsed = int(max_bytes)
    except (TypeError, ValueError) as exc:
        raise PolicyError("max_bytes must be an integer.") from exc
    if parsed < 1:
        raise PolicyError("max_bytes must be at least 1.")
    return min(parsed, MAX_PREVIEW_BYTES)
