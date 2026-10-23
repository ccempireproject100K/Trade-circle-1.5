import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, label } from "../api.js";
import { Author, PostBadges, ReportButton } from "../components/Community.jsx";
import { Field, Notice } from "../components/Form.jsx";
import MessageRequest from "../components/MessageRequest.jsx";
import { EMPLOYMENT_TYPES } from "../labels.js";

// Kind-specific details, shown under the post text with plain headings.
const SECTIONS = {
  project: [["job", "The job"], ["challenge", "What came up"], ["handled", "How it was handled"], ["learned", "What I learned"]],
  lesson: [["what_happened", "What happened"], ["outcome", "What worked or went wrong"], ["resolution", "How it was resolved"], ["tip", "What would help another contractor"]],
  equipment: [["used_for", "Used for"], ["durability", "Durability"], ["problems", "Problems"], ["repairs", "Repairs and maintenance"]],
};

// Photos open full size; clips play in place, loading only when tapped.
export function Media({ items, alt = "" }) {
  const clips = items.filter((p) => p.type === "video");
  const pictures = items.filter((p) => p.type !== "video");
  return (
    <>
      {pictures.length > 0 && <div className="post-photos">{pictures.map((p) => <a key={p.id} href={p.image_url}><img src={p.thumb_url} alt={alt} /></a>)}</div>}
      {clips.map((c) => <video key={c.id} className="post-clip" src={c.video_url} poster={c.thumb_url} controls playsInline preload="none" />)}
    </>
  );
}

function PhotoGroup({ title, photos }) {
  return (
    <>
      <h3 style={{ margin: "12px 0 2px" }}>{title}</h3>
      <Media items={photos} alt={title} />
    </>
  );
}

export function PostBody({ post }) {
  const f = post.fields || {};
  const groups = { before: post.photos.filter((p) => p.group === "before"), after: post.photos.filter((p) => p.group === "after"), other: post.photos.filter((p) => !p.group) };
  return (
    <>
      {post.kind.startsWith("equipment") && (f.product || f.model) && (
        <p style={{ margin: "4px 0" }}><strong>{[f.product, f.model].filter(Boolean).join(" · ")}</strong></p>
      )}
      {post.kind === "opening" && (
        <div className="stack" style={{ gap: 4, margin: "6px 0" }}>
          <p style={{ margin: 0 }}><strong>{f.role}</strong> · {EMPLOYMENT_TYPES[f.employment_type]}{f.pay && ` · ${f.pay}`}</p>
          {f.apply_by && <p className="small" style={{ margin: 0 }}>Apply by {f.apply_by}</p>}
          {f.filled && <p className="notice notice-ok" style={{ margin: 0 }}>This position has been filled.</p>}
        </div>
      )}
      {post.kind === "spot" && (
        <div className="stack" style={{ gap: 4, margin: "6px 0" }}>
          <p style={{ margin: 0 }}><strong>{f.place}</strong> · {f.suggestion === "deal" ? "A deal a member found" : "A place a member recommends"}</p>
          {f.link && <p className="small" style={{ margin: 0 }}><a href={f.link} target="_blank" rel="noreferrer nofollow ugc">{f.link}</a></p>}
          <p className="small muted" style={{ margin: 0 }}>
            Member recommendation, not a sponsored listing. {f.connection === "none" ? "No connection to this place." : `Disclosed connection: ${label(f.connection)}${f.connection_detail ? ` (${f.connection_detail})` : ""}`}
          </p>
        </div>
      )}
      {post.body && <p className="item-message">{post.body}</p>}
      {post.kind === "opening" && (f.requirements || f.how_to_apply) && (
        <>
          {f.requirements && <><h3 style={{ margin: "12px 0 2px" }}>Requirements</h3><p className="item-message" style={{ margin: 0 }}>{f.requirements}</p></>}
          <h3 style={{ margin: "12px 0 2px" }}>How to apply</h3>
          <p className="item-message" style={{ margin: 0 }}>{f.how_to_apply || "Message the poster through Trade Circle."}</p>
        </>
      )}
      {(SECTIONS[post.kind] || []).map(([k, title]) => (
        <div key={k}>
          {f[k] && (
            <>
              <h3 style={{ margin: "12px 0 2px" }}>{title}</h3>
              <p className="item-message" style={{ margin: 0 }}>{f[k]}</p>
            </>
          )}
          {/* Before photos follow the job, finished photos follow how it was handled, whether or not those were answered. */}
          {k === "job" && groups.before.length > 0 && <PhotoGroup title="Before" photos={groups.before} />}
          {k === "handled" && groups.after.length > 0 && <PhotoGroup title="Finished" photos={groups.after} />}
        </div>
      ))}
      {post.kind === "equipment" && (
        <p className="small" style={{ margin: "10px 0 0" }}>
          Would buy again: <strong>{{ yes: "Yes", no: "No", unsure: "Not sure", "": "Not said" }[f.buy_again || ""]}</strong>
          {" · "}
          {f.affiliation === "none" ? "No connection to the seller or maker" : `Disclosed connection: ${label(f.affiliation)}${f.affiliation_detail ? ` (${f.affiliation_detail})` : ""}`}
        </p>
      )}
      {groups.other.length > 0 && <Media items={groups.other} />}
      {post.photos_hidden && <p className="small muted">Photos on this post are hidden.</p>}
    </>
  );
}

