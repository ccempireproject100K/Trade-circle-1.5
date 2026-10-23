import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, dollars, shortDate, toCents } from "../api.js";
import { Field, Notice } from "../components/Form.jsx";

// Payment requests (Full plan): money goes straight to the contractor's own Stripe account.
const STATUS = { open: "Waiting", partly_paid: "Partly paid", paid: "Paid", cancelled: "Closed" };
const BLANK = { customer_name: "", customer_email: "", description: "", amount: "", note: "", allow_partial: false, min_partial: "", card: true, bank: true, offer_save_card: false, job_id: "" };

function NewRequest({ jobs, start, onCreated, onClose }) {
  const [f, setF] = useState({ ...BLANK, ...start });
  const [error, setError] = useState("");
  const set = (key) => (e) => setF({ ...f, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const submit = async (event) => {
    event.preventDefault();
    const amount = toCents(f.amount);
    const min = f.allow_partial && f.min_partial ? toCents(f.min_partial) : null;
    if (!amount || Number.isNaN(amount)) return setError("Enter the amount, like 250 or 1,250.00.");
    if (Number.isNaN(min)) return setError("Enter the smallest part as a dollar amount.");
    try {
      onCreated(await api("/payments/requests", {
        method: "POST",
        body: {
          customer_name: f.customer_name, customer_email: f.customer_email || null, description: f.description, amount_cents: amount, note: f.note,
          allow_partial: f.allow_partial, min_partial_cents: min, card: f.card, bank: f.bank, offer_save_card: f.card && f.offer_save_card, job_id: f.job_id || null,
        },
      }));
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="card stack" onSubmit={submit}>
      <div className="row-between">
        <h2 style={{ margin: 0 }}>Request a payment</h2>
        <button type="button" className="linklike" onClick={onClose}>Close</button>
      </div>
      <div className="grid-2">
        <Field label="Customer name"><input required maxLength={120} value={f.customer_name} onChange={set("customer_name")} /></Field>
        <Field label="Customer email (optional)" hint="Stripe emails the receipt; lets them reuse a saved card"><input type="email" value={f.customer_email} onChange={set("customer_email")} /></Field>
        <Field label="What it's for"><input required maxLength={140} value={f.description} onChange={set("description")} placeholder="Panel upgrade" /></Field>
        <Field label="Amount ($)"><input required inputMode="decimal" value={f.amount} onChange={set("amount")} /></Field>
      </div>
      {jobs.length > 0 && (
        <Field label="Job (optional)">
          <select value={f.job_id} onChange={set("job_id")}>
            <option value="">Not linked</option>
            {jobs.map((j) => <option key={j.id} value={j.id}>{j.title}{j.customer_name ? ` · ${j.customer_name}` : ""}</option>)}
          </select>
        </Field>
      )}
      <Field label="One-line note on the payment page (optional)"><input maxLength={140} value={f.note} onChange={set("note")} placeholder="Thanks for choosing us!" /></Field>
      <fieldset className="checks">
        <legend className="field-label">Customer can pay by</legend>
        <label><input type="checkbox" checked={f.card} onChange={set("card")} /> Card</label>
        <label><input type="checkbox" checked={f.bank} onChange={set("bank")} /> Bank account (ACH)</label>
      </fieldset>
      <label className="check" style={{ alignItems: "center" }}><input type="checkbox" checked={f.allow_partial} onChange={set("allow_partial")} /><span>Let them pay in parts</span></label>
      {f.allow_partial && <Field label="Smallest part ($, optional)"><input inputMode="decimal" value={f.min_partial} onChange={set("min_partial")} /></Field>}
      {f.card && <label className="check" style={{ alignItems: "center" }}><input type="checkbox" checked={f.offer_save_card} onChange={set("offer_save_card")} /><span>Offer to save their card for next time</span></label>}
      <Notice error={error} />
      <button className="btn btn-primary">Create payment link</button>
    </form>
  );
}

function RequestItem({ r, onChange }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const message = `Here's the payment link for ${r.description}: ${r.link}`;
  const cancel = async () => {
    if (!window.confirm("Close this payment request? Anything already paid stays paid.")) return;
    try {
      onChange(await api(`/payments/requests/${r.id}/cancel`, { method: "POST" }));
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <li className="card stack" style={{ margin: 0, gap: 6 }}>
      <div className="row-between">
        <strong>{r.description}</strong>
        <span className={`pill pill-${r.status}`}>{STATUS[r.status]}</span>
      </div>
      <span className="small muted">{r.customer_name} · {shortDate(r.created_at)}</span>
      <span>
        Total {dollars(r.amount_cents)} · paid {dollars(r.paid_cents - r.refunded_cents)}
        {r.processing_cents > 0 && ` · ${dollars(r.processing_cents)} clearing`} · <strong>due {dollars(r.due_cents)}</strong>
      </span>
      {r.payments.length > 0 && (
        <ul className="small" style={{ margin: 0 }}>
          {r.payments.map((p, i) => (
            <li key={i}>
              {shortDate(p.at)}: {dollars(p.amount_cents)} by {p.method === "bank" ? "bank" : "card"} · {{ succeeded: "received", processing: "clearing", failed: "didn't go through" }[p.status]}
              {p.refunded_cents > 0 && ` · ${dollars(p.refunded_cents)} refunded`}
            </li>
          ))}
        </ul>
      )}
      {["open", "partly_paid"].includes(r.status) && (
        <span className="row">
          <button type="button" className="btn btn-small" onClick={() => navigator.clipboard?.writeText(r.link).then(() => setCopied(true), () => {})}>{copied ? "Copied" : "Copy link"}</button>
          <a className="btn btn-small" href={`sms:?&body=${encodeURIComponent(message)}`}>Text it</a>
          {r.customer_email && <a className="btn btn-small" href={`mailto:${r.customer_email}?subject=${encodeURIComponent(`Payment for ${r.description}`)}&body=${encodeURIComponent(message)}`}>Email it</a>}
          <a className="btn btn-small" href={r.link} target="_blank" rel="noreferrer">Preview</a>
          <button type="button" className="linklike small" onClick={cancel}>Close request</button>
        </span>
      )}
      <Notice error={error} />
    </li>
  );
}

export default function Payments() {
  const [params] = useSearchParams();
  const [acct, setAcct] = useState(null);
  const [requests, setRequests] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [adding, setAdding] = useState(!!params.get("job"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  const load = () => {
    api("/payments/account").then(setAcct, (err) => setError(err.message));
    api("/payments/requests").then(setRequests, () => {});
  };
  useEffect(() => {
    load();
    api("/jobs").then(setJobs, () => {});
  }, []);

  const connect = async () => {
    setBusy(true);
    setError("");
    try {
      window.location.assign((await api("/payments/connect", { method: "POST" })).url);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  if (!acct) return <Notice error={error} />;
  const job = jobs.find((j) => j.id === params.get("job"));
  return (
    <>
      <div className="row-between">
        <h1>Payments</h1>
        {acct.charges_enabled && acct.plan_allows && <button type="button" className="btn btn-primary btn-small" onClick={() => setAdding(!adding)}>{adding ? "Close" : "Request payment"}</button>}
      </div>
      <p className="small muted" style={{ marginTop: 0 }}>
        Customers pay by card or bank on a simple page with your colors. Money goes straight to your own Stripe account; Stripe's fees come out of each payment, and
        Trade Circle takes nothing.
      </p>
      <Notice error={error} ok={ok} />
      {!acct.plan_allows ? (
        <p className="card">Taking payments is part of the Full plan. <Link to="/plan">See plans</Link></p>
      ) : !acct.ready ? (
        <p className="card">Customer payments aren't open yet. You'll connect your Stripe account here once they are.</p>
      ) : !acct.charges_enabled ? (
        <section className="card stack">
          <p style={{ margin: 0 }}>
            {acct.connected ? "Your Stripe account isn't finished yet. Stripe needs a few more details before you can take payments." : "Connect a Stripe account so payments go to your bank. Stripe asks for your business and bank details on its own secure pages."}
          </p>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={connect}>{busy ? "Opening Stripe…" : acct.connected ? "Finish on Stripe" : "Connect with Stripe"}</button>
        </section>
      ) : (
        adding && (
          <NewRequest jobs={jobs} start={job ? { job_id: job.id, customer_name: job.customer_name || "", description: job.title, amount: job.estimate_cents ? (job.estimate_cents / 100).toFixed(2) : "" } : {}}
            onClose={() => setAdding(false)} onCreated={(r) => { setAdding(false); setRequests([r, ...requests]); setOk("Payment link created. Send it to your customer."); }} />
        )
      )}
      {requests.length > 0 ? (
        <ul className="items">{requests.map((r) => <RequestItem key={r.id} r={r} onChange={(n) => setRequests(requests.map((x) => (x.id === n.id ? n : x)))} />)}</ul>
      ) : (
        acct.charges_enabled && <p className="empty">No payment requests yet.</p>
      )}
    </>
  );
}
