from __future__ import annotations

import argparse
import json
from typing import Any

from .errors import DependencyError, to_error_payload
from .jobs import JobStore
from .options import suggest_format as suggest_format_goal
from .policy import Policy
from .service import YtdlpService


def create_server(policy: Policy | None = None) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ModuleNotFoundError as exc:
        raise DependencyError(
            "mcp is not installed. Install with: python -m pip install -e '.[dev]'",
            detail=str(exc),
        ) from exc

    effective_policy = policy or Policy.from_env()
    service = YtdlpService(effective_policy)
    jobs = JobStore(effective_policy)
    mcp = FastMCP("yt-dlp")
    read_only_network = ToolAnnotations(
        readOnlyHint=True,
        idempotentHint=True,
        openWorldHint=True,
    )
    read_only_local = ToolAnnotations(
        readOnlyHint=True,
        idempotentHint=True,
        openWorldHint=False,
    )
    writes_files = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
    mutates_jobs = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )

    def _start_download_job(
        *,
        url: str,
        kind: str = "video",
        format_selector: str | None = None,
        audio_format: str = "m4a",
        subtitle_languages: list[str] | None = None,
        subtitle_format: str = "best",
        output_template: str | None = None,
        playlist_items: str | None = None,
    ) -> dict[str, Any]:
        service.validate_download_request(
            url,
            kind=kind,
            format_selector=format_selector,
            audio_format=audio_format,
            subtitle_languages=subtitle_languages,
            subtitle_format=subtitle_format,
            output_template=output_template,
            playlist_items=playlist_items,
        )

        def run(context):
            return service.download(
                url,
                context,
                kind=kind,
                format_selector=format_selector,
                audio_format=audio_format,
                subtitle_languages=subtitle_languages,
                subtitle_format=subtitle_format,
                output_template=output_template,
                playlist_items=playlist_items,
            )

        record = jobs.submit(kind, run)
        return {
            "ok": True,
            "job_id": record.job_id,
            "status_resource": f"ytdlp://jobs/{record.job_id}/status",
            "log_resource": f"ytdlp://jobs/{record.job_id}/log",
        }

    @mcp.tool(annotations=read_only_local)
    def get_version() -> dict[str, Any]:
        """Return server, Python, yt-dlp, and ffmpeg versions."""
        return {"ok": True, "versions": service.versions()}

    @mcp.tool(annotations=read_only_network)
    def probe_url(url: str, playlist_items: str | None = None) -> dict[str, Any]:
        """Extract sanitized media metadata without downloading media."""
        try:
            return {"ok": True, "info": service.probe(url, playlist_items=playlist_items)}
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=read_only_network)
    def list_formats(url: str, playlist_items: str | None = None) -> dict[str, Any]:
        """Return a normalized list of formats for a URL."""
        try:
            return {"ok": True, **service.list_formats(url, playlist_items=playlist_items)}
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=read_only_local)
    def suggest_format(goal: str) -> dict[str, Any]:
        """Convert a simple quality goal into a bounded yt-dlp selector."""
        try:
            return {"ok": True, **suggest_format_goal(goal)}
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=writes_files)
    def start_download(
        url: str,
        kind: str = "video",
        format_selector: str | None = None,
        audio_format: str = "m4a",
        subtitle_languages: list[str] | None = None,
        subtitle_format: str = "best",
        output_template: str | None = None,
        playlist_items: str | None = None,
    ) -> dict[str, Any]:
        """Start an asynchronous download job and return its job_id."""
        try:
            return _start_download_job(
                url=url,
                kind=kind,
                format_selector=format_selector,
                audio_format=audio_format,
                subtitle_languages=subtitle_languages,
                subtitle_format=subtitle_format,
                output_template=output_template,
                playlist_items=playlist_items,
            )
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=writes_files)
    def download_audio(
        url: str,
        audio_format: str = "m4a",
        output_template: str | None = None,
        playlist_items: str | None = None,
    ) -> dict[str, Any]:
        """Start an asynchronous audio-only download job."""
        try:
            return _start_download_job(
                url=url,
                kind="audio",
                audio_format=audio_format,
                output_template=output_template,
                playlist_items=playlist_items,
            )
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=writes_files)
    def download_subtitles(
        url: str,
        subtitle_languages: list[str] | None = None,
        subtitle_format: str = "best",
        output_template: str | None = None,
        playlist_items: str | None = None,
    ) -> dict[str, Any]:
        """Start an asynchronous subtitle-only download job."""
        try:
            return _start_download_job(
                url=url,
                kind="subtitles",
                subtitle_languages=subtitle_languages,
                subtitle_format=subtitle_format,
                output_template=output_template,
                playlist_items=playlist_items,
            )
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=read_only_local)
    def list_jobs(include_logs: bool = False) -> dict[str, Any]:
        """Return all jobs known to this server process."""
        return {"ok": True, "jobs": jobs.list(include_logs=include_logs)}

    @mcp.tool(annotations=read_only_local)
    def get_job_status(job_id: str, include_logs: bool = False) -> dict[str, Any]:
        """Return progress, result, and errors for a job."""
        try:
            return {"ok": True, "job": jobs.get(job_id).public_dict(include_logs=include_logs)}
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=mutates_jobs)
    def cancel_job(job_id: str) -> dict[str, Any]:
        """Request cancellation for a running or queued job."""
        try:
            record = jobs.cancel(job_id)
            return {"ok": True, "job": record.public_dict()}
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.resource("ytdlp://jobs/{job_id}/status")
    def job_status_resource(job_id: str) -> str:
        return _json(jobs.get(job_id).public_dict(include_logs=False))

    @mcp.resource("ytdlp://jobs/{job_id}/log")
    def job_log_resource(job_id: str) -> str:
        return _json({"job_id": job_id, "logs": jobs.get(job_id).logs})

    @mcp.resource("ytdlp://jobs/{job_id}/info")
    def job_info_resource(job_id: str) -> str:
        return _json({"job_id": job_id, "info": jobs.get(job_id).info})

    @mcp.resource("ytdlp://jobs/{job_id}/files")
    def job_files_resource(job_id: str) -> str:
        return _json({"job_id": job_id, "files": jobs.get(job_id).files})

    @mcp.resource("ytdlp://jobs")
    def jobs_resource() -> str:
        return _json({"jobs": jobs.list(include_logs=False)})

    @mcp.resource("ytdlp://config/effective-policy")
    def policy_resource() -> str:
        return _json(effective_policy.as_dict())

    @mcp.prompt()
    def plan_download(goal: str, url: str) -> str:
        """Help a user plan a safe yt-dlp download."""
        return (
            "Plan a safe yt-dlp MCP download.\n"
            f"URL: {url}\n"
            f"Goal: {goal}\n"
            "First call probe_url or list_formats. Only call start_download after the user "
            "has confirmed the desired media type, quality, and output behavior."
        )

    @mcp.prompt()
    def diagnose_error(error_log: str) -> str:
        """Analyze a yt-dlp MCP error log."""
        return (
            "Diagnose this yt-dlp MCP error. Separate likely causes from confirmed facts, "
            "and avoid asking for secrets such as cookies unless absolutely necessary.\n\n"
            f"{error_log}"
        )

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the yt-dlp MCP server.")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    args = parser.parse_args(argv)

    server = create_server()
    server.run(transport=args.transport)
    return 0


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
