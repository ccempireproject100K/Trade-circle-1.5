import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, dollars, toCents } from "../api.js";
import { Field, Notice } from "../components/Form.jsx";

// Job costing: what the job was expected to cost, what it did cost, and what's left as profit.
const KINDS = { labor: "Labor", materials: "Materials", equipment: "Equipment", subcontract: "Subcontractor", permits: "Permits & fees", other: "Other" };
const blankLine = () => ({ kind: "materials", description: "", quantity: "1", unit_cost: "" });
const toForm = (l) => ({ kind: l.kind, description: l.description, quantity: String(l.quantity), unit_cost: (l.unit_cost_cents / 100).toFixed(2) });
const fromForm = (l) => ({ kind: l.kind, description: l.description, quantity: Number(l.quantity) || 0, unit_cost_cents: toCents(l.unit_cost) || 0 });
const pct = (n) => (n == null ? "—" : `${n}%`);

function Lines({ title, lines, onChange }) {
  const set = (i, key) => (e) => onChange(lines.map((l, j) => (j === i ? { ...l, [key]: e.target.value } : l)));
  return (
    <section className="card stack">
      <h2 style={{ margin: 0 }}>{title}</h2>
      {lines.map((l, i) => (
        <div key={i} className="cost-line">
          <select aria-label={`${title} line ${i + 1} type`} value={l.kind} onChange={set(i, "kind")}>
            {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input aria-label={`${title} line ${i + 1} description`} placeholder="What" maxLength={140} value={l.description} onChange={set(i, "description")} />
          <input aria-label={`${title} line ${i + 1} quantity`} inputMode="decimal" placeholder="Qty" value={l.quantity} onChange={set(i, "quantity")} />
          <input aria-label={`${title} line ${i + 1} cost each`} inputMode="decimal" placeholder="$ each" value={l.unit_cost} onChange={set(i, "unit_cost")} />
          <button type="button" className="linklike small" aria-label={`Remove ${title} line ${i + 1}`} onClick={() => onChange(lines.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <button type="button" className="btn btn-small" style={{ justifySelf: "start" }} onClick={() => onChange([...lines, blankLine()])}>Add a line</button>
    </section>
  );
}

function Summary({ s }) {
  const row = (label, a, b) => (
    <tr><th scope="row">{label}</th><td>{a}</td><td>{b}</td></tr>
  );
  return (
    <section className="card">
      <h2>Summary</h2>
      <p style={{ marginTop: 0 }}>Price to customer: <strong>{dollars(s.price_cents)}</strong></p>
      <table className="cost-table">
        <thead><tr><th /><th scope="col">Estimated</th><th scope="col">Actual</th></tr></thead>
        <tbody>
          {row("Direct costs", dollars(s.estimate.direct_cents), dollars(s.actual.direct_cents))}
          {row("Overhead", dollars(s.estimate.overhead_cents), dollars(s.actual.overhead_cents))}
          {row("Total cost", dollars(s.estimate.cost_cents), dollars(s.actual.cost_cents))}
          {row("Profit", dollars(s.estimate.profit_cents), dollars(s.actual.profit_cents))}
          {row("Margin", pct(s.estimate.margin_percent), pct(s.actual.margin_percent))}
          {row("Markup", pct(s.estimate.markup_percent), pct(s.actual.markup_percent))}
        </tbody>
      </table>
      {s.tracked_hours > 0 && <p className="small">Includes {s.tracked_hours} tracked hours ({dollars(s.tracked_labor_cents)}) in actual labor.</p>}
      {Object.keys(s.variance).length > 0 && (
        <p className="small" style={{ marginBottom: 0 }}>
          Versus estimate: {Object.entries(s.variance).map(([k, v]) => `${KINDS[k]} ${v > 0 ? "+" : ""}${dollars(v)}`).join(" · ")}
        </p>
      )}
      <p className="small muted" style={{ marginBottom: 0 }}>Margin is profit as a share of the price. Markup is profit as a share of the cost.</p>
    </section>
  );
}

export default function Costing() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  const fill = (d) => {
    setData(d);
    setForm({
      price: d.price_cents != null ? (d.price_cents / 100).toFixed(2) : "",
      labor_rate: d.labor_cost_per_hour_cents ? (d.labor_cost_per_hour_cents / 100).toFixed(2) : "",
      overhead: String(d.overhead_percent || ""),
      estimate: d.estimate.map(toForm),
      actual: d.actual.map(toForm),
    });
  };
  useEffect(() => {
    api(`/jobs/${id}/costing`).then(fill, (err) => setError(err.message));
    api("/costing/templates").then(setTemplates, () => {});
  }, [id]);

  const body = () => ({
    price_cents: form.price === "" ? null : toCents(form.price),
    labor_cost_per_hour_cents: toCents(form.labor_rate) || 0,
    overhead_percent: Number(form.overhead) || 0,
    estimate: form.estimate.map(fromForm),
    actual: form.actual.map(fromForm),
  });
  const save = async (event) => {
    event?.preventDefault();
    setError("");
    try {
      fill(await api(`/jobs/${id}/costing`, { method: "PUT", body: body() }));
      setOk("Saved.");
    } catch (err) {
      setError(err.message);
    }
  };
  const saveTemplate = async () => {
    const name = window.prompt("Name this template (for example, 200A panel upgrade)");
    if (!name) return;
    try {
      const t = await api("/costing/templates", { method: "POST", body: { name, lines: form.estimate.map(fromForm) } });
      setTemplates([...templates, t].sort((a, b) => a.name.localeCompare(b.name)));
      setOk(`Saved "${name}" as a template.`);
    } catch (err) {
      setError(err.message);
    }
  };

  if (!data || !form) return <Notice error={error} />;
  return (
    <form className="stack" onSubmit={save}>
      <p className="small"><Link to="/jobs">← Jobs</Link></p>
      <h1>Costing: {data.job.title}</h1>
      <section className="card stack">
        <div className="grid-2">
          <Field label="Price to customer ($)" hint={data.job.estimate_cents ? `Blank uses the job's estimate, ${dollars(data.job.estimate_cents)}` : undefined}>
            <input inputMode="decimal" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} />
          </Field>
          <Field label="Labor cost per tracked hour ($)" hint="Wages plus taxes and insurance per hour"><input inputMode="decimal" value={form.labor_rate} onChange={(e) => setForm({ ...form, labor_rate: e.target.value })} /></Field>
          <Field label="Overhead (% added to costs)"><input inputMode="decimal" value={form.overhead} onChange={(e) => setForm({ ...form, overhead: e.target.value })} /></Field>
          {templates.length > 0 && (
            <Field label="Start the estimate from a template">
              <select value="" onChange={(e) => { const t = templates.find((x) => x.id === e.target.value); if (t) setForm({ ...form, estimate: t.lines.map(toForm) }); }}>
                <option value="">Choose…</option>
                {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </Field>
          )}
        </div>
      </section>
      <Lines title="Estimate" lines={form.estimate} onChange={(estimate) => setForm({ ...form, estimate })} />
      <Lines title="Actual" lines={form.actual} onChange={(actual) => setForm({ ...form, actual })} />
      <Notice error={error} ok={ok} />
      <span className="row">
        <button className="btn btn-primary">Save and update summary</button>
        {form.estimate.length > 0 && <button type="button" className="btn" onClick={saveTemplate}>Save estimate as a template</button>}
      </span>
      <Summary s={data.summary} />
    </form>
  );
}
