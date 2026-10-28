# Sealed eval v1 — goals that state the contract (Critic proposal, 2026-10-28)

## Why

Production X_SINGLE on sealed v0 (2026-10-28 22:27 KST, `m_045caf7c2f1e`, evidence `ev_b508203b0158`, real
Muse Spark, `provider_stub=false`): **2/12 passed (16.7%, Wilson 95% 4.7–44.8%)**.

A local re-run of `simple_sequential` with the real Builder showed both diffs **applied cleanly and failed the
held-out tests** because the held-out tests check behaviour the goal never states:

- SV0-SS-01: goal "keep backoff above its floor" — held-out requires the floor to be exactly 100. Muse kept 50
  (the only number in the file) and got the 5xx retry rule right.
- SV0-SS-02: goal "rejects bad elements" — held-out also requires non-positive ints to be silently dropped.

Across v0, 7 of 12 negative tests require a `ValueError` the goal never mentions (AO-02, CD-02, CI-01, CI-02,
PM-01, PM-02, SEC-02), and CD-01, SEC-01 and SS-01 depend on unstated values or formats. v0 therefore measures
guessing hidden requirements more than coding, and any pipeline "improvement" is mostly the retry feedback
revealing those requirements. v0 stays as-is for history; it is not a fair capability number.

## Rule for v1

Additive (`evals/sealed_v1/`, `SUITE_VERSION` selectable, v0 untouched). **Held-out tests, files and reference
fixes are copied unchanged**; only `goal` changes. A goal states the contract a real ticket would state
(inputs, outputs, error conditions, constants, formats) without quoting the tests. Every v1 task must still pass
`check_task` (fails without the reference fix, passes with it).

## Proposed v1 goals

| Task | v1 goal |
|---|---|
| SS-01 | `should_retry(status)` is True only for server errors (`status >= 500`). `backoff(attempt)` is `50 * 2**attempt` milliseconds but never below a floor of 100. `run_chain` unchanged. |
| SS-02 | `pipe(items)` returns, in input order, each positive int doubled; non-positive ints are skipped; any element that is not an int raises `ValueError`. Empty input returns `[]`. |
| AO-01 | (unchanged — passed) Binary search returns the index of `target` in a sorted sequence, or -1 when absent (including empty input). |
| AO-02 | `topk(xs, k)` returns the `k` largest elements in descending order; `k == 0` or empty `xs` returns `[]`; negative `k` raises `ValueError`. |
| CD-01 | `should_resume(dropped, cursor)` is True only when the session dropped **and** `cursor >= 0`. `replay(log, cursor)` returns the turns from `cursor` onward (`[]` when `cursor >= len(log)`). |
| CD-02 | `merge_turns(saved, live)` returns `saved` followed by the `live` turns not already present, order preserved, no duplicates; both empty returns `[]`; a non-list argument raises `ValueError`. |
| CI-01 | `decide(history)` for a list of run results: all True → `"PASS"`, all False → `"FAIL"`, mixed → `"QUARANTINE"`; an empty history raises `ValueError`. |
| CI-02 | `median(xs)` returns the true median (mean of the two middle values for even length, e.g. `2.5`); a single value returns itself; empty input raises `ValueError`. |
| PM-01 | `shard(items, n)` always returns exactly `n` lists whose sizes differ by at most one, larger shards first, together holding every item once; `n <= 0` raises `ValueError`. `merge(shards)` returns all items (empty shards → `[]`). |
| PM-02 | `split_work(items, n)` deals items round-robin (item `i` goes to part `i % n`) into exactly `n` parts; `n <= 0` raises `ValueError`. `combine(partials)` returns their sum (`0` for none). |
| SEC-01 | `redact(record)` replaces the `token` value with `"***"` and adds `preview` = the first two characters of the original token followed by `"**"` (`"**"` for an empty token); the raw token never appears in the output. |
| SEC-02 | `safe_join(root, rel)` returns `os.path.join(root, rel)` when the result stays inside `root`; it raises `ValueError` when `rel` is empty or the path escapes `root` (for example via `..`). |

## Also needed (observability)

Eval evidence must say **why** a task failed, without held-out code: `empty_diff`, `apply_failed`,
`heldout_failed` (with failing test names), `provider_error`. Today only `score` is stored, so a low number
cannot be split into model vs harness vs task-spec causes.
