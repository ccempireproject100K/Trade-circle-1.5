import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, localToday, shortDate } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Field, Notice } from "../components/Form.jsx";

function Alerts() {
  const [alerts, setAlerts] = useState(null);
  const [phone, setPhone] = useState("");
  const [consent, setConsent] = useState(false);
  const [status, setStatus] = useState({});

  useEffect(() => {
    api("/me/alerts").then((a) => {
      setAlerts(a);
      setPhone(a.sms.phone || "");
    }).catch((err) => setStatus({ error: err.message }));
  }, []);

  const enable = async (event) => {
    event.preventDefault();
    try {
      setAlerts(await api("/me/alerts/sms", { method: "PUT", body: { phone, consent } }));
      setStatus({ ok: "Text alerts are on." });
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  const disable = async () => {
    try {
      await api("/me/alerts/sms", { method: "DELETE" });
      setAlerts({ ...alerts, sms: { ...alerts.sms, active: false } });
      setStatus({ ok: "Text alerts are off." });
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  if (!alerts) return null;
  if (!alerts.available) {
    return (
      <section className="card">
        <h2>Lead alerts</h2>
        <p className="muted" style={{ margin: 0 }}>
          On the free plan, new leads wait under Work → Follow-ups. Paid plans get a text and an email the moment a lead comes in.
        </p>
      </section>
    );
  }

  return (
    <section className="card stack">
      <h2>Lead alerts</h2>
      <p className="small muted" style={{ margin: 0 }}>New-lead emails go to {alerts.email}.</p>
      <label className="check">
        <input
          type="checkbox"
          checked={alerts.daily_summary}
          onChange={async (e) => setAlerts(await api("/me/alerts/digest", { method: "PUT", body: { on: e.target.checked } }))}
        />
        <span>
          Daily email summary
          <span className="field-hint" style={{ display: "block" }}>
            Once a morning, only when there's something new: community activity and follow-ups due. If texts are on, one afternoon text when follow-ups are still due.
          </span>
        </span>
      </label>
      {alerts.sms.active ? (
        <div className="row-between">
          <span>Texts go to <strong>{alerts.sms.phone}</strong></span>
          <button type="button" className="btn btn-small" onClick={disable}>Turn off texts</button>
        </div>
      ) : (
        <form className="stack" onSubmit={enable}>
          <Field label="Mobile number for text alerts">
            <input type="tel" autoComplete="tel" required value={phone} onChange={(e) => setPhone(e.target.value)} />
          </Field>
          <label className="check">
            <input type="checkbox" required checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span className="small">
              Text me when I get a new lead. Message and data rates may apply. Reply STOP to opt out at any time.
            </span>
          </label>
          <button className="btn btn-primary" disabled={!consent}>Turn on texts</button>
        </form>
      )}
      <Notice error={status.error} ok={status.ok} />
    </section>
  );
}

function Vacation() {
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ start_on: "", end_on: "", note: "" });
  const [status, setStatus] = useState({});
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  const load = () => api("/me/vacations").then(setData).catch((err) => setStatus({ error: err.message }));
  useEffect(() => {
    load();
  }, []);

  const days = form.start_on && form.end_on ? Math.round((new Date(form.end_on) - new Date(form.start_on)) / 86400000) + 1 : null;

  const add = async (event) => {
    event.preventDefault();
    try {
      await api("/me/vacations", { method: "POST", body: form });
      setForm({ start_on: "", end_on: "", note: "" });
      setStatus({ ok: "Vacation saved. Weekly handoff limits pause on those days." });
      load();
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  const end = async (v) => {
    if (!window.confirm(v.active ? "End this vacation today? Normal handoff limits apply from today." : "Cancel this vacation?")) return;
    try {
      await api(`/me/vacations/${v.id}`, { method: "DELETE" });
      setStatus({ ok: v.active ? "Vacation ended. Normal limits apply from today." : "Vacation cancelled." });
      load();
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  if (!data) return null;
  const current = data.vacations.filter((v) => !v.past);

  return (
    <section className="card stack">
      <h2>Vacation</h2>
      <p className="small muted" style={{ margin: 0 }}>
        While you're on vacation, the weekly handoff limits are paused so you can get your jobs covered. A vacation can last up to{" "}
        {data.max_days} days, including back-to-back entries, and separate vacations need about 3 months ({data.min_gap_days} days) between them.
        Normal limits come back automatically the day after it ends. Coverage beyond {data.max_days} days needs to be arranged outside Trade Circle.
      </p>
      {current.length > 0 && (
        <ul className="items">
          {current.map((v) => (
            <li key={v.id} className="row-between">
              <span>
                <strong>{shortDate(v.start_on)} to {shortDate(v.end_on)}</strong> · {v.days} {v.days === 1 ? "day" : "days"}
                {v.active && <span className="pill pill-won" style={{ marginLeft: 8 }}>On now</span>}
                <br />
                <span className="small muted">{v.note}</span>
              </span>
              <button type="button" className="btn btn-small" onClick={() => end(v)}>{v.active ? "End early" : "Cancel"}</button>
            </li>
          ))}
        </ul>
      )}
      <form className="stack" onSubmit={add}>
        <div className="grid-2">
          <Field label="First day"><input type="date" required min={localToday()} value={form.start_on} onChange={set("start_on")} /></Field>
          <Field label="Last day"><input type="date" required min={form.start_on || localToday()} value={form.end_on} onChange={set("end_on")} /></Field>
        </div>
        {days !== null && days > 0 && (
          <p className={`small ${days > data.max_days ? "notice notice-error" : "muted"}`} style={{ margin: 0 }}>
            {days} {days === 1 ? "day" : "days"}{days > data.max_days ? ` — the most is ${data.max_days}.` : ""}
          </p>
        )}
        <Field label="Short note" hint="For example: family trip, surgery recovery.">
          <input required maxLength={200} value={form.note} onChange={set("note")} />
        </Field>
        <Notice error={status.error} ok={status.ok} />
        <button className="btn" disabled={days !== null && days > data.max_days}>Save vacation</button>
      </form>
    </section>
  );
}

function Password() {
  const [form, setForm] = useState({ current_password: "", new_password: "" });
  const [status, setStatus] = useState({});

  const submit = async (event) => {
    event.preventDefault();
    try {
      await api("/auth/password", { method: "POST", body: form });
      setForm({ current_password: "", new_password: "" });
      setStatus({ ok: "Password changed. Other devices have been signed out." });
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  return (
    <form className="card stack" onSubmit={submit}>
      <h2>Change password</h2>
      <Field label="Current password">
        <input type="password" autoComplete="current-password" required value={form.current_password} onChange={(e) => setForm({ ...form, current_password: e.target.value })} />
      </Field>
      <Field label="New password" hint="At least 10 characters.">
        <input type="password" autoComplete="new-password" required minLength={10} value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} />
      </Field>
      <Notice error={status.error} ok={status.ok} />
      <button className="btn">Change password</button>
    </form>
  );
}

export default function Settings() {
  const { user, logout, setUser } = useAuth();
  const navigate = useNavigate();

  const signOutEverywhere = async () => {
    if (!window.confirm("Sign out on every phone and computer?")) return;
    await api("/auth/logout-everywhere", { method: "POST" });
    setUser(null);
    navigate("/login");
  };

  return (
    <>
      <h1>Settings</h1>
      <p className="muted">Signed in as {user.email}</p>
      <section className="card row-between">
        <span>Plan: <strong>{{ free: "Free", starter: "Starter", full: "Full" }[user.tier] || user.tier}</strong></span>
        <Link className="btn btn-small" to="/plan">Plans and billing</Link>
      </section>
      <Alerts />
      <Vacation />
      <Password />
      <section className="card row">
        <button type="button" className="btn" onClick={async () => { await logout(); navigate("/login"); }}>Sign out</button>
        <button type="button" className="btn btn-danger" onClick={signOutEverywhere}>Sign out everywhere</button>
      </section>
    </>
  );
}
