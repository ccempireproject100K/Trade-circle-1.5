import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AuthStubProvider } from "../auth.jsx";
import { announceSound, MusicProvider, parseYouTube, youTubeUrl } from "../components/Music.jsx";
import BreakRoom from "../pages/BreakRoom.jsx";
import { fakeApi } from "./fakeApi.js";

// A stand-in for YouTube's IFrame API that records what the page asks of it.
function fakeYouTube() {
  const players = [];
  window.YT = {
    Player: class {
      constructor(el, opts) {
        this.opts = opts;
        this.paused = 0;
        this.destroyed = false;
        players.push(this);
        setTimeout(() => opts.events.onReady({ target: this }), 0);
      }
      playVideo() {
        this.playing = true;
      }
      pauseVideo() {
        this.paused += 1;
      }
      destroy() {
        this.destroyed = true;
      }
    },
  };
  return players;
}

const ROUTES = { "POST /usage": [204, null], "GET /break-room/listings?kind=public_offer": { near: null, listings: [] }, "GET /posts?kind=spot": { posts: [] } };

function renderRoom() {
  return render(<AuthStubProvider><MemoryRouter><MusicProvider><BreakRoom /></MusicProvider></MemoryRouter></AuthStubProvider>);
}

describe("YouTube links", () => {
  it("accepts watch, share, Shorts, Music and playlist links only", () => {
    expect(parseYouTube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")).toEqual({ videoId: "dQw4w9WgXcQ", list: null });
    expect(parseYouTube("https://youtu.be/dQw4w9WgXcQ?si=abc")).toEqual({ videoId: "dQw4w9WgXcQ", list: null });
    expect(parseYouTube("https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1234567890ab")).toEqual({ videoId: "dQw4w9WgXcQ", list: "PL1234567890ab" });
    expect(parseYouTube("https://www.youtube.com/shorts/dQw4w9WgXcQ").videoId).toBe("dQw4w9WgXcQ");
    expect(parseYouTube("https://www.youtube.com/playlist?list=PL1234567890ab")).toEqual({ videoId: null, list: "PL1234567890ab" });
    expect(parseYouTube("https://evil.example.com/watch?v=dQw4w9WgXcQ")).toBeNull();
    expect(parseYouTube("not a link")).toBeNull();
    expect(youTubeUrl({ videoId: null, list: "PL1234567890ab" })).toBe("https://www.youtube.com/playlist?list=PL1234567890ab");
  });
});

describe("Music player", () => {
  let players;
  beforeEach(() => {
    players = fakeYouTube();
  });
  afterEach(() => {
    delete window.YT;
  });

  it("starts only on tap, then pauses when the site is hidden, a recording starts, or it's closed", async () => {
    fakeApi(ROUTES);
    renderRoom();
    expect(players).toHaveLength(0);
    await userEvent.type(screen.getByLabelText("YouTube link"), "https://youtu.be/dQw4w9WgXcQ");
    expect(players).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Play here" }));
    await act(() => new Promise((r) => setTimeout(r, 5)));
    expect(players).toHaveLength(1);
    const p = players[0];
    expect(p.opts.videoId).toBe("dQw4w9WgXcQ");
    expect(p.playing).toBe(true);

    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(p.paused).toBe(1);
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });

    act(() => announceSound("recording"));
    expect(p.paused).toBe(2);

    await userEvent.click(screen.getByRole("button", { name: "Close player" }));
    expect(p.paused).toBe(3);
    expect(p.destroyed).toBe(true);
    expect(screen.queryByLabelText("Music player")).not.toBeInTheDocument();
  });

  it("shows a way out when a video can't play here", async () => {
    fakeApi(ROUTES);
    renderRoom();
    await userEvent.type(screen.getByLabelText("YouTube link"), "https://youtu.be/dQw4w9WgXcQ");
    await userEvent.click(screen.getByRole("button", { name: "Play here" }));
    await act(() => new Promise((r) => setTimeout(r, 5)));
    act(() => players[0].opts.events.onError({ data: 150 }));
    expect(screen.getByRole("alert")).toHaveTextContent("YouTube won't play this video here.");
    expect(screen.getByRole("link", { name: "Try it on YouTube" })).toHaveAttribute("href", "https://www.youtube.com/watch?v=dQw4w9WgXcQ");
  });
});

describe("Break Room", () => {
  it("loads a game only when chosen", async () => {
    const calls = fakeApi(ROUTES);
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Games" }));
    expect(document.querySelector("iframe")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Play" }));
    const frame = document.querySelector("iframe");
    expect(frame.getAttribute("src")).toBe("/app/games/2048/index.html");
    expect(calls.some((c) => c.path === "/usage" && c.body.event === "game_opened" && c.body.detail === "2048")).toBe(true);
  });

  it("labels public offers, flags missing end dates and keeps member picks separate", async () => {
    fakeApi({
      ...ROUTES,
      "GET /break-room/listings?kind=public_offer": {
        near: null,
        listings: [{ id: "l1", kind: "public_offer", label: "Public offer", title: "10% off boots", organizer: "Example Boots", official_url: "https://example.com", location: null, expires_on: null, no_end_date: true, needs_recheck: true, last_checked_on: "2026-10-20" }],
      },
      "GET /posts?kind=spot": { posts: [{ id: "s1", kind: "spot", title: "Taco stand", body: "", trade_tags: [], photos: [], fields: { place: "Taco stand", suggestion: "spot", connection: "none" }, author: { business_name: "A" }, comment_count: 0, created_at: "2026-10-01T00:00:00Z" }] },
    });
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Deals & spots" }));
    expect(await screen.findByText("Public offer")).toBeInTheDocument();
    expect(screen.getByText(/No end date published · last checked Oct 20 · details may have changed/)).toBeInTheDocument();
    expect(screen.queryByText(/Sponsored/)).not.toBeInTheDocument();
    expect(await screen.findByText("Member recommendations")).toBeInTheDocument();
    expect(screen.getByText("Member recommendation")).toBeInTheDocument();
  });

  it("explains giveaways are run by their organizers", async () => {
    fakeApi({ ...ROUTES, "GET /break-room/listings?kind=giveaway": { near: null, listings: [] } });
    renderRoom();
    await userEvent.click(screen.getByRole("button", { name: "Giveaways" }));
    expect(await screen.findByText(/doesn't collect or pass on your details, can't promise prizes/)).toBeInTheDocument();
  });
});
