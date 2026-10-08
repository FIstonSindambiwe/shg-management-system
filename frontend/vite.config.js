import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api calls go to the Django server, so the browser sees one address in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
