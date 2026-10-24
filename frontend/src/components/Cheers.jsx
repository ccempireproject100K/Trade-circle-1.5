// The cheers economy, in the interface. A cheer is a thank-you with weight:
// one you receive waits until you send one (1-for-1, oldest first, to anyone
// in the circle). Allowance cheers arrive monthly by plan; cheers you collect
// bank — your banked count is your standing — and a banked cheer given away
// lands double. See backend/app/cheers.py for the rules themselves.
import { useEffect, useState } from "react";
import { api, shortDate } from "../api.js";

// One send button for every cheer surface: a post, a member's page, a handoff.
// Exactly one of postId / toSlug / handoffId. After a send it reports what
// happened — including when the send collected one of your own waiting cheers.
export function CheerButton({ postId = null, toSlug = null, handoffId = null, children = "🎉 Cheer", onSent }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const send = async () => {
    setBusy(true);
    setError("");
    try {
      const body = {};
      if (postId) body.post_id = postId;
      if (toSlug) body.to_slug = toSlug;
      if (handoffId) body.handoff_id = handoffId;
      const res = await api("/cheers", { method: "POST", body });
      setResult(res);
      onSent?.(res);
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  if (result) {
    return (
      <span className="small">
        🎉 Cheered{result.sent === 2 ? " — double!" : ""}
        {result.collected ? ` And your cheer from ${result.collected.from} landed.` : ""}
      </span>
    );
  }
  return (
    <span>
      <button type="button" className="btn btn-small" disabled={busy} onClick={send}>{children}</button>
      {error && <span className="small" style={{ color: "var(--bad)", marginLeft: 8 }}>{error}</span>}
    </span>
  );
}

// The cheer control on a post: the count of cheers the post has drawn, and
// the button (everyone but the author — you can't cheer your own work).
export function PostCheer({ post }) {
  const [count, setCount] = useState(post.cheers || 0);
  if (post.mine) {
    return count > 0 ? <span className="small muted">🎉 {count}</span> : null;
  }
  return (
    <span className="row" style={{ gap: 8 }}>
      <CheerButton postId={post.id} onSent={(res) => setCount((c) => c + res.sent)} />
      {count > 0 && <span className="small muted">{count}</span>}
    </span>
  );
}

function ActivityList({ title, rows, verb }) {
  if (!rows || rows.length === 0) return null;
  return (
    <>
      <h3 style={{ margin: "8px 0 0" }}>{title}</h3>
      <ul className="items" style={{ gap: 6 }}>
        {rows.slice(0, 8).map((row) => (
          <li key={row.id} className="small">
            {verb} {row.member ? row.member.business_name : "a member"}
            {row.status === "waiting" ? " · waiting" : " · banked"}
            {row.note && ` · "${row.note}"`}
            <span className="muted"> · {shortDate(row.created_at)}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

// Your cheers, plainly, on your profile: what you hold, what you've banked,
// what's waiting on you — plus the recent comings and goings.
export function CheersPanel() {
  const [data, setData] = useState(null);

  useEffect(() => {
    api("/cheers/me").then(setData).catch(() => {});
  }, []);

  if (!data) return null;
  return (
    <section className="card stack" id="cheers">
      <h2>Cheers</h2>
      <p className="small muted" style={{ margin: 0 }}>
        Cheers run on paying it forward: a cheer you receive waits until you send one, then it banks. Your banked count
        is your standing — it shows beside your reviews. Banked cheers you give away land double.
        {data.monthly > 0
          ? ` Your plan adds ${data.monthly} allowance cheers a month (wallet holds up to ${data.cap}).`
          : " Free plans hold no allowance — your cheers come from other members cheering your work, and a waiting cheer can always be passed on."}
      </p>
      <div className="work-strip" aria-label="Your cheers">
        <div className="stat"><strong>{data.allowance}</strong>allowance cheers</div>
        <div className="stat"><strong>{data.bank}</strong>bank cheers on hand</div>
        <div className="stat"><strong>{data.banked}</strong>banked (lifetime)</div>
        <div className="stat"><strong>{data.waiting}</strong>waiting</div>
        <div className="stat"><strong>{data.given}</strong>given</div>
      </div>
      {data.waiting > 0 && (
        <p className="notice notice-ok" style={{ margin: 0 }}>
          🎉 {data.waiting} {data.waiting === 1 ? "cheer is" : "cheers are"} waiting for you — send a cheer to collect {data.waiting === 1 ? "it" : "them"}.
        </p>
      )}
      <ActivityList title="Cheers you've received" rows={data.activity?.received} verb="From" />
      <ActivityList title="Cheers you've given" rows={data.activity?.given} verb="To" />
      <p className="small muted" style={{ margin: 0 }}>One cheer per person per day — appreciation is generous, and collecting spreads around the circle.</p>
    </section>
  );
}
