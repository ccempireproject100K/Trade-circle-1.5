import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import MessageRequest from "../components/MessageRequest.jsx";
import Mentoring from "../pages/Mentoring.jsx";
import { MessageList } from "../pages/Messages.jsx";
import PostDetail from "../pages/PostDetail.jsx";
import { fakeApi } from "./fakeApi.js";

const MEMBER = { slug: "bravo", business_name: "Bravo Electric", trade: "electrician", city: "Austin" };

describe("Messaging", () => {
  it("sends a request and explains nothing is shared until accepted", async () => {
    const calls = fakeApi({ "POST /messages/requests": [201, { id: "r1", status: "pending" }] });
    render(<MemoryRouter><MessageRequest member={MEMBER} context="post" postId="p1" /></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: "Message Bravo Electric" }));
    await userEvent.type(screen.getByLabelText("Your message"), "Which branch was this?");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByText(/needs to accept before you can message/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST").body).toEqual({ to_slug: "bravo", note: "Which branch was this?", context: "post", post_id: "p1" });
  });

  it("lets the recipient accept, decline or block", async () => {
    const calls = fakeApi({
      "GET /messages/requests": { incoming: [{ id: "r1", member: MEMBER, note: "Hi there", context: "mentoring", status: "pending", created_at: "2026-10-22T17:00:00Z" }], outgoing: [] },
      "GET /messages/conversations": [],
      "POST /messages/requests/r1/decline": { status: "declined" },
    });
    render(<MemoryRouter><MessageList /></MemoryRouter>);
    expect(await screen.findByText("Mentoring introduction · Oct 22")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Block" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(calls.some((c) => c.path === "/messages/requests/r1/decline")).toBe(true);
  });
});

describe("Mentoring", () => {
  it("is clearly voluntary, hides contact details, and uses introductions", async () => {
    fakeApi({
      "GET /me/mentoring": { mentoring: null },
      "GET /mentoring?mode=offering": [{ member: MEMBER, topics: ["estimating"], experience: "20 years", availability: "Evenings", prefers: "Phone call", seeking: false, offering: true }],
    });
    render(<MemoryRouter><Mentoring /></MemoryRouter>);
    expect(screen.getByText(/volunteers, not certified or checked by Trade Circle, and nobody is promised a reply/)).toBeInTheDocument();
    expect(await screen.findByText("Prefers: Phone call")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask for an introduction" })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/\+1\d{10}/);
    expect(screen.getByRole("button", { name: "Join mentoring" })).toBeInTheDocument();
  });

  it("can be paused or removed", async () => {
    const calls = fakeApi({
      "GET /me/mentoring": { mentoring: { offering: true, seeking: false, topics: ["pricing"], experience: "", contact_method: "messages", contact_value: "", availability: "", paused: false } },
      "GET /mentoring?mode=offering": [],
      "PUT /me/mentoring": { mentoring: {} },
      "DELETE /me/mentoring": [204, null],
    });
    render(<MemoryRouter><Mentoring /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "Pause" }));
    expect(calls.find((c) => c.method === "PUT").body.paused).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Remove my status" }));
    expect(calls.some((c) => c.method === "DELETE" && c.path === "/me/mentoring")).toBe(true);
  });
});

describe("Meetups", () => {
  const MEETUP = {
    id: "m1", kind: "meetup", title: "Coffee and code", body: "", trade_tags: [], category: null, location: { label: "78701" }, supplier: null, photos: [],
    fields: { starts_on: "2026-11-05", starts_at: "07:00", timezone: "America/Chicago", general_location: "Coffee shop downtown" }, status: "published",
    author: { slug: "host", business_name: "Host Electric" }, comment_count: 0, created_at: "2026-10-22T00:00:00Z", published_at: "2026-10-22T00:00:00Z", comments: [],
  };
  const show = () =>
    render(
      <MemoryRouter initialEntries={["/posts/m1"]}>
        <Routes><Route path="/posts/:id" element={<PostDetail />} /></Routes>
      </MemoryRouter>,
    );

  it("shows date, time zone and general location, and takes an RSVP", async () => {
    const calls = fakeApi({
      "GET /posts/m1": { ...MEETUP, mine: false, meetup: { updates: [{ at: "2026-10-23T12:00:00Z", text: "Moved to 7:30" }], cancelled: null, rsvp: { going: 2, maybe: 1, not_going: 0, mine: null } } },
      "PUT /posts/m1/rsvp": {},
    });
    show();
    expect(await screen.findByText("Thursday, November 5 at 7:00 AM (Chicago time)")).toBeInTheDocument();
    expect(screen.getByText("Coffee shop downtown")).toBeInTheDocument();
    expect(screen.getByText("Moved to 7:30")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Going" }));
    expect(calls.find((c) => c.method === "PUT").body).toEqual({ response: "going" });
  });

  it("shows cancellation and stops RSVPs", async () => {
    fakeApi({ "GET /posts/m1": { ...MEETUP, mine: false, meetup: { updates: [], cancelled: { at: "2026-10-23T12:00:00Z", reason: "Rained out." }, rsvp: { going: 0, maybe: 0, not_going: 0, mine: "going" } } } });
    show();
    expect(await screen.findByText(/Cancelled by the host. Rained out./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Going" })).not.toBeInTheDocument();
  });

  it("lets the host post updates", async () => {
    const calls = fakeApi({ "GET /posts/m1": { ...MEETUP, mine: true, meetup: { updates: [], cancelled: null, rsvp: { going: 1, maybe: 0, not_going: 0, mine: null } } }, "POST /posts/m1/updates": [201, {}] });
    show();
    await userEvent.type(await screen.findByLabelText(/Post an update/), "Bring your code book");
    await userEvent.click(screen.getByRole("button", { name: "Post update" }));
    expect(calls.find((c) => c.path === "/posts/m1/updates").body).toEqual({ text: "Bring your code book" });
  });
});
