import { useEffect, useState } from "react";
import { api, label } from "../api.js";
import { CheerButton } from "../components/Cheers.jsx";
import { Author } from "../components/Community.jsx";
import { Field, Notice } from "../components/Form.jsx";
import MessageRequest from "../components/MessageRequest.jsx";

const METHODS = { messages: "Trade Circle messages", phone: "Phone call", text: "Text message", email: "Email" };
const BLANK = { seeking: false, offering: false, topics: "", experience: "", contact_method: "messages", contact_value: "", availability: "", paused: false };

function MyStatus() {
  const [saved, setSaved] = useState(undefined);
  const [form, setForm] = useState(BLANK);
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState({});
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const load = () =>
    api("/me/mentoring").then(({ mentoring }) => {
      setSaved(mentoring);
      setForm(mentoring ? { ...mentoring, topics: mentoring.topics.join(", ") } : BLANK);
    });
  useEffect(() => {
    load();
  }, []);

  const save = async (event, overrides = {}) => {
    event?.preventDefault();
    const body = { ...form, ...overrides, topics: form.topics.split(",").map((t) => t.trim()).filter(Boolean) };
    try {
      await api("/me/mentoring", { method: "PUT", body });
      setStatus({ ok: overrides.paused === true ? "Paused. You won't be listed until you resume." : "Saved." });
      setEditing(false);
      load();
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  const remove = async () => {
    await api("/me/mentoring", { method: "DELETE" });
    setStatus({ ok: "Removed. You're no longer listed." });
    load();
  };

  if (saved === undefined) return null;

  if (saved && !editing) {
    const roles = [saved.offering && "Willing to help", saved.seeking && "Looking for a mentor"].filter(Boolean).join(" and ");
    return (
      <section className="card stack">
        <h2 style={{ margin: 0 }}>Your mentoring status</h2>
        <p style={{ margin: 0 }}>{roles}{saved.paused && " · paused"}</p>
        <p className="small muted" style={{ margin: 0 }}>Topics: {saved.topics.join(", ")}</p>
        <div className="row">
          <button type="button" className="btn btn-small" onClick={() => setEditing(true)}>Edit</button>
          <button type="button" className="btn btn-small" onClick={() => save(null, { paused: !saved.paused })}>{saved.paused ? "Resume" : "Pause"}</button>
          <button type="button" className="link-danger" onClick={remove}>Remove my status</button>
        </div>
        <Notice error={status.error} ok={status.ok} />
      </section>
    );
  }

  if (!editing) {
    return (
      <section className="card stack">
        <p style={{ margin: 0 }}>Want to take part? It's voluntary, and you can pause or leave any time.</p>
        <button type="button" className="btn" onClick={() => setEditing(true)}>Join mentoring</button>
        <Notice ok={status.ok} />
      </section>
    );
  }

  return (
    <form className="card stack" onSubmit={save}>
      <h2 style={{ margin: 0 }}>Your mentoring status</h2>
      <label className="check"><input type="checkbox" checked={form.offering} onChange={set("offering")} /><span>Willing to help</span></label>
      <label className="check"><input type="checkbox" checked={form.seeking} onChange={set("seeking")} /><span>Looking for a mentor</span></label>
      <Field label="Topics" hint="Separate with commas, like: estimating, first hire, pricing service calls">
        <input required value={form.topics} onChange={set("topics")} />
      </Field>
      <Field label="Relevant experience"><textarea maxLength={1000} value={form.experience} onChange={set("experience")} /></Field>
      <Field label="Availability" hint="Be realistic. For example: one call a month, weekday evenings.">
        <input maxLength={300} value={form.availability} onChange={set("availability")} />
      </Field>
      <Field label="Preferred contact after an introduction is accepted">
        <select value={form.contact_method} onChange={set("contact_method")}>
          {Object.entries(METHODS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      {form.contact_method !== "messages" && (
        <Field label={form.contact_method === "email" ? "Email to share" : "Phone number to share"} hint="Only shared with members whose introduction you accept.">
          <input required maxLength={120} value={form.contact_value} onChange={set("contact_value")} />
        </Field>
      )}
      <Notice error={status.error} />
      <span className="row">
        <button className="btn btn-primary">Save</button>
        <button type="button" className="linklike" onClick={() => setEditing(false)}>Cancel</button>
      </span>
    </form>
  );
}

export default function Mentoring() {
  const [mode, setMode] = useState("offering");
  const [topic, setTopic] = useState("");
  const [people, setPeople] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => {
      api(`/mentoring?mode=${mode}${topic ? `&topic=${encodeURIComponent(topic)}` : ""}`).then(setPeople).catch((err) => setError(err.message));
    }, 200);
    return () => clearTimeout(timer);
  }, [mode, topic]);

  return (
    <>
      <h1>Mentoring</h1>
      <p className="small muted">
        Members helping members, by choice. Mentors are volunteers, not certified or checked by Trade Circle, and nobody is promised a reply or ongoing help.
      </p>
      <MyStatus />
      <div className="tabs" role="group" aria-label="Show">
        <button type="button" aria-pressed={mode === "offering"} onClick={() => setMode("offering")}>Willing to help</button>
        <button type="button" aria-pressed={mode === "seeking"} onClick={() => setMode("seeking")}>Looking for a mentor</button>
      </div>
      <input type="search" aria-label="Topic" placeholder="Search topics" value={topic} onChange={(e) => setTopic(e.target.value)} style={{ marginBottom: 12 }} />
      <Notice error={error} />
      {people === null ? (
        <p className="loading">Loading…</p>
      ) : people.length === 0 ? (
        <p className="empty">No one listed{topic ? " for that topic" : ""} yet.</p>
      ) : (
        <ul className="items">
          {people.map((p) => (
            <li key={p.member.slug} className="card stack" style={{ margin: 0, gap: 6 }}>
              <Author author={p.member} />
              <div className="badge-line">{p.topics.map((t) => <span key={t} className="tag">{label(t)}</span>)}</div>
              {p.experience && <p className="small" style={{ margin: 0 }}>{p.experience}</p>}
              {p.availability && <p className="small muted" style={{ margin: 0 }}>Availability: {p.availability}</p>}
              <p className="small muted" style={{ margin: 0 }}>Prefers: {p.prefers}</p>
              <div className="row">
                <MessageRequest member={p.member} context="mentoring" buttonLabel="Ask for an introduction" />
                <CheerButton toSlug={p.member.slug} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
