import unittest
from pathlib import Path

from ytdlp_mcp.errors import PolicyError
from ytdlp_mcp.policy import (
    Policy,
    normalize_proxy_url,
    redact_proxy_url,
    safe_child_path,
    validate_output_template,
    validate_playlist_items,
    validate_url,
)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy(output_root=Path("/tmp/ytdlp-mcp-test"), max_playlist_items=10)

    def test_accepts_https_url(self):
        self.assertEqual(
            validate_url("https://example.com/watch?v=1", self.policy),
            "https://example.com/watch?v=1",
        )

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
        self.assertEqual(
            validate_url("http://localhost:8000/video", policy),
            "http://localhost:8000/video",
        )

    def test_allowed_domains_allow_subdomains(self):
        policy = Policy(output_root=Path("/tmp/ytdlp-mcp-test"), allowed_domains=("example.com",))

        self.assertEqual(
            validate_url("https://media.example.com/video", policy),
            "https://media.example.com/video",
        )

    def test_allowed_domains_block_other_hosts(self):
        policy = Policy(output_root=Path("/tmp/ytdlp-mcp-test"), allowed_domains=("example.com",))

        with self.assertRaises(PolicyError):
            validate_url("https://example.org/video", policy)

    def test_blocked_domains_override_allowed_domains(self):
        policy = Policy(
            output_root=Path("/tmp/ytdlp-mcp-test"),
            allowed_domains=("example.com",),
            blocked_domains=("media.example.com",),
        )

        with self.assertRaises(PolicyError):
            validate_url("https://media.example.com/video", policy)

    def test_domain_matching_does_not_allow_suffix_tricks(self):
        policy = Policy(output_root=Path("/tmp/ytdlp-mcp-test"), allowed_domains=("example.com",))

        with self.assertRaises(PolicyError):
            validate_url("https://badexample.com/video", policy)

    def test_rejects_invalid_domain_policy_entries(self):
        with self.assertRaises(PolicyError):
            Policy(output_root=Path("/tmp/ytdlp-mcp-test"), allowed_domains=("https://example.com",))

    def test_accepts_supported_proxy_schemes(self):
        self.assertEqual(
            normalize_proxy_url("socks5h://127.0.0.1:1080"),
            "socks5h://127.0.0.1:1080",
        )

    def test_rejects_invalid_proxy_scheme(self):
        with self.assertRaises(PolicyError):
            Policy(output_root=Path("/tmp/ytdlp-mcp-test"), proxy="file:///tmp/socket")

    def test_redacts_proxy_credentials(self):
        self.assertEqual(
            redact_proxy_url("socks5h://user:pass@proxy.example.com:1080"),
            "socks5h://<redacted>@proxy.example.com:1080",
        )

    def test_active_egress_profile_sets_effective_proxy(self):
        policy = Policy(
            output_root=Path("/tmp/ytdlp-mcp-test"),
            active_egress_profile="vpn",
            egress_profiles={
                "vpn": {
                    "type": "proxy",
                    "proxy": "socks5h://127.0.0.1:1080",
                }
            },
        )

        self.assertEqual(policy.proxy, "socks5h://127.0.0.1:1080")
        self.assertEqual(policy.active_egress().name, "vpn")

    def test_egress_profile_accepts_country_metadata(self):
        policy = Policy(
            output_root=Path("/tmp/ytdlp-mcp-test"),
            egress_profiles={
                "vpn-us": {
                    "type": "proxy",
                    "proxy": "socks5h://127.0.0.1:1080",
                    "provider": "expressvpn",
                    "region": "usa-san-francisco",
                    "country": "United States",
                    "country_code": "us",
                }
            },
        )

        profile = policy.egress_profile("vpn-us")
        self.assertEqual(profile.country_code, "US")
        self.assertEqual(profile.region, "usa-san-francisco")

    def test_rejects_duplicate_egress_profile_names(self):
        with self.assertRaises(PolicyError):
            Policy(
                output_root=Path("/tmp/ytdlp-mcp-test"),
                egress_profiles=[
                    {"name": "vpn", "type": "proxy"},
                    {"name": "vpn", "type": "proxy"},
                ],
            )

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
