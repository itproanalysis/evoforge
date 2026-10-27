import { NextRequest, NextResponse } from "next/server";
import createIntlMiddleware from 'next-intl/middleware';

const COOKIE_NAME = "__Host-evoforge-session";

// Create next-intl middleware
const intlMiddleware = createIntlMiddleware({
  locales: ['en', 'ko'],
  defaultLocale: 'en',
  localePrefix: 'as-needed',
});

// Server-only auth mode, read at runtime. Any value other than "none"
// means the default "session" behaviour (owner login required).
function authDisabled(): boolean {
  return (process.env.EVO_WEB_AUTH ?? "") === "none";
}

function hexToBytes(hex: string): Uint8Array | null {
  if (hex.length % 2 !== 0) return null;
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    const b = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
    if (Number.isNaN(b)) return null;
    out[i] = b;
  }
  return out;
}

async function validSession(raw: string | undefined, secret: string): Promise<boolean> {
  if (!raw || !secret) return false;
  const parts = raw.split(".");
  if (parts.length !== 3) return false;
  const [random, sigHex, expStr] = parts;
  if (!random || !sigHex || !expStr) return false;
  const expiry = Number(expStr);
  if (!Number.isInteger(expiry)) return false;
  if (expiry <= Math.floor(Date.now() / 1000)) return false;
  const expectedSig = hexToBytes(sigHex);
  if (!expectedSig) return false;
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
    const data = new TextEncoder().encode(`${random}.${expiry}`);
    const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, data));
    if (mac.length !== expectedSig.length) return false;
    let diff = 0;
    for (let i = 0; i < mac.length; i++) diff |= mac[i] ^ expectedSig[i];
    return diff === 0;
  } catch {
    return false;
  }
}

export async function middleware(req: NextRequest) {
  const p = req.nextUrl.pathname;
  
  // Skip auth check for static assets and API routes
  if (
    p.startsWith("/_next/") ||
    p === "/favicon.ico" ||
    p === "/favicon.png" ||
    p.startsWith("/api/")
  ) {
    return NextResponse.next();
  }
  
  // Apply i18n middleware first to handle locale routing
  const intlResponse = intlMiddleware(req);
  
  // If auth is disabled, skip auth check
  if (authDisabled()) {
    if (p === "/login" || p.startsWith("/login/") || p === "/ko/login" || p === "/en/login") {
      const url = req.nextUrl.clone();
      url.pathname = "/";
      url.search = "";
      return NextResponse.redirect(url, 307);
    }
    return intlResponse;
  }
  
  // Skip auth for login pages
  if (
    p === "/login" ||
    p.startsWith("/login/") ||
    p === "/ko/login" ||
    p === "/en/login" ||
    p === "/api/login"
  ) {
    return intlResponse;
  }
  
  // Validate session
  const raw = req.cookies.get(COOKIE_NAME)?.value;
  const secret = process.env.EVO_SESSION_SECRET ?? "";
  if (await validSession(raw, secret)) {
    return intlResponse;
  }
  
  // Redirect to login if not authenticated
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ['/', '/(ko|en)/:path*', '/((?!_next/static|_next/image|favicon.ico|api).*)'],
};
