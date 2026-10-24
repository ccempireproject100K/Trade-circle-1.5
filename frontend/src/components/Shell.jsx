import { NavLink, useLocation } from "react-router-dom";
import { acting } from "../api.js";
import { useAuth } from "../auth.jsx";

// Community comes first: Trade Circle is a network for contractors, with work tools alongside.
const NAV = [
  { to: "/", label: "Home", match: ["/"] },
  { to: "/community", label: "Community", match: ["/community", "/posts", "/share", "/mentoring", "/messages"] },
  { to: "/supplies", label: "Supplies", match: ["/supplies"] },
  { to: "/inbox", label: "Work", match: ["/inbox", "/marketplace", "/jobs", "/calendar", "/time", "/quotes", "/handoffs", "/payments", "/rates"] },
  { to: "/profile", label: "Profile", match: ["/profile", "/photos", "/team", "/referrals", "/reviews"] },
];

const isActive = (item, path) => item.match.some((m) => (m === "/" ? path === "/" : path === m || path.startsWith(`${m}/`)));

export default function Shell({ children }) {
  const { profile } = useAuth();
  const { pathname } = useLocation();
  return (
    <div className="shell">
      <div className="topbar-wrap">
        <header className="topbar">
          <span className="brand">Trade Circle</span>
          <span className="topbar-name">{profile?.business_name}</span>
          <NavLink to="/break-room" className="topbar-link">Break Room</NavLink>
          <NavLink to="/messages" className="topbar-link">Messages</NavLink>
          <NavLink to="/settings" className="topbar-link">Settings</NavLink>
        </header>
        <div className="brand-stripe" aria-hidden="true" />
      </div>
      {acting.get() && (
        <p className="acting-bar" role="status">
          Working for <strong>{acting.get().name}</strong> ·{" "}
          <button type="button" className="linklike" onClick={() => { acting.set(null); window.location.reload(); }}>Back to my account</button>
        </p>
      )}
      <main className="content">{children}</main>
      <nav className="tabbar" aria-label="Main">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} className={() => (isActive(item, pathname) ? "active" : "")} aria-current={isActive(item, pathname) ? "page" : undefined}>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

// Second-level tabs inside a section, such as Leads | Jobs | Handoffs.
export function SubNav({ items }) {
  return (
    <nav className="subnav" aria-label="Section">
      {items.map((item) => (
        <NavLink key={item.to} to={item.to} end>
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

export const WORK_NAV = [
  { to: "/inbox", label: "Follow-ups" },
  { to: "/marketplace", label: "Marketplace" },
  { to: "/jobs", label: "Jobs" },
  { to: "/calendar", label: "Calendar" },
  { to: "/time", label: "Time" },
  { to: "/quotes", label: "Quotes" },
  { to: "/handoffs", label: "Handoffs" },
  { to: "/payments", label: "Payments" },
  { to: "/rates", label: "Rates" },
];

export const PROFILE_NAV = [
  { to: "/profile", label: "Profile" },
  { to: "/photos", label: "Photos" },
  { to: "/team", label: "Team" },
  { to: "/referrals", label: "Referrals" },
  { to: "/reviews", label: "Reviews" },
];
