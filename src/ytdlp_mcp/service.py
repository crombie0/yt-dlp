from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .errors import DependencyError, DownloadError, JobCancelledError
from .jobs import JobContext
from .options import (
    build_download_options,
    build_probe_options,
    ensure_output_root,
    normalize_formats,
)
from .policy import Policy, validate_url


class YtdlpService:
    def __init__(self, policy: Policy):
        self._policy = policy

    def versions(self) -> dict[str, Any]:
        yt_dlp_version: str | None = None
        try:
            yt_dlp = _load_yt_dlp()
            yt_dlp_version = yt_dlp.version.__version__
        except DependencyError:
            yt_dlp_version = None

        return {
            "server": __version__,
            "python": sys.version.split()[0],
            "yt_dlp": yt_dlp_version,
            "ffmpeg": _ffmpeg_version(),
        }

    def probe(self, url: str, *, playlist_items: str | None = None) -> dict[str, Any]:
        validated_url = validate_url(url, self._policy)
        yt_dlp = _load_yt_dlp()
        options = build_probe_options(self._policy, playlist_items=playlist_items)
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(validated_url, download=False)
                return ydl.sanitize_info(info)
        except Exception as exc:
            raise DownloadError("yt-dlp failed while probing the URL.", detail=str(exc)) from exc

    def list_formats(self, url: str, *, playlist_items: str | None = None) -> dict[str, Any]:
        info = self.probe(url, playlist_items=playlist_items)
        return {
            "webpage_url": info.get("webpage_url"),
            "title": info.get("title"),
            "formats": normalize_formats(info),
        }

    def validate_download_request(
        self,
        url: str,
        *,
        kind: str,
        format_selector: str | None = None,
        audio_format: str = "m4a",
        subtitle_languages: list[str] | None = None,
        subtitle_format: str = "best",
        output_template: str | None = None,
        playlist_items: str | None = None,
    ) -> None:
        validate_url(url, self._policy)
        build_download_options(
            self._policy,
            kind=kind,
            format_selector=format_selector,
            audio_format=audio_format,
            subtitle_languages=subtitle_languages,
            subtitle_format=subtitle_format,
            output_template=output_template,
            playlist_items=playlist_items,
        )

    def download(
        self,
        url: str,
        context: JobContext,
        *,
        kind: str,
        format_selector: str | None = None,
        audio_format: str = "m4a",
        subtitle_languages: list[str] | None = None,
        subtitle_format: str = "best",
        output_template: str | None = None,
        playlist_items: str | None = None,
    ) -> dict[str, Any]:
        context.check_cancelled()
        validated_url = validate_url(url, self._policy)
        ensure_output_root(self._policy)
        yt_dlp = _load_yt_dlp()
        seen_files: set[str] = set()

        def progress_hook(progress: dict[str, Any]) -> None:
            context.check_cancelled()
            context.update_progress(progress)
            filename = progress.get("filename") or progress.get("tmpfilename")
            if filename:
                seen_files.add(str(filename))

        logger = _JobLogger(context)
        options = build_download_options(
            self._policy,
            kind=kind,
            format_selector=format_selector,
            audio_format=audio_format,
            subtitle_languages=subtitle_languages,
            subtitle_format=subtitle_format,
            output_template=output_template,
            playlist_items=playlist_items,
            progress_hook=progress_hook,
            logger=logger,
        )

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(validated_url, download=True)
                sanitized = ydl.sanitize_info(info)
        except JobCancelledError:
            raise
        except Exception as exc:
            raise DownloadError("yt-dlp failed while downloading media.", detail=str(exc)) from exc

        files = _discover_existing_files(
            self._policy,
            seen_files | _candidate_files_from_info(sanitized),
        )
        return {
            "ok": True,
            "kind": kind,
            "files": files,
            "info": _compact_info(sanitized),
        }


class _JobLogger:
    def __init__(self, context: JobContext):
        self._context = context

    def debug(self, message: str) -> None:
        self._context.append_log("debug", message)

    def warning(self, message: str) -> None:
        self._context.append_log("warning", message)

    def error(self, message: str) -> None:
        self._context.append_log("error", message)


def _load_yt_dlp() -> Any:
    try:
        return importlib.import_module("yt_dlp")
    except ModuleNotFoundError as exc:
        raise DependencyError(
            "yt-dlp is not installed. Install with: python -m pip install -e '.[dev]'",
            detail=str(exc),
        ) from exc


def _ffmpeg_version() -> str | None:
    if not shutil.which("ffmpeg"):
        return None
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    return first_line or None


def _discover_existing_files(policy: Policy, candidates: set[str]) -> list[str]:
    root = policy.resolved_output_root
    files: list[str] = []
    for candidate in sorted(candidates):
        path = Path(candidate).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not resolved.exists() or not resolved.is_file():
            continue
        if resolved != root and root not in resolved.parents:
            continue
        files.append(str(resolved))
    return files


def _candidate_files_from_info(info: dict[str, Any]) -> set[str]:
    candidates: set[str] = set()
    requested_downloads = info.get("requested_downloads")
    if isinstance(requested_downloads, list):
        for download in requested_downloads:
            if not isinstance(download, dict):
                continue
            for key in ("filepath", "filename"):
                value = download.get(key)
                if value:
                    candidates.add(str(value))
    return candidates


def _compact_info(info: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "title",
        "webpage_url",
        "extractor",
        "extractor_key",
        "duration",
        "thumbnail",
        "playlist_count",
        "requested_downloads",
    )
    return {key: info.get(key) for key in keys if key in info}
