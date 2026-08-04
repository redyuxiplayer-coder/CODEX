import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => ({
  // 生产环境挂在 /app 下，资源路径必须带 /app/ 前缀；开发模式保持根路径
  base: mode === "production" ? "/app/" : "/",
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
}));
