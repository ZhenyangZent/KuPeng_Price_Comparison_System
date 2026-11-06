import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(frontendRoot, "../../..");
export default defineConfig({ root: projectRoot, test: { environment: "node", include: ["tests/web/frontend_a10/**/*.test.ts"], restoreMocks: true } });
