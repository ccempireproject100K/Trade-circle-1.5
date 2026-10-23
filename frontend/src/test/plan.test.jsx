import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AuthStubProvider } from "../auth.jsx";
import Plan from "../pages/Plan.jsx";
import { fakeApi } from "./fakeApi.js";

const PLANS = [
  { key: "free", name: "Free", price_cents: 0, includes: ["Business page"], adds: [] },
  { key: "starter", name: "Starter", price_cents: 300, includes: [], adds: [{ key: "lead_alerts", label: "Instant lead alerts", built: true }, { key: "google_business_profile", label: "Google Business Profile sync", built: false }] },
  { key: "full", name: "Full", price_cents: 900, includes: [], adds: [] },
];
const BILLING = { ready: true, plan: "free", status: null, subscribed: false, current_period_end: null, cancel_at_period_end: false, payment_problem: false, plans: PLANS };
const view = () => render(<AuthStubProvider><MemoryRouter><Plan /></MemoryRouter></AuthStubProvider>);

describe("Plan", () => {
  it("lists prices and marks features that aren't built yet", async () => {
    fakeApi({ "GET /billing": BILLING });
    view();
    expect(await screen.findByText("$3/month")).toBeInTheDocument();
    expect(screen.getByText("(coming later)")).toBeInTheDocument();
    expect(screen.getByText("Current plan")).toBeInTheDocument();
  });

  it("sends members to Stripe's checkout page to subscribe", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const calls = fakeApi({ "GET /billing": BILLING, "POST /billing/checkout": { url: "https://checkout.stripe.test/1" } });
    view();
    await userEvent.click(await screen.findByRole("button", { name: "Choose Full" }));
    expect(calls.find((c) => c.method === "POST").body).toEqual({ plan: "full" });
    expect(assign).toHaveBeenCalledWith("https://checkout.stripe.test/1");
    vi.unstubAllGlobals();
  });

  it("says plainly when billing isn't open and offers no buy button", async () => {
    fakeApi({ "GET /billing": { ...BILLING, ready: false } });
    view();
    expect(await screen.findByText(/Paid plans aren't open yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Choose/ })).not.toBeInTheDocument();
  });

  it("warns about a failed payment and a pending cancellation", async () => {
    fakeApi({ "GET /billing": { ...BILLING, plan: "starter", subscribed: true, payment_problem: true, cancel_at_period_end: true, current_period_end: 1800000000 } });
    view();
    expect(await screen.findByText(/Your last payment didn't go through/)).toBeInTheDocument();
    expect(screen.getByText(/Your Starter plan ends on/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep Starter" })).toBeInTheDocument();
  });
});
