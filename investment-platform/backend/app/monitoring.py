"""
Freshness and pipeline health for the real market data, computed from the DB.

One function (compute_data_status) feeds both:
  * GET /v1/data-status        -- JSON for people (and later the BFF)
  * /metrics (Prometheus)      -- market_* gauges via MarketDataCollector,
                                  used by infra/prometheus/alerts.yml and the
                                  "Market Data & API" Grafana dashboard.

The collector refreshes from the DB at most every METRICS_REFRESH_S seconds,
so Prometheus scraping every 15 s does not hammer Neon.
"""
from __future__ import annotations

import datetime
import logging
import threading
import time

from fastapi import APIRouter, Depends
from prometheus_client.core import REGISTRY, GaugeMetricFamily
from sqlalchemy.orm import Session

from . import market_repo as mr
from .config import settings
from .db import SessionLocal, get_db

log = logging.getLogger("monitoring")

# Max age (calendar days) of the newest bar/value before an item counts as stale.
STALE_AFTER_DAYS = {
    "equities": 4,       # Fri close is fine until Tue; Athens holidays rarely exceed this
    "crypto": 1,         # 24/7 market, loaded every 6 h
    "fundamentals": 488, # ~16 months after fiscal year end: annual reports are due within 4 months
}
# Max hours since a job last ran successfully (ok or partial) before it counts as overdue.
JOB_MAX_HOURS = {"indicators": 26, "snapshots": 26, "crypto": 7, "equities": 76, "fundamentals": 192, "forecasts": 26}


def compute_data_status(db: Session, today: datetime.date | None = None, now: datetime.datetime | None = None) -> dict:
    today = today or datetime.date.today()
    now = now or datetime.datetime.now()
    items: list[dict] = []

    def add(dataset, item, last, threshold):
        age = (today - last).days if last else None
        items.append({"dataset": dataset, "item": item, "last_date": last, "age_days": age,
                      "threshold_days": threshold, "stale": age is None or age > threshold})

    fy_ends = mr.latest_fiscal_year_ends(db)
    for inst, last in mr.last_bar_dates(db):
        dataset = "crypto" if inst.asset_type == "crypto" else "equities"
        add(dataset, inst.ticker, last, STALE_AFTER_DAYS[dataset])
        if inst.lei:
            add("fundamentals", inst.ticker, fy_ends.get(inst.id), STALE_AFTER_DAYS["fundamentals"])

    snap_day = mr.latest_snapshot_date(db)
    for ind_id, snap in (mr.snapshots_on(db, snap_day) if snap_day else {}).items():
        items.append({"dataset": "indicators", "item": ind_id, "last_date": snap.obs_date, "age_days": snap.staleness_d,
                      "threshold_days": None, "stale": not snap.payload_eligible})

    runs = mr.pipeline_runs_by_job(db)
    pipelines = []
    for job, max_h in JOB_MAX_HOURS.items():
        info = runs.get(job)
        last = info["last"] if info else None
        ok_at = info["last_success_at"] if info else None
        hours = round((now - ok_at).total_seconds() / 3600, 2) if ok_at else None
        pipelines.append({
            "job": job, "max_hours": max_h,
            "last_run_at": last.started_at if last else None, "last_status": last.status if last else None,
            "last_rows": last.rows_affected if last else None, "last_detail": last.detail if last else None,
            "last_success_at": ok_at, "hours_since_success": hours,
            "overdue": hours is None or hours > max_h,
        })

    from forecasting import registry  # local import: forecasting imports app modules
    models = []
    for name, mv in sorted(registry.latest_versions(db).items()):
        trained = mv.trained_at.replace(tzinfo=None) if mv.trained_at else None
        preds = registry.latest_predictions(db, name)
        models.append({"model": name, "version": mv.version, "status": mv.status, "reason": mv.status_reason,
                       "trained_hours_ago": round((datetime.datetime.utcnow() - trained).total_seconds() / 3600, 2) if trained else None,
                       "predictions_as_of": preds[0].as_of_date if preds else None,
                       "predictions_age_days": (today - preds[0].as_of_date).days if preds else None,
                       "predictions": len(preds)})

    datasets = {}
    for name in ("equities", "crypto", "indicators", "fundamentals"):
        rows = [i for i in items if i["dataset"] == name]
        datasets[name] = {"items": len(rows), "stale": sum(i["stale"] for i in rows),
                          "stale_items": [i["item"] for i in rows if i["stale"]]}
    critical = any(p["overdue"] or p["last_status"] == "error" for p in pipelines if p["job"] != "fundamentals") \
        or any(datasets[d]["stale"] for d in ("equities", "crypto"))
    degraded = critical or any(d["stale"] for d in datasets.values()) or any(p["overdue"] for p in pipelines)
    return {
        "generated_at": now, "overall": "critical" if critical else "degraded" if degraded else "ok",
        "snapshot_date": snap_day, "datasets": datasets, "pipelines": pipelines, "models": models, "items": items,
    }


