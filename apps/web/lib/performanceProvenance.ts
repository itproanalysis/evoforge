import type { MeasurementView } from "./api";

export type Provenance = "simulated" | "recorded" | "unknown";

export function provenance(value: unknown): Provenance {
  return value === true ? "simulated" : value === false ? "recorded" : "unknown";
}

export function viewProvenance(view: MeasurementView | null | undefined): Provenance {
  const outer = view?.provider_stub;
  const record = view?.record?.provider_stub;
  if (outer === true || record === true) return "simulated";
  return provenance(outer ?? record);
}

export function comparisonProvenance(a: MeasurementView | null | undefined, b: MeasurementView | null | undefined): Provenance {
  const values = [viewProvenance(a), viewProvenance(b)];
  if (values.includes("simulated")) return "simulated";
  if (values.every((v) => v === "recorded")) return "recorded";
  return "unknown";
}
