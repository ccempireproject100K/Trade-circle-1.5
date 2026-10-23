import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { DictateButton } from "../components/Dictation.jsx";
import { Notice } from "../components/Form.jsx";

// The contractor AI helper. The conversation lives only on this screen; the server keeps counts, not questions.
const longDate = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { month: "long", day: "numeric" });

export function Allowance({ status, noun = "questions" }) {
  if (!status) return null;
  if (!status.available) return <p className="notice notice-error">{status.notice}</p>;
  return (
    <p className="small muted" style={{ margin: 0 }}>
      {status.remaining_today} of {status.daily_limit} {noun} left today · {status.remaining_this_month} of {status.monthly_limit} left this month. Daily count resets{" "}
      {longDate(status.day_resets_on)}, monthly count {longDate(status.month_resets_on)} (midnight {status.timezone.split("/").pop().replace("_", " ")} time).
    </p>
  );
}

export default function Helper() {
  const [status, setStatus] = useState(null);
  const [turns, setTurns] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/helper").then(setStatus, (err) => setError(err.message));
  }, []);

  const ask = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api("/helper/ask", { method: "POST", body: { question, history: turns.slice(-6) } });
      setTurns([...turns, { role: "user", content: question }, { role: "assistant", content: res.answer }]);
      setQuestion("");
      setStatus(res.status);
    } catch (err) {
      setError(err.message);
      api("/helper").then(setStatus, () => {});
    }
    setBusy(false);
  };

  const out = status && (!status.available || status.remaining_today === 0);
  return (
    <>
      <h1>Ask the AI helper</h1>
      <p className="small" style={{ marginTop: 0 }}>
        Trade questions, materials research and help using Trade Circle. Answers can be wrong: check codes, manufacturer instructions and your inspector before relying on them.
        It's not a licensed professional or a certification.
      </p>
      <Allowance status={status} />
      {status?.available && status.remaining_today === 0 && <p className="notice notice-error">{status.notice}</p>}
      <ul className="items" aria-live="polite">
        {turns.map((t, i) => (
          <li key={i} className={t.role === "user" ? "card" : "card ai-answer"} style={{ margin: 0 }}>
            <p className="small muted" style={{ margin: 0 }}>{t.role === "user" ? "You" : "AI helper"}</p>
            <p className="item-message" style={{ margin: "4px 0 0" }}>{t.content}</p>
          </li>
        ))}
      </ul>
      <form className="stack" onSubmit={ask}>
        <textarea aria-label="Your question" required minLength={3} maxLength={2000} value={question} onChange={(e) => setQuestion(e.target.value)} disabled={out || busy}
          placeholder="What size breaker for a 30 amp dryer circuit with 10 AWG copper?" />
        <DictateButton onText={(t) => setQuestion((q) => `${q.trimEnd()} ${t}`.trim())} />
        <Notice error={error} />
        <button className="btn btn-primary" disabled={out || busy}>{busy ? "Thinking…" : "Ask"}</button>
      </form>
      <p className="small muted">Looking for a part? Try <Link to="/supplies/parts">part lookup</Link>.</p>
    </>
  );
}
