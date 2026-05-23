import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ytdlp_mcp.diagnostics import build_environment_diagnostics
from ytdlp_mcp.policy import Policy


class DiagnosticsTests(unittest.TestCase):
    def test_reports_ok_for_existing_writable_output_root(self):
        with TemporaryDirectory() as root:
            policy = Policy(output_root=Path(root), allowed_domains=("example.com",))
            report = build_environment_diagnostics(
                policy,
                {
                    "python": "3.13",
                    "mcp": "1.27.1",
                    "yt_dlp": "2026.03.17",
                    "ffmpeg": "ffmpeg version 8",
                },
            )

            checks = {check["name"]: check for check in report["checks"]}
            self.assertEqual(checks["job_db"]["status"], "ok")
            self.assertEqual(checks["job_db"]["detail"], "job persistence is disabled")
            self.assertEqual(checks["output_root"]["status"], "ok")
            self.assertTrue(checks["output_root"]["exists"])
            self.assertEqual(report["status"], "ok")

    def test_reports_warning_for_missing_output_root_with_writable_parent(self):
        with TemporaryDirectory() as root:
            policy = Policy(
                output_root=Path(root) / "missing",
                allowed_domains=("example.com",),
            )
            report = build_environment_diagnostics(
                policy,
                {
                    "python": "3.13",
                    "mcp": "1.27.1",
                    "yt_dlp": "2026.03.17",
                    "ffmpeg": "ffmpeg version 8",
                },
            )

            checks = {check["name"]: check for check in report["checks"]}
            self.assertEqual(checks["output_root"]["status"], "warning")
            self.assertFalse(checks["output_root"]["exists"])
            self.assertEqual(report["status"], "warning")

    def test_reports_error_for_missing_required_dependency(self):
        with TemporaryDirectory() as root:
            policy = Policy(output_root=Path(root), allowed_domains=("example.com",))
            report = build_environment_diagnostics(
                policy,
                {"python": "3.13", "mcp": "1.27.1", "yt_dlp": None, "ffmpeg": None},
            )

            checks = {check["name"]: check for check in report["checks"]}
            self.assertEqual(checks["yt_dlp"]["status"], "error")
            self.assertEqual(checks["ffmpeg"]["status"], "warning")
            self.assertEqual(report["status"], "error")

    def test_reports_policy_warning_for_local_urls(self):
        with TemporaryDirectory() as root:
            policy = Policy(
                output_root=Path(root),
                allow_local_urls=True,
                allowed_domains=("example.com",),
            )
            report = build_environment_diagnostics(
                policy,
                {
                    "python": "3.13",
                    "mcp": "1.27.1",
                    "yt_dlp": "2026.03.17",
                    "ffmpeg": "ffmpeg version 8",
                },
            )

            checks = {check["name"]: check for check in report["checks"]}
            self.assertEqual(checks["policy"]["status"], "warning")
            self.assertIn("local/private URLs", checks["policy"]["detail"])

    def test_reports_policy_warning_without_allowed_domains(self):
        with TemporaryDirectory() as root:
            policy = Policy(output_root=Path(root))
            report = build_environment_diagnostics(
                policy,
                {
                    "python": "3.13",
                    "mcp": "1.27.1",
                    "yt_dlp": "2026.03.17",
                    "ffmpeg": "ffmpeg version 8",
                },
            )

            checks = {check["name"]: check for check in report["checks"]}
            self.assertEqual(checks["policy"]["status"], "warning")
            self.assertIn("no allowed domain list", checks["policy"]["detail"])

    def test_reports_error_when_proxy_is_required_but_missing(self):
        with TemporaryDirectory() as root:
            policy = Policy(
                output_root=Path(root),
                allowed_domains=("example.com",),
                require_proxy=True,
            )
            report = build_environment_diagnostics(
                policy,
                {
                    "python": "3.13",
                    "mcp": "1.27.1",
                    "yt_dlp": "2026.03.17",
                    "ffmpeg": "ffmpeg version 8",
                },
            )

            checks = {check["name"]: check for check in report["checks"]}
            self.assertEqual(checks["policy"]["status"], "error")
            self.assertIn("proxy is required", checks["policy"]["detail"])
            self.assertEqual(report["status"], "error")

    def test_reports_job_db_warning_for_missing_parent(self):
        with TemporaryDirectory() as root:
            policy = Policy(
                output_root=Path(root),
                job_db_path=Path(root) / "missing" / "jobs.sqlite3",
                allowed_domains=("example.com",),
            )
            report = build_environment_diagnostics(
                policy,
                {
                    "python": "3.13",
                    "mcp": "1.27.1",
                    "yt_dlp": "2026.03.17",
                    "ffmpeg": "ffmpeg version 8",
                },
            )

            checks = {check["name"]: check for check in report["checks"]}
            self.assertEqual(checks["job_db"]["status"], "warning")
            self.assertFalse(checks["job_db"]["parent_exists"])


if __name__ == "__main__":
    unittest.main()
