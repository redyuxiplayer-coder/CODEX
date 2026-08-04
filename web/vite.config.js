import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/photos": "http://127.0.0.1:8000",
      "/static": "http://127.0.0.1:8000",
      "/admin": "http://127.0.0.1:8000",
      "/mobile": "http://127.0.0.1:8000",
      "/login": "http://127.0.0.1:8000",
      "/logout": "http://127.0.0.1:8000",
    },
  },
});
