import { readFile, writeFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { stripTypeScriptTypes } from "node:module";

const args = new Map();
for (let index = 2; index < process.argv.length; index += 2) args.set(process.argv[index], process.argv[index + 1]);
const mode = args.get("--mode");
const sourcePath = args.get("--source");
if (!mode || !sourcePath) throw new Error("--mode and --source are required");
const input = JSON.parse(await new Promise((resolve, reject) => {
  let value = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", chunk => value += chunk);
  process.stdin.on("end", () => resolve(value));
  process.stdin.on("error", reject);
}));
const directory = await mkdtemp(join(tmpdir(), "cdh-d06-ts-"));
try {
  let source = await readFile(sourcePath, "utf8");
  if (mode === "parser") {
    const typesPath = args.get("--types");
    if (!typesPath) throw new Error("--types is required in parser mode");
    const types = stripTypeScriptTypes(await readFile(typesPath, "utf8"), { mode: "transform" });
    source = source.replace('from "./types"', 'from "./types.mjs"');
    await writeFile(join(directory, "types.mjs"), types, "utf8");
    await writeFile(join(directory, "runtime.mjs"), stripTypeScriptTypes(source, { mode: "transform" }), "utf8");
    const runtime = await import(pathToFileURL(join(directory, "runtime.mjs")).href);
    const results = input.map(item => {
      try {
        let value;
        if (item.method === "search") value = runtime.parseSearchV2(item.payload);
        else if (item.method === "detail") value = runtime.parseDetailV2(item.payload, item.expected_product_id);
        else if (item.method === "affiliate") value = runtime.parseAffiliateV2(item.payload, item.expected_product_id);
        else throw new Error(`unknown method: ${item.method}`);
        return { name: item.name, method: item.method, success: true, value };
      } catch (error) {
        return { name: item.name, method: item.method, success: false, code: error?.code ?? error?.name ?? "ERROR", message: String(error?.message ?? error) };
      }
    });
    process.stdout.write(JSON.stringify(results));
  } else if (mode === "affiliate") {
    await writeFile(join(directory, "affiliate.mjs"), stripTypeScriptTypes(source, { mode: "transform" }), "utf8");
    const runtime = await import(pathToFileURL(join(directory, "affiliate.mjs")).href);
    const results = input.map(item => {
      const value = runtime.safeAffiliateUrl(item.product_id, item.offer, item.affiliate, item.policy, new Date(item.now));
      return { name: item.name, value };
    });
    process.stdout.write(JSON.stringify(results));
  } else {
    throw new Error(`unknown mode: ${mode}`);
  }
} finally {
  await rm(directory, { recursive: true, force: true });
}
