# PRD: StubHub EDC Shuttle Ticket Monitor Bot

## Introduction

A Python bot that monitors a StubHub event listing page at irregular intervals and sends an email alert when specific Premier Shuttle tickets matching defined criteria become available. The bot runs on Railway until the event date (May 15, 2026).

**Target URL:** https://www.stubhub.com/electric-daisy-carnival-las-vegas-tickets-5-15-2026/event/160232237/?quantity=2&sections=1747871%2C2037648%2C2037647%2C2037641%2C2037642%2C2037643%2C2037640&ticketClasses=14450&rows=&seats=&seatTypes=&listingQty=

*(Pre-filtered to Mid-Strip section + Premier Shuttle ticket class, reducing results from ~82 total event listings to ~30 Mid-Strip listings per check)*

**Problem:** The specific ticket (Mid-Strip Premier Shuttle departing at 6:30 PM) does not currently exist on StubHub. Rather than checking manually, the bot watches the page and notifies the user the moment a qualifying listing appears.

### Polling Philosophy

> "The safest scraper is the one that simply makes fewer requests."

This bot is a **low-frequency monitor, not an aggressive scraper.** Ticket inventory on StubHub does not change millisecond-to-millisecond — a new listing appearing within a 5–10 minute window is perfectly acceptable latency. The strategy is:

1. **Poll infrequently** — base interval of 5 minutes is already conservative
2. **Heavy jitter** — actual sleep varies by ±2 minutes so the pattern is never clock-regular
3. **Automatic backoff** — on any rate-limit (HTTP 429) or error, exponentially increase delay up to 4 hours
4. **Quiet hours** — drop to one check per 30 minutes overnight (2 AM – 9 AM PT) when new listings rarely appear
5. **Reduce request count** — fewer requests is safer than disguising them; all mitigations serve that goal

---

## Goals

- Monitor the StubHub event page at irregular intervals (base: 5 min ± 2 min jitter) without user intervention
- Filter listings to surface only tickets matching all five criteria simultaneously
- Send a single consolidated email alert (not one per ticket) when new matches are found
- Avoid duplicate alerts for listings already seen (only re-alert on price drops)
- Back off automatically on rate-limits and reduce polling overnight to avoid detectable patterns
- Run reliably on Railway and auto-stop on May 15, 2026
- Keep all thresholds configurable via environment variables with no code changes required

---

## Ticket Matching Criteria

All four conditions must be true for a listing to trigger an alert:

| Criterion | Value | Notes |
|---|---|---|
| Location | Contains "mid-strip" (case-insensitive) | e.g. "Mid-Strip - Depart: 6:30PM Return: 4AM" |
| Departure time | 6:30 PM | Return time: any |
| Ticket type | Premier Shuttle only | Standard shuttles are named "Standard Shuttle - [Location]" and must be excluded |
| Price per ticket | < `MAX_PRICE_PER_TICKET` (default $500) | Price shown on StubHub listing IS per-ticket |
| Quantity available | ≥ 2 tickets | Must be enough for a pair |

**How to distinguish Premier vs Standard on StubHub:**
- Standard: `"Standard Shuttle - Mid-Strip"` — no depart time in name
- Premier: `"Mid-Strip - Depart: 6:30PM Return: 4AM"` — depart/return time in name

---

## User Stories

### US-001: Scrape StubHub Ticket Listings
**Description:** As the bot, I need to load the StubHub event page and extract all ticket listings so I can evaluate them against the filter criteria.

**Acceptance Criteria:**
- [ ] Uses Playwright (headless Chromium) to render the full page, handling JS-rendered content
- [ ] Applies `playwright-stealth` to reduce Cloudflare bot detection
- [ ] Sets a realistic `User-Agent` header matching a modern desktop browser
- [ ] Clicks "Show more" button in a loop until no more button exists, with a random pause of `sleep(random(3, 8))` seconds between each click to avoid rapid sequential requests
- [ ] Extracts from each listing: name (title), price per ticket, listing URL (if available), available quantity
- [ ] Returns a structured list of listing objects (name, price, url, quantity)
- [ ] Logs the number of listings found at each check
- [ ] On HTTP 429 response: raises a `RateLimitError` that triggers the backoff system (US-005); does NOT simply retry immediately
- [ ] On Cloudflare block or other page error: logs warning and raises an error so the backoff system handles the retry delay

