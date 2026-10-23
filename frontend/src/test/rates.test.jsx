import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Rates, { calculate } from "../pages/Rates.jsx";
import { fakeApi } from "./fakeApi.js";

const META = { trades: ["electrician", "plumber"], roles: ["journeyman"], experience: ["0-2"], benefits: ["health"], min_contributors: 5, min_age_days: 90, published: true };

describe("Pay & rates", () => {
  const GOV = {
    period: "May 2025", source: "U.S. Bureau of Labor Statistics, Occupational Employment and Wage Statistics", source_url: "https://www.bls.gov/oes/",
    area: "Austin-Round Rock-San Marcos, TX", state: "TX", note: "Not what contractors charge customers.",
    occupations: [{ code: "47-2111", title: "Electricians", where: "area", employment: 7340, mean: 29.25, p10: 18.87, p25: 22.97, median: 29.03, p75: 35.25, p90: 37.9, capped: [] }],
  };
  const pick = async (place = "78701") => {
    await userEvent.type(await screen.findByLabelText("ZIP or City, ST"), place);
    await userEvent.click(screen.getByRole("button", { name: "Show" }));
  };

  it("shows government wages and member figures as separate sections", async () => {
    fakeApi({ "GET /rates/meta": META, "GET /rates/government?trade=electrician&location=78701": GOV, "GET /rates/compare?kind=wage&trade=electrician&location=78701": { published: false } });
    render(<MemoryRouter><Rates /></MemoryRouter>);
    await pick();
    expect(await screen.findByText("Government wage data")).toBeInTheDocument();
    expect(await screen.findByText(/Austin-Round Rock-San Marcos, TX · May 2025/)).toBeInTheDocument();
    expect(screen.getByText(/Median \$29\.03\/hr · middle half \$22\.97 to \$35\.25/)).toBeInTheDocument();
    expect(screen.getByText("From Trade Circle members")).toBeInTheDocument();
    expect(await screen.findByText(/Not published yet/)).toBeInTheDocument();
  });

  it("shows member ranges with sample size, source and the informational note once published", async () => {
    fakeApi({
      "GET /rates/meta": META,
      "GET /rates/government?trade=electrician&location=78701": GOV,
      "GET /rates/compare?kind=wage&trade=electrician&location=78701": {
        published: true, insufficient_data: false, trade: "electrician", area: "TX (statewide)", sample_size: 7, oldest_month: "2026-05", newest_month: "2026-07",
        metrics: { base_hourly: { low: 26, median: 30, high: 34, sample_size: 7 } }, benefits: { health: 57 },
        source: "Self-reported by Trade Circle members. Not verified.", disclaimer: "For information only.",
      },
    });
    render(<MemoryRouter><Rates /></MemoryRouter>);
    await pick();
    expect(await screen.findByText(/7 members · shared 2026-05 to 2026-07 · Self-reported/)).toBeInTheDocument();
    expect(screen.getByText(/middle half \$26 to \$34, median \$30/)).toBeInTheDocument();
    expect(screen.getByText("For information only.")).toBeInTheDocument();
  });

  it("lists outside estimates with their source and lets members add one unchanged", async () => {
    const calls = fakeApi({
      "GET /rates/meta": META,
      "GET /rates/estimates?trade=electrician&location=78701": { estimates: [{ id: "e1", trade: "electrician", service: "Hourly labor rate", unit: "hour", low: 50, high: 100, scope: "national", place: null, source_name: "HomeGuide", source_url: "https://homeguide.com/x", checked_on: "2026-10-20", stale: false, added_by: "Alpha", updated_by: null, changes: 0, note: "" }] },
      "GET /rates/compare?kind=billing&trade=electrician&location=78701": { published: false },
      "POST /rates/estimates": [201, {}],
    });
    render(<MemoryRouter><Rates /></MemoryRouter>);
    await userEvent.selectOptions(await screen.findByLabelText("Compare"), "billing");
    await pick();
    expect(await screen.findByText(/\$50 to \$100 per hour/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "HomeGuide" })).toHaveAttribute("href", "https://homeguide.com/x");
    expect(screen.queryByText("Government wage data")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add one" }));
    expect(screen.getByText(/Don't adjust the numbers/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("What it covers"), "Panel upgrade");
    await userEvent.selectOptions(screen.getByLabelText("Unit"), "project");
    await userEvent.type(screen.getByLabelText("Low ($)"), "1300");
    await userEvent.type(screen.getByLabelText("High ($)"), "3000");
    await userEvent.type(screen.getByLabelText("Source name"), "Angi");
    await userEvent.type(screen.getByLabelText("Link to the page (https)"), "https://www.angi.com/x");
    await userEvent.click(screen.getByRole("button", { name: "Add estimate" }));
    const sent = calls.find((c) => c.method === "POST").body;
    expect(sent).toMatchObject({ trade: "electrician", service: "Panel upgrade", unit: "project", low: 1300, high: 3000, scope: "national", source_name: "Angi" });
  });

  it("calculates on the device without calling the server", async () => {
    const calls = fakeApi({ "GET /rates/meta": META });
    render(<MemoryRouter><Rates /></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: "Cost calculator" }));
    const before = calls.length;
    await userEvent.type(screen.getByLabelText(/Yearly overhead/), "24000");
    await userEvent.type(screen.getByLabelText(/pay yourself/), "60000");
    // 48 weeks × 30 hours = 1,440 hours; 84,000 / 1,440 = 58.33
    expect(screen.getByText("Charge at least $58.33 per hour")).toBeInTheDocument();
    expect(screen.getByText(/A 25% markup is only a 20% margin/)).toBeInTheDocument();
    expect(screen.getByText(/margin 20\.0%/)).toBeInTheDocument();
    expect(calls.length).toBe(before);
  });

  it("turns a margin into a rate and the matching markup", () => {
    const r = calculate({ overhead: 20000, pay: 60000, hours: 1600, margin: 20 });
    expect(r.breakEven).toBe(50);
    expect(r.rate).toBeCloseTo(62.5);
    expect(r.markup).toBeCloseTo(25);
  });
});

