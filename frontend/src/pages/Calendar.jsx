import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, localToday } from "../api.js";
import { Notice } from "../components/Form.jsx";

// Everything with a date, in one place: a month grid on wide screens, a day-by-day list everywhere.
const KINDS = { job: "Job", follow_up: "Follow-up", vacation: "Vacation", handoff: "Handoff", meetup: "Meetup" };
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parse = (s) => new Date(`${s}T12:00:00`);

// Events that span days (vacations, multi-day handoffs) appear on each day they cover.
export function byDay(events) {
  const out = {};
  for (const e of events) {
    const last = e.end || e.date;
    for (let d = parse(e.date); iso(d) <= last; d.setDate(d.getDate() + 1)) (out[iso(d)] ||= []).push(e);
  }
  return out;
}

export default function Calendar() {
  const [month, setMonth] = useState(() => localToday().slice(0, 7));
  const [data, setData] = useState(null);
  const [picked, setPicked] = useState(localToday());
  const [error, setError] = useState("");

  const first = parse(`${month}-01`);
  const gridStart = new Date(first);
  gridStart.setDate(1 - ((first.getDay() + 6) % 7)); // weeks start on Monday
  useEffect(() => {
    setData(null);
    api(`/calendar?start=${iso(gridStart)}&days=42`).then(setData, (err) => setError(err.message));
  }, [month]); // eslint-disable-line react-hooks/exhaustive-deps

  const shift = (n) => {
    const d = new Date(first);
    d.setMonth(d.getMonth() + n);
    setMonth(iso(d).slice(0, 7));
  };
  const days = byDay(data?.events || []);
  const cells = [...Array(42)].map((_, i) => {
    const d = new Date(gridStart);
    d.setDate(d.getDate() + i);
    return iso(d);
  });
  const agenda = cells.filter((d) => d.startsWith(month) && d >= (month === localToday().slice(0, 7) ? localToday() : `${month}-01`) && days[d]);

  return (
    <>
      <h1>Calendar</h1>
      <div className="row-between" style={{ marginBottom: 12 }}>
        <button type="button" className="btn btn-small" aria-label="Previous month" onClick={() => shift(-1)}>←</button>
        <strong>{first.toLocaleDateString("en-US", { month: "long", year: "numeric" })}</strong>
        <button type="button" className="btn btn-small" aria-label="Next month" onClick={() => shift(1)}>→</button>
      </div>
      <Notice error={error} />
      <div className="cal-grid" role="grid" aria-label="Month">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <span key={d} className="cal-head" role="columnheader">{d}</span>)}
        {cells.map((d) => (
          <button key={d} type="button" role="gridcell" aria-pressed={picked === d} aria-label={`${parse(d).toDateString()}${days[d] ? `, ${days[d].length} things` : ""}`}
            className={`cal-cell${d.startsWith(month) ? "" : " cal-out"}${d === localToday() ? " cal-today" : ""}`} onClick={() => setPicked(d)}>
            <span>{parse(d).getDate()}</span>
            <span className="cal-dots">{(days[d] || []).slice(0, 4).map((e, i) => <i key={i} className={`dot dot-${e.kind}`} />)}</span>
          </button>
        ))}
      </div>
      {days[picked] && (
        <section className="card">
          <h2>{parse(picked).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}</h2>
          <Agenda items={days[picked]} />
        </section>
      )}
      <section className="card">
        <h2>Coming up this month</h2>
        {data === null ? (
          <p className="loading">Loading…</p>
        ) : agenda.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>Nothing scheduled. Add dates to <Link to="/jobs">jobs</Link> and follow-ups to see them here.</p>
        ) : (
          agenda.map((d) => (
            <div key={d}>
              <h3 style={{ margin: "10px 0 4px" }}>{parse(d).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</h3>
              <Agenda items={days[d]} />
            </div>
          ))
        )}
      </section>
      <p className="small muted">
        <i className="dot dot-job" /> Jobs · <i className="dot dot-follow_up" /> Follow-ups · <i className="dot dot-handoff" /> Handoffs · <i className="dot dot-meetup" /> Meetups · <i className="dot dot-vacation" /> Vacation
      </p>
    </>
  );
}

function Agenda({ items }) {
  return (
    <ul className="items">
      {items.map((e, i) => (
        <li key={i}>
          <span className={`tag tag-${e.kind}`}>{KINDS[e.kind]}</span> <Link to={e.link}>{e.title}</Link>
          {e.detail && <span className="small muted"> · {e.detail}</span>}
        </li>
      ))}
    </ul>
  );
}
