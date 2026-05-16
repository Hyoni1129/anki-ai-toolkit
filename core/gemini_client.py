# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Gemini Client

Shared Gemini API client for all features:
- Translation generation
- Sentence generation
- Image prompt generation
- Image generation (via Imagen)

Supports both google-generativeai (legacy) and google-genai (new) SDKs.
"""

from __future__ import annotations

import os
import sys
import time
import json
import re
from typing import Dict, List, Optional, Any, Tuple, Union

# Add lib path for bundled dependencies
_addon_dir = os.path.dirname(os.path.dirname(__file__))
_lib_path = os.path.join(_addon_dir, "lib")
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

# Handle google namespace package conflicts - CRITICAL for bundled libraries
_google_lib_path = os.path.join(_lib_path, "google")
if "google" in sys.modules:
    import google
    if hasattr(google, "__path__"):
        # Insert at beginning to prioritize our bundled version
        if _google_lib_path not in google.__path__:
            google.__path__.insert(0, _google_lib_path)
else:
    # If google not yet imported, sys.path is sufficient
    pass

# Import Gemini SDK (legacy google-generativeai)
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError as e:
    GENAI_AVAILABLE = False
    genai = None
    import traceback
    _genai_import_error = traceback.format_exc()

from .logger import StellaLogger
from .api_key_manager import APIKeyManager, get_api_key_manager
from .utils import (
    classify_error, 
    ErrorType, 
    format_error_message,
    should_rotate_key,
    extract_json_from_response,
)


class GeminiError(Exception):
    """Custom exception for Gemini API errors."""
    pass


class GeminiClient:
    """
    Unified Gemini API client for Stella Anki Tools.
    
    Features:
    - Automatic API key rotation on failures
    - Retry logic with exponential backoff
    - Support for text generation (translation, sentences)
    - Support for image prompt generation
    - Response parsing and validation
    """
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        addon_dir: Optional[str] = None,
        model_name: str = "gemini-2.5-flash"
    ) -> None:
        """
        Initialize the Gemini client.
        
        Args:
            api_key: API key (optional, will use key manager if not provided)
            addon_dir: Add-on directory path
            model_name: Default model to use
        """
        if not GENAI_AVAILABLE:
            raise GeminiError(
                "google-generativeai package is not available. "
                "Please ensure the lib folder contains the bundled SDK."
            )
        
        self._addon_dir = addon_dir or _addon_dir
        self._logger = StellaLogger.get_logger(self._addon_dir, "gemini")
        self._key_manager = get_api_key_manager(self._addon_dir)
        self._model_name = model_name
        self._api_key = api_key
        
        # Configure API if key provided
        if api_key:
            self._configure_api(api_key)
    
    def _configure_api(self, api_key: str) -> None:
        """Configure the Gemini API with a key."""
        try:
            # Use REST transport to avoid gRPC dependency issues
            genai.configure(api_key=api_key, transport="rest")
            self._api_key = api_key
            self._logger.debug("Gemini API configured with REST transport")
        except Exception as e:
            self._logger.error(f"Failed to configure Gemini API: {e}")
            raise GeminiError(f"Failed to configure API: {e}")
    
    def _get_api_key(self) -> str:
        """Get the current API key from manager or stored key."""
        if self._key_manager.maybe_auto_reset_after_inactivity():
            self._api_key = None

        if self._api_key:
            return self._api_key
        
        key = self._key_manager.get_current_key()
        if not key:
            raise GeminiError("No API key available. Please add an API key in settings.")
        
        return key
    
    def _get_model(
        self, 
        model_name: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Get a configured Gemini model instance.
        
        Args:
            model_name: Model name override
            generation_config: Generation configuration
            
        Returns:
            Configured GenerativeModel instance
        """
        api_key = self._get_api_key()
        self._configure_api(api_key)
        
        model = model_name or self._model_name
        
        return genai.GenerativeModel(
            model_name=model,
            generation_config=generation_config,
        )
    
    def generate_text(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> str:
        """
        Generate text using Gemini API.
        
        Args:
            prompt: The prompt to send
            model_name: Model name override
            generation_config: Generation configuration
            max_retries: Maximum retry attempts
            retry_delay: Initial delay between retries (seconds)
            
        Returns:
            Generated text response
            
        Raises:
            GeminiError: If generation fails after all retries
        """
        last_error = None
        backoff = retry_delay
        
        for attempt in range(1, max_retries + 1):
            try:
                response_text = self._attempt_generate(prompt, model_name, generation_config, attempt, max_retries)
                self._key_manager.record_success(operation="translation", count=1)
                return response_text
                
            except Exception as e:
                last_error = e
                if not self._handle_generation_error(e, attempt, max_retries, backoff):
                    backoff *= 2  # Exponential backoff
        
        error_msg = format_error_message(last_error, "generate text")
        raise GeminiError(error_msg)
    
    def _attempt_generate(
        self, prompt: str, model_name: Optional[str],
        generation_config: Optional[Dict[str, Any]], attempt: int, max_retries: int
    ) -> str:
        """Single attempt to generate text."""
        model = self._get_model(model_name, generation_config)
        self._logger.debug(f"Generating text (attempt {attempt}/{max_retries})")
        response = model.generate_content(prompt)
        
        if not response:
            raise GeminiError("API returned None response")
        
        response_text = response.text if response.text else ""
        if not response_text.strip():
            raise GeminiError("API returned empty response")
        
        return response_text.strip()
    
    def _handle_generation_error(
        self, error: Exception, attempt: int, max_retries: int, backoff: float
    ) -> bool:
        """Handle generation error. Returns True if retry should be skipped."""
        error_str = str(error)
        self._logger.warning(f"API call failed (attempt {attempt}): {error_str}")
        
        if should_rotate_key(error):
            rotated, new_key_id = self._key_manager.record_failure(error_str)
            if rotated:
                self._logger.info(f"Rotated to new API key: {new_key_id}")
                self._api_key = None
                return True  # Skip delay, retry immediately with new key
        
        self._key_manager.record_failure(error_str)
        
        if attempt < max_retries:
            self._logger.info(f"Retrying in {backoff:.1f} seconds...")
            time.sleep(backoff)
        
        return False
    
    def generate_json(
        self,
        prompt: str,
        schema: Optional[Dict[str, Any]] = None,
        model_name: Optional[str] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        Generate structured JSON response from Gemini.
        
        Args:
            prompt: The prompt to send
            schema: JSON schema for response structure
            model_name: Model name override
            max_retries: Maximum retry attempts
            
        Returns:
            Parsed JSON response as dictionary
            
        Raises:
            GeminiError: If generation or parsing fails
        """
        generation_config: Dict[str, Any] = {
            "temperature": 0.3,
            "max_output_tokens": 512,
        }
        
        # Add JSON format instruction to prompt instead of using response_schema
        # (response_mime_type/response_schema may not be supported in older SDK versions)
        json_prompt = prompt
        if schema:
            json_prompt = f"{prompt}\n\nRespond with valid JSON only. No markdown formatting."
        
        response_text = self.generate_text(
            prompt=json_prompt,
            model_name=model_name,
            generation_config=generation_config,
            max_retries=max_retries,
        )
        
        # Try to parse JSON response
        try:
            # First try direct parsing
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown or other formatting
            extracted = extract_json_from_response(response_text)
            if extracted:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass
            
            raise GeminiError(f"Failed to parse JSON response: {response_text[:100]}...")
    
    def generate_translation(
        self,
        word: str,
        context: str,
        target_language: str,
        model_name: Optional[str] = None,
    ) -> str:
        """
        Generate a translation for a word.
        
        Args:
            word: Word to translate
            context: Context/definition for disambiguation
            target_language: Target language
            model_name: Model name override
            
        Returns:
            Translated text
        """
        from ..config.prompts import get_translation_prompt, TRANSLATION_SYSTEM_PROMPT
        
        prompt = get_translation_prompt(word, context, target_language)
        full_prompt = f"{TRANSLATION_SYSTEM_PROMPT}\n\n{prompt}"
        
        generation_config = {
            "temperature": 0.3,
            "max_output_tokens": 256,
        }
        
        response = self.generate_text(
            prompt=full_prompt,
            model_name=model_name,
            generation_config=generation_config,
        )
        
        return response.strip()
    
    def generate_sentence(
        self,
        word: str,
        target_language: str,
        difficulty: str = "Normal",
        model_name: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Generate an example sentence for a word.
        
        Args:
            word: Word to create sentence for
            target_language: Language for the sentence
            difficulty: Sentence complexity
            model_name: Model name override
            
        Returns:
            Dictionary with sentence data
        """
        from ..config.prompts import get_sentence_prompt, SENTENCE_SYSTEM_PROMPT
        
        prompt = get_sentence_prompt(word, target_language, difficulty)
        full_prompt = f"{SENTENCE_SYSTEM_PROMPT}\n\n{prompt}"
        
        schema = {
            "type": "object",
            "properties": {
                "translated_sentence": {"type": "string"},
                "translated_conjugated_word": {"type": "string"},
                "english_sentence": {"type": "string"},
                "english_word": {"type": "string"},
            },
            "required": [
                "translated_sentence", 
                "translated_conjugated_word",
                "english_sentence", 
                "english_word"
            ],
        }
        
        result = self.generate_json(
            prompt=full_prompt,
            schema=schema,
            model_name=model_name,
        )
        
        # Record success for sentence
        self._key_manager.record_success(operation="sentence", count=1)
        
        return result
    
    def generate_image_prompt(
        self,
        word: str,
        style_preset: str = "anime",
        custom_instructions: str = "",
        model_name: Optional[str] = None,
    ) -> str:
        """
        Generate an image generation prompt for a word.
        
        Args:
            word: Word to visualize
            style_preset: Art style preset
            custom_instructions: Additional instructions
            model_name: Model name override
            
        Returns:
            Image generation prompt
        """
        from ..config.prompts import get_image_prompt, IMAGE_SYSTEM_PROMPT
        
        prompt = get_image_prompt(word, style_preset, custom_instructions)
        full_prompt = f"{IMAGE_SYSTEM_PROMPT}\n\n{prompt}"
        
        generation_config = {
            "temperature": 0.8,
            "max_output_tokens": 1024,
        }
        
        response = self.generate_text(
            prompt=full_prompt,
            model_name=model_name or "gemini-1.5-pro",  # Use pro model for creative tasks
            generation_config=generation_config,
        )
        
        return response.strip()
    
    def generate_image_prompts_batch(
        self,
        words: List[str],
        master_prompt: str = "",
        style_preset: str = "anime",
        model_name: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Generate image prompts for multiple words in a single request.
        
        Args:
            words: List of words (recommended 20-30 per batch)
            master_prompt: Master style guide
            style_preset: Art style preset
            model_name: Model name override
            
        Returns:
            Dictionary mapping words to prompts
        """
        if not words:
            return {}
        
        from ..config.prompts import IMAGE_STYLE_PRESETS, MASTER_IMAGE_PROMPT
        
        style = IMAGE_STYLE_PRESETS.get(style_preset, IMAGE_STYLE_PRESETS["anime"])
        
        words_list = "\n".join([f"- {word}" for word in words])
        
        batch_prompt = f"""Generate image prompts for vocabulary flashcards.

**Style Requirements:**
{style}

**Master Instructions:**
{master_prompt or MASTER_IMAGE_PROMPT}

**Words to process:**
{words_list}

For each word, generate a detailed scene description.
Return a JSON object with word as key and prompt as value.

Example format:
{{
    "apple": "A cute anime-style girl picking a shiny red apple...",
    "run": "An energetic anime character sprinting through..."
}}"""

        schema = {
            "type": "object",
            "additionalProperties": {"type": "string"},
        }
        
        result = self.generate_json(
            prompt=batch_prompt,
            schema=schema,
            model_name=model_name or "gemini-1.5-pro",
        )
        
        return result
    
    def test_connection(self, api_key: Optional[str] = None) -> Tuple[bool, str]:
        """
        Test API connection with a simple request.
        
        Args:
            api_key: API key to test (uses current key if not provided)
            
        Returns:
            Tuple of (success, message)
        """
        try:
            if api_key:
                self._configure_api(api_key)
            
            model = self._get_model()
            response = model.generate_content("Say 'Hello' in one word.")
            
            if response and response.text:
                return True, "Connection successful!"
            else:
                return False, "API returned empty response."
                
        except Exception as e:
            _, message = classify_error(e)
            return False, message


# Module-level client instance
_client: Optional[GeminiClient] = None


def get_gemini_client(addon_dir: Optional[str] = None) -> GeminiClient:
    """Get the shared GeminiClient instance."""
    global _client
    if _client is None:
        _client = GeminiClient(addon_dir=addon_dir)
    return _client
