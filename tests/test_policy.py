import unittest
from pathlib import Path

from ytdlp_mcp.errors import PolicyError
from ytdlp_mcp.policy import (
    Policy,
    safe_child_path,
    validate_output_template,
    validate_playlist_items,
    validate_url,
)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy(output_root=Path("/tmp/ytdlp-mcp-test"), max_playlist_items=10)

    def test_accepts_https_url(self):
        self.assertEqual(validate_url("https://example.com/watch?v=1", self.policy), "https://example.com/watch?v=1")

    def test_blocks_non_http_url(self):
        with self.assertRaises(PolicyError):
            validate_url("file:///etc/passwd", self.policy)

    def test_blocks_localhost_url_by_default(self):
        with self.assertRaises(PolicyError):
            validate_url("http://localhost:8000/video", self.policy)

    def test_blocks_private_ip_by_default(self):
        with self.assertRaises(PolicyError):
            validate_url("http://127.0.0.1:8000/video", self.policy)

    def test_allows_localhost_when_policy_enabled(self):
        policy = Policy(output_root=Path("/tmp/ytdlp-mcp-test"), allow_local_urls=True)
        self.assertEqual(validate_url("http://localhost:8000/video", policy), "http://localhost:8000/video")

    def test_playlist_range_is_bounded(self):
        self.assertEqual(validate_playlist_items("1-3", self.policy), "1-3")
        with self.assertRaises(PolicyError):
            validate_playlist_items("1-99", self.policy)

    def test_output_template_rejects_traversal(self):
        with self.assertRaises(PolicyError):
            validate_output_template("../%(title)s.%(ext)s")

    def test_safe_child_path_rejects_escape(self):
        with self.assertRaises(PolicyError):
            safe_child_path(self.policy, "..", "outside")


if __name__ == "__main__":
    unittest.main()
