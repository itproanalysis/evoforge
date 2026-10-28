import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const require = createRequire(import.meta.url);
const source = readFileSync(new URL("../lib/proxyPolicy.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const exports = {};
runInNewContext(compiled, { exports, require });
const cases = JSON.parse(readFileSync(new URL("../lib/proxyPolicy.cases.json", import.meta.url), "utf8"));
for (const entry of cases) {
  assert.equal(exports.resolveApiPath(entry.path_segments), entry.expected, JSON.stringify(entry.path_segments));
}
assert.equal(exports.resolveApiPath(["v1", "participants"]), "/v1/participants");
assert.equal(exports.resolveApiPath(["v1", "participants", "..", "kernel"]), null);
assert.equal(exports.resolveApiPath(["v1", "kernel", "agents"]), null);
console.log(`Proxy policy: ${cases.length} cases and participant boundary passed`);
