/** Display rules for measured Alchemy values. */

export interface Variant {
  label: string;
  recipe: Record<string, any>;
  target_brightness_hz: number | null;
  brightness_hz: number;
  brightness_change: number;
  estimated_pitch_hz: number | null;
  pitch_shift_cents: number | null;
  pitch_preserved: boolean;
  audio: string;
  spectrogram: string;
}

export interface AlchemyResult {
  goal: {
    direction: string | null;
    atmosphere: boolean;
    preserve_pitch_requested: boolean;
    preserve_pitch: boolean;
  };
  note: string | null;
  base_brightness_hz: number;
  base_pitch_hz: number;
  renders_tested: number;
  pitch_tolerance_cents: number;
  variants: Variant[];
}

export const DEMO_PROMPT = "brighter and more atmospheric, keep the pitch";

export const ALCHEMY_RULES =
  "Alchemy reads your prompt with fixed rules. It makes no model call, and it only supports brightness and atmosphere.";

/** A change in brightness as a multiple of the starting sound. */
export function formatMultiple(value: number): string {
  return `×${value.toFixed(2)}`;
}

export function formatHz(value: number): string {
  return `${Math.round(value)} Hz`;
}

export function formatCents(value: number | null): string {
  if (value === null) return "n/a";
  // The pitch estimator resolves about 10 cents, so smaller shifts can't be told apart.
  return value < 10 ? "under 10 cents" : `${value.toFixed(0)} cents`;
}

export function formatTarget(variant: Pick<Variant, "target_brightness_hz">, baseHz: number): string {
  const target = variant.target_brightness_hz;
  if (target === null) return "None: atmosphere only";
  return `${formatHz(target)} (${formatMultiple(target / baseHz)})`;
}

export function describeGoal(goal: AlchemyResult["goal"]): string {
  const parts = [];
  if (goal.direction) parts.push(goal.direction);
  if (goal.atmosphere) parts.push("more atmospheric");
  if (goal.preserve_pitch) parts.push("pitch kept");
  return parts.join(", ");
}
