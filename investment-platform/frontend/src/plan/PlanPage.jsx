import { useEffect, useState } from "react";
import { api } from "../auth/bff.js";
import { ModelPicker } from "../llm/ModelPicker.jsx";
import { useModelChoice } from "../llm/useModelChoice.js";

// "My plan": risk questionnaire -> profile -> educational proposal for the practice portfolio.
// All numbers come from the API (/v1/profile, /v1/proposals); nothing is computed here.

const SLEEVE_COLOR = { cash: "#94A3B8", bonds: "#0EA65C", global_equity: "#2F5BFF", greek_equity: "#7C3AED", crypto: "#F97316" };
const pct = (x, d = 0) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);
const signedPct = (x) => (x == null ? "–" : `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)}%`);
const muted = { color: "#636B7E", fontSize: 13 };

function Questionnaire({ onDone, initial }) {
  const [q, setQ] = useState(null);
  const [answers, setAnswers] = useState(initial || {});
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/v1/profile/questionnaire").then(setQ).catch((e) => setError(e.message)); }, []);
  if (!q) return error ? <p role="alert">{error}</p> : <p style={muted}>Loading questions…</p>;
  const complete = q.questions.every((x) => answers[x.id]);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await api("/v1/profile", { method: "POST", body: { answers } }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="ip-card" style={{ padding: 20 }}>
      <h2 style={{ marginTop: 0 }}>Your risk profile</h2>
      <p style={muted}>Eight short questions. Your answers shape an illustrative plan for your practice portfolio.</p>
      {q.questions.map((x, i) => (
        <fieldset key={x.id} style={{ border: 0, padding: 0, margin: "18px 0 0" }}>
          <legend style={{ fontWeight: 600, marginBottom: 8 }}>{i + 1}. {x.text}</legend>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {x.options.map((o) => (
              <span key={o.value} role="radio" aria-checked={answers[x.id] === o.value} tabIndex={0}
                className={`ip-chip ${answers[x.id] === o.value ? "on" : ""}`}
                onClick={() => setAnswers({ ...answers, [x.id]: o.value })}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setAnswers({ ...answers, [x.id]: o.value })}>
                {o.label}
              </span>
            ))}
          </div>
        </fieldset>
      ))}
      {error && <p role="alert" style={{ color: "#EF3D3D" }}>{error}</p>}
      <button type="button" className="ip-btn" style={{ marginTop: 20 }} disabled={!complete || busy} onClick={submit}>
        {busy ? "Saving…" : "See my profile"}
      </button>
    </div>
  );
}

function AllocationBar({ allocation }) {
  return (
    <div style={{ display: "flex", height: 18, borderRadius: 9, overflow: "hidden", margin: "8px 0 4px" }} aria-hidden="true">
      {allocation.filter((a) => a.weight_pct > 0).map((a) => (
        <div key={a.sleeve} title={`${a.name} ${a.weight_pct}%`} style={{ width: `${a.weight_pct}%`, background: SLEEVE_COLOR[a.sleeve] }} />
      ))}
    </div>
  );
}

