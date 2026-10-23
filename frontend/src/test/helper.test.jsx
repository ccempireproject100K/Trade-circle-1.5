import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Helper from "../pages/Helper.jsx";
import Parts from "../pages/Parts.jsx";
import { ShareOpening } from "../pages/ShareForms.jsx";
import { fakeApi } from "./fakeApi.js";

const STATUS = { available: true, timezone: "America/Chicago", daily_limit: 3, monthly_limit: 10, remaining_today: 3, remaining_this_month: 10, day_resets_on: "2026-10-24", month_resets_on: "2026-11-01", refreshes_on: "2026-10-24" };

describe("AI helper", () => {
  it("shows the remaining allowance with exact reset dates and time zone", async () => {
    fakeApi({ "GET /helper": STATUS });
    render(<MemoryRouter><Helper /></MemoryRouter>);
    expect(await screen.findByText(/3 of 3 questions left today · 10 of 10 left this month\. Daily count resets October 24, monthly count November 1 \(midnight Chicago time\)/)).toBeInTheDocument();
  });

  it("explains the shared limit only when it's the shared limit", async () => {
    fakeApi({ "GET /helper": { ...STATUS, available: false, notice: "Community AI is temporarily unavailable." } });
    render(<MemoryRouter><Helper /></MemoryRouter>);
    expect(await screen.findByText("Community AI is temporarily unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });

  it("shows the member's own refresh date when they run out", async () => {
    let left = 1;
    fakeApi({
      "GET /helper": () => ({ ...STATUS, remaining_today: left }),
      "POST /helper/ask": () => {
        left = 0;
        return { answer: "Use a 30 A breaker.", status: { ...STATUS, remaining_today: 0, notice: "Your free AI questions refresh on October 24." } };
      },
    });
    render(<MemoryRouter><Helper /></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText("Your question"), "Dryer breaker size?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Use a 30 A breaker.")).toBeInTheDocument();
    expect(screen.getByText("Your free AI questions refresh on October 24.")).toBeInTheDocument();
    expect(screen.queryByText(/Community AI/)).not.toBeInTheDocument();
  });
});

describe("Part lookup", () => {
  it("separates exact model matches and works while photo reading is off", async () => {
    fakeApi({
      "GET /parts/photo": { ...STATUS, available: false, notice: "Community AI is temporarily unavailable." },
      "GET /parts/search?q=ABC-123": {
        query: "ABC-123", note: "Matches come from members' posts.", inquiry: "Hi, do you carry or can you order ABC-123?",
        exact: [{ id: "p1", kind: "equipment", title: "Fan motor", body: "", trade_tags: [], photos: [], fields: { model: "ABC-123" }, author: { business_name: "A" }, comment_count: 0, created_at: "2026-10-01T00:00:00Z" }],
        mentions: [],
      },
    });
    render(<MemoryRouter><Parts /></MemoryRouter>);
    expect(await screen.findByText("Community AI is temporarily unavailable.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Take or choose a photo/ })).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Model or part number"), "ABC-123");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Exact model match (1)")).toBeInTheDocument();
    expect(screen.getByText("Hi, do you carry or can you order ABC-123?")).toBeInTheDocument();
  });
});

describe("Job openings", () => {
  it("posts an opening with its own fields, separate from leads", async () => {
    const calls = fakeApi({ "GET /community/meta": { trades: ["electrician"] }, "POST /posts": [201, { id: "o1" }] });
    render(<MemoryRouter><ShareOpening /></MemoryRouter>);
    expect(screen.getByText(/Customer jobs and leads don't go here/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Headline"), "Hiring");
    await userEvent.type(screen.getByLabelText("Position"), "Apprentice");
    await userEvent.clear(screen.getByLabelText(/^Where/));
    await userEvent.type(screen.getByLabelText(/^Where/), "78701");
    await userEvent.click(screen.getByRole("button", { name: "Post opening" }));
    const sent = calls.find((c) => c.method === "POST").body;
    expect(sent.kind).toBe("opening");
    expect(sent.fields).toMatchObject({ role: "Apprentice", employment_type: "full_time", apply_by: null });
  });
});
