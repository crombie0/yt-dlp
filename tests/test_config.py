import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ytdlp_mcp.config import load_configured_policy
from ytdlp_mcp.errors import PolicyError


class ConfigTests(unittest.TestCase):
    def test_loads_policy_from_json_config(self):
        with TemporaryDirectory() as root:
            config = Path(root) / "ytdlp-mcp.json"
            output_root = Path(root) / "downloads"
            config.write_text(
                json.dumps(
                    {
                        "output_root": str(output_root),
                        "job_db_path": str(Path(root) / "jobs.sqlite3"),
                        "proxy": "socks5h://proxy.example.com:1080",
                        "require_proxy": True,
                        "active_egress_profile": "vpn",
                        "egress_profiles": {
                            "vpn": {
                                "type": "proxy",
                                "proxy": "socks5h://profile.example.com:1080",
                            }
                        },
                        "allow_local_urls": True,
                        "allowed_domains": ["example.com", "media.example.com"],
                        "blocked_domains": ["ads.example.com"],
                        "max_playlist_items": 3,
                        "max_concurrent_jobs": 1,
                        "max_log_lines": 10,
                    }
                ),
                encoding="utf-8",
            )

            result = load_configured_policy(config, env={})

            self.assertEqual(result.policy.resolved_output_root, output_root.resolve())
            self.assertEqual(
                result.policy.resolved_job_db_path,
                (Path(root) / "jobs.sqlite3").resolve(),
            )
            self.assertTrue(result.policy.allow_local_urls)
            self.assertEqual(result.policy.proxy, "socks5h://proxy.example.com:1080")
            self.assertTrue(result.policy.require_proxy)
            self.assertEqual(result.policy.active_egress_profile, "vpn")
            self.assertEqual(result.policy.active_egress().proxy, "socks5h://profile.example.com:1080")
            self.assertEqual(result.policy.allowed_domains, ("example.com", "media.example.com"))
            self.assertEqual(result.policy.blocked_domains, ("ads.example.com",))
            self.assertEqual(result.policy.max_playlist_items, 3)
            self.assertTrue(result.source["config_loaded"])
            self.assertEqual(result.source["config_path"], str(config.resolve()))

    def test_env_overrides_json_config(self):
        with TemporaryDirectory() as root:
            config = Path(root) / "ytdlp-mcp.json"
            file_output_root = Path(root) / "file-downloads"
            env_output_root = Path(root) / "env-downloads"
            env_job_db_path = Path(root) / "env-jobs.sqlite3"
            config.write_text(
                json.dumps(
                    {
                        "output_root": str(file_output_root),
                        "allow_local_urls": False,
                        "max_playlist_items": 3,
                    }
                ),
                encoding="utf-8",
            )

            result = load_configured_policy(
                config,
                env={
                    "YTDLP_MCP_OUTPUT_ROOT": str(env_output_root),
                    "YTDLP_MCP_JOB_DB_PATH": str(env_job_db_path),
                    "YTDLP_MCP_PROXY": "http://env-proxy.example.com:8080",
                    "YTDLP_MCP_REQUIRE_PROXY": "true",
                    "YTDLP_MCP_ALLOW_LOCAL_URLS": "true",
                    "YTDLP_MCP_ALLOWED_DOMAINS": "example.com, youtu.be",
                    "YTDLP_MCP_BLOCKED_DOMAINS": "ads.example.com",
                    "YTDLP_MCP_MAX_PLAYLIST_ITEMS": "5",
                },
            )

            self.assertEqual(result.policy.resolved_output_root, env_output_root.resolve())
            self.assertEqual(result.policy.resolved_job_db_path, env_job_db_path.resolve())
            self.assertEqual(result.policy.proxy, "http://env-proxy.example.com:8080")
            self.assertTrue(result.policy.require_proxy)
            self.assertTrue(result.policy.allow_local_urls)
            self.assertEqual(result.policy.max_playlist_items, 5)
            self.assertEqual(result.policy.allowed_domains, ("example.com", "youtu.be"))
            self.assertEqual(result.policy.blocked_domains, ("ads.example.com",))
            self.assertEqual(
                result.source["env_overrides"],
                [
                    "YTDLP_MCP_OUTPUT_ROOT",
                    "YTDLP_MCP_JOB_DB_PATH",
                    "YTDLP_MCP_PROXY",
                    "YTDLP_MCP_REQUIRE_PROXY",
                    "YTDLP_MCP_ALLOW_LOCAL_URLS",
                    "YTDLP_MCP_ALLOWED_DOMAINS",
                    "YTDLP_MCP_BLOCKED_DOMAINS",
                    "YTDLP_MCP_MAX_PLAYLIST_ITEMS",
                ],
            )

    def test_rejects_unknown_config_keys(self):
        with TemporaryDirectory() as root:
            config = Path(root) / "ytdlp-mcp.json"
            config.write_text(
                json.dumps({"output_root": root, "raw_options": {}}),
                encoding="utf-8",
            )

            with self.assertRaises(PolicyError):
                load_configured_policy(config, env={})

    def test_rejects_invalid_integer_values(self):
        with TemporaryDirectory() as root:
            config = Path(root) / "ytdlp-mcp.json"
            config.write_text(
                json.dumps({"output_root": root, "max_concurrent_jobs": 0}),
                encoding="utf-8",
            )

            with self.assertRaises(PolicyError):
                load_configured_policy(config, env={})

    def test_config_path_can_come_from_env(self):
        with TemporaryDirectory() as root:
            config = Path(root) / "ytdlp-mcp.json"
            config.write_text(json.dumps({"output_root": root}), encoding="utf-8")

            result = load_configured_policy(env={"YTDLP_MCP_CONFIG": str(config)})

            self.assertEqual(result.policy.resolved_output_root, Path(root).resolve())


if __name__ == "__main__":
    unittest.main()
