import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ytdlp_mcp.job_repository import SQLiteJobRepository
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

    def test_job_success_persists_and_restores(self):
        with TemporaryDirectory() as root:
            root_path = Path(root)
            policy = Policy(
                output_root=root_path / "downloads",
                job_db_path=root_path / "jobs.sqlite3",
            )
            store = JobStore(policy)

            def run(context):
                context.update_progress({"status": "downloading", "downloaded_bytes": 10})
                context.append_log("info", "working")
                return {
                    "ok": True,
                    "files": [str(policy.resolved_output_root / "video.mp4")],
                    "info": {"title": "video"},
                }

            record = store.submit("video", run)
            record.future.result(timeout=2)
            restored = JobStore(policy)
            final = restored.get(record.job_id)

            self.assertEqual(final.status, "succeeded")
            self.assertEqual(final.progress["downloaded_bytes"], 10)
            self.assertEqual(final.files, [str(policy.resolved_output_root / "video.mp4")])
            self.assertEqual(final.info, {"title": "video"})
            self.assertEqual(final.logs[0]["message"], "working")

    def test_running_jobs_restore_as_interrupted_failures(self):
        with TemporaryDirectory() as root:
            db_path = Path(root) / "jobs.sqlite3"
            SQLiteJobRepository(db_path).save(
                {
                    "job_id": "job-1",
                    "kind": "video",
                    "status": "running",
                    "created_at": 1.0,
                    "updated_at": 2.0,
                    "progress": {},
                    "result": None,
                    "error": None,
                    "logs": [],
                    "files": [],
                    "info": None,
                }
            )

            restored = JobStore(Policy(output_root=Path(root), job_db_path=db_path))
            record = restored.get("job-1")

            self.assertEqual(record.status, "failed")
            self.assertEqual(record.error["code"], "JOB_INTERRUPTED")
            self.assertEqual(record.logs[-1]["level"], "warning")


if __name__ == "__main__":
    unittest.main()
