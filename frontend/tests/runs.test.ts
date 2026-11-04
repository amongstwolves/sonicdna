import { describe, expect, it } from "vitest";
import {
  bestEntry,
  bestSoFarSeries,
  changedParams,
  chartMax,
  describeRecipe,
  formatLoss,
  headline,
  loggedNotes,
  modeLabel,
  provenanceOf,
  type Entry,
} from "@/lib/runs";

const recipe = {
  oscillator: { type: "saw", frequency_hz: 220, gain: 0.7 },
  oscillator_2: null,
  envelope: { attack_s: 0.02, decay_s: 0.2, sustain: 0.5, release_s: 0.2 },
  filter: { type: "lowpass", cutoff_hz: 2000 },
  distortion: null,
  delay: null,
};

export function entry(overrides: Partial<Entry> = {}): Entry {
  return {
    index: 0,
    timestamp: "2026-11-04T15:46:37+00:00",
    mode: "random",
    seed: 0,
    source: "random",
    planner_call: null,
    hypothesis: null,
    rationale: null,
    expected_effect: null,
    recipe,
    loss: 0.5,
    components: { stft: 0.1, centroid: 0.2, envelope: 0.3 },
    failure: null,
    is_best: false,
    best_loss: 0.5,
    ...overrides,
  };
}

describe("bestSoFarSeries", () => {
  it("uses the logged best_loss and marks improvements", () => {
    const points = bestSoFarSeries([
      entry({ index: 0, loss: 0.8, best_loss: 0.8 }),
      entry({ index: 1, loss: 0.9, best_loss: 0.8 }),
      entry({ index: 2, loss: 0.3, best_loss: 0.3 }),
    ]);
    expect(points.map((p) => p.best)).toEqual([0.8, 0.8, 0.3]);
    expect(points.map((p) => p.isNewBest)).toEqual([true, false, true]);
  });

  it("computes best-so-far when best_loss is absent", () => {
    const points = bestSoFarSeries([
      entry({ index: 0, loss: 0.8, best_loss: null }),
      entry({ index: 1, loss: 0.9, best_loss: null }),
      entry({ index: 2, loss: 0.3, best_loss: null }),
    ]);
    expect(points.map((p) => p.best)).toEqual([0.8, 0.8, 0.3]);
  });

  it("keeps the line through a failed render with null loss", () => {
    const points = bestSoFarSeries([
      entry({ index: 0, loss: null, best_loss: null, failure: "bad" }),
      entry({ index: 1, loss: 0.6, best_loss: 0.6 }),
      entry({ index: 2, loss: null, best_loss: 0.6, failure: "bad" }),
      entry({ index: 3, loss: null, best_loss: null, failure: "bad" }),
    ]);
    expect(points.map((p) => p.best)).toEqual([null, 0.6, 0.6, 0.6]);
    expect(points.map((p) => p.failed)).toEqual([true, false, true, true]);
    expect(points.map((p) => p.loss)).toEqual([null, 0.6, null, null]);
    expect(points.map((p) => p.isNewBest)).toEqual([false, true, false, false]);
  });

  it("is empty for an empty log", () => {
    expect(bestSoFarSeries([])).toEqual([]);
  });
});

describe("bestEntry", () => {
  it("ignores failures and picks the lowest loss", () => {
    const best = bestEntry([
      entry({ index: 0, loss: 0.5 }),
      entry({ index: 1, loss: null, failure: "bad" }),
      entry({ index: 2, loss: 0.2 }),
      entry({ index: 3, loss: 0.3 }),
    ]);
    expect(best?.index).toBe(2);
  });

  it("is null when nothing succeeded", () => {
    expect(bestEntry([entry({ loss: null, failure: "bad" })])).toBeNull();
  });
});

describe("chartMax", () => {
  it("stays above every value and is 1 with no data", () => {
    expect(chartMax([entry({ loss: 0.848, best_loss: 0.806 })])).toBeGreaterThanOrEqual(0.848);
    expect(chartMax([])).toBe(1);
    expect(chartMax([entry({ loss: null, best_loss: null, failure: "x" })])).toBe(1);
  });
});