# ---------------------------------------------------------------- JSON endpoint
router = APIRouter(prefix="/v1", tags=["monitoring"])


@router.get("/data-status")
def data_status(db: Session = Depends(get_db)):
    """Freshness of every loaded series and the health of each market-data job.
    overall: ok | degraded (something stale, e.g. annual reports) | critical
    (prices stale or a daily job overdue/failing)."""
    return compute_data_status(db)


# ---------------------------------------------------------------- Prometheus
class MarketDataCollector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: dict | None = None
        self._ok = 0.0
        self._refreshed = 0.0

    def _refresh(self) -> None:
        if time.monotonic() - self._refreshed < settings.metrics_refresh_s and self._refreshed:
            return
        db = SessionLocal()
        try:
            self._status, self._ok = compute_data_status(db), 1.0
        except Exception as e:  # never break /metrics; surface it as market_monitoring_scrape_ok 0
            log.warning("market data metrics refresh failed: %s", e)
            self._ok = 0.0
        finally:
            db.close()
            self._refreshed = time.monotonic()

    def collect(self):
        with self._lock:
            self._refresh()
        up = GaugeMetricFamily("market_monitoring_scrape_ok", "1 if the last DB refresh of market-data metrics succeeded")
        up.add_metric([], self._ok)
        yield up
        st = self._status
        if not st:
            return
        age = GaugeMetricFamily("market_data_age_days", "Days since the newest value of a series", labels=["dataset", "item"])
        stale = GaugeMetricFamily("market_data_stale", "1 if the series is older than its freshness threshold", labels=["dataset", "item"])
        for i in st["items"]:
            if i["age_days"] is not None:
                age.add_metric([i["dataset"], i["item"]], i["age_days"])
            stale.add_metric([i["dataset"], i["item"]], float(i["stale"]))
        yield age
        yield stale
        n_items = GaugeMetricFamily("market_data_items", "Series tracked per dataset", labels=["dataset"])
        n_stale = GaugeMetricFamily("market_data_stale_items", "Stale series per dataset", labels=["dataset"])
        for name, d in st["datasets"].items():
            n_items.add_metric([name], d["items"])
            n_stale.add_metric([name], d["stale"])
        yield n_items
        yield n_stale
        last_run = GaugeMetricFamily("market_pipeline_last_run_timestamp_seconds", "Start time of the last run", labels=["job"])
        since_ok = GaugeMetricFamily("market_pipeline_hours_since_success", "Hours since the last ok/partial run", labels=["job"])
        overdue = GaugeMetricFamily("market_pipeline_overdue", "1 if no successful run within the job's max hours", labels=["job"])
        status = GaugeMetricFamily("market_pipeline_last_status", "1 for the status of the last run", labels=["job", "status"])
        rows = GaugeMetricFamily("market_pipeline_last_rows", "Rows written by the last run", labels=["job"])
        for p in st["pipelines"]:
            if p["last_run_at"]:
                last_run.add_metric([p["job"]], p["last_run_at"].timestamp())
                rows.add_metric([p["job"]], p["last_rows"] or 0)
            if p["hours_since_success"] is not None:
                since_ok.add_metric([p["job"]], p["hours_since_success"])
            overdue.add_metric([p["job"]], float(p["overdue"]))
            for sname in ("ok", "partial", "error", "skipped"):
                status.add_metric([p["job"], sname], float(p["last_status"] == sname))
        yield from (last_run, since_ok, overdue, status, rows)
        approved = GaugeMetricFamily("model_approved", "1 if the latest version of the model is approved (served)", labels=["model"])
        trained = GaugeMetricFamily("model_trained_hours_ago", "Hours since the latest version was trained", labels=["model"])
        pred_age = GaugeMetricFamily("model_predictions_age_days", "Age of the newest served predictions", labels=["model"])
        n_pred = GaugeMetricFamily("model_predictions", "Rows in the newest served prediction set", labels=["model"])
        for m in st.get("models", []):
            approved.add_metric([m["model"]], float(m["status"] == "approved"))
            if m["trained_hours_ago"] is not None:
                trained.add_metric([m["model"]], m["trained_hours_ago"])
            if m["predictions_age_days"] is not None:
                pred_age.add_metric([m["model"]], m["predictions_age_days"])
            n_pred.add_metric([m["model"]], m["predictions"])
        yield from (approved, trained, pred_age, n_pred)
        overall = GaugeMetricFamily("market_data_overall", "0 ok, 1 degraded, 2 critical")
        overall.add_metric([], {"ok": 0, "degraded": 1, "critical": 2}[st["overall"]])
        yield overall


_collector: MarketDataCollector | None = None


def register_metrics() -> None:
    global _collector
    if _collector is None:
        _collector = MarketDataCollector()
        REGISTRY.register(_collector)
