const fs = require('node:fs');
const path = require('node:path');

const [typescriptPath, frontendRoot, fixturePath, outputPath, profile, compileDir] = process.argv.slice(2);
if (!compileDir || !['baseline-defects', 'canonical-fixed'].includes(profile)) {
  console.error('usage: node evaluate_contract.cjs <typescript.js> <frontend> <fixtures> <output> <profile> <compile-dir>');
  process.exit(64);
}
const ts = require(typescriptPath);
fs.mkdirSync(compileDir, {recursive: true});
const options = {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true};
for (const name of ['types.ts', 'runtimeSchema.ts']) {
  const sourcePath = path.join(frontendRoot, 'src', name);
  const source = fs.readFileSync(sourcePath, 'utf8');
  const result = ts.transpileModule(source, {compilerOptions: options, fileName: sourcePath, reportDiagnostics: true});
  const errors = (result.diagnostics || []).filter(item => item.category === ts.DiagnosticCategory.Error);
  if (errors.length) throw new Error(`TypeScript transpile diagnostics for ${name}: ${errors.length}`);
  fs.writeFileSync(path.join(compileDir, name.replace(/\.ts$/, '.js')), result.outputText);
}
const runtime = require(path.join(compileDir, 'runtimeSchema.js'));
const fixtures = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const results = [];
for (const [caseName, value] of Object.entries(fixtures.cases)) {
  const expected = value.detail.product.id;
  for (const method of ['search', 'detail', 'affiliate']) {
    try {
      const parsed = method === 'search' ? runtime.parseSearchV2(value.search)
        : method === 'detail' ? runtime.parseDetailV2(value.detail, expected)
        : runtime.parseAffiliateV2(value.affiliate, expected);
      results.push({name: caseName, method, success: true, parsed});
    } catch (error) {
      results.push({name: caseName, method, success: false, code: error.code || error.name, message: error.message});
    }
  }
}
const compact = results.map(({name, method, success, code, message}) => ({name, method, success, ...(code ? {code} : {}), ...(message ? {message} : {})}));
const actualPattern = compact.map(item => `${item.name}:${item.method}:${item.success ? 'PASS' : 'FAIL'}`);
const baselinePattern = [
  'valid:search:PASS','valid:detail:PASS','valid:affiliate:PASS',
  'incomplete:search:FAIL','incomplete:detail:FAIL','incomplete:affiliate:PASS',
  'daily_median:search:PASS','daily_median:detail:FAIL','daily_median:affiliate:PASS'
];
const median = fixtures.cases.daily_median;
const rawMinimum = Math.min(...median.detail.history.map(item => item.price_twd));
const dailyMedianMinimum = median.quality.period_low_twd;
const incompleteWire = fixtures.cases.incomplete.search.items[0];
let passed;
if (profile === 'baseline-defects') {
  passed = JSON.stringify(actualPattern) === JSON.stringify(baselinePattern)
    && incompleteWire.price_basis === 'UNAVAILABLE' && incompleteWire.last_observed_price_twd === null
    && rawMinimum === 10 && dailyMedianMinimum === 20;
} else {
  passed = compact.every(item => item.success)
    && incompleteWire.price_basis === 'UNAVAILABLE' && incompleteWire.last_observed_price_twd === null
    && median.detail.observation_period_min_twd === rawMinimum && dailyMedianMinimum === 20;
}
const report = {
  schema: 'CDH-G04-A-B-CONTRACT-EVALUATION-1', profile, passed,
  classification: fixtures.classification, results: compact,
  summary: {success_count: compact.filter(item => item.success).length, failure_count: compact.filter(item => !item.success).length},
  semantics: {incomplete_price_basis: incompleteWire.price_basis, incomplete_price: incompleteWire.last_observed_price_twd, v2_raw_history_minimum: rawMinimum, v2_wire_minimum: median.detail.observation_period_min_twd, v3_daily_median_minimum: dailyMedianMinimum}
};
fs.writeFileSync(outputPath, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report));
process.exit(passed ? 0 : 2);
