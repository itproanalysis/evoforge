import assert from 'node:assert/strict';
import { readFileSync, existsSync, statSync, writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

// Render the actual components. Navigation and translations are provided at the
// framework boundary; effects never run during SSR and no API request is made.
const web = fileURLToPath(new URL('..', import.meta.url));
const require = createRequire(import.meta.url);
let locale = 'ko';
let pathname = '/ko';
let checks = 0;
const messages = Object.fromEntries(['en', 'ko'].map(lang => [lang, JSON.parse(readFileSync(path.join(web, 'messages', `${lang}.json`), 'utf8'))]));
function translate(namespace) {
  const read = key => key.split('.').reduce((value, part) => value?.[part], messages[locale][namespace]);
  const t = (key, values = {}) => {
    const value = read(key);
    assert.equal(typeof value, 'string', `Missing translation ${locale}.${namespace}.${key}`);
    return value.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? `{${name}}`);
  };
  t.has = key => typeof read(key) === 'string';
  return t;
}
const cache = new Map();
function load(filename) {
  const candidate = [filename, `${filename}.tsx`, `${filename}.ts`, path.join(filename, 'index.ts')].find(file => existsSync(file) && statSync(file).isFile());
  assert.ok(candidate, `Cannot resolve ${filename}`);
  if (cache.has(candidate)) return cache.get(candidate);
  const exports = {};
  cache.set(candidate, exports);
  const compiled = ts.transpileModule(readFileSync(candidate, 'utf8'), {compilerOptions: {jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true}}).outputText;
  const componentRequire = specifier => {
    if (specifier === 'next-intl') return {useLocale: () => locale, useTranslations: translate};
    if (specifier === 'next/navigation') return {usePathname: () => pathname, useRouter: () => ({replace() { throw new Error('SSR must not navigate'); }})};
    if (specifier.startsWith('.')) return load(path.resolve(path.dirname(candidate), specifier));
    return require(specifier);
  };
  runInNewContext(compiled, {exports, require: componentRequire, process: {env: {}}, console, URLSearchParams, TextEncoder, TextDecoder, setTimeout, clearTimeout, setInterval, clearInterval});
  return exports;
}
const {StudioOverview} = load(path.join(web, 'components/StudioOverview.tsx'));
const {StudioBreadcrumb} = load(path.join(web, 'components/StudioBreadcrumb.tsx'));
const {FeatureRail} = load(path.join(web, 'components/FeatureRail.tsx'));
const {LanguageSwitcher} = load(path.join(web, 'components/LanguageSwitcher.tsx'));
const {default: Home} = load(path.join(web, 'app/[locale]/page.tsx'));
const render = (Component, props = {}) => renderToStaticMarkup(React.createElement(Component, props));
const empty = {running: false, measured: null, verified: null, participants: null, heldout: null};

for (const lang of ['en', 'ko']) {
  locale = lang;
  pathname = lang === 'ko' ? '/ko' : '/';
  const unknown = render(StudioOverview, empty);
  assert.equal((unknown.match(/studio-metric-value">—</g) ?? []).length, 4);
  assert.ok(unknown.includes(messages[lang].studio.waiting));
  assert.ok(!unknown.includes('is-running'));
  checks += 3;
  const zeros = render(StudioOverview, {...empty, measured: 0, verified: 0, participants: 0, heldout: {passed: 0, n: 0}});
  assert.equal((zeros.match(/studio-metric-value">0</g) ?? []).length, 3);
  assert.ok(!zeros.includes('0 / 0'));
  checks += 2;
  const partial = render(StudioOverview, {...empty, participants: 20, participantsMore: true});
  assert.ok(partial.includes('20+'));
  checks++;
  const recorded = render(StudioOverview, {...empty, runId: 'recorded_fixture', measured: 7, heldout: {passed: 13, n: 21}});
  assert.ok(recorded.includes('13 / 21'));
  assert.ok(recorded.includes(messages[lang].studio.recorded));
  assert.ok(!recorded.includes('is-running'));
  checks += 3;
  const active = render(StudioOverview, {...empty, running: true, runId: 'active_fixture'});
  assert.ok(active.includes('is-running'));
  assert.ok(active.includes(messages[lang].studio.running));
  checks += 2;
  for (const route of ['/arena', '/replay', '/performance']) {
    pathname = `${lang === 'ko' ? '/ko' : ''}${route}`;
    const rail = render(FeatureRail);
    const link = rail.match(/<a[^>]*aria-current="page"[^>]*>/g) ?? [];
    assert.equal(link.length, 1, `${lang} ${route} must mark exactly one current page`);
    assert.ok(link[0].includes(`href="${pathname}"`));
    assert.ok(render(StudioBreadcrumb).includes(messages[lang].navigation[route.slice(1)]));
    checks += 3;
  }
  pathname = lang === 'ko' ? '/ko' : '/';
  const home = render(Home);
  assert.ok(home.includes('studio-preview-lanes') || home.includes('studio-empty'));
  assert.ok(home.includes(messages[lang].studio['empty-title']));
  assert.ok(home.includes('studio-composer'));
  assert.ok(!home.includes('recorded_fixture') && !home.includes('active_fixture'));
  checks += 4;
}
assert.deepEqual(Object.keys(messages.ko.studio).sort(), Object.keys(messages.en.studio).sort());
checks++;
console.log(`${checks} studio render assertions passed (actual components, English and Korean, no network).`);

if (process.argv.includes('--write-preview')) {
  locale = 'ko'; pathname = '/ko';
  const output = path.resolve(web, '../..', '.local/design-review');
  mkdirSync(output, {recursive: true});
  const css = readFileSync(path.join(output, 'studio.css'), 'utf8');
  const body = `<div class="studio-shell">${render(FeatureRail)}<div class="studio-column"><header class="studio-topbar">${render(StudioBreadcrumb)}${render(LanguageSwitcher)}</header><div class="studio-content"><p style="font-size:11px;color:#c6ec94;margin:0 0 18px">로컬 디자인 검토 · 빈 상태 · 실제 실행 결과 아님</p>${render(Home)}</div></div></div>`;
  writeFileSync(path.join(output, 'index.html'), `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'"><title>EvoForge 디자인 검토</title><style>${css}</style></head><body style="margin:0;background:#0d1014;color:#edf1f5">${body}</body></html>`);
  console.log(`Static empty-state preview: ${path.join(output, 'index.html')} (no JS, API, live metrics, or model calls).`);
}
