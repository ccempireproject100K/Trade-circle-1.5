import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { acting, api, localToday } from "../api.js";
import { Field, Notice } from "../components/Form.jsx";

// Time tracking (Starter plan and up): clock in and out, or add hours by hand.
export const hours = (minutes) => `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
const addDays = (iso, n) => {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};
const dayName = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

function Clock({ jobs, status, onChange }) {
  const [job, setJob] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30000);
    return () => clearInterval(t);
  }, []);
  const act = async (path, body) => {
    setError("");
    try {
      await api(path, { method: "POST", body });
      setNote("");
      onChange();
    } catch (err) {
      setError(err.message);
    }
  };
  const running = status.running;
  const elapsed = running ? Math.max(0, Math.round((Date.now() - new Date(running.started_at).getTime()) / 60000)) : 0;
  return (
    <section className="card stack">
      {running ? (
        <>
          <p style={{ margin: 0 }}>
            Clocked in since <strong>{running.start}</strong>{running.job && <> on <strong>{running.job}</strong></>} · about {hours(elapsed)}
          </p>
          <Field label="Note (optional)"><input maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What got done" /></Field>
          <button type="button" className="btn btn-primary clock-button" onClick={() => act("/time/clock-out", note ? { note } : {})}>Clock out</button>
        </>
      ) : (
        <>
          <Field label="Job (optional)">
            <select value={job} onChange={(e) => setJob(e.target.value)}>
              <option value="">No job</option>
              {jobs.map((j) => <option key={j.id} value={j.id}>{j.title}{j.customer_name ? ` · ${j.customer_name}` : ""}</option>)}
            </select>
          </Field>
          <button type="button" className="btn btn-primary clock-button" onClick={() => act("/time/clock-in", { job_id: job || null })}>Clock in</button>
        </>
      )}
      <Notice error={error} />
    </section>
  );
}

function AddTime({ jobs, onAdded, onClose }) {
  const [f, setF] = useState({ job_id: "", day: localToday(), start: "08:00", end: "16:30", break_minutes: "30", note: "" });
  const [error, setError] = useState("");
  const set = (key) => (e) => setF({ ...f, [key]: e.target.value });
  const save = async (event) => {
    event.preventDefault();
    try {
      await api("/time/entries", { method: "POST", body: { ...f, job_id: f.job_id || null, break_minutes: Number(f.break_minutes) || 0 } });
      onAdded();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="card stack" onSubmit={save}>
      <div className="row-between">
        <h2 style={{ margin: 0 }}>Add time by hand</h2>
        <button type="button" className="linklike" onClick={onClose}>Close</button>
      </div>
      <div className="grid-2">
        <Field label="Day"><input type="date" required max={localToday()} value={f.day} onChange={set("day")} /></Field>
        <Field label="Job (optional)">
          <select value={f.job_id} onChange={set("job_id")}>
            <option value="">No job</option>
            {jobs.map((j) => <option key={j.id} value={j.id}>{j.title}</option>)}
          </select>
        </Field>
        <Field label="Start"><input type="time" required value={f.start} onChange={set("start")} /></Field>
        <Field label="End"><input type="time" required value={f.end} onChange={set("end")} /></Field>
        <Field label="Break (minutes)"><input inputMode="numeric" value={f.break_minutes} onChange={set("break_minutes")} /></Field>
        <Field label="Note (optional)"><input maxLength={300} value={f.note} onChange={set("note")} /></Field>
      </div>
      <Notice error={error} />
      <button className="btn btn-primary">Add</button>
    </form>
  );
}

// The CSV comes from the server; fetch it with the same headers as other calls so "working for a business" applies.
async function download(start, end) {
  const headers = acting.get() ? { "X-TC-Business": acting.get().id } : {};
  const res = await fetch(`/api/time/export.csv?start=${start}&end=${end}`, { credentials: "same-origin", headers });
  if (!res.ok) throw new Error("Couldn't export. Please try again.");
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: `time-${start}-to-${end}.csv` });
  a.click();
  URL.revokeObjectURL(url);
}

export default function Time() {
  const [status, setStatus] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [weekOf, setWeekOf] = useState(localToday());
  const [week, setWeek] = useState(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");

  const load = () => {
    api("/time/status").then(setStatus, (err) => setError(err.message));
    api(`/time?start=${weekOf}`).then(setWeek, (err) => setError(err.message));
  };
  useEffect(() => {
    api("/jobs").then((list) => setJobs(list.filter((j) => !["done", "cancelled", "handed_off"].includes(j.status))), () => {});
  }, []);
  useEffect(load, [weekOf]); // eslint-disable-line react-hooks/exhaustive-deps

  const remove = async (e) => {
    if (!window.confirm("Delete this time entry?")) return;
    await api(`/time/entries/${e.id}`, { method: "DELETE" }).catch((err) => setError(err.message));
    load();
  };

  if (!status || !week) return <Notice error={error} />;
  const days = [...Array(7)].map((_, i) => addDays(week.week_of, i));
  return (
    <>
      <div className="row-between">
        <h1>Time</h1>
        {status.allowed && <button type="button" className="btn btn-small" onClick={() => setAdding(!adding)}>{adding ? "Close" : "Add by hand"}</button>}
      </div>
      {!status.allowed && (
        <p className="notice">
          Time tracking is part of the Starter plan. {week.entries.length > 0 ? "Your earlier time stays here to view and export." : ""} <Link to="/plan">See plans</Link>
        </p>
      )}
      {status.allowed && <Clock jobs={jobs} status={status} onChange={load} />}
      {adding && <AddTime jobs={jobs} onClose={() => setAdding(false)} onAdded={() => { setAdding(false); load(); }} />}
      <Notice error={error} />
      <section className="card stack">
        <div className="row-between">
          <button type="button" className="btn btn-small" aria-label="Previous week" onClick={() => setWeekOf(addDays(week.week_of, -7))}>←</button>
          <strong>Week of {dayName(week.week_of)}</strong>
          <button type="button" className="btn btn-small" aria-label="Next week" onClick={() => setWeekOf(addDays(week.week_of, 7))}>→</button>
        </div>
        <p style={{ margin: 0 }}>Total <strong>{hours(week.total_minutes)}</strong></p>
        {days.map((d) => {
          const items = week.entries.filter((e) => e.day === d);
          if (!items.length) return null;
          return (
            <div key={d}>
              <h3 style={{ margin: "8px 0 4px" }}>{dayName(d)} · {hours(week.totals.days[d] || 0)}</h3>
              <ul className="items">
                {items.map((e) => (
                  <li key={e.id} className="row-between">
                    <span>
                      {e.start}–{e.end || "now"} {e.job ? `· ${e.job}` : ""} {Object.keys(week.totals.people).length > 1 && `· ${e.worker}`}
                      {e.break_minutes > 0 && <span className="small muted"> · {e.break_minutes} min break</span>}
                      {e.note && <span className="small muted"> · {e.note}</span>}
                    </span>
                    <span className="row" style={{ gap: 8 }}>
                      <span>{hours(e.minutes)}</span>
                      {!e.running && (e.mine || !acting.get()) && <button type="button" className="linklike small" onClick={() => remove(e)} aria-label={`Delete ${e.start} entry`}>Delete</button>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {week.entries.length === 0 && <p className="empty">No time this week.</p>}
        {Object.keys(week.totals.jobs).length > 0 && (
          <p className="small" style={{ margin: 0 }}>By job: {Object.entries(week.totals.jobs).map(([k, v]) => `${k} ${hours(v)}`).join(" · ")}</p>
        )}
        {week.entries.length > 0 && (
          <button type="button" className="btn btn-small" style={{ justifySelf: "start" }} onClick={() => download(week.week_of, addDays(week.week_of, 6)).catch((err) => setError(err.message))}>Export this week (CSV)</button>
        )}
      </section>
    </>
  );
}
