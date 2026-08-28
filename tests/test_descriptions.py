"""Description coverage and honesty.

A tooltip that is confidently wrong is worse than one that is absent, so the
catalog records whether each description was written by hand or generated from
a pattern -- and generated ones are only produced for families where the name
fully determines the meaning.
"""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import app
from tm750.descriptions import describe

VISIBLE = [
    "Overview", "Performance", "Per Share", "Valuation", "Profitability",
    "Balance Sheet", "Cash Flow", "Growth", "Income Statement", "History",
    "Trend & Momentum", "Technicals", "Ownership", "Dividend", "Forecasts",
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def catalog(client):
    return pd.DataFrame(client.get("/meta/catalog").json()["columns"])


def test_every_company_page_column_is_described(catalog):
    vis = catalog[catalog["segment"].isin(VISIBLE)]
    missing = vis[vis["description_source"] == "none"]
    assert missing.empty, f"undescribed: {list(missing['name'])}"


def test_source_is_always_declared(catalog):
    assert set(catalog["description_source"]) <= {"curated", "generated", "none"}


def test_absent_descriptions_are_empty_not_guessed(catalog):
    """'none' must mean no text at all -- never a placeholder that reads like
    a real definition."""
    none = catalog[catalog["description_source"] == "none"]
    assert (none["description"].fillna("") == "").all()


def test_descriptions_are_one_line(catalog):
    described = catalog[catalog["description_source"] != "none"]
    assert not described["description"].str.contains("\n").any()


def test_descriptions_are_substantive(catalog):
    described = catalog[catalog["description_source"] != "none"]
    too_short = described[described["description"].str.len() < 15]
    assert too_short.empty, f"stub descriptions: {list(too_short['name'])}"


# Generated text must be correct, not merely present.
@pytest.mark.parametrize("column,fragment", [
    ("perf_3m_pct", "three months"),
    ("perf_1y_pct", "one year"),
    ("dist_ema_50_pct", "50-day exponential"),
    ("dist_sma_200_pct", "200-day simple"),
    ("high_52w", "52 weeks"),
    ("pat_cagr_5y_pct", "five years"),
    ("avg_roe_3y", "three years"),
    ("pct_rank_roe_in_sector", "within its own sector"),
    ("pct_rank_roe_in_tier", "within its own cap tier"),
    ("pct_rank_roe", "across all 750"),
    ("beta_1y", "one year"),
    ("profit_growth_5y", "five years"),
])
def test_generated_text_is_accurate(catalog, column, fragment):
    row = catalog[catalog["name"] == column]
    assert not row.empty, f"{column} not in catalog"
    assert fragment in row.iloc[0]["description"], row.iloc[0]["description"]


def test_ambiguous_definitions_are_curated_not_generated(catalog):
    """Where the definition carries a real choice, the text must be
    hand-written -- a pattern cannot know which ROCE formula was used."""
    for column in ["roce", "roce_screener", "pe_ratio", "momentum_12_1_pct",
                   "pat_both_at_ath", "piotroski_f_score", "price_to_book"]:
        row = catalog[catalog["name"] == column].iloc[0]
        assert row["description_source"] == "curated", column


def test_source_divergence_is_disclosed(catalog):
    """Both ROCE columns exist because the sources disagree. The tooltip has
    to say so, or the duplicate looks like an error."""
    text = catalog[catalog["name"] == "roce_screener"].iloc[0]["description"]
    assert "Screener" in text and ("differ" in text.lower()
                                   or "diverge" in text.lower())


def test_no_description_for_unknown_column():
    text, source = describe("some_column_that_does_not_exist")
    assert text == "" and source == "none"


def test_api_serves_descriptions_on_company_items(client):
    d = client.get("/companies/TCS").json()
    items = [i for seg in d["segments"].values() for i in seg]
    described = [i for i in items if i.get("description")]
    assert len(described) == len(items), "some company items lack a description"


def test_api_serves_descriptions_in_segments(client):
    segs = client.get("/meta/segments").json()["segments"]
    cols = [c for s in segs for c in s["columns"]]
    assert all("description" in c for c in cols)
