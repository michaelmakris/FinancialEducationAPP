import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { bffFetch, onSignedOut, setCsrfToken } from "./bff.js";

// Same palette and fonts as App.jsx.
const COLOR = {
  ink: "#0B1220", paper: "#F3F5FA", panel: "#FFFFFF", line: "#E6E9F2", lineStrong: "#CDD3E3",
  muted: "#636B7E", accent: "#2F5BFF", accentSoft: "#EAF0FF", negative: "#EF3D3D", negativeSoft: "#FEECEC",
  positive: "#0EA65C", positiveSoft: "#E1F9EC", gradient: "linear-gradient(135deg, #2F5BFF 0%, #7C3AED 100%)",
};
const FONT_DISPLAY = "'Space Grotesk', 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
const FONT_SANS = "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

const S = {
  field: { width: "100%", padding: "11px 12px", borderRadius: 10, border: `1px solid ${COLOR.lineStrong}`,
    fontFamily: FONT_SANS, fontSize: 15, color: COLOR.ink, background: COLOR.panel, outline: "none" },
  label: { display: "block", fontSize: 13, fontWeight: 600, color: COLOR.ink, margin: "14px 0 6px" },
  primary: { width: "100%", marginTop: 20, padding: "12px 14px", border: 0, borderRadius: 10, background: COLOR.accent,
    color: "#fff", fontWeight: 600, fontSize: 15, fontFamily: FONT_SANS, cursor: "pointer" },
  secondary: { padding: "8px 12px", border: `1px solid ${COLOR.lineStrong}`, borderRadius: 10, background: COLOR.panel,
    color: COLOR.ink, fontSize: 14, fontFamily: FONT_SANS, cursor: "pointer" },
  link: { background: "none", border: 0, color: COLOR.accent, fontWeight: 600, cursor: "pointer", fontSize: 14, padding: 0, fontFamily: FONT_SANS },
  h1: { fontFamily: FONT_DISPLAY, fontSize: 24, margin: 0, color: COLOR.ink },
  h2: { fontFamily: FONT_DISPLAY, fontSize: 17, margin: "0 0 4px", color: COLOR.ink },
  muted: { color: COLOR.muted, margin: "6px 0 4px", fontSize: 14 },
};

function Note({ kind = "info", children }) {
  const colors = { info: [COLOR.accentSoft, COLOR.ink], error: [COLOR.negativeSoft, COLOR.negative], ok: [COLOR.positiveSoft, "#0B7A44"] }[kind];
  return (
    <p role={kind === "error" ? "alert" : "status"}
      style={{ background: colors[0], color: colors[1], borderRadius: 10, padding: "10px 12px", fontSize: 14, marginTop: 14 }}>
      {children}
    </p>
  );
}

// A <form> only when it submits something; otherwise a plain box (so it can hold its own inner forms).
function Card({ children, onSubmit }) {
  const Box = onSubmit ? "form" : "div";
  return (
    <div style={{ minHeight: "100%", display: "grid", placeItems: "center", background: COLOR.paper, padding: 16, fontFamily: FONT_SANS }}>
      <Box onSubmit={onSubmit} style={{ width: "100%", maxWidth: 420, background: COLOR.panel,
        border: `1px solid ${COLOR.line}`, borderRadius: 16, padding: "28px 24px", boxShadow: "0 10px 30px rgba(11,18,32,0.06)" }}>
        <div style={{ width: 40, height: 40, borderRadius: 12, background: COLOR.gradient, marginBottom: 16 }} aria-hidden="true" />
        {children}
      </Box>
    </div>
  );
}

function Field({ id, label, ...props }) {
  return (
    <>
      <label style={S.label} htmlFor={id}>{label}</label>
      <input id={id} style={S.field} {...props} />
    </>
  );
}

function Submit({ busy, children }) {
  return <button type="submit" disabled={busy} style={{ ...S.primary, opacity: busy ? 0.7 : 1, cursor: busy ? "wait" : "pointer" }}>{busy ? "Please wait…" : children}</button>;
}

// Small hook: run an async action with busy/error state.
function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = useCallback(async (fn) => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e.message);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, setError, run };
}

