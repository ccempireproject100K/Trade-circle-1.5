import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, label } from "../api.js";
import { PostCard, PhotoPicker, PRIVACY_REMINDER } from "../components/Community.jsx";
import { Field, Notice } from "../components/Form.jsx";
import { CATEGORY_NAMES, savedArea } from "../labels.js";

const SUPPLY_KINDS = "supply_question,supplier_review,supplier_suggestion";
const TOPICS = ["price", "quality", "availability", "delivery", "service", "returns"];

const query = (params) =>
  new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v !== false && v != null))).toString();

function CategorySelect({ value, onChange, any = "All categories", id }) {
  return (
    <select id={id} aria-label="Category" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{any}</option>
      {Object.entries(CATEGORY_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
    </select>
  );
}

// Ask where to find something, recommend a supplier, or suggest one for the directory.
function Compose({ mode, area, suppliers, onPosted, onClose, supplierId = "" }) {
  const [form, setForm] = useState({ title: "", body: "", category: "", location: area.near, supplier_id: supplierId, experience: "", topics: [], suggested_name: "", suggested_website: "" });
  const [photos, setPhotos] = useState([]);
  const [status, setStatus] = useState({});
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    const base = { title: form.title, body: form.body, category: form.category || null, location: form.location, photos: photos.map((p) => ({ id: p.id })), trade_tags: [] };
    let body;
    if (mode === "ask") body = { ...base, kind: "supply_question" };
    else if (mode === "recommend") body = { ...base, kind: "supplier_review", supplier_id: form.supplier_id || null, fields: { experience: form.experience, topics: form.topics } };
    else body = { ...base, kind: "supplier_suggestion", fields: { suggested_name: form.suggested_name, suggested_website: form.suggested_website, suggested_location: form.location } };
    try {
      const post = await api("/posts", { method: "POST", body });
      onPosted(post);
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  const heading = { ask: "Ask the community", recommend: "Share a supplier experience", suggest: "Suggest a supplier for the directory" }[mode];

  return (
    <form className="card stack" onSubmit={submit}>
      <div className="row-between">
        <h2 style={{ margin: 0 }}>{heading}</h2>
        <button type="button" className="linklike" onClick={onClose}>Close</button>
      </div>
      {mode === "ask" && (
        <Field label="Your question">
          <input required maxLength={140} value={form.title} onChange={set("title")} placeholder="Who has 200A panels in stock near Round Rock?" />
        </Field>
      )}
      {mode === "recommend" && (
        <>
          <Field label="Supplier" hint="Not listed? Suggest it for the directory instead.">
            <select required value={form.supplier_id} onChange={set("supplier_id")}>
              <option value="" disabled>Choose a supplier</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
          <Field label="How was it?">
            <select required value={form.experience} onChange={set("experience")}>
              <option value="" disabled>Choose one</option>
              <option value="positive">Good experience</option>
              <option value="mixed">Mixed experience</option>
              <option value="negative">Bad experience</option>
            </select>
          </Field>
          <fieldset className="row" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="field-label" style={{ marginBottom: 4 }}>About (optional)</legend>
            {TOPICS.map((t) => (
              <label key={t} className="check" style={{ alignItems: "center" }}>
                <input type="checkbox" checked={form.topics.includes(t)} onChange={() => setForm({ ...form, topics: form.topics.includes(t) ? form.topics.filter((x) => x !== t) : [...form.topics, t] })} />
                <span className="small">{label(t)}</span>
              </label>
            ))}
          </fieldset>
          <Field label="Headline"><input required maxLength={140} value={form.title} onChange={set("title")} placeholder="Next-morning delivery to the jobsite" /></Field>
        </>
      )}
      {mode === "suggest" && (
        <>
          <Field label="Supplier name"><input required maxLength={120} value={form.suggested_name} onChange={set("suggested_name")} /></Field>
          <Field label="Website (optional)"><input type="url" maxLength={200} value={form.suggested_website} onChange={set("suggested_website")} placeholder="https://" /></Field>
          <Field label="Headline"><input required maxLength={140} value={form.title} onChange={set("title")} placeholder="Please add this lumber yard" /></Field>
        </>
      )}
      <Field label={mode === "recommend" ? "What happened? (your firsthand experience)" : "Details"}>
        <textarea maxLength={10000} value={form.body} onChange={set("body")} />
      </Field>
      <div className="grid-2">
        <Field label="Category"><CategorySelect value={form.category} onChange={(v) => setForm({ ...form, category: v })} any="Choose (optional)" /></Field>
        <Field label="Area" hint='ZIP or "City, ST", so answers fit your area.'><input value={form.location} onChange={set("location")} placeholder="78701" /></Field>
      </div>
      <PhotoPicker photos={photos} onChange={setPhotos} label="Add photos (optional)" hint={PRIVACY_REMINDER} />
      {mode === "recommend" && <p className="small muted" style={{ margin: 0 }}>Your post is shown as your opinion, not as a fact checked by Trade Circle. Good and bad experiences are both welcome; keep it honest and about your own experience.</p>}
      <Notice error={status.error} />
      <button className="btn btn-primary">{mode === "ask" ? "Post question" : "Post"}</button>
    </form>
  );
}

function SupplierCard({ s }) {
  const e = s.experiences;
  return (
    <li className="card" style={{ margin: 0 }}>
      <div className="row-between">
        <h3><Link to={`/supplies/${s.id}`} style={{ color: "inherit" }}>{s.name}</Link></h3>
        <span className="small muted">Directory listing</span>
      </div>
      <p className="small" style={{ margin: "4px 0" }}>{s.offers || s.categories.map((c) => CATEGORY_NAMES[c]).join(", ")}</p>
      {s.match?.length > 0 && <p className="small" style={{ margin: "4px 0", color: "var(--accent)" }}>{s.match.join(" · ")}</p>}
      <p className="small muted" style={{ margin: 0 }}>
        {e.posts === 0 ? "No member posts yet" : `Member posts: ${e.posts} · ${e.positive} good · ${e.mixed} mixed · ${e.negative} bad`}
      </p>
    </li>
  );
}

export default function Supplies() {
  const [params] = useSearchParams();
  const [area, setArea] = useState(savedArea.get());
  const [draftArea, setDraftArea] = useState(area.near);
  const [category, setCategory] = useState("");
  const [shipsHere, setShipsHere] = useState(false);
  const [name, setName] = useState("");
  const [posts, setPosts] = useState(null);
  const [directory, setDirectory] = useState(null);
  // A supplier page's "Share yours" opens the form with that supplier chosen.
  const [compose, setCompose] = useState(params.get("recommend") ? "recommend" : null);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  useEffect(() => {
    setError("");
    const where = { near: area.near, radius: area.near ? area.radius : "" };
    Promise.all([
      api(`/posts?${query({ kind: SUPPLY_KINDS, category, ...where })}`),
      api(`/suppliers?${query({ category, q: name, ships_here: area.near && shipsHere, ...where })}`),
    ])
      .then(([p, d]) => {
        setPosts(p.posts);
        setDirectory(d.suppliers);
      })
      .catch((err) => setError(err.message));
  }, [area, category, shipsHere, name]);

  const applyArea = (event) => {
    event.preventDefault();
    const next = { ...area, near: draftArea.trim() };
    setArea(next);
    savedArea.set(next);
  };

  return (
    <>
      <h1>Supplies &amp; Vendors</h1>
      <p className="muted small">Where members find materials, better prices and suppliers they rely on. Have a model number? Try <Link to="/supplies/parts">part lookup</Link>.</p>

      <form className="card stack" onSubmit={applyArea} style={{ gap: 10 }}>
        <div className="area">
          <input aria-label="Your area" value={draftArea} onChange={(e) => setDraftArea(e.target.value)} placeholder='ZIP or "City, ST"' />
          <select aria-label="Distance" value={area.radius} onChange={(e) => { const next = { ...area, radius: Number(e.target.value) }; setArea(next); savedArea.set(next); }} style={{ width: "auto" }}>
            {[10, 25, 50, 100].map((r) => <option key={r} value={r}>{r} mi</option>)}
          </select>
        </div>
        <div className="grid-2">
          <CategorySelect value={category} onChange={setCategory} />
          <button className="btn">Show results for this area</button>
        </div>
        {area.near && <p className="small muted" style={{ margin: 0 }}>Showing results within {area.radius} miles of {area.near}. <button type="button" className="linklike small" onClick={() => { setArea({ ...area, near: "" }); setDraftArea(""); savedArea.set({ ...area, near: "" }); }}>Clear area</button></p>}
      </form>
      <Notice error={error} ok={ok} />

      <section className="stack" style={{ marginBottom: 24 }}>
        <div className="row-between">
          <h2 style={{ margin: 0 }}>Member recommendations</h2>
        </div>
        <div className="row">
          <button type="button" className="btn btn-primary btn-small" onClick={() => setCompose("ask")}>Ask a question</button>
          <button type="button" className="btn btn-small" onClick={() => setCompose("recommend")}>Share an experience</button>
          <button type="button" className="btn btn-small" onClick={() => setCompose("suggest")}>Suggest a supplier</button>
        </div>
        {compose && (
          <Compose
            mode={compose}
            area={area}
            suppliers={directory || []}
            supplierId={params.get("recommend") || ""}
            onClose={() => setCompose(null)}
            onPosted={(post) => {
              setPosts((list) => [post, ...(list || [])]);
              setCompose(null);
              setOk(compose === "suggest" ? "Thanks. A moderator will check the details before adding it to the directory." : "Posted.");
            }}
          />
        )}
        {posts === null ? (
          <p className="loading">Loading…</p>
        ) : posts.length === 0 ? (
          <p className="empty">No posts here yet. Ask the first question.</p>
        ) : (
          <ul className="items">{posts.map((p) => <PostCard key={p.id} post={p} />)}</ul>
        )}
      </section>

      <section className="stack">
        <h2 style={{ margin: 0 }}>Supplier directory</h2>
        <p className="small muted" style={{ margin: 0 }}>
          Listings are directory entries, not endorsements, and no supplier pays for placement. Each listing says what Trade Circle checked.
        </p>
        <div className="grid-2">
          <input aria-label="Search suppliers" type="search" placeholder="Search by name" value={name} onChange={(e) => setName(e.target.value)} />
          <label className="check" style={{ alignItems: "center", opacity: area.near ? 1 : 0.5 }}>
            <input type="checkbox" disabled={!area.near} checked={shipsHere} onChange={(e) => setShipsHere(e.target.checked)} />
            <span className="small">Only suppliers that ship to my area</span>
          </label>
        </div>
        {directory === null ? (
          <p className="loading">Loading…</p>
        ) : directory.length === 0 ? (
          <p className="empty">No suppliers match. Suggest one above.</p>
        ) : (
          <ul className="items">{directory.map((s) => <SupplierCard key={s.id} s={s} />)}</ul>
        )}
      </section>
    </>
  );
}
