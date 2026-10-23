import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "../App.jsx";
import { api, ApiError, toCents } from "../api.js";
import { AuthProvider, AuthStubProvider as AuthContextStub } from "../auth.jsx";
import SortableList from "../components/SortableList.jsx";
import Inbox from "../pages/Inbox.jsx";
import { fakeApi } from "./fakeApi.js";

const USER = { id: "u1", email: "spark@example.com", role: "contractor", tier: "free" };
const PROFILE = { id: "p1", slug: "bright-spark", business_name: "Bright Spark Electric", trade: "electrician", city: "Austin", layout: [] };

describe("api client", () => {
  it("sends the CSRF header on writes only", async () => {
    const calls = fakeApi({ "GET /me": USER, "POST /jobs": [201, { id: "j1" }] });
    await api("/me");
    await api("/jobs", { method: "POST", body: { title: "x" } });
    expect(calls[0].headers["X-TC-CSRF"]).toBeUndefined();
    expect(calls[1].headers["X-TC-CSRF"]).toBe("1");
  });

  it("turns validation errors into plain sentences", async () => {
    fakeApi({ "POST /jobs": [422, { detail: [{ loc: ["body", "customer_phone"], msg: "String should match pattern" }] }] });
    const error = await api("/jobs", { method: "POST", body: {} }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("Customer phone: String should match pattern");
  });

  it("parses dollar amounts", () => {
    expect(toCents("1,850.50")).toBe(185050);
    expect(toCents("$40")).toBe(4000);
    expect(toCents("")).toBeNull();
    expect(toCents("abc")).toBeNaN();
  });
});

describe("SortableList", () => {
  it("reorders with the move buttons", async () => {
    const onReorder = vi.fn();
    render(<SortableList label="Order" items={["a", "b", "c"]} getKey={(x) => x} renderItem={(x) => x} onReorder={onReorder} />);
    await userEvent.click(screen.getAllByRole("button", { name: "Move down" })[0]);
    expect(onReorder).toHaveBeenCalledWith(["b", "a", "c"]);
    expect(screen.getAllByRole("button", { name: "Move up" })[0]).toBeDisabled();
  });
});

describe("Follow-up tracker", () => {
  const ENTRIES = [
    { id: "q1", name: "Dana", phone: "+15125550199", message: "Panel", job_type: "Panel upgrade", status: "waiting", source: "trade_circle", notes: "", follow_up_on: "2026-10-30", created_at: "2026-10-22T15:00:00Z" },
    { id: "m1", name: "Sam", phone: null, email: null, message: "", job_type: null, status: "followed_up", source: "manual", channel: "in_person", notes: "Met at supply house", follow_up_on: "2020-01-01", created_at: "2026-10-20T15:00:00Z" },
  ];
  const routes = (extra = {}) => ({
    "GET /inbox?view=upcoming": [ENTRIES[0]],
    "GET /inbox?view=overdue": [ENTRIES[1]],
    "GET /inbox?view=all": ENTRIES,
    ...extra,
  });
  const show = () => render(<MemoryRouter><AuthContextStub><Inbox /></AuthContextStub></MemoryRouter>);

  it("opens on everything, so new requests without a date are never hidden", async () => {
    fakeApi(routes());
    show();
    expect(await screen.findByText("Dana")).toBeInTheDocument();
    expect(screen.getByText("Sam")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Upcoming" }));
    await waitFor(() => expect(screen.queryByText("Sam")).not.toBeInTheDocument());
    expect(screen.getByText("Dana")).toBeInTheDocument();
    expect(screen.getByText(/Quote request through Trade Circle/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Call" })).toHaveAttribute("href", "tel:+15125550199");
    await userEvent.click(screen.getByRole("button", { name: "Overdue (1)" }));
    expect(await screen.findByText("Sam")).toBeInTheDocument();
    expect(screen.getByText(/Added by you · In person/)).toBeInTheDocument();
    expect(screen.getByText("Follow up on (overdue)")).toBeInTheDocument();
    expect(screen.getByText(/Private to you/)).toBeInTheDocument();
  });

  it("adds an inquiry from a phone call", async () => {
    const calls = fakeApi(routes({ "POST /inbox": [201, { ...ENTRIES[1], id: "m2", name: "Lee" }] }));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));
    const form = screen.getByRole("heading", { name: /Add from a call/ }).closest("form");
    await userEvent.type(within(form).getByLabelText("Name"), "Lee");
    await userEvent.type(within(form).getByLabelText("Phone (optional)"), "(512) 555-0100");
    await userEvent.type(within(form).getByLabelText("Follow up on"), "2026-11-01");
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/inbox")).toBe(true));
    const sent = calls.find((c) => c.method === "POST" && c.path === "/inbox");
    expect(sent.body).toMatchObject({ name: "Lee", phone: "(512) 555-0100", follow_up_on: "2026-11-01", channel: "phone", email: null });
  });

  it("turns an entry into a job and marks it won", async () => {
    const calls = fakeApi(routes({ "POST /jobs": [201, { id: "j1" }], "PATCH /inbox/q1": { ...ENTRIES[0], status: "won" } }));
    show();
    await userEvent.click((await screen.findAllByRole("button", { name: "Make job" }))[0]);
    await screen.findByText(/Added "Panel upgrade"/);
    expect(calls.find((c) => c.method === "POST" && c.path === "/jobs").body).toMatchObject({ title: "Panel upgrade", customer_name: "Dana", customer_phone: "+15125550199" });
    expect(calls.find((c) => c.method === "PATCH").body).toEqual({ status: "won" });
  });
});

describe("App", () => {
  it("sends signed-out visitors to sign in, then into the dashboard", async () => {
    let signedIn = false;
    fakeApi({
      "GET /me": () => (signedIn ? USER : [401, { detail: "Not signed in" }]),
      "GET /me/profile": () => (signedIn ? PROFILE : [401, { detail: "Not signed in" }]),
      "POST /auth/login": () => {
        signedIn = true;
        return { user: USER };
      },
      "GET /inbox?view=upcoming": [],
      "GET /inbox?view=overdue": [],
      "GET /inbox?view=all": [],
      "GET /jobs": [],
    });
    render(<MemoryRouter initialEntries={["/inbox"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText("Email"), "spark@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "long enough pw");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    // Returns to the page they asked for.
    expect(await screen.findByRole("heading", { name: "Follow-ups" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/No inquiries yet/)).toBeInTheDocument());
  });

  it("shows a wrong-password message", async () => {
    fakeApi({
      "GET /me": [401, { detail: "Not signed in" }],
      "GET /me/profile": [401, { detail: "Not signed in" }],
      "POST /auth/login": [401, { detail: "Wrong email or password" }],
    });
    render(<MemoryRouter initialEntries={["/login"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText("Email"), "spark@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password");
  });
});
