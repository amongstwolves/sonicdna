import { describe, expect, it } from "vitest";
import { initialReplay, replayReducer, type ReplayState } from "@/lib/replay";

const start = (total = 3, patch: Partial<ReplayState> = {}): ReplayState => ({
  ...initialReplay(total),
  ...patch,
});

describe("replay reducer", () => {
  it("starts with nothing revealed", () => {
    expect(start().revealed).toBe(0);
    expect(start().playing).toBe(false);
  });

  it("reveals the first step at once on play, then one per tick, then stops", () => {
    let state = replayReducer(start(), { type: "play" });
    expect(state).toMatchObject({ revealed: 1, playing: true });
    state = replayReducer(state, { type: "tick" });
    expect(state).toMatchObject({ revealed: 2, playing: true });
    state = replayReducer(state, { type: "tick" });
    expect(state).toMatchObject({ revealed: 3, playing: false });
    state = replayReducer(state, { type: "tick" });
    expect(state.revealed).toBe(3);
  });

  it("starts again when played from the end", () => {
    expect(replayReducer(start(3, { revealed: 3 }), { type: "play" }).revealed).toBe(1);
  });

  it("does nothing when played with an empty log", () => {
    expect(replayReducer(start(0), { type: "play" })).toMatchObject({ revealed: 0, playing: false });
  });

  it("does not stop at the end of a one-entry log with playing left on", () => {
    expect(replayReducer(start(1), { type: "play" })).toMatchObject({ revealed: 1, playing: false });
  });

  it("steps within the bounds and pauses", () => {
    const playing = start(3, { revealed: 1, playing: true });
    expect(replayReducer(playing, { type: "forward" })).toMatchObject({ revealed: 2, playing: false });
    expect(replayReducer(playing, { type: "back" })).toMatchObject({ revealed: 0, playing: false });
    expect(replayReducer(start(3), { type: "back" }).revealed).toBe(0);
    expect(replayReducer(start(3, { revealed: 3 }), { type: "forward" }).revealed).toBe(3);
  });

  it("restarts, reveals all and seeks", () => {
    expect(replayReducer(start(3, { revealed: 2 }), { type: "restart" }).revealed).toBe(0);
    expect(replayReducer(start(3), { type: "reveal_all" }).revealed).toBe(3);
    expect(replayReducer(start(3), { type: "seek", revealed: 99 }).revealed).toBe(3);
  });

  it("changes pace without moving, and keeps pace when a new run loads", () => {
    const paced = replayReducer(start(3, { revealed: 2 }), { type: "pace", msPerStep: 500 });
    expect(paced).toMatchObject({ revealed: 2, msPerStep: 500 });
    expect(replayReducer(paced, { type: "load", total: 7 })).toMatchObject({
      total: 7,
      revealed: 0,
      msPerStep: 500,
    });
  });
});
