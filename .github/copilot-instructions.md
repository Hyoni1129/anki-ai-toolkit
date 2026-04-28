# Stella Anki Tools - AI Coding Assistant Instructions

This Document outlines the architecture, conventions, and developer workflows for the Stella Anki Tools project. Use this context to guide your code generation and analysis.

## 🏗 Project Architecture

### "Big Picture"
This is an **Anki add-on** (Python) that unifies three AI-powered features: **Translation**, **Sentence Generation**, and **Image Generation**.
- **Core Principle:** All features share a unified **Multi-API Key Management System** (`core/api_key_manager.py`) to handle rate limits (Rotates up to 15 keys).
- **Entry Point:** `__init__.py` initializes the add-on, sets up the `lib/` path for dependencies, and instantiates the main controller.
- **Central Controller:** `ui/main_controller.py` (`StellaAnkiTools` class) acts as a Singleton. It coordinates the UI, settings, and lazy-loads the three feature modules.

### Key Directories
- **`core/`**: Shared infrastructure. `api_key_manager.py` (critical), `gemini_client.py` (API interface), `logger.py`, `utils.py`.
- **`ui/`**: Qt-based interface logic. `main_controller.py`, `editor_integration.py` (Editor toolbar buttons), and dialogs.
- **`config/`**: Configuration management `settings.py`.
- **`translation/`, `sentence/`, `image/`**: Feature-specific logic modules.
- **`lib/`**: Vendorized Python dependencies (e.g., Google GenAI SDK) to ensure they work within Anki's environment.

## 🛠 Developer Workflows & Conventions

### Dependency Management
- **Vendorized Libs:** Third-party dependencies are stored in `lib/`.
- **Path Patching:** `__init__.py` inserts `lib/` into `sys.path` before importing other modules.
- **Action:** When adding new dependencies, they must be vendored into `lib/` to prevent conflicts with other Anki add-ons or system Python.

### Anki Integration
- **`aqt` Module:** The project relies heavily on `aqt` (Anki Qt) and `anki` modules.
- **Startup:** The add-on loads when Anki starts. `__init__.py` checks for `aqt.mw` availability.
- **Editor Hooks:** `ui/editor_integration.py` adds buttons/shortcuts to the Card Editor toolbar.
- **Threading:** Long-running tasks (API calls) **must** run on background threads to avoid freezing the Anki UI. Use `aqt.taskman` or distinct worker threads.

### API Key Management
- **Security:** Keys are stored locally in `api_keys.json` (`.gitignore`d — never committed).
- **Rotation:** `APIKeyManager` handles automatic rotation on 429 errors.
- **Obfuscation:** XOR-based obfuscation is used for storage. This is NOT encryption — see `SECURITY.md` for details.

### Testing
- **Unit Tests:** Located in `tests/`.
- **Mocking:** Tests for UI or Anki interactions likely require mocking `aqt` objects since Anki libraries are not installable via pip.
- **Standalone Tests:** Core logic (like `api_key_manager.py`) should be testable without Anki dependencies.

## 📝 Coding Standards

### Python
- **Type Hints:** Use `from __future__ import annotations` and `typing`. Use `if TYPE_CHECKING:` to avoid circular imports.
- **Lazy Loading:** Import heavy dependencies (like feature modules) inside methods or properties in `main_controller.py` to minimize Anki startup impact.
- **Logging:** Use `core.logger.get_logger(__name__)`. Do not use `print()`.

### Error Handling
- **User Feedback:** Exceptions during initialization are caught in `__init__.py` and shown via `aqt.utils.showInfo`.
- **Graceful Degradation:** If API keys fail, the system should degrade gracefully (e.g., disable AI features but keep addon alive).

## ⚠️ Critical Files
- `core/api_key_manager.py`: Logic for key rotation and limits. Handle with care.
- `__init__.py`: Bootloader. Path manipulation here is fragile.
- `ui/main_controller.py`: The "glue" holding the app together.
