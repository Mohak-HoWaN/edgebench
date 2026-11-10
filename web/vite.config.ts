import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the page is served by Vite and the API by the Python server; the proxy keeps them same-origin
// (the server's WebSocket origin check relies on that).
const server = process.env.EDGEBENCH_SERVER ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  // Object form on purpose: the string shorthand turns on changeOrigin, which rewrites Host but not Origin, and the
  // server's same-origin check then refuses every POST.
  server: {
    proxy: {
      "/api": { target: server, changeOrigin: false },
      "/agent": { target: server, changeOrigin: false }, // so the connection command shown in the app works in development too
      "/ws": { target: server, ws: true, changeOrigin: false },
    },
  },
});
