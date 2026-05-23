import asyncio
import functools
import json
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory

from ytdlp_mcp.policy import Policy
from ytdlp_mcp.server import create_server

RUNTIME_AVAILABLE = find_spec("mcp") is not None and find_spec("yt_dlp") is not None


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        return


def _tool_payload(result):
    content, structured = result
    if structured is not None:
        return structured
    return json.loads(content[0].text)


@unittest.skipUnless(RUNTIME_AVAILABLE, "mcp and yt-dlp packages are required")
class LocalDownloadIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_download_job_artifact_flow_with_local_http_file(self):
        with TemporaryDirectory() as root:
            root_path = Path(root)
            web_root = root_path / "web"
            output_root = root_path / "downloads"
            web_root.mkdir()
            output_root.mkdir()
            fixture = web_root / "sample.mp4"
            fixture.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"local-test-media" * 16)

            with _serve_directory(web_root) as base_url:
                server = create_server(
                    Policy(output_root=output_root, allow_local_urls=True)
                )
                start = await server.call_tool(
                    "start_download",
                    {
                        "url": f"{base_url}/sample.mp4",
                        "kind": "video",
                        "format_selector": "best",
                        "output_template": "%(id)s.%(ext)s",
                    },
                )
                start_payload = _tool_payload(start)
                self.assertTrue(start_payload["ok"], start_payload)
                job_id = start_payload["job_id"]

                job = await _wait_for_job(server, job_id)
                self.assertEqual(job["status"], "succeeded", job)
                self.assertTrue(job["files"], job)
                for file_path in job["files"]:
                    self.assertTrue(Path(file_path).is_file(), file_path)
                    self.assertIn(output_root.resolve(), Path(file_path).resolve().parents)

                artifacts = _tool_payload(
                    await server.call_tool("get_job_artifacts", {"job_id": job_id})
                )
                self.assertTrue(artifacts["ok"], artifacts)
                self.assertGreaterEqual(len(artifacts["artifacts"]), 1)
                self.assertTrue(artifacts["artifacts"][0]["exists"])

                preview = _tool_payload(
                    await server.call_tool(
                        "preview_artifact",
                        {"job_id": job_id, "index": 0, "max_bytes": 32},
                    )
                )
                self.assertTrue(preview["ok"], preview)
                self.assertEqual(preview["artifact"]["encoding"], "base64")
                self.assertLessEqual(preview["artifact"]["bytes_read"], 32)


async def _wait_for_job(server, job_id: str, *, timeout: float = 10.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        result = await server.call_tool("get_job_status", {"job_id": job_id, "include_logs": True})
        payload = _tool_payload(result)
        if not payload["ok"]:
            raise AssertionError(payload)
        job = payload["job"]
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return job
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"job {job_id} did not finish before timeout: {job}")
        await asyncio.sleep(0.05)


class _serve_directory:
    def __init__(self, directory: Path):
        handler = functools.partial(QuietHandler, directory=str(directory))
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self._thread.start()
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
