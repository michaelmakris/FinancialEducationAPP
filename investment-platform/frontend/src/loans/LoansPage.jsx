import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../auth/bff.js";
import { useCoach } from "../coach/coachContext.js";
import { loanPlan, monthlyPayment } from "./loanMath.js";

// Loans and interest rates: today's real rates (ECB, Euribor, Greek mortgage averages from the
// API), a fixed vs variable calculator, "what if Euribor moves" and the history of Euribor.
// Education only: real offers depend on the bank, the borrower and fees.

const T = {
  en: {
    title: "Loans & interest rates", sub: "How a loan costs you money, and what changes between a fixed and a variable rate. Example figures, not an offer.",
    today: "Today's rates", ecb: "ECB deposit rate", euribor: "3-month Euribor", mortgage: "Greek new mortgages (average)", deposit: "Greek term deposits (average)",
    calc: "Loan calculator", mortgageType: "Mortgage", personalType: "Car / personal loan", amount: "Amount (EUR)", years: "Years",
    fixed: "Fixed rate", variable: "Variable rate", fixedRate: "Fixed rate (% a year)", margin: "Bank margin over Euribor (%)",
    rateNow: "Rate today", monthly: "Monthly payment", totalPaid: "Total you pay back", totalInterest: "Total interest",
    interestShare: (p) => `Interest is ${p} of what you borrowed`,
    yearly: "Each year: interest vs repayment", interest: "Interest", principal: "Repayment of the loan",
    whatIf: "What if Euribor changes?", whatIfSub: "A variable payment follows Euribor; a fixed one doesn't. Simplified: the new rate applies to the whole loan.",
    change: "Euribor change", varPay: "Variable payment", vsToday: "vs today", fixedPay: "Fixed payment",
    history: "3-month Euribor since 2010", historySub: "Variable rates follow this. Below zero in 2015–2022, then the fastest rise in decades.",
    learn: "Understand it", ask: "Ask Τσιμπ about loans", note: "Example only: real loans also have fees, insurance and checks on your income.",
  },
  el: {
    title: "Δάνεια & επιτόκια", sub: "Πώς σε κοστίζει ένα δάνειο και τι αλλάζει ανάμεσα σε σταθερό και κυμαινόμενο επιτόκιο. Ενδεικτικά νούμερα, όχι προσφορά.",
    today: "Τα σημερινά επιτόκια", ecb: "Επιτόκιο καταθέσεων ΕΚΤ", euribor: "Euribor 3 μηνών", mortgage: "Νέα στεγαστικά στην Ελλάδα (μέσος όρος)", deposit: "Προθεσμιακές καταθέσεις (μέσος όρος)",
    calc: "Υπολογιστής δανείου", mortgageType: "Στεγαστικό", personalType: "Αυτοκίνητο / καταναλωτικό", amount: "Ποσό (€)", years: "Χρόνια",
    fixed: "Σταθερό επιτόκιο", variable: "Κυμαινόμενο επιτόκιο", fixedRate: "Σταθερό επιτόκιο (% τον χρόνο)", margin: "Περιθώριο τράπεζας πάνω από το Euribor (%)",
    rateNow: "Επιτόκιο σήμερα", monthly: "Μηνιαία δόση", totalPaid: "Σύνολο που επιστρέφεις", totalInterest: "Συνολικοί τόκοι",
    interestShare: (p) => `Οι τόκοι είναι το ${p} του ποσού που δανείστηκες`,
    yearly: "Κάθε χρόνο: τόκοι και αποπληρωμή", interest: "Τόκοι", principal: "Αποπληρωμή κεφαλαίου",
    whatIf: "Κι αν αλλάξει το Euribor;", whatIfSub: "Η κυμαινόμενη δόση ακολουθεί το Euribor· η σταθερή όχι. Απλοποίηση: το νέο επιτόκιο ισχύει για όλο το δάνειο.",
    change: "Αλλαγή Euribor", varPay: "Κυμαινόμενη δόση", vsToday: "σε σχέση με σήμερα", fixedPay: "Σταθερή δόση",
    history: "Euribor 3 μηνών από το 2010", historySub: "Τα κυμαινόμενα επιτόκια το ακολουθούν. Κάτω από το μηδέν το 2015–2022, μετά η πιο γρήγορη άνοδος εδώ και δεκαετίες.",
    learn: "Κατάλαβέ το", ask: "Ρώτα τον Τσιμπ για δάνεια", note: "Μόνο παράδειγμα: τα πραγματικά δάνεια έχουν και έξοδα, ασφάλειες και έλεγχο εισοδήματος.",
  },
};

