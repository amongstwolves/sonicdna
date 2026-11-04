/** Pure logic over logged run entries. Everything shown here comes from the log. */

export type Recipe = Record<string, any>;

export interface Entry {
  index: number;
  timestamp: string | null;
  mode: string | null;
  seed: number | null;
  source: string | null;
  planner_call: number | null;
  hypothesis: string | null;
  rationale: string | null;
  expected_effect: string | null;
  recipe: Recipe | null;
  loss: number | null;
  components: Record<string, number> | null;
  failure: string | null;
  is_best: boolean;
  best_loss: number | null;
}

export interface RunSummary {
  id: string;
  target: string;
  mode: string;
  seed: number;
  entries: number;
  skipped_lines: number;
  best_loss: number | null;
}

export interface RunDetail {
  id: string;
  target: string;
  mode: string;
  seed: number;
  is_replay: boolean;
  total: number;
  skipped_lines: number;
  entries: Entry[];
}

export type ProvenanceKey = "model" | "optimizer" | "fallback" | "random" | "unknown";

export interface Provenance {
  key: ProvenanceKey;
  label: string;
  description: string;
}

const PROVENANCE: Record<Exclude<ProvenanceKey, "unknown">, Provenance> = {
  model: {
    key: "model",
    label: "Model",
    description: "Proposed by the AI planner",
  },
  optimizer: {
    key: "optimizer",
    label: "Optimizer",
    description: "Fine-tuned by numeric search",
  },
  fallback: {
    key: "fallback",
    label: "Fallback",
    description: "Deterministic backup, used when the planner's answer was rejected",
  },
  random: {
    key: "random",
    label: "Random",
    description: "Random draw from the allowed parameter ranges",
  },
};

/** Never guesses: a missing or unrecognised source is shown as unknown. */
export function provenanceOf(source: string | null | undefined): Provenance {
  if (source && Object.hasOwn(PROVENANCE, source)) {
    return PROVENANCE[source as keyof typeof PROVENANCE];
  }
  return {
    key: "unknown",
    label: source ? `Source: ${source}` : "Source not logged",
    description: "The log does not say which part of the system made this render",
  };
}

const MODE_LABELS: Record<string, string> = {
  random: "Random search",
  optimizer_only: "Optimizer only",
  hybrid: "AI + optimizer",
};

export function modeLabel(mode: string | null | undefined): string {
  if (!mode) return "Unknown mode";
  return MODE_LABELS[mode] ?? mode;
}

/** A normalized loss as a plain decimal. */
export function formatLoss(loss: number | null | undefined): string {
  return loss === null || loss === undefined || !Number.isFinite(loss) ? "n/a" : loss.toFixed(3);
}

export function renderNumber(entry: Pick<Entry, "index">): number {
  return entry.index + 1;
}

export interface ChartPoint {
  index: number;
  loss: number | null;
  best: number | null;
  failed: boolean;
  isNewBest: boolean;
  provenance: ProvenanceKey;
}

/** Best-so-far per render. Prefers the logged value; failed renders never improve it. */
export function bestSoFarSeries(entries: Entry[]): ChartPoint[] {
  let previous: number | null = null;
  return entries.map((entry) => {
    const failed = entry.failure !== null || entry.loss === null;
    const computed: number | null =
      failed || (previous !== null && previous <= (entry.loss as number)) ? previous : entry.loss;
    const best = entry.best_loss ?? computed;
    const isNewBest = !failed && best !== null && (previous === null || best < previous);
    previous = best;
    return {
      index: entry.index,
      loss: failed ? null : entry.loss,
      best,
      failed,
      isNewBest,
      provenance: provenanceOf(entry.source).key,
    };
  });
}

/** Lowest-loss render so far, or null if none has succeeded. */
export function bestEntry(entries: Entry[]): Entry | null {
  let best: Entry | null = null;
  for (const entry of entries) {
    if (entry.failure !== null || entry.loss === null) continue;
    if (best === null || entry.loss < (best.loss as number)) best = entry;
  }
  return best;
}

/** Fixed y maximum for a whole run, so the axis doesn't jump during a replay. */
export function chartMax(entries: Entry[]): number {
  const values = bestSoFarSeries(entries).flatMap((p) =>
    [p.loss, p.best].filter((v): v is number => v !== null),
  );
  if (values.length === 0) return 1;
  const peak = Math.max(...values);
  if (peak <= 0) return 1;
  const step = 10 ** Math.floor(Math.log10(peak)) / 2;
  return Math.ceil((peak * 1.02) / step) * step;
}

