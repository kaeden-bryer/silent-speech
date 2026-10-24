import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true, // reachable from phones on the same network / tunnels
    allowedHosts: true, // allow cloudflared/ngrok hostnames
    proxy: {
      "/api": "http://localhost:8000", // backend during development
    },
  },
});
