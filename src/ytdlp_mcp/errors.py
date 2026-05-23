from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ErrorPayload:
    code: str
    message: str
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
            },
        }
        if self.detail:
            payload["error"]["detail"] = self.detail
        return payload


class YtdlpMcpError(Exception):
    code = "YTDLP_MCP_ERROR"
    public_message = "The yt-dlp MCP server could not complete the request."

    def __init__(self, message: str | None = None, *, detail: str | None = None):
        super().__init__(message or self.public_message)
        self.detail = detail

    def to_payload(self) -> ErrorPayload:
        return ErrorPayload(self.code, str(self), self.detail)


class PolicyError(YtdlpMcpError):
    code = "POLICY_DENIED"
    public_message = "The request is not allowed by the server policy."


class DependencyError(YtdlpMcpError):
    code = "DEPENDENCY_MISSING"
    public_message = "A required runtime dependency is not installed."


class DownloadError(YtdlpMcpError):
    code = "DOWNLOAD_FAILED"
    public_message = "yt-dlp failed while handling the media request."


class JobNotFoundError(YtdlpMcpError):
    code = "JOB_NOT_FOUND"
    public_message = "No job exists for the supplied job_id."


class JobCancelledError(YtdlpMcpError):
    code = "JOB_CANCELLED"
    public_message = "The job was cancelled."


def to_error_payload(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, YtdlpMcpError):
        return exc.to_payload().as_dict()
    return ErrorPayload("UNEXPECTED_ERROR", str(exc)).as_dict()
