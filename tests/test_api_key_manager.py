# -*- coding: utf-8 -*-
"""
Tests for API Key Manager

Tests encryption, key rotation, and statistics tracking.
"""

import unittest
import os
import tempfile
import shutil
import json
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.api_key_manager import (
    APIKeyManager, APIKeyManagerState, APIKeyStats,
    _simple_encrypt, _simple_decrypt, _derive_encryption_key,
    MAX_API_KEYS, FAILURE_THRESHOLD
)


VALID_TEST_KEY_1 = "AIza" + ("A" * 30) + "1"
VALID_TEST_KEY_2 = "AIza" + ("B" * 30) + "2"


class TestEncryption(unittest.TestCase):
    """Test encryption functions."""
    
    def test_derive_encryption_key(self):
        """Test key derivation produces consistent results."""
        key1 = _derive_encryption_key("test_password")
        key2 = _derive_encryption_key("test_password")
        key3 = _derive_encryption_key("different_password")
        
        self.assertEqual(key1, key2)
        self.assertNotEqual(key1, key3)
        self.assertEqual(len(key1), 32)  # AES-256
    
    def test_encrypt_decrypt_roundtrip(self):
        """Test that encryption and decryption are inverse operations."""
        key = _derive_encryption_key("test_password")
        
        test_strings = [
            "AIza_DUMMY_KEY_FOR_TESTING_PURPOSES_LONG_STRING",
            "simple",
            "with spaces and special chars!@#$%",
            "",
        ]
        
        for original in test_strings:
            encrypted = _simple_encrypt(original, key)
            decrypted = _simple_decrypt(encrypted, key)
            self.assertEqual(original, decrypted, f"Failed for: {original}")
    
    def test_encrypted_differs_from_original(self):
        """Test that encrypted data differs from original."""
        key = _derive_encryption_key("test_password")
        original = "AIza_DUMMY_KEY_FOR_TESTING_PURPOSES"
        
        encrypted = _simple_encrypt(original, key)
        
        self.assertNotEqual(original, encrypted)
        # Encrypted should not start with AIza
        self.assertFalse(encrypted.startswith("AIza"))


class TestAPIKeyManagerState(unittest.TestCase):
    """Test APIKeyManagerState serialization."""
    
    def test_to_dict_without_encryption(self):
        """Test state serialization without encryption."""
        state = APIKeyManagerState(
            current_key_index=0,
            keys=["key1", "key2"],
        )
        
        data = state.to_dict(encrypt=False)
        
        self.assertEqual(data["keys"], ["key1", "key2"])
        self.assertFalse(data.get("encrypted", False))
    
    def test_to_dict_with_encryption(self):
        """Test state serialization with encryption."""
        key = _derive_encryption_key("test")
        state = APIKeyManagerState(
            current_key_index=0,
            keys=["AIza_DUMMY_1", "AIza_DUMMY_2"],
        )
        
        data = state.to_dict(encrypt=True, encryption_key=key)
        
        self.assertTrue(data.get("encrypted", False))
        # Keys should be encrypted (not starting with AIza)
        for encrypted_key in data["keys"]:
            self.assertFalse(encrypted_key.startswith("AIza"))
    
    def test_from_dict_decryption(self):
        """Test state deserialization with decryption."""
        key = _derive_encryption_key("test")
        original_keys = ["AIza_DUMMY_1", "AIza_DUMMY_2"]
        
        # First encrypt
        state = APIKeyManagerState(keys=original_keys)
        data = state.to_dict(encrypt=True, encryption_key=key)
        
        # Then decrypt
        restored = APIKeyManagerState.from_dict(data, encryption_key=key)
        
        self.assertEqual(restored.keys, original_keys)


