"""
Generates a deterministic, clearly-synthetic dataset for the AI Investment
Intelligence Platform demo. This is NOT real market data -- it is a seeded
random-walk/statistical model built to look and behave like plausible market
and fundamental data, so the analytics engine (ratios, risk, factor scores,
Monte Carlo simulation) has something realistic to compute against.

Output: dataset.json, embedded into the React demo artifact at build time.
"""
import json
import math
import uuid
import numpy as np

TRADING_DAYS = 504  # ~2 years
RNG_MASTER_SEED = 20260101

# ---------------------------------------------------------------------------
# Instrument universe. Parameters are hand-set per instrument to give each a
# distinct, sector-plausible character (drift/vol for prices; growth/margin
# assumptions for fundamentals). Everything downstream is computed for real
# from these seeds -- nothing is hand-written per output metric.
# ---------------------------------------------------------------------------
EQUITIES = [
    # ticker, name, sector, start_price, ann_drift, ann_vol,
    # base_revenue(B), revenue_growth, gross_margin, op_margin, net_margin,
    # fcf_margin, debt_to_equity, current_ratio, shares(B)
    dict(ticker="AAPL", name="Apple Inc.", sector="Technology", start_price=185.0,
         drift=0.14, vol=0.24, revenue=383.0, rev_growth=0.06, gross_margin=0.45,
         op_margin=0.30, net_margin=0.25, fcf_margin=0.27, debt_equity=1.45,
         current_ratio=0.99, shares=15.4),
    dict(ticker="MSFT", name="Microsoft Corp.", sector="Technology", start_price=340.0,
         drift=0.16, vol=0.22, revenue=228.0, rev_growth=0.14, gross_margin=0.69,
         op_margin=0.44, net_margin=0.36, fcf_margin=0.31, debt_equity=0.42,
         current_ratio=1.77, shares=7.4),
    dict(ticker="GOOGL", name="Alphabet Inc.", sector="Technology", start_price=138.0,
         drift=0.15, vol=0.26, revenue=307.0, rev_growth=0.09, gross_margin=0.57,
         op_margin=0.30, net_margin=0.24, fcf_margin=0.23, debt_equity=0.11,
         current_ratio=2.10, shares=12.6),
    dict(ticker="NVDA", name="NVIDIA Corp.", sector="Technology", start_price=480.0,
         drift=0.35, vol=0.48, revenue=60.9, rev_growth=1.26, gross_margin=0.73,
         op_margin=0.54, net_margin=0.49, fcf_margin=0.42, debt_equity=0.24,
         current_ratio=4.17, shares=24.6),
    dict(ticker="AMZN", name="Amazon.com Inc.", sector="Consumer Discretionary", start_price=145.0,
         drift=0.18, vol=0.30, revenue=575.0, rev_growth=0.12, gross_margin=0.47,
         op_margin=0.08, net_margin=0.06, fcf_margin=0.05, debt_equity=0.55,
         current_ratio=1.05, shares=10.4),
    dict(ticker="TSLA", name="Tesla Inc.", sector="Consumer Discretionary", start_price=250.0,
         drift=0.12, vol=0.55, revenue=96.8, rev_growth=0.05, gross_margin=0.18,
         op_margin=0.08, net_margin=0.07, fcf_margin=0.03, debt_equity=0.18,
         current_ratio=1.73, shares=3.2),
    dict(ticker="JPM", name="JPMorgan Chase & Co.", sector="Financials", start_price=170.0,
         drift=0.11, vol=0.20, revenue=158.0, rev_growth=0.07, gross_margin=1.00,
         op_margin=0.42, net_margin=0.33, fcf_margin=0.20, debt_equity=1.35,
         current_ratio=1.10, shares=2.9),
    dict(ticker="JNJ", name="Johnson & Johnson", sector="Healthcare", start_price=155.0,
         drift=0.07, vol=0.16, revenue=88.0, rev_growth=0.04, gross_margin=0.66,
         op_margin=0.24, net_margin=0.20, fcf_margin=0.22, debt_equity=0.48,
         current_ratio=1.35, shares=2.4),
    dict(ticker="KO", name="Coca-Cola Co.", sector="Consumer Staples", start_price=60.0,
         drift=0.06, vol=0.14, revenue=45.8, rev_growth=0.03, gross_margin=0.61,
         op_margin=0.29, net_margin=0.23, fcf_margin=0.24, debt_equity=1.72,
         current_ratio=1.11, shares=4.3),
    dict(ticker="XOM", name="Exxon Mobil Corp.", sector="Energy", start_price=105.0,
         drift=0.05, vol=0.27, revenue=344.0, rev_growth=-0.02, gross_margin=0.35,
         op_margin=0.14, net_margin=0.10, fcf_margin=0.11, debt_equity=0.20,
         current_ratio=1.28, shares=4.0),
]

