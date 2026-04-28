# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Image Generator

Generates images using Gemini Imagen (Nano Banana) model.
Handles the actual image generation from text prompts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Dict, Any, Union, List
from dataclasses import dataclass, field
from pathlib import Path
from io import BytesIO
from datetime import datetime
import time
import tempfile
import os
import sys

# Setup lib path for bundled dependencies
_addon_dir = os.path.dirname(os.path.dirname(__file__))
_lib_path = os.path.join(_addon_dir, "lib")
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

# Handle google namespace package conflicts
_google_lib_path = os.path.join(_lib_path, "google")
if "google" in sys.modules:
    import google
    if hasattr(google, "__path__"):
        if _google_lib_path not in google.__path__:
            google.__path__.insert(0, _google_lib_path)

if TYPE_CHECKING:
    from aqt.editor import Editor
    from anki.notes import Note

from ..core.logger import get_logger
from ..core.api_key_manager import APIKeyManager
from ..core.utils import classify_error, ErrorType
from ..core.preview_models import PreviewResult
from ..config.settings import ConfigManager


logger = get_logger(__name__)


@dataclass
class ImageGenerationResult:
    """Result of image generation"""
    word: str
    prompt: str
    success: bool
    image_data: Optional[bytes] = None
    image_path: Optional[str] = None
    error: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    generation_time: float = 0.0
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ImageGenerationError(Exception):
    """Custom exception for image generation errors"""
    pass


