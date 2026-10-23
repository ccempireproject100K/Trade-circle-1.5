// Single-screen share forms: equipment experiences and questions, and meetups.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, label } from "../api.js";
import { PhotoPicker, PRIVACY_REMINDER } from "../components/Community.jsx";
import { DictateButton } from "../components/Dictation.jsx";
import { Field, Notice } from "../components/Form.jsx";
import { EMPLOYMENT_TYPES, savedArea } from "../labels.js";

function TradeTags({ value, onChange }) {
  const [trades, setTrades] = useState([]);
  useEffect(() => {
    api("/community/meta").then((m) => setTrades(m.trades)).catch(() => {});
  }, []);
  return (
    <fieldset className="row" style={{ border: 0, padding: 0, margin: 0 }}>
      <legend className="field-label" style={{ marginBottom: 4 }}>Trades (up to 5)</legend>
      {trades.map((t) => (
        <label key={t} className="check" style={{ alignItems: "center" }}>
          <input type="checkbox" checked={value.includes(t)} disabled={!value.includes(t) && value.length >= 5} onChange={() => onChange(value.includes(t) ? value.filter((x) => x !== t) : [...value, t])} />
          <span className="small">{label(t)}</span>
        </label>
      ))}
    </fieldset>
  );
}

// A text box with tap-to-talk underneath.
function Spoken({ label: text, value, onChange, rows = 3 }) {
  return (
    <Field label={text}>
      <textarea rows={rows} maxLength={2000} value={value} onChange={(e) => onChange(e.target.value)} />
      <DictateButton onText={(t) => onChange(`${value.trimEnd()} ${t}`.trim())} />
    </Field>
  );
}

