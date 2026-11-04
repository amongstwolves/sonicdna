"use client";

import { useEffect, useRef, useState } from "react";
import { clearNowPlaying, setNowPlaying } from "@/lib/playhead";

/** Plays one sound from a URL. Used where no A/B comparison is needed. */
export function PlayButton({ src, label = "Play" }: { src: string; label?: string }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
    return () => {
      audio.current?.pause();
      audio.current = null;
      clearNowPlaying(src);
      setPlaying(false);
    };
  }, [src]);

  function toggle() {
    if (playing) {
      audio.current?.pause();
      clearNowPlaying(src);
      setPlaying(false);
      return;
    }
    const element = audio.current ?? new Audio(src);
    audio.current = element;
    element.onended = () => {
      clearNowPlaying(src);
      setPlaying(false);
    };
    element.onerror = () => {
      clearNowPlaying(src);
      setPlaying(false);
      setFailed(true);
    };
    element.currentTime = 0;
    element.play().then(
      () => {
        setNowPlaying(src, () => element.currentTime / element.duration);
        setPlaying(true);
      },
      () => setFailed(true),
    );
  }

  return (
    <button type="button" className="button" onClick={toggle} disabled={failed} aria-pressed={playing}>
      <span aria-hidden="true">{playing ? "■" : "▶"}</span>{" "}
      {failed ? "Audio unavailable" : playing ? "Stop" : label}
    </button>
  );
}
