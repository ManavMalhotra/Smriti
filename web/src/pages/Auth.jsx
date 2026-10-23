import { useEffect, useRef, useState } from "react";
import Footer from "../components/Footer";
import { requestJson } from "../lib/api";

export default function Auth({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [alias, setAlias] = useState("");
  const [sex, setSex] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const headingRef = useRef(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, [mode]);

  function switchMode(next) {
    setMode(next);
    setPassword("");
    setError("");
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");

    if (mode === "register" && !alias.trim()) {
      setError("Enter a patient alias.");
      return;
    }
    if (!username.trim() || !password) {
      setError("Enter a username and password.");
      return;
    }

    setBusy(true);
    try {
      const body =
        mode === "register"
          ? {
              alias: alias.trim(),
              username: username.trim(),
              password,
              sex: sex || null,
            }
          : { username: username.trim(), password };
      const patient = await requestJson(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      onAuthenticated(patient);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const registering = mode === "register";

  return (
    <div className="shell auth-shell">
      <div className="topbar">
        <div className="wordmark">Smriti</div>
        <span className="topbar-note">Local only · no cloud</span>
      </div>

      <main className="auth-main">
        <section className="panel auth-card" aria-labelledby="auth-heading">
          <p className="eyebrow">Private by default</p>
          <h1 id="auth-heading" ref={headingRef} tabIndex={-1}>
            {registering ? "Create your account" : "Sign in"}
          </h1>
          <p className="auth-lede">
            {registering
              ? "Each patient account sees only its own documents and summary. Use initials or a study ID, not a full name. If this device has one existing record without an account, the first account attaches to it."
              : "Your documents and extracted results are visible only to this account."}
          </p>

          <form onSubmit={handleSubmit} noValidate>
            <div className="form-grid">
              {registering ? (
                <div className="field">
                  <label htmlFor="auth-alias">Patient alias</label>
                  <input
                    id="auth-alias"
                    name="alias"
                    type="text"
                    value={alias}
                    onChange={(event) => setAlias(event.target.value)}
                    maxLength={64}
                    autoComplete="off"
                    required
                  />
                </div>
              ) : null}

              <div className="field">
                <label htmlFor="auth-username">Username</label>
                <input
                  id="auth-username"
                  name="username"
                  type="text"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  minLength={registering ? 3 : 1}
                  maxLength={registering ? 32 : 64}
                  pattern={registering ? "[A-Za-z0-9._-]+" : undefined}
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck="false"
                  required
                />
              </div>

              <div className="field">
                <label htmlFor="auth-password">Password</label>
                <input
                  id="auth-password"
                  name="password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  minLength={registering ? 8 : 1}
                  maxLength={128}
                  autoComplete={registering ? "new-password" : "current-password"}
                  required
                />
                {registering ? (
                  <p className="field-note">At least 8 characters. Stored only on this device.</p>
                ) : null}
              </div>

              {registering ? (
                <div className="field">
                  <label htmlFor="auth-sex">Sex</label>
                  <select
                    id="auth-sex"
                    name="sex"
                    value={sex}
                    onChange={(event) => setSex(event.target.value)}
                  >
                    <option value="">Not recorded</option>
                    <option value="F">Female</option>
                    <option value="M">Male</option>
                    <option value="O">Other</option>
                  </select>
                </div>
              ) : null}
            </div>

            {error ? (
              <div className="alert" role="alert">
                {error}
              </div>
            ) : null}

            <div className="form-actions">
              <button type="submit" className="button-primary" disabled={busy}>
                {busy ? "Please wait…" : registering ? "Create account" : "Sign in"}
              </button>
              <button
                type="button"
                className="text-button"
                onClick={() => switchMode(registering ? "login" : "register")}
              >
                {registering ? "I already have an account" : "Create an account"}
              </button>
            </div>
          </form>
        </section>
      </main>

      <Footer />
    </div>
  );
}
