import { readFile, writeFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { stripTypeScriptTypes } from "node:module";

const args = new Map();
for (let index = 2; index < process.argv.length; index += 2) args.set(process.argv[index], process.argv[index + 1]);
const sourcePath = args.get("--source");
const typesPath = args.get("--types");
if (!sourcePath || !typesPath) throw new Error("--source and --types are required");
const input = JSON.parse(await new Promise((resolve, reject) => {
  let value = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", chunk => value += chunk);
  process.stdin.on("end", () => resolve(value));
  process.stdin.on("error", reject);
}));
const directory = await mkdtemp(join(tmpdir(), "cdh-d08-a09-"));
try {
  let source = await readFile(sourcePath, "utf8");
  source = source.replace('from "./couponTypes"', 'from "./couponTypes.mjs"');
  await writeFile(join(directory, "couponTypes.mjs"), stripTypeScriptTypes(await readFile(typesPath, "utf8"), { mode: "transform" }), "utf8");
  await writeFile(join(directory, "couponRuntimeSchema.mjs"), stripTypeScriptTypes(source, { mode: "transform" }), "utf8");
  const runtime = await import(pathToFileURL(join(directory, "couponRuntimeSchema.mjs")).href);
  const results = input.map(item => {
    try {
      return { name: item.name, success: true, value: runtime.parseCouponPriceV4(item.payload) };
    } catch (error) {
      return { name: item.name, success: false, code: error?.code ?? error?.name ?? "ERROR", message: String(error?.message ?? error) };
    }
  });
  process.stdout.write(JSON.stringify(results));
} finally {
  await rm(directory, { recursive: true, force: true });
}
