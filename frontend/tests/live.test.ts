import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import {
  createPoller,
  initialActivity,
  isLiveSeed,
  QUIET_MS,
  runLabel,
  runOptionLabel,
  START_DISCLOSURE,
  targetLabel,
  waitingState,
} from "@/lib/live";
import type { Entry, RunDetail } from "@/lib/runs";

const entry = (index: number, timestamp: string | null = null): Entry => ({
  index,
  timestamp,
  mode: "hybrid",
  seed: 0,
  source: "optimizer",
  planner_call: null,
  hypothesis: null,
  rationale: null,
  expected_effect: null,
  recipe: null,
  loss: 0.5,
  components: null,
  failure: null,
  is_best: false,
  best_loss: 0.5,
});

const run = (patch: Partial<RunDetail> = {}): RunDetail => ({
  id: "warm_pad-hybrid-seed1793808000000",
  target: "warm_pad",
  mode: "hybrid",
  seed: 1793808000000,
  is_replay: false,
  status: "running",
  budget: 20,
  error: null,
  total: 0,
  skipped_lines: 0,
  entries: [],
  ...patch,
});

describe("runLabel", () => {
  it("says replay only when the API says is_replay", () => {
    const label = runLabel(run({ is_replay: true, status: "logged", seed: 0 }), "Nov 4");
    expect(label.kind).toBe("replay");
    expect(label.title).toBe("Replay of a logged run.");
    expect(label.detail).toContain("No model calls");
  });

  it.each(["running", "finished", "failed"] as const)("never calls a %s live run a replay", (status) => {
    const label = runLabel(run({ status }), "Nov 4");
    expect(label.kind).toBe(status);
    expect(`${label.tag} ${label.title} ${label.detail}`).not.toMatch(/replay/i);
  });

  it("discloses what a running AI run sends, and that optimizer-only sends nothing", () => {
    expect(runLabel(run(), "x").detail).toContain("descriptors and a spectrogram image");
    expect(runLabel(run({ mode: "optimizer_only" }), "x").detail).toContain("no model calls");
  });

  it("says a finished live run finished, with its real count", () => {
    const label = runLabel(run({ status: "finished", entries: [entry(0), entry(1)] }), "x");
    expect(label.title).toBe("Finished live run.");
    expect(label.detail).toContain("2 renders");
  });

  it("shows the failure and its error", () => {
    const label = runLabel(run({ status: "failed", error: "RuntimeError", entries: [entry(0)] }), "x");
    expect(label.title).toBe("This live run failed.");
    expect(label.detail).toContain("RuntimeError");
    expect(label.detail).toContain("1 render logged");
  });

  it("copes with a failure that has no error text", () => {
    expect(runLabel(run({ status: "failed" }), "x").detail).toContain("not reported");
  });

  it("makes the start disclosure specific", () => {
    expect(START_DISCLOSURE).toContain("Meta's model API");
  });
});

describe("waitingState", () => {
  it("is only for running live runs", () => {
    expect(waitingState(run({ status: "finished" }), 1, 0, 9000)).toBeNull();
    expect(waitingState(run({ status: "failed" }), 1, 0, 9000)).toBeNull();
    expect(waitingState(run({ status: "logged", is_replay: true }), 1, 0, 9000)).toBeNull();
  });

  it("waits for the model from the start of a hybrid run, with elapsed time", () => {
    const state = waitingState(run(), 0, 1000, 13500);
    expect(state?.label).toBe("Waiting for the model");
    expect(state?.elapsedSeconds).toBe(12);
    expect(state?.since).toBe("since the run started");
  });

  it("doesn't claim to wait for the model while renders are arriving", () => {
    expect(waitingState(run(), 4, 1000, 1000 + QUIET_MS - 1)?.label).toBe("Receiving renders");
    const quiet = waitingState(run(), 4, 1000, 1000 + QUIET_MS);
    expect(quiet?.label).toBe("Waiting for the model");
    expect(quiet?.since).toBe("since the last render");
  });

  it("never blames the model in an optimizer-only run", () => {
    const state = waitingState(run({ mode: "optimizer_only" }), 0, 0, 40000);
    expect(state?.label).toBe("Waiting for the optimizer");
    expect(state?.note).toBeNull();
  });

  it("reports elapsed time only, with no progress estimate", () => {
    const text = JSON.stringify(waitingState(run(), 3, 0, 20000));
    expect(text).not.toMatch(/%|remaining|eta|almost/i);
  });

  it("doesn't go negative if the clocks disagree", () => {
    expect(waitingState(run(), 0, 5000, 1000)?.elapsedSeconds).toBe(0);
  });
});

