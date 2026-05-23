import asyncio
import json
import os
import sys
import unittest
from importlib.util import find_spec
from pathlib import Path

from ytdlp_mcp.policy import Policy
from ytdlp_mcp.server import create_server

MCP_AVAILABLE = find_spec("mcp") is not None


def _tool_payload(result):
    content, structured = result
    if structured is not None:
        return structured
    return json.loads(content[0].text)


@unittest.skipUnless(MCP_AVAILABLE, "mcp package is not installed")
class FastMcpServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = create_server(Policy(output_root=Path("/tmp/ytdlp-mcp-test")))

    async def test_lists_expected_tools_with_annotations(self):
        tools = await self.server.list_tools()
        by_name = {tool.name: tool for tool in tools}

        self.assertIn("diagnose_environment", by_name)
        self.assertIn("list_egress_profiles", by_name)
        self.assertIn("get_egress_status", by_name)
        self.assertIn("test_egress_ip", by_name)
        self.assertIn("probe_url", by_name)
        self.assertIn("start_download", by_name)
        self.assertIn("list_jobs", by_name)
        self.assertIn("get_job_artifacts", by_name)
        self.assertIn("preview_artifact", by_name)
        self.assertTrue(by_name["probe_url"].annotations.readOnlyHint)
        self.assertFalse(by_name["start_download"].annotations.readOnlyHint)
        self.assertTrue(by_name["start_download"].annotations.openWorldHint)
        self.assertTrue(by_name["list_jobs"].annotations.readOnlyHint)
        self.assertTrue(by_name["get_job_artifacts"].annotations.readOnlyHint)
        self.assertTrue(by_name["diagnose_environment"].annotations.readOnlyHint)
        self.assertTrue(by_name["list_egress_profiles"].annotations.readOnlyHint)

    async def test_suggest_format_call_returns_structured_payload(self):
        result = await self.server.call_tool("suggest_format", {"goal": "audio mp3"})
        payload = _tool_payload(result)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "audio")
        self.assertEqual(payload["audio_format"], "mp3")

    async def test_start_download_rejects_blocked_url_before_queueing(self):
        result = await self.server.call_tool(
            "start_download",
            {"url": "http://127.0.0.1:8000/video.mp4"},
        )
        payload = _tool_payload(result)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "POLICY_DENIED")
        self.assertNotIn("job_id", payload)

    async def test_policy_resource_is_readable(self):
        resource = await self.server.read_resource("ytdlp://config/effective-policy")
        payload = json.loads(resource[0].content)

        self.assertEqual(payload["max_playlist_items"], 20)
        self.assertEqual(payload["output_root"], str(Path("/tmp/ytdlp-mcp-test").resolve()))

    async def test_config_source_resource_is_readable(self):
        server = create_server(
            Policy(output_root=Path("/tmp/ytdlp-mcp-config-test")),
            config_source={
                "config_path": "/tmp/ytdlp-mcp.json",
                "config_loaded": True,
                "env_overrides": ["YTDLP_MCP_OUTPUT_ROOT"],
            },
        )

        resource = await server.read_resource("ytdlp://config/source")
        payload = json.loads(resource[0].content)

        self.assertTrue(payload["config_loaded"])
        self.assertEqual(payload["config_path"], "/tmp/ytdlp-mcp.json")
        self.assertEqual(payload["env_overrides"], ["YTDLP_MCP_OUTPUT_ROOT"])

    async def test_diagnostics_tool_and_resource_are_readable(self):
        tool_result = await self.server.call_tool("diagnose_environment", {})
        tool_payload = _tool_payload(tool_result)
        resource = await self.server.read_resource("ytdlp://diagnostics/environment")
        resource_payload = json.loads(resource[0].content)

        self.assertTrue(tool_payload["ok"])
        self.assertIn(tool_payload["diagnostics"]["status"], {"ok", "warning", "error"})
        self.assertEqual(
            tool_payload["diagnostics"]["policy"]["output_root"],
            str(Path("/tmp/ytdlp-mcp-test").resolve()),
        )
        self.assertEqual(
            resource_payload["policy"]["output_root"],
            str(Path("/tmp/ytdlp-mcp-test").resolve()),
        )

    async def test_egress_status_tool_and_resource_are_readable(self):
        tool_result = await self.server.call_tool("get_egress_status", {})
        tool_payload = _tool_payload(tool_result)
        resource = await self.server.read_resource("ytdlp://egress/status")
        resource_payload = json.loads(resource[0].content)

        self.assertTrue(tool_payload["ok"])
        self.assertEqual(tool_payload["egress"]["active_egress_profile"], None)
        self.assertEqual(resource_payload["active_egress_profile"], None)

    async def test_jobs_resource_lists_known_jobs(self):
        resource = await self.server.read_resource("ytdlp://jobs")
        payload = json.loads(resource[0].content)

        self.assertEqual(payload, {"jobs": []})

    async def test_artifact_tool_reports_missing_job(self):
        result = await self.server.call_tool("get_job_artifacts", {"job_id": "missing"})
        payload = _tool_payload(result)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "JOB_NOT_FOUND")


@unittest.skipUnless(MCP_AVAILABLE, "mcp package is not installed")
class StdioProtocolTests(unittest.TestCase):
    def test_stdio_client_can_list_call_and_read(self):
        asyncio.run(_stdio_smoke())


async def _stdio_smoke():
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    env["YTDLP_MCP_OUTPUT_ROOT"] = "/tmp/ytdlp-mcp-stdio-test"

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ytdlp_mcp", "--transport", "stdio"],
        env=env,
        cwd=Path.cwd(),
    )

    async with (
        stdio_client(params) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        assert "suggest_format" in tool_names
        assert "diagnose_environment" in tool_names

        result = await session.call_tool("suggest_format", {"goal": "1080p mp4"})
        payload = json.loads(result.content[0].text)
        assert payload["ok"] is True
        assert payload["kind"] == "video"

        resource = await session.read_resource("ytdlp://config/effective-policy")
        policy = json.loads(resource.contents[0].text)
        assert policy["output_root"] == str(Path("/tmp/ytdlp-mcp-stdio-test").resolve())

        diagnostics = await session.read_resource("ytdlp://diagnostics/environment")
        report = json.loads(diagnostics.contents[0].text)
        assert report["policy"]["output_root"] == str(
            Path("/tmp/ytdlp-mcp-stdio-test").resolve()
        )
