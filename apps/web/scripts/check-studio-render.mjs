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
const {StudioTabs, StudioPeople, StudioHistory} = load(path.join(web, 'components/StudioViews.tsx'));
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
  pathname = `${lang === 'ko' ? '/ko' : ''}/workspace`;
  assert.ok(render(StudioBreadcrumb).includes(messages[lang].navigation['mission-control']));
  checks++;
  pathname = lang === 'ko' ? '/ko' : '/';
  const home = render(Home);
  assert.ok(home.includes('studio-preview-lanes') || home.includes('studio-empty'));
  assert.ok(home.includes(messages[lang].studio['empty-title']));
  assert.ok(home.includes('studio-composer'));
  assert.ok(!home.includes('recorded_fixture') && !home.includes('active_fixture'));
  checks += 4;
  for (const active of ['work', 'people', 'history']) {
    const tabs = render(StudioTabs, {active, onChange: () => { throw new Error('SSR cannot change tabs'); }});
    assert.equal((tabs.match(/aria-selected="true"/g) ?? []).length, 1);
    assert.ok(tabs.includes(`aria-controls="studio-panel-${active}"`));
    checks += 2;
  }
  assert.ok(render(StudioPeople, {people: [], available: false, loading: false}).includes(messages[lang].studio['people-unavailable']));
  assert.ok(render(StudioPeople, {people: [], available: true, loading: false}).includes(messages[lang].studio['people-empty']));
  assert.ok(render(StudioHistory, {records: [], available: false, loading: false}).includes(messages[lang].studio['history-unavailable']));
  assert.ok(render(StudioHistory, {records: [], available: true, loading: false}).includes(messages[lang].studio['history-empty']));
  checks += 4;
  const record = {measurement_id: 'measurement_fixture', kind: 'X_SINGLE', model: 'test-model', suite_version: 'test-suite', passed: 1, n: 2, created_at: 100, provider_stub: true, evidence_id: 'fixture/id&x'};
  const history = render(StudioHistory, {records: [record], available: true, loading: false});
  assert.ok(history.includes(messages[lang].studio['source-test']));
  assert.ok(!history.includes(messages[lang].studio['source-model']));
  assert.ok(history.includes('fixture%2Fid%26x'));
  assert.ok(history.includes('1970-01-01T00:01:40.000Z'));
  assert.ok(history.includes('1 / 2'));
  checks += 5;
}
assert.deepEqual(Object.keys(messages.ko.studio).sort(), Object.keys(messages.en.studio).sort());
checks++;
console.log(`${checks} studio render assertions passed (actual components, English and Korean, no network).`);

if (process.argv.includes('--write-preview')) {
  locale = 'ko'; pathname = '/ko';
  const output = path.resolve(web, '../..', '.local/design-review');
  mkdirSync(output, {recursive: true});
  const css = readFileSync(path.join(output, 'studio.css'), 'utf8');
  const body = `<div class="studio-shell">${render(FeatureRail)}<div class="studio-column"><header class="studio-topbar">${render(StudioBreadcrumb)}${render(LanguageSwitcher)}</header><div class="studio-content"><p class="studio-review-notice">로컬 디자인 검토 · API 연결 없음</p>${render(Home)}</div></div></div>`;
  writeFileSync(path.join(output, 'index.html'), `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'"><title>EvoForge 디자인 검토</title><style>${css}</style></head><body style="margin:0;background:#f5f4f0;color:#282a26">${body}</body></html>`);
  console.log(`Static empty-state preview: ${path.join(output, 'index.html')} (no JS, API, live metrics, or model calls).`);
}
