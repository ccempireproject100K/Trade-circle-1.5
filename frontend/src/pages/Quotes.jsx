import { useEffect, useState } from "react";
import { api, dollars, localToday, toCents } from "../api.js";
import { Field, Notice } from "../components/Form.jsx";

// Seasonal quote templates: standard prices with adjustments for busy and slow months.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const blank = () => ({ name: "", items: [{ description: "", price: "" }], seasons: [] });

function TemplateForm({ start, onSaved, onClose }) {
  const [f, setF] = useState(start ? { name: start.name, items: start.items.map((i) => ({ description: i.description, price: (i.price_cents / 100).toFixed(2) })), seasons: start.seasons } : blank());
  const [error, setError] = useState("");
  const setItem = (i, key) => (e) => setF({ ...f, items: f.items.map((x, j) => (j === i ? { ...x, [key]: e.target.value } : x)) });
  const setSeason = (i, patch) => setF({ ...f, seasons: f.seasons.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  const toggleMonth = (i, m) => {
    const s = f.seasons[i];
    setSeason(i, { months: s.months.includes(m) ? s.months.filter((x) => x !== m) : [...s.months, m].sort((a, b) => a - b) });
  };
  const save = async (event) => {
    event.preventDefault();
    const body = { name: f.name, items: f.items.map((i) => ({ description: i.description, price_cents: toCents(i.price) || 0 })), seasons: f.seasons.map((s) => ({ ...s, adjust_percent: Number(s.adjust_percent) || 0 })) };
    try {
      onSaved(await api(start ? `/quote-templates/${start.id}` : "/quote-templates", { method: start ? "PUT" : "POST", body }));
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="card stack" onSubmit={save}>
      <div className="row-between">
        <h2 style={{ margin: 0 }}>{start ? "Edit template" : "New quote template"}</h2>
        <button type="button" className="linklike" onClick={onClose}>Close</button>
      </div>
      <Field label="Name"><input required maxLength={80} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="AC tune-up" /></Field>
      <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="field-label">Line items</legend>
        {f.items.map((it, i) => (
          <div key={i} className="row">
            <input aria-label={`Item ${i + 1}`} required maxLength={140} placeholder="What" value={it.description} onChange={setItem(i, "description")} style={{ flex: 2 }} />
            <input aria-label={`Item ${i + 1} price`} required inputMode="decimal" placeholder="$" value={it.price} onChange={setItem(i, "price")} style={{ flex: 1 }} />
            {f.items.length > 1 && <button type="button" className="linklike small" onClick={() => setF({ ...f, items: f.items.filter((_, j) => j !== i) })}>Remove</button>}
          </div>
        ))}
        <button type="button" className="btn btn-small" style={{ justifySelf: "start" }} onClick={() => setF({ ...f, items: [...f.items, { description: "", price: "" }] })}>Add an item</button>
      </fieldset>
      <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="field-label">Seasons (optional)</legend>
        {f.seasons.map((s, i) => (
          <div key={i} className="card stack" style={{ margin: 0 }}>
            <div className="row">
              <input aria-label={`Season ${i + 1} name`} required maxLength={60} placeholder="Peak season" value={s.label} onChange={(e) => setSeason(i, { label: e.target.value })} style={{ flex: 2 }} />
              <input aria-label={`Season ${i + 1} adjustment`} inputMode="decimal" placeholder="+15" value={s.adjust_percent} onChange={(e) => setSeason(i, { adjust_percent: e.target.value })} style={{ flex: 1 }} />
              <span>%</span>
            </div>
            <div className="checks">
              {MONTHS.map((m, k) => (
                <label key={m}><input type="checkbox" checked={s.months.includes(k + 1)} onChange={() => toggleMonth(i, k + 1)} /> {m}</label>
              ))}
            </div>
            <button type="button" className="linklike small" style={{ justifySelf: "start" }} onClick={() => setF({ ...f, seasons: f.seasons.filter((_, j) => j !== i) })}>Remove season</button>
          </div>
        ))}
        <button type="button" className="btn btn-small" style={{ justifySelf: "start" }} onClick={() => setF({ ...f, seasons: [...f.seasons, { label: "", months: [], adjust_percent: "" }] })}>Add a season</button>
      </fieldset>
      <Notice error={error} />
      <button className="btn btn-primary">Save template</button>
    </form>
  );
}

function Pricer({ template }) {
  const [on, setOn] = useState(localToday());
  const [quote, setQuote] = useState(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (on) api(`/quote-templates/${template.id}/price?on=${on}`).then(setQuote, () => setQuote(null));
  }, [on, template]);
  const text = quote ? [...quote.items.map((i) => `${i.description}: ${dollars(i.adjusted_cents)}`), `Total: ${dollars(quote.total_cents)}`].join("\n") : "";
  return (
    <div className="stack" style={{ gap: 6 }}>
      <Field label="Price it for"><input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
      {quote && (
        <>
          <ul className="small" style={{ margin: 0 }}>{quote.items.map((i, k) => <li key={k}>{i.description}: {dollars(i.adjusted_cents)}</li>)}</ul>
          <p style={{ margin: 0 }}>
            <strong>Total {dollars(quote.total_cents)}</strong>
            {quote.season && <span className="small muted"> · {quote.season.label}, {quote.season.adjust_percent > 0 ? "+" : ""}{quote.season.adjust_percent}% on {dollars(quote.subtotal_cents)}</span>}
          </p>
          <button type="button" className="btn btn-small" style={{ justifySelf: "start" }} onClick={() => navigator.clipboard?.writeText(text).then(() => setCopied(true), () => {})}>{copied ? "Copied" : "Copy quote"}</button>
        </>
      )}
    </div>
  );
}

export default function Quotes() {
  const [list, setList] = useState(null);
  const [editing, setEditing] = useState(null); // "new" or a template
  const [error, setError] = useState("");
  useEffect(() => {
    api("/quote-templates").then(setList, (err) => setError(err.message));
  }, []);
  const saved = (t) => {
    setList([...(list || []).filter((x) => x.id !== t.id), t].sort((a, b) => a.name.localeCompare(b.name)));
    setEditing(null);
  };
  const remove = async (t) => {
    if (!window.confirm(`Delete "${t.name}"?`)) return;
    await api(`/quote-templates/${t.id}`, { method: "DELETE" });
    setList(list.filter((x) => x.id !== t.id));
  };
  return (
    <>
      <div className="row-between">
        <h1>Quote templates</h1>
        {!editing && <button type="button" className="btn btn-primary btn-small" onClick={() => setEditing("new")}>New template</button>}
      </div>
      <p className="small muted" style={{ marginTop: 0 }}>Save your usual prices once, with seasonal adjustments, and price any date in a tap.</p>
      <Notice error={error} />
      {editing && <TemplateForm start={editing === "new" ? null : editing} onSaved={saved} onClose={() => setEditing(null)} />}
      {list && list.length === 0 && !editing && <p className="empty">No templates yet.</p>}
      <ul className="items">
        {(list || []).map((t) => (
          <li key={t.id} className="card stack" style={{ margin: 0 }}>
            <div className="row-between">
              <h2 style={{ margin: 0 }}>{t.name}</h2>
              <span className="row" style={{ gap: 8 }}>
                <button type="button" className="linklike small" onClick={() => setEditing(t)}>Edit</button>
                <button type="button" className="linklike small" onClick={() => remove(t)}>Delete</button>
              </span>
            </div>
            {t.seasons.length > 0 && <p className="small muted" style={{ margin: 0 }}>{t.seasons.map((s) => `${s.label}: ${s.adjust_percent > 0 ? "+" : ""}${s.adjust_percent}% (${s.months.map((m) => MONTHS[m - 1]).join(", ")})`).join(" · ")}</p>}
            <Pricer template={t} />
          </li>
        ))}
      </ul>
    </>
  );
}
