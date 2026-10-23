import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, label } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Field, Notice } from "../components/Form.jsx";

export default function Signup() {
  const { signup } = useAuth();
  const [trades, setTrades] = useState([]);
  const [form, setForm] = useState({ business_name: "", trade: "", city: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/meta").then((meta) => setTrades(meta.trades)).catch(() => {});
  }, []);

  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      // Signing up re-renders the route, which opens the dashboard.
      // A referral code from a member's link rides along; an unknown code is simply ignored.
      const ref = new URLSearchParams(window.location.search).get("ref");
      await signup(ref ? { ...form, ref: ref.slice(0, 16) } : form);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <main className="auth">
      <h1 className="brand-lg">Trade Circle</h1>
      <form className="card stack" onSubmit={submit}>
        <h2>Create your free page</h2>
        <Field label="Business name">
          <input required maxLength={120} autoComplete="organization" value={form.business_name} onChange={set("business_name")} />
        </Field>
        <Field label="Trade">
          <select required value={form.trade} onChange={set("trade")}>
            <option value="" disabled>Choose your trade</option>
            {trades.map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </select>
        </Field>
        <Field label="City">
          <input required maxLength={120} autoComplete="address-level2" value={form.city} onChange={set("city")} />
        </Field>
        <Field label="Email">
          <input type="email" required autoComplete="email" value={form.email} onChange={set("email")} />
        </Field>
        <Field label="Password" hint="At least 10 characters.">
          <input type="password" required minLength={10} autoComplete="new-password" value={form.password} onChange={set("password")} />
        </Field>
        <Notice error={error} />
        <button className="btn btn-primary" disabled={busy}>{busy ? "Creating…" : "Create page"}</button>
      </form>
      <p className="auth-switch">Already have a page? <Link to="/login">Sign in</Link></p>
    </main>
  );
}
