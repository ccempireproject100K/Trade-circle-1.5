import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, dollars, label, localToday, shortDate } from "../api.js";
import { Field, Notice } from "../components/Form.jsx";

// The handoff week runs on Trade Circle's time zone, so show the reset in that zone with its label.
const resetText = (iso, timeZone) =>
  new Date(iso).toLocaleString("en-US", { weekday: "long", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone, timeZoneName: "short" });

const dayAfter = (iso) => {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + 1);
  return d.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
};

// What a member sees before sending: the limits, where they stand, and when they reset.
function Allowance({ allowance }) {
  if (allowance.limits_lifted) {
    const v = allowance.vacation;
    return (
      <div className="notice notice-ok">
        You're on vacation ({shortDate(v.start_on)} to {shortDate(v.end_on)}), so weekly handoff limits are paused. Normal limits come back
        automatically on {dayAfter(v.end_on)}.
      </div>
    );
  }
  if (allowance.at_limit) {
    return (
      <div className="notice notice-error" role="alert">
        You've used all {allowance.weekly_limit} handoffs for this week. Your allowance resets {resetText(allowance.resets_at, allowance.timezone)}. Until then you
        can arrange extra coverage outside Trade Circle. Everything else in Trade Circle works as normal.
      </div>
    );
  }
  return (
    <div className="card" style={{ margin: 0, background: "var(--bg)" }}>
      <strong>
        {allowance.used} of {allowance.weekly_limit} handoffs used this week
      </strong>
      <p className="small muted" style={{ margin: "4px 0 0" }}>
        You can hand off up to {allowance.weekly_limit} jobs a week, and no more than {allowance.per_recipient_limit} to the same member.
        Declined or withdrawn offers don't count. Resets {resetText(allowance.resets_at, allowance.timezone)}.
        {allowance.by_recipient.length > 0 &&
          ` This week: ${allowance.by_recipient.map((r) => `${r.business_name} (${r.count})`).join(", ")}.`}
      </p>
    </div>
  );
}

