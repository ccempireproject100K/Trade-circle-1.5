import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthStubProvider as AuthContextStub } from "../auth.jsx";
import { CheersPanel } from "../components/Cheers.jsx";
import { PostCard } from "../components/Community.jsx";
import Handoffs from "../pages/Handoffs.jsx";
import Home from "../pages/Home.jsx";
import { fakeApi } from "./fakeApi.js";

// Slice 17 — the cheers economy in the interface: cheer buttons on posts,
// the author's banked badge, the waiting banner on Home, the numbers on
// the profile, and the after-handoff thank-you prompt.

const POST = (extra = {}) => ({
  id: "p1", kind: "project", title: "200A service upgrade", body: "Swapped the panel.", fields: {}, trade_tags: [],
  photos: [], category: null, supplier: null, location: null, cheers: 3,
  author: { slug: "bravo", business_name: "Bravo Electric", trade: "electrician", banked: 7 },
  mine: false, comment_count: 1, created_at: "2026-10-22T15:00:00Z", published_at: "2026-10-22T15:00:00Z",
  ...extra,
});

describe("post cards", () => {
  it("shows the author's banked badge and the post's cheer count, and cheering sends one", async () => {
    const calls = fakeApi({
      "POST /cheers": { cheer_id: "c1", sent: 1, funding: "allowance", collected: null, wallet: { allowance: 9, bank: 0, waiting: 0, banked: 0 } },
    });
    render(<MemoryRouter><ul><PostCard post={POST()} /></ul></MemoryRouter>);
    expect(screen.getByTitle("Banked cheers — lifetime earned")).toHaveTextContent("🎉 7");
    expect(screen.getByText("3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "🎉 Cheer" }));
    expect(await screen.findByText(/🎉 Cheered/)).toBeInTheDocument();
    expect(calls).toContainEqual(expect.objectContaining({ method: "POST", path: "/cheers", body: { post_id: "p1" } }));
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("says when your send collected one of your own waiting cheers", async () => {
    fakeApi({
      "POST /cheers": { cheer_id: "c2", sent: 2, funding: "bank", collected: { from: "Alpha Electric", note: null }, wallet: { allowance: 0, bank: 0, waiting: 0, banked: 3 } },
    });
    render(<MemoryRouter><ul><PostCard post={POST()} /></ul></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: "🎉 Cheer" }));
    expect(await screen.findByText(/your cheer from Alpha Electric landed/)).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument(); // a banked cheer lands double: 3 + 2
  });

  it("never offers a cheer button on your own post — the count just shows", () => {
    fakeApi({});
    render(<MemoryRouter><ul><PostCard post={POST({ mine: true })} /></ul></MemoryRouter>);
    expect(screen.queryByRole("button", { name: "🎉 Cheer" })).not.toBeInTheDocument();
    expect(screen.getByText("🎉 3")).toBeInTheDocument();
  });
});

describe("the cheers panel (profile)", () => {
  it("shows allowance, bank, banked, waiting and given — and the waiting nudge", async () => {
    fakeApi({
      "GET /cheers/me": {
        allowance: 12, bank: 4, banked: 21, collected: 21, waiting: 2, given: 18, monthly: 30, cap: 100,
        activity: {
          given: [{ id: "g1", member: { slug: "c", business_name: "Charlie Electric" }, status: "waiting", funding: "allowance", post_id: null, handoff_id: null, note: null, created_at: "2026-10-22T15:00:00Z", collected_at: null }],
          received: [{ id: "r1", member: { slug: "a", business_name: "Alpha Electric" }, status: "collected", funding: "allowance", post_id: null, handoff_id: null, note: "Great panel work", created_at: "2026-10-21T15:00:00Z", collected_at: "2026-10-22T15:00:00Z" }],
        },
      },
    });
    render(<CheersPanel />);
    expect(await screen.findByText("banked (lifetime)")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("21")).toBeInTheDocument();
    expect(screen.getByText(/2 cheers are waiting for you/)).toBeInTheDocument();
    expect(screen.getByText(/Great panel work/)).toBeInTheDocument();
    expect(screen.getByText(/Your plan adds 30 allowance cheers a month/)).toBeInTheDocument();
  });
});

describe("home", () => {
  it("banners the waiting count and shows the cheers card", async () => {
    fakeApi({
      "GET /inbox": [],
      "GET /jobs": [],
      "GET /notifications": { items: [], unread: 0 },
      "GET /handoffs": [],
      "GET /marketplace?radius=30": { needs_area: false, requests: [] },
      "GET /posts": { posts: [] },
      "GET /cheers/me": { allowance: 5, bank: 1, banked: 9, collected: 9, waiting: 2, given: 4, monthly: 30, cap: 100, activity: { given: [], received: [] } },
    });
    render(
      <MemoryRouter>
        <AuthContextStub>
          <Home />
        </AuthContextStub>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/2 cheers are waiting for you — send a cheer to collect them/)).toBeInTheDocument();
    expect(screen.getByText(/Allowance 5 · Bank 1 · Banked 9 · Waiting 2 · Given 4/)).toBeInTheDocument();
  });
});

describe("the handoff prompt", () => {
  const ALLOWANCE = {
    week_start: "2026-10-19", resets_at: "2026-10-26T00:00:00-05:00", timezone: "America/Chicago",
    weekly_limit: 3, per_recipient_limit: 2, used: 1, remaining: 2, by_recipient: [], vacation: null,
    limits_lifted: false, at_limit: false,
  };
  const DONE = {
    id: "h1", direction: "outgoing", status: "completed",
    from: { slug: "alpha", business_name: "Alpha Electric" }, to: { slug: "bravo", business_name: "Bravo Electric" },
    job: { title: "Panel upgrade", site_address: "12 Oak St" }, start_on: "2026-10-21", end_on: null, note: "",
    during_vacation: false, proposed_at: "2026-10-20T15:00:00Z", completed_at: "2026-10-22T15:00:00Z",
    cheer_prompt: { to: { slug: "bravo", business_name: "Bravo Electric" } },
  };

  it("offers the thank-you on a completed handoff and sends it", async () => {
    const calls = fakeApi({
      "GET /handoffs/allowance": ALLOWANCE,
      "GET /handoffs": [DONE],
      "GET /jobs": [],
      "GET /members?q=": [],
      "POST /cheers": { cheer_id: "c9", sent: 1, funding: "allowance", collected: null, wallet: { allowance: 29, bank: 0, waiting: 0, banked: 0 } },
    });
    render(<MemoryRouter initialEntries={["/handoffs?view=sent"]}><Handoffs /></MemoryRouter>);
    expect(await screen.findByText(/Your cover had your back/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Send Bravo Electric a cheer/ }));
    expect(await screen.findByText(/🎉 Cheered/)).toBeInTheDocument();
    expect(calls).toContainEqual(expect.objectContaining({ method: "POST", path: "/cheers", body: { handoff_id: "h1" } }));
  });

  it("shows the already-cheered note instead of the prompt", async () => {
    fakeApi({
      "GET /handoffs/allowance": ALLOWANCE,
      "GET /handoffs": [{ ...DONE, cheer_prompt: undefined, cheer_sent: true }],
      "GET /jobs": [],
      "GET /members?q=": [],
    });
    render(<MemoryRouter initialEntries={["/handoffs?view=sent"]}><Handoffs /></MemoryRouter>);
    expect(await screen.findByText(/You cheered Bravo Electric for this one/)).toBeInTheDocument();
    expect(screen.queryByText(/Your cover had your back/)).not.toBeInTheDocument();
  });
});
