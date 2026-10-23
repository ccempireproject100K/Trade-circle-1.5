import { useEffect, useState } from "react";
import { api, label, localToday, shortDate } from "../api.js";
import { ReportButton } from "../components/Community.jsx";
import { Field, Notice } from "../components/Form.jsx";
import { savedArea } from "../labels.js";

// Pay and billing-rate comparisons, private submissions, and a cost calculator that never leaves the device.
const TABS = [
  { key: "compare", label: "Compare" },
  { key: "share", label: "Add your figures" },
  { key: "calculator", label: "Cost calculator" },
];
const METRIC_NAMES = {
  base_hourly: "Base pay per hour",
  overtime_hourly: "Overtime pay per hour",
  labor_hourly: "Labor rate per hour",
  service_call_minimum: "Service-call minimum",
  trip_charge: "Trip charge",
  materials_markup_percent: "Materials markup",
};

const money = (n) => (Number.isFinite(n) ? n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2 }) : "—");
const figure = (key, n) => (key === "materials_markup_percent" ? `${n}%` : money(n));

const UNITS = { hour: "per hour", project: "per project", service_call: "per service call", square_foot: "per sq ft", linear_foot: "per linear ft", other: "" };
const wage = (n) => (n == null ? "—" : money(n));

// Section 1: what employers report paying, from the federal survey. Available everywhere, right away.
function GovernmentWages({ trade, location }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setData(null);
    setError("");
    api(`/rates/government?${new URLSearchParams({ trade, location })}`).then(setData, (err) => setError(err.message));
  }, [trade, location]);
  return (
    <section className="card stack">
      <h2 style={{ margin: 0 }}>Government wage data</h2>
      <Notice error={error} />
      {data && (
        <>
          <p className="small muted" style={{ margin: 0 }}>
            {data.area || `${data.state} statewide`} · {data.period} · <a href={data.source_url} target="_blank" rel="noreferrer">{data.source}</a>
          </p>
          {data.occupations.length === 0 ? (
            <p>No published figures for this trade here.</p>
          ) : (
            <ul className="items">
              {data.occupations.map((o) => (
                <li key={o.code}>
                  <strong>{o.title}</strong>
                  {o.where === "state" && data.area && <span className="small muted"> (statewide; not published for this area)</span>}
                  <br />
                  Median {wage(o.median)}/hr · middle half {wage(o.p25)} to {wage(o.p75)} · most earn {wage(o.p10)} to {o.capped.includes("p90") ? "$115+" : wage(o.p90)}
                  {o.employment && <span className="small muted"> · about {o.employment.toLocaleString()} employed</span>}
                </li>
              ))}
            </ul>
          )}
          <p className="small muted" style={{ margin: 0 }}>{data.note}</p>
        </>
      )}
    </section>
  );
}

const NEW_EST = { service: "", unit: "hour", low: "", high: "", scope: "national", location: "", source_name: "", source_url: "", checked_on: "", note: "" };

