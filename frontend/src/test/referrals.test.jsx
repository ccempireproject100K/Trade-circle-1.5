import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Referrals from "../pages/Referrals.jsx";
import { fakeApi } from "./fakeApi.js";

const DATA = {
  code: "ABCD2345", link: "https://tc/app/signup?ref=ABCD2345", eligible: true, under_review: false,
  summary: { pending: 225, available: 450, paid: 900, clawed_back: 0, adjustments: 0, payable: 450, frozen: false, clearing_days: 60 },
  referred: [{ business_name: "Bravo HVAC", paying: true, earning_until: "2027-04-20T00:00:00Z", joined: "2026-10-01T00:00:00Z" }],
  earnings: [{ month: "2026-10", member: "Bravo HVAC", revenue_cents: 900, share_cents: 225, status: "pending", earned_at: "2026-10-20T00:00:00Z" }],
  terms: { share_percent: 25, months: 6, clearing_days: 60, review_chargebacks: 3 },
};

describe("Referrals", () => {
  it("shows the link, totals and each earning", async () => {
    fakeApi({ "GET /referrals": DATA });
    render(<MemoryRouter><Referrals /></MemoryRouter>);
    expect(await screen.findByText("https://tc/app/signup?ref=ABCD2345")).toBeInTheDocument();
    expect(screen.getByText(/Earn 25% of what each member you refer pays/)).toBeInTheDocument();
    expect(screen.getByText("$4.50")).toBeInTheDocument();
    expect(screen.getByText(/2026-10 · Bravo HVAC paid \$9\.00/)).toBeInTheDocument();
  });

  it("explains holds and eligibility", async () => {
    fakeApi({ "GET /referrals": { ...DATA, eligible: false, summary: { ...DATA.summary, frozen: true, payable: 0 } } });
    render(<MemoryRouter><Referrals /></MemoryRouter>);
    expect(await screen.findByText(/while you're on a paid plan/)).toBeInTheDocument();
    expect(screen.getByText(/Payouts are on hold until a chargeback/)).toBeInTheDocument();
  });
});
