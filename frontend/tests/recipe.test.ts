import { describe, expect, it } from "vitest";
import {
  fromPosition,
  getParam,
  setNodeEnabled,
  setParam,
  SLIDERS,
  toPosition,
} from "@/lib/recipe";

const recipe = {
  envelope: { attack_s: 0.02, decay_s: 0.2, sustain: 0.5, release_s: 0.2 },
  filter: null,
  distortion: { drive: 0.4 },
};

const cutoff = SLIDERS.find((s) => s.path === "filter.cutoff_hz")!;
const drive = SLIDERS.find((s) => s.path === "distortion.drive")!;

describe("sliders", () => {
  it("offers at least three parameters", () => {
    expect(SLIDERS.length).toBeGreaterThanOrEqual(3);
  });

  it("maps positions to values inside the bounds on a log scale", () => {
    const bounds: [number, number] = [20, 20000];
    expect(fromPosition(0, bounds, "log")).toBeCloseTo(20);
    expect(fromPosition(1000, bounds, "log")).toBeCloseTo(20000);
    expect(fromPosition(500, bounds, "log")).toBeCloseTo(632.46, 1);
    expect(toPosition(2000, bounds, "log")).toBe(667);
  });

  it("clamps out-of-range values", () => {
    expect(toPosition(5, [20, 20000], "log")).toBe(0);
    expect(toPosition(2, [0, 1], "linear")).toBe(1000);
  });

  it("edits without changing the original recipe", () => {
    const edited = setParam(recipe, "envelope.attack_s", 0.5);
    expect(getParam(edited, "envelope.attack_s")).toBe(0.5);
    expect(recipe.envelope.attack_s).toBe(0.02);
    expect(edited.envelope.decay_s).toBe(0.2);
  });

  it("reads a switched-off node as null", () => {
    expect(getParam(recipe, "filter.cutoff_hz")).toBeNull();
  });

  it("switches a filter on with a valid node, and off to null", () => {
    const on = setNodeEnabled(recipe, cutoff, true);
    expect(on.filter).toEqual({ type: "lowpass", cutoff_hz: 20000 });
    expect(setNodeEnabled(on, cutoff, false).filter).toBeNull();
    expect(setNodeEnabled(setNodeEnabled(recipe, drive, false), drive, true).distortion).toEqual({ drive: 0 });
  });
});
