"""
Listing filter for the StubHub EDC shuttle ticket monitor.

Applies all five Premier Shuttle alert criteria in sequence and logs
the count after each step.
"""

import logging

from scraper import Listing

logger = logging.getLogger(__name__)


def filter_listings(listings: list[Listing], max_price_per_ticket: float) -> list[Listing]:
    """
    Return listings that match ALL five Premier Shuttle alert criteria.

    Criteria (all must be true):
      1. Name contains "mid-strip" (case-insensitive)
      2. Name contains "6:30" (catches "6:30PM", "6:30 PM", etc.)
      3. Name does NOT start with "Standard Shuttle" (Premier only)
      4. Price < max_price_per_ticket
      5. Quantity >= 2

    Logs the surviving count after each filter step.
    """
    result = listings

    result = [l for l in result if "mid-strip" in l.name.lower()]
    logger.info("After mid-strip filter: %d listings", len(result))

    result = [l for l in result if "6:30" in l.name]
    logger.info("After departure-time filter: %d listings", len(result))

    result = [l for l in result if not l.name.lower().startswith("standard shuttle")]
    logger.info("After Premier-only filter: %d listings", len(result))

    result = [l for l in result if l.price < max_price_per_ticket]
    logger.info("After price filter (< $%.0f): %d listings", max_price_per_ticket, len(result))

    result = [l for l in result if l.quantity >= 2]
    logger.info("After quantity filter (>= 2): %d listings", len(result))

    return result
