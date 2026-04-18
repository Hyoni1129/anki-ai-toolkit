# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Editor Integration

Provides editor buttons, shortcuts, and hooks for all features.
Adds unified UI elements to Anki's note editor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, List, Any, Tuple
import os

if TYPE_CHECKING:
    from aqt.editor import Editor
    from aqt.webview import AnkiWebView
    from anki.notes import Note

from ..core.logger import get_logger
from ..config.settings import ConfigManager


logger = get_logger(__name__)


# Package name for Anki config (extract root package name)
ADDON_NAME = __name__.split('.')[0]


class EditorIntegration:
    """
    Handles Anki editor integration for Stella features.
    
    Provides:
    - Editor toolbar buttons
    - Keyboard shortcuts (Ctrl+Shift+T/S/I)
    - Auto-generation on field change (optional)
    - WebView message handling
    """
    
    _instance: Optional['EditorIntegration'] = None
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize editor integration."""
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self._addon_dir = os.path.dirname(os.path.dirname(__file__))
        self._config_manager = ConfigManager()
        self._config_manager.initialize(self._addon_dir)
        self._hooks_registered = False
        self._initialized = True
        
        logger.info("EditorIntegration initialized")
    
    @property
    def config(self):
        """Get editor configuration."""
        return self._config_manager.config.editor
    
    def setup_hooks(self) -> None:
        """Register all editor hooks."""
        if self._hooks_registered:
            return
        
        try:
            from aqt import gui_hooks
            
            # Editor shortcuts
            gui_hooks.editor_did_init_shortcuts.append(self._on_editor_shortcuts)
            
            # Editor webview initialization (for buttons)
            gui_hooks.editor_web_view_did_init.append(self._on_editor_web_init)
            
            # WebView message handling
            gui_hooks.webview_did_receive_js_message.append(self._on_webview_message)
            
            # Field change (for auto-generation)
            gui_hooks.editor_did_unfocus_field.append(self._on_field_unfocus)
            
            self._hooks_registered = True
            logger.info("Editor hooks registered (2025 API)")
            
        except (ImportError, AttributeError) as e:
            logger.warning(f"Modern hooks unavailable: {e}, trying legacy")
            self._setup_legacy_hooks()
    
    def _setup_legacy_hooks(self) -> None:
        """Set up legacy hooks for older Anki versions."""
        try:
            from aqt.hooks import addHook
            
            addHook("setupEditorShortcuts", self._on_editor_shortcuts_legacy)
            addHook("editFocusLost", self._on_field_unfocus_legacy)
            
            self._hooks_registered = True
            logger.info("Legacy editor hooks registered")
            
        except ImportError as e:
            logger.error(f"Could not register hooks: {e}")
    
    # ========== Hook Handlers ==========
    
    def _on_editor_shortcuts(self, shortcuts: List, editor: 'Editor') -> None:
        """Add keyboard shortcuts to editor (2025 API)."""
        try:
            if not self._has_api_key():
                return
            
            # Ctrl+Shift+T: Translate
            shortcuts.append((
                "Ctrl+Shift+T",
                lambda: self.translate_current_note(editor)
            ))
            
            # Ctrl+Shift+S: Generate sentence
            shortcuts.append((
                "Ctrl+Shift+S",
                lambda: self.generate_sentence_current_note(editor)
            ))
            
            # Ctrl+Shift+I: Generate image
            shortcuts.append((
                "Ctrl+Shift+I",
                lambda: self.generate_image_current_note(editor)
            ))
            
            logger.debug("Editor shortcuts added (T=Translate, S=Sentence, I=Image)")
            
        except Exception as e:
            logger.error(f"Error adding shortcuts: {e}")
    
    def _on_editor_shortcuts_legacy(self, shortcuts: List, editor: 'Editor') -> None:
        """Legacy shortcut handler."""
        self._on_editor_shortcuts(shortcuts, editor)
    
    def _on_editor_web_init(self, editor_web_view: 'AnkiWebView') -> None:
        """Add buttons when editor webview initializes."""
        try:
            if not self._has_api_key():
                return
            
            self._inject_editor_buttons(editor_web_view)
            
        except Exception as e:
            logger.error(f"Error on editor web init: {e}")
    
    def _on_webview_message(
        self,
        handled: Tuple[bool, Any],
        message: str,
        context: Any
    ) -> Tuple[bool, Any]:
        """Handle JavaScript messages from editor buttons."""
        try:
            # Check if this is a Stella message
            if not message.startswith("stella_"):
                return handled
            
            # Find the editor from context
            editor = self._get_editor_from_context(context)
            if not editor:
                logger.warning(f"Could not find editor for message: {message}")
                return handled
            
            # Handle different actions
            if message == "stella_translate":
                self.translate_current_note(editor)
                return (True, None)
            
            elif message == "stella_sentence":
                self.generate_sentence_current_note(editor)
                return (True, None)
            
            elif message == "stella_image":
                self.generate_image_current_note(editor)
                return (True, None)
            
            elif message == "stella_menu":
                self._show_quick_menu(editor)
                return (True, None)
            
        except Exception as e:
            logger.error(f"Error handling webview message '{message}': {e}")
        
        return handled
    
    def _on_field_unfocus(
        self,
        changed: bool,
        note: 'Note',
        current_field_idx: int
    ) -> bool:
        """
        Handle field unfocus for auto-generation.
        
        Note: This method intentionally always returns `changed` as-is per Anki's
        hook contract. The hook is used for side effects (auto-generation),
        not to modify the changed state. This is correct behavior, not a bug.
        (SonarQube S3516 - expected for pass-through hook pattern)
        
        Args:
            changed: Whether the field content changed (passed through unchanged)
            note: The current note being edited
            current_field_idx: Index of the field that lost focus
            
        Returns:
            The original `changed` value (required by Anki hook contract)
        """
        try:
            # Check if auto-generation is enabled
            if not self.config.auto_generate:
                return changed
            
            if not self._has_api_key():
                return changed
            
            if not note:
                return changed
            
            # Get configuration for auto-generation field
            auto_field = self.config.auto_generate_field
            if not auto_field:
                return changed
            
            # Check if the unfocused field matches
            fields = list(note.keys())
            if current_field_idx >= len(fields):
                return changed
            
            current_field = fields[current_field_idx]
            if current_field != auto_field:
                return changed
            
            # Trigger auto-generation based on configured feature
            auto_feature = self.config.auto_generate_feature
            if auto_feature == "translate":
                self._auto_translate(note, current_field_idx)
            elif auto_feature == "sentence":
                self._auto_sentence(note, current_field_idx)
            
        except Exception as e:
            logger.error(f"Error on field unfocus: {e}")
        
        return changed
    
    def _on_field_unfocus_legacy(
        self,
        flag: bool,
        note: 'Note',
        field_idx: int
    ) -> bool:
        """Legacy field unfocus handler."""
        return self._on_field_unfocus(flag, note, field_idx)
    
    # ========== Feature Actions ==========
    
    def translate_current_note(self, editor: 'Editor') -> None:
        """Translate the current note."""
        try:
            if not editor.note:
                return
            
            from ..translation.translator import Translator
            from aqt import mw
            
            translator = Translator()

            config = self._config_manager.config.translation

            def on_error(err: str) -> None:
                logger.error(f"Translation failed: {err}")
                from aqt.utils import showWarning
                showWarning(f"Translation failed: {err}")

            translator.translate_note_async(
                parent_widget=mw,
                note=editor.note,
                source_field=config.source_field,
                context_field=config.context_field,
                destination_field=config.destination_field,
                target_language=config.language,
                model_name=config.model_name,
                success_callback=lambda: editor.loadNote(),
                error_callback=on_error,
            )
            
        except Exception as e:
            logger.error(f"Translation error: {e}")
            from aqt.utils import showWarning
            showWarning(f"Translation error: {e}")
    
    def generate_sentence_current_note(self, editor: 'Editor') -> None:
        """Generate sentence for current note."""
        try:
            if not editor.note:
                return
            
            from ..sentence.sentence_generator import SentenceGenerator
            from aqt import mw
            
            generator = SentenceGenerator()

            config = self._config_manager.config.sentence

            def on_error(err: str) -> None:
                logger.error(f"Sentence generation failed: {err}")
                from aqt.utils import showWarning
                showWarning(f"Sentence generation failed: {err}")

            generator.generate_sentence_async(
                parent_widget=mw,
                note=editor.note,
                expression_field=config.expression_field,
                sentence_field=config.sentence_field,
                translation_field=config.translation_field,
                target_language=config.target_language,
                difficulty=config.difficulty,
                highlight=config.highlight_word,
                model_name=getattr(config, "model_name", "gemini-2.5-flash"),
                success_callback=lambda: editor.loadNote(),
                error_callback=on_error,
            )
            
        except Exception as e:
            logger.error(f"Sentence generation error: {e}")
            from aqt.utils import showWarning
            showWarning(f"Sentence generation error: {e}")
    
    def generate_image_current_note(self, editor: 'Editor') -> None:
        """Generate image for current note."""
        try:
            if not editor.note:
                return
            
            from ..image.prompt_generator import ImagePromptGenerator
            from ..image.image_generator import ImageGenerator
            from ..image.anki_media import AnkiMediaManager
            from aqt.operations import QueryOp
            from aqt import mw
            
            prompt_gen = ImagePromptGenerator()
            image_gen = ImageGenerator()
            media_mgr = AnkiMediaManager()
            
            # Get word from configured field
            config = self._config_manager.config.image
            word_field = config.word_field
            image_field = config.image_field
            
            note = editor.note
            
            if word_field not in note:
                from aqt.utils import showWarning
                showWarning(f"Field '{word_field}' not found in note")
                return
            
            word = note[word_field]
            if not word.strip():
                from aqt.utils import showWarning
                showWarning(f"Field '{word_field}' is empty")
                return
            
            def do_generate() -> dict:
                try:
                    # Generate prompt
                    prompt_result = prompt_gen.generate_prompt(word)
                    if not prompt_result.success:
                        return {"success": False, "error": prompt_result.error}
                    
                    # Generate image
                    image_result = image_gen.generate_image(
                        prompt_result.prompt,
                        word
                    )
                    if not image_result.success:
                        return {"success": False, "error": image_result.error}
                    
                    # Add to Anki media
                    media_result = media_mgr.add_image_to_note(
                        note=note,
                        field_name=image_field,
                        image_data=image_result.image_data,
                        word=word
                    )
                    
                    return {
                        "success": media_result.success,
                        "filename": media_result.filename,
                        "error": media_result.error
                    }
                    
                except Exception as e:
                    return {"success": False, "error": str(e)}
            
            def on_success(result: dict) -> None:
                if result.get("success"):
                    editor.loadNote()
                    logger.info(f"Image added: {result.get('filename')}")
                else:
                    from aqt.utils import showWarning
                    showWarning(f"Image generation failed: {result.get('error')}")
            
            op = QueryOp(
                parent=mw,
                op=lambda col: do_generate(),
                success=on_success
            )
            op.with_progress("Generating image...").run_in_background()
            
        except Exception as e:
            logger.error(f"Image generation error: {e}")
            from aqt.utils import showWarning
            showWarning(f"Image generation error: {e}")
    
    # ========== Helper Methods ==========
    
    def _has_api_key(self) -> bool:
        """Check if API key is configured."""
        try:
            from ..core.api_key_manager import APIKeyManager
            manager = APIKeyManager(self._addon_dir)
            return manager.get_current_key() is not None
        except Exception:
            return False
    
    def _get_editor_from_context(self, context: Any) -> Optional['Editor']:
        """Extract Editor instance from hook context."""
        # Direct editor
        if hasattr(context, 'note') and hasattr(context, 'web'):
            return context
        
        # Has editor attribute
        if hasattr(context, 'editor'):
            return context.editor
        
        # Try to find from Anki main window
        try:
            from aqt import mw
            if mw and hasattr(mw, 'app'):
                active = mw.app.activeWindow()
                if hasattr(active, 'editor'):
                    return active.editor
        except Exception:
            pass
        
        return None
    
    def _inject_editor_buttons(self, editor_web_view: 'AnkiWebView') -> None:
        """Inject Stella buttons into editor toolbar via JavaScript."""
        js_code = """
        (function() {
            // Prevent duplicate injection
            if (document.getElementById('stella-toolbar')) return;
            
            // Create Stella toolbar container
            const toolbar = document.createElement('div');
            toolbar.id = 'stella-toolbar';
            toolbar.style.cssText = `
                display: flex;
                gap: 4px;
                padding: 4px;
                align-items: center;
            `;
            
            // Button factory
            function createButton(id, emoji, title, command) {
                const btn = document.createElement('button');
                btn.id = id;
                btn.innerHTML = emoji;
                btn.title = title;
                btn.className = 'btn btn-sm';
                btn.style.cssText = `
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    padding: 4px 8px;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 14px;
                    transition: all 0.2s ease;
                    min-width: 32px;
                `;
                btn.onmouseover = function() {
                    this.style.transform = 'scale(1.05)';
                    this.style.opacity = '0.9';
                };
                btn.onmouseout = function() {
                    this.style.transform = 'scale(1)';
                    this.style.opacity = '1';
                };
                btn.onclick = function() {
                    if (typeof pycmd !== 'undefined') {
                        pycmd(command);
                    }
                };
                return btn;
            }
            
            // Create buttons
            toolbar.appendChild(createButton(
                'stella-btn-translate', '🌐', 
                'Translate (Ctrl+Shift+T)', 'stella_translate'
            ));
            toolbar.appendChild(createButton(
                'stella-btn-sentence', '✏️',
                'Generate Sentence (Ctrl+Shift+S)', 'stella_sentence'
            ));
            toolbar.appendChild(createButton(
                'stella-btn-image', '🖼️',
                'Generate Image (Ctrl+Shift+I)', 'stella_image'
            ));
            
            // Add separator and menu button
            const sep = document.createElement('span');
            sep.style.cssText = 'width: 1px; height: 20px; background: #ccc; margin: 0 4px;';
            toolbar.appendChild(sep);
            
            toolbar.appendChild(createButton(
                'stella-btn-menu', '⚙️',
                'Stella Menu', 'stella_menu'
            ));
            
            // Find insertion point
            const editorToolbar = document.querySelector('.editor-toolbar') ||
                                 document.querySelector('.topbar') ||
                                 document.querySelector('[class*="toolbar"]');
            
            if (editorToolbar) {
                editorToolbar.appendChild(toolbar);
            } else {
                // Fallback: prepend to body
                document.body.insertBefore(toolbar, document.body.firstChild);
            }
        })();
        """
        
        try:
            if hasattr(editor_web_view, 'eval'):
                editor_web_view.eval(js_code)
            elif hasattr(editor_web_view, 'web') and hasattr(editor_web_view.web, 'eval'):
                editor_web_view.web.eval(js_code)
        except Exception as e:
            logger.error(f"Failed to inject editor buttons: {e}")
    
    def _show_quick_menu(self, editor: 'Editor') -> None:
        """Show quick access menu."""
        try:
            from aqt.qt import QMenu, QCursor
            from aqt import mw
            
            menu = QMenu(mw)
            
            menu.addAction("🌐 Translate Note", lambda: self.translate_current_note(editor))
            menu.addAction("✏️ Generate Sentence", lambda: self.generate_sentence_current_note(editor))
            menu.addAction("🖼️ Generate Image", lambda: self.generate_image_current_note(editor))
            menu.addSeparator()
            menu.addAction("⚙️ Settings...", self._open_settings)
            
            menu.exec(QCursor.pos())
            
        except Exception as e:
            logger.error(f"Failed to show quick menu: {e}")
    
    def _open_settings(self) -> None:
        """Open settings dialog."""
        try:
            from .main_controller import get_controller
            controller = get_controller()
            controller.show_settings_dialog()
        except Exception as e:
            logger.error(f"Failed to open settings: {e}")
    
    def _auto_translate(self, _note: 'Note', field_idx: int) -> None:
        """Auto-translate after field change."""
        # Implementation would queue translation
        logger.debug(f"Auto-translate triggered for field {field_idx}")
    
    def _auto_sentence(self, _note: 'Note', field_idx: int) -> None:
        """Auto-generate sentence after field change."""
        logger.debug(f"Auto-sentence triggered for field {field_idx}")


# Module-level singleton
_integration: Optional[EditorIntegration] = None


def get_editor_integration() -> EditorIntegration:
    """Get editor integration singleton."""
    global _integration
    if _integration is None:
        _integration = EditorIntegration()
    return _integration


def setup_editor_integration() -> EditorIntegration:
    """Initialize and set up editor integration."""
    integration = get_editor_integration()
    integration.setup_hooks()
    return integration
