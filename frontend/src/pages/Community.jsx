import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, label } from "../api.js";
import { PostCard } from "../components/Community.jsx";
import { Notice } from "../components/Form.jsx";
import { KIND_NAMES, savedArea } from "../labels.js";

// Feed filters. Supplier posts live on Supplies & Vendors; everything is searchable here too.
const FILTERS = [
  { key: "", label: "Everything" },
  { key: "project", label: "Projects" },
  { key: "lesson", label: "Lessons" },
  { key: "equipment,equipment_question", label: "Equipment" },
  { key: "meetup", label: "Meetups" },
  { key: "opening", label: "Hiring" },
  { key: "starting_out", label: "Starting Out" },
  { key: "supply_question,supplier_review,supplier_suggestion", label: "Supplies" },
];

export default function Community() {
  const [kind, setKind] = useState("");
  const [trade, setTrade] = useState("");
  const [q, setQ] = useState("");
  const [nearby, setNearby] = useState(false);
  const [trades, setTrades] = useState([]);
  const [posts, setPosts] = useState(null);
  const [error, setError] = useState("");
  const area = savedArea.get();

  useEffect(() => {
    api("/community/meta").then((m) => setTrades(m.trades)).catch(() => {});
  }, []);

  useEffect(() => {
    const params = new URLSearchParams();
    if (kind === "meetup") params.set("upcoming", "true");
    else if (kind) params.set("kind", kind);
    if (trade) params.set("trade", trade);
    if (q.trim()) params.set("q", q.trim());
    if (nearby && area.near) {
      params.set("near", area.near);
      params.set("radius", area.radius);
    }
    const timer = setTimeout(() => {
      api(`/posts?${params}`).then((r) => setPosts(r.posts)).catch((err) => setError(err.message));
    }, 200);
    return () => clearTimeout(timer);
  }, [kind, trade, q, nearby]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="row-between">
        <h1>Community</h1>
        <Link className="btn btn-primary btn-small" to="/share">Share</Link>
      </div>
      <p className="small" style={{ marginTop: 0 }}>
        <Link to="/mentoring">Mentoring</Link> · <Link to="/share/meetup">Host a meetup</Link> · <Link to="/share/opening">Post a job opening</Link> · <Link to="/messages">Messages</Link>
      </p>
      <div className="tabs" role="group" aria-label="Show">
        {FILTERS.map((f) => (
          <button key={f.key} type="button" aria-pressed={kind === f.key} onClick={() => setKind(f.key)}>{f.label}</button>
        ))}
      </div>
      <div className="grid-2" style={{ marginBottom: 12 }}>
        <input type="search" aria-label="Search posts" placeholder="Search posts" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Trade" value={trade} onChange={(e) => setTrade(e.target.value)}>
          <option value="">All trades</option>
          {trades.map((t) => <option key={t} value={t}>{label(t)}</option>)}
        </select>
      </div>
      {area.near && (
        <label className="check" style={{ alignItems: "center", marginBottom: 12 }}>
          <input type="checkbox" checked={nearby} onChange={(e) => setNearby(e.target.checked)} />
          <span className="small">Only within {area.radius} mi of {area.near}</span>
        </label>
      )}
      <Notice error={error} />
      {posts === null ? (
        <p className="loading">Loading…</p>
      ) : posts.length === 0 ? (
        <p className="empty">Nothing here yet{kind ? ` for ${KIND_NAMES[kind.split(",")[0]] || "this filter"}` : ""}. Share the first one.</p>
      ) : (
        <ul className="items">{posts.map((p) => <PostCard key={p.id} post={p} />)}</ul>
      )}
    </>
  );
}
