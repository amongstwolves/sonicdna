"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api, ApiError, urls, type Meta, type RenderResult } from "@/lib/api";
import { initialReplay, PACES, replayReducer } from "@/lib/replay";
import {
  bestEntry,
  formatLoss,
  modeLabel,
  renderNumber,
  type Entry,
  type Recipe,
  type RunDetail,
  type RunSummary,
} from "@/lib/runs";
import { ABPlayer } from "./ABPlayer";
import { ErrorNote } from "./ErrorNote";
import { LossChart } from "./LossChart";
import { RecipeEditor } from "./RecipeEditor";
import { Spectrogram } from "./Spectrogram";
import { StepDetail } from "./StepDetail";
import { Timeline } from "./Timeline";

type BChoice = "selected" | "best" | "edit";

interface Edit {
  baseIndex: number;
  recipe: Recipe;
  result: RenderResult | null;
  rendering: boolean;
  error: string | null;
}

const MODE_ORDER = ["hybrid", "optimizer_only", "random"];

/** Prefers the most interesting mode for a target, then the lowest seed. */
export function defaultRun(runs: RunSummary[], target: string | null): RunSummary | null {
  const pool = target ? runs.filter((run) => run.target === target) : runs;
  const rank = (mode: string) => {
    const position = MODE_ORDER.indexOf(mode);
    return position === -1 ? MODE_ORDER.length : position;
  };
  return (
    [...pool].sort(
      (a, b) =>
        rank(a.mode) - rank(b.mode) ||
        a.target.localeCompare(b.target) ||
        a.seed - b.seed,
    )[0] ?? null
  );
}

