"""
P(stressed Athens market next month).

Target ("stress"): the Athens General index (GD.AT) falls more than 7% from a
peak at some point within the next 21 trading days (path drawdown).

Features at each month end, POINT-IN-TIME: a macro value is used only once it
would have been published (period end + publication lag), so September
inflation is not "known" on 30 September.
    gd_ret_1m, gd_vol_3m, gd_drawdown_6m         market state
    vix, spread_10y, spread_chg_3m               risk appetite / Greek sovereign risk
    euribor_chg_6m, hicp_yoy                     rates and inflation trend

Model: standardised features -> L2 logistic regression (few samples, so kept simple).
Walk-forward: expanding window, refit every month after MIN_TRAIN_MONTHS, using
only samples whose outcome window had closed. Baseline: the training-window
base rate. Approved if Brier skill > 0 and AUC > 0.55 over >= 36 test months.
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
STRESS_DRAWDOWN = -0.07
MIN_TRAIN_MONTHS = 48
MIN_TEST_MONTHS = 36
INDEX = "GD.AT"
# indicator -> (frequency, publication lag in days after the period END)
MACRO = {"vix": ("D", 1), "spread_10y": ("M", 35), "euribor_3m": ("M", 5), "hicp_yoy": ("M", 20)}
FEATURES = ["gd_ret_1m", "gd_vol_3m", "gd_drawdown_6m", "vix", "spread_10y", "spread_chg_3m", "euribor_chg_6m", "hicp_yoy"]


def _period_end(d: pd.Timestamp, freq: str) -> pd.Timestamp:
    return d if freq == "D" else (d + pd.offsets.MonthEnd(0))


def known_at(series: pd.Series, freq: str, lag_days: int) -> pd.Series:
    """Re-index a macro series by the date each value became public."""
    if series.empty:  # indicator not loaded: an empty series that still compares with dates
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    idx = [_period_end(d, freq) + pd.Timedelta(days=lag_days) for d in series.index]
    return pd.Series(series.to_numpy(), index=pd.DatetimeIndex(idx)).sort_index()


def value_at(public: pd.Series, when: pd.Timestamp) -> float:
    s = public[public.index <= when]
    return float(s.iloc[-1]) if len(s) else float("nan")


def build_dataset(index_prices: pd.Series, macro: dict[str, pd.Series]) -> pd.DataFrame:
    """One row per month end: features + label (NaN while the next month is still open)."""
    px = index_prices.dropna()
    public = {k: known_at(macro.get(k, pd.Series(dtype=float)), *MACRO[k]) for k in MACRO}
    month_ends = px.groupby([px.index.year, px.index.month]).tail(1).index
    rows = []
    for t in month_ends:
        i = px.index.get_loc(t)
        if i < 130:
            continue
        hist = px.iloc[: i + 1]
        r = np.diff(np.log(hist.to_numpy()))
        row = {
            "date": t,
            "gd_ret_1m": hist.iloc[-1] / hist.iloc[-22] - 1,
            "gd_vol_3m": float(np.std(r[-63:], ddof=1) * math.sqrt(252)),
            "gd_drawdown_6m": hist.iloc[-1] / hist.iloc[-126:].max() - 1,
            "vix": value_at(public["vix"], t),
            "spread_10y": value_at(public["spread_10y"], t),
            "spread_chg_3m": value_at(public["spread_10y"], t) - value_at(public["spread_10y"], t - pd.Timedelta(days=91)),
            "euribor_chg_6m": value_at(public["euribor_3m"], t) - value_at(public["euribor_3m"], t - pd.Timedelta(days=182)),
            "hicp_yoy": value_at(public["hicp_yoy"], t),
        }
        future = px.iloc[i + 1: i + 1 + HORIZON]
        if len(future) == HORIZON:
            path = np.concatenate([[hist.iloc[-1]], future.to_numpy()])
            row["stress"] = float((path / np.maximum.accumulate(path) - 1).min() < STRESS_DRAWDOWN)
            row["outcome_end"] = future.index[-1]
        else:
            row["stress"], row["outcome_end"] = float("nan"), pd.NaT
        rows.append(row)
    df = pd.DataFrame(rows).set_index("date")
    if not df.empty:
        df["outcome_end"] = pd.to_datetime(df["outcome_end"])
    return df


def _model():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=1000))


def evaluate(ds: pd.DataFrame) -> dict:
    empty = {"n_test": 0, "auc": float("nan"), "brier": float("nan"), "brier_baseline": float("nan"), "bss": float("nan")}
    if ds.empty:
        return empty
    data = ds.dropna(subset=FEATURES)
    probs, base, ys, dates = [], [], [], []
    labelled = data.dropna(subset=["stress"])
    for t in labelled.index:
        train = labelled[labelled["outcome_end"] < t]  # only outcomes already known at t
        if len(train) < MIN_TRAIN_MONTHS or train["stress"].nunique() < 2:
            continue
        m = _model().fit(train[FEATURES], train["stress"])
        probs.append(float(m.predict_proba(labelled.loc[[t], FEATURES])[0, 1]))
        base.append(float(train["stress"].mean()))
        ys.append(float(labelled.loc[t, "stress"]))
        dates.append(t)
    if len(ys) < 2 or len(set(ys)) < 2:
        return {"n_test": len(ys), "auc": float("nan"), "brier": float("nan"), "brier_baseline": float("nan"), "bss": float("nan")}
    b, b0 = brier_score_loss(ys, probs), brier_score_loss(ys, base)
    return {"n_test": len(ys), "test_start": dates[0].date(), "test_end": dates[-1].date(),
            "event_rate": float(np.mean(ys)), "auc": float(roc_auc_score(ys, probs)),
            "brier": float(b), "brier_baseline": float(b0), "bss": float(1 - b / b0) if b0 else float("nan")}


def decide(ev: dict) -> tuple[bool, str]:
    if ev["n_test"] < MIN_TEST_MONTHS:
        return False, f"only {ev['n_test']} out-of-sample months (need {MIN_TEST_MONTHS})"
    if not (ev["bss"] > 0 and ev["auc"] > 0.55):
        return False, f"did not beat the base rate out of sample (Brier skill {ev['bss']:.3f}, AUC {ev['auc']:.3f})"
    return True, f"beats the base rate out of sample (Brier skill {ev['bss']:.3f}, AUC {ev['auc']:.3f}, {ev['n_test']} months)"


def fit_and_predict(ds: pd.DataFrame) -> tuple[dict, dict]:
    """Fit on every labelled month; predict for the latest month end. Returns (prediction row, params)."""
    data = ds.dropna(subset=FEATURES)
    labelled = data.dropna(subset=["stress"])
    m = _model().fit(labelled[FEATURES], labelled["stress"])
    latest = data.iloc[[-1]]
    p = float(m.predict_proba(latest[FEATURES])[0, 1])
    scaler, lr = m.named_steps["standardscaler"], m.named_steps["logisticregression"]
    z = (latest[FEATURES].to_numpy()[0] - scaler.mean_) / scaler.scale_
    contrib = dict(sorted(zip(FEATURES, (lr.coef_[0] * z).tolist()), key=lambda kv: -abs(kv[1])))
    vol_pct = float((data["gd_vol_3m"] <= latest["gd_vol_3m"].iloc[0]).mean())
    current = "stressed" if vol_pct >= 0.8 else "calm" if vol_pct <= 0.33 else "normal"
    row = {"subject": f"market:GR", "target": "p_stress_next_month", "horizon_days": HORIZON, "value": p, "details": {
        "as_of_month_end": latest.index[0].date(), "base_rate": float(labelled["stress"].mean()),
        "features": latest[FEATURES].iloc[0].to_dict(), "drivers_log_odds": contrib,
        "current_volatility_percentile": vol_pct, "current_regime": current,
        "definition": "P(Athens General index falls >7% from a peak within the next 21 trading days)"}}
    params = {"features": FEATURES, "coefficients": dict(zip(FEATURES, lr.coef_[0].tolist())),
              "intercept": float(lr.intercept_[0]), "scaler_mean": dict(zip(FEATURES, scaler.mean_.tolist())),
              "scaler_scale": dict(zip(FEATURES, scaler.scale_.tolist())), "n_train": int(len(labelled))}
    return row, params


def current_conditions(ds: pd.DataFrame) -> dict | None:
    """Measured (not forecast) state of the Athens market at the latest month end:
    where 3-month volatility sits in its own history, and the drawdown from the 6-month high."""
    d = ds.dropna(subset=["gd_vol_3m"])
    if d.empty:
        return None
    last = d.iloc[-1]
    pct = float((d["gd_vol_3m"] <= last["gd_vol_3m"]).mean())
    label = "stressed" if pct >= 0.8 or last["gd_drawdown_6m"] < -0.15 else "calm" if pct <= 0.33 else "normal"
    return {"subject": "market:GR", "target": "volatility_percentile_3m", "horizon_days": 0, "value": pct, "details": {
        "as_of_month_end": d.index[-1].date(), "label": label, "volatility_3m_annualized": float(last["gd_vol_3m"]),
        "drawdown_from_6m_high": float(last["gd_drawdown_6m"]), "return_1m": float(last["gd_ret_1m"]),
        "history_months": int(len(d)), "definition": "Measured, not forecast: Athens General index (GD.AT) 3-month "
        "realised volatility percentile vs its own history; stressed if >= 80th percentile or > 15% below the 6-month high"}}
