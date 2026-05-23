import unittest
from pathlib import Path

from ytdlp_mcp.errors import PolicyError
from ytdlp_mcp.options import (
    build_download_options,
    build_probe_options,
    normalize_formats,
    suggest_format,
)
from ytdlp_mcp.policy import Policy


class OptionsTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy(output_root=Path("/tmp/ytdlp-mcp-test"), max_playlist_items=5)

    def test_probe_options_bound_playlist_items(self):
        options = build_probe_options(self.policy)
        self.assertEqual(options["playlist_items"], "1-5")

    def test_probe_options_include_configured_proxy(self):
        policy = Policy(
            output_root=Path("/tmp/ytdlp-mcp-test"),
            proxy="socks5h://127.0.0.1:1080",
        )
        options = build_probe_options(policy)
        self.assertEqual(options["proxy"], "socks5h://127.0.0.1:1080")

    def test_require_proxy_rejects_direct_probe_options(self):
        policy = Policy(output_root=Path("/tmp/ytdlp-mcp-test"), require_proxy=True)
        with self.assertRaises(PolicyError):
            build_probe_options(policy)

    def test_video_download_options_use_safe_defaults(self):
        options = build_download_options(self.policy, kind="video", playlist_items="1")
        self.assertEqual(options["format"], "bv*+ba/b")
        self.assertEqual(options["merge_output_format"], "mp4")
        self.assertTrue(options["restrictfilenames"])
        self.assertEqual(options["paths"]["home"], str(Path("/tmp/ytdlp-mcp-test").resolve()))

    def test_download_options_include_configured_proxy(self):
        policy = Policy(
            output_root=Path("/tmp/ytdlp-mcp-test"),
            proxy="http://proxy.example.com:8080",
        )
        options = build_download_options(policy, kind="video", playlist_items="1")
        self.assertEqual(options["proxy"], "http://proxy.example.com:8080")

    def test_audio_download_options_add_postprocessor(self):
        options = build_download_options(self.policy, kind="audio", audio_format="mp3")
        self.assertEqual(options["format"], "bestaudio/best")
        self.assertEqual(options["postprocessors"][0]["key"], "FFmpegExtractAudio")
        self.assertEqual(options["postprocessors"][0]["preferredcodec"], "mp3")

    def test_suggest_format_audio(self):
        suggestion = suggest_format("best mp3 audio")
        self.assertEqual(suggestion["kind"], "audio")
        self.assertEqual(suggestion["audio_format"], "mp3")

    def test_normalize_formats(self):
        formats = normalize_formats(
            {
                "formats": [
                    {
                        "format_id": "18",
                        "ext": "mp4",
                        "height": 360,
                        "vcodec": "avc1",
                        "acodec": "mp4a",
                    }
                ]
            }
        )
        self.assertEqual(formats[0]["format_id"], "18")
        self.assertEqual(formats[0]["height"], 360)


if __name__ == "__main__":
    unittest.main()
