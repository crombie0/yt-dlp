from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import PolicyError
from .policy import Policy, validate_output_template, validate_playlist_items

ProgressHook = Callable[[dict[str, Any]], None]

ALLOWED_DOWNLOAD_KINDS = {"video", "audio", "subtitles"}
ALLOWED_AUDIO_FORMATS = {"best", "m4a", "mp3", "opus", "flac", "wav"}
ALLOWED_SUBTITLE_FORMATS = {"best", "srt", "vtt", "ass"}


def build_probe_options(policy: Policy, *, playlist_items: str | None = None) -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": False,
        "skip_download": True,
        "extract_flat": False,
        "playlist_items": validate_playlist_items(playlist_items, policy),
        "noplaylist": False,
    }


def build_download_options(
    policy: Policy,
    *,
    kind: str,
    format_selector: str | None = None,
    audio_format: str = "m4a",
    subtitle_languages: list[str] | None = None,
    subtitle_format: str = "best",
    output_template: str | None = None,
    playlist_items: str | None = None,
    progress_hook: ProgressHook | None = None,
    logger: object | None = None,
) -> dict[str, Any]:
    kind = _validate_kind(kind)
    output_root = policy.resolved_output_root
    template = validate_output_template(output_template)

    options: dict[str, Any] = {
        "paths": {"home": str(output_root)},
        "outtmpl": {"default": template},
        "restrictfilenames": True,
        "windowsfilenames": True,
        "ignoreerrors": False,
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "playlist_items": validate_playlist_items(playlist_items, policy),
        "progress_hooks": [progress_hook] if progress_hook else [],
    }
    if logger is not None:
        options["logger"] = logger

    if kind == "video":
        options["format"] = format_selector or "bv*+ba/b"
        options["merge_output_format"] = "mp4"
        options["writethumbnail"] = False
        options["writeinfojson"] = True
    elif kind == "audio":
        audio_format = _validate_audio_format(audio_format)
        options["format"] = format_selector or "bestaudio/best"
        options["postprocessors"] = _audio_postprocessors(audio_format)
        options["writeinfojson"] = True
    elif kind == "subtitles":
        subtitle_format = _validate_subtitle_format(subtitle_format)
        options["skip_download"] = True
        options["writesubtitles"] = True
        options["writeautomaticsub"] = True
        options["subtitlesformat"] = subtitle_format
        options["subtitleslangs"] = _validate_subtitle_languages(subtitle_languages)

    return options


def suggest_format(goal: str) -> dict[str, str]:
    normalized = " ".join((goal or "").lower().split())
    if not normalized:
        raise PolicyError("A format goal is required.")

    if "audio" in normalized or "mp3" in normalized or "m4a" in normalized:
        audio_format = "mp3" if "mp3" in normalized else "m4a"
        return {
            "kind": "audio",
            "format_selector": "bestaudio/best",
            "audio_format": audio_format,
            "reason": "Audio-only goal detected.",
        }

    if "small" in normalized or "lowest" in normalized or "bandwidth" in normalized:
        return {
            "kind": "video",
            "format_selector": "worst[ext=mp4]/worst",
            "reason": "Small output size goal detected.",
        }

    if "720" in normalized:
        selector = "bv*[height<=720]+ba/b[height<=720]/b"
    elif "1080" in normalized:
        selector = "bv*[height<=1080]+ba/b[height<=1080]/b"
    elif "4k" in normalized or "2160" in normalized:
        selector = "bv*[height<=2160]+ba/b[height<=2160]/b"
    else:
        selector = "bv*+ba/b"

    if "mp4" in normalized:
        selector = selector.replace("bv*", "bv*[ext=mp4]").replace("+ba", "+ba[ext=m4a]")

    return {
        "kind": "video",
        "format_selector": selector,
        "reason": "Video goal converted to a bounded yt-dlp selector.",
    }


def normalize_formats(info: dict[str, Any]) -> list[dict[str, Any]]:
    formats = _formats_from_info(info)
    normalized: list[dict[str, Any]] = []
    for item in formats:
        normalized.append(
            {
                "format_id": item.get("format_id"),
                "ext": item.get("ext"),
                "resolution": item.get("resolution"),
                "height": item.get("height"),
                "width": item.get("width"),
                "fps": item.get("fps"),
                "vcodec": item.get("vcodec"),
                "acodec": item.get("acodec"),
                "filesize": item.get("filesize") or item.get("filesize_approx"),
                "tbr": item.get("tbr"),
                "protocol": item.get("protocol"),
                "format_note": item.get("format_note"),
            }
        )
    return normalized


def ensure_output_root(policy: Policy) -> Path:
    root = policy.resolved_output_root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _formats_from_info(info: dict[str, Any]) -> list[dict[str, Any]]:
    direct_formats = info.get("formats")
    if isinstance(direct_formats, list):
        return [item for item in direct_formats if isinstance(item, dict)]

    entries = info.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("formats"), list):
                return [item for item in entry["formats"] if isinstance(item, dict)]

    return []


def _validate_kind(kind: str) -> str:
    normalized = (kind or "").strip().lower()
    if normalized not in ALLOWED_DOWNLOAD_KINDS:
        allowed = ", ".join(sorted(ALLOWED_DOWNLOAD_KINDS))
        raise PolicyError(f"kind must be one of: {allowed}.")
    return normalized


def _validate_audio_format(audio_format: str) -> str:
    normalized = (audio_format or "m4a").strip().lower()
    if normalized not in ALLOWED_AUDIO_FORMATS:
        allowed = ", ".join(sorted(ALLOWED_AUDIO_FORMATS))
        raise PolicyError(f"audio_format must be one of: {allowed}.")
    return "best" if normalized == "best" else normalized


def _validate_subtitle_format(subtitle_format: str) -> str:
    normalized = (subtitle_format or "best").strip().lower()
    if normalized not in ALLOWED_SUBTITLE_FORMATS:
        allowed = ", ".join(sorted(ALLOWED_SUBTITLE_FORMATS))
        raise PolicyError(f"subtitle_format must be one of: {allowed}.")
    return normalized


def _validate_subtitle_languages(languages: list[str] | None) -> list[str]:
    if not languages:
        return ["en"]

    normalized: list[str] = []
    for language in languages:
        code = (language or "").strip().lower()
        if not code:
            continue
        if len(code) > 12 or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in code):
            raise PolicyError(
                "subtitle language codes may only contain letters, numbers, '_' or '-'."
            )
        normalized.append(code)

    if not normalized:
        raise PolicyError("At least one subtitle language is required.")
    return normalized


def _audio_postprocessors(audio_format: str) -> list[dict[str, Any]]:
    if audio_format == "best":
        return []
    return [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_format,
            "preferredquality": "0",
        }
    ]
