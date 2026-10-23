import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Notice } from "./Form.jsx";

// A YouTube integration: members connect their own channel and choose, clip by
// clip, what posts to it. Nothing posts without the confirm step below.

const NOTICES = {
  connected: { ok: "Your YouTube channel is connected." },
  denied: { error: "That connection wasn't finished at Google. Nothing was connected." },
  error: { error: "Google didn't complete the connection. Try again, or reconnect from here." },
};

export function YouTubeConnect({ notice = "" }) {
  const [yt, setYt] = useState(null);
  const [status, setStatus] = useState(NOTICES[notice] || {});

  useEffect(() => {
    api("/youtube/status").then(setYt).catch((err) => setStatus({ error: err.message }));
  }, []);

  const connect = async () => {
    try {
      const { url } = await api("/youtube/connect");
      window.location.assign(url);
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  const disconnect = async () => {
    try {
      await api("/youtube/connect", { method: "DELETE" });
      setYt({ ...yt, connected: false, channel: null, needs_reconnect: false });
      setStatus({ ok: "Disconnected. The stored sign-in is deleted, here and at Google." });
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  if (!yt) return null;
  return (
    <section className="card stack">
      <h2>YouTube</h2>
      <Notice error={status.error} ok={status.ok} />
      {!yt.configured && (
        <p className="muted" style={{ margin: 0 }}>
          Posting clips to YouTube isn't switched on for this site yet. When it is, you'll be able to connect your channel here and send project clips straight to it.
        </p>
      )}
      {yt.configured && !yt.plan_includes && (
        <p className="muted" style={{ margin: 0 }}>
          Posting clips to your YouTube channel comes with the Starter and Full plans. <Link to="/plan">See the plans</Link>
        </p>
      )}
      {yt.configured && yt.plan_includes && !yt.connected && (
        <>
          <p className="small muted" style={{ margin: 0 }}>
            Connect your channel once, then any project clip can also post to it — you confirm the title, description and visibility every time. Trade Circle stores only a sign-in token from Google, never your password, and you can disconnect here whenever you like.
          </p>
          <span className="row">
            <button type="button" className="btn btn-small" onClick={connect}>Connect your YouTube channel</button>
          </span>
        </>
      )}
      {yt.configured && yt.plan_includes && yt.connected && (
        <>
          <p style={{ margin: 0 }}>
            Connected: <strong>{yt.channel.title}</strong>
          </p>
          {yt.needs_reconnect && (
            <p className="small" style={{ margin: 0 }}>YouTube stopped accepting the stored sign-in. Disconnect and connect again to keep posting.</p>
          )}
          <p className="small muted" style={{ margin: 0 }}>
            {yt.uploads_today} of {yt.daily_cap} posts used today. The daily limit resets at midnight — anything past it waits and posts tomorrow.
          </p>
          <span className="row">
            <button type="button" className="btn btn-small" onClick={disconnect}>Disconnect</button>
          </span>
        </>
      )}
    </section>
  );
}

const POST_STATUS = {
  queued: "On its way to YouTube — it posts in the background, usually within a few minutes.",
  posting: "Posting to YouTube now…",
};

// Sits with a clip in the editor: the opt-in, the confirm step, and afterwards the post's status.
export function YouTubeClipPanel({ clip }) {
  const [yt, setYt] = useState(null);
  const [post, setPost] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [optIn, setOptIn] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState("unlisted");
  const [status, setStatus] = useState({});

  useEffect(() => {
    Promise.all([api("/youtube/status"), api("/youtube/posts")])
      .then(([s, posts]) => {
        setYt(s);
        setPost(posts.find((p) => p.clip_id === clip.id) || null);
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, [clip.id]);

  const send = async () => {
    try {
      await api("/youtube/posts", { method: "POST", body: { clip_id: clip.id, title, description, visibility } });
      setPost({ clip_id: clip.id, status: "queued", title, visibility });
      setStatus({ ok: "Queued. It'll post to your channel in the background." });
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  if (!loaded || !yt || !yt.configured || !yt.plan_includes) return null;
  if (!yt.connected) {
    return <p className="small muted" style={{ margin: 0 }}>Want this clip on YouTube too? Connect your channel under Settings → YouTube, then post clips from here.</p>;
  }
  if (post && post.status !== "failed") {
    return (
      <div className="stack" style={{ gap: 4 }}>
        {post.status === "posted" ? (
          <p className="small" style={{ margin: 0 }}>
            On YouTube: <a href={post.url} target="_blank" rel="noreferrer">{post.title}</a> <span className="muted">({post.visibility})</span>
          </p>
        ) : (
          <p className="small" style={{ margin: 0 }}>{POST_STATUS[post.status] || post.status}</p>
        )}
      </div>
    );
  }
  return (
    <div className="stack" style={{ gap: 8 }}>
      {post?.status === "failed" && (
        <p className="small" style={{ margin: 0 }}>That post didn't go through: {post.error || "YouTube refused it."} You can fix the details below and try again.</p>
      )}
      <label className="check" style={{ alignItems: "center" }}>
        <input type="checkbox" checked={optIn} onChange={(e) => setOptIn(e.target.checked)} />
        <span className="small">Also post this clip to my YouTube channel ({yt.channel.title})</span>
      </label>
      {optIn && (
        <div className="stack" style={{ gap: 8 }}>
          <label className="field">
            <span className="field-label">YouTube title</span>
            <input aria-label="YouTube title" maxLength={100} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What should the video be called?" />
          </label>
          <label className="field">
            <span className="field-label">Description</span>
            <textarea aria-label="YouTube description" rows={3} maxLength={5000} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional — what the clip shows, where, and how to reach you." />
          </label>
          <label className="field">
            <span className="field-label">Who can watch it</span>
            <select aria-label="YouTube visibility" value={visibility} onChange={(e) => setVisibility(e.target.value)}>
              <option value="unlisted">Unlisted — anyone with the link</option>
              <option value="public">Public — anyone can find it</option>
              <option value="private">Private — only you</option>
            </select>
          </label>
          <Notice error={status.error} ok={status.ok} />
          <span className="row">
            <button type="button" className="btn btn-small" disabled={!title.trim()} onClick={send}>Post to YouTube</button>
          </span>
          <p className="small muted" style={{ margin: 0 }}>Nothing posts until you press that button. It goes up in the background; the clip stays here either way.</p>
        </div>
      )}
    </div>
  );
}
