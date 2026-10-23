import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ShareRouter from "../pages/ShareRouter.jsx";
import { fakeApi } from "./fakeApi.js";

// A stand-in for the browser's speech recognition, driven by the test.
class FakeRecognition {
  static last = null;
  static failWith = null;
  constructor() {
    FakeRecognition.last = this;
    this.started = false;
  }
  start() {
    this.started = true;
    if (FakeRecognition.failWith) setTimeout(() => { this.onerror({ error: FakeRecognition.failWith }); this.onend(); });
  }
  stop() {
    this.started = false;
    setTimeout(() => this.onend());
  }
  abort() {
    this.started = false;
  }
  say(text) {
    this.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: text }], { isFinal: true })] });
  }
}

const META = { trades: ["electrician", "plumber"], kinds: [], supply_categories: [], review_topics: [], report_reasons: [] };

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/share" element={<ShareRouter />} />
        <Route path="/share/:kind/:id?" element={<ShareRouter />} />
        <Route path="/posts/:id" element={<p>Published page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  FakeRecognition.last = null;
  FakeRecognition.failWith = null;
});
afterEach(() => {
  delete window.SpeechRecognition;
  delete window.webkitSpeechRecognition;
  vi.resetModules();
});

async function freshShare(routes = {}) {
  // The dictation module reads window.SpeechRecognition when it loads.
  vi.resetModules();
  const { default: Router } = await import("../pages/ShareRouter.jsx");
  const calls = fakeApi({ "GET /community/meta": META, "GET /posts/mine?kind=project&post_status=draft": [], ...routes });
  render(
    <MemoryRouter initialEntries={["/share/project"]}>
      <Routes>
        <Route path="/share/:kind/:id?" element={<Router />} />
        <Route path="/posts/:id" element={<p>Published page</p>} />
      </Routes>
    </MemoryRouter>,
  );
  return calls;
}

