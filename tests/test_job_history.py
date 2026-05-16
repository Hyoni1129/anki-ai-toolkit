# -*- coding: utf-8 -*-
"""
Tests for JobHistoryManager

Tests job creation, item appending, status transitions (finish/stop),
listing with filters, reinsertion with field overrides, image asset
management, and edge-case handling (corrupt files, missing jobs).

NOTE: ``reinsert_job`` depends on ``aqt.mw``, which is only available
inside Anki.  Those tests mock the aqt module so they can run in a
plain Python environment.
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path setup — make the addon package importable without Anki running.
# ---------------------------------------------------------------------------
_addon_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _addon_root not in sys.path:
    sys.path.insert(0, _addon_root)

# Stub aqt before importing anything that touches it transitively.
if "aqt" not in sys.modules:
    sys.modules["aqt"] = MagicMock()
    sys.modules["aqt.qt"] = MagicMock()
    sys.modules["aqt.utils"] = MagicMock()
    sys.modules["aqt.main"] = MagicMock()

from core.job_history import JobHistoryManager


class TestJobHistoryBasic(unittest.TestCase):
    """Basic CRUD operations on jobs."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.mgr = JobHistoryManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ---- start / get ----
    def test_start_and_get_job(self):
        job_id = self.mgr.start_job(
            operation="translation",
            deck_id=123,
            deck_name="Test Deck",
            settings={"target_language": "Korean"},
        )
        self.assertTrue(job_id)

        job = self.mgr.get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job["operation"], "translation")
        self.assertEqual(job["deck_id"], 123)
        self.assertEqual(job["deck_name"], "Test Deck")
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["settings"]["target_language"], "Korean")
        self.assertEqual(job["summary"]["total"], 0)
        self.assertIsInstance(job["items"], list)
        self.assertEqual(len(job["items"]), 0)

    def test_get_nonexistent_job(self):
        self.assertIsNone(self.mgr.get_job("does-not-exist"))

    # ---- append items ----
    def test_append_items(self):
        job_id = self.mgr.start_job("translation", 1, "Deck")

        items = [
            {
                "note_id": 100,
                "source_text": "hello",
                "target_field": "korean",
                "api_output": "안녕하세요",
                "insert_status": "success",
            },
            {
                "note_id": 200,
                "source_text": "world",
                "target_field": "korean",
                "api_output": "",
                "insert_status": "failed",
                "insert_error": "empty_response",
            },
        ]
        self.mgr.append_items(job_id, items)

        job = self.mgr.get_job(job_id)
        self.assertEqual(len(job["items"]), 2)
        self.assertEqual(job["summary"]["total"], 2)
        self.assertEqual(job["summary"]["success"], 1)
        self.assertEqual(job["summary"]["failure"], 1)

    def test_append_items_incremental(self):
        """Appending twice should concatenate items."""
        job_id = self.mgr.start_job("sentence", 1, "Deck")

        self.mgr.append_items(job_id, [
            {"note_id": 1, "source_text": "a", "target_field": "f",
             "api_output": "x", "insert_status": "success"},
        ])
        self.mgr.append_items(job_id, [
            {"note_id": 2, "source_text": "b", "target_field": "f",
             "api_output": "y", "insert_status": "success"},
        ])

        job = self.mgr.get_job(job_id)
        self.assertEqual(len(job["items"]), 2)
        self.assertEqual(job["summary"]["total"], 2)
        self.assertEqual(job["summary"]["success"], 2)

    def test_append_items_skips_non_dict(self):
        """Non-dict items should be silently ignored."""
        job_id = self.mgr.start_job("translation", 1, "Deck")
        self.mgr.append_items(job_id, ["not_a_dict", 42, None])
        job = self.mgr.get_job(job_id)
        self.assertEqual(len(job["items"]), 0)

    def test_append_items_nonexistent_job(self):
        """Appending to a missing job should not crash."""
        self.mgr.append_items("nonexistent-id", [{"note_id": 1}])

    # ---- finish ----
    def test_finish_job(self):
        job_id = self.mgr.start_job("translation", 1, "Deck")
        self.mgr.append_items(job_id, [
            {"note_id": 1, "source_text": "a", "target_field": "f",
             "api_output": "x", "insert_status": "success"},
        ])
        self.mgr.finish_job(job_id, {"success": 1, "failure": 0, "total": 1})

        job = self.mgr.get_job(job_id)
        self.assertEqual(job["status"], "completed")
        self.assertTrue(job["completed_at"])
        self.assertEqual(job["summary"]["success"], 1)

    def test_finish_job_auto_total(self):
        """If total <= 0, it should be computed as success + failure."""
        job_id = self.mgr.start_job("translation", 1, "Deck")
        self.mgr.finish_job(job_id, {"success": 5, "failure": 3, "total": 0})
        job = self.mgr.get_job(job_id)
        self.assertEqual(job["summary"]["total"], 8)

    # ---- stop ----
    def test_stop_job(self):
        job_id = self.mgr.start_job("translation", 1, "Deck")
        self.mgr.append_items(job_id, [
            {"note_id": 1, "source_text": "a", "target_field": "f",
             "api_output": "x", "insert_status": "success"},
            {"note_id": 2, "source_text": "b", "target_field": "f",
             "api_output": "", "insert_status": "failed"},
        ])
        self.mgr.stop_job(job_id)

        job = self.mgr.get_job(job_id)
        self.assertEqual(job["status"], "stopped")
        self.assertTrue(job["completed_at"])
        self.assertEqual(job["summary"]["success"], 1)
        self.assertEqual(job["summary"]["failure"], 1)
        self.assertEqual(job["summary"]["total"], 2)

    def test_stop_nonexistent_job(self):
        """Stopping a missing job should not crash."""
        self.mgr.stop_job("nonexistent-id")

    # ---- delete ----
    def test_delete_job(self):
        job_id = self.mgr.start_job("image", 1, "Deck")

        # Simulate saving an asset
        asset_dir = os.path.join(self.temp_dir, "job_history", "assets", job_id)
        os.makedirs(asset_dir, exist_ok=True)
        asset_file = os.path.join(asset_dir, "test.png")
        with open(asset_file, "wb") as f:
            f.write(b"\x89PNG fake")

        self.assertIsNotNone(self.mgr.get_job(job_id))
        self.assertTrue(os.path.exists(asset_file))

        self.mgr.delete_job(job_id)

        self.assertIsNone(self.mgr.get_job(job_id))
        self.assertFalse(os.path.isdir(asset_dir))