const PASSWORD_HINT = "At least 12 characters. A short sentence works well.";

/* ---------------------------------------------------------------- signed-out screens */

function SignIn({ onSignedIn, go, notice }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState(null);
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const { busy, error, setError, run } = useAction();

  const submitPassword = (e) => {
    e.preventDefault();
    run(async () => {
      const data = await bffFetch("/bff/auth/login", { method: "POST", body: { email, password } });
      setPassword("");
      if (data.mfa_required) setMfaToken(data.mfa_token);
      else onSignedIn(data);
    });
  };
  const submitCode = (e) => {
    e.preventDefault();
    run(async () => {
      const body = useRecovery ? { mfa_token: mfaToken, recovery_code: code } : { mfa_token: mfaToken, code };
      try {
        onSignedIn(await bffFetch("/bff/auth/login/mfa", { method: "POST", body }));
      } catch (err) {
        if (/start again/i.test(err.message)) setMfaToken(null);
        throw err;
      }
    });
  };

  if (mfaToken) {
    return (
      <Card onSubmit={submitCode}>
        <h1 style={S.h1}>Two-step verification</h1>
        <p style={S.muted}>{useRecovery ? "Enter one of your recovery codes." : "Enter the 6-digit code from your authenticator app."}</p>
        <Field id="code" label={useRecovery ? "Recovery code" : "Code"} value={code} onChange={(e) => setCode(e.target.value)} required
          autoComplete="one-time-code" inputMode={useRecovery ? "text" : "numeric"} maxLength={useRecovery ? 20 : 6} autoFocus />
        {error && <Note kind="error">{error}</Note>}
        <Submit busy={busy}>Verify</Submit>
        <p style={{ textAlign: "center", margin: "16px 0 0" }}>
          <button type="button" style={S.link} onClick={() => { setUseRecovery(!useRecovery); setCode(""); setError(null); }}>
            {useRecovery ? "Use the authenticator app instead" : "Lost your phone? Use a recovery code"}
          </button>
        </p>
      </Card>
    );
  }
  return (
    <Card onSubmit={submitPassword}>
      <h1 style={S.h1}>Sign in</h1>
      <p style={S.muted}>Welcome back.</p>
      {notice && !error && <Note kind={notice.kind}>{notice.text}</Note>}
      <Field id="email" label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required maxLength={254} />
      <Field id="password" label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required maxLength={128} />
      <p style={{ textAlign: "right", margin: "8px 0 0" }}>
        <button type="button" style={{ ...S.link, fontSize: 13 }} onClick={() => go("forgot")}>Forgot password?</button>
      </p>
      {error && <Note kind="error">{error}</Note>}
      <Submit busy={busy}>Sign in</Submit>
      <p style={{ textAlign: "center", fontSize: 14, color: COLOR.muted, margin: "16px 0 0" }}>
        New here? <button type="button" style={S.link} onClick={() => go("register")}>Create an account</button>
      </p>
    </Card>
  );
}

function Register({ go }) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useAction();
  const submit = (e) => {
    e.preventDefault();
    run(async () => {
      await bffFetch("/bff/auth/register", { method: "POST", body: { email, password, full_name: fullName } });
      go("check-inbox", { email });
    });
  };
  return (
    <Card onSubmit={submit}>
      <h1 style={S.h1}>Create your account</h1>
      <p style={S.muted}>Practise investing with real market data and a virtual portfolio.</p>
      <Field id="fullName" label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" required maxLength={200} />
      <Field id="email" label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required maxLength={254} />
      <Field id="password" label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" required minLength={12} maxLength={128} />
      <p style={{ color: COLOR.muted, fontSize: 12, margin: "6px 0 0" }}>{PASSWORD_HINT}</p>
      {error && <Note kind="error">{error}</Note>}
      <Submit busy={busy}>Create account</Submit>
      <p style={{ textAlign: "center", fontSize: 14, color: COLOR.muted, margin: "16px 0 0" }}>
        Already have an account? <button type="button" style={S.link} onClick={() => go("signin")}>Sign in</button>
      </p>
    </Card>
  );
}