function Proposal({ p }) {
  const cur = p.current && !p.current.empty ? p.current : null;
  const curStress = Object.fromEntries((cur?.stress_tests || []).map((s) => [s.scenario, s.portfolio_return]));
  const ideas = p.allocation.filter((a) => a.ideas && a.ideas.length);
  return (
    <div className="ip-grid">
      <div className="ip-card" style={{ padding: 20 }}>
        <div style={muted}>Profile {p.profile} of 7</div>
        <h2 style={{ margin: "2px 0 8px" }}>{p.profile_name}</h2>
        <AllocationBar allocation={p.allocation} />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, fontSize: 13 }}>
          {p.allocation.filter((a) => a.weight_pct > 0).map((a) => (
            <span key={a.sleeve}><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: SLEEVE_COLOR[a.sleeve], marginRight: 5 }} />{a.name} {a.weight_pct}%</span>
          ))}
        </div>
        <p style={{ marginBottom: 0 }}>Expected volatility about <strong>{pct(p.expected_volatility, 1)}</strong> a year (limit for your profile {pct(p.volatility_band)}).
          Hardest tested scenario: <strong>{p.worst_scenario}</strong>, {signedPct(p.worst_scenario_return)}.</p>
      </div>

      <div className="ip-card" style={{ padding: 20 }}>
        <h3 style={{ marginTop: 0 }}>In plain words</h3>
        <p style={{ lineHeight: 1.6 }}>{p.narrative}</p>
        <p style={{ ...muted, marginBottom: 0 }}>{p.narrative_source === "ai" ? "Wording assisted by AI and checked against the numbers." : "Generated from the numbers above."}</p>
      </div>

      <div className="ip-card" style={{ padding: 20 }}>
        <h3 style={{ marginTop: 0 }}>Plan vs your practice portfolio</h3>
        <div className="ip-table-wrap">
          <table className="ip-table">
            <thead><tr><th>Asset class</th><th>Plan</th><th>Now</th><th>Expected volatility</th></tr></thead>
            <tbody>
              {p.allocation.map((a) => (
                <tr key={a.sleeve}>
                  <td>{a.name}</td><td>{a.weight_pct}%</td>
                  <td>{cur ? `${cur.weights_pct[a.sleeve] ?? 0}%` : "–"}</td>
                  <td>{a.sleeve === "cash" ? "≈0%" : pct(a.expected_volatility)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {cur && cur.flags.length > 0 && (
          <ul style={{ marginBottom: 0 }}>{cur.flags.map((f) => <li key={f.code}>{f.text}</li>)}</ul>
        )}
        {p.adjustments.length > 1 && (
          <>
            <h4>Adjustments made</h4>
            <ul style={{ marginBottom: 0 }}>{p.adjustments.slice(1).map((a) => <li key={a.step}>{a.detail}</li>)}</ul>
          </>
        )}
      </div>

      <div className="ip-card" style={{ padding: 20 }}>
        <h3 style={{ marginTop: 0 }}>What could happen in a bad market</h3>
        <div className="ip-table-wrap">
          <table className="ip-table">
            <thead><tr><th>Scenario</th><th>Plan</th>{cur && <th>Your portfolio now</th>}<th>Plan, on €10,000</th></tr></thead>
            <tbody>
              {p.stress_tests.map((s) => (
                <tr key={s.scenario}>
                  <td>{s.name}{s.historical && <div style={muted}>real moves, {s.period}</div>}</td>
                  <td>{signedPct(s.portfolio_return)}</td>
                  {cur && <td>{signedPct(curStress[s.scenario])}</td>}
                  <td>€{s.on_10000_eur.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p style={{ ...muted, marginBottom: 0 }}>Scenarios other than the historical replay are round-number hypotheticals, not forecasts.</p>
      </div>

      {ideas.length > 0 && (
        <div className="ip-card" style={{ padding: 20 }}>
          <h3 style={{ marginTop: 0 }}>Ideas to research</h3>
          <p style={muted}>Examples for learning, chosen by annual-report quality and risk. Not recommendations.</p>
          {ideas.map((a) => (
            <div key={a.sleeve} style={{ marginTop: 10 }}>
              <strong>{a.name}</strong>
              <ul style={{ margin: "4px 0 0" }}>
                {a.ideas.map((i) => (
                  <li key={i.ticker}>{i.ticker} {i.name && i.name !== i.ticker ? `– ${i.name}` : ""}
                    {i.quality_score != null && `, quality ${Math.round(i.quality_score)}/100`}
                    {i.expected_volatility != null && `, volatility ${pct(i.expected_volatility)}`}
                    {i.p_loss_10pct_21d != null && `, ${pct(i.p_loss_10pct_21d)} chance of a >10% fall in a month`}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {p.context.length > 0 && (
        <div className="ip-card" style={{ padding: 20 }}>
          <h3 style={{ marginTop: 0 }}>The economy right now</h3>
          <ul style={{ marginBottom: 0 }}>{p.context.map((c) => <li key={c.topic}>{c.text}</li>)}</ul>
        </div>
      )}

      <div className="ip-card" style={{ padding: 20, borderColor: "#B45309" }}>
        <strong>Important</strong>
        <p style={{ marginBottom: 8 }}>{p.disclaimer}</p>
        <details style={muted}>
          <summary>Data and models used</summary>
          <p>Market data as of {p.data_as_of?.snapshots ?? "–"}; risk estimates as of {p.data_as_of?.risk_estimates ?? "–"}.
            Market conditions: {p.market_conditions ?? "not available"}.</p>
          <p>Proxies: {Object.entries(p.sources?.proxies || {}).map(([k, v]) => `${k}: ${v}`).join("; ")}.</p>
          <p>Models: {Object.entries(p.sources?.models || {}).map(([k, v]) => `${k} v${v.version} (${v.status})`).join(", ")}.</p>
          {p.sources?.assumptions?.length > 0 && <p>Assumptions: {p.sources.assumptions.join("; ")}.</p>}
          <p>Plan #{p.id}, engine {p.engine_version}, created {new Date(p.created_at + "Z").toLocaleString()}.</p>
        </details>
      </div>
    </div>
  );
}

// Where the customer is: no profile yet -> questionnaire; profile but no plan -> profile; else the latest plan.
async function loadPlanState() {
  try {
    const profile = await api("/v1/profile");
    try {
      return { step: "plan", profile, proposal: await api("/v1/proposals/latest") };
    } catch {
      return { step: "profile", profile };
    }
  } catch (e) {
    return e.status === 404 ? { step: "questionnaire" } : { step: "error", message: e.message };
  }
}

export default function PlanPage() {
  const [state, setState] = useState({ step: "loading" });
  const [useAi, setUseAi] = useState(false);
  const model = useModelChoice();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    loadPlanState().then((next) => { if (alive) setState(next); });
    return () => { alive = false; };
  }, []);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const proposal = await api("/v1/proposals", { method: "POST", body: { use_ai: useAi, provider: useAi ? model.value : null } });
      setState((s) => ({ ...s, step: "plan", proposal }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h1 className="ip-page-title">My plan</h1>
      <p className="ip-page-sub">An educational, illustrative plan for your practice portfolio, built from your answers and today's market data. Not investment advice.</p>
      {state.step === "loading" && <p style={muted}>Loading…</p>}
      {state.step === "error" && <p role="alert">{state.message}</p>}
      {state.step === "questionnaire" && <Questionnaire onDone={(profile) => setState({ step: "profile", profile })} initial={state.answers} />}
      {(state.step === "profile" || state.step === "plan") && (
        <div className="ip-card" style={{ padding: 16, marginBottom: 12, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 }}>
          <span><strong>{state.profile.profile_name}</strong> ({state.profile.profile} of 7)
            {state.profile.reasons?.length > 0 && <span style={muted}>: {state.profile.reasons.join("; ")}</span>}</span>
          <span style={{ flex: 1 }} />
          <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
            <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} /> Friendlier wording (AI, fact-checked)
          </label>
          {useAi && <ModelPicker providers={model.providers} value={model.value} onChange={model.change} />}
          <button type="button" className="ip-btn" disabled={busy} onClick={generate}>
            {busy ? "Building…" : state.step === "plan" ? "Refresh plan" : "Create my plan"}
          </button>
          <button type="button" className="ip-btn secondary" onClick={() => setState({ step: "questionnaire", answers: state.profile.answers })}>
            Retake questionnaire
          </button>
        </div>
      )}
      {error && <p role="alert" style={{ color: "#EF3D3D" }}>{error}</p>}
      {state.step === "plan" && state.proposal && <Proposal p={state.proposal} />}
    </div>
  );
}
