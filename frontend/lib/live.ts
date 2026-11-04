/** Live-run logic: what a run is called, what it is waiting for, and how it is polled. */

import { ApiError } from "./api";
import { modeLabel, type Entry, type RunDetail, type RunSummary } from "./runs";

export type RunLabelKind = "replay" | "running" | "finished" | "failed" | "logged";

export interface RunLabel {
  kind: RunLabelKind;
  tag: string;
  title: string;
  detail: string;
}

const AI_DISCLOSURE = "This run sends descriptors and a spectrogram image to Meta's model API.";
const OPTIMIZER_NOTE = "Optimizer only: no model calls, and nothing is sent to Meta.";

export const START_DISCLOSURE = `${AI_DISCLOSURE} Each planner call takes about 30 s.`;
export { OPTIMIZER_NOTE };

function sendsText(mode: string): string {
  return mode === "hybrid" ? AI_DISCLOSURE : mode === "optimizer_only" ? OPTIMIZER_NOTE : "";
}

function renders(count: number): string {
  return `${count} render${count === 1 ? "" : "s"}`;
}

/** The replay wording is reachable only when the API says is_replay. */
export function runLabel(run: RunDetail, recorded: string): RunLabel {
  const count = run.entries.length;
  if (run.is_replay === true) {
    return {
      kind: "replay",
      tag: "Replay",
      title: "Replay of a logged run.",
      detail: `Recorded ${recorded}. No model calls are being made.`,
    };
  }
  switch (run.status) {
    case "running":
      return { kind: "running", tag: "Live", title: "Live run in progress.", detail: sendsText(run.mode) };
    case "finished":
      return {
        kind: "finished",
        tag: "Live, finished",
        title: "Finished live run.",
        detail: `${renders(count)} logged by this server, shown as they arrived.`,
      };
    case "failed":
      return {
        kind: "failed",
        tag: "Live, failed",
        title: "This live run failed.",
        detail: `Error: ${run.error ?? "not reported"}. ${renders(count)} logged before it stopped.`,
      };
    default:
      return { kind: "logged", tag: "Logged", title: "Logged run.", detail: `Recorded ${recorded}.` };
  }
}

export interface WaitingState {
  label: string;
  elapsedSeconds: number;
  since: string;
  note: string | null;
}

/** Renders take milliseconds, so this long a silence in a hybrid run means a planner call. */
export const QUIET_MS = 2000;

/** Only the time actually elapsed. Nothing here estimates how far along a run is. */
export function waitingState(
  run: Pick<RunDetail, "status" | "mode" | "is_replay">,
  entryCount: number,
  lastActivityMs: number,
  nowMs: number,
): WaitingState | null {
  if (run.is_replay === true || run.status !== "running") return null;
  const quiet = Math.max(0, nowMs - lastActivityMs);
  const since = entryCount === 0 ? "since the run started" : "since the last render";
  const elapsedSeconds = Math.floor(quiet / 1000);
  if (entryCount > 0 && quiet < QUIET_MS) {
    return { label: "Receiving renders", elapsedSeconds, since, note: null };
  }
  if (run.mode === "hybrid") {
    return {
      label: "Waiting for the model",
      elapsedSeconds,
      since,
      note: "A planner call takes about 30 s, and nothing arrives during one.",
    };
  }
  return { label: "Waiting for the optimizer", elapsedSeconds, since, note: null };
}

/** Live run ids carry milliseconds where a seed would be. */
const LIVE_SEED_FLOOR = 1e11;

export function isLiveSeed(seed: number): boolean {
  return seed >= LIVE_SEED_FLOOR;
}

export function targetLabel(target: string): string {
  return target.startsWith("upload_") ? "Uploaded sound" : target;
}

export function runOptionLabel(run: Pick<RunSummary, "target" | "mode" | "seed" | "status">): string {
  const when = isLiveSeed(run.seed)
    ? `live, ${new Date(run.seed).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`
    : `seed ${run.seed}`;
  const running = run.status === "running" ? " · running" : "";
  return `${targetLabel(run.target)} · ${modeLabel(run.mode)} · ${when}${running}`;
}

/** When the run last did something, for a page opened part-way through it. */
export function initialActivity(run: Pick<RunDetail, "seed">, entries: Entry[], nowMs: number): number {
  const stamp = entries.length ? Date.parse(entries[entries.length - 1].timestamp ?? "") : Number.NaN;
  const started = isLiveSeed(run.seed) ? run.seed : Number.NaN;
  const known = Number.isNaN(stamp) ? started : stamp;
  return Number.isNaN(known) ? nowMs : Math.min(known, nowMs);
}

export const POLL_MS = 1000;
/** The log file appears just after a run is accepted, so a new run can briefly 404. */
const NOT_FOUND_RETRIES = 10;

export interface PollerOptions {
  fetchRun: (after: number, signal: AbortSignal) => Promise<RunDetail>;
  onUpdate: (run: RunDetail, newEntries: number) => void;
  onConnection: (ok: boolean) => void;
  onFatal: (error: unknown) => void;
  onDone: (run: RunDetail) => void;
  expectLive?: boolean;
  intervalMs?: number;
}

/**
 * Fetches a run once, then keeps following it while it is running. The API reads entries
 * before status, so "finished" can arrive without the last entries: one more fetch follows
 * any end state before the poller stops.
 */
export function createPoller(options: PollerOptions): { stop: () => void } {
  const { fetchRun, onUpdate, onConnection, onFatal, onDone, expectLive = false } = options;
  const interval = options.intervalMs ?? POLL_MS;
  const abort = new AbortController();
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let entries: Entry[] = [];
  let seenResponse = false;
  let sawEnd = false;
  let notFound = 0;
  let connected = true;

  const schedule = (delay: number) => {
    if (!stopped) timer = setTimeout(tick, delay);
  };

  async function tick() {
    let response: RunDetail;
    try {
      response = await fetchRun(entries.length - 1, abort.signal);
    } catch (error) {
      if (stopped) return;
      const missing = error instanceof ApiError && error.status === 404;
      if (missing && !seenResponse && expectLive && notFound < NOT_FOUND_RETRIES) {
        notFound += 1;
        schedule(interval / 2);
      } else if (seenResponse && !missing) {
        if (connected) onConnection(false);
        connected = false;
        schedule(interval);
      } else {
        onFatal(error);
      }
      return;
    }
    if (stopped) return;
    if (!connected) onConnection(true);
    connected = true;
    seenResponse = true;
    entries = [...entries, ...response.entries];
    const merged = { ...response, entries };
    onUpdate(merged, response.entries.length);
    if (response.status === "running") {
      sawEnd = false;
      schedule(interval);
    } else if (response.status === "logged" || sawEnd) {
      onDone(merged);
    } else {
      sawEnd = true;
      schedule(0);
    }
  }

  schedule(0);
  return {
    stop() {
      stopped = true;
      if (timer) clearTimeout(timer);
      abort.abort();
    },
  };
}