---

### US-002: Filter Listings Against Criteria
**Description:** As the bot, I need to filter scraped listings against all matching criteria so I only alert on genuinely qualifying tickets.

**Acceptance Criteria:**
- [ ] Filters listings where name contains "mid-strip" (case-insensitive)
- [ ] Filters listings where name contains "6:30" or "6:30PM" departure time
- [ ] Excludes listings where name starts with "Standard Shuttle" (these are not Premier)
- [ ] Filters listings where price < `MAX_PRICE_PER_TICKET` environment variable
- [ ] Filters listings where available quantity ≥ 2
- [ ] Returns only listings passing ALL five checks
- [ ] Logs each filter step with count (e.g. "After mid-strip filter: 3 listings, after depart filter: 1 listing")

---

### US-003: Track Seen Listings to Avoid Duplicate Alerts
**Description:** As the bot, I need to remember which listings I've already alerted on so I don't spam the user with repeated emails for the same ticket. Seen listings are persisted to SQLite so the state survives container restarts on Railway.

**Acceptance Criteria:**
- [ ] Uses a SQLite database (`seen_listings.db`) to persist alerted listings across restarts
- [ ] Table schema: `seen_listings(name TEXT PRIMARY KEY, last_alerted_price REAL, alerted_at TEXT)`
- [ ] Database file path configurable via `DB_PATH` env var (default: `seen_listings.db`)
- [ ] On startup, loads existing seen listings from the database into an in-memory cache for fast lookups
- [ ] A listing is considered "new" if its name has never been alerted on before (not in DB)
- [ ] A listing is considered "changed" if its price has dropped since the last alert (price decrease ≥ $5)
- [ ] Only listings that are "new" OR "changed" trigger an email
- [ ] After sending an alert, upserts each alerted listing into the DB with the current price and timestamp
- [ ] Logs when a listing is skipped due to being a duplicate with no price change

---

### US-004: Send Consolidated Email Alert
**Description:** As the user, I want to receive one email per check cycle summarizing all new matching tickets so I can quickly decide whether to buy.

**Acceptance Criteria:**
- [ ] Sends email only when ≥ 1 new/changed matching listing exists
- [ ] Sends a single email containing ALL new matching listings (not one email per listing)
- [ ] Email subject: `"🎡 EDC Shuttle Alert: [N] matching ticket(s) found – Mid-Strip 6:30PM"`
- [ ] Email body (HTML) contains:
  - Table of matching listings with columns: Ticket Name | Price Per Ticket | Direct URL
  - If listing URL is available, ticket name is a hyperlink to the StubHub listing
  - Total price for 2 tickets shown next to per-ticket price
  - Timestamp of when the check was run (US/Pacific timezone)
- [ ] Email body (plain text fallback) also included for non-HTML clients
- [ ] Screenshot of the current StubHub listings page attached as `stubhub_listings.png`
- [ ] Sends to `NOTIFICATION_EMAIL` environment variable
- [ ] Uses Gmail SMTP with app password via `smtplib` (credentials from env vars `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD`)
- [ ] On email send failure: logs error with full exception, does NOT crash the bot

---

### US-005: Scheduling Loop with Jitter, Backoff, Quiet Hours, and Auto-Stop
**Description:** As the bot, I need to run checks at irregular intervals, back off when rate-limited, slow down overnight, and automatically stop on the event date — so it behaves like a human occasionally checking a website, not a clock-regular scraper.

**Normal interval (active hours):**
```
sleep(random(CHECK_INTERVAL_MINUTES * 60 - 120, CHECK_INTERVAL_MINUTES * 60 + 120))
```
Default: `random(180, 420)` seconds → actual gaps between 3 and 7 minutes

**Quiet hours interval (overnight):**
```
sleep(random(1500, 2100))  # 25–35 minutes
```
Applied between `QUIET_HOURS_START` and `QUIET_HOURS_END` (default: 2:00 AM – 9:00 AM US/Pacific)

**Backoff schedule (on `RateLimitError` or scrape failure):**

| Failure # | Wait before retry |
|---|---|
| 1st | `random(10, 20)` minutes |
| 2nd | `random(20, 40)` minutes |
| 3rd | `random(45, 75)` minutes |
| 4th+ | `random(90, 150)` minutes (cap) |

Backoff counter resets to zero after any successful cycle.

