"""Result dates, scraped from Screener.

Why the scanner cares: a TTM record is only as current as the last filed
quarter. If a company reported this morning and the profit feed has not yet
picked it up, its at_ath verdict describes the PREVIOUS quarter. Result dates
make that staleness visible instead of silent.

Three defects in the reference implementation (daily_tasks.py), each fixed:

1. Dates were never refreshed. The query selected only rows whose result_date
   was 'Not Announced', 'N/A' or 'CONFLICT', so once a real date was stored it
   was never re-checked -- a date that has since passed stayed forever and the
   next quarter's was never fetched. Fixed by needs_check().

2. The tag search could match a page wrapper. soup.find over p/div/span
   returns the first match in document order, which may be an outer div
   containing the entire page; text.split(':')[-1] then parsed garbage and the
   bare except swallowed it as None. Fixed by selecting the INNERMOST match.

3. It scraped the whole universe -- ~800 symbols at 1s each. We only need the
   handful that hit ATH today.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from tm750.scanner import store

PHRASE = "upcoming result date"
DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%d-%m-%Y", "%Y-%m-%d")
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0 Safari/537.36"),
}


def parse_result_date(html: str) -> date | None:
    """Extract the upcoming result date from a Screener company page.

    Returns None -- never raises -- when the phrase is absent or the value is
    unparseable, so a layout change degrades to 'unknown' rather than killing
    a scan.
    """
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")

    # Innermost match: among every element containing the phrase, take the one
    # with no matching descendant. An outer wrapper contains it too, and its
    # text is the whole page.
    candidates = [el for el in soup.find_all(["p", "div", "span", "li"])
                  if PHRASE in el.get_text(" ", strip=True).lower()]
    if not candidates:
        return None
    innermost = min(candidates, key=lambda el: len(el.get_text(" ", strip=True)))
    text = innermost.get_text(" ", strip=True)

    tail = text.split(":", 1)[-1].strip() if ":" in text else text
    low = tail.lower()
    if "tomorrow" in low:
        return date.today() + timedelta(days=1)
    if "today" in low:
        return date.today()

    match = re.search(r"\d{1,2}[\s\-/][A-Za-z]+[\s\-/]\d{4}", tail) \
        or re.search(r"\d{4}-\d{2}-\d{2}", tail) \
        or re.search(r"\d{1,2}-\d{1,2}-\d{4}", tail)
    if not match:
        return None
    cleaned = re.sub(r"\s+", " ", match.group(0)).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def fetch_result_date(symbol: str, timeout: int = 15) -> date | None:
    """One network call. Caller is responsible for rate limiting."""
    import requests

    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        return parse_result_date(resp.text)
    except Exception:
        return None


# ------------------------------------------------------------------- cache
def store_date(symbol: str, result_date: date | None, status: str,
               checked_at: datetime | None = None) -> None:
    store.cursor().execute(
        """INSERT INTO result_dates (symbol, result_date, status, checked_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT (symbol) DO UPDATE SET
               result_date = excluded.result_date,
               status = excluded.status,
               checked_at = excluded.checked_at""",
        [symbol,
         result_date.isoformat() if result_date else None,
         status,
         (checked_at or datetime.now())])


def get_date(symbol: str) -> dict | None:
    row = store.cursor().execute(
        """SELECT result_date, status, checked_at FROM result_dates
           WHERE symbol = ?""", [symbol]).fetchone()
    if row is None:
        return None
    return {"result_date": row[0], "status": row[1], "checked_at": row[2]}


def needs_check(symbol: str, ttl_hours: int = 24) -> bool:
    """Should this symbol be re-scraped?

    Yes when never checked, when the stored date has passed (the reference
    bug), or when we have no date and the last check is older than the TTL.
    No when a future date is already known -- nothing will change until it
    arrives.
    """
    row = get_date(symbol)
    if row is None:
        return True

    stored = row["result_date"]
    if stored is not None:
        if isinstance(stored, datetime):
            stored = stored.date()
        return stored < date.today()

    checked = row["checked_at"]
    if checked is None:
        return True
    return datetime.now() - checked > timedelta(hours=ttl_hours)


def profit_is_stale(result_date, profit_fetched_at) -> bool:
    """Did a result land after the profit data was fetched?

    If so the stored verdict may describe the previous quarter. The verdict is
    not suppressed -- it remains the best available answer -- but the UI marks
    it so the user knows it might have been overtaken.
    """
    if result_date is None or profit_fetched_at is None:
        return False
    if isinstance(result_date, datetime):
        result_date = result_date.date()
    if result_date > date.today():
        return False
    fetched = profit_fetched_at
    if isinstance(fetched, datetime):
        fetched = fetched.date()
    return result_date >= fetched


def refresh_for(symbols: list[str], delay: float = 1.0) -> dict:
    """Scrape only the symbols that need it, politely.

    Typically ~13 names after a scan, so ~13 seconds -- against ~800 in the
    reference script.
    """
    import time as _time

    checked = failed = 0
    for symbol in symbols:
        if not needs_check(symbol):
            continue
        found = fetch_result_date(symbol)
        if found is None:
            store_date(symbol, None, "not_announced")
            failed += 1
        else:
            store_date(symbol, found, "announced")
        checked += 1
        _time.sleep(delay)
    return {"checked": checked, "unresolved": failed}
