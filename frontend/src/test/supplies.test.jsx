import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import SupplierDetail from "../pages/SupplierDetail.jsx";
import Supplies from "../pages/Supplies.jsx";
import { fakeApi } from "./fakeApi.js";

const SUPPLIER = {
  id: "s1",
  name: "ABC Supply Co., Inc.",
  website: "https://www.abcsupply.com",
  offers: "Roofing and siding.",
  categories: ["roofing"],
  trades: ["roofer"],
  coverage: "multi_branch",
  branch_note: "Website lists a locations page.",
  locations: [],
  delivery: "unknown",
  business_account: "unknown",
  ships_to: "unknown",
  verification: ["Checked Oct 23, 2026: Official homepage read directly (abcsupply.com). Confirms only the details shown here.", "Not checked: prices, stock, service quality, or any branch's details."],
  added_by: "Trade Circle",
  experiences: { positive: 1, mixed: 0, negative: 1, posts: 2 },
};
const REVIEW = {
  id: "p1", kind: "supplier_review", title: "Fast delivery", body: "Next morning.", trade_tags: [], category: "roofing", location: { label: "Austin, TX" },
  supplier: { id: "s1", name: "ABC Supply Co., Inc." }, photos: [], fields: { experience: "positive", topics: ["delivery"] }, status: "published",
  author: { slug: "a", business_name: "Alpha Roofing", trade: "roofer" }, mine: false, comment_count: 0, created_at: "2026-10-22T00:00:00Z", published_at: "2026-10-22T00:00:00Z",
};

beforeEach(() => localStorage.clear());

describe("Supplies & Vendors", () => {
  it("shows member posts above the directory and remembers the area", async () => {
    const calls = fakeApi({
      "GET /posts?kind=supply_question%2Csupplier_review%2Csupplier_suggestion": { posts: [REVIEW] },
      "GET /suppliers?": { suppliers: [SUPPLIER] },
      "GET /posts?kind=supply_question%2Csupplier_review%2Csupplier_suggestion&near=78701&radius=25": { posts: [] },
      "GET /suppliers?near=78701&radius=25": { suppliers: [{ ...SUPPLIER, match: ["Has branches in many areas; check their store finder for one near you"] }] },
    });
    render(<MemoryRouter><Supplies /></MemoryRouter>);
    const headings = (await screen.findAllByRole("heading", { level: 2 })).map((h) => h.textContent);
    expect(headings.indexOf("Member recommendations")).toBeLessThan(headings.indexOf("Supplier directory"));
    expect(await screen.findByText("Fast delivery")).toBeInTheDocument();
    expect(screen.getByText("Good experience")).toBeInTheDocument();
    expect(screen.getByText(/not endorsements/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Your area"), "78701");
    await userEvent.click(screen.getByRole("button", { name: "Show results for this area" }));
    expect(await screen.findByText(/check their store finder/)).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("tc-area")).near).toBe("78701");
    expect(calls.some((c) => c.path.includes("near=78701"))).toBe(true);
  });

  it("asks a question with a location", async () => {
    const calls = fakeApi({
      "GET /posts?kind=supply_question%2Csupplier_review%2Csupplier_suggestion": { posts: [] },
      "GET /suppliers?": { suppliers: [] },
      "POST /posts": [201, { ...REVIEW, id: "p2", kind: "supply_question", title: "Who has 200A panels?", supplier: null, fields: {} }],
    });
    render(<MemoryRouter><Supplies /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "Ask a question" }));
    await userEvent.type(screen.getByLabelText("Your question"), "Who has 200A panels?");
    await userEvent.type(screen.getByLabelText(/^Area/), "Round Rock, TX");
    await userEvent.click(screen.getByRole("button", { name: "Post question" }));
    expect(await screen.findByText("Who has 200A panels?")).toBeInTheDocument();
    const sent = calls.find((c) => c.method === "POST").body;
    expect(sent).toMatchObject({ kind: "supply_question", title: "Who has 200A panels?", location: "Round Rock, TX" });
  });
});

describe("Supplier listing", () => {
  it("keeps platform facts apart from member opinions", async () => {
    fakeApi({ "GET /suppliers/s1": { ...SUPPLIER, member_posts: [REVIEW] } });
    render(
      <MemoryRouter initialEntries={["/supplies/s1"]}>
        <Routes><Route path="/supplies/:id" element={<SupplierDetail />} /></Routes>
      </MemoryRouter>,
    );
    const facts = (await screen.findByRole("heading", { name: "Directory information" })).closest("section");
    expect(within(facts).getByText(/A directory entry, not an endorsement/)).toBeInTheDocument();
    expect(within(facts).getAllByText("Not confirmed").length).toBeGreaterThanOrEqual(3);
    expect(within(facts).getByText(/Not checked: prices/)).toBeInTheDocument();
    expect(within(facts).queryByText("Fast delivery")).not.toBeInTheDocument();
    const opinions = screen.getByRole("heading", { name: "Member experiences" }).closest("section");
    expect(within(opinions).getByText(/Opinions of Trade Circle members, not facts/)).toBeInTheDocument();
    expect(within(opinions).getByText("Fast delivery")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request removal of this listing" })).toHaveAttribute("href", "/suppliers/s1/remove");
    expect(document.body.textContent).not.toMatch(/\bverified\b|\btrusted\b/i);
  });
});
