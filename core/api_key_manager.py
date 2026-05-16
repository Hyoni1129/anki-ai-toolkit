# -*- coding: utf-8 -*-
"""
Stella Anki Tools - Multi API Key Manager

Manages multiple Google Gemini API keys with:
- Automatic rotation on failures
- Daily quota tracking
- Usage statistics
- Cooldown management for exhausted keys
- Optional encryption for secure key storage

Adapted from Anki_Deck_Translater/api_key_manager.py with improvements.
"""

from __future__ import annotations

import os
import json
import re
import base64
import hashlib
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field, asdict

from .logger import get_logger

# Module logger
_logger = get_logger(__name__)

# Constants
MAX_API_KEYS = 15
FAILURE_THRESHOLD = 5
KEY_COOLDOWN_HOURS = 24
AUTO_RESET_INACTIVE_HOURS = 12
LAST_KEY_FAILURE_RESET_THRESHOLD = 3
API_KEY_MIN_LENGTH = 35
API_KEY_MAX_LENGTH = 50

# Encryption settings
ENCRYPTION_ENABLED = True
ENCRYPTION_KEY_LENGTH = 32  # AES-256


def _derive_encryption_key(password: str, salt: bytes = b"stella_anki_2025") -> bytes:
    """Derive an encryption key from a password using PBKDF2."""
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000, dklen=ENCRYPTION_KEY_LENGTH)


