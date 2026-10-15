"""Gather inputs from the database, run the engine, store and return the proposal."""
from __future__ import annotations

import datetime
import json
import math

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import market_repo as mr
from app import models, repo
from forecasting import registry

from . import analysis, context, engine, narrative, questionnaire

ENGINE_VERSION = "1.0"
PROXIES = {"global_equity": ["URTH", "^GSPC"], "greek_equity": ["GD.AT"], "crypto": ["BTC-EUR"]}
BOND_DURATION = 7.0          # years, a typical euro government bond fund
BOND_VOL_FALLBACK = 0.06     # used only if the Greek 10y yield history is missing
REPLAY = ("COVID-19 crash", datetime.date(2020, 2, 19), datetime.date(2020, 3, 23))
IDEAS_PER_SLEEVE = 4
MAX_IDEA_VOL_BY_PROFILE = {1: 0.30, 2: 0.30, 3: 0.35, 4: 0.40, 5: 0.50, 6: 0.70, 7: 0.90}


class NoProfile(Exception):
    pass


# ---------------------------------------------------------------- risk profile
def save_assessment(db: Session, customer_id: str, answers: dict) -> models.RiskAssessment:
    result = questionnaire.assess(answers)  # raises InvalidAnswers
    ra = models.RiskAssessment(customer_id=customer_id, questionnaire_version=questionnaire.VERSION,
                               answers_json=json.dumps(answers, sort_keys=True), result_json=json.dumps(result),
                               profile=result["profile"])
    db.add(ra)
    db.commit()
    db.refresh(ra)
    return ra


def latest_assessment(db: Session, customer_id: str) -> models.RiskAssessment | None:
    return db.execute(select(models.RiskAssessment).where(models.RiskAssessment.customer_id == customer_id)
                      .order_by(models.RiskAssessment.id.desc()).limit(1)).scalar_one_or_none()


# ---------------------------------------------------------------- inputs
def _series(db: Session, tickers: list[str]) -> dict[str, pd.Series]:
    found = mr.get_instruments(db, tickers)
    raw = mr.adj_close_series(db, [i.id for i in found.values()])
    return {i.ticker: pd.Series([v for _, v in raw[i.id]], index=pd.DatetimeIndex([d for d, _ in raw[i.id]]))
            for i in found.values() if raw.get(i.id)}


def _first(tickers: list[str], available) -> str | None:
    return next((t for t in tickers if t in available), None)


def gather_inputs(db: Session, profile: int) -> engine.MarketInputs:
    sources: dict = {"proxies": {}, "assumptions": []}
    vol_preds = {(p.subject, p.target): p for p in registry.latest_predictions(db, "volatility")}
    versions = registry.latest_versions(db)
    sources["models"] = {n: {"version": mv.version, "status": mv.status} for n, mv in versions.items()}

    sleeve_vol, proxy_of = {}, {}
    for sleeve, cands in PROXIES.items():
        t = _first(cands, {s for s, _ in vol_preds})
        if t:
            sleeve_vol[sleeve] = vol_preds[(t, "vol_21d_annualized")].value
            proxy_of[sleeve] = t
            sources["proxies"][sleeve] = f"{t} (volatility model)"
    if len(sleeve_vol) < len(PROXIES):
        missing = sorted(set(PROXIES) - set(sleeve_vol))
        raise RuntimeError(f"risk estimates missing for {', '.join(missing)}: run the forecasts job first")

    ggb = mr.indicator_series(db, "ggb_10y")
    if len(ggb) >= 24:
        changes = np.diff([v for _, v in ggb[-37:]])
        sleeve_vol["bonds"] = float(np.std(changes, ddof=1) * BOND_DURATION * math.sqrt(12) / 100)
        sources["proxies"]["bonds"] = f"Greek 10y yield changes x {BOND_DURATION:g}y duration"
    else:
        sleeve_vol["bonds"] = BOND_VOL_FALLBACK
        sources["assumptions"].append(f"bond volatility assumed {BOND_VOL_FALLBACK:.0%} (no yield history)")
    sources["assumptions"].append("bonds assumed uncorrelated with shares and crypto")

    series = _series(db, list(proxy_of.values()))
    rets = pd.concat({s: np.log(series[t]).diff() for s, t in proxy_of.items() if t in series}, axis=1, join="inner").dropna()
    rets = rets[rets.index >= rets.index[-1] - pd.Timedelta(days=730)] if len(rets) else rets
    corr = {}
    if len(rets) > 60:
        c = rets.corr()
        for a in c.columns:
            for b in c.columns:
                if a < b:
                    corr[(a, b)] = float(c.loc[a, b])
    sources["correlation_window"] = "2 years of daily returns" if corr else "not available (assumed 0)"

    cond = registry.latest_predictions(db, "conditions", "market:GR")
    label = json.loads(cond[0].details_json).get("label") if cond else None

    # historical replay: the real moves of the same proxies over the COVID crash
    name, start, end = REPLAY
    replay_returns = {"cash": 0.0}
    for sleeve, t in proxy_of.items():
        s = series.get(t)
        if s is None:
            continue
        a, b = s[s.index <= pd.Timestamp(start)], s[s.index <= pd.Timestamp(end)]
        if len(a) and len(b) and a.index[-1] >= pd.Timestamp(start) - pd.Timedelta(days=7):
            replay_returns[sleeve] = float(b.iloc[-1] / a.iloc[-1] - 1)
    ggb_map = dict(ggb)
    feb, mar = ggb_map.get(datetime.date(2020, 2, 1)), ggb_map.get(datetime.date(2020, 3, 1))
    if feb is not None and mar is not None:
        replay_returns["bonds"] = -(mar - feb) * BOND_DURATION / 100
    replay = {"name": name, "period": f"{start:%d %b %Y} - {end:%d %b %Y}", "returns": replay_returns} \
        if len(replay_returns) >= 4 else None

    return engine.MarketInputs(sleeve_vol=sleeve_vol, correlations=corr, conditions_label=label, replay=replay,
                               ideas=_ideas(db, profile, vol_preds), sources=sources)


