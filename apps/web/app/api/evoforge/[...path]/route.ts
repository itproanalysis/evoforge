import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { resolveApiPath } from "@/lib/proxyPolicy";

const COOKIE_NAME = "__Host-evoforge-session";
const METADATA_BASE = "http://metadata.google.internal";
// Path policy (exact paths such as /v1/ledger plus /v1/evidence/{id} families)
// lives in @/lib/proxyPolicy and is enforced via resolveApiPath() below.

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
  const secret = process.env.EVO_SESSION_SECRET ?? "";
  const jar = await cookies();
  const raw = jar.get(COOKIE_NAME)?.value ?? "";
  if (!verifySession(raw, secret)) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const segs = params.path ?? [];
  const apiPath = resolveApiPath(segs);
  if (apiPath === null) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  const base = apiBase();
  const isAdvance =
    segs.length === 4 && segs[0] === "v1" && segs[1] === "commands" && segs[3] === "advance";
  const qs = isAdvance ? (req.nextUrl.search ?? "") : "";
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
