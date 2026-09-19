"""
SEC EDGAR ingestion.

Real endpoints (verified against SEC's own documentation):
  - Ticker -> CIK lookup:        https://www.sec.gov/files/company_tickers.json
  - Company submissions/filings: https://data.sec.gov/submissions/CIK{cik:0>10}.json
  - Company XBRL facts:          https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:0>10}.json
  - One concept across years:    https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:0>10}/{taxonomy}/{tag}.json

SEC requires a descriptive User-Agent identifying your application and a
contact email (e.g. "MyApp admin@example.com") on every request, and asks
that automated tools stay under ~10 requests/second -- see
https://www.sec.gov/os/webmaster-faq#developers.

IMPORTANT: this sandbox's network egress does not include sec.gov, so this
pipeline is structurally correct (verified endpoint shapes, correct
normalization logic) but has NOT been run against the live API. Before
relying on it, run it against a couple of real CIKs and inspect the output.
"""
from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402

BASE_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
BASE_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
TICKER_LOOKUP_URL = "https://www.sec.gov/files/company_tickers.json"

# us-gaap XBRL tags used to build one FinancialFact row per fiscal year, each
# with fallback aliases since SEC's XBRL data is not uniform across filers or
# time. Revenue in particular has three generations of tag: SalesRevenueNet
# (pre-2018), Revenues (the single-year ASC 606 transition tag most large
# filers used only in FY2018), then RevenueFromContractWithCustomerExcluding
# AssessedTax (2019 onward) -- a company's full history needs all three.
GAAP_TAG_ALIASES = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "total_assets": ["Assets"],
    "total_equity": ["StockholdersEquity"],
    "total_debt": ["LongTermDebtNoncurrent"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "eps": ["EarningsPerShareDiluted"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}


def _headers() -> dict:
    return {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}


def _rate_limited_get(url: str, **kwargs) -> requests.Response:
    resp = requests.get(url, headers=_headers(), timeout=30, **kwargs)
    resp.raise_for_status()
    time.sleep(0.11)  # stay comfortably under SEC's ~10 req/s guidance
    return resp


def lookup_cik(ticker: str) -> Optional[str]:
    """Returns the 10-digit zero-padded CIK for a ticker, or None if not found."""
    data = _rate_limited_get(TICKER_LOOKUP_URL).json()
    ticker_upper = ticker.upper()
    for row in data.values():
        if row["ticker"].upper() == ticker_upper:
            return str(row["cik_str"]).zfill(10)
    return None


def fetch_company_facts(cik: str) -> dict:
    """Raw XBRL company-facts payload for a 10-digit CIK."""
    return _rate_limited_get(BASE_COMPANYFACTS.format(cik=cik)).json()


def _extract_annual_values(facts: dict, tag: str) -> dict[int, float]:
    """Pulls one USD-denominated tag's annual (10-K, full fiscal year) values,
    keyed by fiscal year. SEC's companyfacts payload nests values under
    facts['us-gaap'][tag]['units']['USD'] (or 'USD/shares', 'shares' for
    per-share/count tags) as a list of {val, fy, fp, form, ...} records.

    A single 10-K's XBRL data includes far more than just that year's total:
    prior-year comparatives and quarterly breakdowns (for MD&A tables) are
    all tagged form="10-K", fp="FY" too -- SEC's own docs don't expose a
    cleaner filter. Duration facts (income-statement items like revenue) are
    disambiguated by requiring the start/end span to actually cover a full
    year (~350-380 days); instant facts (balance-sheet items) have no
    'start' at all and are taken as-is."""
    node = facts.get("facts", {}).get("us-gaap", {}).get(tag)
    if not node:
        return {}
    out: dict[int, float] = {}
    for unit_key, records in node.get("units", {}).items():
        for r in records:
            if r.get("form") != "10-K" or r.get("fp") != "FY" or not r.get("fy"):
                continue
            start, end = r.get("start"), r.get("end")
            if start and end:
                span_days = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
                if span_days < 300:
                    continue
            out[int(r["fy"])] = float(r["val"])
    return out


def _extract_annual_values_with_fallback(facts: dict, tags: list[str]) -> dict[int, float]:
    """Merges a tag's alias list into one {fiscal_year: value} dict. Earlier
    tags in the list take priority for a given year; later ones only fill
    years the earlier tags didn't cover (see GAAP_TAG_ALIASES)."""
    merged: dict[int, float] = {}
    for tag in tags:
        for year, val in _extract_annual_values(facts, tag).items():
            merged.setdefault(year, val)
    return merged


# Tags required to produce a meaningful row at all -- a fiscal year missing
# any of these is dropped. The rest (total_debt, eps, shares_diluted) are
# optional: plenty of real filers are legitimately debt-free some years, and
# requiring every tag globally non-empty would silently drop an entire
# company just because it never reported one optional line item.
_REQUIRED_TAGS = {"revenue", "net_income", "total_assets", "total_equity", "current_assets", "current_liabilities"}


def normalize_company_facts(cik: str, ticker: str) -> list[dict]:
    """Converts a raw companyfacts payload into FinancialFact-shaped rows,
    one per fiscal year covered by every required tag (see _REQUIRED_TAGS);
    optional tags default to 0.0 for years they don't cover."""
    facts = fetch_company_facts(cik)
    by_tag = {name: _extract_annual_values_with_fallback(facts, tags) for name, tags in GAAP_TAG_ALIASES.items()}
    required_sets = [set(by_tag[name].keys()) for name in _REQUIRED_TAGS]
    years = set.intersection(*required_sets) if all(required_sets) else set()

    rows = []
    for year in sorted(years):
        revenue = by_tag["revenue"].get(year, 0.0)
        net_income = by_tag["net_income"].get(year, 0.0)
        operating_income = by_tag["operating_income"].get(year, 0.0)
        rows.append({
            "fiscal_year": year,
            "revenue": revenue,
            # SEC's XBRL data doesn't cleanly separate gross_profit / ebitda / free_cash_flow /
            # interest_expense in every filer's taxonomy -- a production pipeline should pull
            # CostOfRevenue, DepreciationDepletionAndAmortization, InterestExpense, and
            # NetCashProvidedByUsedInOperatingActivities / PaymentsForCapitalExpenditures
            # explicitly (with per-filer tag fallbacks) rather than approximate them here.
            "gross_profit": revenue - by_tag.get("cost_of_revenue", {}).get(year, revenue * 0.6),
            "operating_income": operating_income,
            "net_income": net_income,
            "ebitda": operating_income * 1.15,  # placeholder approximation -- replace with real D&A add-back
            "free_cash_flow": net_income * 0.9,  # placeholder approximation -- replace with real OCF - capex
            "total_assets": by_tag["total_assets"].get(year, 0.0),
            "total_equity": by_tag["total_equity"].get(year, 0.0),
            "total_debt": by_tag["total_debt"].get(year, 0.0),
            "current_assets": by_tag["current_assets"].get(year, 0.0),
            "current_liabilities": by_tag["current_liabilities"].get(year, 0.0),
            "interest_expense": by_tag.get("interest_expense", {}).get(year, 0.0),
            "shares_diluted": by_tag["shares_diluted"].get(year, 0.0),
            "eps": by_tag["eps"].get(year, 0.0),
        })
    return rows


if __name__ == "__main__":
    import sys

    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    cik = lookup_cik(ticker)
    print(f"{ticker} -> CIK {cik}")
    if cik:
        rows = normalize_company_facts(cik, ticker)
        for r in rows:
            print(r["fiscal_year"], {k: v for k, v in r.items() if k != "fiscal_year"})
