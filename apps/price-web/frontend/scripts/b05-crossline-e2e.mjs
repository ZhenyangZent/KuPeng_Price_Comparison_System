import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = path.resolve(frontendRoot, "../../..");
const reportRoot = path.join(projectRoot, "reports", "A06", "001");
const evidenceRoot = path.join(reportRoot, "evidence");
const runtimeRoot = path.join(reportRoot, "crossline_runtime", new Date().toISOString().replaceAll(":", "").replaceAll(".", ""));
const database = path.join(runtimeRoot, "a06-b05-test.sqlite3");
const serviceRoot = path.join(projectRoot, "services", "price_query");
const viteBin = path.join(frontendRoot, "node_modules", "vite", "bin", "vite.js");
await Promise.all([mkdir(runtimeRoot, { recursive: true }), mkdir(evidenceRoot, { recursive: true })]);

function run(executable, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { cwd: frontendRoot, shell: false, windowsHide: true, ...options });
    let stdout = "", stderr = "";
    child.stdout?.on("data", (data) => { stdout += data.toString(); });
    child.stderr?.on("data", (data) => { stderr += data.toString(); });
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}
const fixture = await run("python", [path.join(frontendRoot, "scripts", "create-b05-test-fixture.py"), database]);
if (fixture.code !== 0) throw new Error(`fixture creation failed: ${fixture.stderr}`);

const env = { ...process.env, PYTHONPATH: serviceRoot };
const b05 = spawn("python", ["-m", "price_query.server", "--database-copy", database, "--fixture-root", runtimeRoot, "--host", "127.0.0.1", "--port", "8765"], { cwd: projectRoot, env, shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
const vite = spawn(process.execPath, [viteBin, "preview", "--host", "127.0.0.1", "--port", "4173", "--strictPort"], { cwd: frontendRoot, shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
let b05Stdout = "", b05Stderr = "", viteStdout = "", viteStderr = "";
b05.stdout.on("data", (data) => { b05Stdout += data.toString(); });
b05.stderr.on("data", (data) => { b05Stderr += data.toString(); });
vite.stdout.on("data", (data) => { viteStdout += data.toString(); });
vite.stderr.on("data", (data) => { viteStderr += data.toString(); });

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function getJson(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
  const body = await response.json();
  return { response, body };
}
async function waitFor(url) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try { const result = await getJson(url); if (result.response.ok) return result; } catch { /* not ready */ }
    await wait(100);
  }
  throw new Error(`local service did not become ready: ${url}`);
}

let summary;
try {
  const all = await waitFor("http://127.0.0.1:8765/api/v1/products?q=&page=1&limit=100");
  await waitFor("http://127.0.0.1:4173/cdh-local-api/api/v1/products?q=&page=1&limit=100");
  const variant = await getJson("http://127.0.0.1:8765/api/v1/products?q=SKU-XL-42&page=1&limit=20");
  const product = all.body.items?.find((item) => item.variant_signature?.includes("SKU-XL-42"));
  if (!product) throw new Error("bounded catalog did not expose the test variant");
  const detail = await getJson(`http://127.0.0.1:8765/api/v1/products/${encodeURIComponent(product.id)}`);
  const affiliate = await getJson(`http://127.0.0.1:8765/api/v1/products/${encodeURIComponent(product.id)}/affiliate`);
  const proxy = await getJson(`http://127.0.0.1:4173/cdh-local-api/api/v1/products/${encodeURIComponent(product.id)}`);
  const checks = {
    schema_version: all.body.schema_version === "CDH-WEB-CONTRACT-V1" && detail.body.schema_version === "CDH-WEB-CONTRACT-V1",
    source_status: all.body.data_source_status === "USER_RECORDED_ONLY",
    bounded_variant_available: Boolean(product),
    history_count: detail.body.history?.length === 2,
    observation_minimum: detail.body.observation_period_min_twd === 599,
    flat_affiliate_disabled: affiliate.body.state === "UNCONFIGURED" && affiliate.body.click_url === null && affiliate.body.affiliate === undefined,
    same_origin_proxy: proxy.body.product?.id === product.id,
    no_public_cors: all.response.headers.get("access-control-allow-origin") === null && proxy.response.headers.get("access-control-allow-origin") === null
  };
  summary = {
    task_id: "CDH-WEB-A06-FRONTEND-API-INTEGRATION-001",
    backend: "UNMODIFIED_PROJECT_PRICE_QUERY_SERVICE",
    database: "PROJECT_LOCAL_ISOLATED_SYNTHETIC_TEST_FIXTURE",
    direct_variant_query_count: variant.body.total,
    frontend_fallback_required: variant.body.total === 0,
    product_id: product.id,
    raw_item_condition: detail.body.offers?.[0]?.item_condition ?? null,
    detail_source_status_present: detail.body.data_source_status !== undefined,
    checks,
    all_pass: Object.values(checks).every(Boolean),
    fixture_create_exit_code: fixture.code,
    b05_stdout: b05Stdout.trim(), b05_stderr: b05Stderr.trim(), vite_stdout: viteStdout.trim(), vite_stderr: viteStderr.trim()
  };
} finally {
  vite.kill();
  b05.kill();
}
await writeFile(path.join(evidenceRoot, "B05_CROSSLINE_E2E.json"), `${JSON.stringify(summary, null, 2)}\n`, "utf8");
console.log(JSON.stringify(summary));
process.exitCode = summary?.all_pass ? 0 : 1;