class TestAPIKeyManager(unittest.TestCase):
    """Test APIKeyManager functionality."""
    
    def setUp(self):
        """Create temporary directory for tests."""
        self.temp_dir = tempfile.mkdtemp()
        # Reset singleton
        APIKeyManager._instance = None
    
    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        APIKeyManager._instance = None
    
    def test_singleton_pattern(self):
        """Test that manager is a singleton."""
        manager1 = APIKeyManager(self.temp_dir)
        manager2 = APIKeyManager(self.temp_dir)
        
        self.assertIs(manager1, manager2)
    
    def test_add_key(self):
        """Test adding API keys."""
        manager = APIKeyManager(self.temp_dir)
        
        # Add valid key
        success, _ = manager.add_key(VALID_TEST_KEY_1)
        self.assertTrue(success)
        self.assertEqual(len(manager.get_all_keys()), 1)
        
        # Duplicate key should fail
        success, _ = manager.add_key(VALID_TEST_KEY_1)
        self.assertFalse(success)
    
    def test_key_validation(self):
        """Test key validation."""
        manager = APIKeyManager(self.temp_dir)
        
        # Too short
        success, _ = manager.add_key("short")
        self.assertFalse(success)
        
        # Wrong prefix
        success, _ = manager.add_key("NotAValidKey1234567890abcdefghijklmn")
        self.assertFalse(success)
        
        # Valid
        success, _ = manager.add_key(VALID_TEST_KEY_1)
        self.assertTrue(success)
    
    def test_remove_key(self):
        """Test removing API keys."""
        manager = APIKeyManager(self.temp_dir)
        
        manager.add_key(VALID_TEST_KEY_1)
        manager.add_key(VALID_TEST_KEY_2)
        
        self.assertEqual(len(manager.get_all_keys()), 2)
        
        success = manager.remove_key(0)
        self.assertTrue(success)
        self.assertEqual(len(manager.get_all_keys()), 1)
    
    def test_get_current_key(self):
        """Test getting current key."""
        manager = APIKeyManager(self.temp_dir)
        
        self.assertIsNone(manager.get_current_key())
        
        manager.add_key(VALID_TEST_KEY_1)
        self.assertIsNotNone(manager.get_current_key())
    
    def test_record_success(self):
        """Test recording successful requests."""
        manager = APIKeyManager(self.temp_dir)
        manager.add_key(VALID_TEST_KEY_1)
        
        manager.record_success("translation", count=10)
        
        stats = manager.get_summary_stats()
        self.assertEqual(stats["total_requests"], 1)
        self.assertEqual(stats["successful_requests"], 1)
        self.assertEqual(stats["total_words_processed"], 10)
    
    def test_record_failure_triggers_rotation(self):
        """Test that consecutive failures trigger key rotation."""
        manager = APIKeyManager(self.temp_dir)
        manager.add_key(VALID_TEST_KEY_1)
        manager.add_key(VALID_TEST_KEY_2)
        
        # Record failures up to threshold
        for _ in range(FAILURE_THRESHOLD):
            rotated, _ = manager.record_failure("test_error")
        
        # Should have rotated
        self.assertTrue(rotated)

    def test_reset_usage_and_rotation_restarts_from_first_key(self):
        """Reset should clear usage/cooldowns and make rotation start at key 1."""
        manager = APIKeyManager(self.temp_dir)
        manager.add_key(VALID_TEST_KEY_1)
        manager.add_key(VALID_TEST_KEY_2)

        rotated, _ = manager.record_failure("429 quota exhausted")
        self.assertTrue(rotated)
        self.assertEqual(manager.get_current_key_index(), 1)

        manager.record_failure("429 quota exhausted")
        before_reset = manager.get_summary_stats()
        self.assertEqual(before_reset["exhausted_keys"], 2)
        self.assertGreater(before_reset["total_requests"], 0)

        manager.reset_usage_and_rotation()

        self.assertEqual(manager.get_current_key_index(), 0)
        self.assertEqual(manager.get_current_key(), VALID_TEST_KEY_1)
        stats = manager.get_summary_stats()
        self.assertEqual(stats["active_keys"], 2)
        self.assertEqual(stats["exhausted_keys"], 0)
        self.assertEqual(stats["total_requests"], 0)
        self.assertEqual(stats["total_rotations"], 0)
        for key_stats in manager.get_all_stats().values():
            self.assertEqual(key_stats["consecutive_failures"], 0)
            self.assertIsNone(key_stats["exhausted_at"])
    
    def test_persistence(self):
        """Test that state persists across instances."""
        # Create and add key
        manager1 = APIKeyManager(self.temp_dir)
        manager1.add_key(VALID_TEST_KEY_1)
        
        # Reset singleton
        APIKeyManager._instance = None
        
        # Create new instance
        manager2 = APIKeyManager(self.temp_dir)
        
        # Key should still be there
        self.assertEqual(len(manager2.get_all_keys()), 1)


class TestAPIKeyStats(unittest.TestCase):
    """Test APIKeyStats dataclass."""
    
    def test_to_dict(self):
        """Test serialization."""
        stats = APIKeyStats(
            key_id="test_id",
            total_requests=100,
            successful_requests=90,
        )
        
        data = stats.to_dict()
        
        self.assertEqual(data["key_id"], "test_id")
        self.assertEqual(data["total_requests"], 100)
        self.assertEqual(data["successful_requests"], 90)
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "key_id": "test_id",
            "total_requests": 50,
            "successful_requests": 45,
        }
        
        stats = APIKeyStats.from_dict(data)
        
        self.assertEqual(stats.key_id, "test_id")
        self.assertEqual(stats.total_requests, 50)
        self.assertEqual(stats.successful_requests, 45)


if __name__ == "__main__":
    unittest.main()
