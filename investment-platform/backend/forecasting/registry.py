"""Model registry: versions with their out-of-sample metrics, and served predictions."""
from __future__ import annotations

import datetime
import json
import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ModelPrediction, ModelVersion


def _clean(obj):
    """JSON-safe: floats rounded, NaN/inf -> None, dates -> ISO."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) or hasattr(obj, "item"):
        v = float(obj)
        return None if math.isnan(v) or math.isinf(v) else round(v, 6)
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return obj


def register(db: Session, *, model_name: str, algorithm: str, metrics: dict, baseline: dict, params: dict,
             approved: bool, reason: str, data_start=None, data_end=None) -> ModelVersion:
    version = (db.execute(select(func.max(ModelVersion.version)).where(ModelVersion.model_name == model_name)).scalar() or 0) + 1
    mv = ModelVersion(
        model_name=model_name, version=version, algorithm=algorithm,
        data_start=data_start, data_end=data_end,
        metrics_json=json.dumps(_clean(metrics)), baseline_json=json.dumps(_clean(baseline)),
        params_json=json.dumps(_clean(params)),
        status="approved" if approved else "rejected", status_reason=reason[:500],
    )
    db.add(mv)
    db.flush()
    return mv


def save_predictions(db: Session, mv: ModelVersion, as_of: datetime.date, rows: list[dict]) -> int:
    """rows: [{subject, target, value, horizon_days, details}] -- replaces this model's rows for as_of."""
    if mv.status != "approved":
        raise ValueError("only approved model versions may serve predictions")
    db.flush()  # autoflush is off: make rows added earlier in this transaction visible
    existing = {(p.subject, p.target): p for p in db.execute(select(ModelPrediction).where(
        ModelPrediction.model_name == mv.model_name, ModelPrediction.as_of_date == as_of)).scalars()}
    n = 0
    for r in rows:
        if r["value"] is None or (isinstance(r["value"], float) and (math.isnan(r["value"]) or math.isinf(r["value"]))):
            continue
        key = (r["subject"], r["target"])
        fields = dict(model_version_id=mv.id, horizon_days=r.get("horizon_days", 0), value=float(r["value"]),
                      details_json=json.dumps(_clean(r.get("details", {}))))
        if key in existing:
            for k, v in fields.items():
                setattr(existing[key], k, v)
        else:
            db.add(ModelPrediction(model_name=mv.model_name, subject=r["subject"], target=r["target"], as_of_date=as_of, **fields))
        n += 1
    return n


def latest_versions(db: Session) -> dict[str, ModelVersion]:
    """Newest version per model, whatever its status."""
    sub = select(ModelVersion.model_name, func.max(ModelVersion.version).label("v")).group_by(ModelVersion.model_name).subquery()
    rows = db.execute(select(ModelVersion).join(sub, (ModelVersion.model_name == sub.c.model_name) & (ModelVersion.version == sub.c.v))).scalars()
    return {r.model_name: r for r in rows}


def latest_predictions(db: Session, model_name: str, subject: str | None = None) -> list[ModelPrediction]:
    """Rows from the newest as_of_date of the newest *approved* version that has predictions."""
    q = select(func.max(ModelPrediction.as_of_date)).join(ModelVersion, ModelVersion.id == ModelPrediction.model_version_id) \
        .where(ModelPrediction.model_name == model_name, ModelVersion.status == "approved")
    if subject:
        q = q.where(ModelPrediction.subject == subject)
    as_of = db.execute(q).scalar()
    if as_of is None:
        return []
    q = select(ModelPrediction).where(ModelPrediction.model_name == model_name, ModelPrediction.as_of_date == as_of)
    if subject:
        q = q.where(ModelPrediction.subject == subject)
    return list(db.execute(q).scalars())


def as_dict(mv: ModelVersion | None) -> dict | None:
    if mv is None:
        return None
    return {"model_name": mv.model_name, "version": mv.version, "algorithm": mv.algorithm, "status": mv.status,
            "status_reason": mv.status_reason, "trained_at": mv.trained_at, "data_start": mv.data_start,
            "data_end": mv.data_end, "metrics": json.loads(mv.metrics_json), "baseline": json.loads(mv.baseline_json),
            "params": json.loads(mv.params_json)}
