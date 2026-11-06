const fs = require("node:fs");
const path = require("node:path");

const [compiledModule, responsesPath, outputPath] = process.argv.slice(2);
if (![compiledModule, responsesPath, outputPath].every(Boolean)) process.exit(64);
const { parseCouponPriceV4 } = require(path.resolve(compiledModule));
const responses = JSON.parse(fs.readFileSync(responsesPath, "utf8"));

function capture(name, value) {
  try { parseCouponPriceV4(value); return { name, accepted: true, code: null, message: null }; }
  catch (error) { return { name, accepted: false, code: error && error.code || error && error.name || "UNKNOWN", message: String(error && error.message || error) }; }
}
const probes = [capture("search_item", responses.search.body.items[0]), capture("detail_envelope", responses.detail.body)];
const expected = probes[0].code === "V4_VERSION_MISMATCH" && probes[1].code === "INVALID_V4_PAYLOAD";
const report = { schema: "CDH-G06-A09-B10-PARSER-PROBE-1", probes, expected_wire_failure_reproduced: expected };
fs.writeFileSync(outputPath, JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify(report));
process.exitCode = expected ? 0 : 1;
