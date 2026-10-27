import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";

const COOKIE_NAME = "__Host-evoforge-session";
const MAX_AGE = 43200;
const WINDOW_MS = 10 * 60 * 1000;
const MAX_FAILS = 10;

const fails = new Map<string, { count: number; first: number }>();

// Server-only auth mode, read at runtime. Any value other than "none"
// means the default "session" behaviour.
function authDisabled(): boolean {
  return (process.env.EVO_WEB_AUTH ?? "") === "none";
}

function notFound() {
  return NextResponse.json({ error: "not found" }, { status: 404 });
}

function methodNotAllowed() {
  return NextResponse.json({ error: "method not allowed" }, { status: 405 });
}

function clientIp(req: NextRequest): string {
  const fwd = req.headers.get("x-forwarded-for");
  if (fwd) {
    const first = fwd.split(",")[0]?.trim();
    if (first) return first;
  }
  return "unknown";
}

function isRateLimited(ip: string): boolean {
  const e = fails.get(ip);
  if (!e) return false;
  if (Date.now() - e.first > WINDOW_MS) {
    fails.delete(ip);
    return false;
  }
  return e.count >= MAX_FAILS;
}

function recordFail(ip: string): void {
  const now = Date.now();
  const e = fails.get(ip);
  if (!e || now - e.first > WINDOW_MS) {
    fails.set(ip, { count: 1, first: now });
  } else {
    e.count += 1;
  }
}

function safeEqualStr(a: string, b: string): boolean {
  const ha = crypto.createHash("sha256").update(a, "utf8").digest();
  const hb = crypto.createHash("sha256").update(b, "utf8").digest();
  return crypto.timingSafeEqual(ha, hb);
}

function verifyPassword(password: string, stored: string): boolean {
  const parts = stored.split("$");
  if (parts.length !== 6 || parts[0] !== "scrypt") return false;
  const n = Number(parts[1]);
  const r = Number(parts[2]);
  const p = Number(parts[3]);
  if (!Number.isInteger(n) || !Number.isInteger(r) || !Number.isInteger(p)) return false;
  let salt: Buffer;
  let expected: Buffer;
  try {
    salt = Buffer.from(parts[4], "hex");
    expected = Buffer.from(parts[5], "hex");
  } catch {
    return false;
  }
  if (salt.length === 0 || expected.length === 0) return false;
  let derived: Buffer;
  try {
    derived = crypto.scryptSync(password, salt, expected.length, { N: n, r, p });
  } catch {
    return false;
  }
  if (derived.length !== expected.length) return false;
  return crypto.timingSafeEqual(derived, expected);
}

function createSessionValue(secret: string): string {
  const random = crypto.randomBytes(32).toString("base64url");
  const expiry = Math.floor(Date.now() / 1000) + MAX_AGE;
  const data = `${random}.${expiry}`;
  const sig = crypto.createHmac("sha256", secret).update(data, "utf8").digest("hex");
  return `${random}.${sig}.${expiry}`;
}

export async function POST(req: NextRequest) {
  if (authDisabled()) {
    return notFound();
  }
  let body: { username?: unknown; password?: unknown };
  try {
    body = (await req.json()) as { username?: unknown; password?: unknown };
  } catch {
    return NextResponse.json({ error: "invalid request" }, { status: 401 });
  }
  const username = typeof body.username === "string" ? body.username : "";
  const password = typeof body.password === "string" ? body.password : "";
  const ip = clientIp(req);
  if (isRateLimited(ip)) {
    return NextResponse.json({ error: "too many attempts" }, { status: 429 });
  }

  const ownerUser = process.env.EVO_OWNER_USER ?? "";
  const ownerHash = process.env.EVO_OWNER_PASSWORD_HASH ?? "";
  const secret = process.env.EVO_SESSION_SECRET ?? "";
  if (!ownerUser || !ownerHash || !secret) {
    return NextResponse.json({ error: "auth unavailable" }, { status: 401 });
  }

  const userOk = username.length > 0 && safeEqualStr(username, ownerUser);
  const passOk = password.length > 0 && verifyPassword(password, ownerHash);
  if (!userOk || !passOk) {
    recordFail(ip);
    if (isRateLimited(ip)) {
      return NextResponse.json({ error: "too many attempts" }, { status: 429 });
    }
    return NextResponse.json({ error: "invalid credentials" }, { status: 401 });
  }

  fails.delete(ip);
  const value = createSessionValue(secret);
  const jar = await cookies();
  jar.set(COOKIE_NAME, value, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: MAX_AGE,
  });
  return NextResponse.json({ user: ownerUser }, { status: 200 });
}

export async function GET() {
  if (authDisabled()) {
    return notFound();
  }
  return methodNotAllowed();
}

export async function PUT() {
  if (authDisabled()) {
    return notFound();
  }
  return methodNotAllowed();
}

export async function PATCH() {
  if (authDisabled()) {
    return notFound();
  }
  return methodNotAllowed();
}

export async function DELETE() {
  if (authDisabled()) {
    return notFound();
  }
  return methodNotAllowed();
}
