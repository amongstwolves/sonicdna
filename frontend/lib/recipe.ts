/** Slider definitions and immutable recipe edits. Bounds come from the API's /api/meta. */

import type { Recipe } from "./runs";

export interface SliderDef {
  path: string;
  label: string;
  plain: string;
  unit: string;
  scale: "log" | "linear";
  /** Value used if the user switches this node on from off. */
  whenOn?: number;
}

export const SLIDERS: SliderDef[] = [
  {
    path: "filter.cutoff_hz",
    label: "Filter cutoff",
    plain: "Lower sounds darker",
    unit: "Hz",
    scale: "log",
    whenOn: 20000,
  },
  {
    path: "envelope.attack_s",
    label: "Attack",
    plain: "How quickly it starts",
    unit: "s",
    scale: "log",
  },
  {
    path: "envelope.decay_s",
    label: "Decay",
    plain: "How quickly it falls to the held level",
    unit: "s",
    scale: "log",
  },
  {
    path: "envelope.sustain",
    label: "Sustain",
    plain: "The level it holds, 0 to 1",
    unit: "",
    scale: "linear",
  },
  {
    path: "distortion.drive",
    label: "Distortion",
    plain: "Higher sounds grittier, 0 to 1",
    unit: "",
    scale: "linear",
    whenOn: 0,
  },
];

export const SLIDER_STEPS = 1000;

export function toPosition(value: number, [low, high]: [number, number], scale: SliderDef["scale"]) {
  const bounded = Math.max(low, Math.min(high, value));
  const fraction =
    scale === "log"
      ? Math.log(bounded / low) / Math.log(high / low)
      : (bounded - low) / (high - low);
  return Math.round(fraction * SLIDER_STEPS);
}

export function fromPosition(
  position: number,
  [low, high]: [number, number],
  scale: SliderDef["scale"],
) {
  const fraction = position / SLIDER_STEPS;
  const value = scale === "log" ? low * (high / low) ** fraction : low + (high - low) * fraction;
  return Math.max(low, Math.min(high, value));
}

export function getParam(recipe: Recipe, path: string): number | null {
  const [node, field] = path.split(".");
  const value = recipe[node]?.[field];
  return typeof value === "number" ? value : null;
}

export function setParam(recipe: Recipe, path: string, value: number): Recipe {
  const [node, field] = path.split(".");
  return { ...recipe, [node]: { ...recipe[node], [field]: value } };
}

/** Filter and distortion can be off (null) in a recipe. Envelope is always on. */
export function setNodeEnabled(recipe: Recipe, def: SliderDef, enabled: boolean): Recipe {
  const [node, field] = def.path.split(".");
  if (!enabled) return { ...recipe, [node]: null };
  const fixed = node === "filter" ? { type: "lowpass" } : {};
  return { ...recipe, [node]: { ...fixed, [field]: def.whenOn ?? 0 } };
}

export function formatParam(value: number, unit: string): string {
  const text =
    Math.abs(value) >= 100 ? value.toFixed(0) : Number(value.toPrecision(3)).toString();
  return unit ? `${text} ${unit}` : text;
}
