import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, label, shortDate, toCents } from "../api.js";
import { ReportButton } from "../components/Community.jsx";
import { Field, Notice } from "../components/Form.jsx";
import { savedArea } from "../labels.js";

// Jobs customers posted near you. Their contact details come only if they choose you.
function BidForm({ job, onSent }) {
  const [f, setF] = useState({ message: "", low: "", high: "", available_on: "" });
  const [error, setError] = useState("");
  const set = (key) => (e) => setF({ ...f, [key]: e.target.value });
  const send = async (event) => {
    event.preventDefault();
    try {
      const res = await api(`/marketplace/${job.id}/bids`, {
        method: "POST",
        body: { message: f.message, price_low_cents: f.low ? toCents(f.low) : null, price_high_cents: f.high ? toCents(f.high) : null, available_on: f.available_on || null },
      });
      onSent(res);
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="stack" onSubmit={send} style={{ gap: 8 }}>
      <Field label="Your message to the customer"><textarea required minLength={10} maxLength={1500} rows={3} value={f.message} onChange={set("message")} placeholder="What you'd do, and any questions" /></Field>
      <div className="grid-2">
        <Field label="Estimate from ($, optional)"><input inputMode="decimal" value={f.low} onChange={set("low")} /></Field>
        <Field label="Estimate to ($, optional)"><input inputMode="decimal" value={f.high} onChange={set("high")} /></Field>
        <Field label="Could start (optional)"><input type="date" value={f.available_on} onChange={set("available_on")} /></Field>
      </div>
      <Notice error={error} />
      <button className="btn btn-primary">Send bid</button>
    </form>
  );
}

function Job({ job, onBid }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="card stack" style={{ margin: 0, gap: 6 }}>
      <div className="badge-line">
        <span className="tag">{label(job.trade)}</span>
        <span className="small muted">{job.area}{job.distance_miles != null && ` · ${job.distance_miles} mi`} · posted {shortDate(job.posted_at)}</span>
      </div>
      <h3 style={{ margin: 0 }}>{job.title}</h3>
      <p className="item-message" style={{ margin: 0 }}>{job.details}</p>
      <p className="small" style={{ margin: 0 }}>
        When: {job.wanted_on ? shortDate(job.wanted_on) : job.flexible ? "Flexible" : <span className="muted">Not given</span>} · Budget: {job.budget || <span className="muted">Not given</span>}
      </p>
      {job.photos.length > 0 && <div className="post-photos">{job.photos.map((p, i) => <a key={i} href={p.image_url}><img src={p.thumb_url} alt="Job photo" loading="lazy" /></a>)}</div>}
      {job.missing.length > 0 && <p className="small muted" style={{ margin: 0 }}>Not given: {job.missing.join(", ")}. Ask in your bid if you need it.</p>}
      <details className="small"><summary>Why you're seeing this</summary><ul style={{ margin: "4px 0 0" }}>{job.why.map((w) => <li key={w}>{w}</li>)}</ul></details>
      <p className="small muted" style={{ margin: 0 }}>{job.bid_count} {job.bid_count === 1 ? "bid" : "bids"} so far · open until {shortDate(job.closes_on)}</p>
      {job.my_bid ? (
        <p className="notice notice-ok" style={{ margin: 0 }}>{job.my_bid.status === "chosen" ? "The customer chose you. Their details are in Follow-ups." : "You bid on this. The customer will choose who to talk to."}</p>
      ) : open ? (
        <BidForm job={job} onSent={(res) => { setOpen(false); onBid(job, res); }} />
      ) : (
        <span className="row">
          <button type="button" className="btn btn-primary btn-small" onClick={() => setOpen(true)}>Bid on this job</button>
          <ReportButton targetType="lead" targetId={job.id} />
        </span>
      )}
    </li>
  );
}

export default function Marketplace() {
  const [area, setArea] = useState(savedArea.get());
  const [radius, setRadius] = useState(30);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const load = () => {
    const params = new URLSearchParams({ radius });
    if (area.near) params.set("near", area.near);
    api(`/marketplace?${params}`).then(setData, (err) => setError(err.message));
  };
  useEffect(load, [area.near, radius]); // eslint-disable-line react-hooks/exhaustive-deps

  const [place, setPlace] = useState(area.near);
  const apply = (event) => {
    event.preventDefault();
    const next = { ...area, near: place.trim() };
    savedArea.set(next);
    setError("");
    setArea(next);
  };
  const postLink = `${window.location.origin}/request`;
  return (
    <>
      <h1>Marketplace</h1>
      <p className="small muted" style={{ marginTop: 0 }}>
        Jobs customers posted near you, in your trade. You see the job, area, timing, budget and photos; their contact details come to you only if they choose you.
      </p>
      <form className="row" onSubmit={apply} style={{ marginBottom: 8 }}>
        <input aria-label="Your area" placeholder='ZIP or "City, ST"' value={place} onChange={(e) => setPlace(e.target.value)} style={{ flex: 1 }} />
        <select aria-label="Distance" value={radius} onChange={(e) => setRadius(Number(e.target.value))}>
          {[10, 20, 30, 50, 75, 100].map((r) => <option key={r} value={r}>{r} mi</option>)}
        </select>
        <button className="btn btn-small">Show jobs</button>
      </form>
      <Notice error={error} />
      {data && (
        <p className="small" style={{ margin: "0 0 12px" }}>
          {data.bids_left == null ? "Unlimited bids on your plan." : <>{data.bids_left} of {data.free_bids} bids left this month. <Link to="/plan">Full plan</Link> has unlimited bids.</>}
        </p>
      )}
      {!data ? null : data.needs_area ? (
        <p className="empty">Enter your ZIP code or city to see jobs near you.</p>
      ) : data.requests.length === 0 ? (
        <p className="empty">No open {label(data.trade || "")} jobs within {data.radius} miles right now.</p>
      ) : (
        <ul className="items">{data.requests.map((j) => <Job key={j.id} job={j} onBid={(job, res) => setData({ ...data, bids_left: res.bids_left, requests: data.requests.map((x) => (x.id === job.id ? { ...x, my_bid: { status: "sent" }, bid_count: x.bid_count + 1 } : x)) })} />)}</ul>
      )}
      <section className="card stack">
        <h2 style={{ margin: 0 }}>Customers post jobs here</h2>
        <code className="ref-link">{postLink}</code>
        <button type="button" className="btn btn-small" style={{ justifySelf: "start" }} onClick={() => navigator.clipboard?.writeText(postLink).then(() => setCopied(true), () => {})}>{copied ? "Copied" : "Copy link"}</button>
      </section>
    </>
  );
}
