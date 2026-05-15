# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Settings Dialog & Deck Operations

Provides:
- DeckOperationDialog: Main dialog for deck-based batch operations
- StellaSettingsDialog: Configuration dialog
- APIKeyDialog: API key management
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, List, Dict, Any, Set
import os
import threading
import time

if TYPE_CHECKING:
    from aqt.main import AnkiQt
    from ..config.settings import ConfigManager

from aqt import mw
from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QComboBox, QPushButton, QCheckBox, QSpinBox,
    QProgressBar, QGroupBox, QTextEdit, QMessageBox,
    QThreadPool, Qt, QSizePolicy
)
from aqt.utils import showInfo, showWarning, askUser

from ..core.logger import get_logger
from ..core.api_key_manager import get_api_key_manager
from ..core.job_history import JobHistoryManager
from ..core.preview_models import PreviewResult
from ..config.settings import ConfigManager
from ..sentence.progress_state import ProgressStateManager

logger = get_logger(__name__)

# UI Style Constants
STYLE_HEADER = "font-weight: bold; font-size: 14px;"
STYLE_PRIMARY_BTN = "font-weight: bold; padding: 8px;"
STYLE_STOP_BTN = "background-color: #ff6b6b; color: white;"
STYLE_PAUSE_BTN = "background-color: #ffc107; color: black;"
STYLE_PROMPT_EDIT = "font-family: monospace; font-size: 11px;"
STYLE_PROMPT_EDIT_CUSTOM = "font-family: monospace; font-size: 11px; background-color: #fffae6;"

# UI Text Constants
TEXT_PAUSE = "⏸ Pause"
TEXT_STOP = "⏹ Stop"
TEXT_FIELD_MAPPING = "Field Mapping"
TEXT_NONE_OPTION = "(None)"


def format_eta(seconds: float) -> str:
    """Format seconds to human readable ETA string."""
    if seconds <= 0:
        return "calculating..."
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


