# W22 sys.exit scope refinement

Base: release 8 `d905898`. Normal CLI function bodies and the standard
`if __name__ == "__main__"` branch no longer trip the sys.exit screen simply
by containing exit code. An AST walk checks calls evaluated during import,
including module/class bodies, function defaults, decorators and annotations.
Direct `sys` aliases and `from sys import exit` aliases are recognized. Source
is parsed only, never executed. A partial added hunk that mentions exit but
cannot be parsed remains `process_exit_scope_unknown` and requires review.

The os._exit, atexit, report-writing and interpreter-tampering tripwires are
retained. This is a conservative heuristic, not a proof of import safety:
dynamic calls, helper invocation, pre-existing imports and incomplete diff
context can evade it or require manual review. W22 per-file execution and the
independent observer remain open.

Scope/screen/report plus existing PR acceptance checks: **63 passed** in
25.11s. Full release-8 regression is pending. No production requests, model
calls, shared-main code changes or deployment were performed.
