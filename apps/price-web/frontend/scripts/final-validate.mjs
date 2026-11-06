import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = path.resolve(frontendRoot, "../../..");
const logRoot = path.join(projectRoot, "reports", "A08", "logs");
await mkdir(logRoot, { recursive: true });

function execute(name, script, args = []) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script, ...args], {
      cwd: frontendRoot,
      env: process.env,
      shell: false,
      windowsHide: true
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (data) => { stdout += data.toString(); process.stdout.write(data); });
    child.stderr.on("data", (data) => { stderr += data.toString(); process.stderr.write(data); });
    child.on("error", reject);
    child.on("close", async (code) => {
      const record = { name, command: `node ${path.relative(frontendRoot, script)} ${args.join(" ")}`.trim(), exit_code: code, stdout, stderr };
      await writeFile(path.join(logRoot, `${name}.json`), `${JSON.stringify(record, null, 2)}\n`, "utf8");
      resolve(record);
    });
  });
}

const results = [];
results.push(await execute("TYPECHECK", path.join(frontendRoot, "node_modules", "typescript", "bin", "tsc"), ["-b"]));
if (results.at(-1).exit_code === 0) results.push(await execute("BUILD", path.join(frontendRoot, "node_modules", "vite", "bin", "vite.js"), ["build"]));
if (results.at(-1).exit_code === 0) results.push(await execute("UNIT_TESTS", path.join(frontendRoot, "scripts", "run-tests.mjs")));
if (results.at(-1).exit_code === 0) results.push(await execute("ROLE_PATH_TESTS", path.join(frontendRoot, "scripts", "run-role-tests.mjs")));
if (results.at(-1).exit_code === 0) results.push(await execute("A08_ROLE_PATH_TESTS", path.join(frontendRoot, "scripts", "run-a08-role-tests.mjs")));
const summary = {
  task_id: "CDH-A08-UNAVAILABLE-AND-HISTORY-SEMANTICS-001",
  created_at_utc: new Date().toISOString(),
  results: results.map(({ name, command, exit_code }) => ({ name, command, exit_code })),
  all_pass: results.length === 5 && results.every((result) => result.exit_code === 0)
};
await writeFile(path.join(logRoot, "FINAL_VALIDATION.json"), `${JSON.stringify(summary, null, 2)}\n`, "utf8");
console.log(JSON.stringify(summary));
process.exitCode = summary.all_pass ? 0 : 1;