function SendForm({ allowance, jobs, onSent }) {
  const [params] = useSearchParams();
  const [form, setForm] = useState({ job_id: params.get("job") || "", recipient_slug: "", start_on: "", end_on: "", note: "" });
  const [query, setQuery] = useState("");
  const [members, setMembers] = useState([]);
  const [status, setStatus] = useState({});
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  useEffect(() => {
    const job = jobs.find((j) => j.id === form.job_id);
    if (job?.scheduled_on && !form.start_on) setForm((f) => ({ ...f, start_on: job.scheduled_on }));
  }, [form.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const timer = setTimeout(() => {
      api(`/members?q=${encodeURIComponent(query)}`).then(setMembers).catch(() => setMembers([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  const chosen = members.find((m) => m.slug === form.recipient_slug);
  const sentToChosen = allowance.by_recipient.find((r) => r.slug === form.recipient_slug)?.count || 0;
  const recipientFull = !allowance.limits_lifted && sentToChosen >= allowance.per_recipient_limit;

  const submit = async (event) => {
    event.preventDefault();
    try {
      const body = { ...form, end_on: form.end_on || null };
      await api("/handoffs", { method: "POST", body });
      setStatus({ ok: `Sent to ${chosen?.business_name || "the member"}. It isn't handed off until they accept.` });
      setForm({ job_id: "", recipient_slug: "", start_on: "", end_on: "", note: "" });
      onSent();
    } catch (err) {
      setStatus({ error: err.message });
      onSent();
    }
  };

  if (allowance.at_limit) return null;
  if (jobs.length === 0) {
    return (
      <p className="muted">
        You have no open jobs to hand off. <Link to="/jobs">Add a job</Link> first.
      </p>
    );
  }

  return (
    <form className="stack" onSubmit={submit}>
      <Field label="Job">
        <select required value={form.job_id} onChange={set("job_id")}>
          <option value="" disabled>Choose a job</option>
          {jobs.map((j) => (
            <option key={j.id} value={j.id}>
              {j.title}{j.scheduled_on ? ` · ${shortDate(j.scheduled_on)}` : ""}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Find a member" hint="Search by business name.">
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Business name" />
      </Field>
      <Field label="Hand off to">
        <select required value={form.recipient_slug} onChange={set("recipient_slug")}>
          <option value="" disabled>{members.length ? "Choose a member" : "No members found"}</option>
          {members.map((m) => (
            <option key={m.slug} value={m.slug}>{m.business_name} · {label(m.trade)}, {m.city}</option>
          ))}
        </select>
      </Field>
      {recipientFull && (
        <p className="notice notice-error">
          You've already sent {allowance.per_recipient_limit} handoffs to {chosen?.business_name} this week. Choose another member.
        </p>
      )}
      <div className="grid-2">
        <Field label="Starts"><input type="date" required min={localToday()} value={form.start_on} onChange={set("start_on")} /></Field>
        <Field label="Ends (optional)"><input type="date" min={form.start_on || localToday()} value={form.end_on} onChange={set("end_on")} /></Field>
      </div>
      <Field label="Note to the member" hint="Why you need cover, anything they should know.">
        <textarea maxLength={500} value={form.note} onChange={set("note")} />
      </Field>
      <p className="small muted" style={{ margin: 0 }}>
        They'll see the job, dates, address and your note. The customer's name and phone are shared only if they accept.
      </p>
      <Notice error={status.error} ok={status.ok} />
      <button className="btn btn-primary" disabled={recipientFull}>Send handoff</button>
    </form>
  );
}

const ENDED = { reversed: "Handed back", cancelled: "Cancelled by agreement" };

// Reversing (recipient) or asking to cancel (sender) needs a short reason.
function ReasonForm({ label: text, hint, onSubmit, onClose }) {
  const [reason, setReason] = useState("");
  return (
    <div className="stack" style={{ gap: 6, width: "100%" }}>
      <textarea aria-label="Reason" rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="A short reason" />
      <span className="field-hint">{hint}</span>
      <span className="row">
        <button type="button" className="btn btn-small btn-danger" disabled={reason.trim().length < 3} onClick={() => onSubmit(reason)}>{text}</button>
        <button type="button" className="linklike small" onClick={onClose}>Never mind</button>
      </span>
    </div>
  );
}

function HandoffCard({ h, onAction }) {
  const [asking, setAsking] = useState(null);
  const job = h.job;
  const pendingCancel = h.cancel_request?.status === "pending";
  const other = h.direction === "incoming" ? h.from : h.to;
  const dates = h.end_on && h.end_on !== h.start_on ? `${shortDate(h.start_on)} to ${shortDate(h.end_on)}` : shortDate(h.start_on);
  return (
    <li className="card" style={{ margin: 0 }}>
      <div className="row-between">
        <h3>{job.title}</h3>
        <span className={`pill pill-${h.status === "proposed" ? "new" : h.status === "completed" ? "done" : h.status === "accepted" ? "scheduled" : "cancelled"}`}>
          {h.status === "proposed" ? (h.direction === "incoming" ? "Waiting for you" : "Waiting") : ENDED[h.status] || label(h.status)}
        </span>
      </div>
      <p className="small muted" style={{ margin: "2px 0 0" }}>
        {h.direction === "incoming" ? "From" : "To"} <a href={`/p/${other.slug}`} target="_blank" rel="noreferrer">{other.business_name}</a> · {dates}
        {h.during_vacation && " · sent during vacation"}
      </p>
      {job.site_address && <p className="small" style={{ margin: "6px 0 0" }}>{job.site_address}</p>}
      {job.estimate_cents != null && <p className="small" style={{ margin: "2px 0 0" }}>Estimate {dollars(job.estimate_cents)}</p>}
      {h.note && <p className="item-message small">"{h.note}"</p>}
      {job.notes && <p className="item-message small muted">{job.notes}</p>}
      {job.customer_name && (
        <p className="small" style={{ margin: "6px 0 0" }}>
          Customer: {job.customer_name}
          {job.customer_phone && <> · <a href={`tel:${job.customer_phone}`}>{job.customer_phone}</a></>}
        </p>
      )}
      {h.end_reason && <p className="small" style={{ margin: "6px 0 0" }}>Reason: {h.end_reason}</p>}
      {pendingCancel && (
        <p className="notice notice-error small" style={{ marginTop: 8 }}>
          {h.direction === "incoming" ? `${h.from.business_name} asked to cancel: ` : "You asked to cancel, waiting for their answer: "}
          {h.cancel_request.reason}
        </p>
      )}
      {h.cancel_request?.status === "declined" && h.status === "accepted" && h.direction === "outgoing" && (
        <p className="small muted" style={{ marginTop: 8 }}>They chose to keep the job.</p>
      )}
      <div className="row" style={{ marginTop: 8 }}>
        {asking === "reverse" && (
          <ReasonForm label="Hand it back" hint="The job goes back to the sender's job sheet, and they're told why." onClose={() => setAsking(null)} onSubmit={(reason) => onAction(h, "reverse", { reason })} />
        )}
        {asking === "cancel" && (
          <ReasonForm label="Ask to cancel" hint="They can agree or keep the job. If they agree, it comes back to your job sheet; it still counts toward this week's handoffs." onClose={() => setAsking(null)} onSubmit={(reason) => onAction(h, "cancel-request", { reason })} />
        )}
        {!asking && h.direction === "incoming" && h.status === "accepted" && pendingCancel && (
          <>
            <button type="button" className="btn btn-small" onClick={() => onAction(h, "cancel-request/respond", { agree: true })}>Agree to cancel</button>
            <button type="button" className="btn btn-small" onClick={() => onAction(h, "cancel-request/respond", { agree: false })}>Keep the job</button>
          </>
        )}
        {!asking && h.direction === "incoming" && h.status === "accepted" && (
          <button type="button" className="linklike small" onClick={() => setAsking("reverse")}>Hand it back</button>
        )}
        {!asking && h.direction === "outgoing" && h.status === "accepted" && !pendingCancel && (
          <button type="button" className="linklike small" onClick={() => setAsking("cancel")}>Ask to cancel</button>
        )}
        {h.direction === "incoming" && h.status === "proposed" && (
          <>
            <button type="button" className="btn btn-primary btn-small" onClick={() => onAction(h, "accept")}>Accept</button>
            <button type="button" className="btn btn-small" onClick={() => onAction(h, "decline")}>Decline</button>
          </>
        )}
        {!asking && h.direction === "incoming" && h.status === "accepted" && (
          <button type="button" className="btn btn-small" onClick={() => onAction(h, "complete")}>Mark completed</button>
        )}
        {h.direction === "outgoing" && h.status === "proposed" && (
          <button type="button" className="btn btn-small" onClick={() => onAction(h, "withdraw")}>Withdraw</button>
        )}
      </div>
    </li>
  );
}

export default function Handoffs() {
  const [params] = useSearchParams();
  const [allowance, setAllowance] = useState(null);
  const [handoffs, setHandoffs] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [view, setView] = useState(params.get("view") === "sent" ? "outgoing" : "incoming");
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const [a, h, j] = await Promise.all([api("/handoffs/allowance"), api("/handoffs"), api("/jobs")]);
      setAllowance(a);
      setHandoffs(h);
      const offered = new Set(h.filter((x) => x.direction === "outgoing" && ["proposed", "accepted"].includes(x.status)).map((x) => x.job_id));
      setJobs(j.filter((x) => !["done", "cancelled", "handed_off"].includes(x.status) && !offered.has(x.id)));
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const act = async (h, action, body) => {
    setError("");
    try {
      await api(`/handoffs/${h.id}/${action}`, { method: "POST", body });
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  if (!allowance || !handoffs) return error ? <Notice error={error} /> : <p className="loading">Loading…</p>;
  const incoming = handoffs.filter((h) => h.direction === "incoming");
  const outgoing = handoffs.filter((h) => h.direction === "outgoing");
  const waiting = incoming.filter((h) => h.status === "proposed").length;
  const shown = view === "incoming" ? incoming : outgoing;

  return (
    <>
      <h1>Handoffs</h1>
      <p className="muted small">
        Now and then a member needs someone to cover a job they've already committed to. Handoffs are limited so Trade Circle stays a
        community, not a job board.
      </p>

      <section className="card stack">
        <h2>Hand off a job</h2>
        <Allowance allowance={allowance} />
        <SendForm allowance={allowance} jobs={jobs} onSent={load} />
        <p className="small muted" style={{ margin: 0 }}>
          Going away? <Link to="/settings">Set a vacation</Link> of up to 14 days to pause the weekly limits.
        </p>
      </section>

      <div className="tabs" role="group" aria-label="Handoff list">
        <button type="button" aria-pressed={view === "incoming"} onClick={() => setView("incoming")}>
          For you ({incoming.length}){waiting ? ` · ${waiting} waiting` : ""}
        </button>
        <button type="button" aria-pressed={view === "outgoing"} onClick={() => setView("outgoing")}>Sent ({outgoing.length})</button>
      </div>
      <Notice error={error} />
      {shown.length === 0 ? (
        <p className="empty">{view === "incoming" ? "No one has asked you to cover a job." : "You haven't handed off any jobs."}</p>
      ) : (
        <ul className="items">
          {shown.map((h) => <HandoffCard key={h.id} h={h} onAction={act} />)}
        </ul>
      )}
    </>
  );
}
