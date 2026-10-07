"""Train, evaluate, register and (if approved) publish every model. Runs as the
`forecasts` job in pipelines/jobs.py (daily, after the price loads)."""
from __future__ import annotations

import datetime
import logging

from sqlalchemy.orm import Session

from pipelines.jobs import JobResult

from . import data, direction, quality, regime, registry, volatility

log = logging.getLogger("forecasting")
MODELS = ["volatility", "regime", "quality", "direction"]


def _vol(db: Session, as_of: datetime.date, res: JobResult) -> None:
    panel = data.price_panel(db)
    if len(panel) < 3:
        raise RuntimeError("not enough instruments with history")
    insts = data.instruments_by_ticker(db)
    ev = volatility.evaluate(panel)
    method, approved, reason, p_method = volatility.choose(ev)
    mv = registry.register(db, model_name="volatility", algorithm=method, approved=approved, reason=reason,
                           metrics={k: v for k, v in ev.items() if k != "per_asset_qlike"} | {"champion": method, "p_loss_method": p_method},
                           baseline={"method": volatility.BASELINE, "qlike": ev["qlike"][volatility.BASELINE],
                                     "brier_p_loss": ev["brier_p_loss_empirical"]},
                           params={"horizon": volatility.HORIZON, "ewma_lambda": volatility.EWMA_LAMBDA,
                                   "eval_years": volatility.EVAL_YEARS, "loss_threshold": -0.10,
                                   "per_asset_qlike": ev["per_asset_qlike"]},
                           data_start=min(s.index[0] for s in panel.values()).date(),
                           data_end=max(s.index[-1] for s in panel.values()).date())
    rows = volatility.predict(panel, {t: i.asset_type for t, i in insts.items()}, method, p_method)
    res.rows += registry.save_predictions(db, mv, as_of, rows)
    res.notes.append(f"volatility v{mv.version}: {method}, {ev['n_assets']} assets")


def _regime(db: Session, as_of: datetime.date, res: JobResult) -> None:
    panel = data.price_panel(db, ("index",))
    if regime.INDEX not in panel:
        raise RuntimeError(f"{regime.INDEX} prices not loaded")
    ds = regime.build_dataset(panel[regime.INDEX], {k: data.indicator(db, k) for k in regime.MACRO})
    ev = regime.evaluate(ds)
    approved, reason = regime.decide(ev)
    row, params = regime.fit_and_predict(ds) if approved else (None, {"features": regime.FEATURES})
    mv = registry.register(db, model_name="regime", algorithm="logistic_regression_l2", approved=approved, reason=reason,
                           metrics=ev, baseline={"method": "training base rate", "brier": ev.get("brier_baseline")},
                           params=params, data_start=ds.index[0].date() if len(ds) else None,
                           data_end=ds.index[-1].date() if len(ds) else None)
    if approved and row:
        res.rows += registry.save_predictions(db, mv, as_of, [row])
    res.notes.append(f"regime v{mv.version}: {mv.status}")
    # Measured market conditions are published regardless: they are facts, not a forecast.
    cond = regime.current_conditions(ds)
    if cond:
        cv = registry.register(db, model_name="conditions", algorithm="measured_volatility_percentile", approved=True,
                               reason="measurement of current conditions (not a forecast)",
                               metrics={"history_months": cond["details"]["history_months"]}, baseline={},
                               params={"stressed_percentile": 0.8, "calm_percentile": 0.33, "stressed_drawdown": -0.15})
        res.rows += registry.save_predictions(db, cv, as_of, [cond])


def _quality(db: Session, as_of: datetime.date, res: JobResult) -> None:
    funds = data.latest_fundamentals(db)
    rows = quality.score(funds)
    mv = registry.register(db, model_name="quality", algorithm="peer_percentile_rank", approved=bool(rows),
                           reason=f"transparent peer ranking of {len(rows)} companies" if rows else "no fundamentals loaded",
                           metrics={"companies_scored": len(rows), "companies_with_fundamentals": len(funds)}, baseline={},
                           params={"bank_components": list(quality.BANK_COMPONENTS), "corporate_components": list(quality.CORPORATE_COMPONENTS),
                                   "min_components": quality.MIN_COMPONENTS})
    if rows:
        res.rows += registry.save_predictions(db, mv, as_of, rows)
    res.notes.append(f"quality v{mv.version}: {len(rows)} companies")


def _direction(db: Session, as_of: datetime.date, res: JobResult) -> None:
    panel = data.price_panel(db)
    df = direction.build_panel(panel, panel.get(regime.INDEX))
    ev = direction.evaluate(df)
    approved, reason = direction.decide(ev)
    rows, params = direction.fit_and_predict(df) if approved else ([], {"features": direction.FEATURES})
    mv = registry.register(db, model_name="direction", algorithm="logistic_regression_l2_pooled", approved=approved,
                           reason=reason, metrics={k: v for k, v in ev.items() if not k.startswith("baseline")},
                           baseline={k: v for k, v in ev.items() if k.startswith("baseline")}, params=params)
    if approved:
        res.rows += registry.save_predictions(db, mv, as_of, rows)
    res.notes.append(f"direction v{mv.version}: {mv.status}")


_STEPS = {"volatility": _vol, "regime": _regime, "quality": _quality, "direction": _direction}


def run_forecasts(db: Session, full: bool = False, only: list[str] | None = None, as_of: datetime.date | None = None) -> JobResult:
    as_of = as_of or data.last_price_date(db) or datetime.date.today()
    res = JobResult(notes=[f"as_of={as_of}"])
    for name in MODELS:
        if only and name not in only:
            continue
        try:
            _STEPS[name](db, as_of, res)
            res.items += 1
            db.commit()
        except Exception as e:
            db.rollback()
            res.fail(name, e)
            log.exception("model %s failed", name)
    return res
