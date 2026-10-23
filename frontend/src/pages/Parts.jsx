import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, uploadPhoto } from "../api.js";
import { PostCard } from "../components/Community.jsx";
import { Notice } from "../components/Form.jsx";
import { Allowance } from "./Helper.jsx";

// Part lookup: search members' posts by model or part number. Photo reading is a separate, limited AI feature.
function Match({ m }) {
  return (
    <li>
      <strong>{[m.brand, m.model_or_part].filter(Boolean).join(" ") || "Unknown part"}</strong> · {m.description}
    </li>
  );
}

export default function Parts() {
  const [q, setQ] = useState("");
  const [result, setResult] = useState(null);
  const [photoStatus, setPhotoStatus] = useState(null);
  const [read, setRead] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const file = useRef(null);

  useEffect(() => {
    api("/parts/photo").then(setPhotoStatus, () => {});
  }, []);

  const search = async (event, text = q) => {
    event?.preventDefault();
    setError("");
    try {
      setResult(await api(`/parts/search?q=${encodeURIComponent(text)}`));
    } catch (err) {
      setError(err.message);
    }
  };

  const readPhoto = async (event) => {
    const picked = event.target.files[0];
    event.target.value = "";
    if (!picked) return;
    setBusy(true);
    setError("");
    try {
      const res = await uploadPhoto(picked, null, () => {}, "/parts/photo");
      setRead(res);
      setPhotoStatus(res.status);
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  return (
    <>
      <p className="small"><Link to="/supplies">← Supplies</Link></p>
      <h1>Part lookup</h1>
      <form className="row" onSubmit={search}>
        <input type="search" aria-label="Model or part number" placeholder="Model or part number from the label" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} />
        <button className="btn btn-primary">Search</button>
      </form>
      <section className="card stack" style={{ marginTop: 12 }}>
        <h2 style={{ margin: 0 }}>Read a label photo</h2>
        <Allowance status={photoStatus} noun="photo lookups" />
        {photoStatus?.available && (
          <>
            <input ref={file} type="file" accept="image/*" capture="environment" hidden onChange={readPhoto} />
            <button type="button" className="btn" disabled={busy || photoStatus.remaining_today === 0} onClick={() => file.current.click()}>{busy ? "Reading…" : "Take or choose a photo"}</button>
          </>
        )}
        {read && (
          <div className="stack" style={{ gap: 6 }}>
            {read.label_text.length > 0 && <p style={{ margin: 0 }}>Text on the label: {read.label_text.map((t) => <button key={t} type="button" className="tag" onClick={() => { setQ(t); search(null, t); }}>{t}</button>)}</p>}
            {read.exact.length > 0 && (<><h3 style={{ margin: 0 }}>Read from the label</h3><ul>{read.exact.map((m, i) => <Match key={i} m={m} />)}</ul></>)}
            {read.possible.length > 0 && (<><h3 style={{ margin: 0 }}>Possible matches by appearance only</h3><ul>{read.possible.map((m, i) => <Match key={i} m={m} />)}</ul></>)}
            {read.need_more && <p className="small" style={{ margin: 0 }}>{read.need_more}</p>}
            <p className="small muted" style={{ margin: 0 }}>{read.note}</p>
          </div>
        )}
      </section>
      <Notice error={error} />
      {result && (
        <section className="stack" style={{ marginTop: 12 }}>
          <p className="small muted" style={{ margin: 0 }}>{result.note}</p>
          <h2 style={{ margin: 0 }}>Exact model match ({result.exact.length})</h2>
          {result.exact.length ? <ul className="items">{result.exact.map((p) => <PostCard key={p.id} post={p} />)}</ul> : <p className="small muted">No member post lists exactly “{result.query}”.</p>}
          {result.mentions.length > 0 && (<><h2 style={{ margin: 0 }}>Other posts mentioning it</h2><ul className="items">{result.mentions.map((p) => <PostCard key={p.id} post={p} />)}</ul></>)}
          <div className="card stack">
            <h2 style={{ margin: 0 }}>Ask a supplier</h2>
            <p className="item-message" style={{ margin: 0 }}>{result.inquiry}</p>
            <span className="row">
              <button type="button" className="btn btn-small" onClick={() => navigator.clipboard?.writeText(result.inquiry).then(() => setCopied(true), () => {})}>{copied ? "Copied" : "Copy message"}</button>
              <Link className="btn btn-small" to="/supplies">Find a supplier</Link>
            </span>
          </div>
        </section>
      )}
    </>
  );
}
