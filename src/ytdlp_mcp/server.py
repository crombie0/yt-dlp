from __future__ import annotations

import argparse
import json
from typing import Any

from .artifacts import build_artifact_manifest
from .artifacts import preview_artifact as preview_artifact_payload
from .config import load_configured_policy
from .download_archive import archive_summary
from .egress import get_egress_status as build_egress_status
from .egress import list_egress_profiles as build_egress_profiles
from .egress import test_egress_ip as test_egress_ip_request
from .egress_health import EgressHealthStore, classify_failure
from .errors import DependencyError, to_error_payload
from .jobs import JobStore
from .options import suggest_format as suggest_format_goal
from .policy import Policy
from .service import YtdlpService


def create_server(
    policy: Policy | None = None,
    *,
    config_source: dict[str, Any] | None = None,
) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ModuleNotFoundError as exc:
        raise DependencyError(
            "mcp is not installed. Install with: python -m pip install -e '.[dev]'",
            detail=str(exc),
        ) from exc

    loaded_config = None if policy else load_configured_policy()
    effective_policy = policy or loaded_config.policy
    effective_config_source = config_source or (
        loaded_config.source if loaded_config else {"config_loaded": False, "injected_policy": True}
    )
    egress_health = (
        EgressHealthStore(effective_policy.resolved_egress_state_path)
        if effective_policy.resolved_egress_state_path is not None
        else None
    )
    service = YtdlpService(effective_policy, egress_health=egress_health)
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

    @mcp.tool(annotations=read_only_local)
    def diagnose_environment() -> dict[str, Any]:
        """Return dependency, policy, and output-root diagnostics."""
        try:
            return {"ok": True, "diagnostics": service.diagnostics()}
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=read_only_local)
    def list_egress_profiles() -> dict[str, Any]:
        """Return configured egress profiles with secrets redacted."""
        try:
            return {"ok": True, "egress": build_egress_profiles(effective_policy)}
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=read_only_local)
    def get_egress_status() -> dict[str, Any]:
        """Return the active egress profile and blocking issues."""
        try:
            egress = build_egress_status(effective_policy)
            if egress_health is not None:
                egress["health"] = egress_health.status(effective_policy)
            return {"ok": True, "egress": egress}
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=read_only_local)
    def get_egress_health() -> dict[str, Any]:
        """Return persisted egress cooldowns and recent failure events."""
        try:
            if egress_health is None:
                return {
                    "ok": True,
                    "egress_health": {
                        "enabled": False,
                        "detail": "egress_state_path is not configured",
                    },
                }
            return {"ok": True, "egress_health": egress_health.status(effective_policy)}
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=read_only_local)
    def get_download_archive(limit: int = 50) -> dict[str, Any]:
        """Return download archive status and recent recorded media IDs."""
        try:
            return {"ok": True, "archive": archive_summary(effective_policy, limit=limit)}
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=mutates_jobs)
    def report_egress_failure(
        url: str,
        message: str,
    ) -> dict[str, Any]:
        """Record an egress failure and apply cooldown for block-like errors."""
        try:
            if egress_health is None:
                return {
                    "ok": False,
                    "error": {
                        "code": "EGRESS_HEALTH_DISABLED",
                        "message": "egress_state_path is not configured.",
                    },
                }
            classification = classify_failure(message)
            if classification is None:
                return {
                    "ok": True,
                    "classification": None,
                    "event": None,
                }
            event = egress_health.record_failure(
                effective_policy,
                url,
                classification,
                message=message,
            )
            return {
                "ok": True,
                "classification": classification.as_dict(),
                "event": event,
            }
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=mutates_jobs)
    def clear_egress_cooldown(
        profile_name: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Clear persisted egress cooldowns by profile and/or domain."""
        try:
            if egress_health is None:
                return {
                    "ok": False,
                    "error": {
                        "code": "EGRESS_HEALTH_DISABLED",
                        "message": "egress_state_path is not configured.",
                    },
                }
            return {
                "ok": True,
                "result": egress_health.clear_cooldowns(
                    profile_name=profile_name,
                    domain=domain,
                ),
            }
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=read_only_network)
    def test_egress_ip(
        profile_name: str | None = None,
        url: str = "https://api.ipify.org?format=json",
        timeout: int = 10,
    ) -> dict[str, Any]:
        """Check the public IP seen through an egress profile."""
        try:
            return {
                "ok": True,
                "egress": test_egress_ip_request(
                    effective_policy,
                    profile_name=profile_name,
                    url=url,
                    timeout=timeout,
                ),
            }
        except Exception as exc:
            return to_error_payload(exc)

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

    @mcp.tool(annotations=read_only_local)
    def get_job_artifacts(job_id: str) -> dict[str, Any]:
        """Return a manifest of files produced by a job."""
        try:
            record = jobs.get(job_id)
            return {
                "ok": True,
                "job_id": job_id,
                "artifacts": build_artifact_manifest(effective_policy, job_id, record.files),
            }
        except Exception as exc:
            return to_error_payload(exc)

    @mcp.tool(annotations=read_only_local)
    def preview_artifact(
        job_id: str,
        index: int,
        max_bytes: int = 16384,
    ) -> dict[str, Any]:
        """Return a bounded preview for a job artifact."""
        try:
            record = jobs.get(job_id)
            return {
                "ok": True,
                "artifact": preview_artifact_payload(
                    effective_policy,
                    job_id,
                    record.files,
                    index,
                    max_bytes=max_bytes,
                ),
            }
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

    @mcp.resource("ytdlp://jobs/{job_id}/artifacts")
    def job_artifacts_resource(job_id: str) -> str:
        record = jobs.get(job_id)
        return _json(
            {
                "job_id": job_id,
                "artifacts": build_artifact_manifest(effective_policy, job_id, record.files),
            }
        )

    @mcp.resource("ytdlp://jobs/{job_id}/artifacts/{index}/preview")
    def artifact_preview_resource(job_id: str, index: str) -> str:
        record = jobs.get(job_id)
        return _json(preview_artifact_payload(effective_policy, job_id, record.files, int(index)))

    @mcp.resource("ytdlp://jobs")
    def jobs_resource() -> str:
        return _json({"jobs": jobs.list(include_logs=False)})

    @mcp.resource("ytdlp://config/effective-policy")
    def policy_resource() -> str:
        return _json(effective_policy.as_dict())

    @mcp.resource("ytdlp://config/source")
    def config_source_resource() -> str:
        return _json(effective_config_source)

    @mcp.resource("ytdlp://diagnostics/environment")
    def diagnostics_resource() -> str:
        return _json(service.diagnostics())

    @mcp.resource("ytdlp://egress/profiles")
    def egress_profiles_resource() -> str:
        return _json(build_egress_profiles(effective_policy))

    @mcp.resource("ytdlp://egress/status")
    def egress_status_resource() -> str:
        egress = build_egress_status(effective_policy)
        if egress_health is not None:
            egress["health"] = egress_health.status(effective_policy)
        return _json(egress)

    @mcp.resource("ytdlp://egress/health")
    def egress_health_resource() -> str:
        if egress_health is None:
            return _json(
                {
                    "enabled": False,
                    "detail": "egress_state_path is not configured",
                }
            )
        return _json(egress_health.status(effective_policy))

    @mcp.resource("ytdlp://download-archive")
    def download_archive_resource() -> str:
        return _json(archive_summary(effective_policy))

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
    parser.add_argument("--config", help="Path to a JSON config file.")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    args = parser.parse_args(argv)

    loaded_config = load_configured_policy(args.config)
    server = create_server(loaded_config.policy, config_source=loaded_config.source)
    server.run(transport=args.transport)
    return 0


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
