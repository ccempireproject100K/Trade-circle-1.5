import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { acting, api } from "../api.js";
import { AuthStubProvider } from "../auth.jsx";
import Team from "../pages/Team.jsx";
import { fakeApi } from "./fakeApi.js";

const META = { permissions: { profile: "Edit the business profile", portfolio: "Add portfolio photos", follow_ups: "See follow-ups", jobs: "See jobs" }, roles: ["admin", "contributor"] };
const EMPTY_TEAM = { business: { business_name: "Alpha" }, you_are: "owner", members: [], log: [] };

afterEach(() => acting.set(null));

describe("Team", () => {
  it("is optional and invites with explicit permissions", async () => {
    const calls = fakeApi({
      "GET /team/meta": META,
      "GET /team/memberships": { invitations: [], businesses: [], has_team: false },
      "GET /team/u1/members": EMPTY_TEAM,
      "POST /team/u1/invite": [201, {}],
    });
    render(<AuthStubProvider><MemoryRouter><Team /></MemoryRouter></AuthStubProvider>);
    expect(await screen.findByText(/You don't need to set anything up here/)).toBeInTheDocument();
    await userEvent.type(await screen.findByLabelText("Their Trade Circle email"), "sam@example.com");
    await userEvent.click(screen.getByLabelText("See jobs"));
    await userEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    expect(calls.find((c) => c.method === "POST").body).toEqual({ email: "sam@example.com", role: "contributor", permissions: ["portfolio", "jobs"] });
  });

  it("shows an invitation's permissions before the member accepts", async () => {
    const calls = fakeApi({
      "GET /team/meta": META,
      "GET /team/memberships": { invitations: [{ business_id: "b1", business: { business_name: "Bravo HVAC" }, role: "contributor", permissions: ["portfolio"], status: "invited" }], businesses: [], has_team: false },
      "GET /team/u1/members": EMPTY_TEAM,
      "POST /team/invitations/b1/accept": { status: "active" },
    });
    render(<AuthStubProvider><MemoryRouter><Team /></MemoryRouter></AuthStubProvider>);
    expect(await screen.findByText("You'd be able to: Add portfolio photos.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(calls.some((c) => c.path === "/team/invitations/b1/accept")).toBe(true);
  });

  it("names the business on every request while working for it", async () => {
    const calls = fakeApi({ "GET /jobs": [] });
    acting.set({ id: "b1", name: "Bravo HVAC" });
    await api("/jobs");
    expect(calls[0].headers["X-TC-Business"]).toBe("b1");
    acting.set(null);
    await api("/jobs");
    expect(calls[1].headers["X-TC-Business"]).toBeUndefined();
  });
});

describe("Signing in while working for a business", () => {
  it("checks the member's own account without the business header", async () => {
    const { AuthProvider } = await import("../auth.jsx");
    const calls = fakeApi({ "GET /me": { id: "u2", email: "sam@example.com", tier: "free" }, "GET /me/profile": { slug: "sam", business_name: "Sam Rivera" } });
    acting.set({ id: "b1", name: "Bravo HVAC" });
    render(<AuthProvider><span>child</span></AuthProvider>);
    await screen.findByText("child");
    await new Promise((r) => setTimeout(r, 0));
    const profileCall = calls.find((c) => c.path === "/me/profile");
    expect(profileCall.headers["X-TC-Business"]).toBeUndefined();
  });
});
