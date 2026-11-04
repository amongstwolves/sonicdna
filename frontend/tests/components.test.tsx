import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Disclosure } from "@/components/Disclosure";
import { defaultRun } from "@/components/LabScreen";
import { LossChart } from "@/components/LossChart";
import { StepDetail } from "@/components/StepDetail";
import { TimelineCard } from "@/components/Timeline";
import { errorFromResponse, oversizeError } from "@/lib/api";
import type { Entry, RunSummary } from "@/lib/runs";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/lab",
}));

afterEach(cleanup);

const recipe = {
  oscillator: { type: "saw", frequency_hz: 220, gain: 0.7 },
  oscillator_2: null,
  envelope: { attack_s: 0.02, decay_s: 0.2, sustain: 0.5, release_s: 0.2 },
  filter: { type: "lowpass", cutoff_hz: 2000 },
  distortion: null,
  delay: null,
};

function entry(overrides: Partial<Entry> = {}): Entry {
  return {
    index: 0,
    timestamp: null,
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

function card(overrides: Partial<Entry>) {
  return render(<TimelineCard entry={entry(overrides)} selected={false} isBest={false} onSelect={vi.fn()} />);
}

describe("timeline card", () => {
  it("renders an entry from today's logs, with no invented hypothesis", () => {
    const { container } = card({});
    expect(screen.getByText("Random")).toBeTruthy();
    expect(container.textContent).toContain("No hypothesis logged");
    expect(container.textContent).toContain("saw wave at 220 Hz");
    expect(container.textContent).not.toContain("Planner call");
    expect(container.querySelector(".card-random")).toBeTruthy();
  });

  it("renders the new fields from the log", () => {
    const { container } = card({
      source: "model",
      planner_call: 2,
      hypothesis: "Logged hypothesis text",
    });
    expect(screen.getByText("Model")).toBeTruthy();
    expect(screen.getByText("Planner call 2")).toBeTruthy();
    expect(container.textContent).toContain("Logged hypothesis text");
    expect(container.textContent).not.toContain("No hypothesis logged");
    expect(container.querySelector(".card-model")).toBeTruthy();
  });

  it.each(["model", "optimizer", "fallback", "random"])("gives %s its own style", (source) => {
    const { container } = card({ source });
    expect(container.querySelector(`.card-${source}`)).toBeTruthy();
    expect(container.querySelector(`.chip-${source}`)).toBeTruthy();
  });

  it("renders a failed entry with null loss", () => {
    const { container } = card({ source: "model", loss: null, failure: "cutoff out of range", best_loss: null });
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(container.textContent).toContain("cutoff out of range");
    expect(container.textContent).not.toContain("null");
  });

  it("never shows a percentage", () => {
    const { container } = card({ loss: 0.8062527 });
    expect(container.textContent).toContain("0.806");
    expect(container.textContent).not.toContain("%");
  });
});

describe("planner call tag", () => {
  it("doesn't credit an optimizer render to the planner", () => {
    const { container } = card({ source: "optimizer", planner_call: 2 });
    expect(container.textContent).toContain("After planner call 2");
  });
});

describe("step detail", () => {
  it("states that the log has no reasoning rather than making some up", () => {
    const { container } = render(<StepDetail entry={entry()} previous={null} meta={null} />);
    expect(container.textContent).toContain("The log holds no hypothesis or reasoning");
    expect(container.textContent).not.toContain("Why this change?");
  });

  it("shows logged reasoning and the failure text", () => {
    const { container } = render(
      <StepDetail
        entry={entry({ hypothesis: "H", rationale: "R", expected_effect: "E", loss: null, failure: "F" })}
        previous={null}
        meta={null}
      />,
    );
    for (const text of ["Hypothesis", "Why this change?", "Expected effect", "This render failed"]) {
      expect(container.textContent).toContain(text);
    }
    expect(container.textContent).toContain("n/a");
  });

  it("labels the number normalized loss", () => {
    const { container } = render(<StepDetail entry={entry()} previous={null} meta={null} />);
    expect(container.textContent).toContain("normalized loss");
    expect(container.textContent).not.toContain("%");
  });
});

describe("loss chart", () => {
  const entries = [
    entry({ index: 0, loss: 0.8, best_loss: 0.8 }),
    entry({ index: 1, loss: null, best_loss: 0.8, failure: "bad", source: "fallback" }),
    entry({ index: 2, loss: 0.3, best_loss: 0.3, source: "model" }),
  ];

  it("says lower is better and uses the required label", () => {
    const { container } = render(
      <LossChart allEntries={entries} revealed={3} selectedPosition={null} onSelect={vi.fn()} />,
    );
    expect(container.textContent).toContain("normalized loss");
    expect(container.textContent).toContain("Lower is better");
    expect(container.textContent).not.toContain("%");
  });

  it("draws only the revealed renders", () => {
    const { container } = render(
      <LossChart allEntries={entries} revealed={1} selectedPosition={null} onSelect={vi.fn()} />,
    );
    expect(container.querySelectorAll('[data-testid="render-mark"]').length).toBe(1);
    expect(container.textContent).toContain("0.800");
    expect(container.textContent).not.toContain("0.300");
  });

  it("marks a failed render without plotting a loss", () => {
    const { container } = render(
      <LossChart allEntries={entries} revealed={3} selectedPosition={null} onSelect={vi.fn()} />,
    );
    expect(container.querySelectorAll('[data-testid="render-mark"]').length).toBe(2);
    expect(container.querySelectorAll(".failed-mark").length).toBe(1);
  });
});

describe("disclosure", () => {
  it("says what live runs send and that replays send nothing", () => {
    const { container } = render(<Disclosure />);
    expect(container.textContent).toContain("descriptors and a spectrogram image");
    expect(container.textContent).toContain("Meta's model API");
    expect(container.textContent).toContain("Optimizer-only runs and replays send nothing");
  });
});

describe("default run", () => {
  const summary = (target: string, mode: string, seed = 0): RunSummary => ({
    id: `${target}-${mode}-seed${seed}`,
    target,
    mode,
    seed,
    entries: 1,
    skipped_lines: 0,
    best_loss: 0.1,
    status: "logged",
  });

  it("prefers hybrid over baselines, and honours a target", () => {
    const runs = [summary("a", "random"), summary("b", "hybrid"), summary("a", "optimizer_only")];
    expect(defaultRun(runs, null)?.id).toBe("b-hybrid-seed0");
    expect(defaultRun(runs, "a")?.id).toBe("a-optimizer_only-seed0");
    expect(defaultRun(runs, "none")).toBeNull();
  });

  it("picks the lowest seed", () => {
    expect(defaultRun([summary("a", "random", 2), summary("a", "random", 1)], "a")?.seed).toBe(1);
  });
});

describe("api errors", () => {
  it("refuses an oversized file before sending it", () => {
    expect(oversizeError(8 * 1024 * 1024)).toBeNull();
    expect(oversizeError(8 * 1024 * 1024 + 1)?.code).toBe("file_too_large");
    expect(oversizeError(11, 10)?.message).toContain("limit");
  });

  it("reads the API's structured error", async () => {
    const response = new Response(
      JSON.stringify({ detail: { code: "clipped", message: "Clipped.", fix: "Lower it." } }),
      { status: 422 },
    );
    const error = await errorFromResponse(response);
    expect(error.message).toBe("Clipped.");
    expect(error.fix).toBe("Lower it.");
    expect(error.code).toBe("clipped");
  });

  it("turns a bare 404 into something actionable", async () => {
    const error = await errorFromResponse(new Response('{"detail":"Not Found"}', { status: 404 }));
    expect(error.fix).toBe("Pick an item from the list.");
  });

  it("explains an unreachable API behind the proxy", async () => {
    const error = await errorFromResponse(new Response("Internal Server Error", { status: 500 }));
    expect(error.fix).toContain("uvicorn");
  });
});
