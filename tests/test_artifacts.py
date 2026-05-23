import base64
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ytdlp_mcp.artifacts import ArtifactNotFoundError, build_artifact_manifest, preview_artifact
from ytdlp_mcp.errors import PolicyError
from ytdlp_mcp.policy import Policy


class ArtifactTests(unittest.TestCase):
    def test_manifest_includes_safe_resource_links(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "subtitle.vtt"
            path.write_text("WEBVTT\n\nhello\n", encoding="utf-8")
            policy = Policy(output_root=Path(root))

            manifest = build_artifact_manifest(policy, "job-1", [str(path)])

            self.assertEqual(manifest[0]["index"], 0)
            self.assertEqual(manifest[0]["name"], "subtitle.vtt")
            self.assertTrue(manifest[0]["is_text"])
            self.assertTrue(manifest[0]["exists"])
            self.assertEqual(manifest[0]["resource"], "ytdlp://jobs/job-1/artifacts/0/preview")

    def test_text_preview_is_bounded_and_decoded(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "info.json"
            path.write_text(json.dumps({"title": "hello"}), encoding="utf-8")
            policy = Policy(output_root=Path(root))

            preview = preview_artifact(policy, "job-1", [str(path)], 0, max_bytes=8)

            self.assertEqual(preview["encoding"], "utf-8")
            self.assertEqual(preview["text"], '{"title"')
            self.assertTrue(preview["truncated"])

    def test_binary_preview_is_base64(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "clip.mp4"
            path.write_bytes(b"\x00\x01\x02\x03")
            policy = Policy(output_root=Path(root))

            preview = preview_artifact(policy, "job-1", [str(path)], 0)

            self.assertEqual(preview["encoding"], "base64")
            self.assertEqual(base64.b64decode(preview["base64"]), b"\x00\x01\x02\x03")
            self.assertFalse(preview["is_text"])

    def test_preview_rejects_path_escape(self):
        with TemporaryDirectory() as root:
            outside = Path(root).parent / "outside.txt"
            outside.write_text("nope", encoding="utf-8")
            policy = Policy(output_root=Path(root))

            with self.assertRaises(PolicyError):
                preview_artifact(policy, "job-1", [str(outside)], 0)

    def test_preview_rejects_missing_index(self):
        with TemporaryDirectory() as root:
            policy = Policy(output_root=Path(root))

            with self.assertRaises(ArtifactNotFoundError):
                preview_artifact(policy, "job-1", [], 0)


if __name__ == "__main__":
    unittest.main()
