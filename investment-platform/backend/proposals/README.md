# Educational proposals ("My plan")

A holistic, **educational** plan for the customer's **practice portfolio** (virtual money). It combines the
customer's risk profile, the validated risk models, measured market conditions, annual-report quality
scores, macro data and the customer's current practice holdings. It is not investment advice for real money.

```
questionnaire ──► risk profile 1-7 ──┐
volatility model + correlations ─────┤
market conditions (measured) ────────┼──► engine ──► proposal ──► template explanation ──► stored + served
quality scores + risk per stock ─────┤                    │        (optional AI rewrite, checked)
macro snapshots ─────────────────────┤                    └── stress tests incl. real 2020 replay
practice portfolio ──────────────────┘
```

## Risk profile (`questionnaire.py`)

There are 8 questions: horizon, emergency fund, share of savings, income stability, reaction to a 20% fall, goal, acceptable outcome range, and knowledge.

- **Profile** = min(capacity, tolerance, horizon cap), so the more cautious dimension decides.
- **Knowledge** doesn't change the profile, but crypto appears only with prior experience of volatile assets *and* a profile ≥ 5.
- **No emergency fund:** if the customer has no emergency fund, the explanation says to build one first.
- **Audit trail:** every assessment is stored (append-only, `risk_assessments`).

## Engine (`engine.py`)

1. **Strategic mix** per profile across cash, bonds, global shares, Greek shares and crypto (the `STRATEGIC` table).
2. **No crypto** unless the questionnaire allows it; its weight moves to global shares.
3. **Stressed market:** if the Athens market is *measured* as stressed, 5 points move from shares to cash (profiles ≤ 5 only).
4. **Volatility cap:** expected volatility is computed from the volatility model's forecasts and 2 years of measured correlations:
   - proxies: URTH for global shares, GD.AT for Greek shares, BTC-EUR for crypto
   - bonds: Greek 10-year yield moves × 7-year duration
   - if the result is above the profile's band (4% … 25%), every risky part is scaled down into cash
5. **Stress tests:** three hypothetical shocks plus a **replay of the real February-March 2020 crash**, applied to both the plan and the current practice portfolio.
6. **Ideas to research:** the highest-quality Greek company per sector, within a volatility limit for the profile; URTH, the Euro Stoxx 50 and S&P 500 for global shares; BTC and ETH for crypto. They are presented as examples to learn about, never as "buy".

Every adjustment is recorded with its reason.

## Explanation (`narrative.py`)

- **Template:** deterministic, always produced, every number taken from the proposal.
- **Optional AI rewrite** (`use_ai: true`, using `LLM_PROVIDER`). It is accepted only if:
  - every number in it appears in the template
  - it has no advice or promise language and no forward-looking return claims (so a correct number can't be turned into a promise)
  - it is ≤ 2,200 characters

  Otherwise the template is served, and the rejection reason is stored in `narrative_source` and counted in `proposals_generated_total`.

## Storage and access

- `proposals` stores the full proposal JSON: assessment, allocation, stress tests, current-portfolio analysis, macro facts, data dates, model versions and proxies, assumptions, and the explanation with its source.
- API, all for the caller's own customer id only:
  - `GET /v1/profile/questionnaire`
  - `GET|POST /v1/profile`
  - `POST /v1/proposals` (needs `portfolio:write`)
  - `GET /v1/proposals[/latest|/{id}]`
- BFF: allowlisted. Web app: **My plan** tab. MCP: `get_my_risk_profile`, `get_my_proposal` (read only; proposals are generated in the app).
- Monitoring:
  - `proposals_generated_total{narrative}`
  - alerts `ProposalAiNarrativeRejected`, `ProposalsFailing`
  - dashboard row *Proposals*

## Compliance boundary

This is designed as **education on a virtual portfolio**:
- there is no real-money execution and no product placement
- disclaimers appear in the API, the page and the explanation
- "ideas" are framed as research examples

The questionnaire follows the structure of a MiFID II suitability assessment, but that does **not** make the output suitable advice. Using the engine for real money would need, at least:
- compliance sign-off on the questionnaire and scoring
- product governance and target-market checks for every instrument
- cost and charges disclosure
- a suitability report per recommendation, with record-keeping
- independent validation of the models (see `forecasting/MODEL_CARDS.md`)
- a human review step

Review the wording of the disclaimers and the "ideas" with compliance before customers see this page.

## Known limitations (v1)

- **Bonds:** the universe has no bond instruments, so the bond part is explained with yields and has no named examples.
- **Practice prices:** the practice portfolio trades simulated prices (the app's practice market), so its comparison uses simulated volatility.
- **Calm-market estimates:** expected volatility reflects *current* conditions (21-day forecasts). In calm markets it is lower than long-run averages; the stress tests carry the long-run tail risk.
- **Tables are judgement:** strategic weights and volatility bands are set by hand. They are documented in `engine.py` and should be reviewed by the bank's investment committee.
