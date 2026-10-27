import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const COOKIE_NAME = "__Host-evoforge-session";

export async function POST() {
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
