import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Reviews from "../pages/Reviews.jsx";
import { fakeApi } from "./fakeApi.js";

const REVIEW = {
  id: "r1", lead_id: "q1", job_type: "Replace a ceiling fan", stars: 5,
  text: "On time, tidy, and the fan is silent.", reviewer_name: "Pat L.",
  status: "published", created_at: "2026-10-22T12:00:00Z", response: null,
};
const ANSWERED = {
  ...REVIEW, id: "r2", stars: 2, text: "Slow to reply.", reviewer_name: "Sam O.",
  response: { text: "Sorry Sam — we were short-handed that week.", at: "2026-10-23T12:00:00Z", edited_at: null },
};
const DATA = { count: 2, average: 3.5, reviews: [REVIEW, ANSWERED] };

const show = () =>
  render(
    <MemoryRouter>
      <Reviews />
    </MemoryRouter>,
  );

describe("Reviews", () => {
  it("shows the average, the stars and each review with its response", async () => {
    fakeApi({ "GET /reviews": DATA });
    show();
    expect(await screen.findByText("On time, tidy, and the fan is silent.")).toBeInTheDocument();
    expect(screen.getByText("3.5")).toBeInTheDocument();
    expect(screen.getByText(/2 reviews/)).toBeInTheDocument();
    expect(screen.getByText("★★★★★")).toBeInTheDocument();
    expect(screen.getByText("★★☆☆☆")).toBeInTheDocument();
    expect(screen.getByText(/Pat L\. · Oct 22 · Replace a ceiling fan/)).toBeInTheDocument();
    expect(screen.getByText("Sorry Sam — we were short-handed that week.")).toBeInTheDocument();
    expect(screen.getByText(/Your response · Oct 23/)).toBeInTheDocument();
  });

  it("responds to a review and shows the saved response", async () => {
    const calls = fakeApi({
      "GET /reviews": DATA,
      "POST /reviews/r1/response": (body) => ({ ...REVIEW, response: { text: body.text, at: "2026-10-23T12:00:00Z", edited_at: null } }),
    });
    show();
    await screen.findByText("On time, tidy, and the fan is silent.");
    await userEvent.click(screen.getAllByRole("button", { name: "Respond" })[0]);
    await userEvent.type(screen.getByLabelText("Your response"), "Thanks Pat!");
    await userEvent.click(screen.getByRole("button", { name: "Save response" }));
    expect(await screen.findByText("Thanks Pat!")).toBeInTheDocument();
    const sent = calls.find((c) => c.method === "POST" && c.path === "/reviews/r1/response");
    expect(sent.body).toEqual({ text: "Thanks Pat!" });
    // Both cards now offer to edit: this one and the one already answered.
    expect(screen.getAllByRole("button", { name: "Edit response" })).toHaveLength(2);
  });

  it("flags a review for a moderator, with a note", async () => {
    const calls = fakeApi({
      "GET /reviews": DATA,
      "POST /reviews/r1/flag": (body) => ({ ...REVIEW, status: "flagged", flag_note: body.note }),
    });
    show();
    await screen.findByText("On time, tidy, and the fan is silent.");
    await userEvent.click(screen.getAllByRole("button", { name: "Flag for review" })[0]);
    expect(screen.getByText(/stays on your page until a moderator/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Note for the moderator"), "We did show up.");
    await userEvent.click(screen.getByRole("button", { name: "Send flag" }));
    expect(await screen.findByText("Flagged for a moderator")).toBeInTheDocument();
    const sent = calls.find((c) => c.method === "POST" && c.path === "/reviews/r1/flag");
    expect(sent.body).toEqual({ note: "We did show up." });
  });

  it("explains the empty state", async () => {
    fakeApi({ "GET /reviews": { count: 0, average: null, reviews: [] } });
    show();
    expect(await screen.findByText(/No reviews yet/)).toBeInTheDocument();
  });
});