**Acceptance Criteria:**
- [ ] Normal sleep uses `random(base - 120, base + 120)` seconds where base = `CHECK_INTERVAL_MINUTES * 60`
- [ ] At the start of each sleep, checks whether current time (US/Pacific) falls in quiet hours; if so, uses the 25–35 minute sleep range instead of the normal range
- [ ] `QUIET_HOURS_START` and `QUIET_HOURS_END` are configurable env vars (default `02:00` and `09:00`)
- [ ] On `RateLimitError` (HTTP 429 or Cloudflare block): increments backoff counter and sleeps the corresponding backoff duration before next attempt
- [ ] On successful scrape: resets backoff counter to 0
- [ ] Logs the computed sleep duration before sleeping: e.g. `"Sleeping 312s until next check (quiet hours: False, backoff level: 0)"`
- [ ] Checks current date at the start of each cycle; exits cleanly if date ≥ `STOP_DATE` (default: `2026-05-15`)
- [ ] On clean stop: logs `"Event date reached. Bot shutting down."` and exits with code 0
- [ ] Handles `KeyboardInterrupt` gracefully (logs `"Bot stopped by user."` and exits cleanly)

---

### US-006: Configuration via Environment Variables
**Description:** As the operator, I need all thresholds and credentials to be configurable without changing code so I can adjust settings via Railway's dashboard.

**Acceptance Criteria:**
- [ ] All config loaded from environment variables at startup
- [ ] Required vars (bot crashes with clear message if missing): `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`
- [ ] Optional vars with defaults:

| Variable | Default | Description |
|---|---|---|
| `STUBHUB_URL` | (the EDC event URL) | Event page to monitor |
| `MAX_PRICE_PER_TICKET` | `500` | Max price per ticket in USD |
| `CHECK_INTERVAL_MINUTES` | `5` | Base minutes between checks (actual sleep = base ± 2 min jitter) |
| `NOTIFICATION_EMAIL` | `jonathan.wang1996@gmail.com` | Alert recipient |
| `STOP_DATE` | `2026-05-15` | Date to auto-stop (YYYY-MM-DD) |
| `QUIET_HOURS_START` | `02:00` | Start of low-frequency window (US/Pacific, 24h format) |
| `QUIET_HOURS_END` | `09:00` | End of low-frequency window (US/Pacific, 24h format) |
| `HEADLESS` | `true` | Set false for local debugging |

- [ ] Startup log prints all config values (masking credential values) so it's easy to verify settings in Railway logs

---

### US-007: Railway Deployment
**Description:** As the operator, I need to deploy the bot to Railway so it runs 24/7 without a personal machine.

**Acceptance Criteria:**
- [ ] `Dockerfile` present in repo root that:
  - Uses `python:3.11-slim` base
  - Installs system dependencies for Chromium (required by Playwright)
  - Installs Python dependencies from `requirements.txt`
  - Runs `playwright install chromium` during build
  - Sets `CMD ["python", "main.py"]`
- [ ] `requirements.txt` includes: `playwright`, `playwright-stealth`, `python-dotenv`, `Pillow` (for screenshot handling), `pytz`
- [ ] `.env.example` file documents all environment variables with example values
- [ ] `README.md` includes step-by-step setup: local run instructions, Railway deploy instructions, how to set env vars in Railway dashboard
- [ ] Bot logs to stdout only (Railway captures stdout for its logging dashboard)
- [ ] No local file writes required for production operation (screenshots sent via email attachment, not saved to disk permanently)

---

## Functional Requirements

- **FR-1:** Bot must use Playwright with headless Chromium to render the StubHub page (plain HTTP requests will not work due to Cloudflare protection and JavaScript-rendered content)
- **FR-2:** Bot must expand all listings by clicking "Show more" in a loop with a `random(3, 8)` second pause between each click, until the button no longer appears
- **FR-3:** Price extracted from listings must be parsed as a float (strip `$`, commas, and "incl. fees" text)
- **FR-4:** Listing URL must be extracted if the listing element contains an `href` or `<a>` tag; otherwise fall back to the base event URL
- **FR-5:** Email must use both HTML and plain-text MIME parts (multipart/alternative) for compatibility
- **FR-6:** Screenshot must be taken AFTER all "Show more" clicks so the full listing is visible
- **FR-7:** All exceptions during a scrape cycle must be caught and classified as either `RateLimitError` (triggers backoff) or general error (logged, cycle skipped, normal interval resumes) — the bot must never crash permanently
- **FR-8:** Bot must log at the INFO level by default; structured log lines with timestamp, level, and message
- **FR-9:** Backoff state (counter + current delay) must be logged every cycle so Railway logs make it obvious when the bot is in a backoff state
- **FR-10:** During quiet hours, the bot still runs checks — it only extends the sleep interval between checks; it does NOT skip checks entirely

