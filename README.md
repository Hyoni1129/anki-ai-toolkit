<div align="center">

<img src="docs/Stella_Icon.png" alt="Stella Icon" width="100" height="100">

# Stella Anki All-in-One Addon

[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)
[![Anki](https://img.shields.io/badge/Anki-2.1.50%2B-blue.svg)](https://apps.ankiweb.net/)
[![Status: Early Development](https://img.shields.io/badge/Status-Early%20Development-orange.svg)](#%EF%B8%8F-development-status)

</div>

---

> ⚠️ **This project is in early development.** Many features are still unstable or incomplete. Feel free to try it out, report issues, or contribute — all help is welcome.

---

## What is this?

I built this Anki add-on to automate the boring parts of making vocabulary flashcards. It uses **Google Gemini** to handle translation, example sentence generation, and image creation — all from inside the Anki editor.

This started as three separate projects and I'm merging them into one unified add-on.

**Three main features:**

- **Translation** — Translates a word field using the definition as context (so it's more accurate than just dumping the word into a translator)
- **Sentence Generation** — Creates a natural example sentence with the target word bolded, plus a translation
- **Image Generation** — Generates a vocabulary image via Gemini Imagen and saves it directly to your Anki media folder

All three share the same **API key pool**, so you can add up to 15 Gemini keys and they'll rotate automatically when one hits a rate limit.

---

## Installation

**Requirements:** Anki 2.1.50+, at least one [Google Gemini API key](https://aistudio.google.com/app/apikey)

```bash
# Navigate to your Anki add-ons folder:
# Windows: %APPDATA%\Anki2\addons21\
# macOS:   ~/Library/Application Support/Anki2/addons21/

git clone https://github.com/Hyoni1129/Stella_Anki_All_in_one_Addon.git
```

Then restart Anki. The add-on will appear in the menubar.

**Add your API key:** `Stella` → `Manage API Keys` → add a Gemini key

> **Security note:** API keys are stored locally in `api_keys.json`. This file is in `.gitignore` — make sure you never commit it.

---

## Usage

### Single card (in the editor)

Open any note and use the toolbar buttons or shortcuts:
- `Ctrl+Shift+T` — Translate
- `Ctrl+Shift+S` — Generate sentence
- `Ctrl+Shift+I` — Generate image

### Batch processing (in the browser)

Select multiple cards → `Stella` menu → choose an operation. There's a progress dialog with pause/cancel support. Batch jobs can resume if interrupted.

### Settings

`Stella` → `Settings` — configure which note fields to read from/write to, target language, image style, etc.

---

## ⚠️ Development Status

This is an early-stage project I'm building for personal use and sharing openly. Things that may not work yet:

- Image generation stability (depends on Gemini Imagen API access)
- Some settings dialog options don't save correctly yet
- Batch job resume logic is partially tested

If something breaks, please [open an issue](https://github.com/Hyoni1129/Stella_Anki_All_in_one_Addon/issues) with your Anki version and any error messages from the debug console.

---

## Project Structure

```
Stella_Anki_All_in_one_Addon/
├── __init__.py          # Entry point
├── config.json          # Default config
├── core/                # API key manager, Gemini client, logging
├── config/              # Settings loader, AI prompts
├── translation/         # Translation logic (single + batch)
├── sentence/            # Sentence generation
├── image/               # Image generation & Anki media handling
├── ui/                  # All dialogs and editor integration
└── tests/               # Diagnostics and test scripts
```

---

## Contributing

Contributions are very welcome — especially bug reports and fixes while the project is still taking shape. See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to get started.

---

## License

**Stella Anki All-in-One Addon © 2026 JeongHan Lee** — licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

Free to share and adapt for non-commercial purposes with attribution.

---

## Acknowledgments

- [Google Gemini](https://ai.google.dev/) for the AI backbone
- [Anki](https://apps.ankiweb.net/) for being such a great platform to build on
- The original projects this is based on: Stella Anki Translator, Anki Image Gen, BunAI Sentence Generator

<div align="center">

**Made by [JeongHan Lee](https://github.com/Hyoni1129)**

</div>
