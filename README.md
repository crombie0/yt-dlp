# yt-dlp MCP Server

An MCP server that exposes a safe, structured subset of `yt-dlp` for agents.

The server is intentionally designed as a wrapper around the public Python API
instead of a fork of `yt-dlp`. Tools perform URL probing, format listing, and
download job management. Resources expose job state, logs, metadata, and output
file lists.

## Goals

- Keep downloads explicit and auditable.
- Avoid exposing raw `yt-dlp` options directly to LLM clients.
- Force all outputs into a configured safe directory.
- Make long-running downloads asynchronous through job IDs.
- Keep metadata and format inspection read-only.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Run

```bash
YTDLP_MCP_OUTPUT_ROOT="$PWD/downloads" python -m ytdlp_mcp --transport stdio
```

You can also use a JSON config file. Environment variables override config file
values when both are present.

```json
{
  "output_root": "/absolute/path/to/downloads",
  "allow_local_urls": false,
  "max_playlist_items": 20,
  "max_concurrent_jobs": 2,
  "max_log_lines": 200
}
```

```bash
python -m ytdlp_mcp --config /absolute/path/to/ytdlp-mcp.json --transport stdio
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "yt-dlp": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "ytdlp_mcp", "--transport", "stdio"],
      "env": {
        "YTDLP_MCP_OUTPUT_ROOT": "/absolute/path/to/downloads"
      }
    }
  }
}
```

## Tools

- `get_version`: Return server, Python, `yt-dlp`, and optional `ffmpeg` versions.
- `diagnose_environment`: Return dependency, policy, and output-root diagnostics.
- `probe_url`: Extract sanitized metadata without downloading media.
- `list_formats`: Return a compact normalized format table.
- `suggest_format`: Convert a simple goal into a `yt-dlp` format selector.
- `start_download`: Start an asynchronous video/audio/subtitle download job.
- `download_audio`: Convenience wrapper for audio extraction.
- `download_subtitles`: Convenience wrapper for subtitle-only downloads.
- `list_jobs`: Return all jobs known to the current server process.
- `get_job_status`: Inspect job progress, result, errors, and log tail.
- `cancel_job`: Request cancellation for a running job.
- `get_job_artifacts`: Return a safe manifest for files produced by a job.
- `preview_artifact`: Return a bounded text/base64 preview for a job artifact.

## Resources

- `ytdlp://jobs`
- `ytdlp://jobs/{job_id}/status`
- `ytdlp://jobs/{job_id}/log`
- `ytdlp://jobs/{job_id}/info`
- `ytdlp://jobs/{job_id}/files`
- `ytdlp://jobs/{job_id}/artifacts`
- `ytdlp://jobs/{job_id}/artifacts/{index}/preview`
- `ytdlp://config/effective-policy`
- `ytdlp://config/source`
- `ytdlp://diagnostics/environment`

## Safety Model

The default policy blocks local URLs, non-HTTP(S) URLs, path traversal, raw shell
execution, and output outside `YTDLP_MCP_OUTPUT_ROOT`. Cookie access and
advanced postprocessor arguments are intentionally not exposed in the MVP.

Use this software only for media you are allowed to access and download.

## Development

The core tests avoid network access and do not require `yt-dlp` or `mcp` to be
installed.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Full development verification after installing extras:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

External live smoke tests are opt-in so the default suite stays deterministic:

```bash
YTDLP_MCP_LIVE_TEST_URL="https://example.com/media-or-watch-url" \
  .venv/bin/python -m pytest -q tests/test_live_external.py
```

To allow the live smoke to download media, add `YTDLP_MCP_LIVE_DOWNLOAD=1`.
