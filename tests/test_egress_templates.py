import unittest

from ytdlp_mcp.egress_templates import (
    get_egress_template,
    list_egress_templates,
    render_profile_from_template,
)


class EgressTemplateTests(unittest.TestCase):
    def test_lists_and_renders_proxy_template(self):
        payload = list_egress_templates()
        names = {item["name"] for item in payload["templates"]}

        self.assertIn("generic-socks-proxy", names)
        rendered = render_profile_from_template(
            "generic-socks-proxy",
            profile_name="vpn",
            proxy="socks5h://127.0.0.1:1088",
        )
        self.assertEqual(rendered["profile"]["proxy"], "socks5h://127.0.0.1:1088")
        self.assertIn("vpn", rendered["config_patch"]["egress_profiles"])

    def test_gets_expressvpn_template(self):
        payload = get_egress_template("expressvpn-process-vpn")

        self.assertEqual(payload["provider"], "expressvpn")
        self.assertEqual(payload["profile"]["type"], "external_vpn")


if __name__ == "__main__":
    unittest.main()
