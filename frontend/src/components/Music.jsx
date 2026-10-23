// Break Room music: YouTube's official embedded player (a YouTube integration, not a partnership).
// One player lives above the page routes, so it keeps playing while members move around the site.
// It starts only when tapped, stays at least 200 × 200 with YouTube's own controls, branding and ads,
// and pauses when it's closed, when the site isn't visible, when a recording starts or a game opens.
// It never plays hidden or in the background, and no audio is extracted.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const MusicContext = createContext(null);
export const useMusic = () => useContext(MusicContext);

// Other features announce sound of their own with this event; the music pauses for them.
export const OTHER_SOUND = "tc:other-sound";
export const announceSound = (source) => window.dispatchEvent(new CustomEvent(OTHER_SOUND, { detail: source }));

const ID = /^[A-Za-z0-9_-]{11}$/;
const LIST = /^[A-Za-z0-9_-]{10,64}$/;

// Accepts watch, share, Shorts, Music and playlist links. Returns null for anything else.
export function parseYouTube(text) {
  let url;
  try {
    url = new URL(String(text).trim());
  } catch {
    return null;
  }
  const host = url.hostname.replace(/^(www|m|music)\./, "");
  let videoId = null;
  if (host === "youtu.be") videoId = url.pathname.slice(1).split("/")[0];
  else if (host === "youtube.com" || host === "youtube-nocookie.com") {
    if (url.pathname === "/watch") videoId = url.searchParams.get("v");
    else {
      const m = url.pathname.match(/^\/(shorts|embed|live)\/([^/]+)/);
      if (m) videoId = m[2];
    }
  } else return null;
  const list = url.searchParams.get("list");
  const out = { videoId: videoId && ID.test(videoId) ? videoId : null, list: list && LIST.test(list) ? list : null };
  return out.videoId || out.list ? out : null;
}

export const youTubeUrl = ({ videoId, list }) =>
  videoId ? `https://www.youtube.com/watch?v=${videoId}${list ? `&list=${list}` : ""}` : `https://www.youtube.com/playlist?list=${list}`;

let apiPromise = null;
// Loaded only the first time someone presses Play here.
function loadYouTubeApi() {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (!apiPromise) {
    apiPromise = new Promise((resolve, reject) => {
      const previous = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        previous?.();
        resolve(window.YT);
      };
      const script = document.createElement("script");
      script.src = "https://www.youtube.com/iframe_api";
      script.onerror = () => {
        apiPromise = null;
        reject(new Error("YouTube couldn't be reached."));
      };
      document.head.appendChild(script);
    });
  }
  return apiPromise;
}

const UNAVAILABLE = { 2: "That link doesn't point to a video YouTube can play.", 5: "This video can't play in the browser here.", 100: "This video was removed or made private.", 101: "YouTube won't play this video here. Often the owner only allows it on YouTube.", 150: "YouTube won't play this video here. Often the owner only allows it on YouTube." };

function Player({ source, expanded, onExpand, onClose }) {
  const holder = useRef(null);
  const player = useRef(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    loadYouTubeApi()
      .then((YT) => {
        if (cancelled || !holder.current) return;
        const el = document.createElement("div");
        holder.current.replaceChildren(el);
        player.current = new YT.Player(el, {
          host: "https://www.youtube-nocookie.com",
          width: "100%",
          height: "100%",
          videoId: source.videoId || undefined,
          playerVars: { playsinline: 1, rel: 0, ...(source.list ? { listType: "playlist", list: source.list } : {}) },
          events: {
            // The member pressed Play here, so start; if the browser blocks it, YouTube's own play button is there.
            onReady: (e) => e.target.playVideo(),
            onError: (e) => setError(UNAVAILABLE[e.data] || "This video can't be played here."),
            onStateChange: (e) => e.data === 1 && api("/usage", { method: "POST", body: { event: "music_played" } }).catch(() => {}),
          },
        });
      })
      .catch((err) => setError(err.message));
    return () => {
      cancelled = true;
      try {
        player.current?.destroy();
      } catch {
        /* already gone */
      }
      player.current = null;
    };
  }, [source]);

  // Pause whenever the site isn't on screen, a recording starts or a game opens.
  useEffect(() => {
    const pause = () => {
      try {
        player.current?.pauseVideo?.();
      } catch {
        /* not ready yet */
      }
    };
    const onVisibility = () => document.visibilityState === "hidden" && pause();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", pause);
    window.addEventListener(OTHER_SOUND, pause);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", pause);
      window.removeEventListener(OTHER_SOUND, pause);
    };
  }, []);

  const close = () => {
    try {
      player.current?.pauseVideo?.();
    } catch {
      /* not ready yet */
    }
    onClose();
  };

  return (
    <aside className={`music-player ${expanded ? "music-expanded" : "music-compact"}`} aria-label="Music player">
      <div className="music-bar">
        <span className="small">YouTube</span>
        <span className="row" style={{ gap: 4 }}>
          <button type="button" className="btn btn-small" onClick={onExpand}>{expanded ? "Smaller" : "Bigger"}</button>
          <a className="btn btn-small" href={youTubeUrl(source)} target="_blank" rel="noreferrer" onClick={close}>Open in YouTube</a>
          <button type="button" className="btn btn-small" onClick={close} aria-label="Close player">Close</button>
        </span>
      </div>
      {error ? (
        <div className="music-error" role="alert">
          <p>{error}</p>
          <a href={youTubeUrl(source)} target="_blank" rel="noreferrer">Try it on YouTube</a>
        </div>
      ) : (
        <div className="music-frame" ref={holder} data-testid="music-frame" />
      )}
    </aside>
  );
}

export function MusicProvider({ children }) {
  const [source, setSource] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const play = useCallback((parsed) => {
    setSource(parsed);
    api("/usage", { method: "POST", body: { event: "music_opened" } }).catch(() => {});
  }, []);
  return (
    <MusicContext.Provider value={{ source, play, close: () => setSource(null) }}>
      {children}
      {source && <Player source={source} expanded={expanded} onExpand={() => setExpanded(!expanded)} onClose={() => setSource(null)} />}
    </MusicContext.Provider>
  );
}
