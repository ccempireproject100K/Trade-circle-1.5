import { useEffect, useState } from "react";
import { api, label } from "../api.js";
import { useAuth } from "../auth.jsx";
import { CheersPanel } from "../components/Cheers.jsx";
import { Field, Notice } from "../components/Form.jsx";
import SortableList from "../components/SortableList.jsx";

const TEXT_FIELDS = ["business_name", "tagline", "trade", "city", "service_area", "phone", "facetime", "about"];
// Leaving one of these blank removes it from the page.
const CLEARABLE = new Set(["tagline", "service_area", "phone", "facetime", "about"]);
const SECTION_NAMES = {
  about: "About",
  portfolio: "Photos",
  licenses: "Licenses",
  insurance: "Insurance",
  service_area: "Service area",
  quote: "Quote form",
};
const DEFAULT_COLOR = "#4A2F1B";

function DetailsForm({ profile, trades, onSaved }) {
  const initial = Object.fromEntries(TEXT_FIELDS.map((k) => [k, profile[k] || ""]));
  const [form, setForm] = useState({ ...initial, brand_color: profile.brand_color || DEFAULT_COLOR });
  const [status, setStatus] = useState({});
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  const submit = async (event) => {
    event.preventDefault();
    const body = {};
    for (const key of TEXT_FIELDS) {
      const value = form[key].trim();
      if (value === (profile[key] || "")) continue;
      body[key] = value === "" && CLEARABLE.has(key) ? null : value;
    }
    if (form.brand_color !== (profile.brand_color || DEFAULT_COLOR)) body.brand_color = form.brand_color;
    if (!Object.keys(body).length) {
      setStatus({ ok: "No changes to save." });
      return;
    }
    try {
      onSaved(await api("/me/profile", { method: "PUT", body }));
      setStatus({ ok: "Saved." });
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  return (
    <form className="card stack" onSubmit={submit}>
      <h2>Details</h2>
      <Field label="Business name"><input required maxLength={120} value={form.business_name} onChange={set("business_name")} /></Field>
      <Field label="Tagline" hint="One line customers see first. Up to 140 characters.">
        <input maxLength={140} value={form.tagline} onChange={set("tagline")} placeholder="Licensed. Insured. On time." />
      </Field>
      <div className="grid-2">
        <Field label="Trade">
          <select value={form.trade} onChange={set("trade")}>
            {trades.map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </select>
        </Field>
        <Field label="City"><input required maxLength={120} value={form.city} onChange={set("city")} /></Field>
      </div>
      <Field label="Service area"><input maxLength={200} value={form.service_area} onChange={set("service_area")} placeholder="Travis and Williamson counties" /></Field>
      <div className="grid-2">
        <Field label="Phone for the Call button"><input type="tel" autoComplete="tel" value={form.phone} onChange={set("phone")} /></Field>
        <Field label="FaceTime" hint="Apple ID email or phone. Shown on Apple devices only.">
          <input value={form.facetime} onChange={set("facetime")} />
        </Field>
      </div>
      <Field label="Brand color">
        <span className="row">
          <input type="color" value={form.brand_color} onChange={set("brand_color")} />
          <span className="muted small">{form.brand_color.toUpperCase()}</span>
        </span>
      </Field>
      <Field label="About"><textarea maxLength={4000} value={form.about} onChange={set("about")} /></Field>
      <Notice error={status.error} ok={status.ok} />
      <button className="btn btn-primary">Save details</button>
    </form>
  );
}

function Licenses({ profile, onSaved }) {
  const [adding, setAdding] = useState({ name: "", issuer: "", expires_on: "", renewed_on: "" });
  const [status, setStatus] = useState({});
  const licenses = profile.licenses || [];

  const save = async (next, message) => {
    try {
      onSaved(await api("/me/profile", { method: "PUT", body: { licenses: next } }));
      setStatus({ ok: message });
      return true;
    } catch (err) {
      setStatus({ error: err.message });
      return false;
    }
  };

  const add = async (event) => {
    event.preventDefault();
    const entry = { ...adding, renewed_on: adding.renewed_on || null };
    if (await save([...licenses, entry], `Added ${adding.name}.`)) setAdding({ name: "", issuer: "", expires_on: "", renewed_on: "" });
  };

  const set = (key) => (event) => setAdding({ ...adding, [key]: event.target.value });

  return (
    <section className="card stack">
      <h2>Licenses and certifications</h2>
      <p className="small muted" style={{ margin: 0 }}>
        Expired ones show a "lapsed" badge. Add a renewal date and your page shows a celebration banner for 3 days.
      </p>
      {licenses.length > 0 && (
        <ul className="items">
          {licenses.map((lic, i) => (
            <li key={`${lic.name}-${i}`} className="row-between">
              <span><strong>{lic.name}</strong>{lic.issuer && ` · ${lic.issuer}`}<br /><span className="small muted">Expires {lic.expires_on}</span></span>
              <button type="button" className="btn btn-small btn-danger" onClick={() => save(licenses.filter((_, j) => j !== i), `Removed ${lic.name}.`)}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      <form className="stack" onSubmit={add}>
        <div className="grid-2">
          <Field label="License name"><input required maxLength={120} value={adding.name} onChange={set("name")} placeholder="Master Electrician" /></Field>
          <Field label="Issued by"><input maxLength={120} value={adding.issuer} onChange={set("issuer")} placeholder="TDLR" /></Field>
          <Field label="Expires"><input type="date" required value={adding.expires_on} onChange={set("expires_on")} /></Field>
          <Field label="Renewed on (optional)"><input type="date" value={adding.renewed_on} onChange={set("renewed_on")} /></Field>
        </div>
        <Notice error={status.error} ok={status.ok} />
        <button className="btn">Add license</button>
      </form>
    </section>
  );
}

function Insurance() {
  const [form, setForm] = useState({ carrier: "", policy_number: "", expires_on: "", document_url: "" });
  const [status, setStatus] = useState({});
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  const submit = async (event) => {
    event.preventDefault();
    try {
      await api("/me/insurance", { method: "PUT", body: form });
      setStatus({ ok: "Sent for review. Your page shows \"Insurance pending review\" until it's checked." });
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  return (
    <form className="card stack" onSubmit={submit}>
      <h2>Insurance</h2>
      <p className="small muted" style={{ margin: 0 }}>Once we check your certificate, your page shows an "Insured" badge.</p>
      <div className="grid-2">
        <Field label="Insurance company"><input required maxLength={120} value={form.carrier} onChange={set("carrier")} /></Field>
        <Field label="Policy number"><input required maxLength={60} value={form.policy_number} onChange={set("policy_number")} /></Field>
        <Field label="Expires"><input type="date" required value={form.expires_on} onChange={set("expires_on")} /></Field>
        <Field label="Link to certificate" hint="An https link to a PDF or photo.">
          <input type="url" required value={form.document_url} onChange={set("document_url")} placeholder="https://" />
        </Field>
      </div>
      <Notice error={status.error} ok={status.ok} />
      <button className="btn">Submit for review</button>
    </form>
  );
}

export default function Profile() {
  const { profile, setProfile } = useAuth();
  const [meta, setMeta] = useState(null);
  const [status, setStatus] = useState({});

  useEffect(() => {
    api("/meta").then(setMeta).catch((err) => setStatus({ error: err.message }));
  }, []);

  const put = async (body, message) => {
    try {
      setProfile(await api("/me/profile", { method: "PUT", body }));
      setStatus({ ok: message });
    } catch (err) {
      setStatus({ error: err.message });
    }
  };

  if (!meta) return status.error ? <Notice error={status.error} /> : <p className="loading">Loading…</p>;
  const published = profile.published !== false;

  return (
    <>
      <div className="row-between">
        <h1>Profile</h1>
        <a className="btn btn-small" href={`/p/${profile.slug}`} target="_blank" rel="noreferrer">View page</a>
      </div>

      <section className="card stack">
        <label className="check">
          <input type="checkbox" checked={published} onChange={() => put({ published: !published }, published ? "Your page is hidden." : "Your page is live.")} />
          <span>
            Page is live
            <span className="field-hint" style={{ display: "block" }}>Turn off to hide your page and stop quote requests.</span>
          </span>
        </label>
        <Notice error={status.error} ok={status.ok} />
      </section>

      <CheersPanel />

      <DetailsForm profile={profile} trades={meta.trades} onSaved={setProfile} />

      <section className="card stack">
        <h2>Full profile layout</h2>
        <p className="small muted" style={{ margin: 0 }}>Drag the sections into the order you want on your full profile.</p>
        <SortableList
          label="Section order"
          items={profile.layout || meta.sections}
          getKey={(section) => section}
          renderItem={(section) => <strong>{SECTION_NAMES[section] || label(section)}</strong>}
          onReorder={(layout) => put({ layout }, "Layout saved.")}
        />
      </section>

      <Licenses profile={profile} onSaved={setProfile} />
      <Insurance />
    </>
  );
}
