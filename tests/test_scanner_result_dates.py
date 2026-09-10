"""Result-date parsing and staleness. Pure logic -- no network in tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from tm750.scanner import result_dates as rd
from tm750.scanner import store


def _reset():
    store.init_schema()
    store.cursor().execute("DELETE FROM result_dates")


# ---------------------------------------------------------------- parsing
def test_parses_an_explicit_date():
    html = '<p class="sub">Upcoming result date: 24 July 2026</p>'
    assert rd.parse_result_date(html) == date(2026, 7, 24)


def test_parses_relative_wording():
    assert rd.parse_result_date(
        "<p>Upcoming result date: Tomorrow</p>") == date.today() + timedelta(days=1)
    assert rd.parse_result_date(
        "<p>Upcoming result date: Today</p>") == date.today()


def test_prefers_the_innermost_matching_element():
    """Reference bug 2: a page wrapper contains the phrase too. soup.find
    returns it first in document order, and split(':')[-1] then parses the
    whole page tail as a date."""
    html = ("<div><section><div>"
            '<p class="sub">Upcoming result date: 24 July 2026</p>'
            "</div></section></div>")
    assert rd.parse_result_date(html) == date(2026, 7, 24)


def test_handles_abbreviated_month_names():
    assert rd.parse_result_date(
        "<p>Upcoming result date: 24 Jul 2026</p>") == date(2026, 7, 24)


def test_returns_none_when_the_phrase_is_absent():
    assert rd.parse_result_date("<p>Nothing here</p>") is None


def test_returns_none_on_an_unparseable_date_rather_than_raising():
    assert rd.parse_result_date(
        "<p>Upcoming result date: sometime soon</p>") is None


def test_returns_none_on_empty_input():
    assert rd.parse_result_date("") is None


# ------------------------------------------------------------------ cache
def test_a_past_date_is_treated_as_stale_and_rechecked():
    """Reference bug 1: once a date was stored it was never refreshed, so a
    date that has since passed stayed forever."""
    _reset()
    rd.store_date("AAA", date.today() - timedelta(days=3), "announced")
    assert rd.needs_check("AAA") is True


def test_a_future_date_is_not_rechecked():
    _reset()
    rd.store_date("BBB", date.today() + timedelta(days=5), "announced")
    assert rd.needs_check("BBB") is False


def test_an_unseen_symbol_always_needs_a_check():
    _reset()
    assert rd.needs_check("NEVERSEEN") is True


def test_not_announced_is_rechecked_after_the_ttl():
    _reset()
    rd.store_date("CCC", None, "not_announced",
                  checked_at=datetime.now() - timedelta(days=2))
    assert rd.needs_check("CCC", ttl_hours=24) is True


def test_not_announced_is_not_rechecked_within_the_ttl():
    _reset()
    rd.store_date("DDD", None, "not_announced", checked_at=datetime.now())
    assert rd.needs_check("DDD", ttl_hours=24) is False


# -------------------------------------------------------------- staleness
def test_profit_is_flagged_stale_when_a_result_landed_after_the_fetch():
    """The whole point: the verdict describes the previous quarter."""
    assert rd.profit_is_stale(
        result_date=date(2026, 8, 20),
        profit_fetched_at=datetime(2026, 8, 19, 18, 0)) is True


def test_profit_is_not_stale_when_fetched_after_the_result():
    assert rd.profit_is_stale(
        result_date=date(2026, 8, 20),
        profit_fetched_at=datetime(2026, 8, 21, 9, 0)) is False


def test_a_future_result_date_does_not_make_profit_stale():
    """Nothing has been filed yet, so nothing has been missed."""
    assert rd.profit_is_stale(
        result_date=date.today() + timedelta(days=5),
        profit_fetched_at=datetime.now()) is False


def test_no_result_date_means_not_stale():
    assert rd.profit_is_stale(None, datetime.now()) is False


def test_no_fetch_timestamp_means_not_stale():
    assert rd.profit_is_stale(date(2026, 8, 20), None) is False
