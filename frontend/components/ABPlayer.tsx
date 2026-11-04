"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { clearNowPlaying, setNowPlaying } from "@/lib/playhead";

type Side = "a" | "b";

interface Props {
  referenceUrl: string;
  renderUrl: string | null;
  renderLabel: string;
  referenceLabel?: string;
  referenceNote?: string;
  compact?: boolean;
}

/** Only one player sounds at a time, so several cards on a page can't overlap. */
let stopActive: (() => void) | null = null;

async function decode(context: AudioContext, url: string): Promise<AudioBuffer> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`audio request failed: ${response.status}`);
  return context.decodeAudioData(await response.arrayBuffer());
}

/** Plays backend WAVs only. Switching sides keeps the position, so the two line up by ear. */
export function ABPlayer({
  referenceUrl,
  renderUrl,
  renderLabel,
  referenceLabel = "Reference",
  referenceNote = "The original sound",
  compact = false,
}: Props) {
  const context = useRef<AudioContext | null>(null);
  const buffers = useRef<Record<Side, AudioBuffer | null>>({ a: null, b: null });
  const source = useRef<AudioBufferSourceNode | null>(null);
  const startedAt = useRef(0);
  const offsetAt = useRef(0);
  const [side, setSide] = useState<Side | null>(null);
  const [status, setStatus] = useState<Record<Side, "loading" | "ready" | "missing">>({
    a: "loading",
    b: "missing",
  });
  const sideRef = useRef<Side | null>(null);
  const bar = useRef<HTMLDivElement | null>(null);
  const stopRef = useRef<() => void>(() => undefined);
  const playingUrl = useRef<string | null>(null);
  const urlFor = useRef<Record<Side, string | null>>({ a: referenceUrl, b: renderUrl });
  urlFor.current = { a: referenceUrl, b: renderUrl };

  const getContext = () => (context.current ??= new AudioContext());

  const position = useCallback(() => {
    const ctx = context.current;
    return ctx ? offsetAt.current + (ctx.currentTime - startedAt.current) : 0;
  }, []);

  const stop = useCallback(() => {
    if (source.current) {
      source.current.onended = null;
      source.current.stop();
      source.current.disconnect();
      source.current = null;
    }
    if (stopActive === stopRef.current) stopActive = null;
    clearNowPlaying(playingUrl.current);
    playingUrl.current = null;
    sideRef.current = null;
    setSide(null);
    if (bar.current) bar.current.style.transform = "scaleX(0)";
  }, []);

  stopRef.current = stop;

  const start = useCallback(async (which: Side, from: number) => {
    const buffer = buffers.current[which];
    if (!buffer) return;
    const ctx = getContext();
    await ctx.resume();
    if (stopActive && stopActive !== stopRef.current) stopActive();
    stopActive = stopRef.current;
    if (source.current) {
      source.current.onended = null;
      source.current.stop();
      source.current.disconnect();
    }
    const node = ctx.createBufferSource();
    node.buffer = buffer;
    node.loop = true;
    node.connect(ctx.destination);
    const offset = from % buffer.duration;
    node.start(0, offset);
    source.current = node;
    startedAt.current = ctx.currentTime;
    offsetAt.current = offset;
    sideRef.current = which;
    setSide(which);
    clearNowPlaying(playingUrl.current);
    playingUrl.current = urlFor.current[which];
    if (playingUrl.current) {
      setNowPlaying(playingUrl.current, () => (position() % buffer.duration) / buffer.duration);
    }
  }, [position]);

  const load = useCallback(
    (which: Side, url: string | null) => {
      if (!url) {
        buffers.current[which] = null;
        setStatus((s) => ({ ...s, [which]: "missing" }));
        if (sideRef.current === which) stop();
        return () => undefined;
      }
      let current = true;
      setStatus((s) => ({ ...s, [which]: "loading" }));
      decode(getContext(), url).then(
        (buffer) => {
          if (!current) return;
          buffers.current[which] = buffer;
          setStatus((s) => ({ ...s, [which]: "ready" }));
          // A playing side picks up its new sound at the same position.
          if (sideRef.current === which) void start(which, position());
        },
        () => {
          if (!current) return;
          buffers.current[which] = null;
          setStatus((s) => ({ ...s, [which]: "missing" }));
          if (sideRef.current === which) stop();
        },
      );
      return () => {
        current = false;
      };
    },
    [position, start, stop],
  );

  useEffect(() => load("a", referenceUrl), [load, referenceUrl]);
  useEffect(() => load("b", renderUrl), [load, renderUrl]);

  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const buffer = sideRef.current ? buffers.current[sideRef.current] : null;
      if (buffer && bar.current) {
        const fraction = (position() % buffer.duration) / buffer.duration;
        bar.current.style.transform = `scaleX(${fraction})`;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [position]);

  useEffect(
    () => () => {
      if (source.current) source.current.stop();
      if (stopActive === stopRef.current) stopActive = null;
      clearNowPlaying(playingUrl.current);
      void context.current?.close();
      context.current = null;
    },
    [],
  );

  function choose(which: Side) {
    if (side === which) {
      stop();
      return;
    }
    void start(which, side ? position() : 0);
  }

  return (
    <section className={`panel ab${compact ? " ab-compact" : ""}`} aria-label="A/B playback">
      <div className="ab-buttons">
        <button
          type="button"
          className="ab-side"
          aria-pressed={side === "a"}
          disabled={status.a !== "ready"}
          onClick={() => choose("a")}
        >
          <span className="ab-letter">A</span>
          <span>
            <strong>{referenceLabel}</strong>
            <small>{status.a === "missing" ? "Audio missing" : side === "a" ? "Playing" : referenceNote}</small>
          </span>
        </button>
        <button
          type="button"
          className="ab-side"
          aria-pressed={side === "b"}
          disabled={status.b !== "ready"}
          onClick={() => choose("b")}
        >
          <span className="ab-letter">B</span>
          <span>
            <strong>{renderLabel}</strong>
            <small>
              {status.b === "missing"
                ? "No render to play"
                : status.b === "loading"
                  ? "Rendering"
                  : side === "b"
                    ? "Playing"
                    : "Rendered from the recipe"}
            </small>
          </span>
        </button>
        <button type="button" className="button" onClick={stop} disabled={side === null}>
          ■ Stop
        </button>
      </div>
      <div className="ab-progress" aria-hidden="true">
        <div ref={bar} />
      </div>
    </section>
  );
}
