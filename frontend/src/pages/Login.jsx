import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorText } from "../api";
import { useAuth } from "../auth.jsx";
import { L } from "../labels";
import "./login.css";

/** Fireflies: fixed positions per page load so they don't jump on every keystroke. */
function useFireflies(n) {
  return useMemo(() => Array.from({ length: n }, (_, i) => ({
    left: `${Math.round(Math.random() * 100)}%`,
    top: `${Math.round(Math.random() * 100)}%`,
    delay: `${(Math.random() * 6).toFixed(2)}s`,
    duration: `${(5 + Math.random() * 6).toFixed(2)}s`,
    key: i,
  })), [n]);
}

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lampOn, setLampOn] = useState(true);
  const flies = useFireflies(18);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username.trim(), password);
      navigate("/");
    } catch (err) {
      setError(err.response?.status === 401
        ? "Izina cyangwa ijambo ry'ibanga si ryo (Wrong username or password)"
        : errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`lamp-page ${lampOn ? "on" : "off"}`}>
      {flies.map((f) => (
        <span key={f.key} className="firefly"
              style={{ left: f.left, top: f.top, animationDelay: f.delay, animationDuration: f.duration }} />
      ))}

      <div className="lamp-scene" aria-hidden="true">
        <div className="lamp">
          <div className="shade" />
          <div className="bulb" />
          <button type="button" className="chain" onClick={() => setLampOn((v) => !v)}
                  title="Kanda / Pull" tabIndex={-1}>
            <span className="bead" />
          </button>
          <div className="beam" />
          <div className="pole" />
          <div className="base" />
        </div>
      </div>

      <form className="lamp-card" onSubmit={submit}>
        <h1>Murakaza neza</h1>
        <p className="lamp-sub">Welcome back - {L.appName.rw}</p>

        <label className="lamp-field">
          <span className="icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" /></svg>
          </span>
          <input placeholder="Izina ry'ukoresha (Username)" value={username} autoCapitalize="none"
                 autoComplete="username" onChange={(e) => setUsername(e.target.value)} autoFocus
                 aria-label="Username" />
        </label>

        <label className="lamp-field">
          <span className="icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>
          </span>
          <input type="password" placeholder="Ijambo ry'ibanga (Password)" value={password}
                 autoComplete="current-password" onChange={(e) => setPassword(e.target.value)}
                 aria-label="Password" />
        </label>

        {error && <p className="lamp-error">{error}</p>}

        <button className="lamp-btn" disabled={busy || !username || !password}>
          {busy ? "..." : "Injira (Log in)"}
        </button>
        <p className="lamp-foot">Livelihood - Imibereho</p>
      </form>
    </div>
  );
}