describe("provenance", () => {
  it.each([
    ["model", "Model"],
    ["optimizer", "Optimizer"],
    ["fallback", "Fallback"],
    ["random", "Random"],
  ])("labels %s", (source, label) => {
    expect(provenanceOf(source).key).toBe(source);
    expect(provenanceOf(source).label).toBe(label);
  });

  it("gives the four sources four different labels", () => {
    const labels = ["model", "optimizer", "fallback", "random"].map((s) => provenanceOf(s).label);
    expect(new Set(labels).size).toBe(4);
  });

  it("never guesses a missing or unknown source", () => {
    expect(provenanceOf(null).key).toBe("unknown");
    expect(provenanceOf(undefined).label).toBe("Source not logged");
    expect(provenanceOf("gremlin").label).toBe("Source: gremlin");
    expect(provenanceOf("constructor").key).toBe("unknown");
  });

  it("labels run modes", () => {
    expect(modeLabel("hybrid")).toBe("AI + optimizer");
    expect(modeLabel("optimizer_only")).toBe("Optimizer only");
    expect(modeLabel("random")).toBe("Random search");
    expect(modeLabel(null)).toBe("Unknown mode");
  });
});

describe("formatLoss", () => {
  it.each([0, 0.011, 0.5, 0.8062527, 1, 3.79, 100])("never shows %s as a percentage", (value) => {
    expect(formatLoss(value)).toMatch(/^\d+\.\d{3}$/);
    expect(formatLoss(value)).not.toContain("%");
  });

  it("shows missing values as n/a", () => {
    expect(formatLoss(null)).toBe("n/a");
    expect(formatLoss(undefined)).toBe("n/a");
    expect(formatLoss(Number.NaN)).toBe("n/a");
  });
});

describe("headline and notes never invent reasoning", () => {
  it("uses the logged hypothesis when it exists", () => {
    expect(headline(entry({ hypothesis: "  A darker filter fits.  " }))).toEqual({
      kind: "hypothesis",
      text: "A darker filter fits.",
    });
  });

  it("falls back to a factual recipe description, not a hypothesis", () => {
    const line = headline(entry());
    expect(line.kind).toBe("recipe");
    expect(line.text).toBe("saw wave at 220 Hz, low-pass at 2.0 kHz");
  });

  it("treats blank text as absent", () => {
    expect(headline(entry({ hypothesis: "   " })).kind).toBe("recipe");
    expect(loggedNotes(entry({ hypothesis: " ", rationale: "" }))).toEqual([]);
  });

  it("shows a failure when there is no hypothesis", () => {
    const line = headline(entry({ loss: null, failure: "out of range" }));
    expect(line).toEqual({ kind: "failure", text: "out of range" });
  });

  it("returns only the notes present in the log", () => {
    const notes = loggedNotes(entry({ rationale: "because", expected_effect: null }));
    expect(notes).toEqual([{ label: "Why this change?", text: "because" }]);
  });

  it("copes with an unreadable recipe", () => {
    expect(describeRecipe({ oscillator: "broken" })).toBe("This recipe could not be read.");
    expect(describeRecipe(null)).toBe("This recipe could not be read.");
  });
});

describe("changedParams", () => {
  it("lists only what differs, including nodes switching on and off", () => {
    const next = {
      ...recipe,
      filter: null,
      distortion: { drive: 0.25 },
      envelope: { ...recipe.envelope, attack_s: 0.1 },
    };
    const changes = changedParams(recipe, next);
    expect(changes.map((c) => c.path).sort()).toEqual([
      "distortion.drive",
      "envelope.attack_s",
      "filter.cutoff_hz",
    ]);
    expect(changes.find((c) => c.path === "filter.cutoff_hz")).toMatchObject({ from: "2000", to: "off" });
    expect(changes.find((c) => c.path === "distortion.drive")).toMatchObject({ from: "off", to: "0.25" });
  });

  it("finds nothing between identical recipes, and survives a broken one", () => {
    expect(changedParams(recipe, { ...recipe })).toEqual([]);
    expect(() => changedParams({ oscillator: "broken" }, null)).not.toThrow();
  });
});
