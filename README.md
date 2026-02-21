# StubHub EDC Shuttle Monitor

A Python bot that watches StubHub for **EDC Las Vegas 2026 Premier Shuttle** tickets (Mid-Strip, 6:30 PM departure) under a configurable price threshold and sends consolidated Gmail alerts with a screenshot attachment.

---

## How it works

1. Every ~5 minutes the bot loads the StubHub event page via headless Chromium (with stealth headers to avoid blocks).
2. It filters listings to only `Mid-Strip – Depart: 6:30PM Return: 6AM` Premier Shuttle tickets priced below `MAX_PRICE_PER_TICKET` with ≥ 2 available.
3. New listings (or existing ones with a price drop ≥ $5) trigger a Gmail alert with an HTML table and a page screenshot.
4. Seen listings are persisted to SQLite so repeat alerts are suppressed.
5. Quiet hours (2–9 AM PT by default) slow polling to 25–35 min intervals.
6. The bot auto-exits on the event date (May 15, 2026).

---

## Local setup

**Prerequisites:** Python 3.11+, pip

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd stubhub-notifier

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install the Chromium browser (required by Playwright)
playwright install chromium

# 4. Configure environment variables
cp .env.example .env
# Open .env and fill in GMAIL_ADDRESS and GMAIL_APP_PASSWORD at minimum

# 5. Run the bot
python main.py
```

The bot logs to stdout. Press `Ctrl+C` to stop.

---

## Railway deployment

Railway runs the bot 24/7 using the included `Dockerfile`. Chromium is installed at build time — no manual setup needed on the server.

### Steps

1. **Push this repo to GitHub** (make sure `.env` is in `.gitignore` — it is by default).

2. **Create a new Railway project**
   - Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo.
   - Select your repository. Railway will detect the `Dockerfile` automatically.

3. **Set environment variables** in Railway dashboard → your service → *Variables* tab:

   | Variable | Required | Description |
   |----------|----------|-------------|
   | `GMAIL_ADDRESS` | **Yes** | Gmail address that sends alerts |
   | `GMAIL_APP_PASSWORD` | **Yes** | Gmail App Password (not your login password) |
   | `NOTIFICATION_EMAIL` | No | Alert recipient — defaults to `GMAIL_ADDRESS` |
   | `MAX_PRICE_PER_TICKET` | No | Max $/ticket to alert on (default: `500`) |
   | `CHECK_INTERVAL_MINUTES` | No | Polling interval in minutes (default: `5`) |
   | `QUIET_HOURS_START` | No | Start of slow-poll window, PT hour (default: `2`) |
   | `QUIET_HOURS_END` | No | End of slow-poll window, PT hour (default: `9`) |
   | `STOP_DATE` | No | Auto-exit date ISO (default: `2026-05-15`) |
   | `STUBHUB_URL` | No | Override the StubHub listing URL |
   | `DB_PATH` | No | SQLite file path (default: `seen_listings.db`) |
   | `HEADLESS` | No | Set `false` for headed browser — leave `true` on Railway |

4. **Deploy** — click *Deploy* or push a commit. Railway builds the Docker image (≈ 3–5 minutes on first build due to Chromium download) and starts the container.

5. **Monitor** — view live logs in Railway dashboard → *Deployments* → your build → *Logs*.

### Gmail App Password

1. Enable 2-Step Verification on your Google account.
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
3. Create an app password (name it anything, e.g. "StubHub Bot").
4. Copy the 16-character password (shown once) into `GMAIL_APP_PASSWORD`.

---

## Notes

### SQLite on Railway

Railway's filesystem is **ephemeral** — the `seen_listings.db` file is lost on every redeploy or container restart. The bot will re-alert for any listings that still qualify after a restart. This is acceptable for short-term ticket monitoring.

For persistent state across restarts, attach a **Railway Volume** and set `DB_PATH` to a path inside it (e.g. `/data/seen_listings.db`).

### Memory

Headless Chromium uses ~300–400 MB RAM. Railway's **Hobby plan (512 MB)** may be tight. If you see OOM crashes, upgrade to the **Pro plan** (~$20/month, 8 GB RAM).

---

## Project structure

```
.
├── main.py          # Entry point — config, scheduling loop, orchestration
├── scraper.py       # Playwright scraper — fetches & parses StubHub listings
├── filter.py        # Listing filter — Mid-Strip, 6:30PM, price, quantity
├── store.py         # SQLite store — deduplicates alerts across runs
├── notifier.py      # Gmail SMTP email with HTML table + screenshot
├── requirements.txt # Pinned Python dependencies
├── Dockerfile       # Railway/Docker build definition
└── .env.example     # Environment variable documentation
```
