"""
Seen-listings store for the StubHub EDC shuttle ticket monitor.

Persists alerted listings to SQLite so the bot doesn't re-alert on the same
ticket after a container restart on Railway.
"""

import logging
import sqlite3
from datetime import datetime, timezone

from scraper import Listing

logger = logging.getLogger(__name__)

_PRICE_DROP_THRESHOLD = 5.0  # minimum price decrease (dollars) to re-alert


class SeenListingsStore:
    """SQLite-backed store tracking which listings have already triggered alerts."""

    def __init__(self, db_path: str = "seen_listings.db") -> None:
        """
        Open (or create) the database, ensure the table exists, and load
        the existing seen listings into an in-memory cache.
        """
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_listings (
                name               TEXT PRIMARY KEY,
                last_alerted_price REAL NOT NULL,
                alerted_at         TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

        rows = self._conn.execute(
            "SELECT name, last_alerted_price FROM seen_listings"
        ).fetchall()
        self._cache: dict[str, float] = {name: price for name, price in rows}
        logger.info("Loaded %d seen listings from %s", len(self._cache), db_path)

    def filter_new_or_changed(self, listings: list[Listing]) -> list[Listing]:
        """
        Return only listings that should trigger an alert:
          - "new": name not previously alerted
          - "changed": price dropped >= $5 since the last alert

        Logs each skipped listing.
        """
        results: list[Listing] = []
        for listing in listings:
            if listing.name not in self._cache:
                logger.debug("New listing: %r at $%.2f", listing.name, listing.price)
                results.append(listing)
            elif self._cache[listing.name] - listing.price >= _PRICE_DROP_THRESHOLD:
                logger.debug(
                    "Price drop for %r: $%.2f → $%.2f",
                    listing.name,
                    self._cache[listing.name],
                    listing.price,
                )
                results.append(listing)
            else:
                logger.info(
                    "Skipping %r — already alerted at $%.2f, now $%.2f (no significant drop)",
                    listing.name,
                    self._cache[listing.name],
                    listing.price,
                )
        return results

    def mark_alerted(self, listings: list[Listing]) -> None:
        """
        Record each listing as alerted. Upserts into the DB and updates the
        in-memory cache. Call this after successfully sending the alert email.
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for listing in listings:
            self._conn.execute(
                """
                INSERT INTO seen_listings(name, last_alerted_price, alerted_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    last_alerted_price = excluded.last_alerted_price,
                    alerted_at         = excluded.alerted_at
                """,
                (listing.name, listing.price, now),
            )
            self._cache[listing.name] = listing.price
        self._conn.commit()
        logger.info("Marked %d listing(s) as alerted in DB", len(listings))