function CheckInbox({ go, email, purpose }) {
  const { busy, error, run } = useAction();
  const [resent, setResent] = useState(false);
  const resend = () => run(async () => {
    await bffFetch("/bff/auth/resend-verification", { method: "POST", body: { email } });
    setResent(true);
  });
  return (
    <Card>
      <h1 style={S.h1}>Check your inbox</h1>
      <p style={S.muted}>
        {purpose === "reset"
          ? "If an account exists for that address, we've sent a link to choose a new password. It works once and expires in 30 minutes."
          : <>We've sent a confirmation link to <strong>{email}</strong>. Open it to activate your account.</>}
      </p>
      {resent && <Note kind="ok">If the address needs confirming, a new link is on its way.</Note>}
      {error && <Note kind="error">{error}</Note>}
      {purpose !== "reset" && (
        <button type="button" disabled={busy} style={{ ...S.secondary, marginTop: 18, width: "100%" }} onClick={resend}>Send the link again</button>
      )}
      <button type="button" style={{ ...S.primary }} onClick={() => go("signin")}>Back to sign in</button>
    </Card>
  );
}

function Forgot({ go }) {
  const [email, setEmail] = useState("");
  const { busy, error, run } = useAction();
  const submit = (e) => {
    e.preventDefault();
    run(async () => {
      await bffFetch("/bff/auth/password-reset/request", { method: "POST", body: { email } });
      go("check-inbox", { email, purpose: "reset" });
    });
  };
  return (
    <Card onSubmit={submit}>
      <h1 style={S.h1}>Reset your password</h1>
      <p style={S.muted}>Enter your account email and we'll send you a link.</p>
      <Field id="email" label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required maxLength={254} />
      {error && <Note kind="error">{error}</Note>}
      <Submit busy={busy}>Send reset link</Submit>
      <p style={{ textAlign: "center", margin: "16px 0 0" }}><button type="button" style={S.link} onClick={() => go("signin")}>Back to sign in</button></p>
    </Card>
  );
}

function ResetPassword({ token, go }) {
  const [password, setPassword] = useState("");
  const { busy, error, run } = useAction();
  const submit = (e) => {
    e.preventDefault();
    run(async () => {
      const r = await bffFetch("/bff/auth/password-reset/confirm", { method: "POST", body: { token, new_password: password } });
      go("signin", { notice: { kind: "ok", text: r.message } });
    });
  };
  return (
    <Card onSubmit={submit}>
      <h1 style={S.h1}>Choose a new password</h1>
      <p style={S.muted}>You'll be signed out everywhere and can sign in again with the new password.</p>
      <Field id="password" label="New password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" required minLength={12} maxLength={128} autoFocus />
      <p style={{ color: COLOR.muted, fontSize: 12, margin: "6px 0 0" }}>{PASSWORD_HINT}</p>
      {error && <Note kind="error">{error}</Note>}
      <Submit busy={busy}>Set password</Submit>
    </Card>
  );
}

function VerifyEmail({ token, go }) {
  const [error, setError] = useState(null);
  useEffect(() => {
    bffFetch("/bff/auth/verify-email", { method: "POST", body: { token } })
      .then((r) => go("signin", { notice: { kind: "ok", text: r.message } }))
      .catch((e) => setError(e.message));
  }, [token, go]);
  return (
    <Card>
      <h1 style={S.h1}>Confirming your email…</h1>
      {error && <><Note kind="error">{error}</Note><button type="button" style={S.primary} onClick={() => go("signin")}>Back to sign in</button></>}
    </Card>
  );
}

/* ---------------------------------------------------------------- MFA setup (shared by the forced screen and Security) */

function MfaSetup({ onDone }) {
  const [step, setStep] = useState("password");
  const [password, setPassword] = useState("");
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState(null);
  const { busy, error, run } = useAction();

  if (codes) {
    return (
      <div>
        <h2 style={S.h2}>Save your recovery codes</h2>
        <p style={S.muted}>Each code works once if you lose your phone. Store them somewhere safe: they won't be shown again.</p>
        <pre style={{ background: COLOR.paper, borderRadius: 10, padding: 12, columns: 2, fontSize: 14, margin: "12px 0" }}>{codes.join("\n")}</pre>
        <button type="button" style={S.secondary} onClick={() => navigator.clipboard?.writeText(codes.join("\n"))}>Copy</button>
        <button type="button" style={S.primary} onClick={onDone}>I've saved them</button>
      </div>
    );
  }
  if (step === "password") {
    return (
      <form onSubmit={(e) => { e.preventDefault(); run(async () => { setSetup(await bffFetch("/bff/auth/mfa/setup", { method: "POST", body: { password } })); setPassword(""); setStep("scan"); }); }}>
        <p style={S.muted}>Use an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password…). First confirm your password.</p>
        <Field id="mfa-pw" label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        {error && <Note kind="error">{error}</Note>}
        <Submit busy={busy}>Continue</Submit>
      </form>
    );
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); run(async () => { setCodes((await bffFetch("/bff/auth/mfa/enable", { method: "POST", body: { code } })).recovery_codes); }); }}>
      <p style={S.muted}>Scan this QR code with your authenticator app, then enter the 6-digit code it shows.</p>
      <img src={setup.qr_svg_data_uri} alt="QR code for your authenticator app" width={180} height={180} style={{ display: "block", margin: "12px auto" }} />
      <details style={{ fontSize: 13, color: COLOR.muted }}>
        <summary>Can't scan? Enter this key manually</summary>
        <code style={{ wordBreak: "break-all" }}>{setup.secret}</code>
      </details>
      <Field id="mfa-code" label="Code from the app" value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={6} required />
      {error && <Note kind="error">{error}</Note>}
      <Submit busy={busy}>Turn on two-step verification</Submit>
    </form>
  );
}

