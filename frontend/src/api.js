// Talks to the Trade Circle API. The session lives in an HttpOnly cookie, so this
// file never sees the token; writes carry the CSRF header the backend requires.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function messageFrom(status, payload) {
  const detail = payload && payload.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.message === "string") return detail.message;
  if (Array.isArray(detail) && detail.length) {
    // Validation errors: name the field in plain words.
    const first = detail[0];
    const field = (first.loc || []).filter((part) => part !== "body").join(" ").replace(/_/g, " ");
    const text = (first.msg || "is not valid").replace(/^Value error, /, "");
    return field ? `${field[0].toUpperCase()}${field.slice(1)}: ${text}` : text;
  }
  if (status === 429) return "Too many tries. Please wait a few minutes.";
  return "Something went wrong. Please try again.";
}

// When a teammate chooses to work for a business, every request names it. The server
// checks their access each time; pages for the member's own account ignore it.
export const acting = {
  get() {
    try {
      return JSON.parse(sessionStorage.getItem("tc-business"));
    } catch {
      return null;
    }
  },
  set(business) {
    try {
      if (business) sessionStorage.setItem("tc-business", JSON.stringify(business));
      else sessionStorage.removeItem("tc-business");
    } catch {
      /* storage blocked: stays on the member's own account */
    }
  },
};

// `own: true` always means the signed-in member's own account, even while working for a business.
export async function api(path, { method = "GET", body, own = false } = {}) {
  const headers = { Accept: "application/json" };
  const business = own ? null : acting.get();
  if (business) headers["X-TC-Business"] = business.id;
  if (method !== "GET") headers["X-TC-CSRF"] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return null;
  const payload = await res.json().catch(() => null);
  if (!res.ok) {
    const error = new ApiError(res.status, messageFrom(res.status, payload));
    // "member" or "community" for AI limits, so the screen can explain whose limit it was.
    error.who = payload?.detail?.who;
    throw error;
  }
  return payload;
}

// Uploads a photo with progress reporting (fetch can't report upload progress).
// Portfolio photos go to the portfolio; pass to="/media/photos" for photos attached to posts.
export function uploadPhoto(file, caption, onProgress, to = "/me/portfolio/upload") {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${to}`);
    xhr.setRequestHeader("X-TC-CSRF", "1");
    xhr.setRequestHeader("Accept", "application/json");
    if (acting.get()) xhr.setRequestHeader("X-TC-Business", acting.get().id);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      let payload = null;
      try {
        payload = JSON.parse(xhr.responseText);
      } catch {
        payload = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(payload);
      else reject(new ApiError(xhr.status, messageFrom(xhr.status, payload)));
    };
    xhr.onerror = () => reject(new ApiError(0, "Upload failed. Check your connection and try again."));
    const form = new FormData();
    form.append("file", file);
    if (caption !== null) form.append("caption", caption || "");
    xhr.send(form);
  });
}

export const dollars = (cents) =>
  cents == null ? "" : (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });

export const toCents = (text) => {
  const value = String(text).replace(/[$,\s]/g, "");
  if (!value) return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? Math.round(number * 100) : NaN;
};

export const label = (value) =>
  value === "hvac" ? "HVAC" : String(value).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export const shortDate = (iso) =>
  iso ? new Date(iso.length === 10 ? `${iso}T12:00:00` : iso).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "";

// Today's date in the contractor's own time zone, as YYYY-MM-DD.
export const localToday = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
