# W22 first layer: candidate report-tampering screen

This branch adds fixed-code static tripwires for added diff lines, test-control
paths and visible test snippets. A suspected candidate cannot earn GH_INTEGRITY
PASS, even if Runner counters say every test passed. Existing FAILs remain FAIL.
Ordinary patches remain eligible. PR creation repeats the screen so an older
stored PASS cannot bypass the new policy; historical evidence is not modified.

This touches API-core `gates.py` and `_pr_core` in `main.py` as required by W22.
The shared main worktree's Runner/sealed-eval/test changes were preserved.
Focused screen and existing PR acceptance regressions: 42 passed. Full release
checks are pending; this code is not yet integrated or deployed.

The screen is conservative: legitimate use of process shutdown, XML reporting,
or test-environment hooks can require manual review. It is not a parser of the
entire repository, does not follow aliases/dynamic imports or pre-existing
malicious code, and does not authenticate a report. Parent-side cross-checking,
independent per-file execution and an external observer are still separate W22
work. A candidate may evade static rules. No blanket assertion that G2 is secure
or automatic merge is safe follows from these checks. No gate contract or
core.authorize_merge path is bypassed.

Log: `.local/validation-runner-screen-focused.log` in this branch's worktree.

## Release-7 continuation and channel cross-check

The continuation branch `codex/runner-verify-r7` starts from release 7
`e0ee153`, as required by the updated work board; shared main is behind production.
The earlier first-layer change was cherry-picked without altering production.

The Runner now asks pytest for `-rA` terminal summaries. The parent compares
JUnit node identities and statuses, module coverage, duplicate identities and
the exit code with those summary lines. A mismatch is returned as
`report_integrity: false`; API and canonical G2 judgments cannot promote this
to PASS, and PR creation rechecks the flag on stored evidence. The flag is
included in the existing report digest whenever present. Legacy reports
without the flag keep their prior behavior, so API and Runner rollout must be
coordinated and this is not a retroactive verification of old results.

An actual disposable child-process regression writes fabricated passing XML
and calls os._exit before a failing assertion runs. Its aggregate counters are
still preserved as reported, but the absent terminal summary causes the G2
verdict to be INCONCLUSIVE. A normal parameterized class test passes the check.
Focused cross-check/screen/attestation/coverage regressions: 44 passed.
Existing actual Runner-service/client/PR tests plus the cross-check regressions:
70 passed in 72.39s. Full release-7 API/SQL/kernel checks remain pending.

The two child-controlled channels can be forged together. This comparison
does not independently establish which assertion bodies ran, does not derive
every required node ID before execution, and cannot replace per-file isolated
execution or an independent observer. Those W22 requirements remain open.
