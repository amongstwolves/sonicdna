"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ALCHEMY_RULES,
  DEMO_PROMPT,
  describeGoal,
  formatCents,
  formatHz,
  formatMultiple,
  formatTarget,
  type AlchemyResult,
  type Variant,
} from "@/lib/alchemy";
import { api, urls } from "@/lib/api";
import { downloadJson } from "@/lib/download";
import { runOptionLabel } from "@/lib/live";
import {
  bestEntry,
  describeRecipe,
  formatLoss,
  renderNumber,
  type RunDetail,
  type RunSummary,
} from "@/lib/runs";
import { ABPlayer } from "./ABPlayer";
import { ErrorNote } from "./ErrorNote";
import { Spectrogram } from "./Spectrogram";

export function VariantCard({
  variant,
  baseBrightnessHz,
  toleranceCents,
  startingUrl,
  filenameStem,
}: {
  variant: Variant;
  baseBrightnessHz: number;
  toleranceCents: number;
  startingUrl: string;
  filenameStem: string;
}) {
  const stem = `${filenameStem}-${variant.label}`;
  return (
    <article className="variation-card" data-testid="variant-card">
      <header>
        <h3>{variant.label}</h3>
        <span className="multiple mono">{formatMultiple(variant.brightness_change)}</span>
      </header>
      <ABPlayer
        compact
        referenceUrl={startingUrl}
        referenceLabel="Starting sound"
        referenceNote="Before"
        renderUrl={variant.audio}
        renderLabel="This variation"
      />
      <Spectrogram src={variant.spectrogram} title="Spectrogram" audioUrl={variant.audio} />
      <dl className="variant-facts">
        <div>
          <dt>Measured brightness</dt>
          <dd className="mono">
            {formatHz(variant.brightness_hz)} ({formatMultiple(variant.brightness_change)})
          </dd>
        </div>
        <div>
          <dt>Target brightness</dt>
          <dd className="mono">{formatTarget(variant, baseBrightnessHz)}</dd>
        </div>
        <div>
          <dt>Pitch shift</dt>
          <dd className="mono">{formatCents(variant.pitch_shift_cents)}</dd>
        </div>
        <div>
          <dt title={`Within ${toleranceCents} cents of the starting pitch`}>Pitch kept</dt>
          <dd>{variant.pitch_preserved ? "Yes" : "No"}</dd>
        </div>
      </dl>
      <div className="row">
        <button type="button" className="button" onClick={() => downloadJson(variant.recipe, `${stem}.json`)}>
          Recipe (JSON)
        </button>
        <a className="button" href={variant.audio} download={`${stem}.wav`}>
          Audio (WAV)
        </a>
      </div>
    </article>
  );
}

export function AlchemyResults({
  result,
  startingUrl,
  filenameStem,
}: {
  result: AlchemyResult;
  startingUrl: string;
  filenameStem: string;
}) {
  return (
    <section aria-label="Variations">
      <div className="alchemy-summary">
        <span>
          Read as: <strong>{describeGoal(result.goal)}</strong>
        </span>
        <span className="muted">
          Starting brightness {formatHz(result.base_brightness_hz)}, pitch{" "}
          {result.base_pitch_hz.toFixed(1)} Hz. {result.renders_tested} renders tested.
        </span>
      </div>
      {result.note ? (
        <p className="alchemy-note" role="status">
          {result.note}
        </p>
      ) : null}
      {result.variants.length > 0 ? (
        <div className="variation-grid">
          {result.variants.map((variant) => (
            <VariantCard
              key={variant.label}
              variant={variant}
              baseBrightnessHz={result.base_brightness_hz}
              toleranceCents={result.pitch_tolerance_cents}
              startingUrl={startingUrl}
              filenameStem={filenameStem}
            />
          ))}
        </div>
      ) : (
        <p className="alchemy-none">No variation could be made for this sound and prompt.</p>
      )}
    </section>
  );
}

export function AlchemyScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const runId = params.get("run");

  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [runError, setRunError] = useState<unknown>(null);
  const [prompt, setPrompt] = useState(DEMO_PROMPT);
  const [result, setResult] = useState<AlchemyResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);

  useEffect(() => {
    api.runs().then(setRuns, setRunError);
    return () => request.current?.abort();
  }, []);

  useEffect(() => {
    request.current?.abort();
    setRun(null);
    setResult(null);
    setError(null);
    setBusy(false);
    setRunError(null);
    if (!runId) return;
    let current = true;
    api.run(runId).then(
      (detail) => current && setRun(detail),
      (failure) => current && setRunError(failure),
    );
    return () => {
      current = false;
    };
  }, [runId]);

  const best = useMemo(() => (run ? bestEntry(run.entries) : null), [run]);
  const running = run?.status === "running";
  const startingUrl = run && best ? urls.entryAudio(run.id, best.index) : null;

  async function generate() {
    if (!best?.recipe) return;
    request.current?.abort();
    const abort = new AbortController();
    request.current = abort;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const response = await api.alchemy(best.recipe, prompt, abort.signal);
      if (!abort.signal.aborted) setResult(response);
    } catch (failure) {
      if (!abort.signal.aborted) setError(failure);
    } finally {
      if (!abort.signal.aborted) setBusy(false);
    }
  }

  const choices = runs.filter((item) => item.best_loss !== null);
  const listed = choices.some((item) => item.id === runId);

  return (
    <div className="alchemy">
      <p className="alchemy-rules" role="note">
        {ALCHEMY_RULES}
      </p>

      <div className="alchemy-grid">
        <section className="panel">
          <h1>Transform a recovered recipe.</h1>
          <label className="field">
            <span>Start from the best render of</span>
            <select
              className="wide-select"
              value={runId ?? ""}
              onChange={(event) => router.replace(`/alchemy?run=${event.target.value}`)}
            >
              <option value="" disabled>
                Choose a run
              </option>
              {runId && !listed ? <option value={runId}>{run ? runOptionLabel({ ...run }) : runId}</option> : null}
              {choices.map((item) => (
                <option key={item.id} value={item.id}>
                  {runOptionLabel(item)}
                </option>
              ))}
            </select>
          </label>
          {runError ? <ErrorNote error={runError} /> : null}
          {run && !best ? <p className="muted">This run has no successful render to start from.</p> : null}
          {running ? <p className="muted">This run is still going. Its best render may change.</p> : null}
          {best ? (
            <p className="start-recipe">
              <strong>Render {renderNumber(best)}</strong>, normalized loss{" "}
              <span className="mono">{formatLoss(best.loss)}</span>
              <small>{describeRecipe(best.recipe)}</small>
            </p>
          ) : null}
          <label className="field">
            <span>Describe the change</span>
            <textarea rows={3} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          </label>
          <button
            type="button"
            className="button button-primary"
            disabled={!best || !prompt.trim() || busy}
            onClick={() => void generate()}
          >
            {busy ? "Rendering and measuring…" : "Generate variations"}
          </button>
        </section>

        <div className="alchemy-output">
          {error ? <ErrorNote error={error} /> : null}
          {busy ? <div className="panel empty-state">Rendering and measuring candidates…</div> : null}
          {result && startingUrl && run ? (
            <AlchemyResults result={result} startingUrl={startingUrl} filenameStem={`${run.id}-alchemy`} />
          ) : null}
          {!result && !busy && !error ? (
            <div className="panel empty-state">
              {best ? "Generate variations to hear and measure them here." : "Choose a run to start from."}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
