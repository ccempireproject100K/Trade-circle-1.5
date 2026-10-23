import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Calendar, { byDay } from "../pages/Calendar.jsx";
import Costing from "../pages/Costing.jsx";
import Quotes from "../pages/Quotes.jsx";
import Time, { hours } from "../pages/Time.jsx";
import { localToday } from "../api.js";
import { fakeApi } from "./fakeApi.js";

const WEEK = { week_of: "2026-10-19", timezone: "America/Chicago", total_minutes: 480, totals: { days: { "2026-10-21": 480 }, jobs: { "Panel swap": 480 }, people: { Me: 480 } },
  entries: [{ id: "t1", worker: "Me", mine: true, job: "Panel swap", day: "2026-10-21", start: "07:30", end: "16:00", running: false, break_minutes: 30, minutes: 480, note: "", started_at: "2026-10-21T12:30:00Z" }] };

describe("Time", () => {
  it("clocks in with a job and shows the week", async () => {
    const calls = fakeApi({ "GET /time/status": { allowed: true, running: null }, "GET /jobs": [{ id: "j1", title: "Panel swap", status: "scheduled" }], [`GET /time?start=${localToday()}`]: WEEK, "POST /time/clock-in": [201, {}] });
    render(<MemoryRouter><Time /></MemoryRouter>);
    expect(await screen.findByText(/Total/)).toHaveTextContent("Total 8h 00m");
    expect(screen.getByText(/07:30–16:00/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Job (optional)"), "j1");
    await userEvent.click(screen.getByRole("button", { name: "Clock in" }));
    expect(calls.find((c) => c.method === "POST").body).toEqual({ job_id: "j1" });
  });

  it("explains the plan and keeps past time visible", async () => {
    fakeApi({ "GET /time/status": { allowed: false, running: null }, "GET /jobs": [], [`GET /time?start=${localToday()}`]: WEEK });
    render(<MemoryRouter><Time /></MemoryRouter>);
    expect(await screen.findByText(/Time tracking is part of the Starter plan/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clock in" })).not.toBeInTheDocument();
    expect(screen.getByText(/07:30–16:00/)).toBeInTheDocument();
  });

  it("formats hours", () => expect(hours(95)).toBe("1h 35m"));
});

describe("Calendar", () => {
  it("spreads multi-day events across their days", () => {
    const days = byDay([{ kind: "vacation", date: "2026-11-02", end: "2026-11-04", title: "Vacation" }, { kind: "job", date: "2026-11-03", title: "Panel" }]);
    expect(Object.keys(days)).toEqual(["2026-11-02", "2026-11-03", "2026-11-04"]);
    expect(days["2026-11-03"].map((e) => e.kind)).toEqual(["vacation", "job"]);
  });

  it("lists what's coming up with links", async () => {
    const today = new Date();
    const later = new Date(today.getFullYear(), today.getMonth(), Math.min(today.getDate() + 1, 28));
    const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const dayDate = later >= today ? iso(later) : iso(today);
    fakeApi({}); // any calendar range
    globalThis.fetch.mockImplementation(async () => new Response(JSON.stringify({ events: [{ kind: "job", date: dayDate, title: "Panel swap", detail: "Pat", link: "/jobs" }] }), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<MemoryRouter><Calendar /></MemoryRouter>);
    expect((await screen.findAllByRole("link", { name: "Panel swap" }))[0]).toHaveAttribute("href", "/jobs");
  });
});

describe("Job costing", () => {
  it("saves lines in cents and shows margin and markup", async () => {
    const SUMMARY = { price_cents: 300000, tracked_hours: 10, tracked_labor_cents: 40000, estimate: { direct_cents: 154000, overhead_cents: 15400, cost_cents: 169400, profit_cents: 130600, margin_percent: 43.5, markup_percent: 77.1 }, actual: { direct_cents: 145000, overhead_cents: 14500, cost_cents: 159500, profit_cents: 140500, margin_percent: 46.8, markup_percent: 88.1 }, variance: { materials: 15000 } };
    const DATA = { price_cents: null, labor_cost_per_hour_cents: 0, overhead_percent: 0, estimate: [], actual: [], job: { id: "j1", title: "Panel swap", estimate_cents: 300000 }, summary: SUMMARY };
    const calls = fakeApi({ "GET /jobs/j1/costing": DATA, "GET /costing/templates": [], "PUT /jobs/j1/costing": DATA });
    render(<MemoryRouter initialEntries={["/jobs/j1/costing"]}><Routes><Route path="/jobs/:id/costing" element={<Costing />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("43.5%")).toBeInTheDocument();
    expect(screen.getByText(/Includes 10 tracked hours/)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Add a line" })[0]);
    await userEvent.type(screen.getByLabelText("Estimate line 1 description"), "Panel");
    await userEvent.type(screen.getByLabelText("Estimate line 1 cost each"), "900");
    await userEvent.click(screen.getByRole("button", { name: "Save and update summary" }));
    expect(calls.find((c) => c.method === "PUT").body.estimate).toEqual([{ kind: "materials", description: "Panel", quantity: 1, unit_cost_cents: 90000 }]);
  });
});

describe("Quote templates", () => {
  it("prices a template for a date with its season", async () => {
    const T = { id: "q1", name: "AC tune-up", items: [{ description: "Tune-up", price_cents: 12000 }], seasons: [{ label: "Peak AC season", months: [6, 7, 8], adjust_percent: 15 }] };
    fakeApi({ "GET /quote-templates": [T] });
    globalThis.fetch.mockImplementation(async (url) =>
      String(url).includes("/price")
        ? new Response(JSON.stringify({ on: "2027-07-04", season: T.seasons[0], items: [{ description: "Tune-up", price_cents: 12000, adjusted_cents: 13800 }], subtotal_cents: 12000, total_cents: 13800 }), { status: 200, headers: { "Content-Type": "application/json" } })
        : new Response(JSON.stringify([T]), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<MemoryRouter><Quotes /></MemoryRouter>);
    expect(await screen.findByText(/Total \$138\.00/)).toBeInTheDocument();
    expect(screen.getByText(/Peak AC season, \+15% on \$120\.00/)).toBeInTheDocument();
  });
});
