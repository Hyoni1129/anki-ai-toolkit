# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Progress State Manager

Manages persistent state for batch operations to support resume capability.
Adapted from Anki_Sentence_generater/progress_state.py.
"""

from __future__ import annotations

import os
import json
import shutil
from datetime import datetime, timezone
from typing import Dict, List, Optional, Iterable, Any

from ..core.logger import StellaLogger


def _utc_timestamp() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ProgressStateManager:
    """
    Manages persistent batch operation state for resume support.
    
    Features:
    - Atomic writes with backup files
    - Track pending/failed notes per deck
    - Resume interrupted operations
    - Clean up completed runs
    """
    
    def __init__(
        self, 
        addon_dir: str, 
        operation: str = "batch",
        logger: Optional[StellaLogger] = None
    ) -> None:
        """
        Initialize the progress state manager.
        
        Args:
            addon_dir: Add-on directory path
            operation: Operation type (batch, translation, sentence, image)
            logger: Optional logger instance
        """
        self._addon_dir = addon_dir
        self._operation = operation
        self._state_path = os.path.join(addon_dir, f"progress_state_{operation}.json")
        self._backup_path = f"{self._state_path}.bak"
        self._logger = logger or StellaLogger.get_logger(addon_dir, "progress")
        self._state: Dict[str, Dict[str, Any]] = self._load_state()
    
    # === Persistence ===
    
    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        """Load state from file."""
        # Try primary file
        primary = self._read_state_file(self._state_path)
        if primary is not None:
            return primary
        
        # Try backup
        backup = self._read_state_file(self._backup_path)
        if backup is not None:
            self._log_warning("Restored from backup file")
            try:
                self._atomic_write(backup, self._state_path)
            except OSError as e:
                self._log_warning(f"Failed to restore primary file: {e}")
            return backup
        
        return {}
    
    def _read_state_file(self, path: str) -> Optional[Dict[str, Dict[str, Any]]]:
        """Read state from a file."""
        if not os.path.exists(path):
            return None
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if isinstance(data, dict):
                return data
            
            self._log_warning(f"Invalid data format in {path}")
            return None
            
        except (OSError, json.JSONDecodeError) as e:
            self._log_warning(f"Error reading {path}: {e}")
            return None
    
    def _save_state(self) -> None:
        """Save state to file with backup."""
        directory = os.path.dirname(self._state_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        
        try:
            self._atomic_write(self._state, self._state_path)
        except OSError as e:
            self._log_warning(f"Failed to save state: {e}")
            return
        
        # Create backup
        try:
            shutil.copyfile(self._state_path, self._backup_path)
        except OSError as e:
            self._log_warning(f"Failed to create backup: {e}")
    
    def _atomic_write(self, data: Dict, path: str) -> None:
        """Write data atomically using a temp file."""
        temp_path = f"{path}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            
            os.replace(temp_path, path)
            
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
    
    def _log_warning(self, message: str) -> None:
        """Log a warning message."""
        if self._logger:
            self._logger.warning(message)
    
    def _get_run(self, deck_id: int) -> Optional[Dict[str, Any]]:
        """Get run state for a deck."""
        return self._state.get(str(deck_id))
    
    # === Public API ===
    
    def start_run(
        self, 
        deck_id: int, 
        deck_name: str, 
        note_ids: Iterable[int]
    ) -> None:
        """
        Start or restart a run for a deck.
        
        Args:
            deck_id: Anki deck ID
            deck_name: Deck name for display
            note_ids: Note IDs to process
        """
        unique_ids = list(dict.fromkeys(int(nid) for nid in note_ids))
        
        self._state[str(deck_id)] = {
            "deck_name": deck_name,
            "pending": unique_ids,
            "failed": {},
            "total": len(unique_ids),
            "started_at": _utc_timestamp(),
            "last_updated": _utc_timestamp(),
            "operation": self._operation,
        }
        
        self._save_state()
    
    def has_pending_run(self, deck_id: int) -> bool:
        """Check if a deck has pending notes to process."""
        run = self._get_run(deck_id)
        return bool(run and run.get("pending"))
    
    def get_pending_note_ids(self, deck_id: int) -> List[int]:
        """Get list of pending note IDs for a deck."""
        run = self._get_run(deck_id)
        if not run:
            return []
        return [int(nid) for nid in run.get("pending", [])]
    
    def get_failed_details(self, deck_id: int) -> Dict[int, Dict[str, Any]]:
        """Get details of failed notes for a deck."""
        run = self._get_run(deck_id)
        if not run:
            return {}
        failed = run.get("failed", {})
        return {int(k): v for k, v in failed.items()}
    
    def update_pending(self, deck_id: int, remaining_ids: Iterable[int]) -> None:
        """Update the pending list for a deck."""
        run = self._get_run(deck_id)
        if not run:
            return
        
        run["pending"] = list(dict.fromkeys(int(nid) for nid in remaining_ids))
        run["last_updated"] = _utc_timestamp()
        self._save_state()
    
    def mark_success(self, deck_id: int, note_id: int) -> None:
        """Mark a note as successfully processed."""
        run = self._get_run(deck_id)
        if not run:
            return
        
        note_id = int(note_id)
        pending = run.setdefault("pending", [])
        
        if note_id in pending:
            pending.remove(note_id)
        
        # Remove from failed if present
        failed = run.setdefault("failed", {})
        failed.pop(str(note_id), None)
        
        run["last_updated"] = _utc_timestamp()
        self._save_state()
    
    def mark_failure(
        self, 
        deck_id: int, 
        note_id: int, 
        error_message: str
    ) -> None:
        """Mark a note as failed with error details."""
        run = self._get_run(deck_id)
        if not run:
            return
        
        note_id = int(note_id)
        failed = run.setdefault("failed", {})
        
        failure_info = failed.get(str(note_id), {})
        failure_info["message"] = error_message
        failure_info["last_failure"] = _utc_timestamp()
        failure_info["count"] = failure_info.get("count", 0) + 1
        
        failed[str(note_id)] = failure_info
        run["last_updated"] = _utc_timestamp()
        self._save_state()
    
    def clear_run(self, deck_id: int) -> None:
        """Clear run state for a deck."""
        if str(deck_id) in self._state:
            self._state.pop(str(deck_id))
            self._save_state()
    
    def reset_failures_to_pending(self, deck_id: int) -> None:
        """Move all failed notes back to pending."""
        run = self._get_run(deck_id)
        if not run:
            return
        
        failed = run.get("failed", {})
        if not failed:
            return
        
        pending = run.setdefault("pending", [])
        for note_id_str in failed.keys():
            note_id = int(note_id_str)
            if note_id not in pending:
                pending.append(note_id)
        
        run["failed"] = {}
        run["last_updated"] = _utc_timestamp()
        self._save_state()
    
    def clear_missing_notes(
        self, 
        deck_id: int, 
        existing_note_ids: Iterable[int]
    ) -> None:
        """Remove notes that no longer exist from the run."""
        run = self._get_run(deck_id)
        if not run:
            return
        
        existing = set(int(nid) for nid in existing_note_ids)
        
        pending = [nid for nid in run.get("pending", []) if int(nid) in existing]
        failed = {
            str(nid): info
            for nid, info in run.get("failed", {}).items()
            if int(nid) in existing
        }
        
        run["pending"] = pending
        run["failed"] = failed
        run["last_updated"] = _utc_timestamp()
        self._save_state()
    
    def describe_run(self, deck_id: int) -> Optional[Dict[str, Any]]:
        """Get a summary description of a run."""
        run = self._get_run(deck_id)
        if not run:
            return None
        
        return {
            "deck_name": run.get("deck_name"),
            "pending_count": len(run.get("pending", [])),
            "failed_count": len(run.get("failed", {})),
            "total": run.get("total", 0),
            "started_at": run.get("started_at"),
            "last_updated": run.get("last_updated"),
            "operation": run.get("operation", self._operation),
        }
    
    def get_all_runs(self) -> Dict[int, Dict[str, Any]]:
        """Get summaries of all active runs."""
        result = {}
        for deck_id_str in self._state:
            try:
                deck_id = int(deck_id_str)
                summary = self.describe_run(deck_id)
                if summary:
                    result[deck_id] = summary
            except ValueError:
                continue
        return result