ETFS = [
    dict(ticker="SPY", name="SPDR S&P 500 ETF Trust", sector="Broad Market Equity",
         start_price=455.0, drift=0.10, vol=0.16),
    dict(ticker="AGG", name="iShares Core U.S. Aggregate Bond ETF", sector="Broad Market Bonds",
         start_price=98.0, drift=0.035, vol=0.055),
]

CRYPTO = [
    dict(ticker="BTC", name="Bitcoin", sector="Crypto", start_price=43000.0, drift=0.30, vol=0.55),
    dict(ticker="ETH", name="Ethereum", sector="Crypto", start_price=2300.0, drift=0.28, vol=0.65),
    dict(ticker="SOL", name="Solana", sector="Crypto", start_price=95.0, drift=0.40, vol=0.85),
]


def gbm_path(seed, start_price, ann_drift, ann_vol, n_days, freq_per_year=252):
    rng = np.random.default_rng(seed)
    dt = 1.0 / freq_per_year
    shocks = rng.normal(
        (ann_drift - 0.5 * ann_vol ** 2) * dt,
        ann_vol * math.sqrt(dt),
        n_days,
    )
    log_path = np.cumsum(shocks)
    prices = start_price * np.exp(log_path)
    return prices


def make_trading_dates():
    import datetime
    end = datetime.date(2026, 9, 8)
    dates = []
    d = end
    count = 0
    while count < TRADING_DAYS:
        if d.weekday() < 5:
            dates.append(d.isoformat())
            count += 1
        d = d - datetime.timedelta(days=1)
    return dates[::-1]


def make_close_series(ticker, start_price, drift, vol):
    seed = abs(hash(("price", ticker, RNG_MASTER_SEED))) % (2 ** 32)
    prices = gbm_path(seed, start_price, drift, vol, TRADING_DAYS)
    decimals = 2 if start_price < 2000 else 2
    return [round(float(p), decimals) for p in prices]


def make_fundamentals(ticker, revenue, rev_growth, gross_margin, op_margin, net_margin,
                       fcf_margin, debt_equity, current_ratio, shares):
    seed = abs(hash(("fund", ticker, RNG_MASTER_SEED))) % (2 ** 32)
    rng = np.random.default_rng(seed)
    years = [2022, 2023, 2024, 2025]
    rows = []
    rev = revenue / ((1 + rev_growth) ** 3)  # back out so the LATEST year matches `revenue`
    for i, yr in enumerate(years):
        noise = rng.normal(0, 0.01)
        growth_this_year = rev_growth + noise if i > 0 else rev_growth
        if i > 0:
            rev = rev * (1 + growth_this_year)
        gross_profit = rev * gross_margin * (1 + rng.normal(0, 0.005))
        operating_income = rev * op_margin * (1 + rng.normal(0, 0.01))
        net_income = rev * net_margin * (1 + rng.normal(0, 0.01))
        fcf = rev * fcf_margin * (1 + rng.normal(0, 0.02))
        ebitda = operating_income * 1.18
        total_equity = net_income / 0.18 if net_income > 0 else rev * 0.25
        total_debt = total_equity * debt_equity
        total_assets = total_equity + total_debt + rev * 0.15
        current_liabilities = rev * 0.14
        current_assets = current_liabilities * current_ratio
        interest_expense = total_debt * 0.045
        eps = net_income / shares
        rows.append(dict(
            fiscal_year=yr, revenue=round(rev, 2), gross_profit=round(gross_profit, 2),
            operating_income=round(operating_income, 2), net_income=round(net_income, 2),
            ebitda=round(ebitda, 2), free_cash_flow=round(fcf, 2),
            total_assets=round(total_assets, 2), total_equity=round(total_equity, 2),
            total_debt=round(total_debt, 2), current_assets=round(current_assets, 2),
            current_liabilities=round(current_liabilities, 2),
            interest_expense=round(interest_expense, 2),
            shares_diluted=round(shares, 3), eps=round(eps, 3),
            published_at=f"{yr + 1}-02-15",  # when the 10-K would hit the market
        ))
    return rows


