# Default-locale login entry

The previous browser check on the built release-11 integration repeatedly
redirected `/login` to itself. The source middleware returned next-intl's
default-locale rewrite to `/ko/login`; its as-needed canonicalization led
back to the concrete `/login` entry in the production server.

The concrete default login now renders directly. It reuses the existing
translated login component with Korean messages and its own HTML/layout.
The English locale entry stays available. The server locale fallback now
matches the existing Korean middleware default.

Protected page session checks, signatures, cookie properties, API permissions,
login submission and provider settings are unchanged. No credentials were
entered and no authentication mode was changed for the browser check.

## Verification

- `node scripts/check-login-routing.mjs`: direct/public login routing,
  protected pages, valid test-only signatures and rejected invalid/expired
  sessions passed. Its locale response is a unit-test double.
- Actual built-server HTTP: `/login` and `/ko/login` render Korean, `/en/login`
  renders English, and unauthenticated Arena/Replay still redirect to login.
  `scripts/check-login-http.mjs` uses only loopback URLs and GET requests.
  Log: `.local/validation-login-http.log`.
- Existing authentication regressions: 11 passed, one upstream warning.
- TypeScript and clean production build passed; build log:
  `.local/validation-login-build.log`.
- The actual local login was opened through computer-use and visually checked:
  Korean heading and labels, empty inputs and a disabled submit button.
  This is login-entry validation, not an authenticated Arena/R1–R5 browser E2E.

No new model key, paid evaluation, production configuration or deployment was
used. The earlier environment-override review rejection was not bypassed;
ordinary server startup and the normal protected login path were used.