const RSVP = { going: "Going", maybe: "Maybe", not_going: "Can't go" };

function when(f) {
  const [y, m, d] = f.starts_on.split("-").map(Number);
  const [hh, mm] = f.starts_at.split(":").map(Number);
  const day = new Date(y, m - 1, d).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  const time = new Date(2000, 0, 1, hh, mm).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return `${day} at ${time} (${f.timezone.split("/").pop().replace("_", " ")} time)`;
}

function Meetup({ post, onChange }) {
  const m = post.meetup;
  const [attendees, setAttendees] = useState(null);
  const [update, setUpdate] = useState("");
  const [error, setError] = useState("");

  const act = async (fn) => {
    setError("");
    try {
      await fn();
      onChange();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section className="card stack">
      {m.cancelled && <p className="notice notice-error">Cancelled by the host. {m.cancelled.reason}</p>}
      <p style={{ margin: 0 }}><strong>{when(post.fields)}</strong></p>
      <p style={{ margin: 0 }}>{post.fields.general_location}</p>
      <p className="small muted" style={{ margin: 0 }}>Hosted by {post.author.business_name} · {m.rsvp.going} going · {m.rsvp.maybe} maybe</p>
      {!m.cancelled && !post.mine && (
        <div className="tabs" role="group" aria-label="Your RSVP" style={{ margin: 0 }}>
          {Object.entries(RSVP).map(([k, v]) => (
            <button key={k} type="button" aria-pressed={m.rsvp.mine === k} onClick={() => act(() => api(`/posts/${post.id}/rsvp`, { method: "PUT", body: { response: k } }))}>{v}</button>
          ))}
        </div>
      )}
      <button type="button" className="linklike small" style={{ justifySelf: "start" }} onClick={() => api(`/posts/${post.id}/attendees`).then(setAttendees)}>Who's coming?</button>
      {attendees && <p className="small" style={{ margin: 0 }}>{attendees.length ? attendees.map((a) => `${a.member.business_name}${a.response === "maybe" ? " (maybe)" : ""}`).join(", ") : "No one yet."}</p>}
      {m.updates.length > 0 && (
        <div>
          <h3 style={{ margin: "4px 0" }}>Updates from the host</h3>
          {m.updates.map((u) => <p key={u.at} className="small" style={{ margin: "4px 0" }}>{u.text} <span className="muted">· {new Date(u.at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span></p>)}
        </div>
      )}
      {post.mine && !m.cancelled && (
        <div className="stack" style={{ gap: 8 }}>
          <Field label="Post an update" hint="Everyone who said going or maybe is notified in Trade Circle.">
            <textarea rows={2} maxLength={1000} value={update} onChange={(e) => setUpdate(e.target.value)} />
          </Field>
          <span className="row">
            <button type="button" className="btn btn-small" disabled={!update.trim()} onClick={() => act(async () => { await api(`/posts/${post.id}/updates`, { method: "POST", body: { text: update } }); setUpdate(""); })}>Post update</button>
            <button type="button" className="btn btn-small btn-danger" disabled={!update.trim()} onClick={() => window.confirm("Cancel this meetup?") && act(async () => { await api(`/posts/${post.id}/cancel`, { method: "POST", body: { text: update } }); setUpdate(""); })}>Cancel meetup (with this note)</button>
          </span>
        </div>
      )}
      <Notice error={error} />
    </section>
  );
}

export default function PostDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [post, setPost] = useState(null);
  const [reply, setReply] = useState("");
  const [error, setError] = useState("");

  const load = () => api(`/posts/${id}`).then(setPost).catch((err) => setError(err.message));
  useEffect(() => {
    load();
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const send = async (event) => {
    event.preventDefault();
    try {
      await api(`/posts/${id}/comments`, { method: "POST", body: { body: reply } });
      setReply("");
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const removeComment = async (c) => {
    await api(`/comments/${c.id}`, { method: "DELETE" });
    load();
  };

  const removePost = async () => {
    if (!window.confirm("Delete this post?")) return;
    await api(`/posts/${id}`, { method: "DELETE" });
    navigate(-1);
  };

  if (!post) return error ? <Notice error={error} /> : <p className="loading">Loading…</p>;
  const isOpinion = ["supplier_review", "equipment", "spot"].includes(post.kind);

  return (
    <>
      <p className="small"><button type="button" className="linklike small" onClick={() => navigate(-1)}>← Back</button></p>
      <article className="card">
        <PostBadges post={post} />
        <h1 style={{ fontSize: "1.3rem" }}>{post.title || "Untitled"}</h1>
        <Author author={post.author} when={post.published_at || post.created_at} />
        {post.status !== "published" && <p className="notice notice-error">{post.status === "hidden" ? "A moderator has hidden this post." : "Draft: only you can see this."}</p>}
        {isOpinion && <p className="opinion-note">A member's own experience and opinion, not a fact checked by Trade Circle.</p>}
        <PostBody post={post} />
        <div className="row" style={{ marginTop: 10 }}>
          {!post.mine && <MessageRequest member={post.author} context="post" postId={post.id} />}
          {post.mine ? (
            <>
              {["project", "lesson"].includes(post.kind) && <Link className="btn btn-small" to={`/share/${post.kind}/${post.id}`}>Edit</Link>}
              {post.kind === "opening" && (
                <button type="button" className="btn btn-small" onClick={() => api(`/posts/${post.id}`, { method: "PATCH", body: { fields: { filled: !post.fields.filled } } }).then(load, (err) => setError(err.message))}>
                  {post.fields.filled ? "Reopen" : "Mark filled"}
                </button>
              )}
              <button type="button" className="btn btn-small btn-danger" onClick={removePost}>Delete</button>
            </>
          ) : (
            <ReportButton targetType="post" targetId={post.id} />
          )}
        </div>
      </article>
      {post.kind === "meetup" && post.meetup && <Meetup post={post} onChange={load} />}

      {post.status === "published" && (
        <section className="stack">
          <h2 style={{ margin: 0 }}>Replies ({post.comments.length})</h2>
          <ul className="items">
            {post.comments.map((c) => (
              <li key={c.id} className="card" style={{ margin: 0 }}>
                <p className="item-message" style={{ marginTop: 0 }}>{c.body}</p>
                <div className="row-between">
                  <Author author={c.author} when={c.created_at} />
                  {c.mine ? <button type="button" className="linklike small" onClick={() => removeComment(c)}>Delete</button> : <ReportButton targetType="comment" targetId={c.id} />}
                </div>
              </li>
            ))}
          </ul>
          <form className="stack" onSubmit={send}>
            <textarea aria-label="Your reply" required maxLength={4000} value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Add a reply" />
            <Notice error={error} />
            <button className="btn btn-primary">Reply</button>
          </form>
        </section>
      )}
    </>
  );
}
