import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const COOKIE_NAME = "__Host-evoforge-session";

// Server-only auth mode, read at runtime. Any value other than "none"
// means the default "session" behaviour.
function authDisabled(): boolean {
  return (process.env.EVO_WEB_AUTH ?? "") === "none";
}

export async function POST() {
  if (authDisabled()) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const jar = await cookies();
  jar.set(COOKIE_NAME, "", {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return NextResponse.json({ ok: true }, { status: 200 });
}

export async function GET() {
  if (authDisabled()) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json({ error: "method not allowed" }, { status: 405 });
}
