# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Image Prompt Generator

Generates optimized image prompts for vocabulary cards using Gemini API.
Adapts user-provided words/contexts into effective text-to-image prompts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Dict, Any, List
from dataclasses import dataclass
import json
import re

if TYPE_CHECKING:
    from aqt.editor import Editor
    from anki.notes import Note

from ..core.logger import get_logger
from ..core.gemini_client import GeminiClient
from ..core.utils import strip_html, classify_error
from ..config.settings import ConfigManager
from ..config.prompts import get_image_prompt, MASTER_IMAGE_PROMPT, IMAGE_STYLE_PRESETS


logger = get_logger(__name__)


@dataclass
class ImagePromptResult:
    """Result of image prompt generation"""
    word: str
    prompt: str
    style: str
    success: bool
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ImagePromptGenerator:
    """
    Generates optimized image prompts for vocabulary flashcards.
    
    Uses Gemini to create detailed, visually descriptive prompts
    suitable for text-to-image models like Gemini Imagen.
    """
    
    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        """
        Initialize prompt generator.
        
        Args:
            gemini_client: Optional pre-configured GeminiClient instance
        """
        self._gemini_client = gemini_client
        self._config_manager = ConfigManager()
    
    @property
    def gemini_client(self) -> GeminiClient:
        """Lazy-load GeminiClient if not provided."""
        if self._gemini_client is None:
            from ..core.api_key_manager import APIKeyManager
            key_manager = APIKeyManager()
            self._gemini_client = GeminiClient(key_manager)
        return self._gemini_client
    
    @property
    def config(self):
        """Get current image configuration."""
        return self._config_manager.config.image
    
    def generate_prompt(
        self,
        word: str,
        context: Optional[str] = None,
        style: Optional[str] = None,
        custom_instructions: Optional[str] = None
    ) -> ImagePromptResult:
        """
        Generate an optimized image prompt for a word.
        
        Args:
            word: The vocabulary word or phrase
            context: Optional context (sentence, definition) for better prompts
            style: Style preset name (e.g., 'cinematic', 'illustration', 'minimal')
            custom_instructions: Additional instructions for prompt generation
            
        Returns:
            ImagePromptResult with generated prompt
        """
        try:
            word = strip_html(word).strip()
            if not word:
                return ImagePromptResult(
                    word="",
                    prompt="",
                    style=style or "default",
                    success=False,
                    error="Empty word provided"
                )
            
            # Get style preset
            style_name = style or self.config.style_preset
            style_config = IMAGE_STYLE_PRESETS.get(style_name, IMAGE_STYLE_PRESETS.get("cinematic", {}))
            
            # Build the prompt generation request
            prompt_request = self._build_prompt_request(
                word=word,
                context=context,
                style_config=style_config,
                custom_instructions=custom_instructions
            )
            
            # Generate prompt using Gemini
            response = self.gemini_client.generate_json(
                prompt=prompt_request,
                model_name=self._config_manager.config.api.model,
                schema={
                    "type": "object",
                    "properties": {
                        "image_prompt": {"type": "string"},
                        "visual_elements": {"type": "array", "items": {"type": "string"}},
                        "reasoning": {"type": "string"}
                    },
                    "required": ["image_prompt"]
                },
            )

            image_prompt = response.get("image_prompt", "") if isinstance(response, dict) else ""
            if image_prompt:
                
                # Apply style modifiers if configured
                if style_config.get("suffix"):
                    image_prompt = f"{image_prompt}, {style_config['suffix']}"
                
                return ImagePromptResult(
                    word=word,
                    prompt=image_prompt,
                    style=style_name,
                    success=True,
                    metadata={
                        "reasoning": response.get("reasoning", ""),
                        "visual_elements": response.get("visual_elements", [])
                    }
                )
            else:
                # Fallback to simple prompt
                fallback_prompt = self._generate_fallback_prompt(word, style_config)
                return ImagePromptResult(
                    word=word,
                    prompt=fallback_prompt,
                    style=style_name,
                    success=True,
                    metadata={"fallback": True, "error": "No image_prompt in response"}
                )
                
        except Exception as e:
            logger.error(f"Prompt generation failed for '{word}': {e}")
            error_type, error_msg = classify_error(e)
            
            # Still provide a fallback prompt
            fallback_prompt = self._generate_fallback_prompt(word, {})
            return ImagePromptResult(
                word=word,
                prompt=fallback_prompt,
                style=style or self.config.style_preset,
                success=True,  # Fallback succeeded
                error=f"{error_type}: {error_msg}",
                metadata={"fallback": True}
            )
    
    def generate_prompt_sync(
        self,
        word: str,
        style: Optional[str] = None,
        context: Optional[str] = None
    ) -> str:
        """
        Generate a prompt synchronously (simplified interface).
        
        Args:
            word: The vocabulary word
            style: Style preset name
            context: Optional context
            
        Returns:
            Generated prompt string
        """
        result = self.generate_prompt(
            word=word,
            context=context,
            style=style
        )
        return result.prompt
    
    def generate_prompts_batch(
        self,
        words: List[str],
        style: Optional[str] = None,
        custom_instructions: Optional[str] = None
    ) -> Dict[str, ImagePromptResult]:
        """
        Generate prompts for multiple words in a single API call.
        
        Uses batch processing for efficiency (20-30 words per batch).
        
        Args:
            words: List of vocabulary words
            style: Style preset for all words
            custom_instructions: Additional instructions
            
        Returns:
            Dictionary mapping words to their ImagePromptResult
        """
        results: Dict[str, ImagePromptResult] = {}
        
        if not words:
            return results
        
        # Clean words
        clean_words = [strip_html(w).strip() for w in words if strip_html(w).strip()]
        if not clean_words:
            return results
        
        style_name = style or self.config.style_preset
        style_config = IMAGE_STYLE_PRESETS.get(style_name, {})
        
        # Process in batches of 25
        batch_size = 25
        for i in range(0, len(clean_words), batch_size):
            batch = clean_words[i:i + batch_size]
            batch_results = self._generate_batch(batch, style_config, custom_instructions)
            results.update(batch_results)
        
        return results
    
    def _generate_batch(
        self,
        words: List[str],
        style_config: Dict[str, Any],
        custom_instructions: Optional[str]
    ) -> Dict[str, ImagePromptResult]:
        """Generate prompts for a single batch of words."""
        results: Dict[str, ImagePromptResult] = {}
        
        try:
            batch_prompt = self._build_batch_prompt_request(words, style_config, custom_instructions)
            
            # Request JSON response with prompts for all words
            response = self.gemini_client.generate_json(
                prompt=batch_prompt,
                model_name=self._config_manager.config.api.model,
                schema={
                    "type": "object",
                    "properties": {
                        "prompts": {
                            "type": "object",
                            "additionalProperties": {"type": "string"}
                        }
                    },
                    "required": ["prompts"]
                },
            )

            prompts_dict = response.get("prompts", {}) if isinstance(response, dict) else {}
            if prompts_dict:
                
                for word in words:
                    if word in prompts_dict:
                        prompt = prompts_dict[word]
                        if style_config.get("suffix"):
                            prompt = f"{prompt}, {style_config['suffix']}"
                        
                        results[word] = ImagePromptResult(
                            word=word,
                            prompt=prompt,
                            style=style_config.get("name", "default"),
                            success=True
                        )
                    else:
                        # Word missing from response - use fallback
                        results[word] = ImagePromptResult(
                            word=word,
                            prompt=self._generate_fallback_prompt(word, style_config),
                            style=style_config.get("name", "default"),
                            success=True,
                            metadata={"fallback": True}
                        )
            else:
                # Batch failed - generate fallbacks for all
                for word in words:
                    results[word] = ImagePromptResult(
                        word=word,
                        prompt=self._generate_fallback_prompt(word, style_config),
                        style=style_config.get("name", "default"),
                        success=True,
                        error="Missing prompt for word",
                        metadata={"fallback": True}
                    )
                    
        except Exception as e:
            logger.error(f"Batch prompt generation failed: {e}")
            for word in words:
                results[word] = ImagePromptResult(
                    word=word,
                    prompt=self._generate_fallback_prompt(word, style_config),
                    style=style_config.get("name", "default"),
                    success=True,
                    error=str(e),
                    metadata={"fallback": True}
                )
        
        return results
    
    def _build_prompt_request(
        self,
        word: str,
        context: Optional[str],
        style_config: Dict[str, Any],
        custom_instructions: Optional[str]
    ) -> str:
        """Build the prompt generation request for a single word."""
        style_desc = style_config.get("description", "cinematic, photorealistic, high detail")
        
        request = f"""Generate a vivid, visually descriptive image prompt for the vocabulary word: "{word}"

The prompt should:
1. Clearly visualize the meaning of the word
2. Be suitable for a text-to-image AI model (Gemini Imagen)
3. Focus on a single, clear subject
4. Include specific visual details (lighting, composition, mood)
5. Be concise but descriptive (15-40 words ideal)

Style: {style_desc}
"""
        
        if context:
            request += f"\nContext/Definition: {context}\n"
        
        if custom_instructions:
            request += f"\nAdditional Instructions: {custom_instructions}\n"
        
        request += """
Respond with JSON containing:
- "image_prompt": The generated prompt (string)
- "visual_elements": Key visual elements in the prompt (array of strings)
- "reasoning": Brief explanation of your choices (string)
"""
        
        return request
    
    def _build_batch_prompt_request(
        self,
        words: List[str],
        style_config: Dict[str, Any],
        custom_instructions: Optional[str]
    ) -> str:
        """Build batch prompt generation request."""
        style_desc = style_config.get("description", "cinematic, photorealistic, high detail")
        words_list = "\n".join([f"- {word}" for word in words])
        
        request = f"""Generate vivid, visually descriptive image prompts for these vocabulary words:

{words_list}

Requirements for each prompt:
1. Clearly visualize the word's meaning
2. Suitable for text-to-image AI (Gemini Imagen)
3. Single, clear subject
4. Specific visual details (lighting, composition)
5. Concise but descriptive (15-40 words)

Style: {style_desc}
"""
        
        if custom_instructions:
            request += f"\nAdditional Instructions: {custom_instructions}\n"
        
        request += """
Respond with JSON:
{
    "prompts": {
        "word1": "image prompt for word1",
        "word2": "image prompt for word2",
        ...
    }
}
"""
        
        return request
    
    def _generate_fallback_prompt(self, word: str, style_config: Dict[str, Any]) -> str:
        """Generate a simple fallback prompt when API fails."""
        style_suffix = style_config.get("suffix", "cinematic lighting, high detail, professional")
        return f"A clear, vivid illustration of {word}, {style_suffix}"
    
    def refine_prompt(
        self,
        word: str,
        base_prompt: str,
        feedback: Optional[str] = None
    ) -> ImagePromptResult:
        """
        Refine an existing prompt based on feedback or for optimization.
        
        Args:
            word: The vocabulary word
            base_prompt: The existing prompt to refine
            feedback: Optional feedback for improvement
            
        Returns:
            ImagePromptResult with refined prompt
        """
        try:
            refinement_request = f"""Refine this image generation prompt for the word "{word}".

Current prompt: {base_prompt}
"""
            if feedback:
                refinement_request += f"\nFeedback: {feedback}\n"
            
            refinement_request += """
Make it more:
- Visually specific and descriptive
- Effective for text-to-image models
- Clear in conveying the word's meaning

Respond with JSON:
- "image_prompt": The refined prompt
- "changes": What was improved
"""
            
            response = self.gemini_client.generate_json(
                prompt=refinement_request,
                model_name=self._config_manager.config.api.model,
                schema={
                    "type": "object",
                    "properties": {
                        "image_prompt": {"type": "string"},
                        "changes": {"type": "string"}
                    },
                    "required": ["image_prompt"]
                },
            )
            
            if isinstance(response, dict) and response.get("image_prompt"):
                return ImagePromptResult(
                    word=word,
                    prompt=response.get("image_prompt", base_prompt),
                    style="refined",
                    success=True,
                    metadata={"changes": response.get("changes", "")}
                )

            return ImagePromptResult(
                word=word,
                prompt=base_prompt,
                style="original",
                success=False,
                error="No image_prompt in response"
            )
                
        except Exception as e:
            logger.error(f"Prompt refinement failed: {e}")
            return ImagePromptResult(
                word=word,
                prompt=base_prompt,
                style="original",
                success=False,
                error=str(e)
            )
