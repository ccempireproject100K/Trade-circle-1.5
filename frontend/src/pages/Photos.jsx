import { useEffect, useRef, useState } from "react";
import { api, uploadPhoto } from "../api.js";
import { Field, Notice } from "../components/Form.jsx";
import SortableList from "../components/SortableList.jsx";

function Caption({ photo, onSaved }) {
  const [value, setValue] = useState(photo.caption || "");
  const [state, setState] = useState("");

  const save = async () => {
    if (value === (photo.caption || "")) return;
    setState("Saving…");
    try {
      await api(`/me/portfolio/${photo.id}`, { method: "PATCH", body: { caption: value } });
      onSaved({ ...photo, caption: value });
      setState("Saved");
    } catch (err) {
      setState(err.message);
    }
  };

  return (
    <span>
      <input
        aria-label="Caption"
        maxLength={280}
        value={value}
        placeholder="Add a caption"
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        style={{ minHeight: 36, padding: "6px 10px" }}
      />
      {state && <span className="field-hint">{state}</span>}
    </span>
  );
}

function AddByLink({ onAdded }) {
  const [form, setForm] = useState({ image_url: "", caption: "" });
  const [error, setError] = useState("");

  const add = async (event) => {
    event.preventDefault();
    try {
      onAdded(await api("/me/portfolio", { method: "POST", body: form }));
      setForm({ image_url: "", caption: "" });
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <details>
      <summary className="small muted" style={{ cursor: "pointer" }}>Or add a photo by link</summary>
      <form className="stack" style={{ marginTop: 10 }} onSubmit={add}>
        <Field label="Photo link"><input type="url" required value={form.image_url} onChange={(e) => setForm({ ...form, image_url: e.target.value })} placeholder="https://" /></Field>
        <Field label="Caption"><input maxLength={280} value={form.caption} onChange={(e) => setForm({ ...form, caption: e.target.value })} /></Field>
        <Notice error={error} />
        <button className="btn">Add by link</button>
      </form>
    </details>
  );
}

export default function Photos() {
  const [photos, setPhotos] = useState(null);
  const [queue, setQueue] = useState([]); // uploads in progress: { id, name, progress, error }
  const [status, setStatus] = useState({});
  const picker = useRef(null);

  useEffect(() => {
    api("/me/portfolio").then(setPhotos).catch((err) => setStatus({ error: err.message }));
  }, []);

  const setUpload = (id, changes) => setQueue((q) => q.map((u) => (u.id === id ? { ...u, ...changes } : u)));

  const choose = async (event) => {
    const files = [...event.target.files];
    event.target.value = "";
    if (!files.length) return;
    const batch = files.map((file, i) => ({ id: `${Date.now()}-${i}`, file, name: file.name, progress: 0, error: "" }));
    setQueue((q) => [...q, ...batch]);
    setStatus({});
    let added = 0;
    // One at a time keeps phones on slow connections responsive.
    for (const upload of batch) {
      try {
        const photo = await uploadPhoto(upload.file, "", (p) => setUpload(upload.id, { progress: p }));
        setPhotos((list) => [...list, photo]);
        setQueue((q) => q.filter((u) => u.id !== upload.id));
        added += 1;
      } catch (err) {
        setUpload(upload.id, { error: err.message });
      }
    }
    if (added) setStatus({ ok: `${added} ${added === 1 ? "photo" : "photos"} added. Add captions below.` });
  };

  const reorder = async (next) => {
    const previous = photos;
    setPhotos(next);
    try {
      await api("/me/portfolio/order", { method: "PUT", body: { ids: next.map((p) => p.id) } });
      setStatus({ ok: "Order saved." });
    } catch (err) {
      setPhotos(previous);
      setStatus({ error: err.message });
    }
  };

  const remove = async (photo) => {
    if (!window.confirm("Delete this photo?")) return;
    try {
      await api(`/me/portfolio/${photo.id}`, { method: "DELETE" });
      setPhotos(photos.filter((p) => p.id !== photo.id));
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  if (photos === null) return status.error ? <Notice error={status.error} /> : <p className="loading">Loading…</p>;

  return (
    <>
      <h1>Photos</h1>
      <section className="card stack">
        <input ref={picker} type="file" accept="image/*" multiple hidden onChange={choose} data-testid="photo-picker" />
        <button type="button" className="btn btn-primary" style={{ minHeight: 56, fontSize: "1.05rem" }} onClick={() => picker.current.click()}>
          Add photos
        </button>
        <p className="small muted" style={{ margin: 0 }}>
          Take a photo or pick from your library. You can choose several at once. We remove location data from every photo before it goes
          on your page.
        </p>
        {queue.length > 0 && (
          <ul className="items" aria-label="Uploads">
            {queue.map((u) => (
              <li key={u.id} className="stack" style={{ gap: 4 }}>
                <span className="small row-between">
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "70%" }}>{u.name}</span>
                  <span className="muted">{u.error ? "Not added" : `${Math.round(u.progress * 100)}%`}</span>
                </span>
                {u.error ? (
                  <span className="row-between">
                    <span className="notice notice-error small" style={{ flex: 1 }}>{u.error}</span>
                    <button type="button" className="btn btn-small" onClick={() => setQueue((q) => q.filter((x) => x.id !== u.id))}>Dismiss</button>
                  </span>
                ) : (
                  <progress max="1" value={u.progress} style={{ width: "100%" }} />
                )}
              </li>
            ))}
          </ul>
        )}
        <Notice error={status.error} ok={status.ok} />
        <AddByLink onAdded={(photo) => setPhotos([...photos, photo])} />
      </section>

      <section className="card stack">
        <h2>Your photos ({photos.length})</h2>
        <p className="small muted" style={{ margin: 0 }}>The first 6 show on your landing page. Drag to reorder.</p>
        {photos.length === 0 ? (
          <p className="empty">No photos yet. Your best recent jobs make the strongest first impression.</p>
        ) : (
          <SortableList
            label="Photo order"
            items={photos}
            getKey={(p) => p.id}
            onReorder={reorder}
            renderItem={(p) => (
              <span className="photo-row">
                <img className="thumb" src={p.thumb_url || p.image_url} alt="" />
                <span className="photo-meta">
                  <Caption photo={p} onSaved={(saved) => setPhotos((list) => list.map((x) => (x.id === saved.id ? saved : x)))} />
                  <button type="button" className="link-danger" onClick={() => remove(p)}>Delete photo</button>
                </span>
              </span>
            )}
          />
        )}
      </section>
    </>
  );
}