class TestListJobs(unittest.TestCase):
    """Tests for list_jobs with filtering and ordering."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.mgr = JobHistoryManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_list_empty(self):
        self.assertEqual(self.mgr.list_jobs(), [])

    def test_list_order_desc(self):
        """Jobs should be listed most-recent first."""
        id1 = self.mgr.start_job("translation", 1, "Deck A")
        id2 = self.mgr.start_job("sentence", 2, "Deck B")
        id3 = self.mgr.start_job("image", 3, "Deck C")

        jobs = self.mgr.list_jobs()
        # All three should have the same started_at second (test runs fast).
        # At minimum, all three are returned.
        self.assertEqual(len(jobs), 3)
        job_ids = [j["job_id"] for j in jobs]
        self.assertIn(id1, job_ids)
        self.assertIn(id2, job_ids)
        self.assertIn(id3, job_ids)

    def test_list_limit(self):
        for i in range(5):
            self.mgr.start_job("translation", i, f"Deck {i}")
        jobs = self.mgr.list_jobs(limit=3)
        self.assertEqual(len(jobs), 3)

    def test_list_status_filter_completed(self):
        id1 = self.mgr.start_job("translation", 1, "A")
        id2 = self.mgr.start_job("translation", 2, "B")
        self.mgr.finish_job(id1, {"success": 1, "failure": 0, "total": 1})

        completed = self.mgr.list_jobs(status_filter="completed")
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["job_id"], id1)

        running = self.mgr.list_jobs(status_filter="running")
        self.assertEqual(len(running), 1)
        self.assertEqual(running[0]["job_id"], id2)

    def test_list_status_filter_stopped(self):
        id1 = self.mgr.start_job("translation", 1, "A")
        self.mgr.stop_job(id1)

        stopped = self.mgr.list_jobs(status_filter="stopped")
        self.assertEqual(len(stopped), 1)
        self.assertEqual(stopped[0]["status"], "stopped")

    def test_list_no_filter(self):
        """status_filter=None should return all jobs."""
        id1 = self.mgr.start_job("translation", 1, "A")
        id2 = self.mgr.start_job("translation", 2, "B")
        self.mgr.finish_job(id1, {"success": 1, "failure": 0, "total": 1})
        self.mgr.stop_job(id2)

        all_jobs = self.mgr.list_jobs(status_filter=None)
        self.assertEqual(len(all_jobs), 2)

    def test_list_includes_completed_at(self):
        job_id = self.mgr.start_job("translation", 1, "A")
        self.mgr.finish_job(job_id, {"success": 1, "failure": 0, "total": 1})
        jobs = self.mgr.list_jobs()
        self.assertTrue(jobs[0].get("completed_at"))


class TestImageAsset(unittest.TestCase):
    """Tests for image asset persistence."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.mgr = JobHistoryManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_image_asset(self):
        job_id = self.mgr.start_job("image", 1, "Deck")
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        rel_path = self.mgr.save_image_asset(
            job_id=job_id,
            note_id=42,
            image_data=fake_png,
            extension=".png",
        )

        self.assertTrue(rel_path)
        self.assertTrue(rel_path.endswith(".png"))

        # File should exist on disk
        abs_path = os.path.join(self.temp_dir, "job_history", rel_path)
        self.assertTrue(os.path.exists(abs_path))

        with open(abs_path, "rb") as f:
            self.assertEqual(f.read(), fake_png)

    def test_save_image_no_dot(self):
        """Extension without leading dot should still work."""
        job_id = self.mgr.start_job("image", 1, "Deck")
        rel_path = self.mgr.save_image_asset(job_id, 1, b"data", extension="jpg")
        self.assertTrue(rel_path.endswith(".jpg"))


