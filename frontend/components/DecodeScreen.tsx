"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, oversizeError, urls, type Analysis, type Meta, type Target } from "@/lib/api";
import { ErrorNote } from "./ErrorNote";
import { PlayButton } from "./PlayButton";
import { Spectrogram } from "./Spectrogram";
import { Waveform } from "./Waveform";

const DESCRIPTORS: { key: string; label: string; plain: string; format: (v: number) => string }[] = [
  { key: "f0_hz", label: "Pitch", plain: "The note it plays", format: (v) => `${v.toFixed(1)} Hz` },
  {
    key: "spectral_centroid_hz",
    label: "Brightness",
    plain: "Spectral centroid. Higher sounds brighter",
    format: (v) => `${Math.round(v)} Hz`,
  },
  {
    key: "spectral_flatness",
    label: "Noisiness",
    plain: "Spectral flatness. 0 is a pure tone, 1 is noise",
    format: (v) => v.toFixed(3),
  },
  { key: "duration_s", label: "Length", plain: "After trimming leading silence", format: (v) => `${v.toFixed(2)} s` },
  { key: "onset_s", label: "Onset", plain: "When the sound starts", format: (v) => `${v.toFixed(3)} s` },
  { key: "time_to_peak_s", label: "Time to peak", plain: "When it is loudest", format: (v) => `${v.toFixed(3)} s` },
  { key: "level_first_third_db", label: "Level, start", plain: "First third of the sound", format: (v) => `${v.toFixed(1)} dB` },
  { key: "level_middle_third_db", label: "Level, middle", plain: "Middle third", format: (v) => `${v.toFixed(1)} dB` },
  { key: "level_last_third_db", label: "Level, end", plain: "Last third", format: (v) => `${v.toFixed(1)} dB` },
];

type Selection =
  | { kind: "none" }
  | { kind: "target"; name: string }
  | { kind: "upload"; name: string; id: string };