// Adds an estimate, lets its adder edit it, or (mode "correct") suggests a correction for others to confirm.
function EstimateForm({ trade, start, mode = start ? "edit" : "add", onSaved, onCancel }) {
  const [f, setF] = useState(start ? { ...start, location: start.place?.zip || start.place?.label || "", checked_on: mode === "correct" ? localToday() : start.checked_on } : { ...NEW_EST, checked_on: localToday() });
  const [kind, setKind] = useState("change");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const set = (key) => (e) => setF({ ...f, [key]: e.target.value });
  const save = async (event) => {
    event.preventDefault();
    const body = { trade, service: f.service, unit: f.unit, low: Number(f.low), high: Number(f.high), scope: f.scope, location: f.scope === "national" ? "" : f.location, source_name: f.source_name, source_url: f.source_url, checked_on: f.checked_on, note: f.note };
    try {
      if (mode === "correct") await api(`/rates/estimates/${start.id}/corrections`, { method: "POST", body: { kind, reason, proposed: kind === "change" ? body : null } });
      else await api(start ? `/rates/estimates/${start.id}` : "/rates/estimates", { method: start ? "PUT" : "POST", body });
      onSaved();
    } catch (err) {
      setError(err.message);
    }
  };
  const correcting = mode === "correct";
  return (
    <form className="card stack" onSubmit={save}>
      {correcting && (
        <>
          <p className="small" style={{ margin: 0 }}>Other members check your correction against the source. It's applied once two of them confirm it.</p>
          <div className="tabs" role="group" aria-label="Correction type" style={{ margin: 0 }}>
            <button type="button" aria-pressed={kind === "change"} onClick={() => setKind("change")}>Fix the figures</button>
            <button type="button" aria-pressed={kind === "remove"} onClick={() => setKind("remove")}>The source no longer shows this</button>
          </div>
          <Field label="What's wrong, and how you checked"><textarea required minLength={5} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        </>
      )}
      {correcting && kind === "remove" ? null : (
        <>
      <p className="small" style={{ margin: 0 }}>Copy the range exactly as the source shows it, and link to the page. Don't adjust the numbers.</p>
      <div className="grid-2">
        <Field label="What it covers"><input required maxLength={120} value={f.service} onChange={set("service")} placeholder="Hourly labor rate" /></Field>
        <Field label="Unit">
          <select value={f.unit} onChange={set("unit")}>{Object.entries(UNITS).map(([k, v]) => <option key={k} value={k}>{v || "other"}</option>)}</select>
        </Field>
        <Field label="Low ($)"><input required inputMode="decimal" value={f.low} onChange={set("low")} /></Field>
        <Field label="High ($)"><input required inputMode="decimal" value={f.high} onChange={set("high")} /></Field>
        <Field label="The source gives this for">
          <select value={f.scope} onChange={set("scope")}><option value="national">The whole country</option><option value="state">A state</option><option value="local">A city or area</option></select>
        </Field>
        {f.scope !== "national" && <Field label={f.scope === "state" ? "Any ZIP or city in that state" : "ZIP or City, ST"}><input required value={f.location} onChange={set("location")} /></Field>}
        <Field label="Source name"><input required maxLength={80} value={f.source_name} onChange={set("source_name")} placeholder="HomeGuide" /></Field>
        <Field label="Link to the page (https)"><input required type="url" value={f.source_url} onChange={set("source_url")} /></Field>
        <Field label="Date you checked it"><input required type="date" value={f.checked_on} onChange={set("checked_on")} /></Field>
      </div>
      <Field label="Note (optional)"><input maxLength={500} value={f.note} onChange={set("note")} /></Field>
        </>
      )}
      <Notice error={error} />
      <span className="row">
        <button className="btn btn-primary">{correcting ? "Suggest correction" : start ? "Save update" : "Add estimate"}</button>
        <button type="button" className="linklike small" onClick={onCancel}>Cancel</button>
      </span>
    </form>
  );
}

function History({ id }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    api(`/rates/estimates/${id}/history`).then(setRows, () => setRows([]));
  }, [id]);
  if (!rows) return null;
  return (
    <ul className="small">
      {rows.map((r, i) => (
        <li key={i}>
          {shortDate(r.at)}: {r.by} {r.action}
          {Object.entries(r.changes).map(([k, v]) => ` · ${k.replace("_", " ")} ${v.from ?? "—"} → ${v.to ?? "—"}`).join("")}
          {r.confirmed_by?.length > 0 && ` · confirmed by ${r.confirmed_by.join(", ")}`}
        </li>
      ))}
    </ul>
  );
}

