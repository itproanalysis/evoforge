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
assert.equal(exports.isApiMethodAllowed('/v1/models/defaults', 'GET'), true);
assert.equal(exports.isApiMethodAllowed('/v1/models/defaults', 'HEAD'), true);
for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
  assert.equal(exports.isApiMethodAllowed('/v1/models/defaults', method), false);
}
console.log(`Proxy policy: ${cases.length} cases and participant boundary passed`);

const modelExports = {};
runInNewContext(ts.transpileModule(readFileSync(new URL('../lib/modelDefaults.ts', import.meta.url), 'utf8'),
  {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText, {exports: modelExports, require});
const defaults = {
  profile: 'collaborative', ready: true, requires_api_key: false,
  default_builder: 'muse-spark-1.3', default_critic: 'claude-opus-5-5', blocked_reason: null,
  participants: [
    {role: 'builder', provider: 'meta', model: 'muse-spark-1.3', configured: true},
    {role: 'planner', provider: 'openai', model: 'gpt-6.1-sol', configured: true},
    {role: 'planner', provider: 'google', model: 'gemini-4-argon', configured: true},
    {role: 'critic', provider: 'anthropic', model: 'claude-opus-5-5', configured: true},
  ],
};
assert.equal(modelExports.modelDefaultsView(defaults).status, 'ready');
assert.equal(modelExports.modelDefaultsView({...defaults, ready: false}).status, 'blocked');
assert.equal(modelExports.modelDefaultsView({...defaults, participants: defaults.participants.slice(0, 3)}).status, 'blocked');
assert.equal(modelExports.modelDefaultsView({...defaults, participants: defaults.participants.map((p, i) => i === 2 ? {...p, configured: false} : p)}).status, 'blocked');
assert.equal(modelExports.modelDefaultsView({...defaults, default_critic: 'muse-spark-1.3'}).status, 'blocked');
assert.equal(modelExports.modelDefaultsView({...defaults, requires_api_key: true}).status, 'unknown');
assert.equal(modelExports.modelDefaultsView({...defaults, participants: [...defaults.participants, defaults.participants[0]]}).status, 'unknown');
assert.equal(modelExports.modelDefaultsView({...defaults, participants: defaults.participants.map((p, i) => i === 1 ? {...p, provider: 'anthropic'} : p)}).status, 'unknown');
assert.equal(modelExports.modelDefaultsView({...defaults, participants: defaults.participants.map((p, i) => i === 1 ? {...p, model: 'unapproved-model'} : p)}).status, 'unknown');
assert.equal(modelExports.modelDefaultsView({...defaults, participants: [{role: 'builder', model: '__proto__', configured: true}]}).status, 'unknown');
for (const malformed of [null, [], {}, {ready: true}, {...defaults, ready: 'true'}]) {
  assert.equal(modelExports.modelDefaultsView(malformed).status, 'unknown');
}
const sanitised = modelExports.modelDefaultsView({...defaults, secret: 'must-not-copy', participants: defaults.participants.map(p => ({...p, api_key: 'must-not-copy'}))});
assert.ok(!JSON.stringify(sanitised).includes('must-not-copy'));
assert.equal(modelExports.modelDefaultsView({...defaults, profile: 'legacy', default_critic: 'muse-spark-1.3', participants: [defaults.participants[0], {role: 'critic', provider: 'meta', model: 'muse-spark-1.3', configured: true}]}).status, 'ready');
console.log('Model defaults: complete profile, keyless readiness, missing/contradictory/malformed data, and safe fields passed');

const provenanceSource = readFileSync(new URL("../lib/performanceProvenance.ts", import.meta.url), "utf8");
const provenanceExports = {};
runInNewContext(ts.transpileModule(provenanceSource, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
  { exports: provenanceExports, require });
assert.equal(provenanceExports.provenance(true), "simulated");
assert.equal(provenanceExports.provenance(false), "recorded");
assert.equal(provenanceExports.provenance(undefined), "unknown");
assert.equal(provenanceExports.viewProvenance({ provider_stub: false, record: { provider_stub: true } }), "simulated");
assert.equal(provenanceExports.comparisonProvenance({ provider_stub: false }, {}), "unknown");
assert.equal(provenanceExports.comparisonProvenance({ provider_stub: false }, { provider_stub: true }), "simulated");
console.log("Measurement provenance boundary passed");
