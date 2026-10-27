"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const r = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (r.status === 429) {
        setErr("Too many attempts. Try again later.");
        return;
      }
      if (!r.ok) {
        setErr("Invalid credentials.");
        return;
      }
      router.push("/");
      router.refresh();
    } catch {
      setErr("Login failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main style={{ maxWidth: 400, margin: "80px auto" }}>
      <h1>Owner login</h1>
      <form onSubmit={submit}>
        <div style={{ display: "grid", gap: 12 }}>
          <label style={{ fontSize: 13 }}>
            Username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              style={{ display: "block", width: "100%", marginTop: 4, padding: 8, borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5" }}
            />
          </label>
          <label style={{ fontSize: 13 }}>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              style={{ display: "block", width: "100%", marginTop: 4, padding: 8, borderRadius: 6, border: "1px solid #33405c", background: "#0b0e14", color: "#e8edf5" }}
            />
          </label>
          <button
            type="submit"
            disabled={busy || !username || !password}
            style={{ padding: "8px 16px", borderRadius: 6, background: "#2563eb", color: "#fff", border: 0, cursor: "pointer" }}
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>
      </form>
      {err ? <p style={{ color: "#ef4444", fontSize: 13 }}>{err}</p> : null}
    </main>
  );
}