function MfaRequired({ onEnabled, onLogout }) {
  return (
    <Card>
      <h1 style={S.h1}>Protect your account</h1>
      <p style={S.muted}>Two-step verification is required. It takes a minute.</p>
      <MfaSetup onDone={onEnabled} />
      <p style={{ textAlign: "center", margin: "16px 0 0" }}><button type="button" style={S.link} onClick={onLogout}>Sign out</button></p>
    </Card>
  );
}

/* ---------------------------------------------------------------- Security panel */

function SecurityPanel({ account, onClose, refresh }) {
  const { customer, mfaRequired } = account;
  const [mode, setMode] = useState(null); // enable | disable | codes | password
  const [form, setForm] = useState({ password: "", code: "", newPassword: "" });
  const [newCodes, setNewCodes] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [msg, setMsg] = useState(null);
  const { busy, error, setError, run } = useAction();
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const loadSessions = useCallback(() => bffFetch("/bff/auth/sessions").then(setSessions).catch(() => {}), []);
  useEffect(() => { loadSessions(); }, [loadSessions]);
  const reset = () => { setMode(null); setForm({ password: "", code: "", newPassword: "" }); setError(null); };

  const submit = (e) => {
    e.preventDefault();
    run(async () => {
      if (mode === "disable") {
        await bffFetch("/bff/auth/mfa/disable", { method: "POST", body: { password: form.password, code: form.code } });
        setMsg("Two-step verification is off.");
      } else if (mode === "codes") {
        setNewCodes((await bffFetch("/bff/auth/mfa/recovery-codes", { method: "POST", body: { password: form.password, code: form.code } })).recovery_codes);
      } else if (mode === "password") {
        await bffFetch("/bff/auth/password", { method: "POST", body: { current_password: form.password, new_password: form.newPassword } });
        setMsg("Password changed. Your other devices were signed out.");
        loadSessions();
      }
      reset();
      refresh();
    });
  };

  const section = { borderTop: `1px solid ${COLOR.line}`, padding: "16px 0" };
  return (
    <div role="dialog" aria-modal="true" aria-label="Security settings" onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(11,18,32,0.35)", zIndex: 2000, display: "grid", placeItems: "center", padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: COLOR.panel, borderRadius: 16, width: "100%", maxWidth: 520, maxHeight: "90vh",
        overflowY: "auto", padding: "22px 24px", fontFamily: FONT_SANS, color: COLOR.ink }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <h1 style={{ ...S.h1, fontSize: 21 }}>Security</h1>
          <button type="button" style={S.secondary} onClick={onClose} aria-label="Close">Close</button>
        </div>
        {msg && <Note kind="ok">{msg}</Note>}

        <div style={section}>
          <h2 style={S.h2}>Two-step verification</h2>
          <p style={S.muted}>{customer.mfa_enabled ? `On. ${account.recoveryLeft ?? 0} recovery codes left.` : "Off. Add a code from your phone to every sign-in."}</p>
          {mode === "enable" && <MfaSetup onDone={() => { reset(); setMsg("Two-step verification is on."); refresh(); }} />}
          {newCodes && (
            <>
              <pre style={{ background: COLOR.paper, borderRadius: 10, padding: 12, columns: 2, fontSize: 14 }}>{newCodes.join("\n")}</pre>
              <button type="button" style={S.secondary} onClick={() => setNewCodes(null)}>I've saved them</button>
            </>
          )}
          {(mode === "disable" || mode === "codes") && (
            <form onSubmit={submit}>
              <Field id="s-pw" label="Password" type="password" value={form.password} onChange={set("password")} autoComplete="current-password" required />
              <Field id="s-code" label="Code from your authenticator app" value={form.code} onChange={set("code")} inputMode="numeric" maxLength={6} required />
              {error && <Note kind="error">{error}</Note>}
              <Submit busy={busy}>{mode === "disable" ? "Turn off" : "Generate new codes"}</Submit>
            </form>
          )}
          {!mode && !newCodes && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
              {!customer.mfa_enabled && <button type="button" style={S.secondary} onClick={() => setMode("enable")}>Turn on</button>}
              {customer.mfa_enabled && <button type="button" style={S.secondary} onClick={() => setMode("codes")}>New recovery codes</button>}
              {customer.mfa_enabled && !mfaRequired && <button type="button" style={S.secondary} onClick={() => setMode("disable")}>Turn off</button>}
            </div>
          )}
        </div>

        <div style={section}>
          <h2 style={S.h2}>Password</h2>
          {mode === "password" ? (
            <form onSubmit={submit}>
              <Field id="s-cur" label="Current password" type="password" value={form.password} onChange={set("password")} autoComplete="current-password" required />
              <Field id="s-new" label="New password" type="password" value={form.newPassword} onChange={set("newPassword")} autoComplete="new-password" minLength={12} maxLength={128} required />
              <p style={{ color: COLOR.muted, fontSize: 12, margin: "6px 0 0" }}>{PASSWORD_HINT}</p>
              {error && <Note kind="error">{error}</Note>}
              <Submit busy={busy}>Change password</Submit>
            </form>
          ) : (
            !mode && <button type="button" style={{ ...S.secondary, marginTop: 8 }} onClick={() => setMode("password")}>Change password</button>
          )}
        </div>

        <AccessKeysSection mfaEnabled={customer.mfa_enabled} />

        <div style={section}>
          <h2 style={S.h2}>Where you're signed in</h2>
          {sessions.map((s) => (
            <div key={s.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, padding: "8px 0", fontSize: 13 }}>
              <span style={{ minWidth: 0 }}>
                <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.user_agent || "Unknown device"}</span>
                <span style={{ color: COLOR.muted }}>{s.ip} · last active {new Date(s.last_seen_at + "Z").toLocaleString()}</span>
              </span>
              {s.current ? <span style={{ color: COLOR.positive, fontWeight: 600, flexShrink: 0 }}>This device</span> : (
                <button type="button" style={{ ...S.secondary, flexShrink: 0 }}
                  onClick={() => run(async () => { await bffFetch(`/bff/auth/sessions/${s.id}`, { method: "DELETE" }); loadSessions(); })}>
                  Sign out
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- AI assistant access keys (MCP) */

const MCP_URL = import.meta.env.VITE_MCP_URL || "http://localhost:8090/mcp";

function AccessKeysSection({ mfaEnabled }) {
  const [keys, setKeys] = useState([]);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", level: "read", days: 30, password: "", code: "" });
  const [created, setCreated] = useState(null);
  const { busy, error, setError, run } = useAction();
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const load = useCallback(() => bffFetch("/bff/auth/access-keys").then(setKeys).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);

  const submit = (e) => {
    e.preventDefault();
    run(async () => {
      const body = { name: form.name, level: form.level, days: Number(form.days), password: form.password };
      if (mfaEnabled) body.code = form.code;
      setCreated(await bffFetch("/bff/auth/access-keys", { method: "POST", body }));
      setCreating(false);
      setForm({ name: "", level: "read", days: 30, password: "", code: "" });
      load();
    });
  };
  const command = created && `claude mcp add --transport http investment-lab ${MCP_URL} --header "Authorization: Bearer ${created.key}"`;

  return (
    <div style={{ borderTop: `1px solid ${COLOR.line}`, padding: "16px 0" }}>
      <h2 style={S.h2}>AI assistant access</h2>
      <p style={S.muted}>
        Let an AI assistant (e.g. Claude) read market data and your practice portfolio through our MCP server.
        Each key can be revoked at any time.
      </p>
      {created && (
        <div style={{ background: COLOR.accentSoft, borderRadius: 10, padding: 12, marginTop: 10 }}>
          <strong style={{ fontSize: 14 }}>Copy your key now: it won't be shown again.</strong>
          <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all", fontSize: 13, margin: "8px 0" }}>{created.key}</pre>
          <p style={{ fontSize: 13, margin: "8px 0 4px" }}>Claude Code:</p>
          <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all", fontSize: 12, background: COLOR.panel, borderRadius: 8, padding: 8, margin: 0 }}>{command}</pre>
          <p style={{ fontSize: 12, color: COLOR.muted, margin: "8px 0" }}>
            Other MCP clients: server URL {MCP_URL}, header <code>Authorization: Bearer &lt;key&gt;</code>.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" style={S.secondary} onClick={() => navigator.clipboard?.writeText(created.key)}>Copy key</button>
            <button type="button" style={S.secondary} onClick={() => navigator.clipboard?.writeText(command)}>Copy command</button>
            <button type="button" style={S.secondary} onClick={() => setCreated(null)}>Done</button>
          </div>
        </div>
      )}
      {keys.map((k) => (
        <div key={k.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, padding: "8px 0", fontSize: 13 }}>
          <span style={{ minWidth: 0 }}>
            <span style={{ display: "block", fontWeight: 600 }}>{k.name} <span style={{ fontWeight: 400, color: COLOR.muted }}>({k.level === "trade" ? "read + virtual trades" : "read only"})</span></span>
            <span style={{ color: COLOR.muted }}>
              {k.prefix}… · expires {new Date(k.expires_at + "Z").toLocaleDateString()} · {k.last_used_at ? `last used ${new Date(k.last_used_at + "Z").toLocaleString()}` : "never used"}
            </span>
          </span>
          <button type="button" style={{ ...S.secondary, flexShrink: 0 }}
            onClick={() => run(async () => { await bffFetch(`/bff/auth/access-keys/${k.id}`, { method: "DELETE" }); load(); })}>
            Revoke
          </button>
        </div>
      ))}
      {creating ? (
        <form onSubmit={submit}>
          <Field id="k-name" label="Name (where you'll use it)" value={form.name} onChange={set("name")} placeholder="e.g. Claude on my laptop" required maxLength={80} />
          <label style={S.label} htmlFor="k-level">Access</label>
          <select id="k-level" style={S.field} value={form.level} onChange={set("level")}>
            <option value="read">Read only: market data and my portfolio</option>
            <option value="trade">Read + place virtual trades and edit my watchlist</option>
          </select>
          <label style={S.label} htmlFor="k-days">Expires after</label>
          <select id="k-days" style={S.field} value={form.days} onChange={set("days")}>
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
          <Field id="k-pw" label="Your password" type="password" value={form.password} onChange={set("password")} autoComplete="current-password" required />
          {mfaEnabled && <Field id="k-code" label="Code from your authenticator app" value={form.code} onChange={set("code")} inputMode="numeric" maxLength={6} required />}
          {error && <Note kind="error">{error}</Note>}
          <Submit busy={busy}>Create key</Submit>
          <p style={{ textAlign: "center", margin: "10px 0 0" }}><button type="button" style={S.link} onClick={() => { setCreating(false); setError(null); }}>Cancel</button></p>
        </form>
      ) : (
        <button type="button" style={{ ...S.secondary, marginTop: 8 }} onClick={() => setCreating(true)}>Create access key</button>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- shell integration */

const AccountContext = createContext(null);

// Signed-in customer + Security + sign-out, rendered by App.jsx in the sidebar footer.
export function AccountMenu() {
  const account = useContext(AccountContext);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  if (!account) return null;
  const { customer, logout } = account;
  const btn = { flexShrink: 0, border: `1px solid ${COLOR.lineStrong}`, background: COLOR.panel, color: COLOR.ink, borderRadius: 999,
    padding: "4px 10px", cursor: "pointer", fontSize: 12, fontFamily: FONT_SANS };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: FONT_SANS, fontSize: 13 }}>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0, flex: 1 }} title={customer.email}>
        {customer.full_name}
      </span>
      <button type="button" style={btn} onClick={() => setOpen(true)}>Security</button>
      <button type="button" disabled={busy} style={btn} onClick={async () => { setBusy(true); await logout(); }}>Sign out</button>
      {open && <SecurityPanel account={account} onClose={() => setOpen(false)} refresh={account.refresh} />}
    </div>
  );
}

// Links in our emails: /?action=verify-email&token=... and /?action=reset-password&token=...
function readEmailLink() {
  const q = new URLSearchParams(window.location.search);
  const action = q.get("action");
  const token = q.get("token");
  if (!token || !["verify-email", "reset-password"].includes(action)) return null;
  // Drop the token from the address bar and history straight away.
  window.history.replaceState(null, "", window.location.pathname);
  return { action, token };
}

// Renders the app only for a signed-in customer; everyone else sees the sign-in flow.
export default function AuthGate({ children }) {
  const [state, setState] = useState(() => {
    const link = readEmailLink();
    if (link) return { status: "out", view: link.action, params: { token: link.token } };
    return { status: "loading" };
  });

  const signedIn = useCallback((data) => {
    setCsrfToken(data.csrf_token);
    setState({ status: "in", customer: data.customer, mfaRequired: data.mfa_required,
      mfaEnrollmentRequired: data.mfa_enrollment_required, recoveryLeft: data.recovery_codes_remaining });
  }, []);
  const go = useCallback((view, params = {}) => setState({ status: "out", view, params }), []);
  const refresh = useCallback(() => bffFetch("/bff/auth/me").then(signedIn).catch(() => {}), [signedIn]);

  useEffect(() => {
    if (state.status === "loading") {
      bffFetch("/bff/auth/me").then(signedIn).catch(() => go("signin"));
    }
    return onSignedOut(() => {
      setCsrfToken(null);
      go("signin", { notice: { kind: "info", text: "Your session ended. Please sign in again." } });
    });
  }, [state.status, signedIn, go]);

  const logout = useCallback(async () => {
    try {
      await bffFetch("/bff/auth/logout", { method: "POST" });
    } finally {
      setCsrfToken(null);
      go("signin", { notice: { kind: "info", text: "You are signed out." } });
    }
  }, [go]);

  if (state.status === "loading") return <div style={{ minHeight: "100%", background: COLOR.paper }} aria-busy="true" />;
  if (state.status === "out") {
    const p = state.params || {};
    switch (state.view) {
      case "register": return <Register go={go} />;
      case "forgot": return <Forgot go={go} />;
      case "check-inbox": return <CheckInbox go={go} email={p.email} purpose={p.purpose} />;
      case "verify-email": return <VerifyEmail token={p.token} go={go} />;
      case "reset-password": return <ResetPassword token={p.token} go={go} />;
      default: return <SignIn onSignedIn={signedIn} go={go} notice={p.notice} />;
    }
  }
  if (state.mfaEnrollmentRequired) return <MfaRequired onEnabled={refresh} onLogout={logout} />;
  const account = { customer: state.customer, mfaRequired: state.mfaRequired, recoveryLeft: state.recoveryLeft, logout, refresh };
  return <AccountContext.Provider value={account}>{children}</AccountContext.Provider>;
}
