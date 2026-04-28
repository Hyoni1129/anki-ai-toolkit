import sys
import os
from unittest.mock import MagicMock

# Mock aqt/anki before importing
mock_aqt = MagicMock()
mock_mw = MagicMock()
mock_config = {
    "image": { "style_preset": "anime" } # Simulate what we suspect happens
}
mock_mw.addonManager.getConfig.return_value = mock_config
mock_aqt.mw = mock_mw

sys.modules['aqt'] = mock_aqt
sys.modules['aqt.qt'] = MagicMock()
sys.modules['aqt.utils'] = MagicMock()
sys.modules['anki'] = MagicMock()

# Setup path
addon_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, addon_dir)

# Import
print("Importing DeckOperationDialog...")
try:
    from ui.settings_dialog import DeckOperationDialog
    print("Import successful.")
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)

print("Instantiating dialog...")
try:
    dialog = DeckOperationDialog(mock_mw)
    print("Instantiation returned.")
except Exception as e:
    print(f"Instantiation failed: {e}")

print("Done.")
