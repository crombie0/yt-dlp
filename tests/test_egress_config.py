import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ytdlp_mcp.egress_config import activate_profile_in_config
from ytdlp_mcp.errors import PolicyError
from ytdlp_mcp.policy import Policy


class EgressConfigTests(unittest.TestCase):
    def test_activates_profile_in_json_config(self):
        with TemporaryDirectory() as root:
            config = Path(root) / "ytdlp-mcp.json"
            config.write_text(
                json.dumps(
                    {
                        "output_root": str(Path(root) / "downloads"),
                        "require_proxy": True,
                        "active_egress_profile": None,
                        "egress_profiles": {
                            "vpn": {
                                "type": "proxy",
                                "proxy": "socks5h://127.0.0.1:1080",
                                "enabled": False,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            policy = Policy(
                output_root=Path(root) / "downloads",
                require_proxy=True,
                egress_profiles={
                    "vpn": {
                        "type": "proxy",
                        "proxy": "socks5h://127.0.0.1:1080",
                        "enabled": False,
                    }
                },
            )

            result = activate_profile_in_config(
                config_source={
                    "config_path": str(config),
                    "config_loaded": True,
                    "env_overrides": [],
                },
                policy=policy,
                profile_name="vpn",
            )

            payload = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(payload["active_egress_profile"], "vpn")
            self.assertTrue(payload["egress_profiles"]["vpn"]["enabled"])
            self.assertTrue(Path(result["backup_path"]).exists())

    def test_rejects_env_override(self):
        with TemporaryDirectory() as root:
            config = Path(root) / "ytdlp-mcp.json"
            config.write_text(json.dumps({"output_root": root}), encoding="utf-8")
            policy = Policy(output_root=Path(root))

            with self.assertRaises(PolicyError):
                activate_profile_in_config(
                    config_source={
                        "config_path": str(config),
                        "config_loaded": True,
                        "env_overrides": ["YTDLP_MCP_ACTIVE_EGRESS_PROFILE"],
                    },
                    policy=policy,
                    profile_name="vpn",
                )


if __name__ == "__main__":
    unittest.main()
