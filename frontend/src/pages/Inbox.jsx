import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, label, localToday, shortDate } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Field, Notice } from "../components/Form.jsx";

// The private follow-up tracker: quote requests from Trade Circle plus inquiries added by hand.
const STATUSES = { waiting: "Waiting", followed_up: "Followed up", won: "Won", closed: "Closed" };
const CHANNELS = { phone: "Phone call", text: "Text", in_person: "In person", other: "Other" };
// All comes first: new quote requests have no follow-up date yet and must not be hidden.
const VIEWS = [
  { key: "all", label: "All" },
  { key: "upcoming", label: "Upcoming" },
  { key: "overdue", label: "Overdue" },
];
const EMPTY = { name: "", phone: "", email: "", channel: "phone", job_type: "", follow_up_on: "", notes: "" };

function AddForm({ onAdded, onClose }) {
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    const body = { ...form };
    for (const key of ["phone", "email", "job_type", "follow_up_on"]) if (!body[key]) body[key] = null;
    try {
      onAdded(await api("/inbox", { method: "POST", body }));
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <form className="card stack" onSubmit={submit}>
      <div className="row-between">
        <h2 style={{ margin: 0 }}>Add from a call, text or conversation</h2>
        <button type="button" className="linklike" onClick={onClose}>Close</button>
      </div>
      <Field label="Name"><input required maxLength={120} value={form.name} onChange={set("name")} /></Field>
      <div className="grid-2">
        <Field label="Phone (optional)"><input type="tel" value={form.phone} onChange={set("phone")} /></Field>
        <Field label="Email (optional)"><input type="email" value={form.email} onChange={set("email")} /></Field>
        <Field label="How they reached you">
          <select value={form.channel} onChange={set("channel")}>
            {Object.entries(CHANNELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Follow up on"><input type="date" value={form.follow_up_on} onChange={set("follow_up_on")} /></Field>
      </div>
      <Field label="What it's about (optional)"><input maxLength={120} value={form.job_type} onChange={set("job_type")} /></Field>
      <Field label="Private notes"><textarea maxLength={4000} value={form.notes} onChange={set("notes")} /></Field>
      <Notice error={error} />
      <button className="btn btn-primary">Add</button>
    </form>
  );
}

function Entry({ entry, onChange, onRemove, onMakeJob }) {
  const [notes, setNotes] = useState(entry.notes || "");
  const [error, setError] = useState("");
  const overdue = entry.follow_up_on && entry.follow_up_on < localToday() && ["waiting", "followed_up"].includes(entry.status);

  const patch = async (body) => {
    setError("");
    try {
      onChange(await api(`/inbox/${entry.id}`, { method: "PATCH", body }));
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <li className="card" style={{ margin: 0 }}>
      <div className="row-between">
        <h3>{entry.name}</h3>
        <span className={`pill pill-${entry.status}`}>{STATUSES[entry.status] || label(entry.status)}</span>
      </div>
      <p className="small muted" style={{ margin: "2px 0 0" }}>
        {entry.source === "manual" ? `Added by you · ${CHANNELS[entry.channel] || "Other"}` : "Quote request through Trade Circle"}
        {entry.job_type && ` · ${entry.job_type}`} · {shortDate(entry.created_at)}
      </p>
      {entry.message && <p className="item-message">{entry.message}</p>}
      <div className="row" style={{ margin: "8px 0" }}>
        {entry.phone && <a className="btn btn-primary btn-small" href={`tel:${entry.phone}`}>Call</a>}
        {entry.phone && <a className="btn btn-small" href={`sms:${entry.phone}`}>Text</a>}
        {entry.email && <a className="btn btn-small" href={`mailto:${entry.email}`}>Email</a>}
        <button type="button" className="btn btn-small" onClick={() => onMakeJob(entry)}>Make job</button>
      </div>
      <div className="grid-2">
        <Field label="Status">
          <select aria-label={`Status for ${entry.name}`} value={entry.status} onChange={(e) => patch({ status: e.target.value })}>
            {Object.entries(STATUSES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label={overdue ? "Follow up on (overdue)" : "Follow up on"}>
          <input type="date" aria-label={`Follow-up date for ${entry.name}`} value={entry.follow_up_on || ""} onChange={(e) => patch({ follow_up_on: e.target.value || null })} style={overdue ? { borderColor: "var(--bad)" } : undefined} />
        </Field>
      </div>
      <Field label="Private notes">
        <textarea aria-label={`Notes for ${entry.name}`} rows={2} maxLength={4000} value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== (entry.notes || "") && patch({ notes })} />
      </Field>
      <Notice error={error} />
      {entry.source === "manual" && (
        <button type="button" className="link-danger" onClick={() => onRemove(entry)}>Delete</button>
      )}
    </li>
  );
}

export default function Inbox() {
  const { user } = useAuth();
  const [view, setView] = useState("all");
  const [entries, setEntries] = useState(null);
  const [counts, setCounts] = useState({});
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  const load = async () => {
    try {
      const [shown, overdue] = await Promise.all([api(`/inbox?view=${view}`), api("/inbox?view=overdue")]);
      setEntries(shown);
      setCounts({ overdue: overdue.length });
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
  }, [view]); // eslint-disable-line react-hooks/exhaustive-deps

  const makeJob = async (entry) => {
    setError("");
    try {
      await api("/jobs", {
        method: "POST",
        body: { title: entry.job_type || `Job for ${entry.name}`, customer_name: entry.name, customer_phone: entry.phone || null, notes: entry.message || entry.notes || "", quote_id: entry.id },
      });
      if (entry.status !== "won") await api(`/inbox/${entry.id}`, { method: "PATCH", body: { status: "won" } });
      setOk(`Added "${entry.job_type || `Job for ${entry.name}`}" to your jobs.`);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const remove = async (entry) => {
    if (!window.confirm(`Delete ${entry.name}?`)) return;
    await api(`/inbox/${entry.id}`, { method: "DELETE" });
    load();
  };

  return (
    <>
      <div className="row-between">
        <h1>Follow-ups</h1>
        <button type="button" className="btn btn-primary btn-small" onClick={() => setAdding(!adding)}>{adding ? "Close" : "Add"}</button>
      </div>
      <p className="small muted" style={{ marginTop: 0 }}>
        Private to you. Quote requests from your page land here, and you can add inquiries from calls, texts and conversations.
        {user.tier === "free" && " On the free plan, new requests show up here when you log in."}
      </p>
      {adding && <AddForm onClose={() => setAdding(false)} onAdded={() => { setAdding(false); setView("all"); load(); setOk("Added."); }} />}
      <div className="tabs" role="group" aria-label="Show">
        {VIEWS.map((v) => (
          <button key={v.key} type="button" aria-pressed={view === v.key} onClick={() => setView(v.key)}>
            {v.label}{v.key === "overdue" && counts.overdue ? ` (${counts.overdue})` : ""}
          </button>
        ))}
      </div>
      <Notice error={error} ok={ok} />
      {entries === null ? (
        <p className="loading">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="empty">
          {view === "upcoming" ? "Nothing scheduled. Set a follow-up date on an entry to see it here." : view === "overdue" ? "Nothing overdue." : "No inquiries yet. Share your page link, or add one from a call."}
        </p>
      ) : (
        <ul className="items">
          {entries.map((e) => (
            <Entry key={e.id} entry={e} onRemove={remove} onMakeJob={makeJob} onChange={(saved) => setEntries((list) => list.map((x) => (x.id === saved.id ? saved : x)))} />
          ))}
        </ul>
      )}
      {ok.startsWith("Added \"") && <p className="small"><Link to="/jobs">Go to jobs →</Link></p>}
    </>
  );
}
