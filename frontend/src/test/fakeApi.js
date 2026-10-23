import { vi } from "vitest";

// Replaces fetch with a tiny in-memory router: { "GET /inbox": body | (request) => body }.
export function fakeApi(routes) {
  const calls = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init = {}) => {
    const method = init.method || "GET";
    const path = String(url).replace(/^\/api/, "");
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, path, body, headers: init.headers });
    const handler = routes[`${method} ${path}`];
    if (handler === undefined) return new Response(JSON.stringify({ detail: "Not found" }), { status: 404 });
    const result = typeof handler === "function" ? handler(body) : handler;
    const [status, payload] = Array.isArray(result) && typeof result[0] === "number" ? result : [200, result];
    return status === 204 ? new Response(null, { status }) : new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}