export function ShareEquipment() {
  const navigate = useNavigate();
  const [mode, setMode] = useState("share");
  const [f, setF] = useState({ title: "", body: "", product: "", model: "", used_for: "", durability: "", problems: "", repairs: "", buy_again: "", affiliation: "", affiliation_detail: "", supplier_id: "" });
  const [tags, setTags] = useState([]);
  const [photos, setPhotos] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [error, setError] = useState("");
  const set = (key) => (value) => setF((x) => ({ ...x, [key]: typeof value === "string" ? value : value.target.value }));

  useEffect(() => {
    api("/suppliers?category=tools_equipment").then((r) => setSuppliers(r.suppliers)).catch(() => {});
  }, []);

  const submit = async (event) => {
    event.preventDefault();
    const fields = mode === "ask"
      ? { product: f.product, model: f.model }
      : { product: f.product, model: f.model, used_for: f.used_for, durability: f.durability, problems: f.problems, repairs: f.repairs, buy_again: f.buy_again, affiliation: f.affiliation, affiliation_detail: f.affiliation_detail };
    try {
      const post = await api("/posts", {
        method: "POST",
        body: { kind: mode === "ask" ? "equipment_question" : "equipment", title: f.title, body: f.body, trade_tags: tags, category: "tools_equipment", supplier_id: f.supplier_id || null, photos: photos.map((p) => ({ id: p.id })), fields },
      });
      navigate(`/posts/${post.id}`, { replace: true });
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <form className="stack" onSubmit={submit}>
      <h1>Equipment</h1>
      <div className="tabs" role="group" aria-label="What do you want to do?">
        <button type="button" aria-pressed={mode === "share"} onClick={() => setMode("share")}>Share an experience</button>
        <button type="button" aria-pressed={mode === "ask"} onClick={() => setMode("ask")}>Ask a question</button>
      </div>
      <section className="card stack">
        <div className="grid-2">
          <Field label="Product"><input required={mode === "share"} maxLength={120} value={f.product} onChange={set("product")} placeholder="Cordless SDS rotary hammer" /></Field>
          <Field label="Brand and model (optional)"><input maxLength={120} value={f.model} onChange={set("model")} /></Field>
        </div>
        <Field label={mode === "ask" ? "Your question" : "Headline"}>
          <input required maxLength={140} value={f.title} onChange={set("title")} placeholder={mode === "ask" ? "Is this worth it for daily use?" : "Two years of daily use"} />
        </Field>
        {mode === "share" ? (
          <>
            <Spoken label="What do you use it for?" value={f.used_for} onChange={set("used_for")} rows={2} />
            <Spoken label="How has it held up?" value={f.durability} onChange={set("durability")} />
            <Spoken label="Problems you ran into" value={f.problems} onChange={set("problems")} />
            <Spoken label="Repairs and maintenance" value={f.repairs} onChange={set("repairs")} />
            <Field label="Would you buy it again?">
              <select value={f.buy_again} onChange={set("buy_again")}>
                <option value="">Prefer not to say</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
                <option value="unsure">Not sure</option>
              </select>
            </Field>
            <Field label="Do you sell this product, or get anything from its maker or a seller?" hint="Required. Members need to know about any connection.">
              <select required value={f.affiliation} onChange={set("affiliation")}>
                <option value="" disabled>Choose one</option>
                <option value="none">No connection</option>
                <option value="seller">I sell it</option>
                <option value="sponsor">Sponsored or given free product</option>
                <option value="employee">I work for the maker or a seller</option>
                <option value="other">Other connection</option>
              </select>
            </Field>
            {f.affiliation && f.affiliation !== "none" && (
              <Field label="Describe the connection"><input required maxLength={200} value={f.affiliation_detail} onChange={set("affiliation_detail")} /></Field>
            )}
          </>
        ) : (
          <Spoken label="Details" value={f.body} onChange={set("body")} />
        )}
        {suppliers.length > 0 && (
          <Field label="Where you got it (optional)">
            <select value={f.supplier_id} onChange={set("supplier_id")}>
              <option value="">Not linked</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
        )}
        <TradeTags value={tags} onChange={setTags} />
        <PhotoPicker photos={photos} onChange={setPhotos} label="Add photos (optional)" hint={PRIVACY_REMINDER} />
        {mode === "share" && <p className="small muted" style={{ margin: 0 }}>Shown as your own experience and opinion.</p>}
        <Notice error={error} />
        <button className="btn btn-primary">Post</button>
      </section>
    </form>
  );
}

const ZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu"];

export function ShareMeetup() {
  const navigate = useNavigate();
  const here = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const [f, setF] = useState({ title: "", body: "", starts_on: "", starts_at: "07:00", timezone: ZONES.includes(here) ? here : "America/Chicago", general_location: "", location: savedArea.get().near });
  const [tags, setTags] = useState([]);
  const [error, setError] = useState("");
  const set = (key) => (e) => setF({ ...f, [key]: e.target.value });

  const submit = async (event) => {
    event.preventDefault();
    try {
      const post = await api("/posts", {
        method: "POST",
        body: { kind: "meetup", title: f.title, body: f.body, location: f.location, trade_tags: tags, fields: { starts_on: f.starts_on, starts_at: f.starts_at, timezone: f.timezone, general_location: f.general_location } },
      });
      navigate(`/posts/${post.id}`, { replace: true });
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <form className="stack" onSubmit={submit}>
      <h1>Local meetup</h1>
      <p className="small muted" style={{ margin: 0 }}>A simple get-together: coffee, a jobsite tour, a supply-house breakfast. You're the host.</p>
      <section className="card stack">
        <Field label="Title"><input required maxLength={140} value={f.title} onChange={set("title")} placeholder="Coffee and code questions" /></Field>
        <Field label="What's it about?"><textarea maxLength={4000} value={f.body} onChange={set("body")} /></Field>
        <div className="grid-2">
          <Field label="Date"><input type="date" required value={f.starts_on} onChange={set("starts_on")} /></Field>
          <Field label="Time"><input type="time" required value={f.starts_at} onChange={set("starts_at")} /></Field>
        </div>
        <Field label="Time zone">
          <select value={f.timezone} onChange={set("timezone")}>
            {ZONES.map((z) => <option key={z} value={z}>{z.replace("America/", "").replace("Pacific/", "").replace("_", " ")}</option>)}
          </select>
        </Field>
        <Field label="General location" hint="Like 'coffee shop near downtown Austin'. Share the exact spot with people who RSVP.">
          <input required maxLength={160} value={f.general_location} onChange={set("general_location")} />
        </Field>
        <Field label="Area for search" hint='ZIP or "City, ST" so nearby members find it.'>
          <input required value={f.location} onChange={set("location")} />
        </Field>
        <TradeTags value={tags} onChange={setTags} />
        <Notice error={error} />
        <button className="btn btn-primary">Post meetup</button>
      </section>
    </form>
  );
}

// Shared submit for the simple one-screen forms.
function usePostSubmit(build) {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    setError("");
    try {
      const post = await api("/posts", { method: "POST", body: build() });
      navigate(`/posts/${post.id}`, { replace: true });
    } catch (err) {
      setError(err.message);
    }
  };
  return [submit, error];
}

export function ShareOpening() {
  const [f, setF] = useState({ title: "", body: "", role: "", employment_type: "full_time", pay: "", requirements: "", how_to_apply: "", apply_by: "", location: savedArea.get().near });
  const [tags, setTags] = useState([]);
  const set = (key) => (e) => setF({ ...f, [key]: e.target.value });
  const [submit, error] = usePostSubmit(() => ({
    kind: "opening", title: f.title, body: f.body, location: f.location, trade_tags: tags,
    fields: { role: f.role, employment_type: f.employment_type, pay: f.pay, requirements: f.requirements, how_to_apply: f.how_to_apply, apply_by: f.apply_by || null },
  }));
  return (
    <form className="stack" onSubmit={submit}>
      <h1>Job opening</h1>
      <p className="small muted" style={{ margin: 0 }}>For hiring employees or apprentices. Customer jobs and leads don't go here.</p>
      <section className="card stack">
        <Field label="Headline"><input required maxLength={140} value={f.title} onChange={set("title")} placeholder="Hiring a journeyman electrician" /></Field>
        <div className="grid-2">
          <Field label="Position"><input required maxLength={120} value={f.role} onChange={set("role")} /></Field>
          <Field label="Type">
            <select value={f.employment_type} onChange={set("employment_type")}>{Object.entries(EMPLOYMENT_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          </Field>
          <Field label="Pay (optional)" hint="Like $28–34/hr"><input maxLength={120} value={f.pay} onChange={set("pay")} /></Field>
          <Field label="Apply by (optional)" hint="The post leaves search after this date"><input type="date" value={f.apply_by} onChange={set("apply_by")} /></Field>
        </div>
        <Field label="About the job"><textarea maxLength={10000} value={f.body} onChange={set("body")} /></Field>
        <Field label="Requirements (optional)"><textarea maxLength={2000} value={f.requirements} onChange={set("requirements")} /></Field>
        <Field label="How to apply (optional)" hint="Leave empty and applicants message you through Trade Circle."><textarea maxLength={1000} value={f.how_to_apply} onChange={set("how_to_apply")} /></Field>
        <Field label="Where" hint='ZIP or "City, ST"'><input required value={f.location} onChange={set("location")} /></Field>
        <TradeTags value={tags} onChange={setTags} />
        <Notice error={error} />
        <button className="btn btn-primary">Post opening</button>
      </section>
    </form>
  );
}

export function ShareSpot() {
  const [f, setF] = useState({ title: "", body: "", place: "", suggestion: "spot", link: "", connection: "", connection_detail: "", location: savedArea.get().near });
  const set = (key) => (e) => setF({ ...f, [key]: e.target.value });
  const [submit, error] = usePostSubmit(() => ({
    kind: "spot", title: f.title, body: f.body, location: f.location,
    fields: { place: f.place, suggestion: f.suggestion, link: f.link.trim(), connection: f.connection, connection_detail: f.connection_detail },
  }));
  return (
    <form className="stack" onSubmit={submit}>
      <h1>Suggest a spot or deal</h1>
      <p className="small muted" style={{ margin: 0 }}>Shown as your recommendation, never as an ad or a sponsored listing. Members can reply and report.</p>
      <section className="card stack">
        <div className="tabs" role="group" aria-label="What is it?">
          <button type="button" aria-pressed={f.suggestion === "spot"} onClick={() => setF({ ...f, suggestion: "spot" })}>A place</button>
          <button type="button" aria-pressed={f.suggestion === "deal"} onClick={() => setF({ ...f, suggestion: "deal" })}>A deal</button>
        </div>
        <Field label="Name of the place"><input required maxLength={120} value={f.place} onChange={set("place")} /></Field>
        <Field label="Headline"><input required maxLength={140} value={f.title} onChange={set("title")} placeholder="Breakfast tacos by the supply house" /></Field>
        <Field label="Why you recommend it"><textarea maxLength={2000} value={f.body} onChange={set("body")} /></Field>
        <Field label="Link (optional)"><input type="url" maxLength={300} value={f.link} onChange={set("link")} placeholder="https://" /></Field>
        <Field label="Where" hint='ZIP or "City, ST"'><input required value={f.location} onChange={set("location")} /></Field>
        <Field label="Do you own, work for or get paid by this place?" hint="Required, so members can tell a recommendation from an ad.">
          <select required value={f.connection} onChange={set("connection")}>
            <option value="" disabled>Choose one</option>
            <option value="none">No connection</option>
            <option value="owner">I own it</option>
            <option value="employee">I work there</option>
            <option value="paid">I'm paid or rewarded to recommend it</option>
            <option value="other">Other connection</option>
          </select>
        </Field>
        {f.connection && f.connection !== "none" && <Field label="Describe the connection"><input required maxLength={200} value={f.connection_detail} onChange={set("connection_detail")} /></Field>}
        <Notice error={error} />
        <button className="btn btn-primary">Post suggestion</button>
      </section>
    </form>
  );
}
