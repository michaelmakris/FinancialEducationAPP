"""
P(positive return over the next 21 periods) per instrument -- served ONLY if it
beats naive baselines out of sample. Short-horizon direction is close to
unpredictable for liquid assets; this model exists to test that honestly, not
to promise it.

Panel: month-end samples for every instrument.
Features: momentum 1m / 3m / 12m-skip-1m, 3-month volatility, distance from the
52-week high, Athens index 1m return.
Model: standardised features -> L2 logistic regression, pooled across assets.
Walk-forward: refit each month over the last EVAL_YEARS on samples whose
outcome had closed. Baselines: (a) the training base rate, (b) "3-month
momentum > 0 => up" with the training hit rate as probability.
Approval: Brier better than both baselines AND accuracy at least 1 point above
the better baseline accuracy, over >= 24 test months.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HORIZON = 21
EVAL_YEARS = 3
MIN_TEST_MONTHS = 24
MIN_TRAIN_SAMPLES = 200
FEATURES = ["mom_1m", "mom_3m", "mom_12m_skip1", "vol_3m", "dist_52w_high", "market_1m"]


def build_panel(panel: dict[str, pd.Series], market: pd.Series | None) -> pd.DataFrame:
    rows = []
    for ticker, px in panel.items():
        px = px.dropna()
        month_ends = px.groupby([px.index.year, px.index.month]).tail(1).index
        for t in month_ends:
            i = px.index.get_loc(t)
            if i < 260:
                continue
            h = px.iloc[: i + 1].to_numpy()
            r = np.diff(np.log(h[-64:]))
            row = {"ticker": ticker, "date": t,
                   "mom_1m": h[-1] / h[-22] - 1, "mom_3m": h[-1] / h[-64] - 1, "mom_12m_skip1": h[-22] / h[-253] - 1,
                   "vol_3m": float(np.std(r, ddof=1)), "dist_52w_high": h[-1] / h[-253:].max() - 1}
            if market is not None:
                m = market[market.index <= t]
                row["market_1m"] = float(m.iloc[-1] / m.iloc[-22] - 1) if len(m) > 22 else float("nan")
            else:
                row["market_1m"] = 0.0
            fut = px.iloc[i + 1: i + 1 + HORIZON]
            if len(fut) == HORIZON:
                row["up"], row["outcome_end"] = float(fut.iloc[-1] > h[-1]), fut.index[-1]
            else:
                row["up"], row["outcome_end"] = float("nan"), pd.NaT
            rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"], df["outcome_end"] = pd.to_datetime(df["date"]), pd.to_datetime(df["outcome_end"])
    return df


def _model():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=1000))


def evaluate(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n_test_months": 0}
    data = df.dropna(subset=FEATURES)
    labelled = data.dropna(subset=["up"]) if not data.empty else data
    if labelled.empty:
        return {"n_test_months": 0}
    start = labelled["date"].max() - pd.Timedelta(days=365 * EVAL_YEARS)
    test_months = sorted(d for d in labelled["date"].unique() if d >= start)
    y, p, p_base, p_mom = [], [], [], []
    months = 0
    for t in test_months:
        train = labelled[labelled["outcome_end"] < t]
        test = labelled[labelled["date"] == t]
        if len(train) < MIN_TRAIN_SAMPLES or train["up"].nunique() < 2 or test.empty:
            continue
        months += 1
        m = _model().fit(train[FEATURES], train["up"])
        p.extend(m.predict_proba(test[FEATURES])[:, 1].tolist())
        rate = float(train["up"].mean())
        p_base.extend([rate] * len(test))
        hit_pos = float(train.loc[train["mom_3m"] > 0, "up"].mean())
        hit_neg = float(train.loc[train["mom_3m"] <= 0, "up"].mean())
        p_mom.extend(np.where(test["mom_3m"] > 0, hit_pos, hit_neg).tolist())
        y.extend(test["up"].tolist())
    if months == 0 or len(set(y)) < 2:
        return {"n_test_months": months}

    def acc(probs):
        return float(np.mean((np.array(probs) > 0.5) == (np.array(y) > 0.5)))

    return {
        "n_test_months": months, "n_test_samples": len(y), "up_rate": float(np.mean(y)),
        "model": {"brier": float(brier_score_loss(y, p)), "accuracy": acc(p), "auc": float(roc_auc_score(y, p))},
        "baseline_rate": {"brier": float(brier_score_loss(y, p_base)), "accuracy": acc(p_base)},
        "baseline_momentum": {"brier": float(brier_score_loss(y, p_mom)), "accuracy": acc(p_mom),
                              "auc": float(roc_auc_score(y, p_mom)) if len(set(p_mom)) > 1 else float("nan")},
    }


def decide(ev: dict) -> tuple[bool, str]:
    if ev.get("n_test_months", 0) < MIN_TEST_MONTHS:
        return False, f"only {ev.get('n_test_months', 0)} out-of-sample months (need {MIN_TEST_MONTHS})"
    m, b1, b2 = ev["model"], ev["baseline_rate"], ev["baseline_momentum"]
    best_base_acc = max(b1["accuracy"], b2["accuracy"])
    if m["brier"] < min(b1["brier"], b2["brier"]) and m["accuracy"] >= best_base_acc + 0.01:
        return True, (f"beats both baselines out of sample (Brier {m['brier']:.4f} vs {min(b1['brier'], b2['brier']):.4f}, "
                      f"accuracy {m['accuracy']:.3f} vs {best_base_acc:.3f})")
    return False, (f"does not beat naive baselines out of sample (Brier {m['brier']:.4f} vs {min(b1['brier'], b2['brier']):.4f}, "
                   f"accuracy {m['accuracy']:.3f} vs {best_base_acc:.3f}); not served")


def fit_and_predict(df: pd.DataFrame) -> tuple[list[dict], dict]:
    data = df.dropna(subset=FEATURES)
    labelled = data.dropna(subset=["up"])
    m = _model().fit(labelled[FEATURES], labelled["up"])
    latest = data.sort_values("date").groupby("ticker").tail(1)
    probs = m.predict_proba(latest[FEATURES])[:, 1]
    rows = [{"subject": t, "target": "p_up_21d", "horizon_days": HORIZON, "value": float(pr),
             "details": {"as_of_month_end": d.date(), "features": {f: float(v) for f, v in zip(FEATURES, feats)}}}
            for t, d, pr, feats in zip(latest["ticker"], latest["date"], probs, latest[FEATURES].to_numpy())]
    lr = m.named_steps["logisticregression"]
    return rows, {"features": FEATURES, "coefficients": dict(zip(FEATURES, lr.coef_[0].tolist())),
                  "intercept": float(lr.intercept_[0]), "n_train": int(len(labelled))}
