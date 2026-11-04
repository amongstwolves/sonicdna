"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api, ApiError, urls, type LiveMode, type Meta, type RenderResult, type Target } from "@/lib/api";
import {
  createPoller,
  initialActivity,
  runLabel,
  runOptionLabel,
  targetLabel,
  waitingState,
} from "@/lib/live";
import { initialReplay, PACES, replayReducer } from "@/lib/replay";
import {
  bestEntry,
  formatLoss,
  renderNumber,
  type Entry,
  type Recipe,
  type RunDetail,
  type RunSummary,
} from "@/lib/runs";
import { ABPlayer } from "./ABPlayer";
import { ErrorNote } from "./ErrorNote";
import { LiveStatus } from "./LiveStatus";
import { LossChart } from "./LossChart";
import { RecipeEditor } from "./RecipeEditor";
import { Spectrogram } from "./Spectrogram";
import { StartRunPanel } from "./StartRunPanel";
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
  const newParam = params.get("new");

  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [replay, dispatch] = useReducer(replayReducer, initialReplay());
  const [selected, setSelected] = useState<number | null>(null);
  const [choice, setChoice] = useState<BChoice>("selected");
  const [edit, setEdit] = useState<Edit | null>(null);
  const [targets, setTargets] = useState<Target[]>([]);
  const [panelOpen, setPanelOpen] = useState(newParam !== null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<unknown>(null);
  const [runningRunId, setRunningRunId] = useState<string | null>(null);
  const [connected, setConnected] = useState(true);
  const [lastActivity, setLastActivity] = useState(0);
  const [now, setNow] = useState(0);
  const justStarted = useRef<string | null>(null);
  const renderTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const renderAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    api.runs().then(setRuns, setError);
    api.meta().then(setMeta, () => undefined);
    api.targets().then(setTargets, () => undefined);
  }, []);

  useEffect(() => {
    if (newParam) setPanelOpen(true);
  }, [newParam]);

  const runId = useMemo(() => {
    if (!runs) return null;
    if (runParam) return runParam;
    if (newParam) return null;
    return defaultRun(runs, targetParam)?.id ?? null;
  }, [runs, runParam, targetParam, newParam]);

  function cancelRender() {
    if (renderTimer.current) clearTimeout(renderTimer.current);
    renderAbort.current?.abort();
  }

  useEffect(() => {
    cancelRender();
    setRun(null);
    setEdit(null);
    setSelected(null);
    setChoice("selected");
    setError(null);
    setConnected(true);
    if (!runId) return;
    const expectLive = justStarted.current === runId;
    let first = true;
    const poller = createPoller({
      expectLive,
      fetchRun: (after, signal) => api.run(runId, after, signal),
      onUpdate: (detail, newEntries) => {
        const clock = Date.now();
        setRun(detail);
        setNow(clock);
        if (first) {
          first = false;
          dispatch({ type: "load", total: detail.entries.length });
          setLastActivity(expectLive && newEntries === 0 ? clock : initialActivity(detail, detail.entries, clock));
        } else if (newEntries > 0) {
          setLastActivity(clock);
        }
      },
      onConnection: setConnected,
      onFatal: setError,
      onDone: (detail) => {
        if (!detail.is_replay) api.runs().then(setRuns, () => undefined);
      },
    });
    return () => poller.stop();
  }, [runId]);

  const isRunning = run?.status === "running";
  useEffect(() => {
    if (!isRunning) return;
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(clock);
  }, [isRunning]);

  async function startRun(target: string, mode: LiveMode) {
    setStarting(true);
    setStartError(null);
    setRunningRunId(null);
    try {
      const started = await api.startRun(target, mode);
      justStarted.current = started.id;
      setPanelOpen(false);
      router.replace(`/lab?run=${started.id}`);
      api.runs().then(setRuns, () => undefined);
    } catch (failure) {
      setStartError(failure);
      if (failure instanceof ApiError && failure.code === "run_in_progress") {
        api.runs().then((list) => {
          setRuns(list);
          setRunningRunId(list.find((item) => item.status === "running")?.id ?? null);
        }, () => undefined);
      }
    } finally {
      setStarting(false);
    }
  }

  useEffect(() => {
    if (!replay.playing) return;
    const timer = setInterval(() => dispatch({ type: "tick" }), replay.msPerStep);
    return () => clearInterval(timer);
  }, [replay.playing, replay.msPerStep]);

  const entries = run?.entries ?? [];
  const isReplay = run?.is_replay === true;
  // A live run shows everything that has arrived. Only a replay is paced.
  const visible = run && !isReplay ? entries.length : replay.revealed;
  const revealedEntries = useMemo(() => entries.slice(0, visible), [entries, visible]);
  const best = useMemo(() => bestEntry(revealedEntries), [revealedEntries]);
  const position =
    selected !== null && selected < visible ? selected : visible > 0 ? visible - 1 : null;
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

  const groups = (runs ?? []).reduce<Record<string, RunSummary[]>>((all, item) => {
    (all[item.target] ??= []).push(item);
    return all;
  }, {});

  const label = run ? runLabel(run, recordedAt(entries)) : null;
  const waiting = run ? waitingState(run, entries.length, lastActivity, now) : null;
  const wholeRunBest = bestEntry(entries);
  const noRuns = runs !== null && runs.length === 0 && !runId;
  const listedRun = (runs ?? []).some((item) => item.id === runId);
  const heldOut = (target: string) => targets.some((item) => item.name === target && item.held_out);
  const countLabel = !run
    ? "0 renders"
    : isReplay
      ? `${visible} of ${entries.length} renders`
      : run.status === "running" && run.budget
        ? `${entries.length} logged, budget ${run.budget}`
        : `${entries.length} render${entries.length === 1 ? "" : "s"}`;
  const emptyText = !run
    ? "No run loaded."
    : run.status === "running"
      ? "Nothing logged yet. Renders appear here as they happen."
      : entries.length === 0 && !isReplay
        ? "This run logged nothing."
        : entries.length === 0
          ? "This log has no entries."
          : "Press play to reveal the log, one render at a time.";

  const filenameStem = run ? `${run.id}-${showingEdit ? "edit" : `render${shown ? renderNumber(shown) : ""}`}` : "recipe";

  return (
    <div className="lab">
      <section className="replay-bar">
        {label ? (
          <div className={`replay-label run-label-${label.kind}`} role="status">
            <span className={`replay-tag tag-${label.kind}`}>{label.tag}</span>
            <span>
              <strong>{label.title}</strong> {label.detail}
            </span>
          </div>
        ) : !runId ? (
          <div className="replay-label" role="status">
            No run loaded. Choose a sound and a mode below, or open a run from the list.
          </div>
        ) : null}
        <div className="replay-controls">
          <label className="field-inline">
            <span>Run</span>
            <select
              value={runId ?? ""}
              onChange={(event) => router.replace(`/lab?run=${event.target.value}`)}
            >
              {!runId ? <option value="">Choose a run</option> : null}
              {runId && !listedRun ? <option value={runId}>{run ? runOptionLabel(run) : runId}</option> : null}
              {Object.entries(groups).map(([target, items]) => (
                <optgroup key={target} label={`${targetLabel(target)}${heldOut(target) ? " (held out)" : ""}`}>
                  {items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {runOptionLabel(item)}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          {isReplay ? (
            <>
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
            </>
          ) : null}
          <div className="bar-actions">
            {wholeRunBest && run && !isRunning ? (
              <Link className="button" href={`/alchemy?run=${run.id}`}>
                Send this run&apos;s best to Alchemy →
              </Link>
            ) : null}
            <button
              type="button"
              className="button live-button"
              aria-expanded={panelOpen}
              onClick={() => setPanelOpen((open) => !open)}
            >
              Start live run
            </button>
          </div>
        </div>
        {run && !isRunning && run.skipped_lines > 0 ? (
          <p className="warning-inline">
            {run.skipped_lines} line{run.skipped_lines === 1 ? "" : "s"} in this log could not be read
            and {run.skipped_lines === 1 ? "is" : "are"} not shown.
          </p>
        ) : null}
      </section>

      {panelOpen ? (
        <StartRunPanel
          targets={targets}
          initialTarget={newParam ?? run?.target ?? null}
          busy={starting}
          blocked={isRunning}
          error={startError}
          runningRunId={runningRunId}
          publicMode={meta?.public_mode === true}
          onStart={(target, mode) => void startRun(target, mode)}
          onCancel={() => setPanelOpen(false)}
        />
      ) : null}

      {run && !isReplay ? <LiveStatus state={waiting} connected={connected} /> : null}

      {error ? <ErrorNote error={error} /> : null}

      {noRuns ? (
        <div className="panel empty-state hero-empty">
          <h1>No logged runs found.</h1>
          <p>
            Replays read JSON-lines logs from the <code>runs/</code> folder, or the folder named by{" "}
            <code>SONICDNA_RUNS_DIR</code> on the API server. You can also start a live run.
          </p>
        </div>
      ) : null}

      {!runId ? null : (
      <div className="lab-grid">
        <Timeline
          entries={revealedEntries}
          countLabel={countLabel}
          emptyText={emptyText}
          selectedPosition={position}
          bestIndex={best?.index ?? null}
          onSelect={selectStep}
        />

        <div className="lab-main">
          <LossChart
            allEntries={entries}
            revealed={visible}
            capacity={run && !isReplay ? (run.budget ?? 0) : 0}
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
                  <Spectrogram src={urls.targetSpectrogram(run.target)} title={`Reference: ${targetLabel(run.target)}`} />
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
                          : isReplay
                            ? "Press play to reveal the first render."
                            : "No render has arrived yet."
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
      )}
    </div>
  );
}
