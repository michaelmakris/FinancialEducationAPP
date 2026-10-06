"""
ESEF annual reports of Athens-listed companies, via XBRL International's free
filings.xbrl.org index (JSON:API) and its xBRL-JSON conversions. No key.

  Filing index:  https://filings.xbrl.org/api/filings?filter[country]=GR&page[size]=500&include=entity
  One filing:    https://filings.xbrl.org{json_url}

Since FY2021 EU-listed issuers must publish their annual financial report in
iXBRL tagged with the IFRS taxonomy, so this is the issuer's own audited
numbers. Undimensioned facts are the consolidated statements (separate/company-
only figures carry the ConsolidatedAndSeparateFinancialStatementsAxis dimension).
"""
from __future__ import annotations

import datetime

from . import get

BASE = "https://filings.xbrl.org"
_PLAIN_DIMS = {"concept", "entity", "period", "unit", "language"}


def parse_filing_index(payload: dict) -> list[dict]:
    """[{filing_id, lei, entity_name, json_url, processed}] -- one row per filing."""
    entities = {e["id"]: e["attributes"] for e in payload.get("included", []) if e["type"] == "entity"}
    out = []
    for d in payload.get("data", []):
        a = d["attributes"]
        ent = entities.get(((d.get("relationships") or {}).get("entity") or {}).get("data", {}).get("id"), {})
        if not a.get("json_url"):
            continue
        out.append({
            "filing_id": a["fxo_id"], "lei": ent.get("identifier"), "entity_name": ent.get("name"),
            "json_url": a["json_url"], "processed": a.get("processed") or "",
        })
    return out


def fetch_filing_index(country: str = "GR") -> list[dict]:
    payload = get(f"{BASE}/api/filings", params={
        "filter[country]": country, "page[size]": 1000, "include": "entity",
    }, timeout=90).json()
    return parse_filing_index(payload)


def _parse_period(p: str) -> tuple[datetime.date | None, datetime.date]:
    """xBRL-JSON periods are instants ('2023-01-01T00:00:00') or durations
    ('2022-01-01T00:00:00/2023-01-01T00:00:00'), with exclusive end dates --
    so an instant of 2023-01-01 is the 2022-12-31 balance sheet."""
    def day(s: str) -> datetime.date:
        d = datetime.date.fromisoformat(s[:10])
        return d - datetime.timedelta(days=1) if "T00:00:00" in s else d

    if "/" in p:
        start, end = p.split("/")
        return datetime.date.fromisoformat(start[:10]), day(end)
    return None, day(p)


def parse_facts(xbrl_json: dict) -> list[dict]:
    """Consolidated numeric ifrs-full facts: [{concept, period_start, period_end, value, unit}]."""
    out = {}
    for fact in (xbrl_json.get("facts") or {}).values():
        dims = fact.get("dimensions") or {}
        concept = dims.get("concept") or ""
        if not concept.startswith("ifrs-full:") or set(dims) - _PLAIN_DIMS or "period" not in dims:
            continue
        try:
            value = float(fact.get("value"))
        except (TypeError, ValueError):
            continue  # text blocks, booleans
        start, end = _parse_period(dims["period"])
        unit = (dims.get("unit") or "").replace("iso4217:", "").replace("xbrli:", "")
        key = (concept, start, end)
        out[key] = {"concept": concept.split(":", 1)[1], "period_start": start, "period_end": end, "value": value, "unit": unit}
    return list(out.values())


def fetch_facts(json_url: str) -> list[dict]:
    return parse_facts(get(BASE + json_url, timeout=120).json())