const TOPICS = {
  en: [
    ["What is interest?", "Interest is the price of borrowing money, as a percentage per year. On a loan you repay the amount you borrowed (the capital) plus interest. Compare offers by the APR (annual percentage rate), which also includes fees."],
    ["Fixed or variable?", "A fixed rate stays the same for an agreed period, so your payment is predictable. A variable rate = Euribor + the bank's margin, so the payment goes up and down with Euribor. Fixed usually starts a little higher: you pay for certainty."],
    ["What are Euribor and the margin?", "Euribor is the rate at which European banks lend to each other; it moves with the ECB's rates. The margin (spread) is the bank's extra percentage, fixed in your contract. Your variable rate is the two added together."],
    ["Why is the interest higher at the start?", "Each payment first covers the interest on what you still owe. Early on you owe the most, so most of the payment is interest; later more of it pays down the loan. The yearly chart above shows this."],
    ["Paying off early", "Repaying part of the loan early cuts the interest you pay later. Check the contract: some fixed-rate loans charge a fee for early repayment."],
    ["How much can I afford?", "A common rule of thumb is to keep all loan payments under about a third of your monthly net income, and to check that you could still pay if a variable rate rose by 2 percentage points."],
  ],
  el: [
    ["Τι είναι ο τόκος;", "Ο τόκος είναι η τιμή του δανεισμού, ως ποσοστό τον χρόνο. Σε ένα δάνειο επιστρέφεις το ποσό που πήρες (το κεφάλαιο) συν τους τόκους. Σύγκρινε προσφορές με το ΣΕΠΕ (συνολικό ετήσιο πραγματικό επιτόκιο), που περιλαμβάνει και τα έξοδα."],
    ["Σταθερό ή κυμαινόμενο;", "Το σταθερό επιτόκιο μένει ίδιο για μια συμφωνημένη περίοδο, οπότε η δόση είναι προβλέψιμη. Το κυμαινόμενο = Euribor + περιθώριο της τράπεζας, οπότε η δόση ανεβοκατεβαίνει με το Euribor. Το σταθερό συνήθως ξεκινά λίγο ψηλότερα: πληρώνεις για τη βεβαιότητα."],
    ["Τι είναι το Euribor και το περιθώριο;", "Το Euribor είναι το επιτόκιο με το οποίο δανείζονται μεταξύ τους οι ευρωπαϊκές τράπεζες· κινείται μαζί με τα επιτόκια της ΕΚΤ. Το περιθώριο (spread) είναι το επιπλέον ποσοστό της τράπεζας, σταθερό στη σύμβαση. Το κυμαινόμενο επιτόκιό σου είναι το άθροισμά τους."],
    ["Γιατί στην αρχή πληρώνω περισσότερους τόκους;", "Κάθε δόση καλύπτει πρώτα τον τόκο για ό,τι χρωστάς ακόμη. Στην αρχή χρωστάς τα περισσότερα, άρα το μεγαλύτερο μέρος της δόσης είναι τόκοι· αργότερα περισσότερο πάει στο κεφάλαιο. Το ετήσιο γράφημα πιο πάνω το δείχνει."],
    ["Πρόωρη αποπληρωμή", "Αν επιστρέψεις νωρίτερα μέρος του δανείου, γλιτώνεις τόκους. Έλεγξε τη σύμβαση: κάποια δάνεια σταθερού επιτοκίου έχουν χρέωση για πρόωρη εξόφληση."],
    ["Πόσο μπορώ να αντέξω;", "Ένας συνηθισμένος κανόνας: όλες οι δόσεις δανείων κάτω από περίπου το ένα τρίτο του μηνιαίου καθαρού εισοδήματος, και έλεγχος ότι θα μπορούσες να πληρώνεις αν το κυμαινόμενο ανέβαινε 2 ποσοστιαίες μονάδες."],
  ],
};

const PRESETS = { mortgage: { amount: 150000, years: 25 }, personal: { amount: 15000, years: 5, fixedRate: 9 } };
const SCENARIOS = [-1, 0, 1, 2, 3];

const fmt = (lang) => (v, d = 0) => v == null || !isFinite(v) ? "–"
  : v.toLocaleString(lang === "el" ? "el-GR" : "en-GB", { style: "currency", currency: "EUR", maximumFractionDigits: d, minimumFractionDigits: d });
const pctf = (lang) => (v, d = 2) => v == null || !isFinite(v) ? "–" : `${v.toLocaleString(lang === "el" ? "el-GR" : "en-GB", { maximumFractionDigits: d, minimumFractionDigits: 0 })}%`;

