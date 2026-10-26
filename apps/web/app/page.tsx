"use client";
import { useState } from "react";

export default function Page() {
  const [goal, setGoal] = useState("Fix flaky login retry");
  const [out, setOut] = useState<any>(null);
  const run = async () => {
    const r = await fetch("http://localhost:8080/v1/commands/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal, repo_sha: "HEAD", risk: "LOW" }),
    });
    setOut(await r.json());
  };
  return (
    <main style={{ padding: 24, fontFamily: "system-ui" }}>
      <h1>EvoForge — Mission Control (H1 slice)</h1>
      <p>Builder: Muse Spark 1.3 via Meta Model API · Gates: GH_INTEGRITY (oracle_ast + provisional D-054)</p>
      <input value={goal} onChange={(e) => setGoal(e.target.value)} style={{ width: 420 }} />
      <button onClick={run} style={{ marginLeft: 8 }}>Generate candidate</button>
      <pre>{out ? JSON.stringify(out, null, 2) : "no run yet"}</pre>
    </main>
  );
}