describe("naming", () => {
  it("doesn't show a live run's milliseconds as a seed", () => {
    const text = runOptionLabel({ target: "warm_pad", mode: "optimizer_only", seed: 1793808000000, status: "finished" });
    expect(text).not.toContain("seed");
    expect(text).not.toContain("1793808000000");
    expect(text).toContain("live,");
  });

  it("still shows a real seed, and marks a running run", () => {
    expect(runOptionLabel({ target: "a", mode: "hybrid", seed: 2, status: "logged" })).toBe("a · AI + optimizer · seed 2");
    expect(runOptionLabel({ target: "a", mode: "hybrid", seed: 1793808000000, status: "running" })).toContain("running");
    expect(isLiveSeed(2)).toBe(false);
  });

  it("names uploads without their id", () => {
    expect(targetLabel("upload_0123456789ab")).toBe("Uploaded sound");
    expect(targetLabel("warm_pad")).toBe("warm_pad");
  });

  it("dates activity from the last entry, then the run's start", () => {
    const now = 1793808100000;
    expect(initialActivity({ seed: 1793808000000 }, [], now)).toBe(1793808000000);
    const stamp = new Date(1793808050000).toISOString();
    expect(initialActivity({ seed: 1793808000000 }, [entry(0, stamp)], now)).toBe(1793808050000);
    expect(initialActivity({ seed: 0 }, [], now)).toBe(now);
  });
});

describe("createPoller", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function harness(responses: (RunDetail | Error)[], expectLive = false) {
    const calls: number[] = [];
    const updates: RunDetail[] = [];
    const callbacks = {
      onUpdate: vi.fn((detail: RunDetail) => updates.push(detail)),
      onConnection: vi.fn(),
      onFatal: vi.fn(),
      onDone: vi.fn(),
    };
    const poller = createPoller({
      ...callbacks,
      expectLive,
      intervalMs: 1000,
      fetchRun: async (after) => {
        calls.push(after);
        const next = responses.shift();
        if (!next) throw new Error("no more responses");
        if (next instanceof Error) throw next;
        return next;
      },
    });
    return { calls, updates, poller, ...callbacks };
  }

  it("asks only for what's new, and accumulates entries in order", async () => {
    const h = harness([
      run({ entries: [] }),
      run({ entries: [entry(0), entry(1)] }),
      run({ entries: [] }),
      run({ entries: [entry(2)] }),
    ]);
    await vi.advanceTimersByTimeAsync(3100);
    expect(h.calls).toEqual([-1, -1, 1, 1]);
    expect(h.updates.at(-1)?.entries.map((e) => e.index)).toEqual([0, 1, 2]);
    h.poller.stop();
  });

  it("waits a full interval between polls while running", async () => {
    const h = harness([run(), run(), run()]);
    await vi.advanceTimersByTimeAsync(10);
    expect(h.calls.length).toBe(1);
    await vi.advanceTimersByTimeAsync(990);
    expect(h.calls.length).toBe(2);
    h.poller.stop();
  });

  it("fetches once more after finished, and keeps entries that arrive with it", async () => {
    const h = harness([
      run({ entries: [entry(0)] }),
      run({ status: "finished", entries: [] }),
      run({ status: "finished", entries: [entry(1)] }),
    ]);
    await vi.advanceTimersByTimeAsync(5000);
    expect(h.calls).toEqual([-1, 0, 0]);
    expect(h.onDone).toHaveBeenCalledTimes(1);
    expect(h.onDone.mock.calls[0][0].entries.length).toBe(2);
  });

  it("stops after failed in the same way, carrying the error", async () => {
    const h = harness([run({ status: "failed", error: "RuntimeError" }), run({ status: "failed", error: "RuntimeError" })]);
    await vi.advanceTimersByTimeAsync(5000);
    expect(h.onDone.mock.calls[0][0].error).toBe("RuntimeError");
    expect(h.calls.length).toBe(2);
  });

  it("fetches a logged run once and never polls it", async () => {
    const h = harness([run({ status: "logged", is_replay: true, entries: [entry(0)] })]);
    await vi.advanceTimersByTimeAsync(5000);
    expect(h.calls.length).toBe(1);
    expect(h.onDone).toHaveBeenCalledTimes(1);
  });

  it("retries a brief 404 on a run it just started", async () => {
    const missing = new ApiError("gone", null, "unknown_run", 404);
    const h = harness([missing, missing, run({ status: "logged" })], true);
    await vi.advanceTimersByTimeAsync(3000);
    expect(h.onFatal).not.toHaveBeenCalled();
    expect(h.onUpdate).toHaveBeenCalledTimes(1);
  });

  it("reports a 404 at once on a run it didn't start", async () => {
    const h = harness([new ApiError("gone", null, "unknown_run", 404)]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(h.onFatal).toHaveBeenCalledTimes(1);
  });

  it("gives up on a 404 that never clears", async () => {
    const missing = new ApiError("gone", null, "unknown_run", 404);
    const h = harness(Array.from({ length: 20 }, () => missing), true);
    await vi.advanceTimersByTimeAsync(20000);
    expect(h.onFatal).toHaveBeenCalledTimes(1);
  });

  it("keeps trying after losing contact, and says when it is back", async () => {
    const h = harness([run(), new ApiError("down"), new ApiError("down"), run({ entries: [entry(0)] })]);
    await vi.advanceTimersByTimeAsync(3100);
    expect(h.onConnection.mock.calls).toEqual([[false], [true]]);
    expect(h.onFatal).not.toHaveBeenCalled();
    expect(h.updates.at(-1)?.entries.length).toBe(1);
    h.poller.stop();
  });

  it("stops polling when stopped", async () => {
    const h = harness([run(), run(), run()]);
    await vi.advanceTimersByTimeAsync(10);
    h.poller.stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(h.calls.length).toBe(1);
  });
});
