import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, label, shortDate } from "../api.js";
import { PhotoPicker, PRIVACY_REMINDER } from "../components/Community.jsx";
import { DictateButton } from "../components/Dictation.jsx";
import { Field, Notice } from "../components/Form.jsx";
import { PostBody } from "./PostDetail.jsx";

// One short question at a time. Every step can be skipped.
export const FLOWS = {
  project: {
    name: "Project walkthrough",
    steps: [
      { key: "job", q: "What was the job?", hint: "A sentence or two is plenty." },
      { photos: "before", q: "Do you have before photos?" },
      { key: "challenge", q: "What challenge came up?" },
      { key: "handled", q: "How did you handle it?" },
      { photos: "after", q: "Do you have finished photos?" },
      { key: "learned", q: "What did you learn, or what would you change?" },
    ],
  },
  lesson: {
    name: "Lesson from the job",
    steps: [
      { key: "what_happened", q: "What happened?" },
      { key: "outcome", q: "What worked, or what went wrong?" },
      { key: "resolution", q: "How was it resolved?" },
      { key: "tip", q: "What would help another contractor?" },
      { photos: "", q: "Any photos? (optional)" },
    ],
  },
};

const backupKey = (kind, id) => `tc-draft-${kind}-${id || "new"}`;
const backup = {
  read(kind, id) {
    try {
      return JSON.parse(localStorage.getItem(backupKey(kind, id)));
    } catch {
      return null;
    }
  },
  write(kind, id, data) {
    try {
      localStorage.setItem(backupKey(kind, id), JSON.stringify(data));
    } catch {
      /* storage unavailable: the server copy is still saved */
    }
  },
  clear(kind, id) {
    try {
      localStorage.removeItem(backupKey(kind, id));
    } catch {
      /* ignore */
    }
  },
};

// A title made from the member's own first answer, which they can change. Never invented.
const titleFrom = (text) => {
  const first = (text || "").split(/(?<=[.!?])\s|\n/)[0].trim();
  return first.length > 80 ? `${first.slice(0, 77).trimEnd()}…` : first;
};

export function ShareChooser() {
  return (
    <>
      <h1>Share with the community</h1>
      <div className="choice-list">
        <Link className="choice" to="/share/project"><strong>Share a project</strong><span className="small muted">A few short questions about a job, with before and after photos. Type or talk.</span></Link>
        <Link className="choice" to="/share/lesson"><strong>Share a quick lesson</strong><span className="small muted">Something that happened on the job and what would help someone else.</span></Link>
        <Link className="choice" to="/share/equipment"><strong>Equipment</strong><span className="small muted">Ask about a tool or share how one has held up.</span></Link>
        <Link className="choice" to="/share/meetup"><strong>Local meetup</strong><span className="small muted">Post a simple get-together for contractors near you.</span></Link>
        <Link className="choice" to="/share/opening"><strong>Job opening</strong><span className="small muted">Hiring? Post a position for tradespeople near you.</span></Link>
        <Link className="choice" to="/share/spot"><strong>Suggest a spot or deal</strong><span className="small muted">A lunch place, supply-house breakfast or deal other contractors would like.</span></Link>
        <Link className="choice" to="/supplies"><strong>Supplies question</strong><span className="small muted">Ask where to find materials or share a supplier experience.</span></Link>
      </div>
    </>
  );
}

