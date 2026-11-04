import type { WaitingState } from "@/lib/live";

export function LiveStatus({ state, connected }: { state: WaitingState | null; connected: boolean }) {
  if (!connected) {
    return (
      <p className="live-status live-status-lost" role="status">
        Lost contact with the API. Still trying.
      </p>
    );
  }
  if (!state) return null;
  return (
    <p className="live-status" role="status">
      <span className="live-dot" aria-hidden="true" />
      <strong>{state.label}</strong>
      <span className="mono">
        {state.elapsedSeconds} s {state.since}
      </span>
      {state.note ? <span className="muted">{state.note}</span> : null}
    </p>
  );
}
