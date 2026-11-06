import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(frontendRoot, "../../..");

export default defineConfig({
  root: projectRoot,
  plugins: [react()],
  resolve: {
    alias: {
      react: path.join(frontendRoot, "node_modules", "react"),
      "react-dom": path.join(frontendRoot, "node_modules", "react-dom"),
      "@testing-library/react": path.join(frontendRoot, "node_modules", "@testing-library", "react"),
      "@testing-library/jest-dom": path.join(frontendRoot, "node_modules", "@testing-library", "jest-dom")
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: path.join(projectRoot, "tests", "web", "frontend_a07", "setup.ts"),
    include: ["tests/web/frontend_a07/**/*.test.{ts,tsx}"],
    restoreMocks: true
  }
});
