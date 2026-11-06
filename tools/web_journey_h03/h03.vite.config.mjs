import path from "node:path";
import { fileURLToPath } from "node:url";

const toolRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(toolRoot, "../..");
const frontend = process.env.H03_FRONTEND === "A08" ? "A08" : "A07";
const frontendPackage = frontend === "A08" ? "CDH_A08_001_REVIEW" : "CDH_A07_001_REVIEW";
const root = path.join(projectRoot, "review", "H03", "baselines", frontend, frontendPackage, "apps", "price-web", "frontend");
const modules = path.join(projectRoot, "apps", "price-web", "frontend", "node_modules");

export default {
  root,
  esbuild: { jsx: "automatic" },
  resolve: {
    alias: [
      { find: "react/jsx-dev-runtime", replacement: path.join(modules, "react", "jsx-dev-runtime.js") },
      { find: "react/jsx-runtime", replacement: path.join(modules, "react", "jsx-runtime.js") },
      { find: "react-dom/client", replacement: path.join(modules, "react-dom", "client.js") },
      { find: "react-dom", replacement: path.join(modules, "react-dom", "index.js") },
      { find: "react", replacement: path.join(modules, "react", "index.js") }
    ]
  },
  server: {
    fs: { allow: [projectRoot] }
  }
};