function Card({ title, sub, children }) {
  return (
    <div className="ip-card">
      {title && <div className="ip-card-title" style={{ marginBottom: sub ? 2 : 10 }}>{title}</div>}
      {sub && <div style={{ fontSize: 12.5, color: "#636B7E", marginBottom: 10 }}>{sub}</div>}
      {children}
    </div>
  );
}

function Stat({ label, value, strong }) {
  return (
    <div>
      <div className="ip-label">{label}</div>
      <div style={{ fontSize: strong ? 24 : 17, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

export default function LoansPage() {
  const { lang, ask } = useCoach();
  const t = T[lang] || T.en;
  const eur = fmt(lang), pct = pctf(lang);
  const [rates, setRates] = useState({});
  const [history, setHistory] = useState([]);
  const [kind, setKind] = useState("mortgage");
  const [amount, setAmount] = useState(PRESETS.mortgage.amount);
  const [years, setYears] = useState(PRESETS.mortgage.years);
  const [type, setType] = useState("fixed");
  const [fixedRate, setFixedRate] = useState("");     // "" = use today's Greek mortgage average
  const [margin, setMargin] = useState(2);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    let alive = true;
    api("/v1/macro/snapshot").then((s) => {
      if (!alive) return;
      const out = {};
      for (const i of s.indicators || []) if (i.snapshot) out[i.id] = i.snapshot;
      setRates(out);
    }).catch(() => {});
    api("/v1/macro/indicators/euribor_3m/series?start=2010-01-01").then((s) => {
      if (alive) setHistory(s.points.map((p) => ({ date: String(p.period_date).slice(0, 7), value: p.value })));
    }).catch(() => {});
    return () => { alive = false; };
  }, []);

  const euribor = rates.euribor_3m?.value ?? null;
  const defaultFixed = kind === "personal" ? PRESETS.personal.fixedRate : rates.mortgage_rate?.value ?? 3.5;
  const fixedValue = fixedRate === "" ? defaultFixed : Number(fixedRate);
  const variableRate = euribor != null ? Math.max(0, euribor) + Number(margin) : null;
  const rate = type === "fixed" ? fixedValue : variableRate;

  const plan = useMemo(() => (rate == null ? null : loanPlan(Number(amount), rate, Number(years))), [amount, rate, years]);
  const fixedPayment = monthlyPayment(Number(amount), fixedValue, Number(years));

  const choose = (k) => {
    setKind(k);
    setAmount(PRESETS[k].amount);
    setYears(PRESETS[k].years);
    setFixedRate("");
  };

  const when = (s) => s ? new Date(s.obs_date).toLocaleDateString(lang === "el" ? "el-GR" : "en-GB", { month: "short", year: "numeric" }) : "";

  return (
    <div>
      <h1 className="ip-page-title">{t.title}</h1>
      <p className="ip-page-sub">{t.sub}</p>

      <Card title={t.today}>
        <div className="ip-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
          {[["ecb_dfr", t.ecb], ["euribor_3m", t.euribor], ["mortgage_rate", t.mortgage], ["deposit_rate", t.deposit]].map(([id, label]) => (
            <div key={id}>
              <div className="ip-label">{label}</div>
              <div style={{ fontSize: 20, fontWeight: 600 }}>{pct(rates[id]?.value)}</div>
              <div style={{ fontSize: 11.5, color: "#636B7E" }}>{when(rates[id])}</div>
            </div>
          ))}
        </div>
      </Card>

      <Card title={t.calc}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
          <span className={`ip-chip ${kind === "mortgage" ? "on" : ""}`} onClick={() => choose("mortgage")}>{t.mortgageType}</span>
          <span className={`ip-chip ${kind === "personal" ? "on" : ""}`} onClick={() => choose("personal")}>{t.personalType}</span>
        </div>
        <div className="ip-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10, marginBottom: 12 }}>
          <div>
            <label className="ip-label">{t.amount}</label>
            <input className="ip-input" type="number" inputMode="numeric" min="1000" step="1000" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
          <div>
            <label className="ip-label">{t.years}: {years}</label>
            <input type="range" min="1" max="40" value={years} onChange={(e) => setYears(e.target.value)} style={{ width: "100%" }} aria-label={t.years} />
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
          <span className={`ip-chip ${type === "fixed" ? "on" : ""}`} onClick={() => setType("fixed")}>{t.fixed}</span>
          <span className={`ip-chip ${type === "variable" ? "on" : ""}`} onClick={() => setType("variable")}>{t.variable}</span>
        </div>
        <div className="ip-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10, marginBottom: 14 }}>
          {type === "fixed" ? (
            <div>
              <label className="ip-label">{t.fixedRate}</label>
              <input className="ip-input" type="number" inputMode="decimal" step="0.1" min="0" value={fixedRate === "" ? Number(defaultFixed).toFixed(2) : fixedRate}
                onChange={(e) => setFixedRate(e.target.value)} />
            </div>
          ) : (
            <div>
              <label className="ip-label">{t.margin}</label>
              <input className="ip-input" type="number" inputMode="decimal" step="0.1" min="0" value={margin} onChange={(e) => setMargin(e.target.value)} />
              <div style={{ fontSize: 11.5, color: "#636B7E", marginTop: 4 }}>Euribor {pct(euribor)} + {pct(Number(margin))}</div>
            </div>
          )}
          <Stat label={t.rateNow} value={pct(rate)} />
        </div>

        {plan && (
          <>
            <div className="ip-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12, marginBottom: 6 }}>
              <Stat label={t.monthly} value={eur(plan.payment, 2)} strong />
              <Stat label={t.totalPaid} value={eur(plan.totalPaid)} />
              <Stat label={t.totalInterest} value={eur(plan.totalInterest)} />
            </div>
            <div style={{ fontSize: 13, color: "#636B7E", marginBottom: 12 }}>{t.interestShare(pct(plan.totalInterest / Number(amount) * 100, 0))}</div>
            <div className="ip-label">{t.yearly}</div>
            <div style={{ width: "100%", height: 220 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={plan.years} margin={{ top: 6, right: 4, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E6E9F2" vertical={false} />
                  <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} width={56} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                  <Tooltip formatter={(v, name) => [eur(v), name]} labelFormatter={(y) => `${t.years}: ${y}`} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="interest" name={t.interest} stackId="a" fill="#EF8A3D" />
                  <Bar dataKey="principal" name={t.principal} stackId="a" fill="#2F5BFF" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
        <div style={{ fontSize: 11.5, color: "#636B7E", marginTop: 8 }}>{t.note}</div>
      </Card>

      {euribor != null && (
        <Card title={t.whatIf} sub={t.whatIfSub}>
          <div className="ip-table-wrap">
            <table className="ip-table">
              <thead><tr><th>{t.change}</th><th>Euribor</th><th>{t.varPay}</th><th>{t.vsToday}</th><th>{t.fixedPay}</th></tr></thead>
              <tbody>
                {SCENARIOS.map((d) => {
                  const e = Math.max(0, euribor + d);
                  const pay = monthlyPayment(Number(amount), e + Number(margin), Number(years));
                  const base = monthlyPayment(Number(amount), Math.max(0, euribor) + Number(margin), Number(years));
                  return (
                    <tr key={d} style={d === 0 ? { fontWeight: 600 } : undefined}>
                      <td>{d > 0 ? `+${d}` : d} pp</td>
                      <td>{pct(e)}</td>
                      <td>{eur(pay, 0)}</td>
                      <td className={pay > base ? "ip-neg" : pay < base ? "ip-pos" : undefined}>{d === 0 ? "–" : `${pay > base ? "+" : ""}${eur(pay - base, 0)}`}</td>
                      <td>{eur(fixedPayment, 0)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {history.length > 1 && (
        <Card title={t.history} sub={t.historySub}>
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={history} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E6E9F2" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                <YAxis tick={{ fontSize: 11 }} width={40} tickFormatter={(v) => `${v}%`} />
                <Tooltip formatter={(v) => [pct(v), "Euribor"]} />
                <ReferenceLine y={0} stroke="#94A3B8" />
                <Line type="monotone" dataKey="value" stroke="var(--ip-accent, #2F5BFF)" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      <Card title={t.learn}>
        {(TOPICS[lang] || TOPICS.en).map(([q, a], i) => (
          <div key={q} style={{ borderTop: i ? "1px solid #E6E9F2" : 0 }}>
            <button onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}
              style={{ width: "100%", textAlign: "left", background: "none", border: 0, padding: "12px 0", fontSize: 14.5, fontWeight: 600, cursor: "pointer", minHeight: 44 }}>
              {open === i ? "−" : "+"} {q}
            </button>
            {open === i && <div style={{ fontSize: 14, lineHeight: 1.55, paddingBottom: 12 }}>{a}</div>}
          </div>
        ))}
        <button className="ip-btn secondary" style={{ marginTop: 10 }} onClick={() => ask(lang === "el" ? "Τι να προσέξω σε ένα στεγαστικό δάνειο;" : "What should I watch out for in a mortgage?")}>
          🦟 {t.ask}
        </button>
      </Card>
    </div>
  );
}
