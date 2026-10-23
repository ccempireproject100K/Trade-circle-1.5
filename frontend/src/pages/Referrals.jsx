import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, dollars, shortDate } from "../api.js";
import { Notice } from "../components/Form.jsx";

// The member's referral link and what it has earned.
const STATUS = { pending: "Clearing", paid: "Paid", clawed_back: "Held (chargeback)", not_eligible: "Not eligible" };

export default function Referrals() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    api("/referrals").then(setData, (err) => setError(err.message));
  }, []);
  if (!data) return <Notice error={error} />;
  const s = data.summary;
  const t = data.terms;
  return (
    <>
      <h1>Referrals</h1>
      <p style={{ marginTop: 0 }}>
        Earn {t.share_percent}% of what each member you refer pays for their plan, for their first {t.months} months of paying.
      </p>
      <section className="card stack">
        <span className="small muted">Your link</span>
        <code className="ref-link">{data.link}</code>
        <span className="row">
          <button type="button" className="btn btn-small" onClick={() => navigator.clipboard?.writeText(data.link).then(() => setCopied(true), () => {})}>{copied ? "Copied" : "Copy link"}</button>
          <a className="btn btn-small" href={`sms:?&body=${encodeURIComponent(`Join me on Trade Circle: ${data.link}`)}`}>Text it</a>
        </span>
      </section>
      {!data.eligible && (
        <p className="notice">You earn from referrals while you're on a paid plan with payments up to date. <Link to="/plan">See plans</Link></p>
      )}
      {s.frozen && (
        <p className="notice notice-error">
          {data.under_review ? "Payouts are on hold while we review recent chargebacks." : "Payouts are on hold until a chargeback on a referred member's payment is resolved."}
        </p>
      )}
      <div className="stats">
        <div className="stat"><strong>{dollars(s.payable)}</strong>ready to pay out</div>
        <div className="stat"><strong>{dollars(s.pending)}</strong>clearing</div>
        <div className="stat"><strong>{dollars(s.paid)}</strong>paid so far</div>
        {s.clawed_back > 0 && <div className="stat"><strong>{dollars(s.clawed_back)}</strong>held for chargebacks</div>}
      </div>
      <section className="card">
        <h2>People you referred ({data.referred.length})</h2>
        {data.referred.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>No one yet. Share your link with contractors you know.</p>
        ) : (
          <ul className="items">
            {data.referred.map((r, i) => (
              <li key={i} className="row-between">
                <span>{r.business_name}</span>
                <span className="small muted">{r.earning_until ? `earning until ${shortDate(r.earning_until)}` : r.paying ? "paying" : "on the free plan"}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {data.earnings.length > 0 && (
        <section className="card">
          <h2>Earnings</h2>
          <ul className="items">
            {data.earnings.map((e, i) => (
              <li key={i} className="row-between">
                <span>{e.month} · {e.member} paid {dollars(e.revenue_cents)}</span>
                <span>{dollars(e.share_cents)} <span className="small muted">{STATUS[e.status]}</span></span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <details className="card">
        <summary>How it works</summary>
        <ul className="small">
          <li>You earn on what referred members actually pay, after refunds. Their free months don't count.</li>
          <li>Earnings clear after {t.clearing_days} days, in case of refunds or chargebacks, before they're paid out.</li>
          <li>If a referred member's payment is charged back, that month's earnings are held and payouts pause until it's resolved. If the chargeback is reversed, they're released; if it stands, they're withheld.</li>
          <li>{t.review_chargebacks} chargebacks within six months starts a manual review.</li>
          <li>You need to be on a paid plan with payments up to date to earn.</li>
        </ul>
      </details>
    </>
  );
}