// Section 2: ranges other sites publish, kept up to date by members, always shown with their source.
function OutsideEstimates({ trade, location, onChange }) {
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(null); // "new", or { estimate, mode }
  const [showing, setShowing] = useState(null);
  const [error, setError] = useState("");
  const load = () => api(`/rates/estimates?${new URLSearchParams({ trade, location })}`).then(setData, (err) => setError(err.message));
  useEffect(() => {
    load();
  }, [trade, location]); // eslint-disable-line react-hooks/exhaustive-deps
  const saved = () => {
    setEditing(null);
    load();
    onChange?.();
  };
  return (
    <section className="card stack">
      <div className="row-between">
        <h2 style={{ margin: 0 }}>Outside estimates</h2>
        {!editing && <button type="button" className="btn btn-small" onClick={() => setEditing("new")}>Add one</button>}
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        Price ranges published by cost guides and other sites, added and kept current by members. Each shows its source; check it there before relying on it.
      </p>
      {editing === "new" && <EstimateForm trade={trade} onSaved={saved} onCancel={() => setEditing(null)} />}
      <Notice error={error} />
      {data && data.estimates.length === 0 && <p className="empty">No outside estimates for this trade yet. Know a published range? Add it with its link.</p>}
      <ul className="items">
        {data?.estimates.map((e) =>
          editing?.estimate?.id === e.id ? (
            <li key={e.id}><EstimateForm trade={trade} start={e} mode={editing.mode} onSaved={saved} onCancel={() => setEditing(null)} /></li>
          ) : (
            <li key={e.id} className="stack" style={{ gap: 2 }}>
              <span>
                <strong>{e.service}</strong>: {money(e.low)} to {money(e.high)} {UNITS[e.unit]}
              </span>
              <span className="small muted">
                {e.scope === "national" ? "National" : e.scope === "state" ? `${e.place?.state} statewide` : e.place?.label}
                {e.distance_miles != null && ` · ${e.distance_miles} mi`} · <a href={e.source_url} target="_blank" rel="noreferrer nofollow">{e.source_name}</a>, checked {shortDate(e.checked_on)}
                {e.stale && " · may be out of date"} · added by {e.added_by}
                {e.updated_by && `, updated by ${e.updated_by}`}
              </span>
              {e.note && <span className="small">{e.note}</span>}
              {e.open_corrections > 0 && <a className="small" href="#corrections">{e.open_corrections} suggested {e.open_corrections === 1 ? "correction" : "corrections"} waiting for members to check</a>}
              <span className="row">
                {e.mine ? (
                  <button type="button" className="linklike small" onClick={() => setEditing({ estimate: e, mode: "edit" })}>Edit</button>
                ) : (
                  <button type="button" className="linklike small" onClick={() => setEditing({ estimate: e, mode: "correct" })}>Suggest a correction</button>
                )}
                {e.changes > 0 && <button type="button" className="linklike small" onClick={() => setShowing(showing === e.id ? null : e.id)}>History</button>}
                <ReportButton targetType="estimate" targetId={e.id} label="Report" />
              </span>
              {showing === e.id && <History id={e.id} />}
            </li>
          ),
        )}
      </ul>
    </section>
  );
}

const FIELD_NAMES = { low: "Low", high: "High", unit: "Unit", service: "Covers", scope: "Scope", area: "Area", source_name: "Source", source_url: "Link", checked_on: "Checked", note: "Note" };

