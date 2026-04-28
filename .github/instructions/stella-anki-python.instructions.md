---
description: "Use when editing Stella Anki Tools Python code, especially Anki UI actions, startup initialization, API calls, or feature modules. Enforces QueryOp background execution, vendored lib path handling, Stella logging, lazy imports, and user-facing error dialogs."
name: "Stella Anki Python Conventions"
applyTo: "**/*.py"
---
# Stella Anki Python Conventions

These are strong preferences for day-to-day changes. Deviations are allowed when a task explicitly requires it; include a short justification in the change notes when you deviate.

- Use `from __future__ import annotations` and type hints for new or changed Python modules.
- Prefer `if TYPE_CHECKING:` imports for Anki-only types used only for hints.
- Keep heavy or feature-specific imports lazy (inside methods/properties) to reduce startup cost and avoid circular imports.
- Do not block the Anki UI thread for API or network work.
- For UI-triggered operations that perform long work (editor/menu actions), use `aqt.operations.QueryOp` with a background operation, success callback, failure handling, and `with_progress(...)`.
- Do not use `print()` for diagnostics. Use `core.logger.get_logger(...)` and log failures before showing user dialogs.
- For user-facing failures in Anki, use `aqt.utils.showWarning()` or `aqt.utils.showInfo()` with clear, actionable messages.
- Preserve vendored dependency loading rules when touching startup/client code:
  - Ensure `<addon>/lib` is inserted at the front of `sys.path` before importing vendored packages.
  - Keep Google namespace path precedence handling so bundled libraries are preferred.
- Preserve graceful degradation behavior. If keys or AI services fail, keep the add-on alive when possible and fail only the affected feature path.
- Treat `core/api_key_manager.py`, `__init__.py`, and `ui/main_controller.py` as high-risk integration points; keep behavior-compatible changes unless the task explicitly requires architectural change.

## Preferred Background Operation Skeleton

```python
from aqt.operations import QueryOp
from aqt import mw

def op_body(col):
    # long-running work
    return result

def on_success(result):
    # UI updates on main thread
    ...

def on_failure(exc):
    logger.error(f"Operation failed: {exc}")
    from aqt.utils import showWarning
    showWarning(f"Operation failed: {exc}")

QueryOp(parent=mw, op=op_body, success=on_success).failure(on_failure).with_progress(
    "Working..."
).run_in_background()
```