function hz(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(1)} kHz` : `${Math.round(value)} Hz`;
}

/** A factual one-liner about a recipe, computed from its values. Contains no reasoning. */
export function describeRecipe(recipe: Recipe | null | undefined): string {
  const osc = recipe?.oscillator;
  if (!osc || typeof osc !== "object" || typeof osc.frequency_hz !== "number") {
    return "This recipe could not be read.";
  }
  const parts = [`${osc.type} wave at ${hz(osc.frequency_hz)}`];
  if (recipe?.oscillator_2) {
    parts.push(`second ${recipe.oscillator_2.type} wave`);
  }
  if (recipe?.filter) parts.push(`low-pass at ${hz(recipe.filter.cutoff_hz)}`);
  if (recipe?.distortion) parts.push(`distortion ${recipe.distortion.drive.toFixed(2)}`);
  if (recipe?.delay) parts.push(`delay ${Math.round(recipe.delay.time_ms)} ms`);
  return parts.join(", ");
}

export type Headline =
  | { kind: "hypothesis"; text: string }
  | { kind: "failure"; text: string }
  | { kind: "recipe"; text: string };

function present(text: string | null | undefined): string | null {
  return text && text.trim() ? text.trim() : null;
}

/** The one line on a timeline card. Only "hypothesis" is reasoning, and only from the log. */
export function headline(entry: Entry): Headline {
  const hypothesis = present(entry.hypothesis);
  if (hypothesis) return { kind: "hypothesis", text: hypothesis };
  const failure = present(entry.failure);
  if (failure) return { kind: "failure", text: failure };
  return { kind: "recipe", text: describeRecipe(entry.recipe) };
}

export interface LoggedNote {
  label: string;
  text: string;
}

/** Reasoning fields the log actually holds, in reading order. */
export function loggedNotes(entry: Entry): LoggedNote[] {
  const notes: [string, string | null][] = [
    ["Hypothesis", present(entry.hypothesis)],
    ["Why this change?", present(entry.rationale)],
    ["Expected effect", present(entry.expected_effect)],
  ];
  return notes.flatMap(([label, text]) => (text ? [{ label, text }] : []));
}

const PARAM_LABELS: Record<string, string> = {
  "oscillator.type": "Wave shape",
  "oscillator.frequency_hz": "Pitch (Hz)",
  "oscillator.gain": "Wave level",
  "oscillator_2.type": "Second wave shape",
  "oscillator_2.gain": "Second wave level",
  "oscillator_2.frequency_ratio": "Second wave pitch ratio",
  "envelope.attack_s": "Attack (s)",
  "envelope.decay_s": "Decay (s)",
  "envelope.sustain": "Sustain level",
  "envelope.release_s": "Release (s)",
  "filter.cutoff_hz": "Filter cutoff (Hz)",
  "distortion.drive": "Distortion",
  "delay.time_ms": "Delay time (ms)",
  "delay.feedback": "Delay feedback",
  "delay.wet": "Delay level",
};

export interface ParamChange {
  path: string;
  label: string;
  from: string;
  to: string;
}

function flatten(recipe: Recipe | null | undefined): Record<string, unknown> {
  const flat: Record<string, unknown> = {};
  for (const path of Object.keys(PARAM_LABELS)) {
    const [node, field] = path.split(".");
    const parent = recipe?.[node];
    flat[path] = parent && typeof parent === "object" ? parent[field] : undefined;
  }
  return flat;
}

function shown(value: unknown): string {
  if (value === undefined || value === null) return "off";
  if (typeof value !== "number") return String(value);
  return Math.abs(value) >= 100 ? value.toFixed(0) : Number(value.toPrecision(3)).toString();
}

/** What differs between two logged recipes. Computed, so it holds for any source. */
export function changedParams(
  previous: Recipe | null | undefined,
  current: Recipe | null | undefined,
): ParamChange[] {
  const before = flatten(previous);
  const after = flatten(current);
  return Object.keys(PARAM_LABELS).flatMap((path) =>
    before[path] === after[path] || (before[path] ?? null) === (after[path] ?? null)
      ? []
      : [{ path, label: PARAM_LABELS[path], from: shown(before[path]), to: shown(after[path]) }],
  );
}

export const COMPONENT_LABELS: Record<string, { label: string; plain: string }> = {
  stft: { label: "Spectrum", plain: "Which frequencies are present, and when" },
  centroid: { label: "Brightness", plain: "How bright it is, in octaves of difference" },
  envelope: { label: "Loudness shape", plain: "How the level moves over time" },
};
