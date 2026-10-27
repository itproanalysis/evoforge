import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import crypto from "node:crypto";

const COOKIE_NAME = "__Host-evoforge-session";

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

export async function GET() {
  const secret = process.env.EVO_SESSION_SECRET ?? "";
  const jar = await cookies();
  const raw = jar.get(COOKIE_NAME)?.value ?? "";
  if (!verifySession(raw, secret)) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const user = process.env.EVO_OWNER_USER ?? "";
  return NextResponse.json({ user }, { status: 200 });
}
