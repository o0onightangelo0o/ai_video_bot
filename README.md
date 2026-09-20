# 🎬 AI Video Telegram Bot

بوت Telegram يحوّل الوصف النصي إلى فيديو بالذكاء الاصطناعي — Async بالكامل، مع طابور انتظار،
حدّ استخدام، Fallback تلقائي بين المزوّدين، ودعم العربية/الإنجليزية.

A fully asynchronous Telegram bot (aiogram 3) that turns text prompts into AI‑generated
videos, with job queue, rate limiting, provider fallback, SQLite persistence and
bilingual (AR/EN) UI. Runs in **polling** mode locally and **webhook** mode in production.

---

## ✨ Features

| Feature | Details |
|---|---|
| Wizard | `/generate` → prompt → aspect (16:9 / 9:16 / 1:1) → duration (5/8/10s) → style → confirm |
| Providers | `replicate`, `fal`, `mock` — priority list in `PROVIDER_ORDER`, automatic fallback |
| Async polling | Non‑blocking job polling with timeout & cancellation |
| Queue | `asyncio.Queue` + N workers, persisted in SQLite (recovers after restart) |
| Rate limit | Sliding window, `MAX_REQUESTS_PER_HOUR` per user (failed/cancelled jobs don't count) |
| Protection | Prompt length + banned‑word filter, blacklist (`/ban`, `/unban`) |
| Delivery | Sends as **Video** (falls back to Document, then to a link if > 50 MB) with caption |
| Admin | `/stats`, `/ban <id> [reason]`, `/unban <id>` |
| i18n | Auto‑detects Telegram language, `/lang` to switch |
| Logging | loguru → console + daily rotating zipped files in `logs/` |
| Health | `GET /health` in webhook mode (for UptimeRobot / platform checks) |

## 📁 Structure

```
ai_video_bot/
├── bot/
│   ├── main.py            # entry point (polling / webhook)
│   ├── handlers.py        # commands, FSM wizard, callbacks, delivery
│   ├── keyboards.py       # inline keyboards
│   ├── video_service.py   # providers + fallback orchestrator
│   ├── queue_manager.py   # async workers
│   ├── rate_limiter.py    # per-user sliding window
│   ├── database.py        # aiosqlite layer
│   ├── i18n.py            # AR/EN texts
│   └── config.py          # .env loader
├── data/                  # SQLite (volume)
├── logs/                  # rotating logs (volume)
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## 🚀 Quick start (local)

```bash
git clone <your-repo> ai_video_bot && cd ai_video_bot
cp .env.example .env               # then edit BOT_TOKEN and ADMIN_ID
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m bot.main                 # MODE=polling by default
```

Open Telegram → `/start` → `/generate`.
With `PROVIDER_ORDER=mock` the bot returns a sample clip after ~20 s at **zero cost** —
perfect for testing the full flow. Type a prompt containing the word `FAIL` to test the
fallback path.

### One-command Docker run

```bash
cp .env.example .env && nano .env
docker compose up -d --build
docker compose logs -f bot
```

---

## 🔑 Getting the keys

| Key | Where |
|---|---|
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `ADMIN_ID` | [@userinfobot](https://t.me/userinfobot) → your numeric id |
| `REPLICATE_API_KEY` | https://replicate.com/account/api-tokens (trial credit on signup) |
| `FAL_API_KEY` | https://fal.ai/dashboard/keys |

Enable real providers by editing `.env`:

```env
PROVIDER_ORDER=replicate,fal,mock
REPLICATE_API_KEY=r8_xxx
FAL_API_KEY=xxx
```

> ⚠️ No video API has a permanent free tier. Replicate and fal.ai are pay‑as‑you‑go
> (roughly $0.05–0.50 per clip depending on the model). Keep `MAX_REQUESTS_PER_HOUR`
> low and keep `mock` last in the list so users get a clear message instead of silence.

---

## ☁️ Deploy 24/7 for free on **Koyeb** (recommended)

**Why Koyeb?** Its free instance **never sleeps**, needs **no credit card**, builds
straight from a `Dockerfile`, and gives you a public HTTPS URL — exactly what webhook
mode needs. (Railway's free plan is now a 30‑day trial; Render's free web service sleeps
after 15 min and needs an external pinger.)

### Step 1 — Push the code to GitHub

```bash
git init && git add . && git commit -m "AI video bot"
git remote add origin https://github.com/<you>/ai_video_bot.git
git push -u origin main
```
(`.env` is git‑ignored — never commit it.)

### Step 2 — Create the Koyeb service

1. Sign up at https://app.koyeb.com (GitHub login).
2. **Create Service → GitHub → select the repo**.
3. Builder: **Dockerfile** (auto‑detected).
4. Instance type: **Free** (eco / nano), Region: Frankfurt (closest to Lebanon).
5. Exposed port: **8000**, protocol HTTP.
6. Health check: HTTP path `/health`, port 8000.
7. **Environment variables** (Settings → Environment):

   | Name | Value |
   |---|---|
   | `BOT_TOKEN` | *(secret)* |
   | `ADMIN_ID` | your id |
   | `MODE` | `webhook` |
   | `WEBHOOK_BASE_URL` | `https://<app-name>-<org>.koyeb.app` *(shown after first deploy — set it, then redeploy)* |
   | `WEBHOOK_SECRET` | any random string (`openssl rand -hex 16`) |
   | `PROVIDER_ORDER` | `mock` (or `replicate,mock` once you add a key) |
   | `REPLICATE_API_KEY` | *(secret, optional)* |
   | `MAX_REQUESTS_PER_HOUR` | `3` |
   | `DB_PATH` | `/app/data/bot.db` |
   | `LOG_DIR` | `/app/logs` |

8. Click **Deploy**. Watch the logs; you should see:
   `Webhook set to https://…koyeb.app/telegram/webhook` and `Bot @yourbot started in webhook mode`.

### Step 3 — Verify

```bash
curl https://<app>.koyeb.app/health          # {"ok": true, "queue": 0}
curl "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo"
```
Send `/start` in Telegram — instant reply.

### Step 4 — Persistence note

Koyeb's free instance disk is ephemeral: the SQLite file resets on redeploy
(users/jobs history and the rate‑limit window). That's acceptable for a hobby bot; if you
need durability, mount a Koyeb volume (paid) or point `DB_PATH` at a Litestream/Turso
setup.

---

## 🔁 Render (currently deployed) + UptimeRobot

1. New **Web Service** → connect repo → Runtime **Docker** → Free plan.
2. Same env vars as above, `WEBHOOK_BASE_URL=https://<service>.onrender.com`.
3. Render sleeps after 15 min idle → create a free monitor at https://uptimerobot.com
   hitting `https://<service>.onrender.com/health` every 5 min.
4. Add a **Persistent Disk** (free 1 GB) mounted at `/app/data` to keep SQLite.

## 🖥 Alternative: your own VPS

```bash
MODE=polling docker compose up -d
```
No public URL needed; `data/` and `logs/` are mounted as volumes.

---

## 🧪 Testing checklist

- [x] `/start` welcome in Arabic when Telegram language is `ar`, English otherwise
- [x] `/generate` wizard with inline keyboards, `/cancel` at any step
- [x] 4th request within an hour → rate‑limit message with minutes remaining
- [x] Prompt with word `FAIL` on mock → provider fails → fallback → clear error, quota not consumed
- [x] Cancel a running job via button or `/cancel`
- [x] `/stats` for admin only; `/ban` blocks the user immediately
- [x] Restart the container mid‑job → job is re‑queued automatically
- [x] Webhook rejects requests without the secret token (HTTP 401)

## 🛠 Operations

```bash
docker compose logs -f bot            # live logs
docker compose restart bot
sqlite3 data/bot.db "SELECT id,status,provider FROM jobs ORDER BY id DESC LIMIT 10;"
```

## 🔒 Security

* All secrets come from environment variables; nothing is hard‑coded.
* Webhook path is protected by `X-Telegram-Bot-Api-Secret-Token`.
* Container runs as a non‑root user.
* Regenerate your `BOT_TOKEN` in BotFather if it was ever exposed.

## 📄 License

MIT
