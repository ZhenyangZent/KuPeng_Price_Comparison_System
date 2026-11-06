import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const contentSecurityPolicy = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' ws://127.0.0.1:4173; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'";
const localProxy = {
  "/cdh-local-api": { target: "http://127.0.0.1:8765", changeOrigin: false, rewrite: (path: string) => path.replace(/^\/cdh-local-api/, "") },
  "/cdh-coupon-v4": { target: "http://127.0.0.1:8766", changeOrigin: false, rewrite: (path: string) => path.replace(/^\/cdh-coupon-v4/, "") }
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    headers: { "Content-Security-Policy": contentSecurityPolicy },
    proxy: localProxy
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    headers: { "Content-Security-Policy": contentSecurityPolicy },
    proxy: localProxy
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/testSetup.ts",
    include: ["tests/**/*.test.{ts,tsx}"],
    restoreMocks: true
  }
});
