import tempfile
import unittest
from pathlib import Path

from ytdlp_mcp.egress_health import EgressHealthStore, classify_failure
from ytdlp_mcp.policy import Policy
from ytdlp_mcp.preflight import build_download_preflight


class PreflightTests(unittest.TestCase):
    def test_ready_preflight_does_not_create_output_root(self):
        with tempfile.TemporaryDirectory() as root:
            output_root = Path(root) / "downloads"
            policy = Policy(output_root=output_root, max_playlist_items=5)

            payload = build_download_preflight(
                policy,
                url="https://example.com/watch?v=1",
                playlist_items="1",
            )

            self.assertTrue(payload["ok"])
            self.assertTrue(payload["ready"])
            self.assertEqual(payload["recommended_next_tool"], "start_download")
            self.assertEqual(payload["download"]["playlist_items"], "1")
            self.assertEqual(payload["url"]["domain"], "example.com")
            self.assertFalse(output_root.exists())

    def test_preflight_reports_url_and_egress_blockers(self):
        policy = Policy(
            output_root=Path("/tmp/ytdlp-mcp-test"),
            require_proxy=True,
            active_egress_profile="vpn",
            egress_profiles={
                "vpn": {
                    "type": "proxy",
                    "enabled": False,
                }
            },
        )

        payload = build_download_preflight(policy, url="http://127.0.0.1:8000/video")

        self.assertFalse(payload["ready"])
        self.assertIn("Local or private network URLs are blocked by default.", payload["blockers"])
        self.assertIn("active egress profile is disabled: vpn", payload["blockers"])
        self.assertIn(
            "active proxy egress profile has no proxy configured: vpn",
            payload["blockers"],
        )

    def test_preflight_reports_active_egress_cooldown(self):
        with tempfile.TemporaryDirectory() as root:
            policy = Policy(
                output_root=Path(root) / "downloads",
                egress_state_path=Path(root) / "egress-state.json",
                active_egress_profile="vpn",
                egress_profiles={
                    "vpn": {
                        "type": "proxy",
                        "proxy": "socks5h://127.0.0.1:1080",
                    }
                },
            )
            store = EgressHealthStore(policy.resolved_egress_state_path)
            classification = classify_failure("HTTP Error 429: Too Many Requests")
            self.assertIsNotNone(classification)
            store.record_failure(
                policy,
                "https://example.com/watch?v=1",
                classification,
                message="HTTP Error 429: Too Many Requests",
            )

            payload = build_download_preflight(
                policy,
                url="https://example.com/watch?v=1",
                egress_health=store,
            )

            self.assertFalse(payload["ready"])
            self.assertTrue(
                any("cooling down" in blocker for blocker in payload["blockers"]),
                payload["blockers"],
            )
            self.assertIsNotNone(payload["egress_health"]["url_block"])


if __name__ == "__main__":
    unittest.main()
