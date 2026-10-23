import { useEffect, useState } from "react";
import { api, shortDate } from "../api.js";
import { Field, Notice } from "../components/Form.jsx";

// Customer reviews. A customer who chose you in the marketplace can review
// you from their private request link once the lead is won or the job is
// done. Reviews show on your public page; you can answer each one, and flag
// one for a moderator if it shouldn't be there.
export const stars = (n) => "★".repeat(n) + "☆".repeat(5 - n);

const STATUS_LABEL = { flagged: "Flagged for a moderator", hidden: "Hidden by a moderator" };

function ReviewCard({ review, onSaved }) {
  const [mode, setMode] = useState(null); // "respond" | "flag"
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  const open = (next) => {
    setError("");
    setText(next === "respond" ? review.response?.text || "" : "");
    setMode(mode === next ? null : next);
  };

  const submit = async (event) => {
    event.preventDefault();
    try {
      const saved =
        mode === "respond"
          ? await api(`/reviews/${review.id}/response`, { method: "POST", body: { text } })
          : await api(`/reviews/${review.id}/flag`, { method: "POST", body: { note: text } });
      onSaved(saved);
      setMode(null);
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <li className="card" style={{ margin: 0 }}>
      <div className="row-between">
        <span className="stars" role="img" aria-label={`${review.stars} of 5 stars`}>{stars(review.stars)}</span>
        {STATUS_LABEL[review.status] && <span className="pill">{STATUS_LABEL[review.status]}</span>}
      </div>
      <p className="item-message">{review.text}</p>
      <p className="small muted" style={{ margin: "2px 0 0" }}>
        {review.reviewer_name} · {shortDate(review.created_at)}{review.job_type && ` · ${review.job_type}`}
      </p>
      {review.response && mode !== "respond" && (
        <div style={{ marginTop: 8 }}>
          <p className="item-message" style={{ margin: 0 }}>{review.response.text}</p>
          <p className="small muted" style={{ margin: "2px 0 0" }}>Your response · {shortDate(review.response.at)}</p>
        </div>
      )}
      <div className="row" style={{ margin: "8px 0" }}>
        <button type="button" className="btn btn-small" onClick={() => open("respond")}>{review.response ? "Edit response" : "Respond"}</button>
        {review.status !== "hidden" && (
          <button type="button" className="btn btn-small" onClick={() => open("flag")}>Flag for review</button>
        )}
      </div>
      {mode && (
        <form className="stack" onSubmit={submit}>
          <Field label={mode === "respond" ? "Your response (public)" : "Note for the moderator (optional)"}>
            <textarea aria-label={mode === "respond" ? "Your response" : "Note for the moderator"} rows={3} maxLength={mode === "respond" ? 1000 : 500} required={mode === "respond"} value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
          <Notice error={error} />
          <span className="row">
            <button className="btn btn-primary btn-small">{mode === "respond" ? "Save response" : "Send flag"}</button>
            <button type="button" className="btn btn-small" onClick={() => setMode(null)}>Cancel</button>
          </span>
          {mode === "flag" && <p className="small muted" style={{ margin: 0 }}>The review stays on your page until a moderator looks at it.</p>}
        </form>
      )}
      {!mode && <Notice error={error} />}
    </li>
  );
}

export default function Reviews() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/reviews").then(setData, (err) => setError(err.message));
  }, []);

  if (!data) return error ? <Notice error={error} /> : <p className="loading">Loading…</p>;
  const saved = (review) => setData((d) => ({ ...d, reviews: d.reviews.map((r) => (r.id === review.id ? review : r)) }));

  return (
    <>
      <h1>Reviews</h1>
      <p className="small muted" style={{ marginTop: 0 }}>
        Customers who chose you in the marketplace can review you from their request link once the work is won or done. Reviews are on every plan — they show on your public page.
      </p>
      {data.count > 0 && (
        <p>
          <span className="stars" role="img" aria-label={`${data.average} of 5 stars`}>{stars(Math.round(data.average))}</span>{" "}
          <strong>{data.average}</strong> · {data.count} review{data.count === 1 ? "" : "s"}
        </p>
      )}
      {data.reviews.length === 0 ? (
        <p className="empty">No reviews yet. When a marketplace job is won or finished, the customer gets the chance to review you.</p>
      ) : (
        <ul className="items">
          {data.reviews.map((r) => (
            <ReviewCard key={r.id} review={r} onSaved={saved} />
          ))}
        </ul>
      )}
    </>
  );
}
