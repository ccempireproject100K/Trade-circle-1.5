import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, shortDate } from "../api.js";
import { Author, ReportButton } from "../components/Community.jsx";
import { Notice } from "../components/Form.jsx";

const CONTEXT = { mentoring: "Mentoring introduction", post: "About a post", general: "Message request" };

export function MessageList() {
  const [requests, setRequests] = useState(null);
  const [convs, setConvs] = useState(null);
  const [error, setError] = useState("");

  const load = () =>
    Promise.all([api("/messages/requests"), api("/messages/conversations")])
      .then(([r, c]) => {
        setRequests(r);
        setConvs(c);
      })
      .catch((err) => setError(err.message));

  useEffect(() => {
    load();
  }, []);

  const respond = async (r, action) => {
    try {
      if (action === "block") await api(`/members/${r.member.slug}/block`, { method: "POST" });
      else await api(`/messages/requests/${r.id}/${action}`, { method: "POST" });
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  if (!requests || !convs) return error ? <Notice error={error} /> : <p className="loading">Loading…</p>;
  const sent = requests.outgoing.filter((r) => r.status !== "accepted");

  return (
    <>
      <h1>Messages</h1>
      <p className="small muted">Members can only message you after you accept their request. You can block anyone, any time.</p>
      <Notice error={error} />
      {requests.incoming.length > 0 && (
        <section className="stack" style={{ marginBottom: 20 }}>
          <h2 style={{ margin: 0 }}>Requests ({requests.incoming.length})</h2>
          <ul className="items">
            {requests.incoming.map((r) => (
              <li key={r.id} className="card" style={{ margin: 0 }}>
                <p className="small muted" style={{ margin: 0 }}>{CONTEXT[r.context]} · {shortDate(r.created_at)}</p>
                <Author author={r.member} />
                <p className="item-message">{r.note}</p>
                <div className="row">
                  <button type="button" className="btn btn-primary btn-small" onClick={() => respond(r, "accept")}>Accept</button>
                  <button type="button" className="btn btn-small" onClick={() => respond(r, "decline")}>Decline</button>
                  <button type="button" className="link-danger" onClick={() => window.confirm(`Block ${r.member.business_name}?`) && respond(r, "block")}>Block</button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="stack">
        <h2 style={{ margin: 0 }}>Conversations</h2>
        {convs.length === 0 ? (
          <p className="empty">No conversations yet.</p>
        ) : (
          <ul className="items">
            {convs.map((c) => (
              <li key={c.id} className="card" style={{ margin: 0 }}>
                <Link to={`/messages/${c.id}`} style={{ color: "inherit", textDecoration: "none" }}>
                  <strong>{c.member.business_name}</strong>
                  <p className="small muted" style={{ margin: "2px 0 0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.last}</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      {sent.length > 0 && (
        <section className="stack" style={{ marginTop: 20 }}>
          <h2 style={{ margin: 0 }}>Requests you sent</h2>
          <ul className="items">
            {sent.map((r) => <li key={r.id} className="small">{r.member.business_name}: <span className="muted">{r.status === "pending" ? "waiting for them to accept" : "not accepted"}</span></li>)}
          </ul>
        </section>
      )}
    </>
  );
}

export function Conversation() {
  const { id } = useParams();
  const [conv, setConv] = useState(null);
  const [body, setBody] = useState("");
  const [error, setError] = useState("");
  const end = useRef(null);

  const load = () => api(`/messages/conversations/${id}`).then(setConv).catch((err) => setError(err.message));
  useEffect(() => {
    load();
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => end.current?.scrollIntoView?.({ block: "end" }), [conv]);

  const send = async (event) => {
    event.preventDefault();
    try {
      await api(`/messages/conversations/${id}`, { method: "POST", body: { body } });
      setBody("");
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const toggleBlock = async () => {
    if (!conv.i_blocked && !window.confirm(`Block ${conv.member.business_name}? Neither of you will be able to send messages.`)) return;
    await api(`/members/${conv.member.slug}/block`, { method: conv.i_blocked ? "DELETE" : "POST" });
    load();
  };

  if (!conv) return error ? <Notice error={error} /> : <p className="loading">Loading…</p>;

  return (
    <>
      <p className="small"><Link to="/messages">← Messages</Link></p>
      <div className="row-between">
        <h1 style={{ marginBottom: 4 }}>{conv.member.business_name}</h1>
        <span className="row">
          <ReportButton targetType="member" targetId={conv.member.slug} label="Report" />
          <button type="button" className="linklike small" onClick={toggleBlock}>{conv.i_blocked ? "Unblock" : "Block"}</button>
        </span>
      </div>
      <ul className="items" style={{ gap: 8 }}>
        {conv.messages.map((m) => (
          <li key={m.id} className="card" style={{ margin: 0, padding: 12, background: m.mine ? "var(--bg)" : undefined, borderStyle: m.system ? "dashed" : undefined }}>
            <p className="item-message" style={{ margin: 0 }}>{m.body}</p>
            <div className="row-between">
              <span className="small muted">{m.system ? "Shared when the introduction was accepted" : m.mine ? "You" : conv.member.business_name} · {shortDate(m.created_at)}</span>
              {!m.mine && !m.system && <ReportButton targetType="message" targetId={m.id} />}
            </div>
          </li>
        ))}
      </ul>
      <div ref={end} />
      {conv.blocked ? (
        <p className="notice notice-error" style={{ marginTop: 12 }}>Messages are turned off in this conversation.</p>
      ) : (
        <form className="stack" style={{ marginTop: 12 }} onSubmit={send}>
          <textarea aria-label="Message" required maxLength={4000} rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
          <Notice error={error} />
          <button className="btn btn-primary">Send</button>
        </form>
      )}
    </>
  );
}
