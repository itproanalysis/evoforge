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

Validation for code revision `59a3b35`: 34 focused tests passed, including
real Runner service tests and missing-module regressions; 169 PostgreSQL kernel
tests and 96 SQL checks passed. Full API validation is in progress. These tests
do not demonstrate live provider execution or production deployment.
