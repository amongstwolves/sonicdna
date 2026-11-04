"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { LiveMode, Target } from "@/lib/api";
import { OPTIMIZER_NOTE, START_DISCLOSURE, targetLabel } from "@/lib/live";
import { ErrorNote } from "./ErrorNote";

/** Starting a run is always an explicit click here, never a side effect of a link. */
export function StartRunPanel({
  targets,
  initialTarget,
  busy,
  blocked,
  error,
  runningRunId,
  onStart,
  onCancel,
}: {
  targets: Target[];
  initialTarget: string | null;
  busy: boolean;
  blocked: boolean;
  error: unknown;
  runningRunId: string | null;
  onStart: (target: string, mode: LiveMode) => void;
  onCancel: () => void;
}) {
  const [target, setTarget] = useState(initialTarget ?? "");
  const [mode, setMode] = useState<LiveMode | null>(null);
  useEffect(() => {
    if (initialTarget) setTarget(initialTarget);
  }, [initialTarget]);

  const listed = targets.some((item) => item.name === target);
  return (
    <section className="panel start-panel" aria-label="Start a live run">
      <h2>Start a live run</h2>
      <div className="start-fields">
        <label className="field-inline">
          <span>Sound</span>
          <select value={target} onChange={(event) => setTarget(event.target.value)}>
            <option value="" disabled>
              Choose a sound
            </option>
            {target && !listed ? <option value={target}>{targetLabel(target)}</option> : null}
            {targets
              .filter((item) => item.available)
              .map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                  {item.held_out ? " (held out)" : ""}
                </option>
              ))}
          </select>
        </label>
        <fieldset className="mode-choice">
          <legend>Mode</legend>
          <label className="toggle">
            <input
              type="radio"
              name="live-mode"
              checked={mode === "hybrid"}
              onChange={() => setMode("hybrid")}
            />
            AI + optimizer
          </label>
          <label className="toggle">
            <input
              type="radio"
              name="live-mode"
              checked={mode === "optimizer_only"}
              onChange={() => setMode("optimizer_only")}
            />
            Optimizer only
          </label>
        </fieldset>
        <span className="muted">Budget: 20 renders</span>
      </div>
      {mode === "hybrid" ? (
        <p className="start-disclosure" role="note">
          <strong>Sent to Meta:</strong> {START_DISCLOSURE}
        </p>
      ) : null}
      {mode === "optimizer_only" ? <p className="muted">{OPTIMIZER_NOTE}</p> : null}
      {error ? <ErrorNote error={error} /> : null}
      {runningRunId ? (
        <p className="muted">
          <Link href={`/lab?run=${runningRunId}`}>Open the run that is going</Link>
        </p>
      ) : null}
      <div className="row">
        <button
          type="button"
          className="button button-primary"
          disabled={!target || !mode || busy || blocked}
          onClick={() => mode && onStart(target, mode)}
        >
          {busy
            ? "Starting…"
            : mode === "hybrid"
              ? "Start live AI run"
              : mode === "optimizer_only"
                ? "Start optimizer-only run"
                : "Choose a mode to start"}
        </button>
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}
