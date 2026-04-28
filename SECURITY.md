# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅ (current development) |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

1. **DO NOT** open a public issue for security vulnerabilities
2. Email the maintainer directly or use [GitHub's private vulnerability reporting](https://github.com/Hyoni1129/anki-ai-toolkit/security/advisories/new)
3. Include a description of the vulnerability and steps to reproduce

## Known Security Considerations

### API Key Storage

API keys are stored locally in `api_keys.json` using XOR-based obfuscation. This is **not** cryptographic encryption — it prevents accidental plaintext exposure but is not secure against a determined attacker with file access. We chose this trade-off to avoid requiring external cryptography dependencies within Anki's add-on sandbox.

**Best practices for users:**
- Never commit `api_keys.json` to version control (it's in `.gitignore`)
- Use API keys with appropriate quota limits
- Rotate keys periodically through Google AI Studio

### Data Privacy

- All API calls go directly to Google's Gemini API — no intermediate servers
- No telemetry or analytics are collected
- Log files (`logs/`) are stored locally and never transmitted