describe("Community corrections", () => {
  const EST = { id: "e1", trade: "electrician", service: "Hourly labor rate", unit: "hour", low: 50, high: 100, scope: "national", place: null, source_name: "HomeGuide", source_url: "https://homeguide.com/x", checked_on: "2026-10-20", stale: false, added_by: "Alpha", updated_by: null, changes: 0, note: "", open_corrections: 1, mine: false };
  const COR = { id: "c1", estimate: { id: "e1", service: "Hourly labor rate", trade: "electrician", source_name: "HomeGuide", source_url: "https://homeguide.com/x" }, kind: "change", changes: { low: { from: 50, to: 60 } }, reason: "Page now says $60", status: "open", proposed_by: "Bravo", mine: false, my_vote: null, confirms: 1, disputes: 0, needed: 2, notes: [], created_at: "2026-10-23T00:00:00Z" };
  const routes = (extra = {}) => ({
    "GET /rates/meta": META,
    "GET /rates/estimates?trade=electrician&location=78701": { estimates: [EST] },
    "GET /rates/estimates/corrections/open?trade=electrician&location=78701": [COR],
    "GET /rates/compare?kind=billing&trade=electrician&location=78701": { published: false },
    ...extra,
  });
  const open = async () => {
    render(<MemoryRouter><Rates /></MemoryRouter>);
    await userEvent.selectOptions(await screen.findByLabelText("Compare"), "billing");
    await userEvent.type(screen.getByLabelText("ZIP or City, ST"), "78701");
    await userEvent.click(screen.getByRole("button", { name: "Show" }));
  };

  it("shows waiting corrections and lets members confirm after checking the source", async () => {
    const calls = fakeApi(routes({ "POST /rates/estimates/corrections/c1/vote": { ...COR, confirms: 2, status: "applied" } }));
    await open();
    expect(await screen.findByText("Community corrections")).toBeInTheDocument();
    expect(await screen.findByText(/1 of 2 confirmations needed/)).toBeInTheDocument();
    expect(screen.getByText(/“Page now says \$60” · suggested by Bravo/)).toBeInTheDocument();
    expect(screen.getByText("1 suggested correction waiting for members to check")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Note on the correction to Hourly labor rate"), "Saw $60 too");
    await userEvent.click(screen.getByRole("button", { name: "Confirm, I checked the source" }));
    expect(calls.find((c) => c.method === "POST").body).toEqual({ vote: "confirm", note: "Saw $60 too" });
  });

  it("members who didn't add an estimate suggest a correction instead of editing", async () => {
    const calls = fakeApi(routes({ "POST /rates/estimates/e1/corrections": [201, COR] }));
    await open();
    await screen.findByText(/\$50 to \$100 per hour/);
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Suggest a correction" }));
    await userEvent.click(screen.getByRole("button", { name: "The source no longer shows this" }));
    await userEvent.type(screen.getByLabelText("What's wrong, and how you checked"), "The page is gone (404).");
    await userEvent.click(screen.getByRole("button", { name: "Suggest correction" }));
    expect(calls.find((c) => c.method === "POST").body).toEqual({ kind: "remove", reason: "The page is gone (404).", proposed: null });
  });
});
