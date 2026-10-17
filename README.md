# 📱 agy-telegram-bot

> Control your [Google Antigravity](https://antigravity.google) AI coding agent from Telegram — brainstorm, explore code, request changes, run commands, start live tunnels, and screenshot localhost, all from your phone.

<p align="center">
  <b>Your laptop codes and previews while you're on the go.</b>
</p>

---

## ✨ Features

- 💬 **Brainstorm & Explore** — Ask questions about your code, explore dependencies, discuss architecture.
- 🧠 **Safe Planning Mode** — Agent researches files and drafts structured implementation plans *before* touching source code.
- 🎛️ **Telegram Mini App (Mission Control)** — Full embedded web IDE cockpit inside Telegram with live preview, logs, and plan tracking (`/app`).
- 🌐 **Live Cloudflare Tunnel (`/tunnel`)** — Instant public HTTPS URL to browse localhost from your phone.
- 📸 **Mobile & Desktop Screenshots (`/preview`)** — Snap a live Playwright screenshot of your running app and receive it as a photo in chat.
- ⚡ **Dev Server Control (`/dev`)** — Start, stop, restart, and tail dev server logs (Vite, Next.js, Expo, etc.) right from Telegram.
- 🐙 **Git Shortcuts (`/git`)** — Status, diffs, commits, push, and pull with interactive buttons.
- 🔄 **Smart Model Failover** — Defaults to `gemini-3.7-flash` and seamlessly fails over to `gemini-3.5-flash-lite` if rate limits are reached.
- 🔒 **Private & Secure** — Only your Telegram User ID is allowed; zero open incoming firewall ports needed.

---

## 📱 Command Reference

| Command | Action | Example |
|:--------|:-------|:--------|
| `/app` | Launch the Mission Control Telegram Mini App | `/app` |
| `/tunnel` | Expose localhost and get a live URL | `/tunnel` or `/tunnel 5173` or `/tunnel stop` |
| `/preview` | Screenshot localhost and send photo in chat | `/preview`, `/preview /dashboard`, `/preview mobile` |
| `/dev` | Start/stop/restart dev server & view logs | `/dev start`, `/dev restart`, `/dev logs` |
| `/git` | View Git status, diffs, push, pull, log | `/git`, `/git diff`, `/git push`, `/git pull` |
| `/model` | Switch AI model dynamically | `/model flash`, `/model pro`, `/model` |
| `/project` | Switch active workspace directory | `/project C:\path\to\repo` |
| `/status` | Full system, agent, tunnel, dev server status | `/status` |
| `/reset` | Clear conversation memory & start fresh | `/reset` |
| `/help` | Show all available commands | `/help` |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+**
- **Google Antigravity SDK** (`pip install google-antigravity`)
- A **Gemini API Key** ([Google AI Studio](https://aistudio.google.com/))
- A **Telegram account**

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/Bemkin/agy-telegram-bot.git
cd agy-telegram-bot
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Create Your Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to get your bot token.

### 3. Get Your Telegram User ID

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram to get your numeric ID.

### 4. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=your_token_from_botfather
AUTHORIZED_USER_ID=your_numeric_user_id
DEFAULT_PROJECT_DIR=C:\Users\you\Projects\my-app
PROJECTS_ROOT=C:\Users\you\Projects
GEMINI_API_KEY=your_gemini_api_key
AGENT_MODEL=gemini-3.7-flash
```

*(On macOS/Linux, set paths like `DEFAULT_PROJECT_DIR=/home/you/projects/my-app`)*

### 5. Run

**Windows:**
```cmd
start_bot.bat
```
*(or `python bot.py`)*

**macOS / Linux:**
```bash
chmod +x start_bot.sh
./start_bot.sh
```
*(or `python3 bot.py`)*

Open Telegram on your phone and send `/start` to your bot! 🎉

---

## 🧪 Running Tests

Run the test suite to verify everything is working:

```bash
python tests/run_all_tests.py
```

---

## 🔒 Security

- **User Whitelist**: Only messages from `AUTHORIZED_USER_ID` are processed; all others are rejected and logged.
- **No Inbound Open Ports**: Uses long polling for Telegram and outbound Cloudflare tunnels for previewing.
- **Signed Mini App Requests**: The Mission Control API is reachable through a public tunnel, so every `/api` request must carry the Mini App's Telegram-signed `initData`. The server verifies the HMAC signature with your bot token, rejects data older than 24 hours, and only accepts `AUTHORIZED_USER_ID`. No CORS headers are sent, so other websites cannot call the API.
- **Local Machine Access**: The agent operates directly within your configured project directory.

---

## 🤝 Contributing

Community contributions are very welcome! Check out [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, coding guidelines, and suggested features (Dockerization, voice-to-code, macOS/Linux daemons, and more).

---

## 📄 License

MIT — see [LICENSE](LICENSE).
