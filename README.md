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
  "job_db_path": "/absolute/path/to/ytdlp-mcp-jobs.sqlite3",
  "egress_state_path": "/absolute/path/to/ytdlp-mcp-egress-state.json",
  "download_archive_path": "/absolute/path/to/ytdlp-mcp-download-archive.txt",
  "proxy": null,
  "require_proxy": false,
  "active_egress_profile": null,
  "egress_profiles": {
    "local-socks-vpn": {
      "type": "proxy",
      "proxy": "socks5h://127.0.0.1:1080",
      "enabled": false,
      "description": "Enable after a VPN/proxy sidecar is verified"
    }
  },
  "allow_local_urls": false,
  "allowed_domains": ["youtube.com", "youtu.be"],
  "blocked_domains": [],
  "max_playlist_items": 20,
  "max_concurrent_jobs": 2,
  "max_log_lines": 200,
  "egress_cooldown_seconds": 3600
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
- `list_egress_profiles`: Return configured egress profiles with secrets redacted.
- `get_egress_status`: Return the active egress profile and blocking issues.
- `get_egress_health`: Return persisted egress cooldowns and recent failure events.
- `test_egress_ip`: Check the public IP seen through an egress profile.
- `verify_egress_profile`: Test and persist a profile's observed exit IP before activation.
- `activate_egress_profile`: Enable a recently verified profile in JSON config and reload policy.
- `recommend_egress_profile`: Pick the best verified profile that is not cooling down.
- `rotate_egress_profile`: Recommend or activate a verified non-active profile.
- `list_egress_templates`: List non-secret provider/proxy profile templates.
- `get_egress_template`: Return a template with setup notes and placeholders.
- `render_egress_profile_template`: Render a profile config patch from a template.
- `report_egress_failure`: Record a block-like egress failure and apply cooldown.
- `clear_egress_cooldown`: Clear persisted egress cooldowns.
- `get_download_archive`: Return download archive status and recent recorded media IDs.
- `preflight_download`: Check local policy, egress, archive, and output readiness before downloading.
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
- `ytdlp://egress/profiles`
- `ytdlp://egress/status`
- `ytdlp://egress/health`
- `ytdlp://download-archive`

## Safety Model

The default policy blocks local URLs, non-HTTP(S) URLs, path traversal, raw shell
execution, and output outside `YTDLP_MCP_OUTPUT_ROOT`. Cookie access and
advanced postprocessor arguments are intentionally not exposed in the MVP.
Set `job_db_path` or `YTDLP_MCP_JOB_DB_PATH` to persist job history and artifact
metadata across server restarts.
Set `allowed_domains` to restrict downloads to known hosts, and `blocked_domains`
to deny specific hosts or subdomains. Environment overrides are available as
`YTDLP_MCP_ALLOWED_DOMAINS` and `YTDLP_MCP_BLOCKED_DOMAINS` using comma-separated
domain lists.
Set `proxy` or `YTDLP_MCP_PROXY` to route yt-dlp network requests through an
HTTP(S) or SOCKS proxy, for example `socks5h://127.0.0.1:1080`. Set
`require_proxy` or `YTDLP_MCP_REQUIRE_PROXY=true` to fail probe/download calls
unless a proxy is configured. This prevents accidental direct egress, but it
does not guarantee anonymity; the proxy/VPN provider and destination site may
still log traffic.
For provider-agnostic operations, define `egress_profiles` and set
`active_egress_profile`. A `proxy` profile applies a yt-dlp proxy; an
`external_vpn` profile documents process/container-level VPN routing and should
only be enabled after `test_egress_ip` verifies the expected exit IP.
Set `egress_state_path` to persist egress failures and cooldowns. Block-like
errors such as HTTP 429, HTTP 403, CAPTCHA, and bot-detection messages are
classified and place the active profile/domain into cooldown for
`egress_cooldown_seconds`, preventing repeated retries from the same exit path.
The same state file stores successful and failed `verify_egress_profile`
records. `activate_egress_profile` refuses to activate a profile unless it has a
recent successful verification, unless `force=true` is explicitly supplied.
Use `recommend_egress_profile` or `rotate_egress_profile` after a cooldown to
pick a verified profile that is not currently blocked. Rotation changes the
JSON config and reloads the in-process policy, but it is rejected while jobs are
queued or running so in-flight downloads do not unexpectedly switch egress.
Use `list_egress_templates` and `render_egress_profile_template` to generate
non-secret config snippets for generic SOCKS proxies, WireGuard sidecars, or
process-level ExpressVPN-style routes. Secrets belong in the VPN sidecar or
host environment, not in the MCP config.
Set `download_archive_path` to enable yt-dlp's download archive and skip media
IDs that were already successfully recorded. This reduces duplicate requests
and helps protect the active exit IP from unnecessary repeat downloads.

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
