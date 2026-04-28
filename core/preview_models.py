from dataclasses import dataclass
from typing import Optional, Any
import os

@dataclass
class PreviewResult:
    """Standardized result object for previewing generated content."""
    note_id: int
    original_text: str            # The source text used for generation
    generated_content: Any        # Text string or Image Path/Bytes
    target_field: str             # The field where content will be saved
    
    # Metadata for specific features
    secondary_content: Optional[str] = None  # e.g., Translation for Sentence mode
    secondary_field: Optional[str] = None    # Field for secondary content
    
    # Image specific
    is_image: bool = False
    temp_image_path: Optional[str] = None    # Path to temp file for preview
    
    # Error handling
    error: Optional[str] = None   # If validation/generation failed
    
    def cleanup(self):
        """Cleanup temp files if rejected."""
        if self.temp_image_path and os.path.exists(self.temp_image_path):
            try:
                os.remove(self.temp_image_path)
            except OSError:
                pass
