import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const base = new URL(process.argv[2] ?? "http://127.0.0.1:47831");
assert.equal(base.protocol, "http:");
assert.ok(["localhost", "127.0.0.1"].includes(base.hostname), "Use an explicit local test server");
const ko = JSON.parse(readFileSync(new URL("../messages/ko.json", import.meta.url), "utf8"));
const en = JSON.parse(readFileSync(new URL("../messages/en.json", import.meta.url), "utf8"));

async function page(path, maxRedirects = 3) {
  let url = new URL(path, base);
  const visited = new Set();
  for (let redirects = 0; redirects <= maxRedirects; redirects++) {
    assert.ok(!visited.has(url.href), `Redirect loop at ${url.pathname}`);
    visited.add(url.href);
    const response = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(15000) });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      url = new URL(response.headers.get("location"), url);
      assert.ok(["localhost", "127.0.0.1"].includes(url.hostname));
      assert.equal(url.protocol, base.protocol);
      assert.equal(url.port, base.port);
      continue;
    }
    return { response, body: await response.text(), redirects };
  }
  assert.fail(`Too many redirects from ${path}`);
}

for (const path of ["/login", "/ko/login"]) {
  const result = await page(path);
  assert.equal(result.response.status, 200);
  assert.match(result.body, /<html[^>]*lang="ko"/);
  assert.ok(result.body.includes(ko.login.heading));
  assert.ok(result.body.includes(ko.login["username-label"]));
  console.log(`${path}: Korean login rendered, redirects=${result.redirects}`);
}
const english = await page("/en/login");
assert.equal(english.response.status, 200);
assert.match(english.body, /<html[^>]*lang="en"/);
assert.ok(english.body.includes(en.login.heading));
for (const path of ["/arena", "/replay", "/en/arena"]) {
  const response = await fetch(new URL(path, base), {
    redirect: "manual", signal: AbortSignal.timeout(15000),
  });
  assert.ok([307, 308].includes(response.status), `Unauthenticated ${path} must stay protected`);
  assert.equal(new URL(response.headers.get("location"), base).pathname, "/login");
}
console.log("Built-server login HTTP and protected-page checks passed without credentials");
