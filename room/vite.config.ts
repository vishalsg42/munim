import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Built straight into the Python package so `munim-room` serves it with no
// separate static host and no CORS.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../src/munim/room/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8977" } },
});
