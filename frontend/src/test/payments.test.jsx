import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Payments from "../pages/Payments.jsx";
import { fakeApi } from "./fakeApi.js";

const READY = { ready: true, plan_allows: true, connected: true, charges_enabled: true, details_submitted: true };
const view = (path = "/payments") => render(<MemoryRouter initialEntries={[path]}><Payments /></MemoryRouter>);

describe("Payments", () => {
  it("points non-Full members to plans", async () => {
    fakeApi({ "GET /payments/account": { ...READY, plan_allows: false }, "GET /payments/requests": [], "GET /jobs": [] });
    view();
    expect(await screen.findByText(/part of the Full plan/)).toBeInTheDocument();
  });

  it("asks to connect Stripe before requests can be made", async () => {
    fakeApi({ "GET /payments/account": { ...READY, connected: false, charges_enabled: false }, "GET /payments/requests": [], "GET /jobs": [] });
    view();
    expect(await screen.findByRole("button", { name: "Connect with Stripe" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request payment" })).not.toBeInTheDocument();
  });

  it("creates a request from a job with dollars converted to cents", async () => {
    const calls = fakeApi({
      "GET /payments/account": READY,
      "GET /payments/requests": [],
      "GET /jobs": [{ id: "j1", title: "Panel upgrade", customer_name: "Pat Lee", estimate_cents: 250000 }],
      "POST /payments/requests": [201, { id: "r1", description: "Panel upgrade", customer_name: "Pat Lee", amount_cents: 250000, paid_cents: 0, refunded_cents: 0, processing_cents: 0, due_cents: 250000, status: "open", created_at: "2026-10-23T00:00:00Z", link: "https://x/pay/t", payments: [] }],
    });
    view("/payments?job=j1");
    expect(await screen.findByDisplayValue("2500.00")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Pat Lee")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Let them pay in parts"));
    await userEvent.type(screen.getByLabelText("Smallest part ($, optional)"), "500");
    await userEvent.click(screen.getByRole("button", { name: "Create payment link" }));
    const body = calls.find((c) => c.method === "POST").body;
    expect(body).toMatchObject({ amount_cents: 250000, allow_partial: true, min_partial_cents: 50000, job_id: "j1", card: true, bank: true });
    expect(await screen.findByText(/Payment link created/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Text it" })).toBeInTheDocument();
  });

  it("shows the ledger with clearing bank payments", async () => {
    fakeApi({
      "GET /payments/account": READY, "GET /jobs": [],
      "GET /payments/requests": [{ id: "r1", description: "Panel upgrade", customer_name: "Pat Lee", amount_cents: 250000, paid_cents: 100000, refunded_cents: 0, processing_cents: 50000, due_cents: 100000, status: "partly_paid", created_at: "2026-10-23T00:00:00Z", link: "https://x/pay/t",
        payments: [{ amount_cents: 100000, method: "card", status: "succeeded", refunded_cents: 0, at: "2026-10-23T00:00:00Z" }, { amount_cents: 50000, method: "bank", status: "processing", refunded_cents: 0, at: "2026-10-23T00:00:00Z" }] }],
    });
    view();
    expect(await screen.findByText(/\$500\.00 clearing/)).toBeInTheDocument();
    expect(screen.getByText(/\$500\.00 by bank · clearing/)).toBeInTheDocument();
    expect(screen.getByText("Partly paid")).toBeInTheDocument();
  });
});
