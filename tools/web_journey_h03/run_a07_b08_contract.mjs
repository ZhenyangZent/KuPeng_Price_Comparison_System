import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const toolRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(toolRoot, "../..");
const runtimeRoot = path.join(projectRoot, "review", "H03", "runtime");
const frontend = process.argv.includes("--frontend=A08") ? "A08" : "A07";
const backend = process.argv.includes("--backend=B09") ? "B09" : "B08";
const frontendPackage = frontend === "A08" ? "CDH_A08_001_REVIEW" : "CDH_A07_001_REVIEW";
const a07Source = path.join(projectRoot, "review", "H03", "baselines", frontend, frontendPackage, "apps", "price-web", "frontend", "src", "runtimeSchema.ts");
const esbuild = path.join(projectRoot, "apps", "price-web", "frontend", "node_modules", "esbuild", "bin", "esbuild");
const compiled = path.join(runtimeRoot, `${frontend.toLowerCase()}-runtime-schema.mjs`);
const input = path.join(runtimeRoot, `${backend}_CASES.json`);
const output = path.join(runtimeRoot, `${frontend}_${backend}_CONTRACT_RESULTS.json`);

await mkdir(runtimeRoot, { recursive: true });
const build = await new Promise((resolve, reject) => {
  const child = spawn(process.execPath, [esbuild, a07Source, "--bundle", "--platform=node", "--format=esm", `--outfile=${compiled}`], { cwd: projectRoot, shell: false, windowsHide: true });
  let stdout = "", stderr = "";
  child.stdout.on("data", (data) => { stdout += data; });
  child.stderr.on("data", (data) => { stderr += data; });
  child.on("error", reject);
  child.on("close", (exitCode) => resolve({ exitCode, stdout, stderr }));
});
if (build.exitCode !== 0) throw new Error(`A07 runtime schema compile failed: ${build.stderr}`);
const parser = await import(`${pathToFileURL(compiled).href}?v=${Date.now()}`);
const fixture = JSON.parse(await readFile(input, "utf8"));
const calls = [];
function call(caseName, method, action) {
  try {
    action();
    calls.push({ case: caseName, method, outcome: "PASS", error_code: null, error_detail: null });
  } catch (error) {
    calls.push({ case: caseName, method, outcome: "FAIL", error_code: error?.code ?? error?.name ?? "UNKNOWN", error_detail: error?.message ?? String(error) });
  }
}
for (const item of fixture.cases) {
  const productId = item.detail.product.id;
  call(item.case, "SEARCH", () => parser.parseSearchV2(item.search));
  call(item.case, "DETAIL", () => parser.parseDetailV2(item.detail, productId));
  call(item.case, "AFFILIATE", () => parser.parseAffiliateV2(item.affiliate, productId));
}
const defectExpected = [
  ["valid", "SEARCH", "PASS"], ["valid", "DETAIL", "PASS"], ["valid", "AFFILIATE", "PASS"],
  ["unavailable", "SEARCH", "FAIL"], ["unavailable", "DETAIL", "FAIL"], ["unavailable", "AFFILIATE", "PASS"],
  ["raw_min_mismatch", "SEARCH", "PASS"], ["raw_min_mismatch", "DETAIL", "FAIL"], ["raw_min_mismatch", "AFFILIATE", "PASS"]
];
const expected = frontend === "A08" && backend === "B09" ? defectExpected.map(([caseName, method]) => [caseName, method, "PASS"]) : defectExpected;
const expectationMatch = expected.every(([caseName, method, outcome]) => calls.some((item) => item.case === caseName && item.method === method && item.outcome === outcome));
const result = {
  task_id: "CDH-H03-A07-B08-INTEGRATION-JOURNEY-001",
  authority: "AUTHORIZED_SYNTHETIC_OFFLINE_ONLY",
  frontend,
  backend,
  parser_source: path.relative(projectRoot, a07Source).replaceAll("\\", "/"),
  backend_case_source: path.relative(projectRoot, input).replaceAll("\\", "/"),
  compile: { exit_code: build.exitCode, stderr: build.stderr.trim() },
  calls,
  counts: { total: calls.length, pass: calls.filter((item) => item.outcome === "PASS").length, fail: calls.filter((item) => item.outcome === "FAIL").length },
  expected_outcome_match: expectationMatch,
  central_reproduction_match: frontend === "A07" && backend === "B08" ? expectationMatch : null,
  product_integration_gate: calls.every((item) => item.outcome === "PASS") ? "PASS" : "FAIL"
};
await writeFile(output, `${JSON.stringify(result, null, 2)}\n`, "utf8");
console.log(JSON.stringify(result));
process.exitCode = expectationMatch ? 0 : 1;
