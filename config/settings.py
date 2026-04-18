# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Configuration Management

Provides centralized configuration for all modules:
- Load/save settings from Anki's addon config
- Type-safe access to settings
- Default values and validation
"""

from __future__ import annotations

import os
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict

# Constants for repeated literals
DEFAULT_MODEL = "gemini-2.5-flash"


@dataclass
class APIConfig:
    """API-related configuration."""
    keys: List[str] = field(default_factory=list)
    rotation_enabled: bool = True
    cooldown_hours: int = 24
    consecutive_failure_threshold: int = 5
    model: str = DEFAULT_MODEL
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "APIConfig":
        return cls(
            keys=data.get("keys", []),
            rotation_enabled=data.get("rotation_enabled", True),
            cooldown_hours=data.get("cooldown_hours", 24),
            consecutive_failure_threshold=data.get("consecutive_failure_threshold", 5),
            model=data.get("model", DEFAULT_MODEL),
        )


@dataclass
class TranslationConfig:
    """Translation module configuration."""
    enabled: bool = True
    language: str = "Korean"
    source_field: str = "Word"
    context_field: str = "Definition"
    destination_field: str = "Translation"
    batch_size: int = 5
    batch_delay_seconds: int = 8
    skip_existing: bool = True
    overwrite_existing: bool = False
    model_name: str = DEFAULT_MODEL
    
    @property
    def target_language(self) -> str:
        """Alias for language field for UI compatibility."""
        return self.language
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranslationConfig":
        return cls(
            enabled=data.get("enabled", True),
            language=data.get("language", data.get("target_language", "Korean")),
            source_field=data.get("source_field", "Word"),
            context_field=data.get("context_field", "Definition"),
            destination_field=data.get("destination_field", "Translation"),
            batch_size=data.get("batch_size", 5),
            batch_delay_seconds=data.get("batch_delay_seconds", 8),
            skip_existing=data.get("skip_existing", True),
            overwrite_existing=data.get("overwrite_existing", False),
            model_name=data.get("model_name", DEFAULT_MODEL),
        )


@dataclass
class ImageConfig:
    """Image generation module configuration."""
    enabled: bool = True
    word_field: str = "Word"
    image_field: str = "Image"
    style_preset: str = "anime"
    max_width: int = 800
    max_height: int = 600
    batch_size: int = 5
    request_delay_seconds: float = 2.0
    custom_prompts: Dict[str, str] = field(default_factory=dict)  # Custom style prompts

    @property
    def default_style(self) -> str:
        """Backward-compatible alias for style_preset."""
        return self.style_preset

    @default_style.setter
    def default_style(self, value: str) -> None:
        self.style_preset = value
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImageConfig":
        return cls(
            enabled=data.get("enabled", True),
            word_field=data.get("word_field", data.get("source_field", "Word")),
            image_field=data.get("image_field", data.get("destination_field", "Image")),
            style_preset=data.get("style_preset", data.get("default_style", "anime")),
            max_width=data.get("max_width", 800),
            max_height=data.get("max_height", 600),
            batch_size=data.get("batch_size", 5),
            request_delay_seconds=data.get("request_delay_seconds", 2.0),
            custom_prompts=data.get("custom_prompts", {}),
        )


@dataclass
class SentenceConfig:
    """Sentence generation module configuration.
    
    Attributes:
        target_language: The language for generated sentences (what user is learning).
                         Example: "Korean" if learning Korean vocabulary.
        translation_language: The user's native language for understanding sentences.
                              Example: "English" if user is an English speaker.
    """
    enabled: bool = True
    expression_field: str = "Word"
    sentence_field: str = "Sentence"
    translation_field: str = "SentenceTranslation"
    difficulty: str = "Normal"
    highlight_word: bool = True
    target_language: str = "Korean"
    translation_language: str = "English"  # User's native language for sentence translations
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SentenceConfig":
        return cls(
            enabled=data.get("enabled", True),
            expression_field=data.get("expression_field", "Word"),
            sentence_field=data.get("sentence_field", "Sentence"),
            translation_field=data.get("translation_field", "SentenceTranslation"),
            difficulty=data.get("difficulty", "Normal"),
            highlight_word=data.get("highlight_word", True),
            target_language=data.get("target_language", "Korean"),
            translation_language=data.get("translation_language", "English"),
        )


@dataclass
class EditorConfig:
    """Editor integration configuration."""
    buttons_enabled: bool = True
    auto_generate: bool = False
    auto_generate_field: str = ""
    auto_generate_feature: str = "translate"
    shortcuts: Dict[str, str] = field(default_factory=lambda: {
        "translate": "Ctrl+Shift+T",
        "sentence": "Ctrl+Shift+S",
        "image": "Ctrl+Shift+I",
        "all": "Ctrl+Shift+A",
    })
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EditorConfig":
        default_shortcuts = {
            "translate": "Ctrl+Shift+T",
            "sentence": "Ctrl+Shift+S",
            "image": "Ctrl+Shift+I",
            "all": "Ctrl+Shift+A",
        }
        return cls(
            buttons_enabled=data.get("buttons_enabled", True),
            auto_generate=data.get("auto_generate", False),
            auto_generate_field=data.get("auto_generate_field", ""),
            auto_generate_feature=data.get("auto_generate_feature", "translate"),
            shortcuts=data.get("shortcuts", default_shortcuts),
        )


@dataclass
class StellaConfig:
    """Complete configuration for Stella Anki Tools."""
    version: str = "1.0.0"
    api: APIConfig = field(default_factory=APIConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    image: ImageConfig = field(default_factory=ImageConfig)
    sentence: SentenceConfig = field(default_factory=SentenceConfig)
    editor: EditorConfig = field(default_factory=EditorConfig)
    deck: str = ""
    log_level: str = "INFO"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "version": self.version,
            "api": asdict(self.api),
            "translation": asdict(self.translation),
            "image": asdict(self.image),
            "sentence": asdict(self.sentence),
            "editor": asdict(self.editor),
            "deck": self.deck,
            "log_level": self.log_level,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StellaConfig":
        """Create configuration from dictionary."""
        return cls(
            version=data.get("version", "1.0.0"),
            api=APIConfig.from_dict(data.get("api", {})),
            translation=TranslationConfig.from_dict(data.get("translation", {})),
            image=ImageConfig.from_dict(data.get("image", {})),
            sentence=SentenceConfig.from_dict(data.get("sentence", {})),
            editor=EditorConfig.from_dict(data.get("editor", {})),
            deck=data.get("deck", ""),
            log_level=data.get("log_level", "INFO"),
        )


class ConfigManager:
    """
    Manages configuration loading, saving, and access.
    
    Uses Anki's addon configuration system when available,
    falls back to file-based config otherwise.
    """
    
    _instance: Optional["ConfigManager"] = None
    
    def __new__(cls) -> "ConfigManager":
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        
        self._config: Optional[StellaConfig] = None
        self._addon_dir: Optional[str] = None
        self._use_anki_config = False
    
    def initialize(self, addon_dir: str) -> None:
        """
        Initialize the config manager.
        
        Args:
            addon_dir: Path to the add-on directory
        """
        self._addon_dir = addon_dir
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from storage."""
        # Try Anki's config system first
        try:
            from aqt import mw
            if mw and mw.addonManager:
                # Get the addon module name from directory
                addon_name = os.path.basename(self._addon_dir)
                anki_config = mw.addonManager.getConfig(addon_name)
                if anki_config:
                    self._config = StellaConfig.from_dict(anki_config)
                    self._use_anki_config = True
                    return
        except ImportError:
            pass
        
        # Fall back to file-based config
        config_path = os.path.join(self._addon_dir, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._config = StellaConfig.from_dict(data)
                    return
            except Exception:
                pass
        
        # Use defaults
        self._config = StellaConfig()
    
    def save(self) -> None:
        """Save configuration to storage."""
        if self._config is None:
            return
        
        config_dict = self._config.to_dict()
        
        # Save to Anki config system
        if self._use_anki_config:
            try:
                from aqt import mw
                if mw and mw.addonManager:
                    addon_name = os.path.basename(self._addon_dir)
                    mw.addonManager.writeConfig(addon_name, config_dict)
                    return
            except ImportError:
                pass
        
        # Save to file
        config_path = os.path.join(self._addon_dir, "config.json")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_dict, f, indent=4, ensure_ascii=False)
        except Exception:
            pass  # Silent fail - config save not critical
    
    def reload(self) -> None:
        """Reload configuration from storage."""
        self._load_config()
    
    @property
    def config(self) -> StellaConfig:
        """Get the current configuration."""
        if self._config is None:
            self._config = StellaConfig()
        return self._config
    
    # Convenience accessors
    @property
    def api(self) -> APIConfig:
        return self.config.api
    
    @property
    def translation(self) -> TranslationConfig:
        return self.config.translation
    
    @property
    def image(self) -> ImageConfig:
        return self.config.image
    
    @property
    def sentence(self) -> SentenceConfig:
        return self.config.sentence
    
    @property
    def editor(self) -> EditorConfig:
        return self.config.editor
    
    def update_translation(self, **kwargs) -> None:
        """Update translation settings."""
        for key, value in kwargs.items():
            if hasattr(self.config.translation, key):
                setattr(self.config.translation, key, value)
        self.save()
    
    def update_image(self, **kwargs) -> None:
        """Update image settings."""
        for key, value in kwargs.items():
            if hasattr(self.config.image, key):
                setattr(self.config.image, key, value)
        self.save()
    
    def update_sentence(self, **kwargs) -> None:
        """Update sentence settings."""
        for key, value in kwargs.items():
            if hasattr(self.config.sentence, key):
                setattr(self.config.sentence, key, value)
        self.save()


# Global config manager instance
config_manager = ConfigManager()


def get_config() -> StellaConfig:
    """Get the current configuration."""
    return config_manager.config
