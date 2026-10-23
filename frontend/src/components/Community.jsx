// Pieces shared by every community screen: post cards, reporting, photo picking.
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, label, shortDate, uploadPhoto } from "../api.js";
import { CATEGORY_NAMES, EXPERIENCE_NAMES, KIND_NAMES, REPORT_REASONS } from "../labels.js";
import { Notice } from "./Form.jsx";
import { YouTubeClipPanel } from "./YouTube.jsx";

export function Author({ author, when }) {
  return (
    <span className="small muted">
      {author.slug ? <a href={`/p/${author.slug}`} target="_blank" rel="noreferrer">{author.business_name}</a> : author.business_name}
      {author.trade && ` · ${label(author.trade)}`}
      {when && ` · ${shortDate(when)}`}
    </span>
  );
}

export function SupplierLink({ supplier }) {
  if (!supplier) return null;
  if (supplier.removed) return <span className="tag">{supplier.name}</span>;
  return <Link className="tag" to={`/supplies/${supplier.id}`}>{supplier.name}</Link>;
}

export function PostBadges({ post }) {
  const f = post.fields || {};
  return (
    <div className="badge-line">
      <span className="tag">{KIND_NAMES[post.kind] || post.kind}</span>
      {post.kind === "supplier_review" && f.experience && <span className={`tag tag-${f.experience}`}>{EXPERIENCE_NAMES[f.experience]}</span>}
      {post.category && <span className="tag">{CATEGORY_NAMES[post.category]}</span>}
      {post.trade_tags.map((t) => <span key={t} className="tag">{label(t)}</span>)}
      <SupplierLink supplier={post.supplier} />
      {post.location && (
        <span className="small muted">
          {post.location.label}
          {post.distance_miles != null && ` · ${post.distance_miles} mi`}
        </span>
      )}
    </div>
  );
}

export function PostCard({ post }) {
  const f = post.fields || {};
  return (
    <li className="card" style={{ margin: 0 }}>
      <PostBadges post={post} />
      <h3><Link to={`/posts/${post.id}`} style={{ color: "inherit" }}>{post.title || "Untitled"}</Link></h3>
      {post.body && <p className="item-message small" style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{post.body}</p>}
      {post.kind === "supplier_review" && f.topics?.length > 0 && <p className="small muted" style={{ margin: "0 0 6px" }}>About: {f.topics.map(label).join(", ")}</p>}
      {post.kind === "opening" && <p className="small" style={{ margin: "0 0 6px" }}><strong>{f.role}</strong>{f.pay && ` · ${f.pay}`}{f.apply_by && ` · apply by ${f.apply_by}`}</p>}
      {post.kind === "spot" && <p className="small" style={{ margin: "0 0 6px" }}><strong>{f.place}</strong> · {f.suggestion === "deal" ? "Deal" : "Spot"}{f.connection !== "none" && " · connection disclosed"}</p>}
      {post.kind === "supplier_suggestion" && <p className="small" style={{ margin: "0 0 6px" }}>Suggested: <strong>{f.suggested_name}</strong>{f.listing_added && " · now in the directory"}</p>}
      {post.photos.length > 0 && (
        <div className="post-photos">
          {post.photos.slice(0, 3).map((p) => <img key={p.id} src={p.thumb_url} alt="" loading="lazy" />)}
        </div>
      )}
      <div className="row-between">
        <Author author={post.author} when={post.published_at || post.created_at} />
        <Link className="small" to={`/posts/${post.id}`}>{post.comment_count} {post.comment_count === 1 ? "reply" : "replies"}</Link>
      </div>
    </li>
  );
}

