# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Batch Translator

Batch translation processing using QRunnable pattern for background execution.
Adapted from Anki_Deck_Translater/batch_translator.py.
"""

from __future__ import annotations

import os
import sys
import json
import re
import threading
import time
from typing import List, Dict, Any, Optional, Tuple

from aqt import mw
from aqt.qt import QObject, QRunnable, pyqtSignal

# Add lib path for bundled dependencies
_addon_dir = os.path.dirname(os.path.dirname(__file__))
_lib_path = os.path.join(_addon_dir, "lib")
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

# Handle google namespace package - must be done BEFORE importing google.generativeai
_google_lib_path = os.path.join(_lib_path, "google")
if "google" in sys.modules:
    import google
    if hasattr(google, "__path__"):
        if _google_lib_path not in google.__path__:
            google.__path__.insert(0, _google_lib_path)
else:
    pass  # sys.path insertion above handles namespace resolution

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError as e:
    GENAI_AVAILABLE = False
    genai = None
    # Log the actual import error for debugging
    import traceback
    _import_error = traceback.format_exc()

from ..core.logger import StellaLogger
from ..core.api_key_manager import get_api_key_manager
from ..core.utils import strip_html
from ..config.prompts import TRANSLATION_SYSTEM_PROMPT


class BatchTranslationSignals(QObject):
    """Signals emitted by BatchTranslationWorker."""
    
    progress = pyqtSignal(int, int)  # processed, total
    detailed_progress = pyqtSignal(int, int, int, int)  # processed, total, success, failure
    error_detail = pyqtSignal(str, str, int)  # error_type, message, affected_count
    error = pyqtSignal(str)
    finished = pyqtSignal(int, int)  # success_count, failure_count
    key_rotated = pyqtSignal(str, str)  # old_key_id, new_key_id
    batch_results = pyqtSignal(list)  # list of per-item translation results


class BatchTranslator(QRunnable):
    """
    Background worker for batch translation.
    
    Processes multiple notes in batches with:
    - Rate limiting between batches
    - Automatic API key rotation on failures
    - Progress reporting via signals
    - Cancellation support
    
    Note on default values:
        - batch_size=5 (vs Reference's 10): More conservative for stability
        - batch_delay_seconds=8.0 (vs Reference's 5.0): Longer delay to avoid rate limits
        These conservative defaults prioritize reliability over speed.
    """
    
    # Default constants (documented for reference)
    DEFAULT_BATCH_SIZE = 5  # Reference uses 10, we use 5 for stability
    DEFAULT_BATCH_DELAY = 8.0  # Reference uses 5.0, we use 8.0 for rate limit safety
    
    def __init__(
        self,
        notes_data: List[Dict[str, Any]],
        target_language: str,
        destination_field: str,
        model_name: str = "gemini-2.5-flash",
        batch_size: int = DEFAULT_BATCH_SIZE,
        batch_delay_seconds: float = DEFAULT_BATCH_DELAY,
        ignore_errors: bool = True,
        cancel_event: Optional[threading.Event] = None,
        addon_dir: Optional[str] = None,
    ) -> None:
        """
        Initialize batch translator.
        
        Args:
            notes_data: List of dicts with 'note_id', 'word', 'context'
            target_language: Target language for translation
            destination_field: Field to store translations
            model_name: Gemini model to use
            batch_size: Number of words per API call (default: 5 for stability)
            batch_delay_seconds: Delay between batches (default: 8.0s for rate limit safety)
            ignore_errors: Continue on errors if True
            cancel_event: Event to signal cancellation
            addon_dir: Add-on directory path
        """
        super().__init__()
        
        self.notes_data = notes_data
        self.target_language = target_language
        self.destination_field = destination_field
        self.model_name = model_name or "gemini-2.5-flash"
        self.batch_size = max(1, batch_size)
        self.batch_delay_seconds = max(1.0, batch_delay_seconds)
        self.ignore_errors = ignore_errors
        self.cancel_event = cancel_event or threading.Event()
        
        self._addon_dir = addon_dir or _addon_dir
        self._logger = StellaLogger.get_logger(self._addon_dir, "batch_translator")
        self._key_manager = get_api_key_manager(self._addon_dir)
        
        self.signals = BatchTranslationSignals()
        
        self._model = None
        self._current_api_key: Optional[str] = None
        self._consecutive_rate_errors = 0
    
    def run(self) -> None:
        """Execute batch translation."""
        try:
            if not self.notes_data:
                raise ValueError("No notes to translate")
            
            api_key = self._get_active_api_key()
            if not api_key:
                raise ValueError("No API key available")
            
            self._configure_api()
            self._model = self._build_model()
            
            total = len(self.notes_data)
            processed = 0
            success_count = 0
            failure_count = 0
            
            # Process in batches
            for batch in self._chunk_notes():
                if self.cancel_event.is_set():
                    self._logger.warning("Batch translation cancelled")
                    break
                
                try:
                    # Generate translations for batch
                    translations = self._translate_batch(batch)
                    
                    # Apply translations to notes
                    success, failed, batch_results = self._apply_translations(batch, translations)
                    success_count += success
                    failure_count += failed
                    self.signals.batch_results.emit(batch_results)
                    
                    # Record success
                    if success > 0:
                        self._key_manager.record_success(
                            operation="translation", 
                            count=success
                        )
                    
                    if failed > 0:
                        self.signals.error_detail.emit(
                            "TRANSLATION_MISSING",
                            "Some translations were empty or missing",
                            failed
                        )
                        
                except Exception as batch_error:
                    failure_count += len(batch)
                    error_type = self._classify_error(batch_error)
                    
                    self.signals.error_detail.emit(
                        error_type,
                        str(batch_error)[:200],
                        len(batch)
                    )
                    
                    # Try to rotate key on rate limit errors
                    rotated = self._handle_batch_error(batch_error, error_type)
                    
                    if self.ignore_errors:
                        self._logger.warning(f"Batch error ignored: {batch_error}")
                        if rotated:
                            self._configure_api()
                            self._model = self._build_model()
                    else:
                        self._logger.error(f"Batch translation failed: {batch_error}")
                        self.signals.error.emit(str(batch_error))
                        self.signals.finished.emit(success_count, failure_count)
                        return
                
                processed += len(batch)
                self.signals.progress.emit(processed, total)
                self.signals.detailed_progress.emit(
                    processed, total, success_count, failure_count
                )
                
                # Rate limiting delay
                if not self.cancel_event.is_set():
                    delay = self.batch_delay_seconds
                    if self._consecutive_rate_errors > 0:
                        delay = max(delay, 10.0 + (self._consecutive_rate_errors * 5.0))
                        self._logger.info(f"Extended delay: {delay:.1f}s")
                    self._interruptible_sleep(delay)
            
            self.signals.finished.emit(success_count, failure_count)
            
        except Exception as e:
            self._logger.error(f"Batch translation error: {e}")
            self.signals.error.emit(str(e))
    
    def _get_active_api_key(self) -> Optional[str]:
        """Get the current active API key."""
        if self._key_manager.get_key_count() > 0:
            key = self._key_manager.get_current_key()
            if key:
                self._current_api_key = key
                return key
        return self._current_api_key
    
    def _configure_api(self) -> None:
        """Configure Gemini API with current key."""
        if not GENAI_AVAILABLE:
            # Provide more detailed error message
            error_msg = "google-generativeai not available"
            if '_import_error' in globals():
                error_msg += f"\nImport error details:\n{_import_error}"
            raise RuntimeError(error_msg)
        
        key = self._get_active_api_key()
        if key:
            # Use REST transport to avoid gRPC dependency issues
            genai.configure(api_key=key, transport="rest")
    
    def _build_model(self):
        """Build Gemini model instance."""
        return genai.GenerativeModel(
            model_name=self.model_name,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "translations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "note_id": {"type": "integer"},
                                    "word": {"type": "string"},
                                    "translation": {
                                        "type": "string",
                                        "description": "Numbered list of meanings, e.g., '1. 가르치다, 교육하다\n2. 지시하다, 명령하다\n3. 알리다, 전하다'"
                                    },
                                },
                                "required": ["note_id", "word", "translation"],
                            },
                        },
                    },
                    "required": ["translations"],
                },
                "temperature": 0.4,  # Slightly higher for more varied meanings
                "max_output_tokens": 4096,  # Increased for multiple meanings
            },
        )
    
    def _chunk_notes(self):
        """Yield batches of notes."""
        for i in range(0, len(self.notes_data), self.batch_size):
            yield self.notes_data[i:i + self.batch_size]
    
    def _translate_batch(self, batch: List[Dict[str, Any]]) -> Dict[str, Dict[Any, str]]:
        """
        Translate a batch of words.
        
        Args:
            batch: List of note data dicts
            
        Returns:
            Dictionary with both note_id and word based mappings
        """
        # Build batch prompt
        words_info = []
        for item in batch:
            note_id = item.get("note_id", 0)
            word = item.get("word", "")
            context = item.get("context", "")
            if context:
                words_info.append(f'- note_id: {note_id}, word: "{word}" (context: {context})')
            else:
                words_info.append(f'- note_id: {note_id}, word: "{word}"')
        
        words_list = "\n".join(words_info)
        
        prompt = f"""{TRANSLATION_SYSTEM_PROMPT}

Translate the following words to {self.target_language}.
For each word, provide 3-6 different meanings as a numbered list.

IMPORTANT:
- If context is provided for a word, the meaning matching that context should be listed FIRST
- If no context, order meanings by general usage frequency (most common first)
- Group similar meanings with commas (e.g., "가르치다, 교육하다")
- Each numbered item should be on its own line

Words to translate:
{words_list}

Return a JSON object with this exact structure:
{{
    "translations": [
        {{
            "note_id": 12345,
            "word": "original_word",
            "translation": "1. [first meaning]\n2. [second meaning]\n3. [third meaning]"
        }},
        ...
    ]
}}

Example for "instruct" with context "The teacher instructs the students":
{{
    "translations": [
        {{
            "note_id": 12345,
            "word": "instruct",
            "translation": "1. 가르치다, 교육하다\n2. 지시하다, 명령하다\n3. 알리다, 전하다\n4. 설명하다"
        }}
    ]
}}"""
        
        # Call API
        max_retries = 3
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                response = self._model.generate_content(prompt)
                
                if not response or not response.text:
                    raise ValueError("Empty API response")
                
                # Parse response
                result = self._parse_batch_response(response.text, batch)
                self._consecutive_rate_errors = 0
                return result
                
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                
                # Check for rate limit
                if any(x in error_str for x in ["429", "quota", "rate", "exhausted"]):
                    self._consecutive_rate_errors += 1
                    
                    rotated, new_key = self._key_manager.record_failure(str(e))
                    if rotated:
                        self._logger.info(f"Key rotated to: {new_key}")
                        self._configure_api()
                        self._model = self._build_model()
                        continue
                
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
        
        raise ValueError(f"Batch translation failed: {last_error}")
    
    def _parse_batch_response(
        self, 
        response: str, 
        batch: List[Dict[str, Any]]
    ) -> Dict[str, Dict[Any, str]]:
        """Parse batch translation response."""
        cleaned = response.strip()
        
        # Extract JSON from code blocks
        code_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
        if code_match:
            cleaned = code_match.group(1).strip()
        
        # Extract JSON object
        json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if json_match:
            cleaned = json_match.group(0)
        
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
        
        # Build result dictionaries for robust matching
        by_note_id: Dict[int, str] = {}
        by_word: Dict[str, str] = {}
        translations = data.get("translations", [])
        
        for item in translations:
            note_id = item.get("note_id")
            word = item.get("word", "").strip()
            translation = item.get("translation", "").strip()
            if not translation:
                continue

            if note_id is not None:
                try:
                    by_note_id[int(note_id)] = translation
                except Exception:
                    pass

            if word:
                by_word[word.lower()] = translation
        
        # Fallback mapping by source words to avoid total failure
        if not by_word and by_note_id:
            for item in batch:
                try:
                    note_id = int(item.get("note_id"))
                except Exception:
                    note_id = 0
                word = str(item.get("word", "")).strip().lower()
                if not word:
                    continue
                if note_id in by_note_id:
                    by_word[word] = by_note_id[note_id]

        return {
            "by_note_id": by_note_id,
            "by_word": by_word,
        }
    
    def _apply_translations(
        self, 
        batch: List[Dict[str, Any]], 
        translations: Dict[str, Dict[Any, str]]
    ) -> Tuple[int, int, List[Dict[str, Any]]]:
        """
        Apply translations to notes.
        
        Returns:
            Tuple of (success_count, failure_count, per_item_results)
        """
        success = 0
        failed = 0
        item_results: List[Dict[str, Any]] = []

        by_note_id = translations.get("by_note_id", {})
        by_word = translations.get("by_word", {})
        
        for item in batch:
            raw_note_id = item.get("note_id")
            try:
                note_id = int(raw_note_id)
            except Exception:
                note_id = 0
            word = str(item.get("word", "")).strip()
            word_key = word.lower()
            
            translation = ""
            if note_id in by_note_id:
                translation = by_note_id.get(note_id, "")
            elif word_key:
                translation = by_word.get(word_key, "")

            result_item: Dict[str, Any] = {
                "note_id": note_id,
                "word": word,
                "target_field": self.destination_field,
                "translation": translation,
                "insert_status": "failed",
                "insert_error": "",
            }
            
            if not translation:
                failed += 1
                result_item["insert_error"] = "missing_translation"
                item_results.append(result_item)
                continue
            
            try:
                if note_id <= 0:
                    raise ValueError("invalid_note_id")
                ok, error = self._update_note_on_main_thread(note_id, translation)
                if ok:
                    result_item["insert_status"] = "success"
                    success += 1
                else:
                    result_item["insert_error"] = error or "note_update_failed"
                    failed += 1
            except Exception as e:
                self._logger.error(f"Failed to update note {note_id}: {e}")
                result_item["insert_error"] = str(e)
                failed += 1
            finally:
                item_results.append(result_item)
        
        return success, failed, item_results

    def _run_on_main_thread(self, callback, timeout_seconds: float = 15.0):
        """Run callback on main thread and return its result."""
        if threading.current_thread() is threading.main_thread() or not hasattr(mw, "taskman"):
            return callback()

        done = threading.Event()
        state: Dict[str, Any] = {"result": None, "error": None}

        def wrapped() -> None:
            try:
                state["result"] = callback()
            except Exception as exc:
                state["error"] = exc
            finally:
                done.set()

        mw.taskman.run_on_main(wrapped)
        if not done.wait(timeout_seconds):
            raise TimeoutError("Timed out waiting for main-thread note update")
        if state["error"] is not None:
            raise state["error"]
        return state["result"]

    def _update_note_on_main_thread(self, note_id: int, translation: str) -> Tuple[bool, str]:
        """Safely update a note from worker thread."""
        def _update() -> Tuple[bool, str]:
            note = mw.col.get_note(note_id)
            if not note:
                return False, "note_not_found"
            if self.destination_field not in note:
                return False, "field_not_found"

            note[self.destination_field] = translation
            mw.col.update_note(note)
            return True, ""

        result = self._run_on_main_thread(_update)
        return bool(result[0]), str(result[1])
    
    def _classify_error(self, error: Exception) -> str:
        """Classify error type."""
        error_str = str(error).lower()
        
        if any(x in error_str for x in ["429", "rate limit"]):
            return "RATE_LIMIT"
        elif any(x in error_str for x in ["quota", "exhausted"]):
            return "QUOTA_EXCEEDED"
        elif any(x in error_str for x in ["401", "403", "invalid key"]):
            return "INVALID_KEY"
        elif "json" in error_str:
            return "PARSE_ERROR"
        else:
            return "UNKNOWN"
    
    def _handle_batch_error(self, error: Exception, error_type: str) -> bool:
        """Handle batch error and potentially rotate key."""
        if error_type in ("RATE_LIMIT", "QUOTA_EXCEEDED"):
            rotated, new_key = self._key_manager.record_failure(str(error))
            if rotated and new_key:
                old_key = self._key_manager._get_key_id(self._current_api_key or "")
                self.signals.key_rotated.emit(old_key, new_key)
                self._consecutive_rate_errors = 0
                return True
        
        self._key_manager.record_failure(str(error))
        return False
    
    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep that can be interrupted by cancel event."""
        interval = 0.5
        elapsed = 0.0
        while elapsed < seconds and not self.cancel_event.is_set():
            time.sleep(min(interval, seconds - elapsed))
            elapsed += interval
