import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ytdlp_mcp.download_archive import archive_summary
from ytdlp_mcp.policy import Policy


class DownloadArchiveTests(unittest.TestCase):
    def test_reports_disabled_without_archive_path(self):
        payload = archive_summary(Policy(output_root=Path("/tmp/ytdlp-mcp-test")))

        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["entry_count"], 0)

    def test_reports_recent_archive_entries(self):
        with TemporaryDirectory() as root:
            archive = Path(root) / "archive.txt"
            archive.write_text("youtube abc\n\nvimeo def\n", encoding="utf-8")
            payload = archive_summary(
                Policy(
                    output_root=Path(root) / "downloads",
                    download_archive_path=archive,
                ),
                limit=1,
            )

            self.assertTrue(payload["enabled"])
            self.assertTrue(payload["exists"])
            self.assertEqual(payload["entry_count"], 2)
            self.assertEqual(payload["recent_entries"], ["vimeo def"])


if __name__ == "__main__":
    unittest.main()
