# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Translator

Single-note translation using Gemini AI with QueryOp pattern.
Adapted from Anki_Deck_Translater/stella_generator.py.
"""

from __future__ import annotations

import os
import re
import json
import time
from typing import Optional, Dict, Any, Callable

from aqt import mw
from aqt.operations import QueryOp
from aqt.utils import showWarning
from anki.collection import Collection
from anki.notes import Note

from ..core.logger import StellaLogger
from ..core.api_key_manager import get_api_key_manager
from ..core.gemini_client import get_gemini_client, GeminiError
from ..core.utils import strip_html, classify_error, ErrorType
from ..core.preview_models import PreviewResult
from ..config.prompts import get_translation_prompt, TRANSLATION_SYSTEM_PROMPT


class Translator:
    """
    Single-note translator using modern QueryOp pattern.
    
    Supports:
    - Context-aware translation
    - Multi-key rotation
    - Async operation with progress
    """
    
    def __init__(self, addon_dir: Optional[str] = None) -> None:
        """
        Initialize the translator.
        
        Args:
            addon_dir: Add-on directory path
        """
        self._addon_dir = addon_dir or os.path.dirname(os.path.dirname(__file__))
        self._logger = StellaLogger.get_logger(self._addon_dir, "translator")
        self._key_manager = get_api_key_manager(self._addon_dir)
        self._gemini = get_gemini_client(self._addon_dir)
        
        self._logger.info("Translator initialized")
    
    def _extract_word_and_context(
        self, note: Note, source_field: str, context_field: str
    ) -> tuple[str, str]:
        """Extract word and context from note fields."""
        word = strip_html(note[source_field]) if source_field in note else ""
        if not word:
            raise ValueError(f"Source field '{source_field}' is empty")
        
        context = ""
        if context_field and context_field in note:
            context = strip_html(note[context_field])
        return word, context
    
    def translate_note_async(
        self,
        parent_widget,
        note: Note,
        source_field: str,
        context_field: str,
        destination_field: str,
        target_language: str,
        model_name: str = "gemini-2.5-flash",
        success_callback: Optional[Callable[[], None]] = None,
        error_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Translate a single note asynchronously.
        
        Args:
            parent_widget: Qt parent widget for progress dialog
            note: Anki note to translate
            source_field: Field containing the word to translate
            context_field: Field containing context/definition
            destination_field: Field to store translation
            target_language: Target language for translation
            model_name: Gemini model to use
            success_callback: Called on success
            error_callback: Called on failure with error message
        """
        
        def background_operation(_col: Collection) -> str:
            """Background task: generate translation."""
            if not self._key_manager.get_current_key():
                raise GeminiError("No API key available. Please add an API key in settings.")
            
            word, context = self._extract_word_and_context(note, source_field, context_field)
            self._logger.info(f"Translating '{word}' to {target_language}")
            
            translation = self._generate_translation(
                word=word, context=context, target_language=target_language, model_name=model_name
            )
            self._logger.info(f"Translation complete: {translation}")
            return translation
        
        def on_success(translation: str) -> None:
            """Success callback on main thread."""
            self._update_note_with_translation(
                note, destination_field, translation, success_callback, error_callback
            )
        
        def on_failure(error: Exception) -> None:
            """Failure callback on main thread."""
            self._handle_translation_failure(error, error_callback)
        
        op = QueryOp(parent=parent_widget, op=background_operation, success=on_success)
        op.failure(on_failure).with_progress("Generating translation...").run_in_background()
    
    def translate_note_preview(
        self,
        note: Note,
        source_field: str,
        context_field: str,
        destination_field: str,
        target_language: str,
        model_name: str = "gemini-2.5-flash",
    ) -> PreviewResult:
        """
        Generate a translation preview without updating the note.
        
        Returns:
            PreviewResult object with generated translation
        """
        if not self._key_manager.get_current_key():
            return PreviewResult(
                note_id=note.id,
                original_text=strip_html(note[source_field]) if source_field in note else "",
                generated_content="Error: No API key available",
                target_field=destination_field,
                error="No API key available"
            )
            
        word, context = self._extract_word_and_context(note, source_field, context_field)
        
        try:
            translation = self._generate_translation(
                word=word, context=context,
                target_language=target_language, model_name=model_name
            )
            
            return PreviewResult(
                note_id=note.id,
                original_text=word,
                generated_content=translation,
                target_field=destination_field
            )
            
        except Exception as e:
            return PreviewResult(
                note_id=note.id,
                original_text=word,
                generated_content=f"Error: {str(e)}",
                target_field=destination_field,
                error=str(e)
            )
    
    def _update_note_with_translation(
        self,
        note: Note,
        destination_field: str,
        translation: str,
        success_callback: Optional[Callable[[], None]],
        error_callback: Optional[Callable[[str], None]],
    ) -> None:
        """Update note with translation result."""
        try:
            note[destination_field] = translation
            mw.col.update_note(note)
            self._logger.info("Note updated successfully")
            if success_callback:
                success_callback()
        except Exception as e:
            error_msg = f"Failed to update note: {e}"
            self._logger.error(error_msg)
            if error_callback:
                error_callback(error_msg)
    
    def _handle_translation_failure(
        self, error: Exception, error_callback: Optional[Callable[[str], None]]
    ) -> None:
        """Handle translation failure."""
        error_msg = self._format_error_message(str(error))
        self._logger.error(f"Translation failed: {error_msg}")
        if error_callback:
            error_callback(error_msg)
        else:
            showWarning(f"Translation failed:\n{error_msg}")
    
    def translate_note_sync(
        self,
        note: Note,
        source_field: str,
        context_field: str,
        target_language: str,
        model_name: str = "gemini-2.5-flash",
    ) -> str:
        """
        Translate a single note synchronously.
        
        Warning: This blocks the UI thread. Use translate_note_async for user-facing operations.
        
        Args:
            note: Anki note to translate
            source_field: Field containing the word
            context_field: Field containing context
            target_language: Target language
            model_name: Gemini model to use
            
        Returns:
            Generated translation
        """
        word = strip_html(note[source_field]) if source_field in note else ""
        if not word:
            raise ValueError(f"Source field '{source_field}' is empty")
        
        context = ""
        if context_field and context_field in note:
            context = strip_html(note[context_field])
        
        translation = self._generate_translation(
            word=word,
            context=context,
            target_language=target_language,
            model_name=model_name,
        )
        
        return translation
    
    def _generate_translation(
        self,
        word: str,
        context: str,
        target_language: str,
        model_name: str,
    ) -> str:
        """
        Generate translation using Gemini API.
        
        Args:
            word: Word to translate
            context: Context for disambiguation
            target_language: Target language
            model_name: Model to use
            
        Returns:
            Translation text
        """
        # Build prompt with explicit JSON format request
        prompt = get_translation_prompt(word, context, target_language)
        # Add JSON format instruction to ensure structured response
        json_instruction = "\n\nRespond with a JSON object containing: {\"translation\": \"<translation>\", \"notes\": \"<optional notes>\"}"
        full_prompt = f"{TRANSLATION_SYSTEM_PROMPT}\n\n{prompt}{json_instruction}"
        
        # Generation config for translation (avoid unsupported response_mime_type for compatibility)
        generation_config = {
            "temperature": 0.3,
            "max_output_tokens": 300,
        }
        
        # Call API with retry logic
        max_retries = 3
        backoff = 2.0
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                response = self._gemini.generate_text(
                    prompt=full_prompt,
                    model_name=model_name,
                    generation_config=generation_config,
                    max_retries=1,  # Handle retries here for key rotation
                )
                
                # Parse JSON response
                data = self._parse_translation_response(response)
                translation = data.get("translation", "").strip()
                
                if not translation:
                    raise ValueError("Empty translation in response")
                
                translation = self._format_translation_text(translation)

                # Record success
                self._key_manager.record_success(operation="translation", count=1)
                
                return translation
                
            except Exception as e:
                last_error = e
                error_str = str(e)
                self._logger.warning(f"Translation attempt {attempt} failed: {error_str}")
                
                # Check for rate limit errors
                error_type, _ = classify_error(e)
                if error_type in (ErrorType.RATE_LIMIT, ErrorType.QUOTA_EXCEEDED):
                    rotated, new_key = self._key_manager.record_failure(error_str)
                    if rotated:
                        self._logger.info(f"Rotated to key: {new_key}")
                        continue
                
                if attempt < max_retries:
                    time.sleep(backoff ** attempt)
        
        raise GeminiError(f"Translation failed after {max_retries} attempts: {last_error}")

    def _format_translation_text(self, translation: str) -> str:
        """
        Format translation output for clean line breaks.

        Examples:
            "1. Instruct 2. Teach, explain." -> "Instruct\nTeach, explain"
        """
        if not translation:
            return translation

        text = translation.strip()

        # Split by numbered list patterns (1. / 2) / 1) / 2))
        numbered_items = [
            item.strip(" \t\n;-")
            for item in re.split(r"\s*(?:\d+[\.|\)]\s*)", text)
            if item.strip()
        ]
        if len(numbered_items) > 1:
            return "\n".join(numbered_items)

        # Split by bullet characters
        bullet_items = [
            item.strip(" \t\n;-")
            for item in re.split(r"[•◦●▪️]", text)
            if item.strip()
        ]
        if len(bullet_items) > 1:
            return "\n".join(bullet_items)

        # Split by semicolon if used as list separator
        semi_items = [item.strip() for item in text.split(";") if item.strip()]
        if len(semi_items) > 1:
            return "\n".join(semi_items)

        return text
    
    def _parse_translation_response(self, response: str) -> Dict[str, Any]:
        """
        Parse and validate translation API response.
        
        Args:
            response: Raw API response text
            
        Returns:
            Parsed dictionary with translation data
        """
        if not response or not response.strip():
            raise ValueError("Empty API response")
        
        cleaned = response.strip()
        
        # Extract JSON from code blocks if present
        code_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
        if code_match:
            cleaned = code_match.group(1).strip()
        
        # Extract JSON object
        if "{" in cleaned and "}" in cleaned:
            json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if json_match:
                cleaned = json_match.group(0)
        
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            self._logger.error(f"JSON parse failed: {e}")
            raise ValueError(f"Invalid JSON response: {cleaned[:100]}...")
        
        if "translation" not in data:
            raise ValueError("Missing 'translation' field in response")
        
        return data
    
    def _format_error_message(self, error: str) -> str:
        """Format error message for user display."""
        error_lower = error.lower()
        
        if "api" in error_lower and "key" in error_lower:
            return f"API Key Error: {error}\n\nPlease check your API key in settings."
        elif "quota" in error_lower or "exhausted" in error_lower:
            return f"Quota Exceeded: {error}\n\nAPI quota exhausted. Try again later."
        elif "rate limit" in error_lower:
            return f"Rate Limited: {error}\n\nToo many requests. Please wait."
        elif "json" in error_lower:
            return f"Response Error: {error}\n\nInvalid response from API."
        else:
            return f"Translation Error: {error}"


def create_translator(addon_dir: Optional[str] = None) -> Translator:
    """Factory function to create a Translator instance."""
    return Translator(addon_dir)
