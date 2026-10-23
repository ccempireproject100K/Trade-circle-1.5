import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, localToday, shortDate } from "../api.js";
import { useAuth } from "../auth.jsx";
import { PostCard } from "../components/Community.jsx";
import { Notice } from "../components/Form.jsx";

const PLAN_NAMES = { free: "Free", starter: "Starter", full: "Full" };

// The member front door: the feed is the main column, like other social sites.
// Work signals live in a compact strip and the side cards, one tap away.
export default function Home() {
  const { user, profile } = useAuth();
  const [leads, setLeads] = useState(null);
  const [jobs, setJobs] = useState(null);
  const [handoffsWaiting, setHandoffsWaiting] = useState(0);
  const [activity, setActivity] = useState(null);
  const [marketplace, setMarketplace] = useState(null);
  const [posts, setPosts] = useState(null);
  const [feedError, setFeedError] = useState("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api("/inbox"), api("/jobs")])
      .then(([quotes, allJobs]) => {
        setLeads(quotes);
        setJobs(allJobs);
      })
      .catch((err) => setError(err.message));
    api("/notifications").then(setActivity).catch(() => {});
    api("/handoffs")
      .then((list) => setHandoffsWaiting(list.filter((h) => h.direction === "incoming" && h.status === "proposed").length))
      .catch(() => {});
    api("/marketplace?radius=30").then(setMarketplace).catch(() => {});
    api("/posts")
      .then((r) => setPosts(r.posts))
      .catch((err) => setFeedError(err.message));
  }, []);

  const pageUrl = `${window.location.origin}/p/${profile.slug}`;
  const today = localToday();
  const newLeads = leads?.filter((q) => q.status === "waiting" && q.source !== "manual").length ?? "–";
  const followUpsDue = leads?.filter((q) => q.follow_up_on && q.follow_up_on <= today && ["waiting", "followed_up"].includes(q.status)).length ?? "–";
  const openJobs = jobs ? jobs.filter((j) => !["done", "cancelled", "handed_off"].includes(j.status)).length : "–";
  const marketplaceJobs = marketplace ? (marketplace.needs_area ? "Set area" : marketplace.requests.length) : "–";
  const upcoming = (jobs || [])
    .filter((j) => j.scheduled_on && j.scheduled_on >= today && !["done", "cancelled", "handed_off"].includes(j.status))
    .sort((a, b) => a.scheduled_on.localeCompare(b.scheduled_on))
    .slice(0, 3);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(pageUrl);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <>
      <h1>Hi, {profile.business_name}</h1>
      <Notice error={error} />
      <p className="small" style={{ margin: "0 0 16px" }}>
        <Link to="/helper">Ask the AI helper</Link> · <Link to="/supplies/parts">Part lookup</Link> · <Link to="/rates">Pay &amp; rates</Link> · <Link to="/break-room">Break Room</Link>
      </p>

      {handoffsWaiting > 0 && (
        <Link className="notice notice-ok" to="/handoffs" style={{ display: "block", marginBottom: 16, textDecoration: "none" }}>
          {handoffsWaiting} {handoffsWaiting === 1 ? "member is" : "members are"} asking you to cover a job. Review →
        </Link>
      )}

      <div className="home-layout">
        <section className="card stack home-mypage">
          <h2 style={{ margin: 0 }}>My page</h2>
          {profile.published === false ? (
            <>
              <p className="notice notice-error" style={{ margin: 0 }}>Your page is hidden — customers can&apos;t see it.</p>
              <Link className="btn btn-primary" to="/profile">Turn it on in Profile</Link>
            </>
          ) : (
            <p className="small muted" style={{ margin: 0, wordBreak: "break-all" }}>{pageUrl}</p>
          )}
          <div className="row">
            <a className="btn btn-primary" href={`/p/${profile.slug}`} target="_blank" rel="noreferrer">View my page</a>
            <Link className="btn" to="/profile">Edit profile</Link>
            <button type="button" className="btn" onClick={copy}>{copied ? "Copied" : "Copy link"}</button>
          </div>
        </section>

        <div className="work-strip home-strip" aria-label="Work at a glance">
          <Link className="stat" to="/inbox">
            <strong>{newLeads}</strong>
            new quote {newLeads === 1 ? "request" : "requests"}
          </Link>
          <Link className="stat" to="/inbox">
            <strong>{followUpsDue}</strong>
            follow-ups due
          </Link>
          <Link className="stat" to="/jobs">
            <strong>{openJobs}</strong>
            open jobs
          </Link>
          <Link className="stat" to="/marketplace">
            <strong>{marketplaceJobs}</strong>
            marketplace jobs
          </Link>
        </div>

        <section className="home-feed">
          <div className="row-between" style={{ marginBottom: 12 }}>
            <h2 style={{ margin: 0 }}>Your feed</h2>
            <Link className="small" to="/community">Community — search &amp; filters →</Link>
          </div>
          <section className="card stack" style={{ gap: 10 }}>
            <Link className="composer-box" to="/share">Share a project, a lesson, or a question…</Link>
            <p className="small" style={{ margin: 0 }}>
              <Link to="/share/project">Project</Link> · <Link to="/share/lesson">Lesson</Link> · <Link to="/share/equipment">Equipment</Link> · <Link to="/share/meetup">Meetup</Link> · <Link to="/share/opening">Job opening</Link>
            </p>
          </section>
          {feedError ? (
            <p className="empty">Couldn&apos;t load the feed. <Link to="/community">Open the Community page</Link></p>
          ) : posts === null ? (
            <p className="loading">Loading…</p>
          ) : posts.length === 0 ? (
            <section className="card stack">
              <h2 style={{ margin: 0 }}>Welcome to the Circle</h2>
              <p style={{ margin: 0 }}>
                This is where contractors share projects, lessons and questions — and where work finds you. Nothing here yet, so yours can be the first post everyone sees.
              </p>
              <div className="row">
                <Link className="btn btn-primary" to="/share">Share your first post</Link>
                <Link className="btn" to="/profile">Complete your profile</Link>
                <Link className="btn" to="/share/meetup">Host a meetup</Link>
              </div>
            </section>
          ) : (
            <ul className="items">{posts.map((p) => <PostCard key={p.id} post={p} />)}</ul>
          )}
        </section>

        {activity && activity.items.length > 0 && (
          <section className="card stack home-activity">
            <div className="row-between">
              <h2 style={{ margin: 0 }}>Activity{activity.unread ? ` (${activity.unread} new)` : ""}</h2>
              {activity.unread > 0 && (
                <button type="button" className="linklike small" onClick={() => api("/notifications/read", { method: "POST" }).then(() => setActivity({ ...activity, unread: 0, items: activity.items.map((n) => ({ ...n, read: true })) }))}>
                  Mark all read
                </button>
              )}
            </div>
            <ul className="items" style={{ gap: 8 }}>
              {activity.items.slice(0, 5).map((n) => (
                <li key={n.id} className="small" style={{ fontWeight: n.read ? 400 : 700 }}>
                  <Link to={n.link}>{n.text}</Link> <span className="muted">· {shortDate(n.created_at)}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="card home-coming">
          <h2>Coming up</h2>
          {upcoming.length ? (
            <ul className="items">
              {upcoming.map((job) => (
                <li key={job.id} className="row-between">
                  <span><strong>{job.title}</strong>{job.customer_name && ` · ${job.customer_name}`}</span>
                  <span className="muted">{shortDate(job.scheduled_on)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted" style={{ margin: 0 }}>No scheduled jobs. <Link to="/jobs">Add one</Link></p>
          )}
        </section>

        <section className="card home-plan">
          <div className="row-between">
            <h2 style={{ margin: 0 }}>Plan: {PLAN_NAMES[user.tier] || user.tier}</h2>
            <Link className="small" to="/plan">{user.tier === "free" ? "See plans" : "Manage plan"}</Link>
          </div>
          {user.tier === "free" ? (
            <p className="muted" style={{ margin: 0 }}>
              On the free plan, new leads wait here under Work → Follow-ups. Paid plans add email alerts and a daily text allowance.
            </p>
          ) : (
            <p className="muted" style={{ margin: 0 }}>
              Get your leads by email and your daily rundown by text: <Link to="/settings">set up alerts</Link>.
            </p>
          )}
        </section>
      </div>
    </>
  );
}
