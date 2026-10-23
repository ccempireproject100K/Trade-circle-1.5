// Tap-to-talk dictation using the browser's built-in speech recognition.
// It listens only between a tap on "Tap to talk" and a tap on "Stop" (or when the
// person pauses long enough that the browser ends it). Nothing listens in the background.
import { useEffect, useRef, useState } from "react";
import { announceSound } from "./Music.jsx";

const Recognition = typeof window !== "undefined" ? window.SpeechRecognition || window.webkitSpeechRecognition : undefined;

export function useDictation(onText) {
  const [state, setState] = useState(Recognition ? "idle" : "unsupported"); // idle | listening | denied | error | unsupported
  const [interim, setInterim] = useState("");
  const recognizer = useRef(null);
  const callback = useRef(onText);
  callback.current = onText;

  const stop = () => {
    recognizer.current?.stop();
  };

  const start = () => {
    if (!Recognition || recognizer.current) return;
    const r = new Recognition();
    r.lang = navigator.language || "en-US";
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (event) => {
      let finished = "";
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const text = event.results[i][0].transcript;
        if (event.results[i].isFinal) finished += text;
        else pending += text;
      }
      if (finished.trim()) callback.current(finished.trim());
      setInterim(pending);
    };
    r.onerror = (event) => {
      setState(event.error === "not-allowed" || event.error === "service-not-allowed" ? "denied" : "error");
    };
    r.onend = () => {
      recognizer.current = null;
      setInterim("");
      setState((s) => (s === "listening" ? "idle" : s));
    };
    recognizer.current = r;
    setState("listening");
    try {
      announceSound("recording"); // the Break Room music pauses while the member talks
      r.start();
    } catch {
      recognizer.current = null;
      setState("error");
    }
  };

  // Leaving the step or the page always stops the microphone.
  useEffect(() => () => recognizer.current?.abort(), []);

  return { state, interim, start, stop };
}

export function DictateButton({ onText }) {
  const { state, interim, start, stop } = useDictation(onText);

  if (state === "unsupported") {
    return <p className="field-hint">Voice typing isn't available in this browser. Type instead, or use the microphone key on your phone's keyboard.</p>;
  }

  return (
    <div className="stack" style={{ gap: 6 }}>
      {state === "listening" ? (
        <div className="recording" role="status">
          <span className="rec-dot" aria-hidden="true" />
          <span>Listening… speak now</span>
          <button type="button" className="btn btn-small btn-danger" onClick={stop}>Stop</button>
        </div>
      ) : (
        <button type="button" className="btn" onClick={start}>🎤 Tap to talk</button>
      )}
      {interim && <p className="small muted" style={{ margin: 0 }}>{interim}</p>}
      {state === "denied" && (
        <p className="notice notice-error small">Microphone access is blocked, so you can type instead. To use your voice, allow the microphone for this site in your browser settings.</p>
      )}
      {state === "error" && <p className="notice notice-error small">Voice typing stopped. Tap to talk to try again, or type instead.</p>}
      <p className="field-hint">Your browser (Apple or Google) turns speech into text. Trade Circle only receives the text you keep.</p>
    </div>
  );
}
