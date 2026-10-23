import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Notice } from "./Form.jsx";

// Ask to message a member. Nothing can be sent until they accept.
export default function MessageRequest({ member, context = "general", postId = null, buttonLabel }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const send = async (event) => {
    event.preventDefault();
    try {
      setResult(await api("/messages/requests", { method: "POST", body: { to_slug: member.slug, note, context, post_id: postId } }));
    } catch (err) {
      setError(err.message);
    }
  };

  if (!member?.slug) return null;
  if (result?.conversation_id) return <Link className="btn btn-small" to={`/messages/${result.conversation_id}`}>Open conversation</Link>;
  if (result) return <p className="small muted" style={{ margin: 0 }}>Request sent. {member.business_name} needs to accept before you can message each other.</p>;
  if (!open) return <button type="button" className="btn btn-small" onClick={() => setOpen(true)}>{buttonLabel || `Message ${member.business_name}`}</button>;
  return (
    <form className="stack" style={{ gap: 8, width: "100%" }} onSubmit={send}>
      <textarea aria-label="Your message" required maxLength={1000} rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Say who you are and what you'd like to ask." />
      <p className="field-hint" style={{ margin: 0 }}>They'll see this and choose whether to accept.</p>
      <Notice error={error} />
      <span className="row">
        <button className="btn btn-primary btn-small">Send request</button>
        <button type="button" className="linklike small" onClick={() => setOpen(false)}>Cancel</button>
      </span>
    </form>
  );
}
