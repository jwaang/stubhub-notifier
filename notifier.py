"""
Email notifier for the StubHub EDC shuttle ticket monitor.

Sends a single consolidated HTML email (with plain-text fallback and optional
screenshot attachment) whenever new matching listings are found.
"""

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytz

from scraper import Listing

logger = logging.getLogger(__name__)

_PT = pytz.timezone("America/Los_Angeles")


def send_alert(
    listings: list[Listing],
    *,
    gmail_address: str,
    gmail_app_password: str,
    notification_emails: list[str],
) -> None:
    """
    Send one consolidated email summarising all new/changed matching listings.

    Non-fatal: logs errors and returns without raising so the bot keeps running.
    """
    if not listings:
        return

    try:
        _send(listings, gmail_address, gmail_app_password, notification_emails)
        logger.info("Alert email sent to %s (%d listing(s))", ", ".join(notification_emails), len(listings))
    except Exception:
        logger.error("Failed to send alert email", exc_info=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_FEE_PER_TICKET = 159  # StubHub buyer fee per ticket for these shuttle listings


def _build_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone(_PT).strftime("%Y-%m-%d %I:%M %p PT")


def _build_subject(n: int) -> str:
    return f"\U0001f3a1 EDC Shuttle Alert: {n} matching ticket(s) found \u2013 Mid-Strip 6:30PM"


def _all_in(l: Listing) -> float:
    """Return the all-in price per ticket."""
    return l.price if l.is_all_in else l.price + _FEE_PER_TICKET


def _build_html(listings: list[Listing], ts: str) -> str:
    rows = ""
    for l in listings:
        name_cell = (
            f'<a href="{l.url}" style="color:#1a73e8">{l.name}</a>'
            if l.url
            else l.name
        )
        aip = _all_in(l)
        if l.is_all_in:
            breakdown = f"${aip:.0f} incl. fees"
        else:
            breakdown = f"${l.price:.0f} + ${_FEE_PER_TICKET} fees = <strong>${aip:.0f}</strong>"
        rows += (
            f"<tr>"
            f"<td style='padding:6px 12px'>{name_cell}</td>"
            f"<td style='padding:6px 12px;text-align:right'>{breakdown}</td>"
            f"<td style='padding:6px 12px;text-align:right'><strong>${aip * 2:.0f}</strong></td>"
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;color:#202124;max-width:640px;margin:0 auto">
  <h2 style="color:#d93025">\U0001f3a1 EDC Las Vegas Shuttle Alert</h2>
  <p><strong>{len(listings)} matching Mid-Strip 6:30 PM listing(s) found.</strong></p>

  <table border="1" cellpadding="0" cellspacing="0"
         style="border-collapse:collapse;width:100%;border-color:#dadce0">
    <thead>
      <tr style="background:#f1f3f4">
        <th style="padding:8px 12px;text-align:left">Ticket Name</th>
        <th style="padding:8px 12px;text-align:right">Price / Ticket</th>
        <th style="padding:8px 12px;text-align:right">Total (\u00d72)</th>
      </tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>

  <p style="color:#5f6368;font-size:13px">Checked at: {ts}</p>
</body>
</html>"""


def _build_plain(listings: list[Listing], ts: str) -> str:
    lines = [
        f"EDC Las Vegas Shuttle Alert — {len(listings)} matching listing(s)\n",
        f"{'Ticket Name':<55} {'Breakdown':>28} {'Total x2':>10}",
        "-" * 96,
    ]
    for l in listings:
        aip = _all_in(l)
        if l.is_all_in:
            breakdown = f"${aip:.0f} incl. fees"
        else:
            breakdown = f"${l.price:.0f} + ${_FEE_PER_TICKET} fees = ${aip:.0f}"
        lines.append(f"{l.name:<55} {breakdown:>28} ${aip * 2:>8.0f}")
        if l.url:
            lines.append(f"  {l.url}")
    lines += ["", f"Checked at: {ts}"]
    return "\n".join(lines)


def _send(
    listings: list[Listing],
    gmail_address: str,
    gmail_app_password: str,
    notification_emails: list[str],
) -> None:
    ts = _build_timestamp()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = _build_subject(len(listings))
    msg["From"] = gmail_address
    msg["To"] = ", ".join(notification_emails)
    msg.attach(MIMEText(_build_plain(listings, ts), "plain", "utf-8"))
    msg.attach(MIMEText(_build_html(listings, ts), "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(gmail_address, gmail_app_password)
        smtp.send_message(msg)
