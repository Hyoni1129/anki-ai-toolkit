# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Centralized Logging System

Provides unified logging for all modules with:
- File-based logging with daily rotation
- Console output for important messages
- Module-specific prefixes for easy filtering
- Log level configuration
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional


class StellaLogger:
    """
    Centralized logger for Stella Anki Tools.
    
    Features:
    - Daily log rotation
    - File + console handlers
    - Module prefix support
    - Configurable log levels
    """
    
    _instances: dict[str, "StellaLogger"] = {}
    
    def __init__(self, addon_dir: str, module_name: str = "stella") -> None:
        """
        Initialize logger for a specific module.
        
        Args:
            addon_dir: Path to the add-on directory
            module_name: Name prefix for log messages
        """
        self.addon_dir = addon_dir
        self.module_name = module_name
        self._setup_logger()
    
    @classmethod
    def get_logger(cls, addon_dir: str, module_name: str = "stella") -> "StellaLogger":
        """
        Get or create a logger instance for a module.
        
        Args:
            addon_dir: Path to the add-on directory
            module_name: Name prefix for log messages
            
        Returns:
            StellaLogger instance
        """
        key = f"{addon_dir}:{module_name}"
        if key not in cls._instances:
            cls._instances[key] = cls(addon_dir, module_name)
        return cls._instances[key]
    
    def _setup_logger(self) -> None:
        """Configure logging handlers and formatters."""
        # Create logs directory
        log_dir = os.path.join(self.addon_dir, "logs")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # Log file with date
        log_file = os.path.join(
            log_dir, 
            f"stella_anki_tools_{datetime.now().strftime('%Y%m%d')}.log"
        )
        
        # Create logger
        self.logger = logging.getLogger(f"stella_anki_tools.{self.module_name}")
        self.logger.setLevel(logging.DEBUG)
        
        # Clear existing handlers
        if self.logger.handlers:
            self.logger.handlers.clear()
        
        # File handler - capture all levels
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        
        # Console handler - ERROR and above only.
        # Anki monitors stderr and shows any output as an error dialog,
        # so we must restrict console output to genuine errors.
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.ERROR)
        
        # Formatter with module name
        formatter = logging.Formatter(
            "%(asctime)s - [%(name)s] - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def set_level(self, level: str) -> None:
        """
        Set the logging level.
        
        Args:
            level: Log level name (DEBUG, INFO, WARNING, ERROR)
        """
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        log_level = level_map.get(level.upper(), logging.INFO)
        self.logger.setLevel(log_level)
    
    def debug(self, message: str) -> None:
        """Log debug message."""
        self.logger.debug(message)
    
    def info(self, message: str) -> None:
        """Log info message."""
        self.logger.info(message)
    
    def warning(self, message: str) -> None:
        """Log warning message."""
        self.logger.warning(message)
    
    def error(self, message: str) -> None:
        """Log error message."""
        self.logger.error(message)
    
    def exception(self, message: str) -> None:
        """Log exception with traceback."""
        self.logger.exception(message)
    
    # === Specialized logging methods ===
    
    def api_call(self, operation: str, status: str, details: Optional[str] = None) -> None:
        """
        Log API call details.
        
        Args:
            operation: Name of the API operation
            status: success/failure/retry
            details: Additional details
        """
        msg = f"API [{operation}] - {status}"
        if details:
            msg += f" - {details}"
        self.info(msg)
    
    def batch_progress(
        self, 
        operation: str, 
        current: int, 
        total: int, 
        success: int = 0, 
        failed: int = 0
    ) -> None:
        """
        Log batch operation progress.
        
        Args:
            operation: Name of the batch operation
            current: Current item number
            total: Total items
            success: Successful count
            failed: Failed count
        """
        progress = (current / total * 100) if total > 0 else 0
        self.info(
            f"Batch [{operation}] Progress: {current}/{total} ({progress:.1f}%) "
            f"- Success: {success}, Failed: {failed}"
        )
    
    def key_rotation(self, from_key: str, to_key: str, reason: str) -> None:
        """
        Log API key rotation event.
        
        Args:
            from_key: Masked ID of previous key
            to_key: Masked ID of new key
            reason: Reason for rotation
        """
        self.warning(f"API Key Rotation: {from_key} -> {to_key} (Reason: {reason})")
    
    def note_processing(
        self, 
        note_id: int, 
        operation: str, 
        status: str, 
        word: Optional[str] = None
    ) -> None:
        """
        Log individual note processing.
        
        Args:
            note_id: Anki note ID
            operation: translate/sentence/image
            status: success/failure/skipped
            word: The word being processed
        """
        word_info = f"'{word}'" if word else f"ID:{note_id}"
        self.debug(f"Note [{operation}] {word_info} - {status}")


def get_logger(module_name: str = "stella") -> StellaLogger:
    """
    Get a logger instance using the default add-on directory.
    
    Convenience function for module-level logging.
    
    Args:
        module_name: Module name for the logger
        
    Returns:
        StellaLogger instance
    """
    import os
    addon_dir = os.path.dirname(os.path.dirname(__file__))
    return StellaLogger.get_logger(addon_dir, module_name)
