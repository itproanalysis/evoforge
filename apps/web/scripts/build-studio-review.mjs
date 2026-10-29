import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import assert from 'node:assert/strict';

// Local review only. Bundle the real workspace so tabs, menus, settings and
// typing work in the review. Only explicitly supplied saved GET responses can
// be read. There is no API/backend, credential input or model execution.
const require = createRequire(import.meta.url);
const compiledWebpack = require('next/dist/compiled/webpack/webpack');
compiledWebpack.init();
const webpack = compiledWebpack.webpack;
const web = fileURLToPath(new URL('..', import.meta.url));
const output = path.resolve(web, '../../.local/design-review');
mkdirSync(output, {recursive: true});
const snapshot = process.argv.includes('--snapshot') ? JSON.parse(readFileSync(path.join(output, 'snapshot.json'), 'utf8')) : {responses: {}};
const allowedSnapshotPaths = new Set(['/v1/dashboard', '/v1/ledger', '/v1/performance', '/v1/missions', '/v1/outcomes', '/v1/participants', '/v1/arena', '/v1/arena/summary']);
if (Object.keys(snapshot.responses ?? {}).some(key => !allowedSnapshotPaths.has(key))) throw new Error('Unexpected snapshot endpoint');
const capturedLabel = snapshot.captured_at ? new Intl.DateTimeFormat('ko-KR', {dateStyle: 'short', timeStyle: 'short', timeZone: 'Asia/Seoul'}).format(new Date(snapshot.captured_at)) : null;
const reviewNotice = capturedLabel ? `공개 실행 기록의 저장본 · ${capturedLabel} KST · 실시간 아님` : '로컬 디자인 검토 · API 연결 없음';
const save = (name, content) => writeFileSync(path.join(output, name), content);
save('typescript-loader.cjs', `const ts=require(${JSON.stringify(require.resolve('typescript'))});module.exports=function(source){return ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;};`);
save('review-intl.js', `import ko from ${JSON.stringify(path.join(web, 'messages/ko.json'))};import en from ${JSON.stringify(path.join(web, 'messages/en.json'))};
export const useLocale=()=>new URLSearchParams(window.location.search).get('lang')==='en'?'en':'ko';
export function useTranslations(namespace){const read=key=>key.split('.').reduce((v,k)=>v?.[k],(useLocale()==='en'?en:ko)[namespace]);const t=(key,values={})=>{const value=read(key);return typeof value==='string'?value.replace(/\\{(\\w+)\\}/g,(_,key)=>values[key]??'{'+key+'}'):key;};t.has=key=>typeof read(key)==='string';return t;}
`);
save('review-navigation.js', `export const usePathname=()=>new URLSearchParams(window.location.search).get('lang')==='en'?'/':'/ko';export const useRouter=()=>({replace:url=>{window.location.href=url.startsWith('/ko')?'/?lang=ko':'/?lang=en';}});`);
save('review-entry.jsx', `import React from 'react';import{createRoot}from'react-dom/client';
import Home from ${JSON.stringify(path.join(web, 'app/[locale]/page.tsx'))};
import{FeatureRail}from ${JSON.stringify(path.join(web, 'components/FeatureRail.tsx'))};
import{StudioBreadcrumb}from ${JSON.stringify(path.join(web, 'components/StudioBreadcrumb.tsx'))};
import{LanguageSwitcher}from ${JSON.stringify(path.join(web, 'components/LanguageSwitcher.tsx'))};
const saved=${JSON.stringify(snapshot.responses ?? {})};
window.fetch=async(input,options)=>{
 const method=options?.method??(typeof input==='object'?input.method:'GET')??'GET';
 const url=new URL(typeof input==='string'?input:input.url,window.location.origin);
 const key=url.pathname.startsWith('/api/evoforge/')?url.pathname.slice('/api/evoforge'.length):url.pathname;
 if(method.toUpperCase()!=='GET'||url.origin!==window.location.origin||!Object.hasOwn(saved,key))throw new Error('No live API actions in design review');
 return new Response(JSON.stringify(saved[key]),{status:200,headers:{'Content-Type':'application/json'}});
};
Object.defineProperty(window,'EventSource',{value:undefined,configurable:true});
document.addEventListener('click',event=>{const anchor=event.target.closest?.('a[href]');if(anchor&&anchor.getAttribute('href')?.startsWith('/')){event.preventDefault();document.querySelector('.studio-review-notice').textContent='디자인 검토 화면입니다. 기능 이동과 실행은 실제 서비스에서 사용할 수 있습니다.';}});
createRoot(document.getElementById('studio-review-root')).render(<div className="studio-shell"><FeatureRail/><div className="studio-column"><header className="studio-topbar"><StudioBreadcrumb/><LanguageSwitcher/></header><div className="studio-content"><p className="studio-review-notice">{${JSON.stringify(reviewNotice)}}</p><Home/></div></div></div>);
`);
const entry = readFileSync(path.join(output, 'review-entry.jsx'), 'utf8');
const boundary = {location: {origin: 'http://127.0.0.1:47839'}};
runInNewContext(entry.slice(entry.indexOf('const saved='), entry.indexOf('Object.defineProperty')), {window: boundary, URL, Response});
await assert.rejects(() => boundary.fetch('/api/evoforge/v1/arena/prompt', {method: 'POST'}));
await assert.rejects(() => boundary.fetch('https://example.com/api/evoforge/v1/dashboard'));
await assert.rejects(() => boundary.fetch('/api/evoforge/v1/unrecorded'));
if (snapshot.responses?.['/v1/dashboard']) {
  assert.equal((await boundary.fetch('/api/evoforge/v1/dashboard')).status, 200);
}
console.log('Local review boundary passed: mutations, external requests and unrecorded GETs denied.');
await new Promise((resolve, reject) => {
  const compiler = webpack({
    mode: 'production', context: web, entry: path.join(output, 'review-entry.jsx'),
    output: {path: output, filename: 'studio-review.js'},
    resolve: {extensions: ['.tsx', '.ts', '.jsx', '.js', '.json'], modules: [path.join(web, 'node_modules'), 'node_modules'], alias: {'next-intl': path.join(output, 'review-intl.js'), 'next/navigation': path.join(output, 'review-navigation.js')}},
    module: {rules: [{test: /\.[jt]sx?$/, exclude: /node_modules/, use: path.join(output, 'typescript-loader.cjs')}]},
    plugins: [new webpack.DefinePlugin({'process.env.NEXT_PUBLIC_EVO_OPERATOR_CONTROLS': JSON.stringify('0')})],
    optimization: {minimize: false},
    performance: {hints: false},
  });
  compiler.run((error, stats) => {
    compiler.close(() => {});
    if (error) {reject(error); return;}
    if (stats.hasErrors()) {reject(new Error(stats.toString({all: false, errors: true}))); return;}
    resolve();
  });
});
const css = readFileSync(path.join(output, 'studio.css'), 'utf8');
save('interactive.html', `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src data:; frame-src 'self' about:; form-action 'none'; base-uri 'none'"><title>EvoForge 작업실 · 디자인 검토</title><style>${css}</style></head><body style="margin:0;background:#f5f4f0;color:#282a26"><div id="studio-review-root"></div><script src="/studio-review.js" defer></script></body></html>`);
console.log(`Interactive local review built; ${Object.keys(snapshot.responses ?? {}).length} saved GET responses, live requests denied, operator actions off.`);
