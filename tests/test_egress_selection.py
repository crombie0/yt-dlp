import unittest
from pathlib import Path

from ytdlp_mcp.egress_selection import select_request_egress
from ytdlp_mcp.errors import PolicyError
from ytdlp_mcp.policy import Policy


class EgressSelectionTests(unittest.TestCase):
    def test_selects_profile_by_country_code_for_request(self):
        policy = Policy(
            output_root=Path("/tmp/ytdlp-mcp-test"),
            active_egress_profile="vpn-us",
            egress_profiles={
                "vpn-us": {
                    "type": "proxy",
                    "proxy": "socks5h://127.0.0.1:1080",
                    "country_code": "US",
                },
                "vpn-jp": {
                    "type": "proxy",
                    "proxy": "socks5h://127.0.0.1:1081",
                    "country_code": "JP",
                    "country": "Japan",
                },
            },
        )

        selected_policy, selection = select_request_egress(policy, country_code="jp")

        self.assertEqual(selected_policy.active_egress_profile, "vpn-jp")
        self.assertEqual(selected_policy.proxy, "socks5h://127.0.0.1:1081")
        self.assertEqual(selection["selected"]["country_code"], "JP")
        self.assertTrue(selection["policy_override"])

    def test_rejects_profile_country_mismatch(self):
        policy = Policy(
            output_root=Path("/tmp/ytdlp-mcp-test"),
            egress_profiles={
                "vpn-us": {
                    "type": "proxy",
                    "proxy": "socks5h://127.0.0.1:1080",
                    "country_code": "US",
                },
            },
        )

        with self.assertRaises(PolicyError):
            select_request_egress(policy, profile_name="vpn-us", country_code="JP")


if __name__ == "__main__":
    unittest.main()
