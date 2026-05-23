import time
import unittest
from pathlib import Path

from ytdlp_mcp.jobs import JobStore
from ytdlp_mcp.policy import Policy


class JobStoreTests(unittest.TestCase):
    def test_job_success_records_result(self):
        store = JobStore(Policy(output_root=Path("/tmp/ytdlp-mcp-test")))

        def run(context):
            context.update_progress({"status": "downloading", "downloaded_bytes": 10})
            context.append_log("info", "working")
            return {"ok": True, "files": ["/tmp/ytdlp-mcp-test/video.mp4"]}

        record = store.submit("video", run)
        result = record.future.result(timeout=2)

        self.assertTrue(result["ok"])
        final = store.get(record.job_id)
        self.assertEqual(final.status, "succeeded")
        self.assertEqual(final.progress["downloaded_bytes"], 10)
        self.assertEqual(final.files, ["/tmp/ytdlp-mcp-test/video.mp4"])
        self.assertEqual(final.logs[0]["message"], "working")

    def test_cancel_queued_job_sets_event(self):
        store = JobStore(Policy(output_root=Path("/tmp/ytdlp-mcp-test"), max_concurrent_jobs=1))

        def run(context):
            time.sleep(0.05)
            context.check_cancelled()
            return {"ok": True}

        record = store.submit("video", run)
        cancelled = store.cancel(record.job_id)
        self.assertTrue(cancelled.cancel_event.is_set())


if __name__ == "__main__":
    unittest.main()
