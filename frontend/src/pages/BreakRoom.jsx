import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, localToday, shortDate } from "../api.js";
import { useAuth } from "../auth.jsx";
import { PostCard, ReportButton } from "../components/Community.jsx";
import { Field, Notice } from "../components/Form.jsx";
import { announceSound, parseYouTube, useMusic, youTubeUrl } from "../components/Music.jsx";
import { savedArea } from "../labels.js";

// A light corner of the site: music, a game, public deals, giveaways and members' favorite spots.
const TABS = [
  { key: "music", label: "Music" },
  { key: "games", label: "Games" },
  { key: "deals", label: "Deals & spots" },
  { key: "giveaways", label: "Giveaways" },
];

// Only games whose license allows hosting them on a commercial site. Each runs in a frame with no network access.
export const GAMES = [
  { id: "2048", name: "2048", src: "/app/games/2048/index.html", about: "Slide tiles to combine numbers. No sound, no ads. Open-source (MIT license) by Gabriele Cirulli.", sound: false },
];

const count = (event, detail = "") => api("/usage", { method: "POST", body: { event, detail } }).catch(() => {});

function Music() {
  const { play } = useMusic();
  const [link, setLink] = useState("");
  const parsed = parseYouTube(link);
  return (
    <section className="card stack">
      <p style={{ margin: 0 }}>Paste a YouTube video or playlist link.</p>
      <input aria-label="YouTube link" type="url" placeholder="https://www.youtube.com/watch?v=…" value={link} onChange={(e) => setLink(e.target.value)} />
      {link && !parsed && <p className="small" role="alert" style={{ margin: 0, color: "var(--bad)" }}>That doesn't look like a YouTube video or playlist link.</p>}
      <span className="row">
        <button type="button" className="btn btn-primary" disabled={!parsed} onClick={() => play(parsed)}>Play here</button>
        {parsed ? <a className="btn" href={youTubeUrl(parsed)} target="_blank" rel="noreferrer">Open in YouTube</a> : <button type="button" className="btn" disabled>Open in YouTube</button>}
      </span>
      <p className="small muted" style={{ margin: 0 }}>
        Plays in YouTube's own player, with YouTube's controls and any ads. It keeps playing while you use the rest of Trade Circle, and pauses when you close it, leave the
        site or switch apps, or start talking into a form. It doesn't play in the background or with the screen locked. A YouTube integration; Trade Circle isn't affiliated
        with YouTube.
      </p>
    </section>
  );
}

function Games() {
  const [open, setOpen] = useState(null);
  const choose = (game) => {
    if (game.sound) announceSound("game"); // a game with sound pauses the music so they don't overlap
    setOpen(game);
    count("game_opened", game.id);
  };
  return (
    <section className="stack">
      {open ? (
        <>
          <div className="row-between">
            <h2 style={{ margin: 0 }}>{open.name}</h2>
            <button type="button" className="btn btn-small" onClick={() => setOpen(null)}>Close game</button>
          </div>
          {/* Loaded only once chosen. */}
          <iframe className="game-frame" title={open.name} src={open.src} sandbox="allow-scripts allow-same-origin allow-popups" />
        </>
      ) : (
        <ul className="items">
          {GAMES.map((g) => (
            <li key={g.id} className="card row-between" style={{ margin: 0 }}>
              <span>
                <strong>{g.name}</strong>
                <br />
                <span className="small muted">{g.about}</span>
              </span>
              <button type="button" className="btn btn-primary btn-small" onClick={() => choose(g)}>Play</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ListingCard({ l }) {
  return (
    <li className="card listing-card stack" style={{ margin: 0, gap: 4 }}>
      <span className="label">{l.label}</span>
      <h3 style={{ margin: 0 }}>{l.title}</h3>
      <p className="small" style={{ margin: 0 }}>
        {l.organizer}
        {l.location && ` · ${l.location.label}`}
        {l.distance_miles != null && ` · ${l.distance_miles} mi`}
        {!l.location && l.kind === "public_offer" && " · online or nationwide"}
      </p>
      {l.prize && <p style={{ margin: 0 }}>Prize: {l.prize}</p>}
      {l.details && <p className="item-message small" style={{ margin: 0 }}>{l.details}</p>}
      {l.geography && <p className="small" style={{ margin: 0 }}>Who can enter: {l.geography}</p>}
      {l.restrictions && <p className="small" style={{ margin: 0 }}>Restrictions: {l.restrictions}</p>}
      <p className="small muted" style={{ margin: 0 }}>
        {l.no_end_date ? "No end date published" : `${l.kind === "giveaway" ? "Closes" : "Ends"} ${shortDate(l.expires_on)}`} · last checked {shortDate(l.last_checked_on)}
        {l.needs_recheck && " · details may have changed, check the official page"}
      </p>
      <span className="row">
        <a className="btn btn-small" href={l.official_url} target="_blank" rel="noreferrer nofollow">{l.kind === "giveaway" ? "Enter on the organizer's site" : "See the official offer"}</a>
        {l.rules_url && <a className="btn btn-small" href={l.rules_url} target="_blank" rel="noreferrer nofollow">Official rules</a>}
        <ReportButton targetType="listing" targetId={l.id} label="Report a problem" />
      </span>
    </li>
  );
}

function Listings({ kind }) {
  const [area, setArea] = useState(savedArea.get());
  const [nearby, setNearby] = useState(kind === "public_offer" && !!area.near);
  const [data, setData] = useState(null);
  const [spots, setSpots] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams({ kind });
    if (nearby && area.near) {
      params.set("near", area.near);
      params.set("radius", area.radius);
    }
    api(`/break-room/listings?${params}`).then(setData, (err) => setError(err.message));
    if (kind === "public_offer") {
      const p = new URLSearchParams({ kind: "spot" });
      if (nearby && area.near) {
        p.set("near", area.near);
        p.set("radius", area.radius);
      }
      api(`/posts?${p}`).then((r) => setSpots(r.posts), () => {});
    }
    count(kind === "giveaway" ? "giveaways_viewed" : "deals_viewed");
  }, [kind, nearby, area]);

  return (
    <section className="stack">
      {kind === "giveaway" ? (
        <p className="small muted" style={{ margin: 0 }}>
          Giveaways run by other companies. Each organizer runs its own entries, winners and prizes under its official rules. Trade Circle doesn't collect or pass on your
          details, can't promise prizes, and isn't sponsoring these unless a listing says so.
        </p>
      ) : (
        <p className="small muted" style={{ margin: 0 }}>Public offers anyone can use, copied from the business's own page, plus spots members recommend. Nothing here is a paid placement.</p>
      )}
      {kind === "public_offer" && (
        <form className="row" onSubmit={(e) => { e.preventDefault(); savedArea.set(area); setNearby(true); setArea({ ...area }); }}>
          <input aria-label="ZIP or City, ST" placeholder='ZIP or "City, ST"' value={area.near} onChange={(e) => setArea({ ...area, near: e.target.value })} style={{ flex: 1 }} />
          <select aria-label="Distance" value={area.radius} onChange={(e) => setArea({ ...area, radius: Number(e.target.value) })}>
            {[10, 25, 50, 100].map((r) => <option key={r} value={r}>{r} mi</option>)}
          </select>
          <button className="btn btn-small">Near me</button>
          {nearby && <button type="button" className="linklike small" onClick={() => setNearby(false)}>Show all</button>}
        </form>
      )}
      <Notice error={error} />
      {data === null ? (
        <p className="loading">Loading…</p>
      ) : data.listings.length === 0 ? (
        <p className="empty">{kind === "giveaway" ? "No open giveaways right now." : "No public offers here right now."}</p>
      ) : (
        <ul className="items">{data.listings.map((l) => <ListingCard key={l.id} l={l} />)}</ul>
      )}
      {kind === "public_offer" && (
        <>
          <div className="row-between">
            <h2 style={{ margin: 0 }}>Member recommendations</h2>
            <Link className="btn btn-small" to="/share/spot">Suggest a spot or deal</Link>
          </div>
          {spots && spots.length === 0 && <p className="empty">No suggestions yet. Know a good lunch spot or deal? Share it.</p>}
          {spots && spots.length > 0 && <ul className="items">{spots.map((p) => <PostCard key={p.id} post={p} />)}</ul>}
        </>
      )}
    </section>
  );
}

const BLANK = { kind: "public_offer", title: "", organizer: "", official_url: "", details: "", restrictions: "", prize: "", geography: "", rules_url: "", location: "", expires_on: "", last_checked_on: "" };

// Moderators add listings from the organizer's own page, and recheck them.
function Curate() {
  const [form, setForm] = useState({ ...BLANK, last_checked_on: localToday() });
  const [all, setAll] = useState([]);
  const [msg, setMsg] = useState({});
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const load = () => api("/admin/break-room/listings").then(setAll, () => {});
  useEffect(() => {
    load();
  }, []);

  const body = (f) => ({ ...f, rules_url: f.rules_url || null, expires_on: f.expires_on || null, location: f.location?.label ? f.location.zip || f.location.label : f.location || "" });
  const save = async (event) => {
    event.preventDefault();
    try {
      await api("/admin/break-room/listings", { method: "POST", body: body(form) });
      setForm({ ...BLANK, last_checked_on: localToday() });
      setMsg({ ok: "Added." });
      load();
    } catch (err) {
      setMsg({ error: err.message });
    }
  };
  const recheck = async (l) => {
    const { id, label, no_end_date, needs_recheck, expired, distance_miles, status, created_at, updated_at, ...rest } = l; // eslint-disable-line no-unused-vars
    await api(`/admin/break-room/listings/${id}`, { method: "PUT", body: body({ ...rest, last_checked_on: localToday() }) }).catch((err) => setMsg({ error: err.message }));
    load();
  };

  return (
    <details className="card">
      <summary>Moderators: add and recheck listings</summary>
      <form className="stack" onSubmit={save} style={{ marginTop: 12 }}>
        <Field label="Type">
          <select value={form.kind} onChange={set("kind")}><option value="public_offer">Public offer</option><option value="giveaway">Giveaway</option></select>
        </Field>
        <div className="grid-2">
          <Field label="Title"><input required value={form.title} onChange={set("title")} /></Field>
          <Field label="Business or organizer"><input required value={form.organizer} onChange={set("organizer")} /></Field>
          <Field label="Official page (https)"><input required type="url" value={form.official_url} onChange={set("official_url")} /></Field>
          <Field label={form.kind === "giveaway" ? "Closing date" : "End date (blank if none published)"}><input type="date" required={form.kind === "giveaway"} value={form.expires_on} onChange={set("expires_on")} /></Field>
          <Field label="Last checked on"><input type="date" required value={form.last_checked_on} onChange={set("last_checked_on")} /></Field>
          {form.kind === "public_offer" ? (
            <Field label="Location (blank for online)"><input value={form.location} onChange={set("location")} /></Field>
          ) : (
            <>
              <Field label="Prize"><input required value={form.prize} onChange={set("prize")} /></Field>
              <Field label="Who can enter (from the rules)"><input required value={form.geography} onChange={set("geography")} /></Field>
              <Field label="Official rules link"><input required type="url" value={form.rules_url} onChange={set("rules_url")} /></Field>
            </>
          )}
        </div>
        <Field label="Details, copied from the official page"><textarea value={form.details} onChange={set("details")} /></Field>
        <Field label="Restrictions"><textarea value={form.restrictions} onChange={set("restrictions")} /></Field>
        <Notice error={msg.error} ok={msg.ok} />
        <button className="btn btn-primary">Add listing</button>
      </form>
      <ul className="small">
        {all.map((l) => (
          <li key={l.id}>
            {l.label}: {l.title} · checked {l.last_checked_on}
            {l.expired ? " · expired" : l.needs_recheck ? " · needs recheck" : ""} {!l.expired && <button type="button" className="linklike small" onClick={() => recheck(l)}>Checked today</button>}
          </li>
        ))}
      </ul>
    </details>
  );
}

export default function BreakRoom() {
  const { user } = useAuth();
  const [tab, setTab] = useState("music");
  return (
    <>
      <h1>Break Room</h1>
      <div className="tabs" role="group" aria-label="Show">
        {TABS.map((t) => <button key={t.key} type="button" aria-pressed={tab === t.key} onClick={() => setTab(t.key)}>{t.label}</button>)}
      </div>
      {tab === "music" && <Music />}
      {tab === "games" && <Games />}
      {tab === "deals" && <Listings key="deals" kind="public_offer" />}
      {tab === "giveaways" && <Listings key="giveaways" kind="giveaway" />}
      {user?.role === "admin" && ["deals", "giveaways"].includes(tab) && <Curate />}
    </>
  );
}
