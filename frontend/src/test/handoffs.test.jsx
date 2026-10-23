import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Handoffs from "../pages/Handoffs.jsx";
import { fakeApi } from "./fakeApi.js";

const BASE = {
  week_start: "2026-10-19",
  resets_at: "2026-10-26T00:00:00-05:00",
  timezone: "America/Chicago",
  weekly_limit: 3,
  per_recipient_limit: 2,
  used: 0,
  remaining: 3,
  by_recipient: [],
  vacation: null,
  limits_lifted: false,
  at_limit: false,
};
const JOBS = [{ id: "j1", title: "Panel upgrade", status: "scheduled", scheduled_on: "2026-11-02" }];
const MEMBERS = [{ slug: "bravo", business_name: "Bravo Electric", trade: "electrician", city: "Austin" }];

function show(allowance, extra = {}) {
  const calls = fakeApi({
    "GET /handoffs/allowance": { ...BASE, ...allowance },
    "GET /handoffs": [],
    "GET /jobs": JOBS,
    "GET /members?q=": MEMBERS,
    ...extra,
  });
  render(<MemoryRouter initialEntries={["/handoffs"]}><Handoffs /></MemoryRouter>);
  return calls;
}

describe("Handoffs", () => {
  it("explains the limits before sending", async () => {
    show({ used: 1, remaining: 2, by_recipient: [{ slug: "bravo", business_name: "Bravo Electric", count: 1 }] });
    expect(await screen.findByText("1 of 3 handoffs used this week")).toBeInTheDocument();
    expect(screen.getByText(/no more than 2 to the same member/)).toBeInTheDocument();
    expect(screen.getByText(/Bravo Electric \(1\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send handoff" })).toBeEnabled();
  });

  it("blocks sending at the weekly limit and says when it resets", async () => {
    show({ used: 3, remaining: 0, at_limit: true });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You've used all 3 handoffs for this week");
    expect(alert).toHaveTextContent("resets Monday, Oct 26, 12:00 AM CDT");
    expect(alert).toHaveTextContent("arrange extra coverage outside Trade Circle");
    expect(screen.queryByRole("button", { name: "Send handoff" })).not.toBeInTheDocument();
  });

  it("stops a third handoff to the same member", async () => {
    show({ used: 2, remaining: 1, by_recipient: [{ slug: "bravo", business_name: "Bravo Electric", count: 2 }] });
    await screen.findByRole("option", { name: /Bravo Electric/ });
    await userEvent.selectOptions(screen.getByLabelText("Hand off to"), "bravo");
    expect(screen.getByText(/already sent 2 handoffs to Bravo Electric/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send handoff" })).toBeDisabled();
  });

  it("shows paused limits during a vacation and when they return", async () => {
    show({ limits_lifted: true, vacation: { id: "v1", start_on: "2026-10-21", end_on: "2026-10-30", note: "Trip" } });
    const notice = await screen.findByText(/weekly handoff limits are paused/);
    expect(notice).toHaveTextContent("come back automatically on Saturday, Oct 31");
  });

  it("sends the chosen job, member and dates", async () => {
    const calls = show({}, { "POST /handoffs": [201, { id: "h1" }] });
    await userEvent.selectOptions(await screen.findByLabelText("Job"), "j1");
    await screen.findByRole("option", { name: /Bravo Electric/ });
    await userEvent.selectOptions(screen.getByLabelText("Hand off to"), "bravo");
    await userEvent.type(screen.getByLabelText(/Note to the member/), "Out sick");
    await userEvent.click(screen.getByRole("button", { name: "Send handoff" }));
    expect(await screen.findByText(/It isn't handed off until they accept/)).toBeInTheDocument();
    const sent = calls.find((c) => c.method === "POST").body;
    expect(sent).toEqual({ job_id: "j1", recipient_slug: "bravo", start_on: "2026-11-02", end_on: null, note: "Out sick" });
  });
});

describe("After acceptance", () => {
  const ACCEPTED = {
    id: "h1", status: "accepted", from: { slug: "alpha", business_name: "Alpha" }, to: { slug: "bravo", business_name: "Bravo" },
    job: { title: "Panel upgrade" }, start_on: "2026-11-02", end_on: null, note: "", during_vacation: false, proposed_at: "2026-10-22T00:00:00Z",
  };

  it("lets the recipient hand a job back with a reason", async () => {
    const calls = show({}, { "GET /handoffs": [{ ...ACCEPTED, direction: "incoming" }], "POST /handoffs/h1/reverse": {} });
    await userEvent.click(await screen.findByRole("button", { name: "Hand it back" }));
    expect(screen.getByRole("button", { name: "Hand it back" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reason"), "Truck broke down");
    await userEvent.click(screen.getByRole("button", { name: "Hand it back" }));
    expect(calls.find((c) => c.path === "/handoffs/h1/reverse").body).toEqual({ reason: "Truck broke down" });
  });

  it("lets the sender ask to cancel, and the recipient answer", async () => {
    const calls = show({}, { "GET /handoffs": [{ ...ACCEPTED, direction: "outgoing", job_id: "j1" }], "POST /handoffs/h1/cancel-request": {} });
    await userEvent.click(await screen.findByRole("button", { name: "Sent (1)" }));
    await userEvent.click(screen.getByRole("button", { name: "Ask to cancel" }));
    expect(screen.getByText(/it still counts toward this week's handoffs/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Reason"), "Customer asked for me");
    await userEvent.click(screen.getByRole("button", { name: "Ask to cancel" }));
    expect(calls.find((c) => c.path === "/handoffs/h1/cancel-request").body).toEqual({ reason: "Customer asked for me" });
  });

  it("shows a pending cancellation request to the recipient", async () => {
    const pending = { ...ACCEPTED, direction: "incoming", cancel_request: { status: "pending", reason: "Customer asked for me" } };
    const calls = show({}, { "GET /handoffs": [pending], "POST /handoffs/h1/cancel-request/respond": {} });
    expect(await screen.findByText(/Alpha asked to cancel: Customer asked for me/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Keep the job" }));
    expect(calls.find((c) => c.path.endsWith("/respond")).body).toEqual({ agree: false });
  });
});
