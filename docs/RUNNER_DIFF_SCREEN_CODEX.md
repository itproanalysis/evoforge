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