function Correction({ c, onChange }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const act = async (path, body) => {
    setError("");
    try {
      await api(path, { method: "POST", body });
      onChange();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <li className="card stack" style={{ margin: 0, gap: 6 }}>
      <span>
        <strong>{c.estimate.service}</strong> <span className="small muted">from <a href={c.estimate.source_url} target="_blank" rel="noreferrer nofollow">{c.estimate.source_name}</a></span>
      </span>
      {c.kind === "remove" ? (
        <p style={{ margin: 0 }}>Suggested: remove it, the source no longer shows it.</p>
      ) : (
        <ul className="small" style={{ margin: 0 }}>
          {Object.entries(c.changes).map(([k, v]) => <li key={k}>{FIELD_NAMES[k] || k}: {String(v.from ?? "—")} → <strong>{String(v.to ?? "—")}</strong></li>)}
        </ul>
      )}
      <p className="small" style={{ margin: 0 }}>“{c.reason}” · suggested by {c.proposed_by}</p>
      <p className="small muted" style={{ margin: 0 }}>
        {c.confirms} of {c.needed} confirmations needed{c.disputes > 0 && ` · ${c.disputes} disputed (needs more confirmations than disputes)`}
      </p>
      {c.notes.length > 0 && <ul className="small" style={{ margin: 0 }}>{c.notes.map((n, i) => <li key={i}>{n.by} ({n.vote === "confirm" ? "confirmed" : "disputed"}): {n.note}</li>)}</ul>}
      {c.mine ? (
        <button type="button" className="linklike small" style={{ justifySelf: "start" }} onClick={() => act(`/rates/estimates/corrections/${c.id}/withdraw`)}>Withdraw my correction</button>
      ) : (
        <>
          <input aria-label={`Note on the correction to ${c.estimate.service}`} placeholder="Optional note: what you saw on the source" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
          <span className="row">
            <button type="button" className="btn btn-small" aria-pressed={c.my_vote === "confirm"} onClick={() => act(`/rates/estimates/corrections/${c.id}/vote`, { vote: "confirm", note })}>
              {c.my_vote === "confirm" ? "Confirmed" : "Confirm, I checked the source"}
            </button>
            <button type="button" className="btn btn-small" aria-pressed={c.my_vote === "dispute"} onClick={() => act(`/rates/estimates/corrections/${c.id}/vote`, { vote: "dispute", note })}>
              {c.my_vote === "dispute" ? "Disputed" : "Dispute"}
            </button>
          </span>
        </>
      )}
      <Notice error={error} />
    </li>
  );
}

// Suggested fixes to outside estimates, waiting for other members to check them against the source.
function CommunityCorrections({ trade, location, version, onChange }) {
  const [items, setItems] = useState(null);
  const load = () => api(`/rates/estimates/corrections/open?${new URLSearchParams({ trade, location })}`).then(setItems, () => setItems([]));
  useEffect(() => {
    load();
  }, [trade, location, version]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section className="card stack" id="corrections">
      <h2 style={{ margin: 0 }}>Community corrections</h2>
      <p className="small muted" style={{ margin: 0 }}>
        Members suggest fixes when a source changes. Open the source, check it, then confirm or dispute. A correction is applied once two members confirm it and confirmations
        outnumber disputes.
      </p>
      {items && items.length === 0 && <p className="empty">No corrections waiting. Spot something out of date? Use “Suggest a correction” on that estimate.</p>}
      {items && items.length > 0 && <ul className="items">{items.map((c) => <Correction key={c.id} c={c} onChange={() => { load(); onChange(); }} />)}</ul>}
    </section>
  );
}

// Section 3: what members privately shared, shown only in protected aggregate form.
function MemberFigures({ meta, kind, trade, location, role }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const params = new URLSearchParams({ kind, trade, location });
    if (kind === "wage" && role) params.set("role", role);
    setError("");
    api(`/rates/compare?${params}`).then(setResult, (err) => setError(err.message));
  }, [kind, trade, location, role]);
  return (
    <section className="card stack">
      <h2 style={{ margin: 0 }}>From Trade Circle members</h2>
      <Notice error={error} />
      {result && !result.published && (
        <p style={{ margin: 0 }}>
          Not published yet. We're reviewing how shared figures are protected before showing any. Figures you add are kept private and will count once this opens.
        </p>
      )}
      {result?.published && result.insufficient_data && (
        <p style={{ margin: 0 }}>
          Not enough data for {label(result.trade)} in {result.area} yet. We show figures only when at least {meta.min_contributors} members have shared them, and only figures
          more than {meta.min_age_days} days old.
        </p>
      )}
      {result?.published && !result.insufficient_data && (
        <>
          <p className="small muted" style={{ margin: 0 }}>
            {result.area} · {result.sample_size} members · shared {result.oldest_month === result.newest_month ? result.oldest_month : `${result.oldest_month} to ${result.newest_month}`} · {result.source}
          </p>
          {Object.keys(result.metrics).length === 0 && <p>Not enough answers to any single figure yet.</p>}
          <ul className="items">
            {Object.entries(result.metrics).map(([key, m]) => (
              <li key={key}>
                <strong>{METRIC_NAMES[key]}</strong>: middle half {figure(key, m.low)} to {figure(key, m.high)}, median {figure(key, m.median)}{" "}
                <span className="small muted">({m.sample_size} answers)</span>
              </li>
            ))}
          </ul>
          {result.benefits && <p className="small">Benefits mentioned: {Object.entries(result.benefits).map(([b, pct]) => `${label(b)} ${pct}%`).join(" · ")}</p>}
          {result.pricing && <p className="small">Bills hourly {result.pricing.hourly}% · by the project {result.pricing.project}%</p>}
          <p className="small muted" style={{ margin: 0 }}>{result.disclaimer}</p>
        </>
      )}
    </section>
  );
}

