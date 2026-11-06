import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const toolRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(toolRoot, "../..");
const runtime = path.join(projectRoot, "review", "H03", "runtime");
const frontend = process.argv.includes("--frontend=A08") ? "A08" : "A07";
const backend = process.argv.includes("--backend=B09") ? "B09" : "B08";
const pair = `${frontend}_${backend}`;
const output = path.join(runtime, `integration-report-${pair}`, "index.html");
const result = JSON.parse(await readFile(path.join(runtime, `${pair}_CONTRACT_RESULTS.json`), "utf8"));
const cases = JSON.parse(await readFile(path.join(runtime, `${backend}_CASES.json`), "utf8"));

const escape = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
const cards = cases.cases.map((fixture) => {
  const calls = result.calls.filter((call) => call.case === fixture.case);
  const rows = calls.map((call) => `<tr><td>${escape(call.method)}</td><td><span class="pill ${call.outcome.toLowerCase()}">${escape(call.outcome)}</span></td><td>${escape(call.error_code ?? "—")}</td><td>${escape(call.error_detail ?? "—")}</td></tr>`).join("");
  return `<section class="case"><header><div><small>TEST_ONLY · ${escape(fixture.case)}</small><h2>${fixture.case === "valid" ? "有效精確商品" : fixture.case === "unavailable" ? "價格不可用（UNAVAILABLE）" : "Raw history 與 daily low 分流"}</h2></div><strong>${calls.every((call) => call.outcome === "PASS") ? "PASS" : "DEFECT REPRODUCED"}</strong></header><dl><dt>raw history min</dt><dd>${escape(fixture.derived.raw_history_min_twd)}</dd><dt>V2 observation min</dt><dd>${escape(fixture.derived.v2_observation_period_min_twd)}</dd><dt>V3 daily period low</dt><dd>${escape(fixture.derived.v3_daily_period_low_twd)}</dd></dl><div class="table"><table><thead><tr><th>Method</th><th>Outcome</th><th>Error</th><th>Visible detail</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}).join("");
const html = `<!doctype html><html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>H03 ${frontend} × ${backend} Integration Evidence</title><style>
:root{font-family:Inter,"Noto Sans TC",system-ui,sans-serif;color:#eef3ff;background:#07101e}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,#17315e 0,transparent 38%),#07101e}main{width:min(1180px,calc(100% - 32px));margin:auto;padding:36px 0 64px}.banner,.case{background:#0d192c;border:1px solid #273a59;border-radius:18px;box-shadow:0 12px 36px #0007}.banner{padding:26px;margin-bottom:22px;border-left:6px solid #ffb02e}.banner small,.case small{color:#91a8cc;letter-spacing:.1em}.banner h1{font-size:clamp(28px,5vw,48px);margin:7px 0}.banner p{color:#bdc9dc;margin:6px 0}.summary{display:flex;gap:12px;flex-wrap:wrap;margin-top:18px}.summary span,.pill{padding:6px 10px;border-radius:999px;background:#162844}.summary .fail,.pill.fail{background:#4b1d2b;color:#ffb6c4}.summary .pass,.pill.pass{background:#143a31;color:#8ff0c4}.case{padding:22px;margin:18px 0}.case header{display:flex;gap:14px;justify-content:space-between;align-items:flex-start}.case h2{margin:5px 0 13px}.case header>strong{color:#ffb6c4}.case dl{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0 18px}.case dt{font-size:12px;color:#91a8cc}.case dd{margin:3px 0;font-size:22px;font-weight:700}.table{overflow:auto}table{width:100%;border-collapse:collapse;min-width:650px}th,td{text-align:left;padding:11px 9px;border-bottom:1px solid #223550;vertical-align:top}th{color:#91a8cc;font-size:12px;text-transform:uppercase}td:last-child{color:#ffced7}footer{color:#91a8cc;text-align:center;padding-top:12px}@media(max-width:600px){main{width:min(100% - 18px,1180px);padding-top:18px}.banner,.case{border-radius:12px;padding:16px}.case header{display:block}.case dl{grid-template-columns:1fr}.banner h1{font-size:28px}}
</style></head><body><main><section class="banner"><small>CDH-H03 · AUTHORIZED_SYNTHETIC_OFFLINE_ONLY</small><h1>${frontend} × ${backend} 契約整合${result.product_integration_gate === "PASS" ? "驗證" : "重現"}</h1><p>精確交件版本；沒有真實商品、沒有外部擷取、沒有購物或分潤點擊。</p><div class="summary"><span>${result.counts.total} calls</span><span class="pass">${result.counts.pass} PASS</span><span class="fail">${result.counts.fail} FAIL</span><span class="${result.product_integration_gate === "PASS" ? "pass" : "fail"}">PRODUCT INTEGRATION: ${result.product_integration_gate}</span></div></section>${cards}<footer>CDH H03 independent evidence · TEST_ONLY</footer></main></body></html>`;
await mkdir(path.dirname(output), { recursive: true });
await writeFile(output, html, "utf8");
console.log(JSON.stringify({ status: "PASS", output }));
