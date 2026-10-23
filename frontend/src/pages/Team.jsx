import { useEffect, useState } from "react";
import { acting, api, label, shortDate } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Field, Notice } from "../components/Form.jsx";

// Optional teammates. Solo contractors can ignore this page entirely.
const ACTIONS = {
  invited: "invited", accepted: "accepted the invitation", declined: "declined the invitation", changed_access: "changed access for",
  removed: "removed", left: "left the team", shown_on_profile: "showed their link on the profile", hidden_from_profile: "hid their link from the profile",
};

function PermissionPicker({ catalog, value, onChange }) {
  return (
    <fieldset className="checks">
      <legend className="field-label">Can</legend>
      {Object.entries(catalog).map(([k, text]) => (
        <label key={k}><input type="checkbox" checked={value.includes(k)} onChange={() => onChange(value.includes(k) ? value.filter((x) => x !== k) : [...value, k])} /> {text}</label>
      ))}
    </fieldset>
  );
}

function Manage({ businessId, meta }) {
  const [team, setTeam] = useState(null);
  const [form, setForm] = useState({ email: "", role: "contributor", permissions: ["portfolio"] });
  const [error, setError] = useState("");
  const load = () => api(`/team/${businessId}/members`).then(setTeam, (err) => setError(err.message));
  useEffect(() => {
    load();
  }, [businessId]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (fn) => {
    setError("");
    try {
      await fn();
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  if (!team) return <Notice error={error} />;
  const owner = team.you_are === "owner";
  return (
    <section className="stack">
      <h2 style={{ margin: 0 }}>{owner ? "Your team" : `${team.business.business_name} team`}</h2>
      <form className="card stack" onSubmit={(e) => { e.preventDefault(); run(() => api(`/team/${businessId}/invite`, { method: "POST", body: form })).then(() => setForm({ ...form, email: "" })); }}>
        <p className="small muted" style={{ margin: 0 }}>Teammates sign in with their own Trade Circle account and must accept before they can do anything. Billing, alerts, handoffs and ownership always stay with the owner.</p>
        <div className="grid-2">
          <Field label="Their Trade Circle email"><input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Role">
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="contributor">Contributor: only what you tick</option>
              {owner && <option value="admin">Admin: everything below, and manages contributors</option>}
            </select>
          </Field>
        </div>
        {form.role === "contributor" && <PermissionPicker catalog={meta.permissions} value={form.permissions} onChange={(permissions) => setForm({ ...form, permissions })} />}
        <button className="btn btn-primary">Send invitation</button>
      </form>
      <Notice error={error} />
      <ul className="items">
        {team.members.map((m) => (
          <li key={m.user_id} className="card stack" style={{ margin: 0, gap: 6 }}>
            <div className="row-between">
              <strong>{m.member.business_name}</strong>
              <span className="tag">{m.status === "invited" ? "Invited" : label(m.role)}</span>
            </div>
            {m.role === "contributor" ? (
              <PermissionPicker catalog={meta.permissions} value={m.permissions} onChange={(permissions) => run(() => api(`/team/${businessId}/members/${m.user_id}`, { method: "PATCH", body: { permissions } }))} />
            ) : (
              <p className="small muted" style={{ margin: 0 }}>All business permissions</p>
            )}
            <span className="row">
              {owner && <button type="button" className="btn btn-small" onClick={() => run(() => api(`/team/${businessId}/members/${m.user_id}`, { method: "PATCH", body: { role: m.role === "admin" ? "contributor" : "admin" } }))}>{m.role === "admin" ? "Make contributor" : "Make admin"}</button>}
              {(owner || m.role === "contributor") && <button type="button" className="btn btn-small btn-danger" onClick={() => window.confirm(`Remove ${m.member.business_name}?`) && run(() => api(`/team/${businessId}/members/${m.user_id}`, { method: "DELETE" }))}>Remove</button>}
            </span>
          </li>
        ))}
      </ul>
      {team.log.length > 0 && (
        <details className="card">
          <summary>Change history</summary>
          <ul className="small">{team.log.map((e, i) => <li key={i}>{shortDate(e.at)}: {e.actor} {ACTIONS[e.action] || e.action}{["invited", "changed_access", "removed"].includes(e.action) ? ` ${e.target}` : ""}</li>)}</ul>
        </details>
      )}
    </section>
  );
}

export default function Team() {
  const { user } = useAuth();
  const [meta, setMeta] = useState(null);
  const [mine, setMine] = useState(null);
  const [error, setError] = useState("");
  const load = () => api("/team/memberships").then(setMine, (err) => setError(err.message));
  useEffect(() => {
    api("/team/meta").then(setMeta, () => {});
    load();
  }, []);

  const run = async (fn) => {
    setError("");
    try {
      await fn();
      load();
    } catch (err) {
      setError(err.message);
    }
  };
  const workFor = (b) => {
    acting.set({ id: b.business_id, name: b.business.business_name });
    window.location.assign("/app/");
  };

  if (!meta || !mine) return <Notice error={error} />;
  return (
    <>
      <h1>Team</h1>
      <p className="small muted" style={{ marginTop: 0 }}>Optional. Working on your own? You don't need to set anything up here.</p>
      <Notice error={error} />
      {mine.invitations.map((b) => (
        <div key={b.business_id} className="card stack">
          <p style={{ margin: 0 }}><strong>{b.business.business_name}</strong> invited you as {b.role === "admin" ? "an admin" : "a contributor"}.</p>
          <p className="small" style={{ margin: 0 }}>You'd be able to: {b.permissions.length ? b.permissions.map((p) => meta.permissions[p]).join("; ") : "nothing yet"}.</p>
          <span className="row">
            <button type="button" className="btn btn-primary btn-small" onClick={() => run(() => api(`/team/invitations/${b.business_id}/accept`, { method: "POST" }))}>Accept</button>
            <button type="button" className="btn btn-small" onClick={() => run(() => api(`/team/invitations/${b.business_id}/decline`, { method: "POST" }))}>Decline</button>
          </span>
        </div>
      ))}
      {mine.businesses.map((b) => (
        <div key={b.business_id} className="card stack">
          <p style={{ margin: 0 }}><strong>{b.business.business_name}</strong> · {label(b.role)}</p>
          <p className="small" style={{ margin: 0 }}>{b.permissions.map((p) => meta.permissions[p]).join("; ") || "No permissions yet"}</p>
          <label className="check" style={{ alignItems: "center" }}>
            <input type="checkbox" checked={b.show_on_profile} onChange={(e) => run(() => api(`/team/memberships/${b.business_id}/visibility`, { method: "PUT", body: { show_on_profile: e.target.checked } }))} />
            <span className="small">Show that I'm on this team on their public profile</span>
          </label>
          <span className="row">
            <button type="button" className="btn btn-small" onClick={() => workFor(b)}>Work for this business</button>
            <button type="button" className="btn btn-small btn-danger" onClick={() => window.confirm("Leave this team?") && run(() => api(`/team/${b.business_id}/members/${user.id}`, { method: "DELETE" }))}>Leave</button>
          </span>
          {b.role === "admin" && <Manage businessId={b.business_id} meta={meta} />}
        </div>
      ))}
      <Manage businessId={user.id} meta={meta} />
    </>
  );
}
