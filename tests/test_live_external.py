import json
import os
import unittest
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory

from ytdlp_mcp.policy import Policy
from ytdlp_mcp.service import YtdlpService

YTDLP_AVAILABLE = find_spec("yt_dlp") is not None
LIVE_TEST_URL = os.environ.get("YTDLP_MCP_LIVE_TEST_URL")
LIVE_DOWNLOAD = os.environ.get("YTDLP_MCP_LIVE_DOWNLOAD") == "1"


@unittest.skipUnless(YTDLP_AVAILABLE, "yt-dlp package is required")
@unittest.skipUnless(LIVE_TEST_URL, "set YTDLP_MCP_LIVE_TEST_URL to run external live smoke")
class ExternalLiveSmokeTests(unittest.TestCase):
    def test_probe_external_live_url(self):
        with TemporaryDirectory() as root:
            service = YtdlpService(Policy(output_root=Path(root)))

            info = service.probe(LIVE_TEST_URL, playlist_items="1")

            self.assertIsInstance(info, dict)
            self.assertTrue(info.get("id") or info.get("title") or info.get("webpage_url"))

    @unittest.skipUnless(LIVE_DOWNLOAD, "set YTDLP_MCP_LIVE_DOWNLOAD=1 to download live URL")
    def test_download_external_live_url(self):
        from ytdlp_mcp.jobs import JobStore

        with TemporaryDirectory() as root:
            policy = Policy(output_root=Path(root))
            service = YtdlpService(policy)
            store = JobStore(policy)

            record = store.submit(
                "video",
                lambda context: service.download(
                    LIVE_TEST_URL,
                    context,
                    kind="video",
                    format_selector="best",
                    output_template="%(id)s.%(ext)s",
                    playlist_items="1",
                ),
            )
            result = record.future.result(timeout=60)

            self.assertTrue(result["ok"], json.dumps(result, indent=2))
            self.assertTrue(result["files"], json.dumps(result, indent=2))


if __name__ == "__main__":
    unittest.main()