export function ReportButton({ targetType, targetId, label: text = "Report" }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("spam");
  const [note, setNote] = useState("");
  const [status, setStatus] = useState({});

  const send = async () => {
    try {
      await api("/reports", { method: "POST", body: { target_type: targetType, target_id: targetId, reason, note } });
      setStatus({ ok: "Thanks. A moderator will look at it." });
      setOpen(false);
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  if (status.ok) return <span className="small muted">{status.ok}</span>;
  if (!open) return <button type="button" className="linklike small" onClick={() => setOpen(true)}>{text}</button>;
  return (
    <div className="stack" style={{ gap: 8 }}>
      <select aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)}>
        {Object.entries(REPORT_REASONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <input aria-label="Details (optional)" placeholder="Details (optional)" maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      <Notice error={status.error} />
      <span className="row">
        <button type="button" className="btn btn-small" onClick={send}>Send report</button>
        <button type="button" className="linklike small" onClick={() => setOpen(false)}>Cancel</button>
      </span>
    </div>
  );
}

// Preview a clip before publishing; trim the start or end, or remove the sound. Each change makes a new cleaned copy.
function ClipEditor({ clip, onReplace, onClose }) {
  const [start, setStart] = useState("0");
  const [end, setEnd] = useState(String(clip.duration || ""));
  const [mute, setMute] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const apply = async () => {
    setBusy(true);
    setError("");
    try {
      const next = await api(`/media/videos/${clip.id}/edit`, { method: "POST", body: { start: Number(start) || 0, end: end === "" ? null : Number(end), mute } });
      onReplace({ ...next, group: clip.group || "" });
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };
  return (
    <div className="card stack" style={{ gap: 8 }}>
      <video src={clip.video_url} poster={clip.thumb_url} controls playsInline preload="metadata" style={{ width: "100%", maxHeight: 320, background: "#000" }} />
      <p className="small" style={{ margin: 0 }}>
        Watch it through. If it shows faces, house numbers, street signs, plates or anything private, trim that part out or remove the clip. Blurring isn't available yet.
      </p>
      <YouTubeClipPanel clip={clip} />
      <div className="grid-2">
        <label className="field"><span className="field-label">Start at (seconds)</span><input inputMode="decimal" value={start} onChange={(e) => setStart(e.target.value)} /></label>
        <label className="field"><span className="field-label">End at (seconds)</span><input inputMode="decimal" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
      </div>
      {clip.has_audio && <label className="check" style={{ alignItems: "center" }}><input type="checkbox" checked={mute} onChange={(e) => setMute(e.target.checked)} /><span className="small">Remove the sound (for example, if someone's name is said)</span></label>}
      <Notice error={error} />
      <span className="row">
        <button type="button" className="btn btn-small" disabled={busy} onClick={apply}>{busy ? "Working…" : "Apply changes"}</button>
        <button type="button" className="linklike small" onClick={onClose}>Done</button>
      </span>
    </div>
  );
}

// Uploads photos (and, where offered, video clips) for a post as soon as they're picked, so drafts keep them.
export function PhotoPicker({ photos, onChange, group = "", label: text = "Add photos", hint, videos = false }) {
  const input = useRef(null);
  const videoInput = useRef(null);
  const [busy, setBusy] = useState(0);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null);
  const mine = photos.filter((p) => (p.group || "") === group);

  const pickVideo = async (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    setError("");
    setBusy((n) => n + 1);
    try {
      const up = await uploadPhoto(file, null, () => {}, "/media/videos");
      const clip = { ...up, group };
      onChange([...photos, clip]);
      setEditing(clip);
    } catch (err) {
      setError(`${file.name}: ${err.message}`);
    }
    setBusy((n) => n - 1);
  };

  const pick = async (event) => {
    const files = [...event.target.files];
    event.target.value = "";
    setError("");
    let next = photos;
    for (const file of files) {
      setBusy((n) => n + 1);
      try {
        const up = await uploadPhoto(file, null, () => {}, "/media/photos");
        next = [...next, { id: up.id, group, thumb_url: up.thumb_url, image_url: up.image_url }];
        onChange(next);
      } catch (err) {
        setError(`${file.name}: ${err.message}`);
      }
      setBusy((n) => n - 1);
    }
  };

  return (
    <div className="stack" style={{ gap: 8 }}>
      <input ref={input} type="file" accept="image/*" multiple hidden onChange={pick} />
      {mine.length > 0 && (
        <div className="post-photos">
          {mine.map((p) => (
            <span key={p.id} style={{ position: "relative" }}>
              {p.type === "video" ? (
                <button type="button" className="clip-thumb" aria-label="Preview and edit clip" onClick={() => setEditing(p)}><img src={p.thumb_url} alt="" /><span aria-hidden="true">▶</span></button>
              ) : (
                <img src={p.thumb_url} alt="" />
              )}
              <button type="button" className="btn btn-icon" aria-label={p.type === "video" ? "Remove clip" : "Remove photo"} style={{ position: "absolute", top: 4, right: 4, minHeight: 28, width: 28 }} onClick={() => onChange(photos.filter((x) => x.id !== p.id))}>×</button>
            </span>
          ))}
        </div>
      )}
      {editing && (
        <ClipEditor
          key={editing.id}
          clip={editing}
          onClose={() => setEditing(null)}
          onReplace={(next) => {
            onChange(photos.map((p) => (p.id === editing.id ? next : p)));
            setEditing(next);
          }}
        />
      )}
      <span className="row">
        <button type="button" className="btn" onClick={() => input.current.click()} disabled={busy > 0}>
          {busy > 0 ? "Uploading…" : text}
        </button>
        {videos && (
          <>
            <input ref={videoInput} type="file" accept="video/*" hidden onChange={pickVideo} />
            <button type="button" className="btn" onClick={() => videoInput.current.click()} disabled={busy > 0}>Add a video clip</button>
          </>
        )}
      </span>
      {videos && <span className="field-hint">Clips you already have, up to 3 minutes. Location and other hidden details are removed.</span>}
      {hint && <span className="field-hint">{hint}</span>}
      <Notice error={error} />
    </div>
  );
}

export const PRIVACY_REMINDER = "Don't include customer names, addresses, house numbers or license plates in text or photos.";