def _simple_encrypt(data: str, key: bytes) -> str:
    """
    Simple XOR-based obfuscation for API keys at rest.
    
    Security Note (CWE-327):
        This is NOT cryptographic encryption. It provides only basic obfuscation
        to prevent accidental exposure of API keys in plaintext config files.
        The keys are still recoverable by anyone with access to the source code
        and the config file. For true security, users should rely on environment
        variables or a system keyring. This trade-off avoids requiring external
        cryptography dependencies within the Anki add-on sandbox.
    """
    if not data:
        return ""
    
    data_bytes = data.encode('utf-8')
    key_extended = (key * ((len(data_bytes) // len(key)) + 1))[:len(data_bytes)]
    encrypted = bytes(a ^ b for a, b in zip(data_bytes, key_extended))
    return base64.urlsafe_b64encode(encrypted).decode('utf-8')


def _simple_decrypt(encrypted_data: str, key: bytes) -> str:
    """Decrypt data that was encrypted with _simple_encrypt."""
    if not encrypted_data:
        return ""
    
    try:
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode('utf-8'))
        key_extended = (key * ((len(encrypted_bytes) // len(key)) + 1))[:len(encrypted_bytes)]
        decrypted = bytes(a ^ b for a, b in zip(encrypted_bytes, key_extended))
        return decrypted.decode('utf-8')
    except Exception:
        # Return original if decryption fails (might be unencrypted legacy key)
        return encrypted_data


def _sanitize_error_reason(reason: str) -> str:
    """
    Sanitize error reason to prevent API key leakage in logs.
    
    Removes any potential API key fragments from error messages.
    """
    if not reason:
        return "unknown"
    
    # Remove anything that looks like an API key
    sanitized = re.sub(r"AIza[A-Za-z0-9_-]{30,}", "[REDACTED_KEY]", reason)
    # Remove Bearer tokens
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9_.-]+", "Bearer [REDACTED]", sanitized)
    # Truncate to reasonable length
    return sanitized[:200]


@dataclass
class APIKeyStats:
    """Statistics for a single API key."""
    key_id: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    consecutive_failures: int = 0
    total_words_processed: int = 0
    total_images_generated: int = 0
    total_sentences_generated: int = 0
    last_used: Optional[str] = None
    last_failure: Optional[str] = None
    last_failure_reason: Optional[str] = None
    exhausted_at: Optional[str] = None
    is_active: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "APIKeyStats":
        # Handle legacy stats that don't have all fields
        return cls(
            key_id=data.get("key_id", "unknown"),
            total_requests=data.get("total_requests", 0),
            successful_requests=data.get("successful_requests", 0),
            failed_requests=data.get("failed_requests", 0),
            consecutive_failures=data.get("consecutive_failures", 0),
            total_words_processed=data.get("total_words_processed", data.get("total_words_translated", 0)),
            total_images_generated=data.get("total_images_generated", 0),
            total_sentences_generated=data.get("total_sentences_generated", 0),
            last_used=data.get("last_used"),
            last_failure=data.get("last_failure"),
            last_failure_reason=data.get("last_failure_reason"),
            exhausted_at=data.get("exhausted_at"),
            is_active=data.get("is_active", True),
        )


@dataclass
class APIKeyManagerState:
    """Persistent state for the API Key Manager."""
    current_key_index: int = 0
    keys: List[str] = field(default_factory=list)
    stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    last_rotation: Optional[str] = None
    total_rotations: int = 0
    encryption_enabled: bool = True  # Enable encryption by default
    
    def to_dict(self, encrypt: bool = False, encryption_key: Optional[bytes] = None) -> Dict[str, Any]:
        """
        Convert state to dictionary.
        
        Args:
            encrypt: Whether to encrypt the API keys
            encryption_key: Key to use for encryption
        """
        keys_to_store = self.keys
        
        if encrypt and encryption_key and self.keys:
            # Encrypt each key before storing
            keys_to_store = [_simple_encrypt(key, encryption_key) for key in self.keys]
        
        return {
            "current_key_index": self.current_key_index,
            "keys": keys_to_store,
            "stats": self.stats,
            "last_rotation": self.last_rotation,
            "total_rotations": self.total_rotations,
            "encrypted": encrypt,  # Flag to indicate if keys are encrypted
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], encryption_key: Optional[bytes] = None) -> "APIKeyManagerState":
        """
        Create state from dictionary.
        
        Args:
            data: Dictionary containing state data
            encryption_key: Key to use for decryption if keys are encrypted
        """
        keys = data.get("keys", [])
        is_encrypted = data.get("encrypted", False)
        
        if is_encrypted and encryption_key and keys:
            # Decrypt each key
            decrypted_keys = []
            for key in keys:
                decrypted = _simple_decrypt(key, encryption_key)
                # Validate it looks like an API key (starts with AIza)
                if decrypted.startswith("AIza") or not key.startswith("AIza"):
                    decrypted_keys.append(decrypted)
                else:
                    # Decryption failed or key is not encrypted, use original
                    decrypted_keys.append(key)
            keys = decrypted_keys
        
        return cls(
            current_key_index=data.get("current_key_index", 0),
            keys=keys,
            stats=data.get("stats", {}),
            last_rotation=data.get("last_rotation"),
            total_rotations=data.get("total_rotations", 0),
            encryption_enabled=data.get("encrypted", True),
        )


class APIKeyManager:
    """
    Manages multiple API keys with automatic rotation and statistics tracking.
    
    Features:
    - Store up to 15 API keys
    - Automatic rotation on consecutive failures
    - Daily quota tracking (keys exhausted for 24 hours)
    - Usage statistics per key
    - Event listeners for UI updates
    - Encrypted storage for API keys
    - Thread-safe singleton pattern
    """
    
    _instance: Optional["APIKeyManager"] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls, addon_dir: Optional[str] = None) -> "APIKeyManager":
        """Thread-safe singleton pattern to ensure single instance."""
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, addon_dir: Optional[str] = None) -> None:
        if self._initialized:
            if addon_dir and addon_dir != self._addon_dir:
                # Re-initialize with new directory
                self._addon_dir = addon_dir
                self._setup_paths()
                self._load_state()
                self._load_stats()
            return
        
        self._initialized = True
        self._addon_dir = addon_dir or os.path.dirname(os.path.dirname(__file__))
        self._setup_paths()
        
        # Generate encryption key from addon directory path (machine-specific)
        self._encryption_key = _derive_encryption_key(self._addon_dir)
        
        self.state = APIKeyManagerState()
        self._load_state()
        self._load_stats()
        
        # Runtime tracking (not persisted)
        self._current_session_failures = 0
        self._listeners: List[Callable[[str, Dict[str, Any]], None]] = []
    
    def _setup_paths(self) -> None:
        """Set up file paths for persistence."""
        self._keys_file = os.path.join(self._addon_dir, "api_keys.json")
        self._stats_file = os.path.join(self._addon_dir, "api_stats.json")
    
    def reload(self) -> None:
        """Reload state and stats from persistent storage."""
        self._load_state()
        self._load_stats()
    
    def _get_key_id(self, key: str) -> str:
        """Generate a masked identifier for a key."""
        if not key or len(key) < 10:
            return "invalid"
        return f"{key[:4]}...{key[-4:]}"
    
    def _load_state(self) -> None:
        """Load state from persistent storage with decryption support."""
        try:
            if os.path.exists(self._keys_file):
                with open(self._keys_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Pass encryption key for decryption
                    self.state = APIKeyManagerState.from_dict(data, self._encryption_key)
        except (json.JSONDecodeError, IOError, OSError) as e:
            _logger.warning(f"Failed to load API key state, using defaults: {e}")
            self.state = APIKeyManagerState()
        except Exception as e:
            _logger.error(f"Unexpected error loading API key state: {e}")
            self.state = APIKeyManagerState()
    
    def _save_state(self) -> None:
        """Save state to persistent storage with encryption."""
        try:
            with open(self._keys_file, "w", encoding="utf-8") as f:
                # Always save with encryption enabled
                json.dump(
                    self.state.to_dict(encrypt=ENCRYPTION_ENABLED, encryption_key=self._encryption_key), 
                    f, indent=2, ensure_ascii=False
                )
        except (IOError, OSError) as e:
            _logger.debug(f"Non-critical: Could not save API key state: {e}")
        except Exception as e:
            _logger.debug(f"Non-critical: Unexpected error saving API key state: {e}")
    
    def _load_stats(self) -> None:
        """Load statistics from persistent storage."""
        try:
            if os.path.exists(self._stats_file):
                with open(self._stats_file, "r", encoding="utf-8") as f:
                    self.state.stats = json.load(f)
        except (json.JSONDecodeError, IOError, OSError) as e:
            _logger.debug(f"Non-critical: Could not load API stats, will reset: {e}")
        except Exception as e:
            _logger.debug(f"Non-critical: Unexpected error loading API stats: {e}")
    
    def _save_stats(self) -> None:
        """Save statistics to persistent storage."""
        try:
            with open(self._stats_file, "w", encoding="utf-8") as f:
                json.dump(self.state.stats, f, indent=2, ensure_ascii=False)
        except (IOError, OSError) as e:
            _logger.debug(f"Non-critical: Could not save API stats: {e}")
        except Exception as e:
            _logger.debug(f"Non-critical: Unexpected error saving API stats: {e}")
    
    def _ensure_stats_for_key(self, key: str) -> None:
        """Ensure statistics entry exists for a key."""
        key_id = self._get_key_id(key)
        if key_id not in self.state.stats:
            self.state.stats[key_id] = APIKeyStats(key_id=key_id).to_dict()
    
    def _notify_listeners(self, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Notify all registered listeners of an event."""
        for listener in self._listeners:
            try:
                listener(event, data or {})
            except Exception as e:
                _logger.debug(f"Non-critical: Event listener failed for '{event}': {e}")
    
    # ========== Listener Management ==========
    
    def add_listener(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """Register a callback for manager events."""
        if callback not in self._listeners:
            self._listeners.append(callback)
    
    def remove_listener(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """Remove a registered callback."""
        if callback in self._listeners:
            self._listeners.remove(callback)
    
    # ========== Key Management ==========
    
    def add_key(self, key: str) -> Tuple[bool, str]:
        """
        Add a new API key.
        
        Args:
            key: The API key to add
            
        Returns:
            Tuple of (success, message)
        """
        key = key.strip()
        
        if not key:
            return False, "API key is empty."
        
        if len(self.state.keys) >= MAX_API_KEYS:
            return False, f"Maximum of {MAX_API_KEYS} API keys can be registered."
        
        if key in self.state.keys:
            return False, "This API key is already registered."
        
        # Validation: Google API keys start with "AIza"
        if not key.startswith("AIza"):
            return False, "Invalid Google AI API key format (must start with 'AIza')."
        
        if len(key) < API_KEY_MIN_LENGTH or len(key) > API_KEY_MAX_LENGTH:
            return False, f"Invalid API key length. Expected {API_KEY_MIN_LENGTH}-{API_KEY_MAX_LENGTH} characters."
        
        self.state.keys.append(key)
        self._ensure_stats_for_key(key)
        self._save_state()
        self._save_stats()
        
        self._notify_listeners("key_added", {"key_id": self._get_key_id(key)})
        return True, f"API key added. (Total: {len(self.state.keys)})"
    
    def remove_key(self, index: int) -> Tuple[bool, str]:
        """
        Remove an API key by index.
        
        Args:
            index: Index of the key to remove
            
        Returns:
            Tuple of (success, message)
        """
        if index < 0 or index >= len(self.state.keys):
            return False, "Invalid index."
        
        key = self.state.keys[index]
        key_id = self._get_key_id(key)
        
        self.state.keys.pop(index)
        
        # Adjust current index if needed
        if self.state.current_key_index >= len(self.state.keys):
            self.state.current_key_index = max(0, len(self.state.keys) - 1)
        
        self._save_state()
        self._notify_listeners("key_removed", {"key_id": key_id})
        return True, f"API key removed. ({key_id})"
    
    def get_all_keys(self) -> List[str]:
        """Get all registered API keys."""
        return self.state.keys.copy()
    
    def get_key_count(self) -> int:
        """Get the number of registered keys."""
        return len(self.state.keys)
    
    def get_masked_keys(self) -> List[str]:
        """Get all keys in masked format."""
        return [self._get_key_id(k) for k in self.state.keys]
    
    def clear_all_keys(self) -> None:
        """Remove all API keys."""
        self.state.keys = []
        self.state.current_key_index = 0
        self._save_state()
        self._notify_listeners("keys_cleared", {})
    
    # ========== Key Rotation ==========

    def _get_latest_activity_time(self) -> Optional[datetime]:
        """Return the most recent API activity timestamp across all keys."""
        latest: Optional[datetime] = None
        for stats in self.state.stats.values():
            for field_name in ("last_used", "last_failure"):
                timestamp = stats.get(field_name)
                if not timestamp:
                    continue
                try:
                    parsed = datetime.fromisoformat(timestamp)
                except (ValueError, TypeError):
                    continue
                if latest is None or parsed > latest:
                    latest = parsed
        return latest

    def maybe_auto_reset_after_inactivity(self) -> bool:
        """Reset usage/rotation if no API key has been used for the inactivity window."""
        if not self.state.keys:
            return False

        latest_activity = self._get_latest_activity_time()
        if latest_activity is None:
            return False

        if datetime.now() - latest_activity < timedelta(hours=AUTO_RESET_INACTIVE_HOURS):
            return False

        self.reset_usage_and_rotation(reason="auto_inactivity")
        return True
    
    def get_current_key(self) -> Optional[str]:
        """
        Get the current active API key.
        
        Automatically skips exhausted keys.
        
        Returns:
            Current API key or None if no keys available
        """
        self.maybe_auto_reset_after_inactivity()

        if not self.state.keys:
            return None
        
        # Check if current key is usable
        attempts = 0
        while attempts < len(self.state.keys):
            if self.state.current_key_index >= len(self.state.keys):
                self.state.current_key_index = 0
            
            current_key = self.state.keys[self.state.current_key_index]
            key_id = self._get_key_id(current_key)
            
            if self._is_key_usable(key_id):
                return current_key
            
            # Try next key
            self.state.current_key_index = (self.state.current_key_index + 1) % len(self.state.keys)
            attempts += 1
        
        # All keys are exhausted - return the first one anyway
        return self.state.keys[0] if self.state.keys else None
    
    def get_current_key_index(self) -> int:
        """Get the index of the current key."""
        return self.state.current_key_index
    
    def get_current_key_id(self) -> Optional[str]:
        """Get the masked ID of the current key."""
        key = self.get_current_key()
        return self._get_key_id(key) if key else None
    
    def _is_key_usable(self, key_id: str) -> bool:
        """Check if a key is usable (not exhausted or cooldown expired)."""
        if key_id not in self.state.stats:
            return True
        
        stats = self.state.stats[key_id]
        
        if not stats.get("is_active", True):
            return False
        
        exhausted_at = stats.get("exhausted_at")
        if exhausted_at:
            try:
                exhausted_time = datetime.fromisoformat(exhausted_at)
                cooldown_expires = exhausted_time + timedelta(hours=KEY_COOLDOWN_HOURS)
                
                if datetime.now() < cooldown_expires:
                    return False
                else:
                    # Cooldown expired, reactivate the key
                    stats["exhausted_at"] = None
                    stats["consecutive_failures"] = 0
                    self._save_stats()
            except (ValueError, TypeError):
                pass
        
        return True
    
    def rotate_to_next_key(self, reason: str = "manual") -> Tuple[bool, Optional[str]]:
        """
        Rotate to the next available API key.
        
        Args:
            reason: Reason for rotation
            
        Returns:
            Tuple of (success, new_key_id or error_message)
        """
        if len(self.state.keys) <= 1:
            return False, "No other API key available to switch to."
        
        original_index = self.state.current_key_index
        
        # Try to find next usable key
        for _ in range(len(self.state.keys)):
            self.state.current_key_index = (self.state.current_key_index + 1) % len(self.state.keys)
            
            if self.state.current_key_index == original_index:
                break
            
            current_key = self.state.keys[self.state.current_key_index]
            key_id = self._get_key_id(current_key)
            
            if self._is_key_usable(key_id):
                self.state.total_rotations += 1
                self.state.last_rotation = datetime.now().isoformat()
                self._save_state()
                
                self._notify_listeners("key_rotated", {
                    "new_key_id": key_id,
                    "reason": reason,
                    "total_rotations": self.state.total_rotations,
                })
                
                return True, key_id
        
        return False, "No usable API key available. All keys are exhausted."
    
    def force_set_current_key(self, index: int) -> bool:
        """Force set the current key by index."""
        if 0 <= index < len(self.state.keys):
            self.state.current_key_index = index
            self._save_state()
            return True
        return False
    
    # ========== Statistics Tracking ==========
    
    def record_success(
        self, 
        operation: str = "translation",
        count: int = 1
    ) -> None:
        """
        Record a successful API call.
        
        Args:
            operation: Type of operation (translation, image, sentence)
            count: Number of items processed
        """
        key = self.get_current_key()
        if not key:
            return
        
        key_id = self._get_key_id(key)
        self._ensure_stats_for_key(key)
        
        stats = self.state.stats[key_id]
        stats["total_requests"] = stats.get("total_requests", 0) + 1
        stats["successful_requests"] = stats.get("successful_requests", 0) + 1
        stats["consecutive_failures"] = 0
        stats["last_used"] = datetime.now().isoformat()
        
        # Track by operation type
        if operation == "translation":
            stats["total_words_processed"] = stats.get("total_words_processed", 0) + count
        elif operation == "image":
            stats["total_images_generated"] = stats.get("total_images_generated", 0) + count
        elif operation == "sentence":
            stats["total_sentences_generated"] = stats.get("total_sentences_generated", 0) + count
        
        self._current_session_failures = 0
        self._save_stats()
        
        self._notify_listeners("request_success", {
            "key_id": key_id,
            "operation": operation,
            "count": count,
        })
    
    def record_failure(
        self,
        reason: str = "unknown",
        key: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Record a failed API call.
        
        Args:
            reason: Reason for the failure
            key: API key that actually made the failed request. If omitted,
                the current key is used.
            
        Returns:
            Tuple of (key_rotated, new_key_id or None)
        """
        self.maybe_auto_reset_after_inactivity()

        failed_key = key or self.get_current_key()
        if not failed_key:
            return False, None
        
        key_id = self._get_key_id(failed_key)
        self._ensure_stats_for_key(failed_key)
        try:
            failed_key_index = self.state.keys.index(failed_key)
        except ValueError:
            failed_key_index = self.state.current_key_index
        
        stats = self.state.stats[key_id]
        stats["total_requests"] = stats.get("total_requests", 0) + 1
        stats["failed_requests"] = stats.get("failed_requests", 0) + 1
        stats["consecutive_failures"] = stats.get("consecutive_failures", 0) + 1
        stats["last_failure"] = datetime.now().isoformat()
        stats["last_failure_reason"] = _sanitize_error_reason(reason)
        
        self._current_session_failures += 1
        
        # Check if this is a quota exhaustion error
        reason_lower = reason.lower()
        is_quota_error = any(x in reason_lower for x in [
            "429", "quota", "rate", "resource_exhausted", "limit", "exhausted"
        ])
        
        # Check if we should rotate
        consecutive = stats["consecutive_failures"]
        should_rotate = False
        
        if is_quota_error:
            # Mark key as exhausted immediately for quota errors
            stats["exhausted_at"] = datetime.now().isoformat()
            stats["is_active"] = True  # Will be reactivated after cooldown
            should_rotate = True
        elif consecutive >= FAILURE_THRESHOLD:
            # Too many consecutive failures, rotate
            should_rotate = True

        should_reset_rotation = (
            len(self.state.keys) > 1
            and failed_key_index == len(self.state.keys) - 1
            and consecutive >= LAST_KEY_FAILURE_RESET_THRESHOLD
        )
        
        self._save_stats()
        
        self._notify_listeners("request_failure", {
            "key_id": key_id,
            "reason": reason,
            "consecutive_failures": consecutive,
            "is_quota_error": is_quota_error,
        })

        if should_reset_rotation:
            self.reset_usage_and_rotation(reason="last_key_failed_retries")
            return True, self.get_current_key_id()
        
        if should_rotate and len(self.state.keys) > 1:
            rotation_reason = "quota_exhausted" if is_quota_error else "consecutive_failures"
            success, new_key_id = self.rotate_to_next_key(reason=rotation_reason)
            return success, new_key_id
        
        return False, None
    
    def get_key_stats(self, key_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific key."""
        return self.state.stats.get(key_id)
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all keys."""
        return self.state.stats.copy()
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """Get summary statistics across all keys."""
        total_requests = 0
        total_success = 0
        total_failure = 0
        total_words = 0
        total_images = 0
        total_sentences = 0
        active_keys = 0
        exhausted_keys = 0
        
        for key_id, stats in self.state.stats.items():
            total_requests += stats.get("total_requests", 0)
            total_success += stats.get("successful_requests", 0)
            total_failure += stats.get("failed_requests", 0)
            total_words += stats.get("total_words_processed", 0)
            total_images += stats.get("total_images_generated", 0)
            total_sentences += stats.get("total_sentences_generated", 0)
            
            if self._is_key_usable(key_id):
                active_keys += 1
            else:
                exhausted_keys += 1
        
        return {
            "total_keys": len(self.state.keys),
            "active_keys": active_keys,
            "exhausted_keys": exhausted_keys,
            "total_requests": total_requests,
            "successful_requests": total_success,
            "failed_requests": total_failure,
            "success_rate": (total_success / total_requests * 100) if total_requests > 0 else 0,
            "total_words_processed": total_words,
            "total_images_generated": total_images,
            "total_sentences_generated": total_sentences,
            "total_rotations": self.state.total_rotations,
            "current_key_index": self.state.current_key_index,
            "current_key_id": self.get_current_key_id(),
        }
    
    def reset_stats(self) -> None:
        """Reset all statistics."""
        self.state.stats = {}
        self.state.total_rotations = 0
        self.state.last_rotation = None
        
        # Re-initialize stats for existing keys
        for key in self.state.keys:
            self._ensure_stats_for_key(key)
        
        self._save_stats()
        self._save_state()
        self._notify_listeners("stats_reset", {})

    def reset_usage_and_rotation(self, reason: str = "manual") -> None:
        """Reset usage statistics, cooldowns, and restart rotation from the first key."""
        self.state.current_key_index = 0
        self.state.stats = {}
        self.state.total_rotations = 0
        self.state.last_rotation = None
        self._current_session_failures = 0

        # Recreate clean stats entries so every key is immediately usable again.
        for key in self.state.keys:
            self._ensure_stats_for_key(key)

        self._save_stats()
        self._save_state()
        self._notify_listeners("usage_rotation_reset", {
            "total_keys": len(self.state.keys),
            "current_key_index": self.state.current_key_index,
            "reason": reason,
        })
    
    def reset_key_cooldown(self, index: int) -> bool:
        """Manually reset cooldown for a specific key."""
        if 0 <= index < len(self.state.keys):
            key = self.state.keys[index]
            key_id = self._get_key_id(key)
            
            if key_id in self.state.stats:
                self.state.stats[key_id]["exhausted_at"] = None
                self.state.stats[key_id]["consecutive_failures"] = 0
                self._save_stats()
                return True
        return False
    
    # ========== Migration ==========
    
    def migrate_from_single_key(self, key: str) -> None:
        """Migrate from old single-key system if needed."""
        if key and key.strip() and key not in self.state.keys:
            self.add_key(key)
    
    def migrate_from_legacy_config(self, config: Dict[str, Any]) -> None:
        """
        Migrate from legacy configuration formats.
        
        Handles:
        - Single gemini_api_key
        - Old api.keys list
        """
        # Single key migration
        single_key = config.get("gemini_api_key", "")
        if single_key:
            self.migrate_from_single_key(single_key)
        
        # API keys list migration
        api_config = config.get("api", {})
        keys_list = api_config.get("keys", [])
        for key in keys_list:
            if key and key not in self.state.keys:
                self.add_key(key)


# Singleton instance getter
def get_api_key_manager(addon_dir: Optional[str] = None) -> APIKeyManager:
    """Get the singleton APIKeyManager instance."""
    return APIKeyManager(addon_dir)
