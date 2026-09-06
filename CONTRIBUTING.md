# Contributing to agy-telegram-bot 🚀

Thank you for your interest in contributing to **agy-telegram-bot**! This project bridges Google Antigravity AI agents running on local machines with Telegram to enable seamless mobile agentic development.

We welcome all types of contributions: bug fixes, new features, documentation improvements, and platform adapters.

---

## 🛠️ Development Setup

1. **Fork and Clone the Repository**:
   ```bash
   git clone https://github.com/Bemkin/agy-telegram-bot.git
   cd agy-telegram-bot
   ```

2. **Create a Virtual Environment**:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS / Linux:
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   python -m playwright install chromium
   ```

4. **Set Up Local Configuration**:
   ```bash
   cp .env.example .env
   ```
   Add your bot token from [@BotFather](https://t.me/BotFather) and your user ID from [@userinfobot](https://t.me/userinfobot).

---

## 🧪 Running Tests

Before submitting changes, ensure all tests pass:

```bash
# Run all unit and integration tests
python tests/run_all_tests.py

# Run module import sanity checks
python test_imports.py
```

---

## 🌟 High-Priority Roadmap & "Good First Issues"

If you are looking for ideas on where to contribute, these are top community priorities:

### 1. 🐳 Docker & DevContainer Support
- Create a `Dockerfile` and `docker-compose.yml` with Playwright and Python pre-configured.
- Enable running the bot inside a lightweight container while mounting the host directory.

### 2. 🍏 macOS & Linux Daemon Scripts
- Add `systemd` service templates (`agy-bot.service`) for Linux.
- Add `launchd` plist configurations for macOS background startup.

### 3. 🎙️ Voice-to-Code Input
- Ingest Telegram voice notes (`.ogg`), transcribe via Google GenAI Audio / Whisper, and route them to the agent bridge.

### 4. 💬 Discord & Slack Adapters
- Abstract the messaging interface so the same Antigravity bridge, dev manager, and preview manager can be controlled from Discord or Slack.

### 5. 🛡️ Enhanced Multi-Project Management
- Allow switching and tracking multiple dev servers and tunnels across different workspaces simultaneously.

---

## 📬 Pull Request Guidelines

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/my-new-feature
   ```
2. **Keep commits clear and focused**.
3. **Never commit secrets**:
   - Double check that `.env` and `logs/` are not tracked.
4. **Run tests**:
   - Verify `python tests/run_all_tests.py` passes cleanly.
5. **Open a PR** with a brief description of your changes and why they are needed.

Thank you for helping make mobile agentic coding better for everyone!