export default function GuidedPost() {
  const { kind, id } = useParams();
  const flow = FLOWS[kind];
  const navigate = useNavigate();
  const total = flow.steps.length;

  const [postId, setPostId] = useState(id || null);
  const [loaded, setLoaded] = useState(!id);
  const [drafts, setDrafts] = useState(null);
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState({});
  const [photos, setPhotos] = useState([]);
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState([]);
  const [featured, setFeatured] = useState(false);
  const [trades, setTrades] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState("");
  const [notice, setNotice] = useState({});
  const [preview, setPreview] = useState(false);
  const saving = useRef(null);
  // Set when this screen created the draft, so the address change doesn't reload over new typing.
  const createdHere = useRef(null);

  useEffect(() => {
    api("/community/meta").then((m) => setTrades(m.trades)).catch(() => {});
  }, []);

  const apply = useCallback((post, local) => {
    const fields = { ...(post?.fields || {}), ...(local?.answers || {}) };
    setAnswers(Object.fromEntries(flow.steps.filter((s) => s.key).map((s) => [s.key, fields[s.key] || ""])));
    setPhotos(local?.photos || post?.photos || []);
    setTitle(local?.title ?? post?.title ?? "");
    setTags(local?.tags || post?.trade_tags || []);
    setFeatured(local?.featured ?? post?.featured ?? false);
    setStep(Math.min(local?.step ?? fields.step ?? 0, total));
  }, [flow, total]);

  // Opening an existing draft: load it, plus anything saved on this phone that didn't reach the server.
  useEffect(() => {
    if (id && createdHere.current === id) return;
    if (!id) {
      api(`/posts/mine?kind=${kind}&post_status=draft`).then(setDrafts).catch(() => setDrafts([]));
      const local = backup.read(kind, null);
      if (local) {
        apply(null, local);
        setDirty(true);
        setNotice({ ok: "We recovered answers that hadn't been saved yet." });
      }
      return;
    }
    api(`/posts/${id}`)
      .then((post) => {
        const local = backup.read(kind, id);
        apply(post, local);
        if (local) {
          setDirty(true);
          setNotice({ ok: "We recovered changes that hadn't been saved yet." });
        }
        setLoaded(true);
      })
      .catch((err) => setNotice({ error: err.message }));
  }, [id, kind, apply]);

  const payload = () => ({
    title: title.trim(),
    trade_tags: tags,
    featured,
    photos: photos.map((p) => ({ id: p.id, group: p.group || "" })),
    fields: { ...answers, step },
  });

  const save = useCallback(async () => {
    if (saving.current) return saving.current;
    const run = (async () => {
      setSaveState("Saving…");
      backup.write(kind, postId, { answers, photos, title, tags, featured, step });
      try {
        if (!postId) {
          const created = await api("/posts", { method: "POST", body: { kind, ...payload() } });
          backup.clear(kind, null);
          createdHere.current = created.id;
          setPostId(created.id);
          navigate(`/share/${kind}/${created.id}`, { replace: true });
        } else {
          await api(`/posts/${postId}`, { method: "PATCH", body: payload() });
          backup.clear(kind, postId);
        }
        setDirty(false);
        setSaveState("Draft saved");
      } catch (err) {
        setSaveState("Not saved yet. Your answers are kept on this phone.");
        throw err;
      } finally {
        saving.current = null;
      }
    })();
    saving.current = run;
    return run;
  }, [answers, photos, title, tags, featured, step, postId, kind]); // eslint-disable-line react-hooks/exhaustive-deps

  // Autosave about a second after the last change. A copy is kept on the phone right away,
  // so nothing is lost if the person leaves before the save goes through.
  useEffect(() => {
    if (!dirty || !loaded) return undefined;
    backup.write(kind, postId, { answers, photos, title, tags, featured, step });
    setSaveState("Unsaved changes…");
    const timer = setTimeout(() => save().catch(() => {}), 1000);
    return () => clearTimeout(timer);
  }, [dirty, loaded, save]); // eslint-disable-line react-hooks/exhaustive-deps

  // Save straight away when leaving this screen or switching away from the app.
  const pending = useRef({ dirty, save });
  pending.current = { dirty, save };
  useEffect(() => {
    const flush = () => {
      if (pending.current.dirty) pending.current.save().catch(() => {});
    };
    const onHide = () => document.visibilityState === "hidden" && flush();
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", flush);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", flush);
      flush();
    };
  }, []);

  const change = (fn) => (...args) => {
    fn(...args);
    setDirty(true);
  };
  const setAnswer = change((key, value) => setAnswers((a) => ({ ...a, [key]: value })));
  const go = change((to) => {
    setStep(to);
    setPreview(false);
  });

  if (!flow) return <Notice error="Unknown post type." />;
  if (!loaded) return notice.error ? <Notice error={notice.error} /> : <p className="loading">Loading…</p>;

  if (!id && drafts && drafts.length > 0 && !dirty) {
    const d = drafts[0];
    return (
      <>
        <h1>{flow.name}</h1>
        <section className="card stack">
          <p style={{ margin: 0 }}>
            You have a draft from {shortDate(d.updated_at)}: <strong>{d.title || titleFrom(Object.values(d.fields).find((v) => typeof v === "string" && v)) || "Untitled"}</strong>
          </p>
          <div className="row">
            <Link className="btn btn-primary" to={`/share/${kind}/${d.id}`}>Continue draft</Link>
            <button type="button" className="btn" onClick={() => setDrafts([])}>Start a new one</button>
          </div>
        </section>
      </>
    );
  }

  const current = flow.steps[step];
  const atReview = step >= total;
  const firstAnswer = flow.steps.filter((s) => s.key).map((s) => answers[s.key]).find(Boolean);

  const finalTitle = title.trim() || titleFrom(firstAnswer);

  const publish = async () => {
    try {
      await save();
      // Saved again with the title shown in the preview, then published as one explicit step.
      await api(`/posts/${postId}`, { method: "PATCH", body: { ...payload(), title: finalTitle } });
      const post = await api(`/posts/${postId}/publish`, { method: "POST" });
      backup.clear(kind, postId);
      navigate(`/posts/${post.id}`, { replace: true });
    } catch (err) {
      setNotice({ error: err.message });
    }
  };

  return (
    <>
      <div className="row-between">
        <h1 style={{ marginBottom: 6 }}>{flow.name}</h1>
        <span className="save-state" aria-live="polite">{saveState}</span>
      </div>
      <div className="progress-steps" aria-label={`Step ${Math.min(step + 1, total + 1)} of ${total + 1}`}>
        {[...flow.steps, "review"].map((_, i) => <span key={i} className={i <= step ? "done" : ""} />)}
      </div>
      <Notice error={notice.error} ok={notice.ok} />

      {!atReview && (
        <section className="card stack">
          <h2 className="question">{current.q}</h2>
          {current.key ? (
            <>
              <textarea
                aria-label={current.q}
                rows={5}
                maxLength={2000}
                value={answers[current.key] || ""}
                onChange={(e) => setAnswer(current.key, e.target.value)}
                placeholder="Type here, or tap to talk"
              />
              {current.hint && <span className="field-hint">{current.hint}</span>}
              <DictateButton key={step} onText={(text) => setAnswer(current.key, `${(answers[current.key] || "").trimEnd()} ${text}`.trim())} />
            </>
          ) : (
            <PhotoPicker photos={photos} onChange={change(setPhotos)} group={current.photos} label="Add photos" hint={PRIVACY_REMINDER} videos />
          )}
          <div className="step-actions">
            <button type="button" className="btn" onClick={() => go(step - 1)} disabled={step === 0}>Back</button>
            <button type="button" className="linklike small" onClick={() => save().then(() => setNotice({ ok: "Draft saved. You can come back to it anytime from Share." })).catch(() => {})}>Save draft</button>
            {current.key && !answers[current.key] ? (
              <button type="button" className="btn" onClick={() => go(step + 1)}>Skip</button>
            ) : current.photos !== undefined && !photos.some((p) => (p.group || "") === current.photos) ? (
              <button type="button" className="btn" onClick={() => go(step + 1)}>Skip</button>
            ) : (
              <button type="button" className="btn btn-primary" onClick={() => go(step + 1)}>Next</button>
            )}
          </div>
        </section>
      )}

      {atReview && !preview && (
        <section className="card stack">
          <h2 style={{ margin: 0 }}>Check your post</h2>
          <p className="small muted" style={{ margin: 0 }}>Your answers, arranged under headings. Change anything you like. Nothing is posted until you tap Publish.</p>
          <Field label="Title" hint={!title && firstAnswer ? "Suggested from your first answer." : undefined}>
            <input maxLength={140} value={title} placeholder={titleFrom(firstAnswer)} onChange={(e) => change(setTitle)(e.target.value)} onFocus={() => !title && firstAnswer && change(setTitle)(titleFrom(firstAnswer))} />
          </Field>
          {flow.steps.map((s, i) =>
            s.key ? (
              <Field key={s.key} label={s.q}>
                <textarea rows={3} maxLength={2000} value={answers[s.key] || ""} onChange={(e) => setAnswer(s.key, e.target.value)} />
              </Field>
            ) : (
              <div key={`photos-${i}`}>
                <span className="field-label">{s.q}</span>
                <PhotoPicker photos={photos} onChange={change(setPhotos)} group={s.photos} label="Add photos" videos />
              </div>
            ),
          )}
          <fieldset className="row" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="field-label" style={{ marginBottom: 4 }}>Trades (up to 5)</legend>
            {trades.map((t) => (
              <label key={t} className="check" style={{ alignItems: "center" }}>
                <input type="checkbox" checked={tags.includes(t)} disabled={!tags.includes(t) && tags.length >= 5} onChange={() => change(setTags)(tags.includes(t) ? tags.filter((x) => x !== t) : [...tags, t])} />
                <span className="small">{label(t)}</span>
              </label>
            ))}
          </fieldset>
          {kind === "project" && (
            <label className="check">
              <input type="checkbox" checked={featured} onChange={(e) => change(setFeatured)(e.target.checked)} />
              <span>Feature this on my full profile as portfolio content</span>
            </label>
          )}
          <p className="notice notice-error small" style={{ fontWeight: 500 }}>{PRIVACY_REMINDER}</p>
          <div className="step-actions">
            <button type="button" className="btn" onClick={() => go(step - 1)}>Back</button>
            <span />
            <button type="button" className="btn btn-primary" onClick={() => save().then(() => setPreview(true)).catch(() => {})}>Preview</button>
          </div>
        </section>
      )}

      {atReview && preview && (
        <>
          <p className="small muted">Preview: this is how your post will look.</p>
          <article className="card">
            <h1 style={{ fontSize: "1.3rem" }}>{finalTitle || "Untitled"}</h1>
            <PostBody post={{ kind, body: "", fields: answers, photos, photos_hidden: false }} />
            {featured && <p className="small muted">Will be featured on your full profile.</p>}
          </article>
          <div className="step-actions">
            <button type="button" className="btn" onClick={() => setPreview(false)}>Keep editing</button>
            <span />
            <button type="button" className="btn btn-primary" onClick={publish}>Publish</button>
          </div>
        </>
      )}
    </>
  );
}
