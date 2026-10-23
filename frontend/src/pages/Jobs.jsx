import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, dollars, label, shortDate, toCents } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Field, Notice } from "../components/Form.jsx";

const STATUSES = ["lead", "scheduled", "in_progress", "done", "cancelled"];
// Set by a handoff, not chosen by hand.
const HANDED_OFF = "handed_off";
const EMPTY = { title: "", customer_name: "", customer_phone: "", site_address: "", scheduled_on: "", estimate: "", notes: "" };

function JobForm({ onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  const submit = async (event) => {
    event.preventDefault();
    const estimate_cents = toCents(form.estimate);
    if (Number.isNaN(estimate_cents)) {
      setError("Estimate: enter a dollar amount, like 1850 or 1,850.00");
      return;
    }
    setBusy(true);
    setError("");
    const { estimate, ...rest } = form;
    const body = { ...rest, estimate_cents, status: form.scheduled_on ? "scheduled" : "lead" };
    for (const key of ["customer_phone", "scheduled_on"]) if (!body[key]) body[key] = null;
    try {
      onSaved(await api("/jobs", { method: "POST", body }));
      setForm(EMPTY);
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  return (
    <form className="card stack" onSubmit={submit}>
      <h2>Add a job</h2>
      <Field label="Job"><input required maxLength={120} value={form.title} onChange={set("title")} placeholder="Panel upgrade" /></Field>
      <div className="grid-2">
        <Field label="Customer"><input maxLength={120} value={form.customer_name} onChange={set("customer_name")} /></Field>
        <Field label="Customer phone"><input type="tel" value={form.customer_phone} onChange={set("customer_phone")} /></Field>
      </div>
      <Field label="Address"><input maxLength={200} autoComplete="off" value={form.site_address} onChange={set("site_address")} /></Field>
      <div className="grid-2">
        <Field label="Date"><input type="date" value={form.scheduled_on} onChange={set("scheduled_on")} /></Field>
        <Field label="Estimate ($)"><input inputMode="decimal" value={form.estimate} onChange={set("estimate")} placeholder="1850" /></Field>
      </div>
      <Field label="Notes"><textarea maxLength={4000} value={form.notes} onChange={set("notes")} /></Field>
      <Notice error={error} />
      <button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Add job"}</button>
    </form>
  );
}

export default function Jobs() {
  const { user } = useAuth();
  const [jobs, setJobs] = useState(null);
  const [filter, setFilter] = useState("open");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/jobs").then(setJobs).catch((err) => setError(err.message));
  }, []);

  const update = async (job, changes) => {
    setError("");
    try {
      const saved = await api(`/jobs/${job.id}`, { method: "PATCH", body: changes });
      setJobs(jobs.map((j) => (j.id === job.id ? saved : j)));
    } catch (err) {
      setError(err.message);
    }
  };

  const remove = async (job) => {
    if (!window.confirm(`Delete "${job.title}"?`)) return;
    try {
      await api(`/jobs/${job.id}`, { method: "DELETE" });
      setJobs(jobs.filter((j) => j.id !== job.id));
    } catch (err) {
      setError(err.message);
    }
  };

  if (jobs === null) return error ? <Notice error={error} /> : <p className="loading">Loading…</p>;
  const isOpen = (j) => !["done", "cancelled", HANDED_OFF].includes(j.status);
  const shown = jobs
    .filter((j) => (filter === "open" ? isOpen(j) : !isOpen(j)))
    .sort((a, b) => (a.scheduled_on || "9999").localeCompare(b.scheduled_on || "9999"));

  return (
    <>
      <div className="row-between">
        <h1>Jobs</h1>
        <span className="row">
          <Link className="btn" to="/handoffs">Handoffs</Link>
          <button type="button" className="btn btn-primary" onClick={() => setAdding(!adding)}>{adding ? "Close" : "Add job"}</button>
        </span>
      </div>
      {adding && <JobForm onSaved={(job) => { setJobs([job, ...jobs]); setAdding(false); }} />}
      <div className="tabs" role="group" aria-label="Filter jobs">
        <button type="button" aria-pressed={filter === "open"} onClick={() => setFilter("open")}>Open ({jobs.filter(isOpen).length})</button>
        <button type="button" aria-pressed={filter === "closed"} onClick={() => setFilter("closed")}>Done ({jobs.filter((j) => !isOpen(j)).length})</button>
      </div>
      <Notice error={error} />
      {shown.length === 0 ? (
        <p className="empty">{filter === "open" ? "No open jobs." : "No finished jobs yet."}</p>
      ) : (
        <ul className="items">
          {shown.map((job) => (
            <li key={job.id} className="card" style={{ margin: 0 }}>
              <div className="row-between">
                <h3>{job.title}</h3>
                <span className={`pill pill-${job.status}`}>{label(job.status)}</span>
              </div>
              <p className="small muted" style={{ margin: "2px 0 0" }}>
                {[job.customer_name, job.scheduled_on && shortDate(job.scheduled_on), dollars(job.estimate_cents)].filter(Boolean).join(" · ")}
              </p>
              {job.site_address && <p className="small" style={{ margin: "4px 0 0" }}>{job.site_address}</p>}
              {job.notes && <p className="item-message small">{job.notes}</p>}
              <div className="row" style={{ marginTop: 8 }}>
                {job.customer_phone && <a className="btn btn-small" href={`tel:${job.customer_phone}`}>Call</a>}
                {job.status === HANDED_OFF ? (
                  <Link className="btn btn-small" to="/handoffs?view=sent">See handoff</Link>
                ) : (
                <select
                  aria-label={`Status for ${job.title}`}
                  value={job.status}
                  onChange={(e) => update(job, { status: e.target.value })}
                  style={{ width: "auto", minHeight: 36, padding: "4px 8px" }}
                >
                  {STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
                </select>
                )}
                {isOpen(job) && <Link className="btn btn-small" to={`/handoffs?job=${job.id}`}>Hand off</Link>}
                <Link className="btn btn-small" to={`/jobs/${job.id}/costing`}>Costing</Link>
                {user?.tier === "full" && job.status !== "cancelled" && <Link className="btn btn-small" to={`/payments?job=${job.id}`}>Request payment</Link>}
                <input
                  type="date"
                  aria-label={`Date for ${job.title}`}
                  value={job.scheduled_on || ""}
                  onChange={(e) => update(job, { scheduled_on: e.target.value || null })}
                  style={{ width: "auto", minHeight: 36, padding: "4px 8px" }}
                />
                <button type="button" className="btn btn-small btn-danger" onClick={() => remove(job)}>Delete</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