function recordedAt(entries: Entry[]): string {
  const stamp = entries.find((entry) => entry.timestamp)?.timestamp;
  if (!stamp) return "time not logged";
  const date = new Date(stamp);
  return Number.isNaN(date.getTime()) ? stamp : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function LabScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const runParam = params.get("run");
  const targetParam = params.get("target");

  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [replay, dispatch] = useReducer(replayReducer, initialReplay());
  const [selected, setSelected] = useState<number | null>(null);
  const [choice, setChoice] = useState<BChoice>("selected");
  const [edit, setEdit] = useState<Edit | null>(null);
  const renderTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const renderAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    api.runs().then(setRuns, setError);
    api.meta().then(setMeta, () => undefined);
  }, []);

  const runId = useMemo(() => {
    if (!runs) return null;
    if (runParam) return runParam;
    return defaultRun(runs, targetParam)?.id ?? null;
  }, [runs, runParam, targetParam]);

  function cancelRender() {
    if (renderTimer.current) clearTimeout(renderTimer.current);
    renderAbort.current?.abort();
  }

  useEffect(() => {
    if (!runId) return;
    let current = true;
    cancelRender();
    setRun(null);
    setEdit(null);
    setSelected(null);
    setChoice("selected");
    setError(null);
    api.run(runId).then(
      (detail) => {
        if (!current) return;
        setRun(detail);
        dispatch({ type: "load", total: detail.entries.length });
      },
      (failure) => current && setError(failure),
    );
    return () => {
      current = false;
    };
  }, [runId]);

  useEffect(() => {
    if (!replay.playing) return;
    const timer = setInterval(() => dispatch({ type: "tick" }), replay.msPerStep);
    return () => clearInterval(timer);
  }, [replay.playing, replay.msPerStep]);

  const entries = run?.entries ?? [];
  const revealedEntries = useMemo(() => entries.slice(0, replay.revealed), [entries, replay.revealed]);
  const best = useMemo(() => bestEntry(revealedEntries), [revealedEntries]);
  const position =
    selected !== null && selected < replay.revealed
      ? selected
      : replay.revealed > 0
        ? replay.revealed - 1
        : null;
  const current = position !== null ? entries[position] : null;
  const previous = position !== null && position > 0 ? entries[position - 1] : null;

  const editBase = edit ? (entries.find((e) => e.index === edit.baseIndex) ?? null) : null;
  const shown: Entry | null = choice === "best" ? best : choice === "edit" ? editBase : current;
  const editorBase = editBase ?? shown;

  const showingEdit = choice === "edit" && edit !== null;
  const unrenderable = shown?.failure !== null && shown?.failure !== undefined;
  const bUrl = !run
    ? null
    : showingEdit
      ? (edit.result?.audio ?? null)
      : shown && !unrenderable
        ? urls.entryAudio(run.id, shown.index)
        : null;
  const bLabel = showingEdit
    ? "Your edit"
    : shown
      ? `Render ${renderNumber(shown)}${choice === "best" ? " (best)" : ""}`
      : "No render yet";
  const renderedSpectrogram = !run
    ? null
    : showingEdit
      ? (edit.result?.spectrogram ?? null)
      : shown && !unrenderable
        ? urls.entrySpectrogram(run.id, shown.index)
        : null;

  function selectStep(next: number) {
    cancelRender();
    dispatch({ type: "pause" });
    setSelected(next);
    setEdit(null);
    setChoice("selected");
  }

  function control(action: Parameters<typeof dispatch>[0]) {
    if (action.type !== "pace" && action.type !== "pause") {
      cancelRender();
      setSelected(null);
      setEdit(null);
      if (choice === "edit") setChoice("selected");
    }
    dispatch(action);
  }

  function changeRecipe(recipe: Recipe) {
    if (!run || !editorBase) return;
    dispatch({ type: "pause" });
    setChoice("edit");
    setEdit((old) => ({
      baseIndex: editorBase.index,
      recipe,
      result: old?.result ?? null,
      rendering: true,
      error: null,
    }));
    cancelRender();
    const target = run.target;
    renderTimer.current = setTimeout(() => {
      const abort = new AbortController();
      renderAbort.current = abort;
      api.render(recipe, target, abort.signal).then(
        (result) =>
          setEdit((old) => (old && old.recipe === recipe ? { ...old, result, rendering: false } : old)),
        (failure) => {
          if ((failure as Error).name === "AbortError") return;
          setEdit((old) =>
            old && old.recipe === recipe
              ? {
                  ...old,
                  rendering: false,
                  error: failure instanceof ApiError ? failure.message : "The render failed.",
                }
              : old,
          );
        },
      );
    }, 220);
  }

  function resetEdit() {
    cancelRender();
    setEdit(null);
    setChoice("selected");
  }

  if (runs && runs.length === 0) {
    return (
      <div className="panel empty-state hero-empty">
        <h1>No logged runs found.</h1>
        <p>
          Replays read JSON-lines logs from the <code>runs/</code> folder, or the folder named by{" "}
          <code>SONICDNA_RUNS_DIR</code> on the API server.
        </p>
      </div>
    );
  }

  const groups = (runs ?? []).reduce<Record<string, RunSummary[]>>((all, item) => {
    (all[item.target] ??= []).push(item);
    return all;
  }, {});

  const filenameStem = run ? `${run.id}-${showingEdit ? "edit" : `render${shown ? renderNumber(shown) : ""}`}` : "recipe";

  return (
    <div className="lab">
      <section className="replay-bar">
        <div className="replay-label" role="status">
          <span className="replay-tag">Replay</span>
          <span>
            <strong>Replay of a logged run.</strong> Recorded {recordedAt(entries)}. No model calls are
            being made.
          </span>
        </div>
        <div className="replay-controls">
          <label className="field-inline">
            <span>Run</span>
            <select
              value={runId ?? ""}
              onChange={(event) => router.replace(`/lab?run=${event.target.value}`)}
            >
              {Object.entries(groups).map(([target, items]) => (
                <optgroup key={target} label={target}>
                  {items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {target} · {modeLabel(item.mode)} · seed {item.seed}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <div className="transport" role="group" aria-label="Replay controls">
            <button type="button" className="button" title="Back to the start" onClick={() => control({ type: "restart" })}>
              ⏮ Restart
            </button>
            <button type="button" className="button" title="Previous render" onClick={() => control({ type: "back" })}>
              ◀ Step
            </button>
            {replay.playing ? (
              <button type="button" className="button button-primary" onClick={() => control({ type: "pause" })}>
                ❚❚ Pause
              </button>
            ) : (
              <button
                type="button"
                className="button button-primary"
                disabled={entries.length === 0}
                onClick={() => control({ type: "play" })}
              >
                ▶ Play replay
              </button>
            )}
            <button type="button" className="button" title="Next render" onClick={() => control({ type: "forward" })}>
              Step ▶
            </button>
            <button type="button" className="button" onClick={() => control({ type: "reveal_all" })}>
              Show all
            </button>
          </div>
          <div className="pace" role="group" aria-label="Replay pace">
            <span>Pace</span>
            {PACES.map((pace) => (
              <button
                key={pace.label}
                type="button"
                className="pace-button"
                aria-pressed={replay.msPerStep === pace.ms}
                onClick={() => control({ type: "pace", msPerStep: pace.ms })}
              >
                {pace.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="button live-button"
            disabled
            title="Live runs are not connected yet"
          >
            Start live run (not connected)
          </button>
        </div>
        {run && run.skipped_lines > 0 ? (
          <p className="warning-inline">
            {run.skipped_lines} line{run.skipped_lines === 1 ? "" : "s"} in this log could not be read
            and {run.skipped_lines === 1 ? "is" : "are"} not shown.
          </p>
        ) : null}
      </section>

      {error ? <ErrorNote error={error} /> : null}

      <div className="lab-grid">
        <Timeline
          entries={revealedEntries}
          total={entries.length}
          selectedPosition={position}
          bestIndex={best?.index ?? null}
          onSelect={selectStep}
        />

        <div className="lab-main">
          <LossChart
            allEntries={entries}
            revealed={replay.revealed}
            selectedPosition={position}
            onSelect={selectStep}
          />

          {run ? (
            <>
              <ABPlayer
                referenceUrl={urls.targetAudio(run.target)}
                renderUrl={bUrl}
                renderLabel={bLabel}
              />
              <div className="b-choice" role="group" aria-label="Which render to compare">
                <span>Compare the reference with</span>
                <button type="button" className="pace-button" aria-pressed={choice === "selected"} onClick={() => setChoice("selected")}>
                  Selected render
                </button>
                <button
                  type="button"
                  className="pace-button"
                  aria-pressed={choice === "best"}
                  disabled={!best}
                  onClick={() => setChoice("best")}
                >
                  Best so far{best ? ` (render ${renderNumber(best)}, ${formatLoss(best.loss)})` : ""}
                </button>
                <button
                  type="button"
                  className="pace-button"
                  aria-pressed={choice === "edit"}
                  disabled={!edit}
                  onClick={() => setChoice("edit")}
                >
                  Your edit
                </button>
              </div>
              <div className="spectro-pair">
                <div className="panel">
                  <Spectrogram src={urls.targetSpectrogram(run.target)} title={`Reference: ${run.target}`} />
                </div>
                <div className="panel">
                  <Spectrogram
                    src={renderedSpectrogram}
                    title={showingEdit ? "Your edit" : shown ? `Rendered: render ${renderNumber(shown)}` : "Rendered"}
                    emptyText={
                      unrenderable
                        ? "This render failed, so there is nothing to show."
                        : showingEdit
                          ? "Rendering your edit…"
                          : "Press play to reveal the first render."
                    }
                  />
                </div>
              </div>
              <div className="detail-pair">
                <StepDetail entry={choice === "best" ? best : current} previous={choice === "best" ? null : previous} meta={meta} />
                <RecipeEditor
                  meta={meta}
                  recipe={edit?.recipe ?? editorBase?.recipe ?? null}
                  baseName={editorBase ? `render ${renderNumber(editorBase)}` : "no render"}
                  baseLoss={editorBase?.loss ?? null}
                  edited={edit !== null}
                  editLoss={edit?.result?.loss ?? null}
                  notScoredReason={edit?.result?.not_scored_reason ?? null}
                  rendering={edit?.rendering ?? false}
                  error={edit?.error ?? null}
                  audioUrl={bUrl}
                  filenameStem={filenameStem}
                  onChange={changeRecipe}
                  onReset={resetEdit}
                />
              </div>
              <p className="muted lab-footnote">
                Normalized loss is a defined measurement of spectrum, brightness and loudness shape. It
                is not a measure of how alike two sounds seem to a listener. The recipe is a plausible
                reconstruction, not proof of how the original was made.{" "}
                <Link href={`/decode?target=${run.target}`}>Inspect this sound in Decode</Link>
              </p>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