class DeckOperationDialog(QDialog):
    """
    Main dialog for deck-based batch operations.
    
    Allows users to:
    - Select a deck directly (no browser required)
    - Configure field mappings
    - Run batch translation, sentence, or image generation
    - Monitor progress in real-time with ETA
    - Pause/resume operations
    - Resume interrupted batches
    """
    
    def __init__(self, parent: 'AnkiQt'):
        super().__init__(parent)
        self._mw = parent
        self._addon_dir = os.path.dirname(os.path.dirname(__file__))
        self._config_manager = ConfigManager()
        self._config_manager.initialize(self._addon_dir)
        self._key_manager = get_api_key_manager(self._addon_dir)
        self._thread_pool = QThreadPool.globalInstance()
        self._progress_manager = ProgressStateManager(self._addon_dir, operation="deck")
        self._history_manager = JobHistoryManager(self._addon_dir)
        
        # Current state
        self._current_deck = ""
        self._current_deck_id: Optional[int] = None  # Track deck ID for progress operations
        self._pending_deck_id: Optional[int] = None  # Track deck with pending operations to resume
        self._active_job_id: Optional[str] = None
        self._active_job_operation: Optional[str] = None
        self._suppress_deck_warnings = False
        self._updating_field_dropdowns = False
        self._current_fields: List[str] = []
        self._active_worker = None
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()  # New: for pause functionality
        
        # ETA tracking
        self._start_time: float = 0
        self._items_processed: int = 0
        self._total_items: int = 0
        
        # UI elements
        self._deck_dropdown: Optional[QComboBox] = None
        self._source_dropdown: Optional[QComboBox] = None
        self._context_dropdown: Optional[QComboBox] = None
        self._dest_dropdown: Optional[QComboBox] = None
        self._sentence_word_dropdown: Optional[QComboBox] = None
        self._sentence_field_dropdown: Optional[QComboBox] = None
        self._sentence_trans_dropdown: Optional[QComboBox] = None
        self._image_word_dropdown: Optional[QComboBox] = None
        self._image_field_dropdown: Optional[QComboBox] = None
        self._language_dropdown: Optional[QComboBox] = None
        self._model_dropdown: Optional[QComboBox] = None
        self._style_dropdown: Optional[QComboBox] = None
        self._history_job_dropdown: Optional[QComboBox] = None
        self._history_detail_text: Optional[QTextEdit] = None
        self._history_overwrite_cb: Optional[QCheckBox] = None
        self._prompt_edit: Optional[QTextEdit] = None
        self._batch_size_spin: Optional[QSpinBox] = None
        self._delay_spin: Optional[QSpinBox] = None
        self._progress_bar: Optional[QProgressBar] = None
        self._progress_label: Optional[QLabel] = None
        self._status_label: Optional[QLabel] = None
        self._eta_label: Optional[QLabel] = None
        self._error_log: Optional[QTextEdit] = None
        
        # Stats
        self._success_count = 0
        self._failure_count = 0
        
        logger.info("DeckOperationDialog __init__: calling _setup_ui...")
        self._setup_ui()
        logger.info("DeckOperationDialog __init__: _setup_ui completed, calling _load_decks...")
        self._load_decks()
        self._refresh_history_jobs()
        self._check_pending_operations()
        logger.info("DeckOperationDialog initialized")
    
    def _check_pending_operations(self) -> None:
        """Check for interrupted operations that can be resumed."""
        # Get all pending runs across all decks
        all_runs = self._progress_manager.get_all_runs()
        if not all_runs:
            return
        
        # Find the first deck with pending operations
        for deck_id, run_info in all_runs.items():
            pending_count = run_info.get('pending_count', 0)
            if pending_count > 0:
                self._pending_deck_id = deck_id
                
                if askUser(
                    f"Found interrupted operation:\n\n"
                    f"Deck: {run_info.get('deck_name', 'unknown')}\n"
                    f"Type: {run_info.get('operation', 'unknown')}\n"
                    f"Started: {run_info.get('started_at', 'unknown')}\n"
                    f"Pending items: {pending_count}\n\n"
                    f"Would you like to resume?"
                ):
                    self._resume_pending_operation()
                else:
                    if askUser("Clear this interrupted operation?"):
                        self._progress_manager.clear_run(deck_id)
                break  # Handle one pending operation at a time
    
    def _resume_pending_operation(self) -> None:
        """Resume an interrupted operation."""
        if self._pending_deck_id is None:
            showInfo("No pending operation found.")
            return
        
        run_info = self._progress_manager.describe_run(self._pending_deck_id)
        pending_ids = self._progress_manager.get_pending_note_ids(self._pending_deck_id)
        
        if not pending_ids or not run_info:
            showInfo("No pending items to process.")
            return
        
        # Get the stored run info
        run_type = run_info.get("operation", "")
        
        if run_type == "sentence":
            self._resume_sentence_batch(pending_ids, run_info)
        elif run_type == "image":
            self._resume_image_batch(pending_ids, run_info)
        elif run_type == "translation":
            showInfo("Translation resume not yet implemented.")
        else:
            showWarning(f"Unknown operation type: {run_type}")
    
    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        self.setWindowTitle("Stella Anki Tools - Deck Operations")
        self.setMinimumWidth(550)
        self.setMinimumHeight(700)
        
        layout = QVBoxLayout(self)
        
        # Shared Deck Selection (visible across all tabs)
        deck_group = QGroupBox("Select Deck")
        deck_group_layout = QHBoxLayout(deck_group)
        deck_group_layout.addWidget(QLabel("Deck:"))
        self._deck_dropdown = QComboBox()
        deck_group_layout.addWidget(self._deck_dropdown, 1)
        layout.addWidget(deck_group)
        
        # Create tab widget
        tab_widget = QTabWidget()
        
        # Translation Tab
        translation_tab = self._create_translation_tab()
        tab_widget.addTab(translation_tab, "🌐 Translation")
        
        # Sentence Tab
        sentence_tab = self._create_sentence_tab()
        tab_widget.addTab(sentence_tab, "✏️ Sentences")
        
        # Image Tab
        image_tab = self._create_image_tab()
        tab_widget.addTab(image_tab, "🖼️ Images")

        # History Tab
        history_tab = self._create_history_tab()
        tab_widget.addTab(history_tab, "🗂 History")
        
        # Settings Tab
        settings_tab = self._create_settings_tab()
        tab_widget.addTab(settings_tab, "⚙️ Settings")
        
        layout.addWidget(tab_widget)
        
        # Progress section (shared)
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)
        
        # Status and ETA row
        status_row = QHBoxLayout()
        self._status_label = QLabel("Ready")
        status_row.addWidget(self._status_label, 1)
        self._eta_label = QLabel("ETA: --")
        self._eta_label.setStyleSheet("color: #666;")
        status_row.addWidget(self._eta_label)
        progress_layout.addLayout(status_row)
        
        # API Key status row
        api_key_row = QHBoxLayout()
        self._api_key_status_label = QLabel("🔑 API Key: --")
        self._api_key_status_label.setStyleSheet("color: #888; font-size: 11px;")
        api_key_row.addWidget(self._api_key_status_label)
        api_key_row.addStretch()
        progress_layout.addLayout(api_key_row)
        
        # Update initial key status
        self._update_api_key_status()
        
        progress_row = QHBoxLayout()
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(True)
        progress_row.addWidget(self._progress_bar)
        self._progress_label = QLabel("0 / 0")
        progress_row.addWidget(self._progress_label)
        progress_layout.addLayout(progress_row)
        
        # Control buttons row
        control_row = QHBoxLayout()
        self._pause_btn = QPushButton(TEXT_PAUSE)
        self._pause_btn.setStyleSheet(STYLE_PAUSE_BTN)
        self._pause_btn.setEnabled(False)
        self._pause_btn.clicked.connect(self._toggle_pause)
        control_row.addWidget(self._pause_btn)
        
        self._global_stop_btn = QPushButton("⏹ Stop All")
        self._global_stop_btn.setStyleSheet("background-color: #dc3545; color: white;")
        self._global_stop_btn.setEnabled(False)
        self._global_stop_btn.clicked.connect(self._stop_operation)
        control_row.addWidget(self._global_stop_btn)
        
        control_row.addStretch()
        progress_layout.addLayout(control_row)
        
        # Error log (collapsible)
        self._error_log = QTextEdit()
        self._error_log.setReadOnly(True)
        self._error_log.setMaximumHeight(80)
        self._error_log.setPlaceholderText("Errors will appear here...")
        self._error_log.hide()
        progress_layout.addWidget(self._error_log)
        
        layout.addWidget(progress_group)
        
        # Bottom buttons
        button_row = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_row.addStretch()
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)
        
        # Connect deck change signal now that all tabs/widgets are created
        self._deck_dropdown.currentTextChanged.connect(self._on_deck_changed)

        # Persist field mappings on user changes
        field_dropdowns = [
            self._source_dropdown,
            self._context_dropdown,
            self._dest_dropdown,
            self._sentence_word_dropdown,
            self._sentence_field_dropdown,
            self._sentence_trans_dropdown,
            self._image_word_dropdown,
            self._image_field_dropdown,
        ]
        for dropdown in field_dropdowns:
            if dropdown is not None:
                dropdown.currentTextChanged.connect(self._on_field_mapping_changed)
        
        # Debug: Verify all dropdowns are created at end of _setup_ui
        logger.info(f"_setup_ui complete. Dropdown status: "
                    f"source={self._source_dropdown is not None}, "
                    f"context={self._context_dropdown is not None}, "
                    f"dest={self._dest_dropdown is not None}, "
                    f"sentence_word={self._sentence_word_dropdown is not None}, "
                    f"image_word={self._image_word_dropdown is not None}")
    
    def _create_translation_tab(self) -> QWidget:
        """Create the translation tab."""
        logger.info("Creating translation tab...")
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Header
        header = QLabel("Batch Translation")
        header.setStyleSheet(STYLE_HEADER)
        layout.addWidget(header)
        
        # Field mappings
        fields_group = QGroupBox(TEXT_FIELD_MAPPING)
        fields_layout = QVBoxLayout(fields_group)
        
        # Source field
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source Field (Word):"))
        self._source_dropdown = QComboBox()
        self._source_dropdown.setEnabled(False)
        source_row.addWidget(self._source_dropdown, 1)
        fields_layout.addLayout(source_row)
        
        # Context field
        context_row = QHBoxLayout()
        context_row.addWidget(QLabel("Context Field (Optional):"))
        self._context_dropdown = QComboBox()
        self._context_dropdown.setEnabled(False)
        context_row.addWidget(self._context_dropdown, 1)
        fields_layout.addLayout(context_row)
        
        # Destination field
        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Destination Field:"))
        self._dest_dropdown = QComboBox()
        self._dest_dropdown.setEnabled(False)
        dest_row.addWidget(self._dest_dropdown, 1)
        fields_layout.addLayout(dest_row)
        
        layout.addWidget(fields_group)
        
        # Debug: Confirm dropdowns were created
        logger.info(f"Translation tab dropdowns created: source={self._source_dropdown is not None}, "
                    f"context={self._context_dropdown is not None}, dest={self._dest_dropdown is not None}")
        
        # Options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        
        # Language
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Target Language:"))
        self._language_dropdown = QComboBox()
        self._language_dropdown.setEditable(True)
        self._language_dropdown.addItems([
            "Korean", "Japanese", "Chinese (Simplified)", "Chinese (Traditional)",
            "Spanish", "French", "German", "Italian", "Portuguese", "Russian",
            "Vietnamese", "Thai", "Indonesian", "Arabic", "Hindi"
        ])
        self._language_dropdown.setCurrentText(
            self._config_manager.config.translation.target_language
        )
        lang_row.addWidget(self._language_dropdown, 1)
        options_layout.addLayout(lang_row)
        
        # Model
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self._model_dropdown = QComboBox()
        self._model_dropdown.setEditable(True)
        self._model_dropdown.addItems([
            "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"
        ])
        self._model_dropdown.setCurrentText(
            self._config_manager.config.translation.model_name
        )
        model_row.addWidget(self._model_dropdown, 1)
        options_layout.addLayout(model_row)
        
        # Checkboxes
        self._overwrite_cb = QCheckBox("Overwrite existing translations")
        self._overwrite_cb.setChecked(self._config_manager.config.translation.overwrite_existing)
        options_layout.addWidget(self._overwrite_cb)
        
        self._skip_existing_cb = QCheckBox("Skip cards with existing translation")
        self._skip_existing_cb.setChecked(True)
        options_layout.addWidget(self._skip_existing_cb)
        
        layout.addWidget(options_group)
        
        # Batch settings
        batch_group = QGroupBox("Batch Settings")
        batch_layout = QHBoxLayout(batch_group)
        
        batch_layout.addWidget(QLabel("Batch Size:"))
        self._batch_size_spin = QSpinBox()
        self._batch_size_spin.setRange(1, 30)
        self._batch_size_spin.setValue(self._config_manager.config.translation.batch_size)
        batch_layout.addWidget(self._batch_size_spin)
        
        batch_layout.addWidget(QLabel("Delay (sec):"))
        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(1, 60)
        self._delay_spin.setValue(int(self._config_manager.config.translation.batch_delay_seconds))
        batch_layout.addWidget(self._delay_spin)
        
        batch_layout.addStretch()
        layout.addWidget(batch_group)
        
        # Action buttons
        button_row = QHBoxLayout()
        
        self._translate_preview_btn = QPushButton("🧪 Preview (3)")
        self._translate_preview_btn.setToolTip("Test translation on 3 random cards")
        self._translate_preview_btn.clicked.connect(lambda: self._run_preview("translation"))
        button_row.addWidget(self._translate_preview_btn)

        self._translate_btn = QPushButton("▶ Start Translation")
        self._translate_btn.setStyleSheet(STYLE_PRIMARY_BTN)
        self._translate_btn.clicked.connect(self._start_translation)
        button_row.addWidget(self._translate_btn)
        
        layout.addLayout(button_row)
        layout.addStretch()
        
        return tab
    
    def _create_sentence_tab(self) -> QWidget:
        """Create the sentence generation tab."""
        logger.info("Creating sentence tab...")
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        header = QLabel("Batch Sentence Generation")
        header.setStyleSheet(STYLE_HEADER)
        layout.addWidget(header)
        
        info = QLabel("Generates example sentences for vocabulary cards using AI.")
        info.setStyleSheet("color: gray;")
        layout.addWidget(info)
        
        # Field mappings with descriptions
        fields_group = QGroupBox(TEXT_FIELD_MAPPING)
        fields_layout = QVBoxLayout(fields_group)
        
        # Help text for field mapping
        field_help = QLabel(
            "💡 <b>Word Field:</b> The vocabulary word to create a sentence for.<br>"
            "<b>Sentence Field:</b> Where the generated sentence will be saved.<br>"
            "<b>Translation Field:</b> Where the sentence translation will be saved."
        )
        field_help.setStyleSheet("color: #555; font-size: 11px; padding: 4px; background-color: #f5f5f5; border-radius: 4px;")
        field_help.setWordWrap(True)
        fields_layout.addWidget(field_help)
        
        # Expression field (word)
        expr_row = QHBoxLayout()
        word_label = QLabel("Word Field:")
        word_label.setToolTip("Select the field containing the vocabulary word.")
        expr_row.addWidget(word_label)
        self._sentence_word_dropdown = QComboBox()
        self._sentence_word_dropdown.setEnabled(False)
        self._sentence_word_dropdown.setToolTip("The field containing vocabulary words to use in sentences.")
        expr_row.addWidget(self._sentence_word_dropdown, 1)
        fields_layout.addLayout(expr_row)
        
        # Sentence field
        sent_row = QHBoxLayout()
        sent_label = QLabel("Sentence Field:")
        sent_label.setToolTip("Select the field where the generated sentence will be saved.")
        sent_row.addWidget(sent_label)
        self._sentence_field_dropdown = QComboBox()
        self._sentence_field_dropdown.setEnabled(False)
        self._sentence_field_dropdown.setToolTip("The AI-generated example sentence will be saved here.")
        sent_row.addWidget(self._sentence_field_dropdown, 1)
        fields_layout.addLayout(sent_row)
        
        # Translation field
        trans_row = QHBoxLayout()
        trans_label = QLabel("Translation Field:")
        trans_label.setToolTip("Select the field where the sentence translation will be saved.\\n"
                               "This will contain the sentence meaning in your Translation Language.")
        trans_row.addWidget(trans_label)
        self._sentence_trans_dropdown = QComboBox()
        self._sentence_trans_dropdown.setEnabled(False)
        self._sentence_trans_dropdown.setToolTip("The sentence translation in your native language will be saved here.")
        trans_row.addWidget(self._sentence_trans_dropdown, 1)
        fields_layout.addLayout(trans_row)
        
        layout.addWidget(fields_group)
        
        # Debug: Confirm dropdowns were created
        logger.info(f"Sentence tab dropdowns created: word={self._sentence_word_dropdown is not None}, "
                    f"field={self._sentence_field_dropdown is not None}, trans={self._sentence_trans_dropdown is not None}")
        
        # Options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        
        # Help text explaining language settings
        lang_help = QLabel(
            "💡 <b>Example:</b> If you're a Korean speaker learning English words:<br>"
            "&nbsp;&nbsp;&nbsp;• <b>Sentence Language:</b> English (sentences will be in English)<br>"
            "&nbsp;&nbsp;&nbsp;• <b>Translation Language:</b> Korean (translations will be in Korean)"
        )
        lang_help.setStyleSheet("color: #555; font-size: 11px; padding: 6px; background-color: #e8f4f8; border-radius: 4px;")
        lang_help.setWordWrap(True)
        options_layout.addWidget(lang_help)
        
        # Sentence Language - The language in which the example sentence will be generated
        lang_row = QHBoxLayout()
        lang_label = QLabel("Sentence Language:")
        lang_label.setToolTip("The language for the generated example sentence.\n"
                              "Example: If you're learning Korean, select 'Korean' to get\n"
                              "Korean example sentences using your vocabulary words.")
        lang_row.addWidget(lang_label)
        self._sentence_lang_dropdown = QComboBox()
        self._sentence_lang_dropdown.setEditable(True)
        self._sentence_lang_dropdown.addItems([
            "English", "Korean", "Japanese", "Chinese (Simplified)", "Chinese (Traditional)",
            "Spanish", "French", "German", "Italian", "Portuguese", "Russian",
            "Vietnamese", "Thai", "Indonesian", "Arabic", "Hindi"
        ])
        self._sentence_lang_dropdown.setCurrentText(
            self._config_manager.config.sentence.target_language
        )
        self._sentence_lang_dropdown.setToolTip(
            "Select the language for the generated example sentences.\n"
            "This is the language you are learning."
        )
        lang_row.addWidget(self._sentence_lang_dropdown, 1)
        options_layout.addLayout(lang_row)
        
        # Translation Language - The language for sentence translation (user's native language)
        trans_lang_row = QHBoxLayout()
        trans_lang_label = QLabel("Translation Language:")
        trans_lang_label.setToolTip("Your native language for understanding the generated sentences.\n"
                                    "Example: If you're a Korean speaker learning English,\n"
                                    "select 'Korean' to get Korean translations of the English sentences.")
        trans_lang_row.addWidget(trans_lang_label)
        self._translation_lang_dropdown = QComboBox()
        self._translation_lang_dropdown.setEditable(True)
        self._translation_lang_dropdown.addItems([
            "English", "Korean", "Japanese", "Chinese (Simplified)", "Chinese (Traditional)",
            "Spanish", "French", "German", "Italian", "Portuguese", "Russian",
            "Vietnamese", "Thai", "Indonesian", "Arabic", "Hindi"
        ])
        self._translation_lang_dropdown.setCurrentText(
            getattr(self._config_manager.config.sentence, 'translation_language', 'English')
        )
        self._translation_lang_dropdown.setToolTip(
            "Select your native language for sentence translations.\n"
            "The Translation Field will contain the sentence meaning in this language."
        )
        trans_lang_row.addWidget(self._translation_lang_dropdown, 1)
        options_layout.addLayout(trans_lang_row)
        
        # Difficulty
        diff_row = QHBoxLayout()
        diff_row.addWidget(QLabel("Difficulty:"))
        self._difficulty_dropdown = QComboBox()
        self._difficulty_dropdown.addItems(["Beginner", "Normal", "Complex"])
        self._difficulty_dropdown.setCurrentText(
            self._config_manager.config.sentence.difficulty
        )
        diff_row.addWidget(self._difficulty_dropdown, 1)
        options_layout.addLayout(diff_row)
        
        # Model selection
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self._sentence_model_dropdown = QComboBox()
        self._sentence_model_dropdown.setEditable(True)
        self._sentence_model_dropdown.addItems([
            "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"
        ])
        self._sentence_model_dropdown.setCurrentText(
            getattr(self._config_manager.config.sentence, 'model_name', 'gemini-2.5-flash')
        )
        model_row.addWidget(self._sentence_model_dropdown, 1)
        options_layout.addLayout(model_row)
        
        # Highlight
        self._highlight_cb = QCheckBox("Highlight word in sentence")
        self._highlight_cb.setChecked(self._config_manager.config.sentence.highlight_word)
        options_layout.addWidget(self._highlight_cb)
        
        # Skip existing
        self._skip_sentence_cb = QCheckBox("Skip cards with existing sentences")
        self._skip_sentence_cb.setChecked(True)
        options_layout.addWidget(self._skip_sentence_cb)
        
        layout.addWidget(options_group)
        
        # Batch settings
        batch_group = QGroupBox("Batch Settings")
        batch_layout = QHBoxLayout(batch_group)
        
        batch_layout.addWidget(QLabel("Batch Size:"))
        self._sentence_batch_size_spin = QSpinBox()
        self._sentence_batch_size_spin.setRange(1, 30)
        self._sentence_batch_size_spin.setValue(
            getattr(self._config_manager.config.sentence, 'batch_size', 5)
        )
        batch_layout.addWidget(self._sentence_batch_size_spin)
        
        batch_layout.addWidget(QLabel("Delay (sec):"))
        self._sentence_delay_spin = QSpinBox()
        self._sentence_delay_spin.setRange(1, 60)
        self._sentence_delay_spin.setValue(
            int(getattr(self._config_manager.config.sentence, 'batch_delay_seconds', 8))
        )
        batch_layout.addWidget(self._sentence_delay_spin)
        
        batch_layout.addStretch()
        layout.addWidget(batch_group)
        
        # Action buttons
        button_row = QHBoxLayout()
        
        self._sentence_preview_btn = QPushButton("🧪 Preview (3)")
        self._sentence_preview_btn.setToolTip("Test generation on 3 random cards")
        self._sentence_preview_btn.clicked.connect(lambda: self._run_preview("sentence"))
        button_row.addWidget(self._sentence_preview_btn)

        self._sentence_btn = QPushButton("▶ Generate Sentences")
        self._sentence_btn.setStyleSheet(STYLE_PRIMARY_BTN)
        self._sentence_btn.clicked.connect(self._start_sentence_generation)
        button_row.addWidget(self._sentence_btn)
        
        layout.addLayout(button_row)
        layout.addStretch()
        
        return tab
    
    def _create_image_tab(self) -> QWidget:
        """Create the image generation tab."""
        logger.info("Creating image tab...")
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        header = QLabel("Batch Image Generation")
        header.setStyleSheet(STYLE_HEADER)
        layout.addWidget(header)
        
        info = QLabel("Generates images for vocabulary cards using Gemini Imagen.")
        info.setStyleSheet("color: gray;")
        layout.addWidget(info)
        
        # Field mappings
        fields_group = QGroupBox(TEXT_FIELD_MAPPING)
        fields_layout = QVBoxLayout(fields_group)
        
        # Word field
        word_row = QHBoxLayout()
        word_row.addWidget(QLabel("Word Field:"))
        self._image_word_dropdown = QComboBox()
        self._image_word_dropdown.setEnabled(False)
        word_row.addWidget(self._image_word_dropdown, 1)
        fields_layout.addLayout(word_row)
        
        # Image field
        img_row = QHBoxLayout()
        img_row.addWidget(QLabel("Image Field:"))
        self._image_field_dropdown = QComboBox()
        self._image_field_dropdown.setEnabled(False)
        img_row.addWidget(self._image_field_dropdown, 1)
        fields_layout.addLayout(img_row)
        
        layout.addWidget(fields_group)
        
        # Debug: Confirm dropdowns were created
        logger.info(f"Image tab dropdowns created: word={self._image_word_dropdown is not None}, "
                    f"field={self._image_field_dropdown is not None}")
        
        # Style and Prompt Options
        options_group = QGroupBox("Style & Prompt Options")
        options_layout = QVBoxLayout(options_group)
        
        # Style selection row
        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Image Style:"))
        self._style_dropdown = QComboBox()
        self._style_dropdown.addItems([
            "realistic", "illustration", "anime", "watercolor",
            "sketch", "minimalist", "cartoon", "pixel_art"
        ])
        self._style_dropdown.setCurrentText(
            self._config_manager.config.image.style_preset
        )
        self._style_dropdown.currentTextChanged.connect(self._on_style_changed)
        style_row.addWidget(self._style_dropdown, 1)
        options_layout.addLayout(style_row)
        
        # Prompt editing area
        prompt_label = QLabel("Style Prompt (editable):")
        prompt_label.setStyleSheet("margin-top: 8px;")
        options_layout.addWidget(prompt_label)
        
        self._prompt_edit = QTextEdit()
        self._prompt_edit.setPlaceholderText("Select a style to view/edit its prompt...")
        self._prompt_edit.setMaximumHeight(120)
        self._prompt_edit.setStyleSheet(STYLE_PROMPT_EDIT)
        options_layout.addWidget(self._prompt_edit)
        
        # Prompt action buttons
        prompt_btn_row = QHBoxLayout()
        
        self._reset_prompt_btn = QPushButton("Reset to Default")
        self._reset_prompt_btn.clicked.connect(self._reset_style_prompt)
        prompt_btn_row.addWidget(self._reset_prompt_btn)
        
        self._save_prompt_btn = QPushButton("Save Custom Prompt")
        self._save_prompt_btn.setStyleSheet("background-color: #28a745; color: white;")
        self._save_prompt_btn.clicked.connect(self._save_style_prompt)
        prompt_btn_row.addWidget(self._save_prompt_btn)
        
        prompt_btn_row.addStretch()
        options_layout.addLayout(prompt_btn_row)
        
        # Skip existing
        self._skip_image_cb = QCheckBox("Skip cards with existing images")
        self._skip_image_cb.setChecked(True)
        options_layout.addWidget(self._skip_image_cb)
        
        layout.addWidget(options_group)
        
        # Initialize prompt display
        self._on_style_changed(self._style_dropdown.currentText())
        
        # Action buttons
        button_row = QHBoxLayout()
        
        self._image_preview_btn = QPushButton("🧪 Preview (3)")
        self._image_preview_btn.setToolTip("Test generation on 3 random cards")
        self._image_preview_btn.clicked.connect(lambda: self._run_preview("image"))
        button_row.addWidget(self._image_preview_btn)
        
        self._image_btn = QPushButton("▶ Generate Images")
        self._image_btn.setStyleSheet(STYLE_PRIMARY_BTN)
        self._image_btn.clicked.connect(self._start_image_generation)
        button_row.addWidget(self._image_btn)
        
        layout.addLayout(button_row)
        layout.addStretch()
        
        return tab
    
    def _on_style_changed(self, style_name: str) -> None:
        """Handle style dropdown change - update prompt editor."""
        from ..config.prompts import IMAGE_STYLE_PRESETS
        
        # Check for custom prompt first
        custom_prompts = self._config_manager.config.image.custom_prompts
        if style_name in custom_prompts:
            self._prompt_edit.setText(custom_prompts[style_name])
            self._prompt_edit.setStyleSheet(STYLE_PROMPT_EDIT_CUSTOM)
        else:
            # Use default prompt
            default_prompt = IMAGE_STYLE_PRESETS.get(style_name, "")
            self._prompt_edit.setText(default_prompt)
            self._prompt_edit.setStyleSheet(STYLE_PROMPT_EDIT)
    
    def _save_style_prompt(self) -> None:
        """Save the current prompt as a custom prompt for the selected style."""
        style_name = self._style_dropdown.currentText()
        custom_prompt = self._prompt_edit.toPlainText().strip()
        
        if not custom_prompt:
            showWarning("Prompt cannot be empty.")
            return
        
        try:
            # Save to config
            self._config_manager.config.image.custom_prompts[style_name] = custom_prompt
            self._config_manager.save()
            
            # Update UI to show it's a custom prompt
            self._prompt_edit.setStyleSheet(STYLE_PROMPT_EDIT_CUSTOM)
            showInfo(f"Custom prompt saved for '{style_name}' style.", title="Prompt Saved")
            logger.info(f"Saved custom image prompt for style: {style_name}")
        except Exception as e:
            logger.error(f"Failed to save custom prompt: {e}")
            showWarning(f"Failed to save prompt:\n{e}")
    
    def _reset_style_prompt(self) -> None:
        """Reset the current style's prompt to default."""
        from ..config.prompts import IMAGE_STYLE_PRESETS
        
        style_name = self._style_dropdown.currentText()
        
        # Remove custom prompt if exists
        if style_name in self._config_manager.config.image.custom_prompts:
            del self._config_manager.config.image.custom_prompts[style_name]
            self._config_manager.save()
        
        # Load default prompt
        default_prompt = IMAGE_STYLE_PRESETS.get(style_name, "")
        self._prompt_edit.setText(default_prompt)
        self._prompt_edit.setStyleSheet(STYLE_PROMPT_EDIT)
        showInfo(f"Prompt for '{style_name}' reset to default.", title="Prompt Reset")
    
    def _create_settings_tab(self) -> QWidget:
        """Create the settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        header = QLabel("Settings")
        header.setStyleSheet(STYLE_HEADER)
        layout.addWidget(header)
        
        # API Key section
        api_group = QGroupBox("API Keys")
        api_layout = QVBoxLayout(api_group)
        
        key_count = len(self._key_manager.get_all_keys())
        self._api_status_label = QLabel(f"API Keys configured: {key_count}")
        api_layout.addWidget(self._api_status_label)
        
        api_btn_row = QHBoxLayout()
        add_key_btn = QPushButton("Add API Key")
        add_key_btn.clicked.connect(self._add_api_key)
        api_btn_row.addWidget(add_key_btn)
        
        view_stats_btn = QPushButton("View Statistics")
        view_stats_btn.clicked.connect(self._show_api_stats)
        api_btn_row.addWidget(view_stats_btn)
        
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._test_api_connection)
        api_btn_row.addWidget(test_btn)
        
        api_btn_row.addStretch()
        api_layout.addLayout(api_btn_row)
        
        layout.addWidget(api_group)
        
        # General settings
        general_group = QGroupBox("General Settings")
        general_layout = QVBoxLayout(general_group)
        
        general_layout.addWidget(QLabel(
            "Additional settings can be configured via:\n"
            "Tools → Add-ons → Stella Anki Tools → Config"
        ))
        
        layout.addWidget(general_group)
        
        layout.addStretch()
        return tab

    def _create_history_tab(self) -> QWidget:
        """Create API result history tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        header = QLabel("Saved Job History")
        header.setStyleSheet(STYLE_HEADER)
        layout.addWidget(header)

        desc = QLabel(
            "Review past API outputs and reinsert them into notes later. "
            "Images are stored with their generated assets."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666;")
        layout.addWidget(desc)

        select_row = QHBoxLayout()
        select_row.addWidget(QLabel("Job:"))
        self._history_job_dropdown = QComboBox()
        self._history_job_dropdown.currentIndexChanged.connect(self._on_history_job_changed)
        select_row.addWidget(self._history_job_dropdown, 1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_history_jobs)
        select_row.addWidget(refresh_btn)
        layout.addLayout(select_row)

        self._history_detail_text = QTextEdit()
        self._history_detail_text.setReadOnly(True)
        self._history_detail_text.setPlaceholderText("Select a job to view details...")
        layout.addWidget(self._history_detail_text, 1)

        controls_row = QHBoxLayout()
        self._history_overwrite_cb = QCheckBox("Overwrite existing field content")
        self._history_overwrite_cb.setChecked(True)
        controls_row.addWidget(self._history_overwrite_cb)

        reinsert_btn = QPushButton("Reinsert Selected Job")
        reinsert_btn.setStyleSheet(STYLE_PRIMARY_BTN)
        reinsert_btn.clicked.connect(self._reinsert_selected_job)
        controls_row.addWidget(reinsert_btn)
        controls_row.addStretch()
        layout.addLayout(controls_row)

        return tab

    def _refresh_history_jobs(self) -> None:
        """Reload history jobs into the history dropdown."""
        if not self._history_job_dropdown:
            return

        jobs = self._history_manager.list_jobs(limit=300)

        self._history_job_dropdown.blockSignals(True)
        self._history_job_dropdown.clear()

        if not jobs:
            self._history_job_dropdown.addItem("(No saved jobs)", "")
        else:
            for job in jobs:
                display = (
                    f"[{job.get('started_at', '')}] "
                    f"{job.get('operation', 'unknown')} | "
                    f"{job.get('deck_name', '')} | "
                    f"{job.get('success', 0)}/{job.get('total', 0)}"
                )
                self._history_job_dropdown.addItem(display, job.get("job_id", ""))

        self._history_job_dropdown.blockSignals(False)
        self._on_history_job_changed()

    def _on_history_job_changed(self) -> None:
        """Show details for selected history job."""
        if not self._history_job_dropdown or not self._history_detail_text:
            return

        job_id = self._history_job_dropdown.currentData()
        if not job_id:
            self._history_detail_text.setPlainText("No history job selected.")
            return

        job = self._history_manager.get_job(str(job_id))
        if not job:
            self._history_detail_text.setPlainText("Selected job could not be loaded.")
            return

        summary = job.get("summary", {})
        items = job.get("items", [])
        settings = job.get("settings", {})
        preview_items = items[:10] if isinstance(items, list) else []

        lines = [
            f"Job ID: {job.get('job_id', '')}",
            f"Operation: {job.get('operation', '')}",
            f"Deck: {job.get('deck_name', '')}",
            f"Started: {job.get('started_at', '')}",
            f"Completed: {job.get('completed_at', '')}",
            f"Status: {job.get('status', '')}",
            "",
            "Summary:",
            f"  Total: {summary.get('total', 0)}",
            f"  Success: {summary.get('success', 0)}",
            f"  Failure: {summary.get('failure', 0)}",
            "",
            f"Settings: {settings}",
            "",
            "Recent items:",
        ]

        for item in preview_items:
            lines.append(
                f"- note_id={item.get('note_id')} | field={item.get('target_field')} | "
                f"status={item.get('insert_status')} | error={item.get('insert_error', '')}"
            )

        if isinstance(items, list) and len(items) > len(preview_items):
            lines.append(f"... ({len(items) - len(preview_items)} more items)")

        self._history_detail_text.setPlainText("\n".join(lines))

    def _reinsert_selected_job(self) -> None:
        """Reinsert selected history job outputs into notes."""
        if not self._history_job_dropdown:
            return

        job_id = self._history_job_dropdown.currentData()
        if not job_id:
            showWarning("Please select a saved job first.")
            return

        overwrite = bool(self._history_overwrite_cb and self._history_overwrite_cb.isChecked())

        if not askUser(
            "Reinsert all saved outputs from this job?\n\n"
            f"Overwrite existing content: {'Yes' if overwrite else 'No'}"
        ):
            return

        result = self._history_manager.reinsert_job(str(job_id), overwrite=overwrite)
        showInfo(
            "Reinsert complete.\n\n"
            f"✅ Success: {result.get('success', 0)}\n"
            f"❌ Failed: {result.get('failed', 0)}\n"
            f"⏭ Skipped: {result.get('skipped', 0)}\n"
            f"📊 Total: {result.get('total', 0)}"
        )

        self._refresh_history_jobs()
    
    # ========== Deck Management ==========
    
    def _load_decks(self) -> None:
        """Load available decks into dropdown."""
        logger.info("Loading decks into dropdown...")
        
        if not mw or not mw.col:
            logger.warning("mw or mw.col not available, cannot load decks")
            return
        
        deck_names = []
        for deck in mw.col.decks.all():
            deck_name = deck['name']
            deck_id = deck.get("id")
            card_ids, used_query = self._find_cards_for_deck(deck_name, deck_id)
            
            if card_ids:  # Only include decks with cards
                deck_names.append(deck_name)
            else:
                logger.debug(f"No cards found for deck '{deck_name}' using query '{used_query}'")
        
        # Sort alphabetically
        deck_names.sort()
        logger.info(f"Found {len(deck_names)} decks with cards")
        
        if not deck_names:
            self._deck_dropdown.addItem("(No decks with cards)")
            return
            
        # Block signals temporarily to prevent premature triggering
        self._deck_dropdown.blockSignals(True)
        self._deck_dropdown.clear()
        self._deck_dropdown.addItems(deck_names)
        
        # Restore last selection
        saved_deck = self._config_manager.config.deck
        if saved_deck and saved_deck in deck_names:
            self._deck_dropdown.setCurrentText(saved_deck)
        
        self._deck_dropdown.blockSignals(False)
        
        # Explicitly trigger field loading for the initial deck selection
        # This ensures field dropdowns are populated on dialog open
        current_deck = self._deck_dropdown.currentText()
        logger.info(f"Initial deck selection: '{current_deck}'")
        
        if current_deck and current_deck != "(No decks with cards)":
            self._suppress_deck_warnings = True
            self._on_deck_changed(current_deck)
            self._suppress_deck_warnings = False
    
    def _on_deck_changed(self, deck_name: str) -> None:
        """Handle deck selection change."""
        logger.info(f"_on_deck_changed called with deck: '{deck_name}'")
        
        if not deck_name:
            logger.warning("deck_name is empty, returning")
            return
            
        if not mw or not mw.col:
            logger.warning("mw or mw.col not available")
            return

        if deck_name == "(No decks with cards)":
            self._clear_field_dropdowns()
            return
        
        self._current_deck = deck_name
        self._persist_current_deck_selection()
        
        # Get fields from first card in deck
        try:
            deck_id = self._resolve_deck_id(deck_name)
            self._current_deck_id = deck_id
            card_ids, query = self._find_cards_for_deck(deck_name, deck_id)
            logger.info(f"Found {len(card_ids)} cards using query: {query}")
            
            if not card_ids:
                msg = f"No cards found in deck '{deck_name}' (ID: {deck_id}).\nQuery used: {query}\n\nCannot retrieve fields."
                logger.warning(msg)
                if not self._suppress_deck_warnings:
                    showWarning(msg)
                self._clear_field_dropdowns()
                return
            
            card = mw.col.get_card(card_ids[0])
            note = card.note()
            model = note.note_type()
            
            # Get field names
            fields = [field["name"] for field in model["flds"]]
            logger.info(f"Found fields: {fields}")
            
            self._current_fields = fields
            
            # Update all field dropdowns
            self._update_field_dropdowns(fields)
            
            # Show card count
            unique_notes = len({mw.col.get_card(cid).nid for cid in card_ids})
            self._status_label.setText(f"Selected: {deck_name} ({unique_notes} notes)")
            logger.info(f"Successfully loaded {len(fields)} fields for {unique_notes} notes")
            
        except Exception as e:
            logger.error(f"Error loading deck fields: {e}", exc_info=True)
            if not self._suppress_deck_warnings:
                showWarning(f"Failed to load deck fields:\n{str(e)}")
            self._status_label.setText(f"Error: {e}")
            self._clear_field_dropdowns()

    def _resolve_deck_id(self, deck_name: str) -> Optional[int]:
        """Resolve deck ID from name without creating new decks."""
        if not mw or not mw.col:
            return None

        try:
            if hasattr(mw.col.decks, "id_for_name"):
                deck_id = mw.col.decks.id_for_name(deck_name)
                if deck_id:
                    return deck_id
        except Exception:
            pass

        try:
            if hasattr(mw.col.decks, "by_name"):
                deck_info = mw.col.decks.by_name(deck_name)
                if deck_info:
                    return deck_info.get("id")
        except Exception:
            pass

        return None

    def _find_cards_for_deck(self, deck_name: str, deck_id: Optional[int]) -> tuple[List[int], str]:
        """Find cards using robust fallback strategy."""
        safe_deck_name = deck_name.replace('"', '\\"')
        queries: List[str] = []
        if deck_id:
            queries.append(f"did:{deck_id}")
        queries.append(f'"deck:{safe_deck_name}"')

        last_query = ""
        for query in queries:
            last_query = query
            try:
                card_ids = mw.col.find_cards(query)
            except Exception as exc:
                logger.warning(f"Deck query failed ({query}): {exc}")
                continue

            if card_ids:
                return card_ids, query

        return [], last_query

    def _persist_current_deck_selection(self) -> None:
        """Persist selected deck in config."""
        try:
            self._config_manager.config.deck = self._current_deck
            self._config_manager.save()
        except Exception as exc:
            logger.warning(f"Failed to persist selected deck: {exc}")
    
    def _update_field_dropdowns(self, fields: List[str]) -> None:
        """Update all field dropdown menus."""
        logger.info(f"Updating field dropdowns with {len(fields)} fields: {fields}")
        self._updating_field_dropdowns = True
        try:
            # Helper function to safely update a dropdown
            def update_dropdown(dropdown: Optional[QComboBox], name: str, add_none_option: bool = False) -> bool:
                if dropdown is not None:
                    dropdown.clear()
                    if add_none_option:
                        dropdown.addItem(TEXT_NONE_OPTION)
                    dropdown.addItems(fields)
                    dropdown.setEnabled(True)
                    logger.debug(f"Enabled {name} dropdown with {dropdown.count()} items")
                    return True
                else:
                    logger.warning(f"{name} dropdown is None!")
                    return False
            
            # Translation tab - use direct attribute access
            update_dropdown(self._source_dropdown, "Translation source")
            update_dropdown(self._context_dropdown, "Translation context", add_none_option=True)
            update_dropdown(self._dest_dropdown, "Translation dest")
            
            # Sentence tab
            update_dropdown(self._sentence_word_dropdown, "Sentence word")
            update_dropdown(self._sentence_field_dropdown, "Sentence field")
            update_dropdown(self._sentence_trans_dropdown, "Sentence trans")
            
            # Image tab
            update_dropdown(self._image_word_dropdown, "Image word")
            update_dropdown(self._image_field_dropdown, "Image field")
            
            logger.info("Field dropdowns updated successfully")
            
            # Try to restore saved field selections
            self._restore_field_selections(fields)
        finally:
            self._updating_field_dropdowns = False

    def _on_field_mapping_changed(self, _value: str) -> None:
        """Persist field mapping changes when user updates dropdowns."""
        if self._updating_field_dropdowns:
            return

        try:
            config = self._config_manager.config

            if self._source_dropdown is not None:
                config.translation.source_field = self._source_dropdown.currentText()
            if self._context_dropdown is not None:
                context = self._context_dropdown.currentText()
                config.translation.context_field = "" if context == TEXT_NONE_OPTION else context
            if self._dest_dropdown is not None:
                config.translation.destination_field = self._dest_dropdown.currentText()

            if self._sentence_word_dropdown is not None:
                config.sentence.expression_field = self._sentence_word_dropdown.currentText()
            if self._sentence_field_dropdown is not None:
                config.sentence.sentence_field = self._sentence_field_dropdown.currentText()
            if self._sentence_trans_dropdown is not None:
                config.sentence.translation_field = self._sentence_trans_dropdown.currentText()

            if self._image_word_dropdown is not None:
                config.image.word_field = self._image_word_dropdown.currentText()
            if self._image_field_dropdown is not None:
                config.image.image_field = self._image_field_dropdown.currentText()

            if self._current_deck:
                config.deck = self._current_deck

            self._config_manager.save()
        except Exception as exc:
            logger.warning(f"Failed to persist field mapping changes: {exc}")
    
    def _restore_field_selections(self, fields: List[str]) -> None:
        """Restore previously saved field selections."""
        config = self._config_manager.config
        
        # Define dropdown-to-field mappings for each category
        translation_mappings = [
            (self._source_dropdown, config.translation.source_field),
            (self._context_dropdown, config.translation.context_field),
            (self._dest_dropdown, config.translation.destination_field),
        ]
        sentence_mappings = [
            (self._sentence_word_dropdown, config.sentence.expression_field),
            (self._sentence_field_dropdown, config.sentence.sentence_field),
            (self._sentence_trans_dropdown, config.sentence.translation_field),
        ]
        image_mappings = [
            (self._image_word_dropdown, config.image.word_field),
            (self._image_field_dropdown, config.image.image_field),
        ]
        
        # Apply all mappings
        for dropdown, field_value in translation_mappings + sentence_mappings + image_mappings:
            self._restore_dropdown_selection(dropdown, field_value, fields)
    
    def _restore_dropdown_selection(
        self, dropdown: Optional[QComboBox], field_value: str, fields: List[str]
    ) -> None:
        """Restore a single dropdown selection if valid."""
        if not dropdown:
            return

        if dropdown is self._context_dropdown and not field_value:
            none_idx = dropdown.findText(TEXT_NONE_OPTION)
            if none_idx >= 0:
                dropdown.setCurrentIndex(none_idx)
            return

        if field_value in fields:
            dropdown.setCurrentText(field_value)
    
    def _clear_field_dropdowns(self) -> None:
        """Clear and disable all field dropdowns."""
        for dropdown in [self._source_dropdown, self._context_dropdown, self._dest_dropdown,
                         self._sentence_word_dropdown, self._sentence_field_dropdown,
                         self._sentence_trans_dropdown, self._image_word_dropdown,
                         self._image_field_dropdown]:
            if dropdown:
                dropdown.clear()
                dropdown.setEnabled(False)
    
    # ========== Note Collection ==========
    
    def _collect_notes_from_deck(
        self,
        source_field: str,
        context_field: Optional[str] = None,
        skip_if_has_content_in: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Collect notes from the selected deck.
        
        Args:
            source_field: Field to read word from
            context_field: Optional context field
            skip_if_has_content_in: Skip notes that have content in this field
            
        Returns:
            List of note data dictionaries
        """
        if not self._current_deck or not mw or not mw.col:
            return []
        
        try:
            card_ids, query = self._find_cards_for_deck(self._current_deck, self._current_deck_id)
            logger.info(f"Collecting notes from deck '{self._current_deck}' using query: {query}")
            
            notes_data = []
            seen_notes: Set[int] = set()
            
            for card_id in card_ids:
                note_data = self._process_card_for_collection(
                    card_id, seen_notes, source_field, context_field, skip_if_has_content_in
                )
                if note_data:
                    notes_data.append(note_data)
            
            return notes_data
            
        except Exception as e:
            logger.error(f"Error collecting notes: {e}")
            return []
    
    def _process_card_for_collection(
        self, card_id: int, seen_notes: Set[int], source_field: str,
        context_field: Optional[str], skip_if_has_content_in: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Process a single card and return note data if valid."""
        card = mw.col.get_card(card_id)
        note = card.note()
        
        if note.id in seen_notes:
            return None
        seen_notes.add(note.id)
        
        if self._should_skip_note(note, skip_if_has_content_in):
            return None
        
        word = self._extract_word_from_note(note, source_field)
        if not word:
            return None
        
        context = self._extract_context_from_note(note, context_field)
        
        return {"note": note, "note_id": note.id, "word": word, "context": context}
    
    def _should_skip_note(self, note, skip_field: Optional[str]) -> bool:
        """Check if note should be skipped based on existing content."""
        if not skip_field or skip_field not in note:
            return False
        content = note[skip_field].strip()
        return bool(content and not content.startswith("<!--"))
    
    def _extract_word_from_note(self, note, source_field: str) -> str:
        """Extract word from note's source field."""
        if source_field not in note:
            return ""
        return self._strip_html(note[source_field])
    
    def _extract_context_from_note(self, note, context_field: Optional[str]) -> str:
        """Extract context from note if field is valid."""
        if not context_field or context_field == TEXT_NONE_OPTION or context_field not in note:
            return ""
        return self._strip_html(note[context_field])
    
    def _strip_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        import re
        clean = re.sub(r'<[^>]+>', '', text)
        return clean.strip()
    
    # ========== Preview Operations ==========
    
    def _get_sample_notes(self, operation_type: str, count: int = 3) -> List:
        """
        Get sample notes for preview operation.
        
        Prioritizes notes with empty target fields to simulate real work.
        
        Args:
            operation_type: "translation", "sentence", or "image"
            count: Number of samples to return
            
        Returns:
            List of Anki Note objects
        """
        import random
        
        if not self._current_deck:
            return []
        
        # Get all notes from the deck
        deck_id = mw.col.decks.id(self._current_deck)
        card_ids = mw.col.decks.cids(deck_id, children=True)
        note_ids = list(set(mw.col.get_card(cid).nid for cid in card_ids))
        
        if not note_ids:
            return []
        
        # Get field settings based on operation type
        if operation_type == "translation":
            source_field = self._source_dropdown.currentText()
            skip_field = self._dest_dropdown.currentText()
        elif operation_type == "sentence":
            source_field = self._sentence_word_dropdown.currentText()
            skip_field = self._sentence_field_dropdown.currentText()
        elif operation_type == "image":
            source_field = self._image_word_dropdown.currentText()
            skip_field = self._image_field_dropdown.currentText()
        else:
            return []
        
        # Categorize notes: prefer empty target fields
        empty_target_notes = []
        filled_target_notes = []
        
        for nid in note_ids:
            note = mw.col.get_note(nid)
            
            # Skip if source field is empty
            if source_field not in note or not note[source_field].strip():
                continue
            
            # Categorize by target field content
            if skip_field in note and note[skip_field].strip():
                filled_target_notes.append(note)
            else:
                empty_target_notes.append(note)
        
        # Prefer notes with empty targets, but include some with content if needed
        sample_pool = empty_target_notes if empty_target_notes else filled_target_notes
        
        # Random selection
        if len(sample_pool) <= count:
            return sample_pool
        
        return random.sample(sample_pool, count)
    
    def _generate_translation_preview(self, note) -> PreviewResult:
        """Generate a translation preview for a single note."""
        from ..translation.translator import Translator
        
        translator = Translator(self._addon_dir)
        
        source_field = self._source_dropdown.currentText()
        context_field = self._context_dropdown.currentText()
        dest_field = self._dest_dropdown.currentText()
        target_language = self._language_dropdown.currentText()
        model_name = self._model_dropdown.currentText()
        
        # Handle "None" context field
        if context_field == TEXT_NONE_OPTION:
            context_field = ""
        
        return translator.translate_note_preview(
            note=note,
            source_field=source_field,
            context_field=context_field,
            destination_field=dest_field,
            target_language=target_language,
            model_name=model_name
        )
    
    def _generate_sentence_preview(self, note) -> PreviewResult:
        """Generate a sentence preview for a single note."""
        from ..sentence.sentence_generator import SentenceGenerator
        
        generator = SentenceGenerator(self._addon_dir)
        
        expression_field = self._sentence_word_dropdown.currentText()
        sentence_field = self._sentence_field_dropdown.currentText()
        target_language = self._sentence_lang_dropdown.currentText()
        difficulty = self._difficulty_dropdown.currentText()
        highlight = self._highlight_cb.isChecked()
        model_name = self._sentence_model_dropdown.currentText()
        
        return generator.generate_sentence_preview(
            note=note,
            expression_field=expression_field,
            sentence_field=sentence_field,
            target_language=target_language,
            difficulty=difficulty,
            highlight=highlight,
            model_name=model_name,
        )
    
    def _generate_image_preview(self, note) -> PreviewResult:
        """Generate an image preview for a single note."""
        from ..image.image_generator import ImageGenerator
        from ..image.prompt_generator import ImagePromptGenerator
        
        word_field = self._image_word_dropdown.currentText()
        image_field = self._image_field_dropdown.currentText()
        style = self._style_dropdown.currentText()
        custom_prompt = self._prompt_edit.toPlainText().strip() if self._prompt_edit else ""
        
        # Get word from note
        word = note[word_field].strip() if word_field in note else ""
        
        if not word:
            return PreviewResult(
                note_id=note.id,
                original_text="",
                generated_content="Error: Empty word field",
                target_field=image_field,
                is_image=True,
                error="Word field is empty"
            )
        
        # Generate prompt (with fallback)
        prompt_generator = ImagePromptGenerator()
        prompt_result = prompt_generator.generate_prompt(
            word=word,
            style=style,
            custom_instructions=custom_prompt or None,
        )
        prompt = prompt_result.prompt if prompt_result and prompt_result.prompt else f"{word}, {style} style"
        
        # Generate image
        generator = ImageGenerator(self._key_manager)
        
        return generator.generate_image_preview(
            note=note,
            prompt=prompt,
            image_field=image_field,
            word=word
        )
    
    def _apply_preview_results(self, results: List[PreviewResult], operation_type: str) -> None:
        """
        Apply accepted preview results to notes.
        
        Args:
            results: List of PreviewResult objects
            operation_type: "translation", "sentence", or "image"
        """
        for result in results:
            if result.error:
                # Skip failed results
                continue
            
            try:
                note = mw.col.get_note(result.note_id)
                
                if result.is_image and result.temp_image_path:
                    # Handle image: move from temp to Anki media
                    import os
                    if os.path.exists(result.temp_image_path):
                        # Add to Anki media collection
                        filename = mw.col.media.add_file(result.temp_image_path)
                        note[result.target_field] = f'<img src="{filename}">'
                        
                        # Clean up temp file
                        result.cleanup()
                else:
                    # Handle text content
                    note[result.target_field] = result.generated_content
                    
                    # Handle secondary content (e.g., sentence translation)
                    if result.secondary_content and result.secondary_field:
                        # Find the actual field name in the note
                        if operation_type == "sentence":
                            trans_field = self._sentence_trans_dropdown.currentText()
                            if trans_field in note:
                                note[trans_field] = result.secondary_content
                
                mw.col.update_note(note)
                logger.info(f"Applied preview result to note {result.note_id}")
                
            except Exception as e:
                logger.error(f"Failed to apply preview result to note {result.note_id}: {e}")
    
    # ========== Translation Operations ==========
    
    def _start_translation(self) -> None:
        """Start batch translation."""
        # Validate
        if not self._validate_api_key():
            return
        
        source_field = self._source_dropdown.currentText()
        dest_field = self._dest_dropdown.currentText()
        context_field = self._context_dropdown.currentText()
        
        if not source_field or not dest_field:
            showWarning("Please select source and destination fields.")
            return
        
        if source_field == dest_field:
            showWarning("Source and destination fields must be different.")
            return
        
        # Collect notes
        skip_field = dest_field if self._skip_existing_cb.isChecked() else None
        notes_data = self._collect_notes_from_deck(
            source_field=source_field,
            context_field=context_field if context_field != TEXT_NONE_OPTION else None,
            skip_if_has_content_in=skip_field
        )
        
        if not notes_data:
            showInfo("No notes to translate (all may already have translations).")
            return
        
        # Confirm
        if not askUser(f"Translate {len(notes_data)} notes?\n\nThis may take a while."):
            return
        
        # Start batch worker
        self._start_batch_operation(
            operation_type="translation",
            notes_data=notes_data,
            dest_field=dest_field
        )
    
    def _start_batch_operation(
        self,
        operation_type: str,
        notes_data: List[Dict],
        dest_field: str
    ) -> None:
        """Start a batch operation with progress tracking."""
        from ..translation.batch_translator import BatchTranslator
        
        # Reset state + update shared progress UI controls
        total = len(notes_data)
        self._start_batch_ui(total, operation_type)
        self._translate_btn.setEnabled(False)

        self._start_history_job(
            operation_type=operation_type,
            settings={
                "deck": self._current_deck,
                "target_field": dest_field,
                "source_field": self._source_dropdown.currentText() if self._source_dropdown else "",
                "context_field": self._context_dropdown.currentText() if self._context_dropdown else "",
                "target_language": self._language_dropdown.currentText() if self._language_dropdown else "",
                "model": self._model_dropdown.currentText() if self._model_dropdown else "",
                "batch_size": self._batch_size_spin.value() if self._batch_size_spin else 0,
                "delay_seconds": self._delay_spin.value() if self._delay_spin else 0,
            },
        )
        
        # Create worker
        worker = BatchTranslator(
            notes_data=notes_data,
            target_language=self._language_dropdown.currentText(),
            destination_field=dest_field,
            model_name=self._model_dropdown.currentText(),
            batch_size=self._batch_size_spin.value(),
            batch_delay_seconds=float(self._delay_spin.value()),
            ignore_errors=True,
            cancel_event=self._cancel_event,
            pause_event=self._pause_event,
        )
        
        # Connect signals
        worker.signals.progress.connect(self._on_progress)
        worker.signals.detailed_progress.connect(self._on_detailed_progress)
        worker.signals.error_detail.connect(self._on_error_detail)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        worker.signals.batch_results.connect(self._on_translation_batch_results)
        
        self._active_worker = worker
        self._thread_pool.start(worker)
    
    def _on_progress(self, processed: int, total: int) -> None:
        """Update progress bar."""
        self._progress_bar.setValue(processed)
        self._progress_label.setText(f"{processed} / {total}")
    
    def _on_detailed_progress(
        self, processed: int, total: int, success: int, failure: int
    ) -> None:
        """Update detailed progress."""
        self._success_count = success
        self._failure_count = failure
        rate = (success / processed * 100) if processed > 0 else 0
        self._status_label.setText(
            f"Processing... ✅ {success} | ❌ {failure} | Rate: {rate:.1f}%"
        )
        self._update_api_key_status()
    
    def _on_error_detail(self, error_type: str, message: str, count: int) -> None:
        """Log error details."""
        self._error_log.show()
        self._error_log.append(f"[{error_type}] {message} (x{count})")
    
    def _on_error(self, error: str) -> None:
        """Handle critical error."""
        self._active_worker = None
        self._translate_btn.setEnabled(True)
        self._end_batch_ui()
        total = self._success_count + self._failure_count
        self._finish_active_history_job(
            success=self._success_count,
            failure=self._failure_count,
            total=total,
        )
        showWarning(f"Operation error:\n{error}")
    
    def _on_finished(self, success: int, failure: int) -> None:
        """Handle operation completion."""
        self._active_worker = None
        operation_type = self._active_job_operation
        
        # Re-enable buttons
        self._translate_btn.setEnabled(True)
        if operation_type == "translation":
            self._end_batch_ui()
        
        # Show results
        total = success + failure
        self._status_label.setText(f"Completed: {success} success, {failure} failed")
        self._finish_active_history_job(success=success, failure=failure, total=total)
        
        showInfo(
            f"Operation Complete!\n\n"
            f"✅ Successful: {success}\n"
            f"❌ Failed: {failure}\n"
            f"📊 Total: {total}"
        )

    def _start_history_job(self, operation_type: str, settings: Optional[Dict[str, Any]] = None) -> None:
        """Start a persistent history job for current batch."""
        if self._active_job_id:
            total = self._success_count + self._failure_count
            self._finish_active_history_job(self._success_count, self._failure_count, total)

        try:
            self._active_job_id = self._history_manager.start_job(
                operation=operation_type,
                deck_id=self._current_deck_id,
                deck_name=self._current_deck,
                settings=settings or {},
            )
            self._active_job_operation = operation_type
        except Exception as exc:
            logger.error(f"Failed to start history job: {exc}")
            self._active_job_id = None
            self._active_job_operation = None

    def _append_history_items(self, items: List[Dict[str, Any]]) -> None:
        """Append items to active history job if available."""
        if not self._active_job_id or not items:
            return

        try:
            self._history_manager.append_items(self._active_job_id, items)
        except Exception as exc:
            logger.error(f"Failed to append history items: {exc}")

    def _finish_active_history_job(self, success: int, failure: int, total: int) -> None:
        """Finalize active history job summary."""
        if not self._active_job_id:
            return

        try:
            self._history_manager.finish_job(
                self._active_job_id,
                {
                    "success": success,
                    "failure": failure,
                    "total": total,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to finish history job: {exc}")
        finally:
            self._active_job_id = None
            self._active_job_operation = None
            self._refresh_history_jobs()

    def _on_translation_batch_results(self, batch_results: List[Dict[str, Any]]) -> None:
        """Persist per-note translation results to history."""
        if not batch_results or self._active_job_operation != "translation":
            return

        history_items: List[Dict[str, Any]] = []
        for result in batch_results:
            history_items.append(
                {
                    "note_id": result.get("note_id"),
                    "source_text": result.get("word", ""),
                    "target_field": result.get("target_field", ""),
                    "api_output": result.get("translation", ""),
                    "insert_status": result.get("insert_status", "failed"),
                    "insert_error": result.get("insert_error", ""),
                }
            )

        self._append_history_items(history_items)
    
    def _stop_operation(self) -> None:
        """Stop the current operation."""
        if self._cancel_event:
            self._cancel_event.set()
            self._pause_event.set()  # Also release pause if paused
            self._status_label.setText("Stopping...")
            self._pause_btn.setEnabled(False)
            self._global_stop_btn.setEnabled(False)
    
    def _toggle_pause(self) -> None:
        """Toggle pause/resume state."""
        if self._pause_event.is_set():
            # Currently paused, resume
            self._pause_event.clear()
            self._pause_btn.setText(TEXT_PAUSE)
            self._pause_btn.setStyleSheet(STYLE_PAUSE_BTN)
            self._status_label.setText("Resuming...")
        else:
            # Running, pause
            self._pause_event.set()
            self._pause_btn.setText("▶ Resume")
            self._pause_btn.setStyleSheet("background-color: #28a745; color: white;")
            self._status_label.setText("Paused")
    
    def _update_eta(self, processed: int, total: int) -> None:
        """Update ETA based on current progress."""
        self._items_processed = processed
        if processed <= 0 or self._start_time <= 0:
            self._eta_label.setText("ETA: calculating...")
            return
        
        elapsed = time.time() - self._start_time
        avg_time_per_item = elapsed / processed
        remaining = total - processed
        eta_seconds = avg_time_per_item * remaining
        
        self._eta_label.setText(f"ETA: {format_eta(eta_seconds)}")
    
    def _start_batch_ui(self, total: int, operation_type: str) -> None:
        """Initialize UI for batch operation."""
        self._cancel_event.clear()
        self._pause_event.clear()
        self._success_count = 0
        self._failure_count = 0
        self._start_time = time.time()
        self._total_items = total
        self._items_processed = 0
        self._error_log.clear()
        self._error_log.hide()
        
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(0)
        self._progress_label.setText(f"0 / {total}")
        self._status_label.setText(f"Starting {operation_type}...")
        self._eta_label.setText("ETA: calculating...")
        
        # Enable control buttons
        self._pause_btn.setEnabled(True)
        self._pause_btn.setText(TEXT_PAUSE)
        self._pause_btn.setStyleSheet(STYLE_PAUSE_BTN)
        self._global_stop_btn.setEnabled(True)
    
    def _end_batch_ui(self) -> None:
        """Reset UI after batch operation ends."""
        self._pause_btn.setEnabled(False)
        self._global_stop_btn.setEnabled(False)
        self._eta_label.setText("ETA: --")
        self._update_api_key_status()
    
    def _update_api_key_status(self) -> None:
        """Update the API key status display."""
        try:
            total_keys = self._key_manager.get_key_count()
            if total_keys == 0:
                self._api_key_status_label.setText("🔑 API Key: No keys configured")
                self._api_key_status_label.setStyleSheet("color: #dc3545; font-size: 11px;")
                return
            
            current_index = self._key_manager.get_current_key_index() + 1  # 1-based for display
            current_key_id = self._key_manager.get_current_key_id() or "--"
            
            self._api_key_status_label.setText(
                f"🔑 API Key: {current_key_id} (using key {current_index} of {total_keys})"
            )
            self._api_key_status_label.setStyleSheet("color: #28a745; font-size: 11px;")
        except Exception as e:
            logger.warning(f"Failed to update API key status: {e}")
            self._api_key_status_label.setText("🔑 API Key: --")
    
    # ========== Preview Features ==========

    def _run_preview(self, mode: str) -> None:
        """Run preview for the specified mode (sentence, translation, image)."""
        import random
        from .preview_dialog import PreviewDialog
        from aqt.qt import QProgressDialog, Qt, QApplication
        
        # 1. Validation & Setup
        if not self._validate_api_key():
            return
            
        source_field = ""
        target_field = ""
        context_field = ""
        sentence_translation_field = ""
        
        # Determine fields and params based on mode
        if mode == "sentence":
            source_field = self._sentence_word_dropdown.currentText()
            target_field = self._sentence_field_dropdown.currentText()
            sentence_translation_field = self._sentence_trans_dropdown.currentText()
            
            if not source_field or not target_field:
                showWarning("Please select Word and Sentence fields first.")
                return
        elif mode == "translation":
            source_field = self._source_dropdown.currentText()
            context_field = self._context_dropdown.currentText()
            target_field = self._dest_dropdown.currentText()
            
            if not source_field or not target_field:
                showWarning("Please select Source and Destination fields first.")
                return
        elif mode == "image":
            source_field = self._image_word_dropdown.currentText()
            target_field = self._image_field_dropdown.currentText()
            
            if not source_field or not target_field:
                showWarning("Please select Word and Image fields first.")
                return
        else:
            return

        # 2. Collect Sample Notes
        skip_field = target_field
        # Logic to skip already filled cards if possible, to show real generation
        skip_if_filled = True
        
        if mode == "sentence" and not self._skip_sentence_cb.isChecked(): skip_if_filled = False
        elif mode == "translation" and not self._skip_existing_cb.isChecked(): skip_if_filled = False
        elif mode == "image" and not self._skip_image_cb.isChecked(): skip_if_filled = False
        
        check_skip = skip_field if skip_if_filled else None
             
        notes_data = self._collect_notes_from_deck(
            source_field=source_field,
            context_field=context_field if context_field and context_field != TEXT_NONE_OPTION else None,
            skip_if_has_content_in=check_skip
        )
        
        # Fallback: if no empty cards found but we want to preview, try allowing filled cards
        if not notes_data and skip_if_filled:
            notes_data = self._collect_notes_from_deck(
                source_field=source_field,
                context_field=context_field if context_field and context_field != TEXT_NONE_OPTION else None,
                skip_if_has_content_in=None
            )
        
        if not notes_data:
            showWarning("No suitable cards found for preview in the current deck.")
            return
            
        # Sample 3 random notes
        sample_size = min(3, len(notes_data))
        sample_notes_data = random.sample(notes_data, sample_size)
        sample_nids = [d["note_id"] for d in sample_notes_data]
        
        # 3. Generate Previews (Blocking with Progress Dialog)
        # Preview uses individual requests with delay for safety (not batch mode)
        PREVIEW_DELAY_SECONDS = 5.0  # Delay between requests to avoid rate limits
        
        # Get current API key info for display
        total_keys = self._key_manager.get_key_count()
        current_key_num = self._key_manager.get_current_key_index() + 1
        current_key_id = self._key_manager.get_current_key_id() or "--"
        key_info = f"🔑 API Key: {current_key_id} (key {current_key_num}/{total_keys})"
        
        progress = QProgressDialog(
            f"⏳ Preview Mode (Safe Testing)\n\n"
            f"Generating previews one-by-one with delay...\n"
            f"This is slower than batch mode for stability.\n\n"
            f"{key_info}",
            "Cancel", 0, sample_size, self
        )
        window_modal = getattr(getattr(Qt, "WindowModality", Qt), "WindowModal", None)
        if window_modal is None:
            window_modal = getattr(Qt, "WindowModal", None)
        if window_modal is not None:
            progress.setWindowModality(window_modal)
        progress.setMinimumDuration(0)
        progress.setMinimumWidth(450)
        progress.setValue(0)
        
        results = []
        
        try:
            for i, nid in enumerate(sample_nids):
                if progress.wasCanceled():
                    break
                
                # Add delay between requests (except for the first one)
                if i > 0:
                    # Update key info (may have rotated)
                    current_key_num = self._key_manager.get_current_key_index() + 1
                    current_key_id = self._key_manager.get_current_key_id() or "--"
                    key_info = f"🔑 API Key: {current_key_id} (key {current_key_num}/{total_keys})"
                    
                    progress.setLabelText(
                        f"⏳ Preview Mode (Safe Testing)\n\n"
                        f"Waiting {int(PREVIEW_DELAY_SECONDS)}s before next request...\n"
                        f"(Batch mode is faster, this delay ensures stability)\n\n"
                        f"{key_info}"
                    )
                    if not self._interruptible_delay(PREVIEW_DELAY_SECONDS):
                        break
                    if progress.wasCanceled():
                        break
                
                # Update progress text with key info
                current_key_num = self._key_manager.get_current_key_index() + 1
                current_key_id = self._key_manager.get_current_key_id() or "--"
                key_info = f"🔑 API Key: {current_key_id} (key {current_key_num}/{total_keys})"
                
                progress.setLabelText(
                    f"⏳ Preview Mode (Safe Testing)\n\n"
                    f"Generating preview ({i+1}/{sample_size})...\n"
                    f"(Batch mode processes multiple items faster)\n\n"
                    f"{key_info}"
                )
                
                note = self._mw.col.get_note(nid)
                try:
                    if mode == "sentence":
                        res = self._generate_sentence_preview(note)
                        if res.secondary_content and sentence_translation_field:
                            res.secondary_field = sentence_translation_field
                    elif mode == "translation":
                        res = self._generate_translation_preview(note)
                    else:
                        res = self._generate_image_preview(note)
                except Exception as e:
                    res = PreviewResult(
                        note_id=note.id,
                        original_text=self._extract_word_from_note(note, source_field),
                        generated_content=f"Error: {e}",
                        target_field=target_field,
                        is_image=(mode == "image"),
                        error=str(e),
                    )
                results.append(res)
                
                progress.setValue(i + 1)
                QApplication.processEvents()
                
        except Exception as e:
            # Cleanup any already generated
            for r in results:
                r.cleanup()
            logger.error(f"Preview generation failed: {e}", exc_info=True)
            showWarning(f"Preview generation failed: {e}")
            return
        finally:
            progress.setValue(sample_size)
            
        if progress.wasCanceled():
            for r in results: r.cleanup()
            return
            
        if not results:
            return

        # 4. Show Preview Dialog
        dialog = PreviewDialog(self, results)
        if dialog.exec():
            # Apply Changes
            self._apply_preview_results(results, mode)
        else:
            pass

    # ========== Sentence Generation ==========
    
    def _start_sentence_generation(self) -> None:
        """Start batch sentence generation."""
        if not self._validate_api_key():
            return
        
        word_field = self._sentence_word_dropdown.currentText()
        sentence_field = self._sentence_field_dropdown.currentText()
        trans_field = self._sentence_trans_dropdown.currentText()
        
        if not word_field or not sentence_field:
            showWarning("Please select word and sentence fields.")
            return
        
        # Collect notes
        skip_field = sentence_field if self._skip_sentence_cb.isChecked() else None
        notes_data = self._collect_notes_from_deck(
            source_field=word_field,
            skip_if_has_content_in=skip_field
        )
        
        if not notes_data:
            showInfo("No notes to process.")
            return
        
        if not askUser(f"Generate sentences for {len(notes_data)} notes?"):
            return
        
        # Start batch (using simple loop for now)
        self._run_sentence_batch(
            notes_data=notes_data,
            word_field=word_field,
            sentence_field=sentence_field,
            trans_field=trans_field
        )
    
    def _run_sentence_batch(
        self,
        notes_data: List[Dict],
        word_field: str,
        sentence_field: str,
        trans_field: str,
        resume_ids: Optional[Set[int]] = None
    ) -> None:
        """Run sentence generation batch with pause/resume support."""
        from ..sentence.sentence_generator import SentenceGenerator
        
        generator = SentenceGenerator()
        total = len(notes_data)
        
        language = self._sentence_lang_dropdown.currentText()
        translation_language = self._translation_lang_dropdown.currentText()
        difficulty = self._difficulty_dropdown.currentText()
        highlight = self._highlight_cb.isChecked()
        model_name = self._sentence_model_dropdown.currentText()
        batch_delay = float(self._sentence_delay_spin.value())
        
        # Initialize UI and progress
        self._start_batch_ui(total, "sentence generation")
        self._sentence_btn.setEnabled(False)
        self._init_sentence_progress(notes_data)
        self._start_history_job(
            operation_type="sentence",
            settings={
                "deck": self._current_deck,
                "word_field": word_field,
                "sentence_field": sentence_field,
                "translation_field": trans_field,
                "sentence_language": language,
                "translation_language": translation_language,
                "difficulty": difficulty,
                "highlight": highlight,
            },
        )
        
        # Process notes
        success, failure = self._process_sentence_notes(
            notes_data, total, generator, language, translation_language, 
            difficulty, highlight, sentence_field, trans_field, resume_ids,
            model_name, batch_delay
        )
        
        # Cleanup
        self._cleanup_sentence_batch()
        self._on_finished(success, failure)
    
    def _init_sentence_progress(self, notes_data: List[Dict]) -> None:
        """Initialize progress state for sentence batch."""
        note_ids = [n["note_id"] for n in notes_data]
        if self._current_deck_id is not None:
            self._progress_manager.start_run(
                deck_id=self._current_deck_id,
                deck_name=self._current_deck,
                note_ids=note_ids
            )
    
    def _process_sentence_notes(
        self, notes_data: List[Dict], total: int, generator,
        language: str, translation_language: str, difficulty: str, highlight: bool,
        sentence_field: str, trans_field: str, resume_ids: Optional[Set[int]],
        model_name: str = "gemini-2.5-flash", batch_delay: float = 2.0
    ) -> tuple[int, int]:
        """Process all notes for sentence generation."""
        from aqt.qt import QApplication
        
        success = failure = 0
        
        for i, note_data in enumerate(notes_data):
            if not self._check_batch_continue():
                break
            
            note_id = note_data["note_id"]
            if resume_ids and note_id not in resume_ids:
                continue
            
            self._update_sentence_progress(i, total, note_data["word"])
            QApplication.processEvents()
            
            result_success = self._process_single_sentence(
                note_data, generator, language, translation_language, 
                difficulty, highlight, sentence_field, trans_field, model_name
            )
            
            if result_success:
                success += 1
            else:
                failure += 1
            
            if batch_delay > 0 and not self._interruptible_delay(batch_delay):
                break
        
        return success, failure
    
    def _update_sentence_progress(self, i: int, total: int, word: str) -> None:
        """Update progress UI for sentence generation."""
        self._progress_bar.setValue(i + 1)
        self._progress_label.setText(f"{i + 1} / {total}")
        self._status_label.setText(f"Processing: {word[:20]}...")
        self._update_eta(i + 1, total)
        self._update_api_key_status()
    
    def _process_single_sentence(
        self, note_data: Dict, generator, language: str, translation_language: str,
        difficulty: str, highlight: bool, sentence_field: str, trans_field: str,
        model_name: str = "gemini-2.5-flash"
    ) -> bool:
        """Process a single note for sentence generation. Returns True on success."""
        note = note_data["note"]
        note_id = note_data["note_id"]
        word = note_data["word"]
        
        try:
            result = generator.generate_sentence_sync(
                word=word, 
                target_language=language, 
                translation_language=translation_language,
                difficulty=difficulty,
                model_name=model_name
            )
            
            sentence = result.get("translated_sentence", "")
            translation = result.get("english_sentence", "")
            
            if highlight:
                sentence, translation = self._apply_sentence_highlighting(result, word, sentence, translation)
            
            note[sentence_field] = sentence
            if trans_field and trans_field in note:
                note[trans_field] = translation
            mw.col.update_note(note)

            self._append_history_items([
                {
                    "note_id": note_id,
                    "source_text": word,
                    "target_field": sentence_field,
                    "api_output": sentence,
                    "secondary_field": trans_field,
                    "secondary_output": translation,
                    "insert_status": "success",
                    "insert_error": "",
                }
            ])
            
            if self._current_deck_id is not None:
                self._progress_manager.mark_success(self._current_deck_id, note_id)
            self._key_manager.record_success("sentence")
            return True
            
        except Exception as e:
            logger.error(f"Sentence generation failed for '{word}': {e}")
            self._append_history_items([
                {
                    "note_id": note_id,
                    "source_text": word,
                    "target_field": sentence_field,
                    "api_output": "",
                    "secondary_field": trans_field,
                    "secondary_output": "",
                    "insert_status": "failed",
                    "insert_error": str(e),
                }
            ])
            if self._current_deck_id is not None:
                self._progress_manager.mark_failure(self._current_deck_id, note_id, str(e))
            self._key_manager.record_failure(str(e))
            return False
    
    def _apply_sentence_highlighting(
        self, result: Dict, word: str, sentence: str, translation: str
    ) -> tuple[str, str]:
        """Apply highlighting to sentence and translation."""
        from ..core.utils import highlight_word
        conj = result.get("translated_conjugated_word", word)
        eng_word = result.get("english_word", word)
        return highlight_word(sentence, conj), highlight_word(translation, eng_word)
    
    def _cleanup_sentence_batch(self) -> None:
        """Cleanup after sentence batch."""
        self._sentence_btn.setEnabled(True)
        self._end_batch_ui()
        
        if not self._cancel_event.is_set() and self._current_deck_id is not None:
            self._progress_manager.clear_run(self._current_deck_id)
    
    def _resume_sentence_batch(self, pending_ids: List[int], run_info: Dict) -> None:
        """Resume an interrupted sentence batch."""
        extra = run_info.get("extra_info", {})
        
        # Rebuild notes_data from pending IDs
        notes_data = []
        for note_id in pending_ids:
            try:
                note = mw.col.get_note(note_id)
                word_field = extra.get("word_field", "")
                if word_field and word_field in note:
                    word = self._strip_html(note[word_field])
                    notes_data.append({
                        "note": note,
                        "note_id": note_id,
                        "word": word,
                        "context": "",
                    })
            except Exception as e:
                logger.error(f"Could not load note {note_id}: {e}")
        
        if not notes_data:
            showInfo("No pending notes could be loaded.")
            return
        
        # Restore settings
        if extra.get("language"):
            self._sentence_lang_dropdown.setCurrentText(extra["language"])
        if extra.get("difficulty"):
            self._difficulty_dropdown.setCurrentText(extra["difficulty"])
        if extra.get("highlight") is not None:
            self._highlight_cb.setChecked(extra["highlight"])
        
        # Run batch with resume
        self._run_sentence_batch(
            notes_data=notes_data,
            word_field=extra.get("word_field", ""),
            sentence_field=extra.get("sentence_field", ""),
            trans_field=extra.get("trans_field", ""),
            resume_ids=set(pending_ids)
        )
    
    # ========== Image Generation ==========
    
    def _start_image_generation(self) -> None:
        """Start batch image generation."""
        if not self._validate_api_key():
            return
        
        word_field = self._image_word_dropdown.currentText()
        image_field = self._image_field_dropdown.currentText()
        
        if not word_field or not image_field:
            showWarning("Please select word and image fields.")
            return
        
        # Collect notes
        skip_field = image_field if self._skip_image_cb.isChecked() else None
        notes_data = self._collect_notes_from_deck(
            source_field=word_field,
            skip_if_has_content_in=skip_field
        )
        
        if not notes_data:
            showInfo("No notes to process.")
            return
        
        if not askUser(f"Generate images for {len(notes_data)} notes?\n\nThis may take a long time."):
            return
        
        # Start batch
        self._run_image_batch(notes_data, word_field, image_field)
    
    def _run_image_batch(
        self,
        notes_data: List[Dict],
        word_field: str,
        image_field: str,
        resume_ids: Optional[Set[int]] = None
    ) -> None:
        """Run image generation batch with pause/resume support."""
        from ..image.image_generator import ImageGenerator
        from ..image.prompt_generator import ImagePromptGenerator
        from ..image.anki_media import AnkiMediaManager
        
        image_gen = ImageGenerator(self._key_manager)
        prompt_gen = ImagePromptGenerator()
        media_mgr = AnkiMediaManager()
        
        total = len(notes_data)
        style = self._style_dropdown.currentText()
        
        # Initialize UI and progress
        self._start_batch_ui(total, "image generation")
        self._image_btn.setEnabled(False)
        self._init_image_progress(notes_data)
        self._start_history_job(
            operation_type="image",
            settings={
                "deck": self._current_deck,
                "word_field": word_field,
                "image_field": image_field,
                "style": style,
            },
        )
        
        # Process notes
        success, failure = self._process_image_notes(
            notes_data, total, style, image_gen, prompt_gen, media_mgr,
            image_field, resume_ids
        )
        
        # Cleanup
        self._cleanup_image_batch()
        self._on_finished(success, failure)
    
    def _init_image_progress(self, notes_data: List[Dict]) -> None:
        """Initialize progress state for image batch."""
        note_ids = [n["note_id"] for n in notes_data]
        if self._current_deck_id is not None:
            self._progress_manager.start_run(
                deck_id=self._current_deck_id,
                deck_name=self._current_deck,
                note_ids=note_ids
            )
    
    def _process_image_notes(
        self, notes_data: List[Dict], total: int, style: str,
        image_gen, prompt_gen, media_mgr, image_field: str,
        resume_ids: Optional[Set[int]]
    ) -> tuple[int, int]:
        """Process all notes for image generation."""
        from aqt.qt import QApplication
        
        success = failure = 0
        
        for i, note_data in enumerate(notes_data):
            if not self._check_batch_continue():
                break
            
            note_id = note_data["note_id"]
            if resume_ids and note_id not in resume_ids:
                continue
            
            self._update_image_progress(i, total, note_data["word"])
            QApplication.processEvents()
            
            result_success = self._process_single_image(
                note_data, style, image_gen, prompt_gen, media_mgr, image_field
            )
            
            if result_success:
                success += 1
            else:
                failure += 1
            
            if not self._interruptible_delay(3.0):
                break
        
        return success, failure
    
    def _check_batch_continue(self) -> bool:
        """Check if batch should continue (handles cancel and pause)."""
        from aqt.qt import QApplication
        
        if self._cancel_event.is_set():
            return False
        
        while self._pause_event.is_set() and not self._cancel_event.is_set():
            QApplication.processEvents()
            time.sleep(0.1)
        
        return not self._cancel_event.is_set()

    def _interruptible_delay(self, seconds: float) -> bool:
        """Delay helper that remains responsive to pause/cancel events."""
        from aqt.qt import QApplication

        elapsed = 0.0
        interval = 0.1
        while elapsed < seconds:
            if not self._check_batch_continue():
                return False
            step = min(interval, seconds - elapsed)
            time.sleep(step)
            elapsed += step
            QApplication.processEvents()
        return True
    
    def _update_image_progress(self, i: int, total: int, word: str) -> None:
        """Update progress UI for image generation."""
        self._progress_bar.setValue(i + 1)
        self._progress_label.setText(f"{i + 1} / {total}")
        self._status_label.setText(f"Generating image: {word[:20]}...")
        self._update_eta(i + 1, total)
        self._update_api_key_status()
    
    def _process_single_image(
        self, note_data: Dict, style: str, image_gen, prompt_gen, media_mgr, image_field: str
    ) -> bool:
        """Process a single note for image generation. Returns True on success."""
        note = note_data["note"]
        note_id = note_data["note_id"]
        word = note_data["word"]
        
        try:
            prompt = prompt_gen.generate_prompt_sync(word=word, style=style)
            result = image_gen.generate_image(prompt=prompt, word=word)
            
            if result.success and result.image_data:
                asset_path = ""
                if self._active_job_id:
                    try:
                        asset_path = self._history_manager.save_image_asset(
                            job_id=self._active_job_id,
                            note_id=note_id,
                            image_data=result.image_data,
                            extension=".png",
                        )
                    except Exception as exc:
                        logger.warning(f"Failed to persist image asset for history: {exc}")

                saved, save_error = self._save_generated_image(note, note_id, image_field, word, result, media_mgr)
                self._append_history_items([
                    {
                        "note_id": note_id,
                        "source_text": word,
                        "target_field": image_field,
                        "api_output": "[image]",
                        "asset_path": asset_path,
                        "insert_status": "success" if saved else "failed",
                        "insert_error": save_error,
                    }
                ])
                return saved
            else:
                error_message = result.error or "Generation failed"
                self._mark_image_failure(note_id, error_message)
                self._append_history_items([
                    {
                        "note_id": note_id,
                        "source_text": word,
                        "target_field": image_field,
                        "api_output": "",
                        "insert_status": "failed",
                        "insert_error": error_message,
                    }
                ])
                return False
                
        except Exception as e:
            logger.error(f"Image generation failed for '{word}': {e}")
            self._mark_image_failure(note_id, str(e))
            self._append_history_items([
                {
                    "note_id": note_id,
                    "source_text": word,
                    "target_field": image_field,
                    "api_output": "",
                    "insert_status": "failed",
                    "insert_error": str(e),
                }
            ])
            return False
    
    def _save_generated_image(
        self, note, note_id: int, image_field: str, word: str, result, media_mgr
    ) -> tuple[bool, str]:
        """Save generated image to note. Returns (success, error)."""
        media_result = media_mgr.add_image_from_bytes(
            image_data=result.image_data, word=word, extension=".png"
        )
        
        if media_result.success and media_result.filename:
            note[image_field] = f'<img src="{media_result.filename}">'
            mw.col.update_note(note)
            if self._current_deck_id is not None:
                self._progress_manager.mark_success(self._current_deck_id, note_id)
            self._key_manager.record_success("image")
            return True, ""
        else:
            error_message = media_result.error or "Save failed"
            self._mark_image_failure(note_id, error_message)
            logger.warning(f"Failed to save image: {error_message}")
            return False, error_message
    
    def _mark_image_failure(self, note_id: int, error: str) -> None:
        """Mark image generation failure in progress state."""
        if self._current_deck_id is not None:
            self._progress_manager.mark_failure(self._current_deck_id, note_id, error)
        self._key_manager.record_failure(error)
    
    def _cleanup_image_batch(self) -> None:
        """Cleanup after image batch."""
        self._image_btn.setEnabled(True)
        self._end_batch_ui()
        
        if not self._cancel_event.is_set() and self._current_deck_id is not None:
            self._progress_manager.clear_run(self._current_deck_id)
    
    def _resume_image_batch(self, pending_ids: List[int], run_info: Dict) -> None:
        """Resume an interrupted image batch."""
        extra = run_info.get("extra_info", {})
        
        # Rebuild notes_data from pending IDs
        notes_data = []
        for note_id in pending_ids:
            try:
                note = mw.col.get_note(note_id)
                word_field = extra.get("word_field", "")
                if word_field and word_field in note:
                    word = self._strip_html(note[word_field])
                    notes_data.append({
                        "note": note,
                        "note_id": note_id,
                        "word": word,
                        "context": "",
                    })
            except Exception as e:
                logger.error(f"Could not load note {note_id}: {e}")
        
        if not notes_data:
            showInfo("No pending notes could be loaded.")
            return
        
        # Restore settings
        if extra.get("style"):
            self._style_dropdown.setCurrentText(extra["style"])
        
        # Run batch with resume
        self._run_image_batch(
            notes_data=notes_data,
            word_field=extra.get("word_field", ""),
            image_field=extra.get("image_field", ""),
            resume_ids=set(pending_ids)
        )
    
    # ========== API Key Management ==========
    
    def _validate_api_key(self) -> bool:
        """Check if API key is configured."""
        if not self._key_manager.get_current_key():
            showWarning(
                "No API key configured!\n\n"
                "Please add an API key in the Settings tab."
            )
            return False
        return True
    
    def _add_api_key(self) -> None:
        """Add a new API key."""
        from aqt.utils import getText
        
        key, ok = getText("Enter Google API key:", parent=self)
        if ok and key.strip():
            self._key_manager.add_key(key.strip())
            key_count = len(self._key_manager.get_all_keys())
            self._api_status_label.setText(f"API Keys configured: {key_count}")
            showInfo("API key added successfully!")
    
    def _show_api_stats(self) -> None:
        """Show API statistics."""
        stats = self._key_manager.get_summary_stats()
        
        msg = "📊 API Key Statistics\n\n"
        msg += f"Total Keys: {stats.get('total_keys', 0)}\n"
        msg += f"Active Keys: {stats.get('active_keys', 0)}\n"
        msg += f"Total Requests: {stats.get('total_requests', 0)}\n"
        msg += f"Success Rate: {stats.get('success_rate', 0):.1f}%\n"
        
        showInfo(msg, title="API Statistics")
    
    def _test_api_connection(self) -> None:
        """
        Test API connection with comprehensive error detection.
        
        Uses JSON schema validation to properly test the API endpoint
        and provides detailed error classification for common issues.
        """
        api_key = self._key_manager.get_current_key()
        if not api_key:
            showWarning("No API key configured. Please add an API key first.")
            return
        
        self._status_label.setText("Testing API connection...")
        
        # Disable test button temporarily
        test_btn = self.sender()
        if test_btn:
            test_btn.setEnabled(False)
            test_btn.setText("Testing...")
        
        try:
            from ..core.api_tester import test_api_connection
            
            # Get current model and language settings
            model_name = self._config_manager.config.translation.model_name
            language = self._config_manager.config.translation.language
            
            success, message = test_api_connection(
                api_key=api_key,
                language=language,
                model_name=model_name
            )
            
            if success:
                showInfo(f"✅ {message}")
            else:
                showWarning(f"❌ API Test Failed:\n\n{message}")
                
        except ImportError:
            # Fallback to simple test if api_tester not available
            try:
                from ..core.gemini_client import get_gemini_client
                client = get_gemini_client()
                response = client.generate_text("Say 'Hello'", max_retries=1)
                
                if response:
                    showInfo("✅ API connection successful!")
                else:
                    showWarning("API returned empty response.")
            except Exception as e:
                self._handle_api_test_error(e)
                
        except Exception as e:
            self._handle_api_test_error(e)
        
        finally:
            # Re-enable test button
            if test_btn:
                test_btn.setEnabled(True)
                test_btn.setText("Test Connection")
            self._status_label.setText("Ready")
    
    def _handle_api_test_error(self, error: Exception) -> None:
        """Handle and classify API test errors with helpful messages."""
        error_msg = str(error).lower()
        
        # Map error patterns to user-friendly messages
        error_patterns = [
            (["api key", "api_key"], "❌ Invalid API Key\n\nPlease check your API key is correct."),
            (["resource exhausted", "quota exceeded"], 
             "❌ API Quota Exceeded\n\nYour API quota has been exhausted. Please wait or try a different API key."),
            (["rate limit", "too many requests"], "❌ Rate Limit Reached\n\nPlease wait a moment and try again."),
            (["permission", "forbidden"], "❌ Permission Denied\n\nYour API key may not have access to this model."),
            (["connection", "timeout", "network"], "❌ Network Error\n\nPlease check your internet connection."),
            (["invalid", "bad request"], f"❌ Invalid Request\n\n{error}"),
        ]
        
        # Check for 429 in original error
        if "429" in str(error):
            showWarning("❌ Rate Limit Reached\n\nPlease wait a moment and try again.")
            return
        
        # Check model not found separately (needs both conditions)
        if "model" in error_msg and ("not found" in error_msg or "does not exist" in error_msg):
            showWarning("❌ Model Not Found\n\nThe selected model may not be available. "
                       "Try using 'gemini-2.5-flash' instead.")
            return
        
        # Check other patterns
        for patterns, message in error_patterns:
            if any(p in error_msg for p in patterns):
                showWarning(message)
                return
        
        # Default error message
        showWarning(f"❌ API Test Failed ({type(error).__name__}):\n\n{error}")


# Legacy classes for backward compatibility
class StellaSettingsDialog:
    """Settings dialog - now redirects to DeckOperationDialog."""
    
    def __init__(self, parent: 'AnkiQt', config_manager: 'ConfigManager'):
        self._parent = parent
        self._config_manager = config_manager
    
    def exec(self) -> None:
        """Show the settings dialog."""
        dialog = DeckOperationDialog(self._parent)
        dialog.exec()


class APIKeyDialog:
    """API Key management dialog."""
    
    def __init__(self, parent: 'AnkiQt', key_manager):
        self._parent = parent
        self._key_manager = key_manager
    
    def exec(self) -> None:
        """Show API key management dialog."""
        try:
            from aqt.utils import getText, showInfo, askUser
            from aqt.qt import QInputDialog
            
            current_count = len(self._key_manager.get_all_keys())
            
            # Show options
            options = [
                "Add new API key",
                "View key statistics", 
                "Remove all keys",
                "Cancel"
            ]
            
            from aqt.qt import QInputDialog
            choice, ok = QInputDialog.getItem(
                self._parent,
                "Stella API Keys",
                f"Current keys: {current_count}\n\nSelect action:",
                options,
                0,
                False
            )
            
            if not ok:
                return
            
            if choice == "Add new API key":
                self._add_key()
            elif choice == "View key statistics":
                self._show_stats()
            elif choice == "Remove all keys":
                self._clear_keys()
                
        except Exception as e:
            from aqt.utils import showWarning
            showWarning(f"Error: {e}")
    
    def _add_key(self) -> None:
        """Add a new API key."""
        from aqt.utils import getText, showInfo
        
        key, ok = getText("Enter Google API key:", parent=self._parent)
        if ok and key.strip():
            self._key_manager.add_key(key.strip())
            showInfo(f"API key added!\nTotal keys: {len(self._key_manager.get_all_keys())}")
    
    def _show_stats(self) -> None:
        """Show key statistics."""
        from aqt.utils import showInfo
        
        stats = self._key_manager.get_summary_stats()
        
        msg = "📊 API Key Statistics\n\n"
        msg += f"Total Keys: {stats.get('total_keys', 0)}\n"
        msg += f"Active Keys: {stats.get('active_keys', 0)}\n"
        msg += f"Current Key Index: {stats.get('current_key_index', 0)}\n"
        msg += f"Total Requests: {stats.get('total_requests', 0)}\n"
        msg += f"Success Rate: {stats.get('success_rate', 0):.1f}%\n"
        
        showInfo(msg, title="API Statistics")
    
    def _clear_keys(self) -> None:
        """Clear all API keys."""
        from aqt.utils import askUser, showInfo
        
        if askUser("Are you sure you want to remove all API keys?"):
            # This would need a clear_all method in key_manager
            showInfo("Key clearing not yet implemented.\nPlease edit api_keys.json manually.")
