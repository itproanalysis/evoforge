import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const exports = {};
const timers = new Map();
let nextTimer = 0;
runInNewContext(ts.transpileModule(readFileSync(new URL("../lib/replaySelection.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports,
  setTimeout: (callback) => { timers.set(++nextTimer, callback); return nextTimer; },
  clearTimeout: (id) => timers.delete(id),
});
const watch = exports.watchReplaySelection;
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function tick() {
  const first = timers.entries().next().value;
  assert.ok(first, "Expected one scheduled poll");
  timers.delete(first[0]);
  first[1]();
}

const old = deferred(), fresh = deferred(), updates = [];
const cancelOld = watch("old", () => old.promise, (state) => updates.push(state));
cancelOld();
const cancelFresh = watch("new", () => fresh.promise, (state) => updates.push(state));
fresh.resolve({ run_id: "new", status: "succeeded" });
await flush();
old.resolve({ run_id: "old", status: "running" });
await flush();
assert.equal(updates.at(-1).run.run_id, "new");
assert.equal(updates.filter((s) => s.runId === "old" && s.status === "ready").length, 0);
assert.equal(timers.size, 0, "A recorded completed run must not poll");
cancelFresh();

const mismatch = [];
watch("requested", async () => ({ run_id: "other", status: "succeeded" }), (s) => mismatch.push(s));
await flush();
assert.equal(mismatch.at(-1).status, "error");
assert.equal(mismatch.at(-1).run, undefined);

const initialFailure = [];
watch("unavailable", async () => { throw new Error("404"); }, (s) => initialFailure.push(s));
await flush();
assert.equal(initialFailure.at(-1).status, "error");
assert.equal(timers.size, 0);

const poll = deferred(), recovered = deferred(), pollUpdates = [];
let calls = 0;
const cancelPoll = watch("live", () => {
  calls++;
  if (calls === 1) return Promise.resolve({ run_id: "live", status: "running" });
  return calls === 2 ? poll.promise : recovered.promise;
}, (s) => pollUpdates.push(s));
await flush();
assert.equal(timers.size, 1);
tick();
assert.equal(calls, 2);
assert.equal(timers.size, 0, "No next poll while this GET is pending");
poll.reject(new Error("network failure"));
await flush();
assert.equal(pollUpdates.at(-1).status, "ready");
assert.equal(pollUpdates.at(-1).run.run_id, "live");
assert.ok(pollUpdates.at(-1).refreshError);
assert.equal(timers.size, 1);
tick();
recovered.resolve({ run_id: "live", status: "succeeded" });
await flush();
assert.equal(pollUpdates.at(-1).refreshError, undefined);
assert.equal(timers.size, 0);
cancelPoll();

const late = deferred(), stopped = [];
let reads = 0;
const cancel = watch("cancelled", () => ++reads === 1
  ? Promise.resolve({ run_id: "cancelled", status: "running" }) : late.promise,
  (s) => stopped.push(s));
await flush();
tick();
cancel();
const count = stopped.length;
late.resolve({ run_id: "cancelled", status: "succeeded" });
await flush();
assert.equal(stopped.length, count);
assert.equal(timers.size, 0);

const queuedCancel = watch("queued", async () => ({ run_id: "queued", status: "running" }), () => {});
await flush();
assert.equal(timers.size, 1);
queuedCancel();
assert.equal(timers.size, 0);
console.log("Replay selection binding, late-response cancellation, serialized polls and recovery passed");

if (process.argv.includes("--http")) {
  const docs = JSON.parse(readFileSync(0, "utf8"));
  const delayed = deferred(), states = [];
  const cancelA = watch(docs.old.run_id, () => delayed.promise, (s) => states.push(s));
  cancelA();
  const cancelB = watch(docs.selected.run_id, async () => docs.selected, (s) => states.push(s));
  await flush();
  delayed.resolve(docs.old);
  await flush();
  assert.equal(states.at(-1).run.run_id, docs.selected.run_id);
  assert.equal(states.at(-1).run.manifest.base_sha, docs.selected.manifest.base_sha);
  assert.equal(states.filter((s) => s.runId === docs.old.run_id && s.status === "ready").length, 0);
  cancelB();
  assert.equal(timers.size, 0);
  console.log("Actual Evolution HTTP payloads retain the selected run and manifest");
}
