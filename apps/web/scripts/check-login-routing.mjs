import assert from "node:assert/strict";
import { createHmac, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const require = createRequire(import.meta.url);
const { NextRequest, NextResponse } = require("next/server");
const source = readFileSync(new URL("../middleware.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, esModuleInterop: true,
} }).outputText;

// The locale response is a test double. A separate built-server HTTP check
// proves that the real Next/next-intl combination no longer loops.
function middlewareFor(env) {
  const exports = {};
  runInNewContext(js, { exports, process: { env }, crypto: webcrypto,
    TextEncoder, Uint8Array, Date, Number, parseInt,
    require: (name) => name === "next-intl/middleware"
      ? () => (req) => {
          const url = req.nextUrl.clone();
          if (url.pathname.startsWith("/ko/")) {
            url.pathname = url.pathname.slice(3);
            return NextResponse.redirect(url, 307);
          }
          if (url.pathname.startsWith("/en/")) return NextResponse.next();
          url.pathname = `/ko${url.pathname}`;
          return NextResponse.rewrite(url);
        }
      : require(name),
  });
  return exports.middleware;
}

for (const mode of [undefined, "session", "unknown"]) {
  const middleware = middlewareFor({ EVO_WEB_AUTH: mode });
  for (const path of ["/login", "/login/"]) {
    const result = await middleware(new NextRequest(`http://localhost${path}`));
    assert.equal(result.status, 200);
    assert.equal(result.headers.get("location"), null);
    assert.equal(result.headers.get("x-middleware-rewrite"), null);
  }
  const korean = await middleware(new NextRequest("http://localhost/ko/login"));
  assert.equal(new URL(korean.headers.get("location")).pathname, "/login");
  const english = await middleware(new NextRequest("http://localhost/en/login"));
  assert.equal(english.status, 200);
  for (const path of ["/", "/arena", "/replay", "/en/arena"]) {
    const protectedPage = await middleware(new NextRequest(`http://localhost${path}`));
    assert.equal(protectedPage.status, 307);
    assert.equal(new URL(protectedPage.headers.get("location")).pathname, "/login");
  }
}

const secret = "unit-test-only-signing-key";
const middleware = middlewareFor({ EVO_SESSION_SECRET: secret });
function session(expiry, signingKey = secret) {
  const sig = createHmac("sha256", signingKey).update(`test-only.${expiry}`).digest("hex");
  return `test-only.${sig}.${expiry}`;
}
const future = Math.floor(Date.now() / 1000) + 120;
for (const [value, allowed] of [
  [session(future), true], [session(future, "wrong-test-key"), false],
  [session(1), false], ["malformed", false],
]) {
  const result = await middleware(new NextRequest("http://localhost/arena", {
    headers: { cookie: `__Host-evoforge-session=${value}` },
  }));
  assert.equal(result.headers.get("location") === null, allowed);
}
console.log("Default/English login entry and protected-page session checks passed");
