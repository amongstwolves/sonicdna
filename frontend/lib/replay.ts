/** Replay pacing as a pure reducer. It only controls how much of a real log is visible. */

export const PACES = [
  { label: "Slow", ms: 3000 },
  { label: "Normal", ms: 1500 },
  { label: "Fast", ms: 500 },
] as const;

export interface ReplayState {
  total: number;
  revealed: number;
  playing: boolean;
  msPerStep: number;
}

export type ReplayAction =
  | { type: "load"; total: number }
  | { type: "play" }
  | { type: "pause" }
  | { type: "tick" }
  | { type: "forward" }
  | { type: "back" }
  | { type: "restart" }
  | { type: "reveal_all" }
  | { type: "seek"; revealed: number }
  | { type: "pace"; msPerStep: number };

export function initialReplay(total = 0): ReplayState {
  return { total, revealed: 0, playing: false, msPerStep: PACES[1].ms };
}

export function replayReducer(state: ReplayState, action: ReplayAction): ReplayState {
  const clamp = (n: number) => Math.max(0, Math.min(state.total, n));
  switch (action.type) {
    case "load":
      return { ...initialReplay(action.total), msPerStep: state.msPerStep };
    case "play": {
      if (state.total === 0) return state;
      // Playing from the end starts again, and the first step shows at once.
      const from = state.revealed >= state.total ? 0 : state.revealed;
      return { ...state, revealed: from + 1, playing: from + 1 < state.total };
    }
    case "pause":
      return { ...state, playing: false };
    case "tick": {
      const revealed = clamp(state.revealed + 1);
      return { ...state, revealed, playing: state.playing && revealed < state.total };
    }
    case "forward":
      return { ...state, revealed: clamp(state.revealed + 1), playing: false };
    case "back":
      return { ...state, revealed: clamp(state.revealed - 1), playing: false };
    case "restart":
      return { ...state, revealed: 0, playing: false };
    case "reveal_all":
      return { ...state, revealed: state.total, playing: false };
    case "seek":
      return { ...state, revealed: clamp(action.revealed), playing: false };
    case "pace":
      return { ...state, msPerStep: action.msPerStep };
  }
}
