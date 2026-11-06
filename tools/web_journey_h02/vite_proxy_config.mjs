import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const frontendRoot = path.join(projectRoot, "review", "H02", "baselines", "A06", "apps", "price-web", "frontend");
const proxy = {
  "/cdh-local-api": {
    target: "http://127.0.0.1:8765",
    changeOrigin: false,
    rewrite: (requestPath) => requestPath.replace(/^\/cdh-local-api/, "")
  }
};

// This H02-owned config reproduces the exact frozen A06 preview host, port,
// strictPort and proxy fields while serving the SHA-bound extracted A06 dist.
export default {
  root: frontendRoot,
  preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy }
};

