import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { YouTubeClipPanel, YouTubeConnect } from "../components/YouTube.jsx";
import { fakeApi } from "./fakeApi.js";

const OFF = { configured: false, plan_includes: true, connected: false, channel: null, needs_reconnect: false, daily_cap: 6, uploads_today: 0 };
const FREE = { ...OFF, configured: true, plan_includes: false };
const READY = { ...OFF, configured: true };
const CONNECTED = { ...READY, connected: true, channel: { id: "chan-1", title: "Bright Spark TV" }, uploads_today: 2 };

describe("YouTube settings card", () => {
  it("is honest while the site hasn't switched it on", async () => {
    fakeApi({ "GET /youtube/status": OFF });
    render(<MemoryRouter><YouTubeConnect /></MemoryRouter>);
    expect(await screen.findByText(/isn't switched on for this site yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Connect/ })).not.toBeInTheDocument();
  });

  it("tells a free member it comes with the paid plans", async () => {
    fakeApi({ "GET /youtube/status": FREE });
    render(<MemoryRouter><YouTubeConnect /></MemoryRouter>);
    expect(await screen.findByText(/comes with the Starter and Full plans/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Connect/ })).not.toBeInTheDocument();
  });

  it("asks the server for Google's consent URL when connecting", async () => {
    const calls = fakeApi({ "GET /youtube/status": READY, "GET /youtube/connect": { url: "https://accounts.google.com/o/oauth2/v2/auth?state=x" } });
    render(<MemoryRouter><YouTubeConnect /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "Connect your YouTube channel" }));
    expect(calls.some((c) => c.method === "GET" && c.path === "/youtube/connect")).toBe(true);
  });

  it("shows the connected channel and disconnects", async () => {
    const calls = fakeApi({ "GET /youtube/status": CONNECTED, "DELETE /youtube/connect": [204, null] });
    render(<MemoryRouter><YouTubeConnect /></MemoryRouter>);
    expect(await screen.findByText("Bright Spark TV")).toBeInTheDocument();
    expect(screen.getByText(/2 of 6 posts used today/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    expect(await screen.findByText(/Disconnected\. The stored sign-in is deleted/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE" && c.path === "/youtube/connect")).toBe(true);
  });
});

describe("YouTube clip panel", () => {
  const clip = { id: "clip1" };

  it("hides the confirm step until the member opts in, then posts what they confirmed", async () => {
    const calls = fakeApi({
      "GET /youtube/status": CONNECTED,
      "GET /youtube/posts": [],
      "POST /youtube/posts": [201, { clip_id: "clip1", status: "queued", title: "Panel swap", visibility: "unlisted" }],
    });
    render(<YouTubeClipPanel clip={clip} />);
    const box = await screen.findByLabelText(/Also post this clip to my YouTube channel/);
    expect(screen.queryByLabelText("YouTube title")).not.toBeInTheDocument();
    await userEvent.click(box);
    expect(screen.getByLabelText("YouTube visibility")).toHaveValue("unlisted");
    expect(screen.getByRole("button", { name: "Post to YouTube" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("YouTube title"), "Panel swap");
    await userEvent.click(screen.getByRole("button", { name: "Post to YouTube" }));
    const post = calls.find((c) => c.method === "POST" && c.path === "/youtube/posts");
    expect(post.body).toEqual({ clip_id: "clip1", title: "Panel swap", description: "", visibility: "unlisted" });
    expect(await screen.findByText(/On its way to YouTube/)).toBeInTheDocument();
  });

  it("shows a posted clip's YouTube link", async () => {
    fakeApi({
      "GET /youtube/status": CONNECTED,
      "GET /youtube/posts": [{ clip_id: "clip1", status: "posted", title: "Panel swap", visibility: "public", url: "https://www.youtube.com/watch?v=vid-9", video_id: "vid-9" }],
    });
    render(<YouTubeClipPanel clip={clip} />);
    const link = await screen.findByRole("link", { name: "Panel swap" });
    expect(link).toHaveAttribute("href", "https://www.youtube.com/watch?v=vid-9");
    expect(screen.queryByLabelText(/Also post this clip/)).not.toBeInTheDocument();
  });

  it("shows why a post failed and offers the form again", async () => {
    fakeApi({
      "GET /youtube/status": CONNECTED,
      "GET /youtube/posts": [{ clip_id: "clip1", status: "failed", title: "Panel swap", visibility: "unlisted", error: "YouTube refused the file." }],
    });
    render(<YouTubeClipPanel clip={clip} />);
    expect(await screen.findByText(/That post didn't go through: YouTube refused the file\./)).toBeInTheDocument();
    expect(screen.getByLabelText(/Also post this clip/)).toBeInTheDocument();
  });

  it("points an unconnected member at Settings", async () => {
    fakeApi({ "GET /youtube/status": READY, "GET /youtube/posts": [] });
    render(<YouTubeClipPanel clip={clip} />);
    expect(await screen.findByText(/Connect your channel under Settings/)).toBeInTheDocument();
  });
});