function Compare({ meta }) {
  const [q, setQ] = useState({ kind: "wage", trade: "electrician", role: "" });
  const [place, setPlace] = useState(savedArea.get().near || "");
  const [location, setLocation] = useState(savedArea.get().near || "");
  const [version, setVersion] = useState(0); // bumps when an estimate or correction changes, so both sections reload
  const set = (key) => (e) => setQ({ ...q, [key]: e.target.value });
  const apply = (event) => {
    event.preventDefault();
    setLocation(place.trim());
  };
  return (
    <div className="stack">
      <div className="grid-2">
        <Field label="Compare">
          <select value={q.kind} onChange={set("kind")}>
            <option value="wage">Employee wages</option>
            <option value="billing">What contractors charge</option>
          </select>
        </Field>
        <Field label="Trade">
          <select value={q.trade} onChange={set("trade")}>{meta.trades.map((t) => <option key={t} value={t}>{label(t)}</option>)}</select>
        </Field>
        {q.kind === "wage" && (
          <Field label="Role (member figures)">
            <select value={q.role} onChange={set("role")}>
              <option value="">All roles</option>
              {meta.roles.map((r) => <option key={r} value={r}>{label(r)}</option>)}
            </select>
          </Field>
        )}
      </div>
      <form className="row" onSubmit={apply}>
        <input aria-label="ZIP or City, ST" placeholder='ZIP or "City, ST"' value={place} onChange={(e) => setPlace(e.target.value)} style={{ flex: 1 }} />
        <button className="btn btn-small">Show</button>
      </form>
      {!location ? (
        <p className="empty">Enter a ZIP code or city to see figures for your area.</p>
      ) : q.kind === "wage" ? (
        <>
          <GovernmentWages trade={q.trade} location={location} />
          <MemberFigures meta={meta} kind="wage" trade={q.trade} location={location} role={q.role} />
        </>
      ) : (
        <>
          <OutsideEstimates key={`est-${version}`} trade={q.trade} location={location} onChange={() => setVersion((v) => v + 1)} />
          <CommunityCorrections trade={q.trade} location={location} version={version} onChange={() => setVersion((v) => v + 1)} />
          <MemberFigures meta={meta} kind="billing" trade={q.trade} location={location} />
          <p className="small muted" style={{ margin: 0 }}>Government data covers employee pay only, so it isn't shown here.</p>
        </>
      )}
    </div>
  );
}

const BLANK = { kind: "wage", trade: "electrician", location: "", role: "journeyman", experience: "", base_hourly: "", overtime_hourly: "", benefits: [], pricing: "hourly", labor_hourly: "", service_call_minimum: "", trip_charge: "", materials_markup_percent: "" };

