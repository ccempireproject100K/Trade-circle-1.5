import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Marketplace from "../pages/Marketplace.jsx";
import { fakeApi } from "./fakeApi.js";

const JOB = { id: "m1", trade: "electrician", title: "Replace a ceiling fan", details: "Old fan wobbles.", area: "78702", distance_miles: 1.7, wanted_on: null, flexible: false, budget: null, photos: [],
  missing: ["date", "budget", "photos"], why: ["It's electrician work, your trade", "It's 1.7 mi from your area"], bid_count: 0, posted_at: "2026-10-23T00:00:00Z", closes_on: "2026-11-06", my_bid: null };

describe("Marketplace", () => {
  it("asks for an area before showing jobs", async () => {
    fakeApi({ "GET /marketplace?radius=30": { needs_area: true, bids_left: 3, free_bids: 3, requests: [] } });
    render(<MemoryRouter><Marketplace /></MemoryRouter>);
    expect(await screen.findByText(/Enter your ZIP code or city/)).toBeInTheDocument();
    expect(screen.getByText(/3 of 3 bids left this month/)).toBeInTheDocument();
  });

  it("marks missing details, explains the match and sends a bid", async () => {
    const calls = fakeApi({
      "GET /marketplace?radius=30": { needs_area: true, bids_left: 3, free_bids: 3, requests: [] },
      "GET /marketplace?radius=30&near=78701": { needs_area: false, near: "78701", radius: 30, trade: "electrician", bids_left: 3, free_bids: 3, requests: [JOB] },
      "POST /marketplace/m1/bids": [201, { status: "sent", bids_left: 2 }],
    });
    render(<MemoryRouter><Marketplace /></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText("Your area"), "78701");
    await userEvent.click(screen.getByRole("button", { name: "Show jobs" }));
    expect(await screen.findByText("Replace a ceiling fan")).toBeInTheDocument();
    expect(screen.getByText(/Not given: date, budget, photos/)).toBeInTheDocument();
    expect(screen.getByText("It's electrician work, your trade")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Bid on this job" }));
    await userEvent.type(screen.getByLabelText("Your message to the customer"), "Can do it Tuesday.");
    await userEvent.type(screen.getByLabelText("Estimate from ($, optional)"), "250");
    await userEvent.click(screen.getByRole("button", { name: "Send bid" }));
    expect(calls.find((c) => c.method === "POST").body).toEqual({ message: "Can do it Tuesday.", price_low_cents: 25000, price_high_cents: null, available_on: null });
    expect(await screen.findByText(/You bid on this/)).toBeInTheDocument();
    expect(screen.getByText(/2 of 3 bids left/)).toBeInTheDocument();
  });
});
