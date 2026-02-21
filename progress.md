# Implementation Progress

## US-001: StubHub Scraper — COMPLETE ✅

### Key Technical Discoveries

#### 1. `page.content()` does NOT contain listing data
StubHub serves a 478KB server-rendered HTML with listing JSON embedded. After JavaScript hydration, `page.content()` returns the live React DOM (~100KB), which discards the raw JSON. **Fix:** Intercept the HTTP response body via `page.on("response", handler)` before `page.goto()` completes.

#### 2. Use the section/ticketClass-filtered URL as STUBHUB_URL
The base event URL returns all ~82 listings (all ticket types). The filtered URL pre-narrows to ~30 Mid-Strip listings:
`?quantity=2&sections=1747871%2C2037648%2C2037647%2C2037641%2C2037642%2C2037643%2C2037640&ticketClasses=14450&rows=&seats=&seatTypes=&listingQty=`
**The section/ticketClass params must also be forwarded to the pagination POST body** (`Sections`, `TicketClasses` fields) — otherwise pages 2+ return unfiltered results. Parse from URL with `urllib.parse.parse_qs`.

#### 3. Listing data location in initial HTML
Pattern: `"grid":{"items":[...], "currentPage":1, "pageSize":6, "itemsRemaining":N}`
- Fields: `sectionMapName` (name), `rawPrice` (float), `availableTickets` (int), `listingId`
- Extract by string-searching initial HTML response body, then balance brackets

#### 3. playwright-stealth v2 API change
v2.0.2 removed `stealth_async` function. New API:
```python
from playwright_stealth import Stealth
await Stealth().apply_stealth_async(page)
```

#### 4. Pagination
"Show more" triggers an in-browser POST to the same event URL. Use `page.evaluate()` fetch() so session cookies are sent automatically. POST body includes `PageVisitId` (extracted from initial HTML), `CurrentPage`, `PageSize=6`, etc.

### Files Created
- `scraper.py` — main scraper module (Listing dataclass, scrape_listings(), helpers)
- `requirements.txt` — pinned dependencies

---

---

## US-002: Filter Listings — COMPLETE ✅

- Implemented `filter_listings(listings, max_price_per_ticket)` in `filter.py`
- Five sequential filters with `logger.info` count after each step
- Verified against live data: `Mid-Strip - Depart: 6:30PM Return: 6AM` at $540/$900 correctly reaches the price filter (2 listings) and is excluded (0 matches) — bot correctly stays silent until a <$500 listing appears
- **Files created:** `filter.py`

---

---

## US-003: Seen Listings Store — COMPLETE ✅

- Implemented `SeenListingsStore` class in `store.py`
- SQLite via stdlib `sqlite3` (no new deps) — table: `seen_listings(name PK, last_alerted_price, alerted_at)`
- In-memory `dict[str, float]` cache loaded from DB on init for O(1) lookups
- `filter_new_or_changed()` returns new listings + listings with price drop ≥ $5; logs all skips
- `mark_alerted()` upserts to DB and updates cache atomically; call after email sent
- DB survives container restarts; `db_path` passed in at construction (US-006 will wire `DB_PATH` env var)
- **Files created:** `store.py`

---

## US-004: Email Notifier — COMPLETE ✅

- Created `notifier.py` with `send_alert(listings, screenshot_path, *, gmail_address, gmail_app_password, notification_email)`
- HTML email: styled table with Ticket Name (hyperlink), Price/Ticket, Total×2 columns + PT timestamp
- Plain-text fallback included in same `MIMEMultipart("alternative")` part
- Screenshot attached as `stubhub_listings.png` via `MIMEImage` when `screenshot_path` provided
- Gmail SMTP via port 587 + STARTTLS; entire send wrapped in try/except (non-fatal)
- Modified `scraper.py`: added `screenshot_path: str | None = None` param; screenshot taken just before `browser.close()` inside the try block (reuses existing authenticated session, no extra Playwright launch)
- No new dependencies (`smtplib`, `email.mime.*` stdlib; `pytz` already pinned)
- **Files created:** `notifier.py` | **Files modified:** `scraper.py`

---

## Remaining Work

- [x] US-001: StubHub scraper
- [x] US-002: Filter listings
- [x] US-003: Seen listings store (SQLite)
- [x] US-004: Email alert with HTML table + screenshot
- [x] US-005: Scheduling loop (jitter, backoff, quiet hours, auto-stop)
- [x] US-006: Environment variable configuration
- [x] US-007: Railway Dockerfile + deployment

---

## US-005: Scheduling Loop — COMPLETE ✅

- Created `main.py` — wires scraper → filter → store → notifier inside `while True` loop
- `Config` dataclass loaded from env vars via `_load_config()` (required vars raise `ValueError` on missing)
- Normal sleep: `random(base-120, base+120)` where `base = CHECK_INTERVAL_MINUTES * 60`
- Quiet hours: `random(1500, 2100)` when `QUIET_HOURS_START <= hour_pt < QUIET_HOURS_END`
- Backoff: 4-level table `[(10,20), (20,40), (45,75), (90,150)]` minutes, resets on success
- Both `RateLimitError` and generic `Exception` trigger backoff + `continue` (skips normal sleep)
- Screenshot temp file always cleaned up in `finally` block
- Auto-stop: `_date_today_pt() >= cfg.stop_date` → `sys.exit(0)`
- `KeyboardInterrupt` caught in `main()` → clean exit log + `sys.exit(0)`
- **Files created:** `main.py`

---

## US-006: Environment Variable Configuration — COMPLETE ✅

- `headless: bool` added to `Config` dataclass; parsed from `HEADLESS` env var (`!= "false"`)
- `STUBHUB_URL` and `NOTIFICATION_EMAIL` now optional with hardcoded sensible defaults
- `_parse_hour()` accepts both `"02:00"` and `"2"` integer formats for `QUIET_HOURS_*`
- Masked startup config log block: `GMAIL_APP_PASSWORD` shows only last 4 chars (`***vpel`), URL truncated to 80 chars
- `headless=cfg.headless` threaded into `scrape_listings()` call in `run_loop()`
- **Files modified:** `main.py` only

---

## US-007: Railway Dockerfile + Deployment — COMPLETE ✅

- `Dockerfile`: `python:3.11-slim` base → pip install → `playwright install --with-deps chromium` → `CMD ["python", "main.py"]`
  - `--with-deps` installs Chromium OS deps in one step (no manual apt list needed)
  - `COPY . .` placed last so pip/Playwright layers stay cached on code-only changes
- `.env.example`: documents all 11 env vars with descriptions, required/optional markers, and Railway-specific notes (SQLite ephemerality, memory caveat)
- `README.md`: overview, local setup steps, Railway deployment steps (GitHub → new project → set vars → deploy), Gmail App Password instructions, SQLite/memory notes, project structure map
- No application code changes required — logging was already stdout-only, screenshots already use `tempfile` + `finally: os.unlink`
- **Learnings:**
  - `playwright install --with-deps chromium` is the cleanest single-command approach for Docker; it internally calls `apt-get install` for all Chromium runtime deps
  - Railway Hobby plan (512 MB) may OOM with headless Chromium (~300–400 MB); Pro plan recommended
  - Railway filesystem is ephemeral — SQLite DB resets on redeploy; acceptable for short-term monitoring, Railway Volumes available for persistence if needed
- **Files created:** `Dockerfile`, `.env.example`, `README.md`

---
