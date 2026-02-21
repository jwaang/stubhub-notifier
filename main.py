"""
StubHub EDC Shuttle Ticket Monitor — main entry point.

Runs a polling loop that:
  1. Scrapes the StubHub listings page
  2. Filters for qualifying Mid-Strip 6:30 PM Premier Shuttle tickets
  3. Sends an email alert for any new or price-dropped listings
  4. Sleeps with jitter (quiet-hours slowdown + exponential backoff on errors)
  5. Auto-stops on the event date
"""

import asyncio
import datetime
import logging
import os
import random
import sys
from dataclasses import dataclass

import pytz
from dotenv import load_dotenv

from filter import filter_listings
from notifier import send_alert
from scraper import RateLimitError, scrape_listings
from store import SeenListingsStore

logger = logging.getLogger(__name__)

_PT = pytz.timezone("America/Los_Angeles")

_DEFAULT_STUBHUB_URL = (
    "https://www.stubhub.com/electric-daisy-carnival-las-vegas-tickets-5-15-2026/"
    "event/160232237/?quantity=2&sections=1747871%2C2037648%2C2037647%2C2037641"
    "%2C2037642%2C2037643%2C2037640&ticketClasses=14450&rows=&seats=&seatTypes=&listingQty="
)
_DEFAULT_NOTIFICATION_EMAIL = "jonathan.wang1996@gmail.com"

# Backoff sleep ranges (minutes) indexed by failure count (capped at last entry).
_BACKOFF_RANGES: list[tuple[int, int]] = [
    (10, 20),   # 1st consecutive failure
    (20, 40),   # 2nd
    (45, 75),   # 3rd
    (90, 150),  # 4th+ (cap)
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class Config:
    stubhub_url: str
    max_price_per_ticket: float
    check_interval_minutes: int
    quiet_hours_start: int   # PT hour, inclusive (0–23)
    quiet_hours_end: int     # PT hour, exclusive (0–23)
    stop_date: datetime.date
    gmail_address: str
    gmail_app_password: str
    notification_emails: list[str]
    db_path: str
    headless: bool


def _parse_hour(val: str) -> int:
    """Parse a quiet-hours value — accepts '02:00' or plain '2'."""
    return int(val.strip().split(":")[0])


def _load_config() -> Config:
    def require(key: str) -> str:
        val = os.environ.get(key, "").strip()
        if not val:
            raise ValueError(f"Required environment variable {key!r} is not set")
        return val

    return Config(
        stubhub_url=os.environ.get("STUBHUB_URL", _DEFAULT_STUBHUB_URL).strip(),
        max_price_per_ticket=float(os.environ.get("MAX_PRICE_PER_TICKET", "500")),
        check_interval_minutes=int(os.environ.get("CHECK_INTERVAL_MINUTES", "5")),
        quiet_hours_start=_parse_hour(os.environ.get("QUIET_HOURS_START", "2")),
        quiet_hours_end=_parse_hour(os.environ.get("QUIET_HOURS_END", "9")),
        stop_date=datetime.date.fromisoformat(
            os.environ.get("STOP_DATE", "2026-05-15")
        ),
        gmail_address=require("GMAIL_ADDRESS"),
        gmail_app_password=require("GMAIL_APP_PASSWORD"),
        notification_emails=[
            e.strip()
            for e in os.environ.get("NOTIFICATION_EMAIL", _DEFAULT_NOTIFICATION_EMAIL).split(",")
            if e.strip()
        ],
        db_path=os.environ.get("DB_PATH", "seen_listings.db"),
        headless=os.environ.get("HEADLESS", "true").strip().lower() != "false",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_today_pt() -> datetime.date:
    return datetime.datetime.now(_PT).date()


def _compute_sleep(cfg: Config) -> tuple[float, bool]:
    """Return (sleep_seconds, is_quiet_hours)."""
    now_hour = datetime.datetime.now(_PT).hour
    quiet = cfg.quiet_hours_start <= now_hour < cfg.quiet_hours_end
    if quiet:
        secs = random.uniform(1500, 2100)  # 25–35 min
    else:
        base = cfg.check_interval_minutes * 60
        secs = random.uniform(base - 120, base + 120)
    return secs, quiet


def _backoff_sleep_secs(backoff_level: int) -> float:
    idx = min(backoff_level - 1, len(_BACKOFF_RANGES) - 1)
    lo, hi = _BACKOFF_RANGES[idx]
    return random.uniform(lo * 60, hi * 60)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_loop(cfg: Config) -> None:
    store = SeenListingsStore(cfg.db_path)
    backoff_level = 0

    while True:
        # --- Auto-stop ---
        if _date_today_pt() >= cfg.stop_date:
            logger.info("Event date reached. Bot shutting down.")
            sys.exit(0)

        # --- Scrape → filter → alert ---
        try:
            listings = await scrape_listings(cfg.stubhub_url, headless=cfg.headless)
            filtered = filter_listings(listings, cfg.max_price_per_ticket)
            new = store.filter_new_or_changed(filtered)

            if new:
                send_alert(
                    new,
                    gmail_address=cfg.gmail_address,
                    gmail_app_password=cfg.gmail_app_password,
                    notification_emails=cfg.notification_emails,
                )
                store.mark_alerted(new)

            backoff_level = 0  # successful cycle — reset backoff

        except RateLimitError as exc:
            backoff_level = min(backoff_level + 1, len(_BACKOFF_RANGES))
            wait = _backoff_sleep_secs(backoff_level)
            logger.warning("Rate limited: %s", exc)
            logger.info(
                "Backoff level %d — sleeping %.0fs before retry", backoff_level, wait
            )
            await asyncio.sleep(wait)
            continue

        except Exception as exc:
            backoff_level = min(backoff_level + 1, len(_BACKOFF_RANGES))
            wait = _backoff_sleep_secs(backoff_level)
            logger.warning("Scrape error: %s", exc, exc_info=True)
            logger.info(
                "Backoff level %d — sleeping %.0fs before retry", backoff_level, wait
            )
            await asyncio.sleep(wait)
            continue

        # --- Sleep until next check ---
        sleep_secs, quiet = _compute_sleep(cfg)
        logger.info(
            "Sleeping %.0fs until next check (quiet hours: %s, backoff level: %d)",
            sleep_secs,
            quiet,
            backoff_level,
        )
        await asyncio.sleep(sleep_secs)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    load_dotenv()

    try:
        cfg = _load_config()
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    logger.info("=== Bot Configuration ===")
    logger.info("  STUBHUB_URL:             %s", cfg.stubhub_url[:80] + "...")
    logger.info("  MAX_PRICE_PER_TICKET:    $%.0f", cfg.max_price_per_ticket)
    logger.info("  CHECK_INTERVAL_MINUTES:  %d", cfg.check_interval_minutes)
    logger.info("  QUIET_HOURS:             %02d:00\u2013%02d:00 PT", cfg.quiet_hours_start, cfg.quiet_hours_end)
    logger.info("  STOP_DATE:               %s", cfg.stop_date)
    logger.info("  GMAIL_ADDRESS:           %s", cfg.gmail_address)
    logger.info("  GMAIL_APP_PASSWORD:      %s", "***" + cfg.gmail_app_password[-4:])
    logger.info("  NOTIFICATION_EMAIL:      %s", ", ".join(cfg.notification_emails))
    logger.info("  DB_PATH:                 %s", cfg.db_path)
    logger.info("  HEADLESS:                %s", cfg.headless)
    logger.info("=========================")

    try:
        asyncio.run(run_loop(cfg))
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
