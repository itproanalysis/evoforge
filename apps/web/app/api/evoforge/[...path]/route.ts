import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { resolveApiPath } from "@/lib/proxyPolicy";

const COOKIE_NAME = "__Host-evoforge-session";
const METADATA_BASE = "http://metadata.google.internal";
const POST_WINDOW_MS = 60 * 1000;
const DEFAULT_POST_PER_MIN = 20;
// Rolling per-IP POST timestamps for "none" auth mode.
const postHits = new Map<string, number[]>();
// Path policy (exact paths such as /v1/ledger plus /v1/evidence/{id} families)
// lives in @/lib/proxyPolicy and is enforced via resolveApiPath() below.

// Server-only auth mode, read at runtime. Any value other than "none"
// means the default "session" behaviour (owner login required).
function authDisabled(): boolean {
  return (process.env.EVO_WEB_AUTH ?? "") === "none";
}

function clientIp(req: NextRequest): string {
  const fwd = req.headers.get("x-forwarded-for");
  if (fwd) {
    const first = fwd.split(",")[0]?.trim();
    if (first) return first;
  }
  return "unknown";
}

function postLimitPerMin(): number {
  const raw = (process.env.EVO_WEB_POST_PER_MIN ?? "").trim();
  if (raw !== "") {
    const n = Number(raw);
    if (Number.isInteger(n) && n >= 0) return n;
  }
  return DEFAULT_POST_PER_MIN;
}

function isPostRateLimited(ip: string, limit: number): boolean {
  const now = Date.now();
  let hits = postHits.get(ip);
  if (!hits) {
    hits = [];
    postHits.set(ip, hits);
  }
  while (hits.length > 0 && (hits[0] as number) <= now - POST_WINDOW_MS) hits.shift();
  if (hits.length >= limit) return true;
  hits.push(now);
  return false;
}

function verifySession(value: string, secret: string): boolean {
  if (!value || !secret) return false;
  const parts = value.split(".");
  if (parts.length !== 3) return false;
  const [random, sigHex, expStr] = parts;
  if (!random || !sigHex || !expStr) return false;
  const expiry = Number(expStr);
  if (!Number.isInteger(expiry)) return false;
  if (expiry <= Math.floor(Date.now() / 1000)) return false;
  const data = `${random}.${expiry}`;
  let expected: Buffer;
  let actual: Buffer;
  try {
    expected = crypto.createHmac("sha256", secret).update(data, "utf8").digest();
    actual = Buffer.from(sigHex, "hex");
  } catch {
    return false;
  }
  if (actual.length !== expected.length) return false;
  return crypto.timingSafeEqual(actual, expected);
}

function apiBase(): string {
  const base = (process.env.EVO_API_BASE ?? "").trim()
    || (process.env.EVO_API_URL ?? "").trim()
    || "http://localhost:8080";
  return base.replace(/\/+$/, "");
}

async function fetchIdToken(audience: string): Promise<string | null> {
  const url =
    `${METADATA_BASE}/computeMetadata/v1/instance/service-accounts/default/identity` +
    `?audience=${encodeURIComponent(audience)}&format=full`;
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2500);
    try {
      const r = await fetch(url, {
        headers: { "Metadata-Flavor": "Google" },
        signal: ctrl.signal,
      });
      if (!r.ok) return null;
      const text = (await r.text()).trim();
      return text || null;
    } finally {
      clearTimeout(t);
    }
  } catch {
    return null;
  }
}

async function handle(req: NextRequest, params: { path?: string[] }) {
  const noAuth = authDisabled();
  if (!noAuth) {
    const secret = process.env.EVO_SESSION_SECRET ?? "";
    const jar = await cookies();
    const raw = jar.get(COOKIE_NAME)?.value ?? "";
    if (!verifySession(raw, secret)) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
  }

  const segs = params.path ?? [];
  const apiPath = resolveApiPath(segs);
  if (apiPath === null) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  if (noAuth && req.method === "POST") {
    if (isPostRateLimited(clientIp(req), postLimitPerMin())) {
      return NextResponse.json({ error: "rate limited" }, { status: 429 });
    }
  }

  const base = apiBase();
  const isAdvance =
    segs.length === 4 && segs[0] === "v1" && segs[1] === "commands" && segs[3] === "advance";
  // Query strings are forwarded only where an endpoint needs one: mission advance, and the sealed-suite
  // catalogue version (allowlisted values only).
  const suiteVersion = req.nextUrl.searchParams.get("suite_version");
  const qs = isAdvance
    ? (req.nextUrl.search ?? "")
    : req.method === "GET" && apiPath === "/v1/eval/suites" && (suiteVersion === "v0" || suiteVersion === "v1" || suiteVersion === "v2")
      ? `?suite_version=${suiteVersion}`
      : "";
  const target = `${base}${apiPath}${qs}`;

  const idToken = await fetchIdToken(base);
  const headers: Record<string, string> = {};
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;
  const accept = req.headers.get("accept");
  if (accept) headers["accept"] = accept;
  if (idToken) headers["authorization"] = `Bearer ${idToken}`;

  let body: ArrayBuffer | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    try {
      body = await req.arrayBuffer();
    } catch {
      body = undefined;
    }
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: body === undefined ? undefined : Buffer.from(body),
    });
  } catch {
    return NextResponse.json({ error: "upstream unavailable" }, { status: 502 });
  }

  const buf = Buffer.from(await upstream.arrayBuffer());
  const outCt = upstream.headers.get("content-type") ?? "application/json";
  return new NextResponse(buf, {
    status: upstream.status,
    headers: { "content-type": outCt },
  });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  return handle(req, await ctx.params);
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  return handle(req, await ctx.params);
}

export async function PUT(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  return handle(req, await ctx.params);
}

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  return handle(req, await ctx.params);
}

export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }) {
  return handle(req, await ctx.params);
}
