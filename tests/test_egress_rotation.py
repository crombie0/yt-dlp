import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ytdlp_mcp.egress_health import EgressHealthStore, classify_failure
from ytdlp_mcp.egress_rotation import recommend_egress_profile
from ytdlp_mcp.policy import Policy


class EgressRotationTests(unittest.TestCase):
    def test_recommends_verified_non_cooling_profile(self):
        with TemporaryDirectory() as root:
            policy = Policy(
                output_root=Path(root) / "downloads",
                active_egress_profile="vpn-a",
                egress_profiles={
                    "vpn-a": {
                        "type": "proxy",
                        "proxy": "socks5h://127.0.0.1:1080",
                    },
                    "vpn-b": {
                        "type": "proxy",
                        "proxy": "socks5h://127.0.0.1:1081",
                        "enabled": False,
                    },
                },
            )
            store = EgressHealthStore(Path(root) / "egress-state.json")
            store.record_failure(
                policy,
                "https://example.com/video",
                classify_failure("HTTP Error 429"),
                message="HTTP Error 429",
            )
            store.record_verification(
                profile_name="vpn-b",
                result={"ip": "203.0.113.2", "url": "https://api.ipify.org?format=json"},
                verified=True,
            )

            payload = recommend_egress_profile(
                policy,
                egress_health=store,
                url="https://example.com/video",
                exclude_active=True,
            )

            self.assertEqual(payload["recommended_profile"], "vpn-b")
            self.assertTrue(payload["recommended"]["ready_for_activation"])


if __name__ == "__main__":
    unittest.main()
