import type { EvolutionRun } from "./api";

export type ReplaySelection =
  | { runId: string; status: "loading" }
  | { runId: string; status: "ready"; run: EvolutionRun; refreshError?: unknown }
  | { runId: string; status: "error"; error: unknown };

/** Only GETs the selected run; cleanup invalidates pending responses and timers. */
export function watchReplaySelection(
  runId: string,
  read: (id: string) => Promise<EvolutionRun>,
  update: (state: ReplaySelection) => void,
  intervalMs = 5000,
): () => void {
  let active = true;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let lastRun: EvolutionRun | undefined;
  update({ runId, status: "loading" });

  async function refresh() {
    try {
      const run = await read(runId);
      if (!active) return;
      if (!run || run.run_id !== runId) throw new Error("Unexpected replay run response");
      lastRun = run;
      update({ runId, status: "ready", run });
    } catch (error) {
      if (!active) return;
      update(lastRun
        ? { runId, status: "ready", run: lastRun, refreshError: error }
        : { runId, status: "error", error });
    }
    // Schedule after completion: a slow GET can never overlap the next poll.
    if (active && lastRun?.status === "running") timer = setTimeout(refresh, intervalMs);
  }
  void refresh();
  return () => {
    active = false;
    if (timer !== undefined) clearTimeout(timer);
  };
}
