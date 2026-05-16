from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .logger import get_logger

logger = get_logger(__name__)


class JobHistoryManager:
    """Persist API outputs for later inspection and reinsertion."""

    def __init__(self, addon_dir: str) -> None:
        self._addon_dir = addon_dir
        self._history_dir = os.path.join(addon_dir, "job_history")
        self._jobs_dir = os.path.join(self._history_dir, "jobs")
        self._assets_dir = os.path.join(self._history_dir, "assets")
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        os.makedirs(self._jobs_dir, exist_ok=True)
        os.makedirs(self._assets_dir, exist_ok=True)

    def _job_path(self, job_id: str) -> str:
        return os.path.join(self._jobs_dir, f"{job_id}.json")

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _write_json_atomic(self, path: str, data: Dict[str, Any]) -> None:
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(prefix="job_", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _read_json(self, path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.error(f"Failed to read history file {path}: {exc}")
            return None

    def start_job(
        self,
        operation: str,
        deck_id: Optional[int],
        deck_name: str,
        settings: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create and persist a new job record."""
        job_id = str(uuid.uuid4())
        now = self._now()

        job_data: Dict[str, Any] = {
            "job_id": job_id,
            "operation": operation,
            "deck_id": deck_id,
            "deck_name": deck_name,
            "started_at": now,
            "completed_at": "",
            "status": "running",
            "settings": settings or {},
            "summary": {
                "total": 0,
                "success": 0,
                "failure": 0,
            },
            "items": [],
        }

        self._write_json_atomic(self._job_path(job_id), job_data)
        return job_id

    def append_items(self, job_id: str, items: List[Dict[str, Any]]) -> None:
        """Append result items to a job file."""
        if not items:
            return

        path = self._job_path(job_id)
        job_data = self._read_json(path)
        if not job_data:
            logger.warning(f"Cannot append items; job {job_id} not found")
            return

        existing = job_data.get("items", [])
        if not isinstance(existing, list):
            existing = []

        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = {
                "note_id": int(item.get("note_id", 0)) if item.get("note_id") is not None else 0,
                "source_text": str(item.get("source_text", "")),
                "target_field": str(item.get("target_field", "")),
                "api_output": str(item.get("api_output", "")),
                "secondary_field": str(item.get("secondary_field") or ""),
                "secondary_output": str(item.get("secondary_output") or ""),
                "asset_path": str(item.get("asset_path") or ""),
                "insert_status": str(item.get("insert_status", "failed")),
                "insert_error": str(item.get("insert_error") or ""),
                "created_at": self._now(),
            }
            existing.append(normalized)

        job_data["items"] = existing

        success = sum(1 for i in existing if i.get("insert_status") == "success")
        failure = sum(1 for i in existing if i.get("insert_status") != "success")
        job_data["summary"] = {
            "total": len(existing),
            "success": success,
            "failure": failure,
        }

        self._write_json_atomic(path, job_data)

    def finish_job(self, job_id: str, summary: Optional[Dict[str, int]] = None) -> None:
        """Mark job as completed and update summary."""
        path = self._job_path(job_id)
        job_data = self._read_json(path)
        if not job_data:
            return

        job_data["completed_at"] = self._now()
        job_data["status"] = "completed"

        if summary:
            total = int(summary.get("total", 0))
            success = int(summary.get("success", 0))
            failure = int(summary.get("failure", 0))
            if total <= 0:
                total = success + failure
            job_data["summary"] = {
                "total": total,
                "success": success,
                "failure": failure,
            }

        self._write_json_atomic(path, job_data)

    def stop_job(self, job_id: str) -> None:
        """Mark a job as stopped (user-cancelled) and preserve current summary."""
        path = self._job_path(job_id)
        job_data = self._read_json(path)
        if not job_data:
            return

        job_data["completed_at"] = self._now()
        job_data["status"] = "stopped"

        # Recalculate summary from items if not already set
        items = job_data.get("items", [])
        if isinstance(items, list) and items:
            success = sum(1 for i in items if i.get("insert_status") == "success")
            failure = sum(1 for i in items if i.get("insert_status") != "success")
            job_data["summary"] = {
                "total": len(items),
                "success": success,
                "failure": failure,
            }

        self._write_json_atomic(path, job_data)

    def list_jobs(self, limit: int = 200, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return recent jobs sorted by started_at descending.

        Args:
            limit: Maximum number of jobs to return.
            status_filter: If set, only return jobs with this status
                           (e.g. ``"completed"``, ``"stopped"``, ``"running"``).
        """
        jobs: List[Dict[str, Any]] = []

        if not os.path.exists(self._jobs_dir):
            return jobs

        for filename in os.listdir(self._jobs_dir):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self._jobs_dir, filename)
            data = self._read_json(path)
            if not data:
                continue

            job_status = data.get("status", "unknown")
            if status_filter and job_status != status_filter:
                continue

            summary = data.get("summary", {})
            jobs.append(
                {
                    "job_id": data.get("job_id", filename[:-5]),
                    "operation": data.get("operation", "unknown"),
                    "deck_name": data.get("deck_name", ""),
                    "started_at": data.get("started_at", ""),
                    "completed_at": data.get("completed_at", ""),
                    "status": job_status,
                    "total": int(summary.get("total", 0) or 0),
                    "success": int(summary.get("success", 0) or 0),
                    "failure": int(summary.get("failure", 0) or 0),
                }
            )

        jobs.sort(key=lambda item: item.get("started_at", ""), reverse=True)
        return jobs[:limit]

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Load a full job record."""
        return self._read_json(self._job_path(job_id))

    def save_image_asset(
        self,
        job_id: str,
        note_id: int,
        image_data: bytes,
        extension: str = ".png",
    ) -> str:
        """Persist generated image bytes for future reinsertion."""
        safe_ext = extension if extension.startswith(".") else f".{extension}"
        folder = os.path.join(self._assets_dir, job_id)
        os.makedirs(folder, exist_ok=True)

        filename = f"note_{note_id}_{uuid.uuid4().hex[:8]}{safe_ext}"
        abs_path = os.path.join(folder, filename)

        with open(abs_path, "wb") as fh:
            fh.write(image_data)

        return os.path.relpath(abs_path, self._history_dir).replace("\\", "/")

    def reinsert_job(
        self,
        job_id: str,
        overwrite: bool = True,
        target_field_override: str = "",
        secondary_field_override: str = "",
    ) -> Dict[str, int]:
        """Reinsert saved outputs into note fields.

        Args:
            job_id: The job whose items should be reinserted.
            overwrite: If ``True``, overwrite existing field content.
            target_field_override: If non-empty, insert into this field
                instead of the originally recorded ``target_field``.
            secondary_field_override: If non-empty, insert secondary
                output (e.g. sentence translation) into this field.
        """
        from aqt import mw

        job_data = self.get_job(job_id)
        if not job_data:
            return {"success": 0, "failed": 0, "skipped": 0, "total": 0}

        items = job_data.get("items", [])
        if not isinstance(items, list):
            return {"success": 0, "failed": 0, "skipped": 0, "total": 0}

        success = 0
        failed = 0
        skipped = 0

        for item in items:
            try:
                note_id = int(item.get("note_id", 0))
                target_field = target_field_override or str(item.get("target_field", ""))
                api_output = str(item.get("api_output", ""))

                if note_id <= 0 or not target_field:
                    failed += 1
                    continue

                # Skip items that had no API output (nothing to reinsert)
                asset_path = str(item.get("asset_path", "")).strip()
                if not api_output and not asset_path:
                    failed += 1
                    continue

                note = mw.col.get_note(note_id)
                if not note or target_field not in note:
                    failed += 1
                    continue

                existing = str(note[target_field]).strip()
                if existing and not overwrite:
                    skipped += 1
                    continue

                if asset_path:
                    abs_asset_path = os.path.join(self._history_dir, asset_path)
                    if not os.path.exists(abs_asset_path):
                        failed += 1
                        continue
                    media_filename = mw.col.media.add_file(abs_asset_path)
                    note[target_field] = f'<img src="{media_filename}">'
                else:
                    note[target_field] = api_output

                sec_field = secondary_field_override or str(item.get("secondary_field", "")).strip()
                secondary_output = str(item.get("secondary_output", ""))
                if sec_field and sec_field in note and secondary_output:
                    note[sec_field] = secondary_output

                mw.col.update_note(note)
                success += 1

            except Exception as exc:
                logger.error(f"Reinsert failed for job {job_id} item {item}: {exc}")
                failed += 1

        try:
            mw.col.save()
        except Exception as exc:
            logger.warning(f"Collection save after reinsertion failed: {exc}")

        return {
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "total": len(items),
        }

    def delete_job(self, job_id: str) -> None:
        """Delete a job and its stored assets."""
        job_path = self._job_path(job_id)
        if os.path.exists(job_path):
            os.remove(job_path)

        asset_dir = os.path.join(self._assets_dir, job_id)
        if os.path.isdir(asset_dir):
            shutil.rmtree(asset_dir, ignore_errors=True)
