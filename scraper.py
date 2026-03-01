"""
StubHub ticket listing scraper.

Extracts all ticket listings from a StubHub event page using:
1. Playwright (headless Chromium) to load the page and bypass Cloudflare
2. Embedded JSON in the initial HTML for page 1 of listings
3. In-browser fetch() POSTs for subsequent pages (preserves session cookies)
"""

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Page, async_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Maximum listings pages to fetch.
# The POST pagination API starts with a higher itemsRemaining count than the
# initial HTML (it returns ShowAllTickets=True inventory). With 6 items/page
# and up to ~100 listings, 20 pages is a safe cap.
_MAX_PAGES = 20


class RateLimitError(Exception):
    """Raised when StubHub returns HTTP 429 or a Cloudflare challenge page."""


@dataclass
class Listing:
    name: str
    price: float
    url: str
    quantity: int
    is_all_in: bool = True  # False means rawPrice is pre-fee; True means price includes all fees


async def scrape_listings(
    url: str,
    headless: bool = True,
) -> list[Listing]:
    """
    Load the StubHub event page and return all visible ticket listings.

    Args:
        url: StubHub event URL (with optional section/ticketClass filter params).
        headless: Whether to launch Chromium in headless mode.

    Raises:
        RateLimitError: On HTTP 429 or Cloudflare/WAF challenge detection.
        Exception: On unexpected page load failures.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=[
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        try:
            # --- Capture the raw initial HTTP response body ---
            # StubHub embeds listing JSON in the server-rendered HTML, but after
            # JavaScript hydration page.content() returns the live React DOM which
            # no longer contains the raw JSON. We must capture the response body
            # before JS runs.
            raw_html_holder: list[str] = []

            async def _capture_main_response(response):
                if raw_html_holder:
                    return  # already captured
                event_path = url.split("?")[0].rstrip("/").split("/")[-1]  # e.g. "160232237"
                if event_path in response.url:
                    try:
                        body = await response.body()
                        raw_html_holder.append(body.decode("utf-8", errors="replace"))
                    except Exception:
                        pass

            page.on("response", _capture_main_response)

            # --- Load the page ---
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            if response and response.status == 429:
                raise RateLimitError(f"HTTP 429 received from {url}")

            await _check_for_blocks(page)

            # Wait for the listings container to confirm the page rendered.
            # Use Locator API (not deprecated wait_for_selector) with state="attached"
            # to avoid false timeouts from React hydration detach/reattach cycles.
            try:
                await page.locator('[data-testid="listings-container"]').wait_for(
                    state="attached", timeout=15_000
                )
            except Exception:
                logger.warning("Listings container not found within 15s timeout")
                raise

            # --- Extract page 1 from the raw response HTML ---
            # Use captured response body; fall back to page.content() if not captured.
            html = raw_html_holder[0] if raw_html_holder else await page.content()
            if not raw_html_holder:
                logger.warning("Raw response not captured; falling back to page.content()")
            listings, page_state = _extract_from_html(html, url)
            logger.debug(
                "Page 1: extracted %d listings, itemsRemaining=%d",
                len(listings),
                page_state.get("itemsRemaining", 0),
            )

            # --- Fetch subsequent pages while items remain ---
            current_page = 1
            while page_state.get("itemsRemaining", 0) > 0 and current_page < _MAX_PAGES:
                sleep_secs = random.uniform(3, 8)
                logger.debug("Sleeping %.1fs before fetching page %d", sleep_secs, current_page + 1)
                await asyncio.sleep(sleep_secs)

                current_page += 1
                page_listings, page_state = await _fetch_page(page, url, page_state, current_page)
                if not page_listings:
                    logger.debug("Page %d returned 0 listings — stopping pagination", current_page)
                    break
                listings.extend(page_listings)
                logger.debug(
                    "Page %d: extracted %d listings, itemsRemaining=%d",
                    current_page,
                    len(page_listings),
                    page_state.get("itemsRemaining", 0),
                )

            # Deduplicate by (name, price) — same listing shouldn't appear twice
            seen: set[tuple[str, float]] = set()
            deduped: list[Listing] = []
            for listing in listings:
                key = (listing.name, listing.price)
                if key not in seen:
                    seen.add(key)
                    deduped.append(listing)

            logger.info("Found %d listings (%d after dedup)", len(listings), len(deduped))
            return deduped

        finally:
            await browser.close()


async def _check_for_blocks(page: Page) -> None:
    """Detect Cloudflare challenges, CAPTCHA, and access-denied pages."""
    title = await page.title()
    title_lower = title.lower()

    if "just a moment" in title_lower or "cloudflare" in title_lower:
        raise RateLimitError(f"Cloudflare challenge detected (title: {title!r})")

    try:
        body_text = await page.inner_text("body")
    except Exception:
        body_text = ""

    body_lower = body_text.lower()
    if "access denied" in body_lower or "captcha" in body_lower:
        raise RateLimitError("Access denied or CAPTCHA detected on page")


def _extract_from_html(html: str, base_url: str) -> tuple[list[Listing], dict]:
    """
    Parse the embedded JSON blob from StubHub's server-rendered HTML.

    StubHub embeds listing data in a JavaScript variable like:
        "grid":{"items":[...], "currentPage":1, "pageSize":6, "itemsRemaining":16}

    Returns:
        (listings, page_state) where page_state contains pagination info.
    """
    # Find the start of the items array
    grid_marker = '"grid":{"items":['
    idx = html.find(grid_marker)
    if idx == -1:
        logger.warning("Could not find embedded grid JSON in page HTML")
        return [], {"itemsRemaining": 0}

    # Extract the items array by balancing brackets
    items_start = idx + len('"grid":{"items":') # points to the '['
    depth = 0
    items_end = items_start
    for i in range(items_start, min(items_start + 300_000, len(html))):
        c = html[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                items_end = i + 1
                break

    if items_end == items_start:
        logger.warning("Could not find closing bracket for items array")
        return [], {"itemsRemaining": 0}

    try:
        items_raw: list[dict] = json.loads(html[items_start:items_end])
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse embedded items JSON: %s", exc)
        return [], {"itemsRemaining": 0}

    # Extract pagination state from the JSON following the items array.
    # These fields ("currentPage", "pageSize", "itemsRemaining") live in the
    # same grid object but ~14 000 chars after the items array ends, so search
    # a 20 000-char window to be safe.
    after_items = html[items_end : items_end + 20_000]
    page_state: dict = {}

    for field in ("currentPage", "pageSize", "itemsRemaining"):
        m = re.search(rf'"{field}":(\d+)', after_items)
        if m:
            page_state[field] = int(m.group(1))

    # Extract PageVisitId — needed for POST pagination requests
    pv_match = re.search(r'"PageVisitId"\s*:\s*"([^"]+)"', html)
    if not pv_match:
        # Try alternate casing
        pv_match = re.search(r'"pageVisitId"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
    if pv_match:
        page_state["PageVisitId"] = pv_match.group(1)
    else:
        # Generate a fallback UUID if not found
        import uuid
        page_state["PageVisitId"] = str(uuid.uuid4()).upper()
        logger.debug("PageVisitId not found in HTML, generated: %s", page_state["PageVisitId"])

    listings = _parse_items(items_raw, base_url)
    return listings, page_state


async def _fetch_page(
    page: Page, base_url: str, page_state: dict, page_num: int
) -> tuple[list[Listing], dict]:
    """
    Fetch a subsequent page of listings via in-browser POST request.

    Uses page.evaluate() so that session cookies and headers are sent
    automatically by the browser context.
    """
    # Strip query params from base_url for the POST target URL
    parsed = urlparse(base_url)
    post_url = parsed._replace(query="").geturl()

    # Carry URL filter params (sections, ticketClasses, etc.) into the POST body
    # so pagination returns the same filtered set as the initial page load.
    qs = parse_qs(parsed.query, keep_blank_values=True)
    sections = qs.get("sections", [""])[0]
    ticket_classes = qs.get("ticketClasses", [""])[0]
    rows = qs.get("rows", [""])[0]
    seats = qs.get("seats", [""])[0]
    seat_types = qs.get("seatTypes", [""])[0]

    post_body = {
        "ShowAllTickets": True,
        "HideDuplicateTicketsV2": False,
        "Quantity": 2,
        "IsInitialQuantityChange": False,
        "PageVisitId": page_state.get("PageVisitId", ""),
        "PageSize": page_state.get("pageSize", 6),
        "CurrentPage": page_num,
        "SortBy": "NEWPRICE",
        "SortDirection": 1,
        "Sections": sections,
        "Rows": rows,
        "Seats": seats,
        "SeatTypes": seat_types,
        "TicketClasses": ticket_classes,
        "ListingNoteIds": "",
    }

    try:
        result: dict = await page.evaluate(
            """async (args) => {
                const resp = await fetch(args.url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify(args.body)
                });
                if (!resp.ok) {
                    return { error: resp.status, items: [] };
                }
                return await resp.json();
            }""",
            {"url": post_url, "body": post_body},
        )
    except Exception as exc:
        logger.warning("In-browser POST for page %d failed: %s", page_num, exc)
        return [], {"itemsRemaining": 0}

    if "error" in result:
        status = result["error"]
        if status == 429:
            raise RateLimitError(f"HTTP 429 on pagination POST (page {page_num})")
        logger.warning("Pagination POST returned HTTP %s on page %d", status, page_num)
        return [], {"itemsRemaining": 0}

    items_raw: list[dict] = result.get("items", [])
    new_page_state = {
        "PageVisitId": page_state.get("PageVisitId", ""),
        "pageSize": result.get("pageSize", page_state.get("pageSize", 6)),
        "currentPage": result.get("currentPage", page_num),
        "itemsRemaining": result.get("itemsRemaining", 0),
    }

    listings = _parse_items(items_raw, base_url)
    return listings, new_page_state


def _parse_items(items: list[dict], base_url: str) -> list[Listing]:
    """Convert raw listing dicts to Listing dataclass instances."""
    base = base_url.split("?")[0]
    results: list[Listing] = []

    for item in items:
        name = item.get("sectionMapName", "").strip()
        if not name:
            continue

        try:
            price = float(item.get("rawPrice", 0))
        except (TypeError, ValueError):
            logger.debug("Skipping item %r: invalid rawPrice %r", name, item.get("rawPrice"))
            continue

        quantity = int(item.get("availableTickets", 0))
        is_all_in = bool(item.get("isAllInGridListingPriceAndFeeDisclosure", False))
        listing_id = item.get("listingId")

        if listing_id:
            url = f"{base}?listingId={listing_id}&quantity=2"
        else:
            url = base_url

        results.append(Listing(name=name, price=price, url=url, quantity=quantity, is_all_in=is_all_in))

    return results
