<div align="center">

<img src="docs/Stella_Icon.png" alt="Stella Icon" width="120" height="120">

# 🌟 Anki AI Toolkit (v2026)

**All-in-One AI-Powered Toolkit for Anki Flashcards**

[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)
[![Anki](https://img.shields.io/badge/Anki-2.1.50%2B-blue.svg)](https://apps.ankiweb.net/)
[![Python](https://img.shields.io/badge/Python-3.9%2B-yellow.svg)](https://www.python.org/)

**Translation** • **Sentence Generation** • **Image Generation**

</div>

---

## 🎯 About The Project

**Anki AI Toolkit** is a comprehensive Anki add-on that combines three powerful AI features into a single, unified package. Powered by **Google Gemini 2.5**, it automates the most time-consuming aspects of flashcard creation:

| Feature | Description |
|---------|-------------|
| 🌐 **AI Translation** | Context-aware vocabulary translation with nuanced understanding |
| ✏️ **AI Sentences** | Generate natural example sentences with word highlighting |
| 🖼️ **AI Images** | Create visual flashcard images using Gemini Imagen |

All features share a robust **Multi-API Key Management System** with automatic rotation, ensuring uninterrupted workflow even with API rate limits.

---

## ✨ Key Features

### 🌐 **Smart Translation**
- **Contextual Understanding**: Uses definition fields to guide accurate translations
- **Batch Operations**: Process hundreds of cards with automatic key rotation
- **Multi-Language Support**: Translate to any language (default: Korean)

### ✏️ **Sentence Generation**
- **Natural Examples**: AI-generated sentences that showcase word usage in context
- **Word Highlighting**: Target vocabulary automatically bolded in sentences
- **Dual Output**: Both English sentences and translations in your target language
- **Resume Capability**: Continue interrupted batch operations from where you left off

### 🖼️ **Image Generation**
- **Gemini Imagen**: Generate vivid, educational images for vocabulary
- **Style Presets**: Cinematic, illustration, anime, and more
- **Auto-Optimization**: Images automatically sized for Anki cards
- **Direct Integration**: Images saved directly to Anki media collection

### 🔑 **Unified API Key Management**
- **Key Rotation**: Up to **15 API keys** with automatic switching on rate limits
- **Auto-Cooldown**: Keys on quota (429 errors) disabled for 24 hours automatically
- **Usage Statistics**: Track success/failure rates and token usage per key
- **Shared Pool**: All features share the same key pool for efficient usage

### 🎛️ **Seamless Editor Integration**
- **Toolbar Buttons**: 🌐 Translate | ✏️ Sentence | 🖼️ Image | ⚙️ Menu
- **Keyboard Shortcuts**: 
  - `Ctrl+Shift+T` - Translate
  - `Ctrl+Shift+S` - Generate Sentence
  - `Ctrl+Shift+I` - Generate Image
- **Real-time Feedback**: Progress indicators and status updates

---

## 🚀 Quick Start

### Prerequisites
- **Anki 2.1.50** or later
- One or more **Google Gemini API Keys** ([Get them here](https://aistudio.google.com/app/apikey))

### 🔐 Security Note
Your API keys are sensitive. This add-on stores keys locally and they are **never** transmitted except to Google's API. Never commit `api_keys.json` to version control.

### Installation

1. **Download the Add-on**:
   ```bash
   # Clone into Anki add-ons folder
   # Windows
   cd %APPDATA%\Anki2\addons21\
   git clone https://github.com/Hyoni1129/anki-ai-toolkit.git

   # macOS
   cd ~/Library/Application\ Support/Anki2/addons21/
   git clone https://github.com/Hyoni1129/anki-ai-toolkit.git
   ```

2. **Restart Anki**: The add-on loads automatically.

3. **Add API Key**: Go to `Anki AI Toolkit` → `Manage API Keys` → Add your Gemini API key.

4. **Start Using**: Open any note and use the toolbar buttons or shortcuts!

---

## 📖 Usage Guide

### 🔧 Configuration

Access settings via `Anki AI Toolkit` menu in the menubar:

| Menu Item | Description |
|-----------|-------------|
| ⚙️ Settings | Configure field mappings, languages, and styles |
| 🔑 Manage API Keys | Add, remove, and monitor API keys |
| 🧪 Test API Connection | Verify your API key works |
| 📊 API Statistics | View usage stats and key health |

### 📝 Single Note (Editor)

1. Open **Add** or **Edit** window
2. Fill in the word/vocabulary field
3. Click the desired button in toolbar:
   - 🌐 **Translate** - Fills translation field
   - ✏️ **Sentence** - Generates example sentence + translation
   - 🖼️ **Image** - Creates and attaches an image
4. Or use keyboard shortcuts for faster workflow

### 📚 Batch Processing (Browser)

1. Open **Card Browser**
2. Select multiple cards
3. Go to `Anki AI Toolkit` menu:
   - **Translate Selected Notes**
   - **Generate Sentences**
   - **Generate Images**
4. Watch progress dialog with pause/cancel support

---

## ⚙️ Configuration Options

### General Settings

| Option | Description | Default |
|--------|-------------|---------|
| `api.model` | Gemini model version | `gemini-2.5-flash` |
| `api.rotation_enabled` | Enable automatic key switching | `true` |
| `api.cooldown_hours` | Hours to disable exhausted keys | `24` |

### Translation Settings

| Option | Description | Default |
|--------|-------------|---------|
| `translation.language` | Target translation language | `Korean` |
| `translation.source_field` | Field containing word to translate | `Word` |
| `translation.context_field` | Field with definition for context | `Definition` |
| `translation.destination_field` | Field to write translation | `Translation` |
| `translation.batch_size` | Cards per API call | `5` |
| `translation.skip_existing` | Skip already translated cards | `true` |

### Sentence Settings

| Option | Description | Default |
|--------|-------------|---------|
| `sentence.expression_field` | Field with target word | `Word` |
| `sentence.sentence_field` | Field for generated sentence | `Sentence` |
| `sentence.translation_field` | Field for sentence translation | `SentenceTranslation` |
| `sentence.difficulty` | Sentence complexity level | `Normal` |
| `sentence.highlight_word` | Bold the target word | `true` |

### Image Settings

| Option | Description | Default |
|--------|-------------|---------|
| `image.word_field` | Field with word for image | `Word` |
| `image.image_field` | Field to add image | `Image` |
| `image.default_style` | Image style preset | `cinematic` |
| `image.max_width` | Maximum image width | `800` |
| `image.max_height` | Maximum image height | `600` |

---

## 📁 Project Structure

```
anki-ai-toolkit/
├── 📄 __init__.py              # Entry point & initialization
├── 📄 config.json              # Default configuration
├── 📄 meta.json                # Anki add-on metadata
│
├── 📁 core/                    # Shared infrastructure
│   ├── api_key_manager.py      # Multi-key rotation & storage
│   ├── gemini_client.py        # Unified Gemini API interface
│   ├── logger.py               # Centralized logging
│   └── utils.py                # Common utilities
│
├── 📁 config/                  # Configuration management
│   ├── settings.py             # Config loading & validation
│   └── prompts.py              # AI prompts for all features
│
├── 📁 translation/             # Translation feature
│   ├── translator.py           # Single-note translation
│   └── batch_translator.py     # Batch processing
│
├── 📁 sentence/                # Sentence generation feature
│   ├── sentence_generator.py   # Sentence creation
│   └── progress_state.py       # Resume capability
│
├── 📁 image/                   # Image generation feature
│   ├── prompt_generator.py     # Image prompt creation
│   ├── image_generator.py      # Gemini Imagen client
│   └── anki_media.py           # Media file management
│
├── 📁 ui/                      # User interface
│   ├── main_controller.py      # Menu & coordination
│   ├── editor_integration.py   # Editor buttons & shortcuts
│   ├── progress_dialog.py      # Batch progress UI
│   └── settings_dialog.py      # Configuration dialogs
│
└── 📁 lib/                     # Bundled dependencies
    └── google-generativeai/    # Gemini SDK
```

---

## 🛠️ Troubleshooting

### Common Issues

| Problem | Solution |
|---------|----------|
| "No API key configured" | Add a key via `Stella` → `Manage API Keys` |
| "Rate limit exceeded" | Add more API keys for automatic rotation |
| Buttons not appearing | Restart Anki, check add-on is enabled |
| Image generation slow | Normal - takes 5-10 seconds per image |
| Translation incorrect | Ensure Definition field has context |

### Debug Mode

Enable debug logging in Anki:
1. Start Anki from terminal: `anki --debug`
2. Check console for `[Anki AI Toolkit]` log messages

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. **Fork the Project**
2. **Create your Feature Branch** (`git checkout -b feature/AmazingFeature`)
3. **Commit your Changes** (`git commit -m '[feature] add: AmazingFeature'`)
4. **Push to the Branch** (`git push origin feature/AmazingFeature`)
5. **Open a Pull Request**

### Development Setup

```bash
# Clone the repository
git clone https://github.com/Hyoni1129/anki-ai-toolkit.git

# Link to Anki add-ons folder for testing
ln -s $(pwd)/anki-ai-toolkit ~/Library/Application\ Support/Anki2/addons21/
```

---

## 📜 License

**Anki AI Toolkit © 2026 by JeongHan Lee** is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

You are free to:
- **Share** — copy and redistribute the material
- **Adapt** — remix, transform, and build upon the material

Under the following terms:
- **Attribution** — Give appropriate credit
- **NonCommercial** — Not for commercial purposes
- **ShareAlike** — Distribute under the same license

---

## 🙏 Acknowledgments

- [Google Gemini](https://ai.google.dev/) - AI models powering all features
- [Anki](https://apps.ankiweb.net/) - The amazing flashcard platform
- Original projects that inspired this unified tool:
  - Stella Anki Translator
  - Anki Image Gen with Nano Banana
  - Anki Sentence Generator (BunAI)

---

## 👨‍💻 Developer

<div align="center">

**JeongHan Lee**

[![GitHub](https://img.shields.io/badge/GitHub-100000?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Hyoni1129)

---

**⭐ If you find this useful, please star the repository! ⭐**

</div>