---

## Non-Goals (Out of Scope)

- No automatic ticket purchasing — this is an alert-only system
- No web dashboard or admin UI
- No SMS/push notifications — email only
- No complex database — SQLite only, for seen-listing persistence across restarts (no Postgres, Redis, etc.)
- No monitoring of multiple events or multiple StubHub URLs simultaneously
- No price history tracking or charting
- No Telegram/Slack/Discord integrations
- No proxy rotation or residential IP management

---

## Technical Considerations

### Scraping Strategy
StubHub uses **Next.js App Router with React Server Components (RSC)**. The ticket data is server-rendered HTML — there is no simple public JSON API to call. Playwright is required to execute JavaScript and render the page. Key observations:
- Listings appear under `[data-testid="listings-container"]`
- Text content of listings is unobfuscated and human-readable
- The "Show more" button loads additional listings without page navigation
- New listings are appended to the same container

### Anti-Bot Mitigations

The core principle: **reduce request count rather than disguise requests.** Every measure below either cuts the number of requests or makes timing less predictable — not just spoofs headers.

| Mitigation | Implementation |
|---|---|
| Infrequent polling | Base 5-min interval; active hours only via quiet hours logic |
| Heavy jitter | `random(base - 120, base + 120)` seconds; never a fixed schedule |
| Overnight slowdown | 25–35 min intervals between 2–9 AM PT |
| Intra-page jitter | `random(3, 8)` second pause between each "Show more" click |
| Exponential backoff | 10→20→45→90 min on rate-limit signals (HTTP 429 / Cloudflare block) |
| Stealth fingerprinting | `playwright-stealth` patches `navigator.webdriver` and related APIs |
| Realistic User-Agent | Chrome 124 on macOS, kept up to date in code |

### Email Provider
Gmail SMTP with an App Password (not the account password). User must:
1. Enable 2FA on Google account
2. Create an App Password at https://myaccount.google.com/apppasswords
3. Set `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` env vars

### Railway Deployment Notes
- Railway will build the Dockerfile on push to `main`
- Playwright's Chromium install (~300MB) happens at build time, not runtime
- Memory: Chromium requires ~300-500MB RAM. Railway Hobby plan ($5/month) provides 512MB — may need to upgrade to Pro ($20/month) for headroom
- Railway's free tier is NOT suitable (limited to 500 hours/month)

---

## Success Metrics

- Bot runs continuously for 30+ days without manual intervention or crashes
- No missed alerts: every qualifying listing that appears triggers an email within 10 minutes (active hours) or 40 minutes (quiet hours)
- No false positives: Standard Shuttle Mid-Strip listings do not trigger alerts
- Email delivered within 60 seconds of a matching listing being detected
- Zero HTTP 429 responses during normal operation (backoff kicks in before sustained rate-limiting)

---

## Open Questions

1. **Playwright memory on Railway Hobby:** If RAM usage exceeds 512MB, should we upgrade to Railway Pro or explore a lighter scraping approach (e.g. attempt direct HTTP with cloudscraper first, fall back to Playwright)?
2. **Gmail sending limits:** Gmail SMTP allows ~500 emails/day. With jitter and quiet hours, actual checks ≈ 180–220/day — well within limits. A 30-minute minimum cooldown between emails (even if new matches appear) is recommended to prevent alert fatigue if multiple new listings appear in quick succession. Should this cooldown be added?
3. **Listing URL availability:** The current page does not clearly expose individual listing deep-links in the DOM. The fallback (base event URL) is functional but not ideal. Should we investigate StubHub's internal API (`/jsa/v1/events` endpoint) for richer listing data including direct URLs?
4. ~~**Restarting the bot resets seen-listing memory.**~~ **Resolved:** SQLite persistence added in US-003. The `seen_listings.db` file survives Railway container restarts (Railway provides persistent volumes on Hobby/Pro plans — mount the DB at a persistent path).
