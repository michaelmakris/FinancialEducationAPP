"""
Forecasting and scoring models over the real market data (v1).

    volatility  21-day volatility + P(fall > 10% within 21 days) per instrument   (EWMA / GARCH, champion by validation)
    regime      P(stressed Athens market next month)                            (logistic regression on macro + market)
    quality     0-100 quality score within sector from annual-report ratios      (transparent scoring, not a forecast)
    direction   P(positive 21-day return) per instrument                         (logistic regression; served only if it
                                                                                   beats naive baselines out of sample)

Every run evaluates the model walk-forward (only data available at each date),
compares it with a simple baseline, and records both in `model_versions`.
Predictions are written to `model_predictions` only for approved versions.
See MODEL_CARDS.md.
"""
