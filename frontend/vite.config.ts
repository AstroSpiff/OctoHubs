import { defineConfig } from "vite";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const apiTarget = process.env.OCTOHUBS_API_PROXY_TARGET || "http://127.0.0.1:5052";

export default defineConfig({
  base: "/app/",
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": apiTarget,
      "/ws": { target: apiTarget.replace(/^http/, "ws"), ws: true },
      "/login": apiTarget,
      "/logout": apiTarget,
      "/static": apiTarget,
      "/dashboard": apiTarget,
      "/emby": apiTarget,
      "/collections": apiTarget,
      "/probe": apiTarget,
      "/configuration": apiTarget,
    },
  },
});