class ImageGenerator:
    """
    Generates images using Gemini Imagen (gemini-2.5-flash-image-preview).
    
    Handles API communication, rate limiting, retries, and image processing.
    Designed to work with Anki add-on architecture (uses bundled SDK).
    """
    
    # Model for image generation
    IMAGE_MODEL = "gemini-2.5-flash-image-preview"
    
    # Rate limiting
    DEFAULT_REQUEST_DELAY = 2.0  # seconds between requests
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY = 5.0  # seconds
    
    def __init__(
        self,
        api_key_manager: Optional[APIKeyManager] = None,
        request_delay: Optional[float] = None,
        max_retries: Optional[int] = None
    ):
        """
        Initialize image generator.
        
        Args:
            api_key_manager: APIKeyManager for key rotation
            request_delay: Delay between requests in seconds
            max_retries: Maximum retry attempts
        """
        self._key_manager = api_key_manager
        self._config_manager = ConfigManager()
        self._client = None
        self._legacy_mode = False
        
        # Rate limiting configuration
        self.request_delay = request_delay or self.DEFAULT_REQUEST_DELAY
        self.max_retries = max_retries or self.DEFAULT_MAX_RETRIES
        self.retry_delay = self.DEFAULT_RETRY_DELAY
        
        # Statistics
        self._stats = {
            "total_requests": 0,
            "successful": 0,
            "failed": 0,
            "total_generation_time": 0.0
        }
    
    @property
    def key_manager(self) -> APIKeyManager:
        """Lazy-load APIKeyManager."""
        if self._key_manager is None:
            self._key_manager = APIKeyManager()
        return self._key_manager
    
    @property
    def config(self):
        """Get current image configuration."""
        return self._config_manager.config.image
    
    def _ensure_client(self) -> bool:
        """
        Ensure the Gemini client is initialized.
        
        Returns:
            True if client is ready, False otherwise
        """
        if self._client is not None:
            return True
        
        api_key = self.key_manager.get_current_key()
        if not api_key:
            logger.error("No API key available for image generation")
            return False
        
        try:
            # Try new GenAI SDK first (google-genai)
            try:
                from google import genai
                self._client = genai.Client(api_key=api_key)
                self._legacy_mode = False
                logger.info("Image generator using new GenAI SDK")
                return True
            except ImportError:
                pass
            
            # Fall back to legacy SDK (google-generativeai)
            try:
                import google.generativeai as genai_legacy
                genai_legacy.configure(api_key=api_key)
                self._client = genai_legacy.GenerativeModel(model_name=self.IMAGE_MODEL)
                self._legacy_mode = True
                logger.info("Image generator using legacy google-generativeai SDK")
                return True
            except ImportError:
                pass
            
            logger.error("No Gemini SDK available for image generation")
            return False
            
        except Exception as e:
            logger.error(f"Failed to initialize image generation client: {e}")
            return False
    
    def _reinitialize_with_new_key(self) -> bool:
        """Reinitialize client with a new API key after rotation."""
        self._client = None
        return self._ensure_client()
    
    def generate_image(
        self,
        prompt: str,
        word: Optional[str] = None
    ) -> ImageGenerationResult:
        """
        Generate an image from a text prompt.
        
        Args:
            prompt: Text prompt for image generation
            word: Optional word for logging/naming purposes
            
        Returns:
            ImageGenerationResult with image data or error
        """
        word = word or "unknown"
        start_time = time.time()
        self._stats["total_requests"] += 1
        
        if not self._ensure_client():
            return self._create_failure_result(word, prompt, "Failed to initialize image generation client", 0, 0)
        
        last_error = None
        for attempt in range(self.max_retries):
            result = self._attempt_image_generation(prompt, word, attempt, start_time)
            if result.success:
                return result
            last_error = result.error
            
            if attempt < self.max_retries - 1:
                logger.info(f"Retrying in {self.retry_delay}s...")
                time.sleep(self.retry_delay)
        
        return self._finalize_failure(word, prompt, last_error, start_time)

    def generate_image_preview(
        self,
        note: Note,
        prompt: str,
        image_field: str,
        word: Optional[str] = None
    ) -> PreviewResult:
        """
        Generate an image preview without saving to Anki media.
        Saves to a temporary file instead.
        
        Returns:
            PreviewResult containing path to temp file
        """
        word = word or "unknown"
        
        # Reuse existing generation logic
        result = self.generate_image(prompt, word)
        
        if not result.success:
             return PreviewResult(
                note_id=note.id,
                original_text=word,
                generated_content="Image Generation Failed",
                target_field=image_field,
                is_image=True,
                error=result.error
            )
            
        # Success - write to temp file
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tf.write(result.image_data)
                temp_path = tf.name
                
            return PreviewResult(
                note_id=note.id,
                original_text=word,
                generated_content="[Image Generated]",
                target_field=image_field,
                is_image=True,
                temp_image_path=temp_path
            )
        except Exception as e:
            return PreviewResult(
                note_id=note.id,
                original_text=word,
                generated_content="Error saving text file",
                target_field=image_field,
                is_image=True,
                error=f"File error: {str(e)}"
            )

    def _attempt_image_generation(
        self, prompt: str, word: str, attempt: int, start_time: float
    ) -> ImageGenerationResult:
        """Single attempt at image generation."""
        try:
            logger.info(f"Generating image for '{word}' (attempt {attempt + 1})")
            
            response = self._make_generation_request(prompt)
            image_data = self._extract_image_data(response)
            
            if not image_data:
                raise ImageGenerationError("No image data in response")
            
            return self._create_success_result(word, prompt, image_data, attempt, start_time)
            
        except Exception as e:
            self._handle_image_error(e)
            return self._create_failure_result(word, prompt, str(e), attempt, time.time() - start_time)
    
    def _create_success_result(
        self, word: str, prompt: str, image_data: bytes, attempt: int, start_time: float
    ) -> ImageGenerationResult:
        """Create a successful result."""
        generation_time = time.time() - start_time
        self._stats["successful"] += 1
        self._stats["total_generation_time"] += generation_time
        self.key_manager.record_success(operation="image")
        
        width, height = self._get_image_dimensions(image_data)
        logger.info(f"Image generated for '{word}' in {generation_time:.1f}s")
        
        return ImageGenerationResult(
            word=word, prompt=prompt, success=True, image_data=image_data,
            width=width, height=height, generation_time=generation_time, retry_count=attempt
        )
    
    def _create_failure_result(
        self, word: str, prompt: str, error: str, attempt: int, generation_time: float
    ) -> ImageGenerationResult:
        """Create a failure result."""
        return ImageGenerationResult(
            word=word, prompt=prompt, success=False, error=error,
            generation_time=generation_time, retry_count=attempt
        )
    
    def _handle_image_error(self, error: Exception) -> None:
        """Handle image generation error and potentially rotate keys."""
        error_type, error_msg = classify_error(error)
        logger.warning(f"Image generation failed: {error_type.value} - {error_msg}")
        
        # Use ErrorType enum for proper comparison (not strings)
        if error_type in (ErrorType.RATE_LIMIT, ErrorType.QUOTA_EXCEEDED, ErrorType.INVALID_KEY):
            rotated, new_key_id = self.key_manager.record_failure(str(error))
            if rotated:
                logger.info(f"Rotated to next API key: {new_key_id}")
                self._reinitialize_with_new_key()
    
    def _finalize_failure(
        self, word: str, prompt: str, last_error: Optional[str], start_time: float
    ) -> ImageGenerationResult:
        """Finalize after all attempts failed."""
        self._stats["failed"] += 1
        generation_time = time.time() - start_time
        return ImageGenerationResult(
            word=word, prompt=prompt, success=False, error=str(last_error),
            generation_time=generation_time, retry_count=self.max_retries
        )
    
    def _make_generation_request(self, prompt: str) -> Any:
        """Make the actual API request for image generation."""
        if self._legacy_mode:
            # Legacy SDK
            return self._client.generate_content(prompt)
        else:
            # New GenAI SDK
            return self._client.models.generate_content(
                model=self.IMAGE_MODEL,
                contents=[prompt]
            )
    
    def _extract_image_data(self, response: Any) -> Optional[bytes]:
        """Extract image bytes from API response."""
        try:
            if not hasattr(response, 'candidates') or not response.candidates:
                return None
            
            candidate = response.candidates[0]
            
            if not hasattr(candidate, 'content') or not candidate.content:
                return None
            
            if not hasattr(candidate.content, 'parts') or not candidate.content.parts:
                return None
            
            # Find image data in parts
            for part in candidate.content.parts:
                if hasattr(part, 'inline_data') and part.inline_data is not None:
                    if hasattr(part.inline_data, 'data') and part.inline_data.data:
                        return part.inline_data.data
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to extract image data: {e}")
            return None
    
    def _get_image_dimensions(self, image_data: bytes) -> tuple:
        """Get image dimensions using PIL if available."""
        try:
            from PIL import Image
            img = Image.open(BytesIO(image_data))
            return img.size
        except ImportError:
            logger.debug("PIL not available, skipping dimension extraction")
            return (None, None)
        except Exception as e:
            logger.warning(f"Failed to get image dimensions: {e}")
            return (None, None)
    
    def generate_image_for_word(
        self,
        word: str,
        prompt: str,
        output_dir: Optional[Union[str, Path]] = None
    ) -> ImageGenerationResult:
        """
        Generate and save an image for a specific word.
        
        Args:
            word: The vocabulary word
            prompt: Image generation prompt
            output_dir: Optional directory to save the image
            
        Returns:
            ImageGenerationResult with saved image path
        """
        result = self.generate_image(prompt, word)
        
        if result.success and result.image_data:
            # Save to file
            output_path = self._save_image(
                word=word,
                image_data=result.image_data,
                output_dir=output_dir
            )
            result.image_path = str(output_path) if output_path else None
        
        return result
    
    def _save_image(
        self,
        word: str,
        image_data: bytes,
        output_dir: Optional[Union[str, Path]] = None
    ) -> Optional[Path]:
        """Save image data to file."""
        try:
            # Default to temp directory if no output specified
            if output_dir is None:
                output_dir = Path(tempfile.gettempdir()) / "stella_anki_images"
            else:
                output_dir = Path(output_dir)
            
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Create filename: word_YYYYMMDD.png
            date_str = datetime.now().strftime("%Y%m%d")
            safe_word = "".join(c for c in word if c.isalnum() or c in "_-").lower()
            if len(safe_word) > 30:
                safe_word = safe_word[:30]
            
            base_name = f"{safe_word}_{date_str}"
            output_path = output_dir / f"{base_name}.png"
            
            # Handle duplicates
            counter = 2
            while output_path.exists():
                output_path = output_dir / f"{base_name}_{counter}.png"
                counter += 1
            
            # Save image
            output_path.write_bytes(image_data)
            logger.info(f"Image saved to {output_path}")
            
            return output_path
            
        except Exception as e:
            logger.error(f"Failed to save image: {e}")
            return None
    
    def generate_images_batch(
        self,
        prompts_data: List[Dict[str, str]],
        output_dir: Optional[Union[str, Path]] = None,
        progress_callback: Optional[callable] = None
    ) -> List[ImageGenerationResult]:
        """
        Generate multiple images with rate limiting.
        
        Args:
            prompts_data: List of dicts with 'word' and 'prompt' keys
            output_dir: Optional directory to save images
            progress_callback: Optional callback(current, total, word, success)
            
        Returns:
            List of ImageGenerationResult for each prompt
        """
        results = []
        total = len(prompts_data)
        
        logger.info(f"Starting batch image generation for {total} prompts")
        
        for i, data in enumerate(prompts_data):
            word = data.get("word", f"word_{i}")
            prompt = data.get("prompt", "")
            
            if not prompt:
                results.append(ImageGenerationResult(
                    word=word,
                    prompt="",
                    success=False,
                    error="Empty prompt"
                ))
                continue
            
            # Generate image
            result = self.generate_image_for_word(word, prompt, output_dir)
            results.append(result)
            
            # Progress callback
            if progress_callback:
                progress_callback(i + 1, total, word, result.success)
            
            logger.info(f"Batch progress: {i + 1}/{total} - '{word}' {'✓' if result.success else '✗'}")
            
            # Rate limiting between requests
            if i < total - 1:
                time.sleep(self.request_delay)
        
        successful = sum(1 for r in results if r.success)
        logger.info(f"Batch complete: {successful}/{total} successful")
        
        return results
    
    def resize_image_for_anki(
        self,
        image_data: bytes,
        max_width: int = 800,
        max_height: int = 600,
        quality: int = 85
    ) -> bytes:
        """
        Resize image for optimal Anki card display.
        
        Args:
            image_data: Original image bytes
            max_width: Maximum width in pixels
            max_height: Maximum height in pixels
            quality: Output quality (for JPEG)
            
        Returns:
            Resized image bytes (PNG format)
        """
        try:
            from PIL import Image
            
            img = Image.open(BytesIO(image_data))
            original_width, original_height = img.size
            
            # Check if resize is needed
            if original_width <= max_width and original_height <= max_height:
                return image_data
            
            # Calculate new dimensions
            width_ratio = max_width / original_width
            height_ratio = max_height / original_height
            scale = min(width_ratio, height_ratio)
            
            new_width = int(original_width * scale)
            new_height = int(original_height * scale)
            
            # Resize
            resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Save to bytes
            output = BytesIO()
            resized.save(output, format="PNG", optimize=True)
            
            logger.debug(f"Resized image from {original_width}x{original_height} to {new_width}x{new_height}")
            
            return output.getvalue()
            
        except ImportError:
            logger.warning("PIL not available, returning original image")
            return image_data
        except Exception as e:
            logger.error(f"Failed to resize image: {e}")
            return image_data
    
    def validate_image(self, image_data: bytes) -> Dict[str, Any]:
        """
        Validate image quality and dimensions.
        
        Args:
            image_data: Image bytes to validate
            
        Returns:
            Validation results dictionary
        """
        validation = {
            "valid": True,
            "readable": False,
            "dimensions": None,
            "file_size": len(image_data),
            "issues": []
        }
        
        try:
            from PIL import Image
            
            img = Image.open(BytesIO(image_data))
            validation["readable"] = True
            validation["dimensions"] = img.size
            
            width, height = img.size
            
            # Check dimensions
            if width < 256 or height < 256:
                validation["issues"].append(f"Image too small: {width}x{height}")
            
            if width > 2048 or height > 2048:
                validation["issues"].append(f"Image too large: {width}x{height}")
            
        except ImportError:
            validation["issues"].append("PIL not available for validation")
        except Exception as e:
            validation["readable"] = False
            validation["issues"].append(f"Cannot read image: {e}")
        
        # File size checks
        if validation["file_size"] < 1024:
            validation["issues"].append("File size too small (<1KB)")
        elif validation["file_size"] > 10 * 1024 * 1024:
            validation["issues"].append("File size too large (>10MB)")
        
        validation["valid"] = validation["readable"] and len(validation["issues"]) == 0
        
        return validation
    
    def get_stats(self) -> Dict[str, Any]:
        """Get generation statistics."""
        stats = dict(self._stats)
        
        if stats["total_requests"] > 0:
            stats["success_rate"] = stats["successful"] / stats["total_requests"]
            if stats["successful"] > 0:
                stats["avg_generation_time"] = stats["total_generation_time"] / stats["successful"]
        else:
            stats["success_rate"] = 0.0
            stats["avg_generation_time"] = 0.0
        
        stats["model"] = self.IMAGE_MODEL
        stats["legacy_mode"] = self._legacy_mode
        
        return stats
