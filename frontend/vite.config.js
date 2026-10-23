import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend serves the built app at /app; in development, Vite proxies API calls to it.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/p": "http://localhost:8000",
      "/static": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
  },
});
