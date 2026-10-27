"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, Input, Card } from "../../../components/ui";

export default function LoginPage() {
  const router = useRouter();
  const t = useTranslations("login");

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
        setErr(t("error-too-many-attempts"));
        return;
      }
      if (!r.ok) {
        setErr(t("error-invalid-credentials"));
        return;
      }
      router.push("/");
      router.refresh();
    } catch {
      setErr(t("error-login-failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="max-w-[400px] mx-auto mt-20">
      <h1 className="text-2xl font-bold mb-4">{t("heading")}</h1>
      <Card>
        <form onSubmit={submit} className="grid gap-3">
          <Input
            label={t("username-label")}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
          />
          <Input
            label={t("password-label")}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          <Button
            type="submit"
            disabled={busy || !username || !password}
            loading={busy}
            variant="primary"
          >
            {busy ? t("signing-in") : t("sign-in")}
          </Button>
        </form>
        {err && <p className="text-accent-red text-sm mt-2">{err}</p>}
      </Card>
    </main>
  );
}