def _ideas(db: Session, profile: int, vol_preds: dict) -> dict[str, list[dict]]:
    insts = {i.ticker: i for i in mr.list_instruments(db)}
    max_vol = MAX_IDEA_VOL_BY_PROFILE[profile]

    def risk(t):
        v, p = vol_preds.get((t, "vol_21d_annualized")), vol_preds.get((t, "p_loss_10pct_21d"))
        return (v.value if v else None), (p.value if p else None)

    greek, seen_sectors = [], set()
    for q in sorted(registry.latest_predictions(db, "quality"), key=lambda p: -p.value):
        inst = insts.get(q.subject)
        vol, p_loss = risk(q.subject)
        if not inst or vol is None or vol > max_vol or inst.sector in seen_sectors:
            continue
        seen_sectors.add(inst.sector)
        greek.append({"ticker": q.subject, "name": inst.name, "sector": inst.sector, "quality_score": q.value,
                      "expected_volatility": vol, "p_loss_10pct_21d": p_loss})
        if len(greek) == IDEAS_PER_SLEEVE:
            break
    out = {"greek_equity": greek}
    for sleeve, tickers in (("global_equity", ["URTH", "^STOXX50E", "^GSPC"]), ("crypto", ["BTC-EUR", "ETH-EUR"])):
        out[sleeve] = [{"ticker": t, "name": insts[t].name, "expected_volatility": risk(t)[0], "p_loss_10pct_21d": risk(t)[1]}
                       for t in tickers if t in insts and risk(t)[0] is not None]
    return out


# ---------------------------------------------------------------- proposal
def _holding_series(db: Session, tickers: list[str]) -> dict[str, dict]:
    """{ticker: {asset_type, sector, market, close}}: a year of closes on the dates every holding traded."""
    insts = mr.get_instruments(db, tickers)
    since = datetime.date.today() - datetime.timedelta(days=400)
    series = mr.adj_close_series(db, [i.id for i in insts.values()], since=since)
    common = None
    for i in insts.values():
        days = {d for d, _ in series.get(i.id, [])}
        common = days if common is None else common & days
    out = {}
    for i in insts.values():
        closes = [v for d, v in series.get(i.id, []) if d in (common or set())]
        out[i.ticker] = {"asset_type": i.asset_type, "sector": i.sector, "market": i.market, "close": closes}
    return out


def generate(db: Session, customer_id: str, use_ai: bool = False) -> models.Proposal:
    ra = latest_assessment(db, customer_id)
    if ra is None:
        raise NoProfile()
    assessment = json.loads(ra.result_json)
    m = gather_inputs(db, assessment["profile"])
    p = engine.build(assessment, m)
    p["assessment"] = assessment

    # the customer's practice portfolio
    from app.services import practice  # same valuation the portfolio page shows
    pf = practice.summary(db, repo.get_or_create_portfolio(db, customer_id))
    target = {a["sleeve"]: a["weight_pct"] for a in p["allocation"]}
    p["current"] = analysis.analyse(pf, _holding_series(db, [x["ticker"] for x in pf["positions"]]), target)
    if not p["current"].get("empty"):
        p["current"]["stress_tests"] = engine.stress(p["current"]["weights_pct"], m)

    snap_day = mr.latest_snapshot_date(db)
    p["context"] = context.facts(mr.snapshots_on(db, snap_day) if snap_day else {})
    p["data_as_of"] = {"snapshots": snap_day, "risk_estimates": max((x.as_of_date for x in registry.latest_predictions(db, "volatility")), default=None)}
    p["disclaimer"] = narrative.DISCLAIMER

    text = narrative.template(p)
    source = "template"
    if use_ai:
        text, source = narrative.ai_rewrite(text, {k: p[k] for k in ("profile_name", "allocation", "expected_volatility", "stress_tests")})
    prop = models.Proposal(customer_id=customer_id, risk_assessment_id=ra.id, engine_version=ENGINE_VERSION,
                           proposal_json=json.dumps(registry._clean(p)), narrative=text, narrative_source=source)
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


def as_dict(prop: models.Proposal) -> dict:
    return {"id": prop.id, "created_at": prop.created_at, "engine_version": prop.engine_version,
            "narrative": prop.narrative, "narrative_source": prop.narrative_source, **json.loads(prop.proposal_json)}