describe("Share a project", () => {
  it("asks one question at a time with Back and Skip", async () => {
    await freshShare();
    expect(await screen.findByRole("heading", { name: "What was the job?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(screen.getByRole("heading", { name: "Do you have before photos?" })).toBeInTheDocument();
    expect(screen.getByText(/Don't include customer names, addresses/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("heading", { name: "What was the job?" })).toBeInTheDocument();
  });

  it("falls back to typing when voice isn't available", async () => {
    await freshShare();
    await screen.findByRole("heading", { name: "What was the job?" });
    expect(screen.queryByRole("button", { name: /Tap to talk/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Voice typing isn't available in this browser/)).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "What was the job?" }), "Panel swap");
    expect(screen.getByRole("textbox", { name: "What was the job?" })).toHaveValue("Panel swap");
  });

  it("listens only after a tap, shows it's recording, and stops on Stop", async () => {
    window.SpeechRecognition = FakeRecognition;
    await freshShare();
    await screen.findByRole("heading", { name: "What was the job?" });
    expect(FakeRecognition.last).toBeNull(); // nothing listening until tapped
    await userEvent.click(screen.getByRole("button", { name: /Tap to talk/ }));
    expect(screen.getByText("Listening… speak now")).toBeInTheDocument();
    act(() => FakeRecognition.last.say("Swapped a 100 amp panel for 200 amp"));
    expect(screen.getByRole("textbox", { name: "What was the job?" })).toHaveValue("Swapped a 100 amp panel for 200 amp");
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(screen.queryByText("Listening… speak now")).not.toBeInTheDocument());
    expect(FakeRecognition.last.started).toBe(false);
  });

  it("keeps typing available when microphone permission is declined", async () => {
    window.SpeechRecognition = FakeRecognition;
    FakeRecognition.failWith = "not-allowed";
    await freshShare();
    await userEvent.click(await screen.findByRole("button", { name: /Tap to talk/ }));
    expect(await screen.findByText(/Microphone access is blocked, so you can type instead/)).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "What was the job?" }), "Typed anyway");
    expect(screen.getByRole("textbox", { name: "What was the job?" })).toHaveValue("Typed anyway");
  });

  it("autosaves a draft and only publishes after preview and an explicit tap", async () => {
    const calls = await freshShare({
      "POST /posts": [201, { id: "d1", kind: "project", status: "draft", fields: {}, photos: [], trade_tags: [] }],
      "PATCH /posts/d1": { id: "d1" },
      "POST /posts/d1/publish": { id: "d1", status: "published" },
    });
    await userEvent.type(await screen.findByRole("textbox", { name: "What was the job?" }), "Rewired a 1950s kitchen. Old cloth wiring.");
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/posts")).toBe(true), { timeout: 3000 });
    const created = calls.find((c) => c.method === "POST" && c.path === "/posts").body;
    expect(created).toMatchObject({ kind: "project", fields: { job: "Rewired a 1950s kitchen. Old cloth wiring." } });
    expect(created.publish).toBeUndefined();
    expect(await screen.findByText("Draft saved")).toBeInTheDocument();

    for (let i = 0; i < 6; i += 1) {
      await userEvent.click(screen.getByRole("button", { name: /^(Skip|Next)$/ }));
    }
    expect(screen.getByRole("heading", { name: "Check your post" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/publish"))).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    // The title comes from the member's own first sentence, not invented text.
    expect(await screen.findByRole("heading", { name: "Rewired a 1950s kitchen." })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByText("Published page")).toBeInTheDocument();
    const lastPatch = calls.filter((c) => c.method === "PATCH").pop().body;
    expect(lastPatch.title).toBe("Rewired a 1950s kitchen.");
  });

  it("saves right away when leaving the screen before autosave runs", async () => {
    vi.resetModules();
    const { default: Router } = await import("../pages/ShareRouter.jsx");
    const calls = fakeApi({ "GET /community/meta": META, "GET /posts/mine?kind=project&post_status=draft": [], "POST /posts": [201, { id: "d2" }] });
    const view = render(
      <MemoryRouter initialEntries={["/share/project"]}>
        <Routes><Route path="/share/:kind/:id?" element={<Router />} /></Routes>
      </MemoryRouter>,
    );
    await userEvent.type(await screen.findByRole("textbox", { name: "What was the job?" }), "Quick answer");
    expect(screen.getByText("Unsaved changes…")).toBeInTheDocument();
    // A copy is already on the phone.
    expect(JSON.parse(localStorage.getItem("tc-draft-project-new")).answers.job).toBe("Quick answer");
    view.unmount();
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/posts")).toBe(true));
    expect(calls.find((c) => c.method === "POST").body.fields.job).toBe("Quick answer");
  });

  it("offers to continue an existing draft", async () => {
    fakeApi({
      "GET /community/meta": META,
      "GET /posts/mine?kind=project&post_status=draft": [{ id: "d9", title: "", fields: { job: "Deck ledger repair" }, updated_at: "2026-10-22T10:00:00Z" }],
    });
    renderAt("/share/project");
    expect(await screen.findByText("Deck ledger repair")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue draft" })).toHaveAttribute("href", "/share/project/d9");
  });

  it("recovers answers that never reached the server", async () => {
    localStorage.setItem("tc-draft-project-new", JSON.stringify({ answers: { job: "Saved on the phone only" }, photos: [], title: "", tags: [], featured: false, step: 0 }));
    await freshShare({ "POST /posts": [503, { detail: "down" }] });
    expect(await screen.findByText(/recovered answers that hadn't been saved/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "What was the job?" })).toHaveValue("Saved on the phone only");
  });
});

describe("Post body", () => {
  it("shows before and finished photos even when the nearby answers were skipped", async () => {
    const { PostBody } = await import("../pages/PostDetail.jsx");
    render(
      <PostBody
        post={{ kind: "project", body: "", fields: { job: "", challenge: "", handled: "", learned: "Lesson" }, photos_hidden: false,
          photos: [{ id: "b", group: "before", thumb_url: "/b.jpg", image_url: "/b.jpg" }, { id: "a", group: "after", thumb_url: "/a.jpg", image_url: "/a.jpg" }] }}
      />,
    );
    expect(screen.getByRole("heading", { name: "Before" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Finished" })).toBeInTheDocument();
    expect(screen.getByAltText("Finished")).toHaveAttribute("src", "/a.jpg");
  });
});
