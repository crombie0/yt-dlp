import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ytdlp_mcp.egress_health import EgressHealthStore, classify_failure
from ytdlp_mcp.errors import PolicyError
from ytdlp_mcp.policy import Policy


class EgressHealthTests(unittest.TestCase):
    def test_classifies_rate_limit_as_cooldown_failure(self):
        classification = classify_failure("HTTP Error 429: Too Many Requests")

        self.assertEqual(classification.category, "RATE_LIMITED")
        self.assertTrue(classification.cooldown)

    def test_classifies_auth_required_without_cooldown(self):
        classification = classify_failure("Sign in to confirm your age")

        self.assertEqual(classification.category, "AUTH_REQUIRED")
        self.assertFalse(classification.cooldown)

    def test_records_and_enforces_cooldown(self):
        with TemporaryDirectory() as root:
            policy = Policy(
                output_root=Path(root) / "downloads",
                active_egress_profile="vpn",
                egress_profiles={
                    "vpn": {
                        "type": "proxy",
                        "proxy": "socks5h://127.0.0.1:1080",
                    }
                },
                egress_cooldown_seconds=60,
            )
            store = EgressHealthStore(Path(root) / "egress-state.json")
            classification = classify_failure("HTTP Error 403: Forbidden")
            now = time.time()

            event = store.record_failure(
                policy,
                "https://example.com/video",
                classification,
                message="HTTP Error 403: Forbidden",
                now=now,
            )

            self.assertEqual(event["category"], "FORBIDDEN")
            with self.assertRaises(PolicyError):
                store.enforce_available(policy, "https://example.com/other")

            result = store.clear_cooldowns(profile_name="vpn", domain="example.com")
            self.assertEqual(result["removed"], 1)
            store.enforce_available(policy, "https://example.com/other")

    def test_expired_cooldown_is_not_active(self):
        with TemporaryDirectory() as root:
            policy = Policy(
                output_root=Path(root) / "downloads",
                active_egress_profile="vpn",
                egress_profiles={
                    "vpn": {
                        "type": "proxy",
                        "proxy": "socks5h://127.0.0.1:1080",
                    }
                },
                egress_cooldown_seconds=1,
            )
            store = EgressHealthStore(Path(root) / "egress-state.json")
            store.record_failure(
                policy,
                "https://example.com/video",
                classify_failure("HTTP Error 429"),
                message="HTTP Error 429",
                now=time.time() - 10,
            )

            self.assertIsNone(store.active_block(policy, url="https://example.com/video"))


if __name__ == "__main__":
    unittest.main()