export function DecodeScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const targetParam = params.get("target");

  const [targets, setTargets] = useState<Target[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [listError, setListError] = useState<unknown>(null);
  const [selection, setSelection] = useState<Selection>({ kind: "none" });
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    api.targets().then(setTargets, setListError);
    api.meta().then(setMeta, () => undefined);
  }, []);

  useEffect(() => {
    if (!targetParam) return;
    const id = ++requestId.current;
    setSelection({ kind: "target", name: targetParam });
    setAnalysis(null);
    setError(null);
    setBusy(true);
    api
      .analyzeTarget(targetParam)
      .then(
        (result) => id === requestId.current && setAnalysis(result),
        (failure) => id === requestId.current && setError(failure),
      )
      .finally(() => id === requestId.current && setBusy(false));
  }, [targetParam]);

  async function upload(file: File) {
    const id = ++requestId.current;
    if (targetParam) router.replace("/decode");
    setSelection({ kind: "none" });
    setAnalysis(null);
    setError(null);
    const tooLarge = oversizeError(file.size, meta?.upload_limits.max_bytes);
    if (tooLarge) {
      setError(tooLarge);
      setBusy(false);
      return;
    }
    setBusy(true);
    try {
      const result = await api.analyzeUpload(file);
      if (id !== requestId.current) return;
      setAnalysis(result);
      setSelection({ kind: "upload", name: file.name, id: result.upload_id as string });
    } catch (failure) {
      if (id === requestId.current) setError(failure);
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }

  const soundId =
    selection.kind === "target" ? selection.name : selection.kind === "upload" ? selection.id : null;
  const selectedTarget =
    selection.kind === "target" ? targets.find((t) => t.name === selection.name) : undefined;
  const limits = meta?.upload_limits;

  return (
    <div className="decode-grid">
      <aside className="stack">
        {meta?.public_mode ? (
          <section className="panel" aria-label="About this demo">
            <h2>Public demo</h2>
            <p className="muted">
              Uploads and live AI runs are off here. <Link href="/lab">Replay the recorded AI run</Link>,
              or pick a test sound below.
            </p>
          </section>
        ) : (
        <section className="panel">
          <h2>Upload a sound</h2>
          <div
            className={`dropzone${dragging ? " is-dragging" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              const file = event.dataTransfer.files[0];
              if (file) void upload(file);
            }}
          >
            <p>Drop a WAV here</p>
            <button type="button" className="button" onClick={() => fileInput.current?.click()}>
              Choose a file
            </button>
            <input
              ref={fileInput}
              type="file"
              accept=".wav,.wave,audio/wav"
              hidden
              data-testid="wav-input"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
                event.target.value = "";
              }}
            />
            <small>
              {limits
                ? `One isolated sound, ${limits.min_duration_s} to ${limits.max_duration_s} seconds, mono or stereo, up to ${
                    limits.max_bytes / (1024 * 1024)
                  } MB, not clipped.`
                : "One isolated sound, 1 to 5 seconds."}{" "}
              The file is stored on the server. Nothing goes to a model until a live AI run is
              started.
            </small>
          </div>
        </section>
        )}

        <section className="panel">
          <h2>{meta?.public_mode ? "Pick a test sound" : "Or pick a test sound"}</h2>
          <p className="muted">Made with our own synth, so the true recipe is known.</p>
          {listError ? <ErrorNote error={listError} /> : null}
          <ul className="target-list">
            {targets.map((target) => (
              <li key={target.name}>
                <button
                  type="button"
                  className="target-button"
                  aria-pressed={selection.kind === "target" && selection.name === target.name}
                  disabled={!target.available}
                  onClick={() => router.replace(`/decode?target=${target.name}`)}
                >
                  {target.name}
                  {target.held_out ? <span className="held-out-tag">held out</span> : null}
                  {!target.available ? " (audio missing)" : ""}
                </button>
              </li>
            ))}
          </ul>
        </section>
      </aside>

      <section className="stack">
        {error ? <ErrorNote error={error} /> : null}
        {busy ? <div className="panel empty-state">Analysing the sound…</div> : null}
        {!analysis && !busy && !error ? (
          <div className="panel empty-state hero-empty">
            <h1>Start with one short sound.</h1>
            <p>
              Decode measures its pitch, brightness and shape. The Experiment Lab then tries to
              rebuild it as a synth recipe you can read and edit.
            </p>
          </div>
        ) : null}
        {analysis ? (
          <>
            <div className="panel sound-header">
              <div>
                <small className="eyebrow">
                  {selection.kind === "upload" || soundId?.startsWith("upload_")
                    ? "Uploaded sound"
                    : selectedTarget?.held_out
                      ? "Test sound, held out"
                      : "Test sound"}
                </small>
                <h1>{soundId?.startsWith("upload_") && selection.kind !== "upload" ? "Uploaded sound" : analysis.name}</h1>
              </div>
              <div className="row">
                {soundId ? <PlayButton src={urls.targetAudio(soundId)} /> : null}
                {selectedTarget?.has_runs ? (
                  <Link className="button" href={`/lab?target=${selectedTarget.name}`}>
                    See its experiments
                  </Link>
                ) : null}
                {soundId ? (
                  <Link className="button button-primary" href={`/lab?new=${soundId}`}>
                    Rebuild it in the Lab →
                  </Link>
                ) : null}
              </div>
            </div>
            {analysis.warnings.length > 0 ? (
              <ul className="warning-list">
                {analysis.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
            <section className="panel">
              <h2>Waveform</h2>
              <Waveform
                min={analysis.waveform.min}
                max={analysis.waveform.max}
                audioUrl={soundId ? urls.targetAudio(soundId) : null}
              />
            </section>
            <div className="decode-lower">
              <section className="panel">
                <Spectrogram
                  src={analysis.spectrogram}
                  title="Spectrogram"
                  note="Brighter means more energy"
                  audioUrl={soundId ? urls.targetAudio(soundId) : null}
                />
              </section>
              <section className="panel">
                <h2>Descriptors</h2>
                <dl className="descriptors">
                  {DESCRIPTORS.map((row) => {
                    const value = analysis.descriptors[row.key];
                    return (
                      <div key={row.key}>
                        <dt>
                          {row.label}
                          <small>{row.plain}</small>
                        </dt>
                        <dd>
                          {value === null || value === undefined
                            ? row.key === "f0_hz"
                              ? "No clear pitch"
                              : "n/a"
                            : row.format(value)}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              </section>
            </div>
          </>
        ) : null}
      </section>
    </div>
  );
}