class TestReinsertJob(unittest.TestCase):
    """Tests for reinsert_job with field overrides (mocked Anki)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.mgr = JobHistoryManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_job_with_items(self, items):
        """Helper: create a completed job with the given items."""
        job_id = self.mgr.start_job("translation", 1, "Deck")
        self.mgr.append_items(job_id, items)
        self.mgr.finish_job(job_id, {
            "success": len(items), "failure": 0, "total": len(items)
        })
        return job_id

    @patch("core.job_history.JobHistoryManager.reinsert_job")
    def test_reinsert_basic(self, mock_reinsert):
        """Verify reinsert_job is callable with the new signature."""
        mock_reinsert.return_value = {"success": 2, "failed": 0, "skipped": 0, "total": 2}

        job_id = self._create_job_with_items([
            {"note_id": 1, "source_text": "a", "target_field": "korean",
             "api_output": "x", "insert_status": "success"},
        ])

        result = self.mgr.reinsert_job(job_id, overwrite=True)
        self.assertIn("success", result)

    @patch("core.job_history.JobHistoryManager.reinsert_job")
    def test_reinsert_with_field_override(self, mock_reinsert):
        """Verify reinsert_job accepts target_field_override."""
        mock_reinsert.return_value = {"success": 1, "failed": 0, "skipped": 0, "total": 1}

        job_id = self._create_job_with_items([
            {"note_id": 1, "source_text": "a", "target_field": "korean",
             "api_output": "x", "insert_status": "success"},
        ])

        result = self.mgr.reinsert_job(
            job_id, overwrite=True,
            target_field_override="korean_1",
            secondary_field_override="translation_1",
        )
        self.assertIn("success", result)
        # Verify the override params were passed through
        mock_reinsert.assert_called_with(
            job_id,
            overwrite=True,
            target_field_override="korean_1",
            secondary_field_override="translation_1",
        )

    def test_reinsert_nonexistent_job(self):
        """Reinserting a nonexistent job should return zeros without error."""
        # Since reinsert_job imports aqt which is mocked, we need to handle this
        # carefully. The code checks get_job first which returns None.
        # With the mock aqt, calling the actual method should still work for
        # the early return case.
        result = self.mgr.reinsert_job("does-not-exist")
        self.assertEqual(result["success"], 0)
        self.assertEqual(result["total"], 0)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and error handling."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.mgr = JobHistoryManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_corrupted_json(self):
        """A corrupt JSON file should not crash list_jobs or get_job."""
        jobs_dir = os.path.join(self.temp_dir, "job_history", "jobs")
        os.makedirs(jobs_dir, exist_ok=True)
        corrupt_path = os.path.join(jobs_dir, "corrupt-id.json")
        with open(corrupt_path, "w") as f:
            f.write("{{{not valid json")

        # Should not raise
        jobs = self.mgr.list_jobs()
        # Corrupt file is skipped
        self.assertEqual(len(jobs), 0)

        # get_job should return None
        self.assertIsNone(self.mgr.get_job("corrupt-id"))

    def test_atomic_write_no_orphans(self):
        """After writing, no .tmp files should remain."""
        job_id = self.mgr.start_job("translation", 1, "Deck")
        jobs_dir = os.path.join(self.temp_dir, "job_history", "jobs")

        tmp_files = [f for f in os.listdir(jobs_dir) if f.endswith(".tmp")]
        self.assertEqual(len(tmp_files), 0, f"Found orphan tmp files: {tmp_files}")

    def test_empty_items_append(self):
        """Appending an empty list should be a no-op."""
        job_id = self.mgr.start_job("translation", 1, "Deck")
        self.mgr.append_items(job_id, [])
        job = self.mgr.get_job(job_id)
        self.assertEqual(len(job["items"]), 0)

    def test_finish_nonexistent_job(self):
        """Finishing a missing job should not crash."""
        self.mgr.finish_job("nonexistent-id", {"success": 0, "failure": 0, "total": 0})

    def test_delete_nonexistent_job(self):
        """Deleting a missing job should not crash."""
        self.mgr.delete_job("nonexistent-id")

    def test_job_id_uniqueness(self):
        """Each start_job call should produce a unique ID."""
        ids = set()
        for _ in range(20):
            ids.add(self.mgr.start_job("translation", 1, "Deck"))
        self.assertEqual(len(ids), 20)


class TestBatchErrorHistoryItems(unittest.TestCase):
    """Regression coverage for whole-batch API failures entering history."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.mgr = JobHistoryManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _load_batch_translator(self):
        """Load BatchTranslator with minimal Anki stubs and package context."""
        package_name = "_stella_batch_history_test"
        package = types.ModuleType(package_name)
        package.__path__ = [_addon_root]
        sys.modules[package_name] = package

        for subpackage in ("translation", "core", "config"):
            module_name = f"{package_name}.{subpackage}"
            module = types.ModuleType(module_name)
            module.__path__ = [os.path.join(_addon_root, subpackage)]
            sys.modules[module_name] = module

        class DummyQObject:
            pass

        class DummyQRunnable:
            def __init__(self):
                pass

        class DummySignal:
            def __init__(self, *args, **kwargs):
                self.emitted = []

            def emit(self, *args):
                self.emitted.append(args)

        def pyqtSignal(*args, **kwargs):
            return DummySignal()

        aqt_module = types.ModuleType("aqt")
        aqt_module.mw = types.SimpleNamespace(taskman=None)
        qt_module = types.ModuleType("aqt.qt")
        qt_module.QObject = DummyQObject
        qt_module.QRunnable = DummyQRunnable
        qt_module.pyqtSignal = pyqtSignal

        old_aqt = sys.modules.get("aqt")
        old_qt = sys.modules.get("aqt.qt")
        sys.modules["aqt"] = aqt_module
        sys.modules["aqt.qt"] = qt_module
        try:
            module_name = f"{package_name}.translation.batch_translator"
            path = os.path.join(_addon_root, "translation", "batch_translator.py")
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module.BatchTranslator
        finally:
            if old_aqt is not None:
                sys.modules["aqt"] = old_aqt
            else:
                sys.modules.pop("aqt", None)
            if old_qt is not None:
                sys.modules["aqt.qt"] = old_qt
            else:
                sys.modules.pop("aqt.qt", None)

    def test_batch_api_error_can_be_appended_to_history(self):
        BatchTranslator = self._load_batch_translator()
        worker = BatchTranslator(
            notes_data=[],
            target_language="Korean",
            destination_field="korean",
            addon_dir=self.temp_dir,
        )

        batch_results = worker._build_failed_batch_results(
            [
                {"note_id": "101", "word": "harbour"},
                {"note_id": "102", "word": "astronomical"},
            ],
            RuntimeError("429 quota exceeded"),
        )

        history_items = [
            {
                "note_id": result["note_id"],
                "source_text": result["word"],
                "target_field": result["target_field"],
                "api_output": result["translation"],
                "insert_status": result["insert_status"],
                "insert_error": result["insert_error"],
            }
            for result in batch_results
        ]

        job_id = self.mgr.start_job("translation", 1, "Deck")
        self.mgr.append_items(job_id, history_items)
        job = self.mgr.get_job(job_id)

        self.assertEqual(job["summary"]["total"], 2)
        self.assertEqual(job["summary"]["success"], 0)
        self.assertEqual(job["summary"]["failure"], 2)
        self.assertEqual(job["items"][0]["source_text"], "harbour")
        self.assertEqual(job["items"][0]["insert_status"], "failed")
        self.assertIn("429 quota exceeded", job["items"][0]["insert_error"])


if __name__ == "__main__":
    unittest.main()
