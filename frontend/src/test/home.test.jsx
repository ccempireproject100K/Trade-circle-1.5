import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthStubProvider as AuthContextStub } from "../auth.jsx";
import Home from "../pages/Home.jsx";
import { fakeApi } from "./fakeApi.js";

// There were no Home tests before Slice 15; these pin the feed-first structure.
const POST = (id, title) => ({
  id, kind: "project", title, body: "What happened on the job.", fields: {}, trade_tags: [], photos: [],
  category: null, supplier: null, location: null,
  author: { slug: "bright-spark", business_name: "Bright Spark Electric", trade: "electrician" },
  comment_count: 2, created_at: "2026-10-22T15:00:00Z", published_at: "2026-10-22T15:00:00Z",
});

const routes = (extra = {}) => ({
  "GET /inbox": [],
  "GET /jobs": [],
  "GET /notifications": { items: [], unread: 0 },
  "GET /handoffs": [],
  "GET /marketplace?radius=30": { needs_area: false, requests: [] },
  "GET /posts": { posts: [] },
  ...extra,
});

const show = (profile) => render(
  <MemoryRouter>
    <AuthContextStub profile={profile}>
      <Home />
    </AuthContextStub>
  </MemoryRouter>,
);

describe("member home (feed-first)", () => {
  it("leads with the community feed, rendered with the shared post cards", async () => {
    fakeApi(routes({ "GET /posts": { posts: [POST("x1", "Panel upgrade walkthrough"), POST("x2", "Hiring a second van")] } }));
    show();
    expect(await screen.findByRole("link", { name: "Panel upgrade walkthrough" })).toHaveAttribute("href", "/posts/x1");
    expect(screen.getByRole("link", { name: "Hiring a second van" })).toHaveAttribute("href", "/posts/x2");
    expect(screen.getAllByText("Bright Spark Electric")).toHaveLength(2);
    expect(screen.getAllByText("2 replies")).toHaveLength(2);
    // The composer is the community page's Share entry, with quick kinds.
    expect(screen.getByRole("link", { name: /Share a project, a lesson, or a question/ })).toHaveAttribute("href", "/share");
    expect(screen.getByRole("link", { name: "Project" })).toHaveAttribute("href", "/share/project");
    expect(screen.getByRole("link", { name: "Community — search & filters →" })).toHaveAttribute("href", "/community");
  });

  it("shows a friendly starter state, never a blank column, when the feed is empty", async () => {
    fakeApi(routes());
    show();
    expect(await screen.findByText("Welcome to the Circle")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Share your first post" })).toHaveAttribute("href", "/share");
    expect(screen.getByRole("link", { name: "Complete your profile" })).toHaveAttribute("href", "/profile");
    expect(screen.getByRole("link", { name: "Host a meetup" })).toHaveAttribute("href", "/share/meetup");
  });

  it("My page card links to the member's public page and profile editor", async () => {
    fakeApi(routes());
    show();
    expect(await screen.findByText("Welcome to the Circle")).toBeInTheDocument();
    const view = screen.getByRole("link", { name: "View my page" });
    expect(view).toHaveAttribute("href", "/p/a");
    expect(view).toHaveAttribute("target", "_blank");
    expect(screen.getByText(`${window.location.origin}/p/a`)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Edit profile" })).toHaveAttribute("href", "/profile");
  });

  it("a hidden page leads with the fix instead of the link", async () => {
    fakeApi(routes());
    show({ slug: "a", business_name: "Alpha", published: false });
    expect(await screen.findByText(/Your page is hidden/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Turn it on in Profile" })).toHaveAttribute("href", "/profile");
  });

  it("the work strip shows leads, follow-ups due, open jobs and marketplace counts with links", async () => {
    fakeApi(routes({
      "GET /inbox": [
        { id: "q1", status: "waiting", source: "trade_circle", follow_up_on: null },
        { id: "q2", status: "waiting", source: "trade_circle", follow_up_on: "2020-01-01" },
        { id: "q3", status: "followed_up", source: "manual", follow_up_on: "2020-01-02" },
      ],
      "GET /jobs": [{ id: "j1", title: "Rewire", status: "scheduled", scheduled_on: "2999-01-01" }],
      "GET /marketplace?radius=30": { needs_area: false, requests: [{ id: "r1" }, { id: "r2" }, { id: "r3" }] },
    }));
    show();
    const leads = await screen.findByRole("link", { name: /new quote requests/ });
    expect(leads).toHaveAttribute("href", "/inbox");
    expect(leads.textContent).toContain("2");
    const due = screen.getByRole("link", { name: /follow-ups due/ });
    expect(due).toHaveAttribute("href", "/inbox");
    expect(due.textContent).toContain("2");
    const jobs = screen.getByRole("link", { name: /open jobs/ });
    expect(jobs).toHaveAttribute("href", "/jobs");
    expect(jobs.textContent).toContain("1");
    const market = screen.getByRole("link", { name: /marketplace jobs/ });
    expect(market).toHaveAttribute("href", "/marketplace");
    expect(market.textContent).toContain("3");
  });

  it("keeps the re-homed activity and coming-up cards", async () => {
    fakeApi(routes({
      "GET /notifications": { unread: 1, items: [{ id: "n1", text: "Dana chose your bid", link: "/marketplace", read: false, created_at: "2026-10-22T15:00:00Z" }] },
      "GET /jobs": [{ id: "j1", title: "Panel swap", customer_name: "Dana", status: "scheduled", scheduled_on: "2999-01-01" }],
      "GET /handoffs": [{ id: "h1", direction: "incoming", status: "proposed" }],
    }));
    show();
    expect(await screen.findByText("Dana chose your bid")).toBeInTheDocument();
    expect(screen.getByText("Panel swap")).toBeInTheDocument();
    expect(screen.getByText(/asking you to cover a job/)).toBeInTheDocument();
  });
});