def make_macro_series():
    """Small synthetic macro panel: policy rate, 10Y yield, CPI YoY, VIX-like vol index."""
    rng = np.random.default_rng(RNG_MASTER_SEED + 999)
    n_months = 24
    import datetime
    end = datetime.date(2026, 8, 1)
    dates = []
    y, m = end.year, end.month
    for i in range(n_months):
        dates.append(datetime.date(y, m, 1).isoformat())
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    dates = dates[::-1]

    def mean_reverting(level, target, speed, vol, n):
        path = [level]
        for _ in range(n - 1):
            nxt = path[-1] + speed * (target - path[-1]) + rng.normal(0, vol)
            path.append(nxt)
        return path

    policy_rate = mean_reverting(5.25, 3.75, 0.06, 0.10, n_months)
    yield_10y = mean_reverting(4.4, 4.0, 0.05, 0.08, n_months)
    cpi_yoy = mean_reverting(3.2, 2.4, 0.05, 0.12, n_months)
    vix = mean_reverting(15.0, 16.0, 0.15, 1.4, n_months)
    series = []
    for i, d in enumerate(dates):
        series.append(dict(date=d, policy_rate=round(policy_rate[i], 2),
                            yield_10y=round(yield_10y[i], 2), cpi_yoy=round(cpi_yoy[i], 2),
                            vix=round(max(vix[i], 9.0), 2)))
    return series


def build():
    dates = make_trading_dates()
    instruments = []
    for e in EQUITIES:
        iid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "equity-" + e["ticker"]))
        close = make_close_series(e["ticker"], e["start_price"], e["drift"], e["vol"])
        fundamentals = make_fundamentals(
            e["ticker"], e["revenue"], e["rev_growth"], e["gross_margin"], e["op_margin"],
            e["net_margin"], e["fcf_margin"], e["debt_equity"], e["current_ratio"], e["shares"])
        instruments.append(dict(
            instrument_id=iid, ticker=e["ticker"], name=e["name"], asset_type="equity",
            sector=e["sector"], exchange="NASDAQ/NYSE (demo)", currency="USD",
            close=close, fundamentals=fundamentals))
    for e in ETFS:
        iid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "etf-" + e["ticker"]))
        close = make_close_series(e["ticker"], e["start_price"], e["drift"], e["vol"])
        instruments.append(dict(
            instrument_id=iid, ticker=e["ticker"], name=e["name"], asset_type="etf",
            sector=e["sector"], exchange="NYSE Arca (demo)", currency="USD",
            close=close, fundamentals=[]))
    for e in CRYPTO:
        iid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "crypto-" + e["ticker"]))
        close = make_close_series(e["ticker"], e["start_price"], e["drift"], e["vol"])
        instruments.append(dict(
            instrument_id=iid, ticker=e["ticker"], name=e["name"], asset_type="crypto",
            sector=e["sector"], exchange="Major venues (demo)", currency="USD",
            close=close, fundamentals=[]))

    macro = make_macro_series()
    dataset = dict(
        generated_note="SIMULATED DEMO DATA - not real market data. Seeded statistical model.",
        as_of="2026-09-08",
        dates=dates,
        instruments=instruments,
        macro=macro,
    )
    return dataset


if __name__ == "__main__":
    ds = build()
    with open("dataset.json", "w") as f:
        json.dump(ds, f, separators=(",", ":"))
    # sanity checks
    assert len(ds["dates"]) == TRADING_DAYS
    for inst in ds["instruments"]:
        assert all(p > 0 for p in inst["close"]), inst["ticker"]
        assert len(inst["close"]) == TRADING_DAYS, inst["ticker"]
        if inst["fundamentals"]:
            for row in inst["fundamentals"]:
                assert row["revenue"] > 0, inst["ticker"]
    print("instruments:", len(ds["instruments"]))
    print("macro points:", len(ds["macro"]))
    import os
    print("dataset.json bytes:", os.path.getsize("dataset.json"))
