import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Notice } from "../components/Form.jsx";

// Plans and subscription billing. Payment happens on Stripe's own pages; the plan changes when Stripe confirms.
const price = (cents) => (cents ? `$${(cents / 100).toFixed(0)}/month` : "Free");
const endDate = (secs) => (secs ? new Date(secs * 1000).toLocaleDateString("en-US", { month: "long", day: "numeric" }) : "");

export default function Plan() {
  const { refresh } = useAuth();
  const [params] = useSearchParams();
  const [billing, setBilling] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const returning = params.get("checkout") === "done";

  const load = () => api("/billing").then((b) => (setBilling(b), b), (err) => setError(err.message));
  useEffect(() => {
    let tries = 0;
    let timer;
    const poll = async () => {
      const b = await load();
      // Back from Stripe: the plan updates once Stripe confirms, usually within seconds.
      if (returning && b && !b.subscribed && tries++ < 10) timer = setTimeout(poll, 2000);
      else if (returning && b?.subscribed) {
        setOk("You're all set. Thanks for subscribing!");
        refresh?.();
      }
    };
    poll();
    return () => clearTimeout(timer);
  }, [returning]); // eslint-disable-line react-hooks/exhaustive-deps

  const go = async (path, body, label) => {
    setBusy(label);
    setError("");
    setOk("");
    try {
      const res = await api(path, { method: "POST", body });
      if (res.url) {
        window.location.assign(res.url);
        return;
      }
      setBilling(res);
      refresh?.();
      setOk(body?.plan === "free" ? "Your plan will end at the close of this billing period." : "Your plan has been updated.");
    } catch (err) {
      setError(err.message);
    }
    setBusy("");
  };

  if (!billing) return <Notice error={error} />;
  const current = billing.plan;
  return (
    <>
      <h1>Plans and billing</h1>
      {returning && !billing.subscribed && !error && <p className="notice notice-ok" role="status">Confirming your payment with Stripe…</p>}
      <Notice error={error} ok={ok} />
      {billing.payment_problem && (
        <p className="notice notice-error">
          Your last payment didn't go through. Stripe will try again; update your card so you keep your plan.{" "}
          <button type="button" className="linklike" onClick={() => go("/billing/portal", undefined, "portal")}>Update card</button>
        </p>
      )}
      {billing.cancel_at_period_end && (
        <p className="notice">
          Your {billing.plans.find((p) => p.key === current)?.name} plan ends on {endDate(billing.current_period_end)}. After that you're on Free; nothing you've made is deleted.
        </p>
      )}
      {!billing.ready && <p className="notice">Paid plans aren't open yet. You'll be able to upgrade here once billing is set up.</p>}
      <div className="plan-grid">
        {billing.plans.map((p) => {
          const mine = p.key === current;
          return (
            <section key={p.key} className={`card stack plan-card${mine ? " plan-current" : ""}`}>
              <div className="row-between">
                <h2 style={{ margin: 0 }}>{p.name}</h2>
                {mine && <span className="tag">Current plan</span>}
              </div>
              <p style={{ margin: 0, fontSize: "1.4rem", fontWeight: 700 }}>{price(p.price_cents)}</p>
              <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                {p.key !== "free" && <li>Everything in {p.key === "starter" ? "Free" : "Starter"}</li>}
                {p.includes.map((f) => <li key={f}>{f}</li>)}
                {p.adds.map((f) => (
                  <li key={f.key}>{f.label}{!f.built && <span className="muted"> (coming later)</span>}</li>
                ))}
              </ul>
              {!mine && billing.ready && p.key !== "free" && !billing.subscribed && (
                <button type="button" className="btn btn-primary" disabled={!!busy} onClick={() => go("/billing/checkout", { plan: p.key }, p.key)}>
                  {busy === p.key ? "Opening Stripe…" : `Choose ${p.name}`}
                </button>
              )}
              {!mine && billing.ready && billing.subscribed && (p.key !== "free" || !billing.cancel_at_period_end) && (
                <button type="button" className="btn" disabled={!!busy} onClick={() => (p.key !== "free" || window.confirm("Cancel at the end of this billing period?")) && go("/billing/change", { plan: p.key }, p.key)}>
                  {p.key === "free" ? "Cancel paid plan" : `Switch to ${p.name}`}
                </button>
              )}
              {mine && billing.cancel_at_period_end && p.key !== "free" && (
                <button type="button" className="btn btn-primary" disabled={!!busy} onClick={() => go("/billing/change", { plan: p.key }, p.key)}>Keep {p.name}</button>
              )}
            </section>
          );
        })}
      </div>
      {billing.subscribed && (
        <p className="small">
          <button type="button" className="linklike" onClick={() => go("/billing/portal", undefined, "portal")}>Card, invoices and receipts</button> are managed on Stripe's secure page.
        </p>
      )}
      <p className="small muted">Prices are per month. Payments are processed by Stripe; Trade Circle never sees your card number. Switching plans is prorated.</p>
    </>
  );
}