function Share({ meta }) {
  const [form, setForm] = useState(BLANK);
  const [mine, setMine] = useState([]);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const load = () => api("/rates/mine").then(setMine, () => {});
  useEffect(() => {
    load();
  }, []);

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    const num = (v) => (v === "" ? null : Number(v));
    const body = { kind: form.kind, trade: form.trade, location: form.location };
    if (form.kind === "wage") {
      Object.assign(body, { role: form.role, experience: form.experience || null, base_hourly: num(form.base_hourly), overtime_hourly: num(form.overtime_hourly), benefits: form.benefits });
    } else {
      Object.assign(body, { pricing: form.pricing, labor_hourly: num(form.labor_hourly), service_call_minimum: num(form.service_call_minimum), trip_charge: num(form.trip_charge), materials_markup_percent: num(form.materials_markup_percent) });
    }
    try {
      await api("/rates/mine", { method: "PUT", body });
      setOk("Saved. Only you can see what you entered.");
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const toggleBenefit = (b) => setForm({ ...form, benefits: form.benefits.includes(b) ? form.benefits.filter((x) => x !== b) : [...form.benefits, b] });

  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>
        What you enter is private: nobody can see your figures, and only your state is kept from the location. Comparisons use groups of at least {meta.min_contributors} members and
        figures more than {meta.min_age_days} days old.
      </p>
      <form className="card stack" onSubmit={submit}>
        <div className="grid-2">
          <Field label="I'm sharing">
            <select value={form.kind} onChange={set("kind")}>
              <option value="wage">What I'm paid as an employee</option>
              <option value="billing">What I charge customers</option>
            </select>
          </Field>
          <Field label="Trade"><select value={form.trade} onChange={set("trade")}>{meta.trades.map((t) => <option key={t} value={t}>{label(t)}</option>)}</select></Field>
          <Field label="ZIP or City, ST"><input required value={form.location} onChange={set("location")} placeholder="78701" /></Field>
        </div>
        {form.kind === "wage" ? (
          <>
            <div className="grid-2">
              <Field label="Role"><select value={form.role} onChange={set("role")}>{meta.roles.map((r) => <option key={r} value={r}>{label(r)}</option>)}</select></Field>
              <Field label="Years in the trade (optional)">
                <select value={form.experience} onChange={set("experience")}><option value="">—</option>{meta.experience.map((x) => <option key={x}>{x}</option>)}</select>
              </Field>
              <Field label="Base pay per hour ($)"><input required inputMode="decimal" value={form.base_hourly} onChange={set("base_hourly")} /></Field>
              <Field label="Overtime per hour ($, optional)"><input inputMode="decimal" value={form.overtime_hourly} onChange={set("overtime_hourly")} /></Field>
            </div>
            <fieldset className="checks">
              <legend className="field-label">Benefits you get</legend>
              {meta.benefits.map((b) => (
                <label key={b}><input type="checkbox" checked={form.benefits.includes(b)} onChange={() => toggleBenefit(b)} /> {label(b)}</label>
              ))}
            </fieldset>
          </>
        ) : (
          <div className="grid-2">
            <Field label="How you bill">
              <select value={form.pricing} onChange={set("pricing")}>
                <option value="hourly">Hourly</option>
                <option value="project">By the project</option>
                <option value="both">Both</option>
              </select>
            </Field>
            <Field label={`Labor rate per hour ($${form.pricing === "project" ? ", optional" : ""})`}><input inputMode="decimal" value={form.labor_hourly} onChange={set("labor_hourly")} /></Field>
            <Field label="Service-call minimum ($, optional)"><input inputMode="decimal" value={form.service_call_minimum} onChange={set("service_call_minimum")} /></Field>
            <Field label="Trip charge ($, optional)"><input inputMode="decimal" value={form.trip_charge} onChange={set("trip_charge")} /></Field>
            <Field label="Materials markup (%, optional)"><input inputMode="decimal" value={form.materials_markup_percent} onChange={set("materials_markup_percent")} /></Field>
          </div>
        )}
        <Notice error={error} ok={ok} />
        <button className="btn btn-primary">Save privately</button>
      </form>
      {mine.length > 0 && (
        <div className="card">
          <h2>Your figures (only you see these)</h2>
          <ul className="items">
            {mine.map((m) => (
              <li key={m.id} className="row-between">
                <span>
                  {m.kind === "wage" ? `${label(m.role)} wage` : "Billing rate"} · {label(m.trade)} · {m.state} · {m.kind === "wage" ? money(m.base_hourly) + "/hr" : m.labor_hourly != null ? money(m.labor_hourly) + "/hr" : "project pricing"}
                </span>
                <button type="button" className="link-danger" onClick={async () => { await api(`/rates/mine/${m.id}`, { method: "DELETE" }); load(); }}>Remove</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// All math runs here, in the browser. Nothing typed into the calculator is sent anywhere.
export function calculate({ overhead, pay, hours, margin }) {
  const cost = overhead + pay;
  if (!(hours > 0)) return null;
  const breakEven = cost / hours;
  const m = margin / 100;
  const rate = m > 0 && m < 1 ? breakEven / (1 - m) : breakEven;
  return { cost, breakEven, rate, markup: m > 0 && m < 1 ? (m / (1 - m)) * 100 : 0 };
}

function Calculator() {
  const [v, setV] = useState({ overhead: "", pay: "", weeks: "48", hoursPerWeek: "30", margin: "" });
  const [conv, setConv] = useState({ cost: "100", markup: "25" });
  const n = (x) => Number(x) || 0;
  const set = (key) => (e) => setV({ ...v, [key]: e.target.value });
  const hours = n(v.weeks) * n(v.hoursPerWeek);
  const r = calculate({ overhead: n(v.overhead), pay: n(v.pay), hours, margin: n(v.margin) });
  const price = n(conv.cost) * (1 + n(conv.markup) / 100);
  const convMargin = price > 0 ? ((price - n(conv.cost)) / price) * 100 : 0;

  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>Private: this runs on your device and nothing you type here is saved or sent.</p>
      <div className="card stack">
        <h2 style={{ margin: 0 }}>Your hourly rate</h2>
        <div className="grid-2">
          <Field label="Yearly overhead ($)" hint="Insurance, vehicle, fuel, tools, phone, software, licenses, office"><input inputMode="decimal" value={v.overhead} onChange={set("overhead")} /></Field>
          <Field label="What you want to pay yourself per year ($)"><input inputMode="decimal" value={v.pay} onChange={set("pay")} /></Field>
          <Field label="Working weeks per year"><input inputMode="decimal" value={v.weeks} onChange={set("weeks")} /></Field>
          <Field label="Billable hours per week" hint="Hours you can charge for, not travel, quoting or paperwork"><input inputMode="decimal" value={v.hoursPerWeek} onChange={set("hoursPerWeek")} /></Field>
          <Field label="Profit margin (%, optional)" hint="Share of the price kept as profit"><input inputMode="decimal" value={v.margin} onChange={set("margin")} /></Field>
        </div>
        {r ? (
          <div aria-live="polite">
            <p style={{ margin: 0 }}>
              <strong>Charge at least {money(r.rate)} per hour</strong>
            </p>
            <ol className="small">
              <li>Yearly costs: {money(n(v.overhead))} overhead + {money(n(v.pay))} pay = {money(r.cost)}</li>
              <li>Billable hours: {n(v.weeks)} weeks × {n(v.hoursPerWeek)} hours = {hours.toLocaleString()} hours</li>
              <li>Break-even: {money(r.cost)} ÷ {hours.toLocaleString()} = {money(r.breakEven)} per hour</li>
              {n(v.margin) > 0 && n(v.margin) < 100 && (
                <li>
                  With a {n(v.margin)}% margin: {money(r.breakEven)} ÷ (1 − {n(v.margin) / 100}) = {money(r.rate)}. That's a {r.markup.toFixed(1)}% markup on cost.
                </li>
              )}
            </ol>
          </div>
        ) : (
          <p className="small muted">Enter billable hours to see a rate.</p>
        )}
      </div>
      <div className="card stack">
        <h2 style={{ margin: 0 }}>Markup or margin?</h2>
        <p className="small" style={{ margin: 0 }}>
          Markup is added on top of your cost. Margin is the share of the final price you keep. A 25% markup is only a 20% margin.
        </p>
        <div className="grid-2">
          <Field label="Your cost ($)"><input inputMode="decimal" value={conv.cost} onChange={(e) => setConv({ ...conv, cost: e.target.value })} /></Field>
          <Field label="Markup (%)"><input inputMode="decimal" value={conv.markup} onChange={(e) => setConv({ ...conv, markup: e.target.value })} /></Field>
        </div>
        <p style={{ margin: 0 }} aria-live="polite">
          Price {money(price)} · profit {money(price - n(conv.cost))} · margin {convMargin.toFixed(1)}%
        </p>
      </div>
    </div>
  );
}

export default function Rates() {
  const [tab, setTab] = useState("compare");
  const [meta, setMeta] = useState(null);
  useEffect(() => {
    api("/rates/meta").then(setMeta, () => {});
  }, []);
  return (
    <>
      <h1>Pay & rates</h1>
      <div className="tabs" role="group" aria-label="Show">
        {TABS.map((t) => (
          <button key={t.key} type="button" aria-pressed={tab === t.key} onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>
      {tab === "calculator" ? <Calculator /> : !meta ? <p className="loading">Loading…</p> : tab === "compare" ? <Compare meta={meta} /> : <Share meta={meta} />}
    </>
  );
}
