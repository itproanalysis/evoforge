# Runner test-module collection evidence

The remote Runner checks the JUnit testcase class names for at least one case
from every submitted visible and held-out test module. If any module is absent,
the Runner retains the reported counts but returns a nonzero exit code. The
API-side Runner client rejects a claimed success with a nonzero exit code.
Class-name components after the first matching module cannot stand in for a
different module.

This check addresses under-collection hidden by multiple test cases in another
module. It depends on the trusted Runner and pytest report; it is not a signed
attestation or a defense against a candidate that can forge the report. The
local in-process Runner still needs the same protection, and its existing
uncommitted changes are intentionally untouched.

The remote visible suite uses the same isolated Python startup and pytest
configuration policy as the held-out suite: candidate `conftest.py`, pytest
configuration, plugin autoload, and a candidate `pytest.py` are ignored. Tests
that depend on candidate pytest plugins or fixtures will therefore fail rather
than inherit candidate-controlled collection behavior. This prevents a
reproduced `conftest.py` hook from fabricating a second module's node ID. Test
code still executes under the Runner process identity and may tamper with pytest
or files; this mitigation is not an adversarial execution boundary.

This is a demonstrated limitation, not only a hypothetical one: a synthetic
visible test registered an `atexit` handler, read the `--junitxml` path from its
own arguments, and replaced the report with two fabricated module entries.
The remote Runner then returned `pass=2`, `n=2`, `exit_code=0` even though the
second module contained no collected tests. Preventing this requires an
independent isolation and evidence boundary that candidate test code cannot
write to or impersonate. The current result must not be treated as such proof.

Validation for code revision `59a3b35`: 34 focused tests passed, including
real Runner service tests and missing-module regressions; 169 PostgreSQL kernel
tests and 96 SQL checks passed. Full API validation is in progress. These tests
do not demonstrate live provider execution or production deployment.
