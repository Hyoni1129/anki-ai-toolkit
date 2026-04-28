# Contributing to Stella Anki All-in-One Addon

Thanks for your interest in contributing! This project is in early development, so there's a lot to improve. Whether you're reporting a bug, fixing something, or suggesting a feature — all of it is appreciated.

---

## ⚠️ Important: Early Development Notice

This add-on is **not yet stable**. Some features are partially implemented, some settings don't persist correctly, and the codebase is still being restructured. If you're looking for a quick win, check the [Issues](https://github.com/Hyoni1129/Stella_Anki_All_in_one_Addon/issues) tab for things tagged `good first issue` or `bug`.

---

## Ways to Contribute

### 🐛 Reporting Bugs

If something doesn't work, please open an issue with:
- Your **Anki version** (Help → About)
- Your **OS** (Windows / macOS / Linux)
- A description of what you did and what happened
- Any error messages from the debug console (start Anki with `anki --debug` to see them)
- The `[Stella]` or `[Anki AI Toolkit]` log lines if present

The more detail the better — this is a small project and I don't always have time to reproduce vague reports.

### 💡 Suggesting Features

Open an issue with the `enhancement` label. Describe what you want and why it'd be useful. No guarantees on timeline, but good ideas will be considered.

### 🔧 Submitting a Fix or Feature

1. **Fork** the repository
2. **Create a branch** from `main`:
   ```bash
   git checkout -b fix/your-description
   # or
   git checkout -b feature/your-description
   ```
3. **Make your changes** (see development setup below)
4. **Test** that Anki loads the add-on without errors and the relevant feature works
5. **Commit** with a clear message:
   ```bash
   git commit -m "fix: translation fails when Definition field is empty"
   git commit -m "feat: add retry count display to API key list"
   ```
6. **Push** and open a **Pull Request** against `main`

In the PR description, explain what you changed and why. If it fixes a bug, link the issue.

---

## Development Setup

### Prerequisites

- Anki 2.1.50+
- Python 3.9+ (Anki's bundled Python is fine for running, but you'll want a local install for linting/testing)
- A Google Gemini API key for testing AI features

### Getting the code into Anki

The simplest approach is to clone directly into your Anki add-ons folder:

```bash
# Windows
cd %APPDATA%\Anki2\addons21\
git clone https://github.com/Hyoni1129/Stella_Anki_All_in_one_Addon.git

# macOS
cd ~/Library/Application\ Support/Anki2/addons21/
git clone https://github.com/Hyoni1129/Stella_Anki_All_in_one_Addon.git
```

Restart Anki and the add-on will load. You can then edit files in the cloned folder and restart Anki to see changes.

### API Keys for Testing

Copy the template and fill in your key:

```bash
cp api_keys.template.json api_keys.json
```

Then add your key via the Anki UI (`Stella` → `Manage API Keys`) or edit `api_keys.json` directly. **Never commit `api_keys.json`** — it's in `.gitignore` for a reason.

### Debug Logging

Start Anki from terminal with the `--debug` flag to see log output:

```bash
# Windows (from Anki install directory)
anki --debug

# macOS
/Applications/Anki.app/Contents/MacOS/anki --debug
```

Look for lines prefixed with `[Stella]` or `[Anki AI Toolkit]`.

### Running the Diagnostics

There's a basic diagnostics script in `tests/diagnostics.py`. You can run it from the Anki Tools → Debug Console, or look at the test scripts in the repo root for isolated tests.

---

## Code Structure

```
core/           # Shared infrastructure — touch carefully
  api_key_manager.py   # Key rotation, cooldown, stats
  gemini_client.py     # All Gemini API calls go through here
  logger.py            # Centralized logging
config/
  settings.py          # Config loading & defaults
  prompts.py           # All AI prompt strings live here
translation/    # Translation feature
sentence/       # Sentence generation feature
image/          # Image generation + Anki media handling
ui/             # All Qt dialogs and editor toolbar integration
```

A few conventions:
- **AI prompts** live in `config/prompts.py` — not scattered across feature files
- **API calls** go through `core/gemini_client.py`, not directly via the SDK
- **Logging** uses `core/logger.py` — prefer `logger.info/debug/warning` over `print()`

---

## Commit Message Format

```
type: short description

# Types:
fix:      Bug fix
feat:     New feature
refactor: Code restructuring, no behavior change
docs:     README, comments, docstrings
test:     Test additions or fixes
chore:    Config, dependencies, tooling
```

Keep the first line under 72 characters. Add more detail in the body if needed.

---

## Pull Request Guidelines

- **Keep PRs focused** — one fix or feature per PR
- **Test before submitting** — at minimum, make sure Anki loads without errors and the feature you touched still works
- **Don't reformat unrelated code** — keep diffs clean and reviewable
- It's fine to open a draft PR early if you want feedback on direction before finishing

---

## Questions?

Open an [issue](https://github.com/Hyoni1129/Stella_Anki_All_in_one_Addon/issues) and tag it `question`. I'll try to respond when I can.
